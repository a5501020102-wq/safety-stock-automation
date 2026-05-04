"""
週模式日數據計算 -- 單元測試 + 整合測試

測試週模式 + selected_weeks 的完整流程：
1. _build_daily_values_from_weeks() 日數據建立
2. 週模式 mean/std 用日數據計算
3. days_per_period = 1，SS = Z x sigma x sqrt(LT)
4. 數據不足警告
5. 月模式不受影響（regression）
"""
import math

import pytest

from src.calculator import SafetyStockCalculator
from src.models import SalesData
from tests.conftest import (
    assert_close,
    build_mock_sales_df,
)


@pytest.fixture
def calc():
    return SafetyStockCalculator()


def _build_daily_records(
    sku: str = "SKU001",
    site: str = "1002",
    daily_qtys: dict[str, float] | None = None,
) -> list[dict]:
    """建立日粒度的銷貨記錄。

    Args:
        daily_qtys: {"2025-03-03": 100, "2025-03-04": 200, ...}
    """
    if daily_qtys is None:
        daily_qtys = {}
    records = []
    for date_str, qty in daily_qtys.items():
        if qty > 0:
            records.append({"date": date_str, "sku": sku, "qty": qty, "site": site})
    return records


def _build_weekly_sales(records: list[dict], site: str = "1002") -> SalesData:
    """從記錄建立 SalesData。"""
    df = build_mock_sales_df(records, site=site)
    available_weeks = sorted(df["year_week"].dropna().unique().tolist()) if "year_week" in df.columns else []
    return SalesData(
        df=df,
        available_sites=[site],
        has_stock_data=False,
        has_price_data=False,
        record_count=len(df),
        available_weeks=available_weeks,
    )


class TestBuildDailyValuesFromWeeks:
    """_build_daily_values_from_weeks 日數據建立。"""

    def test_single_week_7_days(self, calc):
        """1 週 = 7 個日數據點。"""
        # 2025-W10: 2025-03-03 (Mon) ~ 2025-03-09 (Sun)
        records = _build_daily_records(daily_qtys={
            "2025-03-03": 100,
            "2025-03-05": 200,
            "2025-03-07": 150,
        })
        sales = _build_weekly_sales(records)

        results, _, _ = calc.calculate(
            sales_data=sales,
            granularity="weekly",
            selected_weeks=["2025-W10"],
            enable_outlier_detection=False,
            enable_moving_average=False,
            min_months=0,
        )

        r = next((r for r in results if r.sku == "SKU001"), None)
        assert r is not None
        assert r.data_point_count == 7
        # 日數據：[100, 0, 200, 0, 150, 0, 0]
        assert len(r.monthly_values) == 7

    def test_two_weeks_14_days(self, calc):
        """2 週 = 14 個日數據點。"""
        records = _build_daily_records(daily_qtys={
            "2025-03-03": 100,  # W10 Mon
            "2025-03-10": 200,  # W11 Mon
        })
        sales = _build_weekly_sales(records)

        results, _, _ = calc.calculate(
            sales_data=sales,
            granularity="weekly",
            selected_weeks=["2025-W10", "2025-W11"],
            enable_outlier_detection=False,
            enable_moving_average=False,
            min_months=0,
        )

        r = next((r for r in results if r.sku == "SKU001"), None)
        assert r is not None
        assert r.data_point_count == 14

    def test_no_sales_week_all_zeros(self, calc):
        """選到完全沒出貨的週，日數據全為 0。"""
        records = _build_daily_records(daily_qtys={
            "2025-03-03": 100,  # W10
        })
        sales = _build_weekly_sales(records)

        # 選 W11（沒有出貨）
        results, _, _ = calc.calculate(
            sales_data=sales,
            granularity="weekly",
            selected_weeks=["2025-W11"],
            enable_outlier_detection=False,
            enable_moving_average=False,
            min_months=0,
        )

        r = next((r for r in results if r.sku == "SKU001"), None)
        assert r is not None
        assert r.mean_demand == 0.0
        assert r.safety_stock == 0


