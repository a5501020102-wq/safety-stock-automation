"""上傳端點：存成暫存檔、解析並回傳 file_id 與資料摘要。"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from flask import Blueprint, request

from src.error_codes import ErrorCode
from src.services.upload import FILE_LOADERS, build_upload_metadata
from src.temp_manager import ALLOWED_EXTENSIONS, cleanup_temp_files, get_temp_path, is_allowed_extension

from ..responses import ApiError, error_boundary, json_success
from .common import parse_file

logger = logging.getLogger(__name__)

bp = Blueprint("upload", __name__)

# 暫存檔保留時間：足夠完成一輪上傳→計算，又不會長期佔用 Render 免費方案的磁碟
TEMP_FILE_TTL_MINUTES = 60


@bp.post("/api/upload/<file_type>")
def upload_file(file_type: str):
    """Upload a file, save to temp, extract metadata, return file_id."""
    # 每次上傳順便清掉過期檔案（lazy cleanup）
    cleanup_temp_files(ttl_minutes=TEMP_FILE_TTL_MINUTES)

    loader = FILE_LOADERS.get(file_type)
    if loader is None:
        raise ApiError(ErrorCode.INVALID_FILE_TYPE)
    if "file" not in request.files:
        raise ApiError(ErrorCode.NO_FILE)

    upload = request.files["file"]
    if not upload.filename:
        raise ApiError(ErrorCode.EMPTY_FILENAME)

    ext = Path(upload.filename).suffix.lower()
    if not is_allowed_extension(ext):
        raise ApiError(ErrorCode.INVALID_EXTENSION, f"僅支援 {', '.join(sorted(ALLOWED_EXTENSIONS))} 檔案")

    file_id = str(uuid.uuid4())
    save_path = get_temp_path(file_id, ext)
    try:
        upload.save(str(save_path))
    except OSError as e:
        logger.error(f"Failed to save upload: {e}")
        raise ApiError(ErrorCode.INTERNAL_ERROR, "儲存檔案失敗") from e

    try:
        with error_boundary(ErrorCode.PARSE_ERROR, f"Unexpected error parsing {upload.filename}"):
            data = parse_file(loader, save_path)
            metadata = build_upload_metadata(file_type, data, file_id, upload.filename, save_path)
    except ApiError:
        save_path.unlink(missing_ok=True)
        raise

    logger.info(
        f"Upload OK: {file_type} {upload.filename} -> {file_id} "
        f"({metadata.get('record_count', metadata.get('item_count', 0))} items)"
    )
    return json_success(metadata)
