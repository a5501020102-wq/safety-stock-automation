// ============================================================================
// 安全庫存自動化系統 v4.3.4 - 主程式（Z-scores 修復版）
// ============================================================================
// ✅ Code Review 完成
// ✅ Debug 完成
// ✅ Z-scores 參數格式已修復
//
// v4.3.4 更新：
// - ✅ 修復 z_scores 參數格式（z_a/z_b/z_c → z_scores: {A, B, C}）
// - ✅ 新增參數驗證和除錯日誌
// - ✅ 支援 abc_thresholds 參數（預設值）
//
// 功能：檔案上傳、參數設定、計算、結果顯示、SAP MM17 匯出
// 架構：混合式 (Python 後端 + JavaScript 前端)
// ============================================================================

'use strict';

// ============================================================================
// 全域變數和狀態管理
// ============================================================================

const AppState = {
  uploadedFiles: {
    sales: null,
    price: null,
    plan: null
  },
  calculationResult: null,
  currentMode: null,
  currentFilter: 'all',
  currentSiteFilter: 'all',
  currentPage: 1,
  itemsPerPage: 50,
  searchTerm: ''
};

// ============================================================================
// API 介面層
// ============================================================================

const API = {
  /**
   * 上傳銷貨資料
   */
  async uploadSales(file) {
    const formData = new FormData();
    formData.append('file', file);

    const resp = await fetch('/api/upload/sales', {
      method: 'POST',
      body: formData
    });

    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}));
      throw new Error(errData?.error || '上傳失敗');
    }

    return await resp.json();
  },

  /**
   * 上傳單價資料
   */
  async uploadPrice(file) {
    const formData = new FormData();
    formData.append('file', file);

    const resp = await fetch('/api/upload/price', {
      method: 'POST',
      body: formData
    });

    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}));
      throw new Error(errData?.error || '上傳失敗');
    }

    return await resp.json();
  },

  /**
   * 上傳計劃資料
   */
  async uploadPlan(file) {
    const formData = new FormData();
    formData.append('file', file);

    const resp = await fetch('/api/upload/plan', {
      method: 'POST',
      body: formData
    });

    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}));
      throw new Error(errData?.error || '上傳失敗');
    }

    return await resp.json();
  },

  /**
   * 執行安全庫存計算
   */
  async calculate(params) {
    const resp = await fetch('/api/calculate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params)
    });

    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}));
      throw new Error(errData?.error || '計算失敗');
    }

    return await resp.json();
  },

  /**
   * 匯出 Excel
   */
  async exportExcel(mode = null) {
    const payload = { mode };
    console.log('📤 Excel 匯出請求:', payload);

    const resp = await fetch('/api/export/excel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}));
      throw new Error(errData?.error || 'Excel 匯出失敗');
    }

    const blob = await resp.blob();
    const contentDisp = resp.headers.get('Content-Disposition');
    let filename = 'safety_stock.xlsx';

    if (contentDisp) {
      const match = contentDisp.match(/filename[^;=\n]*=(['"]?)([^'";\n]*)\1/);
      if (match && match[2]) {
        filename = decodeURIComponent(match[2]);
      }
    }

    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    document.body.removeChild(a);

    console.log('✅ Excel 匯出成功:', filename);
    return filename;
  },

  /**
   * 匯出 SAP MM17 格式
   */
  async exportSAP(format = 'xlsx', mode = null) {
    const payload = { format, mode };
    console.log('📤 SAP MM17 匯出請求:', payload);

    const resp = await fetch('/api/export/sap', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}));
      throw new Error(errData?.error || 'SAP MM17 匯出失敗');
    }

    const blob = await resp.blob();
    const contentDisp = resp.headers.get('Content-Disposition');
    let filename = `sap_mm17_${Date.now()}.${format}`;

    if (contentDisp) {
      const match = contentDisp.match(/filename[^;=\n]*=(['"]?)([^'";\n]*)\1/);
      if (match && match[2]) {
        filename = decodeURIComponent(match[2]);
      }
    }

    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    document.body.removeChild(a);

    console.log('✅ SAP MM17 匯出成功:', filename);
    return filename;
  }
};

// ============================================================================
// UI 工具函數
// ============================================================================

const UI = {
  /**
   * 顯示載入中動畫
   */
  showLoading(text = '處理中...') {
    const loading = document.getElementById('loading');
    if (loading) {
      const loadingText = loading.querySelector('.loading-text');
      if (loadingText) loadingText.textContent = text;
      loading.style.display = 'flex';
    }
  },

  /**
   * 隱藏載入中動畫
   */
  hideLoading() {
    const loading = document.getElementById('loading');
    if (loading) {
      loading.style.display = 'none';
    }
  },

  /**
   * 顯示警告訊息
   */
  showAlert(message, type = 'error') {
    const alertMap = {
      error: 'alertError',
      success: 'alertSuccess',
      warning: 'alertWarning'
    };

    const alertId = alertMap[type] || 'alertError';
    const alertEl = document.getElementById(alertId);

    if (alertEl) {
      alertEl.textContent = message;
      alertEl.style.display = 'block';

      setTimeout(() => {
        alertEl.style.display = 'none';
      }, 5000);
    }
  },

  /**
   * 隱藏所有警告
   */
  hideAllAlerts() {
    ['alertError', 'alertSuccess', 'alertWarning'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.style.display = 'none';
    });
  }
};

// ============================================================================
// 檔案上傳功能
// ============================================================================

/**
 * 初始化檔案上傳功能
 */
function initFileUploads() {
  const uploads = [
    { card: 'salesUpload', input: 'salesFile', type: 'sales', apiMethod: API.uploadSales },
    { card: 'priceUpload', input: 'priceFile', type: 'price', apiMethod: API.uploadPrice },
    { card: 'planUpload', input: 'planFile', type: 'plan', apiMethod: API.uploadPlan }
  ];

  uploads.forEach(({ card, input, type, apiMethod }) => {
    const cardEl = document.getElementById(card);
    const inputEl = document.getElementById(input);

    if (!cardEl || !inputEl) return;

    // 點擊上傳區域觸發檔案選擇
    const uploadArea = cardEl.querySelector('.upload-area');
    if (uploadArea) {
      uploadArea.addEventListener('click', () => inputEl.click());
    }

    // 檔案選擇後處理
    inputEl.addEventListener('change', async (e) => {
      const file = e.target.files[0];
      if (!file) return;

      const fileTypeMap = { sales: '銷貨', price: '單價', plan: '庫存' };
      console.log(`📤 上傳${fileTypeMap[type]}資料:`, file.name, file.type, file.size);

      try {
        UI.showLoading(`上傳 ${file.name}...`);
        const result = await apiMethod(file);
        console.log(`📥 上傳結果 (${type}):`, result);

        AppState.uploadedFiles[type] = file.name;

        // 更新 UI
        const fileInfo = cardEl.querySelector('.file-info');
        if (fileInfo) {
          fileInfo.innerHTML = `
            <span class="file-name">✅ ${file.name}</span>
            <span class="file-size">${(file.size / 1024).toFixed(1)} KB</span>
          `;
          fileInfo.style.display = 'flex';
        }

        cardEl.classList.add('uploaded');

        // 銷貨資料上傳後啟用計算按鈕
        if (type === 'sales') {
          const calcBtn = document.getElementById('calculateBtn');
          if (calcBtn) {
            calcBtn.disabled = false;
            console.log('✅ 計算按鈕已啟用');
          }
        }

        UI.showAlert(`${file.name} 上傳成功`, 'success');
      } catch (error) {
        console.error(`❌ 上傳失敗 (${type}):`, error);
        UI.showAlert(`上傳失敗：${error.message}`, 'error');

        // 重置輸入
        inputEl.value = '';
        AppState.uploadedFiles[type] = null;
      } finally {
        UI.hideLoading();
      }
    });
  });
}

// ============================================================================
// 計算參數和控制項
// ============================================================================

/**
 * 初始化計算參數控制項
 */
function initCalculationControls() {
  // Toggle 開關
  const outlierToggle = document.getElementById('outlierToggle');
  const maToggle = document.getElementById('maToggle');
  const enableOutlier = document.getElementById('enableOutlier');
  const enableMA = document.getElementById('enableMA');
  const maSettings = document.getElementById('maSettings');

  if (outlierToggle && enableOutlier) {
    outlierToggle.addEventListener('click', () => {
      outlierToggle.classList.toggle('active');
      enableOutlier.checked = outlierToggle.classList.contains('active');
    });
  }

  if (maToggle && enableMA && maSettings) {
    maToggle.addEventListener('click', () => {
      maToggle.classList.toggle('active');
      enableMA.checked = maToggle.classList.contains('active');
      maSettings.style.display = maToggle.classList.contains('active') ? 'block' : 'none';
    });
  }

  // 移動平均窗口滑桿
  const maWindow = document.getElementById('maWindow');
  const maWindowValue = document.getElementById('maWindowValue');

  if (maWindow && maWindowValue) {
    maWindow.addEventListener('input', (e) => {
      maWindowValue.textContent = e.target.value;
    });
  }

  // 月份選擇按鈕
  const selectAllBtn = document.getElementById('selectAllMonths');
  const deselectAllBtn = document.getElementById('deselectAllMonths');

  if (selectAllBtn) {
    selectAllBtn.addEventListener('click', () => {
      document.querySelectorAll('input[name="selectedMonths"]').forEach(cb => {
        cb.checked = true;
      });
    });
  }

  if (deselectAllBtn) {
    deselectAllBtn.addEventListener('click', () => {
      document.querySelectorAll('input[name="selectedMonths"]').forEach(cb => {
        cb.checked = false;
      });
    });
  }

  // 計算按鈕
  const calculateBtn = document.getElementById('calculateBtn');
  if (calculateBtn) {
    calculateBtn.addEventListener('click', handleCalculation);
  }

  // 重新計算按鈕
  const resetBtn = document.getElementById('resetBtn');
  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      location.reload();
    });
  }

  // Excel 匯出按鈕
  const exportExcelBtn = document.getElementById('exportExcelBtn');
  if (exportExcelBtn) {
    exportExcelBtn.addEventListener('click', handleExcelExport);
  }
}

