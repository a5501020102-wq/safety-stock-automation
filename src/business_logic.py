"""
業務邏輯層 - Business Logic Layer
從 Streamlit 提取的核心計算邏輯，供 Flask 和 Streamlit 共用

Version: 4.3.4 (z_scores & abc_thresholds Support)
Author: 松鼠
Last Updated: 2026-01-29

🔧 v4.3.4 功能增強：
- ✅ calculate_comparison_mode() 支援 z_scores 和 abc_thresholds 參數
- ✅ 參數驗證和預設值處理
- ✅ 向後兼容（沒有參數時使用預設值）
- ✅ 增強日誌輸出
- ✅ 優化錯誤處理

更新 v4.3.1：
- ✅ 添加 SAP MM17 匯出功能（XLSX 和 CSV）
- ✅ 添加對比模式完整 Excel 匯出
- ✅ 優化代碼結構和錯誤處理
- ✅ 增強日誌輸出

重點修復 v4.2.3：
- 🔴 修復 CV 欄位映射錯誤：coefficient_of_variation → cv
- 🟡 修復 reorder_point 和 max_inventory：先讀取後端，沒有才計算
- 🟡 添加 import math 支援
- 🟢 優化重複的安全轉換
- 🟢 添加調試日誌
"""

from __future__ import annotations

from typing import Optional, Dict, List, Tuple, Any, Union
from datetime import datetime
from io import BytesIO
import logging
import math
import pandas as pd

logger = logging.getLogger(__name__)

# ============================================================================
# 導入模型（允許 fallback）
# ============================================================================

try:
    from src.calculator import SafetyStockCalculator
    from src.models import CalculationResult, ExcludedItem, CalculationSummary
except ImportError:
    try:
        from calculator import SafetyStockCalculator
        from models import CalculationResult, ExcludedItem, CalculationSummary
    except ImportError as e:
        logger.warning(f"無法導入模型（將使用 Any fallback）：{e}")
        SafetyStockCalculator = Any
        CalculationResult = Any
        ExcludedItem = Any
        CalculationSummary = Any


# ============================================================================
# 小工具：安全取值/格式化
# ============================================================================

def _safe_float(v: Any, default: float = 0.0) -> float:
    """安全轉換為浮點數"""
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default


def _safe_int(v: Any, default: int = 0) -> int:
    """安全轉換為整數"""
    try:
        if v is None or v == "":
            return default
        return int(v)
    except Exception:
        return default


def _round(v: Any, ndigits: int = 2, default: float = 0.0) -> float:
    """安全四捨五入"""
    return round(_safe_float(v, default=default), ndigits)


def _get_enum_value(v: Any) -> Any:
    """
    支援 Enum 或 str。
    Enum -> .value
    其他 -> 原樣
    """
    try:
        return v.value
    except Exception:
        return v


def _calc_cv(std_dev: Any, mean_demand: Any) -> float:
    """
    計算變異係數（Coefficient of Variation）
    CV = σ / μ
    """
    s = _safe_float(std_dev, 0)
    m = _safe_float(mean_demand, 0)
    if m <= 0:
        return 0.0
    return s / m


def _resolve_cv(r: Any) -> float:
    """
    Resolve CV from a CalculationResult using the canonical priority:
    coefficient_of_variation → cv attr → manual σ/μ calculation.
    """
    cv = getattr(r, "coefficient_of_variation", None)
    if cv is None:
        cv = getattr(r, "cv", None)
    if cv is None:
        std_dev = _safe_float(getattr(r, "std_dev", 0), 0)
        mean_demand = _safe_float(getattr(r, "mean_demand", 0), 0)
        cv = _calc_cv(std_dev, mean_demand)
    return _safe_float(cv, 0.0)


# ============================================================================
# 對比模式計算（v4.3.4 增強版）
# ============================================================================

