"""服務層純函式的單元測試：ma-detail、匯出輔助、參數快照、物料主檔摘要。"""

import pytest

from src.error_codes import ErrorCode
from src.services.calculation import _incomplete_month, resolve_days_per_period
from src.services.export import (
    ExportError,
    _filter_by_site,
    _site_suffix,
    _snake,
    build_sap_export,
    deserialize_results,
)
from src.services.ma_detail import (
    MAX_MONTH_SPAN,
    clean_monthly_data,
    find_filled_months,
    ma_recommendation,
    parse_statistics,
    summarize_by_quarter,
)
from src.services.material_master import summarize_material_groups


class TestMaDetail:
    def test_clean_drops_non_numeric(self):
        assert clean_monthly_data({"2025-01": "abc", "2025-02": None, "2025-03": "4"}) == {"2025-03": 4.0}

    def test_quarter_summary_across_years(self):
        summary = summarize_by_quarter({"2024-11": 10.0, "2025-02": 4.0, "2025-03": 2.0})
        assert list(summary) == ["Q1 2025", "Q4 2024"]
        assert summary["Q1 2025"] == {
            "months": ["2025-02", "2025-03"], "values": [4.0, 2.0], "avg": 3.0, "total": 6.0, "count": 2,
        }

    def test_filled_months_cross_year_gap(self):
        assert find_filled_months({"2024-11": 1.0, "2025-02": 1.0}) == ["2024-12", "2025-01"]

    def test_filled_months_guard_limits_span(self):
        # 起訖跨距超過保護上限時，最多只展開 MAX_MONTH_SPAN 個月
        filled = find_filled_months({"1900-01": 1.0, "2100-01": 1.0})
        assert len(filled) == MAX_MONTH_SPAN - 1

    @pytest.mark.parametrize("std, mean, level", [
        (0, 10, "info"),      # 標準差 0
        (6, 10, "warning"),   # CV 0.6 > 0.5
        (4, 10, "info"),      # CV 0.4 介於 0.3-0.5
        (3, 10, "success"),   # CV 0.3 不大於 0.3
        (4, 0, "success"),    # 平均 0 時 CV 視為 0
    ])
    def test_recommendation_levels(self, std, mean, level):
        assert ma_recommendation(std, mean)["level"] == level

    def test_parse_statistics_defaults_and_aliases(self):
        stats = parse_statistics({"mean_demand": "4", "maWindow": 0})
        assert stats["mean_demand"] == 4.0
        assert stats["ma_window"] == 3  # 0 視為未提供

    def test_parse_statistics_rejects_text(self):
        with pytest.raises(ValueError):
            parse_statistics({"stdDev": "x"})


class TestExportHelpers:
    def test_snake(self):
        assert _snake("safetyStockValue") == "safety_stock_value"
        assert _snake("cv") == "cv"

    def test_deserialize_results(self):
        (row,) = deserialize_results([{"safetyStock": 3, "site": "1002"}])
        assert (row.safety_stock, row.site) == (3, "1002")

    def test_site_suffix_sanitizes(self):
        assert _site_suffix("10 02/x") == "_10_02_x"
        assert _site_suffix(None) == ""

    def test_filter_all_means_no_filter(self):
        rows = deserialize_results([{"site": "1002"}, {"site": "1003"}])
        assert _filter_by_site(rows, "all") == rows
        assert len(_filter_by_site(rows, "1003")) == 1

    def test_sap_rejects_unknown_format(self):
        with pytest.raises(ExportError) as exc_info:
            build_sap_export({"format": "pdf"})
        assert exc_info.value.code == ErrorCode.INVALID_EXPORT_FORMAT

    def test_sap_site_without_rows(self):
        with pytest.raises(ExportError) as exc_info:
            build_sap_export({"results": [{"site": "1002"}], "siteFilter": "9999"})
        assert exc_info.value.message == "出貨點 9999 沒有資料"


class TestCalculationHelpers:
    @pytest.mark.parametrize("granularity, working_days, expected", [
        ("monthly", None, 30),
        ("monthly", 22, 22),
        ("weekly", 22, 7),   # 工作天數只影響月粒度
        ("daily", None, 1),
    ])
    def test_days_per_period(self, granularity, working_days, expected):
        assert resolve_days_per_period(granularity, working_days) == expected

    def test_incomplete_month(self):
        from datetime import datetime
        assert _incomplete_month(datetime(2026, 4, 15)) == "2026-04"
        assert _incomplete_month(datetime(2026, 4, 30)) is None
        assert _incomplete_month(None) is None


class TestMaterialGroups:
    def test_unavailable_when_empty(self):
        assert summarize_material_groups({}) == {"available": False, "categories": {}, "version": None}

    def test_slims_categories(self):
        master = {
            "version": "v1", "totalSkus": 2, "totalCategories": 1,
            "categories": {"15": {"name": "管", "totalCount": 2, "extra": 1,
                                  "groups": {"151": {"name": "PVC", "count": 2, "skus": ["a"]}}}},
        }
        summary = summarize_material_groups(master)
        assert summary["categories"] == {"15": {"name": "管", "totalCount": 2, "groups": {"151": {"name": "PVC", "count": 2}}}}
