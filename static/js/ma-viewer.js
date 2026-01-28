/**
 * 安全庫存自動化系統 - MA 分析查看器
 * Safety Stock Automation System - MA Viewer
 *
 * Version: 4.2.2 (Hotfix+)
 * Author: 松鼠
 * Last Updated: 2026-01-26
 *
 * Fix/Improve:
 * - ✅ 防止重複插入 modal/style（腳本重載不會爆）
 * - ✅ show/hide 都 purge Plotly，避免越開越卡
 * - ✅ 取消 inline onclick，改事件綁定
 * - ✅ 支援 ESC 關閉 / 點背景關閉
 * - ✅ escapeHtml 防 XSS
 * - ✅ renderChart 防呆，不因資料缺失炸掉
 */

(function () {
  "use strict";

  class MAViewer {
    constructor() {
      this.modal = null;
      this._eventsBound = false;

      this.init();
    }

    init() {
      this.createModal();
      this.addModalStyles();
      this.bindEvents();
      console.log("✅ MA Viewer 已載入 (v4.2.2 - Hotfix+)");
    }

    // -----------------------------
    // Modal creation (idempotent)
    // -----------------------------
    createModal() {
      // 如果已存在（例如熱更新 / 重複載入腳本），直接抓現成的
      const existing = document.getElementById("maModal");
      if (existing) {
        this.modal = existing;
        return;
      }

      const modalHTML = `
        <div id="maModal" class="ma-modal" style="display:none;">
          <div class="ma-modal-dialog" role="dialog" aria-modal="true" aria-labelledby="maModalTitle">
            <div class="ma-modal-content">
              <div class="ma-modal-header">
                <h5 class="ma-modal-title" id="maModalTitle">移動平均分析</h5>
                <button type="button" class="ma-btn-close" id="maModalCloseBtn" aria-label="Close">×</button>
              </div>
              <div class="ma-modal-body">
                <div id="maDetailContent"></div>
              </div>
            </div>
          </div>
        </div>
      `;

      const wrapper = document.createElement("div");
      wrapper.innerHTML = modalHTML;
      document.body.appendChild(wrapper);

      this.modal = document.getElementById("maModal");
    }

    addModalStyles() {
      // 避免重複插入 style
      const styleId = "maViewerStyles";
      if (document.getElementById(styleId)) return;

      const style = document.createElement("style");
      style.id = styleId;
      style.textContent = `
        .ma-modal{
          position:fixed; inset:0;
          width:100%; height:100%;
          background:rgba(0,0,0,.5);
          z-index:10000;
          display:flex;
          align-items:center;
          justify-content:center;
          padding:1rem;
        }
        .ma-modal-dialog{
          max-width:1200px;
          width:100%;
          max-height:90vh;
          overflow:auto;
        }
        .ma-modal-content{
          background:#fff;
          border-radius:.75rem;
          box-shadow:0 20px 25px -5px rgba(0,0,0,.1);
        }
        .ma-modal-header{
          display:flex;
          justify-content:space-between;
          align-items:center;
          padding:1.5rem;
          border-bottom:1px solid #e5e7eb;
        }
        .ma-modal-title{
          font-size:1.25rem;
          font-weight:600;
          margin:0;
        }
        .ma-btn-close{
          background:none;
          border:none;
          font-size:1.5rem;
          cursor:pointer;
          color:#6b7280;
          padding:0;
          width:2rem;
          height:2rem;
          display:flex;
          align-items:center;
          justify-content:center;
          border-radius:.375rem;
        }
        .ma-btn-close:hover{
          background:#f3f4f6;
          color:#111827;
        }
        .ma-modal-body{
          padding:1.5rem;
        }

        .ma-info-grid{
          display:grid;
          grid-template-columns:repeat(auto-fit, minmax(150px, 1fr));
          gap:1rem;
          margin-bottom:1.5rem;
        }
        .ma-info-item{
          background:#f9fafb;
          padding:1rem;
          border-radius:.5rem;
          border:1px solid #e5e7eb;
        }
        .ma-info-label{
          font-size:.75rem;
          color:#6b7280;
          margin-bottom:.25rem;
        }
        .ma-info-value{
          font-size:1.125rem;
          font-weight:600;
          color:#111827;
          word-break:break-all;
        }

        .ma-chart-container{
          margin:1.5rem 0;
          height:400px;
          border:1px solid #e5e7eb;
          border-radius:.5rem;
          padding:1rem;
          background:#fff;
        }

        .ma-quarterly-table{
          margin-top:1.5rem;
        }

        .ma-recommendation{
          padding:1rem;
          border-radius:.5rem;
          margin-top:1.5rem;
          display:flex;
          gap:1rem;
          align-items:flex-start;
        }
        .ma-recommendation.success{ background:#d1fae5; border:1px solid #6ee7b7; color:#065f46; }
        .ma-recommendation.warning{ background:#fef3c7; border:1px solid #fcd34d; color:#92400e; }
        .ma-recommendation.info{ background:#dbeafe; border:1px solid #93c5fd; color:#1e40af; }
        .ma-recommendation-icon{ font-size:1.5rem; }
        .ma-recommendation-text{ flex:1; }
      `;
      document.head.appendChild(style);
    }

    bindEvents() {
      if (this._eventsBound) return;
      this._eventsBound = true;

      // 點 X 關閉
      document.addEventListener("click", (e) => {
        const closeBtn = e.target.closest("#maModalCloseBtn");
        if (closeBtn) {
          this.hide();
          return;
        }

        // 點背景關閉（點到 modal 背景，而不是 dialog 內容）
        if (e.target && e.target.id === "maModal") {
          this.hide();
        }
      });

      // ESC 關閉
      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
          const isOpen = this.modal && this.modal.style.display !== "none";
          if (isOpen) this.hide();
        }
      });
    }

    // -----------------------------
    // Public API
    // -----------------------------
    show(data) {
      if (!this.modal) this.createModal();

      const content = document.getElementById("maDetailContent");
      if (!content) {
        console.error("❌ MAViewer: missing #maDetailContent");
        return;
      }

      // 渲染內容
      try {
        content.innerHTML = this.renderContent(data || {});
      } catch (e) {
        console.error("❌ MAViewer.renderContent failed:", e);
        content.innerHTML = `<div class="alert alert-danger">內容渲染失敗，請檢查資料格式</div>`;
      }

      // 顯示 modal
      this.modal.style.display = "flex";

      // ✅ 先清掉舊圖（避免重開疊圖/越來越卡）
      this.purgePlotly();

      // 延遲渲染圖表（確保 DOM 已插入）
      setTimeout(() => {
        try {
          this.renderChart(data || {});
        } catch (e) {
          console.error("❌ MAViewer.renderChart failed:", e);
          const container = document.getElementById("maChartContainer");
          if (container) {
            container.innerHTML = `<div class="alert alert-warning">圖表渲染失敗（已忽略），請檢查資料格式或圖表庫載入狀態。</div>`;
          }
        }
      }, 50);
    }

    hide() {
      if (!this.modal) return;
      this.modal.style.display = "none";
      this.purgePlotly();
    }

    purgePlotly() {
      const container = document.getElementById("maChartContainer");
      if (container && typeof Plotly !== "undefined") {
        try {
          Plotly.purge(container);
        } catch (e) {
          // ignore
        }
      }
    }

    // -----------------------------
    // Rendering
    // -----------------------------
    renderContent(data) {
      const safeSite = this.escapeHtml(data?.site ?? "-");
      const safeSku = this.escapeHtml(data?.sku ?? "-");
      const safeName = this.escapeHtml(data?.name ?? "-");
      const maWindow = Number.isFinite(Number(data?.ma_window)) ? Number(data.ma_window) : 3;

      return `
        <!-- 基本資訊 -->
        <div class="ma-info-grid">
          <div class="ma-info-item">
            <div class="ma-info-label">出貨點</div>
            <div class="ma-info-value">${safeSite}</div>
          </div>
          <div class="ma-info-item">
            <div class="ma-info-label">料號</div>
            <div class="ma-info-value">${safeSku}</div>
          </div>
          <div class="ma-info-item">
            <div class="ma-info-label">品名</div>
            <div class="ma-info-value">${safeName}</div>
          </div>
          <div class="ma-info-item">
            <div class="ma-info-label">MA 窗口</div>
            <div class="ma-info-value">${this.escapeHtml(maWindow)} 個月</div>
          </div>
        </div>

        <!-- 統計資訊 -->
        ${data?.statistics ? this.renderStatistics(data.statistics) : ""}

        <!-- 圖表 -->
        <div class="ma-chart-container" id="maChartContainer"></div>

        <!-- 季度摘要 -->
        ${data?.quarterly_summary ? this.renderQuarterlySummary(data.quarterly_summary) : ""}

        <!-- 建議 -->
        ${data?.recommendation ? this.renderRecommendation(data.recommendation) : ""}

        <!-- 填補月份 -->
        ${
          Array.isArray(data?.filled_months) && data.filled_months.length > 0
            ? this.renderFilledMonths(data.filled_months)
            : ""
        }
      `;
    }

    renderStatistics(stats) {
      const s = stats || {};
      return `
        <div class="card">
          <div class="card-header">
            <h6 class="card-title">📊 統計資訊</h6>
          </div>
          <div class="card-body">
            <div class="ma-info-grid">
              <div class="ma-info-item">
                <div class="ma-info-label">原始標準差</div>
                <div class="ma-info-value">${this.formatNumber(s.std_original, 2)}</div>
              </div>
              <div class="ma-info-item">
                <div class="ma-info-label">MA 標準差</div>
                <div class="ma-info-value text-success">${this.formatNumber(s.std_ma, 2)}</div>
              </div>
              <div class="ma-info-item">
                <div class="ma-info-label">波動降低</div>
                <div class="ma-info-value text-success">${this.formatNumber(s.reduction_pct, 1)}%</div>
              </div>
              <div class="ma-info-item">
                <div class="ma-info-label">原始安全庫存</div>
                <div class="ma-info-value">${this.formatNumber(s.ss_original, 0)}</div>
              </div>
              <div class="ma-info-item">
                <div class="ma-info-label">MA 安全庫存</div>
                <div class="ma-info-value text-success">${this.formatNumber(s.ss_ma, 0)}</div>
              </div>
              ${
                s.outliers_removed
                  ? `
                <div class="ma-info-item">
                  <div class="ma-info-label">移除異常值</div>
                  <div class="ma-info-value">${this.escapeHtml(s.outliers_removed)} 個</div>
                </div>
              `
                  : ""
              }
            </div>
          </div>
        </div>
      `;
    }

    renderQuarterlySummary(quarterly) {
      const q = quarterly || {};
      const quarters = Object.keys(q).sort();

      return `
        <div class="card ma-quarterly-table">
          <div class="card-header">
            <h6 class="card-title">📅 季度趨勢</h6>
          </div>
          <div class="card-body">
            <table class="table table-sm">
              <thead>
                <tr>
                  <th>季度</th>
                  <th>月份</th>
                  <th class="text-right">平均需求（原始）</th>
                  <th class="text-right">平均需求（MA）</th>
                  <th class="text-right">標準差（原始）</th>
                  <th class="text-right">標準差（MA）</th>
                </tr>
              </thead>
              <tbody>
                ${quarters
                  .map((key) => {
                    const d = q[key] || {};
                    const monthsText = Array.isArray(d.months) ? d.months.join(", ") : "-";
                    return `
                      <tr>
                        <td><strong>${this.escapeHtml(key)}</strong></td>
                        <td>${this.escapeHtml(monthsText)}</td>
                        <td class="text-right">${this.formatNumber(d.avg_original, 2)}</td>
                        <td class="text-right">${this.formatNumber(d.avg_ma, 2)}</td>
                        <td class="text-right">${this.formatNumber(d.std_original, 2)}</td>
                        <td class="text-right">${this.formatNumber(d.std_ma, 2)}</td>
                      </tr>
                    `;
                  })
                  .join("")}
              </tbody>
            </table>
          </div>
        </div>
      `;
    }

    renderRecommendation(rec) {
      const r = rec || {};
      const levelClass = r.level || "info";
      const icon = r.icon || "💡";
      const text = this.escapeHtml(r.text ?? "");
      return `
        <div class="ma-recommendation ${this.escapeHtml(levelClass)}">
          <div class="ma-recommendation-icon">${this.escapeHtml(icon)}</div>
          <div class="ma-recommendation-text">
            <strong>建議：</strong> ${text}
          </div>
        </div>
      `;
    }

    renderFilledMonths(months) {
      const list = Array.isArray(months) ? months : [];
      return `
        <div class="alert alert-info mt-3">
          <strong>📝 填補月份：</strong> ${list.map((m) => this.escapeHtml(this.formatYearMonth(m))).join(", ")}
        </div>
      `;
    }

    // -----------------------------
    // Chart
    // -----------------------------
    renderChart(data) {
      const container = document.getElementById("maChartContainer");
      if (!container) return;

      const monthly = data?.monthly_data;
      if (!monthly || typeof monthly !== "object") {
        container.innerHTML = `<div class="alert alert-warning">沒有 monthly_data，無法渲染圖表。</div>`;
        return;
      }

      const months = Object.keys(monthly).sort();
      if (months.length === 0) {
        container.innerHTML = `<div class="alert alert-warning">monthly_data 為空，無法渲染圖表。</div>`;
        return;
      }

      const labels = months.map((m) => this.formatYearMonth(m));
      const originalY = [];
      const maY = [];
      const filledX = [];
      const filledY = [];

      for (const m of months) {
        const d = monthly[m] || {};
        const o = Number(d.original);
        const ma = Number(d.ma);

        originalY.push(Number.isFinite(o) ? o : null);
        maY.push(Number.isFinite(ma) ? ma : null);

        if (d.filled) {
          filledX.push(this.formatYearMonth(m));
          filledY.push(Number.isFinite(ma) ? ma : null);
        }
      }

      // Plotly
      if (typeof Plotly !== "undefined") {
        const traces = [
          {
            x: labels,
            y: originalY,
            type: "scatter",
            mode: "lines+markers",
            name: "原始需求",
            line: { color: "#6b7280", width: 2 },
            marker: { size: 6 },
          },
          {
            x: labels,
            y: maY,
            type: "scatter",
            mode: "lines+markers",
            name: "MA 平滑",
            line: { color: "#2563eb", width: 2 },
            marker: { size: 6 },
          },
        ];

        if (filledX.length > 0) {
          traces.push({
            x: filledX,
            y: filledY,
            type: "scatter",
            mode: "markers",
            name: "填補月份",
            marker: { size: 10, color: "#ef4444", symbol: "x" },
          });
        }

        const layout = {
          title: "月需求趨勢與 MA 平滑對比",
          xaxis: { title: "月份" },
          yaxis: { title: "需求量" },
          hovermode: "x unified",
          showlegend: true,
          height: 400,
          margin: { l: 50, r: 20, t: 50, b: 50 },
        };

        Plotly.newPlot(container, traces, layout, { responsive: true });
        return;
      }

      // Fallback
      container.innerHTML = `
        <div class="alert alert-warning">
          圖表庫未載入（Plotly 不存在），顯示數據表格：
          <table class="table table-sm mt-2">
            <thead>
              <tr>
                <th>月份</th>
                <th class="text-right">原始</th>
                <th class="text-right">MA</th>
                <th>狀態</th>
              </tr>
            </thead>
            <tbody>
              ${months
                .map((m) => {
                  const d = monthly[m] || {};
                  return `
                    <tr>
                      <td>${this.escapeHtml(this.formatYearMonth(m))}</td>
                      <td class="text-right">${this.formatNumber(d.original, 2)}</td>
                      <td class="text-right">${this.formatNumber(d.ma, 2)}</td>
                      <td>${d.filled ? '<span class="badge badge-danger">填補</span>' : ""}</td>
                    </tr>
                  `;
                })
                .join("")}
            </tbody>
          </table>
        </div>
      `;
    }

    // -----------------------------
    // Utils
    // -----------------------------
    escapeHtml(text) {
      if (text === null || text === undefined) return "-";
      const div = document.createElement("div");
      div.textContent = String(text);
      return div.innerHTML;
    }

    formatNumber(value, decimals = 0) {
      if (value === null || value === undefined || value === "") return "-";
      const num = parseFloat(value);
      if (!Number.isFinite(num)) return "-";
      return num.toLocaleString("zh-TW", {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      });
    }

    formatYearMonth(ym) {
      if (!ym) return "-";
      return ym.toString().replace(/(\d{4})(\d{2})/, "$1-$2");
    }
  }

  // 單例輸出（重複載入不會爆）
  if (!window.MAViewer || !(window.MAViewer instanceof MAViewer)) {
    window.MAViewer = new MAViewer();
  } else {
    console.warn("⚠️ MAViewer already exists, reuse existing instance");
  }
})();