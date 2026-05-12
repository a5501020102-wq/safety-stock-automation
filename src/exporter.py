"""
Generic Exporter for SS Automation.
通用匯出模組 - 提供 Excel 和 JSON 匯出功能

This module provides simple export functions for main.py.
For SAP MM17 specific exports, see sap_exporter.py

Version: 4.0.0
Author: 松鼠
Last Updated: 2024-12-19
"""

import json
import logging
from pathlib import Path

import pandas as pd

from .calculator import CalculationResult, CalculationSummary, ExcludedItem, StockStatus

logger = logging.getLogger(__name__)


# ============================================================================
# Excel Export
# ============================================================================

def export_to_excel(
        results: list[CalculationResult],
        excluded: list[ExcludedItem],
        summary: CalculationSummary,
        output_path: Path | str,
        skip_validation: bool = False,
        force_upload: bool = False,
) -> None:
    """
    Export calculation results to Excel file with multiple sheets.

    Sheets:
        1. Summary - 計算摘要
        2. Results - 計算結果
        3. Shortage Risk - 缺貨風險品項
        4. Excluded - 排除品項

    Args:
        results: Calculation results
        excluded: Excluded items
        summary: Calculation summary
        output_path: Output file path
        skip_validation: Skip validation checks (not used in this implementation)
        force_upload: Include items needing review (not used in this implementation)

    Raises:
        Exception: If export fails
    """
    output_path = Path(output_path)
    logger.info(f"匯出 Excel: {output_path}")

    try:
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            # Sheet 1: Summary
            _write_summary_sheet(writer, summary)

            # Sheet 2: Results
            _write_results_sheet(writer, results)

            # Sheet 3: Shortage Risk
            _write_shortage_sheet(writer, results)

            # Sheet 4: Excluded
            _write_excluded_sheet(writer, excluded)

        logger.info(f" Excel 匯出完成: {output_path}")

    except Exception as e:
        logger.error(f"Excel 匯出失敗: {e}")
        raise


def _write_summary_sheet(writer: pd.ExcelWriter, summary: CalculationSummary) -> None:
    """Write summary sheet."""
    data = {
        '項目': [
            '執行時間',
            '總 SKU 數',
            '排除項目',
            '移除離群值',
            '缺貨風險',
            '健康庫存',
            '超量風險',
            '無資料',
            '前置期(天)',
            '最少月數',
            '離群值偵測',
        ],
        '數值': [
            summary.run_date.strftime('%Y-%m-%d %H:%M:%S'),
            summary.total_skus,
            summary.excluded_count,
            summary.total_outliers_removed,
            summary.shortage_risk_count,
            summary.healthy_count,
            summary.overstock_risk_count,
            summary.no_data_count,
            summary.lead_time_days,
            summary.min_months,
            '啟用' if summary.outlier_removal_enabled else '停用',
        ]
    }

    df = pd.DataFrame(data)
    df.to_excel(writer, sheet_name='Summary', index=False)


def _write_results_sheet(writer: pd.ExcelWriter, results: list[CalculationResult]) -> None:
    """Write results sheet."""
    data = []

    for r in results:
        data.append({
            '出貨點': r.site,
            '料號': r.sku,
            '品名': r.name,
            'ABC類別': r.abc_class.value,
            '總需求': r.total_qty,
            '總價值': round(r.total_value, 2),
            '活躍月數': r.active_months,
            '平均需求': round(r.mean_demand, 2),
            '標準差': round(r.std_dev, 2),
            '安全庫存': r.safety_stock,
            '安全庫存價值': round(r.safety_stock_value, 2),
            'Z分數': r.applied_z_score,
            '現有庫存': r.current_stock if r.current_stock is not None else '',
            '健康狀態': _status_to_text(r.status),
            '離群值數': r.outliers_removed,
            '樣本不足': '是' if r.has_insufficient_samples else '否',
        })

    df = pd.DataFrame(data)
    df.to_excel(writer, sheet_name='Results', index=False)


def _write_shortage_sheet(writer: pd.ExcelWriter, results: list[CalculationResult]) -> None:
    """Write shortage risk sheet."""
    shortage_items = [r for r in results if r.status == StockStatus.RED]

    if not shortage_items:
        df = pd.DataFrame({'訊息': ['無缺貨風險品項']})
        df.to_excel(writer, sheet_name='Shortage Risk', index=False)
        return

    data = []

    for r in shortage_items:
        data.append({
            '出貨點': r.site,
            '料號': r.sku,
            '品名': r.name,
            'ABC類別': r.abc_class.value,
            '安全庫存': r.safety_stock,
            '現有庫存': r.current_stock if r.current_stock is not None else 0,
            '缺口': (r.current_stock or 0) - r.safety_stock,
            '建議訂購': r.suggested_order if r.has_plan else '',
            '首次缺貨月份': r.first_shortage_month if r.has_plan else '',
            '訂購期限': r.order_deadline if r.has_plan else '',
        })

    df = pd.DataFrame(data)
    df.to_excel(writer, sheet_name='Shortage Risk', index=False)


