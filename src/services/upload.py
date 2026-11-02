"""
上傳服務：依檔案類型選擇載入器，並整理上傳回應的中繼資料。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.data_loader import load_plan_data, load_price_data, load_sales_data

FILE_LOADERS: dict[str, Callable[[Path], Any]] = {
    "sales": load_sales_data,
    "price": load_price_data,
    "plan": load_plan_data,
}


def _sales_metadata(data: Any) -> dict[str, Any]:
    df = data.df
    has_year_month = "year_month" in df.columns
    return {
        "record_count": int(data.record_count),
        "detected_sites": list(data.available_sites),
        "detected_skus": int(df["sku"].nunique()) if "sku" in df.columns else 0,
        "date_range": {
            "start": df["year_month"].min() if has_year_month else None,
            "end": df["year_month"].max() if has_year_month else None,
        },
        "max_date": data.max_date.isoformat() if data.max_date else None,
        "skipped_date_count": int(data.skipped_date_count),
        "has_price_data": bool(data.has_price_data),
        "has_stock_data": bool(data.has_stock_data),
        "available_weeks": list(data.available_weeks),
    }


def _price_metadata(data: Any) -> dict[str, Any]:
    return {"record_count": int(data.record_count)}


def _plan_metadata(data: Any) -> dict[str, Any]:
    return {
        "item_count": len(data.items),
        "detected_months": list(data.detected_months),
        "has_cumulative_columns": bool(data.has_cumulative_columns),
        "planning_horizon": data.planning_horizon,
    }


_METADATA_BUILDERS: dict[str, Callable[[Any], dict[str, Any]]] = {
    "sales": _sales_metadata,
    "price": _price_metadata,
    "plan": _plan_metadata,
}


def build_upload_metadata(
    file_type: str,
    data: Any,
    file_id: str,
    original_name: str,
    saved_path: Path,
) -> dict[str, Any]:
    """組出上傳回應：共通欄位加上各檔案類型的摘要。"""
    try:
        size_bytes = saved_path.stat().st_size
    except OSError:
        size_bytes = 0

    base = {
        "file_id": file_id,
        "filename": original_name,
        "file_size_bytes": size_bytes,
        "uploaded_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    return {**base, **_METADATA_BUILDERS[file_type](data)}
