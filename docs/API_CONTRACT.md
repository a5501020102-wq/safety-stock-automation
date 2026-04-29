# Safety Stock Automation API Contract

**Version:** 5.0.0 (Stateless)
**Base URL (local):** `http://localhost:5000`
**Base URL (production):** `https://safety-stock-automation.onrender.com`
**Last Updated:** 2026-04-15

---

## Conventions

- All responses are JSON except binary exports (Excel / CSV / SAP MM17).
- **All keys are `camelCase`** (converted from Python `snake_case` at the boundary).
- Success envelope: `{ success: true, ...payload }`
- Error envelope: `{ success: false, error: string, code: string, detail?: string }`
- Dates use ISO 8601 (`YYYY-MM-DDTHH:mm:ssZ`) except month-level fields which use `YYYY-MM`.
- `Content-Disposition` is exposed for file downloads (use via CORS `expose_headers`).

---

## Error Codes

| Code | HTTP | Meaning |
|------|------|---------|
| `NO_FILE` | 400 | No file in multipart request |
| `EMPTY_FILENAME` | 400 | Uploaded file has empty name |
| `INVALID_FILE_TYPE` | 400 | `file_type` is not sales/price/plan |
| `INVALID_EXTENSION` | 400 | Extension not .xlsx or .xls |
| `FILE_TOO_LARGE` | 413 | Over 50MB |
| `PARSE_ERROR` | 400 | Excel could not be parsed |
| `FILE_NOT_FOUND` | 404 | fileId expired or invalid |
| `MISSING_SALES_FILE` | 400 | `salesFileId` not provided |
| `INVALID_PARAMS` | 400 | Calculation params invalid |
| `CALC_FAILED` | 500 | Calculation threw unhandled error |
| `NO_RESULTS` | 400 | No results to export |
| `EXPORT_FAILED` | 500 | Export generation failed |
| `INVALID_EXPORT_FORMAT` | 400 | Export format not xlsx/csv |
| `MISSING_MONTHLY_VALUES` | 400 | MA detail missing `monthlyData` |
| `MA_COMPUTE_FAILED` | 500 | MA detail computation failed |
| `NOT_FOUND` | 404 | Route not found |
| `METHOD_NOT_ALLOWED` | 405 | HTTP method not allowed |
| `BAD_REQUEST` | 400 | Malformed JSON |
| `INTERNAL_ERROR` | 500 | Unhandled exception |

---

## Endpoints

### `GET /`

API health and service info.

**Response 200:**
```json
{
  "status": "ok",
  "service": "Safety Stock Automation API",
  "version": "5.0.0",
  "legacyUi": "/legacy",
  "modulesAvailable": true
}
```

---

### `GET /legacy`

Legacy Jinja2 UI (preserved during migration). Returns HTML.

---

### `POST /api/upload/<fileType>`

Upload an Excel file. `fileType` is `sales`, `price`, or `plan`.

**Request:** `multipart/form-data` with field `file`.

**Response 200 (sales):**
```json
{
  "success": true,
  "fileId": "3f9a7c12-...",
  "filename": "2026_sales.xlsx",
  "fileSizeBytes": 240592,
  "uploadedAt": "2026-04-15T08:30:00Z",
  "recordCount": 2741,
  "detectedSites": ["1002", "1003", "1004"],
  "detectedSkus": 333,
  "dateRange": { "start": "2026-01", "end": "2026-04" },
  "maxDate": "2026-04-01T00:00:00",
  "skippedDateCount": 0,
  "hasPriceData": false,
  "hasStockData": false
}
```

**Response 200 (price):**
```json
{
  "success": true,
  "fileId": "...",
  "filename": "prices.xlsx",
  "fileSizeBytes": 12345,
  "uploadedAt": "...",
  "recordCount": 250
}
```

**Response 200 (plan):**
```json
{
  "success": true,
  "fileId": "...",
  "filename": "plan.xlsx",
  "fileSizeBytes": 54321,
  "uploadedAt": "...",
  "itemCount": 150,
  "detectedMonths": ["202601", "202602", "202603"],
  "hasCumulativeColumns": false
}
```

**Errors:** `NO_FILE`, `EMPTY_FILENAME`, `INVALID_FILE_TYPE`, `INVALID_EXTENSION`, `PARSE_ERROR`, `FILE_TOO_LARGE`

---

### `POST /api/calculate`

Run safety stock calculation. Returns complete results (stateless).

