"""黃金樣本比對工具的單元測試：確保比對本身不會漏報或誤報差異。"""

from tests.golden.golden_master import (
    FLOAT_TOLERANCE,
    TIMESTAMP_PLACEHOLDER,
    UUID_PLACEHOLDER,
    _diff,
    _normalize,
    build_scenarios,
)


def _collect_diffs(a, b) -> list[str]:
    out: list[str] = []
    _diff(a, b, "root", out)
    return out


class TestNormalize:
    def test_drops_volatile_keys_recursively(self):
        data = {"executedAt": "x", "summary": {"runDate": "y", "totalSkus": 3}}
        assert _normalize(data) == {"summary": {"totalSkus": 3}}

    def test_masks_timestamps_inside_strings(self):
        assert _normalize("產出時間 2026-10-28 11:05:33") == f"產出時間 {TIMESTAMP_PLACEHOLDER}"

    def test_masks_upload_uuid_filenames(self):
        name = "4fd63f07-934f-475f-b734-12e79ad6eef6.xlsx"
        assert _normalize(name) == f"{UUID_PLACEHOLDER}.xlsx"

    def test_keeps_month_level_dates(self):
        # 月份欄位（YYYY-MM）是計算結果的一部分，不可被遮蔽
        assert _normalize("2026-04") == "2026-04"


class TestDiff:
    def test_identical_structures_have_no_diff(self):
        data = {"results": [{"sku": "A", "safetyStock": 12}]}
        assert _collect_diffs(data, data) == []

    def test_detects_numeric_change(self):
        diffs = _collect_diffs({"ss": 12}, {"ss": 13})
        assert diffs == ["root.ss: 12 != 13"]

    def test_tolerates_only_serialization_noise(self):
        assert _collect_diffs({"cv": 0.1}, {"cv": 0.1 + FLOAT_TOLERANCE / 10}) == []
        assert _collect_diffs({"cv": 0.1}, {"cv": 0.1 + 1e-6}) != []

    def test_detects_missing_key_and_length_change(self):
        assert _collect_diffs({"a": 1}, {}) == ["root.a: 只存在於基準"]
        assert _collect_diffs([1, 2], [1]) == ["root: 長度 2 != 1"]

    def test_bool_is_not_compared_as_number(self):
        assert _collect_diffs({"flag": True}, {"flag": 1}) != []


def test_scenarios_cover_all_modes_and_granularities():
    scenarios = build_scenarios()
    for mode in ("all", "total", "compare"):
        for granularity in ("daily", "weekly", "monthly"):
            assert f"{mode}_{granularity}" in scenarios
