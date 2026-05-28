"""
需求型態分類 (Syntetos-Boylan) -- 單元測試

測試：
1. _classify_demand_pattern() 四象限切點
2. _compute_demand_pattern() 用非零值算 ADI/CV²
3. 邊界：非月粒度、樣本不足、全零（除零防護）
4. 整合：透過 calculate() 確認欄位流到 CalculationResult
"""
import pytest

from src.calculator import (
    Granularity,
    SafetyStockCalculator,
    _classify_demand_pattern,
)
from src.models import SalesData
from tests.conftest import assert_close, build_mock_sales_df, build_monthly_records


@pytest.fixture
def calc():
    return SafetyStockCalculator()


# ============================================================================
# _classify_demand_pattern 切點測試（ADI=1.32, CV²=0.49）
# ============================================================================

class TestClassifyThresholds:
    """四象限切點，含邊界值（>= 用於上界）。"""

    def test_smooth(self):
        # ADI < 1.32 且 CV² < 0.49
        assert _classify_demand_pattern(1.0, 0.1) == "smooth"
        assert _classify_demand_pattern(1.31, 0.48) == "smooth"

    def test_erratic(self):
        # ADI < 1.32 且 CV² >= 0.49
        assert _classify_demand_pattern(1.0, 0.49) == "erratic"
        assert _classify_demand_pattern(1.31, 2.0) == "erratic"

    def test_intermittent(self):
        # ADI >= 1.32 且 CV² < 0.49
        assert _classify_demand_pattern(1.32, 0.1) == "intermittent"
        assert _classify_demand_pattern(4.0, 0.48) == "intermittent"

    def test_lumpy(self):
        # ADI >= 1.32 且 CV² >= 0.49
        assert _classify_demand_pattern(1.32, 0.49) == "lumpy"
        assert _classify_demand_pattern(4.0, 2.0) == "lumpy"


# ============================================================================
# _compute_demand_pattern 計算測試（月粒度）
# ============================================================================

class TestComputeDemandPattern:
    """用合成序列驗證 ADI/CV² 計算與分類。"""

    def _compute(self, values, total_periods):
        return SafetyStockCalculator._compute_demand_pattern(
            values, total_periods, Granularity.MONTHLY, False
        )

    def test_smooth_series(self):
        """[100,120,80,110,90] 每月都有、量穩。

        驗算：nonzero=5, ADI=5/5=1.0
          mean=100, var=1000/4=250, std=15.81, CV²=0.025
          → smooth
        """
        pattern, adi, cv2 = self._compute([100, 120, 80, 110, 90], 5)
        assert pattern == "smooth"
        assert_close(adi, 1.0)
        assert_close(cv2, 0.025, tolerance=0.005)

    def test_intermittent_series(self):
        """[100,0,0,110,0,0,90,0,0] 不常出但量穩。

        驗算：nonzero=[100,110,90] n=3, total=9, ADI=3.0
          mean=100, var=200/2=100, std=10, CV²=0.01
          → intermittent
        """
        pattern, adi, cv2 = self._compute([100, 0, 0, 110, 0, 0, 90, 0, 0], 9)
        assert pattern == "intermittent"
        assert_close(adi, 3.0)
        assert_close(cv2, 0.01, tolerance=0.005)

    def test_lumpy_series(self):
        """[500,0,0,20,0,0,800,0,0] 不常出且量亂。

        驗算：nonzero=[500,20,800] n=3, total=9, ADI=3.0
          mean=440, var=309600/2=154800, std=393.4, CV²≈0.799
          → lumpy
        """
        pattern, adi, cv2 = self._compute([500, 0, 0, 20, 0, 0, 800, 0, 0], 9)
        assert pattern == "lumpy"
        assert_close(adi, 3.0)
        assert cv2 >= 0.49

    def test_erratic_series(self):
        """[100,800,50,900,30,1000] 頻繁但量亂。

        驗算：nonzero all 6, total=6, ADI=1.0
          mean=480, CV²≈0.94 → erratic
        """
        pattern, adi, cv2 = self._compute([100, 800, 50, 900, 30, 1000], 6)
        assert pattern == "erratic"
        assert_close(adi, 1.0)
        assert cv2 >= 0.49


