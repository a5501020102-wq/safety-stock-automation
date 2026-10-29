"""從 business_logic 拆出的匯出、序列化、對比彙總模組的單元測試。"""

import csv
import io
from types import SimpleNamespace

import openpyxl
import pytest

from src.calculator import DEFAULT_Z_SCORES, CalculationParams
from src.comparison import _resolve_comparison_params, summarize_comparison
from src.exports.excel import _build_diff_rows, _comparison_param_rows, export_to_excel
from src.exports.sap import export_to_sap_mm17
from src.serialization import _resolve_max_inventory, _resolve_reorder_point, serialize_results_for_json
from src.value_utils import enum_value, resolve_cv, safe_float, safe_int


def _row(**kwargs):
    return SimpleNamespace(**kwargs)


class TestValueUtils:
    @pytest.mark.parametrize("raw, expected", [(None, 7.0), ("", 7.0), ("x", 7.0), ("1.5", 1.5), ([1], 7.0)])
    def test_safe_float(self, raw, expected):
        assert safe_float(raw, 7.0) == expected

    def test_safe_int_handles_infinity(self):
        assert safe_int(float("inf"), 3) == 3

    def test_enum_value(self):
        assert enum_value(SimpleNamespace(value="A")) == "A"
        assert enum_value("B") == "B"

    def test_resolve_cv_priority(self):
        assert resolve_cv(_row(coefficient_of_variation=0.2, cv=0.9)) == 0.2
        assert resolve_cv(_row(cv=0.9)) == 0.9
        assert resolve_cv(_row(std_dev=2, mean_demand=10)) == 0.2
        assert resolve_cv(_row(std_dev=2, mean_demand=0)) == 0.0


class TestComparison:
    def test_summary_savings(self):
        summary = summarize_comparison(
            [_row(safety_stock=60, safety_stock_value=600), _row(safety_stock=40, safety_stock_value=400)],
            [_row(safety_stock=75, safety_stock_value=750)],
        )
        assert summary["inventory_saved"] == 25
        assert summary["savings_percentage"] == 25.0
        assert summary["cost_saved"] == 250.0
        assert summary["節省比例"] == summary["savings_percentage"]
        assert (summary["all_sku_count"], summary["total_sku_count"]) == (2, 1)

    def test_summary_empty_has_zero_percent(self):
        assert summarize_comparison([], None)["savings_percentage"] == 0.0

    def test_resolve_params_fills_defaults(self):
        params = _resolve_comparison_params(CalculationParams())
        assert params.selected_months == list(range(1, 13))
        assert params.z_scores == DEFAULT_Z_SCORES

    def test_resolve_params_rejects_bad_months(self):
        with pytest.raises(ValueError):
            _resolve_comparison_params(CalculationParams(selected_months=[13]))


class TestExcel:
    def test_param_rows_weekly_daily(self):
        rows = _comparison_param_rows(
            {"selected_weeks": ["2025-W01", "2025-W02"], "lead_time_days": 14}, "weekly", True,
        )
        assert ("分析範圍", "2025-W01 ~ 2025-W02 (2 週 / 14 天)") in rows
        assert ("前置期", "14 天") in rows
        assert rows[-1] == ("", "")

    def test_param_rows_empty_without_params(self):
        assert _comparison_param_rows(None, "monthly", False) == []

    def test_diff_rows_threshold(self):
        all_rows = [_row(site="1002", sku="A", safety_stock=100), _row(site="1002", sku="B", safety_stock=100)]
        total_rows = [_row(site="1002", sku="A", safety_stock=96), _row(site="1002", sku="B", safety_stock=95)]
        diff = _build_diff_rows(all_rows, total_rows)
        # 差異 4% 不列入，差異 5% 列入
        assert [r["料號"] for r in diff] == ["B"]
        assert diff[0]["差異百分比 (%)"] == 5.0

    def test_export_excel_sheets(self):
        content = export_to_excel([_row(site="1002", sku="A")], [], None)
        workbook = openpyxl.load_workbook(io.BytesIO(content))
        assert workbook.sheetnames == ["計算結果"]


class TestSap:
    def test_csv_rounds_and_skips_missing_sku(self):
        content = export_to_sap_mm17(
            [_row(sku=" A1 ", site="1002", safety_stock=2.5), _row(sku="", site="1002", safety_stock=1)],
            None, format="csv",
        )
        rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
        assert rows == [["MATNR", "WERKS", "EISBE"], ["A1", "1002", "2"]]

    def test_rejects_unknown_format(self):
        with pytest.raises(ValueError):
            export_to_sap_mm17([_row(sku="A", site="1")], None, format="pdf")

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            export_to_sap_mm17([], None)


class TestSerialization:
    def test_engine_values_take_priority(self):
        r = _row(reorder_point=12, max_inventory=20)
        rop = _resolve_reorder_point(r, mean_demand=30, safety_stock=5, lead_time_days=30)
        assert rop == 12
        assert _resolve_max_inventory(r, rop, 5) == 20

    def test_fallback_when_missing(self):
        r = _row()
        rop = _resolve_reorder_point(r, mean_demand=30, safety_stock=5, lead_time_days=10)
        assert rop == 15  # ceil(30/30*10 + 5)
        assert _resolve_max_inventory(r, rop, 5) == 20

    def test_serialize_shape(self):
        out = serialize_results_for_json([_row(sku="A", monthly_values=[1.234])], [], None)
        assert set(out) == {"summary", "results", "excluded"}
        result = out["results"][0]
        assert result["monthly_values"] == [1.23]
        assert result["monthly_plan"] == []
        assert result["lead_time_days"] == 30
