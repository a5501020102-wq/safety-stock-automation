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

  updateStat('statProducts', summary.products || data.length);
  updateStat('statShortage', summary.shortage || 0);
  updateStat('statHealthy', summary.healthy || 0);
  updateStat('statOverstock', summary.overstock || 0);
  updateStat('statExcluded', result.excluded?.length || 0);

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
 * 渲染結果表格
 */
function renderResultsTable(data) {
  const tbody = document.querySelector('#resultsTable tbody');
  if (!tbody) return;

  tbody.innerHTML = '';

  const filteredData = filterData(data);
  const paginatedData = paginateData(filteredData);

  if (paginatedData.length === 0) {
    tbody.innerHTML = '<tr><td colspan="12" class="text-center">暫無資料</td></tr>';
    return;
  }

  paginatedData.forEach((row, idx) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${(AppState.currentPage - 1) * AppState.itemsPerPage + idx + 1}</td>
      <td>${row['出貨點'] || row.site || '-'}</td>
      <td>${row['料號'] || row.sku || '-'}</td>
      <td>${row['品名'] || row.name || '-'}</td>
      <td><span class="abc-badge ${row['ABC類別'] || row.abc_grade}">${row['ABC類別'] || row.abc_grade || '-'}</span></td>
      <td class="text-right">${formatNumber(row['月均需求'] || row.avg_monthly_demand)}</td>
      <td class="text-right">${formatNumber(row['標準差'] || row.std_dev)}</td>
      <td class="text-right">${formatNumber(row['變異係數'] || row.cv, 2)}</td>
      <td class="text-right"><strong>${formatNumber(row['安全庫存'] || row.safety_stock)}</strong></td>
      <td class="text-right">${formatNumber(row['再訂購點'] || row.reorder_point)}</td>
      <td class="text-right">${formatNumber(row['最大庫存'] || row.max_inventory)}</td>
      <td>-</td>
    `;
    tbody.appendChild(tr);
  });
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

  // 狀態篩選
  if (AppState.currentFilter !== 'all') {
    filtered = filtered.filter(row => parseStatus(row) === AppState.currentFilter);
  }

  // 搜尋
  if (AppState.searchTerm) {
    const term = AppState.searchTerm.toLowerCase();
    filtered = filtered.filter(row => {
      const materialNo = String(row['料號'] || row.sku || '').toLowerCase();
      const materialName = String(row['品名'] || row.name || '').toLowerCase();
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
  const ss = row['安全庫存'] || row.safety_stock || 0;
  const current = row['現有庫存'] || row.current_inventory || 0;
  const rop = row['再訂購點'] || row.reorder_point || 0;

  if (current < ss) return 'shortage';
  if (current > rop * 1.5) return 'overstock';
  return 'healthy';
}

/**
 * 格式化數字
 */
function formatNumber(num, decimals = 0) {
  if (num === null || num === undefined || isNaN(num)) return '-';
  return Number(num).toFixed(decimals);
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

  // 設置樣式
  popup.style.cssText = `
    display: none;
    position: fixed;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    z-index: 9999999;
    background: white;
    border: 6px solid #28a745;
    border-radius: 16px;
    box-shadow: 0 0 40px rgba(0, 0, 0, 0.5);
    padding: 40px;
    min-width: 450px;
    text-align: center;
  `;

  // 創建內容
  popup.innerHTML = `
    <div style="font-size: 28px; font-weight: bold; margin-bottom: 12px; color: #28a745;">
      📤 SAP MM17 匯出
    </div>
    <div style="font-size: 14px; color: #666; margin-bottom: 8px;">
      格式：MATNR, WERKS, EISBE
    </div>
    <div style="font-size: 12px; color: #999; margin-bottom: 28px;">
      （正確的 SAP MM17 格式）
    </div>
    <button id="sapPopupXlsxBtn" type="button" style="
      display: block;
      width: 100%;
      padding: 20px;
      margin-bottom: 16px;
      background: linear-gradient(135deg, #28a745 0%, #20c997 100%);
      color: white;
      border: none;
      border-radius: 10px;
      cursor: pointer;
      font-size: 18px;
      font-weight: bold;
      box-shadow: 0 4px 12px rgba(40, 167, 69, 0.3);
      transition: all 0.3s;
    ">
      <i class="fas fa-file-excel" style="margin-right: 8px;"></i>
      📊 XLSX 格式
    </button>
    <button id="sapPopupCsvBtn" type="button" style="
      display: block;
      width: 100%;
      padding: 20px;
      margin-bottom: 20px;
      background: linear-gradient(135deg, #17a2b8 0%, #138496 100%);
      color: white;
      border: none;
      border-radius: 10px;
      cursor: pointer;
      font-size: 18px;
      font-weight: bold;
      box-shadow: 0 4px 12px rgba(23, 162, 184, 0.3);
      transition: all 0.3s;
    ">
      <i class="fas fa-file-csv" style="margin-right: 8px;"></i>
      📄 CSV 格式
    </button>
    <button id="sapPopupCancelBtn" type="button" style="
      display: block;
      width: 100%;
      padding: 12px;
      background: transparent;
      color: #6c757d;
      border: 2px solid #dee2e6;
      border-radius: 8px;
      cursor: pointer;
      font-size: 14px;
      transition: all 0.2s;
    ">
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

  searchInput.addEventListener('input', (e) => {
    AppState.searchTerm = e.target.value;
    AppState.currentPage = 1;

    if (AppState.calculationResult) {
      const data = AppState.calculationResult.results || [];
      renderResultsTable(data);
    }
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

  // ✅ 延遲綁定 SAP MM17 事件（確保 DOM 完全載入）
  setTimeout(() => {
    console.log('⏰ 延遲 500ms 後初始化 SAP MM17 功能');
    bindSapMM17Events();
  }, 500);

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