# ============================================================================
# 邊界情境
# ============================================================================

class TestComputeEdgeCases:

    def test_non_monthly_returns_dash(self):
        """週/日粒度不計算，回傳 ('—', None, None)。"""
        for gran in (Granularity.WEEKLY, Granularity.DAILY):
            pattern, adi, cv2 = SafetyStockCalculator._compute_demand_pattern(
                [100, 120, 80, 110], 4, gran, False
            )
            assert pattern == "—"
            assert adi is None
            assert cv2 is None

    def test_weekly_daily_mode_returns_dash(self):
        """週模式日數據 (is_weekly_daily=True) 不計算。"""
        pattern, adi, cv2 = SafetyStockCalculator._compute_demand_pattern(
            [100, 120, 80, 110], 4, Granularity.MONTHLY, True
        )
        assert pattern == "—"
        assert adi is None
        assert cv2 is None

    def test_single_nonzero_insufficient(self):
        """只有 1 個非零期 → 無法算 CV²，回傳 ('—', None, None)。"""
        pattern, adi, cv2 = SafetyStockCalculator._compute_demand_pattern(
            [100, 0, 0], 3, Granularity.MONTHLY, False
        )
        assert pattern == "—"
        assert adi is None
        assert cv2 is None

    def test_all_zero_no_division_error(self):
        """全零序列 → n_demand=0，不可除零，回傳 ('—', None, None)。"""
        pattern, adi, cv2 = SafetyStockCalculator._compute_demand_pattern(
            [0, 0, 0], 3, Granularity.MONTHLY, False
        )
        assert pattern == "—"
        assert adi is None
        assert cv2 is None

    def test_empty_series(self):
        """空序列不崩潰。"""
        pattern, adi, cv2 = SafetyStockCalculator._compute_demand_pattern(
            [], 0, Granularity.MONTHLY, False
        )
        assert pattern == "—"


# ============================================================================
# 整合：透過 calculate() 確認欄位流到 CalculationResult
# ============================================================================

class TestPatternIntegration:

    def _sales(self, sku, monthly_values):
        records = build_monthly_records(sku=sku, monthly_values=monthly_values)
        df = build_mock_sales_df(records)
        return SalesData(
            df=df, available_sites=["1002"],
            has_stock_data=False, has_price_data=False,
            record_count=len(records),
        )

    def test_smooth_flows_to_result(self):
        """每月穩定序列 → result.demand_pattern == 'smooth'，adi/cv² 有值。"""
        sales = self._sales("SKU_SMOOTH", [100, 120, 80, 110, 90, 100])
        results, _, _ = self._run(sales)
        r = results[0]
        assert r.demand_pattern == "smooth"
        assert r.adi is not None
        assert r.cv_squared is not None
        assert_close(r.adi, 1.0)

    def test_intermittent_flows_to_result(self):
        """間歇序列 → result.demand_pattern == 'intermittent'。

        序列 [100,0,0,110,0,0,90]：首(月1)→末(月7) span=7、3 次需求。
        ADI = 7/3 ≈ 2.33（尾部無需求不計入 span，符合 Syntetos-Boylan）。
        """
        sales = self._sales("SKU_INT", [100, 0, 0, 110, 0, 0, 90])
        results, _, _ = self._run(sales, min_months=1)
        r = results[0]
        assert r.demand_pattern == "intermittent"
        assert r.adi >= 1.32  # 落在間歇/塊狀區
        assert_close(r.adi, 7 / 3, tolerance=0.05)

    def test_weekly_result_pattern_dash(self):
        """週粒度 → demand_pattern 為 '—'（本期不分類週）。"""
        sales = self._sales("SKU_W", [100, 120, 80, 110, 90, 100])
        results, _, _ = self._run(sales, granularity="weekly")
        # weekly 模式下不應計算型態
        assert all(r.demand_pattern == "—" for r in results)

    def _run(self, sales, granularity="monthly", min_months=0):
        calc = SafetyStockCalculator()
        return calc.calculate(
            sales_data=sales,
            granularity=granularity,
            min_months=min_months,
            enable_outlier_detection=False,
            enable_moving_average=False,
        )
