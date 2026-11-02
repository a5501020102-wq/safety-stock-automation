"""
Excel 匯出：單一模式的計算結果，以及對比模式的完整分析（摘要、分倉、總倉、差異、排除項目）。
"""

from __future__ import annotations

import logging
from io import BytesIO
from typing import Any

import pandas as pd

from src.value_utils import enum_value, resolve_cv, safe_float, safe_int, safe_round

logger = logging.getLogger(__name__)

# 需求型態英文值 → 中文顯示（Excel 匯出用）
_DEMAND_PATTERN_ZH = {
    "smooth": "穩定",
    "erratic": "波動",
    "intermittent": "零星",
    "lumpy": "雜亂",
}

# 差異分析只列出分倉與總倉安全庫存差異達此百分比的品項
DIFF_ANALYSIS_MIN_PCT = 5
DAYS_PER_WEEK = 7
PERCENT = 100


def export_to_excel(results: list[Any], excluded: list[Any], summary: Any,
                    granularity: str = "monthly", is_weekly_daily: bool = False) -> bytes:
    """
    匯出計算結果為 Excel 檔案

    Args:
        results: 計算結果列表
        excluded: 排除項目列表
        summary: 計算摘要

    Returns:
        Excel 檔案的二進位內容
    """
    output = BytesIO()

    try:
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            if results:
                _write_results_sheet(writer, results, granularity=granularity, is_weekly_daily=is_weekly_daily)
            if excluded:
                _write_excluded_sheet(writer, excluded, granularity=granularity, is_weekly_daily=is_weekly_daily)
            if summary:
                _write_summary_sheet(writer, summary)

        output.seek(0)
        return output.read()

    except ImportError as err:
        raise ImportError("請安裝 xlsxwriter: pip install xlsxwriter") from err


def _period_labels(granularity: str = "monthly", is_weekly_daily: bool = False) -> tuple:
    """Return (active_label, mean_label) based on granularity.

    Args:
        granularity: 粒度（"monthly", "weekly", "daily"）
        is_weekly_daily: 週模式是否使用日數據計算（selected_weeks 有值時為 True）
    """
    # 週模式用日數據時，欄位名稱用「日」而非「周」
    if granularity == "daily" or is_weekly_daily:
        return "活躍天數", "日平均需求"
    elif granularity == "weekly":
        return "活躍周數", "周平均需求"
    return "活躍月數", "月平均需求"


def _result_to_row(r: Any, granularity: str = "monthly", is_weekly_daily: bool = False) -> dict[str, Any]:
    """將單一 CalculationResult 轉為 Excel / 匯出用的 dict（共用邏輯）"""
    mean_demand = safe_float(getattr(r, "mean_demand", 0), 0)
    std_dev = safe_float(getattr(r, "std_dev", 0), 0)
    cv = resolve_cv(r)
    active_label, mean_label = _period_labels(granularity, is_weekly_daily)

    return {
        "出貨點": getattr(r, "site", ""),
        "料號": getattr(r, "sku", ""),
        "品名": getattr(r, "name", ""),
        "ABC分類": enum_value(getattr(r, "abc_class", "")),
        "總需求量": safe_float(getattr(r, "total_qty", 0), 0),
        "總需求金額": safe_round(getattr(r, "total_value", 0), 2, 0.0),
        active_label: safe_int(getattr(r, "active_months", 0), 0),
        mean_label: safe_round(mean_demand, 2, 0.0),
        "標準差": safe_round(std_dev, 2, 0.0),
        "CV": safe_round(cv, 3, 0.0),
        "安全庫存": safe_float(getattr(r, "safety_stock", 0), 0),
        "安全庫存金額": safe_round(getattr(r, "safety_stock_value", 0), 2, 0.0),
        "再訂購點": safe_float(getattr(r, "reorder_point", 0), 0),
        "最大庫存": safe_float(getattr(r, "max_inventory", 0), 0),
        "前置期(天)": safe_int(getattr(r, "lead_time_days", 0), 0),
        "現有庫存": getattr(r, "current_stock", ""),
        "庫存狀態": enum_value(getattr(r, "status", "")),
        "周轉率": getattr(r, "turnover_rate", None) or "",
        "離群值數量": safe_int(getattr(r, "outliers_removed", 0), 0),
        "單價": safe_float(getattr(r, "price", 0), 0),
        "需求型態": _DEMAND_PATTERN_ZH.get(getattr(r, "demand_pattern", "—"), "—"),
    }


