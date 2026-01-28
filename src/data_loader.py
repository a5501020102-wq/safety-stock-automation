"""
Data loader for SS Automation.
資料載入模組 - 處理 Excel 讀取、欄位對照與驗證

This module handles loading and validation of input Excel files:
- Sales data with automatic column mapping
- Price data
- Inventory plan data (v4.1.0)

Version: 4.2.0 (Optimized)
Author: 松鼠
Last Updated: 2025-01-14

Changelog v4.2.0:
- Fixed: 循環導入問題（使用 models.py）
- Improved: 更清晰的 import 結構
- Optimized: 日期處理向量化
- Optimized: 欄位模式緩存
- Maintained: 所有原有功能

Configuration:
    Uses config.column_mapping for flexible column name mapping.

File Formats:
    Sales Data:
        Required: site, sku, date, quantity
        Optional: name, price, stock

    Price Data:
        Required: sku, price

    Plan Data:
        Required: site, sku, current_stock, month columns (YYYYMM)
        Optional: demand, supply, transfer_in, transfer_out, independent_demand

Examples:
    >>> from data_loader import load_sales_data, load_price_data
    >>>
    >>> # Load sales data
    >>> sales_data = load_sales_data("sales.xlsx")
    >>> print(f"Loaded {sales_data.record_count} records")
    >>>
    >>> # Load price data
    >>> price_data = load_price_data("price.xlsx")
    >>> print(f"Loaded {len(price_data.price_map)} prices")
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from .config_loader import config
# ✅ v4.2.0: 從 models 導入共用數據類別
from .models import (
    MonthlyPlanData,
    PlanData,
    PlanItemData,
    SalesData,
    PriceData,
    KEY_DELIMITER,
)

# Configure logging
logger = logging.getLogger(__name__)


class DataLoadError(Exception):
    """Data loading related errors."""
    pass


# ============================================================================
# Column Mapping Helper
# ============================================================================

class ColumnMapper:
    """
    Handles flexible column name mapping from config.

    Maps user-defined column names to standard internal names.
    This allows the system to work with different Excel templates.

    v4.2.0: 兼容 column_mapping 和 column_aliases
    """

    def __init__(self):
        """Initialize with mappings from config."""
        # ✅ 兼容兩種配置鍵名
        self.mappings = config._config.get('column_mapping', {})

        if not self.mappings:
            # 如果 column_mapping 不存在，嘗試使用 column_aliases
            self.mappings = config._config.get('column_aliases', {})

        if not self.mappings:
            logger.warning(
                "配置檔案中未找到 column_mapping 或 column_aliases，"
                "將無法進行欄位對照"
            )
        else:
            logger.debug(f"載入欄位對照: {len(self.mappings)} 個標準欄位")

    def get_standard_name(self, user_column: str) -> str | None:
        """
        Get standard column name from user column name.

        Args:
            user_column: Column name from Excel file

        Returns:
            Standard column name or None if not mapped
        """
        user_lower = user_column.lower().strip()

        for standard_name, variants in self.mappings.items():
            # 兼容不同的配置格式
            if isinstance(variants, list):
                # 列表格式：['出貨日期', 'Date']
                if user_lower in [v.lower() for v in variants]:
                    return standard_name
            elif isinstance(variants, str):
                # 字串格式：單一值
                if user_lower == variants.lower():
                    return standard_name

        return None

    def map_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Rename DataFrame columns to standard names.

        Args:
            df: Input DataFrame with user column names

        Returns:
            DataFrame with standard column names
        """
        rename_dict = {}

        for col in df.columns:
            standard = self.get_standard_name(str(col))
            if standard:
                rename_dict[col] = standard

        if rename_dict:
            df = df.rename(columns=rename_dict)
            logger.debug(f"欄位對照成功: {rename_dict}")
        else:
            logger.warning("未對照到任何欄位，可能導致後續錯誤")

        return df


# ============================================================================
# Sales Data Loader
# ============================================================================

