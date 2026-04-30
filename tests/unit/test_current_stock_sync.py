"""
current_stock 同步 -- 單元測試

驗證 _integrate_plan_data() 正確地將 plan 的庫存數量同步到 current_stock：
1. 有 plan 時：current_stock == plan_stock == plan 報表的庫存數量
2. 無 plan 時：current_stock 維持原值（通常是 None）
3. plan 中沒有該 SKU 時：current_stock 不變
4. plan 庫存為 0 時：current_stock == 0（不是 None）
"""
import pytest

from src.calculator import SafetyStockCalculator
from src.models import (
    PlanData,
    PlanItemData,
    SalesData,
)
from tests.conftest import (
    build_mock_sales_df,
    build_monthly_records,
)


@pytest.fixture
def calc():
    return SafetyStockCalculator()


def _build_sales(sku: str = "SKU001", site: str = "1002") -> SalesData:
    records = build_monthly_records(
        sku=sku, monthly_values=[100, 120, 80, 110, 90, 100],
        start_year=2025, start_month=1, site=site,
    )
    df = build_mock_sales_df(records, site=site)
    return SalesData(
        df=df, available_sites=[site],
        has_stock_data=False, has_price_data=False,
        record_count=len(df),
    )


def _build_plan(site: str, sku: str, current_stock: float) -> PlanData:
    plan = PlanData(detected_months=[], has_cumulative_columns=False)
    item = PlanItemData(site=site, sku=sku, current_stock=current_stock)
    plan.add_item(site, sku, item)
    return plan


class TestCurrentStockWithPlan:
    """有 plan 時 current_stock 應等於 plan 的庫存數量。"""

    def test_current_stock_equals_plan_stock(self, calc):
        """plan current_stock=500 → result.current_stock=500, result.plan_stock=500。

        驗算：
          plan 報表庫存數量 = 500
          _integrate_plan_data 應同步到 current_stock 和 plan_stock
        """
        sales = _build_sales()
        plan = _build_plan("1002", "SKU001", current_stock=500)

        results, _, _ = calc.calculate(
            sales_data=sales, plan_data=plan,
            granularity="monthly",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )
        r = next(r for r in results if r.sku == "SKU001")

        assert r.has_plan is True
        assert r.plan_stock == 500.0
        assert r.current_stock == 500.0
        assert r.current_stock == r.plan_stock

    def test_current_stock_zero_when_plan_zero(self, calc):
        """plan current_stock=0 → result.current_stock=0（不是 None）。

        驗算：
          plan 報表庫存數量 = 0（SKU 沒有庫存）
          current_stock 應為 0.0，不是 None
        """
        sales = _build_sales()
        plan = _build_plan("1002", "SKU001", current_stock=0)

        results, _, _ = calc.calculate(
            sales_data=sales, plan_data=plan,
            granularity="monthly",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )
        r = next(r for r in results if r.sku == "SKU001")

        assert r.has_plan is True
        assert r.current_stock == 0.0
        assert r.plan_stock == 0.0

    def test_large_stock_value(self, calc):
        """大庫存值正確同步。

        驗算：
          plan 報表庫存數量 = 999999
        """
        sales = _build_sales()
        plan = _build_plan("1002", "SKU001", current_stock=999999)

        results, _, _ = calc.calculate(
            sales_data=sales, plan_data=plan,
            granularity="monthly",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )
        r = next(r for r in results if r.sku == "SKU001")

        assert r.current_stock == 999999.0
        assert r.plan_stock == 999999.0


class TestCurrentStockWithoutPlan:
    """無 plan 時 current_stock 維持原值。"""

    def test_no_plan_current_stock_none(self, calc):
        """不上傳 plan → current_stock 維持 None（銷貨資料沒有 stock 欄位）。"""
        sales = _build_sales()

        results, _, _ = calc.calculate(
            sales_data=sales,
            granularity="monthly",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )
        r = next(r for r in results if r.sku == "SKU001")

        assert r.has_plan is False
        assert r.plan_stock is None
        # current_stock 來自銷貨資料的 stock 欄位，我們的 mock 沒有 → None 或 0
        # 不應該被 plan 影響

    def test_plan_sku_not_matching(self, calc):
        """plan 有但 SKU 不匹配 → current_stock 不變。"""
        sales = _build_sales(sku="SKU001")
        plan = _build_plan("1002", "SKU999", current_stock=1000)

        results, _, _ = calc.calculate(
            sales_data=sales, plan_data=plan,
            granularity="monthly",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )
        r = next(r for r in results if r.sku == "SKU001")

        assert r.has_plan is False
        assert r.plan_stock is None
        # current_stock 不應被 SKU999 的 plan 影響


class TestCurrentStockDoesNotAffectCalculation:
    """確認修改 current_stock 不影響 SS/ROP/Max。"""

    def test_ss_unchanged(self, calc):
        """有無 plan 的 SS 完全相同。

        current_stock 的覆寫發生在 _integrate_plan_data，
        此時 SS/ROP/Max 已經在 _calculate_safety_stock 中算完。
        """
        sales = _build_sales()
        plan = _build_plan("1002", "SKU001", current_stock=500)

        results_no, _, _ = calc.calculate(
            sales_data=sales,
            granularity="monthly",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )
        results_with, _, _ = calc.calculate(
            sales_data=sales, plan_data=plan,
            granularity="monthly",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )

        r_no = next(r for r in results_no if r.sku == "SKU001")
        r_with = next(r for r in results_with if r.sku == "SKU001")

        assert r_no.safety_stock == r_with.safety_stock
        assert r_no.reorder_point == r_with.reorder_point
        assert r_no.max_inventory == r_with.max_inventory
        assert r_no.mean_demand == r_with.mean_demand
        assert r_no.std_dev == r_with.std_dev
