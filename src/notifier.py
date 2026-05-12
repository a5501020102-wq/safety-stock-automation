"""
Notification module for SS Automation.
通知模組 - 支援 Email 與 LINE Notify

This module handles:
- Email notifications via SMTP
- LINE Notify messages
- Notification templates and formatting

Version: 4.0.0 (Fixed & Reviewed)
Author: 松鼠
Last Updated: 2024-12-19
"""

import json
import logging
import smtplib
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from enum import Enum
from pathlib import Path
from typing import Any

from .calculator import CalculationSummary
from .config_loader import config

# Import ChangeValidationResult only if needed (avoid circular import)
try:
    from .sap_exporter import ChangeValidationResult
except ImportError:
    ChangeValidationResult = None

logger = logging.getLogger(__name__)


class NotificationType(Enum):
    """Types of notifications."""
    CALCULATION_COMPLETE = "calculation_complete"
    SHORTAGE_RISK = "shortage_risk"
    LARGE_CHANGE = "large_change"
    ERROR = "error"
    SCHEDULE_START = "schedule_start"


class NotificationPriority(Enum):
    """Notification priority levels."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


@dataclass
class NotificationResult:
    """Result of a notification attempt."""
    success: bool
    channel: str  # email, line
    message: str
    timestamp: datetime
    error: str | None = None


@dataclass
class NotificationPayload:
    """Payload for notifications."""
    notification_type: NotificationType
    priority: NotificationPriority
    subject: str
    summary: str
    details: dict[str, Any]
    attachments: list[Path] | None = None


class EmailNotifier:
    """
    Email notification handler using SMTP.

    Supports:
    - Plain text and HTML emails
    - File attachments
    - Multiple recipients
    - TLS/SSL encryption
    """

    def __init__(self):
        """Initialize email notifier with config settings."""
        email_config = config.email

        self.enabled = email_config.get("enabled", False)
        self.smtp_server = email_config.get("smtp_server", "smtp.gmail.com")
        self.smtp_port = email_config.get("smtp_port", 587)
        self.use_tls = email_config.get("use_tls", True)
        self.sender = email_config.get("sender", "")
        self.password = email_config.get("password", "")
        self.recipients = email_config.get("recipients", [])
        self.notify_on = email_config.get("notify_on", {})

    def is_enabled(self) -> bool:
        """Check if email notifications are enabled and configured."""
        return (
                self.enabled
                and bool(self.sender)
                and bool(self.password)
                and bool(self.recipients)
        )

    def should_notify(self, notification_type: NotificationType) -> bool:
        """Check if notification should be sent for this type."""
        if not self.is_enabled():
            return False

        type_mapping = {
            NotificationType.CALCULATION_COMPLETE: "calculation_complete",
            NotificationType.SHORTAGE_RISK: "shortage_risk",
            NotificationType.LARGE_CHANGE: "large_change",
            NotificationType.ERROR: "error",
        }

        config_key = type_mapping.get(notification_type)
        return self.notify_on.get(config_key, False)

    def send(
            self,
            payload: NotificationPayload,
            html_body: str | None = None,
    ) -> NotificationResult:
        """
        Send email notification.

        Args:
            payload: Notification payload
            html_body: Optional HTML body content

        Returns:
            NotificationResult indicating success/failure
        """
        if not self.is_enabled():
            return NotificationResult(
                success=False,
                channel="email",
                message="Email notifications not enabled",
                timestamp=datetime.now(),
                error="Not configured",
            )

        try:
            # Create message
            msg = MIMEMultipart("alternative")
            msg["Subject"] = payload.subject
            msg["From"] = self.sender
            msg["To"] = ", ".join(self.recipients)

            # Add priority header
            if payload.priority == NotificationPriority.URGENT:
                msg["X-Priority"] = "1"
                msg["X-MSMail-Priority"] = "High"
            elif payload.priority == NotificationPriority.HIGH:
                msg["X-Priority"] = "2"

            # Plain text body
            text_body = self._format_text_body(payload)
            msg.attach(MIMEText(text_body, "plain", "utf-8"))

            # HTML body
            if html_body:
                msg.attach(MIMEText(html_body, "html", "utf-8"))
            else:
                default_html = self._format_html_body(payload)
                msg.attach(MIMEText(default_html, "html", "utf-8"))

            # Attachments
            if payload.attachments:
                for file_path in payload.attachments:
                    if file_path.exists():
                        self._attach_file(msg, file_path)

            # Send email
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                if self.use_tls:
                    server.starttls()
                server.login(self.sender, self.password)
                server.send_message(msg)

            logger.info(f"Email sent successfully to {len(self.recipients)} recipients")

            return NotificationResult(
                success=True,
                channel="email",
                message=f"Email sent to {len(self.recipients)} recipients",
                timestamp=datetime.now(),
            )

        except smtplib.SMTPAuthenticationError as e:
            error_msg = "SMTP authentication failed. Check email/password."
            logger.error(f"Email auth error: {e}")
            return NotificationResult(
                success=False,
                channel="email",
                message="Authentication failed",
                timestamp=datetime.now(),
                error=error_msg,
            )

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Email send error: {e}")
            return NotificationResult(
                success=False,
                channel="email",
                message="Failed to send email",
                timestamp=datetime.now(),
                error=error_msg,
            )

    def _attach_file(self, msg: MIMEMultipart, file_path: Path) -> None:
        """Attach a file to the email message."""
        with open(file_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())

        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f"attachment; filename={file_path.name}",
        )
        msg.attach(part)

    def _format_text_body(self, payload: NotificationPayload) -> str:
        """Format plain text email body."""
        lines = [
            "SS Automation 通知",
            "=" * 40,
            "",
            payload.summary,
            "",
        ]

        # Add details
        for key, value in payload.details.items():
            lines.append(f"{key}: {value}")

        lines.extend([
            "",
            "-" * 40,
            f"通知類型: {payload.notification_type.value}",
            f"時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ])

        return "\n".join(lines)

    def _format_html_body(self, payload: NotificationPayload) -> str:
        """Format HTML email body."""
        # Priority color
        priority_colors = {
            NotificationPriority.URGENT: "#dc3545",
            NotificationPriority.HIGH: "#fd7e14",
            NotificationPriority.NORMAL: "#0d6efd",
            NotificationPriority.LOW: "#6c757d",
        }
        priority_color = priority_colors.get(payload.priority, "#0d6efd")

        # Build details table rows
        detail_rows = ""
        for key, value in payload.details.items():
            detail_rows += f"""
            <tr>
                <td style="padding: 8px; border-bottom: 1px solid #dee2e6; font-weight: bold;">{key}</td>
                <td style="padding: 8px; border-bottom: 1px solid #dee2e6;">{value}</td>
            </tr>
            """

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{ font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, {priority_color}, #6f42c1); color: white; padding: 20px; border-radius: 8px 8px 0 0; }}
                .content {{ background: #fff; padding: 20px; border: 1px solid #dee2e6; border-top: none; }}
                .summary {{ background: #f8f9fa; padding: 15px; border-radius: 4px; margin: 15px 0; }}
                .footer {{ text-align: center; padding: 15px; color: #6c757d; font-size: 12px; }}
                table {{ width: 100%; border-collapse: collapse; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2 style="margin: 0;"> SS Automation 通知</h2>
                    <p style="margin: 5px 0 0 0; opacity: 0.9;">{payload.notification_type.value}</p>
                </div>
                <div class="content">
                    <div class="summary">
                        <p style="margin: 0;">{payload.summary}</p>
                    </div>

                    <h3>詳細資訊</h3>
                    <table>
                        {detail_rows}
                    </table>
                </div>
                <div class="footer">
                    <p>此郵件由 SS Automation 自動發送<br>
                    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                </div>
            </div>
        </body>
        </html>
        """

        return html