def load_sales_data(file_path: str | Path) -> SalesData:
    """
    Load sales data from Excel file.

    Args:
        file_path: Path to Excel file

    Returns:
        SalesData object with loaded and validated data

    Raises:
        DataLoadError: If file cannot be loaded or required columns missing
        FileNotFoundError: If file does not exist
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"銷貨資料檔案不存在: {file_path}")

    logger.info(f"載入銷貨資料: {file_path}")

    try:
        # Read Excel file
        df = pd.read_excel(file_path)
        logger.debug(f"原始資料: {len(df)} 列, {len(df.columns)} 欄")

        # Map columns to standard names
        mapper = ColumnMapper()
        df = mapper.map_columns(df)

        # Validate required columns
        required_cols = ['site', 'sku', 'date', 'quantity']
        missing_cols = set(required_cols) - set(df.columns)

        if missing_cols:
            raise DataLoadError(
                f"缺少必要欄位: {missing_cols}\n"
                f"可用欄位: {list(df.columns)}"
            )

        # Process date column and add year_month (vectorized)
        df, skipped_count = _process_date_column_vectorized(df)

        # Get available sites
        available_sites = df['site'].unique().tolist() if 'site' in df.columns else []

        # Check for optional columns
        has_stock_data = 'stock' in df.columns
        has_price_data = 'price' in df.columns

        # Clean data
        df = _clean_sales_data(df)

        logger.info(
            f"✓ 載入完成: {len(df)} 筆有效記錄 "
            f"(跳過 {skipped_count} 筆無效日期)"
        )

        return SalesData(
            df=df,
            available_sites=available_sites,
            has_stock_data=has_stock_data,
            has_price_data=has_price_data,
            record_count=len(df),
            skipped_date_count=skipped_count,
        )

    except Exception as e:
        logger.error(f"載入銷貨資料失敗: {e}")
        raise DataLoadError(f"載入銷貨資料失敗: {e}") from e


def _process_date_column_vectorized(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """
    Process date column and add year_month field (vectorized for performance).

    Args:
        df: DataFrame with 'date' column

    Returns:
        Tuple of (processed DataFrame, skipped_count)
    """
    try:
        original_count = len(df)

        # Convert dates (handles datetime, string, numeric)
        df['parsed_date'] = pd.to_datetime(df['date'], errors='coerce')

        # Create year_month
        df['year_month'] = df['parsed_date'].dt.strftime('%Y-%m')

        # Count and remove invalid dates
        skipped_count = df['year_month'].isna().sum()
        df = df[df['year_month'].notna()].copy()

        # Cleanup
        df = df.drop(columns=['parsed_date'])

        logger.debug(f"向量化日期處理: {original_count} → {len(df)} 筆")

        return df, int(skipped_count)

    except Exception as e:
        logger.warning(f"向量化日期處理失敗，使用備用方案: {e}")
        return _process_date_column_fallback(df)


def _process_date_column_fallback(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """
    Fallback: Process date column row-by-row (original implementation).

    Used when vectorized processing fails.
    """
    skipped_count = 0
    year_months = []

    for idx, row in df.iterrows():
        date_val = row['date']

        try:
            if pd.isna(date_val):
                year_months.append(None)
                skipped_count += 1
                continue

            # Handle different date types
            if isinstance(date_val, datetime):
                dt = date_val
            elif isinstance(date_val, str):
                dt = pd.to_datetime(date_val)
            elif isinstance(date_val, (int, float)):
                dt = pd.to_datetime(date_val, origin='1899-12-30', unit='D')
            else:
                year_months.append(None)
                skipped_count += 1
                continue

            year_month = f"{dt.year}-{dt.month:02d}"
            year_months.append(year_month)

        except Exception as e:
            logger.debug(f"第 {idx} 列日期格式無效: {date_val} ({e})")
            year_months.append(None)
            skipped_count += 1

    df['year_month'] = year_months
    df = df[df['year_month'].notna()].copy()

    return df, skipped_count


def _clean_sales_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean sales data.

    - Remove rows with missing SKU
    - Ensure quantity is numeric and >= 0
    - Clean string fields

    Args:
        df: Input DataFrame

    Returns:
        Cleaned DataFrame
    """
    # Remove rows with missing SKU
    df = df[df['sku'].notna()].copy()

    # Clean SKU (remove whitespace)
    df['sku'] = df['sku'].astype(str).str.strip()

    # Ensure quantity is numeric
    df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce').fillna(0)

    # Remove negative quantities
    df = df[df['quantity'] >= 0].copy()

    # Clean optional string fields
    if 'name' in df.columns:
        df['name'] = df['name'].fillna('').astype(str).str.strip()

    # Ensure numeric fields are float
    if 'price' in df.columns:
        df['price'] = pd.to_numeric(df['price'], errors='coerce').fillna(0)

    if 'stock' in df.columns:
        df['stock'] = pd.to_numeric(df['stock'], errors='coerce')

    return df