**Request body:**
```json
{
  "salesFileId": "3f9a7c12-...",
  "priceFileId": null,
  "planFileId": null,
  "params": {
    "calcMode": "all",
    "selectedMonths": [1,2,3,4,5,6,7,8,9,10,11,12],
    "leadTime": 30,
    "minMonths": 2,
    "enableOutlier": true,
    "enableMa": false,
    "maWindow": 3,
    "zScores": { "A": 2.05, "B": 1.65, "C": 1.28 },
    "abcThresholds": { "A": 0.80, "B": 0.95 },
    "targetSite": null
  }
}
```

`params` may also be passed at the top level (flat), both shapes accepted.
Parameter keys accept both camelCase and snake_case (backwards compat).

**Response 200 (single mode: all / total):**
```json
{
  "success": true,
  "mode": "all",
  "version": "5.0.0",
  "parameters": { ...ParametersSnapshot },
  "summary": { ...CalculationSummary },
  "results": [ ...SkuResult ],
  "excluded": [ ...ExcludedSku ]
}
```

**Response 200 (compare mode):**
```json
{
  "success": true,
  "mode": "compare",
  "version": "5.0.0",
  "parameters": { ...ParametersSnapshot },
  "comparison": { ...ComparisonStats },
  "allSummary": {
    "summary": { ...CalculationSummary },
    "results": [ ...SkuResult ],
    "excluded": [ ...ExcludedSku ]
  },
  "totalSummary": { ...same shape }
}
```

**Errors:** `MISSING_SALES_FILE`, `FILE_NOT_FOUND`, `INVALID_PARAMS`, `PARSE_ERROR`, `CALC_FAILED`

---

### `POST /api/export/excel`

Generate Excel file from results payload. Returns binary xlsx.

**Request body (non-compare):**
```json
{
  "mode": "all",
  "siteFilter": null,
  "summary": { ...CalculationSummary },
  "results": [ ...SkuResult ]
}
```

**Request body (compare):**
```json
{
  "mode": "compare",
  "siteFilter": null,
  "comparison": { ...ComparisonStats },
  "allSummary": { "summary": {...}, "results": [...] },
  "totalSummary": { "summary": {...}, "results": [...] }
}
```

**Response 200:** `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` with `Content-Disposition: attachment; filename=safety_stock_all_20260415_...xlsx`

**Errors:** `NO_RESULTS`, `EXPORT_FAILED`

---

### `POST /api/export/sap`

Generate SAP MM17 file. Same stateless pattern.

**Request body:**
```json
{
  "format": "xlsx",
  "mode": "all",
  "sapMode": "all",
  "siteFilter": null,
  "includeHeader": true,
  "summary": { ... },
  "results": [ ... ]
}
```

- `format`: `"xlsx"` or `"csv"`
- `sapMode`: only used when `mode === "compare"`, selects which side to export

**Response 200:** Binary xlsx or csv.

---

### `POST /api/ma-detail`

Pure-function moving-average detail for a single SKU. No file or session needed — pass the data the client already has.

**Request body:**
```json
{
  "site": "1002",
  "sku": "235M202003151",
  "name": "太平洋 PVC 1.6mm",
  "abcClass": "A",
  "monthlyData": {
    "2026-01": 39800,
    "2026-02": 33500,
    "2026-03": 46100
  },
  "meanDemand": 39800,
  "stdDev": 6300,
  "totalQty": 170400,
  "activeMonths": 3,
  "outliersRemoved": 0,
  "maWindow": 3
}
```

**Response 200:**
```json
{
  "success": true,
  "site": "1002",
  "sku": "235M202003151",
  "name": "太平洋 PVC 1.6mm",
  "abcClass": "A",
  "monthlyData": { "2026-01": 39800, ... },
  "quarterlySummary": {
    "Q1 2026": {
      "months": ["2026-01", "2026-02", "2026-03"],
      "values": [39800, 33500, 46100],
      "avg": 39800,
      "total": 119400,
      "count": 3
    }
  },
  "filledMonths": [],
  "statistics": {
    "stdOriginal": 6300,
    "mean": 39800,
    "totalQty": 170400,
    "activeMonths": 3,
    "outliersRemoved": 0
  },
  "recommendation": {
    "text": "需求相對穩定 (CV=0.16)，移動平均效果有限",
    "level": "success"
  },
  "maWindow": 3
}
```

**Errors:** `MISSING_MONTHLY_VALUES`, `INVALID_PARAMS`, `MA_COMPUTE_FAILED`

