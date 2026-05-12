"""
Utility functions for SS Automation.
共用工具函數模組
"""

from datetime import datetime, timedelta


def format_month_display(yyyymm: str | None) -> str:
    """
    Format YYYYMM to YYYY/MM for display.

    Args:
        yyyymm: Month string in YYYYMM format (e.g., "202512")

    Returns:
        Formatted string "YYYY/MM" or empty string if invalid

    Example:
        >>> format_month_display("202512")
        "2025/12"
    """
    if not yyyymm or len(yyyymm) < 6:
        return ""
    try:
        year = yyyymm[:4]
        month = int(yyyymm[4:6])
        return f"{year}/{month}"
    except (ValueError, IndexError):
        return ""


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


def parse_yyyymm(yyyymm: str) -> tuple[int, int] | None:
    """
    Parse YYYYMM string to (year, month) tuple.

    Args:
        yyyymm: Month string in YYYYMM format

    Returns:
        Tuple of (year, month) or None if invalid
    """
    if not yyyymm or len(yyyymm) < 6:
        return None
    try:
        year = int(yyyymm[:4])
        month = int(yyyymm[4:6])
        if 1 <= month <= 12:
            return (year, month)
        return None
    except (ValueError, IndexError):
        return None


def create_composite_key(site: str, sku: str, delimiter: str = "|||") -> str:
    """
    Create composite key from site and SKU.

    Args:
        site: Site/warehouse code
        sku: Material number
        delimiter: Key delimiter (default: "|||")

    Returns:
        Composite key string
    """
    return f"{site}{delimiter}{sku}"


def parse_composite_key(key: str, delimiter: str = "|||") -> tuple[str, str]:
    """
    Parse composite key to site and SKU.

    Args:
        key: Composite key string
        delimiter: Key delimiter (default: "|||")

    Returns:
        Tuple of (site, sku)
    """
    parts = key.split(delimiter)
    if len(parts) >= 2:
        return (parts[0], parts[1])
    return ("", key)


def status_to_chinese(status_value: str) -> str:
    """
    Convert status value to Chinese display text.

    Args:
        status_value: Status enum value (red, green, blue, gray)

    Returns:
        Chinese display text with emoji
    """
    mapping = {
        "red": " 缺貨風險",
        "green": " 健康",
        "blue": " 呆滯風險",
        "gray": " 無資料",
    }
    return mapping.get(status_value, str(status_value))


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """
    Safe division that returns default on division by zero.

    Args:
        numerator: The numerator
        denominator: The denominator
        default: Default value if denominator is zero

    Returns:
        Division result or default
    """
    if denominator == 0:
        return default
    return numerator / denominator


def clamp(value: float, min_value: float, max_value: float) -> float:
    """
    Clamp a value to a range.

    Args:
        value: Value to clamp
        min_value: Minimum allowed value
        max_value: Maximum allowed value

    Returns:
        Clamped value
    """
    return max(min_value, min(max_value, value))

# 在文件末尾添加以下內容：

# ============================================================================
# 新增函數（用於 Flask 移動平均分析 v4.2.1）
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
    """解析 YYYY-MM 格式（不同於 parse_yyyymm 的 YYYYMM）"""
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


def format_number(value: float, decimals: int = 0) -> str:
    """格式化數字顯示（千分位）"""
    if decimals == 0:
        return f"{int(value):,}"
    else:
        return f"{value:,.{decimals}f}"


def calculate_percentage_change(old_value: float, new_value: float) -> float:
    """計算百分比變化"""
    if old_value == 0:
        return 0.0
    return ((new_value - old_value) / old_value) * 100


def truncate_string(text: str, max_length: int = 30, suffix: str = "...") -> str:
    """截斷過長的字串"""
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix
