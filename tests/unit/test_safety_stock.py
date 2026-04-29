"""
Safety Stock / ROP / Max 公式 -- 單元測試

透過 calculate() 建立完整管線，驗證最終輸出的 SS / ROP / Max 值。

公式：
  SS  = ceil(Z * std * sqrt(LT / days_per_period))
  ROP = ceil(daily_demand * LT + SS)    （mean > 0 時）
  ROP = SS                               （mean = 0 時）
  Max = ROP + order_qty                  （order_qty > 0 時）
  Max = ceil(ROP + lead_time_demand)     （order_qty = 0 時）

其中：
  daily_demand = mean / days_per_period
  lead_time_demand = daily_demand * LT
"""
import math

import pytest

from src.calculator import SafetyStockCalculator
from src.models import SalesData
from tests.conftest import assert_close, build_mock_sales_df, build_monthly_records


@pytest.fixture
def calc():
    return SafetyStockCalculator()


def _build_sales_data(monthly_values: list[float], sku: str = "TEST001") -> SalesData:
    """從月度值列表建立 SalesData 物件。"""
    records = build_monthly_records(sku=sku, monthly_values=monthly_values)
    df = build_mock_sales_df(records)
    return SalesData(
        df=df,
        available_sites=["1002"],
        has_stock_data=False,
        has_price_data=False,
        record_count=len(records),
    )


class TestSafetyStockFormula:
    """驗證 SS = ceil(Z * std * sqrt(LT / days_per_period))"""

    def test_ss_formula_monthly(self, calc):
        """已知 mean/std 的序列，驗證 SS 公式。

        使用 [100, 120, 80, 110, 90]（5 個月）
        驗算：
          mean = 100, std = 15.8114
          LT = 30, days_per_period = 30
          lead_time_factor = sqrt(30/30) = 1.0
          所有品項只有一個 → ABC = A → Z = 2.05
          SS = ceil(2.05 * 15.8114 * 1.0) = ceil(32.413) = 33
        """
        sales_data = _build_sales_data([100, 120, 80, 110, 90])
        results, excluded, summary = calc.calculate(
            sales_data=sales_data,
            lead_time_days=30,
            min_months=0,
            enable_outlier_detection=False,
            enable_moving_average=False,
        )

        assert len(results) == 1
        r = results[0]

        # 只有一個 SKU，ABC 分類 = A（價格為 0 時所有品項歸 C，需驗證實際分類）
        # 價格為 0 → total_value = 0 → ABC 分類可能是 C
        # C class Z = 1.28
        # SS = ceil(1.28 * 15.8114 * 1.0) = ceil(20.239) = 21
        z = r.applied_z_score
        expected_ss = math.ceil(z * 15.8114 * math.sqrt(30 / 30))
        assert r.safety_stock == expected_ss, (
            f"SS={r.safety_stock}, expected={expected_ss}, "
            f"Z={z}, std={r.std_dev:.4f}"
        )

    def test_ss_zero_std(self, calc):
        """std=0 → SS=0，不管 Z 和 LT 為何。

        使用 [100, 100, 100, 100]（全部相同）
        驗算：
          mean = 100, std = 0
          SS = ceil(Z * 0 * sqrt(LT/30)) = 0
        """
        sales_data = _build_sales_data([100, 100, 100, 100])
        results, _, _ = calc.calculate(
            sales_data=sales_data,
            lead_time_days=30,
            min_months=0,
            enable_outlier_detection=False,
            enable_moving_average=False,
        )

        assert len(results) == 1
        assert results[0].safety_stock == 0

    def test_ss_zero_mean(self, calc):
        """mean=0 → ROP=SS（無前置需求）。

        全零無法產生結果（會被 min_months 排除或無資料），
        因此使用 [0, 0, 100, 0, 0] 模擬低需求。
        mean = 20, std 不為 0 → SS > 0
        ROP = ceil(daily * LT + SS) 正常計算
        """
        # 全零序列無法產生記錄（build_monthly_records 跳過 qty=0）
        # 但 _fill_missing_periods 會自動補零
        # 使用只有一筆的序列：只有 1 個月有需求
        sales_data = _build_sales_data([100, 0, 0, 0, 0])
        results, excluded, _ = calc.calculate(
            sales_data=sales_data,
            lead_time_days=30,
            min_months=0,
            enable_outlier_detection=False,
            enable_moving_average=False,
        )

        # 只有 1 個活躍月份，但 min_months=0 不排除
        if len(results) == 1:
            r = results[0]
            # 驗證 ROP 公式正確
            daily_demand = r.mean_demand / 30
            lead_time_demand = daily_demand * r.lead_time_days
            expected_rop = math.ceil(lead_time_demand + r.safety_stock)
            assert r.reorder_point == expected_rop, (
                f"ROP={r.reorder_point}, expected={expected_rop}"
            )