def calculate_comparison_mode(
        calculator: SafetyStockCalculator,
        sales_data: Any,
        price_data: Optional[Dict[str, float]] = None,
        plan_data: Optional[Any] = None,
        selected_months: Optional[List[int]] = None,
        min_months: int = 2,
        lead_time: int = 30,
        enable_outlier: bool = True,
        enable_ma: bool = False,
        ma_window: int = 3,
        z_scores: Optional[Dict[str, float]] = None,          # ✅ v4.3.4 新增
        abc_thresholds: Optional[Dict[str, float]] = None     # ✅ v4.3.4 新增
) -> Dict[str, Any]:
    """
    對比模式：同時計算分倉(all)與總倉(total)

    Args:
        calculator: 計算引擎實例
        sales_data: 銷貨資料
        price_data: 單價資料（可選）
        plan_data: 庫存計劃（可選）
        selected_months: 選擇的月份
        min_months: 最少月數
        lead_time: 前置期（天）
        enable_outlier: 啟用離群值檢測
        enable_ma: 啟用移動平均
        ma_window: 移動平均窗口
        z_scores: 服務水準設定（可選）✅ v4.3.4
        abc_thresholds: ABC 分類門檻（可選）✅ v4.3.4

    Returns:
        {
            "all": (results, excluded, summary),
            "total": (results, excluded, summary),
            "comparison": {各種對比指標}
        }
    """
    # ========================================
    # ✅ v4.3.4: 參數預設值處理
    # ========================================
    if z_scores is None:
        z_scores = {"A": 2.05, "B": 1.65, "C": 1.28}
        logger.debug("z_scores 未提供，使用預設值")
    else:
        logger.debug(f"z_scores 已提供: {z_scores}")

    if abc_thresholds is None:
        abc_thresholds = {"A": 0.80, "B": 0.95}
        logger.debug("abc_thresholds 未提供，使用預設值")
    else:
        logger.debug(f"abc_thresholds 已提供: {abc_thresholds}")

    # ========================================
    # 參數驗證
    # ========================================
    if selected_months is None:
        selected_months = list(range(1, 13))

    if not isinstance(selected_months, list):
        raise TypeError("selected_months 必須是列表")

    if not all(isinstance(m, int) and 1 <= m <= 12 for m in selected_months):
        raise ValueError("selected_months 必須包含 1-12 的月份（int）")

    # ========================================
    # 執行計算
    # ========================================
    logger.info(f"📊 對比模式計算開始")
    logger.info(f"   服務水準: A={z_scores['A']:.2f}, B={z_scores['B']:.2f}, C={z_scores['C']:.2f}")
    logger.info(f"   ABC門檻: A={abc_thresholds['A']:.0%}, B={abc_thresholds['B']:.0%}")

    try:
        # ========================================
        # 分倉模式
        # ========================================
        logger.info(f"   → 計算分倉模式...")
        results_all, excluded_all, summary_all = calculator.calculate(
            sales_data=sales_data,
            price_data=price_data,
            plan_data=plan_data,
            calc_mode='all',
            selected_months=selected_months,
            min_months=min_months,
            lead_time_days=lead_time,
            enable_outlier_detection=enable_outlier,
            enable_moving_average=enable_ma,
            ma_window=ma_window,
            z_scores=z_scores,              # ✅ v4.3.4 傳遞
            abc_thresholds=abc_thresholds,  # ✅ v4.3.4 傳遞
        )
        logger.info(f"   ✅ 分倉計算完成: {len(results_all)} 筆")

        # ========================================
        # 總倉模式
        # ========================================
        logger.info(f"   → 計算總倉模式...")
        results_total, excluded_total, summary_total = calculator.calculate(
            sales_data=sales_data,
            price_data=price_data,
            plan_data=plan_data,
            calc_mode='total',
            selected_months=selected_months,
            min_months=min_months,
            lead_time_days=lead_time,
            enable_outlier_detection=enable_outlier,
            enable_moving_average=enable_ma,
            ma_window=ma_window,
            z_scores=z_scores,              # ✅ v4.3.4 傳遞
            abc_thresholds=abc_thresholds,  # ✅ v4.3.4 傳遞
        )
        logger.info(f"   ✅ 總倉計算完成: {len(results_total)} 筆")

    except Exception as e:
        logger.exception(f"❌ 計算過程發生錯誤：{e}")
        raise ValueError(f"計算失敗：{str(e)}") from e

    # ========================================
    # 對比分析（安全計算）
    # ========================================
    logger.info(f"   → 生成對比分析...")

    total_ss_all = sum(_safe_float(getattr(r, "safety_stock", 0), 0) for r in (results_all or []))
    total_ss_total = sum(_safe_float(getattr(r, "safety_stock", 0), 0) for r in (results_total or []))

    total_value_all = sum(_safe_float(getattr(r, "safety_stock_value", 0), 0) for r in (results_all or []))
    total_value_total = sum(_safe_float(getattr(r, "safety_stock_value", 0), 0) for r in (results_total or []))

    inventory_saved = total_ss_all - total_ss_total
    cost_saved = total_value_all - total_value_total

    savings_pct = 0.0
    if total_ss_all > 0:
        savings_pct = (inventory_saved / total_ss_all) * 100

    savings_value_pct = 0.0
    if total_value_all > 0:
        savings_value_pct = (cost_saved / total_value_all) * 100

    logger.info(f"   ✅ 對比分析完成")
    logger.info(f"      節省數量: {int(inventory_saved)} ({savings_pct:.2f}%)")
    logger.info(f"      節省金額: ${cost_saved:.2f} ({savings_value_pct:.2f}%)")

    # ✅ 同時輸出兩套 key（避免前端字段不一致）
    comparison = {
        # --- 前端 comparison.js 常用（英文字段風格）---
        "total_all_safety_stock": int(total_ss_all),
        "total_total_safety_stock": int(total_ss_total),
        "inventory_saved": int(inventory_saved),
        "savings_percentage": round(savings_pct, 2),

        "total_all_value": round(total_value_all, 2),
        "total_total_value": round(total_value_total, 2),
        "cost_saved": round(cost_saved, 2),
        "savings_value_percentage": round(savings_value_pct, 2),

        "all_sku_count": len(results_all or []),
        "total_sku_count": len(results_total or []),

        # --- 中文 key（保留相容）---
        "分倉_總安全庫存": int(total_ss_all),
        "總倉_總安全庫存": int(total_ss_total),
        "節省數量": int(inventory_saved),
        "節省比例": round(savings_pct, 2),
        "分倉_總價值": round(total_value_all, 2),
        "總倉_總價值": round(total_value_total, 2),
        "節省價值": round(cost_saved, 2),
        "節省價值比例": round(savings_value_pct, 2),
        "分倉_SKU數": len(results_all or []),
        "總倉_SKU數": len(results_total or []),
    }

    return {
        "all": (results_all, excluded_all, summary_all),
        "total": (results_total, excluded_total, summary_total),
        "comparison": comparison,
    }