class TestWeeklyDailyCalculation:
    """週模式日數據的 mean/std/SS 計算。"""

    def test_mean_std_from_daily(self, calc):
        """mean/std 用日數據計算。

        驗算：
          W10: Mon=100, Wed=200, Fri=150, 其餘=0
          daily = [100, 0, 200, 0, 150, 0, 0]
          mean = 450/7 = 64.2857
          std = sqrt(Σ(xi-mean)²/6) （手算）
        """
        records = _build_daily_records(daily_qtys={
            "2025-03-03": 100,
            "2025-03-05": 200,
            "2025-03-07": 150,
        })
        sales = _build_weekly_sales(records)

        results, _, _ = calc.calculate(
            sales_data=sales,
            granularity="weekly",
            selected_weeks=["2025-W10"],
            enable_outlier_detection=False,
            enable_moving_average=False,
            min_months=0,
        )

        r = next(r for r in results if r.sku == "SKU001")
        values = [100, 0, 200, 0, 150, 0, 0]
        manual_mean = sum(values) / 7
        manual_var = sum((v - manual_mean) ** 2 for v in values) / 6
        manual_std = math.sqrt(manual_var)

        assert_close(r.mean_demand, manual_mean, tolerance=0.01)
        assert_close(r.std_dev, manual_std, tolerance=0.01)

    def test_ss_uses_sqrt_lt(self, calc):
        """SS = ceil(Z x sigma x sqrt(LT))，days_per_period=1。

        驗算：
          mean=64.2857, std=手算, Z=1.28(C), LT=30
          SS = ceil(1.28 x std x sqrt(30))
        """
        records = _build_daily_records(daily_qtys={
            "2025-03-03": 100,
            "2025-03-05": 200,
            "2025-03-07": 150,
        })
        sales = _build_weekly_sales(records)

        results, _, _ = calc.calculate(
            sales_data=sales,
            granularity="weekly",
            selected_weeks=["2025-W10"],
            enable_outlier_detection=False,
            enable_moving_average=False,
            min_months=0,
        )

        r = next(r for r in results if r.sku == "SKU001")
        # days_per_period = 1 → factor = sqrt(LT/1) = sqrt(30)
        factor = math.sqrt(30)
        manual_ss = math.ceil(r.applied_z_score * r.std_dev * factor)
        assert r.safety_stock == manual_ss


class TestDataPointWarning:
    """數據不足警告。"""

    def test_warning_under_7_days(self, calc):
        """< 7 天強提示（但 1 週剛好 = 7 天，所以不觸發強提示）。"""
        # 這裡無法用少於 7 天，因為 1 週 = 7 天
        # 7 天觸發輕提示
        records = _build_daily_records(daily_qtys={"2025-03-03": 100})
        sales = _build_weekly_sales(records)

        results, _, _ = calc.calculate(
            sales_data=sales,
            granularity="weekly",
            selected_weeks=["2025-W10"],
            enable_outlier_detection=False,
            enable_moving_average=False,
            min_months=0,
        )

        r = next(r for r in results if r.sku == "SKU001")
        assert r.data_point_count == 7
        assert r.data_point_warning is not None
        assert "7 天" in r.data_point_warning

    def test_no_warning_14_days_plus(self, calc):
        """>= 14 天無警告。"""
        records = _build_daily_records(daily_qtys={
            "2025-03-03": 100,
            "2025-03-10": 200,
        })
        sales = _build_weekly_sales(records)

        results, _, _ = calc.calculate(
            sales_data=sales,
            granularity="weekly",
            selected_weeks=["2025-W10", "2025-W11"],
            enable_outlier_detection=False,
            enable_moving_average=False,
            min_months=0,
        )

        r = next(r for r in results if r.sku == "SKU001")
        assert r.data_point_count == 14
        assert r.data_point_warning is None


class TestMonthlyNotAffected:
    """月模式不受週模式改動影響（regression）。"""

    def test_monthly_same_result(self, calc):
        """同樣資料，月模式結果不因週模式改動而改變。"""
        from tests.conftest import build_monthly_records

        records = build_monthly_records(
            sku="SKU001",
            monthly_values=[100, 120, 80, 110, 90, 100],
            start_year=2025,
            start_month=1,
        )
        df = build_mock_sales_df(records)
        sales = SalesData(
            df=df,
            available_sites=["1002"],
            has_stock_data=False,
            has_price_data=False,
            record_count=len(df),
        )

        results, _, _ = calc.calculate(
            sales_data=sales,
            granularity="monthly",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )

        r = next(r for r in results if r.sku == "SKU001")
        # 月模式的 mean = (100+120+80+110+90+100)/6 = 100
        assert_close(r.mean_demand, 100.0, tolerance=0.01)
        # data_point_warning 應為 None（月模式不走週邏輯）
        assert r.data_point_warning is None
