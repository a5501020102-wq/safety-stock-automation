"""
SAP MM17 匯出（大量維護安全庫存）。

欄位結構是下游 SAP 匯入依賴的格式，不可變動：
- MATNR: 料號（物料編號）
- WERKS: 工廠/出貨點
- EISBE: 安全庫存（整數）
"""

from __future__ import annotations

import logging
from io import BytesIO
from typing import Any

import pandas as pd

from src.value_utils import safe_float

logger = logging.getLogger(__name__)

SAP_COLUMNS = ["MATNR", "WERKS", "EISBE"]
SAP_SHEET_NAME = "SAP_MM17"
# 各欄寬度（Excel 字元寬）
SAP_COLUMN_WIDTHS = {"A:A": 18, "B:B": 12, "C:C": 12}
SAP_HEADER_FORMAT = {"bold": True, "bg_color": "#4472C4", "font_color": "white", "border": 1}


def _sap_rows(results: list[Any]) -> list[dict[str, Any]]:
    """轉成 SAP 欄位；安全庫存四捨五入為整數，沒有料號的列略過。"""
    rows = []
    for r in results:
        matnr = str(getattr(r, "sku", "")).strip()
        werks = str(getattr(r, "site", "")).strip()
        if not matnr:
            logger.warning(f" 跳過無料號的數據：site={werks}")
            continue
        eisbe = int(round(safe_float(getattr(r, "safety_stock", 0), 0)))
        rows.append({"MATNR": matnr, "WERKS": werks, "EISBE": eisbe})
    return rows


def _to_csv(df: pd.DataFrame, include_header: bool) -> bytes:
    output = BytesIO()
    # utf-8-sig 讓 Excel 直接開啟 CSV 時能正確顯示中文
    df.to_csv(output, index=False, header=include_header, encoding="utf-8-sig")
    output.seek(0)
    return output.read()


def _to_xlsx(df: pd.DataFrame, include_header: bool) -> bytes:
    output = BytesIO()
    try:
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            df.to_excel(writer, sheet_name=SAP_SHEET_NAME, index=False, header=include_header)
            worksheet = writer.sheets[SAP_SHEET_NAME]
            for column_range, width in SAP_COLUMN_WIDTHS.items():
                worksheet.set_column(column_range, width)
            if include_header:
                header_format = writer.book.add_format(SAP_HEADER_FORMAT)
                for col_num, value in enumerate(df.columns):
                    worksheet.write(0, col_num, value, header_format)
    except ImportError as err:
        raise ImportError("請安裝 xlsxwriter: pip install xlsxwriter") from err
    output.seek(0)
    return output.read()


def export_to_sap_mm17(
        results: list[Any],
        summary: Any,
        format: str = "xlsx",
        include_header: bool = True,
) -> bytes:
    """
    匯出為 SAP MM17 格式

    Args:
        results: 計算結果列表
        summary: 計算摘要（保留參數以維持呼叫介面，目前未使用）
        format: 'xlsx' 或 'csv'
        include_header: 是否包含檔頭

    Returns:
        檔案的二進位內容
    """
    if not results:
        raise ValueError("無計算結果可匯出")

    rows = _sap_rows(results)
    if not rows:
        raise ValueError("無有效數據可匯出至 SAP MM17")
    logger.info(f" 準備完成：{len(rows)} 筆 SAP MM17 數據，格式: {format}")

    df = pd.DataFrame(rows)[SAP_COLUMNS]
    if format == "csv":
        return _to_csv(df, include_header)
    if format == "xlsx":
        return _to_xlsx(df, include_header)
    raise ValueError(f"不支援的格式: {format}")