# ============================================================================
# 移動平均詳情
# ============================================================================

def get_ma_detail_for_sku(
        results: List[Any],
        site: str,
        sku: str,
        sales_data: Any,
        ma_window: int = 3
) -> Optional[Dict[str, Any]]:
    """
    取得單一 SKU 的移動平均分析詳情

    Args:
        results: 計算結果列表
        site: 出貨點
        sku: 料號
        sales_data: 銷售資料（需有 .df 屬性）
        ma_window: 移動平均窗口

    Returns:
        移動平均詳情字典，若找不到則返回 None
    """
    # 導入工具函數
    try:
        from src.utils import group_by_quarter, parse_year_month, get_quarter
    except ImportError:
        logger.warning("無法從 src.utils 導入，使用本地函數")

        def parse_year_month(ym: str) -> Tuple[int, int]:
            try:
                year, month = ym.split("-")
                return int(year), int(month)
            except Exception:
                return 0, 0

        def get_quarter(month: int) -> str:
            if 1 <= month <= 3:
                return "Q1"
            elif 4 <= month <= 6:
                return "Q2"
            elif 7 <= month <= 9:
                return "Q3"
            return "Q4"

        def group_by_quarter(monthly_data: Dict[str, float]) -> Dict[str, List[Tuple[str, float]]]:
            quarters: Dict[str, List[Tuple[str, float]]] = {}
            for ym, value in sorted(monthly_data.items()):
                year, month = parse_year_month(ym)
                if year == 0:
                    continue
                quarter = get_quarter(month)
                key = f"{quarter} {year}"
                quarters.setdefault(key, []).append((ym, value))
            return quarters

    if not results:
        logger.warning("結果列表為空")
        return None

    if not hasattr(sales_data, "df"):
        raise AttributeError("sales_data 必須有 .df 屬性")

    # 注意：results 可能是 all 模式（含 site）或 total 模式（不含 site）
    target_result = next((r for r in results if getattr(r, "site", None) == site and getattr(r, "sku", None) == sku),
                         None)
    if not target_result:
        logger.info(f"找不到 SKU: {site}-{sku}")
        return None

    df = sales_data.df

    try:
        df_sku = df[(df["site"] == site) & (df["sku"] == sku)].copy()
    except Exception as e:
        logger.error(f"DataFrame 過濾失敗：{e}")
        return None

    if df_sku.empty:
        return None

    try:
        monthly_demand = df_sku.groupby("year_month")["quantity"].sum().to_dict()
    except Exception as e:
        logger.error(f"彙總月度需求失敗：{e}")
        return None

    if not monthly_demand:
        return None

    quarterly_summary: Dict[str, Dict[str, Any]] = {}
    quarterly_data = group_by_quarter(monthly_demand)

    for quarter, months in sorted(quarterly_data.items()):
        month_values = [v for _, v in months]
        quarterly_summary[quarter] = {
            "months": [ym for ym, _ in months],
            "values": month_values,
            "avg": round(sum(month_values) / len(month_values), 2) if month_values else 0,
            "total": sum(month_values),
            "count": len(month_values),
        }

    filled_months = _find_filled_months(monthly_demand, parse_year_month)

    # 統計資訊
    mean_demand = getattr(target_result, "mean_demand", None)
    std_dev = getattr(target_result, "std_dev", None)

    statistics_data = {
        "std_original": _round(std_dev, 2, 0.0),
        "mean": _round(mean_demand, 2, 0.0),
        "total_qty": _safe_float(getattr(target_result, "total_qty", 0), 0),
        "active_months": _safe_int(getattr(target_result, "active_months", 0), 0),
        "outliers_removed": _safe_int(getattr(target_result, "outliers_removed", 0), 0),
    }

    recommendation = _generate_recommendation(target_result)

    return {
        "site": site,
        "sku": sku,
        "name": getattr(target_result, "name", ""),
        "abc_class": _get_enum_value(getattr(target_result, "abc_class", "")),
        "monthly_data": monthly_demand,
        "quarterly_summary": quarterly_summary,
        "filled_months": filled_months,
        "statistics": statistics_data,
        "recommendation": recommendation,
        "ma_window": ma_window,
    }