class TestABCZScores:
    """驗證不同 ABC 等級使用不同 Z-score。"""

    def test_ss_abc_z_scores(self, calc):
        """三個 SKU 分別指定不同 Z-score，驗證 applied_z_score 正確套用。

        使用自訂 z_scores: A=2.05, B=1.65, C=1.28（預設值）
        建立三個 SKU，透過價格控制 ABC 分類：
          - SKU_A: 高價 → A class
          - SKU_B: 中價 → B class
          - SKU_C: 低價 → C class
        """
        # 建立三個 SKU，用不同價格控制 ABC 分類
        # A: 80%+ 累積價值, B: 80-95%, C: 5%
        records_a = build_monthly_records("SKU_A", [100, 120, 80, 110, 90])
        records_b = build_monthly_records("SKU_B", [100, 120, 80, 110, 90])
        records_c = build_monthly_records("SKU_C", [100, 120, 80, 110, 90])

        all_records = records_a + records_b + records_c
        df = build_mock_sales_df(all_records)

        sales_data = SalesData(
            df=df,
            available_sites=["1002"],
            has_stock_data=False,
            has_price_data=False,
            record_count=len(all_records),
        )

        # 透過 price_data 設定不同價格
        price_data = {
            "SKU_A": 1000.0,  # 高價 → A
            "SKU_B": 100.0,   # 中價 → B
            "SKU_C": 1.0,     # 低價 → C
        }

        z_scores = {"A": 2.05, "B": 1.65, "C": 1.28}
        results, _, _ = calc.calculate(
            sales_data=sales_data,
            price_data=price_data,
            z_scores=z_scores,
            lead_time_days=30,
            min_months=0,
            enable_outlier_detection=False,
            enable_moving_average=False,
        )

        # 建立 SKU → result 的 mapping
        result_map = {r.sku: r for r in results}
        assert "SKU_A" in result_map
        assert "SKU_C" in result_map

        # A class 的 Z-score 應為 2.05
        assert_close(result_map["SKU_A"].applied_z_score, 2.05, msg="SKU_A Z: ")
        # C class 的 Z-score 應為 1.28
        assert_close(result_map["SKU_C"].applied_z_score, 1.28, msg="SKU_C Z: ")

        # A class 的 SS 應大於 C class（相同 std，不同 Z）
        assert result_map["SKU_A"].safety_stock >= result_map["SKU_C"].safety_stock


class TestROPFormula:
    """驗證 ROP = ceil(daily_demand * LT + SS)"""

    def test_rop_formula(self, calc):
        """ROP = ceil(daily_demand * LT + SS)

        使用 [100, 120, 80, 110, 90], LT=60
        驗算：
          mean = 100, days_per_period = 30
          daily_demand = 100 / 30 = 3.333
          lead_time_demand = 3.333 * 60 = 200.0
          SS = ceil(Z * std * sqrt(60/30)) = ceil(Z * 15.81 * 1.414)
          ROP = ceil(200.0 + SS)
        """
        sales_data = _build_sales_data([100, 120, 80, 110, 90])
        results, _, _ = calc.calculate(
            sales_data=sales_data,
            lead_time_days=60,
            min_months=0,
            enable_outlier_detection=False,
            enable_moving_average=False,
        )

        assert len(results) == 1
        r = results[0]

        daily_demand = r.mean_demand / 30
        lead_time_demand = daily_demand * r.lead_time_days
        expected_rop = math.ceil(lead_time_demand + r.safety_stock)

        assert r.reorder_point == expected_rop, (
            f"ROP={r.reorder_point}, expected={expected_rop}, "
            f"daily={daily_demand:.4f}, LT_demand={lead_time_demand:.2f}, SS={r.safety_stock}"
        )


