"""
Data Models for Safety Stock Automation System.
安全庫存系統資料模型

This module contains all shared data classes used across the system.
This prevents circular import issues between calculator and data_loader.

所有數據模型的中心模組，用於避免循環導入問題。

Version: 4.2.0
Author: 松鼠
Last Updated: 2025-01-14

Exports:
    - StockStatus: 庫存健康狀態枚舉
    - ABCClass: ABC 分類枚舉
    - MonthlyPlanData: 單月計劃資料
    - PlanItemData: 單一料號的完整計劃
    - PlanData: 完整的庫存計劃資料集
    - SalesData: 銷貨資料容器
    - PriceData: 價格資料容器
    - KEY_DELIMITER: 複合鍵分隔符
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

# ============================================================================
# Constants
# ============================================================================

KEY_DELIMITER = "|||"
"""複合鍵分隔符，用於組合 site 和 SKU"""


# ============================================================================
# Enums
# ============================================================================


class StockStatus(Enum):
    """
    Stock health status indicators.
    庫存健康狀態枚舉

    Attributes:
        RED: 缺貨風險 - 庫存低於安全庫存
        GREEN: 健康 - 庫存在安全範圍內
        BLUE: 呆滯風險 - 庫存超過安全庫存 3 倍
        GRAY: 無資料 - 無庫存資料或無需求
    """
    RED = "red"
    GREEN = "green"
    BLUE = "blue"
    GRAY = "gray"


class ABCClass(Enum):
    """
    ABC classification categories.
    ABC 分類枚舉

    Attributes:
        A: 高價值品項 (累積價值前 80%)
        B: 中價值品項 (累積價值 80-95%)
        C: 低價值品項 (累積價值後 5%)
    """
    A = "A"
    B = "B"
    C = "C"


# ============================================================================
# 庫存計劃資料結構
# ============================================================================


@dataclass
class MonthlyPlanData:
    """
    Single month plan data.
    單月計劃資料

    包含該月的需求、供給、調撥等資訊，以及計算後的期末庫存。

    Attributes:
        month: 月份 (YYYYMM 格式，例如 "202512")
        demand: 實際需求
        supply: 實際供給
        transfer_in: 調撥入庫
        transfer_out: 調撥出庫
        independent_demand: 獨立需求
        net_change: 淨變動 (自動計算)
        ending_stock: 期末庫存 (需外部設定)

    Note:
        net_change 在 __post_init__ 中自動計算
        ending_stock 需要透過 PlanItemData.calculate_monthly_stocks() 設定
    """
    month: str
    demand: float = 0.0
    supply: float = 0.0
    transfer_in: float = 0.0
    transfer_out: float = 0.0
    independent_demand: float = 0.0
    net_change: float = 0.0
    ending_stock: float = 0.0

    def __post_init__(self) -> None:
        """
        Initialize and calculate net change.
        初始化後自動計算淨變動

        Formula:
            net_change = supply + transfer_in - demand - transfer_out - independent_demand
        """
        self.net_change = (
                self.supply +
                self.transfer_in -
                self.demand -
                self.transfer_out -
                self.independent_demand
        )


@dataclass
class PlanItemData:
    """
    Complete inventory plan for a single SKU at a specific site.
    單一料號在特定出貨點的完整庫存計劃

    Attributes:
        site: 出貨點/倉別代碼
        sku: 料號
        current_stock: 現有庫存
        months: 各月計劃資料 (key: YYYYMM, value: MonthlyPlanData)

    Methods:
        get_final_stock: 取得最終預測庫存
        get_min_stock_month: 取得最低庫存及其發生月份
        calculate_monthly_stocks: 計算各月期末庫存

    Example:
        >>> item = PlanItemData(site="1002", sku="A001", current_stock=100)
        >>> item.months["202512"] = MonthlyPlanData(month="202512", demand=50, supply=30)
        >>> item.calculate_monthly_stocks()
        >>> print(item.get_final_stock())
        80.0
    """
    site: str
    sku: str
    current_stock: float
    months: dict[str, MonthlyPlanData] = field(default_factory=dict)

    def get_final_stock(self) -> float:
        """
        Get projected final stock at end of plan period.
        取得計劃期末的最終預測庫存

        Returns:
            最後一個月的期末庫存，如果無計劃則返回現有庫存
        """
        if not self.months:
            return self.current_stock

        last_month = sorted(self.months.keys())[-1]
        return self.months[last_month].ending_stock

    def get_min_stock_month(self) -> tuple[float, str | None]:
        """
        Get minimum stock level and the month it occurs.
        取得最低庫存水平及其發生月份

        Returns:
            Tuple of (minimum_stock, month_or_none)
            - minimum_stock: 最低庫存量
            - month_or_none: 發生月份 (YYYYMM) 或 None (如果最低點是現有庫存)

        Example:
            >>> min_stock, min_month = item.get_min_stock_month()
            >>> if min_month:
            ...     print(f"最低庫存 {min_stock} 發生在 {min_month}")
        """
        if not self.months:
            return self.current_stock, None

        min_stock = self.current_stock
        min_month: str | None = None

        for month, data in sorted(self.months.items()):
            if data.ending_stock < min_stock:
                min_stock = data.ending_stock
                min_month = month

        return min_stock, min_month

    def calculate_monthly_stocks(self) -> None:
        """
        Calculate ending stock for each month (rolling calculation).
        計算各月期末庫存 (滾動計算)

        This method updates the ending_stock field of each MonthlyPlanData
        based on current_stock and net_change.

        此方法會更新每個 MonthlyPlanData 的 ending_stock 欄位

        Example:
            >>> item.current_stock = 100
            >>> item.months["202501"] = MonthlyPlanData(month="202501", net_change=-20)
            >>> item.months["202502"] = MonthlyPlanData(month="202502", net_change=10)
            >>> item.calculate_monthly_stocks()
            >>> print(item.months["202501"].ending_stock)  # 100 - 20 = 80
            80.0
            >>> print(item.months["202502"].ending_stock)  # 80 + 10 = 90
            90.0
        """
        running_stock = self.current_stock

        for month in sorted(self.months.keys()):
            month_data = self.months[month]
            running_stock += month_data.net_change
            month_data.ending_stock = running_stock


@dataclass
class PlanData:
    """
    Complete inventory plan dataset for all SKUs.
    完整的庫存計劃資料集

    Attributes:
        items: 所有料號的計劃資料 (key: "site|||sku", value: PlanItemData)
        detected_months: 偵測到的月份列表 (已排序的 YYYYMM 列表)
        has_cumulative_columns: 是否包含累積欄位
        planning_horizon: 計劃涵蓋範圍，例如 "202604-202606"
        source_filename: 原始檔名（用於前端顯示）

    Methods:
        get_item: 根據 site 和 sku 取得計劃資料
        add_item: 添加料號計劃資料

    Example:
        >>> plan_data = PlanData()
        >>> plan_data.detected_months = ["202501", "202502", "202503"]
        >>> item = PlanItemData(site="1002", sku="A001", current_stock=100)
        >>> plan_data.add_item("1002", "A001", item)
        >>> retrieved = plan_data.get_item("1002", "A001")
        >>> print(retrieved.current_stock)
        100.0
    """
    items: dict[str, PlanItemData] = field(default_factory=dict)
    detected_months: list[str] = field(default_factory=list)
    has_cumulative_columns: bool = False
    planning_horizon: str | None = None
    source_filename: str | None = None

    def get_item(self, site: str, sku: str) -> PlanItemData | None:
        """
        Get plan data for a specific site and SKU.
        根據 site 和 sku 取得計劃資料

        Args:
            site: 出貨點代碼
            sku: 料號

        Returns:
            PlanItemData 或 None (如果不存在)
        """
        key = f"{site}{KEY_DELIMITER}{sku}"
        return self.items.get(key)

    def add_item(self, site: str, sku: str, item: PlanItemData) -> None:
        """
        Add plan data for a SKU.
        添加料號計劃資料

        Args:
            site: 出貨點代碼
            sku: 料號
            item: PlanItemData 物件
        """
        key = f"{site}{KEY_DELIMITER}{sku}"
        self.items[key] = item


# ============================================================================
# 資料載入相關
# ============================================================================


@dataclass
class SalesData:
    """
    Container for loaded sales data.
    銷貨資料容器

    Attributes:
        df: Pandas DataFrame 包含銷貨記錄
        available_sites: 可用的出貨點列表
        has_stock_data: 是否包含庫存資料
        has_price_data: 是否包含價格資料
        record_count: 記錄總數
        skipped_date_count: 跳過的無效日期記錄數

    Note:
        df 的必要欄位: site, sku, year_month, quantity
        可選欄位: name, price, stock
    """
    df: 'pd.DataFrame'
    available_sites: list[str]
    has_stock_data: bool
    has_price_data: bool
    record_count: int
    skipped_date_count: int = 0
    max_date: datetime | None = None


@dataclass
class PriceData:
    """
    Container for price mapping data.
    價格對照資料容器

    Attributes:
        price_map: SKU 到價格的映射 (key: sku, value: price)
        record_count: 價格記錄總數

    Example:
        >>> price_data = PriceData(
        ...     price_map={"A001": 100.0, "A002": 200.0},
        ...     record_count=2
        ... )
        >>> print(price_data.price_map["A001"])
        100.0
    """
    price_map: dict[str, float]
    record_count: int


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [
    # Constants
    'KEY_DELIMITER',

    # Enums
    'StockStatus',
    'ABCClass',

    # Plan Data
    'MonthlyPlanData',
    'PlanItemData',
    'PlanData',

    # Loader Data
    'SalesData',
    'PriceData',
]
