"""
MAD (Median Absolute Deviation) 離群值偵測 -- 單元測試

測試 SafetyStockCalculator._calculate_mad_statistics() 的每一步：
1. 從非零值計算中位數
2. 從非零值計算 MAD
3. 轉換成 sigma equivalent (MAD * 1.4826)
4. 設定上下界 (median +/- 3 * sigma_eq)
5. 標記超出界限的非零值為離群值
6. 零值永遠不被標為離群值
"""
import pytest

from src.calculator import CalculationOptions, SafetyStockCalculator
from tests.conftest import assert_close
from tests.fixtures.mock_data import (
    MAD_IDENTICAL_OUTLIER_EXPECTED,
    MAD_UPPER_OUTLIER_EXPECTED,
    SERIES_ALL_ZEROS,
    SERIES_IDENTICAL,
    SERIES_IDENTICAL_PLUS_OUTLIER,
    SERIES_NORMAL,
    SERIES_SINGLE,
    SERIES_SPARSE,
    SERIES_THREE_NONZERO,
    SERIES_TWO_VALUES,
    SERIES_WITH_NEGATIVES,
    SERIES_WITH_UPPER_OUTLIER,
)


@pytest.fixture
def calc():
    return SafetyStockCalculator()


class TestMadNoOutliers:
    """正常序列，預期無離群值。"""

    def test_normal_series(self, calc):
        """[100, 120, 80, 110, 90] 全部在合理範圍內。

        驗算：
          non-zero = [100, 120, 80, 110, 90]
          sorted = [80, 90, 100, 110, 120]
          median = 100
          abs_devs = [0, 10, 10, 20, 20] sorted
          MAD = 10
          sigma_eq = 10 * 1.4826 = 14.826
          upper = 100 + 3 * 14.826 = 144.5
          lower = 100 - 3 * 14.826 = 55.5
          全部在 [55.5, 144.5] 內
        """
        result = calc._calculate_mad_statistics(SERIES_NORMAL)
        assert len(result.outliers) == 0
        assert result.final_sample_size == 5

    def test_identical_values(self, calc):
        """[100, 100, 100, 100] MAD=0，跳過偵測。

        驗算：
          non-zero = [100, 100, 100, 100]
          MAD = 0（50%+ 值相同）
          → 不做偵測，outliers = 0
        """
        result = calc._calculate_mad_statistics(SERIES_IDENTICAL)
        assert len(result.outliers) == 0
        assert_close(result.mean, 100.0)
        assert_close(result.std_dev, 0.0)


class TestMadWithOutliers:
    """含離群值的序列。"""

    def test_upper_outlier_detected(self, calc):
        """[100, 120, 80, 110, 90, 800] → 800 應被標為 upper outlier。

        驗算：
          median = 105, MAD = 15.0
          sigma_eq = 22.24, upper = 171.72
          800 > 171.72 → outlier
        """
        result = calc._calculate_mad_statistics(SERIES_WITH_UPPER_OUTLIER)
        expected = MAD_UPPER_OUTLIER_EXPECTED

        assert len(result.outliers) == expected["outlier_count"]
        assert result.outliers[0].value == 800.0
        assert result.outliers[0].bound == "upper"
        assert_close(result.outliers[0].threshold, expected["upper_bound"], tolerance=0.1)

    def test_identical_plus_outlier_mad_zero(self, calc):
        """[100, 100, 100, 100, 5000] → MAD=0，不做偵測。

        驗算：
          non-zero median = 100, abs_devs = [0, 0, 0, 0, 4900]
          MAD = 0 → 跳過偵測
          5000 不會被標記（因為 MAD=0）
        """
        result = calc._calculate_mad_statistics(SERIES_IDENTICAL_PLUS_OUTLIER)
        assert len(result.outliers) == MAD_IDENTICAL_OUTLIER_EXPECTED["outlier_count"]


