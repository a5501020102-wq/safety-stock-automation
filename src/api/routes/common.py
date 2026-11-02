"""路由共用的小工具：解析上傳檔、以 file_id 找暫存檔。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from src.data_loader import DataLoadError
from src.error_codes import ErrorCode
from src.temp_manager import find_file

from ..responses import ApiError

logger = logging.getLogger(__name__)

T = TypeVar("T")


def parse_file(loader: Callable[[Path], T], path: Path) -> T:
    """呼叫載入器；資料格式錯誤轉成 PARSE_ERROR，訊息直接告訴使用者哪裡有問題。"""
    try:
        return loader(path)
    except DataLoadError as e:
        logger.warning(f"Parse error for {path.name}: {e}")
        raise ApiError(ErrorCode.PARSE_ERROR, str(e)) from e


def resolve_file(file_id: Any, missing_code: str | None = None) -> Path | None:
    """
    以 file_id 找暫存檔。

    未提供 file_id 時：有 missing_code 就拋出該錯誤（必要檔案），否則回傳 None（選配檔案）。
    提供了但找不到（過期或不存在）時拋出 FILE_NOT_FOUND。
    """
    if not file_id:
        if missing_code:
            raise ApiError(missing_code)
        return None

    path = find_file(file_id)
    if path is None:
        raise ApiError(ErrorCode.FILE_NOT_FOUND, f"檔案不存在或已過期 (id={file_id})")
    return path
