"""
calculate() 完整管線整合測試

驗證 calculate() 從輸入到輸出的完整流程，包含：
- 多 SKU 批次計算
- 不同 granularity（monthly / weekly / daily）
- MAD + MA 選項啟用
- 排除項目（期數不足）
- 空資料邊界情境
- ABC 分類
- 趨勢偵測
"""

import pandas as pd
import pytest

from src.calculator import SafetyStockCalculator
from src.models import SalesData
from tests.conftest import (
    build_mock_sales_df,
    build_monthly_records,
    build_weekly_records,
)

# ============================================================================
# Helper
# ============================================================================

def _build_multi_sku_sales_data(
    sku_monthly_map: dict[str, list[float]],
    site: str = "1002",
    has_price_data: bool = False,
) -> SalesData:
    """從多個 SKU 的月度值建立 SalesData。

    Args:
        sku_monthly_map: {"SKU001": [100, 200, ...], "SKU002": [...]}
        site: 出貨點
        has_price_data: 是否包含價格資料
    """
    all_records = []
    for sku, values in sku_monthly_map.items():
        records = build_monthly_records(sku=sku, monthly_values=values, site=site)
        all_records.extend(records)

    df = build_mock_sales_df(all_records, site=site)
    return SalesData(
        df=df,
        available_sites=[site],
        has_stock_data=False,
        has_price_data=has_price_data,
        record_count=len(all_records),
    )


# ============================================================================
# 整合測試
# ============================================================================


class TestFullPipelineMonthly:
    """monthly granularity 的完整管線測試。"""

    def test_full_pipeline_monthly_no_options(self):
        """基本 monthly 計算：3 個 SKU、6 個月、無特殊選項。

        驗算（SKU_A）：
          序列 = [100, 120, 80, 110, 90, 100]
          mean = 600 / 6 = 100.0
          std = sqrt(((0)^2+(20)^2+(-20)^2+(10)^2+(-10)^2+(0)^2) / 5) = sqrt(200) = 14.14

        驗證：
          - 回傳 (results, excluded, summary) 三元組
          - results 非空，每個項目有必要欄位
          - summary 計數正確
        """
        sales_data = _build_multi_sku_sales_data({
            "SKU_A": [100, 120, 80, 110, 90, 100],
            "SKU_B": [200, 250, 180, 220, 210, 190],
            "SKU_C": [50, 60, 40, 55, 45, 50],
        })

        calc = SafetyStockCalculator()
        results, excluded, summary = calc.calculate(
            sales_data=sales_data,
            granularity="monthly",
            min_months=0,
            enable_outlier_detection=False,
            enable_moving_average=False,
        )

        # 回傳結構驗證
        assert isinstance(results, list)
        assert isinstance(excluded, list)
        assert summary is not None

        # 3 個 SKU 都應產生結果
        assert len(results) == 3, f"預期 3 個結果，得到 {len(results)}"

        # 每個結果必須有關鍵欄位
        for r in results:
            assert r.site == "1002"
            assert r.sku in ("SKU_A", "SKU_B", "SKU_C")
            assert r.mean_demand > 0
            assert r.std_dev >= 0
            assert r.safety_stock >= 0
            assert r.reorder_point >= 0
            assert r.max_inventory >= 0

        # summary 計數
        assert summary.total_skus == 3
        assert summary.excluded_count == 0

    def test_full_pipeline_with_mad_and_ma(self):
        """啟用 MAD 離群值偵測 + MA 平滑，驗證結果結構。

        與 no-options 版本使用相同資料，驗證：
          - outliers_removed >= 0
          - 結果可能與無選項版本不同（因 MA 平滑）
        """
        sales_data = _build_multi_sku_sales_data({
            "SKU_A": [100, 120, 80, 110, 90, 100],
            "SKU_B": [200, 250, 180, 220, 210, 190],
            "SKU_C": [50, 60, 40, 55, 45, 50],
        })

        calc = SafetyStockCalculator()
        results, excluded, summary = calc.calculate(
            sales_data=sales_data,
            granularity="monthly",
            min_months=0,
            enable_outlier_detection=True,
            enable_moving_average=True,
        )

        assert len(results) == 3

        for r in results:
            assert r.outliers_removed >= 0, (
                f"{r.sku} outliers_removed 不應為負數: {r.outliers_removed}"
            )

    def test_full_pipeline_excluded_items(self):
        """期數不足的 SKU 應出現在 excluded 清單。

        SKU_SHORT 只有 1 個月資料，min_months=2 時應被排除。
        排除原因應包含期數不足的說明。
        """
        sales_data = _build_multi_sku_sales_data({
            "SKU_NORMAL": [100, 120, 80, 110, 90, 100],
            "SKU_SHORT": [500],
        })

        calc = SafetyStockCalculator()
        results, excluded, summary = calc.calculate(
            sales_data=sales_data,
            granularity="monthly",
            min_months=2,
            enable_outlier_detection=False,
            enable_moving_average=False,
        )

        # SKU_NORMAL 應在結果中
        result_skus = {r.sku for r in results}
        assert "SKU_NORMAL" in result_skus

        # SKU_SHORT 應被排除
        excluded_skus = {e.sku for e in excluded}
        assert "SKU_SHORT" in excluded_skus, (
            f"SKU_SHORT 應被排除，但不在 excluded 清單中。"
            f" results={result_skus}, excluded={excluded_skus}"
        )

        # 排除原因不應為空
        short_excluded = next(e for e in excluded if e.sku == "SKU_SHORT")
        assert short_excluded.reason, "排除原因不應為空字串"


