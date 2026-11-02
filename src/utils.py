"""
Utility functions for SS Automation.
共用工具函數模組
"""

from datetime import datetime, timedelta


def calculate_order_deadline(shortage_month: str, lead_time_days: int) -> str:
    """
    Calculate the latest order date to prevent shortage.

    Args:
        shortage_month: Month when shortage occurs (YYYYMM format)
        lead_time_days: Lead time in days

    Returns:
        Order deadline as YYYY-MM-DD string

    Example:
        >>> calculate_order_deadline("202512", 30)
        "2025-11-01"
    """
    try:
        year = int(shortage_month[:4])
        month = int(shortage_month[4:6])

        # First day of shortage month
        first_day = datetime(year, month, 1)

        # Subtract lead time
        deadline = first_day - timedelta(days=lead_time_days)

        return deadline.strftime("%Y-%m-%d")
    except (ValueError, IndexError):
        return ""


# ============================================================================
# 季度分組（ma-detail 端點使用）
# ============================================================================

def get_quarter(month: int) -> str:
    """取得月份對應的季度（Q1-Q4）"""
    if 1 <= month <= 3:
        return 'Q1'
    elif 4 <= month <= 6:
        return 'Q2'
    elif 7 <= month <= 9:
        return 'Q3'
    else:
        return 'Q4'


def parse_year_month(year_month_str: str) -> tuple[int, int]:
    """解析 YYYY-MM 格式，失敗回傳 (0, 0)"""
    try:
        year, month = year_month_str.split('-')
        return int(year), int(month)
    except (ValueError, AttributeError, TypeError):
        return 0, 0


def group_by_quarter(monthly_data: dict[str, float]) -> dict[str, list[tuple[str, float]]]:
    """將月度資料按季度分組（用於季度可視化）"""
    quarters = {}
    for ym, value in sorted(monthly_data.items()):
        year, month = parse_year_month(ym)
        if year == 0:
            continue
        quarter = get_quarter(month)
        quarter_key = f"{quarter} {year}"
        if quarter_key not in quarters:
            quarters[quarter_key] = []
        quarters[quarter_key].append((ym, value))
    return quarters


