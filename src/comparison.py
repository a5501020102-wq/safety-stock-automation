"""
對比模式：以同一組參數分別計算分倉(all)與總倉(total)，並彙總兩者差異。
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from .calculator import DEFAULT_ABC_THRESHOLDS, DEFAULT_Z_SCORES, CalculationParams, SafetyStockCalculator
from .value_utils import safe_float

logger = logging.getLogger(__name__)

PERCENT = 100


def _resolve_comparison_params(params: CalculationParams) -> CalculationParams:
    """補上對比模式需要的預設值，並驗證 selected_months。"""
    selected_months = params.selected_months if params.selected_months is not None else list(range(1, 13))
    if not isinstance(selected_months, list):
        raise TypeError("selected_months 必須是列表")
    if not all(isinstance(m, int) and 1 <= m <= 12 for m in selected_months):
        raise ValueError("selected_months 必須包含 1-12 的月份（int）")
    return replace(
        params,
        selected_months=selected_months,
        z_scores=params.z_scores if params.z_scores is not None else dict(DEFAULT_Z_SCORES),
        abc_thresholds=params.abc_thresholds if params.abc_thresholds is not None else dict(DEFAULT_ABC_THRESHOLDS),
    )


def _sum_field(results: list[Any] | None, field_name: str) -> float:
    return sum(safe_float(getattr(r, field_name, 0), 0) for r in (results or []))


def _share_percent(part: float, whole: float) -> float:
    """part 佔 whole 的百分比；whole <= 0 時為 0。"""
    return (part / whole) * PERCENT if whole > 0 else 0.0


def summarize_comparison(results_all: list[Any] | None, results_total: list[Any] | None) -> dict[str, Any]:
    """
    分倉與總倉的安全庫存數量、金額與差異。

    同時輸出英文與中文兩套 key：英文給前端，中文保留給舊版介面相容。
    """
    total_ss_all = _sum_field(results_all, "safety_stock")
    total_ss_total = _sum_field(results_total, "safety_stock")
    total_value_all = _sum_field(results_all, "safety_stock_value")
    total_value_total = _sum_field(results_total, "safety_stock_value")

    inventory_saved = total_ss_all - total_ss_total
    cost_saved = total_value_all - total_value_total
    savings_pct = _share_percent(inventory_saved, total_ss_all)
    savings_value_pct = _share_percent(cost_saved, total_value_all)

    logger.info(" 對比分析完成")
    logger.info(f"      節省數量: {int(inventory_saved)} ({savings_pct:.2f}%)")
    logger.info(f"      節省金額: ${cost_saved:.2f} ({savings_value_pct:.2f}%)")

    all_count = len(results_all or [])
    total_count = len(results_total or [])
    return {
        # --- 前端 comparison.js 常用（英文字段風格）---
        "total_all_safety_stock": int(total_ss_all),
        "total_total_safety_stock": int(total_ss_total),
        "inventory_saved": int(inventory_saved),
        "savings_percentage": round(savings_pct, 2),

        "total_all_value": round(total_value_all, 2),
        "total_total_value": round(total_value_total, 2),
        "cost_saved": round(cost_saved, 2),
        "savings_value_percentage": round(savings_value_pct, 2),

        "all_sku_count": all_count,
        "total_sku_count": total_count,

        # --- 中文 key（保留相容）---
        "分倉_總安全庫存": int(total_ss_all),
        "總倉_總安全庫存": int(total_ss_total),
        "節省數量": int(inventory_saved),
        "節省比例": round(savings_pct, 2),
        "分倉_總價值": round(total_value_all, 2),
        "總倉_總價值": round(total_value_total, 2),
        "節省價值": round(cost_saved, 2),
        "節省價值比例": round(savings_value_pct, 2),
        "分倉_SKU數": all_count,
        "總倉_SKU數": total_count,
    }


def calculate_comparison_mode(
        calculator: SafetyStockCalculator,
        sales_data: Any,
        params: CalculationParams,
        price_data: dict[str, float] | None = None,
        plan_data: Any | None = None,
        material_master: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    對比模式：以同一組參數分別計算分倉(all)與總倉(total)

    Args:
        calculator: 計算引擎實例
        sales_data: 銷貨資料
        params: 計算參數（z_scores / abc_thresholds / selected_months 為 None 時使用預設值）
        price_data: 單價資料（可選）
        plan_data: 庫存計劃（可選）
        material_master: 物料主檔（可選）

    Returns:
        {
            "all": (results, excluded, summary),
            "total": (results, excluded, summary),
            "comparison": {各種對比指標}
        }
    """
    params = _resolve_comparison_params(params)

    logger.info(" 對比模式計算開始")
    logger.info(f"   服務水準: A={params.z_scores['A']:.2f}, B={params.z_scores['B']:.2f}, C={params.z_scores['C']:.2f}")
    logger.info(f"   ABC門檻: A={params.abc_thresholds['A']:.0%}, B={params.abc_thresholds['B']:.0%}")

    results_all, excluded_all, summary_all = calculator.calculate(
        sales_data, price_data, plan_data, calc_mode="all", material_master=material_master, params=params,
    )
    logger.info(f" 分倉計算完成: {len(results_all)} 筆")
    results_total, excluded_total, summary_total = calculator.calculate(
        sales_data, price_data, plan_data, calc_mode="total", material_master=material_master, params=params,
    )
    logger.info(f" 總倉計算完成: {len(results_total)} 筆")

    return {
        "all": (results_all, excluded_all, summary_all),
        "total": (results_total, excluded_total, summary_total),
        "comparison": summarize_comparison(results_all, results_total),
    }
