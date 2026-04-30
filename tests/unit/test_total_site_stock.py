"""
總倉庫存加總 -- 單元測試

驗證 _integrate_plan_data() 在總倉模式下：
1. 加總各倉的 current_stock
2. 正確計算 turnover_rate
3. 不影響分倉結果
4. SS/ROP/Max 不受影響
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


def _build_multi_site_sales() -> SalesData:
    """建立 3 個 site 的銷貨資料，同一個 SKU。"""
    records = []
    for site in ["1002", "1003", "1004"]:
        records.extend(build_monthly_records(
            sku="SKU001",
            monthly_values=[100, 120, 80, 110, 90, 100],
            start_year=2025, start_month=1, site=site,
        ))
    df = build_mock_sales_df(records)
    return SalesData(
        df=df, available_sites=["1002", "1003", "1004"],
        has_stock_data=False, has_price_data=False,
        record_count=len(df),
    )


def _build_multi_site_plan(stocks: dict[str, float]) -> PlanData:
    """建立多 site 的 plan 資料。

    Args:
        stocks: {"1002": 100, "1003": 200, "1004": 300}
    """
    plan = PlanData(detected_months=[], has_cumulative_columns=False)
    for site, stock in stocks.items():
        item = PlanItemData(site=site, sku="SKU001", current_stock=stock)
        plan.add_item(site, "SKU001", item)
    return plan


class TestTotalSiteStockSummed:
    """總倉庫存應為各倉加總。"""

    def test_three_sites_summed(self, calc):
        """3 個 site 各有 100, 200, 300 → 總倉 = 600。

        驗算：
          1002: 100 + 1003: 200 + 1004: 300 = 600
        """
        sales = _build_multi_site_sales()
        plan = _build_multi_site_plan({"1002": 100, "1003": 200, "1004": 300})

        results, _, _ = calc.calculate(
            sales_data=sales, plan_data=plan,
            calc_mode="total",  # 總倉模式
            granularity="monthly",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )

        total_r = next((r for r in results if r.site == "總倉"), None)
        assert total_r is not None, "Should have a result with site='總倉'"
        assert total_r.has_plan is True
        assert_close(total_r.plan_stock, 600.0)
        assert_close(total_r.current_stock, 600.0)

    def test_partial_sites_in_plan(self, calc):
        """只有 2 個 site 在 plan 中 → 總倉 = 那 2 個的加總。

        驗算：
          1002: 100 + 1003: 200 = 300（1004 不在 plan 中）
        """
        sales = _build_multi_site_sales()
        plan = _build_multi_site_plan({"1002": 100, "1003": 200})

        results, _, _ = calc.calculate(
            sales_data=sales, plan_data=plan,
            calc_mode="total",
            granularity="monthly",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )

        total_r = next((r for r in results if r.site == "總倉"), None)
        assert total_r is not None
        assert total_r.has_plan is True
        assert_close(total_r.plan_stock, 300.0)
        assert_close(total_r.current_stock, 300.0)

    def test_all_zero_stock(self, calc):
        """3 個 site 庫存都是 0 → 總倉 = 0（不是 None）。"""
        sales = _build_multi_site_sales()
        plan = _build_multi_site_plan({"1002": 0, "1003": 0, "1004": 0})

        results, _, _ = calc.calculate(
            sales_data=sales, plan_data=plan,
            calc_mode="total",
            granularity="monthly",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )

        total_r = next((r for r in results if r.site == "總倉"), None)
        assert total_r is not None
        assert total_r.has_plan is True
        assert total_r.current_stock == 0.0
        assert total_r.plan_stock == 0.0


class TestTotalSiteTurnoverRate:
    """總倉的周轉率用加總庫存計算。"""

    def test_turnover_with_summed_stock(self, calc):
        """total_qty(總倉) / 加總庫存。

        驗算：
          每個 site 銷量 = 600，總倉合計 = 1800
          庫存：100 + 200 + 300 = 600
          周轉率 = 1800 / 600 = 3.0
        """
        sales = _build_multi_site_sales()
        plan = _build_multi_site_plan({"1002": 100, "1003": 200, "1004": 300})

        results, _, _ = calc.calculate(
            sales_data=sales, plan_data=plan,
            calc_mode="total",
            granularity="monthly",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )

        total_r = next((r for r in results if r.site == "總倉"), None)
        assert total_r is not None
        assert total_r.turnover_rate is not None
        assert_close(total_r.turnover_rate, 3.0, tolerance=0.01)

    def test_turnover_zero_stock(self, calc):
        """庫存加總 = 0 → turnover_rate = None。"""
        sales = _build_multi_site_sales()
        plan = _build_multi_site_plan({"1002": 0, "1003": 0, "1004": 0})

        results, _, _ = calc.calculate(
            sales_data=sales, plan_data=plan,
            calc_mode="total",
            granularity="monthly",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )

        total_r = next((r for r in results if r.site == "總倉"), None)
        assert total_r is not None
        assert total_r.turnover_rate is None


class TestTotalSiteNoMonthlyPlan:
    """總倉模式暫不計算月投影（Step B 再處理）。"""

    def test_no_monthly_plan(self, calc):
        """monthly_plan 應為空。"""
        sales = _build_multi_site_sales()
        plan = _build_multi_site_plan({"1002": 100, "1003": 200, "1004": 300})

        results, _, _ = calc.calculate(
            sales_data=sales, plan_data=plan,
            calc_mode="total",
            granularity="monthly",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )

        total_r = next((r for r in results if r.site == "總倉"), None)
        assert total_r is not None
        assert len(total_r.monthly_plan) == 0
        assert total_r.first_shortage_month is None
        assert total_r.suggested_order == 0


class TestTotalSiteDoesNotAffectSS:
    """總倉的 SS/ROP/Max 不受 plan 影響。"""

    def test_ss_unchanged(self, calc):
        """有無 plan 的 SS 完全相同。"""
        sales = _build_multi_site_sales()
        plan = _build_multi_site_plan({"1002": 100, "1003": 200, "1004": 300})

        results_no, _, _ = calc.calculate(
            sales_data=sales, calc_mode="total",
            granularity="monthly",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )
        results_with, _, _ = calc.calculate(
            sales_data=sales, plan_data=plan,
            calc_mode="total",
            granularity="monthly",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )

        r_no = next(r for r in results_no if r.site == "總倉")
        r_with = next(r for r in results_with if r.site == "總倉")

        assert r_no.safety_stock == r_with.safety_stock
        assert r_no.reorder_point == r_with.reorder_point
        assert r_no.max_inventory == r_with.max_inventory
