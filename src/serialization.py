"""
計算結果的 JSON 序列化（snake_case；API 邊界再由 case_converter 轉成 camelCase）。
"""

from __future__ import annotations

import logging
import math
from typing import Any

from .value_utils import enum_value, resolve_cv, safe_float, safe_int

logger = logging.getLogger(__name__)

DEFAULT_LEAD_TIME_DAYS = 30
# 備用 ROP 計算把月平均需求換成日需求時使用的天數
FALLBACK_DAYS_PER_MONTH = 30


def serialize_results_for_json(results: list[Any], excluded: list[Any], summary: Any) -> dict[str, Any]:
    """
    將計算結果序列化為 JSON 格式

    Returns:
        包含 summary, results, excluded 的字典
    """
    return {
        "summary": _serialize_summary(summary),
        "results": [_serialize_result(r) for r in (results or [])],
        "excluded": _serialize_excluded(excluded),
    }


def _serialize_summary(summary: Any) -> dict[str, Any]:
    """序列化計算摘要"""
    run_date = getattr(summary, "run_date", None)
    return {
        "run_date": run_date.isoformat() if hasattr(run_date, "isoformat") else None,
        "total_skus": safe_int(getattr(summary, "total_skus", 0), 0),
        "excluded_count": safe_int(getattr(summary, "excluded_count", 0), 0),
        "total_outliers_removed": safe_int(getattr(summary, "total_outliers_removed", 0), 0),
        "shortage_risk_count": safe_int(getattr(summary, "shortage_risk_count", 0), 0),
        "healthy_count": safe_int(getattr(summary, "healthy_count", 0), 0),
        "overstock_risk_count": safe_int(getattr(summary, "overstock_risk_count", 0), 0),
        "no_data_count": safe_int(getattr(summary, "no_data_count", 0), 0),
        "moving_average_enabled": bool(getattr(summary, "moving_average_enabled", False)),
        "ma_window": getattr(summary, "ma_window", None),
        "lead_time_days": safe_int(getattr(summary, "lead_time_days", DEFAULT_LEAD_TIME_DAYS), DEFAULT_LEAD_TIME_DAYS),
        "min_months": safe_int(getattr(summary, "min_months", 2), 2),
        "calc_mode": getattr(summary, "calc_mode", "all"),
    }


def _resolve_reorder_point(r: Any, mean_demand: float, safety_stock: float, lead_time_days: int) -> float:
    """
    ROP 優先使用計算引擎的值；缺值或為 0 時才用 月平均需求/30 × 前置天數 + 安全庫存 備用計算。

    計算引擎在需求 > 0 時 ROP 必定 >= 1，所以備用公式只會在結果物件缺欄位時使用。
    """
    reorder_point = getattr(r, "reorder_point", None)
    if reorder_point is None or safe_float(reorder_point, 0) == 0:
        if mean_demand > 0 and lead_time_days > 0:
            lead_time_demand = mean_demand / FALLBACK_DAYS_PER_MONTH * lead_time_days
            reorder_point = math.ceil(lead_time_demand + safety_stock)
        else:
            reorder_point = safety_stock
    return safe_float(reorder_point, 0)


def _resolve_max_inventory(r: Any, reorder_point: float, safety_stock: float) -> float:
    """最大庫存優先使用計算引擎的值（含舊欄位別名）；缺值或為 0 時以 ROP + 安全庫存 備用。"""
    max_inventory = (
        getattr(r, "max_inventory", None)
        or getattr(r, "max_stock", None)
        or getattr(r, "target_stock", None)
    )
    if max_inventory is None or safe_float(max_inventory, 0) == 0:
        max_inventory = reorder_point + safety_stock
    return safe_float(max_inventory, 0)


def _serialize_monthly_plan(r: Any) -> list[dict[str, Any]]:
    return [
        {
            "month": mp.month,
            "demand": mp.demand,
            "supply": mp.supply,
            "transfer_in": mp.transfer_in,
            "transfer_out": mp.transfer_out,
            "independent_demand": mp.independent_demand,
            "net_change": mp.net_change,
            "ending_stock": mp.ending_stock,
        }
        for mp in (getattr(r, "monthly_plan", []) or [])
    ]


