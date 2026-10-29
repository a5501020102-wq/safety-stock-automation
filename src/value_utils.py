"""
寬鬆取值工具：匯出與序列化時，結果物件可能是 CalculationResult，
也可能是由前端 JSON 還原的 SimpleNamespace，欄位型別不保證一致。
"""

from __future__ import annotations

from typing import Any


def safe_float(v: Any, default: float = 0.0) -> float:
    """安全轉換為浮點數；None、空字串或無法轉換時回傳預設值。"""
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError, OverflowError):
        return default


def safe_int(v: Any, default: int = 0) -> int:
    """安全轉換為整數；None、空字串或無法轉換時回傳預設值。"""
    try:
        if v is None or v == "":
            return default
        return int(v)
    except (TypeError, ValueError, OverflowError):
        return default


def safe_round(v: Any, ndigits: int = 2, default: float = 0.0) -> float:
    """安全四捨五入"""
    return round(safe_float(v, default=default), ndigits)


def enum_value(v: Any) -> Any:
    """Enum 取 .value，其他型別原樣回傳。"""
    return getattr(v, "value", v)


def _calc_cv(std_dev: Any, mean_demand: Any) -> float:
    """變異係數 CV = σ / μ；μ <= 0 時回傳 0。"""
    s = safe_float(std_dev, 0)
    m = safe_float(mean_demand, 0)
    if m <= 0:
        return 0.0
    return s / m


def resolve_cv(r: Any) -> float:
    """
    Resolve CV from a CalculationResult using the canonical priority:
    coefficient_of_variation → cv attr → manual σ/μ calculation.
    """
    cv = getattr(r, "coefficient_of_variation", None)
    if cv is None:
        cv = getattr(r, "cv", None)
    if cv is None:
        std_dev = safe_float(getattr(r, "std_dev", 0), 0)
        mean_demand = safe_float(getattr(r, "mean_demand", 0), 0)
        cv = _calc_cv(std_dev, mean_demand)
    return safe_float(cv, 0.0)
