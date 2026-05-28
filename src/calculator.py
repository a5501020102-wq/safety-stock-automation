"""
Safety Stock Calculator - Core calculation module (Optimized & Reviewed).
安全庫存計算核心模組 (優化與審查版)

Version: 4.3.4 (Z-scores & ABC Thresholds Support)
Author: 松鼠
Last Updated: 2026-01-29

Changelog v4.3.4:
- Added: z_scores 參數支援（A/B/C 類服務水準）
- Added: abc_thresholds 參數支援（ABC 分類門檻）
- Fixed: calculate() 方法接受新參數
- Improved: 參數覆寫邏輯

Changelog v4.2.1:
- Fixed: 添加 CV (Coefficient of Variation) 計算
- Fixed: 添加 reorder_point 計算
- Fixed: 添加 max_inventory 計算
- Improved: 完整的數據驗證
- Improved: 更好的錯誤處理

Key Features:
1. CV = std_dev / mean_demand (避免除以零)
2. reorder_point = lead_time_demand + safety_stock
3. max_inventory = reorder_point + order_quantity (可選)
4. z_scores = {A: 2.05, B: 1.65, C: 1.28} (可自訂)
5. abc_thresholds = {A: 0.80, B: 0.95} (可自訂)
"""

import calendar
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

import pandas as pd
from dateutil.relativedelta import relativedelta

from .config_loader import config
from .models import (
    KEY_DELIMITER,
    ABCClass,
    PlanData,
    SalesData,
    StockStatus,
)
from .utils import calculate_order_deadline, create_composite_key

# ============================================================================
# Granularity Enum
# ============================================================================

class Granularity(str, Enum):
    """Aggregation granularity for demand analysis."""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"

    @property
    def days_per_period(self) -> int:
        if self == Granularity.DAILY:
            return 1
        elif self == Granularity.WEEKLY:
            return 7
        else:
            return 30

# Configure logging
logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

MAD_TO_SIGMA_CONSTANT = 1.4826
DEFAULT_OVERSTOCK_MULTIPLIER = 3
MIN_RELIABLE_SAMPLE_SIZE = 3

# Syntetos-Boylan 需求型態分類切點（業界標準值）
# ADI (Average Demand Interval) = 期數 / 有需求期數
# CV² = (非零期需求 std / mean)²
ADI_THRESHOLD = 1.32
CV2_THRESHOLD = 0.49


def _classify_demand_pattern(adi: float, cv_squared: float) -> str:
    """Syntetos-Boylan 四象限需求型態分類。

    smooth (穩定):       頻繁且量穩 → 標準 SS 公式適用
    erratic (波動):      頻繁但量波動大
    intermittent (零星): 不常出但量穩
    lumpy (雜亂):        不常出且量亂 → 最難預測
    """
    if adi < ADI_THRESHOLD and cv_squared < CV2_THRESHOLD:
        return "smooth"
    if adi < ADI_THRESHOLD and cv_squared >= CV2_THRESHOLD:
        return "erratic"
    if adi >= ADI_THRESHOLD and cv_squared < CV2_THRESHOLD:
        return "intermittent"
    return "lumpy"


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
    total_months: int = 0
    mean_demand: float = 0.0
    std_dev: float = 0.0

    # v4.2.1: 新增 CV 和 reorder_point
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
    # 周轉率 = 銷貨總數 / 庫存數量（需要 plan 報表提供庫存數量）
    turnover_rate: float | None = None
    # 覆蓋天數 = 現有庫存 / 日均需求（表示庫存可撐幾天）
    coverage_days: float | None = None

    # Trend detection
    trend_pct: float | None = None
    trend_label: str = "—"  # "+X%", "-X%", "New", "Discontinued", "—"

    # ABC metadata
    is_price_missing: bool = False

    # Raw data for debugging
    monthly_values: list[float] = field(default_factory=list)
    price: float = 0.0

    # 週模式日數據統計
    data_point_count: int = 0
    data_point_warning: str | None = None

    # 需求型態分類（Syntetos-Boylan，僅月粒度計算）
    demand_pattern: str = "—"  # smooth / erratic / intermittent / lumpy / "—"
    adi: float | None = None  # 平均需求間隔
    cv_squared: float | None = None  # 非零期需求變異平方


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
    days_per_period: int = 30
    min_months: int = 2
    granularity: Granularity = Granularity.MONTHLY

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

    # v4.2.1: 新增訂購量參數（用於計算 max_inventory）
    default_order_quantity: int = 0

    # v4.4.0: 資料最大日期（用於排除未完成月份）
    max_date: datetime | None = None

    # v5.1.0: Category-based lead time overrides
    category_lead_times: dict[str, int] = field(default_factory=dict)
    group_lead_times: dict[str, int] = field(default_factory=dict)

    # v5.1.0: Date range filter
    date_from: datetime | None = None
    date_to: datetime | None = None

    # Trend detection
    trend_mode: str = "none"  # "short" / "yoy" / "none"

    # 週模式：選定的週列表（例如 ["2025-W10", "2025-W11", ...]）
    # 有值時，週模式改用選定週內的日數據計算 mean/std，days_per_period 改為 1
    selected_weeks: list[str] | None = None


