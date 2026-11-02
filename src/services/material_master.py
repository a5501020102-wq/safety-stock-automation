"""
物料主檔（data/material_master.json）的載入與摘要。

主檔由 convert_master.py 從 SAP 物料清單產生，啟動時載入一次。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def load_material_master(path: Path) -> dict[str, Any]:
    """載入物料主檔；檔案不存在或格式錯誤時回傳空 dict，品類相關功能隨之停用。"""
    if not path.exists():
        logger.info("No material_master.json found, category features disabled")
        return {}
    try:
        with path.open(encoding="utf-8") as fh:
            master = json.load(fh)
    except (OSError, ValueError) as e:
        logger.warning(f"Failed to load material master: {e}")
        return {}
    logger.info(
        f"Material master loaded: {master.get('totalSkus', 0)} SKUs, "
        f"{master.get('totalCategories', 0)} categories"
    )
    return master


def summarize_material_groups(master: dict[str, Any]) -> dict[str, Any]:
    """給前端品類前置天數面板用的精簡版本：只保留名稱與數量，不含 SKU 對照表。"""
    if not master:
        return {"available": False, "categories": {}, "version": None}

    categories = {
        prefix: {
            "name": cat["name"],
            "totalCount": cat["totalCount"],
            "groups": {gid: {"name": g["name"], "count": g["count"]} for gid, g in cat["groups"].items()},
        }
        for prefix, cat in master.get("categories", {}).items()
    }
    return {
        "available": True,
        "version": master.get("version"),
        "totalSkus": master.get("totalSkus", 0),
        "totalCategories": master.get("totalCategories", 0),
        "categories": categories,
    }
