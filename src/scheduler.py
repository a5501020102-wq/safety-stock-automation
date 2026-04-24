"""
Scheduler module for SS Automation.
排程管理模組 - 支援 Windows Task Scheduler 與 Linux cron

This module handles:
- Creating and managing scheduled tasks
- Cross-platform scheduling support
- Schedule configuration and status
"""

import logging
import platform
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ScheduleFrequency(Enum):
    """Schedule frequency options."""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class DayOfWeek(Enum):
    """Days of the week."""
    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6


@dataclass
class ScheduleConfig:
    """Configuration for a scheduled task."""
    frequency: ScheduleFrequency
    time: time
    day_of_week: DayOfWeek | None = None  # For weekly schedules
    day_of_month: int | None = None  # For monthly schedules
    enabled: bool = True
    task_name: str = "SS_Automation"
    description: str = "安全庫存自動化計算"


@dataclass
class ScheduleStatus:
    """Status of a scheduled task."""
    exists: bool
    enabled: bool
    next_run: datetime | None
    last_run: datetime | None
    last_result: str | None
    details: dict[str, Any]


class WindowsScheduler:
    """
    Windows Task Scheduler handler.

    Uses schtasks.exe to create and manage scheduled tasks.
    """

    def __init__(self, project_root: Path | None = None):
        """
        Initialize Windows scheduler.

        Args:
            project_root: Root directory of the project
        """
        self.project_root = project_root or Path(__file__).parent.parent
        self.python_exe = sys.executable
        self.script_path = self.project_root / "scripts" / "scheduled_run.py"

    def create_task(self, schedule: ScheduleConfig) -> tuple[bool, str]:
        """
        Create a Windows scheduled task.

        Args:
            schedule: Schedule configuration

        Returns:
            Tuple of (success, message)
        """
        try:
            # Build schedule string
            time_str = schedule.time.strftime("%H:%M")

            # Base command
            cmd = [
                "schtasks", "/create",
                "/tn", schedule.task_name,
                "/tr", f'"{self.python_exe}" "{self.script_path}"',
                "/sc", schedule.frequency.value.upper(),
                "/st", time_str,
                "/f",  # Force overwrite if exists
            ]

            # Add day for weekly schedule
            if schedule.frequency == ScheduleFrequency.WEEKLY and schedule.day_of_week:
                day_names = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
                cmd.extend(["/d", day_names[schedule.day_of_week.value]])

            # Add day for monthly schedule
            if schedule.frequency == ScheduleFrequency.MONTHLY and schedule.day_of_month:
                cmd.extend(["/d", str(schedule.day_of_month)])

            # Execute command
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                shell=True,
            )

            if result.returncode == 0:
                logger.info(f"Task '{schedule.task_name}' created successfully")
                return True, f"排程 '{schedule.task_name}' 建立成功"
            else:
                error_msg = result.stderr or result.stdout
                logger.error(f"Failed to create task: {error_msg}")
                return False, f"建立排程失敗: {error_msg}"

        except Exception as e:
            logger.exception("Error creating scheduled task")
            return False, f"建立排程時發生錯誤: {e}"

    def delete_task(self, task_name: str) -> tuple[bool, str]:
        """
        Delete a Windows scheduled task.

        Args:
            task_name: Name of the task to delete

        Returns:
            Tuple of (success, message)
        """
        try:
            cmd = ["schtasks", "/delete", "/tn", task_name, "/f"]
            result = subprocess.run(cmd, capture_output=True, text=True, shell=True)

            if result.returncode == 0:
                return True, f"排程 '{task_name}' 已刪除"
            else:
                return False, f"刪除排程失敗: {result.stderr or result.stdout}"

        except Exception as e:
            return False, f"刪除排程時發生錯誤: {e}"

    def get_status(self, task_name: str) -> ScheduleStatus:
        """
        Get status of a scheduled task.

        Args:
            task_name: Name of the task

        Returns:
            ScheduleStatus object
        """
        try:
            cmd = ["schtasks", "/query", "/tn", task_name, "/fo", "LIST", "/v"]
            result = subprocess.run(cmd, capture_output=True, text=True, shell=True)

            if result.returncode != 0:
                return ScheduleStatus(
                    exists=False,
                    enabled=False,
                    next_run=None,
                    last_run=None,
                    last_result=None,
                    details={},
                )

            # Parse output
            details = {}
            for line in result.stdout.split("\n"):
                if ":" in line:
                    key, value = line.split(":", 1)
                    details[key.strip()] = value.strip()

            # Extract info
            enabled = details.get("Scheduled Task State", "").lower() == "enabled"
            last_result = details.get("Last Result", "")

            # Parse dates (format varies by locale)
            next_run = None
            last_run = None

            return ScheduleStatus(
                exists=True,
                enabled=enabled,
                next_run=next_run,
                last_run=last_run,
                last_result=last_result,
                details=details,
            )

        except Exception as e:
            logger.error(f"Error getting task status: {e}")
            return ScheduleStatus(
                exists=False,
                enabled=False,
                next_run=None,
                last_run=None,
                last_result=None,
                details={"error": str(e)},
            )

    def enable_task(self, task_name: str) -> tuple[bool, str]:
        """Enable a scheduled task."""
        try:
            cmd = ["schtasks", "/change", "/tn", task_name, "/enable"]
            result = subprocess.run(cmd, capture_output=True, text=True, shell=True)

            if result.returncode == 0:
                return True, f"排程 '{task_name}' 已啟用"
            return False, f"啟用排程失敗: {result.stderr or result.stdout}"
        except Exception as e:
            return False, f"啟用排程時發生錯誤: {e}"

    def disable_task(self, task_name: str) -> tuple[bool, str]:
        """Disable a scheduled task."""
        try:
            cmd = ["schtasks", "/change", "/tn", task_name, "/disable"]
            result = subprocess.run(cmd, capture_output=True, text=True, shell=True)

            if result.returncode == 0:
                return True, f"排程 '{task_name}' 已停用"
            return False, f"停用排程失敗: {result.stderr or result.stdout}"
        except Exception as e:
            return False, f"停用排程時發生錯誤: {e}"

    def run_now(self, task_name: str) -> tuple[bool, str]:
        """Run a scheduled task immediately."""
        try:
            cmd = ["schtasks", "/run", "/tn", task_name]
            result = subprocess.run(cmd, capture_output=True, text=True, shell=True)

            if result.returncode == 0:
                return True, f"排程 '{task_name}' 已開始執行"
            return False, f"執行排程失敗: {result.stderr or result.stdout}"
        except Exception as e:
            return False, f"執行排程時發生錯誤: {e}"