class LineNotifier:
    """
    LINE Notify notification handler.

    Requires a LINE Notify access token.
    Get one at: https://notify-bot.line.me/
    """

    NOTIFY_API_URL = "https://notify-api.line.me/api/notify"

    def __init__(self, access_token: str | None = None):
        """
        Initialize LINE notifier.

        Args:
            access_token: LINE Notify access token (or from config)
        """
        self.access_token = access_token or config.get("line", "access_token", default="")
        self.enabled = config.get("line", "enabled", default=False)

    def is_enabled(self) -> bool:
        """Check if LINE notifications are enabled and configured."""
        return self.enabled and bool(self.access_token)

    def send(
            self,
            payload: NotificationPayload,
            image_path: Path | None = None,
    ) -> NotificationResult:
        """
        Send LINE Notify message.

        Args:
            payload: Notification payload
            image_path: Optional image to attach

        Returns:
            NotificationResult indicating success/failure
        """
        if not self.is_enabled():
            return NotificationResult(
                success=False,
                channel="line",
                message="LINE Notify not enabled",
                timestamp=datetime.now(),
                error="Not configured",
            )

        try:
            # Format message
            message = self._format_message(payload)

            # Prepare request
            headers = {
                "Authorization": f"Bearer {self.access_token}",
            }

            data = urllib.parse.urlencode({"message": message}).encode("utf-8")

            req = urllib.request.Request(
                self.NOTIFY_API_URL,
                data=data,
                headers=headers,
                method="POST",
            )

            # Send request
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))

            if result.get("status") == 200:
                logger.info("LINE Notify sent successfully")
                return NotificationResult(
                    success=True,
                    channel="line",
                    message="LINE message sent",
                    timestamp=datetime.now(),
                )
            else:
                raise Exception(result.get("message", "Unknown error"))

        except Exception as e:
            error_msg = str(e)
            logger.error(f"LINE Notify error: {e}")
            return NotificationResult(
                success=False,
                channel="line",
                message="Failed to send LINE message",
                timestamp=datetime.now(),
                error=error_msg,
            )

    def _format_message(self, payload: NotificationPayload) -> str:
        """Format LINE Notify message."""
        # Priority emoji
        priority_emoji = {
            NotificationPriority.URGENT: "",
            NotificationPriority.HIGH: "",
            NotificationPriority.NORMAL: "",
            NotificationPriority.LOW: "ℹ",
        }
        emoji = priority_emoji.get(payload.priority, "")

        lines = [
            f"\n{emoji} SS Automation 通知",
            f"類型: {payload.notification_type.value}",
            "",
            payload.summary,
            "",
        ]

        # Add key details (limit for LINE message length)
        important_keys = ["計算料號", "缺貨風險", "需人工確認", "錯誤"]
        for key in important_keys:
            if key in payload.details:
                lines.append(f"• {key}: {payload.details[key]}")

        lines.append(f"\n時間: {datetime.now().strftime('%H:%M:%S')}")

        return "\n".join(lines)


