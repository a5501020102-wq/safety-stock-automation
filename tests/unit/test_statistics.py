"""
Mean / Std / CV 統計計算 -- 單元測試

測試 _calculate_mad_statistics() 回傳的 mean 與 std_dev 值
（mean/std 使用完整序列計算，包含零值，使用 sample std (N-1)）。

同時驗證 CV (coefficient of variation) 的計算邏輯。
"""
import math

import pytest

from src.calculator import SafetyStockCalculator
from tests.conftest import assert_close
from tests.fixtures.mock_data import (
    SERIES_ALL_ZEROS,
    SERIES_IDENTICAL,
    SERIES_NORMAL,
    SERIES_SINGLE,
    SERIES_SPARSE,
)


@pytest.fixture
def calc():
    return SafetyStockCalculator()


class TestMeanStd:
    """驗證 mean 與 std_dev 的正確性。"""

    def test_mean_std_normal(self, calc):
        """SERIES_NORMAL [100, 120, 80, 110, 90] → mean=100, std=15.81

        驗算：
          N = 5
          mean = (100+120+80+110+90)/5 = 500/5 = 100.0
          deviations^2: (0)^2 + (20)^2 + (-20)^2 + (10)^2 + (-10)^2
                      = 0 + 400 + 400 + 100 + 100 = 1000
          variance = 1000 / (5-1) = 250
          std = sqrt(250) = 15.8114
        """
        result = calc._calculate_mad_statistics(SERIES_NORMAL)
        assert_close(result.mean, 100.0, tolerance=0.01, msg="mean: ")
        assert_close(result.std_dev, 15.81, tolerance=0.01, msg="std: ")

    def test_mean_std_with_zeros(self, calc):
        """SERIES_SPARSE [100, 0, 0, 200, 0, 100] → mean=66.67

        驗算：
          N = 6
          mean = (100+0+0+200+0+100)/6 = 400/6 = 66.667
          deviations^2:
            (100-66.667)^2 = 1111.11
            (0-66.667)^2   = 4444.44
            (0-66.667)^2   = 4444.44
            (200-66.667)^2 = 17777.78
            (0-66.667)^2   = 4444.44
            (100-66.667)^2 = 1111.11
          sum = 33333.33
          variance = 33333.33 / 5 = 6666.67
          std = sqrt(6666.67) = 81.65
        """
        result = calc._calculate_mad_statistics(SERIES_SPARSE)
        assert_close(result.mean, 66.67, tolerance=0.01, msg="mean: ")
        assert_close(result.std_dev, 81.65, tolerance=0.1, msg="std: ")

    def test_mean_std_single_value(self, calc):
        """SERIES_SINGLE [500] → mean=500, std=0

        驗算：
          N = 1 → 特殊處理：mean = 500, std = 0（無法算 sample std）
        """
        result = calc._calculate_mad_statistics(SERIES_SINGLE)
        assert_close(result.mean, 500.0, msg="mean: ")
        assert_close(result.std_dev, 0.0, msg="std: ")

    def test_mean_std_identical(self, calc):
        """SERIES_IDENTICAL [100, 100, 100, 100] → mean=100, std=0

        驗算：
          N = 4
          mean = 400/4 = 100
          所有偏差 = 0 → variance = 0 → std = 0
        """
        result = calc._calculate_mad_statistics(SERIES_IDENTICAL)
        assert_close(result.mean, 100.0, msg="mean: ")
        assert_close(result.std_dev, 0.0, msg="std: ")

    def test_mean_std_all_zeros(self, calc):
        """SERIES_ALL_ZEROS [0, 0, 0, 0, 0] → mean=0, std=0

        驗算：
          N = 5, 全零 → mean=0, std=0
        """
        result = calc._calculate_mad_statistics(SERIES_ALL_ZEROS)
        assert_close(result.mean, 0.0, msg="mean: ")
        assert_close(result.std_dev, 0.0, msg="std: ")


class TestCoefficientOfVariation:
    """驗證 CV = std / mean 的計算。"""

    def test_cv_normal(self, calc):
        """SERIES_NORMAL → CV = 15.81 / 100 = 0.1581

        驗算：
          mean = 100, std = 15.8114
          CV = 15.8114 / 100 = 0.1581
        """
        result = calc._calculate_mad_statistics(SERIES_NORMAL)
        # CV 由 _calculate_safety_stock 計算，此處手動驗算
        cv = result.std_dev / result.mean if result.mean > 0 else 0.0
        assert_close(cv, 0.1581, tolerance=0.001, msg="CV: ")

    def test_cv_zero_mean(self, calc):
        """全零序列 → mean=0 → CV=0（避免除以零）。"""
        result = calc._calculate_mad_statistics(SERIES_ALL_ZEROS)
        cv = result.std_dev / result.mean if result.mean > 0 else 0.0
        assert_close(cv, 0.0, msg="CV: ")

    def test_cv_identical(self, calc):
        """SERIES_IDENTICAL → std=0 → CV=0。

        驗算：
          mean = 100, std = 0
          CV = 0 / 100 = 0
        """
        result = calc._calculate_mad_statistics(SERIES_IDENTICAL)
        cv = result.std_dev / result.mean if result.mean > 0 else 0.0
        assert_close(cv, 0.0, msg="CV: ")

    def test_cv_not_used_in_ss_formula(self, calc):
        """CV 不影響 SS 計算。SS = ceil(Z * std * sqrt(LT / days_per_period))

        CV 僅作為參考指標，不參與 SS/ROP/Max 公式。
        兩個 std 相同但 mean 不同的序列（因此 CV 不同）應得到相同的 SS。

        驗算：
          序列 A: [100, 120, 80, 110, 90] → mean=100, std=15.81
          序列 B: [200, 220, 180, 210, 190] → mean=200, std=15.81
          CV_A = 0.158, CV_B = 0.079（不同）
          但 SS = ceil(Z * 15.81 * sqrt(LT/30)) 兩者相同
        """
        series_a = [100.0, 120.0, 80.0, 110.0, 90.0]
        series_b = [200.0, 220.0, 180.0, 210.0, 190.0]

        result_a = calc._calculate_mad_statistics(series_a)
        result_b = calc._calculate_mad_statistics(series_b)

        # 兩序列的 std 相同
        assert_close(result_a.std_dev, result_b.std_dev, tolerance=0.01, msg="std 應相同: ")

        # CV 不同
        cv_a = result_a.std_dev / result_a.mean
        cv_b = result_b.std_dev / result_b.mean
        assert cv_a != cv_b, "CV 應不同（mean 不同）"

        # SS 公式只用 std，不用 CV，因此相同 std 得到相同 SS
        z = 1.65  # B class
        lt = 30
        days_per_period = 30
        ss_a = math.ceil(z * result_a.std_dev * math.sqrt(lt / days_per_period))
        ss_b = math.ceil(z * result_b.std_dev * math.sqrt(lt / days_per_period))
        assert ss_a == ss_b, f"相同 std 應得到相同 SS，但 SS_A={ss_a}, SS_B={ss_b}"
