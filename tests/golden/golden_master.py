"""
黃金樣本（golden master）擷取與比對工具。

用途：重構前先用真實資料擷取 /api/calculate 與兩種匯出的完整輸出，
重構後再擷取一次並逐值比對，證明重構沒有改變任何計算結果或匯出內容。

用法：
    python tests/golden/golden_master.py capture --sales <銷貨檔> --out <輸出資料夾>
    python tests/golden/golden_master.py compare <基準資料夾> <新資料夾>

注意：輸出含公司真實資料，輸出資料夾必須放在 git repo 之外。
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path
from typing import Any

import openpyxl

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

# 每次執行都會變動、與計算結果無關的欄位，比對時排除
VOLATILE_KEYS = frozenset({"executedAt", "executionTimeMs", "runDate", "uploadedAt", "fileId"})

# 匯出檔內的執行時間戳（例如「2026-10-28 11:05:33」），比對時以固定字串取代
TIMESTAMP_PATTERN = re.compile(r"\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}(:\d{2})?")
TIMESTAMP_PLACEHOLDER = "<TIMESTAMP>"

# 匯出檔名內的時間戳（例如 safety_stock_all_20261028_110533.xlsx）
FILENAME_TIMESTAMP_PATTERN = re.compile(r"\d{8}_\d{6}")

# 上傳暫存檔以 uuid4 命名（例如 parameters.salesFilename），每次上傳都不同
UUID_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
UUID_PLACEHOLDER = "<UUID>"

# 浮點數比對容許誤差：只吸收 JSON 序列化的位數差異，不吸收任何計算差異
FLOAT_TOLERANCE = 1e-9

BASE_PARAMS: dict[str, Any] = {
    "selectedMonths": list(range(1, 13)),
    "leadTime": 30,
    "minMonths": 2,
    "enableOutlier": True,
    "enableMa": False,
    "maWindow": 3,
    "zScores": {"A": 2.05, "B": 1.65, "C": 1.28},
    "abcThresholds": {"A": 0.80, "B": 0.95},
    "targetSite": None,
    "trendMode": "none",
}

CALC_MODES = ("all", "total", "compare")
GRANULARITIES = ("daily", "weekly", "monthly")

# 在月粒度 / 分倉模式上，逐一切換單一參數，覆蓋各條計算分支
MONTHLY_VARIANTS: dict[str, dict[str, Any]] = {
    "outlier_off": {"enableOutlier": False},
    "ma_on": {"enableMa": True, "maWindow": 3},
    "trend_short": {"trendMode": "short"},
    "trend_yoy": {"trendMode": "yoy"},
    "working_days_22": {"workingDaysPerMonth": 22},
    "lead_time_60": {"leadTime": 60},
    "months_h1": {"selectedMonths": [1, 2, 3, 4, 5, 6]},
    "min_months_6": {"minMonths": 6},
    "date_range_2025": {"dateFrom": "2025-01-01", "dateTo": "2025-12-31"},
}


def build_scenarios() -> dict[str, dict[str, Any]]:
    """組出所有情境：3 模式 x 3 粒度，再加上月粒度的參數變化。"""
    scenarios: dict[str, dict[str, Any]] = {}
    for mode in CALC_MODES:
        for granularity in GRANULARITIES:
            scenarios[f"{mode}_{granularity}"] = {
                **BASE_PARAMS, "calcMode": mode, "granularity": granularity,
            }
    for name, override in MONTHLY_VARIANTS.items():
        scenarios[f"all_monthly_{name}"] = {
            **BASE_PARAMS, "calcMode": "all", "granularity": "monthly", **override,
        }
    return scenarios


# ma-detail 是純函式，用固定輸入覆蓋：缺月補齊、跨年分季、無效值丟棄、三種變異程度
MA_DETAIL_CASES: dict[str, dict[str, Any]] = {
    "gap_and_cross_year": {
        "site": "1002", "sku": "SKU-A", "name": "測試品", "abcClass": "A",
        "monthlyData": {"2024-11": 10, "2024-12": 0, "2025-02": 25.5, "2025-04": 7},
        "meanDemand": 10.6, "stdDev": 9.1, "totalQty": 42.5, "activeMonths": 3,
        "outliersRemoved": 1, "maWindow": 3,
    },
    "drops_bad_values": {
        "sku": "SKU-B", "monthlyData": {"2025-01": "abc", "2025-02": None, "2025-03": "4"},
        "mean_demand": 4, "std_dev": 1.5, "ma_window": 6,
    },
    "zero_std": {"sku": "SKU-C", "monthlyData": {"2025-05": 3, "2025-06": 3}, "meanDemand": 3, "stdDev": 0},
    "moderate_cv": {"sku": "SKU-D", "monthlyData": {"2025-07": 3}, "meanDemand": 10, "stdDev": 4},
    "zero_mean": {"sku": "SKU-E", "monthlyData": {"2025-07": 3}, "meanDemand": 0, "stdDev": 4},
    "missing_monthly": {"sku": "SKU-F", "monthlyData": {}},
    "non_numeric_stats": {"sku": "SKU-G", "monthlyData": {"2025-01": 1}, "stdDev": "x"},
}


def _record(resp: Any) -> dict[str, Any]:
    return {"status": resp.status_code, "body": resp.get_json(silent=True)}


def _upload(client: Any, file_type: str, path: Path) -> Any:
    with path.open("rb") as fh:
        return client.post(
            f"/api/upload/{file_type}",
            data={"file": (fh, path.name)},
            content_type="multipart/form-data",
        )


def _upload_ok(client: Any, file_type: str, path: Path, out_dir: Path) -> str:
    resp = _upload(client, file_type, path)
    body = resp.get_json()
    if resp.status_code != 200 or not body.get("success"):
        raise RuntimeError(f"上傳 {file_type} 失敗：{body}")
    _write_json(out_dir / "api" / f"upload_{file_type}.json", _record(resp))
    return body["fileId"]


def _upload_bytes(client: Any, url: str, filename: str, content: bytes) -> Any:
    return client.post(url, data={"file": (io.BytesIO(content), filename)}, content_type="multipart/form-data")


def _capture_api_surface(client: Any, sales_file_id: str, out_dir: Path) -> None:
    """擷取計算以外的端點與錯誤回應，確保重構後狀態碼、錯誤碼與訊息不變。"""
    base_params = {**BASE_PARAMS, "calcMode": "all", "granularity": "monthly"}
    calc_cases: dict[str, dict[str, Any]] = {
        "missing_sales_file": {"params": base_params},
        "unknown_file_id": {"salesFileId": "00000000-0000-0000-0000-000000000000", "params": base_params},
        "bad_calc_mode": {"salesFileId": sales_file_id, "params": {**base_params, "calcMode": "x"}},
        "bad_z_type": {"salesFileId": sales_file_id, "params": {**base_params, "zScores": [1]}},
        "bad_z_range": {"salesFileId": sales_file_id, "params": {**base_params, "zScores": {"A": 9}}},
        "bad_z_value": {"salesFileId": sales_file_id, "params": {**base_params, "zScores": {"B": "x"}}},
        "bad_abc_order": {"salesFileId": sales_file_id, "params": {**base_params, "abcThresholds": {"A": 0.9, "B": 0.8}}},
        "bad_abc_range": {"salesFileId": sales_file_id, "params": {**base_params, "abcThresholds": {"A": 1.2}}},
        "bad_months": {"salesFileId": sales_file_id, "params": {**base_params, "selectedMonths": [0, 13]}},
        "bad_lead_time": {"salesFileId": sales_file_id, "params": {**base_params, "leadTime": 400}},
        "bad_lead_time_type": {"salesFileId": sales_file_id, "params": {**base_params, "leadTime": "x"}},
        "bad_min_months": {"salesFileId": sales_file_id, "params": {**base_params, "minMonths": 13}},
        "bad_ma_window": {"salesFileId": sales_file_id, "params": {**base_params, "maWindow": 1}},
        "bad_granularity": {"salesFileId": sales_file_id, "params": {**base_params, "granularity": "yearly"}},
        # 以下無效值會被靜默忽略、回到預設值（既有行為）
        "ignored_trend_mode": {"salesFileId": sales_file_id, "params": {**base_params, "trendMode": "x"}},
        "ignored_working_days": {"salesFileId": sales_file_id, "params": {**base_params, "workingDaysPerMonth": 40}},
        "ignored_bad_dates": {"salesFileId": sales_file_id, "params": {**base_params, "dateFrom": "abc", "dateTo": 5}},
        "flat_snake_body": {"sales_file_id": sales_file_id, "calc_mode": "total", "lead_time": 45, "granularity": "monthly"},
    }
    records: dict[str, Any] = {
        f"calculate_{name}": _record(client.post("/api/calculate", json=body))
        for name, body in calc_cases.items()
    }

    records["index"] = _record(client.get("/"))
    records["health"] = _record(client.get("/health"))
    records["material_groups"] = _record(client.get("/api/material-groups"))
    records["not_found"] = _record(client.get("/api/nope"))
    records["method_not_allowed"] = _record(client.get("/api/calculate"))
    records["legacy_status"] = {"status": client.get("/legacy").status_code}

    records["upload_bad_type"] = _record(_upload_bytes(client, "/api/upload/foo", "a.xlsx", b"x"))
    records["upload_no_file"] = _record(client.post("/api/upload/sales", data={}, content_type="multipart/form-data"))
    records["upload_bad_ext"] = _record(_upload_bytes(client, "/api/upload/sales", "a.txt", b"x"))
    records["upload_corrupt"] = _record(_upload_bytes(client, "/api/upload/sales", "a.xlsx", b"not excel"))

    records["export_sap_bad_format"] = _record(client.post("/api/export/sap", json={"format": "pdf"}))
    records["export_sap_no_site_rows"] = _record(client.post(
        "/api/export/sap", json={"results": [{"site": "1002", "sku": "X"}], "siteFilter": "9999"}))
    records["export_excel_no_site_rows"] = _record(client.post(
        "/api/export/excel", json={"results": [{"site": "1002", "sku": "X"}], "siteFilter": "9999"}))

    # 出貨點篩選會進入下載檔名，特殊字元必須被替換
    site = "10 02/x"
    site_rows = {"results": [{"site": site, "sku": "X", "safetyStock": 1}], "summary": {}}
    site_exports = {
        "excel_single": ("/api/export/excel", {**site_rows, "mode": "all", "siteFilter": site}),
        "excel_compare": ("/api/export/excel", {
            "mode": "compare", "siteFilter": site, "comparison": {},
            "allSummary": site_rows, "totalSummary": site_rows,
        }),
        "sap_csv": ("/api/export/sap", {**site_rows, "mode": "total", "siteFilter": site, "format": "csv"}),
    }
    for name, (url, body) in site_exports.items():
        resp = client.post(url, json=body)
        records[f"export_site_{name}"] = {"status": resp.status_code, "headers": _export_headers(resp)}

    for name, body in MA_DETAIL_CASES.items():
        records[f"ma_detail_{name}"] = _record(client.post("/api/ma-detail", json=body))

    for name, record in records.items():
        _write_json(out_dir / "api" / f"{name}.json", record)


def _xlsx_to_values(data: bytes) -> dict[str, list[list[Any]]]:
    workbook = openpyxl.load_workbook(io.BytesIO(data), data_only=False)
    return {
        sheet.title: [list(row) for row in sheet.iter_rows(values_only=True)]
        for sheet in workbook.worksheets
    }


def _export_bodies(calc_body: dict[str, Any], params: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """依計算結果組出與前端相同結構的匯出請求。"""
    mode = calc_body["mode"]
    common = {"mode": mode, "siteFilter": None, "granularity": params["granularity"], "calcParams": params}
    if mode == "compare":
        payload = {
            "comparison": calc_body["comparison"],
            "allSummary": calc_body["allSummary"],
            "totalSummary": calc_body["totalSummary"],
        }
        return {
            "excel.xlsx": {**common, **payload},
            "sap_all.xlsx": {**common, **payload, "format": "xlsx", "sapMode": "all", "includeHeader": True},
            "sap_total.csv": {**common, **payload, "format": "csv", "sapMode": "total", "includeHeader": True},
        }
    payload = {"summary": calc_body["summary"], "results": calc_body["results"]}
    return {
        "excel.xlsx": {**common, **payload},
        "sap.xlsx": {**common, **payload, "format": "xlsx", "includeHeader": True},
        "sap.csv": {**common, **payload, "format": "csv", "includeHeader": True},
    }


def capture(sales: Path, price: Path | None, plan: Path | None, out_dir: Path) -> None:
    from app import app

    (out_dir / "api").mkdir(parents=True, exist_ok=True)
    client = app.test_client()
    file_ids = {
        "salesFileId": _upload_ok(client, "sales", sales, out_dir),
        "priceFileId": _upload_ok(client, "price", price, out_dir) if price else None,
        "planFileId": _upload_ok(client, "plan", plan, out_dir) if plan else None,
    }
    _capture_api_surface(client, file_ids["salesFileId"], out_dir)

    for name, params in build_scenarios().items():
        resp = client.post("/api/calculate", json={**file_ids, "params": params})
        calc_body = resp.get_json()
        scenario_dir = out_dir / name
        scenario_dir.mkdir(exist_ok=True)
        _write_json(scenario_dir / "calculate.json", {"status": resp.status_code, "body": calc_body})
        if resp.status_code != 200:
            print(f"[{name}] calculate HTTP {resp.status_code}：{calc_body.get('code')}")
            continue

        headers: dict[str, dict[str, str]] = {}
        for filename, export_body in _export_bodies(calc_body, params).items():
            endpoint = "/api/export/excel" if filename.startswith("excel") else "/api/export/sap"
            export_resp = client.post(endpoint, json=export_body)
            if export_resp.status_code != 200:
                _write_json(scenario_dir / f"{filename}.error.json", export_resp.get_json())
                print(f"[{name}] {filename} HTTP {export_resp.status_code}")
                continue
            (scenario_dir / filename).write_bytes(export_resp.data)
            headers[filename] = _export_headers(export_resp)
        _write_json(scenario_dir / "export_headers.json", headers)
        print(f"[{name}] OK")


def _export_headers(resp: Any) -> dict[str, str]:
    """下載檔名與 MIME 類型也是前端依賴的 contract，時間戳遮蔽後一併比對。"""
    disposition = FILENAME_TIMESTAMP_PATTERN.sub(TIMESTAMP_PLACEHOLDER, resp.headers.get("Content-Disposition", ""))
    return {"Content-Type": resp.headers.get("Content-Type", ""), "Content-Disposition": disposition}


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


def _normalize(value: Any) -> Any:
    """移除易變欄位、遮蔽時間戳，讓兩次擷取可以逐值比對。"""
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items() if k not in VOLATILE_KEYS}
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    if isinstance(value, str):
        masked = TIMESTAMP_PATTERN.sub(TIMESTAMP_PLACEHOLDER, value)
        return UUID_PATTERN.sub(UUID_PLACEHOLDER, masked)
    if hasattr(value, "isoformat"):
        return TIMESTAMP_PLACEHOLDER
    return value


def _load_normalized(path: Path) -> Any:
    if path.suffix == ".json":
        return _normalize(json.loads(path.read_text(encoding="utf-8")))
    if path.suffix == ".xlsx":
        return _normalize(_xlsx_to_values(path.read_bytes()))
    if path.suffix == ".csv":
        text = path.read_bytes().decode("utf-8-sig")
        return _normalize(list(csv.reader(io.StringIO(text))))
    raise ValueError(f"不支援的檔案類型：{path}")


def _diff(a: Any, b: Any, where: str, out: list[str]) -> None:
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                out.append(f"{where}.{key}: 只存在於{'新' if key not in a else '基準'}")
            else:
                _diff(a[key], b[key], f"{where}.{key}", out)
        return
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{where}: 長度 {len(a)} != {len(b)}")
        # 長度差異已在上面回報，這裡只比對共同的部分
        for i, (x, y) in enumerate(zip(a, b, strict=False)):
            _diff(x, y, f"{where}[{i}]", out)
        return
    is_numeric_pair = isinstance(a, (int, float)) and isinstance(b, (int, float)) \
        and not isinstance(a, bool) and not isinstance(b, bool)
    if is_numeric_pair:
        if abs(a - b) > FLOAT_TOLERANCE:
            out.append(f"{where}: {a!r} != {b!r}")
        return
    # Python 中 True == 1，型別不同也要視為差異
    if type(a) is not type(b) or a != b:
        out.append(f"{where}: {a!r} != {b!r}")


def compare(baseline: Path, candidate: Path) -> int:
    base_files = {p.relative_to(baseline) for p in baseline.rglob("*") if p.is_file()}
    cand_files = {p.relative_to(candidate) for p in candidate.rglob("*") if p.is_file()}
    problems: list[str] = [f"缺少檔案：{p}" for p in sorted(base_files - cand_files)]
    problems += [f"多出檔案：{p}" for p in sorted(cand_files - base_files)]

    for rel in sorted(base_files & cand_files):
        diffs: list[str] = []
        _diff(_load_normalized(baseline / rel), _load_normalized(candidate / rel), str(rel), diffs)
        problems += diffs

    print(f"比對檔案數：{len(base_files & cand_files)}，差異數：{len(problems)}")
    for line in problems[:200]:
        print(line)
    return 0 if not problems else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    cap = sub.add_parser("capture")
    cap.add_argument("--sales", type=Path, required=True)
    cap.add_argument("--price", type=Path)
    cap.add_argument("--plan", type=Path)
    cap.add_argument("--out", type=Path, required=True)
    cmp_ = sub.add_parser("compare")
    cmp_.add_argument("baseline", type=Path)
    cmp_.add_argument("candidate", type=Path)
    args = parser.parse_args()

    if args.command == "capture":
        if REPO_ROOT in args.out.resolve().parents:
            parser.error("輸出含真實資料，--out 必須在 git repo 之外")
        capture(args.sales, args.price, args.plan, args.out)
        return 0
    return compare(args.baseline, args.candidate)


if __name__ == "__main__":
    sys.exit(main())