class NotificationManager:
    """
    Unified notification manager.

    Handles sending notifications through multiple channels
    based on configuration and notification type.
    """

    def __init__(self):
        """Initialize notification manager (backends created lazily)."""
        self._email: EmailNotifier | None = None
        self._line: LineNotifier | None = None

    @property
    def email(self) -> EmailNotifier:
        """Lazily create EmailNotifier on first access."""
        if self._email is None:
            self._email = EmailNotifier()
        return self._email

    @property
    def line(self) -> LineNotifier:
        """Lazily create LineNotifier on first access."""
        if self._line is None:
            self._line = LineNotifier()
        return self._line

    def notify_calculation_complete(
            self,
            summary: CalculationSummary,
            validation_result=None,  # ChangeValidationResult | None
            output_files: dict[str, Path] | None = None,
    ) -> list[NotificationResult]:
        """
        Send notification for completed calculation.

        Args:
            summary: Calculation summary
            validation_result: Optional validation result
            output_files: Optional output file paths

        Returns:
            List of notification results
        """
        # Determine priority
        priority = NotificationPriority.NORMAL
        if summary.shortage_risk_count > 10:
            priority = NotificationPriority.HIGH
        if validation_result and hasattr(validation_result,
                                         'has_blocking_changes') and validation_result.has_blocking_changes:
            priority = NotificationPriority.HIGH

        # Build details
        details = {
            "計算料號": summary.total_skus,
            "排除料號": summary.excluded_count,
            "缺貨風險 ": summary.shortage_risk_count,
            "健康 ": summary.healthy_count,
            "呆滯風險 ": summary.overstock_risk_count,
            "前置期": f"{summary.lead_time_days} 天",
        }

        if validation_result and hasattr(validation_result, 'auto_approved'):
            details["自動通過"] = len(validation_result.auto_approved)
            details["建議審核"] = len(validation_result.review_suggested)
            details["需人工確認"] = len(validation_result.force_review)

        # Build summary text
        summary_text = f"安全庫存計算完成，共 {summary.total_skus} 個料號。"
        if summary.shortage_risk_count > 0:
            summary_text += f"\n 有 {summary.shortage_risk_count} 個料號存在缺貨風險！"
        if validation_result and hasattr(validation_result,
                                         'has_blocking_changes') and validation_result.has_blocking_changes:
            summary_text += f"\n 有 {len(validation_result.force_review)} 筆變動需人工確認！"

        payload = NotificationPayload(
            notification_type=NotificationType.CALCULATION_COMPLETE,
            priority=priority,
            subject=f"[SS Automation] 計算完成 - {summary.total_skus} 料號",
            summary=summary_text,
            details=details,
            attachments=list(output_files.values()) if output_files else None,
        )

        return self._send_all(payload)

    def notify_shortage_risk(
            self,
            shortage_items: list[dict[str, Any]],
    ) -> list[NotificationResult]:
        """
        Send urgent notification for shortage risks.

        Args:
            shortage_items: List of items with shortage risk

        Returns:
            List of notification results
        """
        details = {
            "缺貨風險數量": len(shortage_items),
        }

        # Add top 5 items
        for i, item in enumerate(shortage_items[:5], 1):
            details[f"#{i} {item.get('sku', 'N/A')}"] = (
                f"缺口: {item.get('gap', 0)}, "
                f"最晚下單: {item.get('order_deadline', 'N/A')}"
            )

        if len(shortage_items) > 5:
            details["...更多"] = f"還有 {len(shortage_items) - 5} 個項目"

        payload = NotificationPayload(
            notification_type=NotificationType.SHORTAGE_RISK,
            priority=NotificationPriority.URGENT,
            subject=f"[SS Automation] 缺貨風險警報 - {len(shortage_items)} 項目",
            summary=f"偵測到 {len(shortage_items)} 個料號存在缺貨風險，請立即處理！",
            details=details,
        )

        return self._send_all(payload)

    def notify_large_changes(
            self,
            validation_result,  # ChangeValidationResult
    ) -> list[NotificationResult]:
        """
        Send notification for large SS changes requiring review.

        Args:
            validation_result: Validation result with changes

        Returns:
            List of notification results
        """
        force_review = validation_result.force_review

        details = {
            "需人工確認": len(force_review),
            "建議審核": len(validation_result.review_suggested),
            "自動通過": len(validation_result.auto_approved),
        }

        # Add top changes
        for i, change in enumerate(force_review[:3], 1):
            change_desc = f"{change.old_ss} → {change.new_ss}"
            if change.change_pct is not None:
                change_desc += f" ({change.change_pct:+.1f}%)"
            details[f"#{i} {change.sku}"] = change_desc

        payload = NotificationPayload(
            notification_type=NotificationType.LARGE_CHANGE,
            priority=NotificationPriority.HIGH,
            subject=f"[SS Automation] 大幅變動需審核 - {len(force_review)} 項目",
            summary=f"有 {len(force_review)} 筆安全庫存變動超過 50%，需人工確認後才能上傳。",
            details=details,
        )

        return self._send_all(payload)

    def notify_error(
            self,
            error_message: str,
            error_details: str | None = None,
    ) -> list[NotificationResult]:
        """
        Send notification for errors.

        Args:
            error_message: Error message
            error_details: Optional detailed error info

        Returns:
            List of notification results
        """
        details = {
            "錯誤訊息": error_message,
        }

        if error_details:
            # Truncate long details
            if len(error_details) > 500:
                error_details = error_details[:500] + "..."
            details["詳細資訊"] = error_details

        payload = NotificationPayload(
            notification_type=NotificationType.ERROR,
            priority=NotificationPriority.URGENT,
            subject="[SS Automation] 執行錯誤",
            summary=f"SS Automation 執行時發生錯誤：{error_message}",
            details=details,
        )

        return self._send_all(payload)

    def notify_schedule_start(self) -> list[NotificationResult]:
        """Send notification when scheduled run starts."""
        payload = NotificationPayload(
            notification_type=NotificationType.SCHEDULE_START,
            priority=NotificationPriority.LOW,
            subject="[SS Automation] 排程執行開始",
            summary="SS Automation 排程作業已開始執行。",
            details={
                "開始時間": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        )

        # Only send to LINE for quick notification
        results = []
        if self.line.is_enabled():
            results.append(self.line.send(payload))

        return results

    def _send_all(self, payload: NotificationPayload) -> list[NotificationResult]:
        """Send notification through all enabled channels."""
        results = []

        # Email
        if self.email.should_notify(payload.notification_type):
            results.append(self.email.send(payload))

        # LINE
        if self.line.is_enabled():
            results.append(self.line.send(payload))

        return results


# ============================================================================
# Module-level functions (for backward compatibility with main.py)
# ============================================================================

# Create a singleton instance
_notification_manager = NotificationManager()


def send_calculation_notification(summary, excel_path):
    """
    Send calculation completion notification.

    Module-level wrapper for NotificationManager.notify_calculation_complete()

    Args:
        summary: CalculationSummary object
        excel_path: Path to Excel file

    Returns:
        List of NotificationResult objects
    """
    try:
        output_files = {"excel": excel_path}
        results = _notification_manager.notify_calculation_complete(
            summary=summary,
            validation_result=None,
            output_files=output_files,
        )

        # Log results
        for result in results:
            if result.success:
                logger.info(f" 通知已發送 ({result.channel}): {result.message}")
            else:
                logger.warning(f" 通知失敗 ({result.channel}): {result.error}")

        return results

    except Exception as e:
        logger.error(f"發送通知時發生錯誤: {e}")
        return []


def test_notification():
    """
    Test notification system.

    Sends a test notification through all enabled channels.

    Returns:
        List of NotificationResult objects
    """
    logger.info("測試通知功能...")

    # Create test payload
    test_payload = NotificationPayload(
        notification_type=NotificationType.CALCULATION_COMPLETE,
        priority=NotificationPriority.NORMAL,
        subject="[SS Automation] 測試通知",
        summary="這是一個測試通知,用於驗證通知系統是否正常運作。",
        details={
            "測試時間": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "通知狀態": "正常",
        },
    )

    results = _notification_manager._send_all(test_payload)

    print("\n=== 通知測試結果 ===")
    for result in results:
        status = " 成功" if result.success else " 失敗"
        print(f"{status} - {result.channel}: {result.message}")
        if result.error:
            print(f"   錯誤: {result.error}")

    if not results:
        print(" 無啟用的通知管道")

    return results


# Export all
__all__ = [
    'NotificationType',
    'NotificationPriority',
    'NotificationResult',
    'NotificationPayload',
    'EmailNotifier',
    'LineNotifier',
    'NotificationManager',
    'send_calculation_notification',
    'test_notification',
]
