"""
API 回應格式與錯誤處理。

- 成功回應：key 一律轉 camelCase，並強制 success=True
- 錯誤回應：以 ApiError 例外表達，由 create_app 註冊的 handler 統一轉成 JSON
"""

from __future__ import annotations

import logging
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from flask import current_app, jsonify

from src.case_converter import keys_to_camel
from src.error_codes import error_response

logger = logging.getLogger(__name__)


class ApiError(Exception):
    """可預期的 API 錯誤，handler 會依 code 決定 HTTP 狀態碼。"""

    def __init__(self, code: str, message: str | None = None, **extra: Any):
        super().__init__(message or code)
        self.code = code
        self.message = message
        self.extra = extra


def json_success(payload: dict[str, Any]) -> Any:
    """
    Build a success response with camelCase keys.

    Forces success=True even if the incoming payload already has a `success`
    key (defensive: prevents an accidental success=false from passing through).
    """
    body = {k: v for k, v in payload.items() if k != "success"}
    return jsonify(keys_to_camel({"success": True, **body}))


def json_error(code: str, message: str | None = None, **extra: Any) -> tuple[Any, int]:
    """Build an error response (code is kept uppercase, keys are not converted)."""
    payload, status = error_response(code, message, **extra)
    return jsonify(payload), status


def is_debug_errors() -> bool:
    """開發模式下錯誤回應附上例外細節，正式環境不外洩。"""
    return bool(current_app.config.get("DEBUG_ERRORS"))


@contextmanager
def error_boundary(code: str, log_message: str, *, include_traceback: bool = False) -> Iterator[None]:
    """
    API 邊界：把非預期例外轉成指定錯誤碼的 ApiError。

    這是唯一刻意捕捉所有 Exception 的地方——端點不能因為未知錯誤回傳 HTML 500，
    必須回傳前端看得懂的錯誤碼。ApiError 屬於可預期錯誤，原樣往外傳。
    """
    try:
        yield
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001 - API 邊界的統一錯誤處理
        logger.exception(log_message)
        extra: dict[str, Any] = {}
        if is_debug_errors():
            extra["detail"] = str(exc)
            if include_traceback:
                extra["traceback"] = traceback.format_exc()
        raise ApiError(code, **extra) from exc
