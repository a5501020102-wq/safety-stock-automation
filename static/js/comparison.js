/**
 * 對比視圖模組 - 出貨點篩選修復版（v4.5.1）
 * Comparison View Module - Site Filter Fix
 *
 * Version: 4.5.1
 * Author: 松鼠
 * Last Updated: 2026-01-27
 *
 * v4.5.1 緊急修復：
 * - 修復出貨點篩選未生效問題
 * - Excel 和 SAP 匯出都支援出貨點篩選
 * - 增強參數驗證和錯誤提示
 */

(function () {
  "use strict";

  class ComparisonView {
    constructor() {
      this.currentData = null;
      this.eventsBound = false;

      this.boundHandlers = {
        click: null,
        input: null,
        change: null,
        keydown: null,
      };

      this.pagination = {
        all: { currentPage: 1, pageSize: 20, filteredResults: [] },
        total: { currentPage: 1, pageSize: 20, filteredResults: [] },
      };

      this.searchTerms = { all: "", total: "" };

      this.sorting = {
        all: { column: null, direction: "asc" },
        total: { column: null, direction: "asc" },
      };

      this.searchDebounceTimers = { all: null, total: null };

      this.LARGE_DATASET_THRESHOLD = 5000;

      this.API_BASE = "";

      this.init();
      this.bindGlobalEvents();
    }

    init() {
      console.log(" Comparison View 已載入 (v4.5.1 - Site Filter Fix)");
    }

    // =============================
    // 生命週期管理
    // =============================

    destroy() {
      console.log(" 正在清理 ComparisonView...");
      this.unbindGlobalEvents();

      Object.keys(this.searchDebounceTimers).forEach((key) => {
        if (this.searchDebounceTimers[key]) {
          clearTimeout(this.searchDebounceTimers[key]);
          this.searchDebounceTimers[key] = null;
        }
      });

      this.cleanupCharts();

      this.currentData = null;
      this.pagination = {
        all: { currentPage: 1, pageSize: 20, filteredResults: [] },
        total: { currentPage: 1, pageSize: 20, filteredResults: [] },
      };

      console.log(" ComparisonView 已清理完成");
    }

    cleanupCharts() {
      if (!window.Plotly) return;

      try {
        const div1 = document.getElementById("comparisonPlot1");
        const div2 = document.getElementById("comparisonPlot2");

        if (div1) window.Plotly.purge(div1);
        if (div2) window.Plotly.purge(div2);
      } catch (error) {
        console.warn(" 清理 Plotly 圖表時發生錯誤:", error);
      }
    }

    // =============================
    // 資料正規化
    // =============================

    getAllBucket(data) {
      return data?.all_summary || data?.all_data || null;
    }

    getTotalBucket(data) {
      return data?.total_summary || data?.total_data || null;
    }

    normalizeData(data) {
      const compRaw = data?.comparison || {};

      const normalizedComparison = {
        total_all_safety_stock:
          compRaw["分倉_總安全庫存"] ??
          compRaw.total_all_safety_stock ??
          compRaw.totalAllSafetyStock ??
          0,

        total_total_safety_stock:
          compRaw["總倉_總安全庫存"] ??
          compRaw.total_total_safety_stock ??
          compRaw.totalTotalSafetyStock ??
          0,

        inventory_saved:
          compRaw["節省數量"] ?? compRaw.inventory_saved ?? compRaw.inventorySaved ?? 0,

        savings_percentage:
          compRaw["節省比例"] ??
          compRaw.savings_percentage ??
          compRaw.savingsPercentage ??
          0,

        cost_saved: compRaw["節省價值"] ?? compRaw.cost_saved ?? compRaw.costSaved ?? 0,
      };

      const allSummary = data.all_summary || this.getAllBucket(data);
      const totalSummary = data.total_summary || this.getTotalBucket(data);

      const normalizeResults = (bucket) => {
        if (!bucket) return { results: [] };
        const results = Array.isArray(bucket.results) ? bucket.results : [];
        return {
          ...bucket,
          results: results.map((x) => this.normalizeResultItem(x)),
        };
      };

      return {
        ...data,
        comparison: normalizedComparison,
        all_summary: normalizeResults(allSummary),
        total_summary: normalizeResults(totalSummary),
        all_data: normalizeResults(allSummary),
        total_data: normalizeResults(totalSummary),
      };
    }

    normalizeResultItem(item) {
      const sku =
        item.sku ?? item.MATNR ?? item.material ?? item["料號"] ?? item["Material"] ?? "";

      const site =
        item.site ?? item.WERKS ?? item.plant ?? item["出貨點"] ?? item["Plant"] ?? "";

      const name = item.name ?? item["品名"] ?? item.description ?? "";

      const safety_stock = item.safety_stock ?? item["安全庫存"] ?? item["Safety Stock"] ?? 0;
      const reorder_point = item.reorder_point ?? item["再訂購點"] ?? item["Reorder Point"] ?? 0;
      const max_inventory = item.max_inventory ?? item["最大庫存"] ?? item["Maximum Stock"] ?? 0;

      return {
        ...item,
        sku: String(sku || "").trim(),
        site: String(site || "").trim(),
        name: String(name || "").trim(),

        avg_monthly_demand: item.mean_demand ?? item.avg_monthly_demand ?? 0,
        std_dev: item.std_deviation ?? item.std_dev ?? 0,
        cv: item.coefficient_of_variation ?? item.cv ?? 0,

        safety_stock,
        reorder_point,
        max_inventory,

        abc_grade: item.abc_grade ?? item.abc_class ?? item["ABC等級"] ?? "N/A",
        lead_time_days: item.lead_time_days ?? item["前置天數"] ?? 30,
        total_months: item.total_months ?? item.active_months ?? 0,
        months_count: item.active_months ?? item.months_count ?? item["資料月數"] ?? 0,
      };
    }

    // =============================
    // 主要渲染方法
    // =============================

    render(data) {
      try {
        if (!data) {
          throw new Error("沒有收到對比資料");
        }

        data = this.normalizeData(data);

        if (!data.comparison) {
          throw new Error("數據格式錯誤（missing comparison）");
        }

        this.currentData = data;

        this.pagination.all.filteredResults = data.all_summary?.results || [];
        this.pagination.total.filteredResults = data.total_summary?.results || [];
        this.pagination.all.currentPage = 1;
        this.pagination.total.currentPage = 1;

        const comparisonSection = document.getElementById("comparisonSection");
        const comparisonContent = document.getElementById("comparisonContent");

        if (!comparisonSection || !comparisonContent) {
          throw new Error("頁面元素缺失（comparisonSection 或 comparisonContent）");
        }

        comparisonSection.classList.remove("d-none");
        comparisonContent.innerHTML = this.buildComparisonHTML(data);

        this.safeRenderCharts(data.comparison);

        this.renderTableWithPagination("all");
        this.renderTableWithPagination("total");

        setTimeout(() => this.populateSiteSelector(), 0);

        console.log(" 對比模式渲染完成", {
          all: this.pagination.all.filteredResults.length,
          total: this.pagination.total.filteredResults.length,
        });
      } catch (error) {
        console.error(" 渲染失敗:", error);
        this.showError(error.message || "未知錯誤，請重新計算");

        if (window.errorReporter) {
          window.errorReporter.log("ComparisonView.render", error);
        }
      }
    }

    // =============================
    // HTML 建構方法
    // =============================

    buildComparisonHTML(data) {
      const comp = data.comparison;

      return `
        <div class="section-header">
          <div class="section-icon"></div>
          <h2>對比分析：分倉 vs 總倉</h2>
        </div>

        <div class="stats-grid">
          <div class="stat-card">
            <div class="stat-label">分倉總庫存</div>
            <div class="stat-value">${this.formatNumber(comp.total_all_safety_stock)}</div>
            <div class="stat-hint">All Sites</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">總倉庫存</div>
            <div class="stat-value">${this.formatNumber(comp.total_total_safety_stock)}</div>
            <div class="stat-hint">Total Warehouse</div>
          </div>
          <div class="stat-card stat-success">
            <div class="stat-label">節省數量</div>
            <div class="stat-value">${this.formatNumber(comp.inventory_saved)}</div>
            <div class="stat-hint">減少 ${this.formatNumber(comp.savings_percentage, 2)}%</div>
          </div>
          <div class="stat-card stat-info">
            <div class="stat-label">成本節省</div>
            <div class="stat-value">$${this.formatNumber(comp.cost_saved, 0)}</div>
            <div class="stat-hint">Based on Unit Price</div>
          </div>
        </div>

        ${this.buildRecommendation(comp)}

        <div class="comparison-grid">
          <div class="chart-container">
            <div class="card-title"> 安全庫存對比</div>
            <div id="comparisonPlot1" style="width:100%; height:320px;"></div>
            <div id="comparisonChart1Fallback" class="text-muted" style="display:none; padding:8px;"></div>
          </div>
          <div class="chart-container">
            <div class="card-title"> 成本節省</div>
            <div id="comparisonPlot2" style="width:100%; height:320px;"></div>
            <div id="comparisonChart2Fallback" class="text-muted" style="display:none; padding:8px;"></div>
          </div>
        </div>

        ${this.buildExportSection()}

        <div class="comparison-tables">
          ${this.buildDetailTablesPlaceholder()}
        </div>

        ${this.buildDetailModal()}
      `;
    }

    buildExportSection() {
      return `
        <div class="export-section">
          <h3 class="export-title"> 匯出資料</h3>
          <div class="export-controls">
            <div class="export-filter-group">
              <div class="export-filter">
                <label for="exportSiteSelector"><strong>選擇出貨點：</strong></label>
                <select id="exportSiteSelector" class="form-control" aria-label="選擇要匯出的出貨點">
                  <option value="all">全部出貨點</option>
                </select>
              </div>

              <div class="export-filter">
                <label for="sapFormatSelector"><strong>SAP 格式：</strong></label>
                <select id="sapFormatSelector" class="form-control" aria-label="選擇 SAP MM17 匯出格式">
                  <option value="xlsx">XLSX（Excel 格式）</option>
                  <option value="csv">CSV（純文字格式）</option>
                </select>
              </div>

              <div class="export-filter">
                <label for="sapModeSelector"><strong>SAP 模式：</strong></label>
                <select id="sapModeSelector" class="form-control" aria-label="選擇要匯出分倉或總倉數據">
                  <option value="all">分倉數據</option>
                  <option value="total">總倉數據</option>
                </select>
              </div>
            </div>

            <div class="export-buttons">
              <button class="btn btn-primary" id="btnExportExcel" aria-label="匯出為 Excel XLSX 格式">
                 匯出 Excel (.xlsx)
              </button>
              <button class="btn btn-secondary" id="btnExportSAP" aria-label="匯出為 SAP MM17 格式">
                 匯出 SAP MM17
              </button>
            </div>
          </div>

          <div class="export-stats" role="status" aria-live="polite">
            <span id="exportStatsText">準備匯出資料...</span>
          </div>

          <div class="text-muted" style="margin-top:8px; font-size:12px;">
            ※ 匯出功能由後端處理，確保資料安全與格式正確。<br>
            ※ 選擇出貨點後，僅匯出該出貨點的資料；選擇「全部出貨點」則匯出所有資料。
          </div>
        </div>
      `;
    }

    buildDetailTablesPlaceholder() {
      return `
        <div class="comparison-grid">
          <div>
            <div class="card-title"> 分倉計算詳情</div>
            <div class="table-search">
              <label for="searchAll" class="sr-only">搜尋分倉資料</label>
              <input type="text" class="form-control" id="searchAll"
                     placeholder=" 搜尋 SKU、品名、出貨點..."
                     autocomplete="off"
                     aria-label="搜尋分倉資料">
            </div>
            <div class="table-container"><div id="tableAll"></div></div>
            <div class="pagination-container" id="paginationAll" role="navigation" aria-label="分倉資料分頁"></div>
          </div>

          <div>
            <div class="card-title"> 總倉計算詳情</div>
            <div class="table-search">
              <label for="searchTotal" class="sr-only">搜尋總倉資料</label>
              <input type="text" class="form-control" id="searchTotal"
                     placeholder=" 搜尋 SKU、品名..."
                     autocomplete="off"
                     aria-label="搜尋總倉資料">
            </div>
            <div class="table-container"><div id="tableTotal"></div></div>
            <div class="pagination-container" id="paginationTotal" role="navigation" aria-label="總倉資料分頁"></div>
          </div>
        </div>
      `;
    }

    buildDetailModal() {
      return `
        <div id="detailModal" class="detail-modal" style="display: none;"
             role="dialog" aria-modal="true" aria-labelledby="detailModalTitle">
          <div class="detail-modal-content">
            <div class="detail-modal-header">
              <h3 id="detailModalTitle"> SKU 詳細分析</h3>
              <button class="modal-close" id="modalCloseBtn" aria-label="關閉詳情視窗">×</button>
            </div>
            <div class="detail-modal-body" id="detailModalBody"></div>
          </div>
        </div>
      `;
    }

    buildRecommendation(comp) {
      const savingsPercent = parseFloat(comp.savings_percentage) || 0;

      if (!isFinite(savingsPercent) || savingsPercent < 5) {
        return `
          <div class="alert alert-warning" role="alert">
            <strong> 策略建議：</strong>
            分倉與總倉差異不大（節省 < 5%），建議維持現有分倉模式，或考慮採用混合策略。
          </div>
        `;
      }

      return `
        <div class="alert alert-success" role="alert">
          <strong> 策略建議：</strong>
          分倉模式可節省 ${this.formatNumber(savingsPercent, 2)}% 的庫存，
          建議採用分倉配送策略以降低總庫存成本。
        </div>
      `;
    }

    // =============================
    // 表格渲染（保持不變）
    // =============================

    renderTableWithPagination(mode) {
      const tableId = mode === "all" ? "tableAll" : "tableTotal";
      const paginationId = mode === "all" ? "paginationAll" : "paginationTotal";

      const tableContainer = document.getElementById(tableId);
      const paginationContainer = document.getElementById(paginationId);

      if (!tableContainer || !paginationContainer) {
        console.warn(` 找不到表格容器: ${tableId} 或 ${paginationId}`);
        return;
      }

      const filteredResults = this.pagination[mode].filteredResults || [];
      const pageSize = this.pagination[mode].pageSize;

      if (filteredResults.length === 0) {
        const hasSearchTerm = this.searchTerms[mode] && this.searchTerms[mode].length > 0;
        const message = hasSearchTerm
          ? `找不到符合 "${this.escapeHtml(this.searchTerms[mode])}" 的資料`
          : "暫無資料";

        tableContainer.innerHTML = `<p class="text-center text-muted" role="status">${message}</p>`;
        paginationContainer.innerHTML = '<div class="pagination-info">無資料</div>';
        return;
      }

      const totalPages = Math.ceil(filteredResults.length / pageSize);
      let currentPage = this.pagination[mode].currentPage;

      if (currentPage > totalPages) {
        currentPage = totalPages;
        this.pagination[mode].currentPage = currentPage;
      } else if (currentPage < 1) {
        currentPage = 1;
        this.pagination[mode].currentPage = currentPage;
      }

      const startIndex = (currentPage - 1) * pageSize;
      const endIndex = Math.min(startIndex + pageSize, filteredResults.length);
      const pageResults = filteredResults.slice(startIndex, endIndex);

      tableContainer.innerHTML = this.buildTable(pageResults, mode, startIndex);
      paginationContainer.innerHTML = this.buildPagination(
        mode,
        currentPage,
        totalPages,
        filteredResults.length
      );
    }

    buildTable(results, mode, startIndex = 0) {
      if (!results || results.length === 0) {
        const hasSearchTerm = this.searchTerms[mode] && this.searchTerms[mode].length > 0;
        const message = hasSearchTerm
          ? `找不到符合 "${this.escapeHtml(this.searchTerms[mode])}" 的資料`
          : "暫無資料";
        return `<p class="text-center text-muted" role="status">${message}</p>`;
      }

      const headers = this.buildTableHeaders(mode);

      const rows = results
        .map((row, indexInPage) => {
          const filteredIndex = startIndex + indexInPage;
          return `
            <tr data-row-id="${mode}-${filteredIndex}" role="row">
              ${mode === "all" ? `<td role="cell">${this.escapeHtml(row.site || "-")}</td>` : ""}
              <td role="cell">${this.escapeHtml(row.sku || "-")}</td>
              <td role="cell">${this.escapeHtml(row.name || "-")}</td>
              <td role="cell"><span class="abc-badge ${row.abc_grade || ''}">${this.escapeHtml(row.abc_grade || row.abc_class || "-")}</span></td>
              <td class="text-right" role="cell">${this.formatNumber(row.avg_monthly_demand || row.mean_demand, 2)}</td>
              <td class="text-right" role="cell">${this.formatNumber(row.std_dev, 2)}</td>
              <td class="text-right" role="cell">${this.formatNumber(row.cv, 2)}</td>
              <td class="text-right" role="cell"><strong>${this.formatNumber(row.safety_stock, 0)}</strong></td>
              <td class="text-right" role="cell">${this.formatNumber(row.reorder_point, 0)}</td>
              <td class="text-right" role="cell">${this.formatNumber(row.max_inventory, 0)}</td>
              <td class="text-right" role="cell">${row.total_months || '-'}</td>
              <td role="cell">
                <button class="btn btn-sm btn-detail"
                        data-mode="${mode}"
                        data-row-index="${filteredIndex}"
                        aria-label="查看 ${this.escapeHtml(row.sku)} 詳細資料">
                   詳情
                </button>
              </td>
            </tr>
          `;
        })
        .join("");

      return `
        <table class="comparison-table" role="grid" aria-label="${mode === "all" ? "分倉" : "總倉"}計算詳情">
          <thead>
            <tr data-table-mode="${mode}" role="row">${headers}</tr>
          </thead>
          <tbody role="rowgroup">${rows}</tbody>
        </table>
      `;
    }

    buildTableHeaders(mode) {
      const sorting = this.sorting[mode];

      const getSortIcon = (column) => {
        if (sorting.column === column) {
          return sorting.direction === "asc" ? " ▲" : " ▼";
        }
        return "";
      };

      const commonHeaders = [
        { key: "sku", label: "料號" },
        { key: "name", label: "品名" },
        { key: "abc_grade", label: "ABC" },
        { key: "avg_monthly_demand", label: "月均需求" },
        { key: "std_dev", label: "標準差" },
        { key: "cv", label: "CV" },
        { key: "safety_stock", label: "安全庫存" },
        { key: "reorder_point", label: "再訂購點" },
        { key: "max_inventory", label: "最大庫存" },
        { key: "total_months", label: "月數" },
      ];

      const siteHeader = { key: "site", label: "出貨點" };

      const headers = mode === "all" ? [siteHeader, ...commonHeaders] : commonHeaders;

      const headerHtml = headers
        .map((h) => {
          const sortLabel =
            sorting.column === h.key
              ? `，目前${sorting.direction === "asc" ? "升冪" : "降冪"}排序`
              : "";
          return `<th data-sort="${h.key}" role="columnheader"
                      aria-sort="${
                        sorting.column === h.key
                          ? sorting.direction === "asc"
                            ? "ascending"
                            : "descending"
                          : "none"
                      }"
                      aria-label="${h.label}${sortLabel}，點擊排序"
                      style="cursor: pointer;">
                    ${h.label}${getSortIcon(h.key)}
                  </th>`;
        })
        .join("");

      return headerHtml + '<th role="columnheader">操作</th>';
    }

    buildPagination(mode, currentPage, totalPages, totalResults) {
      if (totalPages <= 1) {
        return `<div class="pagination-info" role="status">共 ${totalResults} 筆資料</div>`;
      }

      const pageSize = this.pagination[mode].pageSize;
      const startRecord = (currentPage - 1) * pageSize + 1;
      const endRecord = Math.min(currentPage * pageSize, totalResults);

      let html = '<div class="pagination-controls">';

      html += `
        <button class="btn btn-sm btn-pagination ${currentPage === 1 ? "disabled" : ""}"
                data-mode="${mode}"
                data-action="prev"
                ${currentPage === 1 ? "disabled" : ""}
                aria-label="上一頁">
          ◀ 上一頁
        </button>
      `;

      html += '<div class="pagination-pages">';

      let startPage = Math.max(1, currentPage - 2);
      let endPage = Math.min(totalPages, currentPage + 2);

      if (startPage > 1) {
        html += `<button class="btn btn-sm btn-pagination"
                         data-mode="${mode}"
                         data-action="goto"
                         data-page="1"
                         aria-label="前往第 1 頁">1</button>`;
        if (startPage > 2) {
          html += '<span class="pagination-ellipsis" aria-hidden="true">...</span>';
        }
      }

      for (let i = startPage; i <= endPage; i++) {
        html += `
          <button class="btn btn-sm btn-pagination ${i === currentPage ? "active" : ""}"
                  data-mode="${mode}"
                  data-action="goto"
                  data-page="${i}"
                  aria-label="前往第 ${i} 頁"
                  ${i === currentPage ? 'aria-current="page"' : ""}>${i}</button>
        `;
      }

      if (endPage < totalPages) {
        if (endPage < totalPages - 1) {
          html += '<span class="pagination-ellipsis" aria-hidden="true">...</span>';
        }
        html += `<button class="btn btn-sm btn-pagination"
                         data-mode="${mode}"
                         data-action="goto"
                         data-page="${totalPages}"
                         aria-label="前往第 ${totalPages} 頁">${totalPages}</button>`;
      }

      html += "</div>";

      html += `
        <button class="btn btn-sm btn-pagination ${currentPage === totalPages ? "disabled" : ""}"
                data-mode="${mode}"
                data-action="next"
                ${currentPage === totalPages ? "disabled" : ""}
                aria-label="下一頁">
          下一頁 ▶
        </button>
      `;

      html += `</div>
        <div class="pagination-info" role="status">
          顯示 ${startRecord}-${endRecord} / 共 ${totalResults} 筆
        </div>
      `;

      return html;
    }

    handlePagination(mode, action, page = null) {
      const pagination = this.pagination[mode];
      const totalPages = Math.ceil((pagination.filteredResults || []).length / pagination.pageSize);

      switch (action) {
        case "prev":
          if (pagination.currentPage > 1) pagination.currentPage--;
          break;
        case "next":
          if (pagination.currentPage < totalPages) pagination.currentPage++;
          break;
        case "goto":
          if (page && page >= 1 && page <= totalPages) pagination.currentPage = page;
          break;
      }

      this.renderTableWithPagination(mode);
    }

    // =============================
    // 搜尋功能（保持不變）
    // =============================

    handleSearch(mode, searchTerm) {
      if (this.searchDebounceTimers[mode]) {
        clearTimeout(this.searchDebounceTimers[mode]);
      }

      this.searchDebounceTimers[mode] = setTimeout(() => {
        this.executeSearch(mode, searchTerm);
      }, 300);
    }

    executeSearch(mode, searchTerm) {
      searchTerm = String(searchTerm || "")
        .toLowerCase()
        .trim();
      this.searchTerms[mode] = searchTerm;

      const bucket =
        mode === "all" ? this.currentData?.all_summary : this.currentData?.total_summary;
      const allResults = bucket?.results || [];

      if (allResults.length > this.LARGE_DATASET_THRESHOLD) {
        const tableContainer = document.getElementById(mode === "all" ? "tableAll" : "tableTotal");
        if (tableContainer) {
          tableContainer.innerHTML = '<p class="text-center" role="status"> 搜尋中...</p>';
        }
      }

      const performSearch = () => {
        if (!searchTerm) {
          this.pagination[mode].filteredResults = allResults;
        } else {
          this.pagination[mode].filteredResults = allResults.filter((item) => {
            const sku = String(item.sku || "").toLowerCase();
            const name = String(item.name || "").toLowerCase();
            const site = String(item.site || "").toLowerCase();
            return (
              sku.includes(searchTerm) ||
              name.includes(searchTerm) ||
              (mode === "all" && site.includes(searchTerm))
            );
          });
        }

        this.pagination[mode].currentPage = 1;
        this.renderTableWithPagination(mode);
      };

      if (window.requestIdleCallback) {
        window.requestIdleCallback(performSearch);
      } else {
        setTimeout(performSearch, 0);
      }
    }

    // =============================
    // 排序功能（保持不變）
    // =============================

    handleSort(mode, column) {
      const sorting = this.sorting[mode];

      if (sorting.column === column) {
        sorting.direction = sorting.direction === "asc" ? "desc" : "asc";
      } else {
        sorting.column = column;
        sorting.direction = "asc";
      }

      const numericColumns = [
        "avg_monthly_demand",
        "std_dev",
        "cv",
        "safety_stock",
        "reorder_point",
        "max_inventory",
        "lead_time_days",
        "total_months",
        "months_count",
      ];

      this.pagination[mode].filteredResults.sort((a, b) => {
        let aVal = a[column];
        let bVal = b[column];

        if (numericColumns.includes(column)) {
          aVal = this.parseNumber(aVal);
          bVal = this.parseNumber(bVal);

          if (aVal !== bVal) {
            return sorting.direction === "asc" ? aVal - bVal : bVal - aVal;
          }

          const aSku = String(a.sku || "").toLowerCase();
          const bSku = String(b.sku || "").toLowerCase();
          return aSku.localeCompare(bSku);
        }

        aVal = String(aVal || "").toLowerCase();
        bVal = String(bVal || "").toLowerCase();

        if (aVal !== bVal) {
          if (aVal < bVal) return sorting.direction === "asc" ? -1 : 1;
          if (aVal > bVal) return sorting.direction === "asc" ? 1 : -1;
        }

        const aSku = String(a.sku || "").toLowerCase();
        const bSku = String(b.sku || "").toLowerCase();
        return aSku.localeCompare(bSku);
      });

      this.renderTableWithPagination(mode);
    }

    // =============================
    // 匯出功能（v4.5.1 - 修復出貨點篩選）
    // =============================

    updateExportStats() {
      const selector = document.getElementById("exportSiteSelector");
      const statsText = document.getElementById("exportStatsText");

      if (!selector || !statsText || !this.currentData) return;

      const selectedSite = selector.value;
      const allResults = this.currentData.all_summary?.results || [];

      if (selectedSite === "all") {
        statsText.textContent = `準備匯出全部 ${allResults.length} 筆資料`;
      } else {
        const filteredCount = allResults.filter((item) => item.site === selectedSite).length;
        statsText.textContent = `準備匯出出貨點 ${selectedSite} 的 ${filteredCount} 筆資料`;
      }
    }

    populateSiteSelector() {
      const selector = document.getElementById("exportSiteSelector");
      if (!selector || !this.currentData) return;

      const results = this.currentData.all_summary?.results || [];
      const sites = [...new Set(results.map((item) => item.site).filter(Boolean))].sort();

      selector.innerHTML = '<option value="all">全部出貨點</option>';
      sites.forEach((site) => {
        const option = document.createElement("option");
        option.value = site;
        option.textContent = site;
        selector.appendChild(option);
      });

      this.updateExportStats();
    }

    /**
     * 處理匯出（v4.5.1 - 修復出貨點篩選）
     * @param {string} type - "excel" 或 "sap"
     */
    async handleExport(type) {
      const statsText = document.getElementById("exportStatsText");

      try {
        // 取得出貨點選擇器
        const siteSelector = document.getElementById("exportSiteSelector");
        const selectedSite = siteSelector ? siteSelector.value : "all";

        // 驗證是否有資料
        if (!this.currentData) {
          throw new Error("請先執行計算");
        }

        // 顯示載入提示
        if (statsText) {
          const siteText = selectedSite === "all" ? "全部資料" : `出貨點 ${selectedSite}`;
          statsText.textContent = ` 正在匯出 ${siteText}，請稍候...`;
        }

        if (type === "excel") {
          // ===== Excel 匯出 =====
          console.log(" 呼叫後端 Excel API");
          console.log(`   出貨點: ${selectedSite}`);

          // 傳遞 site_filter 參數
          await this.exportViaBackend("/api/export/excel", "POST", {
            site_filter: selectedSite !== "all" ? selectedSite : null,
          });
        } else if (type === "sap") {
          // ===== SAP MM17 匯出 =====
          console.log(" 呼叫後端 SAP MM17 API");

          // 取得使用者選擇
          const formatSelector = document.getElementById("sapFormatSelector");
          const modeSelector = document.getElementById("sapModeSelector");

          const format = formatSelector ? formatSelector.value : "xlsx";
          const mode = modeSelector ? modeSelector.value : "all";

          console.log(`   格式: ${format}`);
          console.log(`   模式: ${mode}`);
          console.log(`   出貨點: ${selectedSite}`);

          // 傳遞 site_filter 參數
          await this.exportViaBackend("/api/export/sap", "POST", {
            format: format,
            mode: mode,
            site_filter: selectedSite !== "all" ? selectedSite : null,
            include_header: true,
          });
        }

        // 恢復統計文字
        if (statsText) {
          this.updateExportStats();
        }
      } catch (error) {
        console.error(" 匯出失敗:", error);

        // 更友善的錯誤訊息
        let errorMsg = error.message || "未知錯誤";
        if (errorMsg.includes("沒有資料")) {
          errorMsg = `選擇的出貨點沒有資料，請確認篩選條件`;
        }

        alert(`匯出失敗：${errorMsg}`);

        // 恢復統計文字
        if (statsText) {
          this.updateExportStats();
        }
      }
    }

    /**
     * 透過後端 API 匯出檔案
     * @param {string} url - API 路徑
     * @param {string} method - HTTP 方法
     * @param {Object|null} body - 請求 body
     */
    async exportViaBackend(url, method = "POST", body = null) {
      console.log(` 呼叫後端 API: ${url}`);

      // 記錄傳遞的參數
      if (body) {
        console.log(`   參數:`, body);
      }

      const fullUrl = this.API_BASE + url;

      const options = {
        method: method,
        headers: {},
        credentials: "same-origin",
      };

      if (body) {
        options.headers["Content-Type"] = "application/json";
        options.body = JSON.stringify(body);
      }

      const response = await fetch(fullUrl, options);

      if (!response.ok) {
        let errorMsg = `HTTP ${response.status}`;
        try {
          const errorData = await response.json();
          errorMsg = errorData.error || errorData.detail || errorMsg;
        } catch (e) {
          // JSON 解析失敗，使用狀態碼
        }
        throw new Error(errorMsg);
      }

      // 取得檔案 blob
      const blob = await response.blob();

      // 取得檔名
      const contentDisposition = response.headers.get("Content-Disposition");
      let filename = "download.xlsx";

      if (contentDisposition) {
        const matches = contentDisposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
        if (matches && matches[1]) {
          filename = matches[1].replace(/['"]/g, "").trim();
        }
      }

      // 下載檔案
      const downloadUrl = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = downloadUrl;
      link.download = filename;
      link.style.display = "none";
      document.body.appendChild(link);
      link.click();

      setTimeout(() => {
        document.body.removeChild(link);
        window.URL.revokeObjectURL(downloadUrl);
      }, 100);

      console.log(` 檔案下載成功: ${filename}`);
    }

    // =============================
    // 詳情模態框（保持不變）
    // =============================

    handleDetailButtonClick(detailBtn) {
      const mode = detailBtn.dataset.mode;
      const rowIndex = parseInt(detailBtn.dataset.rowIndex, 10);

      if (!mode || !Number.isFinite(rowIndex)) {
        console.warn(" detail btn missing dataset", { mode, rowIndex });
        return;
      }

      const list = this.pagination?.[mode]?.filteredResults || [];
      const row = list[rowIndex];

      if (!row) {
        alert("找不到該筆資料（可能搜尋/排序/分頁後資料變動）");
        return;
      }

      const body = document.getElementById("detailModalBody");
      const modal = document.getElementById("detailModal");

      if (!body || !modal) {
        alert("找不到詳情視窗元素");
        return;
      }

      const monthlyValues = row.monthly_values || [];
      const monthlyHtml = monthlyValues.length > 0
        ? `<tr><td style="color:#666;">月度出貨明細</td><td>${monthlyValues.map((v, i) => `<span style="display:inline-block;margin:2px 6px 2px 0;padding:2px 8px;background:${v > 0 ? '#e8f5e9' : '#ffebee'};border-radius:4px;font-size:13px;">第${i+1}月: ${this.formatNumber(v, 0)}</span>`).join('')}</td></tr>`
        : '';

      body.innerHTML = `
        <table style="width:100%;border-collapse:collapse;font-size:14px;">
          <tbody>
            <tr style="background:#f0f4ff;">
              <td style="padding:10px;font-weight:600;width:120px;border-bottom:1px solid #e0e0e0;">出貨點</td>
              <td style="padding:10px;border-bottom:1px solid #e0e0e0;">${this.escapeHtml(row.site || "-")}</td>
            </tr>
            <tr>
              <td style="padding:10px;font-weight:600;border-bottom:1px solid #e0e0e0;">料號</td>
              <td style="padding:10px;border-bottom:1px solid #e0e0e0;">${this.escapeHtml(row.sku || "-")}</td>
            </tr>
            <tr style="background:#f0f4ff;">
              <td style="padding:10px;font-weight:600;border-bottom:1px solid #e0e0e0;">品名</td>
              <td style="padding:10px;border-bottom:1px solid #e0e0e0;">${this.escapeHtml(row.name || "-")}</td>
            </tr>
            <tr>
              <td style="padding:10px;font-weight:600;border-bottom:1px solid #e0e0e0;">ABC 等級</td>
              <td style="padding:10px;border-bottom:1px solid #e0e0e0;"><span class="abc-badge ${row.abc_grade || row.abc_class || ''}">${this.escapeHtml(row.abc_grade || row.abc_class || "-")}</span></td>
            </tr>
            <tr style="background:#fff8e1;">
              <td colspan="2" style="padding:8px 10px;font-weight:600;color:#e65100;border-bottom:1px solid #e0e0e0;">需求統計</td>
            </tr>
            <tr>
              <td style="padding:10px;font-weight:600;border-bottom:1px solid #e0e0e0;">月均需求</td>
              <td style="padding:10px;border-bottom:1px solid #e0e0e0;">${this.formatNumber(row.avg_monthly_demand || row.mean_demand, 2)}</td>
            </tr>
            <tr style="background:#f0f4ff;">
              <td style="padding:10px;font-weight:600;border-bottom:1px solid #e0e0e0;">標準差</td>
              <td style="padding:10px;border-bottom:1px solid #e0e0e0;">${this.formatNumber(row.std_dev, 2)}</td>
            </tr>
            <tr>
              <td style="padding:10px;font-weight:600;border-bottom:1px solid #e0e0e0;">變異係數 (CV)</td>
              <td style="padding:10px;border-bottom:1px solid #e0e0e0;">${this.formatNumber(row.cv, 4)}</td>
            </tr>
            <tr style="background:#f0f4ff;">
              <td style="padding:10px;font-weight:600;border-bottom:1px solid #e0e0e0;">資料月數</td>
              <td style="padding:10px;border-bottom:1px solid #e0e0e0;">${row.total_months || row.months_count || '-'} 個月（有效出貨: ${row.active_months || row.months_count || '-'} 個月）</td>
            </tr>
            ${monthlyHtml}
            <tr style="background:#e8f5e9;">
              <td colspan="2" style="padding:8px 10px;font-weight:600;color:#2e7d32;border-bottom:1px solid #e0e0e0;">庫存建議</td>
            </tr>
            <tr>
              <td style="padding:10px;font-weight:600;border-bottom:1px solid #e0e0e0;">安全庫存</td>
              <td style="padding:10px;border-bottom:1px solid #e0e0e0;font-weight:700;color:#1565c0;">${this.formatNumber(row.safety_stock, 0)}</td>
            </tr>
            <tr style="background:#f0f4ff;">
              <td style="padding:10px;font-weight:600;border-bottom:1px solid #e0e0e0;">再訂購點</td>
              <td style="padding:10px;border-bottom:1px solid #e0e0e0;">${this.formatNumber(row.reorder_point, 0)}</td>
            </tr>
            <tr>
              <td style="padding:10px;font-weight:600;border-bottom:1px solid #e0e0e0;">最大庫存</td>
              <td style="padding:10px;border-bottom:1px solid #e0e0e0;">${this.formatNumber(row.max_inventory, 0)}</td>
            </tr>
            <tr style="background:#f0f4ff;">
              <td style="padding:10px;font-weight:600;">前置天數</td>
              <td style="padding:10px;">${row.lead_time_days || 30} 天</td>
            </tr>
          </tbody>
        </table>
      `;

      modal.style.display = "block";

      const closeBtn = document.getElementById("modalCloseBtn");
      if (closeBtn) closeBtn.focus();
    }

    closeDetailModal() {
      const modal = document.getElementById("detailModal");
      if (modal) {
        modal.style.display = "none";
      }
    }

    // =============================
    // 圖表渲染（保持不變）
    // =============================

    safeRenderCharts(comp) {
      try {
        if (window.Plotly) {
          this.renderChartsPlotly(comp);
        } else {
          this.renderChartsTextFallback(comp);
        }
      } catch (error) {
        console.error(" 圖表渲染失敗，降級到文字顯示:", error);
        this.renderChartsTextFallback(comp);
      }
    }

    renderChartsPlotly(comp) {
      const allSS = this.parseNumber(comp?.total_all_safety_stock);
      const totalSS = this.parseNumber(comp?.total_total_safety_stock);
      const costSaved = this.parseNumber(comp?.cost_saved);

      try {
        const div1 = document.getElementById("comparisonPlot1");
        if (div1) {
          window.Plotly.purge(div1);
          window.Plotly.newPlot(
            div1,
            [
              {
                x: ["分倉", "總倉"],
                y: [allSS, totalSS],
                type: "bar",
                name: "安全庫存",
                marker: { color: ["#4CAF50", "#2196F3"] },
              },
            ],
            {
              title: "安全庫存對比",
              margin: { t: 40, r: 20, b: 40, l: 60 },
              yaxis: { title: "數量" },
            },
            { responsive: true, displayModeBar: false }
          );

          const fallback1 = document.getElementById("comparisonChart1Fallback");
          if (fallback1) fallback1.style.display = "none";
        }

        const div2 = document.getElementById("comparisonPlot2");
        if (div2) {
          window.Plotly.purge(div2);
          window.Plotly.newPlot(
            div2,
            [
              {
                x: ["成本節省"],
                y: [costSaved],
                type: "bar",
                name: "節省價值",
                marker: { color: "#FF9800" },
              },
            ],
            {
              title: "成本節省",
              margin: { t: 40, r: 20, b: 40, l: 60 },
              yaxis: { title: "金額 ($)" },
            },
            { responsive: true, displayModeBar: false }
          );

          const fallback2 = document.getElementById("comparisonChart2Fallback");
          if (fallback2) fallback2.style.display = "none";
        }
      } catch (error) {
        console.error(" Plotly 渲染失敗:", error);
        throw error;
      }
    }

    renderChartsTextFallback(comp) {
      const allSS = this.parseNumber(comp?.total_all_safety_stock);
      const totalSS = this.parseNumber(comp?.total_total_safety_stock);
      const savedQty = this.parseNumber(comp?.inventory_saved);
      const savedPct = this.parseNumber(comp?.savings_percentage);
      const costSaved = this.parseNumber(comp?.cost_saved);

      const div1 = document.getElementById("comparisonPlot1");
      const fallback1 = document.getElementById("comparisonChart1Fallback");

      if (div1 && fallback1) {
        div1.style.display = "none";
        fallback1.style.display = "block";
        fallback1.innerHTML = `
          <div style="padding:12px; line-height:1.8;">
            <div style="font-weight:600; margin-bottom:8px;">（圖表庫未載入）文字顯示</div>
            <div>分倉總庫存：<b>${this.formatNumber(allSS, 0)}</b></div>
            <div>總倉庫存：<b>${this.formatNumber(totalSS, 0)}</b></div>
            <div>節省數量：<b>${this.formatNumber(savedQty, 0)}</b></div>
            <div>節省比例：<b>${this.formatNumber(savedPct, 2)}%</b></div>
          </div>
        `;
      }

      const div2 = document.getElementById("comparisonPlot2");
      const fallback2 = document.getElementById("comparisonChart2Fallback");

      if (div2 && fallback2) {
        div2.style.display = "none";
        fallback2.style.display = "block";
        fallback2.innerHTML = `
          <div style="padding:12px; line-height:1.8;">
            <div style="font-weight:600; margin-bottom:8px;">（圖表庫未載入）文字顯示</div>
            <div>成本節省：<b>$${this.formatNumber(costSaved, 0)}</b></div>
          </div>
        `;
      }
    }

    // =============================
    // 事件處理（保持不變）
    // =============================

    bindGlobalEvents() {
      if (this.eventsBound) {
        console.warn(" 事件已綁定，跳過重複綁定");
        return;
      }

      this.boundHandlers.click = (e) => {
        const detailBtn = e.target.closest(".btn-detail");
        if (detailBtn) {
          e.preventDefault();
          return void this.handleDetailButtonClick(detailBtn);
        }

        const closeBtn = e.target.closest("#modalCloseBtn, .modal-close");
        if (closeBtn) {
          e.preventDefault();
          return void this.closeDetailModal();
        }

        if (e.target.id === "detailModal") {
          return void this.closeDetailModal();
        }

        const pageBtn = e.target.closest(".btn-pagination");
        if (pageBtn && !pageBtn.disabled) {
          e.preventDefault();
          const mode = pageBtn.dataset.mode;
          const action = pageBtn.dataset.action;
          const page = parseInt(pageBtn.dataset.page, 10);
          return void this.handlePagination(mode, action, page);
        }

        const sortTh = e.target.closest("th[data-sort]");
        if (sortTh) {
          const column = sortTh.dataset.sort;
          const mode = sortTh.closest("tr")?.dataset.tableMode;
          if (mode && column) return void this.handleSort(mode, column);
        }

        const exportExcelBtn = e.target.closest("#btnExportExcel");
        if (exportExcelBtn) {
          e.preventDefault();
          return void this.handleExport("excel");
        }

        const exportSapBtn = e.target.closest("#btnExportSAP");
        if (exportSapBtn) {
          e.preventDefault();
          return void this.handleExport("sap");
        }
      };

      this.boundHandlers.input = (e) => {
        if (e.target.id === "searchAll") {
          this.handleSearch("all", e.target.value);
        }
        if (e.target.id === "searchTotal") {
          this.handleSearch("total", e.target.value);
        }
      };

      this.boundHandlers.change = (e) => {
        if (e.target.id === "exportSiteSelector") {
          this.updateExportStats();
        }
      };

      this.boundHandlers.keydown = (e) => {
        if (e.key === "Escape") {
          const modal = document.getElementById("detailModal");
          if (modal && modal.style.display !== "none") {
            this.closeDetailModal();
          }
        }
      };

      document.addEventListener("click", this.boundHandlers.click);
      document.addEventListener("input", this.boundHandlers.input);
      document.addEventListener("change", this.boundHandlers.change);
      document.addEventListener("keydown", this.boundHandlers.keydown);

      this.eventsBound = true;
      console.log(" ComparisonView 全域事件已綁定");
    }

    unbindGlobalEvents() {
      if (!this.eventsBound) return;

      document.removeEventListener("click", this.boundHandlers.click);
      document.removeEventListener("input", this.boundHandlers.input);
      document.removeEventListener("change", this.boundHandlers.change);
      document.removeEventListener("keydown", this.boundHandlers.keydown);

      this.boundHandlers = {
        click: null,
        input: null,
        change: null,
        keydown: null,
      };

      this.eventsBound = false;
      console.log(" ComparisonView 事件已解除綁定");
    }

    // =============================
    // 工具函數
    // =============================

    escapeHtml(text) {
      if (text === null || text === undefined) return "-";
      const div = document.createElement("div");
      div.textContent = String(text);
      return div.innerHTML;
    }

    getTimestamp() {
      const now = new Date();
      const year = now.getFullYear();
      const month = String(now.getMonth() + 1).padStart(2, "0");
      const day = String(now.getDate()).padStart(2, "0");
      const hours = String(now.getHours()).padStart(2, "0");
      const minutes = String(now.getMinutes()).padStart(2, "0");
      const seconds = String(now.getSeconds()).padStart(2, "0");
      return `${year}${month}${day}_${hours}${minutes}${seconds}`;
    }

    showError(message) {
      alert(" " + message);
    }

    formatNumber(value, decimals = 0) {
      if (value === null || value === undefined || value === "") return "-";

      const num = this.parseNumber(value);
      if (!isFinite(num)) return "-";

      return num.toLocaleString("zh-TW", {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      });
    }

    parseNumber(value) {
      if (value === null || value === undefined || value === "") return 0;

      const cleaned = String(value).replace(/,/g, "").trim();
      const num = parseFloat(cleaned);

      return isNaN(num) ? 0 : num;
    }
  }

  // =============================
  // 模組輸出（單例）
  // =============================
  window.ComparisonView = new ComparisonView();
  console.log(" Comparison View Module 已載入 (v4.5.1 - Site Filter Fix)");
})();s