def _find_filled_months(monthly_demand: Dict[str, float], parse_year_month) -> List[str]:
    """找出需要填補的月份（連續月份中缺失的）"""
    sorted_months = sorted(monthly_demand.keys())
    if not sorted_months:
        return []

    start_ym = sorted_months[0]
    end_ym = sorted_months[-1]

    start_year, start_month = parse_year_month(start_ym)
    end_year, end_month = parse_year_month(end_ym)

    if start_year == 0 or end_year == 0:
        return []

    all_months: List[str] = []
    current_year, current_month = start_year, start_month

    max_iterations = 365
    iterations = 0

    while (current_year < end_year) or (current_year == end_year and current_month <= end_month):
        all_months.append(f"{current_year}-{current_month:02d}")

        current_month += 1
        if current_month > 12:
            current_month = 1
            current_year += 1

        iterations += 1
        if iterations > max_iterations:
            logger.warning("月份生成超過最大迭代次數，疑似資料異常")
            break

    return [m for m in all_months if m not in monthly_demand]


def _generate_recommendation(result: Any) -> Dict[str, str]:
    """根據 CV 值生成移動平均建議"""
    std_dev = _safe_float(getattr(result, "std_dev", 0), 0)
    mean_demand = _safe_float(getattr(result, "mean_demand", 0), 0)

    if std_dev <= 0:
        return {"icon": "ℹ️", "text": "標準差為 0，無需移動平均", "level": "info"}

    cv = _calc_cv(std_dev, mean_demand)

    if cv > 0.5:
        return {"icon": "💡", "text": f"需求波動較大（CV={cv:.2f}），建議啟用移動平均平滑", "level": "warning"}
    elif cv > 0.3:
        return {"icon": "📊", "text": f"需求波動中等（CV={cv:.2f}），移動平均可能有幫助", "level": "info"}
    else:
        return {"icon": "✅", "text": f"需求相對穩定（CV={cv:.2f}），移動平均效果有限", "level": "success"}


# ============================================================================
# Excel 匯出功能
# ============================================================================

def export_to_excel(results: List[Any], excluded: List[Any], summary: Any) -> bytes:
    """
    匯出計算結果為 Excel 檔案

    Args:
        results: 計算結果列表
        excluded: 排除項目列表
        summary: 計算摘要

    Returns:
        Excel 檔案的二進位內容
    """
    output = BytesIO()

    try:
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            if results:
                _write_results_sheet(writer, results)
            if excluded:
                _write_excluded_sheet(writer, excluded)
            if summary:
                _write_summary_sheet(writer, summary)

        output.seek(0)
        return output.read()

    except ImportError:
        raise ImportError("請安裝 xlsxwriter: pip install xlsxwriter")
    except Exception as e:
        logger.exception(f"Excel 匯出失敗：{e}")
        raise ValueError(f"無法匯出 Excel：{str(e)}") from e


def _result_to_row(r: Any) -> Dict[str, Any]:
    """將單一 CalculationResult 轉為 Excel / 匯出用的 dict（共用邏輯）"""
    mean_demand = _safe_float(getattr(r, "mean_demand", 0), 0)
    std_dev = _safe_float(getattr(r, "std_dev", 0), 0)
    cv = _resolve_cv(r)

    return {
        "出貨點": getattr(r, "site", ""),
        "料號": getattr(r, "sku", ""),
        "品名": getattr(r, "name", ""),
        "ABC分類": _get_enum_value(getattr(r, "abc_class", "")),
        "總需求量": _safe_float(getattr(r, "total_qty", 0), 0),
        "總需求金額": _round(getattr(r, "total_value", 0), 2, 0.0),
        "活躍月數": _safe_int(getattr(r, "active_months", 0), 0),
        "月平均需求": _round(mean_demand, 2, 0.0),
        "標準差": _round(std_dev, 2, 0.0),
        "CV": _round(cv, 3, 0.0),
        "安全庫存": _safe_float(getattr(r, "safety_stock", 0), 0),
        "安全庫存金額": _round(getattr(r, "safety_stock_value", 0), 2, 0.0),
        "再訂購點": _safe_float(getattr(r, "reorder_point", 0), 0),
        "最大庫存": _safe_float(getattr(r, "max_inventory", 0), 0),
        "前置期(天)": _safe_int(getattr(r, "lead_time_days", 0), 0),
        "現有庫存": getattr(r, "current_stock", ""),
        "庫存狀態": _get_enum_value(getattr(r, "status", "")),
        "離群值數量": _safe_int(getattr(r, "outliers_removed", 0), 0),
        "單價": _safe_float(getattr(r, "price", 0), 0),
    }


