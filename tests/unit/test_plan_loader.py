"""
Plan Data Loader -- 單元測試

測試 load_plan_data() 及其相關函式：
1. fallback aliases（中文欄位名映射）
2. _parse_mrp_columns()（MRP 複合欄位解析）
3. _extract_mrp_month_data()（MRP 單月資料提取）
4. _normalize_string_col()（float → clean string）
5. 錯誤處理（缺欄位、空檔案）
6. 真實 SAP MRP 報表載入
"""
from pathlib import Path

import pandas as pd
import pytest

from src.data_loader import (
    _apply_fallback_aliases,
    _extract_mrp_month_data,
    _normalize_string_col,
    _parse_mrp_columns,
    load_plan_data,
)

# ============================================================================
# _parse_mrp_columns 單元測試
# ============================================================================

class TestParseMrpColumns:
    """MRP 複合欄位名稱解析。"""

    def test_standard_mrp_columns(self):
        """標準 MRP 欄位格式：M202604實際需求。

        驗算：
          M202604實際需求 → month=202604, dimension=demand
          M202604實際供給 → month=202604, dimension=supply
          M202604調撥(出) → month=202604, dimension=transfer_out
        """
        columns = [
            "工廠", "料號", "庫存數量",
            "M202604實際需求", "M202604實際供給", "M202604可用數量",
            "M202604計劃訂單", "M202604獨立需求",
            "M202604調撥(出)", "M202604調撥(入)",
            "M202605實際需求", "M202605實際供給",
        ]
        result = _parse_mrp_columns(columns)

        assert "202604" in result
        assert "202605" in result
        assert result["202604"]["demand"] == "M202604實際需求"
        assert result["202604"]["supply"] == "M202604實際供給"
        assert result["202604"]["available"] == "M202604可用數量"
        assert result["202604"]["planned_order"] == "M202604計劃訂單"
        assert result["202604"]["independent_demand"] == "M202604獨立需求"
        assert result["202604"]["transfer_out"] == "M202604調撥(出)"
        assert result["202604"]["transfer_in"] == "M202604調撥(入)"
        assert result["202605"]["demand"] == "M202605實際需求"

    def test_cumulative_columns_ignored(self):
        """累計欄位（<=M202603、>=M202607）目前不解析為獨立月份。"""
        columns = ["<=M202603實際需求", ">=M202607計劃訂單", "M202604實際需求"]
        result = _parse_mrp_columns(columns)

        # 只有 202604 被解析，累計欄位的格式不匹配（有 <= 或 >= 前綴）
        assert "202604" in result

    def test_no_mrp_columns(self):
        """無 MRP 格式欄位 → 回傳空 dict。"""
        columns = ["工廠", "料號", "庫存數量"]
        result = _parse_mrp_columns(columns)
        assert result == {}

    def test_invalid_month_ignored(self):
        """無效月份（M999913）被忽略。"""
        columns = ["M999913實際需求", "M202604實際需求"]
        result = _parse_mrp_columns(columns)
        assert "999913" not in result
        assert "202604" in result

    def test_unknown_dimension_ignored(self):
        """未知維度（M202604未知欄位）被忽略。"""
        columns = ["M202604未知欄位", "M202604實際需求"]
        result = _parse_mrp_columns(columns)
        assert "demand" in result.get("202604", {})
        assert "未知" not in str(result)


# ============================================================================
# _extract_mrp_month_data 單元測試
# ============================================================================