def _write_results_sheet(writer, results: list[Any], sheet_name: str = "計算結果",
                         granularity: str = "monthly", is_weekly_daily: bool = False) -> None:
    """寫入計算結果工作表（支援自訂工作表名稱）"""
    rows = [_result_to_row(r, granularity, is_weekly_daily) for r in results]
    pd.DataFrame(rows).to_excel(writer, sheet_name=sheet_name, index=False)


def _write_excluded_sheet(writer, excluded: list[Any], granularity: str = "monthly",
                          is_weekly_daily: bool = False) -> None:
    """寫入排除項目工作表"""
    active_label = _period_labels(granularity, is_weekly_daily)[0]
    rows = [
        {
            "出貨點": getattr(e, "site", ""),
            "料號": getattr(e, "sku", ""),
            "品名": getattr(e, "name", ""),
            active_label: safe_int(getattr(e, "active_months", 0), 0),
            "總需求量": safe_float(getattr(e, "total_qty", 0), 0),
            "排除原因": getattr(e, "reason", ""),
        }
        for e in excluded
    ]
    pd.DataFrame(rows).to_excel(writer, sheet_name="排除項目", index=False)


def _write_summary_sheet(writer, summary: Any) -> None:
    """寫入計算摘要工作表"""
    run_date = getattr(summary, "run_date", None)
    run_date_str = run_date.strftime("%Y-%m-%d %H:%M:%S") if hasattr(run_date, "strftime") else ""
    ma_window = getattr(summary, "ma_window", None)

    rows = [
        ("執行時間", run_date_str),
        ("總 SKU 數", safe_int(getattr(summary, "total_skus", 0), 0)),
        ("排除項目", safe_int(getattr(summary, "excluded_count", 0), 0)),
        ("移除離群值", safe_int(getattr(summary, "total_outliers_removed", 0), 0)),
        ("缺貨風險", safe_int(getattr(summary, "shortage_risk_count", 0), 0)),
        ("健康庫存", safe_int(getattr(summary, "healthy_count", 0), 0)),
        ("超量風險", safe_int(getattr(summary, "overstock_risk_count", 0), 0)),
        ("無資料", safe_int(getattr(summary, "no_data_count", 0), 0)),
        ("前置期（天）", safe_int(getattr(summary, "lead_time_days", 0), 0)),
        ("最少月數", safe_int(getattr(summary, "min_months", 0), 0)),
        ("移動平均", "啟用" if bool(getattr(summary, "moving_average_enabled", False)) else "關閉"),
        ("MA 窗口", ma_window if ma_window is not None else "N/A"),
    ]
    data = {"項目": [item for item, _ in rows], "數值": [value for _, value in rows]}
    pd.DataFrame(data).to_excel(writer, sheet_name="計算摘要", index=False)


# ============================================================================
# 對比模式
# ============================================================================

def _comparison_param_rows(
        calc_params: dict | None, granularity: str, is_weekly_daily: bool,
) -> list[tuple[str, object]]:
    """對比摘要最前面的計算參數區塊；最後一列是空白分隔列。"""
    if not calc_params:
        return []

    rows: list[tuple[str, object]] = [
        ("計算模式", calc_params.get("calc_mode", "compare").capitalize()),
        ("時間粒度", "Weekly (日數據)" if is_weekly_daily else granularity.capitalize()),
    ]
    if is_weekly_daily:
        weeks = calc_params.get("selected_weeks", [])
        if weeks:
            days = len(weeks) * DAYS_PER_WEEK
            rows.append(("分析範圍", f"{weeks[0]} ~ {weeks[-1]} ({len(weeks)} 週 / {days} 天)"))

    lead_time = calc_params.get("lead_time_days") or calc_params.get("lead_time", 30)
    rows.append(("前置期", f"{lead_time} 天"))

    z = calc_params.get("z_scores", {})
    if z:
        rows.append(("服務水準", f"A={z.get('A', '-')} / B={z.get('B', '-')} / C={z.get('C', '-')}"))

    rows.append(("離群值偵測", "開啟" if calc_params.get("enable_outlier", True) else "關閉"))
    rows.append(("移動平均", "開啟" if calc_params.get("enable_ma", False) else "關閉"))

    working_days = calc_params.get("working_days_per_month")
    if working_days and granularity == "monthly":
        rows.append(("每月工作日", f"{working_days} 天"))

    rows.append(("", ""))
    return rows