# ============================================================================
# Price Data Loader
# ============================================================================

def load_price_data(file_path: str | Path) -> PriceData:
    """
    Load price data from Excel file.

    Args:
        file_path: Path to Excel file

    Returns:
        PriceData object with SKU->price mapping

    Raises:
        DataLoadError: If file cannot be loaded or required columns missing
        FileNotFoundError: If file does not exist
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"單價資料檔案不存在: {file_path}")

    logger.info(f"載入單價資料: {file_path}")

    try:
        # Read Excel file
        df = pd.read_excel(file_path)

        # Map columns
        mapper = ColumnMapper()
        df = mapper.map_columns(df)

        # Validate required columns
        if 'sku' not in df.columns or 'price' not in df.columns:
            raise DataLoadError(
                f"單價資料缺少必要欄位 (sku, price)\n"
                f"可用欄位: {list(df.columns)}"
            )

        # Clean data
        df = df[df['sku'].notna()].copy()
        df['sku'] = df['sku'].astype(str).str.strip()
        df['price'] = pd.to_numeric(df['price'], errors='coerce').fillna(0)

        # Remove zero/negative prices
        df = df[df['price'] > 0].copy()

        # Create price mapping (if duplicate SKUs, use last)
        price_map = dict(zip(df['sku'], df['price']))

        logger.info(f"✓ 載入完成: {len(price_map)} 個 SKU 價格")

        return PriceData(
            price_map=price_map,
            record_count=len(price_map),
        )

    except Exception as e:
        logger.error(f"載入單價資料失敗: {e}")
        raise DataLoadError(f"載入單價資料失敗: {e}") from e


# ============================================================================
# Plan Data Loader (v4.1.0)
# ============================================================================

def load_plan_data(file_path: str | Path) -> PlanData:
    """
    Load inventory plan data from Excel file (v4.1.0).

    Expected format:
    - Columns: site, sku, current_stock, demand_YYYYMM, supply_YYYYMM, etc.
    - Each row represents one SKU's plan
    - Month columns detected automatically by YYYYMM pattern

    Args:
        file_path: Path to Excel file

    Returns:
        PlanData object with loaded plan data

    Raises:
        DataLoadError: If file cannot be loaded or format invalid
        FileNotFoundError: If file does not exist
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"庫存計劃檔案不存在: {file_path}")

    logger.info(f"載入庫存計劃: {file_path}")

    try:
        # Read Excel file
        df = pd.read_excel(file_path)

        # Map columns
        mapper = ColumnMapper()
        df = mapper.map_columns(df)

        # Validate basic columns
        required_cols = ['site', 'sku', 'current_stock']
        missing_cols = set(required_cols) - set(df.columns)

        if missing_cols:
            raise DataLoadError(
                f"庫存計劃缺少必要欄位: {missing_cols}\n"
                f"可用欄位: {list(df.columns)}"
            )

        # Detect month columns (YYYYMM pattern)
        detected_months = _detect_month_columns(df.columns)

        if not detected_months:
            logger.warning("未偵測到任何月份欄位 (YYYYMM 格式)")
            detected_months = []

        logger.info(f"偵測到 {len(detected_months)} 個月份: {detected_months}")

        # Check if using cumulative columns format
        has_cumulative = any('累計' in col or 'cumulative' in col.lower()
                             for col in df.columns)

        # Parse plan data
        plan_data = PlanData(
            detected_months=sorted(detected_months),
            has_cumulative_columns=has_cumulative,
        )

        # Process each row
        for _, row in df.iterrows():
            try:
                item = _convert_row_to_plan_item(row, detected_months, has_cumulative)
                if item:
                    plan_data.add_item(item.site, item.sku, item)
            except Exception as e:
                logger.warning(f"解析計劃資料列失敗: {e}")
                continue

        logger.info(f"✓ 載入完成: {len(plan_data.items)} 個品項計劃")

        return plan_data

    except Exception as e:
        logger.error(f"載入庫存計劃失敗: {e}")
        raise DataLoadError(f"載入庫存計劃失敗: {e}") from e