class TestExtractMrpMonthData:
    """MRP 單月資料提取。"""

    def test_extract_with_data(self):
        """有需求和供給的月份。

        驗算：
          demand=800, supply=500 → net_change = 500 - 800 = -300
        """
        row = pd.Series({
            "M202604實際需求": 800,
            "M202604實際供給": 500,
            "M202604調撥(出)": 0,
            "M202604調撥(入)": 0,
        })
        col_map = {
            "demand": "M202604實際需求",
            "supply": "M202604實際供給",
            "transfer_out": "M202604調撥(出)",
            "transfer_in": "M202604調撥(入)",
        }
        result = _extract_mrp_month_data(row, "202604", col_map)

        assert result is not None
        assert result.month == "202604"
        assert result.demand == 800.0
        assert result.supply == 500.0
        assert result.net_change == -300.0  # supply - demand = 500 - 800

    def test_negative_demand_converted(self):
        """SAP 負數需求（代表消耗）取絕對值。

        驗算：
          demand=-600 → abs(-600) = 600
        """
        row = pd.Series({"M202604實際需求": -600})
        col_map = {"demand": "M202604實際需求"}
        result = _extract_mrp_month_data(row, "202604", col_map)

        assert result is not None
        assert result.demand == 600.0

    def test_all_zeros_returns_none(self):
        """全部為零 → 回傳 None（不建立空的 MonthlyPlanData）。"""
        row = pd.Series({
            "M202604實際需求": 0,
            "M202604實際供給": 0,
        })
        col_map = {
            "demand": "M202604實際需求",
            "supply": "M202604實際供給",
        }
        result = _extract_mrp_month_data(row, "202604", col_map)
        assert result is None

    def test_missing_column_defaults_to_zero(self):
        """col_map 中的欄位不在 row 中 → 該維度為 0。"""
        row = pd.Series({"M202604實際需求": 100})
        col_map = {
            "demand": "M202604實際需求",
            "supply": "M202604實際供給",  # 不存在於 row
        }
        result = _extract_mrp_month_data(row, "202604", col_map)

        assert result is not None
        assert result.demand == 100.0
        assert result.supply == 0.0

    def test_negative_transfer_out_converted(self):
        """SAP 調撥(出) 為負數（代表出庫），取絕對值。

        驗算：
          transfer_out=-1200 → abs(-1200) = 1200
          net_change = 0 + 0 - 0 - 1200 - 0 = -1200
        """
        row = pd.Series({"M202604調撥(出)": -1200})
        col_map = {"transfer_out": "M202604調撥(出)"}
        result = _extract_mrp_month_data(row, "202604", col_map)

        assert result is not None
        assert result.transfer_out == 1200.0
        assert result.net_change == -1200.0

    def test_positive_transfer_out_unchanged(self):
        """transfer_out 若已是正數則不變。"""
        row = pd.Series({"M202604調撥(出)": 500})
        col_map = {"transfer_out": "M202604調撥(出)"}
        result = _extract_mrp_month_data(row, "202604", col_map)

        assert result is not None
        assert result.transfer_out == 500.0
        assert result.net_change == -500.0

    def test_negative_independent_demand_converted(self):
        """SAP 獨立需求為負數（代表消耗），取絕對值。

        驗算：
          independent_demand=-300 → abs(-300) = 300
          net_change = 0 + 0 - 0 - 0 - 300 = -300
        """
        row = pd.Series({"M202604獨立需求": -300})
        col_map = {"independent_demand": "M202604獨立需求"}
        result = _extract_mrp_month_data(row, "202604", col_map)

        assert result is not None
        assert result.independent_demand == 300.0
        assert result.net_change == -300.0

    def test_mixed_negative_values_all_converted(self):
        """demand/transfer_out/independent_demand 同時為負數，全部取絕對值。

        驗算：
          demand=abs(-800)=800, supply=2400, transfer_out=abs(-400)=400
          net_change = 2400 + 0 - 800 - 400 - 0 = 1200
        """
        row = pd.Series({
            "M202604實際需求": -800,
            "M202604實際供給": 2400,
            "M202604調撥(出)": -400,
        })
        col_map = {
            "demand": "M202604實際需求",
            "supply": "M202604實際供給",
            "transfer_out": "M202604調撥(出)",
        }
        result = _extract_mrp_month_data(row, "202604", col_map)

        assert result is not None
        assert result.demand == 800.0
        assert result.supply == 2400.0
        assert result.transfer_out == 400.0
        assert result.net_change == 1200.0


# ============================================================================
# _normalize_string_col 單元測試
# ============================================================================

class TestNormalizeStringCol:
    """字串欄位正規化，特別是 float → clean string。"""

    def test_float_to_int_string(self):
        """1002.0 → '1002'（去掉 .0）。"""
        df = pd.DataFrame({"site": [1002.0, 1003.0, 1004.0]})
        _normalize_string_col(df, "site")
        assert df["site"].tolist() == ["1002", "1003", "1004"]

    def test_string_preserved(self):
        """已經是字串的值不變。"""
        df = pd.DataFrame({"sku": ["SKU001", " SKU002 ", "SKU003"]})
        _normalize_string_col(df, "sku")
        assert df["sku"].tolist() == ["SKU001", "SKU002", "SKU003"]

    def test_nan_to_empty(self):
        """NaN → 空字串。"""
        df = pd.DataFrame({"site": [1002.0, None, 1004.0]})
        _normalize_string_col(df, "site")
        assert df["site"].tolist() == ["1002", "", "1004"]

    def test_nonexistent_col_no_error(self):
        """欄位不存在時不報錯。"""
        df = pd.DataFrame({"other": [1, 2, 3]})
        _normalize_string_col(df, "site")  # 不應報錯


