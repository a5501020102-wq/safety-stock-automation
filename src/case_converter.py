"""
Case conversion utilities for API boundary layer.

Python 內部保持 snake_case 慣例，API 回傳前統一轉為 camelCase，
讓 TypeScript 前端型別契約乾淨。

Design rationale:
- Python 內部不動 (遵循 PEP 8)
- 轉換只發生在 API 邊界 (jsonify 前)
- 遞迴處理巢狀結構
- 對非字串 key 保持原值 (避免破壞 dict 結構)
- 自動序列化 datetime 為 ISO 8601

Version: 1.0.0
Last Updated: 2026-04-15
"""

from __future__ import annotations

import datetime
from typing import Any


def to_camel(snake_str: str) -> str:
    """
    snake_case -> camelCase

    Handles edge cases:
    - Non-string input: return as-is
    - Empty string: return empty
    - No underscore: return as-is
    - All-upper first segment (e.g. "API_VERSION"): lowercase first ("apiVersion")
    - Leading/trailing underscores: stripped from split result
    - Empty segments between underscores (e.g. "foo__bar"): filtered out

    Examples:
        >>> to_camel("hello_world")
        'helloWorld'
        >>> to_camel("API_VERSION")
        'apiVersion'
        >>> to_camel("_private")
        'private'
        >>> to_camel("trailing_")
        'trailing'
        >>> to_camel("already_camelCase")
        'alreadyCamelCase'
        >>> to_camel("single")
        'single'
        >>> to_camel("")
        ''
    """
    if not isinstance(snake_str, str) or not snake_str:
        return snake_str

    # Fast-path: no underscore means nothing to convert
    if "_" not in snake_str:
        return snake_str

    # Filter out empty parts (handles leading/trailing/duplicate underscores)
    parts = [p for p in snake_str.split("_") if p]
    if not parts:
        return snake_str  # e.g. "__" or "_"

    # First segment: lowercase if it's an all-caps acronym (preserve
    # semantics of API_VERSION -> apiVersion rather than APIVersion)
    first = parts[0].lower() if parts[0].isupper() else parts[0]

    # Later segments: PascalCase them.
    #  - All-caps acronyms ("VERSION") -> first letter kept, rest lowered
    #    so API_VERSION -> apiVersion (not apiVERSION)
    #  - Mixed case ("camelCase") -> only first letter capitalized, rest
    #    preserved so user_camelCase -> userCamelCase
    def _cap(p: str) -> str:
        if not p:
            return p
        if p.isupper():
            return p[0] + p[1:].lower()
        return p[0].upper() + p[1:]

    rest = [_cap(p) for p in parts[1:]]

    return first + "".join(rest)


def keys_to_camel(obj: Any) -> Any:
    """
    Recursively convert all string dict keys from snake_case to camelCase.

    - dict: convert keys (skip non-string keys, keep value type)
    - list / tuple: recurse into each element
    - datetime / date: serialize as ISO 8601 string
    - other: return as-is

    Tuples are coerced to lists (JSON has no tuple type).
    """
    if isinstance(obj, dict):
        return {
            (to_camel(k) if isinstance(k, str) else k): keys_to_camel(v)
            for k, v in obj.items()
        }

    if isinstance(obj, (list, tuple)):
        return [keys_to_camel(item) for item in obj]

    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()

    return obj


__all__ = ["to_camel", "keys_to_camel"]