/**
 * 執行計算
 */
async function handleCalculation() {
  const params = getCalculationParams();
  console.log('📤 計算參數:', params);

  try {
    UI.hideAllAlerts();
    UI.showLoading('計算中...');

    const result = await API.calculate(params);
    console.log('📥 計算結果:', result);

    AppState.calculationResult = result;
    AppState.currentMode = result.mode;

    handleCalculationComplete(result);

    UI.showAlert('計算完成', 'success');
  } catch (error) {
    console.error('❌ 計算錯誤:', error);
    UI.showAlert(`計算失敗：${error.message}`, 'error');
  } finally {
    UI.hideLoading();
  }
}

/**
 * 取得計算參數（v4.3.4 修復版）
 */
function getCalculationParams() {
  const form = document.getElementById('calculationForm');
  const formData = new FormData(form);

  const calcMode = formData.get('calcMode') || 'all';
  const selectedMonths = Array.from(formData.getAll('selectedMonths')).map(Number);

  // ========================================
  // ✅ v4.3.4: 修復 z_scores 參數格式
  // ========================================
  const zScores = {
    A: parseFloat(formData.get('zA') || 2.05),
    B: parseFloat(formData.get('zB') || 1.65),
    C: parseFloat(formData.get('zC') || 1.28)
  };

  // ✅ 驗證 z_scores 數值合理性
  Object.keys(zScores).forEach(key => {
    const value = zScores[key];
    if (isNaN(value) || value < 0.5 || value > 3.5) {
      console.warn(`⚠️  Z-score ${key} 值異常: ${value}，使用預設值`);
      const defaults = { A: 2.05, B: 1.65, C: 1.28 };
      zScores[key] = defaults[key];
    }
  });

  // ========================================
  // ✅ v4.3.4: 新增 abc_thresholds 支援（使用預設值）
  // ========================================
  const abcThresholds = {
    A: 0.80,  // 80% 累積占比
    B: 0.95   // 95% 累積占比
  };

  // ========================================
  // 組合參數
  // ========================================
  const params = {
    calc_mode: calcMode,
    enable_ma: document.getElementById('enableMA')?.checked || false,
    ma_window: parseInt(formData.get('maWindow') || 3),
    lead_time: parseInt(formData.get('leadTime') || 30),
    min_months: parseInt(formData.get('minMonths') || 2),
    enable_outlier: document.getElementById('enableOutlier')?.checked !== false,
    z_scores: zScores,              // ✅ 修正後的格式
    abc_thresholds: abcThresholds,  // ✅ 新增
    selected_months: selectedMonths.length > 0 ? selectedMonths : [1,2,3,4,5,6,7,8,9,10,11,12]
  };

  // ========================================
  // ✅ 除錯日誌
  // ========================================
  console.log('📊 服務水準 (Z-scores):', zScores);
  console.log('📊 ABC 門檻:', abcThresholds);
  console.log('📤 完整計算參數:', params);

  return params;
}