def _write_excluded_sheet(writer: pd.ExcelWriter, excluded: list[ExcludedItem]) -> None:
    """Write excluded items sheet."""
    if not excluded:
        df = pd.DataFrame({'訊息': ['無排除品項']})
        df.to_excel(writer, sheet_name='Excluded', index=False)
        return

    data = []

    for item in excluded:
        data.append({
            '出貨點': item.site,
            '料號': item.sku,
            '品名': item.name,
            '活躍月數': item.active_months,
            '總需求': item.total_qty,
            '排除原因': item.reason,
        })

    df = pd.DataFrame(data)
    df.to_excel(writer, sheet_name='Excluded', index=False)


def _status_to_text(status: StockStatus) -> str:
    """Convert status enum to Chinese text."""
    mapping = {
        StockStatus.RED: '缺貨風險',
        StockStatus.GREEN: '健康',
        StockStatus.BLUE: '超量',
        StockStatus.GRAY: '無資料',
    }
    return mapping.get(status, '未知')


# ============================================================================
# JSON Export
# ============================================================================

def export_to_json(
        results: list[CalculationResult],
        excluded: list[ExcludedItem],
        summary: CalculationSummary,
        output_path: Path | str,
) -> None:
    """
    Export calculation results to JSON file.

    Args:
        results: Calculation results
        excluded: Excluded items
        summary: Calculation summary
        output_path: Output file path

    Raises:
        Exception: If export fails
    """
    output_path = Path(output_path)
    logger.info(f"匯出 JSON: {output_path}")

    try:
        # Convert to dict
        data = {
            'summary': _summary_to_dict(summary),
            'results': [_result_to_dict(r) for r in results],
            'excluded': [_excluded_to_dict(e) for e in excluded],
        }

        # Write JSON
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)

        logger.info(f" JSON 匯出完成: {output_path}")

    except Exception as e:
        logger.error(f"JSON 匯出失敗: {e}")
        raise


def _summary_to_dict(summary: CalculationSummary) -> dict:
    """Convert summary to dict."""
    return {
        'run_date': summary.run_date.isoformat(),
        'total_skus': summary.total_skus,
        'excluded_count': summary.excluded_count,
        'total_outliers_removed': summary.total_outliers_removed,
        'skipped_dates': summary.skipped_dates,
        'shortage_risk_count': summary.shortage_risk_count,
        'healthy_count': summary.healthy_count,
        'overstock_risk_count': summary.overstock_risk_count,
        'no_data_count': summary.no_data_count,
        'lead_time_days': summary.lead_time_days,
        'min_months': summary.min_months,
        'selected_months': summary.selected_months,
        'z_scores': summary.z_scores,
        'outlier_removal_enabled': summary.outlier_removal_enabled,
    }


def _result_to_dict(result: CalculationResult) -> dict:
    """Convert result to dict."""
    return {
        'site': result.site,
        'sku': result.sku,
        'name': result.name,
        'abc_class': result.abc_class.value,
        'total_qty': result.total_qty,
        'total_value': result.total_value,
        'active_months': result.active_months,
        'mean_demand': result.mean_demand,
        'std_dev': result.std_dev,
        'safety_stock': result.safety_stock,
        'safety_stock_value': result.safety_stock_value,
        'applied_z_score': result.applied_z_score,
        'current_stock': result.current_stock,
        'status': result.status.value,
        'outliers_removed': result.outliers_removed,
        'has_insufficient_samples': result.has_insufficient_samples,
        'has_plan': result.has_plan,
        'plan_stock': result.plan_stock if result.has_plan else None,
        'final_stock': result.final_stock if result.has_plan else None,
        'min_stock': result.min_stock if result.has_plan else None,
        'min_stock_month': result.min_stock_month if result.has_plan else None,
        'gap': result.gap if result.has_plan else None,
        'suggested_order': result.suggested_order if result.has_plan else None,
        'first_shortage_month': result.first_shortage_month,
        'order_deadline': result.order_deadline,
        'turnover_rate': result.turnover_rate,
    }


def _excluded_to_dict(excluded: ExcludedItem) -> dict:
    """Convert excluded item to dict."""
    return {
        'site': excluded.site,
        'sku': excluded.sku,
        'name': excluded.name,
        'active_months': excluded.active_months,
        'total_qty': excluded.total_qty,
        'reason': excluded.reason,
    }


# ============================================================================
# Export All
# ============================================================================

__all__ = [
    'export_to_excel',
    'export_to_json',
]
