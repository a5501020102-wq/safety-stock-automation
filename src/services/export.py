"""
匯出服務：把前端送回的計算結果（camelCase JSON）還原成匯出函式可用的物件，
並產生 Excel 或 SAP MM17 檔案。API 是無狀態的，所以結果由請求本身帶回。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import Any

from src.error_codes import ErrorCode
from src.exports.excel import export_comparison_to_excel, export_to_excel
from src.exports.sap import export_to_sap_mm17

XLSX_MIMETYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV_MIMETYPE = "text/csv; charset=utf-8"
SAP_FORMATS = ("xlsx", "csv")


class ExportError(Exception):
    """可預期的匯出錯誤（例如篩選後沒有資料），route 會轉成對應錯誤碼。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ExportFile:
    content: bytes
    filename: str
    mimetype: str


def _snake(s: str) -> str:
    """camelCase -> snake_case (for reverse conversion at export boundary)."""
    if not isinstance(s, str) or not s:
        return s
    out = []
    for i, ch in enumerate(s):
        if ch.isupper() and i > 0:
            out.append("_")
            out.append(ch.lower())
        else:
            out.append(ch.lower() if ch.isupper() else ch)
    return "".join(out)


def _snake_keys(payload: dict[str, Any] | None) -> dict[str, Any]:
    return {_snake(k): v for k, v in (payload or {}).items()}


def deserialize_results(payload: list[dict[str, Any]] | None) -> list[SimpleNamespace]:
    """
    把 JSON 結果列表還原成可用 getattr 存取的物件。

    匯出函式本來就以 getattr 加字串 fallback 讀取欄位，
    所以用 SimpleNamespace 即可，不需要重建 enum。
    """
    return [SimpleNamespace(**_snake_keys(r)) for r in payload or []]


def deserialize_summary(payload: dict[str, Any] | None) -> SimpleNamespace:
    """Convert summary JSON dict into a SimpleNamespace for export functions."""
    return SimpleNamespace(**_snake_keys(payload))


def _get(body: dict[str, Any], camel: str, snake: str) -> Any:
    return body.get(camel) or body.get(snake)


def _filter_by_site(results: list[Any], site_filter: str | None) -> list[Any]:
    """依出貨點篩選；未指定或 all 時不篩選。"""
    if not site_filter or site_filter == "all":
        return results
    return [r for r in results if getattr(r, "site", None) == site_filter]


def _no_results(site_filter: str) -> ExportError:
    return ExportError(ErrorCode.NO_RESULTS, f"出貨點 {site_filter} 沒有資料")


def _site_suffix(site_filter: str | None) -> str:
    """檔名用的出貨點後綴；只保留安全字元，避免路徑或標頭注入。"""
    return f"_{re.sub(r'[^a-zA-Z0-9_-]', '_', site_filter)}" if site_filter else ""


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _is_weekly_daily(body: dict[str, Any], granularity: str, calc_params: dict[str, Any]) -> bool:
    """週模式且有選定週時，結果是以日數據計算，Excel 的欄位標題需要對應調整。"""
    selected_weeks = _get(body, "selectedWeeks", "selected_weeks") or calc_params.get("selected_weeks")
    return granularity == "weekly" and bool(selected_weeks)


def build_excel_export(body: dict[str, Any]) -> ExportFile:
    """產生 Excel 匯出檔；compare 模式含分倉、總倉與對比摘要。"""
    mode = body.get("mode", "all")
    site_filter = _get(body, "siteFilter", "site_filter")
    granularity = body.get("granularity", "monthly")
    timestamp = _timestamp()
    # 前端傳入的 calcParams 是 camelCase（來自 ParametersSnapshot）
    calc_params = _snake_keys(_get(body, "calcParams", "calc_params"))
    is_weekly_daily = _is_weekly_daily(body, granularity, calc_params)

    if mode == "compare":
        all_summary = _get(body, "allSummary", "all_summary") or {}
        total_summary = _get(body, "totalSummary", "total_summary") or {}
        all_results = deserialize_results(all_summary.get("results", []))
        total_results = deserialize_results(total_summary.get("results", []))

        if site_filter:
            # 兩邊都篩選，對比總數才會一致
            all_results = _filter_by_site(all_results, site_filter)
            total_results = _filter_by_site(total_results, site_filter)
            if not all_results and not total_results:
                raise _no_results(site_filter)

        content = export_comparison_to_excel(
            all_data=(all_results, [], deserialize_summary(all_summary.get("summary", {}))),
            total_data=(total_results, [], deserialize_summary(total_summary.get("summary", {}))),
            comparison=_snake_keys(body.get("comparison")),
            granularity=granularity,
            is_weekly_daily=is_weekly_daily,
            calc_params=calc_params or None,
        )
        filename = f"safety_stock_compare{_site_suffix(site_filter)}_{timestamp}.xlsx"
        return ExportFile(content, filename, XLSX_MIMETYPE)

    results = deserialize_results(body.get("results", []))
    if site_filter:
        results = _filter_by_site(results, site_filter)
        if not results:
            raise _no_results(site_filter)

    content = export_to_excel(
        results, [], deserialize_summary(body.get("summary", {})),
        granularity=granularity, is_weekly_daily=is_weekly_daily,
    )
    filename = f"safety_stock_{mode}{_site_suffix(site_filter)}_{timestamp}.xlsx"
    return ExportFile(content, filename, XLSX_MIMETYPE)


def build_sap_export(body: dict[str, Any]) -> ExportFile:
    """產生 SAP MM17 匯出檔；compare 模式由 sapMode 決定匯出分倉或總倉。"""
    export_format = body.get("format", "xlsx")
    if export_format not in SAP_FORMATS:
        raise ExportError(ErrorCode.INVALID_EXPORT_FORMAT, "format 必須是 xlsx 或 csv")
    site_filter = _get(body, "siteFilter", "site_filter")
    mode = body.get("mode", "all")
    include_header = bool(body.get("includeHeader", body.get("include_header", True)))
    timestamp = _timestamp()

    if mode == "compare":
        sap_mode = _get(body, "sapMode", "sap_mode") or "all"
        bucket = (
            _get(body, "totalSummary", "total_summary") if sap_mode == "total"
            else _get(body, "allSummary", "all_summary")
        ) or {}
        results = deserialize_results(bucket.get("results", []))
        summary = deserialize_summary(bucket.get("summary", {}))
        mode_suffix = sap_mode
    else:
        results = deserialize_results(body.get("results", []))
        summary = deserialize_summary(body.get("summary", {}))
        mode_suffix = mode

    if site_filter:
        results = _filter_by_site(results, site_filter)
        if not results:
            raise _no_results(site_filter)

    content = export_to_sap_mm17(
        results=results, summary=summary, format=export_format, include_header=include_header,
    )
    filename = f"sap_mm17_{mode_suffix}{_site_suffix(site_filter)}_{timestamp}.{export_format}"
    mimetype = CSV_MIMETYPE if export_format == "csv" else XLSX_MIMETYPE
    return ExportFile(content, filename, mimetype)
