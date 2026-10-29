"""
/api/calculate 請求參數的解析與驗證。

前端送 camelCase，舊版呼叫端送 snake_case，兩者都接受；
參數可放在 body.params 內，也可直接放在 body 頂層。
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.calculator import (
    DEFAULT_ABC_THRESHOLDS,
    DEFAULT_Z_SCORES,
    TREND_MODES,
    CalculationParams,
    Granularity,
)
from src.error_codes import ErrorCode

from .responses import ApiError

CALC_MODES = ("all", "total", "compare", "single")
GRANULARITIES = tuple(g.value for g in Granularity)

# 數值參數的 (預設值, 下限, 上限)
LEAD_TIME_RANGE = (30, 1, 365)
MIN_MONTHS_RANGE = (2, 0, 12)
MA_WINDOW_RANGE = (3, 2, 12)
Z_SCORE_MIN, Z_SCORE_MAX = 0.5, 3.5
WORKING_DAYS_MIN, WORKING_DAYS_MAX = 1, 31
ALL_MONTHS = list(range(1, 13))


@dataclass
class CalculateRequest:
    """解析後的 /api/calculate 請求。"""
    calc_mode: str
    target_site: str | None
    params: CalculationParams
    # 參數快照的 calc_mode 取自 body 頂層的 snake_case key（既有行為，見 build_parameters_snapshot）
    snapshot_calc_mode: str


def _get(params: dict[str, Any], snake: str, camel: str) -> Any:
    """依序讀取 snake_case、camelCase key，空值（None、0、空字串、空容器）視為未提供。"""
    return params.get(snake) or params.get(camel)


def _invalid(message: str) -> ApiError:
    return ApiError(ErrorCode.INVALID_PARAMS, message)


def validate_z_scores(z_scores: Any) -> dict[str, float]:
    """驗證各 ABC 類別的 Z 值；未提供時使用預設值。"""
    if not z_scores:
        return dict(DEFAULT_Z_SCORES)
    if not isinstance(z_scores, dict):
        raise _invalid("z_scores 必須是物件 {A, B, C}")

    cleaned: dict[str, float] = {}
    for key in ("A", "B", "C"):
        try:
            value = float(z_scores.get(key, DEFAULT_Z_SCORES[key]))
        except (TypeError, ValueError) as exc:
            raise _invalid(f"z_scores.{key} 必須是數字") from exc
        if not (Z_SCORE_MIN <= value <= Z_SCORE_MAX):
            raise _invalid(f"z_scores.{key} 必須介於 {Z_SCORE_MIN}-{Z_SCORE_MAX}")
        cleaned[key] = value
    return cleaned


def validate_abc_thresholds(abc_thresholds: Any) -> dict[str, float]:
    """驗證 ABC 累計占比門檻（開區間 0-1，且 A < B）；未提供時使用預設值。"""
    if not abc_thresholds:
        return dict(DEFAULT_ABC_THRESHOLDS)
    if not isinstance(abc_thresholds, dict):
        raise _invalid("abc_thresholds 必須是物件 {A, B}")

    cleaned: dict[str, float] = {}
    for key in ("A", "B"):
        try:
            value = float(abc_thresholds.get(key, DEFAULT_ABC_THRESHOLDS[key]))
        except (TypeError, ValueError) as exc:
            raise _invalid(f"abc_thresholds.{key} 必須是數字") from exc
        if not (0.0 < value < 1.0):
            raise _invalid(f"abc_thresholds.{key} 必須介於 0-1 (開區間)")
        cleaned[key] = value
    if cleaned["A"] >= cleaned["B"]:
        raise _invalid("abc_thresholds.A 必須小於 B")
    return cleaned


def parse_int_param(params: dict[str, Any], snake: str, camel: str, bounds: tuple[int, int, int]) -> int:
    """讀取整數參數並檢查範圍；這裡 0 是合法值，只有 None 才視為未提供。"""
    default, low, high = bounds
    raw = params.get(snake) if params.get(snake) is not None else params.get(camel)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{snake} 必須是整數") from exc
    if not (low <= value <= high):
        raise _invalid(f"{snake} 必須介於 {low}-{high}")
    return value


def _parse_date(raw: Any) -> datetime | None:
    """解析 YYYY-MM-DD 或 YYYY/MM/DD；格式錯誤時視為未提供（既有行為）。"""
    if not raw:
        return None
    with contextlib.suppress(ValueError, AttributeError):
        return datetime.strptime(raw.replace("/", "-"), "%Y-%m-%d")
    return None


def _parse_working_days(raw: Any) -> int | None:
    """每月工作天數；超出 1-31 或非整數時忽略，回到日曆天（既有行為）。"""
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if WORKING_DAYS_MIN <= value <= WORKING_DAYS_MAX else None


def parse_calculate_body(body: dict[str, Any]) -> CalculateRequest:
    """
    把請求 body 轉成 CalculateRequest。

    驗證順序與錯誤訊息是 API contract 的一部分：
    計算模式 → z_scores → abc_thresholds → selected_months → lead_time → min_months → ma_window → granularity。
    max_date 不在這裡設定，計算引擎會改用銷貨資料的最大日期。
    """
    params = body.get("params") or body

    calc_mode = _get(params, "calc_mode", "calcMode") or "all"
    if calc_mode not in CALC_MODES:
        raise _invalid(f"未知的計算模式: {calc_mode}")

    z_scores = validate_z_scores(_get(params, "z_scores", "zScores"))
    abc_thresholds = validate_abc_thresholds(_get(params, "abc_thresholds", "abcThresholds"))

    selected_months = _get(params, "selected_months", "selectedMonths") or list(ALL_MONTHS)
    is_valid_months = isinstance(selected_months, list) and all(
        isinstance(m, int) and 1 <= m <= 12 for m in selected_months
    )
    if not is_valid_months:
        raise _invalid("selected_months 必須是 1-12 的整數列表")

    lead_time = parse_int_param(params, "lead_time", "leadTime", LEAD_TIME_RANGE)
    min_months = parse_int_param(params, "min_months", "minMonths", MIN_MONTHS_RANGE)
    ma_window = parse_int_param(params, "ma_window", "maWindow", MA_WINDOW_RANGE)

    granularity = params.get("granularity", Granularity.MONTHLY.value)
    if granularity not in GRANULARITIES:
        raise _invalid(f"granularity 必須是 {GRANULARITIES} 之一，收到: {granularity}")

    trend_mode = _get(params, "trend_mode", "trendMode") or "none"
    selected_weeks = _get(params, "selected_weeks", "selectedWeeks")

    calc_params = CalculationParams(
        selected_months=selected_months,
        min_months=min_months,
        lead_time_days=lead_time,
        z_scores=z_scores,
        abc_thresholds=abc_thresholds,
        enable_outlier_detection=bool(params.get("enable_outlier", params.get("enableOutlier", True))),
        enable_moving_average=bool(params.get("enable_ma", params.get("enableMa", False))),
        ma_window=ma_window,
        granularity=granularity,
        category_lead_times=_get(params, "category_lead_times", "categoryLeadTimes") or {},
        group_lead_times=_get(params, "group_lead_times", "groupLeadTimes") or {},
        date_from=_parse_date(_get(params, "date_from", "dateFrom")),
        date_to=_parse_date(_get(params, "date_to", "dateTo")),
        # 無效的趨勢模式回到 none（既有行為）
        trend_mode=trend_mode if trend_mode in TREND_MODES else "none",
        working_days_per_month=_parse_working_days(_get(params, "working_days_per_month", "workingDaysPerMonth")),
        selected_weeks=selected_weeks if isinstance(selected_weeks, list) else None,
    )
    return CalculateRequest(
        calc_mode=calc_mode,
        target_site=_get(params, "target_site", "targetSite"),
        params=calc_params,
        snapshot_calc_mode=body.get("calc_mode", "all"),
    )
