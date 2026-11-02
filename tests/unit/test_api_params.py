"""/api/calculate 參數解析的單元測試：驗證順序、預設值與「無效值靜默忽略」的既有行為。"""

import pytest

from src.api.params import (
    parse_calculate_body,
    parse_int_param,
    validate_abc_thresholds,
    validate_z_scores,
)
from src.api.responses import ApiError
from src.calculator import DEFAULT_ABC_THRESHOLDS, DEFAULT_Z_SCORES


def _error_message(body):
    with pytest.raises(ApiError) as exc_info:
        parse_calculate_body(body)
    assert exc_info.value.code == "INVALID_PARAMS"
    return exc_info.value.message


class TestDefaults:
    def test_empty_body_uses_defaults(self):
        req = parse_calculate_body({})
        assert req.calc_mode == "all"
        assert req.params.z_scores == DEFAULT_Z_SCORES
        assert req.params.abc_thresholds == DEFAULT_ABC_THRESHOLDS
        assert req.params.selected_months == list(range(1, 13))
        assert (req.params.lead_time_days, req.params.min_months, req.params.ma_window) == (30, 2, 3)
        assert req.params.enable_outlier_detection is True
        assert req.params.enable_moving_average is False
        assert req.params.granularity == "monthly"

    def test_defaults_are_independent_copies(self):
        req = parse_calculate_body({})
        req.params.z_scores["A"] = 9
        req.params.selected_months.append(99)
        assert DEFAULT_Z_SCORES["A"] == 2.05
        assert parse_calculate_body({}).params.selected_months == list(range(1, 13))


class TestKeyStyles:
    def test_nested_camel_case(self):
        req = parse_calculate_body({"params": {"calcMode": "total", "leadTime": 45, "targetSite": "1002"}})
        assert (req.calc_mode, req.params.lead_time_days, req.target_site) == ("total", 45, "1002")

    def test_flat_snake_case(self):
        req = parse_calculate_body({"calc_mode": "compare", "lead_time": 45})
        assert (req.calc_mode, req.params.lead_time_days) == ("compare", 45)

    def test_snapshot_calc_mode_reads_top_level_snake_key_only(self):
        # 既有行為：快照的 calcMode 只看 body 頂層的 calc_mode
        assert parse_calculate_body({"params": {"calcMode": "compare"}}).snapshot_calc_mode == "all"
        assert parse_calculate_body({"calc_mode": "total"}).snapshot_calc_mode == "total"


class TestValidationErrors:
    def test_unknown_calc_mode(self):
        assert _error_message({"calcMode": "x"}) == "未知的計算模式: x"

    def test_calc_mode_checked_before_z_scores(self):
        assert _error_message({"calcMode": "x", "zScores": [1]}) == "未知的計算模式: x"

    def test_bad_months(self):
        assert _error_message({"selectedMonths": [0, 13]}) == "selected_months 必須是 1-12 的整數列表"

    def test_bad_granularity_lists_choices(self):
        message = _error_message({"granularity": "yearly"})
        assert message == "granularity 必須是 ('daily', 'weekly', 'monthly') 之一，收到: yearly"


class TestValidators:
    def test_z_scores_partial_override_keeps_defaults(self):
        assert validate_z_scores({"A": 2.33}) == {"A": 2.33, "B": 1.65, "C": 1.28}

    @pytest.mark.parametrize("value, message", [
        ([1], "z_scores 必須是物件 {A, B, C}"),
        ({"A": 9}, "z_scores.A 必須介於 0.5-3.5"),
        ({"B": "x"}, "z_scores.B 必須是數字"),
    ])
    def test_z_scores_errors(self, value, message):
        with pytest.raises(ApiError) as exc_info:
            validate_z_scores(value)
        assert exc_info.value.message == message

    def test_abc_thresholds_must_be_ascending(self):
        with pytest.raises(ApiError) as exc_info:
            validate_abc_thresholds({"A": 0.9, "B": 0.8})
        assert exc_info.value.message == "abc_thresholds.A 必須小於 B"

    def test_abc_thresholds_open_interval(self):
        with pytest.raises(ApiError):
            validate_abc_thresholds({"A": 0.0})

    def test_int_param_zero_is_valid_value(self):
        # min_months=0 是合法值，不能被當成「未提供」而回到預設 2
        assert parse_int_param({"min_months": 0}, "min_months", "minMonths", (2, 0, 12)) == 0

    def test_int_param_bounds_inclusive(self):
        assert parse_int_param({"leadTime": 365}, "lead_time", "leadTime", (30, 1, 365)) == 365
        with pytest.raises(ApiError):
            parse_int_param({"leadTime": 366}, "lead_time", "leadTime", (30, 1, 365))


class TestSilentlyIgnoredValues:
    """這些欄位的無效值不報錯，而是回到預設值（既有行為）。"""

    def test_invalid_trend_mode(self):
        assert parse_calculate_body({"trendMode": "x"}).params.trend_mode == "none"

    @pytest.mark.parametrize("raw", [0, 32, "x"])
    def test_invalid_working_days(self, raw):
        assert parse_calculate_body({"workingDaysPerMonth": raw}).params.working_days_per_month is None

    def test_working_days_accepts_numeric_string(self):
        assert parse_calculate_body({"workingDaysPerMonth": "22"}).params.working_days_per_month == 22

    def test_dates_accept_slash_and_ignore_garbage(self):
        params = parse_calculate_body({"dateFrom": "2025/01/02", "dateTo": "abc"}).params
        assert (params.date_from.year, params.date_from.month, params.date_from.day) == (2025, 1, 2)
        assert params.date_to is None

    def test_non_list_selected_weeks(self):
        assert parse_calculate_body({"selectedWeeks": "2025-W01"}).params.selected_weeks is None
