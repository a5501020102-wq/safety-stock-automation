"""
周轉率 (Turnover Rate) -- 單元測試

公式：turnover_rate = total_qty / current_stock
條件：
  - current_stock > 0 且 total_qty >= 0 時才計算
  - current_stock <= 0 → turnover_rate = None（不計算）
  - total_qty < 0 → turnover_rate = None（不計算）
  - 結果四捨五入到小數點後 2 位
"""
import pytest

from src.calculator import SafetyStockCalculator
from src.models import (
    PlanData,
    PlanItemData,
    SalesData,
)
from tests.conftest import (
    assert_close,
    build_mock_sales_df,
    build_monthly_records,
)


@pytest.fixture
def calc():
    return SafetyStockCalculator()


def _build_sales(sku: str = "SKU001", site: str = "1002",
                 monthly_values: list[float] | None = None) -> SalesData:
    """建立測試用銷貨資料。"""
    if monthly_values is None:
        monthly_values = [100, 120, 80, 110, 90, 100]
    records = build_monthly_records(
        sku=sku, monthly_values=monthly_values,
        start_year=2025, start_month=1, site=site,
    )
    df = build_mock_sales_df(records, site=site)
    return SalesData(
        df=df, available_sites=[site],
        has_stock_data=False, has_price_data=False,
        record_count=len(df),
    )


def _build_plan(site: str, sku: str, current_stock: float) -> PlanData:
    """建立只有 current_stock 的簡易 PlanData。"""
    plan = PlanData(detected_months=[], has_cumulative_columns=False)
    item = PlanItemData(site=site, sku=sku, current_stock=current_stock)
    plan.add_item(site, sku, item)
    return plan


class TestTurnoverRateNormal:
    """正常情境。"""

    def test_basic_calculation(self, calc):
        """total_qty=600, current_stock=200 → turnover_rate=3.0

        驗算：
          銷貨：[100, 120, 80, 110, 90, 100] → total=600
          庫存：200
          周轉率 = 600 / 200 = 3.0
        """
        sales = _build_sales()
        plan = _build_plan("1002", "SKU001", current_stock=200)

        results, _, _ = calc.calculate(
            sales_data=sales, plan_data=plan,
            granularity="monthly",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )
        r = next(r for r in results if r.sku == "SKU001")
        assert r.turnover_rate is not None
        assert_close(r.turnover_rate, 3.0, tolerance=0.01)

    def test_high_turnover(self, calc):
        """大銷量小庫存 → 高周轉率。

        驗算：
          total_qty=600, current_stock=10
          周轉率 = 600 / 10 = 60.0
        """
        sales = _build_sales()
        plan = _build_plan("1002", "SKU001", current_stock=10)

        results, _, _ = calc.calculate(
            sales_data=sales, plan_data=plan,
            granularity="monthly",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )
        r = next(r for r in results if r.sku == "SKU001")
        assert r.turnover_rate is not None
        assert_close(r.turnover_rate, 60.0, tolerance=0.01)

    def test_low_turnover(self, calc):
        """小銷量大庫存 → 低周轉率。

        驗算：
          total_qty=600, current_stock=10000
          周轉率 = 600 / 10000 = 0.06
        """
        sales = _build_sales()
        plan = _build_plan("1002", "SKU001", current_stock=10000)

        results, _, _ = calc.calculate(
            sales_data=sales, plan_data=plan,
            granularity="monthly",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )
        r = next(r for r in results if r.sku == "SKU001")
        assert r.turnover_rate is not None
        assert_close(r.turnover_rate, 0.06, tolerance=0.01)


class TestTurnoverRateZeroDivision:
    """分母為零的情境。"""

    def test_zero_stock(self, calc):
        """current_stock=0 → turnover_rate=None（不計算）。"""
        sales = _build_sales()
        plan = _build_plan("1002", "SKU001", current_stock=0)

        results, _, _ = calc.calculate(
            sales_data=sales, plan_data=plan,
            granularity="monthly",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )
        r = next(r for r in results if r.sku == "SKU001")
        assert r.turnover_rate is None

    def test_no_plan(self, calc):
        """不上傳 plan 報表 → turnover_rate=None。"""
        sales = _build_sales()

        results, _, _ = calc.calculate(
            sales_data=sales,
            granularity="monthly",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )
        r = next(r for r in results if r.sku == "SKU001")
        assert r.turnover_rate is None


class TestTurnoverRateNegative:
    """負數處理。"""

    def test_negative_stock(self, calc):
        """current_stock=-100 → turnover_rate=None（負庫存不計算）。"""
        sales = _build_sales()
        plan = _build_plan("1002", "SKU001", current_stock=-100)

        results, _, _ = calc.calculate(
            sales_data=sales, plan_data=plan,
            granularity="monthly",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )
        r = next(r for r in results if r.sku == "SKU001")
        assert r.turnover_rate is None

    def test_zero_sales_raises_error(self, calc):
        """全零銷量 → 空 DataFrame → calculate 拒絕空資料。

        這是正確行為：沒有銷貨紀錄就不該計算安全庫存。
        build_monthly_records 會跳過 qty=0，產出空 list → 空 DataFrame。
        """
        sales = _build_sales(monthly_values=[0, 0, 0, 0, 0, 0])
        plan = _build_plan("1002", "SKU001", current_stock=500)

        with pytest.raises(ValueError):
            calc.calculate(
                sales_data=sales, plan_data=plan,
                granularity="monthly",
                enable_outlier_detection=False,
                enable_moving_average=False,
            )


class TestTurnoverRateDataType:
    """資料型別驗證。"""

    def test_type_is_float_or_none(self, calc):
        """turnover_rate 應為 float 或 None。"""
        sales = _build_sales()
        plan = _build_plan("1002", "SKU001", current_stock=200)

        results, _, _ = calc.calculate(
            sales_data=sales, plan_data=plan,
            granularity="monthly",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )
        r = next(r for r in results if r.sku == "SKU001")
        assert isinstance(r.turnover_rate, (float, type(None)))

    def test_rounded_to_2_decimals(self, calc):
        """結果應四捨五入到 2 位小數。

        驗算：
          total_qty=600, current_stock=700
          600 / 700 = 0.857142... → 0.86
        """
        sales = _build_sales()
        plan = _build_plan("1002", "SKU001", current_stock=700)

        results, _, _ = calc.calculate(
            sales_data=sales, plan_data=plan,
            granularity="monthly",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )
        r = next(r for r in results if r.sku == "SKU001")
        assert r.turnover_rate is not None
        # 驗證小數點後不超過 2 位
        str_val = str(r.turnover_rate)
        if "." in str_val:
            decimal_places = len(str_val.split(".")[1])
            assert decimal_places <= 2
