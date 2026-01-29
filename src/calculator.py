"""
Safety Stock Calculator - Core calculation module (Optimized & Reviewed).
安全庫存計算核心模組 (優化與審查版)

Version: 4.3.4 (Z-scores & ABC Thresholds Support)
Author: 松鼠
Last Updated: 2026-01-29

Changelog v4.3.4:
- ✅ Added: z_scores 參數支援（A/B/C 類服務水準）
- ✅ Added: abc_thresholds 參數支援（ABC 分類門檻）
- ✅ Fixed: calculate() 方法接受新參數
- ✅ Improved: 參數覆寫邏輯

Changelog v4.2.1:
- ✅ Fixed: 添加 CV (Coefficient of Variation) 計算
- ✅ Fixed: 添加 reorder_point 計算
- ✅ Fixed: 添加 max_inventory 計算
- ✅ Improved: 完整的數據驗證
- ✅ Improved: 更好的錯誤處理

Key Features:
1. CV = std_dev / mean_demand (避免除以零)
2. reorder_point = lead_time_demand + safety_stock
3. max_inventory = reorder_point + order_quantity (可選)
4. z_scores = {A: 2.05, B: 1.65, C: 1.28} (可自訂)
5. abc_thresholds = {A: 0.80, B: 0.95} (可自訂)
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd

from .config_loader import config
from .models import (
    PlanData,
    PlanItemData,
    SalesData,
    StockStatus,
    ABCClass,
    KEY_DELIMITER,
)
from .utils import calculate_order_deadline, create_composite_key

# Configure logging
logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

MAD_TO_SIGMA_CONSTANT = 1.4826
DEFAULT_OVERSTOCK_MULTIPLIER = 3
MIN_RELIABLE_SAMPLE_SIZE = 3


# ============================================================================
# Data Classes (Calculator-specific)
# ============================================================================

@dataclass
class OutlierInfo:
    """Information about a detected outlier."""
    index: int
    value: float
    bound: str  # 'upper' or 'lower'
    threshold: float


@dataclass
class StatisticsResult:
    """Result of statistical calculations."""
    mean: float
    std_dev: float
    outliers: list[OutlierInfo]
    outliers_removed: int
    final_sample_size: int


@dataclass
class MonthlyPlanResult:
    """Monthly inventory projection result (用於結果展示)."""
    month: str
    demand: float
    supply: float
    transfer_in: float
    transfer_out: float
    independent_demand: float
    net_change: float
    ending_stock: float


@dataclass
class CalculationResult:
    """Result for a single SKU calculation."""
    # Required fields (no defaults - must come first)
    site: str = ""
    sku: str = ""
    name: str = ""
    abc_class: ABCClass = ABCClass.C

    # Demand statistics
    total_qty: float = 0.0
    total_value: float = 0.0
    active_months: int = 0
    mean_demand: float = 0.0
    std_dev: float = 0.0

    # ✅ v4.2.1: 新增 CV 和 reorder_point
    coefficient_of_variation: float = 0.0  # CV = std_dev / mean_demand
    reorder_point: int = 0  # ROP = lead_time_demand + safety_stock
    max_inventory: int = 0  # Max = reorder_point + order_quantity (可選)
    lead_time_days: int = 30  # 前置天數

    # Safety stock
    safety_stock: int = 0
    safety_stock_value: float = 0.0
    applied_z_score: float = 0.0

    # Current state
    current_stock: float | None = None
    status: StockStatus = StockStatus.GRAY

    # Outlier info
    outliers: list[OutlierInfo] = field(default_factory=list)
    outliers_removed: int = 0
    has_insufficient_samples: bool = False

    # Plan integration (v4.1.0)
    has_plan: bool = False
    plan_stock: float | None = None
    final_stock: float | None = None
    min_stock: float | None = None
    min_stock_month: str | None = None
    gap: float | None = None
    suggested_order: int = 0
    first_shortage_month: str | None = None
    order_deadline: str | None = None
    monthly_plan: list[MonthlyPlanResult] = field(default_factory=list)

    # Raw data for debugging
    monthly_values: list[float] = field(default_factory=list)
    price: float = 0.0


@dataclass
class ExcludedItem:
    """Item excluded from calculation due to insufficient data."""
    site: str
    sku: str
    name: str
    active_months: int
    total_qty: float
    reason: str


@dataclass
class CalculationSummary:
    """Summary of a calculation run."""
    run_date: datetime
    total_skus: int
    excluded_count: int
    total_outliers_removed: int
    skipped_dates: int

    # Health distribution
    shortage_risk_count: int
    healthy_count: int
    overstock_risk_count: int
    no_data_count: int

    # Parameters used
    lead_time_days: int
    min_months: int
    selected_months: list[int]
    z_scores: dict[str, float]
    outlier_removal_enabled: bool

    # v4.2.0 新增 - with defaults at the end
    moving_average_enabled: bool = False
    ma_window: int | None = None


@dataclass
class CalculationOptions:
    """Parameters for a calculation run."""
    # Time parameters
    lead_time_days: int = 30
    days_per_month: int = 30
    min_months: int = 2

    # Classification parameters
    abc_thresholds: dict[str, float] = field(default_factory=lambda: {"A": 0.80, "B": 0.95})
    z_scores: dict[str, float] = field(default_factory=lambda: {"A": 2.05, "B": 1.65, "C": 1.28})

    # Stock health parameters
    overstock_multiplier: int = DEFAULT_OVERSTOCK_MULTIPLIER

    # Outlier detection parameters
    enable_outlier_detection: bool = True
    mad_constant: float = MAD_TO_SIGMA_CONSTANT
    mad_multiplier: int = 3
    min_sample_size: int = 2
    min_confidence_samples: int = MIN_RELIABLE_SAMPLE_SIZE

    # Month selection
    selected_months: list[int] = field(default_factory=lambda: list(range(1, 13)))

    # v4.2.0: 移動平均參數
    enable_moving_average: bool = False
    ma_window: int = 3
    ma_min_periods: int = 2
    ma_fill_missing: bool = True
    ma_fill_value: float = 0.0

    # ✅ v4.2.1: 新增訂購量參數（用於計算 max_inventory）
    default_order_quantity: int = 0  # 默認訂購量（如果 = 0，則使用 safety_stock）


@dataclass
class CalculationRequest:
    """Request object for calculation."""
    sales_data: SalesData
    price_data: dict[str, float] | None = None
    plan_data: PlanData | None = None
    calc_mode: str = "all"  # 'all', 'total', or 'single'
    target_site: str | None = None
    options: CalculationOptions = field(default_factory=CalculationOptions)


# ============================================================================
# Main Calculator Class
# ============================================================================

class SafetyStockCalculator:
    """Safety Stock Calculator with ABC classification and outlier detection."""

    def __init__(self):
        """Initialize calculator with default parameters from config."""
        calc_config = config._config.get('calculation', {})
        outlier_config = config._config.get('outlier_detection', {})
        stock_health_config = calc_config.get('stock_health', {})
        ma_config = calc_config.get('moving_average', {})

        # Load default parameters from config
        self._default_options = CalculationOptions(
            lead_time_days=calc_config.get("lead_time_days", 30),
            days_per_month=calc_config.get("days_per_month", 30),
            min_months=calc_config.get("min_months", 2),
            abc_thresholds=calc_config.get("abc_thresholds", {"A": 0.80, "B": 0.95}).copy(),
            z_scores=calc_config.get("z_scores", {"A": 2.05, "B": 1.65, "C": 1.28}).copy(),
            overstock_multiplier=stock_health_config.get(
                "overstock_multiplier", DEFAULT_OVERSTOCK_MULTIPLIER
            ),
            enable_outlier_detection=outlier_config.get("enabled", True),
            mad_constant=outlier_config.get("consistency_constant", MAD_TO_SIGMA_CONSTANT),
            mad_multiplier=outlier_config.get("multiplier", 3),
            min_sample_size=outlier_config.get("min_sample_size", 2),
            enable_moving_average=ma_config.get("enabled", False),
            ma_window=ma_config.get("window", 3),
            ma_min_periods=ma_config.get("min_periods", 2),
            ma_fill_missing=ma_config.get("fill_missing", True),
            ma_fill_value=ma_config.get("fill_value", 0.0),
            default_order_quantity=calc_config.get("default_order_quantity", 0),
        )

        logger.info("SafetyStockCalculator initialized (v4.3.4 - Z-scores & ABC Support)")

    def calculate(
            self,
            sales_data: SalesData,
            price_data: dict[str, float] | None = None,
            plan_data: PlanData | None = None,
            calc_mode: str = "all",
            target_site: str | None = None,
            selected_months: list[int] | None = None,
            min_months: int | None = None,
            lead_time_days: int | None = None,
            z_scores: dict[str, float] | None = None,
            abc_thresholds: dict[str, float] | None = None,  # ✅ v4.3.4: 新增
            enable_outlier_detection: bool | None = None,
            enable_moving_average: bool | None = None,
            ma_window: int | None = None,
    ) -> tuple[list[CalculationResult], list[ExcludedItem], CalculationSummary]:
        """
        Execute the complete safety stock calculation.

        ✅ v4.3.4: 新增 abc_thresholds 參數支援

        Args:
            sales_data: 銷貨資料
            price_data: 單價資料（可選）
            plan_data: 庫存計畫資料（可選）
            calc_mode: 計算模式 ('all', 'total', 'single')
            target_site: 目標出貨點（僅 single 模式）
            selected_months: 選擇的月份列表
            min_months: 最少需求月數
            lead_time_days: 前置天數
            z_scores: 服務水準 Z-scores，例如 {"A": 2.05, "B": 1.65, "C": 1.28}
            abc_thresholds: ABC 分類門檻，例如 {"A": 0.80, "B": 0.95}
            enable_outlier_detection: 是否啟用離群值檢測
            enable_moving_average: 是否啟用移動平均
            ma_window: 移動平均窗口大小

        Returns:
            (結果列表, 排除項目列表, 計算摘要)
        """
        logger.info("=" * 60)
        logger.info("開始安全庫存計算 (v4.3.4)")
        logger.info("=" * 60)

        # Create options with overrides
        options = self._create_options(
            selected_months=selected_months,
            min_months=min_months,
            lead_time_days=lead_time_days,
            z_scores=z_scores,
            abc_thresholds=abc_thresholds,  # ✅ v4.3.4: 新增
            enable_outlier_detection=enable_outlier_detection,
            enable_moving_average=enable_moving_average,
            ma_window=ma_window,
        )

        # ✅ v4.3.4: 日誌輸出參數資訊
        logger.info(f"📊 計算參數：")
        logger.info(f"   服務水準: A={options.z_scores['A']:.2f}, "
                    f"B={options.z_scores['B']:.2f}, "
                    f"C={options.z_scores['C']:.2f}")
        logger.info(f"   ABC門檻: A={options.abc_thresholds['A']:.0%}, "
                    f"B={options.abc_thresholds['B']:.0%}")
        logger.info(f"   前置期: {options.lead_time_days} 天")
        logger.info(f"   最少月數: {options.min_months}")

        # Create request object
        request = CalculationRequest(
            sales_data=sales_data,
            price_data=price_data,
            plan_data=plan_data,
            calc_mode=calc_mode,
            target_site=target_site,
            options=options,
        )

        # Execute calculation pipeline
        try:
            results, excluded, summary = self._execute_calculation(request)
            logger.info(f"✓ 計算完成: {summary.total_skus} 個 SKU")
            return results, excluded, summary
        except Exception as e:
            logger.error(f"✗ 計算失敗: {e}")
            raise

    def _create_options(
            self,
            selected_months: list[int] | None = None,
            min_months: int | None = None,
            lead_time_days: int | None = None,
            z_scores: dict[str, float] | None = None,
            abc_thresholds: dict[str, float] | None = None,  # ✅ v4.3.4: 新增
            enable_outlier_detection: bool | None = None,
            enable_moving_average: bool | None = None,
            ma_window: int | None = None,
    ) -> CalculationOptions:
        """
        Create calculation options with overrides applied to defaults.

        ✅ v4.3.4: 新增 abc_thresholds 參數處理
        """
        # Start with defaults
        options = CalculationOptions(
            lead_time_days=self._default_options.lead_time_days,
            days_per_month=self._default_options.days_per_month,
            min_months=self._default_options.min_months,
            abc_thresholds=self._default_options.abc_thresholds.copy(),
            z_scores=self._default_options.z_scores.copy(),
            overstock_multiplier=self._default_options.overstock_multiplier,
            enable_outlier_detection=self._default_options.enable_outlier_detection,
            mad_constant=self._default_options.mad_constant,
            mad_multiplier=self._default_options.mad_multiplier,
            min_sample_size=self._default_options.min_sample_size,
            min_confidence_samples=self._default_options.min_confidence_samples,
            selected_months=self._default_options.selected_months.copy(),
            enable_moving_average=self._default_options.enable_moving_average,
            ma_window=self._default_options.ma_window,
            ma_min_periods=self._default_options.ma_min_periods,
            ma_fill_missing=self._default_options.ma_fill_missing,
            ma_fill_value=self._default_options.ma_fill_value,
            default_order_quantity=self._default_options.default_order_quantity,
        )

        # Apply overrides
        if lead_time_days is not None:
            options.lead_time_days = lead_time_days
            logger.debug(f"覆寫 lead_time_days: {lead_time_days}")

        if min_months is not None:
            options.min_months = min_months
            logger.debug(f"覆寫 min_months: {min_months}")

        if z_scores is not None:
            options.z_scores = z_scores.copy()
            logger.debug(f"覆寫 z_scores: {z_scores}")

        # ✅ v4.3.4: 處理 abc_thresholds 覆寫
        if abc_thresholds is not None:
            options.abc_thresholds = abc_thresholds.copy()
            logger.debug(f"覆寫 abc_thresholds: {abc_thresholds}")

        if enable_outlier_detection is not None:
            options.enable_outlier_detection = enable_outlier_detection
            logger.debug(f"覆寫 enable_outlier_detection: {enable_outlier_detection}")

        if selected_months is not None:
            options.selected_months = selected_months.copy()
            logger.debug(f"覆寫 selected_months: {selected_months}")

        if enable_moving_average is not None:
            options.enable_moving_average = enable_moving_average
            logger.debug(f"覆寫 enable_moving_average: {enable_moving_average}")

        if ma_window is not None:
            options.ma_window = ma_window
            logger.debug(f"覆寫 ma_window: {ma_window}")

        return options

    def _execute_calculation(
            self,
            request: CalculationRequest,
    ) -> tuple[list[CalculationResult], list[ExcludedItem], CalculationSummary]:
        """Execute the calculation pipeline."""
        # Step 1: Validate input data
        logger.info("步驟 1: 驗證輸入資料")
        self._validate_sales_data(request.sales_data.df)

        # Step 2: Aggregate data
        logger.info("步驟 2: 彙總銷貨資料")
        aggregated = self._aggregate_data(request)
        logger.info(f"  ✓ 彙總了 {len(aggregated)} 個 SKU")

        # Step 3: Calculate statistics (v4.2.0: 包含移動平均)
        logger.info("步驟 3: 計算統計數據")
        if request.options.enable_moving_average:
            logger.info(f"  ✓ 啟用 {request.options.ma_window} 個月移動平均")
        items_with_stats = self._calculate_statistics(aggregated, request.options)
        logger.info(f"  ✓ 計算了 {len(items_with_stats)} 個品項的統計")

        # Step 4: ABC Classification
        logger.info("步驟 4: 執行 ABC 分類")
        self._perform_abc_classification(items_with_stats, request.options)

        # Step 5: Calculate Safety Stock
        logger.info("步驟 5: 計算安全庫存")
        results, excluded = self._calculate_safety_stock(items_with_stats, request.options)
        logger.info(f"  ✓ 計算成功: {len(results)} 個")
        logger.info(f"  ✓ 排除項目: {len(excluded)} 個")

        # Step 6: Integrate Plan Data (v4.1.0)
        if request.plan_data and request.plan_data.items:
            logger.info("步驟 6: 整合庫存計畫")
            self._integrate_plan_data(results, request.plan_data, request.options)

        # Step 7: Sort results
        logger.info("步驟 7: 排序結果")
        results.sort(key=lambda r: (
            0 if r.status == StockStatus.RED else 1,
            r.site,
            r.abc_class.value,
            -r.total_value,
        ))

        # Step 8: Generate summary
        summary = self._generate_summary(
            results, excluded, request.sales_data.skipped_date_count, request.options
        )

        return results, excluded, summary

    def _validate_sales_data(self, df: pd.DataFrame) -> None:
        """Validate input sales data."""
        required_cols = ["site", "sku", "year_month", "quantity"]
        missing_cols = set(required_cols) - set(df.columns)

        if missing_cols:
            raise ValueError(f"銷貨資料缺少必要欄位: {missing_cols}")

        if df.empty:
            raise ValueError("銷貨資料為空")

        errors = []

        for idx, row in df.iterrows():
            sku = row.get("sku")
            if pd.isna(sku) or str(sku).strip() == "":
                errors.append(f"第 {idx} 列: SKU 為空")
                continue

            try:
                qty = float(row.get("quantity", 0))
                if qty < 0:
                    errors.append(f"第 {idx} 列: 數量為負數 ({qty})")
            except (ValueError, TypeError):
                errors.append(f"第 {idx} 列: 數量格式無效 ({row.get('quantity')})")

            year_month = row.get("year_month")
            if pd.isna(year_month):
                errors.append(f"第 {idx} 列: year_month 為空")
            elif not isinstance(year_month, str) or "-" not in str(year_month):
                errors.append(f"第 {idx} 列: year_month 格式無效 ({year_month}),應為 'YYYY-MM'")

        if errors:
            error_summary = "\n".join(errors[:10])
            if len(errors) > 10:
                error_summary += f"\n... 還有 {len(errors) - 10} 個錯誤"
            raise ValueError(f"資料驗證失敗:\n{error_summary}")

        logger.info(f"  ✓ 驗證通過: {len(df)} 筆記錄")

    def _aggregate_data(self, request: CalculationRequest) -> dict[str, dict[str, Any]]:
        """Aggregate sales data by site+SKU, building monthly timelines."""
        df = request.sales_data.df
        price_map = request.price_data or {}
        calc_mode = request.calc_mode
        target_site = request.target_site

        aggregated_data: dict[str, dict[str, Any]] = {}
        skipped_rows = 0

        for _, row in df.iterrows():
            site = self._determine_site_from_row(row, calc_mode, target_site)

            if site is None:
                skipped_rows += 1
                continue

            sku = str(row.get("sku", "")).strip()
            if not sku:
                skipped_rows += 1
                logger.debug(f"跳過無 SKU 的資料列")
                continue

            year_month = row.get("year_month")
            if not year_month:
                skipped_rows += 1
                logger.debug(f"跳過無 year_month 的資料列: SKU={sku}")
                continue

            qty = float(row.get("quantity", 0))

            composite_key = create_composite_key(site, sku, KEY_DELIMITER)

            if composite_key not in aggregated_data:
                aggregated_data[composite_key] = self._initialize_aggregated_item(
                    row, site, sku, price_map
                )

            timeline = aggregated_data[composite_key]["timeline"]
            timeline[year_month] = timeline.get(year_month, 0.0) + qty

        if skipped_rows > 0:
            logger.info(f"  ℹ 跳過 {skipped_rows} 筆無效資料")

        return aggregated_data

    def _determine_site_from_row(
            self,
            row: pd.Series,
            calc_mode: str,
            target_site: str | None,
    ) -> str | None:
        """Determine site identifier based on calculation mode."""
        raw_site = str(row.get("site", "DEFAULT"))

        if calc_mode == "total":
            return "總倉"
        elif calc_mode == "single":
            if target_site and raw_site != target_site:
                return None
            return raw_site
        else:  # calc_mode == "all"
            return raw_site

    def _initialize_aggregated_item(
            self,
            row: pd.Series,
            site: str,
            sku: str,
            price_map: dict[str, float],
    ) -> dict[str, Any]:
        """Initialize a new aggregated item entry."""
        price = price_map.get(sku, 0.0)
        if price == 0.0:
            try:
                price = float(row.get("price", 0.0))
            except (ValueError, TypeError):
                price = 0.0

        stock = row.get("stock")
        stock = stock if pd.notna(stock) else None

        return {
            "site": site,
            "sku": sku,
            "name": str(row.get("name", "")),
            "price": price,
            "stock": stock,
            "timeline": {},
        }

    # ========================================================================
    # v4.2.0: 移動平均相關方法
    # ========================================================================

    def _fill_missing_months(
            self,
            timeline: dict[str, float],
            selected_months: list[int],
            fill_value: float = 0.0,
    ) -> tuple[list[float], int]:
        """填補缺失月份並返回完整的月度數據列表 (v4.2.0)"""
        if not timeline:
            return [], 0

        try:
            from datetime import datetime
            from dateutil.relativedelta import relativedelta
        except ImportError:
            logger.error("需要安裝 python-dateutil: pip install python-dateutil")
            return list(timeline.values()), 0

        year_months = sorted(timeline.keys())
        start_ym = year_months[0]
        end_ym = year_months[-1]

        try:
            start_date = datetime.strptime(start_ym, '%Y-%m')
            end_date = datetime.strptime(end_ym, '%Y-%m')
        except ValueError as e:
            logger.error(f"日期格式錯誤: {e}, 跳過填補")
            return list(timeline.values()), 0

        all_months = []
        current = start_date
        while current <= end_date:
            if current.month in selected_months:
                ym_str = f"{current.year}-{current.month:02d}"
                all_months.append(ym_str)
            current += relativedelta(months=1)

        filled_values = []
        missing_count = 0

        for ym in all_months:
            if ym in timeline:
                filled_values.append(timeline[ym])
            else:
                filled_values.append(fill_value)
                missing_count += 1

        return filled_values, missing_count

    def _apply_moving_average(
            self,
            values: list[float],
            window: int = 3,
            min_periods: int = 2,
    ) -> list[float]:
        """對月度數據進行簡單移動平均平滑 (v4.2.0)"""
        if not values or len(values) < min_periods:
            logger.debug(f"樣本數不足 ({len(values)} < {min_periods})，跳過移動平均")
            return values

        if window >= len(values):
            logger.debug(f"窗口大小 ({window}) >= 樣本數 ({len(values)})，使用全部數據平均")
            mean_val = sum(values) / len(values)
            return [mean_val] * len(values)

        try:
            import pandas as pd
            series = pd.Series(values)

            smoothed = series.rolling(
                window=window,
                min_periods=min_periods
            ).mean()

            smoothed_list = smoothed.fillna(series).tolist()

            logger.debug(
                f"移動平均 (window={window}): "
                f"{len(values)} 個月 → 完成平滑"
            )

            return smoothed_list

        except ImportError:
            logger.warning("pandas 未安裝，使用純 Python 實作移動平均")
            return self._apply_moving_average_pure_python(values, window, min_periods)

    def _apply_moving_average_pure_python(
            self,
            values: list[float],
            window: int,
            min_periods: int,
    ) -> list[float]:
        """純 Python 實作的移動平均（不依賴 pandas）(v4.2.0)"""
        smoothed = []

        for i in range(len(values)):
            start = max(0, i - window + 1)
            window_values = values[start:i + 1]

            if len(window_values) >= min_periods:
                avg = sum(window_values) / len(window_values)
                smoothed.append(avg)
            else:
                smoothed.append(values[i])

        return smoothed

    # ========================================================================
    # 統計計算（整合移動平均）
    # ========================================================================

    def _calculate_statistics(
            self,
            aggregated: dict[str, dict[str, Any]],
            options: CalculationOptions,
    ) -> list[dict[str, Any]]:
        """Calculate demand statistics for each item. v4.2.0: 整合移動平均功能"""
        items = []

        for key, item in aggregated.items():
            if options.enable_moving_average and options.ma_fill_missing:
                filled_values, missing_count = self._fill_missing_months(
                    item["timeline"],
                    options.selected_months,
                    options.ma_fill_value
                )

                if missing_count > 0:
                    logger.debug(
                        f"{item['sku']}: 填補了 {missing_count} 個缺失月份"
                    )

                monthly_values = filled_values
                total_qty = sum(monthly_values)

            else:
                monthly_values = []
                total_qty = 0.0

                for time_key, qty in item["timeline"].items():
                    try:
                        month = int(time_key.split("-")[1])
                        if month in options.selected_months:
                            monthly_values.append(qty)
                            total_qty += qty
                    except (IndexError, ValueError):
                        logger.warning(f"無效的 year_month 格式: {time_key}")
                        continue

            if options.enable_moving_average and len(monthly_values) > 0:
                smoothed_values = self._apply_moving_average(
                    monthly_values,
                    window=options.ma_window,
                    min_periods=options.ma_min_periods
                )

                logger.debug(
                    f"{item['sku']}: 移動平均 "
                    f"(原始={len(monthly_values)}月, window={options.ma_window})"
                )
            else:
                smoothed_values = monthly_values

            active_months = sum(1 for v in monthly_values if v > 0)
            stats = self._calculate_mad_statistics(smoothed_values, options)

            items.append({
                **item,
                "monthly_values": monthly_values,
                "smoothed_values": smoothed_values if options.enable_moving_average else monthly_values,
                "active_months": active_months,
                "total_qty": total_qty,
                "total_value": total_qty * item["price"],
                "mean": stats.mean,
                "std_dev": stats.std_dev,
                "outliers": stats.outliers,
                "outliers_removed": stats.outliers_removed,
                "has_insufficient_samples": stats.final_sample_size < options.min_confidence_samples,
            })

        return items

    def _calculate_mad_statistics(
            self,
            values: list[float],
            options: CalculationOptions | None = None,
    ) -> StatisticsResult:
        """Calculate mean and standard deviation with MAD-based outlier detection."""
        if options is None:
            mad_constant = MAD_TO_SIGMA_CONSTANT
            mad_multiplier = 3
            min_sample_size = 2
            outlier_enabled = True
        else:
            mad_constant = options.mad_constant
            mad_multiplier = options.mad_multiplier
            min_sample_size = options.min_sample_size
            outlier_enabled = options.enable_outlier_detection

        if not values:
            return StatisticsResult(
                mean=0, std_dev=0, outliers=[],
                outliers_removed=0, final_sample_size=0
            )

        if len(values) == 1:
            return StatisticsResult(
                mean=values[0], std_dev=0, outliers=[],
                outliers_removed=0, final_sample_size=1
            )

        n = len(values)
        sorted_values = sorted(values)

        mid = n // 2
        median = (
            (sorted_values[mid - 1] + sorted_values[mid]) / 2
            if n % 2 == 0
            else sorted_values[mid]
        )

        absolute_deviations = [abs(v - median) for v in values]
        sorted_deviations = sorted(absolute_deviations)
        mad = (
            (sorted_deviations[mid - 1] + sorted_deviations[mid]) / 2
            if n % 2 == 0
            else sorted_deviations[mid]
        )

        sigma_equivalent = mad * mad_constant

        lower_bound = median - mad_multiplier * sigma_equivalent
        upper_bound = median + mad_multiplier * sigma_equivalent

        outliers: list[OutlierInfo] = []
        clean_values: list[float] = []

        for idx, v in enumerate(values):
            if sigma_equivalent > 0 and (v < lower_bound or v > upper_bound):
                outliers.append(OutlierInfo(
                    index=idx,
                    value=v,
                    bound="upper" if v > upper_bound else "lower",
                    threshold=upper_bound if v > upper_bound else lower_bound,
                ))
            else:
                clean_values.append(v)

        final_values: list[float]
        outliers_removed = 0

        if (
                outlier_enabled
                and outliers
                and len(clean_values) >= min_sample_size
        ):
            final_values = clean_values
            outliers_removed = len(outliers)
            logger.debug(
                f"移除 {outliers_removed} 個離群值，保留 {len(final_values)} 個樣本"
            )
        else:
            final_values = values

        final_n = len(final_values)
        mean = sum(final_values) / final_n

        std_dev = 0.0
        if final_n > 1:
            variance = sum((v - mean) ** 2 for v in final_values) / (final_n - 1)
            std_dev = math.sqrt(variance)

        return StatisticsResult(
            mean=mean,
            std_dev=std_dev,
            outliers=outliers,
            outliers_removed=outliers_removed,
            final_sample_size=final_n,
        )

    def _perform_abc_classification(
            self,
            items: list[dict[str, Any]],
            options: CalculationOptions,
    ) -> None:
        """
        Perform ABC classification based on total value or quantity.

        ✅ v4.3.4: 使用 options.abc_thresholds 進行分類
        """
        if not items:
            return

        if len(items) == 1:
            items[0]["abc_class"] = ABCClass.A
            logger.debug("單一品項，分類為 A")
            return

        use_value = any(item["price"] > 0 for item in items)
        sort_key = "total_value" if use_value else "total_qty"

        logger.debug(f"ABC 分類使用: {'價值' if use_value else '數量'}")

        items.sort(key=lambda x: x[sort_key], reverse=True)

        total = sum(item[sort_key] for item in items)

        if total == 0:
            logger.warning("總價值/數量為 0，所有品項分類為 C")
            for item in items:
                item["abc_class"] = ABCClass.C
            return

        cumulative = 0.0
        # ✅ v4.3.4: 使用參數傳入的 abc_thresholds
        threshold_a = options.abc_thresholds["A"]
        threshold_b = options.abc_thresholds["B"]

        logger.debug(f"ABC 分類門檻: A={threshold_a:.0%}, B={threshold_b:.0%}")

        for item in items:
            cumulative += item[sort_key]
            percentage = cumulative / total

            if percentage <= threshold_a:
                item["abc_class"] = ABCClass.A
            elif percentage <= threshold_b:
                item["abc_class"] = ABCClass.B
            else:
                item["abc_class"] = ABCClass.C

        class_counts = {
            ABCClass.A: sum(1 for i in items if i["abc_class"] == ABCClass.A),
            ABCClass.B: sum(1 for i in items if i["abc_class"] == ABCClass.B),
            ABCClass.C: sum(1 for i in items if i["abc_class"] == ABCClass.C),
        }
        logger.debug(f"ABC 分類結果: A={class_counts[ABCClass.A]}, "
                     f"B={class_counts[ABCClass.B]}, C={class_counts[ABCClass.C]}")

    def _calculate_safety_stock(
            self,
            items: list[dict[str, Any]],
            options: CalculationOptions,
    ) -> tuple[list[CalculationResult], list[ExcludedItem]]:
        """
        Calculate safety stock for each item.

        ✅ v4.2.1: 添加 CV 和 reorder_point 計算
        ✅ v4.3.4: 使用 options.z_scores 進行安全庫存計算

        Formula:
        - SS = Z × σ_monthly × √(LT/30)
        - CV = σ / μ  (Coefficient of Variation)
        - ROP = (μ / 30) × LT + SS  (Reorder Point)
        - Max = ROP + Q  (Maximum Inventory)
        """
        results: list[CalculationResult] = []
        excluded: list[ExcludedItem] = []

        lead_time_factor = math.sqrt(options.lead_time_days / options.days_per_month)

        for item in items:
            # Check minimum months requirement
            if options.min_months > 0 and item["active_months"] < options.min_months:
                excluded.append(ExcludedItem(
                    site=item["site"],
                    sku=item["sku"],
                    name=item["name"],
                    active_months=item["active_months"],
                    total_qty=item["total_qty"],
                    reason=f"月數不足 ({item['active_months']} < {options.min_months})",
                ))
                continue

            # ✅ v4.3.4: Get Z-score for ABC class from options
            abc_class: ABCClass = item["abc_class"]
            applied_z = options.z_scores.get(abc_class.value, 1.65)

            # Calculate safety stock
            safety_stock = math.ceil(applied_z * item["std_dev"] * lead_time_factor)
            safety_stock_value = safety_stock * item["price"]

            # ✅ v4.2.1: 計算 CV (Coefficient of Variation)
            # CV = std_dev / mean_demand
            # 避免除以零
            mean_demand = item["mean"]
            std_dev = item["std_dev"]

            if mean_demand > 0:
                coefficient_of_variation = std_dev / mean_demand
            else:
                coefficient_of_variation = 0.0

            # ✅ v4.2.1: 計算 Reorder Point (ROP)
            # ROP = Lead Time Demand + Safety Stock
            # Lead Time Demand = (mean_monthly_demand / 30) * lead_time_days
            if mean_demand > 0:
                daily_demand = mean_demand / options.days_per_month
                lead_time_demand = daily_demand * options.lead_time_days
                reorder_point = math.ceil(lead_time_demand + safety_stock)
            else:
                reorder_point = safety_stock  # 如果沒有需求，ROP = SS

            # ✅ v4.2.1: 計算 Maximum Inventory (Max)
            # Max = ROP + Order Quantity
            # 如果沒有設定訂購量，使用 safety_stock 作為默認值
            order_quantity = options.default_order_quantity
            if order_quantity == 0:
                order_quantity = safety_stock  # 默認訂購量 = 安全庫存

            max_inventory = reorder_point + order_quantity

            # Debug logging for first few items
            if len(results) < 3:
                logger.debug(
                    f"SKU {item['sku']}: "
                    f"ABC={abc_class.value}, Z={applied_z:.2f}, "
                    f"mean={mean_demand:.2f}, std={std_dev:.2f}, "
                    f"CV={coefficient_of_variation:.3f}, SS={safety_stock}, "
                    f"ROP={reorder_point}, Max={max_inventory}"
                )

            # Determine stock health status
            status = self._determine_stock_health(
                item["stock"], safety_stock, options.overstock_multiplier
            )

            results.append(CalculationResult(
                site=item["site"],
                sku=item["sku"],
                name=item["name"],
                abc_class=abc_class,
                total_qty=item["total_qty"],
                total_value=item["total_value"],
                active_months=item["active_months"],
                mean_demand=mean_demand,
                std_dev=std_dev,
                coefficient_of_variation=coefficient_of_variation,  # ✅ 新增
                reorder_point=reorder_point,  # ✅ 新增
                max_inventory=max_inventory,  # ✅ 新增
                lead_time_days=options.lead_time_days,  # ✅ 新增
                safety_stock=safety_stock,
                safety_stock_value=safety_stock_value,
                applied_z_score=applied_z,
                current_stock=item["stock"],
                status=status,
                outliers=item["outliers"],
                outliers_removed=item["outliers_removed"],
                has_insufficient_samples=item["has_insufficient_samples"],
                monthly_values=item["monthly_values"],
                price=item["price"],
            ))

        return results, excluded

    def _determine_stock_health(
            self,
            stock: float | None,
            safety_stock: int,
            overstock_multiplier: int,
    ) -> StockStatus:
        """Determine stock health status based on current stock level."""
        if stock is None:
            return StockStatus.GRAY

        if safety_stock == 0 and stock == 0:
            return StockStatus.GRAY

        if stock < safety_stock:
            return StockStatus.RED

        if safety_stock > 0 and stock > safety_stock * overstock_multiplier:
            return StockStatus.BLUE

        return StockStatus.GREEN

    def _integrate_plan_data(
            self,
            results: list[CalculationResult],
            plan_data: PlanData,
            options: CalculationOptions,
    ) -> None:
        """Integrate inventory plan data with calculation results (v4.1.0)."""
        integrated_count = 0

        for result in results:
            plan_item = plan_data.get_item(result.site, result.sku)

            if not plan_item:
                result.has_plan = False
                continue

            result.has_plan = True
            result.plan_stock = plan_item.current_stock

            running_stock = plan_item.current_stock
            first_shortage: str | None = None
            min_stock = plan_item.current_stock
            min_stock_month: str | None = None

            monthly_results: list[MonthlyPlanResult] = []

            for month in plan_data.detected_months:
                month_data = plan_item.months.get(month)
                if not month_data:
                    continue

                running_stock += month_data.net_change

                monthly_results.append(MonthlyPlanResult(
                    month=month,
                    demand=month_data.demand,
                    supply=month_data.supply,
                    transfer_in=month_data.transfer_in,
                    transfer_out=month_data.transfer_out,
                    independent_demand=month_data.independent_demand,
                    net_change=month_data.net_change,
                    ending_stock=running_stock,
                ))

                if running_stock < min_stock:
                    min_stock = running_stock
                    min_stock_month = month

                if first_shortage is None and running_stock < result.safety_stock:
                    first_shortage = month

            result.final_stock = running_stock
            result.min_stock = min_stock
            result.min_stock_month = min_stock_month
            result.first_shortage_month = first_shortage
            result.monthly_plan = monthly_results

            result.gap = running_stock - result.safety_stock
            result.suggested_order = max(0, -int(result.gap))

            if first_shortage:
                result.order_deadline = calculate_order_deadline(
                    first_shortage, options.lead_time_days
                )

            result.status = self._determine_stock_health_with_plan(
                result.final_stock, result.safety_stock, min_stock, options.overstock_multiplier
            )

            integrated_count += 1

        logger.info(f"  ✓ 整合了 {integrated_count} 個品項的庫存計畫")

    def _determine_stock_health_with_plan(
            self,
            final_stock: float | None,
            safety_stock: int,
            min_stock: float | None,
            overstock_multiplier: int,
    ) -> StockStatus:
        """Determine stock health using plan data (v4.1.0)."""
        check_stock = min_stock if min_stock is not None else final_stock

        return self._determine_stock_health(
            check_stock, safety_stock, overstock_multiplier
        )

    def _generate_summary(
            self,
            results: list[CalculationResult],
            excluded: list[ExcludedItem],
            skipped_dates: int,
            options: CalculationOptions,
    ) -> CalculationSummary:
        """Generate calculation summary statistics."""
        total_outliers = sum(r.outliers_removed for r in results)

        status_counts = {
            StockStatus.RED: 0,
            StockStatus.GREEN: 0,
            StockStatus.BLUE: 0,
            StockStatus.GRAY: 0,
        }
        for result in results:
            status_counts[result.status] += 1

        return CalculationSummary(
            run_date=datetime.now(),
            total_skus=len(results),
            excluded_count=len(excluded),
            total_outliers_removed=total_outliers,
            skipped_dates=skipped_dates,
            shortage_risk_count=status_counts[StockStatus.RED],
            healthy_count=status_counts[StockStatus.GREEN],
            overstock_risk_count=status_counts[StockStatus.BLUE],
            no_data_count=status_counts[StockStatus.GRAY],
            lead_time_days=options.lead_time_days,
            min_months=options.min_months,
            selected_months=options.selected_months,
            z_scores=options.z_scores.copy(),
            outlier_removal_enabled=options.enable_outlier_detection,
            moving_average_enabled=options.enable_moving_average,
            ma_window=options.ma_window if options.enable_moving_average else None,
        )