/**
 * 處理計算完成
 */
function handleCalculationComplete(result) {
  console.log('🔄 計算完成處理: mode=' + result.mode);

  const resultsSection = document.getElementById('resultsSection');
  const comparisonSection = document.getElementById('comparisonSection');
  const summaryCard = document.getElementById('summaryCard');
  const resultsTableCard = document.getElementById('resultsTableCard');

  if (!resultsSection) return;

  resultsSection.classList.remove('d-none');

  // 更新 SAP 模式選擇器
  updateSapModeSelector();

  if (result.mode === 'compare') {
    // 對比模式
    console.log('📊 進入對比模式');

    if (comparisonSection) comparisonSection.classList.remove('d-none');
    if (summaryCard) summaryCard.style.display = 'none';
    if (resultsTableCard) resultsTableCard.style.display = 'none';

    // 渲染對比視圖（由 comparison.js 提供）
    if (window.ComparisonView && typeof window.ComparisonView.render === 'function') {
      try {
        window.ComparisonView.render(result);
        console.log('✅ 對比視圖渲染完成');
      } catch (error) {
        console.error('❌ 對比視圖渲染錯誤:', error);
        UI.showAlert('對比視圖渲染失敗', 'error');
      }
    }
  } else {
    // 標準模式
    console.log('📦 進入標準模式');

    if (comparisonSection) comparisonSection.classList.add('d-none');
    if (summaryCard) summaryCard.style.display = 'block';
    if (resultsTableCard) resultsTableCard.style.display = 'block';

    renderStandardView(result);
  }
}