def _write_results_sheet(writer, results: List[Any], sheet_name: str = "計算結果") -> None:
    """寫入計算結果工作表（支援自訂工作表名稱）"""
    rows = [_result_to_row(r) for r in results]
    pd.DataFrame(rows).to_excel(writer, sheet_name=sheet_name, index=False)


def _write_excluded_sheet(writer, excluded: List[Any]) -> None:
    """寫入排除項目工作表"""
    rows = []
    for e in excluded:
        rows.append({
            "出貨點": getattr(e, "site", ""),
            "料號": getattr(e, "sku", ""),
            "品名": getattr(e, "name", ""),
            "活躍月數": _safe_int(getattr(e, "active_months", 0), 0),
            "總需求量": _safe_float(getattr(e, "total_qty", 0), 0),
            "排除原因": getattr(e, "reason", ""),
        })

    pd.DataFrame(rows).to_excel(writer, sheet_name="排除項目", index=False)


def _write_summary_sheet(writer, summary: Any) -> None:
    """寫入計算摘要工作表"""
    run_date = getattr(summary, "run_date", None)
    if hasattr(run_date, "strftime"):
        run_date_str = run_date.strftime("%Y-%m-%d %H:%M:%S")
    else:
        run_date_str = ""

    data = {
        "項目": [
            "執行時間",
            "總 SKU 數",
            "排除項目",
            "移除離群值",
            "缺貨風險",
            "健康庫存",
            "超量風險",
            "無資料",
            "前置期（天）",
            "最少月數",
            "移動平均",
            "MA 窗口",
        ],
        "數值": [
            run_date_str,
            _safe_int(getattr(summary, "total_skus", 0), 0),
            _safe_int(getattr(summary, "excluded_count", 0), 0),
            _safe_int(getattr(summary, "total_outliers_removed", 0), 0),
            _safe_int(getattr(summary, "shortage_risk_count", 0), 0),
            _safe_int(getattr(summary, "healthy_count", 0), 0),
            _safe_int(getattr(summary, "overstock_risk_count", 0), 0),
            _safe_int(getattr(summary, "no_data_count", 0), 0),
            _safe_int(getattr(summary, "lead_time_days", 0), 0),
            _safe_int(getattr(summary, "min_months", 0), 0),
            "啟用" if bool(getattr(summary, "moving_average_enabled", False)) else "關閉",
            getattr(summary, "ma_window", None) if getattr(summary, "ma_window", None) is not None else "N/A",
        ],
    }

    pd.DataFrame(data).to_excel(writer, sheet_name="計算摘要", index=False)


# ============================================================================
# SAP MM17 匯出功能（v4.3.1 新增）
# ============================================================================

def export_to_sap_mm17(
        results: List[Any],
        summary: Any,
        format: str = 'xlsx',
        include_header: bool = True
) -> bytes:
    """
    匯出為 SAP MM17 格式

    SAP MM17 格式規格：
    - MATNR: 料號（物料編號）
    - WERKS: 工廠/出貨點
    - EISBE: 安全庫存（整數）

    Args:
        results: 計算結果列表
        summary: 計算摘要（用於判斷模式）
        format: 'xlsx' 或 'csv'
        include_header: 是否包含檔頭

    Returns:
        檔案的二進位內容
    """
    if not results:
        raise ValueError("無計算結果可匯出")

    logger.info(f"📁 開始準備 SAP MM17 數據，格式: {format}")

    # 準備 SAP MM17 數據
    sap_data = []

    for r in results:
        matnr = str(getattr(r, "sku", "")).strip()
        werks = str(getattr(r, "site", "")).strip()

        # 安全庫存：四捨五入為整數
        safety_stock = getattr(r, "safety_stock", 0)
        eisbe = int(round(_safe_float(safety_stock, 0)))

        # 跳過無效數據
        if not matnr:
            logger.warning(f"⚠️  跳過無料號的數據：site={werks}")
            continue

        sap_data.append({
            "MATNR": matnr,
            "WERKS": werks,
            "EISBE": eisbe
        })

    if not sap_data:
        raise ValueError("無有效數據可匯出至 SAP MM17")

    logger.info(f"✅ 準備完成：{len(sap_data)} 筆 SAP MM17 數據")

    # 創建 DataFrame
    df = pd.DataFrame(sap_data)

    # 確保欄位順序
    df = df[["MATNR", "WERKS", "EISBE"]]

    if format == 'csv':
        # CSV 格式
        output = BytesIO()
        df.to_csv(
            output,
            index=False,
            header=include_header,
            encoding='utf-8-sig'  # 支援中文（如果有）
        )
        output.seek(0)
        logger.info(f"✅ CSV 匯出成功")
        return output.read()

    elif format == 'xlsx':
        # Excel 格式
        output = BytesIO()

        try:
            with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                df.to_excel(
                    writer,
                    sheet_name="SAP_MM17",
                    index=False,
                    header=include_header
                )

                # 格式化工作表
                workbook = writer.book
                worksheet = writer.sheets['SAP_MM17']

                # 設定欄寬
                worksheet.set_column('A:A', 18)  # MATNR
                worksheet.set_column('B:B', 12)  # WERKS
                worksheet.set_column('C:C', 12)  # EISBE

                # 檔頭格式
                if include_header:
                    header_format = workbook.add_format({
                        'bold': True,
                        'bg_color': '#4472C4',
                        'font_color': 'white',
                        'border': 1
                    })

                    for col_num, value in enumerate(df.columns):
                        worksheet.write(0, col_num, value, header_format)

            output.seek(0)
            logger.info(f"✅ XLSX 匯出成功")
            return output.read()

        except ImportError:
            raise ImportError("請安裝 xlsxwriter: pip install xlsxwriter")
    else:
        raise ValueError(f"不支援的格式: {format}")