class LinuxScheduler:
    """
    Linux cron scheduler handler.

    Uses crontab to create and manage scheduled tasks.
    """

    CRON_MARKER = "# SS_Automation"

    def __init__(self, project_root: Path | None = None):
        """
        Initialize Linux scheduler.

        Args:
            project_root: Root directory of the project
        """
        self.project_root = project_root or Path(__file__).parent.parent
        self.python_exe = sys.executable
        self.script_path = self.project_root / "scripts" / "scheduled_run.py"

    def create_task(self, schedule: ScheduleConfig) -> tuple[bool, str]:
        """
        Create a cron job.

        Args:
            schedule: Schedule configuration

        Returns:
            Tuple of (success, message)
        """
        try:
            # Build cron expression
            minute = schedule.time.minute
            hour = schedule.time.hour

            if schedule.frequency == ScheduleFrequency.DAILY:
                cron_expr = f"{minute} {hour} * * *"
            elif schedule.frequency == ScheduleFrequency.WEEKLY:
                dow = schedule.day_of_week.value if schedule.day_of_week else 1
                cron_expr = f"{minute} {hour} * * {dow}"
            elif schedule.frequency == ScheduleFrequency.MONTHLY:
                dom = schedule.day_of_month or 1
                cron_expr = f"{minute} {hour} {dom} * *"
            else:
                cron_expr = f"{minute} {hour} * * *"

            # Build cron line
            cron_line = f'{cron_expr} {self.python_exe} "{self.script_path}" {self.CRON_MARKER}'

            # Get current crontab
            result = subprocess.run(
                ["crontab", "-l"],
                capture_output=True,
                text=True,
            )

            current_crontab = result.stdout if result.returncode == 0 else ""

            # Remove existing SS_Automation entries
            lines = [
                line for line in current_crontab.split("\n")
                if self.CRON_MARKER not in line and line.strip()
            ]

            # Add new entry
            lines.append(cron_line)
            new_crontab = "\n".join(lines) + "\n"

            # Install new crontab
            process = subprocess.Popen(
                ["crontab", "-"],
                stdin=subprocess.PIPE,
                text=True,
            )
            process.communicate(input=new_crontab)

            if process.returncode == 0:
                logger.info("Cron job created successfully")
                return True, f"排程建立成功: {cron_expr}"
            else:
                return False, "建立 cron 排程失敗"

        except Exception as e:
            logger.exception("Error creating cron job")
            return False, f"建立排程時發生錯誤: {e}"

    def delete_task(self, task_name: str = "") -> tuple[bool, str]:
        """
        Delete SS_Automation cron job.

        Args:
            task_name: Not used for cron (kept for interface compatibility)

        Returns:
            Tuple of (success, message)
        """
        try:
            # Get current crontab
            result = subprocess.run(
                ["crontab", "-l"],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                return True, "無排程需要刪除"

            # Remove SS_Automation entries
            lines = [
                line for line in result.stdout.split("\n")
                if self.CRON_MARKER not in line and line.strip()
            ]

            # Install cleaned crontab
            new_crontab = "\n".join(lines) + "\n" if lines else ""

            process = subprocess.Popen(
                ["crontab", "-"],
                stdin=subprocess.PIPE,
                text=True,
            )
            process.communicate(input=new_crontab)

            if process.returncode == 0:
                return True, "排程已刪除"
            return False, "刪除排程失敗"

        except Exception as e:
            return False, f"刪除排程時發生錯誤: {e}"

    def get_status(self, task_name: str = "") -> ScheduleStatus:
        """
        Get status of SS_Automation cron job.

        Args:
            task_name: Not used for cron

        Returns:
            ScheduleStatus object
        """
        try:
            result = subprocess.run(
                ["crontab", "-l"],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                return ScheduleStatus(
                    exists=False,
                    enabled=False,
                    next_run=None,
                    last_run=None,
                    last_result=None,
                    details={},
                )

            # Find SS_Automation entry
            for line in result.stdout.split("\n"):
                if self.CRON_MARKER in line:
                    return ScheduleStatus(
                        exists=True,
                        enabled=True,
                        next_run=None,  # Cron doesn't provide this easily
                        last_run=None,
                        last_result=None,
                        details={"cron_line": line},
                    )

            return ScheduleStatus(
                exists=False,
                enabled=False,
                next_run=None,
                last_run=None,
                last_result=None,
                details={},
            )

        except Exception as e:
            return ScheduleStatus(
                exists=False,
                enabled=False,
                next_run=None,
                last_run=None,
                last_result=None,
                details={"error": str(e)},
            )


class SchedulerManager:
    """
    Cross-platform scheduler manager.

    Automatically selects the appropriate scheduler based on OS.
    """

    def __init__(self, project_root: Path | None = None):
        """
        Initialize scheduler manager.

        Args:
            project_root: Root directory of the project
        """
        self.project_root = project_root or Path(__file__).parent.parent
        self.system = platform.system()

        if self.system == "Windows":
            self.scheduler = WindowsScheduler(self.project_root)
        else:
            self.scheduler = LinuxScheduler(self.project_root)

    @property
    def is_windows(self) -> bool:
        """Check if running on Windows."""
        return self.system == "Windows"

    def create_schedule(
            self,
            frequency: str = "weekly",
            hour: int = 8,
            minute: int = 0,
            day_of_week: int = 0,  # Monday
            day_of_month: int = 1,
            task_name: str = "SS_Automation",
    ) -> tuple[bool, str]:
        """
        Create a scheduled task.

        Args:
            frequency: 'daily', 'weekly', or 'monthly'
            hour: Hour to run (0-23)
            minute: Minute to run (0-59)
            day_of_week: Day of week for weekly (0=Monday)
            day_of_month: Day of month for monthly (1-31)
            task_name: Name for the task

        Returns:
            Tuple of (success, message)
        """
        schedule_config = ScheduleConfig(
            frequency=ScheduleFrequency(frequency),
            time=time(hour, minute),
            day_of_week=DayOfWeek(day_of_week) if frequency == "weekly" else None,
            day_of_month=day_of_month if frequency == "monthly" else None,
            task_name=task_name,
        )

        return self.scheduler.create_task(schedule_config)

    def delete_schedule(self, task_name: str = "SS_Automation") -> tuple[bool, str]:
        """Delete a scheduled task."""
        return self.scheduler.delete_task(task_name)

    def get_status(self, task_name: str = "SS_Automation") -> ScheduleStatus:
        """Get status of a scheduled task."""
        return self.scheduler.get_status(task_name)

    def run_now(self, task_name: str = "SS_Automation") -> tuple[bool, str]:
        """Run scheduled task immediately (Windows only)."""
        if self.is_windows:
            return self.scheduler.run_now(task_name)
        else:
            # For Linux, just run the script directly
            try:
                script_path = self.project_root / "scripts" / "scheduled_run.py"
                subprocess.Popen(
                    [sys.executable, str(script_path)],
                    start_new_session=True,
                )
                return True, "排程已在背景執行"
            except Exception as e:
                return False, f"執行失敗: {e}"
