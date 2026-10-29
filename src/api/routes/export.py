"""匯出端點：Excel 與 SAP MM17。結果由前端隨請求送回（無狀態）。"""

from __future__ import annotations

import io
import logging
from collections.abc import Callable
from typing import Any

from flask import Blueprint, request, send_file

from src.error_codes import ErrorCode
from src.services.export import ExportError, ExportFile, build_excel_export, build_sap_export

from ..responses import ApiError, error_boundary

logger = logging.getLogger(__name__)

bp = Blueprint("export", __name__)


def _send_export(builder: Callable[[dict[str, Any]], ExportFile], label: str):
    body = request.get_json(silent=True) or {}
    with error_boundary(ErrorCode.EXPORT_FAILED, f"{label} export failed"):
        try:
            export = builder(body)
        except ExportError as e:
            # 可預期的匯出錯誤（格式不支援、篩選後無資料）轉成 ApiError，error_boundary 會原樣放行
            raise ApiError(e.code, e.message) from e
    logger.info(f"{label} export OK: {export.filename}")
    return send_file(
        io.BytesIO(export.content), mimetype=export.mimetype, as_attachment=True, download_name=export.filename,
    )


@bp.post("/api/export/excel")
def export_excel():
    """Stateless Excel export. Client sends the results payload."""
    return _send_export(build_excel_export, "Excel")


@bp.post("/api/export/sap")
def export_sap():
    """Stateless SAP MM17 export."""
    return _send_export(build_sap_export, "SAP")
