"""計算端點：無狀態，結果完整放在回應中。"""

from __future__ import annotations

import logging

from flask import Blueprint, current_app, request

from src.data_loader import DataLoadError
from src.error_codes import ErrorCode
from src.services.calculation import build_parameters_snapshot, load_inputs, run_calculation

from ..params import parse_calculate_body
from ..responses import ApiError, error_boundary, json_success
from .common import resolve_file

logger = logging.getLogger(__name__)

bp = Blueprint("calculate", __name__)


@bp.post("/api/calculate")
def calculate():
    """Run safety stock calculation. Stateless — results returned in response."""
    body = request.get_json(silent=True) or {}

    # 先確認檔案，再驗證參數（錯誤回應的優先順序是 API contract 的一部分）
    sales_path = resolve_file(body.get("salesFileId") or body.get("sales_file_id"), ErrorCode.MISSING_SALES_FILE)
    price_path = resolve_file(body.get("priceFileId") or body.get("price_file_id"))
    plan_path = resolve_file(body.get("planFileId") or body.get("plan_file_id"))

    req = parse_calculate_body(body)

    try:
        inputs = load_inputs(sales_path, price_path, plan_path)
    except DataLoadError as e:
        raise ApiError(ErrorCode.PARSE_ERROR, str(e)) from e

    version = current_app.config["API_VERSION"]
    with error_boundary(ErrorCode.CALC_FAILED, "Calculation failed", include_traceback=True):
        result_body, execution_ms = run_calculation(
            req.calc_mode, req.target_site, req.params, inputs, current_app.config["MATERIAL_MASTER"] or None,
        )
        snapshot = build_parameters_snapshot(req.snapshot_calc_mode, req.params, inputs, version, execution_ms)

    logger.info(f"Calculate OK ({req.calc_mode}) in {execution_ms:.0f}ms")
    return json_success({"mode": req.calc_mode, "version": version, "parameters": snapshot, **result_body})