/**
 * 渲染標準視圖
 */
function renderStandardView(result) {
  const data = result.results || [];
  const summary = result.summary || {};

  // 更新統計摘要
  const updateStat = (id, value) => {
    const el = document.getElementById(id);
    if (el) el.textContent = value || 0;
  };

  updateStat('statProducts', summary.total_skus || data.length);
  updateStat('statShortage', summary.shortage_risk_count || 0);
  updateStat('statHealthy', summary.healthy_count || 0);
  updateStat('statOverstock', summary.overstock_risk_count || 0);
  updateStat('statExcluded', summary.excluded_count || result.excluded?.length || 0);

  // 移動平均資訊
  if (result.ma_info) {
    const maSummary = document.getElementById('maSummary');
    if (maSummary) {
      maSummary.style.display = 'block';
      updateStat('maWindowDisplay', result.ma_info.window);
      updateStat('maAvgReduction', result.ma_info.avg_reduction || 0);
    }
  }

  // 渲染表格
  renderResultsTable(data);

  // 初始化篩選標籤
  initFilterTabs(data);
}

/**
 * 渲染結果表格（含分頁和出貨點篩選）
 */
function renderResultsTable(data) {
  const tbody = document.querySelector('#resultsTable tbody');
  if (!tbody) return;

  tbody.innerHTML = '';

  // 出貨點篩選
  initSiteFilter(data);

  const filteredData = filterData(data);
  const totalItems = filteredData.length;
  const totalPages = Math.ceil(totalItems / AppState.itemsPerPage);

  if (AppState.currentPage > totalPages && totalPages > 0) {
    AppState.currentPage = totalPages;
  }

  const paginatedData = paginateData(filteredData);

  if (paginatedData.length === 0) {
    tbody.innerHTML = '<tr><td colspan="12" class="text-center">暫無資料</td></tr>';
    renderPagination(0, 0);
    return;
  }

  paginatedData.forEach((row, idx) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${(AppState.currentPage - 1) * AppState.itemsPerPage + idx + 1}</td>
      <td>${row.site || '-'}</td>
      <td>${row.sku || '-'}</td>
      <td>${row.name || '-'}</td>
      <td><span class="abc-badge ${row.abc_grade}">${row.abc_grade || '-'}</span></td>
      <td class="text-right">${formatNumber(row.mean_demand || row.avg_monthly_demand)}</td>
      <td class="text-right">${formatNumber(row.std_dev)}</td>
      <td class="text-right">${formatNumber(row.cv, 2)}</td>
      <td class="text-right"><strong>${formatNumber(row.safety_stock)}</strong></td>
      <td class="text-right">${formatNumber(row.reorder_point)}</td>
      <td class="text-right">${formatNumber(row.max_inventory)}</td>
      <td>-</td>
    `;
    tbody.appendChild(tr);
  });

  renderPagination(totalItems, totalPages);
}

/**
 * 初始化出貨點篩選（標準模式）
 */
function initSiteFilter(data) {
  const filterRow = document.querySelector('.filter-row');
  if (!filterRow) return;

  // 只在第一次建立
  if (document.getElementById('siteFilter')) return;

  const sites = [...new Set(data.map(r => r.site).filter(Boolean))].sort();
  if (sites.length <= 1) return;

  const container = document.createElement('div');
  container.style.cssText = 'display:flex;align-items:center;gap:0.5rem;margin-left:1rem;';
  container.innerHTML = `
    <label style="font-weight:600;white-space:nowrap;">出貨點：</label>
    <select id="siteFilter" class="form-control" style="width:auto;min-width:120px;">
      <option value="all">全部 (${data.length})</option>
      ${sites.map(s => {
        const count = data.filter(r => r.site === s).length;
        return `<option value="${s}">${s} (${count})</option>`;
      }).join('')}
    </select>
  `;
  filterRow.appendChild(container);

  document.getElementById('siteFilter').addEventListener('change', (e) => {
    AppState.currentSiteFilter = e.target.value;
    AppState.currentPage = 1;
    renderResultsTable(data);
  });
}

/**
 * 渲染分頁控制項
 */
function renderPagination(totalItems, totalPages) {
  let paginationEl = document.getElementById('standardPagination');
  if (!paginationEl) {
    const tableWrapper = document.querySelector('#resultsTableCard .table-wrapper');
    if (!tableWrapper) return;
    paginationEl = document.createElement('div');
    paginationEl.id = 'standardPagination';
    paginationEl.style.cssText = 'display:flex;justify-content:space-between;align-items:center;padding:1rem 0;';
    tableWrapper.after(paginationEl);
  }

  if (totalPages <= 1) {
    paginationEl.innerHTML = `<div style="color:#666;">共 ${totalItems} 筆資料</div>`;
    return;
  }

  const start = (AppState.currentPage - 1) * AppState.itemsPerPage + 1;
  const end = Math.min(AppState.currentPage * AppState.itemsPerPage, totalItems);

  let btns = '';
  const maxShow = 5;
  let startPage = Math.max(1, AppState.currentPage - 2);
  let endPage = Math.min(totalPages, startPage + maxShow - 1);
  if (endPage - startPage < maxShow - 1) startPage = Math.max(1, endPage - maxShow + 1);

  for (let i = startPage; i <= endPage; i++) {
    btns += `<button class="btn btn-sm ${i === AppState.currentPage ? 'btn-primary' : 'btn-secondary'}"
              onclick="AppState.currentPage=${i};renderResultsTable(AppState.calculationResult.results);"
              style="margin:0 2px;">${i}</button>`;
  }

  paginationEl.innerHTML = `
    <div style="color:#666;">顯示 ${start}-${end} / 共 ${totalItems} 筆</div>
    <div style="display:flex;gap:4px;align-items:center;">
      <button class="btn btn-sm btn-secondary" ${AppState.currentPage <= 1 ? 'disabled' : ''}
              onclick="AppState.currentPage--;renderResultsTable(AppState.calculationResult.results);">◀</button>
      ${btns}
      <button class="btn btn-sm btn-secondary" ${AppState.currentPage >= totalPages ? 'disabled' : ''}
              onclick="AppState.currentPage++;renderResultsTable(AppState.calculationResult.results);">▶</button>
    </div>
  `;
}

/**
 * 初始化篩選標籤
 */
function initFilterTabs(data) {
  const filterTabs = document.getElementById('filterTabs');
  if (!filterTabs) return;

  const counts = {
    all: data.length,
    shortage: data.filter(r => parseStatus(r) === 'shortage').length,
    healthy: data.filter(r => parseStatus(r) === 'healthy').length,
    overstock: data.filter(r => parseStatus(r) === 'overstock').length
  };

  filterTabs.innerHTML = `
    <button class="filter-tab active" data-filter="all">全部 (${counts.all})</button>
    <button class="filter-tab" data-filter="shortage">缺貨風險 (${counts.shortage})</button>
    <button class="filter-tab" data-filter="healthy">健康 (${counts.healthy})</button>
    <button class="filter-tab" data-filter="overstock">呆滯 (${counts.overstock})</button>
  `;

  filterTabs.querySelectorAll('.filter-tab').forEach(tab => {
    tab.addEventListener('click', (e) => {
      filterTabs.querySelectorAll('.filter-tab').forEach(t => t.classList.remove('active'));
      e.target.classList.add('active');
      AppState.currentFilter = e.target.dataset.filter;
      AppState.currentPage = 1;
      renderResultsTable(data);
    });
  });
}

/**
 * 篩選資料
 */
function filterData(data) {
  let filtered = data;

  // 出貨點篩選
  if (AppState.currentSiteFilter && AppState.currentSiteFilter !== 'all') {
    filtered = filtered.filter(row => row.site === AppState.currentSiteFilter);
  }

  // 狀態篩選
  if (AppState.currentFilter !== 'all') {
    filtered = filtered.filter(row => parseStatus(row) === AppState.currentFilter);
  }

  // 搜尋
  if (AppState.searchTerm) {
    const term = AppState.searchTerm.toLowerCase();
    filtered = filtered.filter(row => {
      const materialNo = String(row.sku || '').toLowerCase();
      const materialName = String(row.name || '').toLowerCase();
      return materialNo.includes(term) || materialName.includes(term);
    });
  }

  return filtered;
}

/**
 * 分頁資料
 */
function paginateData(data) {
  const start = (AppState.currentPage - 1) * AppState.itemsPerPage;
  const end = start + AppState.itemsPerPage;
  return data.slice(start, end);
}

/**
 * 解析狀態
 */
function parseStatus(row) {
  const status = row.status;
  if (status === 'red') return 'shortage';
  if (status === 'blue') return 'overstock';
  if (status === 'green') return 'healthy';
  return 'healthy';
}

/**
 * 格式化數字
 */
function formatNumber(num, decimals = 0) {
  if (num === null || num === undefined || isNaN(num)) return '-';
  return Number(num).toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals
  });
}

// ============================================================================
// Excel 匯出功能
// ============================================================================

/**
 * 處理 Excel 匯出
 */
async function handleExcelExport() {
  try {
    if (!AppState.calculationResult) {
      UI.showAlert('請先完成計算', 'warning');
      return;
    }

    UI.showLoading('匯出 Excel...');

    const mode = AppState.currentMode === 'compare' ? 'all' : null;
    await API.exportExcel(mode);

    UI.showAlert('Excel 匯出成功', 'success');
  } catch (error) {
    console.error('❌ Excel 匯出錯誤:', error);
    UI.showAlert(`Excel 匯出失敗：${error.message}`, 'error');
  } finally {
    UI.hideLoading();
  }
}

// ============================================================================
// SAP MM17 匯出功能（v4.3.1 最終修復版）
// ============================================================================

/**
 * SAP MM17 匯出主函數
 */
async function exportSapMM17(format) {
  console.log(`📊 SAP MM17 匯出開始: ${format}`);

  try {
    if (!AppState.calculationResult) {
      UI.showAlert('請先完成計算', 'warning');
      return;
    }

    UI.showLoading(`匯出 SAP MM17 (${format.toUpperCase()})...`);

    // 取得選擇的模式（對比模式時）
    let exportMode = null;
    if (AppState.currentMode === 'compare') {
      const selectedMode = document.querySelector('input[name="sapExportMode"]:checked');
      if (selectedMode) {
        exportMode = selectedMode.value;
      }
    }

    await API.exportSAP(format, exportMode);
    UI.showAlert(`SAP MM17 ${format.toUpperCase()} 匯出成功`, 'success');
  } catch (error) {
    console.error('❌ SAP MM17 匯出錯誤:', error);
    UI.showAlert(`SAP MM17 匯出失敗：${error.message}`, 'error');
  } finally {
    UI.hideLoading();
  }
}

/**
 * 更新 SAP 模式選擇器顯示
 */
function updateSapModeSelector() {
  const selector = document.getElementById('sapModeSelector');
  if (!selector) {
    console.warn('⚠️  sapModeSelector 元素不存在');
    return;
  }

  const currentMode = AppState.currentMode;
  console.log(`🔄 更新 SAP 模式選擇器: mode=${currentMode}`);

  if (currentMode === 'compare') {
    selector.classList.remove('d-none');
    console.log('✅ SAP 模式選擇器已顯示');
  } else {
    selector.classList.add('d-none');
    console.log('✅ SAP 模式選擇器已隱藏');
  }
}

// ============================================================================
// SAP MM17 彈出菜單系統（v4.3.1 最終修復版）
// ============================================================================

/**
 * 創建 SAP MM17 彈出菜單
 */
function createSapMM17PopupMenu() {
  const popup = document.getElementById('sapMM17PopupMenu');
  if (!popup) {
    console.error('❌ 找不到 sapMM17PopupMenu 容器');
    return;
  }

  // 如果已經創建過，跳過
  if (popup.innerHTML) {
    console.log('✅ 彈出菜單已存在，跳過創建');
    return;
  }

  // 設置樣式（使用 CSS 類別，避免大量 inline style）
  popup.className = 'sap-popup-overlay';

  // 創建內容
  popup.innerHTML = `
    <div class="sap-popup-title">
      📤 SAP MM17 匯出
    </div>
    <div class="sap-popup-subtitle">
      格式：MATNR, WERKS, EISBE
    </div>
    <div class="sap-popup-hint">
      （正確的 SAP MM17 格式）
    </div>
    <button id="sapPopupXlsxBtn" type="button" class="sap-popup-btn sap-popup-btn-xlsx">
      <i class="fas fa-file-excel"></i>
      📊 XLSX 格式
    </button>
    <button id="sapPopupCsvBtn" type="button" class="sap-popup-btn sap-popup-btn-csv">
      <i class="fas fa-file-csv"></i>
      📄 CSV 格式
    </button>
    <button id="sapPopupCancelBtn" type="button" class="sap-popup-btn-cancel">
      取消
    </button>
  `;

  console.log('✅ SAP MM17 彈出菜單已創建');
}

/**
 * 綁定 SAP MM17 事件（修復版）
 */
function bindSapMM17Events() {
  console.log('🔧 開始綁定 SAP MM17 事件（修復版）...');

  // 創建彈出菜單
  createSapMM17PopupMenu();

  // 獲取元素
  const sapBtn = document.getElementById('exportSAPBtn');
  const popup = document.getElementById('sapMM17PopupMenu');

  if (!sapBtn) {
    console.error('❌ exportSAPBtn 不存在');
    return;
  }

  if (!popup) {
    console.error('❌ sapMM17PopupMenu 不存在');
    return;
  }

  // 清除舊事件（使用克隆方式）
  const newSapBtn = sapBtn.cloneNode(true);
  sapBtn.parentNode.replaceChild(newSapBtn, sapBtn);
  console.log('✅ 已清除舊事件監聽器');

  // 重新獲取按鈕
  const cleanSapBtn = document.getElementById('exportSAPBtn');

  // 綁定主按鈕點擊
  cleanSapBtn.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    popup.style.display = 'block';
    console.log('✅ SAP MM17 彈出菜單已顯示');
  });
  console.log('✅ 主按鈕點擊事件已綁定');

  // 綁定菜單按鈕
  const xlsxBtn = document.getElementById('sapPopupXlsxBtn');
  const csvBtn = document.getElementById('sapPopupCsvBtn');
  const cancelBtn = document.getElementById('sapPopupCancelBtn');

  if (xlsxBtn) {
    xlsxBtn.addEventListener('click', () => {
      console.log('📥 SAP MM17 XLSX 按鈕點擊');
      popup.style.display = 'none';
      exportSapMM17('xlsx');
    });

    // 懸停效果
    xlsxBtn.addEventListener('mouseenter', function() {
      this.style.transform = 'translateY(-2px)';
      this.style.boxShadow = '0 6px 20px rgba(40, 167, 69, 0.4)';
    });
    xlsxBtn.addEventListener('mouseleave', function() {
      this.style.transform = 'translateY(0)';
      this.style.boxShadow = '0 4px 12px rgba(40, 167, 69, 0.3)';
    });

    console.log('✅ XLSX 按鈕已綁定');
  }

  if (csvBtn) {
    csvBtn.addEventListener('click', () => {
      console.log('📥 SAP MM17 CSV 按鈕點擊');
      popup.style.display = 'none';
      exportSapMM17('csv');
    });

    // 懸停效果
    csvBtn.addEventListener('mouseenter', function() {
      this.style.transform = 'translateY(-2px)';
      this.style.boxShadow = '0 6px 20px rgba(23, 162, 184, 0.4)';
    });
    csvBtn.addEventListener('mouseleave', function() {
      this.style.transform = 'translateY(0)';
      this.style.boxShadow = '0 4px 12px rgba(23, 162, 184, 0.3)';
    });

    console.log('✅ CSV 按鈕已綁定');
  }

  if (cancelBtn) {
    cancelBtn.addEventListener('click', () => {
      popup.style.display = 'none';
      console.log('✅ 菜單已關閉');
    });

    // 懸停效果
    cancelBtn.addEventListener('mouseenter', function() {
      this.style.backgroundColor = '#f8f9fa';
    });
    cancelBtn.addEventListener('mouseleave', function() {
      this.style.backgroundColor = 'transparent';
    });

    console.log('✅ 取消按鈕已綁定');
  }

  // 點擊外部關閉
  document.addEventListener('click', (e) => {
    if (popup.style.display === 'block' &&
        !popup.contains(e.target) &&
        e.target !== cleanSapBtn) {
      popup.style.display = 'none';
      console.log('✅ 點擊外部關閉菜單');
    }
  });

  // ESC 鍵關閉
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && popup.style.display === 'block') {
      popup.style.display = 'none';
      console.log('✅ ESC 關閉菜單');
    }
  });

  console.log('🎉 SAP MM17 事件綁定完成（修復版）！');
}

// ============================================================================
// 搜尋功能
// ============================================================================

/**
 * 初始化搜尋功能
 */
function initSearch() {
  const searchInput = document.getElementById('searchInput');
  if (!searchInput) return;

  let searchTimer = null;
  searchInput.addEventListener('input', (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      AppState.searchTerm = e.target.value;
      AppState.currentPage = 1;

      if (AppState.calculationResult) {
        const data = AppState.calculationResult.results || [];
        renderResultsTable(data);
      }
    }, 300);
  });
}

// ============================================================================
// 主初始化函數
// ============================================================================

/**
 * DOMContentLoaded 主初始化
 */
document.addEventListener('DOMContentLoaded', () => {
  console.log('🚀 系統啟動 v4.3.4 (Z-scores 修復版)');

  // 初始化各項功能
  initFileUploads();
  initCalculationControls();
  initSearch();

  console.log('✅ 主初始化完成');

  // ✅ 綁定 SAP MM17 事件（DOMContentLoaded 已保證 DOM 就緒）
  bindSapMM17Events();

  console.log('✅ main.js v4.3.4 已載入 - Z-scores 修復版');
});

// ============================================================================
// 全域導出
// ============================================================================

// 導出給其他模組使用
window.AppState = AppState;
window.API = API;
window.UI = UI;
window.exportSapMM17 = exportSapMM17;
window.updateSapModeSelector = updateSapModeSelector;
window.handleCalculationComplete = handleCalculationComplete;

console.log('✅ 全域變數已導出');