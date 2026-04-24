# Safety Stock Automation — 開發規則

> 本檔案為 Claude Code 在本 repo 工作時的常駐規則。每次任務前必須遵守。

---

## 專案概要 / Project

- **後端**：Flask + Python 3.10（`safety-stock-automation/`，branch `feature/stateless-api`）
- **前端**：Next.js 16 + React 19 + TypeScript（`safety-stock-frontend/`，branch `main`）
- **部署**：Vercel（前端）+ Render Free（後端）
- **業務領域**：管材建材業採購安全庫存計算
- **詳細文件**：`TECHNICAL_SPEC.md`（技術）、`USER_GUIDE.md`（使用者）

---

## 設計哲學 / Design Philosophy

**最高原則：系統提供數據，使用者做決策。**

### 可以做
- 顯示客觀數字（CV、變化率、覆蓋天數）
- 用 UI 控件讓使用者自選參數
- 設定純技術參數的合理預設（Z-score、MAD constant）

### 絕對不行
- 加「系統建議你做 X」的訊息
- 自動分類好/壞/警告（除非使用者自訂閾值）
- 預設業務決策（補多少貨、何時下單）
- 假設使用者意圖

---

## 工作流程 / Workflow

### 改動前先討論

| 等級 | 範例 | 流程 |
|------|------|------|
| 大改動 | 新功能、改公式、改 API contract | 先寫計畫 → 討論 → 確認後實作 |
| 中改動 | 改現有行為、改 UI 流程、改型別 | 說明 what/why/which files → 等「OK」→ 實作 |
| 小改動 | typo、註解、格式化、明顯 bug | 直接修 → 回報做了什麼 |

### 計算類功能的特殊流程

實作前：
- 使用者可能提供預期輸出（常用 Excel 算出）
- 若使用者提供 → 實作必須對得上
- 若使用者未提供 → 寫公式前主動詢問至少一個預期範例

實作後：
1. **Code review** — 檢查可讀性、無 dead code、無 magic number、邊界處理
2. **Debug** — 確認 console/logs 無錯誤
3. **Test** — 跑相關測試，全綠
4. **Report** — 摘要改動內容與測試結果

任一步失敗 → 修完才能說「完成」。

---

## 程式碼品質 / Code Quality

### 必須遵守

- 業務邏輯必須有註解（例：「Z=2.05 對應 98% 服務水準」）
- 業務參數放 config / options，不寫死
- 同邏輯重複 ≥ 3 次 → 抽成 function
- 數字使用 ≥ 2 次 → 抽成命名常數
- 布林變數用 `is_` / `has_` / `can_` 前綴
- 不用 `except:` 抓所有錯誤，必須指定錯誤類型
- 不留 dead code，刪掉而不是註解掉

### 警示線（超過要在 commit message 說明原因，非絕對禁止）

- 單一函式 > 60 行 → 考慮拆分
- 單一檔案 > 800 行 → 考慮分模組
- 函式參數 > 5 個 → 考慮用 options object

---

## 計算正確性 — 零容忍 / Calculation Correctness

### 公式改動驗證流程（任何公式改動都必做）

1. 用真實資料的至少 5 個不同 SKU 跑計算
2. 每個 SKU 輸出完整 trace：
   - 輸入 series
   - 中間值（mean、std、MAD bounds、偵測到的 outliers）
   - 最終結果（SS、ROP、Max）
3. trace 格式化成使用者可貼到 Excel 對照
4. 標出可疑結果（例：SS > Max、負值）

### 使用者回報「數字看起來不對」時

- 預設為已確認的 bug，直到證明不是
- 不能用「四捨五入誤差」打發，必須展示算式
- 先調查再辯護

---

## 測試 / Testing

### 現況
- Python 單元測試：0 個
- Playwright E2E：33 個（全綠）

### 目標（棘輪原則 ratchet — 只能進步不能退步）
- `calculator.py` 新增程式碼 → 必須附單元測試
- 新增 API endpoint → 必須附至少一個單元測試
- 既有無測試的程式碼 → 不強迫回頭補，但若改到了，改的部分要補測試

### 硬性規則
- 覆蓋率不能 commit-to-commit 下降
- E2E push 前必須 100% 綠
- 新公式或計算 → 必須用真實 SAP 資料樣本驗證

---

## 不能改的東西 / Do Not Change Without Asking

| 項目 | 原因 |
|------|------|
| `_fill_missing_periods` 邏輯 | 已驗證所有 filter 組合都正確 |
| `_calculate_statistics` 內部流程 | MAD→MA 順序是刻意設計 |
| `case_converter.py` | snake↔camel 邊界，改了所有 API response 會炸 |
| API contract（`/api/calculate` 等） | 前端依賴精確結構 |
| Excel / SAP MM17 export 欄位結構 | 下游 SAP 匯入依賴格式 |
| `Granularity.days_per_period` 值（1/7/30） | 所有公式依賴這些值 |
| `material_master.json` 結構 | 前後端都依賴此格式 |
| CORS 設定 | 改了 production 會斷 |
| `localStorage` key `ss-workflow:v1` | 改了所有使用者暫存失效 |

---

## 溝通 / Communication

- 全程**繁體中文**（討論、回報、commit message、註解）
- **不使用 emoji**（程式碼、UI、回報、commit message 都不用）
- 回報用條列式
- 不確定就問，不要猜
- Commit message 格式：`feat:` / `fix:` / `docs:` / `refactor:` / `test:` / `chore:`
- 一個 commit = 一個邏輯改動
- Message 寫「為什麼」，不只是「改什麼」

---

## 已知陷阱 / Known Gotchas

- **Render Free tier** 閒置會休眠，首次請求 30-60 秒
- **camelCase boundary**：後端 snake_case → 前端 camelCase。Export 函式必須轉回 snake_case（comparison dict 曾踩過此坑）
- **`_fill_missing_periods` 的 `selectedMonths`** 是「跳過」非「填零」。新功能若依賴 series 長度必須注意
- **`working_days_per_month`** 只在 monthly granularity 下覆寫 `days_per_period`，影響所有計算（SS/ROP/Max/Daily）
- **`localStorage` key 是 `ss-workflow:v1`** — 不可隨意改

---

## 進行中的開發決策 / Active Development Decisions

以下決策是經過長時間討論後確定的，必須遵守：

### Phase 1：趨勢偵測（已實作）
- 使用者選擇模式（Short-term / YoY / None），預設 None
- **不**自動分類 rising/declining，只顯示原始百分比
- YoY 條件不滿足時必須灰掉（需跨 2 年 + 同月份重複 + selectedMonths 在兩年都有資料）
- 特殊標籤判定優先級：全零→期數不足→非連續月份→New→Discontinued→正常計算
- 奇數長度 series：中間點丟棄，前後半對稱比較
- YoY 只比最近兩年，只取兩年共有月份（對齊基準）

### Phase 2a：日均需求（已實作）
- 有 `workingDaysPerMonth` 輸入框（僅 Monthly 粒度顯示）
- 此值覆寫 `days_per_period`，影響所有計算（SS/ROP/Max/Daily）
- 空值或 30 = 日曆天（與舊版行為一致）
- DAILY 欄位前端計算（meanDemand / daysPerPeriod），可排序

### Phase 2b：回測
- 已決定**不做**
- 使用者需驗證可信度時手動處理即可
