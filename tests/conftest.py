"""
Safety Stock Calculator -- 測試共用設施

提供：
1. SafetyStockCalculator instance fixture
2. 浮點數比較 helper（帶 tolerance）
3. Trace formatter（可貼到 Excel 對照）
4. Mock SalesData builder
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

# 確保 src/ 在 import path 中
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.calculator import SafetyStockCalculator

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def calculator():
    """建立乾淨的 SafetyStockCalculator instance。"""
    return SafetyStockCalculator()


# ============================================================================
# Assertion Helpers
# ============================================================================

def assert_close(actual: float, expected: float, tolerance: float = 0.01, msg: str = "") -> None:
    """
    比較兩個浮點數，允許 tolerance 範圍內的誤差。

    Args:
        actual: 實際值
        expected: 預期值
        tolerance: 容許誤差（預設 0.01）
        msg: 額外錯誤訊息
    """
    diff = abs(actual - expected)
    assert diff <= tolerance, (
        f"{msg}actual={actual}, expected={expected}, diff={diff}, tolerance={tolerance}"
    )


def assert_close_pct(actual: float, expected: float, pct: float = 1.0, msg: str = "") -> None:
    """
    比較兩個浮點數，允許百分比誤差。

    Args:
        actual: 實際值
        expected: 預期值
        pct: 容許百分比誤差（預設 1.0%）
        msg: 額外錯誤訊息
    """
    if expected == 0:
        assert actual == 0, f"{msg}expected 0, got {actual}"
        return
    diff_pct = abs(actual - expected) / abs(expected) * 100
    assert diff_pct <= pct, (
        f"{msg}actual={actual}, expected={expected}, diff={diff_pct:.2f}%, tolerance={pct}%"
    )


# ============================================================================
# Trace Formatter（輸出可貼到 Excel 對照的格式）
# ============================================================================

def format_trace(
    label: str,
    values: list[float],
    mean: float,
    std: float,
    cv: float | None = None,
    outliers: list[int] | None = None,
) -> str:
    """
    格式化計算 trace，方便貼到 Excel 對照。

    Returns:
        多行字串，包含輸入序列、中間值、最終結果
    """
    lines = [
        f"=== {label} ===",
        f"輸入序列: {values}",
        f"期數 N = {len(values)}",
        f"非零期數 = {sum(1 for v in values if v > 0)}",
        f"平均值 = {mean:.4f}",
        f"標準差 = {std:.4f}",
    ]
    if cv is not None:
        lines.append(f"CV = {cv:.4f}")
    if outliers:
        lines.append(f"離群值 index = {outliers}")
    return "\n".join(lines)


# ============================================================================
# Mock SalesData Builder
# ============================================================================

def build_mock_sales_df(
    records: list[dict],
    site: str = "1002",
) -> pd.DataFrame:
    """
    從簡易記錄建立 mock 銷貨 DataFrame。

    Args:
        records: [{"date": "2025-01-15", "sku": "SKU001", "qty": 100}, ...]
        site: 預設出貨點

    Returns:
        格式化的 DataFrame（欄位名已對應系統預期）
    """
    rows = []
    for r in records:
        rows.append({
            "date": pd.Timestamp(r["date"]),
            "site": str(r.get("site", site)),
            "sku": str(r["sku"]),
            "name": r.get("name", ""),
            "quantity": float(r["qty"]),
            "year_month": pd.Timestamp(r["date"]).strftime("%Y-%m"),
            "year_week": (
                f"{pd.Timestamp(r['date']).isocalendar()[0]}"
                f"-W{pd.Timestamp(r['date']).isocalendar()[1]:02d}"
            ),
            "date_str": pd.Timestamp(r["date"]).strftime("%Y-%m-%d"),
        })
    return pd.DataFrame(rows)


def build_monthly_records(
    sku: str,
    monthly_values: list[float],
    start_year: int = 2025,
    start_month: int = 1,
    site: str = "1002",
) -> list[dict]:
    """
    從月度值列表建立銷貨記錄（每月 15 號出貨一次）。

    Args:
        sku: 料號
        monthly_values: [100, 200, 150, ...]（每月一筆）
        start_year: 起始年
        start_month: 起始月
        site: 出貨點

    Returns:
        records list（可傳入 build_mock_sales_df）
    """
    records = []
    for i, qty in enumerate(monthly_values):
        month = start_month + i
        year = start_year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        if qty != 0:
            records.append({
                "date": f"{year}-{month:02d}-15",
                "sku": sku,
                "qty": qty,
                "site": site,
            })
    return records


def build_weekly_records(
    sku: str,
    weekly_values: list[float],
    start_date: str = "2025-01-06",
    site: str = "1002",
) -> list[dict]:
    """
    從週度值列表建立銷貨記錄（每週一出貨一次）。

    Args:
        sku: 料號
        weekly_values: [100, 200, 0, 150, ...]（每週一筆，0 表示該週不出貨）
        start_date: 第一週的週一日期
        site: 出貨點

    Returns:
        records list
    """
    records = []
    base = pd.Timestamp(start_date)
    for i, qty in enumerate(weekly_values):
        if qty != 0:
            records.append({
                "date": (base + pd.Timedelta(weeks=i)).strftime("%Y-%m-%d"),
                "sku": sku,
                "qty": qty,
                "site": site,
            })
    return records