class TestMadEdgeCases:
    """邊界情境。"""

    def test_empty_values(self, calc):
        """空序列 → mean=0, std=0, 無離群值。"""
        result = calc._calculate_mad_statistics([])
        assert result.mean == 0
        assert result.std_dev == 0
        assert len(result.outliers) == 0
        assert result.final_sample_size == 0

    def test_single_value(self, calc):
        """[500] → mean=500, std=0, 無離群值。"""
        result = calc._calculate_mad_statistics(SERIES_SINGLE)
        assert_close(result.mean, 500.0)
        assert_close(result.std_dev, 0.0)
        assert len(result.outliers) == 0
        assert result.final_sample_size == 1

    def test_all_zeros(self, calc):
        """[0, 0, 0, 0, 0] → non-zero < 3，跳過偵測。"""
        result = calc._calculate_mad_statistics(SERIES_ALL_ZEROS)
        assert len(result.outliers) == 0
        assert_close(result.mean, 0.0)
        assert_close(result.std_dev, 0.0)

    def test_two_values(self, calc):
        """[100, 200] → non-zero=2 < 3，跳過偵測。"""
        result = calc._calculate_mad_statistics(SERIES_TWO_VALUES)
        assert len(result.outliers) == 0
        assert_close(result.mean, 150.0)

    def test_three_nonzero(self, calc):
        """[100, 0, 200, 0, 300] → non-zero=3，剛好達到偵測門檻。

        驗算：
          non-zero = [100, 200, 300]
          sorted = [100, 200, 300]
          median = 200
          abs_devs = [0, 100, 100] sorted
          MAD = 100
          sigma_eq = 100 * 1.4826 = 148.26
          upper = 200 + 3 * 148.26 = 644.8
          lower = 200 - 3 * 148.26 = -244.8
          全部在界內
        """
        result = calc._calculate_mad_statistics(SERIES_THREE_NONZERO)
        assert len(result.outliers) == 0

    def test_negatives_not_flagged(self, calc):
        """[100, -50, 200, 100] → 負值被視為 <= 0，不參與 MAD，不被標記。"""
        result = calc._calculate_mad_statistics(SERIES_WITH_NEGATIVES)
        # non-zero (> 0) = [100, 200, 100], -50 被排除
        # 不管 MAD 結果如何，-50 不應該出現在 outliers 中
        for o in result.outliers:
            assert o.value > 0, f"負值 {o.value} 不應被標為離群值"

    def test_sparse_zeros_not_flagged(self, calc):
        """[100, 0, 0, 200, 0, 100] → 零值永遠不被標記。"""
        result = calc._calculate_mad_statistics(SERIES_SPARSE)
        for o in result.outliers:
            assert o.value != 0, "零值不應被標為離群值"


class TestMadDisabled:
    """停用離群值偵測。"""

    def test_disabled_returns_no_outliers(self, calc):
        """enable_outlier_detection=False → 不做偵測。"""
        options = CalculationOptions(enable_outlier_detection=False)
        result = calc._calculate_mad_statistics(SERIES_WITH_UPPER_OUTLIER, options)
        assert len(result.outliers) == 0

    def test_disabled_still_calculates_mean_std(self, calc):
        """停用偵測仍然回傳正確的 mean/std。"""
        options = CalculationOptions(enable_outlier_detection=False)
        result = calc._calculate_mad_statistics(SERIES_NORMAL, options)
        assert_close(result.mean, 100.0)
        assert result.std_dev > 0


class TestMadMeanStdConsistency:
    """確認 MAD 回傳的 mean/std 是用完整序列（含零值）算的。"""

    def test_mean_includes_zeros(self, calc):
        """SERIES_SPARSE 的 mean 應包含零值。

        驗算：
          [100, 0, 0, 200, 0, 100] → sum=400, N=6
          mean = 400/6 = 66.67
        """
        result = calc._calculate_mad_statistics(SERIES_SPARSE)
        assert_close(result.mean, 66.67, tolerance=0.01)

    def test_std_includes_zeros(self, calc):
        """SERIES_SPARSE 的 std 應包含零值。

        驗算：
          mean = 66.67
          deviations: (33.33)^2 + (-66.67)^2 + (-66.67)^2 + (133.33)^2 + (-66.67)^2 + (33.33)^2
          = 1111.1 + 4444.4 + 4444.4 + 17777.8 + 4444.4 + 1111.1 = 33333.3
          variance = 33333.3 / 5 = 6666.67
          std = sqrt(6666.67) = 81.65
        """
        result = calc._calculate_mad_statistics(SERIES_SPARSE)
        assert_close(result.std_dev, 81.65, tolerance=0.1)
