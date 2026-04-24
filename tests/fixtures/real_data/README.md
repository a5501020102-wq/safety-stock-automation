# tests/fixtures/real_data/

此目錄存放從 SAP 匯出的真實 SKU 測試資料。

## 用途

- 用於 calculator.py 的整合測試驗證
- 搭配 Excel 手算結果對照，確保計算正確性

## 注意事項

- **此目錄下的所有檔案（除本 README）已被 .gitignore 排除**
- 請勿將真實 SAP 資料提交到 git
- JSON fixture 命名規則：`sap_{sku_type}.json`（例：`sap_class_a.json`）

## 預計結構（Phase 1 / Step 5）

```
real_data/
  sap_class_a.json       # A 類常用品
  sap_class_b.json       # B 類中等
  sap_class_c.json       # C 類零星
  sap_seasonal.json      # 季節性品項
  sap_discontinued.json  # 停用品
```

每個 JSON 包含：輸入 series、Excel 手算的預期輸出、容許誤差（tolerance）。