---

## TypeScript Interfaces

Drop-in types for the Next.js frontend:

```typescript
// lib/types.ts

export type CalcMode = 'all' | 'total' | 'compare';
export type AbcClass = 'A' | 'B' | 'C';
export type StockStatus = 'red' | 'green' | 'blue' | 'gray';

export interface SkuResult {
  site: string;
  sku: string;
  name: string;
  abcClass: AbcClass;
  abcGrade: AbcClass;
  status: StockStatus;
  totalQty: number;
  totalValue: number;
  activeMonths: number;
  totalMonths: number;
  monthsCount: number;
  meanDemand: number;
  avgMonthlyDemand: number;
  stdDev: number;
  cv: number;
  safetyStock: number;
  safetyStockValue: number;
  reorderPoint: number;
  maxInventory: number;
  leadTimeDays: number;
  currentStock: number | null;
  outliersRemoved: number;
  price: number;
  enableMa: boolean;
  monthlyValues: number[];
}

export interface ExcludedSku {
  site: string;
  sku: string;
  name: string | null;
  activeMonths: number;
  monthsCount: number;
  totalQty: number;
  reason: string;
}

export interface CalculationSummary {
  runDate: string;
  totalSkus: number;
  excludedCount: number;
  totalOutliersRemoved: number;
  shortageRiskCount: number;
  healthyCount: number;
  overstockRiskCount: number;
  noDataCount: number;
  movingAverageEnabled: boolean;
  maWindow: number | null;
  leadTimeDays: number;
  minMonths: number;
  calcMode: CalcMode;
}

export interface ComparisonStats {
  totalAllSafetyStock: number;
  totalTotalSafetyStock: number;
  inventorySaved: number;
  savingsPercentage: number;
  totalAllValue: number;
  totalTotalValue: number;
  costSaved: number;
  savingsValuePercentage: number;
  allSkuCount: number;
  totalSkuCount: number;
}

export interface ParametersSnapshot {
  calcMode: CalcMode;
  dataMinDate: string | null;
  dataMaxDate: string | null;
  dataMaxDateExact: string | null;
  excludedMonth: string | null;
  selectedMonths: number[];
  leadTimeDays: number;
  minMonths: number;
  zScores: { A: number; B: number; C: number };
  abcThresholds: { A: number; B: number };
  enableOutlier: boolean;
  enableMa: boolean;
  maWindow: number | null;
  salesFilename: string | null;
  priceFilename: string | null;
  planFilename: string | null;
  executedAt: string;
  executionTimeMs: number;
}

export interface SingleModeResponse {
  success: true;
  mode: 'all' | 'total';
  version: string;
  parameters: ParametersSnapshot;
  summary: CalculationSummary;
  results: SkuResult[];
  excluded: ExcludedSku[];
}

export interface CompareModeResponse {
  success: true;
  mode: 'compare';
  version: string;
  parameters: ParametersSnapshot;
  comparison: ComparisonStats;
  allSummary: { summary: CalculationSummary; results: SkuResult[]; excluded: ExcludedSku[] };
  totalSummary: { summary: CalculationSummary; results: SkuResult[]; excluded: ExcludedSku[] };
}

export type CalculationResponse = SingleModeResponse | CompareModeResponse;

export interface ApiError {
  success: false;
  error: string;
  code: string;
  detail?: string;
}

export interface UploadSalesResponse {
  success: true;
  fileId: string;
  filename: string;
  fileSizeBytes: number;
  uploadedAt: string;
  recordCount: number;
  detectedSites: string[];
  detectedSkus: number;
  dateRange: { start: string | null; end: string | null };
  maxDate: string | null;
  skippedDateCount: number;
  hasPriceData: boolean;
  hasStockData: boolean;
}
```

---

## Local Development

```bash
# Backend (Flask API)
cd safety-stock-automation
pip install -r requirements.txt
python app.py
# Runs on http://localhost:5000

# Frontend (Next.js, separate repo)
cd safety-stock-frontend
npm install
npm run dev
# Runs on http://localhost:3000
```

Set `NEXT_PUBLIC_API_URL=http://localhost:5000` in the frontend `.env.local`.

---

## CORS

- `http://localhost:3000` and `http://127.0.0.1:3000` always allowed.
- Any `https://*.vercel.app` allowed (Vercel preview URLs).
- Extra origins via `ALLOWED_ORIGINS` env var (comma-separated).
- `Content-Disposition` exposed so frontend can read the download filename.