@dataclass
class CalculationRequest:
    """Request object for calculation."""
    sales_data: SalesData
    price_data: dict[str, float] | None = None
    plan_data: PlanData | None = None
    calc_mode: str = "all"
    target_site: str | None = None
    material_master: dict[str, Any] | None = None
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
            days_per_period=Granularity.MONTHLY.days_per_period,
            min_months=calc_config.get("min_months", 2),
            granularity=Granularity.MONTHLY,
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
            abc_thresholds: dict[str, float] | None = None,
            enable_outlier_detection: bool | None = None,
            enable_moving_average: bool | None = None,
            ma_window: int | None = None,
            max_date: datetime | None = None,
            granularity: str | Granularity | None = None,
            category_lead_times: dict[str, int] | None = None,
            group_lead_times: dict[str, int] | None = None,
            material_master: dict[str, Any] | None = None,
            date_from: datetime | None = None,
            date_to: datetime | None = None,
            trend_mode: str = "none",
            working_days_per_month: int | None = None,
            selected_weeks: list[str] | None = None,
    ) -> tuple[list[CalculationResult], list[ExcludedItem], CalculationSummary]:
        """
        Execute the complete safety stock calculation.

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
            selected_weeks: 週模式下選定的週列表（例如 ["2025-W10", "2025-W11"]）

        Returns:
            (結果列表, 排除項目列表, 計算摘要)
        """
        logger.info("=" * 60)
        logger.info("開始安全庫存計算 (v4.4.0)")
        logger.info("=" * 60)

        # Resolve max_date: prefer explicit param, fallback to sales_data
        resolved_max_date = max_date or getattr(sales_data, 'max_date', None)

        # Create options with overrides
        options = self._create_options(
            selected_months=selected_months,
            min_months=min_months,
            lead_time_days=lead_time_days,
            z_scores=z_scores,
            abc_thresholds=abc_thresholds,
            enable_outlier_detection=enable_outlier_detection,
            enable_moving_average=enable_moving_average,
            ma_window=ma_window,
            max_date=resolved_max_date,
            granularity=granularity,
            category_lead_times=category_lead_times,
            group_lead_times=group_lead_times,
            date_from=date_from,
            date_to=date_to,
            trend_mode=trend_mode,
            working_days_per_month=working_days_per_month,
            selected_weeks=selected_weeks,
        )

        # v4.3.4: 日誌輸出參數資訊
        logger.info(" 計算參數：")
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
            material_master=material_master,
        )

        # Execute calculation pipeline
        try:
            results, excluded, summary = self._execute_calculation(request)
            logger.info(f" 計算完成: {summary.total_skus} 個 SKU")
            return results, excluded, summary
        except Exception as e:
            logger.error(f" 計算失敗: {e}")
            raise

    def _create_options(
            self,
            selected_months: list[int] | None = None,
            min_months: int | None = None,
            lead_time_days: int | None = None,
            z_scores: dict[str, float] | None = None,
            abc_thresholds: dict[str, float] | None = None,
            enable_outlier_detection: bool | None = None,
            enable_moving_average: bool | None = None,
            ma_window: int | None = None,
            max_date: datetime | None = None,
            granularity: str | Granularity | None = None,
            category_lead_times: dict[str, int] | None = None,
            group_lead_times: dict[str, int] | None = None,
            date_from: datetime | None = None,
            date_to: datetime | None = None,
            trend_mode: str = "none",
            working_days_per_month: int | None = None,
            selected_weeks: list[str] | None = None,
    ) -> CalculationOptions:
        """Create calculation options with overrides applied to defaults."""
        # Resolve granularity
        resolved_granularity = self._default_options.granularity
        if granularity is not None:
            if isinstance(granularity, str):
                resolved_granularity = Granularity(granularity)
            else:
                resolved_granularity = granularity

        # Start with defaults
        options = CalculationOptions(
            lead_time_days=self._default_options.lead_time_days,
            days_per_period=resolved_granularity.days_per_period,
            min_months=self._default_options.min_months,
            granularity=resolved_granularity,
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

        # v4.3.4: 處理 abc_thresholds 覆寫
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

        if max_date is not None:
            options.max_date = max_date
            logger.debug(f"覆寫 max_date: {max_date}")

        if category_lead_times:
            options.category_lead_times = {str(k): int(v) for k, v in category_lead_times.items()}
        if group_lead_times:
            options.group_lead_times = {str(k): int(v) for k, v in group_lead_times.items()}

        if date_from is not None:
            options.date_from = date_from
        if date_to is not None:
            options.date_to = date_to

        if trend_mode in ("short", "yoy", "none"):
            options.trend_mode = trend_mode

        if working_days_per_month is not None and options.granularity == Granularity.MONTHLY:
            options.days_per_period = working_days_per_month

        # 週模式：設定 selected_weeks
        # 有值時改用日數據計算，days_per_period 在 _calculate_safety_stock 中覆寫為 1
        if selected_weeks and options.granularity == Granularity.WEEKLY:
            options.selected_weeks = selected_weeks.copy()

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
        logger.info(f" 彙總了 {len(aggregated)} 個 SKU")

        # Step 3: Calculate statistics
        logger.info("步驟 3: 計算統計數據")
        logger.info(f"  粒度: {request.options.granularity.value}")
        if request.options.enable_moving_average:
            logger.info(f" 啟用 {request.options.ma_window} 期移動平均")
        items_with_stats = self._calculate_statistics(aggregated, request.options)
        logger.info(f" 計算了 {len(items_with_stats)} 個品項的統計")

        # Step 4: ABC Classification
        logger.info("步驟 4: 執行 ABC 分類")
        self._perform_abc_classification(items_with_stats, request.options)

        # Step 5: Calculate Safety Stock
        logger.info("步驟 5: 計算安全庫存")
        results, excluded = self._calculate_safety_stock(
            items_with_stats, request.options, request.material_master
        )
        logger.info(f" 計算成功: {len(results)} 個")
        logger.info(f" 排除項目: {len(excluded)} 個")

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

        # Vectorized validation (avoid iterrows for performance)
        sku_series = df["sku"]
        empty_sku_mask = sku_series.isna() | (sku_series.astype(str).str.strip() == "")
        if empty_sku_mask.any():
            for idx in df.index[empty_sku_mask][:10]:
                errors.append(f"第 {idx} 列: SKU 為空")

        qty_numeric = pd.to_numeric(df["quantity"], errors="coerce")
        invalid_qty_mask = qty_numeric.isna() & ~df["quantity"].isna()
        if invalid_qty_mask.any():
            for idx in df.index[invalid_qty_mask][:10]:
                errors.append(f"第 {idx} 列: 數量格式無效 ({df.at[idx, 'quantity']})")

        negative_qty_count = int((qty_numeric.fillna(0) < 0).sum())
        if negative_qty_count > 0:
            logger.info(f"  ℹ 偵測到 {negative_qty_count} 筆負數量（退貨），將在聚合時自動沖抵")

        ym_series = df["year_month"]
        empty_ym_mask = ym_series.isna()
        if empty_ym_mask.any():
            for idx in df.index[empty_ym_mask][:10]:
                errors.append(f"第 {idx} 列: year_month 為空")

        valid_ym = ym_series.dropna()
        bad_format_mask = ~valid_ym.astype(str).str.contains("-", na=False)
        if bad_format_mask.any():
            for idx in valid_ym.index[bad_format_mask][:10]:
                errors.append(f"第 {idx} 列: year_month 格式無效 ({df.at[idx, 'year_month']}),應為 'YYYY-MM'")

        if errors:
            error_summary = "\n".join(errors[:10])
            if len(errors) > 10:
                error_summary += f"\n... 還有 {len(errors) - 10} 個錯誤"
            raise ValueError(f"資料驗證失敗:\n{error_summary}")

        logger.info(f" 驗證通過: {len(df)} 筆記錄")

    @staticmethod
    def _get_period_key(row: pd.Series, granularity: Granularity) -> str | None:
        """Return the appropriate time-period key based on granularity."""
        if granularity == Granularity.DAILY:
            return row.get("date_str") or None
        elif granularity == Granularity.WEEKLY:
            return row.get("year_week") or None
        else:
            return row.get("year_month") or None

    def _aggregate_data(self, request: CalculationRequest) -> dict[str, dict[str, Any]]:
        """Aggregate sales data by site+SKU, building period timelines."""
        df = request.sales_data.df
        price_map = request.price_data or {}
        calc_mode = request.calc_mode
        target_site = request.target_site
        granularity = request.options.granularity

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
                continue

            period_key = self._get_period_key(row, granularity)
            if not period_key:
                skipped_rows += 1
                continue

            qty = float(row.get("quantity", 0))

            composite_key = create_composite_key(site, sku, KEY_DELIMITER)

            if composite_key not in aggregated_data:
                aggregated_data[composite_key] = self._initialize_aggregated_item(
                    row, site, sku, price_map
                )

            timeline = aggregated_data[composite_key]["timeline"]
            timeline[period_key] = timeline.get(period_key, 0.0) + qty

            # 額外記錄日粒度資料（供週模式的日數據計算使用）
            date_str = row.get("date_str")
            if date_str:
                daily_tl = aggregated_data[composite_key].setdefault("daily_timeline", {})
                daily_tl[date_str] = daily_tl.get(date_str, 0.0) + qty

        if skipped_rows > 0:
            logger.info(f"  ℹ 跳過 {skipped_rows} 筆無效資料")

        for _comp_key, item in aggregated_data.items():
            tl = item["timeline"]
            for period_key in list(tl.keys()):
                if tl[period_key] < 0:
                    logger.warning(
                        f"SKU {item.get('sku','')} @ {item.get('site','')} "
                        f"期間 {period_key} 淨需求為負 ({tl[period_key]:.1f})，歸零處理"
                    )
                    tl[period_key] = 0.0

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

    # ========================================================================
    # Period fill helpers (daily / weekly / monthly)
    # ========================================================================

    @staticmethod
    def _parse_period_key(key: str, granularity: Granularity) -> datetime | None:
        """Parse a period key string back to a datetime."""
        try:
            if granularity == Granularity.DAILY:
                return datetime.strptime(key, "%Y-%m-%d")
            elif granularity == Granularity.WEEKLY:
                return datetime.strptime(key + "-1", "%G-W%V-%u")
            else:
                return datetime.strptime(key, "%Y-%m")
        except ValueError:
            return None

    @staticmethod
    def _format_period_key(dt: datetime, granularity: Granularity) -> str:
        """Format a datetime into a period key string."""
        if granularity == Granularity.DAILY:
            return dt.strftime("%Y-%m-%d")
        elif granularity == Granularity.WEEKLY:
            iso = dt.isocalendar()
            return f"{iso[0]}-W{iso[1]:02d}"
        else:
            return f"{dt.year}-{dt.month:02d}"

    @staticmethod
    def _period_step(granularity: Granularity):
        """Return the time increment for one period."""
        if granularity == Granularity.DAILY:
            return timedelta(days=1)
        elif granularity == Granularity.WEEKLY:
            return timedelta(weeks=1)
        else:
            return None  # monthly uses relativedelta

    @staticmethod
    def _month_of_period(dt: datetime, granularity: Granularity) -> int:
        """Determine which month a period belongs to (for selected_months filter).
        For weekly: use ISO convention — the month of Thursday decides."""
        if granularity == Granularity.WEEKLY:
            thursday = dt + timedelta(days=(3 - dt.weekday()))
            return thursday.month
        return dt.month

    def _is_period_complete(
            self, dt: datetime, granularity: Granularity, max_date: datetime
    ) -> bool:
        """Check if a period is complete based on max_date."""
        if granularity == Granularity.DAILY:
            return True
        elif granularity == Granularity.WEEKLY:
            week_sunday = dt + timedelta(days=(6 - dt.weekday()))
            return max_date >= week_sunday
        else:
            last_day = calendar.monthrange(dt.year, dt.month)[1]
            month_end = dt.replace(day=last_day)
            if max_date.year == dt.year and max_date.month == dt.month:
                return max_date.day >= last_day
            return max_date > month_end

    def _fill_missing_periods(
            self,
            timeline: dict[str, float],
            granularity: Granularity,
            selected_months: list[int],
            fill_value: float = 0.0,
            max_date: datetime | None = None,
            date_from: datetime | None = None,
            date_to: datetime | None = None,
    ) -> tuple[list[float], int, int, list[str]]:
        """
        Fill missing periods and return a complete time series.

        Supports daily, weekly, and monthly granularity.
        Excludes incomplete trailing periods based on max_date.

        Returns:
            (filled_values, missing_count, total_periods, period_keys)
        """
        if not timeline:
            return [], 0, 0, []

        sorted_keys = sorted(timeline.keys())
        start_dt = self._parse_period_key(sorted_keys[0], granularity)
        end_dt = self._parse_period_key(sorted_keys[-1], granularity)

        if start_dt is None or end_dt is None:
            logger.error(f"Period key parse failed: {sorted_keys[0]} / {sorted_keys[-1]}")
            vals = [timeline[k] for k in sorted_keys]
            return vals, 0, len(vals), sorted_keys

        # Apply user-specified date range override
        if date_from is not None and date_from > start_dt:
            start_dt = date_from
        if date_to is not None and date_to < end_dt:
            end_dt = date_to

        # Exclude incomplete trailing period
        if max_date is not None:
            end_key = sorted_keys[-1]
            end_period_dt = end_dt
            if not self._is_period_complete(end_period_dt, granularity, max_date):
                logger.info(
                    f"排除未完成期間: {end_key} "
                    f"(max_date={max_date.strftime('%Y-%m-%d')})"
                )
                if granularity == Granularity.MONTHLY:
                    end_dt = end_dt - relativedelta(months=1)
                elif granularity == Granularity.WEEKLY:
                    end_dt = end_dt - timedelta(weeks=1)
                else:
                    end_dt = end_dt - timedelta(days=1)

            # Also exclude incomplete leading period (weekly/daily)
            if granularity == Granularity.WEEKLY:
                start_weekday = start_dt.weekday()
                if start_weekday != 0:
                    start_dt = start_dt + timedelta(days=(7 - start_weekday))
                    logger.info(f"排除不完整首周，起始調整至: {start_dt.strftime('%Y-%m-%d')}")

        if end_dt < start_dt:
            logger.warning("排除不完整期間後無有效資料")
            return [], 0, 0, []

        # Generate all period keys in range
        all_keys: list[str] = []
        current = start_dt
        step = self._period_step(granularity)

        while current <= end_dt:
            month_of = self._month_of_period(current, granularity)
            if month_of in selected_months:
                key = self._format_period_key(current, granularity)
                all_keys.append(key)

            if step is not None:
                current = current + step
            else:
                current = current + relativedelta(months=1)

        # Fill values
        filled_values: list[float] = []
        missing_count = 0

        for key in all_keys:
            if key in timeline:
                filled_values.append(timeline[key])
            else:
                filled_values.append(fill_value)
                missing_count += 1

        return filled_values, missing_count, len(all_keys), all_keys

    @staticmethod
    def _build_daily_values_from_weeks(
            item: dict[str, Any],
            selected_weeks: list[str],
    ) -> tuple[list[float], float, int, list[str], int]:
        """將 selected_weeks 轉為日數據序列。

        Args:
            item: 彙總後的品項資料（含 daily_timeline）
            selected_weeks: 選定的週列表，例如 ["2025-W10", "2025-W11"]

        Returns:
            (daily_values, total_qty, active_days, period_keys, data_point_count)
        """
        daily_timeline = item.get("daily_timeline", {})
        daily_values: list[float] = []
        period_keys: list[str] = []

        for week_str in sorted(selected_weeks):
            # 解析 "2025-W10" → year=2025, week=10
            parts = week_str.split("-W")
            if len(parts) != 2:
                continue
            try:
                year = int(parts[0])
                week_num = int(parts[1])
            except ValueError:
                continue

            # ISO 週的週一到週日（7 天）
            monday = datetime.fromisocalendar(year, week_num, 1)
            for day_offset in range(7):
                day = monday + timedelta(days=day_offset)
                day_key = day.strftime("%Y-%m-%d")
                daily_values.append(daily_timeline.get(day_key, 0.0))
                period_keys.append(day_key)

        total_qty = sum(daily_values)
        active_days = sum(1 for v in daily_values if v > 0)
        data_point_count = len(daily_values)

        return daily_values, total_qty, active_days, period_keys, data_point_count

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

        # 當窗口 >= 樣本數時，仍使用 rolling 正常處理（不再替換為全域平均）
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
        """
        Calculate demand statistics for each item.

        v5.1.0:
        - Multi-granularity support (daily/weekly/monthly)
        - MAD outlier detection BEFORE moving average (correct order)
        - selectedMonths consistency for total_qty
        """
        items = []
        granularity = options.granularity
        is_weekly_daily = (
            granularity == Granularity.WEEKLY
            and options.selected_weeks is not None
            and len(options.selected_weeks) > 0
        )

        for _key, item in aggregated.items():
            # 週模式 + selected_weeks：改用日數據計算
            if is_weekly_daily:
                period_values, total_qty, active_periods, period_keys, data_point_count = (
                    self._build_daily_values_from_weeks(item, options.selected_weeks)
                )
                total_periods = data_point_count
            else:
                filled_values, missing_count, total_periods, period_keys = self._fill_missing_periods(
                    item["timeline"],
                    granularity,
                    options.selected_months,
                    fill_value=0.0,
                    max_date=options.max_date,
                    date_from=options.date_from,
                    date_to=options.date_to,
                )

                if missing_count > 0:
                    logger.debug(
                        f"{item['sku']}: 填補了 {missing_count} 個缺失期間 "
                        f"(完整期數={total_periods}, 粒度={granularity.value})"
                    )

                period_values = filled_values
                data_point_count = len(period_values)

                # total_qty: only sum periods within selected range (consistency fix)
                selected_keys = set(period_keys)
                total_qty = sum(
                    v for k, v in item["timeline"].items() if k in selected_keys
                )

                active_periods = sum(1 for v in period_values if v > 0)

            # Step 1: MAD outlier detection on RAW period values (before MA)
            # Uses non-zero values for median/MAD, applies bounds to full series
            stats_raw = self._calculate_mad_statistics(period_values, options)
            outliers = stats_raw.outliers
            outliers_removed = 0

            # Step 2: Method B — replace outlier positions with 0, keep sequence length
            outlier_indices = {o.index for o in outliers}
            if outlier_indices:
                non_outlier_count = len(period_values) - len(outlier_indices)
                if non_outlier_count >= options.min_sample_size:
                    cleaned_values = [
                        0.0 if i in outlier_indices else v
                        for i, v in enumerate(period_values)
                    ]
                    outliers_removed = len(outlier_indices)
                    logger.debug(
                        f"{item['sku']}: {outliers_removed} 個離群值填回零 "
                        f"(序列長度保持 {len(cleaned_values)})"
                    )
                else:
                    cleaned_values = list(period_values)
            else:
                cleaned_values = list(period_values)

            # Step 3: Moving average on cleaned values (after outlier replacement)
            if options.enable_moving_average and len(cleaned_values) > 0:
                smoothed_values = self._apply_moving_average(
                    cleaned_values,
                    window=options.ma_window,
                    min_periods=options.ma_min_periods,
                )
            else:
                smoothed_values = cleaned_values

            # Step 4: Final mean/std from the processed series
            final_n = len(smoothed_values)
            if final_n == 0:
                mean_val = 0.0
                std_val = 0.0
            elif final_n == 1:
                mean_val = smoothed_values[0]
                std_val = 0.0
            else:
                mean_val = sum(smoothed_values) / final_n
                variance = sum((v - mean_val) ** 2 for v in smoothed_values) / (final_n - 1)
                std_val = math.sqrt(variance)

            # 數據不足警告（週模式日數據）
            data_point_warning: str | None = None
            if is_weekly_daily:
                if data_point_count < 7:
                    data_point_warning = f"分析數據僅 {data_point_count} 天，統計可靠性低，建議選擇更多週"
                elif data_point_count < 14:
                    data_point_warning = f"分析數據 {data_point_count} 天，結果僅供短期參考"

            # Trend detection
            trend_pct, trend_label = self._calculate_trend(
                period_values, options.trend_mode, options.selected_months, period_keys,
            )

            # 需求型態分類（Syntetos-Boylan）—— 僅月粒度，用原始非零值（MAD/MA 前）
            # ADI 分母：有明確 date range 時用「報告窗口期數」，否則用 SKU 首末區間
            # （避免寬窗口下零星品被誤判為穩定品）
            if options.date_from is not None and options.date_to is not None:
                window_periods = self._count_window_periods(
                    options.date_from, options.date_to,
                    options.selected_months, options.max_date,
                )
                denom_periods = window_periods if window_periods > 0 else total_periods
            else:
                denom_periods = total_periods
            demand_pattern, adi_val, cv2_val = self._compute_demand_pattern(
                period_values, denom_periods, granularity, is_weekly_daily
            )

            items.append({
                **item,
                "monthly_values": period_values,
                "data_point_count": data_point_count,
                "data_point_warning": data_point_warning,
                "smoothed_values": smoothed_values,
                "active_months": active_periods,
                "total_months": total_periods,
                "total_qty": total_qty,
                "total_value": total_qty * item["price"],
                "mean": mean_val,
                "std_dev": std_val,
                "outliers": outliers,
                "outliers_removed": outliers_removed,
                "has_insufficient_samples": final_n < options.min_confidence_samples,
                "demand_pattern": demand_pattern,
                "adi": adi_val,
                "cv_squared": cv2_val,
                "trend_pct": trend_pct,
                "trend_label": trend_label,
            })

        return items

    @staticmethod
    def _count_window_periods(
            date_from: datetime,
            date_to: datetime,
            selected_months: list[int],
            max_date: datetime | None,
    ) -> int:
        """計算月報告窗口 [date_from, date_to] 內、月份屬 selected_months 的月數。

        用於需求型態 ADI 分母：當使用者明確指定 date range 時，分母應反映
        「使用者選的報告窗口」而非該 SKU 首末出貨區間（_fill_missing_periods
        的 date range 只能縮小、不能放大 SKU 區間，會在寬窗口下讓零星品誤判為
        穩定品）。尾端以 max_date 裁切，避免把未來空月算進分母。
        """
        end = date_to
        if max_date is not None and max_date < end:
            end = max_date
        count = 0
        current = datetime(date_from.year, date_from.month, 1)
        end_marker = datetime(end.year, end.month, 1)
        while current <= end_marker:
            if current.month in selected_months:
                count += 1
            current = current + relativedelta(months=1)
        return count

    @staticmethod
    def _compute_demand_pattern(
            period_values: list[float],
            denom_periods: int,
            granularity: Granularity,
            is_weekly_daily: bool,
    ) -> tuple[str, float | None, float | None]:
        """計算 Syntetos-Boylan 需求型態（僅月粒度）。

        用原始非零期值（MAD/MA 之前）計算 CV²，與離線分析一致。
        denom_periods 為 ADI 分母：呼叫端在有 date range 時傳「報告窗口期數」，
        否則傳 total_periods（SKU 首末區間）。型態會隨使用者篩選範圍變動。

        Returns:
            (demand_pattern, adi, cv_squared)
            非月粒度或樣本不足時回傳 ("—", None, None)
        """
        # 僅月粒度計算（週/日的 ADI 語意不同，本期不做）
        if granularity != Granularity.MONTHLY or is_weekly_daily:
            return "—", None, None

        nonzero = [v for v in period_values if v > 0]
        n_demand = len(nonzero)

        # 需至少 2 個非零期才能算 CV²（std 需 n>=2），且分母不可為零
        if n_demand < 2 or denom_periods <= 0:
            return "—", None, None

        adi = denom_periods / n_demand
        mean_nz = sum(nonzero) / n_demand
        if mean_nz <= 0:
            return "—", None, None
        variance_nz = sum((v - mean_nz) ** 2 for v in nonzero) / (n_demand - 1)
        cv_squared = (math.sqrt(variance_nz) / mean_nz) ** 2

        return _classify_demand_pattern(adi, cv_squared), adi, cv_squared

    @staticmethod
    def _compute_median(sorted_vals: list[float]) -> float:
        """Compute median from a pre-sorted list."""
        n = len(sorted_vals)
        mid = n // 2
        if n % 2 == 0:
            return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2
        return sorted_vals[mid]

    @staticmethod
    def _calculate_trend(
            values: list[float],
            mode: str,
            selected_months: list[int],
            period_keys: list[str],
    ) -> tuple[float | None, str]:
        """
        Calculate trend percentage.

        Returns (trend_pct, trend_label):
          trend_pct: float percentage or None
          trend_label: "+X%", "-X%", "New", "Discontinued", "—"

        Priority:
          1. all zero → "—"
          2. < 4 periods → "—"
          3. non-contiguous selectedMonths (short mode) → "—"
          4. first_half=0, second_half>0 → "New"
          5. first_half>0, second_half=0 → "Discontinued"
          6. normal → "+X%" / "-X%"
        """
        if mode == "none" or not values:
            return None, "—"

        if mode == "yoy":
            return SafetyStockCalculator._calculate_trend_yoy(values, period_keys)

        # --- Short-term trend ---

        # Rule 1: all zero
        if all(v == 0 for v in values):
            return None, "—"

        # Rule 2: < 4 periods
        if len(values) < 4:
            return None, "—"

        # Rule 3: non-contiguous selectedMonths
        if selected_months and len(selected_months) > 1:
            sorted_sm = sorted(selected_months)
            for i in range(1, len(sorted_sm)):
                if sorted_sm[i] - sorted_sm[i - 1] > 1:
                    # Exception: 11,12,1,2 is contiguous (wraps around year)
                    if not (sorted_sm[-1] == 12 and sorted_sm[0] == 1):
                        return None, "—"

        # Split into halves (odd length: drop middle)
        n = len(values)
        mid = n // 2
        first_half = values[:mid]
        second_half = values[mid + 1:] if n % 2 != 0 else values[mid:]

        first_avg = sum(first_half) / len(first_half) if first_half else 0
        second_avg = sum(second_half) / len(second_half) if second_half else 0

        # Rule 4: New (first=0, second>0)
        if first_avg == 0 and second_avg > 0:
            return None, "New"

        # Rule 5: Discontinued (first>0, second=0)
        if first_avg > 0 and second_avg == 0:
            return None, "Discontinued"

        # Rule 6: normal calculation
        if first_avg == 0:
            return None, "—"

        pct = ((second_avg - first_avg) / first_avg) * 100
        label = f"+{pct:.1f}%" if pct >= 0 else f"{pct:.1f}%"
        return round(pct, 1), label

    @staticmethod
    def _calculate_trend_yoy(
            values: list[float],
            period_keys: list[str],
    ) -> tuple[float | None, str]:
        """
        YoY: compare latest two years using only months that exist in both.
        """
        if not period_keys or len(period_keys) < 2:
            return None, "—"

        # Group values by year
        year_data: dict[int, dict[int, float]] = {}
        for key, val in zip(period_keys, values, strict=True):
            try:
                parts = key.split("-")
                year = int(parts[0])
                month = int(parts[1])
            except (ValueError, IndexError):
                continue
            if year not in year_data:
                year_data[year] = {}
            year_data[year][month] = year_data[year].get(month, 0) + val

        years = sorted(year_data.keys())
        if len(years) < 2:
            return None, "—"

        # Latest two years
        this_year = years[-1]
        last_year = years[-2]

        # Intersection of months
        common_months = set(year_data[this_year].keys()) & set(year_data[last_year].keys())
        if not common_months:
            return None, "—"

        last_avg = sum(year_data[last_year][m] for m in common_months) / len(common_months)
        this_avg = sum(year_data[this_year][m] for m in common_months) / len(common_months)

        if last_avg == 0 and this_avg > 0:
            return None, "New"
        if last_avg > 0 and this_avg == 0:
            return None, "Discontinued"
        if last_avg == 0:
            return None, "—"

        pct = ((this_avg - last_avg) / last_avg) * 100
        label = f"+{pct:.1f}%" if pct >= 0 else f"{pct:.1f}%"
        return round(pct, 1), label

    def _calculate_mad_statistics(
            self,
            values: list[float],
            options: CalculationOptions | None = None,
    ) -> StatisticsResult:
        """
        MAD-based outlier detection with zero-value exclusion (v5.1.0).

        Key design:
        - Median and MAD are computed from NON-ZERO values only,
          so zero-demand periods don't dilute the center estimate.
        - Outlier bounds are then applied to the FULL series,
          but zero values are never flagged as outliers (they are
          business-normal idle periods, not anomalies).
        - If non-zero count < 3 or MAD = 0, no outlier detection
          is performed.
        """
        if options is None:
            mad_constant = MAD_TO_SIGMA_CONSTANT
            mad_multiplier = 3
            outlier_enabled = True
        else:
            mad_constant = options.mad_constant
            mad_multiplier = options.mad_multiplier
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

        # Extract non-zero values for MAD calculation
        non_zero = [v for v in values if v > 0]

        # Not enough non-zero data or detection disabled → skip
        skip_detection = (
            not outlier_enabled
            or len(non_zero) < 3
        )

        outliers: list[OutlierInfo] = []

        if not skip_detection:
            sorted_nz = sorted(non_zero)
            median_nz = self._compute_median(sorted_nz)

            abs_devs = sorted(abs(v - median_nz) for v in non_zero)
            mad = self._compute_median(abs_devs)

            # MAD = 0 means 50%+ of non-zero values are identical → skip
            if mad > 0:
                sigma_eq = mad * mad_constant
                lower_bound = median_nz - mad_multiplier * sigma_eq
                upper_bound = median_nz + mad_multiplier * sigma_eq

                for idx, v in enumerate(values):
                    if v <= 0:
                        continue
                    if v > upper_bound:
                        outliers.append(OutlierInfo(
                            index=idx, value=v,
                            bound="upper", threshold=upper_bound,
                        ))
                    elif v < lower_bound:
                        outliers.append(OutlierInfo(
                            index=idx, value=v,
                            bound="lower", threshold=lower_bound,
                        ))

        # Mean and std are computed on the full series (caller decides
        # whether to remove outliers or replace them with zeros).
        n = len(values)
        mean = sum(values) / n
        std_dev = 0.0
        if n > 1:
            variance = sum((v - mean) ** 2 for v in values) / (n - 1)
            std_dev = math.sqrt(variance)

        return StatisticsResult(
            mean=mean,
            std_dev=std_dev,
            outliers=outliers,
            outliers_removed=len(outliers),
            final_sample_size=n,
        )

    def _perform_abc_classification(
            self,
            items: list[dict[str, Any]],
            options: CalculationOptions,
    ) -> None:
        """
        Perform ABC classification based on total value or quantity.

        v5.1.0:
        - Uses prev_cum_share to fix boundary classification
        - No-price items are marked is_price_missing=True and classified as C
        """
        if not items:
            return

        for item in items:
            item.setdefault("is_price_missing", False)

        if len(items) == 1:
            items[0]["abc_class"] = ABCClass.A
            items[0]["is_price_missing"] = items[0]["price"] <= 0
            return

        # Separate priced vs unpriced items
        priced = [i for i in items if i["price"] > 0]
        unpriced = [i for i in items if i["price"] <= 0]

        # Mark unpriced items
        for item in unpriced:
            item["is_price_missing"] = True

        if not priced:
            # All items lack price → classify entirely by quantity
            self._abc_classify_list(items, "total_qty", options)
            return

        # Priced items → classify by value
        self._abc_classify_list(priced, "total_value", options)

        # Unpriced items → classify independently by quantity (not stuck at C)
        if unpriced:
            self._abc_classify_list(unpriced, "total_qty", options)
            logger.info(
                f"ABC: {len(unpriced)} 品項無價格資料，按數量獨立分類 (is_price_missing)"
            )

        class_counts = {
            ABCClass.A: sum(1 for i in items if i["abc_class"] == ABCClass.A),
            ABCClass.B: sum(1 for i in items if i["abc_class"] == ABCClass.B),
            ABCClass.C: sum(1 for i in items if i["abc_class"] == ABCClass.C),
        }
        logger.debug(f"ABC 分類結果: A={class_counts[ABCClass.A]}, "
                     f"B={class_counts[ABCClass.B]}, C={class_counts[ABCClass.C]}")

    def _abc_classify_list(
            self,
            items: list[dict[str, Any]],
            sort_key: str,
            options: CalculationOptions,
    ) -> None:
        """Classify a list of items using prev_cum_share logic."""
        items.sort(key=lambda x: x[sort_key], reverse=True)
        total = sum(item[sort_key] for item in items)

        if total == 0:
            for item in items:
                item["abc_class"] = ABCClass.C
            return

        threshold_a = options.abc_thresholds["A"]
        threshold_b = options.abc_thresholds["B"]
        prev_cum_share = 0.0

        for item in items:
            if prev_cum_share < threshold_a:
                item["abc_class"] = ABCClass.A
            elif prev_cum_share < threshold_b:
                item["abc_class"] = ABCClass.B
            else:
                item["abc_class"] = ABCClass.C
            prev_cum_share += item[sort_key] / total

    @staticmethod
    def _resolve_lead_time(
            sku: str,
            options: CalculationOptions,
            material_master: dict[str, Any] | None,
    ) -> int:
        """Three-layer lead time lookup: group → category → default."""
        if not material_master:
            return options.lead_time_days

        mapping = material_master.get("mapping", {})
        group_id = mapping.get(sku)
        if not group_id:
            return options.lead_time_days

        if group_id in options.group_lead_times:
            return options.group_lead_times[group_id]

        category_id = group_id.split("-")[0] if "-" in group_id else group_id
        if category_id in options.category_lead_times:
            return options.category_lead_times[category_id]

        return options.lead_time_days

    def _calculate_safety_stock(
            self,
            items: list[dict[str, Any]],
            options: CalculationOptions,
            material_master: dict[str, Any] | None = None,
    ) -> tuple[list[CalculationResult], list[ExcludedItem]]:
        """
        Calculate safety stock for each item.

        v5.1.0:
        - Per-SKU lead time via material master category mapping
        - Multi-granularity: SS = Z * sigma * sqrt(LT / days_per_period)
        - (s,S) policy for Max: Max = ROP + lead_time_demand (when no EOQ)
        """
        results: list[CalculationResult] = []
        excluded: list[ExcludedItem] = []

        # 週模式 + selected_weeks：使用日數據，days_per_period = 1
        is_weekly_daily = (
            options.granularity == Granularity.WEEKLY
            and options.selected_weeks is not None
            and len(options.selected_weeks) > 0
        )
        days_per_period = 1 if is_weekly_daily else options.days_per_period
        period_label = options.granularity.value

        for item in items:
            if options.min_months > 0 and item["active_months"] < options.min_months:
                excluded.append(ExcludedItem(
                    site=item["site"],
                    sku=item["sku"],
                    name=item["name"],
                    active_months=item["active_months"],
                    total_qty=item["total_qty"],
                    reason=f"活躍期數不足 ({item['active_months']} < {options.min_months})",
                ))
                continue

            abc_class: ABCClass = item["abc_class"]
            applied_z = options.z_scores.get(abc_class.value, 1.65)

            mean_demand = item["mean"]
            std_dev = item["std_dev"]

            sku_lt = self._resolve_lead_time(item["sku"], options, material_master)
            lead_time_factor = math.sqrt(sku_lt / days_per_period)

            safety_stock = math.ceil(applied_z * std_dev * lead_time_factor)
            safety_stock_value = safety_stock * item["price"]

            coefficient_of_variation = std_dev / mean_demand if mean_demand > 0 else 0.0

            if mean_demand > 0:
                daily_demand = mean_demand / days_per_period
                lead_time_demand = daily_demand * sku_lt
                reorder_point = math.ceil(lead_time_demand + safety_stock)
            else:
                lead_time_demand = 0.0
                reorder_point = safety_stock

            if options.default_order_quantity > 0:
                max_inventory = math.ceil(reorder_point + options.default_order_quantity)
            else:
                max_inventory = math.ceil(reorder_point + lead_time_demand)

            if len(results) < 3:
                logger.debug(
                    f"SKU {item['sku']}: "
                    f"ABC={abc_class.value}, Z={applied_z:.2f}, "
                    f"mean={mean_demand:.2f}, std={std_dev:.2f}, "
                    f"CV={coefficient_of_variation:.3f}, SS={safety_stock}, "
                    f"ROP={reorder_point}, Max={max_inventory}, "
                    f"granularity={period_label}"
                )

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
                total_months=item.get("total_months", item["active_months"]),
                mean_demand=mean_demand,
                std_dev=std_dev,
                coefficient_of_variation=coefficient_of_variation,
                reorder_point=reorder_point,
                max_inventory=max_inventory,
                lead_time_days=sku_lt,
                safety_stock=safety_stock,
                safety_stock_value=safety_stock_value,
                applied_z_score=applied_z,
                current_stock=item["stock"],
                status=status,
                outliers=item["outliers"],
                outliers_removed=item["outliers_removed"],
                has_insufficient_samples=item["has_insufficient_samples"],
                trend_pct=item.get("trend_pct"),
                trend_label=item.get("trend_label", "—"),
                is_price_missing=item.get("is_price_missing", False),
                monthly_values=item["monthly_values"],
                price=item["price"],
                data_point_count=item.get("data_point_count", 0),
                data_point_warning=item.get("data_point_warning"),
                demand_pattern=item.get("demand_pattern", "—"),
                adi=item.get("adi"),
                cv_squared=item.get("cv_squared"),
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

            # 總倉模式：site="總倉"，plan 中沒有此 site
            # 需要加總各倉的庫存數量
            if not plan_item and result.site == "總倉":
                total_stock = 0.0
                found = False
                for item in plan_data.items.values():
                    if item.sku == result.sku:
                        total_stock += item.current_stock
                        found = True
                if found:
                    result.has_plan = True
                    result.plan_stock = total_stock
                    result.current_stock = total_stock
                    # 周轉率 = 銷貨總數 / 庫存加總
                    if total_stock > 0 and result.total_qty >= 0:
                        result.turnover_rate = round(result.total_qty / total_stock, 2)
                    # 覆蓋天數 = 庫存加總 / 日均需求
                    daily_demand = result.mean_demand / options.days_per_period if options.days_per_period > 0 else 0
                    if daily_demand > 0 and total_stock > 0:
                        result.coverage_days = round(total_stock / daily_demand, 1)
                    integrated_count += 1
                else:
                    result.has_plan = False
                continue

            if not plan_item:
                result.has_plan = False
                continue

            result.has_plan = True
            result.plan_stock = plan_item.current_stock
            # 同步填入 current_stock，讓 Excel 匯出、JSON 匯出、前端顯示都能正確取值
            # 此時 SS/ROP/Max 已經算完（_integrate_plan_data 在 _calculate_safety_stock 之後執行），
            # 且 plan 模式的庫存狀態由 _determine_stock_health_with_plan 決定，不讀 current_stock，
            # 所以這裡覆寫 current_stock 不影響任何計算
            result.current_stock = plan_item.current_stock

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

            # 周轉率 = 銷貨總數 / 庫存數量
            # 只在庫存 > 0 時計算，避免除以零
            # 負數庫存視為無效，不計算
            if plan_item.current_stock > 0 and result.total_qty >= 0:
                result.turnover_rate = round(result.total_qty / plan_item.current_stock, 2)

            # 覆蓋天數 = 現有庫存 / 日均需求
            # 表示以目前庫存，按平均日需求可以撐幾天
            daily_demand = result.mean_demand / options.days_per_period if options.days_per_period > 0 else 0
            if daily_demand > 0 and plan_item.current_stock > 0:
                result.coverage_days = round(plan_item.current_stock / daily_demand, 1)

            integrated_count += 1

        logger.info(f" 整合了 {integrated_count} 個品項的庫存計畫")

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
