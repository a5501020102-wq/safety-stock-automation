"""
Flask app 工廠：設定、CORS、Blueprint 與統一錯誤處理。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Flask, request
from flask_cors import CORS
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from src.error_codes import ErrorCode
from src.services.material_master import load_material_master
from src.temp_manager import init_temp_dir

from .responses import ApiError, is_debug_errors, json_error
from .routes import calculate, export, ma_detail, meta, upload

logger = logging.getLogger(__name__)

API_VERSION = "5.1.0"
MAX_UPLOAD_MB = 50
BYTES_PER_MB = 1024 * 1024
TEMP_UPLOAD_DIR = "temp_uploads"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
MATERIAL_MASTER_PATH = PROJECT_ROOT / "data" / "material_master.json"

# 本機開發的前端；正式環境的網域由 ALLOWED_ORIGINS 環境變數（逗號分隔）提供
LOCAL_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]


def _allowed_origins() -> list[str]:
    origins = list(LOCAL_ORIGINS)
    env_origins = os.environ.get("ALLOWED_ORIGINS", "").strip()
    if env_origins:
        origins.extend(o.strip() for o in env_origins.split(",") if o.strip())
    return origins


def _register_error_handlers(app: Flask) -> None:
    """所有錯誤都回傳 JSON（前端依 code 顯示訊息），不回傳 HTML 錯誤頁。"""

    @app.errorhandler(ApiError)
    def _handle_api_error(error: ApiError):
        return json_error(error.code, error.message, **error.extra)

    @app.errorhandler(404)
    def _handle_404(error: HTTPException):
        return json_error(ErrorCode.NOT_FOUND, f"路由不存在: {request.path}")

    @app.errorhandler(405)
    def _handle_405(error: HTTPException):
        return json_error(ErrorCode.METHOD_NOT_ALLOWED, f"{request.method} {request.path}")

    @app.errorhandler(413)
    @app.errorhandler(RequestEntityTooLarge)
    def _handle_413(error: HTTPException):
        return json_error(ErrorCode.FILE_TOO_LARGE, f"檔案超過 {MAX_UPLOAD_MB}MB 限制")

    @app.errorhandler(500)
    def _handle_500(error: HTTPException):
        logger.exception("500 error")
        extra = {"detail": str(error)} if is_debug_errors() else {}
        return json_error(ErrorCode.INTERNAL_ERROR, **extra)


def create_app() -> Flask:
    """建立 Flask app。"""
    project_root = str(PROJECT_ROOT)
    app = Flask(__name__, root_path=project_root, template_folder="templates", static_folder="static")
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * BYTES_PER_MB
    app.config["API_VERSION"] = API_VERSION
    is_debug = os.environ.get("FLASK_ENV") == "development"
    app.config["DEBUG_ERRORS"] = is_debug
    app.config["MATERIAL_MASTER"] = load_material_master(MATERIAL_MASTER_PATH)

    origins = _allowed_origins()
    logger.info(f"CORS allowed origins: {origins}")
    CORS(
        app,
        resources={r"/*": {"origins": origins}},
        expose_headers=["Content-Disposition"],
        supports_credentials=False,
        max_age=600,
    )

    init_temp_dir(TEMP_UPLOAD_DIR)

    for module in (meta, upload, calculate, export, ma_detail):
        app.register_blueprint(module.bp)
    _register_error_handlers(app)

    logger.info(f"Flask API initialized (v{API_VERSION}, debug={is_debug})")
    return app
