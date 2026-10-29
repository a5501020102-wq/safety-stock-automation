"""
單一 SKU 的移動平均明細（純函式，不讀檔、不依賴伺服器狀態）。

輸入是前端從 /api/calculate 已取得的月度資料與統計值。
"""

from __future__ import annotations

from typing import Any

from src.utils import group_by_quarter, parse_year_month

# 迴圈保護：月份區間超過約 33 年視為資料異常，避免無窮迴圈
MAX_MONTH_SPAN = 400

# CV（變異係數）門檻：用於移動平均的參考說明文字
HIGH_CV_THRESHOLD = 0.5
MODERATE_CV_THRESHOLD = 0.3

DEFAULT_MA_WINDOW = 3


def clean_monthly_data(monthly_data: dict[Any, Any]) -> dict[str, float]:
    """月度資料轉成 {YYYY-MM: float}；無法轉成數字的值直接丟棄。"""
    cleaned: dict[str, float] = {}
    for key, value in monthly_data.items():
        try:
            cleaned[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return cleaned


def summarize_by_quarter(monthly_data: dict[str, float]) -> dict[str, dict[str, Any]]:
    """依季度彙總：各季的月份、數值、平均、合計與月數。"""
    summary: dict[str, dict[str, Any]] = {}
    for quarter, pairs in sorted(group_by_quarter(monthly_data).items()):
        values = [value for _, value in pairs]
        summary[quarter] = {
            "months": [ym for ym, _ in pairs],
            "values": values,
            "avg": round(sum(values) / len(values), 2) if values else 0,
            "total": sum(values),
            "count": len(values),
        }
    return summary


def find_filled_months(monthly_data: dict[str, float]) -> list[str]:
    """回傳最早與最晚月份之間、資料中缺少的月份。"""
    sorted_months = sorted(monthly_data.keys())
    if not sorted_months:
        return []

    start_year, start_month = parse_year_month(sorted_months[0])
    end_year, end_month = parse_year_month(sorted_months[-1])
    if start_year == 0 or end_year == 0:
        return []

    expected: list[str] = []
    year, month = start_year, start_month
    while (year, month) <= (end_year, end_month) and len(expected) < MAX_MONTH_SPAN:
        expected.append(f"{year}-{month:02d}")
        month += 1
        if month > 12:
            month = 1
            year += 1
    return [ym for ym in expected if ym not in monthly_data]


def ma_recommendation(std_dev: float, mean_demand: float) -> dict[str, str]:
    """依 CV 給出移動平均的參考說明（既有功能，文字維持原樣）。"""
    if std_dev <= 0:
        return {"text": "標準差為 0，無需移動平均", "level": "info"}
    cv = std_dev / mean_demand if mean_demand > 0 else 0
    if cv > HIGH_CV_THRESHOLD:
        return {"text": f"需求波動較大 (CV={cv:.2f})，建議啟用移動平均平滑", "level": "warning"}
    if cv > MODERATE_CV_THRESHOLD:
        return {"text": f"需求波動中等 (CV={cv:.2f})，移動平均可能有幫助", "level": "info"}
    return {"text": f"需求相對穩定 (CV={cv:.2f})，移動平均效果有限", "level": "success"}


def _number(body: dict[str, Any], camel: str, snake: str, cast: type, default: float) -> Any:
    """讀取數值欄位；缺值或空值使用預設值，非數字時拋出 ValueError / TypeError。"""
    return cast(body.get(camel, body.get(snake, default)) or default)


def parse_statistics(body: dict[str, Any]) -> dict[str, Any]:
    """讀取請求中的統計欄位。非數字時拋出 ValueError 或 TypeError。"""
    return {
        "mean_demand": _number(body, "meanDemand", "mean_demand", float, 0),
        "std_dev": _number(body, "stdDev", "std_dev", float, 0),
        "total_qty": _number(body, "totalQty", "total_qty", float, 0),
        "active_months": _number(body, "activeMonths", "active_months", int, 0),
        "outliers_removed": _number(body, "outliersRemoved", "outliers_removed", int, 0),
        "ma_window": _number(body, "maWindow", "ma_window", int, DEFAULT_MA_WINDOW),
    }


def build_ma_detail(body: dict[str, Any], monthly_data: dict[str, float], stats: dict[str, Any]) -> dict[str, Any]:
    """組出 /api/ma-detail 的回應主體。"""
    return {
        "site": body.get("site", ""),
        "sku": body.get("sku", ""),
        "name": body.get("name", ""),
        "abc_class": body.get("abcClass") or body.get("abc_class") or "",
        "monthly_data": monthly_data,
        "quarterly_summary": summarize_by_quarter(monthly_data),
        "filled_months": find_filled_months(monthly_data),
        "statistics": {
            "std_original": stats["std_dev"],
            "mean": stats["mean_demand"],
            "total_qty": stats["total_qty"],
            "active_months": stats["active_months"],
            "outliers_removed": stats["outliers_removed"],
        },
        "recommendation": ma_recommendation(stats["std_dev"], stats["mean_demand"]),
        "ma_window": stats["ma_window"],
    }
