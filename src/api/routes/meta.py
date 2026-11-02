"""服務資訊端點：健康檢查、物料群組、舊版 UI。"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, render_template

from src.case_converter import keys_to_camel
from src.services.material_master import summarize_material_groups

from ..responses import json_success

bp = Blueprint("meta", __name__)


@bp.get("/")
def index():
    """API root — returns health info and a pointer to the legacy UI."""
    return jsonify(keys_to_camel({
        "status": "ok",
        "service": "Safety Stock Automation API",
        "version": current_app.config["API_VERSION"],
        "legacy_ui": "/legacy",
        # API contract 欄位：核心模組改為啟動時直接 import，能回應即代表已載入
        "modules_available": True,
    }))


@bp.get("/health")
def health():
    """Lightweight liveness probe."""
    return jsonify({"status": "ok", "version": current_app.config["API_VERSION"]})


@bp.get("/api/material-groups")
def material_groups():
    """Return material master categories for the frontend category-LT panel."""
    return json_success(summarize_material_groups(current_app.config["MATERIAL_MASTER"]))


@bp.get("/legacy")
def legacy_ui():
    """Legacy Jinja UI (preserved during migration)."""
    return render_template("index.html")
