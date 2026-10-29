"""單一 SKU 移動平均明細端點（純計算，不讀檔）。"""

from __future__ import annotations

from flask import Blueprint, request

from src.error_codes import ErrorCode
from src.services.ma_detail import build_ma_detail, clean_monthly_data, parse_statistics

from ..responses import ApiError, error_boundary, json_success

bp = Blueprint("ma_detail", __name__)


@bp.post("/api/ma-detail")
def ma_detail():
    """
    Compute moving-average detail for a single SKU (pure function).

    Input: the monthly data the client already has from /api/calculate.
    No file or session lookup needed.
    """
    body = request.get_json(silent=True) or {}

    monthly_data = body.get("monthlyData") or body.get("monthly_data")
    if not isinstance(monthly_data, dict) or not monthly_data:
        raise ApiError(ErrorCode.MISSING_MONTHLY_VALUES)
    cleaned = clean_monthly_data(monthly_data)

    try:
        stats = parse_statistics(body)
    except (TypeError, ValueError) as e:
        raise ApiError(ErrorCode.INVALID_PARAMS, "統計欄位必須是數字") from e

    with error_boundary(ErrorCode.MA_COMPUTE_FAILED, "MA detail failed"):
        payload = build_ma_detail(body, cleaned, stats)
    return json_success(payload)
