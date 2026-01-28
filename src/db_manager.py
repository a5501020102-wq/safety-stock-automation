"""
Database Manager for SS Automation.
資料庫管理模組 - SQLite 操作與歷史紀錄管理
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Generator

from .calculator import (
    ABCClass,
    CalculationResult,
    CalculationSummary,
    ExcludedItem,
    StockStatus,
)
from .config_loader import config


class DatabaseError(Exception):
    """Database related errors."""
    pass


class DatabaseManager:
    """
    SQLite database manager for SS calculation history.

    Manages:
    - Calculation run records
    - SS results per SKU
    - SS change history tracking
    - Alerts and notifications
    """

    SCHEMA_VERSION = 1

    def __init__(self, db_path: str | Path | None = None):
        """
        Initialize database manager.

        Args:
            db_path: Path to SQLite database. Uses config if not provided.
        """
        if db_path is None:
            db_path = config.paths.get("database", "./data/ss_history.db")

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_database()

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Get a database connection with proper cleanup.

        Yields:
            SQLite connection with row factory set to dict-like access
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_database(self) -> None:
        """Initialize database schema if not exists."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Schema version tracking
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Calculation runs
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS calculation_runs (
                    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_date DATETIME NOT NULL,
                    input_file TEXT,
                    calc_mode TEXT,
                    target_site TEXT,
                    lead_time_days INTEGER,
                    min_months INTEGER,
                    selected_months TEXT,
                    z_scores TEXT,
                    outlier_removal INTEGER,
                    total_skus INTEGER,
                    excluded_count INTEGER,
                    outliers_removed INTEGER,
                    skipped_dates INTEGER,
                    shortage_risk_count INTEGER,
                    healthy_count INTEGER,
                    overstock_risk_count INTEGER,
                    no_data_count INTEGER,
                    status TEXT DEFAULT 'completed',
                    notes TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # SS results per SKU
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ss_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    site TEXT NOT NULL,
                    sku TEXT NOT NULL,
                    name TEXT,
                    abc_class TEXT,
                    total_qty REAL,
                    total_value REAL,
                    active_months INTEGER,
                    mean_demand REAL,
                    std_dev REAL,
                    safety_stock INTEGER,
                    ss_value REAL,
                    applied_z REAL,
                    current_stock REAL,
                    status TEXT,
                    outliers_removed INTEGER DEFAULT 0,
                    low_confidence INTEGER DEFAULT 0,
                    has_plan INTEGER DEFAULT 0,
                    plan_stock REAL,
                    final_stock REAL,
                    min_stock REAL,
                    min_stock_month TEXT,
                    gap REAL,
                    suggested_order INTEGER,
                    first_shortage_month TEXT,
                    order_deadline TEXT,
                    FOREIGN KEY (run_id) REFERENCES calculation_runs(run_id)
                )
            """)

            # Indexes for common queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_ss_results_run_id 
                ON ss_results(run_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_ss_results_site_sku 
                ON ss_results(site, sku)
            """)

            # SS change history
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ss_change_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    change_date DATETIME NOT NULL,
                    run_id INTEGER,
                    site TEXT NOT NULL,
                    sku TEXT NOT NULL,
                    old_ss INTEGER,
                    new_ss INTEGER,
                    change_amount INTEGER,
                    change_pct REAL,
                    change_category TEXT,
                    change_reason TEXT DEFAULT 'scheduled',
                    uploaded_to_sap INTEGER DEFAULT 0,
                    upload_date DATETIME,
                    FOREIGN KEY (run_id) REFERENCES calculation_runs(run_id)
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_change_history_site_sku 
                ON ss_change_history(site, sku)
            """)

            # Excluded items
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS excluded_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    site TEXT NOT NULL,
                    sku TEXT NOT NULL,
                    name TEXT,
                    active_months INTEGER,
                    total_qty REAL,
                    reason TEXT,
                    FOREIGN KEY (run_id) REFERENCES calculation_runs(run_id)
                )
            """)

            # Alerts
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_date DATETIME NOT NULL,
                    run_id INTEGER,
                    alert_type TEXT NOT NULL,
                    severity TEXT DEFAULT 'info',
                    site TEXT,
                    sku TEXT,
                    message TEXT,
                    details TEXT,
                    acknowledged INTEGER DEFAULT 0,
                    acknowledged_by TEXT,
                    acknowledged_at DATETIME,
                    FOREIGN KEY (run_id) REFERENCES calculation_runs(run_id)
                )
            """)

            # Check and apply schema version
            cursor.execute("SELECT MAX(version) as v FROM schema_version")
            row = cursor.fetchone()
            current_version = row["v"] if row and row["v"] else 0

            if current_version < self.SCHEMA_VERSION:
                cursor.execute(
                    "INSERT INTO schema_version (version) VALUES (?)",
                    (self.SCHEMA_VERSION,)
                )

            conn.commit()

    def save_calculation_run(
            self,
            results: list[CalculationResult],
            excluded: list[ExcludedItem],
            summary: CalculationSummary,
            input_file: str | None = None,
            calc_mode: str = "all",
            target_site: str | None = None,
            notes: str | None = None,
    ) -> int:
        """
        Save a complete calculation run to database.

        Args:
            results: List of calculation results
            excluded: List of excluded items
            summary: Calculation summary
            input_file: Name of input file
            calc_mode: Calculation mode used
            target_site: Target site (for single mode)
            notes: Optional notes

        Returns:
            run_id of the saved run
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Insert run record
            cursor.execute("""
                INSERT INTO calculation_runs (
                    run_date, input_file, calc_mode, target_site,
                    lead_time_days, min_months, selected_months, z_scores,
                    outlier_removal, total_skus, excluded_count, outliers_removed,
                    skipped_dates, shortage_risk_count, healthy_count,
                    overstock_risk_count, no_data_count, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                summary.run_date.isoformat(),
                input_file,
                calc_mode,
                target_site,
                summary.lead_time_days,
                summary.min_months,
                ",".join(map(str, summary.selected_months)),
                str(summary.z_scores),
                1 if summary.outlier_removal_enabled else 0,
                summary.total_skus,
                summary.excluded_count,
                summary.total_outliers_removed,
                summary.skipped_dates,
                summary.shortage_risk_count,
                summary.healthy_count,
                summary.overstock_risk_count,
                summary.no_data_count,
                notes,
            ))

            run_id = cursor.lastrowid

            # Insert results
            for r in results:
                cursor.execute("""
                    INSERT INTO ss_results (
                        run_id, site, sku, name, abc_class,
                        total_qty, total_value, active_months, mean_demand, std_dev,
                        safety_stock, ss_value, applied_z, current_stock, status,
                        outliers_removed, low_confidence, has_plan, plan_stock,
                        final_stock, min_stock, min_stock_month, gap,
                        suggested_order, first_shortage_month, order_deadline
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    run_id,
                    r.site,
                    r.sku,
                    r.name,
                    r.abc_class.value,
                    r.total_qty,
                    r.total_value,
                    r.active_months,
                    r.mean_demand,
                    r.std_dev,
                    r.safety_stock,
                    r.ss_value,
                    r.applied_z,
                    r.current_stock,
                    r.status.value,
                    r.outliers_removed,
                    1 if r.low_confidence else 0,
                    1 if r.has_plan else 0,
                    r.plan_stock,
                    r.final_stock,
                    r.min_stock,
                    r.min_stock_month,
                    r.gap,
                    r.suggested_order,
                    r.first_shortage_month,
                    r.order_deadline,
                ))

            # Insert excluded items
            for e in excluded:
                cursor.execute("""
                    INSERT INTO excluded_items (
                        run_id, site, sku, name, active_months, total_qty, reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    run_id,
                    e.site,
                    e.sku,
                    e.name,
                    e.active_months,
                    e.total_qty,
                    e.reason,
                ))

            conn.commit()
            return run_id

    def get_latest_ss_for_site_sku(
            self,
            site: str,
            sku: str,
    ) -> dict[str, Any] | None:
        """
        Get the most recent SS value for a site+SKU combination.

        Args:
            site: Site/warehouse code
            sku: Material number

        Returns:
            Dict with SS info or None if not found
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT r.*, cr.run_date
                FROM ss_results r
                JOIN calculation_runs cr ON r.run_id = cr.run_id
                WHERE r.site = ? AND r.sku = ?
                ORDER BY cr.run_date DESC
                LIMIT 1
            """, (site, sku))

            row = cursor.fetchone()
            return dict(row) if row else None

    def get_previous_run_results(self) -> dict[str, int]:
        """
        Get SS values from the most recent calculation run.

        Returns:
            Dict mapping "site|||sku" to safety_stock value
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Get latest run_id
            cursor.execute("""
                SELECT run_id FROM calculation_runs
                ORDER BY run_date DESC
                LIMIT 1
            """)
            row = cursor.fetchone()

            if not row:
                return {}

            run_id = row["run_id"]

            # Get all results from that run
            cursor.execute("""
                SELECT site, sku, safety_stock
                FROM ss_results
                WHERE run_id = ?
            """, (run_id,))

            results = {}
            for row in cursor.fetchall():
                key = f"{row['site']}|||{row['sku']}"
                results[key] = row["safety_stock"]

            return results

    def record_ss_changes(
            self,
            run_id: int,
            changes: list[dict[str, Any]],
    ) -> None:
        """
        Record SS changes for tracking and audit.

        Args:
            run_id: Associated calculation run ID
            changes: List of change records
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            for change in changes:
                cursor.execute("""
                    INSERT INTO ss_change_history (
                        change_date, run_id, site, sku,
                        old_ss, new_ss, change_amount, change_pct,
                        change_category, change_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    datetime.now().isoformat(),
                    run_id,
                    change["site"],
                    change["sku"],
                    change.get("old_ss"),
                    change["new_ss"],
                    change.get("change_amount", 0),
                    change.get("change_pct", 0),
                    change.get("category", "auto"),
                    change.get("reason", "scheduled"),
                ))

            conn.commit()

    def mark_uploaded_to_sap(
            self,
            site: str,
            sku: str,
            change_id: int | None = None,
    ) -> None:
        """
        Mark a change record as uploaded to SAP.

        Args:
            site: Site code
            sku: Material number
            change_id: Specific change ID, or latest if None
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            if change_id:
                cursor.execute("""
                    UPDATE ss_change_history
                    SET uploaded_to_sap = 1, upload_date = ?
                    WHERE id = ?
                """, (datetime.now().isoformat(), change_id))
            else:
                cursor.execute("""
                    UPDATE ss_change_history
                    SET uploaded_to_sap = 1, upload_date = ?
                    WHERE site = ? AND sku = ? AND uploaded_to_sap = 0
                """, (datetime.now().isoformat(), site, sku))

            conn.commit()

    def create_alert(
            self,
            alert_type: str,
            message: str,
            run_id: int | None = None,
            site: str | None = None,
            sku: str | None = None,
            severity: str = "info",
            details: str | None = None,
    ) -> int:
        """
        Create an alert record.

        Args:
            alert_type: Type of alert (shortage_risk, large_change, etc.)
            message: Alert message
            run_id: Associated run ID
            site: Related site
            sku: Related SKU
            severity: info, warning, error
            details: Additional details (JSON string)

        Returns:
            Alert ID
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO alerts (
                    alert_date, run_id, alert_type, severity,
                    site, sku, message, details
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                run_id,
                alert_type,
                severity,
                site,
                sku,
                message,
                details,
            ))

            conn.commit()
            return cursor.lastrowid

    def get_run_history(
            self,
            limit: int = 10,
            offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Get calculation run history.

        Args:
            limit: Maximum records to return
            offset: Records to skip

        Returns:
            List of run records
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM calculation_runs
                ORDER BY run_date DESC
                LIMIT ? OFFSET ?
            """, (limit, offset))

            return [dict(row) for row in cursor.fetchall()]

    def get_ss_trend(
            self,
            site: str,
            sku: str,
            limit: int = 12,
    ) -> list[dict[str, Any]]:
        """
        Get SS trend for a specific site+SKU over time.

        Args:
            site: Site code
            sku: Material number
            limit: Maximum data points

        Returns:
            List of historical SS values with dates
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT 
                    r.safety_stock,
                    r.mean_demand,
                    r.std_dev,
                    r.status,
                    cr.run_date
                FROM ss_results r
                JOIN calculation_runs cr ON r.run_id = cr.run_id
                WHERE r.site = ? AND r.sku = ?
                ORDER BY cr.run_date DESC
                LIMIT ?
            """, (site, sku, limit))

            return [dict(row) for row in cursor.fetchall()]

    def get_pending_alerts(self) -> list[dict[str, Any]]:
        """Get unacknowledged alerts."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM alerts
                WHERE acknowledged = 0
                ORDER BY alert_date DESC
            """)

            return [dict(row) for row in cursor.fetchall()]

    def acknowledge_alert(self, alert_id: int, acknowledged_by: str = "system") -> None:
        """Mark an alert as acknowledged."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE alerts
                SET acknowledged = 1, acknowledged_by = ?, acknowledged_at = ?
                WHERE id = ?
            """, (acknowledged_by, datetime.now().isoformat(), alert_id))

            conn.commit()