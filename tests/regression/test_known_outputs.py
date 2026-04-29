"""
已知輸出回歸測試 -- 使用真實 Excel 資料驗證

這些測試使用先前分析中經手動驗算確認的數值，
確保計算引擎的改動不會導致結果偏移。

標記 @pytest.mark.slow，因為需要載入真實 Excel 檔案。
若資料檔不存在則自動跳過。
"""
from pathlib import Path

import pytest

from src.calculator import SafetyStockCalculator
from tests.conftest import assert_close

# ============================================================================
# 資料路徑
# ============================================================================

SALES_FILE_170 = Path(__file__).parent.parent.parent.parent / "data" / "2025_170.xlsx"


# ============================================================================
# 回歸測試：2025_170 資料集
# ============================================================================


@pytest.mark.slow
class TestKnownOutputs170:
    """使用 2025_170 資料集的回歸測試。

    這些數值在 2026-04-28 經手動驗算確認。
    若計算引擎改動導致結果偏移，這些測試會立即捕捉。
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        """載入真實資料，若檔案不存在則跳過。"""
        if not SALES_FILE_170.exists():
            pytest.skip("真實資料檔 2025_170.xlsx 不存在，跳過回歸測試")
        from src.data_loader import load_sales_data
        self.sales_data = load_sales_data(str(SALES_FILE_170))
        self.calc = SafetyStockCalculator()

    # ----------------------------------------------------------------
    # 特定 SKU 的精確數值驗證
    # ----------------------------------------------------------------

    def test_regression_daily_1700602125000(self):
        """SKU 1700602125000 @ 1002，daily 模式，無 MAD/MA。

        驗算值（2026-04-28 手動確認）：
          mean = 1774.56
          std = 2125.55
          系統輸出與手動計算完全吻合。
        """
        results, _, _ = self.calc.calculate(
            sales_data=self.sales_data,
            granularity="daily",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )
        r = next(r for r in results if r.site == "1002" and r.sku == "1700602125000")
        assert_close(r.mean_demand, 1774.56, tolerance=1.0)
        assert_close(r.std_dev, 2125.55, tolerance=1.0)

    def test_regression_monthly_mad_ma_1700602125000(self):
        """SKU 1700602125000 @ 1002，monthly 模式，啟用 MAD + MA。

        驗算值（2026-04-28 手動確認）：
          mean = 51383.74（經 MA 平滑後）
          std = 7334.10
          outliers_removed = 0
        """
        results, _, _ = self.calc.calculate(
            sales_data=self.sales_data,
            granularity="monthly",
            enable_outlier_detection=True,
            enable_moving_average=True,
        )
        r = next(r for r in results if r.site == "1002" and r.sku == "1700602125000")
        assert_close(r.mean_demand, 51383.74, tolerance=1.0)
        assert_close(r.std_dev, 7334.10, tolerance=1.0)
        assert r.outliers_removed == 0

    # ----------------------------------------------------------------
    # 資料集層級的統計驗證
    # ----------------------------------------------------------------

    def test_regression_result_count(self):
        """monthly 模式的總 SKU 數應接近 998。"""
        results, excluded, _ = self.calc.calculate(
            sales_data=self.sales_data,
            granularity="monthly",
        )
        total = len(results) + len(excluded)
        assert 900 < total < 1100, f"預期約 998 個 SKU，得到 {total}"

    # ----------------------------------------------------------------
    # 公式不變式（invariant）驗證
    # ----------------------------------------------------------------

    def test_regression_no_negative_ss(self):
        """所有 SKU 的安全庫存不應為負數。

        SS = ceil(Z * std * sqrt(LT / days_per_period))
        所有因子 >= 0，結果必 >= 0。
        """
        results, _, _ = self.calc.calculate(
            sales_data=self.sales_data,
            granularity="monthly",
        )
        for r in results:
            assert r.safety_stock >= 0, (
                f"{r.site}/{r.sku} 安全庫存為負數: {r.safety_stock}"
            )

    def test_regression_rop_gte_ss(self):
        """ROP 必須 >= SS。

        ROP = ceil(daily_demand * LT + SS)
        daily_demand * LT >= 0，因此 ROP >= SS。
        """
        results, _, _ = self.calc.calculate(
            sales_data=self.sales_data,
            granularity="monthly",
        )
        for r in results:
            assert r.reorder_point >= r.safety_stock, (
                f"{r.site}/{r.sku}: ROP={r.reorder_point} < SS={r.safety_stock}"
            )

    def test_regression_max_gte_rop(self):
        """Max 必須 >= ROP。

        Max = ROP + order_qty（order_qty >= 0）
        或 Max = ceil(ROP + lead_time_demand)（lead_time_demand >= 0）
        兩種情況 Max 都 >= ROP。
        """
        results, _, _ = self.calc.calculate(
            sales_data=self.sales_data,
            granularity="monthly",
        )
        for r in results:
            assert r.max_inventory >= r.reorder_point, (
                f"{r.site}/{r.sku}: Max={r.max_inventory} < ROP={r.reorder_point}"
            )