def _detect_month_columns(columns: pd.Index | list[str]) -> list[str]:
    """
    Detect month columns from column names.

    Looks for YYYYMM pattern in column names.

    Args:
        columns: Column names (pandas Index or list)

    Returns:
        Sorted list of unique YYYYMM strings

    Examples:
        >>> cols = ['site', 'sku', 'demand_202501', 'supply_202501', 'demand_202502']
        >>> _detect_month_columns(cols)
        ['202501', '202502']
    """
    month_pattern = re.compile(r'(\d{6})')  # YYYYMM
    months: set[str] = set()

    for col in columns:
        matches = month_pattern.findall(str(col))
        for match in matches:
            # Validate it's a real month (01-12)
            try:
                year = int(match[:4])
                month = int(match[4:6])
                if 1 <= month <= 12 and 2000 <= year <= 2100:
                    months.add(match)
            except ValueError:
                continue

    return sorted(months)


def _convert_row_to_plan_item(
        row: pd.Series,
        detected_months: list[str],
        has_cumulative: bool,
) -> PlanItemData | None:
    """
    Convert a DataFrame row to PlanItemData.

    Args:
        row: DataFrame row
        detected_months: List of detected month strings (YYYYMM)
        has_cumulative: Whether data uses cumulative format

    Returns:
        PlanItemData or None if row is invalid
    """
    # Get basic info
    site = str(row.get('site', '')).strip()
    sku = str(row.get('sku', '')).strip()

    if not site or not sku:
        return None

    try:
        current_stock = float(row.get('current_stock', 0))
    except (ValueError, TypeError):
        current_stock = 0.0

    # Create item
    item = PlanItemData(
        site=site,
        sku=sku,
        current_stock=current_stock,
    )

    # Parse monthly data
    for month in detected_months:
        month_data = _extract_month_data(row, month, has_cumulative)
        if month_data:
            item.months[month] = month_data

    return item


@lru_cache(maxsize=128)
def _get_column_patterns(month: str) -> dict[str, list[str]]:
    """
    Get column name patterns for a specific month (cached for performance).

    Args:
        month: Month string (YYYYMM)

    Returns:
        Dictionary of field -> possible column names
    """
    return {
        'demand': [f'demand_{month}', f'需求_{month}', f'實際需求_{month}'],
        'supply': [f'supply_{month}', f'供給_{month}', f'實際供給_{month}'],
        'transfer_in': [f'transfer_in_{month}', f'調撥入_{month}', f'入庫_{month}'],
        'transfer_out': [f'transfer_out_{month}', f'調撥出_{month}', f'出庫_{month}'],
        'independent_demand': [f'independent_{month}', f'獨立需求_{month}'],
    }


def _extract_month_data(
        row: pd.Series,
        month: str,
        has_cumulative: bool,
) -> MonthlyPlanData | None:
    """
    Extract monthly plan data from row.

    Looks for columns like:
    - demand_202501, supply_202501
    - 需求_202501, 供給_202501
    - etc.

    Args:
        row: DataFrame row
        month: Month string (YYYYMM)
        has_cumulative: Whether using cumulative format

    Returns:
        MonthlyPlanData or None if no data for this month
    """
    # Get cached patterns
    patterns = _get_column_patterns(month)

    # Extract values
    values = {}
    for field, possible_cols in patterns.items():
        val = 0.0
        for col in possible_cols:
            if col in row.index:
                try:
                    val = float(row[col])
                    break
                except (ValueError, TypeError):
                    continue
        values[field] = val

    # Check if any non-zero value exists
    if all(v == 0 for v in values.values()):
        return None

    # Create MonthlyPlanData
    # net_change will be calculated in __post_init__
    return MonthlyPlanData(
        month=month,
        demand=values['demand'],
        supply=values['supply'],
        transfer_in=values['transfer_in'],
        transfer_out=values['transfer_out'],
        independent_demand=values['independent_demand'],
    )


# ============================================================================
# Utility Functions
# ============================================================================

def validate_file_format(file_path: Path, expected_format: str = 'xlsx') -> bool:
    """
    Validate file format.

    Args:
        file_path: Path to file
        expected_format: Expected file extension

    Returns:
        True if valid, False otherwise
    """
    return file_path.suffix.lower() == f'.{expected_format}'


def get_file_info(file_path: Path) -> dict[str, Any]:
    """
    Get file information.

    Args:
        file_path: Path to file

    Returns:
        Dictionary with file info (size, modified time, etc.)
    """
    if not file_path.exists():
        return {}

    stat = file_path.stat()

    return {
        'name': file_path.name,
        'size_bytes': stat.st_size,
        'size_mb': round(stat.st_size / (1024 * 1024), 2),
        'modified': datetime.fromtimestamp(stat.st_mtime),
    }