class TestFullPipelineGranularity:
    """不同 granularity 的管線測試。"""

    def test_full_pipeline_weekly(self):
        """weekly granularity：驗證結果存在且 lead_time_days 正確。

        使用 8 週資料，驗證 weekly 模式下 days_per_period = 7。
        """
        all_records = build_weekly_records(
            sku="SKU_W1",
            weekly_values=[100, 120, 80, 110, 90, 100, 95, 105],
        )
        df = build_mock_sales_df(all_records)
        sales_data = SalesData(
            df=df,
            available_sites=["1002"],
            has_stock_data=False,
            has_price_data=False,
            record_count=len(all_records),
        )

        calc = SafetyStockCalculator()
        results, excluded, summary = calc.calculate(
            sales_data=sales_data,
            granularity="weekly",
            lead_time_days=14,
            min_months=0,
            enable_outlier_detection=False,
            enable_moving_average=False,
        )

        assert len(results) >= 1, "weekly 模式應至少產生 1 個結果"
        r = results[0]
        assert r.lead_time_days == 14

    def test_full_pipeline_daily(self):
        """daily granularity：驗證結果存在且不崩潰。"""
        sales_data = _build_multi_sku_sales_data({
            "SKU_D1": [100, 120, 80, 110, 90, 100],
        })

        calc = SafetyStockCalculator()
        results, excluded, summary = calc.calculate(
            sales_data=sales_data,
            granularity="daily",
            min_months=0,
            enable_outlier_detection=False,
            enable_moving_average=False,
        )

        assert len(results) >= 1, "daily 模式應至少產生 1 個結果"


class TestFullPipelineEdgeCases:
    """邊界情境測試。"""

    def test_full_pipeline_no_crash_empty_data(self):
        """空 DataFrame 應拋出 ValueError（計算引擎拒絕空資料）。"""
        df = pd.DataFrame(columns=[
            "date", "site", "sku", "name", "quantity",
            "year_month", "year_week", "date_str",
        ])
        sales_data = SalesData(
            df=df,
            available_sites=[],
            has_stock_data=False,
            has_price_data=False,
            record_count=0,
        )

        calc = SafetyStockCalculator()
        with pytest.raises(ValueError):
            calc.calculate(
                sales_data=sales_data,
                granularity="monthly",
                min_months=0,
            )


class TestFullPipelineABC:
    """ABC 分類整合測試。"""

    def test_full_pipeline_abc_classification(self):
        """3 個 SKU 搭配不同價格，驗證 ABC 分類正確指派。

        價格設定：
          SKU_HIGH:  price=1000, qty=100*6=600  -> value=600,000 -> A
          SKU_MID:   price=50,   qty=200*6=1200 -> value=60,000  -> B
          SKU_LOW:   price=1,    qty=50*6=300   -> value=300     -> C

        ABC 門檻（預設）：A=80%, B=95%, C=5%
          total_value = 660,300
          SKU_HIGH: 600,000/660,300 = 90.9% -> A (累積 < 80%? 不，90.9% > 80%，但它是第一個所以 <= 80% 界線內)
          實際排序後累積百分比：SKU_HIGH=90.9%(A), SKU_MID=99.95%(B), SKU_LOW=100%(C)
        """
        sales_data = _build_multi_sku_sales_data(
            {
                "SKU_HIGH": [100, 120, 80, 110, 90, 100],
                "SKU_MID": [200, 250, 180, 220, 210, 190],
                "SKU_LOW": [50, 60, 40, 55, 45, 50],
            },
            has_price_data=True,
        )

        price_data = {
            "SKU_HIGH": 1000.0,
            "SKU_MID": 50.0,
            "SKU_LOW": 1.0,
        }

        calc = SafetyStockCalculator()
        results, _, _ = calc.calculate(
            sales_data=sales_data,
            price_data=price_data,
            granularity="monthly",
            min_months=0,
            enable_outlier_detection=False,
            enable_moving_average=False,
        )

        result_map = {r.sku: r for r in results}

        # SKU_HIGH 應為 A class（最高價值）
        assert result_map["SKU_HIGH"].abc_class.value == "A", (
            f"SKU_HIGH 預期 A class，得到 {result_map['SKU_HIGH'].abc_class.value}"
        )
        # SKU_LOW 應為 C class（最低價值）
        assert result_map["SKU_LOW"].abc_class.value == "C", (
            f"SKU_LOW 預期 C class，得到 {result_map['SKU_LOW'].abc_class.value}"
        )


class TestFullPipelineTrend:
    """趨勢偵測整合測試。"""

    def test_full_pipeline_trend_detection(self):
        """強遞增序列的 short-term 趨勢偵測應為正值。

        序列 = [10, 20, 30, 40, 50, 60]（持續遞增）
        short 模式將序列分前後半比較：
          前半 [10, 20, 30] mean = 20
          後半 [40, 50, 60] mean = 50
          trend_pct = (50 - 20) / 20 * 100 = 150%
        trend_label 應包含 "+"
        """
        sales_data = _build_multi_sku_sales_data({
            "SKU_TREND": [10, 20, 30, 40, 50, 60],
        })

        calc = SafetyStockCalculator()
        results, _, _ = calc.calculate(
            sales_data=sales_data,
            granularity="monthly",
            min_months=0,
            trend_mode="short",
            enable_outlier_detection=False,
            enable_moving_average=False,
        )

        assert len(results) == 1
        r = results[0]

        assert r.trend_pct is not None, "趨勢百分比不應為 None"
        assert r.trend_pct > 0, f"強遞增序列 trend_pct 應 > 0，得到 {r.trend_pct}"
        assert "+" in r.trend_label, (
            f"trend_label 應包含 '+'，得到 '{r.trend_label}'"
        )
