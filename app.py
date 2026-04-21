"""
Safety Stock Automation - Flask API (v5.0.0, Stateless)

Major change from v4.4.0:
- Removed Flask session + pickle. Fully stateless JSON API.
- Upload returns a file_id; subsequent calls reference it.
- Calculate returns full payload (including parameters snapshot).
- Export receives results in request body (no server state).
- All response keys converted to camelCase at the boundary.
- CORS enabled for local dev (localhost:3000) and Vercel Preview URLs.
- Legacy Jinja UI preserved at /legacy during migration.

Endpoints:
    GET  /                           API health check
    GET  /legacy                     Legacy Jinja UI
    POST /api/upload/<file_type>     Upload sales/price/plan file
    POST /api/calculate              Run safety stock calculation
    POST /api/export/excel           Generate Excel export
    POST /api/export/sap             Generate SAP MM17 export
    POST /api/ma-detail              Compute moving average detail (pure function)

Author: 松鼠
Version: 5.0.0
Last Updated: 2026-04-15
"""

from __future__ import annotations

import calendar
import io
import logging
import os
import re
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from flask import Flask, jsonify, render_template, request, send_file
from flask_cors import CORS
from werkzeug.exceptions import RequestEntityTooLarge

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("app.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

sys.path.insert(0, str(Path(__file__).parent))

# ---------------------------------------------------------------------------
# Core modules
# ---------------------------------------------------------------------------

MODULES_AVAILABLE = False
try:
    from src.business_logic import (
        calculate_comparison_mode,
        export_comparison_to_excel,
        export_to_excel,
        export_to_sap_mm17,
        serialize_results_for_json,
    )
    from src.calculator import SafetyStockCalculator
    from src.case_converter import keys_to_camel
    from src.data_loader import (
        DataLoadError,
        load_plan_data,
        load_price_data,
        load_sales_data,
    )
    from src.error_codes import ErrorCode, error_response, make_error
    from src.temp_manager import (
        ALLOWED_EXTENSIONS,
        cleanup_temp_files,
        find_file,
        get_temp_path,
        init_temp_dir,
        is_allowed_extension,
    )

    MODULES_AVAILABLE = True
    logger.info("Core modules loaded")
except ImportError as exc:
    logger.error(f"Failed to import core modules: {exc}")

# ---------------------------------------------------------------------------
# Flask app setup
# ---------------------------------------------------------------------------

API_VERSION = "5.1.0"
MAX_UPLOAD_MB = 50

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
app.config["JSON_AS_ASCII"] = False  # keep Chinese readable in JSON

DEBUG_MODE = os.environ.get("FLASK_ENV") == "development"

# CORS: always allow localhost + any origins from ALLOWED_ORIGINS env var.
_allowed_origins: List[str] = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
_env_origins = os.environ.get("ALLOWED_ORIGINS", "").strip()
if _env_origins:
    _allowed_origins.extend(o.strip() for o in _env_origins.split(",") if o.strip())

logger.info(f"CORS allowed origins: {_allowed_origins}")

CORS(
    app,
    resources={r"/*": {"origins": _allowed_origins}},
    expose_headers=["Content-Disposition"],
    supports_credentials=False,
    max_age=600,
)

# Initialize temp dir on startup
if MODULES_AVAILABLE:
    init_temp_dir("temp_uploads")

# ---------------------------------------------------------------------------
# Material Master (loaded once at startup from data/material_master.json)
# ---------------------------------------------------------------------------

_MATERIAL_MASTER: Dict[str, Any] = {}

_master_path = Path(__file__).parent / "data" / "material_master.json"
if _master_path.exists():
    try:
        import json as _json
        with open(_master_path, encoding="utf-8") as _f:
            _MATERIAL_MASTER = _json.load(_f)
        logger.info(
            f"Material master loaded: {_MATERIAL_MASTER.get('totalSkus', 0)} SKUs, "
            f"{_MATERIAL_MASTER.get('totalCategories', 0)} categories"
        )
    except Exception as _e:
        logger.warning(f"Failed to load material master: {_e}")
else:
    logger.info("No material_master.json found, category features disabled")

logger.info(f"Flask API initialized (v{API_VERSION}, debug={DEBUG_MODE})")


# ===========================================================================
# Helpers
# ===========================================================================

def _jsonify_success(payload: Dict[str, Any]) -> Any:
    """
    Build a success response with camelCase keys.

    Forces success=True even if the incoming payload already has a `success`
    key (defensive: prevents an accidental success=false from passing through).
    """
    payload = dict(payload)  # shallow copy so caller's dict isn't mutated
    payload.pop("success", None)
    payload = {"success": True, **payload}
    return jsonify(keys_to_camel(payload))


def _jsonify_error(code: str, message: str | None = None, **extra) -> Tuple[Any, int]:
    """Build an error response (already snake_case keys, but code is kept uppercase)."""
    payload, status = error_response(code, message, **extra)
    # camelCase the `detail` field etc but keep error/code as-is
    return jsonify(payload), status


def _validate_z_scores(z_scores: Any) -> Tuple[bool, str, Dict[str, float]]:
    """Validate the z_scores dict shape and numeric ranges."""
    defaults = {"A": 2.05, "B": 1.65, "C": 1.28}

    if not z_scores:
        return True, "", defaults
    if not isinstance(z_scores, dict):
        return False, "z_scores 必須是物件 {A, B, C}", defaults

    cleaned: Dict[str, float] = {}
    for key in ("A", "B", "C"):
        raw = z_scores.get(key, defaults[key])
        try:
            val = float(raw)
        except (TypeError, ValueError):
            return False, f"z_scores.{key} 必須是數字", defaults
        if not (0.5 <= val <= 3.5):
            return False, f"z_scores.{key} 必須介於 0.5-3.5", defaults
        cleaned[key] = val
    return True, "", cleaned


def _validate_abc_thresholds(abc_thresholds: Any) -> Tuple[bool, str, Dict[str, float]]:
    """Validate ABC threshold dict."""
    defaults = {"A": 0.80, "B": 0.95}

    if not abc_thresholds:
        return True, "", defaults
    if not isinstance(abc_thresholds, dict):
        return False, "abc_thresholds 必須是物件 {A, B}", defaults

    cleaned: Dict[str, float] = {}
    for key in ("A", "B"):
        raw = abc_thresholds.get(key, defaults[key])
        try:
            val = float(raw)
        except (TypeError, ValueError):
            return False, f"abc_thresholds.{key} 必須是數字", defaults
        if not (0.0 < val < 1.0):
            return False, f"abc_thresholds.{key} 必須介於 0-1 (開區間)", defaults
        cleaned[key] = val
    if cleaned["A"] >= cleaned["B"]:
        return False, "abc_thresholds.A 必須小於 B", defaults
    return True, "", cleaned


def _filter_results_by_site(results: List[Any], site_filter: Optional[str]) -> List[Any]:
    """Filter a list of CalculationResult-like objects by site attribute."""
    if not site_filter or site_filter == "all":
        return results
    return [r for r in results if getattr(r, "site", None) == site_filter]


def _parse_year_month(ym: str) -> Tuple[int, int]:
    """Parse 'YYYY-MM' -> (year, month). Returns (0, 0) on failure."""
    try:
        year, month = ym.split("-")
        return int(year), int(month)
    except Exception:
        return 0, 0


# ===========================================================================
# Health check
# ===========================================================================

@app.route("/", methods=["GET"])
def index():
    """API root — returns health info and a pointer to the legacy UI."""
    return jsonify(keys_to_camel({
        "status": "ok",
        "service": "Safety Stock Automation API",
        "version": API_VERSION,
        "legacy_ui": "/legacy",
        "modules_available": MODULES_AVAILABLE,
    }))


@app.route("/health", methods=["GET"])
def health():
    """Lightweight liveness probe."""
    return jsonify({"status": "ok", "version": API_VERSION})


@app.route("/api/material-groups", methods=["GET"])
def material_groups():
    """Return material master categories for the frontend category-LT panel."""
    if not _MATERIAL_MASTER:
        return _jsonify_success({
            "available": False,
            "categories": {},
            "version": None,
        })

    cats = _MATERIAL_MASTER.get("categories", {})
    slim_cats: Dict[str, Any] = {}
    for prefix, cat in cats.items():
        slim_cats[prefix] = {
            "name": cat["name"],
            "totalCount": cat["totalCount"],
            "groups": {
                gid: {"name": g["name"], "count": g["count"]}
                for gid, g in cat["groups"].items()
            },
        }

    return _jsonify_success({
        "available": True,
        "version": _MATERIAL_MASTER.get("version"),
        "totalSkus": _MATERIAL_MASTER.get("totalSkus", 0),
        "totalCategories": _MATERIAL_MASTER.get("totalCategories", 0),
        "categories": slim_cats,
    })


@app.route("/legacy", methods=["GET"])
def legacy_ui():
    """Legacy Jinja UI (preserved during migration to Next.js)."""
    return render_template("index.html")


# ===========================================================================
# Upload
# ===========================================================================

_FILE_LOADERS: Dict[str, Any] = {
    "sales": None,  # populated lazily below
    "price": None,
    "plan": None,
}


def _get_file_loaders() -> Dict[str, Any]:
    """Lazy init to avoid NameError when modules aren't available."""
    if MODULES_AVAILABLE and _FILE_LOADERS["sales"] is None:
        _FILE_LOADERS["sales"] = load_sales_data
        _FILE_LOADERS["price"] = load_price_data
        _FILE_LOADERS["plan"] = load_plan_data
    return _FILE_LOADERS


def _build_upload_metadata(
    file_type: str,
    data: Any,
    file_id: str,
    original_name: str,
    saved_path: Path,
) -> Dict[str, Any]:
    """Shape per-type metadata for the upload response."""
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

    if file_type == "sales":
        df = data.df
        return {
            **base,
            "record_count": int(data.record_count),
            "detected_sites": list(data.available_sites),
            "detected_skus": int(df["sku"].nunique()) if "sku" in df.columns else 0,
            "date_range": {
                "start": df["year_month"].min() if "year_month" in df.columns else None,
                "end": df["year_month"].max() if "year_month" in df.columns else None,
            },
            "max_date": data.max_date.isoformat() if data.max_date else None,
            "skipped_date_count": int(data.skipped_date_count),
            "has_price_data": bool(data.has_price_data),
            "has_stock_data": bool(data.has_stock_data),
        }

    if file_type == "price":
        return {
            **base,
            "record_count": int(data.record_count),
        }

    if file_type == "plan":
        return {
            **base,
            "item_count": len(data.items),
            "detected_months": list(data.detected_months),
            "has_cumulative_columns": bool(data.has_cumulative_columns),
        }

    return base


@app.route("/api/upload/<file_type>", methods=["POST"])
def upload_file(file_type: str):
    """Upload a file, save to temp, extract metadata, return file_id."""
    if not MODULES_AVAILABLE:
        return _jsonify_error(ErrorCode.INTERNAL_ERROR, "核心模組未載入")

    # Lazy cleanup of expired files on every upload
    cleanup_temp_files(ttl_minutes=60)

    loaders = _get_file_loaders()
    if file_type not in loaders:
        return _jsonify_error(ErrorCode.INVALID_FILE_TYPE)

    if "file" not in request.files:
        return _jsonify_error(ErrorCode.NO_FILE)

    f = request.files["file"]
    if not f.filename:
        return _jsonify_error(ErrorCode.EMPTY_FILENAME)

    ext = Path(f.filename).suffix.lower()
    if not is_allowed_extension(ext):
        return _jsonify_error(
            ErrorCode.INVALID_EXTENSION,
            f"僅支援 {', '.join(sorted(ALLOWED_EXTENSIONS))} 檔案",
        )

    file_id = str(uuid.uuid4())
    save_path = get_temp_path(file_id, ext)

    try:
        f.save(str(save_path))
    except OSError as e:
        logger.error(f"Failed to save upload: {e}")
        return _jsonify_error(ErrorCode.INTERNAL_ERROR, "儲存檔案失敗")

    try:
        data = loaders[file_type](save_path)
        metadata = _build_upload_metadata(file_type, data, file_id, f.filename, save_path)
        logger.info(
            f"Upload OK: {file_type} {f.filename} -> {file_id} "
            f"({metadata.get('record_count', metadata.get('item_count', 0))} items)"
        )
        return _jsonify_success(metadata)
    except DataLoadError as e:
        save_path.unlink(missing_ok=True)
        logger.warning(f"Parse error for {f.filename}: {e}")
        return _jsonify_error(ErrorCode.PARSE_ERROR, str(e))
    except Exception as e:  # noqa: BLE001 - we want to catch any loader bug
        save_path.unlink(missing_ok=True)
        logger.exception(f"Unexpected error parsing {f.filename}")
        extra = {"detail": str(e)} if DEBUG_MODE else {}
        return _jsonify_error(ErrorCode.PARSE_ERROR, **extra)


# ===========================================================================
# Calculate
# ===========================================================================

def _build_parameters_snapshot(
    body: Dict[str, Any],
    options: Any,
    sales_data: Any,
    filenames: Dict[str, Optional[str]],
    execution_time_ms: float,
) -> Dict[str, Any]:
    """
    Assemble the parameters snapshot for the frontend.

    Includes resolved values (post-validation), data range, and timing.
    """
    # Determine excluded month (if any) — matches calculator.py logic
    excluded_month = None
    if sales_data.max_date is not None:
        max_date = sales_data.max_date
        last_day = calendar.monthrange(max_date.year, max_date.month)[1]
        if max_date.day < last_day:
            excluded_month = f"{max_date.year}-{max_date.month:02d}"

    df = sales_data.df
    return {
        "calc_mode": body.get("calc_mode", "all"),
        "data_min_date": df["year_month"].min() if "year_month" in df.columns else None,
        "data_max_date": df["year_month"].max() if "year_month" in df.columns else None,
        "data_max_date_exact": sales_data.max_date.isoformat() if sales_data.max_date else None,
        "excluded_month": excluded_month,
        "selected_months": options.selected_months,
        "lead_time_days": options.lead_time_days,
        "min_months": options.min_months,
        "z_scores": options.z_scores,
        "abc_thresholds": options.abc_thresholds,
        "enable_outlier": options.enable_outlier_detection,
        "enable_ma": options.enable_moving_average,
        "ma_window": options.ma_window if options.enable_moving_average else None,
        "granularity": getattr(options, "granularity", "monthly"),
        "engine_version": API_VERSION,
        "sales_filename": filenames.get("sales"),
        "price_filename": filenames.get("price"),
        "plan_filename": filenames.get("plan"),
        "executed_at": datetime.now(tz=timezone.utc).isoformat(),
        "execution_time_ms": round(execution_time_ms, 1),
    }


def _resolve_file(file_id: Optional[str], required_code: Optional[str] = None):
    """
    Resolve a file_id to a path. Returns (path, error_tuple).

    If file_id is None and required_code is None, returns (None, None) (optional file).
    If file_id is None and required_code is set, returns (None, (payload, status)).
    If file_id is set but file not found, returns (None, (payload, status)).
    """
    if not file_id:
        if required_code:
            return None, _jsonify_error(required_code)
        return None, None

    path = find_file(file_id)
    if path is None:
        return None, _jsonify_error(
            ErrorCode.FILE_NOT_FOUND,
            f"檔案不存在或已過期 (id={file_id})",
        )
    return path, None


@app.route("/api/calculate", methods=["POST"])
def calculate():
    """Run safety stock calculation. Stateless — results returned in response."""
    if not MODULES_AVAILABLE:
        return _jsonify_error(ErrorCode.INTERNAL_ERROR, "核心模組未載入")

    body = request.get_json(silent=True) or {}

    # --- Resolve files ------------------------------------------------------
    sales_path, err = _resolve_file(
        body.get("salesFileId") or body.get("sales_file_id"),
        ErrorCode.MISSING_SALES_FILE,
    )
    if err:
        return err

    price_path, err = _resolve_file(
        body.get("priceFileId") or body.get("price_file_id")
    )
    if err:
        return err

    plan_path, err = _resolve_file(
        body.get("planFileId") or body.get("plan_file_id")
    )
    if err:
        return err

    # --- Extract and validate params ---------------------------------------
    params = body.get("params") or body  # accept either nested or flat
    calc_mode = params.get("calc_mode") or params.get("calcMode") or "all"
    if calc_mode not in ("all", "total", "compare", "single"):
        return _jsonify_error(ErrorCode.INVALID_PARAMS, f"未知的計算模式: {calc_mode}")

    # z_scores / abc_thresholds — accept both camel and snake from body
    z_raw = params.get("z_scores") or params.get("zScores")
    ok, msg, z_scores = _validate_z_scores(z_raw)
    if not ok:
        return _jsonify_error(ErrorCode.INVALID_PARAMS, msg)

    abc_raw = params.get("abc_thresholds") or params.get("abcThresholds")
    ok, msg, abc_thresholds = _validate_abc_thresholds(abc_raw)
    if not ok:
        return _jsonify_error(ErrorCode.INVALID_PARAMS, msg)

    selected_months = params.get("selected_months") or params.get("selectedMonths") or list(range(1, 13))
    if not isinstance(selected_months, list) or not all(
        isinstance(m, int) and 1 <= m <= 12 for m in selected_months
    ):
        return _jsonify_error(ErrorCode.INVALID_PARAMS, "selected_months 必須是 1-12 的整數列表")

    def _int_param(key_snake: str, key_camel: str, default: int, lo: int, hi: int) -> Tuple[int, Optional[Tuple]]:
        raw = params.get(key_snake) if params.get(key_snake) is not None else params.get(key_camel)
        if raw is None:
            return default, None
        try:
            val = int(raw)
        except (TypeError, ValueError):
            return default, _jsonify_error(ErrorCode.INVALID_PARAMS, f"{key_snake} 必須是整數")
        if not (lo <= val <= hi):
            return default, _jsonify_error(
                ErrorCode.INVALID_PARAMS, f"{key_snake} 必須介於 {lo}-{hi}"
            )
        return val, None

    lead_time, err = _int_param("lead_time", "leadTime", 30, 1, 365)
    if err:
        return err
    min_months, err = _int_param("min_months", "minMonths", 2, 0, 12)
    if err:
        return err
    ma_window, err = _int_param("ma_window", "maWindow", 3, 2, 12)
    if err:
        return err

    enable_outlier = bool(
        params.get("enable_outlier", params.get("enableOutlier", True))
    )
    enable_ma = bool(
        params.get("enable_ma", params.get("enableMa", False))
    )

    granularity_str = params.get("granularity", "monthly")
    valid_granularities = ("daily", "weekly", "monthly")
    if granularity_str not in valid_granularities:
        return _jsonify_error(
            ErrorCode.INVALID_PARAMS,
            f"granularity 必須是 {valid_granularities} 之一，收到: {granularity_str}"
        )

    category_lead_times = params.get("category_lead_times") or params.get("categoryLeadTimes") or {}
    group_lead_times = params.get("group_lead_times") or params.get("groupLeadTimes") or {}

    date_from_str = params.get("date_from") or params.get("dateFrom") or None
    date_to_str = params.get("date_to") or params.get("dateTo") or None

    date_from = None
    date_to = None
    if date_from_str:
        try:
            date_from = datetime.strptime(date_from_str.replace("/", "-"), "%Y-%m-%d")
        except (ValueError, AttributeError):
            pass
    if date_to_str:
        try:
            date_to = datetime.strptime(date_to_str.replace("/", "-"), "%Y-%m-%d")
        except (ValueError, AttributeError):
            pass

    # --- Load data ----------------------------------------------------------
    try:
        sales_data = load_sales_data(sales_path)
    except DataLoadError as e:
        return _jsonify_error(ErrorCode.PARSE_ERROR, str(e))

    price_data = None
    if price_path:
        try:
            price_data = load_price_data(price_path).price_map
        except DataLoadError as e:
            logger.warning(f"Price load failed, continuing without: {e}")

    plan_data = None
    if plan_path:
        try:
            plan_data = load_plan_data(plan_path)
        except DataLoadError as e:
            logger.warning(f"Plan load failed, continuing without: {e}")

    filenames = {
        "sales": sales_path.name if sales_path else None,
        "price": price_path.name if price_path else None,
        "plan": plan_path.name if plan_path else None,
    }

    # --- Run calculation ---------------------------------------------------
    calculator = SafetyStockCalculator()
    start_ts = time.perf_counter()

    try:
        if calc_mode == "compare":
            comparison_data = calculate_comparison_mode(
                calculator=calculator,
                sales_data=sales_data,
                price_data=price_data,
                plan_data=plan_data,
                selected_months=selected_months,
                min_months=min_months,
                lead_time=lead_time,
                enable_outlier=enable_outlier,
                enable_ma=enable_ma,
                ma_window=ma_window,
                z_scores=z_scores,
                abc_thresholds=abc_thresholds,
                max_date=sales_data.max_date,
                granularity=granularity_str,
                category_lead_times=category_lead_times,
                group_lead_times=group_lead_times,
                material_master=_MATERIAL_MASTER or None,
                date_from=date_from,
                date_to=date_to,
            )
            # For the parameter snapshot, derive options from the (all) summary
            all_summary_obj = comparison_data["all"][2]
            # Reconstruct a light "options" object for snapshot building
            options_like = _OptionsSnapshot(
                calc_mode=calc_mode,
                selected_months=selected_months,
                lead_time_days=lead_time,
                min_months=min_months,
                z_scores=z_scores,
                abc_thresholds=abc_thresholds,
                enable_outlier_detection=enable_outlier,
                enable_moving_average=enable_ma,
                ma_window=ma_window,
                granularity=granularity_str,
            )
            execution_ms = (time.perf_counter() - start_ts) * 1000
            snapshot = _build_parameters_snapshot(
                body, options_like, sales_data, filenames, execution_ms
            )

            response = {
                "mode": "compare",
                "version": API_VERSION,
                "parameters": snapshot,
                "comparison": comparison_data["comparison"],
                "all_summary": serialize_results_for_json(*comparison_data["all"]),
                "total_summary": serialize_results_for_json(*comparison_data["total"]),
            }
        else:
            target_site = params.get("target_site") or params.get("targetSite")
            results, excluded, summary = calculator.calculate(
                sales_data=sales_data,
                price_data=price_data,
                plan_data=plan_data,
                calc_mode=calc_mode,
                target_site=target_site,
                selected_months=selected_months,
                min_months=min_months,
                lead_time_days=lead_time,
                enable_outlier_detection=enable_outlier,
                enable_moving_average=enable_ma,
                ma_window=ma_window,
                z_scores=z_scores,
                abc_thresholds=abc_thresholds,
                max_date=sales_data.max_date,
                granularity=granularity_str,
                category_lead_times=category_lead_times,
                group_lead_times=group_lead_times,
                material_master=_MATERIAL_MASTER or None,
                date_from=date_from,
                date_to=date_to,
            )

            options_like = _OptionsSnapshot(
                calc_mode=calc_mode,
                selected_months=selected_months,
                lead_time_days=lead_time,
                min_months=min_months,
                z_scores=z_scores,
                abc_thresholds=abc_thresholds,
                enable_outlier_detection=enable_outlier,
                enable_moving_average=enable_ma,
                ma_window=ma_window,
                granularity=granularity_str,
            )
            execution_ms = (time.perf_counter() - start_ts) * 1000
            snapshot = _build_parameters_snapshot(
                body, options_like, sales_data, filenames, execution_ms
            )

            serialized = serialize_results_for_json(results, excluded, summary)
            response = {
                "mode": calc_mode,
                "version": API_VERSION,
                "parameters": snapshot,
                **serialized,
            }

        logger.info(f"Calculate OK ({calc_mode}) in {execution_ms:.0f}ms")
        return _jsonify_success(response)

    except Exception as e:  # noqa: BLE001
        logger.exception("Calculation failed")
        extra = {"detail": str(e), "traceback": traceback.format_exc()} if DEBUG_MODE else {}
        return _jsonify_error(ErrorCode.CALC_FAILED, **extra)


class _OptionsSnapshot:
    """Lightweight carrier mirroring CalculationOptions for snapshot building."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


# ===========================================================================
# Export (Excel / SAP MM17) — stateless
# ===========================================================================

def _deserialize_results(payload: List[Dict[str, Any]]) -> List[Any]:
    """
    Convert the JSON result list back into lightweight objects that the
    export functions can treat as CalculationResult-like via getattr.

    We use a SimpleNamespace-style shim rather than re-importing enums, because
    the exporter code already uses getattr with string fallbacks.
    """
    from types import SimpleNamespace

    out: List[Any] = []
    for r in payload or []:
        # Convert nested structures if any (status/abcClass are primitives here)
        obj = SimpleNamespace(**{_snake(k): v for k, v in r.items()})
        out.append(obj)
    return out


def _snake(s: str) -> str:
    """camelCase -> snake_case (for reverse conversion at export boundary)."""
    if not isinstance(s, str) or not s:
        return s
    out = []
    for i, ch in enumerate(s):
        if ch.isupper() and i > 0:
            out.append("_")
            out.append(ch.lower())
        else:
            out.append(ch.lower() if ch.isupper() else ch)
    return "".join(out)


def _deserialize_summary(payload: Dict[str, Any]) -> Any:
    """Convert summary JSON dict into a SimpleNamespace for export functions."""
    from types import SimpleNamespace

    if not payload:
        return SimpleNamespace()
    return SimpleNamespace(**{_snake(k): v for k, v in payload.items()})


@app.route("/api/export/excel", methods=["POST"])
def export_excel():
    """Stateless Excel export. Client sends the results payload."""
    if not MODULES_AVAILABLE:
        return _jsonify_error(ErrorCode.INTERNAL_ERROR, "核心模組未載入")

    body = request.get_json(silent=True) or {}
    mode = body.get("mode", "all")
    site_filter = body.get("siteFilter") or body.get("site_filter")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    try:
        if mode == "compare":
            # Compare mode: need allSummary + totalSummary + comparison
            all_summary = body.get("allSummary") or body.get("all_summary") or {}
            total_summary = body.get("totalSummary") or body.get("total_summary") or {}
            comparison_raw = body.get("comparison") or {}
            comparison = {_snake(k): v for k, v in comparison_raw.items()}

            all_results = _deserialize_results(all_summary.get("results", []))
            total_results = _deserialize_results(total_summary.get("results", []))
            all_sum = _deserialize_summary(all_summary.get("summary", {}))
            total_sum = _deserialize_summary(total_summary.get("summary", {}))

            if site_filter:
                # Filter both sides so comparison totals remain consistent
                all_results = _filter_results_by_site(all_results, site_filter)
                total_results = _filter_results_by_site(total_results, site_filter)
                if not all_results and not total_results:
                    return _jsonify_error(
                        ErrorCode.NO_RESULTS, f"出貨點 {site_filter} 沒有資料"
                    )

            excel_bytes = export_comparison_to_excel(
                all_data=(all_results, [], all_sum),
                total_data=(total_results, [], total_sum),
                comparison=comparison,
            )
            site_suffix = f"_{re.sub(r'[^a-zA-Z0-9_-]', '_', site_filter)}" if site_filter else ""
            filename = f"safety_stock_compare{site_suffix}_{timestamp}.xlsx"

        else:
            results_payload = body.get("results", [])
            summary_payload = body.get("summary", {})
            results = _deserialize_results(results_payload)
            summary = _deserialize_summary(summary_payload)

            if site_filter:
                results = _filter_results_by_site(results, site_filter)
                if not results:
                    return _jsonify_error(
                        ErrorCode.NO_RESULTS, f"出貨點 {site_filter} 沒有資料"
                    )

            excel_bytes = export_to_excel(results, [], summary)
            site_suffix = f"_{re.sub(r'[^a-zA-Z0-9_-]', '_', site_filter)}" if site_filter else ""
            filename = f"safety_stock_{mode}{site_suffix}_{timestamp}.xlsx"

        buf = io.BytesIO(excel_bytes)
        buf.seek(0)
        logger.info(f"Excel export OK: {filename}")
        return send_file(
            buf,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=filename,
        )

    except Exception as e:  # noqa: BLE001
        logger.exception("Excel export failed")
        extra = {"detail": str(e)} if DEBUG_MODE else {}
        return _jsonify_error(ErrorCode.EXPORT_FAILED, **extra)


@app.route("/api/export/sap", methods=["POST"])
def export_sap():
    """Stateless SAP MM17 export."""
    if not MODULES_AVAILABLE:
        return _jsonify_error(ErrorCode.INTERNAL_ERROR, "核心模組未載入")

    body = request.get_json(silent=True) or {}
    export_format = body.get("format", "xlsx")
    if export_format not in ("xlsx", "csv"):
        return _jsonify_error(
            ErrorCode.INVALID_EXPORT_FORMAT, "format 必須是 xlsx 或 csv"
        )

    site_filter = body.get("siteFilter") or body.get("site_filter")
    mode = body.get("mode", "all")
    include_header = bool(body.get("includeHeader", body.get("include_header", True)))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    try:
        # Compare mode: client chooses which side (all/total) to export via `sapMode`
        if mode == "compare":
            sap_mode = body.get("sapMode") or body.get("sap_mode") or "all"
            bucket_key = "totalSummary" if sap_mode == "total" else "allSummary"
            bucket = body.get(bucket_key) or body.get(_snake(bucket_key)) or {}
            results = _deserialize_results(bucket.get("results", []))
            summary = _deserialize_summary(bucket.get("summary", {}))
            mode_suffix = sap_mode
        else:
            results = _deserialize_results(body.get("results", []))
            summary = _deserialize_summary(body.get("summary", {}))
            mode_suffix = mode

        if site_filter:
            results = _filter_results_by_site(results, site_filter)
            if not results:
                return _jsonify_error(
                    ErrorCode.NO_RESULTS, f"出貨點 {site_filter} 沒有資料"
                )

        sap_bytes = export_to_sap_mm17(
            results=results,
            summary=summary,
            format=export_format,
            include_header=include_header,
        )
        site_suffix = f"_{re.sub(r'[^a-zA-Z0-9_-]', '_', site_filter)}" if site_filter else ""
        filename = f"sap_mm17_{mode_suffix}{site_suffix}_{timestamp}.{export_format}"
        mime = (
            "text/csv; charset=utf-8"
            if export_format == "csv"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        buf = io.BytesIO(sap_bytes)
        buf.seek(0)
        logger.info(f"SAP export OK: {filename} ({len(results)} rows)")
        return send_file(buf, mimetype=mime, as_attachment=True, download_name=filename)

    except Exception as e:  # noqa: BLE001
        logger.exception("SAP export failed")
        extra = {"detail": str(e)} if DEBUG_MODE else {}
        return _jsonify_error(ErrorCode.EXPORT_FAILED, **extra)


# ===========================================================================
# Moving Average detail — pure compute (stateless)
# ===========================================================================

def _group_by_quarter(monthly_data: Dict[str, float]) -> Dict[str, Dict[str, Any]]:
    """Group monthly data into quarterly summary. Pure function, no deps."""
    buckets: Dict[str, List[Tuple[str, float]]] = {}
    for ym, value in sorted(monthly_data.items()):
        year, month = _parse_year_month(ym)
        if year == 0:
            continue
        if 1 <= month <= 3:
            quarter = "Q1"
        elif 4 <= month <= 6:
            quarter = "Q2"
        elif 7 <= month <= 9:
            quarter = "Q3"
        else:
            quarter = "Q4"
        key = f"{quarter} {year}"
        buckets.setdefault(key, []).append((ym, float(value)))

    summary: Dict[str, Dict[str, Any]] = {}
    for key, pairs in sorted(buckets.items()):
        values = [v for _, v in pairs]
        summary[key] = {
            "months": [ym for ym, _ in pairs],
            "values": values,
            "avg": round(sum(values) / len(values), 2) if values else 0,
            "total": sum(values),
            "count": len(values),
        }
    return summary


def _find_filled_months(monthly_data: Dict[str, float]) -> List[str]:
    """Return months between min and max that are missing from monthly_data."""
    sorted_months = sorted(monthly_data.keys())
    if not sorted_months:
        return []

    start_year, start_month = _parse_year_month(sorted_months[0])
    end_year, end_month = _parse_year_month(sorted_months[-1])
    if start_year == 0 or end_year == 0:
        return []

    expected: List[str] = []
    y, m = start_year, start_month
    guard = 0
    while (y, m) <= (end_year, end_month) and guard < 400:
        expected.append(f"{y}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
        guard += 1
    return [ym for ym in expected if ym not in monthly_data]


def _ma_recommendation(std_dev: float, mean_demand: float) -> Dict[str, str]:
    """Small heuristic recommendation text."""
    if std_dev <= 0:
        return {"text": "標準差為 0，無需移動平均", "level": "info"}
    cv = std_dev / mean_demand if mean_demand > 0 else 0
    if cv > 0.5:
        return {"text": f"需求波動較大 (CV={cv:.2f})，建議啟用移動平均平滑", "level": "warning"}
    if cv > 0.3:
        return {"text": f"需求波動中等 (CV={cv:.2f})，移動平均可能有幫助", "level": "info"}
    return {"text": f"需求相對穩定 (CV={cv:.2f})，移動平均效果有限", "level": "success"}


@app.route("/api/ma-detail", methods=["POST"])
def ma_detail():
    """
    Compute moving-average detail for a single SKU (pure function).

    Input: the monthly data the client already has from /api/calculate.
    No file or session lookup needed.
    """
    if not MODULES_AVAILABLE:
        return _jsonify_error(ErrorCode.INTERNAL_ERROR, "核心模組未載入")

    body = request.get_json(silent=True) or {}

    site = body.get("site", "")
    sku = body.get("sku", "")
    name = body.get("name", "")
    abc_class = body.get("abcClass") or body.get("abc_class") or ""

    monthly_data = body.get("monthlyData") or body.get("monthly_data")
    if not isinstance(monthly_data, dict) or not monthly_data:
        return _jsonify_error(ErrorCode.MISSING_MONTHLY_VALUES)

    # Coerce to float values; drop bad entries
    cleaned: Dict[str, float] = {}
    for k, v in monthly_data.items():
        try:
            cleaned[str(k)] = float(v)
        except (TypeError, ValueError):
            continue

    try:
        mean_demand = float(body.get("meanDemand", body.get("mean_demand", 0)) or 0)
        std_dev = float(body.get("stdDev", body.get("std_dev", 0)) or 0)
        total_qty = float(body.get("totalQty", body.get("total_qty", 0)) or 0)
        active_months = int(body.get("activeMonths", body.get("active_months", 0)) or 0)
        outliers_removed = int(body.get("outliersRemoved", body.get("outliers_removed", 0)) or 0)
        ma_window = int(body.get("maWindow", body.get("ma_window", 3)) or 3)
    except (TypeError, ValueError):
        return _jsonify_error(ErrorCode.INVALID_PARAMS, "統計欄位必須是數字")

    try:
        quarterly = _group_by_quarter(cleaned)
        filled = _find_filled_months(cleaned)
        recommendation = _ma_recommendation(std_dev, mean_demand)

        payload = {
            "site": site,
            "sku": sku,
            "name": name,
            "abc_class": abc_class,
            "monthly_data": cleaned,
            "quarterly_summary": quarterly,
            "filled_months": filled,
            "statistics": {
                "std_original": std_dev,
                "mean": mean_demand,
                "total_qty": total_qty,
                "active_months": active_months,
                "outliers_removed": outliers_removed,
            },
            "recommendation": recommendation,
            "ma_window": ma_window,
        }
        return _jsonify_success(payload)
    except Exception as e:  # noqa: BLE001
        logger.exception("MA detail failed")
        extra = {"detail": str(e)} if DEBUG_MODE else {}
        return _jsonify_error(ErrorCode.MA_COMPUTE_FAILED, **extra)


# ===========================================================================
# Error handlers (return JSON instead of HTML)
# ===========================================================================

@app.errorhandler(404)
def _handle_404(error):
    return _jsonify_error(ErrorCode.NOT_FOUND, f"路由不存在: {request.path}")


@app.errorhandler(405)
def _handle_405(error):
    return _jsonify_error(ErrorCode.METHOD_NOT_ALLOWED, f"{request.method} {request.path}")


@app.errorhandler(413)
@app.errorhandler(RequestEntityTooLarge)
def _handle_413(error):
    return _jsonify_error(ErrorCode.FILE_TOO_LARGE, f"檔案超過 {MAX_UPLOAD_MB}MB 限制")


@app.errorhandler(500)
def _handle_500(error):
    logger.exception("500 error")
    extra = {"detail": str(error)} if DEBUG_MODE else {}
    return _jsonify_error(ErrorCode.INTERNAL_ERROR, **extra)


# ===========================================================================
# Main
# ===========================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=DEBUG_MODE)
