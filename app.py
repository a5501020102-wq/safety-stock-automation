"""
安全庫存自動化系統 - Flask 應用（v4.3.4 - Z-scores 參數支援）
Safety Stock Automation - Flask Application

Version: 4.3.4
Author: 松鼠
Last Updated: 2026-01-29
Last Updated: 2026-01-29

🔧 v4.3.4 功能增強：
- ✅ 新增 z_scores 參數支援（前端服務水準設定生效）
- ✅ 新增 abc_thresholds 參數支援（可自訂 ABC 分類門檻）
- ✅ 優化參數驗證和錯誤處理
- ✅ 增強日誌輸出（顯示服務水準和 ABC 門檻）
- ✅ 向後兼容（沒有傳參數時使用預設值）

修改內容：
- calculate() API：接收並傳遞 z_scores 和 abc_thresholds
- 對比模式：同步支援新參數
- 日誌：顯示完整的計算參數
- 驗證：確保參數格式正確
"""

from flask import Flask, render_template, request, jsonify, send_file, session
from flask_session import Session
from werkzeug.utils import secure_filename
import os
from pathlib import Path
import json
from datetime import datetime
import traceback
import logging
import pickle
from typing import Optional, Dict, Any, Tuple, List
import pandas as pd
import io

# ============================================================================
# 日誌配置
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('app.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# ============================================================================
# 路徑設定
# ============================================================================

import sys

sys.path.insert(0, str(Path(__file__).parent))

# ============================================================================
# 導入核心模組
# ============================================================================

MODULES_AVAILABLE = False

try:
    from src.calculator import SafetyStockCalculator
    from src.data_loader import load_sales_data, load_price_data, load_plan_data, DataLoadError
    from src.business_logic import (
        calculate_comparison_mode,
        get_ma_detail_for_sku,
        export_to_excel,
        export_to_sap_mm17,
        export_comparison_to_excel,
        serialize_results_for_json
    )

    MODULES_AVAILABLE = True
    logger.info("✅ 核心模組載入成功")
except ImportError as e:
    logger.error(f"❌ 無法導入核心模組：{e}")
    logger.warning("⚠️  部分功能將無法使用")

# ============================================================================
# Flask 應用初始化
# ============================================================================

app = Flask(__name__)

app.config.update(
    SECRET_KEY=os.environ.get('SECRET_KEY', 'ss-automation-dev-key-change-me'),
    SESSION_TYPE='filesystem',
    SESSION_FILE_DIR='flask_session',
    SESSION_PERMANENT=False,
    SESSION_USE_SIGNER=True,
    PERMANENT_SESSION_LIFETIME=3600,
    UPLOAD_FOLDER='uploads',
    CACHE_FOLDER='cache',
    OUTPUT_FOLDER='data/output',
    MAX_CONTENT_LENGTH=100 * 1024 * 1024,
    ALLOWED_EXTENSIONS={'xlsx', 'xls'},
)

Session(app)

DEBUG_MODE = os.environ.get('FLASK_ENV') == 'development'

for folder in ['UPLOAD_FOLDER', 'CACHE_FOLDER', 'OUTPUT_FOLDER', 'SESSION_FILE_DIR']:
    Path(app.config.get(folder, folder)).mkdir(parents=True, exist_ok=True)

logger.info(f"🚀 Flask 應用初始化完成 v4.3.4")
logger.info(f"📁 Session 存儲: {app.config['SESSION_FILE_DIR']}")


# ============================================================================
# 工具函數
# ============================================================================

def allowed_file(filename: str) -> bool:
    """檢查檔案類型"""
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


def validate_upload(file) -> Tuple[bool, str]:
    """驗證上傳檔案"""
    if not file or file.filename == '':
        return False, '未選擇檔案'

    if not allowed_file(file.filename):
        return False, f'不支援的檔案格式，僅支援: {", ".join(app.config["ALLOWED_EXTENSIONS"])}'

    if hasattr(file, 'content_length') and file.content_length:
        max_size = app.config['MAX_CONTENT_LENGTH']
        if file.content_length > max_size:
            return False, f'檔案過大（最大 {max_size // (1024 * 1024)} MB）'

    return True, ''


def save_upload_file(file, prefix: str = 'file') -> Tuple[bool, str, str]:
    """安全保存上傳檔案"""
    try:
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        saved_filename = f"{prefix}_{timestamp}_{filename}"

        upload_dir = Path(app.config['UPLOAD_FOLDER']).resolve()
        filepath = (upload_dir / saved_filename).resolve()

        if not str(filepath).startswith(str(upload_dir)):
            logger.error(f"🚨 路徑遍歷攻擊嘗試：{filepath}")
            return False, '無效的檔案路徑', ''

        file.save(str(filepath))
        logger.info(f"✅ 檔案已保存：{saved_filename}")

        return True, saved_filename, str(filepath)

    except Exception as e:
        logger.error(f"❌ 保存檔案失敗：{e}", exc_info=True)
        return False, f'保存檔案失敗：{str(e)}', ''


def get_safe_filepath(filename: str) -> Optional[str]:
    """安全取得檔案路徑"""
    try:
        upload_dir = Path(app.config['UPLOAD_FOLDER']).resolve()
        filepath = (upload_dir / filename).resolve()

        if not str(filepath).startswith(str(upload_dir)):
            logger.warning(f"⚠️  嘗試存取非法路徑：{filepath}")
            return None

        if not filepath.exists():
            logger.warning(f"⚠️  檔案不存在：{filepath}")
            return None

        return str(filepath)

    except Exception as e:
        logger.error(f"❌ 取得檔案路徑失敗：{e}", exc_info=True)
        return None


def init_session():
    """初始化 session"""
    if 'initialized' not in session:
        session['sales_filename'] = None
        session['price_filename'] = None
        session['plan_filename'] = None
        session['calculation_results'] = None
        session['calculation_summary'] = None
        session['calculation_results_total'] = None
        session['calculation_summary_total'] = None
        session['comparison_data'] = None
        session['sales_data'] = None
        session['calc_mode'] = None
        session['initialized'] = True
        logger.debug("Session 已初始化")


def filter_results_by_site(results: List, site_filter: Optional[str]) -> List:
    """
    根據出貨點篩選結果

    Args:
        results: 計算結果列表
        site_filter: 出貨點篩選（None 或 "all" 表示不篩選）

    Returns:
        篩選後的結果列表
    """
    if not site_filter or site_filter == "all":
        return results

    filtered = [r for r in results if getattr(r, 'site', None) == site_filter]

    logger.info(f"   出貨點篩選 [{site_filter}]: {len(results)} → {len(filtered)} 筆")

    return filtered


def validate_z_scores(z_scores: Dict[str, float]) -> Tuple[bool, str, Dict[str, float]]:
    """
    驗證 z_scores 參數格式和數值範圍

    Args:
        z_scores: Z-scores 字典

    Returns:
        (是否有效, 錯誤訊息, 清理後的值)
    """
    try:
        # 預設值
        default_z_scores = {"A": 2.05, "B": 1.65, "C": 1.28}

        if not z_scores or not isinstance(z_scores, dict):
            return True, '', default_z_scores

        # 驗證必要的 key
        required_keys = ['A', 'B', 'C']
        for key in required_keys:
            if key not in z_scores:
                logger.warning(f"⚠️  z_scores 缺少 key: {key}，使用預設值")
                z_scores[key] = default_z_scores[key]

        # 驗證數值範圍 (合理的 Z-score 範圍: 0.5 - 3.5)
        cleaned = {}
        for key in required_keys:
            try:
                value = float(z_scores[key])
                if not (0.5 <= value <= 3.5):
                    logger.warning(f"⚠️  z_scores[{key}] = {value} 超出合理範圍 [0.5, 3.5]，使用預設值")
                    cleaned[key] = default_z_scores[key]
                else:
                    cleaned[key] = value
            except (ValueError, TypeError):
                logger.warning(f"⚠️  z_scores[{key}] 格式無效，使用預設值")
                cleaned[key] = default_z_scores[key]

        return True, '', cleaned

    except Exception as e:
        logger.error(f"❌ 驗證 z_scores 失敗：{e}")
        return False, f'z_scores 參數格式錯誤：{str(e)}', default_z_scores


def validate_abc_thresholds(abc_thresholds: Dict[str, float]) -> Tuple[bool, str, Dict[str, float]]:
    """
    驗證 abc_thresholds 參數格式和邏輯

    Args:
        abc_thresholds: ABC 分類門檻字典

    Returns:
        (是否有效, 錯誤訊息, 清理後的值)
    """
    try:
        # 預設值
        default_thresholds = {"A": 0.80, "B": 0.95}

        if not abc_thresholds or not isinstance(abc_thresholds, dict):
            return True, '', default_thresholds

        # 驗證必要的 key
        if 'A' not in abc_thresholds or 'B' not in abc_thresholds:
            logger.warning(f"⚠️  abc_thresholds 格式不完整，使用預設值")
            return True, '', default_thresholds

        # 驗證數值
        try:
            threshold_a = float(abc_thresholds['A'])
            threshold_b = float(abc_thresholds['B'])
        except (ValueError, TypeError):
            logger.warning(f"⚠️  abc_thresholds 數值格式無效，使用預設值")
            return True, '', default_thresholds

        # 驗證邏輯：A < B < 1.0
        if not (0.0 < threshold_a < threshold_b < 1.0):
            error_msg = f'ABC 門檻邏輯錯誤：需要 0 < A({threshold_a}) < B({threshold_b}) < 1'
            logger.error(f"❌ {error_msg}")
            return False, error_msg, default_thresholds

        # 合理範圍檢查
        if threshold_a < 0.5 or threshold_a > 0.95:
            logger.warning(f"⚠️  A類門檻 {threshold_a} 不在建議範圍 [0.5, 0.95]，但仍接受")

        if threshold_b < 0.8 or threshold_b > 0.99:
            logger.warning(f"⚠️  B類門檻 {threshold_b} 不在建議範圍 [0.8, 0.99]，但仍接受")

        cleaned = {"A": threshold_a, "B": threshold_b}
        return True, '', cleaned

    except Exception as e:
        logger.error(f"❌ 驗證 abc_thresholds 失敗：{e}")
        return False, f'abc_thresholds 參數格式錯誤：{str(e)}', default_thresholds


# ============================================================================
# 路由：健康檢查
# ============================================================================

@app.route('/health', methods=['GET'])
def health():
    """健康檢查端點"""
    return jsonify({
        'status': 'healthy',
        'version': '4.3.4',
        'modules_available': MODULES_AVAILABLE,
        'session_type': app.config['SESSION_TYPE'],
        'timestamp': datetime.now().isoformat()
    })


# ============================================================================
# 路由：頁面
# ============================================================================

@app.route('/')
def index():
    """主頁"""
    try:
        init_session()
        return render_template('index.html')
    except Exception as e:
        logger.error(f"❌ 渲染首頁失敗：{e}", exc_info=True)
        return f"系統錯誤：{str(e)}", 500


# ============================================================================
# 路由：API - 檔案上傳
# ============================================================================

@app.route('/api/upload/sales', methods=['POST'])
def upload_sales():
    """上傳銷貨資料"""
    try:
        if not MODULES_AVAILABLE:
            return jsonify({
                'success': False,
                'error': '核心模組未載入，請檢查系統設定'
            }), 500

        init_session()

        file = request.files.get('file')
        valid, error_msg = validate_upload(file)
        if not valid:
            return jsonify({'success': False, 'error': error_msg}), 400

        success, result, filepath = save_upload_file(file, 'sales')
        if not success:
            return jsonify({'success': False, 'error': result}), 500

        try:
            logger.info(f"📂 開始載入銷貨資料：{result}")
            sales_data = load_sales_data(filepath)

            df = sales_data.df
            sites = sorted(df['site'].unique().tolist())
            records = len(df)

            if 'year_month' in df.columns:
                year_months = sorted([ym for ym in df['year_month'].unique() if pd.notna(ym)])
                date_range = f"{year_months[0]} to {year_months[-1]}" if year_months else "Unknown"
            else:
                date_range = "Unknown"

            session['sales_filename'] = result
            logger.info(f"✅ 銷貨資料載入成功：{records} 筆，{len(sites)} 個出貨點")

            return jsonify({
                'success': True,
                'filename': result,
                'records': records,
                'sites': sites,
                'date_range': date_range
            })

        except DataLoadError as e:
            logger.error(f"❌ 資料載入錯誤：{e}", exc_info=True)
            return jsonify({
                'success': False,
                'error': f'資料格式錯誤：{str(e)}'
            }), 400

    except Exception as e:
        logger.error(f"❌ 上傳失敗：{e}", exc_info=True)
        response = {'success': False, 'error': '上傳失敗'}
        if DEBUG_MODE:
            response['detail'] = str(e)
            response['traceback'] = traceback.format_exc()
        return jsonify(response), 500


@app.route('/api/upload/price', methods=['POST'])
def upload_price():
    """上傳單價資料"""
    try:
        if not MODULES_AVAILABLE:
            return jsonify({'success': False, 'error': '核心模組未載入'}), 500

        init_session()

        file = request.files.get('file')
        valid, error_msg = validate_upload(file)
        if not valid:
            return jsonify({'success': False, 'error': error_msg}), 400

        success, result, filepath = save_upload_file(file, 'price')
        if not success:
            return jsonify({'success': False, 'error': result}), 500

        try:
            logger.info(f"📂 開始載入單價資料：{result}")
            price_data = load_price_data(filepath)
            session['price_filename'] = result
            logger.info(f"✅ 單價資料載入成功：{len(price_data.price_map)} 筆")

            return jsonify({
                'success': True,
                'filename': result,
                'count': len(price_data.price_map)
            })
        except Exception as e:
            logger.error(f"❌ 單價資料載入失敗：{e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 400

    except Exception as e:
        logger.error(f"❌ 上傳單價資料失敗：{e}", exc_info=True)
        return jsonify({'success': False, 'error': '上傳失敗'}), 500


@app.route('/api/upload/plan', methods=['POST'])
def upload_plan():
    """上傳庫存計劃"""
    try:
        if not MODULES_AVAILABLE:
            return jsonify({'success': False, 'error': '核心模組未載入'}), 500

        init_session()

        file = request.files.get('file')
        valid, error_msg = validate_upload(file)
        if not valid:
            return jsonify({'success': False, 'error': error_msg}), 400

        success, result, filepath = save_upload_file(file, 'plan')
        if not success:
            return jsonify({'success': False, 'error': result}), 500

        try:
            logger.info(f"📂 開始載入庫存計劃：{result}")
            plan_data = load_plan_data(filepath)
            session['plan_filename'] = result
            logger.info(f"✅ 庫存計劃載入成功")

            return jsonify({
                'success': True,
                'filename': result
            })
        except Exception as e:
            logger.error(f"❌ 庫存計劃載入失敗：{e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 400

    except Exception as e:
        logger.error(f"❌ 上傳庫存計劃失敗：{e}", exc_info=True)
        return jsonify({'success': False, 'error': '上傳失敗'}), 500


# ============================================================================
# 路由：API - 計算
# ============================================================================

@app.route('/api/calculate', methods=['POST'])
def calculate():
    """執行安全庫存計算（v4.3.4 - 支援 z_scores 和 abc_thresholds）"""
    try:
        if not MODULES_AVAILABLE:
            return jsonify({'success': False, 'error': '核心模組未載入'}), 500

        init_session()

        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': '無效的請求數據'}), 400

        # ========================================
        # 基本參數
        # ========================================
        calc_mode = data.get('calc_mode', 'all')
        enable_ma = data.get('enable_ma', False)
        ma_window = data.get('ma_window', 3)
        lead_time = data.get('lead_time', 30)
        min_months = data.get('min_months', 2)
        selected_months = data.get('selected_months', list(range(1, 13)))
        enable_outlier = data.get('enable_outlier', True)

        # ========================================
        # ✅ v4.3.4 新增：Z-scores（服務水準）
        # ========================================
        z_scores_raw = data.get('z_scores', None)
        valid, error_msg, z_scores = validate_z_scores(z_scores_raw)
        if not valid:
            return jsonify({'success': False, 'error': error_msg}), 400

        # ========================================
        # ✅ v4.3.4 新增：ABC 分類門檻
        # ========================================
        abc_thresholds_raw = data.get('abc_thresholds', None)
        valid, error_msg, abc_thresholds = validate_abc_thresholds(abc_thresholds_raw)
        if not valid:
            return jsonify({'success': False, 'error': error_msg}), 400

        # ========================================
        # 日誌輸出
        # ========================================
        logger.info(f"🧮 開始計算")
        logger.info(f"   模式: {calc_mode}")
        logger.info(f"   移動平均: {'啟用' if enable_ma else '停用'} (窗口: {ma_window})")
        logger.info(f"   前置期: {lead_time} 天")
        logger.info(f"   最少月數: {min_months}")
        logger.info(f"   離群值檢測: {'啟用' if enable_outlier else '停用'}")
        logger.info(f"   ✅ 服務水準: A={z_scores['A']:.2f}, B={z_scores['B']:.2f}, C={z_scores['C']:.2f}")
        logger.info(f"   ✅ ABC門檻: A={abc_thresholds['A']:.0%}, B={abc_thresholds['B']:.0%}")

        # ========================================
        # 載入資料
        # ========================================
        sales_filename = session.get('sales_filename')
        if not sales_filename:
            return jsonify({'success': False, 'error': '請先上傳銷貨資料'}), 400

        sales_path = get_safe_filepath(sales_filename)
        if not sales_path:
            return jsonify({'success': False, 'error': '找不到銷貨資料檔案'}), 400

        sales_data = load_sales_data(sales_path)
        logger.info(f"✅ 銷貨資料載入完成")

        # 單價資料（選填）
        price_data = None
        price_filename = session.get('price_filename')
        if price_filename:
            price_path = get_safe_filepath(price_filename)
            if price_path:
                try:
                    price_data_obj = load_price_data(price_path)
                    price_data = price_data_obj.price_map
                    logger.info(f"✅ 單價資料載入完成")
                except Exception as e:
                    logger.warning(f"⚠️  載入單價資料失敗：{e}")
        else:
            logger.info(f"ℹ️  未提供單價資料，將使用數量進行 ABC 分類")

        # 庫存計劃（選填）
        plan_data = None
        plan_filename = session.get('plan_filename')
        if plan_filename:
            plan_path = get_safe_filepath(plan_filename)
            if plan_path:
                try:
                    plan_data = load_plan_data(plan_path)
                    logger.info(f"✅ 庫存計劃載入完成")
                except Exception as e:
                    logger.warning(f"⚠️  載入計劃資料失敗：{e}")

        # ========================================
        # 執行計算
        # ========================================
        calculator = SafetyStockCalculator()

        if calc_mode == 'compare':
            logger.info(f"📊 執行對比模式計算")

            comparison_data = calculate_comparison_mode(
                calculator, sales_data, price_data, plan_data,
                selected_months, min_months, lead_time,
                enable_outlier, enable_ma, ma_window,
                z_scores, abc_thresholds  # ✅ v4.3.4 新增參數
            )

            session['calculation_results'] = pickle.dumps(comparison_data['all'][0])
            session['calculation_summary'] = pickle.dumps(comparison_data['all'][2])
            session['calculation_results_total'] = pickle.dumps(comparison_data['total'][0])
            session['calculation_summary_total'] = pickle.dumps(comparison_data['total'][2])
            session['comparison_data'] = comparison_data['comparison']
            session['sales_data'] = pickle.dumps(sales_data)
            session['calc_mode'] = calc_mode

            logger.info(f"✅ 對比模式計算完成")
            logger.info(f"   分倉數據: {len(comparison_data['all'][0])} 筆")
            logger.info(f"   總倉數據: {len(comparison_data['total'][0])} 筆")

            all_serialized = serialize_results_for_json(*comparison_data['all'])
            total_serialized = serialize_results_for_json(*comparison_data['total'])

            response_data = {
                'success': True,
                'mode': 'compare',
                'comparison': comparison_data['comparison'],
                'all_data': all_serialized,
                'total_data': total_serialized,
                'all_summary': all_serialized,
                'total_summary': total_serialized
            }

            logger.info(f"📤 返回對比模式數據")
            return jsonify(response_data)

        else:
            logger.info(f"📦 執行單一模式計算：{calc_mode}")

            results, excluded, summary = calculator.calculate(
                sales_data=sales_data,
                price_data=price_data,
                plan_data=plan_data,
                calc_mode=calc_mode,
                selected_months=selected_months,
                min_months=min_months,
                lead_time_days=lead_time,
                enable_outlier_detection=enable_outlier,
                enable_moving_average=enable_ma,
                ma_window=ma_window,
                z_scores=z_scores,  # ✅ v4.3.4 新增
                abc_thresholds=abc_thresholds,  # ✅ v4.3.4 新增
            )

            session['calculation_results'] = pickle.dumps(results)
            session['calculation_summary'] = pickle.dumps(summary)
            session['sales_data'] = pickle.dumps(sales_data)
            session['calc_mode'] = calc_mode

            logger.info(f"✅ 單一模式計算完成")
            logger.info(f"   有效 SKU: {len(results)} 筆")
            logger.info(f"   排除 SKU: {len(excluded)} 筆")

            response_data = {
                'success': True,
                'mode': calc_mode,
                **serialize_results_for_json(results, excluded, summary)
            }

            logger.info(f"📤 返回單一模式數據")
            return jsonify(response_data)

    except Exception as e:
        logger.error(f"❌ 計算失敗：{e}", exc_info=True)

        response = {'success': False, 'error': '計算失敗'}
        if DEBUG_MODE:
            response['detail'] = str(e)
            response['traceback'] = traceback.format_exc()

        return jsonify(response), 500


# ============================================================================
# 路由：API - 移動平均詳情
# ============================================================================

@app.route('/api/ma-detail/<site>/<sku>', methods=['GET'])
def get_ma_detail(site, sku):
    """取得移動平均詳情"""
    try:
        if not MODULES_AVAILABLE:
            return jsonify({'success': False, 'error': '核心模組未載入'}), 500

        if 'calculation_results' not in session or session['calculation_results'] is None:
            return jsonify({'success': False, 'error': '請先執行計算'}), 400

        logger.info(f"📊 取得 MA 詳情：{site} / {sku}")

        results = pickle.loads(session['calculation_results'])
        sales_data = pickle.loads(session['sales_data'])
        summary = pickle.loads(session['calculation_summary'])

        detail = get_ma_detail_for_sku(
            results, site, sku, sales_data,
            ma_window=summary.ma_window if hasattr(summary, 'ma_window') else 3
        )

        if detail is None:
            logger.warning(f"⚠️  找不到 SKU：{site} / {sku}")
            return jsonify({'success': False, 'error': 'SKU 不存在'}), 404

        logger.info(f"✅ MA 詳情取得成功")
        return jsonify({
            'success': True,
            **detail
        })

    except Exception as e:
        logger.error(f"❌ 取得 MA 詳情失敗：{e}", exc_info=True)

        response = {'success': False, 'error': '取得詳情失敗'}
        if DEBUG_MODE:
            response['detail'] = str(e)
            response['traceback'] = traceback.format_exc()

        return jsonify(response), 500


# ============================================================================
# 路由：API - 匯出（v4.3.3 修復版）
# ============================================================================

@app.route('/api/export/excel', methods=['POST'])
def export_excel_api():
    """
    匯出 Excel（v4.3.3 - 支援出貨點篩選）

    請求參數（JSON）：
    {
        "site_filter": "SITE01" | null  # 出貨點篩選（可選）
    }
    """
    try:
        if not MODULES_AVAILABLE:
            return jsonify({'success': False, 'error': '核心模組未載入'}), 500

        if 'calculation_results' not in session or session['calculation_results'] is None:
            return jsonify({'success': False, 'error': '請先執行計算'}), 400

        # ✅ 取得參數
        data = request.get_json() or {}
        site_filter = data.get('site_filter', None)

        logger.info(f"📥 開始匯出 Excel")
        logger.info(f"   出貨點篩選: {site_filter or '無（全部）'}")

        calc_mode = session.get('calc_mode', 'all')
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # ========================================
        # 對比模式匯出
        # ========================================
        if calc_mode == 'compare':
            try:
                results_all = pickle.loads(session.get('calculation_results'))
                summary_all = pickle.loads(session.get('calculation_summary'))
                results_total = pickle.loads(session.get('calculation_results_total'))
                summary_total = pickle.loads(session.get('calculation_summary_total'))
                comparison = session.get('comparison_data', {})

                # ✅ 出貨點篩選（僅對分倉數據）
                if site_filter:
                    results_all = filter_results_by_site(results_all, site_filter)

                    if len(results_all) == 0:
                        return jsonify({
                            'success': False,
                            'error': f'出貨點 {site_filter} 沒有資料'
                        }), 400

                logger.info(f"📊 對比模式匯出")
                logger.info(f"   分倉數據: {len(results_all)} 筆")
                logger.info(f"   總倉數據: {len(results_total)} 筆")

                excel_bytes = export_comparison_to_excel(
                    all_data=(results_all, [], summary_all),
                    total_data=(results_total, [], summary_total),
                    comparison=comparison
                )

                # ✅ 檔名包含出貨點資訊
                site_suffix = f"_{site_filter}" if site_filter else ""
                filename = f"safety_stock_compare{site_suffix}_{timestamp}.xlsx"

                logger.info(f"✅ 對比模式 Excel 匯出成功：{filename}")

            except Exception as e:
                logger.error(f"❌ 對比模式匯出失敗：{e}", exc_info=True)
                results = pickle.loads(session['calculation_results'])
                summary = pickle.loads(session['calculation_summary'])

                # 降級也要篩選
                if site_filter:
                    results = filter_results_by_site(results, site_filter)

                excel_bytes = export_to_excel(results, [], summary)
                site_suffix = f"_{site_filter}" if site_filter else ""
                filename = f"safety_stock_all{site_suffix}_{timestamp}.xlsx"
                logger.warning(f"⚠️  降級到普通匯出：{filename}")

        # ========================================
        # 非對比模式匯出
        # ========================================
        else:
            results = pickle.loads(session['calculation_results'])
            summary = pickle.loads(session['calculation_summary'])

            # ✅ 出貨點篩選
            if site_filter:
                results = filter_results_by_site(results, site_filter)

                if len(results) == 0:
                    return jsonify({
                        'success': False,
                        'error': f'出貨點 {site_filter} 沒有資料'
                    }), 400

            excel_bytes = export_to_excel(results, [], summary)

            # ✅ 檔名包含出貨點資訊
            site_suffix = f"_{site_filter}" if site_filter else ""
            filename = f"safety_stock_{calc_mode}{site_suffix}_{timestamp}.xlsx"

            logger.info(f"✅ Excel 匯出成功：{filename} ({len(results)} 筆)")

        # 使用 BytesIO
        excel_io = io.BytesIO(excel_bytes)
        excel_io.seek(0)

        return send_file(
            excel_io,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        logger.error(f"❌ 匯出 Excel 失敗：{e}", exc_info=True)
        response = {'success': False, 'error': '匯出失敗'}
        if DEBUG_MODE:
            response['detail'] = str(e)
            response['traceback'] = traceback.format_exc()
        return jsonify(response), 500


@app.route('/api/export/sap', methods=['POST'])
def export_sap():
    """
    匯出 SAP MM17 格式（v4.3.3 - 支援出貨點篩選）

    請求參數（JSON）：
    {
        "format": "xlsx" | "csv",       # 檔案格式（必填）
        "mode": "all" | "total",        # 對比模式時選擇（可選）
        "site_filter": "SITE01" | null, # 出貨點篩選（可選）
        "include_header": true          # 是否包含檔頭（可選，默認 true）
    }
    """
    try:
        if not MODULES_AVAILABLE:
            return jsonify({'success': False, 'error': '核心模組未載入'}), 500

        if 'calculation_results' not in session or session['calculation_results'] is None:
            return jsonify({'success': False, 'error': '請先執行計算'}), 400

        # ✅ 取得參數
        data = request.get_json() or {}
        export_format = data.get('format', 'xlsx')
        sap_mode = data.get('mode', None)
        site_filter = data.get('site_filter', None)
        include_header = data.get('include_header', True)

        # 驗證格式
        if export_format not in ['xlsx', 'csv']:
            return jsonify({'success': False, 'error': '格式必須是 xlsx 或 csv'}), 400

        logger.info(f"📁 開始匯出 SAP MM17")
        logger.info(f"   格式: {export_format}")
        logger.info(f"   模式: {sap_mode or '自動'}")
        logger.info(f"   出貨點篩選: {site_filter or '無（全部）'}")

        calc_mode = session.get('calc_mode', 'all')
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # ========================================
        # 決定匯出哪個結果
        # ========================================
        if calc_mode == 'compare':
            if sap_mode == 'total':
                results = pickle.loads(session.get('calculation_results_total'))
                summary = pickle.loads(session.get('calculation_summary_total'))
                mode_suffix = 'total'
                logger.info(f"   對比模式：匯出總倉結果")
            else:
                results = pickle.loads(session.get('calculation_results'))
                summary = pickle.loads(session.get('calculation_summary'))
                mode_suffix = 'all'
                logger.info(f"   對比模式：匯出分倉結果")
        else:
            results = pickle.loads(session['calculation_results'])
            summary = pickle.loads(session['calculation_summary'])
            mode_suffix = calc_mode

        # ========================================
        # ✅ 出貨點篩選
        # ========================================
        if site_filter:
            results = filter_results_by_site(results, site_filter)

            if len(results) == 0:
                return jsonify({
                    'success': False,
                    'error': f'出貨點 {site_filter} 沒有資料'
                }), 400

        # ========================================
        # 生成 SAP MM17 文件
        # ========================================
        sap_bytes = export_to_sap_mm17(
            results=results,
            summary=summary,
            format=export_format,
            include_header=include_header
        )

        # ✅ 檔名包含出貨點資訊
        site_suffix = f"_{site_filter}" if site_filter else ""
        filename = f"sap_mm17_{mode_suffix}{site_suffix}_{timestamp}.{export_format}"

        # MIME 類型
        mime_types = {
            'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'csv': 'text/csv; charset=utf-8'
        }

        # 使用 BytesIO
        sap_io = io.BytesIO(sap_bytes)
        sap_io.seek(0)

        logger.info(f"✅ SAP MM17 匯出成功：{filename}")
        logger.info(f"   共 {len(results)} 筆數據")

        return send_file(
            sap_io,
            mimetype=mime_types[export_format],
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        logger.error(f"❌ 匯出 SAP MM17 失敗：{e}", exc_info=True)
        response = {'success': False, 'error': 'SAP MM17 匯出失敗'}
        if DEBUG_MODE:
            response['detail'] = str(e)
            response['traceback'] = traceback.format_exc()
        return jsonify(response), 500


# ============================================================================
# 錯誤處理
# ============================================================================

@app.errorhandler(404)
def not_found(error):
    """404 錯誤"""
    path = request.path

    ignore_paths = [
        "/favicon.ico",
        "/.well-known/appspecific/com.chrome.devtools.json"
    ]

    if path in ignore_paths:
        return "", 404

    logger.warning(f"⚠️  404 錯誤：{request.url}")
    return jsonify({'success': False, 'error': '找不到資源'}), 404


@app.errorhandler(500)
def internal_error(error):
    """500 錯誤"""
    logger.error(f"❌ 500 內部錯誤：{error}", exc_info=True)

    response = {'success': False, 'error': '伺服器內部錯誤'}
    if DEBUG_MODE:
        response['detail'] = str(error)

    return jsonify(response), 500


@app.errorhandler(413)
def request_entity_too_large(error):
    """檔案過大錯誤"""
    max_mb = app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)
    logger.warning(f"⚠️  413 檔案過大：超過 {max_mb} MB")
    return jsonify({
        'success': False,
        'error': f'檔案過大，最大允許 {max_mb} MB'
    }), 413


# ============================================================================
# 啟動設定
# ============================================================================

if __name__ == '__main__':
    import os

    port = int(os.environ.get('PORT', 5000))

    # 本地開發環境
    if os.environ.get('FLASK_ENV') != 'production':
        print("=" * 60)
        print("🚀 開發模式 v4.3.4")
        print("=" * 60)
        app.run(debug=True, port=port, host='0.0.0.0')
    else:
        # 生產環境（Render）
        print("=" * 60)
        print("🚀 生產環境 v4.3.4")
        print("=" * 60)
        app.run(debug=False, port=port, host='0.0.0.0')