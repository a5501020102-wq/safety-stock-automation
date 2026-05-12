"""
Data loader for SS Automation.
資料載入模組 - 處理 Excel 讀取、欄位對照與驗證

This module handles loading and validation of input Excel files:
- Sales data with automatic column mapping (+ fallback aliases)
- Price data (+ fallback aliases)
- Inventory plan data (v4.1.0)

Version: 4.2.3 (支援出貨/退貨日期欄位)
Author: 松鼠
Last Updated: 2026-01-28

Key changes in v4.2.3:
- 新增「出貨/退貨日期」→ date (關鍵修復！)
- 新增「品名」→ name 的完整映射
- 優化日誌輸出（顯示出貨點、資料範圍）
- 更清楚的錯誤訊息

Previous changes (v4.2.1):
- Sales/Price 都加入 fallback column aliases（當 config mapping 沒命中時）
- Sales fallback log 補 missing_after，方便 debug
- Date vectorized 兼容 Excel serial number（數字日期）
- 更一致的欄位清洗（site/sku/quantity/price）
"""

import logging
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from .config_loader import config
from .models import (
    MonthlyPlanData,
    PlanData,
    PlanItemData,
    PriceData,
    SalesData,
)

logger = logging.getLogger(__name__)


class DataLoadError(Exception):
    """Data loading related errors."""
    pass


# =============================================================================
# Column Mapping Helper
# =============================================================================

class ColumnMapper:
    """
    Handles flexible column name mapping from config.

    v4.2.x: 兼容 column_mapping 和 column_aliases
    """

    def __init__(self):
        self.mappings = config._config.get("column_mapping", {}) or config._config.get("column_aliases", {})

        if not self.mappings:
            logger.warning(
                "配置檔案中未找到 column_mapping 或 column_aliases，將使用 fallback aliases"
            )
        else:
            logger.debug(f"載入欄位對照: {len(self.mappings)} 個標準欄位")

    def get_standard_name(self, user_column: str) -> str | None:
        user_lower = user_column.lower().strip()

        for standard_name, variants in self.mappings.items():
            if isinstance(variants, list):
                if user_lower in [str(v).lower().strip() for v in variants]:
                    return standard_name
            elif isinstance(variants, str):
                if user_lower == variants.lower().strip():
                    return standard_name

        return None

    def map_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        rename_dict: dict[Any, str] = {}

        for col in df.columns:
            standard = self.get_standard_name(str(col))
            if standard:
                rename_dict[col] = standard

        if rename_dict:
            df = df.rename(columns=rename_dict)
            logger.debug(f"欄位對照成功: {rename_dict}")
        else:
            logger.debug("Config mapping 未命中任何欄位，將使用 fallback aliases")

        return df


# =============================================================================
# Common Helpers
# =============================================================================

def _apply_fallback_aliases(
        df: pd.DataFrame,
        required_cols: list[str],
        aliases: dict[str, str],
        context: str,
) -> pd.DataFrame:
    """
    Apply built-in fallback aliases when config mapping didn't hit.

    - 只在 required_cols 缺欄位時才啟用
    - log 會印 missing_before / missing_after / columns
    """
    missing_before = set(required_cols) - set(df.columns)
    if not missing_before:
        logger.debug(f"{context}: 所有必要欄位已存在，不需要 fallback")
        return df

    # 執行 fallback 映射
    rename_dict = {k: v for k, v in aliases.items() if k in df.columns}
    if rename_dict:
        df = df.rename(columns=rename_dict)
        logger.info(f" {context} fallback 映射: {rename_dict}")

    missing_after = set(required_cols) - set(df.columns)

    if missing_after:
        logger.warning(
            f" {context} 欄位驗證：\n"
            f"   Config mapping 前缺少: {missing_before}\n"
            f"   Fallback mapping 後仍缺: {missing_after}\n"
            f"   目前欄位: {list(df.columns)}"
        )
    else:
        logger.info(f" {context} 所有必要欄位已就緒")

    return df


