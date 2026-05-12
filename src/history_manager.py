"""
History Manager for SS Automation.
歷史管理器 - 簡單的 JSON 儲存

這是一個輕量級的歷史管理器,用於 main.py。
如需完整的資料庫功能,請使用 DatabaseManager。

Version: 4.0.0
Author: 松鼠
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class HistoryManager:
    """
    Simple history manager using JSON storage.

    For full database features, use DatabaseManager instead.
    """

    def __init__(self, history_file: str | Path | None = None):
        """
        Initialize history manager.

        Args:
            history_file: Path to JSON history file
        """
        if history_file is None:
            history_file = Path("data/history.json")

        self.history_file = Path(history_file)
        self.history_file.parent.mkdir(parents=True, exist_ok=True)

        logger.debug(f"HistoryManager 初始化: {self.history_file}")

    def save_calculation(self, summary, excel_path, json_path):
        """
        Save calculation to history.

        Args:
            summary: CalculationSummary object
            excel_path: Path to Excel file
            json_path: Path to JSON file
        """
        try:
            # Load existing history
            history = self._load_history()

            # Add new record
            record = {
                'run_date': summary.run_date.isoformat(),
                'total_skus': summary.total_skus,
                'excluded_count': summary.excluded_count,
                'shortage_risk_count': summary.shortage_risk_count,
                'healthy_count': summary.healthy_count,
                'overstock_risk_count': summary.overstock_risk_count,
                'no_data_count': summary.no_data_count,
                'total_outliers_removed': summary.total_outliers_removed,
                'lead_time_days': summary.lead_time_days,
                'min_months': summary.min_months,
                'outlier_removal_enabled': summary.outlier_removal_enabled,
                'excel_path': str(excel_path),
                'json_path': str(json_path),
            }

            history.insert(0, record)

            # Keep only last 100 records
            history = history[:100]

            # Save
            self._save_history(history)

            logger.info(f" 已儲存計算歷史 ({len(history)} 筆記錄)")

        except Exception as e:
            logger.warning(f"儲存歷史失敗: {e}")

    def get_recent(self, limit: int = 10):
        """
        Get recent calculations.

        Args:
            limit: Number of records to return

        Returns:
            List of recent calculation records
        """
        try:
            history = self._load_history()
            return history[:limit]
        except Exception as e:
            logger.error(f"讀取歷史失敗: {e}")
            return []

    def get_all(self):
        """
        Get all history records.

        Returns:
            List of all calculation records
        """
        return self._load_history()

    def clear_history(self):
        """Clear all history records."""
        try:
            self._save_history([])
            logger.info("已清空歷史記錄")
        except Exception as e:
            logger.error(f"清空歷史失敗: {e}")
            raise

    def _load_history(self) -> list:
        """Load history from JSON file."""
        if not self.history_file.exists():
            return []

        try:
            with open(self.history_file, encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.warning("歷史檔案格式錯誤,將重新建立")
            return []
        except Exception as e:
            logger.error(f"載入歷史失敗: {e}")
            return []

    def _save_history(self, history: list) -> None:
        """Save history to JSON file."""
        with open(self.history_file, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