# ============================================================================
# 對比模式 Excel 匯出（v4.3.1 新增）
# ============================================================================

def export_comparison_to_excel(
        all_data: tuple,
        total_data: tuple,
        comparison: dict
) -> bytes:
    """
    匯出對比模式的完整 Excel 分析

    Args:
        all_data: 分倉計算結果 (results, excluded, summary)
        total_data: 總倉計算結果 (results, excluded, summary)
        comparison: 對比統計數據

    Returns:
        Excel 檔案的二進位內容
    """
    output = BytesIO()

    results_all, excluded_all, summary_all = all_data
    results_total, excluded_total, summary_total = total_data

    logger.info(f"📊 開始匯出對比模式 Excel")
    logger.info(f"   分倉數據: {len(results_all)} 筆")
    logger.info(f"   總倉數據: {len(results_total)} 筆")

    try:
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            workbook = writer.book

            # ========================================
            # Sheet 1: 對比摘要
            # ========================================
            comparison_data = {
                "項目": [
                    "分倉總安全庫存",
                    "總倉總安全庫存",
                    "庫存差異",
                    "優化潛力 (%)",
                    "分倉總金額",
                    "總倉總金額",
                    "金額差異",
                    "金額優化 (%)",
                    "分倉 SKU 數量",
                    "總倉 SKU 數量"
                ],
                "數值": [
                    _safe_float(comparison.get("total_all_safety_stock", 0), 0),
                    _safe_float(comparison.get("total_total_safety_stock", 0), 0),
                    _safe_float(comparison.get("inventory_saved", 0), 0),
                    _round(comparison.get("savings_percentage", 0), 2, 0),
                    _safe_float(comparison.get("total_all_value", 0), 0),
                    _safe_float(comparison.get("total_total_value", 0), 0),
                    _safe_float(comparison.get("cost_saved", 0), 0),
                    _round(comparison.get("savings_value_percentage", 0), 2, 0),
                    comparison.get("all_sku_count", 0),
                    comparison.get("total_sku_count", 0)
                ]
            }

            pd.DataFrame(comparison_data).to_excel(
                writer,
                sheet_name="對比摘要",
                index=False
            )

            logger.info(f"✅ Sheet 1: 對比摘要 - 完成")

            # ========================================
            # Sheet 2: 分倉計算
            # ========================================
            if results_all:
                _write_results_sheet(writer, results_all, "分倉計算")
                logger.info(f"✅ Sheet 2: 分倉計算 - {len(results_all)} 筆")

            # ========================================
            # Sheet 3: 總倉計算
            # ========================================
            if results_total:
                _write_results_sheet(writer, results_total, "總倉計算")
                logger.info(f"✅ Sheet 3: 總倉計算 - {len(results_total)} 筆")

            # ========================================
            # Sheet 4: 差異分析（重點）
            # ========================================
            diff_rows = []

            # 建立 SKU 映射
            total_map = {}
            for r in results_total:
                sku = getattr(r, "sku", "")
                site = getattr(r, "site", "")
                key = f"{site}_{sku}"
                total_map[key] = r

            for r_all in results_all:
                sku = getattr(r_all, "sku", "")
                site = getattr(r_all, "site", "")
                key = f"{site}_{sku}"

                # 找對應的總倉數據
                r_total = total_map.get(key)
                if not r_total:
                    continue

                ss_all = _safe_float(getattr(r_all, "safety_stock", 0), 0)
                ss_total = _safe_float(getattr(r_total, "safety_stock", 0), 0)

                diff = ss_all - ss_total

                # 計算差異百分比
                diff_pct = 0
                if ss_all > 0:
                    diff_pct = (diff / ss_all) * 100

                # 只顯示差異 > 5% 的項目
                if abs(diff_pct) < 5:
                    continue

                diff_rows.append({
                    "出貨點": site,
                    "料號": sku,
                    "品名": getattr(r_all, "name", ""),
                    "ABC分類": _get_enum_value(getattr(r_all, "abc_class", "")),
                    "分倉安全庫存": int(round(ss_all)),
                    "總倉安全庫存": int(round(ss_total)),
                    "差異數量": int(round(diff)),
                    "差異百分比 (%)": _round(diff_pct, 2, 0),
                    "建議": "總倉" if diff > 0 else "分倉"
                })

            if diff_rows:
                pd.DataFrame(diff_rows).to_excel(
                    writer,
                    sheet_name="差異分析",
                    index=False
                )
                logger.info(f"✅ Sheet 4: 差異分析 - {len(diff_rows)} 筆（差異 > 5%）")
            else:
                logger.info(f"⚠️  Sheet 4: 差異分析 - 無顯著差異項目")

            # ========================================
            # Sheet 5: 排除項目
            # ========================================
            if excluded_all or excluded_total:
                all_excluded = list(excluded_all or []) + list(excluded_total or [])
                _write_excluded_sheet(writer, all_excluded)
                logger.info(f"✅ Sheet 5: 排除項目 - {len(all_excluded)} 筆")

        output.seek(0)
        logger.info(f"🎉 對比模式 Excel 匯出完成")
        return output.read()

    except Exception as e:
        logger.exception(f"❌ 對比模式 Excel 匯出失敗：{e}")
        raise ValueError(f"無法匯出對比分析：{str(e)}") from e