def _write_comparison_summary_sheet(writer, comparison: dict, param_rows: list[tuple[str, object]]) -> None:
    """Sheet 1：計算參數 + 分倉/總倉的數量與金額對比。"""
    metric_rows: list[tuple[str, object]] = [
        ("分倉總安全庫存", safe_float(comparison.get("total_all_safety_stock", 0), 0)),
        ("總倉總安全庫存", safe_float(comparison.get("total_total_safety_stock", 0), 0)),
        ("庫存差異", safe_float(comparison.get("inventory_saved", 0), 0)),
        ("優化潛力 (%)", safe_round(comparison.get("savings_percentage", 0), 2, 0)),
        ("分倉總金額", safe_float(comparison.get("total_all_value", 0), 0)),
        ("總倉總金額", safe_float(comparison.get("total_total_value", 0), 0)),
        ("金額差異", safe_float(comparison.get("cost_saved", 0), 0)),
        ("金額優化 (%)", safe_round(comparison.get("savings_value_percentage", 0), 2, 0)),
        ("分倉 SKU 數量", comparison.get("all_sku_count", 0)),
        ("總倉 SKU 數量", comparison.get("total_sku_count", 0)),
    ]
    rows = param_rows + metric_rows
    data = {"項目": [item for item, _ in rows], "數值": [value for _, value in rows]}
    pd.DataFrame(data).to_excel(writer, sheet_name="對比摘要", index=False)


def _build_diff_rows(results_all: list[Any], results_total: list[Any]) -> list[dict[str, Any]]:
    """Sheet 4：同一出貨點+料號在分倉與總倉的安全庫存差異（只列差異達門檻者）。"""
    total_map = {f"{getattr(r, 'site', '')}_{getattr(r, 'sku', '')}": r for r in results_total}

    rows = []
    for r_all in results_all:
        sku = getattr(r_all, "sku", "")
        site = getattr(r_all, "site", "")
        r_total = total_map.get(f"{site}_{sku}")
        if not r_total:
            continue

        ss_all = safe_float(getattr(r_all, "safety_stock", 0), 0)
        ss_total = safe_float(getattr(r_total, "safety_stock", 0), 0)
        diff = ss_all - ss_total
        diff_pct = (diff / ss_all) * PERCENT if ss_all > 0 else 0
        if abs(diff_pct) < DIFF_ANALYSIS_MIN_PCT:
            continue

        rows.append({
            "出貨點": site,
            "料號": sku,
            "品名": getattr(r_all, "name", ""),
            "ABC分類": enum_value(getattr(r_all, "abc_class", "")),
            "分倉安全庫存": int(round(ss_all)),
            "總倉安全庫存": int(round(ss_total)),
            "差異數量": int(round(diff)),
            "差異百分比 (%)": safe_round(diff_pct, 2, 0),
            "建議": "總倉" if diff > 0 else "分倉",
        })
    return rows


def export_comparison_to_excel(
        all_data: tuple,
        total_data: tuple,
        comparison: dict,
        granularity: str = "monthly",
        is_weekly_daily: bool = False,
        calc_params: dict | None = None,
) -> bytes:
    """
    匯出對比模式的完整 Excel 分析

    Args:
        all_data: 分倉計算結果 (results, excluded, summary)
        total_data: 總倉計算結果 (results, excluded, summary)
        comparison: 對比統計數據
        granularity: 粒度
        is_weekly_daily: 週模式是否以日數據計算
        calc_params: 計算參數（snake_case），有值時列在摘要最前面

    Returns:
        Excel 檔案的二進位內容
    """
    results_all, excluded_all, _ = all_data
    results_total, excluded_total, _ = total_data

    logger.info(" 開始匯出對比模式 Excel")
    logger.info(f"   分倉數據: {len(results_all)} 筆")
    logger.info(f"   總倉數據: {len(results_total)} 筆")

    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        _write_comparison_summary_sheet(
            writer, comparison, _comparison_param_rows(calc_params, granularity, is_weekly_daily),
        )

        if results_all:
            _write_results_sheet(writer, results_all, "分倉計算", granularity=granularity, is_weekly_daily=is_weekly_daily)
        if results_total:
            _write_results_sheet(writer, results_total, "總倉計算", granularity=granularity, is_weekly_daily=is_weekly_daily)

        diff_rows = _build_diff_rows(results_all, results_total)
        if diff_rows:
            pd.DataFrame(diff_rows).to_excel(writer, sheet_name="差異分析", index=False)
        logger.info(f" 差異分析: {len(diff_rows)} 筆（差異 >= {DIFF_ANALYSIS_MIN_PCT}%）")

        if excluded_all or excluded_total:
            _write_excluded_sheet(writer, list(excluded_all or []) + list(excluded_total or []))

    output.seek(0)
    logger.info(" 對比模式 Excel 匯出完成")
    return output.read()
