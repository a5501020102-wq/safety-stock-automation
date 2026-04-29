"""
Moving Average (MA) 平滑 -- 單元測試

測試 SafetyStockCalculator._apply_moving_average() 與
_apply_moving_average_pure_python() 的行為：
1. 基本 rolling window 計算
2. 樣本不足時回傳原值
3. 窗口等於序列長度
4. 全零序列
5. 離群值被替換為 0 後的平滑
6. pandas 版與純 Python 版結果一致
7. 使用 mock_data 中的預期值驗證
"""
import pytest

from src.calculator import SafetyStockCalculator
from tests.conftest import assert_close
from tests.fixtures.mock_data import (
    MA_NORMAL_EXPECTED,
    SERIES_ALL_ZEROS,
    SERIES_NORMAL,
)


@pytest.fixture
def calc():
    return SafetyStockCalculator()


class TestMovingAverageBasic:
    """基本移動平均計算。"""

    def test_ma_basic(self, calc):
        """[100, 200, 300, 400, 500] window=3, min_periods=2

        驗算（rolling window=3, min_periods=2）：
          [0] 100 → 只有 1 值 < min_periods=2 → 保留原值 100
          [1] (100+200)/2 = 150.0  （2 值 >= min_periods）
          [2] (100+200+300)/3 = 200.0
          [3] (200+300+400)/3 = 300.0
          [4] (300+400+500)/3 = 400.0
        """
        values = [100.0, 200.0, 300.0, 400.0, 500.0]
        result = calc._apply_moving_average(values, window=3, min_periods=2)

        assert len(result) == 5
        assert_close(result[0], 100.0, msg="idx 0: ")
        assert_close(result[1], 150.0, msg="idx 1: ")
        assert_close(result[2], 200.0, msg="idx 2: ")
        assert_close(result[3], 300.0, msg="idx 3: ")
        assert_close(result[4], 400.0, msg="idx 4: ")

    def test_ma_too_few_values(self, calc):
        """[100] → 長度 1 < min_periods=2，回傳原序列。"""
        values = [100.0]
        result = calc._apply_moving_average(values, window=3, min_periods=2)
        assert result == [100.0]

    def test_ma_window_equals_length(self, calc):
        """[100, 200, 300] window=3, min_periods=2

        驗算：
          [0] 100 → 1 值 < min_periods → 保留 100
          [1] (100+200)/2 = 150.0
          [2] (100+200+300)/3 = 200.0
        """
        values = [100.0, 200.0, 300.0]
        result = calc._apply_moving_average(values, window=3, min_periods=2)

        assert len(result) == 3
        assert_close(result[0], 100.0, msg="idx 0: ")
        assert_close(result[1], 150.0, msg="idx 1: ")
        assert_close(result[2], 200.0, msg="idx 2: ")

    def test_ma_all_zeros(self, calc):
        """[0, 0, 0, 0, 0] → 全零，MA 後仍全零。

        驗算：
          每個窗口的平均值都是 0.0
        """
        result = calc._apply_moving_average(SERIES_ALL_ZEROS, window=3, min_periods=2)
        assert len(result) == 5
        for i, v in enumerate(result):
            assert_close(v, 0.0, msg=f"idx {i}: ")

    def test_ma_with_outlier_replaced(self, calc):
        """[100, 0, 100, 100, 100] 模擬離群值被替換為 0 的情境。

        驗算（window=3, min_periods=2）：
          [0] 100 → 1 值 < min_periods → 保留 100
          [1] (100+0)/2 = 50.0
          [2] (100+0+100)/3 = 66.67
          [3] (0+100+100)/3 = 66.67
          [4] (100+100+100)/3 = 100.0
        """
        values = [100.0, 0.0, 100.0, 100.0, 100.0]
        result = calc._apply_moving_average(values, window=3, min_periods=2)

        assert len(result) == 5
        assert_close(result[0], 100.0, msg="idx 0: ")
        assert_close(result[1], 50.0, msg="idx 1: ")
        assert_close(result[2], 66.67, tolerance=0.01, msg="idx 2: ")
        assert_close(result[3], 66.67, tolerance=0.01, msg="idx 3: ")
        assert_close(result[4], 100.0, msg="idx 4: ")


class TestMovingAveragePurePython:
    """純 Python 實作的移動平均。"""

    def test_ma_pure_python_matches_pandas(self, calc):
        """兩種實作（pandas vs pure Python）對同一序列應產生相同結果。

        使用 [100, 200, 300, 400, 500] window=3, min_periods=2
        """
        values = [100.0, 200.0, 300.0, 400.0, 500.0]
        pandas_result = calc._apply_moving_average(values, window=3, min_periods=2)
        python_result = calc._apply_moving_average_pure_python(values, window=3, min_periods=2)

        assert len(pandas_result) == len(python_result)
        for i in range(len(pandas_result)):
            assert_close(
                python_result[i],
                pandas_result[i],
                tolerance=0.01,
                msg=f"idx {i} 不一致: ",
            )

    def test_ma_pure_python_basic(self, calc):
        """純 Python 版基本驗算：[100, 200, 300, 400, 500] window=3, min_periods=2

        驗算：
          [0] window=[100], len=1 < 2 → 保留 100
          [1] window=[100, 200], len=2 >= 2 → (100+200)/2 = 150
          [2] window=[100, 200, 300], len=3 >= 2 → (100+200+300)/3 = 200
          [3] window=[200, 300, 400], len=3 → 300
          [4] window=[300, 400, 500], len=3 → 400
        """
        values = [100.0, 200.0, 300.0, 400.0, 500.0]
        result = calc._apply_moving_average_pure_python(values, window=3, min_periods=2)

        assert len(result) == 5
        assert_close(result[0], 100.0, msg="idx 0: ")
        assert_close(result[1], 150.0, msg="idx 1: ")
        assert_close(result[2], 200.0, msg="idx 2: ")
        assert_close(result[3], 300.0, msg="idx 3: ")
        assert_close(result[4], 400.0, msg="idx 4: ")


class TestMovingAverageMockData:
    """使用 mock_data 中的預期值驗證。"""

    def test_ma_series_normal(self, calc):
        """SERIES_NORMAL [100, 120, 80, 110, 90] window=3, min_periods=2

        驗算（來自 mock_data.MA_NORMAL_EXPECTED）：
          [0] 100 → 保留 100
          [1] (100+120)/2 = 110
          [2] (100+120+80)/3 = 100
          [3] (120+80+110)/3 = 103.33
          [4] (80+110+90)/3 = 93.33
        """
        result = calc._apply_moving_average(SERIES_NORMAL, window=3, min_periods=2)

        assert len(result) == len(MA_NORMAL_EXPECTED)
        for i in range(len(result)):
            assert_close(
                result[i],
                MA_NORMAL_EXPECTED[i],
                tolerance=0.01,
                msg=f"idx {i}: ",
            )