# _write_results_sheet_custom removed — consolidated into _write_results_sheet(sheet_name=...)


# ============================================================================
# JSON 序列化（v4.2.3）
# ============================================================================

def serialize_results_for_json(results: List[Any], excluded: List[Any], summary: Any) -> Dict[str, Any]:
    """
    將計算結果序列化為 JSON 格式

    Args:
        results: 計算結果列表
        excluded: 排除項目列表
        summary: 計算摘要

    Returns:
        包含 summary, results, excluded 的字典
    """
    return {
        "summary": _serialize_summary(summary),
        "results": _serialize_results(results),
        "excluded": _serialize_excluded(excluded),
    }


def _serialize_summary(summary: Any) -> Dict[str, Any]:
    """序列化計算摘要"""
    run_date = getattr(summary, "run_date", None)
    return {
        "run_date": run_date.isoformat() if hasattr(run_date, "isoformat") else None,
        "total_skus": _safe_int(getattr(summary, "total_skus", 0), 0),
        "excluded_count": _safe_int(getattr(summary, "excluded_count", 0), 0),
        "total_outliers_removed": _safe_int(getattr(summary, "total_outliers_removed", 0), 0),
        "shortage_risk_count": _safe_int(getattr(summary, "shortage_risk_count", 0), 0),
        "healthy_count": _safe_int(getattr(summary, "healthy_count", 0), 0),
        "overstock_risk_count": _safe_int(getattr(summary, "overstock_risk_count", 0), 0),
        "no_data_count": _safe_int(getattr(summary, "no_data_count", 0), 0),
        "moving_average_enabled": bool(getattr(summary, "moving_average_enabled", False)),
        "ma_window": getattr(summary, "ma_window", None),
        "lead_time_days": _safe_int(getattr(summary, "lead_time_days", 30), 30),
        "min_months": _safe_int(getattr(summary, "min_months", 2), 2),
        "calc_mode": getattr(summary, "calc_mode", "all"),  # 添加計算模式
    }