# ============================================================================
# Plan fallback aliases 單元測試
# ============================================================================

class TestPlanFallbackAliases:
    """驗證 plan 的中文欄位映射。"""

    def test_chinese_to_english_mapping(self):
        """工廠→site, 料號→sku, 庫存數量→current_stock。"""
        df = pd.DataFrame({
            "工廠": [1002],
            "料號": ["SKU001"],
            "庫存數量": [500],
        })
        aliases = {
            "工廠": "site",
            "料號": "sku",
            "庫存數量": "current_stock",
        }
        result = _apply_fallback_aliases(df, ["site", "sku", "current_stock"], aliases, "test")
        assert "site" in result.columns
        assert "sku" in result.columns
        assert "current_stock" in result.columns

    def test_already_english_no_change(self):
        """欄位已經是英文 → 不做映射。"""
        df = pd.DataFrame({
            "site": [1002],
            "sku": ["SKU001"],
            "current_stock": [500],
        })
        aliases = {"工廠": "site", "料號": "sku", "庫存數量": "current_stock"}
        result = _apply_fallback_aliases(df, ["site", "sku", "current_stock"], aliases, "test")
        assert list(result.columns) == ["site", "sku", "current_stock"]

    def test_partial_mapping(self):
        """部分欄位是中文、部分是英文。"""
        df = pd.DataFrame({
            "site": [1002],
            "料號": ["SKU001"],
            "庫存數量": [500],
        })
        aliases = {"料號": "sku", "庫存數量": "current_stock"}
        result = _apply_fallback_aliases(df, ["site", "sku", "current_stock"], aliases, "test")
        assert "site" in result.columns
        assert "sku" in result.columns
        assert "current_stock" in result.columns


# ============================================================================
# load_plan_data 整合測試（真實資料）
# ============================================================================

PLAN_FILE = Path(__file__).parent.parent.parent.parent / "data" / "235_庫存_0428_eg.xlsx"


@pytest.mark.slow
class TestLoadPlanDataReal:
    """用真實 SAP MRP 報表驗證完整載入流程。"""

    @pytest.fixture(autouse=True)
    def skip_if_no_file(self):
        if not PLAN_FILE.exists():
            pytest.skip("Real plan data file not available")

    def test_load_success(self):
        """報表應成功載入，不報錯。"""
        plan = load_plan_data(str(PLAN_FILE))
        assert len(plan.items) > 0

    def test_item_count(self):
        """應有約 6000+ 品項（3 個工廠 x 2000+ SKU）。"""
        plan = load_plan_data(str(PLAN_FILE))
        assert len(plan.items) > 5000

    def test_months_detected(self):
        """應偵測到 MRP 月份。"""
        plan = load_plan_data(str(PLAN_FILE))
        assert len(plan.detected_months) >= 3

    def test_planning_horizon(self):
        """planning_horizon 應被設定。"""
        plan = load_plan_data(str(PLAN_FILE))
        assert plan.planning_horizon is not None
        assert "-" in plan.planning_horizon

    def test_site_no_float_suffix(self):
        """site 值不應有 .0 後綴。"""
        plan = load_plan_data(str(PLAN_FILE))
        for item in list(plan.items.values())[:10]:
            assert ".0" not in item.site, f"site={item.site} has .0 suffix"

    def test_items_with_stock(self):
        """應有部分品項有庫存。"""
        plan = load_plan_data(str(PLAN_FILE))
        with_stock = sum(1 for it in plan.items.values() if it.current_stock > 0)
        assert with_stock > 100

    def test_items_with_month_data(self):
        """應有部分品項有月份資料。"""
        plan = load_plan_data(str(PLAN_FILE))
        with_months = sum(1 for it in plan.items.values() if len(it.months) > 0)
        assert with_months > 50

    def test_month_data_has_correct_net_change(self):
        """月份資料的 net_change 應 = supply + transfer_in - demand - transfer_out。"""
        plan = load_plan_data(str(PLAN_FILE))
        for item in plan.items.values():
            for month, md in item.months.items():
                expected_net = md.supply + md.transfer_in - md.demand - md.transfer_out - md.independent_demand
                assert abs(md.net_change - expected_net) < 0.01, (
                    f"{item.site}/{item.sku}/{month}: "
                    f"net_change={md.net_change} != expected={expected_net}"
                )
