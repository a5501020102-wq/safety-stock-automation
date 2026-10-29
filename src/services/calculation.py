"""
計算流程服務：載入已上傳的檔案、執行計算、組出 /api/calculate 的回應內容。
"""

from __future__ import annotations

import calendar
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.calculator import CalculationParams, Granularity, SafetyStockCalculator
from src.comparison import calculate_comparison_mode
from src.data_loader import DataLoadError, load_plan_data, load_price_data, load_sales_data
from src.models import PlanData, SalesData
from src.serialization import serialize_results_for_json

logger = logging.getLogger(__name__)


@dataclass
class CalculationInputs:
    """一次計算需要的已載入資料。"""
    sales_data: SalesData
    price_data: dict[str, float] | None
    plan_data: PlanData | None
    # 參數快照記錄的檔名（目前是暫存檔名，非使用者上傳時的原始檔名）
    filenames: dict[str, str | None]


def load_inputs(sales_path: Path, price_path: Path | None, plan_path: Path | None) -> CalculationInputs:
    """
    載入計算用的檔案。

    銷貨檔失敗時拋出 DataLoadError；單價與庫存計畫是選配，載入失敗只記錄警告並略過。
    """
    sales_data = load_sales_data(sales_path)

    price_data = None
    if price_path:
        try:
            price_data = load_price_data(price_path).price_map
        except DataLoadError as e:
            logger.warning(f"Price load failed, continuing without: {e}")

    plan_data = None
    if plan_path:
        try:
            plan_data = load_plan_data(plan_path)
        except DataLoadError as e:
            logger.warning(f"Plan load failed, continuing without: {e}")

    return CalculationInputs(
        sales_data=sales_data,
        price_data=price_data,
        plan_data=plan_data,
        filenames={
            "sales": sales_path.name,
            "price": price_path.name if price_path else None,
            "plan": plan_path.name if plan_path else None,
        },
    )


def resolve_days_per_period(granularity: str, working_days: int | None) -> int:
    """依粒度決定 days_per_period。月模式可被 workingDaysPerMonth 覆寫。"""
    resolved = Granularity(granularity)
    if resolved == Granularity.MONTHLY and working_days:
        return working_days
    return resolved.days_per_period


def _incomplete_month(max_date: datetime | None) -> str | None:
    """資料最後一天不是月底時，該月視為未完成月份（與 calculator 的排除邏輯一致）。"""
    if max_date is None:
        return None
    last_day = calendar.monthrange(max_date.year, max_date.month)[1]
    if max_date.day < last_day:
        return f"{max_date.year}-{max_date.month:02d}"
    return None


def build_parameters_snapshot(
    snapshot_calc_mode: str,
    params: CalculationParams,
    inputs: CalculationInputs,
    engine_version: str,
    execution_time_ms: float,
) -> dict[str, Any]:
    """組出回傳給前端的參數快照：驗證後的參數值、資料範圍與執行時間。"""
    sales_data = inputs.sales_data
    df = sales_data.df
    has_year_month = "year_month" in df.columns
    is_monthly = params.granularity == Granularity.MONTHLY.value
    return {
        "calc_mode": snapshot_calc_mode,
        "data_min_date": df["year_month"].min() if has_year_month else None,
        "data_max_date": df["year_month"].max() if has_year_month else None,
        "data_max_date_exact": sales_data.max_date.isoformat() if sales_data.max_date else None,
        "excluded_month": _incomplete_month(sales_data.max_date),
        "selected_months": params.selected_months,
        "lead_time_days": params.lead_time_days,
        "min_months": params.min_months,
        "z_scores": params.z_scores,
        "abc_thresholds": params.abc_thresholds,
        "enable_outlier": params.enable_outlier_detection,
        "enable_ma": params.enable_moving_average,
        "ma_window": params.ma_window if params.enable_moving_average else None,
        "granularity": params.granularity,
        "selected_weeks": params.selected_weeks,
        # 月模式下 days_per_period 會被 workingDaysPerMonth 覆寫；其他粒度為 None
        "working_days_per_month": (
            resolve_days_per_period(params.granularity, params.working_days_per_month) if is_monthly else None
        ),
        "engine_version": engine_version,
        "sales_filename": inputs.filenames.get("sales"),
        "price_filename": inputs.filenames.get("price"),
        "plan_filename": inputs.filenames.get("plan"),
        "executed_at": datetime.now(tz=timezone.utc).isoformat(),
        "execution_time_ms": round(execution_time_ms, 1),
    }


def run_calculation(
    calc_mode: str,
    target_site: str | None,
    params: CalculationParams,
    inputs: CalculationInputs,
    material_master: dict[str, Any] | None,
) -> tuple[dict[str, Any], float]:
    """
    執行計算並回傳 (回應主體, 執行毫秒數)。

    compare 模式回傳 comparison / all_summary / total_summary；
    其他模式回傳 results / excluded / summary。
    """
    calculator = SafetyStockCalculator()
    start_ts = time.perf_counter()

    if calc_mode == "compare":
        comparison_data = calculate_comparison_mode(
            calculator=calculator,
            sales_data=inputs.sales_data,
            params=params,
            price_data=inputs.price_data,
            plan_data=inputs.plan_data,
            material_master=material_master,
        )
        body = {
            "comparison": comparison_data["comparison"],
            "all_summary": serialize_results_for_json(*comparison_data["all"]),
            "total_summary": serialize_results_for_json(*comparison_data["total"]),
        }
    else:
        results, excluded, summary = calculator.calculate(
            inputs.sales_data,
            inputs.price_data,
            inputs.plan_data,
            calc_mode=calc_mode,
            target_site=target_site,
            material_master=material_master,
            params=params,
        )
        body = serialize_results_for_json(results, excluded, summary)

    return body, (time.perf_counter() - start_ts) * 1000