def _serialize_results(results: List[Any]) -> List[Dict[str, Any]]:
    """
    ✅ v4.2.3 修復版本：正確讀取後端欄位 + 備用計算

    主要修復：
    1. CV 欄位映射：coefficient_of_variation → cv
    2. reorder_point：先讀取，沒有才計算
    3. max_inventory：先讀取，沒有才計算
    4. 優化重複的安全轉換
    """
    out: List[Dict[str, Any]] = []

    for r in (results or []):
        # === 基礎欄位 ===
        site = getattr(r, "site", None)
        sku = getattr(r, "sku", None)
        name = getattr(r, "name", None)

        abc_class = _get_enum_value(getattr(r, "abc_class", None))
        status = _get_enum_value(getattr(r, "status", None))

        # === 統計數據 ===
        mean_demand = _safe_float(getattr(r, "mean_demand", 0), 0)
        std_dev = _safe_float(getattr(r, "std_dev", 0), 0)
        safety_stock = _safe_float(getattr(r, "safety_stock", 0), 0)

        # ✅ CV resolution via shared helper
        cv = _resolve_cv(r)

        # === 月數 ===
        active_months = _safe_int(getattr(r, "active_months", 0), 0)
        months_count = _safe_int(getattr(r, "months_count", active_months), active_months)

        # === 前置期 ===
        lead_time_days = _safe_int(
            getattr(r, "lead_time_days", None) or getattr(r, "lead_time", 30),
            30
        )

        # 🟡 FIX #2: reorder_point - 先讀取後端計算值，沒有才主動計算
        reorder_point = getattr(r, "reorder_point", None)
        if reorder_point is None or _safe_float(reorder_point, 0) == 0:
            if mean_demand > 0 and lead_time_days > 0:
                daily_demand = mean_demand / 30
                lead_time_demand = daily_demand * lead_time_days
                reorder_point = math.ceil(lead_time_demand + safety_stock)
                logger.debug(f"SKU {sku}: ROP 由前端計算 = {reorder_point}")
            else:
                reorder_point = safety_stock
                logger.debug(f"SKU {sku}: ROP 使用安全庫存 = {reorder_point}")
        else:
            logger.debug(f"SKU {sku}: ROP 從後端讀取 = {reorder_point}")
        reorder_point = _safe_float(reorder_point, 0)

        # 🟡 FIX #3: max_inventory - 先讀取後端計算值，沒有才主動計算
        max_inventory = (
                getattr(r, "max_inventory", None) or
                getattr(r, "max_stock", None) or
                getattr(r, "target_stock", None)
        )
        if max_inventory is None or _safe_float(max_inventory, 0) == 0:
            max_inventory = reorder_point + safety_stock
            logger.debug(f"SKU {sku}: Max 由前端計算 = {max_inventory}")
        else:
            logger.debug(f"SKU {sku}: Max 從後端讀取 = {max_inventory}")
        max_inventory = _safe_float(max_inventory, 0)

        # === 別名欄位 ===
        avg_monthly_demand = _safe_float(
            getattr(r, "avg_monthly_demand", mean_demand),
            mean_demand
        )
        abc_grade = getattr(r, "abc_grade", abc_class) or abc_class

        # === 組裝結果 ===
        out.append({
            # --- 基礎 ---
            "site": site,
            "sku": sku,
            "name": name,

            # --- ABC/狀態 ---
            "abc_class": abc_class,
            "abc_grade": abc_grade,
            "status": status,

            # --- 需求/統計 ---
            "total_qty": _safe_float(getattr(r, "total_qty", 0), 0),
            "total_value": round(_safe_float(getattr(r, "total_value", 0), 0), 2),
            "active_months": active_months,
            "months_count": months_count,
            "mean_demand": round(mean_demand, 2),
            "avg_monthly_demand": round(avg_monthly_demand, 2),
            "std_dev": round(std_dev, 2),
            "cv": round(cv, 4),

            # --- 庫存建議 ---
            "safety_stock": round(safety_stock, 0),
            "safety_stock_value": round(_safe_float(getattr(r, "safety_stock_value", 0), 0), 2),
            "reorder_point": round(reorder_point, 0),
            "max_inventory": round(max_inventory, 0),
            "lead_time_days": lead_time_days,

            # --- 其他 ---
            "current_stock": getattr(r, "current_stock", None),
            "outliers_removed": _safe_int(getattr(r, "outliers_removed", 0), 0),
            "price": _safe_float(getattr(r, "price", 0), 0),

            # --- MA 相關 ---
            "enable_ma": bool(getattr(r, "enable_ma", False)),
        })

    return out


def _serialize_excluded(excluded: List[Any]) -> List[Dict[str, Any]]:
    """序列化排除項目"""
    out: List[Dict[str, Any]] = []
    for e in (excluded or []):
        out.append({
            "site": getattr(e, "site", None),
            "sku": getattr(e, "sku", None),
            "name": getattr(e, "name", None),
            "active_months": _safe_int(getattr(e, "active_months", 0), 0),
            "months_count": _safe_int(getattr(e, "months_count", getattr(e, "active_months", 0)), 0),
            "total_qty": _safe_float(getattr(e, "total_qty", 0), 0),
            "reason": getattr(e, "reason", None),
        })
    return out


# ============================================================================
# 版本資訊
# ============================================================================

__version__ = "4.3.4"
__author__ = "松鼠"
__last_updated__ = "2026-01-29"


def get_version_info() -> Dict[str, str]:
    """取得版本資訊"""
    return {
        "version": __version__,
        "author": __author__,
        "last_updated": __last_updated__,
        "changes": [
            "v4.3.4: 支援 z_scores 和 abc_thresholds 參數（對比模式）",
            "v4.3.4: 增強參數驗證和日誌輸出",
            "v4.3.4: 向後兼容（沒有參數時使用預設值）",
            "v4.3.1: 添加 SAP MM17 匯出功能（XLSX 和 CSV）",
            "v4.3.1: 添加對比模式完整 Excel 匯出",
            "v4.3.1: 優化代碼結構和錯誤處理",
            "v4.2.3: 修復 CV/ROP/Max 欄位映射和計算邏輯",
            "v4.2.2: 補齊前端所需欄位和向下相容別名",
            "v4.2.1: 初始版本",
        ]
    }


if __name__ == "__main__":
    # 測試版本資訊
    info = get_version_info()
    print(f"業務邏輯層版本：{info['version']}")
    print(f"作者：{info['author']}")
    print(f"最後更新：{info['last_updated']}")
    print("\n更新歷程：")
    for change in info['changes']:
        print(f"  - {change}")