def _serialize_plan_fields(r: Any) -> dict[str, Any]:
    """庫存計畫整合欄位（有上傳 plan 檔時才有值）。"""
    return {
        "has_plan": bool(getattr(r, "has_plan", False)),
        "plan_stock": getattr(r, "plan_stock", None),
        "final_stock": getattr(r, "final_stock", None),
        "min_stock": getattr(r, "min_stock", None),
        "min_stock_month": getattr(r, "min_stock_month", None),
        "gap": getattr(r, "gap", None),
        "suggested_order": safe_int(getattr(r, "suggested_order", 0), 0),
        "first_shortage_month": getattr(r, "first_shortage_month", None),
        "order_deadline": getattr(r, "order_deadline", None),
        "turnover_rate": getattr(r, "turnover_rate", None),
        "coverage_days": getattr(r, "coverage_days", None),
        "monthly_plan": _serialize_monthly_plan(r),
    }


def _serialize_result(r: Any) -> dict[str, Any]:
    """序列化單一品項結果。"""
    abc_class = enum_value(getattr(r, "abc_class", None))
    mean_demand = safe_float(getattr(r, "mean_demand", 0), 0)
    std_dev = safe_float(getattr(r, "std_dev", 0), 0)
    safety_stock = safe_float(getattr(r, "safety_stock", 0), 0)
    active_months = safe_int(getattr(r, "active_months", 0), 0)
    lead_time_days = safe_int(
        getattr(r, "lead_time_days", None) or getattr(r, "lead_time", DEFAULT_LEAD_TIME_DAYS),
        DEFAULT_LEAD_TIME_DAYS,
    )
    reorder_point = _resolve_reorder_point(r, mean_demand, safety_stock, lead_time_days)
    max_inventory = _resolve_max_inventory(r, reorder_point, safety_stock)
    avg_monthly_demand = safe_float(getattr(r, "avg_monthly_demand", mean_demand), mean_demand)

    return {
        # --- 基礎 ---
        "site": getattr(r, "site", None),
        "sku": getattr(r, "sku", None),
        "name": getattr(r, "name", None),

        # --- ABC/狀態 ---
        "abc_class": abc_class,
        "abc_grade": getattr(r, "abc_grade", abc_class) or abc_class,
        "status": enum_value(getattr(r, "status", None)),

        # --- 需求/統計 ---
        "total_qty": safe_float(getattr(r, "total_qty", 0), 0),
        "total_value": round(safe_float(getattr(r, "total_value", 0), 0), 2),
        "active_months": active_months,
        "total_months": safe_int(getattr(r, "total_months", active_months), active_months),
        "months_count": safe_int(getattr(r, "months_count", active_months), active_months),
        "mean_demand": round(mean_demand, 2),
        "avg_monthly_demand": round(avg_monthly_demand, 2),
        "std_dev": round(std_dev, 2),
        "cv": round(resolve_cv(r), 4),

        # --- 庫存建議 ---
        "safety_stock": round(safety_stock, 0),
        "safety_stock_value": round(safe_float(getattr(r, "safety_stock_value", 0), 0), 2),
        "reorder_point": round(reorder_point, 0),
        "max_inventory": round(max_inventory, 0),
        "lead_time_days": lead_time_days,

        # --- 其他 ---
        "current_stock": getattr(r, "current_stock", None),
        "outliers_removed": safe_int(getattr(r, "outliers_removed", 0), 0),
        "price": safe_float(getattr(r, "price", 0), 0),
        "enable_ma": bool(getattr(r, "enable_ma", False)),

        # --- 趨勢 ---
        "trend_pct": getattr(r, "trend_pct", None),
        "trend_label": getattr(r, "trend_label", "—"),

        # --- ABC 元數據 ---
        "is_price_missing": bool(getattr(r, "is_price_missing", False)),

        # --- 期間明細（供前端展示） ---
        "monthly_values": [round(v, 2) for v in (getattr(r, "monthly_values", []) or [])],

        # --- Plan 整合 ---
        **_serialize_plan_fields(r),
        "data_point_count": safe_int(getattr(r, "data_point_count", 0), 0),
        "data_point_warning": getattr(r, "data_point_warning", None),

        # 需求型態分類（Syntetos-Boylan，僅月粒度）
        "demand_pattern": getattr(r, "demand_pattern", "—"),
        "adi": getattr(r, "adi", None),
        "cv_squared": getattr(r, "cv_squared", None),
    }


def _serialize_excluded(excluded: list[Any]) -> list[dict[str, Any]]:
    """序列化排除項目"""
    return [
        {
            "site": getattr(e, "site", None),
            "sku": getattr(e, "sku", None),
            "name": getattr(e, "name", None),
            "active_months": safe_int(getattr(e, "active_months", 0), 0),
            "months_count": safe_int(getattr(e, "months_count", getattr(e, "active_months", 0)), 0),
            "total_qty": safe_float(getattr(e, "total_qty", 0), 0),
            "reason": getattr(e, "reason", None),
        }
        for e in (excluded or [])
    ]