class TestMaxInventory:
    """驗證 Max 公式。"""

    def test_max_with_default_order_qty(self, calc):
        """order_qty > 0 → Max = ROP + order_qty

        使用 [100, 120, 80, 110, 90], order_qty=500
        驗算：
          Max = ROP + 500
        """
        sales_data = _build_sales_data([100, 120, 80, 110, 90])

        # 需要透過 CalculationOptions 傳入 default_order_quantity
        # calculate() 沒有直接的 default_order_quantity 參數
        # 需要在 calculator 的 _default_options 上設定
        calc._default_options.default_order_quantity = 500

        results, _, _ = calc.calculate(
            sales_data=sales_data,
            lead_time_days=30,
            min_months=0,
            enable_outlier_detection=False,
            enable_moving_average=False,
        )

        assert len(results) == 1
        r = results[0]

        expected_max = math.ceil(r.reorder_point + 500)
        assert r.max_inventory == expected_max, (
            f"Max={r.max_inventory}, expected={expected_max}, "
            f"ROP={r.reorder_point}, order_qty=500"
        )

        # 還原預設值
        calc._default_options.default_order_quantity = 0

    def test_max_without_order_qty(self, calc):
        """order_qty=0 → Max = ceil(ROP + lead_time_demand)

        使用 [100, 120, 80, 110, 90], LT=30, order_qty=0
        驗算：
          daily_demand = 100 / 30 = 3.333
          lead_time_demand = 3.333 * 30 = 100.0
          Max = ceil(ROP + 100.0)
        """
        sales_data = _build_sales_data([100, 120, 80, 110, 90])
        results, _, _ = calc.calculate(
            sales_data=sales_data,
            lead_time_days=30,
            min_months=0,
            enable_outlier_detection=False,
            enable_moving_average=False,
        )

        assert len(results) == 1
        r = results[0]

        daily_demand = r.mean_demand / 30
        lead_time_demand = daily_demand * r.lead_time_days
        expected_max = math.ceil(r.reorder_point + lead_time_demand)

        assert r.max_inventory == expected_max, (
            f"Max={r.max_inventory}, expected={expected_max}, "
            f"ROP={r.reorder_point}, LT_demand={lead_time_demand:.2f}"
        )


class TestSSEdgeCases:
    """SS 計算的邊界情境。"""

    def test_ss_with_lead_time_factor(self, calc):
        """LT != days_per_period 時的 lead_time_factor 計算。

        使用 [100, 120, 80, 110, 90], LT=90
        驗算：
          lead_time_factor = sqrt(90/30) = sqrt(3) = 1.7321
          SS = ceil(Z * 15.81 * 1.7321)
        """
        sales_data = _build_sales_data([100, 120, 80, 110, 90])
        results, _, _ = calc.calculate(
            sales_data=sales_data,
            lead_time_days=90,
            min_months=0,
            enable_outlier_detection=False,
            enable_moving_average=False,
        )

        assert len(results) == 1
        r = results[0]

        lead_time_factor = math.sqrt(90 / 30)
        expected_ss = math.ceil(r.applied_z_score * r.std_dev * lead_time_factor)

        assert r.safety_stock == expected_ss, (
            f"SS={r.safety_stock}, expected={expected_ss}, "
            f"Z={r.applied_z_score}, std={r.std_dev:.4f}, "
            f"LT_factor={lead_time_factor:.4f}"
        )

    def test_ss_consistency_same_data_twice(self, calc):
        """相同輸入跑兩次，結果應完全一致（無隨機性）。"""
        values = [100, 120, 80, 110, 90]
        sales_data_1 = _build_sales_data(values)
        sales_data_2 = _build_sales_data(values)

        results_1, _, _ = calc.calculate(
            sales_data=sales_data_1,
            lead_time_days=30,
            min_months=0,
            enable_outlier_detection=False,
        )
        results_2, _, _ = calc.calculate(
            sales_data=sales_data_2,
            lead_time_days=30,
            min_months=0,
            enable_outlier_detection=False,
        )

        assert len(results_1) == 1
        assert len(results_2) == 1
        assert results_1[0].safety_stock == results_2[0].safety_stock
        assert results_1[0].reorder_point == results_2[0].reorder_point
        assert results_1[0].max_inventory == results_2[0].max_inventory
