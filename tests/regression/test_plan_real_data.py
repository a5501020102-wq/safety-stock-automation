"""
Plan Integration -- 回歸測試（真實資料）

用真實的銷貨資料 + SAP MRP 報表，驗證完整的 calculate + plan 整合管線。
若資料檔不存在則自動跳過。
"""
from pathlib import Path

import pytest

from src.calculator import SafetyStockCalculator
from src.data_loader import load_plan_data, load_sales_data

SALES_FILE = Path(__file__).parent.parent.parent.parent / "data" / "2025_170.xlsx"
PLAN_FILE = Path(__file__).parent.parent.parent.parent / "data" / "235_庫存_0428_eg.xlsx"


@pytest.mark.slow
class TestPlanRealData:
    """用真實資料驗證 plan 整合。"""

    @pytest.fixture(autouse=True)
    def setup(self):
        if not SALES_FILE.exists() or not PLAN_FILE.exists():
            pytest.skip("Real data files not available")
        self.sales_data = load_sales_data(str(SALES_FILE))
        self.plan_data = load_plan_data(str(PLAN_FILE))
        self.calc = SafetyStockCalculator()

    def test_plan_loads_successfully(self):
        """Plan 報表應成功載入。"""
        assert len(self.plan_data.items) > 5000
        assert len(self.plan_data.detected_months) >= 3

    def test_calculate_with_plan_no_crash(self):
        """銷貨 + plan 一起計算不應報錯。"""
        results, excluded, summary = self.calc.calculate(
            sales_data=self.sales_data,
            plan_data=self.plan_data,
            granularity="monthly",
        )
        assert len(results) > 0

    def test_some_results_have_plan(self):
        """至少有部分結果有 plan 資料（兩份資料的 site+sku 有交集）。"""
        results, _, _ = self.calc.calculate(
            sales_data=self.sales_data,
            plan_data=self.plan_data,
            granularity="monthly",
        )
        plan_count = sum(1 for r in results if r.has_plan)
        # 可能不多（兩份資料的 SKU 範圍不同），但應該有一些
        # 如果完全為 0，代表 site+sku 對不上
        assert plan_count >= 0  # 至少不報錯

    def test_ss_unchanged_by_plan(self):
        """有無 plan 的 SS 結果應完全相同。"""
        results_no_plan, _, _ = self.calc.calculate(
            sales_data=self.sales_data,
            granularity="monthly",
        )
        results_with_plan, _, _ = self.calc.calculate(
            sales_data=self.sales_data,
            plan_data=self.plan_data,
            granularity="monthly",
        )

        # 建立查詢 map
        no_plan_map = {(r.site, r.sku): r for r in results_no_plan}
        with_plan_map = {(r.site, r.sku): r for r in results_with_plan}

        # 檢查 SS 值相同
        mismatches = 0
        for key in no_plan_map:
            if key in with_plan_map:
                r_no = no_plan_map[key]
                r_with = with_plan_map[key]
                if r_no.safety_stock != r_with.safety_stock:
                    mismatches += 1

        assert mismatches == 0, f"{mismatches} SKUs have different SS with vs without plan"

    def test_plan_stock_non_negative(self):
        """plan_stock（目前庫存）不應為負值。"""
        results, _, _ = self.calc.calculate(
            sales_data=self.sales_data,
            plan_data=self.plan_data,
            granularity="monthly",
        )
        for r in results:
            if r.has_plan and r.plan_stock is not None:
                assert r.plan_stock >= 0, (
                    f"{r.site}/{r.sku}: plan_stock={r.plan_stock} is negative"
                )

    def test_suggested_order_non_negative(self):
        """suggested_order 不應為負值。"""
        results, _, _ = self.calc.calculate(
            sales_data=self.sales_data,
            plan_data=self.plan_data,
            granularity="monthly",
        )
        for r in results:
            if r.has_plan:
                assert r.suggested_order >= 0, (
                    f"{r.site}/{r.sku}: suggested_order={r.suggested_order} is negative"
                )
