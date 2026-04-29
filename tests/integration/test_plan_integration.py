"""
Plan Integration -- 整合測試

測試 calculate() + plan_data 的完整管線：
1. 銷貨資料 + plan 報表同時輸入
2. _integrate_plan_data() 正確整合
3. CalculationResult 的 plan 欄位有正確值
4. 無 plan 時 plan 欄位為預設值
"""

import pytest

from src.calculator import SafetyStockCalculator
from src.models import (
    MonthlyPlanData,
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


def _build_simple_plan(site: str, sku: str, current_stock: float, months: dict) -> PlanData:
    """建立簡易 PlanData 用於測試。

    Args:
        months: {"202501": {"demand": 100, "supply": 50}, ...}
    """
    plan = PlanData(
        detected_months=sorted(months.keys()),
        has_cumulative_columns=False,
    )
    item = PlanItemData(site=site, sku=sku, current_stock=current_stock)
    for m, vals in months.items():
        item.months[m] = MonthlyPlanData(
            month=m,
            demand=vals.get("demand", 0),
            supply=vals.get("supply", 0),
            transfer_in=vals.get("transfer_in", 0),
            transfer_out=vals.get("transfer_out", 0),
            independent_demand=vals.get("independent_demand", 0),
        )
    plan.add_item(site, sku, item)
    return plan


def _build_test_sales_data(sku: str = "SKU001", site: str = "1002") -> SalesData:
    """建立 6 個月的穩定銷貨資料。"""
    records = build_monthly_records(
        sku=sku,
        monthly_values=[100, 120, 80, 110, 90, 100],
        start_year=2025,
        start_month=1,
        site=site,
    )
    df = build_mock_sales_df(records, site=site)
    return SalesData(
        df=df,
        available_sites=[site],
        has_stock_data=False,
        has_price_data=False,
        record_count=len(df),
    )


class TestPlanIntegrationBasic:
    """基本 plan 整合：銷貨 + plan 一起跑 calculate()。"""

    def test_plan_fields_populated(self, calc):
        """有 plan 時，CalculationResult 的 plan 欄位應有值。

        驗算：
          current_stock = 500
          month 202507: demand=100, supply=50 → net = 50 - 100 = -50
          running_stock = 500 + (-50) = 450
          SS = 已知（從銷貨算出）
          gap = 450 - SS
        """
        sales = _build_test_sales_data()
        plan = _build_simple_plan(
            site="1002", sku="SKU001", current_stock=500,
            months={"202507": {"demand": 100, "supply": 50}},
        )

        results, _, _ = calc.calculate(
            sales_data=sales,
            plan_data=plan,
            granularity="monthly",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )

        r = next((r for r in results if r.sku == "SKU001"), None)
        assert r is not None
        assert r.has_plan is True
        assert r.plan_stock == 500.0
        assert r.final_stock is not None
        assert r.suggested_order >= 0
        # 周轉率：total_qty=600, current_stock=500 → 1.2
        assert r.turnover_rate is not None
        assert isinstance(r.turnover_rate, float)

    def test_no_plan_fields_default(self, calc):
        """無 plan 時，plan 欄位應為預設值。"""
        sales = _build_test_sales_data()

        results, _, _ = calc.calculate(
            sales_data=sales,
            granularity="monthly",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )

        r = next((r for r in results if r.sku == "SKU001"), None)
        assert r is not None
        assert r.has_plan is False
        assert r.plan_stock is None
        assert r.suggested_order == 0

    def test_plan_sku_not_in_sales(self, calc):
        """plan 有但 sales 沒有的 SKU → has_plan=False（因為不在 results 中）。"""
        sales = _build_test_sales_data(sku="SKU001")
        plan = _build_simple_plan(
            site="1002", sku="SKU999", current_stock=1000,
            months={"202507": {"demand": 200}},
        )

        results, _, _ = calc.calculate(
            sales_data=sales,
            plan_data=plan,
            granularity="monthly",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )

        r = next((r for r in results if r.sku == "SKU001"), None)
        assert r is not None
        assert r.has_plan is False  # SKU001 在 plan 中找不到


class TestPlanIntegrationCalculation:
    """驗證 plan 整合後的計算正確性。"""

    def test_shortage_detection(self, calc):
        """庫存不足以支撐需求 → first_shortage_month 有值。

        驗算：
          current_stock = 50（很低）
          month 202507: demand=200, supply=0 → net = -200
          running_stock = 50 + (-200) = -150（低於任何 SS）
          → first_shortage_month = "202507"
        """
        sales = _build_test_sales_data()
        plan = _build_simple_plan(
            site="1002", sku="SKU001", current_stock=50,
            months={"202507": {"demand": 200}},
        )

        results, _, _ = calc.calculate(
            sales_data=sales,
            plan_data=plan,
            granularity="monthly",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )

        r = next(r for r in results if r.sku == "SKU001")
        assert r.has_plan is True
        assert r.first_shortage_month == "202507"
        assert r.suggested_order > 0

    def test_sufficient_stock_no_shortage(self, calc):
        """庫存充足 → first_shortage_month 為 None。

        驗算：
          current_stock = 10000（非常充足）
          month 202507: demand=100 → net = -100
          running_stock = 9900（遠高於 SS）
        """
        sales = _build_test_sales_data()
        plan = _build_simple_plan(
            site="1002", sku="SKU001", current_stock=10000,
            months={"202507": {"demand": 100}},
        )

        results, _, _ = calc.calculate(
            sales_data=sales,
            plan_data=plan,
            granularity="monthly",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )

        r = next(r for r in results if r.sku == "SKU001")
        assert r.has_plan is True
        assert r.first_shortage_month is None
        assert r.suggested_order == 0

    def test_multi_month_projection(self, calc):
        """多月投影：3 個月的 demand/supply → 逐月計算。

        驗算：
          current_stock = 500
          202507: demand=100, supply=50 → net=-50, running=450
          202508: demand=150, supply=0  → net=-150, running=300
          202509: demand=200, supply=100 → net=-100, running=200
          final_stock = 200
          min_stock = 200（最後一個月最低）
        """
        sales = _build_test_sales_data()
        plan = _build_simple_plan(
            site="1002", sku="SKU001", current_stock=500,
            months={
                "202507": {"demand": 100, "supply": 50},
                "202508": {"demand": 150, "supply": 0},
                "202509": {"demand": 200, "supply": 100},
            },
        )

        results, _, _ = calc.calculate(
            sales_data=sales,
            plan_data=plan,
            granularity="monthly",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )

        r = next(r for r in results if r.sku == "SKU001")
        assert r.has_plan is True
        assert_close(r.plan_stock, 500.0)
        assert_close(r.final_stock, 200.0, tolerance=1.0)
        assert len(r.monthly_plan) == 3

    def test_transfer_in_out_considered(self, calc):
        """調撥(入/出)應影響 net_change。

        驗算：
          demand=100, supply=0, transfer_in=80, transfer_out=30
          net = 0 + 80 - 100 - 30 = -50
        """
        sales = _build_test_sales_data()
        plan = _build_simple_plan(
            site="1002", sku="SKU001", current_stock=500,
            months={
                "202507": {
                    "demand": 100,
                    "supply": 0,
                    "transfer_in": 80,
                    "transfer_out": 30,
                },
            },
        )

        results, _, _ = calc.calculate(
            sales_data=sales,
            plan_data=plan,
            granularity="monthly",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )

        r = next(r for r in results if r.sku == "SKU001")
        assert r.has_plan is True
        # final_stock = 500 + (0 + 80 - 100 - 30) = 450
        assert_close(r.final_stock, 450.0, tolerance=1.0)


class TestPlanDoesNotAffectSSCalculation:
    """確認 plan 資料不影響 SS/ROP/Max 的計算。"""

    def test_ss_same_with_and_without_plan(self, calc):
        """同樣的銷貨資料，有無 plan 的 SS 應完全相同。"""
        sales = _build_test_sales_data()
        plan = _build_simple_plan(
            site="1002", sku="SKU001", current_stock=500,
            months={"202507": {"demand": 100}},
        )

        results_no_plan, _, _ = calc.calculate(
            sales_data=sales,
            granularity="monthly",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )
        results_with_plan, _, _ = calc.calculate(
            sales_data=sales,
            plan_data=plan,
            granularity="monthly",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )

        r_no = next(r for r in results_no_plan if r.sku == "SKU001")
        r_with = next(r for r in results_with_plan if r.sku == "SKU001")

        assert r_no.safety_stock == r_with.safety_stock
        assert r_no.reorder_point == r_with.reorder_point
        assert r_no.max_inventory == r_with.max_inventory
        assert r_no.mean_demand == r_with.mean_demand
        assert r_no.std_dev == r_with.std_dev