def _normalize_string_col(df: pd.DataFrame, col: str) -> None:
    """In-place normalize for string-ish identifier columns.

    處理 Excel 數字欄位轉字串時的 float 尾巴問題：
    1002.0 → "1002"（而非 "1002.0"）
    """
    if col in df.columns:
        def _to_clean_str(val: object) -> str:
            if pd.isna(val):
                return ""
            # 如果是 float 且可以無損轉成 int（例如 1002.0），去掉 .0
            if isinstance(val, float) and val == int(val):
                return str(int(val)).strip()
            return str(val).strip()

        df[col] = df[col].apply(_to_clean_str)


# =============================================================================
# Sales Data Loader
# =============================================================================

def load_sales_data(file_path: str | Path) -> SalesData:
    """
    載入銷貨資料 - 完整修復版 v4.2.3

    支援欄位格式：
    - 出貨/退貨日期、出貨點、料號、品名、數量
    - 或其他類似名稱（見 sales_aliases）
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"銷貨資料檔案不存在: {file_path}")

    logger.info(f" 載入銷貨資料: {file_path.name}")

    try:
        # 讀取 Excel
        df = pd.read_excel(file_path)
        logger.info(f" 讀取成功: {len(df)} 列, {len(df.columns)} 欄")
        logger.info(f" 原始欄位: {list(df.columns)}")

        # Step 1: 嘗試 config mapping
        mapper = ColumnMapper()
        df = mapper.map_columns(df)
        logger.debug(f" Config mapping 後: {list(df.columns)}")

        # Step 2: Fallback aliases（銷貨）- v4.2.3 完整版
        required_cols = ["site", "sku", "date", "quantity"]
        sales_aliases = {
            # 出貨點 / 倉庫
            "出貨點": "site",
            "工廠": "site",
            "銷售組織": "site",
            "倉別": "site",
            "倉庫": "site",
            "據點": "site",

            # SKU / 料號
            "料號": "sku",
            "品號": "sku",
            "物料": "sku",
            "物料編號": "sku",
            "產品編號": "sku",
            "料件編號": "sku",

            # 品名（可選）
            "品名": "name",
            "產品名稱": "name",
            "料品名稱": "name",
            "名稱": "name",
            "品項": "name",

            # 數量
            "數量": "quantity",
            "出貨數量": "quantity",
            "出貨量": "quantity",
            "銷貨數量": "quantity",
            "銷售數量": "quantity",

            # 日期 - 關鍵修復！
            "出貨/退貨日期": "date", # 用戶的 Excel 格式
            "出貨/交易日期": "date",
            "出貨/總受日期": "date",
            "讓貨日期": "date",
            "出貨日期": "date",
            "退貨日期": "date",
            "交易日期": "date",
            "銷貨日期": "date",
            "單據日期": "date",
            "日期": "date",
        }

        df = _apply_fallback_aliases(df, required_cols, sales_aliases, context="銷貨資料")
        logger.info(f" Fallback mapping 後: {list(df.columns)}")

        # Step 3: Validate required columns
        missing_cols = set(required_cols) - set(df.columns)
        if missing_cols:
            raise DataLoadError(
                f" 缺少必要欄位: {missing_cols}\n"
                f" 您的檔案欄位: {list(df.columns)}\n\n"
                f" 提示：系統需要以下欄位（或類似名稱）：\n"
                f" 出貨點 (或: 倉庫、工廠、據點)\n"
                f" 料號 (或: 產品編號、物料編號、品號)\n"
                f" 數量 (或: 出貨數量、銷貨數量)\n"
                f" 日期 (或: 出貨/退貨日期、出貨日期)\n"
                f"   (可選) 品名 (或: 產品名稱)"
            )

        # Step 4: Normalize string columns
        _normalize_string_col(df, "site")
        _normalize_string_col(df, "sku")

        if "name" in df.columns:
            _normalize_string_col(df, "name")

        # Step 5: Process date column (vectorized)
        df, skipped_count, max_date = _process_date_column_vectorized(df)

        # Step 6: Get available sites
        available_sites = df["site"].unique().tolist()
        logger.info(f" 偵測到 {len(available_sites)} 個出貨點: {available_sites}")

        # Step 7: Check optional columns
        has_stock_data = "stock" in df.columns
        has_price_data = "price" in df.columns

        # Step 8: Clean data
        df = _clean_sales_data(df)

        # Step 9: Log summary
        logger.info(
            f" 載入完成: {len(df)} 筆有效記錄 "
            f"(跳過 {skipped_count} 筆無效日期)"
        )

        if len(df) > 0:
            date_range = f"{df['year_month'].min()} ~ {df['year_month'].max()}"
            logger.info(f" 資料範圍: {date_range}")
            logger.info(f" SKU 數量: {df['sku'].nunique()} 個")
            if max_date:
                logger.info(f" 資料最大日期: {max_date.strftime('%Y-%m-%d')}")

        # 提取可用的 ISO 週列表（供週模式選擇器使用）
        available_weeks: list[str] = []
        if "year_week" in df.columns:
            available_weeks = sorted(df["year_week"].dropna().unique().tolist())

        return SalesData(
            df=df,
            available_sites=available_sites,
            has_stock_data=has_stock_data,
            has_price_data=has_price_data,
            record_count=len(df),
            skipped_date_count=skipped_count,
            max_date=max_date,
            available_weeks=available_weeks,
        )

    except Exception as e:
        logger.error(f" 載入銷貨資料失敗: {e}")
        raise DataLoadError(f"載入銷貨資料失敗: {e}") from e


def _process_date_column_vectorized(df: pd.DataFrame) -> tuple[pd.DataFrame, int, datetime | None]:
    """
    Vectorized date processing:
    - Try normal pd.to_datetime first
    - If many NaT and source looks numeric, try Excel-serial conversion
    - Returns (df, skipped_count, max_date)
    """
    try:
        original_count = len(df)

        # First pass: normal parse
        parsed = pd.to_datetime(df["date"], errors="coerce")

        # Heuristic: if too many NaT and date column looks numeric -> try Excel serial parse
        nat_ratio = float(parsed.isna().mean()) if len(parsed) > 0 else 1.0

        if nat_ratio > 0.3:
            # Try numeric conversion
            numeric = pd.to_numeric(df["date"], errors="coerce")
            numeric_ratio = float(numeric.notna().mean()) if len(numeric) > 0 else 0.0

            if numeric_ratio > 0.7:
                parsed2 = pd.to_datetime(numeric, errors="coerce", origin="1899-12-30", unit="D")
                # Keep whichever gives fewer NaT
                if parsed2.isna().sum() < parsed.isna().sum():
                    parsed = parsed2
                    logger.debug(" 日期欄位判定為 Excel serial number，已套用 origin+unit 解析")

        # Extract max_date before converting to year_month
        max_date = None
        valid_dates = parsed.dropna()
        if len(valid_dates) > 0:
            max_date = valid_dates.max().to_pydatetime()

        df = df.copy()
        df["year_month"] = parsed.dt.strftime("%Y-%m")

        iso_cal = parsed.dt.isocalendar()
        df["year_week"] = (
            iso_cal["year"].astype(str)
            + "-W"
            + iso_cal["week"].astype(str).str.zfill(2)
        )

        df["date_str"] = parsed.dt.strftime("%Y-%m-%d")

        skipped_count = int(df["year_month"].isna().sum())
        df = df[df["year_month"].notna()].copy()

        logger.debug(f" 向量化日期處理: {original_count} → {len(df)} 筆有效")
        return df, skipped_count, max_date

    except Exception as e:
        logger.warning(f" 向量化日期處理失敗，使用備用方案: {e}")
        return _process_date_column_fallback(df)


def _process_date_column_fallback(df: pd.DataFrame) -> tuple[pd.DataFrame, int, datetime | None]:
    """Fallback date processing (row by row)"""
    skipped_count = 0
    year_months: list[str | None] = []
    year_weeks: list[str | None] = []
    date_strs: list[str | None] = []
    max_date: datetime | None = None

    for idx, row in df.iterrows():
        date_val = row["date"]

        try:
            if pd.isna(date_val):
                year_months.append(None)
                year_weeks.append(None)
                date_strs.append(None)
                skipped_count += 1
                continue

            if isinstance(date_val, datetime):
                dt = date_val
            elif isinstance(date_val, str):
                dt = pd.to_datetime(date_val)
            elif isinstance(date_val, (int, float)):
                dt = pd.to_datetime(date_val, origin="1899-12-30", unit="D")
            else:
                year_months.append(None)
                year_weeks.append(None)
                date_strs.append(None)
                skipped_count += 1
                continue

            year_months.append(f"{dt.year}-{dt.month:02d}")
            iso = dt.isocalendar()
            year_weeks.append(f"{iso[0]}-W{iso[1]:02d}")
            date_strs.append(dt.strftime("%Y-%m-%d"))
            if max_date is None or dt > max_date:
                max_date = dt

        except Exception as e:
            logger.debug(f"第 {idx} 列日期格式無效: {date_val} ({e})")
            year_months.append(None)
            year_weeks.append(None)
            date_strs.append(None)
            skipped_count += 1

    df = df.copy()
    df["year_month"] = year_months
    df["year_week"] = year_weeks
    df["date_str"] = date_strs
    df = df[df["year_month"].notna()].copy()
    return df, skipped_count, max_date


def _clean_sales_data(df: pd.DataFrame) -> pd.DataFrame:
    """清洗銷貨資料"""
    df = df.copy()

    # SKU must exist and be valid
    df = df[df["sku"].notna()].copy()
    df["sku"] = df["sku"].astype(str).str.strip()
    df = df[df["sku"] != ""].copy()

    # site normalize
    if "site" in df.columns:
        df["site"] = df["site"].astype(str).str.strip()

    # quantity numeric — keep negatives (returns) for natural offset in aggregation
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0)

    # optional string columns
    if "name" in df.columns:
        df["name"] = df["name"].fillna("").astype(str).str.strip()

    # optional numeric columns
    if "price" in df.columns:
        df["price"] = pd.to_numeric(df["price"], errors="coerce").fillna(0)

    if "stock" in df.columns:
        df["stock"] = pd.to_numeric(df["stock"], errors="coerce")

    return df


# =============================================================================
# Price Data Loader
# =============================================================================

def load_price_data(file_path: str | Path) -> PriceData:
    """載入單價資料"""
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"單價資料檔案不存在: {file_path}")

    logger.info(f" 載入單價資料: {file_path.name}")

    try:
        df = pd.read_excel(file_path)
        logger.info(f" 讀取成功: {len(df)} 列")

        mapper = ColumnMapper()
        df = mapper.map_columns(df)

        # Fallback aliases（單價）
        required_cols = ["sku", "price"]
        price_aliases = {
            "料號": "sku",
            "品號": "sku",
            "物料": "sku",
            "物料編號": "sku",
            "產品編號": "sku",
            "料件編號": "sku",
            "單價": "price",
            "價格": "price",
            "含稅單價": "price",
            "未稅單價": "price",
        }
        df = _apply_fallback_aliases(df, required_cols, price_aliases, context="單價資料")

        if "sku" not in df.columns or "price" not in df.columns:
            raise DataLoadError(
                f" 單價資料缺少必要欄位 (sku, price)\n"
                f" 可用欄位: {list(df.columns)}"
            )

        # Clean data
        df = df[df["sku"].notna()].copy()
        df["sku"] = df["sku"].astype(str).str.strip()
        df["price"] = pd.to_numeric(df["price"], errors="coerce").fillna(0)

        # Remove zero/negative prices
        df = df[df["price"] > 0].copy()

        # If duplicate SKUs, keep last
        price_map = dict(zip(df["sku"], df["price"], strict=True))

        logger.info(f" 載入完成: {len(price_map)} 個 SKU 價格")

        return PriceData(
            price_map=price_map,
            record_count=len(price_map),
        )

    except Exception as e:
        logger.error(f" 載入單價資料失敗: {e}")
        raise DataLoadError(f"載入單價資料失敗: {e}") from e


# =============================================================================
# Plan Data Loader (v4.1.0)
# =============================================================================

def load_plan_data(file_path: str | Path) -> PlanData:
    """載入庫存計劃（v5.1.1: 新增 fallback aliases + MRP 欄位解析）"""
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"庫存計劃檔案不存在: {file_path}")

    logger.info(f"載入庫存計劃: {file_path.name}")

    # Plan 欄位的 fallback aliases（與 sales_aliases 的 site/sku 保持一致）
    plan_aliases: dict[str, str] = {
        # 出貨點 / 倉庫
        "出貨點": "site",
        "工廠": "site",
        "銷售組織": "site",
        "倉別": "site",
        "倉庫": "site",
        "據點": "site",
        # SKU / 料號
        "料號": "sku",
        "品號": "sku",
        "物料": "sku",
        "物料編號": "sku",
        "產品編號": "sku",
        "料件編號": "sku",
        # 品名（選填，不在 required 中）
        "品名": "name",
        "產品名稱": "name",
        "料品名稱": "name",
        "名稱": "name",
        "料號說明": "name",
        # 庫存數量
        "庫存數量": "current_stock",
        "現有庫存": "current_stock",
        "在庫量": "current_stock",
        "庫存量": "current_stock",
        "可用庫存": "current_stock",
        "期末庫存": "current_stock",
        # 月平均銷售數量（選填）
        "月平均銷售數量": "avg_monthly_demand",
        # SAP 安全庫存（選填，讀入但不顯示在前端）
        "安全庫存": "sap_safety_stock",
    }

    try:
        df = pd.read_excel(file_path)

        # Step 1: Config-based mapping（優先）
        mapper = ColumnMapper()
        df = mapper.map_columns(df)

        # Step 2: Fallback aliases（Config 未命中時啟用）
        required_cols = ["site", "sku", "current_stock"]
        df = _apply_fallback_aliases(df, required_cols, plan_aliases, "庫存計劃")

        # Step 3: 驗證必要欄位
        missing_cols = set(required_cols) - set(df.columns)
        if missing_cols:
            # 同時顯示中英文欄位名，方便使用者對照
            friendly = {"site": "工廠/出貨點", "sku": "料號", "current_stock": "庫存數量"}
            missing_zh = [f"{col}({friendly.get(col, col)})" for col in sorted(missing_cols)]
            raise DataLoadError(
                f"庫存計劃缺少必要欄位: {', '.join(missing_zh)}\n"
                f"可用欄位: {list(df.columns)}"
            )

        _normalize_string_col(df, "site")
        _normalize_string_col(df, "sku")

        # Step 4: 月份偵測（先嘗試 MRP 格式，fallback 到純 YYYYMM）
        mrp_columns = _parse_mrp_columns(df.columns)
        if mrp_columns:
            detected_months = sorted(mrp_columns.keys())
            logger.info(f"偵測到 MRP 格式欄位: {len(detected_months)} 個月份: {detected_months}")
        else:
            detected_months = _detect_month_columns(df.columns)
            mrp_columns = {}
            if not detected_months:
                logger.warning("未偵測到任何月份欄位")
            else:
                logger.info(f"偵測到 {len(detected_months)} 個月份: {detected_months}")

        has_cumulative = any(("累計" in str(col)) or ("cumulative" in str(col).lower()) for col in df.columns)

        # Step 5: 推導時間戳
        planning_horizon = (
            f"{detected_months[0]}-{detected_months[-1]}"
            if detected_months else None
        )
        source_filename = file_path.name

        plan_data = PlanData(
            detected_months=sorted(detected_months),
            has_cumulative_columns=has_cumulative,
            planning_horizon=planning_horizon,
            source_filename=source_filename,
        )

        for _, row in df.iterrows():
            try:
                item = _convert_row_to_plan_item(
                    row, detected_months, has_cumulative, mrp_columns,
                )
                if item:
                    plan_data.add_item(item.site, item.sku, item)
            except Exception as e:
                logger.warning(f"解析計劃資料列失敗: {e}")
                continue

        logger.info(f"載入完成: {len(plan_data.items)} 個品項計劃")
        return plan_data

    except DataLoadError:
        raise
    except Exception as e:
        logger.error(f"載入庫存計劃失敗: {e}")
        raise DataLoadError(f"載入庫存計劃失敗: {e}") from e


def _parse_mrp_columns(
        columns: pd.Index | list[str],
) -> dict[str, dict[str, str]]:
    """
    解析 SAP MRP 報表的複合欄位名（例如 M202604實際需求）。

    不改動 _detect_month_columns()（銷貨資料用），這是獨立的 plan 專用解析器。

    欄位格式：
      - 一般月份：M{YYYYMM}{中文維度}，例如 M202604實際需求
      - 累計前期：<=M{YYYYMM}{中文維度}，例如 <=M202603實際需求
      - 累計後期：>=M{YYYYMM}{中文維度}，例如 >=M202607計劃訂單

    回傳結構：
      {
          "202604": {
              "demand": "M202604實際需求",
              "supply": "M202604實際供給",
              "available": "M202604可用數量",
              ...
          },
          "202605": { ... },
      }
    """
    # 維度關鍵字 → 英文 key 的對應
    dimension_map: dict[str, str] = {
        "實際需求": "demand",
        "實際供給": "supply",
        "可用數量": "available",
        "計劃訂單": "planned_order",
        "獨立需求": "independent_demand",
        "調撥(出)": "transfer_out",
        "調撥(入)": "transfer_in",
    }

    # regex: 匹配 [<=|>=]M{YYYYMM}{維度}
    pattern = re.compile(r"^[<>]?=?M(\d{6})(.+)$")

    result: dict[str, dict[str, str]] = {}
    matched_count = 0

    for col in columns:
        col_str = str(col).strip()
        m = pattern.match(col_str)
        if not m:
            continue

        month_str = m.group(1)  # "202604"
        dimension_zh = m.group(2)  # "實際需求"

        # 驗證月份合理性
        try:
            year = int(month_str[:4])
            month = int(month_str[4:6])
            if not (1 <= month <= 12 and 2000 <= year <= 2100):
                continue
        except ValueError:
            continue

        # 對應維度
        dimension_en = dimension_map.get(dimension_zh)
        if not dimension_en:
            continue

        if month_str not in result:
            result[month_str] = {}
        result[month_str][dimension_en] = col_str
        matched_count += 1

    if matched_count > 0:
        logger.debug(f"MRP 欄位解析: {matched_count} 個欄位, {len(result)} 個月份")

    return result


def _detect_month_columns(columns: pd.Index | list[str]) -> list[str]:
    """偵測月份欄位（YYYYMM 格式）-- 銷貨資料用，不改動"""
    month_pattern = re.compile(r"(\d{6})")  # YYYYMM
    months: set[str] = set()

    for col in columns:
        matches = month_pattern.findall(str(col))
        for match in matches:
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
        mrp_columns: dict[str, dict[str, str]] | None = None,
) -> PlanItemData | None:
    """轉換 DataFrame 行為 PlanItemData（支援 MRP 格式和舊格式）"""
    site = str(row.get("site", "")).strip()
    sku = str(row.get("sku", "")).strip()

    if not site or not sku:
        return None

    try:
        current_stock = float(row.get("current_stock", 0))
    except (ValueError, TypeError):
        current_stock = 0.0

    item = PlanItemData(
        site=site,
        sku=sku,
        current_stock=current_stock,
    )

    for month in detected_months:
        if mrp_columns and month in mrp_columns:
            # MRP 格式：從 mrp_columns 映射讀取
            month_data = _extract_mrp_month_data(row, month, mrp_columns[month])
        else:
            # 舊格式：用原有的 pattern matching
            month_data = _extract_month_data(row, month, has_cumulative)
        if month_data:
            item.months[month] = month_data

    return item


@lru_cache(maxsize=128)
def _get_column_patterns(month: str) -> dict[str, list[str]]:
    """取得月份欄位模式（快取）"""
    return {
        "demand": [f"demand_{month}", f"需求_{month}", f"實際需求_{month}"],
        "supply": [f"supply_{month}", f"供給_{month}", f"實際供給_{month}"],
        "transfer_in": [f"transfer_in_{month}", f"調撥入_{month}", f"入庫_{month}"],
        "transfer_out": [f"transfer_out_{month}", f"調撥出_{month}", f"出庫_{month}"],
        "independent_demand": [f"independent_{month}", f"獨立需求_{month}"],
    }


def _extract_month_data(
        row: pd.Series,
        month: str,
        has_cumulative: bool,
) -> MonthlyPlanData | None:
    """提取單月資料"""
    patterns = _get_column_patterns(month)

    values: dict[str, float] = {}
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

    if all(v == 0 for v in values.values()):
        return None

    return MonthlyPlanData(
        month=month,
        demand=values["demand"],
        supply=values["supply"],
        transfer_in=values["transfer_in"],
        transfer_out=values["transfer_out"],
        independent_demand=values["independent_demand"],
    )


def _extract_mrp_month_data(
        row: pd.Series,
        month: str,
        col_map: dict[str, str],
) -> MonthlyPlanData | None:
    """從 MRP 格式的欄位提取單月資料。

    Args:
        row: DataFrame 行
        month: YYYYMM 格式月份
        col_map: 該月份的欄位映射，例如
                 {"demand": "M202604實際需求", "supply": "M202604實際供給", ...}
    """
    def _safe_float(col_name: str | None) -> float:
        if not col_name or col_name not in row.index:
            return 0.0
        try:
            val = float(row[col_name])
            return val if not pd.isna(val) else 0.0
        except (ValueError, TypeError):
            return 0.0

    demand = _safe_float(col_map.get("demand"))
    supply = _safe_float(col_map.get("supply"))
    transfer_in = _safe_float(col_map.get("transfer_in"))
    transfer_out = _safe_float(col_map.get("transfer_out"))
    independent_demand = _safe_float(col_map.get("independent_demand"))

    # SAP MRP 的消耗類欄位通常是負數（代表消耗/出庫），統一取絕對值
    # 公式 net_change = supply + transfer_in - demand - transfer_out - independent_demand
    # 需要所有值為正數才能正確計算
    if demand < 0:
        demand = abs(demand)
    if transfer_out < 0:
        transfer_out = abs(transfer_out)
    if independent_demand < 0:
        independent_demand = abs(independent_demand)

    if all(v == 0 for v in [demand, supply, transfer_in, transfer_out, independent_demand]):
        return None

    return MonthlyPlanData(
        month=month,
        demand=demand,
        supply=supply,
        transfer_in=transfer_in,
        transfer_out=transfer_out,
        independent_demand=independent_demand,
    )


# =============================================================================
# Utility Functions
# =============================================================================

def validate_file_format(file_path: Path, expected_format: str = "xlsx") -> bool:
    """驗證檔案格式"""
    return file_path.suffix.lower() == f".{expected_format}"


def get_file_info(file_path: Path) -> dict[str, Any]:
    """取得檔案資訊"""
    if not file_path.exists():
        return {}

    stat = file_path.stat()
    return {
        "name": file_path.name,
        "size_bytes": stat.st_size,
        "size_mb": round(stat.st_size / (1024 * 1024), 2),
        "modified": datetime.fromtimestamp(stat.st_mtime),
    }
