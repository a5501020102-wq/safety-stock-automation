"""
Canonical error codes for the API.

Usage:
    from src.error_codes import ErrorCode, make_error

    return make_error(ErrorCode.FILE_NOT_FOUND), 404

Front-end maps these codes to localized user-facing messages.
Backend `error` field is also human-readable (Traditional Chinese).

Version: 1.0.0
Last Updated: 2026-04-15
"""

from __future__ import annotations


class ErrorCode:
    # ---- Upload / File validation ----
    NO_FILE = "NO_FILE"
    EMPTY_FILENAME = "EMPTY_FILENAME"
    INVALID_FILE_TYPE = "INVALID_FILE_TYPE"
    INVALID_EXTENSION = "INVALID_EXTENSION"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    PARSE_ERROR = "PARSE_ERROR"

    # ---- Calculate ----
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    MISSING_SALES_FILE = "MISSING_SALES_FILE"
    INVALID_PARAMS = "INVALID_PARAMS"
    CALC_FAILED = "CALC_FAILED"

    # ---- Export ----
    NO_RESULTS = "NO_RESULTS"
    EXPORT_FAILED = "EXPORT_FAILED"
    INVALID_EXPORT_FORMAT = "INVALID_EXPORT_FORMAT"

    # ---- MA detail ----
    MISSING_MONTHLY_VALUES = "MISSING_MONTHLY_VALUES"
    MA_COMPUTE_FAILED = "MA_COMPUTE_FAILED"

    # ---- Generic ----
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    BAD_REQUEST = "BAD_REQUEST"
    INTERNAL_ERROR = "INTERNAL_ERROR"


# Default human-readable messages. Keep in Traditional Chinese to match
# the rest of the app. Frontend may still override based on code.
DEFAULT_MESSAGES: dict[str, str] = {
    ErrorCode.NO_FILE: "未提供檔案",
    ErrorCode.EMPTY_FILENAME: "檔名為空",
    ErrorCode.INVALID_FILE_TYPE: "未知檔案類型（僅支援 sales / price / plan）",
    ErrorCode.INVALID_EXTENSION: "僅支援 .xlsx 或 .xls 檔案",
    ErrorCode.FILE_TOO_LARGE: "檔案超過大小限制",
    ErrorCode.PARSE_ERROR: "檔案解析失敗",

    ErrorCode.FILE_NOT_FOUND: "檔案不存在或已過期，請重新上傳",
    ErrorCode.MISSING_SALES_FILE: "缺少銷貨資料檔案",
    ErrorCode.INVALID_PARAMS: "計算參數無效",
    ErrorCode.CALC_FAILED: "計算失敗",

    ErrorCode.NO_RESULTS: "沒有可匯出的結果",
    ErrorCode.EXPORT_FAILED: "匯出失敗",
    ErrorCode.INVALID_EXPORT_FORMAT: "不支援的匯出格式",

    ErrorCode.MISSING_MONTHLY_VALUES: "缺少月度資料",
    ErrorCode.MA_COMPUTE_FAILED: "移動平均計算失敗",

    ErrorCode.NOT_FOUND: "路由不存在",
    ErrorCode.METHOD_NOT_ALLOWED: "方法不允許",
    ErrorCode.BAD_REQUEST: "請求格式錯誤",
    ErrorCode.INTERNAL_ERROR: "內部錯誤",
}


def make_error(code: str, message: str | None = None, **extra) -> dict:
    """
    Build a standardized error payload.

    Always includes: success=False, error, code
    Optional extra fields (e.g. detail) are merged in.

    Example:
        return jsonify(make_error(ErrorCode.FILE_NOT_FOUND)), 404
    """
    payload = {
        "success": False,
        "error": message or DEFAULT_MESSAGES.get(code, "未知錯誤"),
        "code": code,
    }
    if extra:
        payload.update(extra)
    return payload


# Map of common error codes to HTTP status codes, for convenience.
HTTP_STATUS: dict[str, int] = {
    ErrorCode.NO_FILE: 400,
    ErrorCode.EMPTY_FILENAME: 400,
    ErrorCode.INVALID_FILE_TYPE: 400,
    ErrorCode.INVALID_EXTENSION: 400,
    ErrorCode.FILE_TOO_LARGE: 413,
    ErrorCode.PARSE_ERROR: 400,

    ErrorCode.FILE_NOT_FOUND: 404,
    ErrorCode.MISSING_SALES_FILE: 400,
    ErrorCode.INVALID_PARAMS: 400,
    ErrorCode.CALC_FAILED: 500,

    ErrorCode.NO_RESULTS: 400,
    ErrorCode.EXPORT_FAILED: 500,
    ErrorCode.INVALID_EXPORT_FORMAT: 400,

    ErrorCode.MISSING_MONTHLY_VALUES: 400,
    ErrorCode.MA_COMPUTE_FAILED: 500,

    ErrorCode.NOT_FOUND: 404,
    ErrorCode.METHOD_NOT_ALLOWED: 405,
    ErrorCode.BAD_REQUEST: 400,
    ErrorCode.INTERNAL_ERROR: 500,
}


def error_response(code: str, message: str | None = None, **extra) -> tuple[dict, int]:
    """
    Convenience: return both payload and HTTP status for Flask routes.

    Example:
        payload, status = error_response(ErrorCode.FILE_NOT_FOUND)
        return jsonify(payload), status
    """
    return make_error(code, message, **extra), HTTP_STATUS.get(code, 500)


__all__ = [
    "ErrorCode",
    "DEFAULT_MESSAGES",
    "HTTP_STATUS",
    "make_error",
    "error_response",
]
