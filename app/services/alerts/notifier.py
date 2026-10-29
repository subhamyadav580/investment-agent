"""Formats alert payloads and fans them out to the configured channels (log | telegram | email)."""

import logging
from typing import Any, Protocol

from app.core.config import Settings
from app.utils.notifications.email import EmailClient
from app.utils.notifications.telegram import TelegramClient

logger = logging.getLogger(__name__)

_SEVERITY_ICON = {"critical": "[CRITICAL]", "warning": "[WARNING]", "info": "[INFO]"}


class Notifier(Protocol):
    def send(self, payload: dict[str, Any]) -> None:
        """Raise on failure so the caller can record and retry."""
        ...


def format_alert(payload: dict[str, Any]) -> tuple[str, str]:
    subject = f"{_SEVERITY_ICON.get(payload['severity'], '')} {payload['symbol']}: {payload['trigger']}"
    lines = [
        subject,
        f"{payload.get('name', '')} ({payload['exchange']}:{payload['symbol']})",
        "",
        f"Rule: {payload['rule_id']}   Threshold: {payload.get('threshold')}   Observed: {payload.get('observed')}",
    ]
    if payload.get("comparison_period"):
        lines.append(f"Period: {payload['comparison_period']}")
    lines += ["", f"Why it may matter: {payload['why_it_matters']}", f"Suggested follow-up: {payload['follow_up']}"]
    for ev in payload.get("evidence", [])[:4]:
        if ev.get("type") == "metric":
            lines.append(f"  - metric {ev['key']} = {ev['value']} ({ev.get('period')})")
        else:
            synthetic = " [SYNTHETIC]" if ev.get("synthetic") else ""
            lines.append(f"  - source: {ev.get('title')} {ev.get('url') or ''} published {ev.get('published_at')}{synthetic}")
    for w in payload.get("data_quality_warnings", [])[:3]:
        lines.append(f"  ! data: {w}")
    if payload.get("report_url"):
        lines.append(f"\nLatest report: {payload['report_url']}")
    lines.append(f"Triggered: {payload.get('triggered_at')}\nResearch alert only - not a trade instruction.")
    return subject, "\n".join(lines)


class LogNotifier:
    def send(self, payload: dict[str, Any]) -> None:
        logger.info("ALERT\n%s", format_alert(payload)[1])


class TelegramNotifier:
    def __init__(self, client: TelegramClient):
        self.client = client

    def send(self, payload: dict[str, Any]) -> None:
        self.client.send(format_alert(payload)[1])


class EmailNotifier:
    def __init__(self, client: EmailClient):
        self.client = client

    def send(self, payload: dict[str, Any]) -> None:
        subject, body = format_alert(payload)
        self.client.send(subject, body)


class MultiNotifier:
    """Delivers to every channel; raises if ANY channel failed (so the alert is retried)."""

    def __init__(self, channels: dict[str, Notifier]):
        self.channels = channels

    def send(self, payload: dict[str, Any]) -> None:
        failures = []
        for name, channel in self.channels.items():
            try:
                channel.send(payload)
            except Exception as e:  # one channel failing must not block the others
                failures.append(f"{name}: {type(e).__name__}: {e}")
        if failures:
            raise RuntimeError("; ".join(failures))


def build_notifier(settings: Settings) -> MultiNotifier:
    channels: dict[str, Notifier] = {}
    for name in settings.notification_channels:
        if name == "log":
            channels["log"] = LogNotifier()
        elif name == "telegram":
            if not (settings.telegram_bot_token and settings.telegram_chat_id):
                raise ValueError("telegram channel enabled but TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set")
            channels["telegram"] = TelegramNotifier(TelegramClient(settings.telegram_bot_token, settings.telegram_chat_id))
        elif name == "email":
            if not (settings.smtp_host and settings.alert_email_to):
                raise ValueError("email channel enabled but SMTP_HOST / ALERT_EMAIL_TO not set")
            channels["email"] = EmailNotifier(EmailClient(
                settings.smtp_host, settings.smtp_port, settings.smtp_username, settings.smtp_password,
                settings.smtp_from or settings.smtp_username, settings.alert_email_to,
            ))  # fmt: skip
        else:
            raise ValueError(f"unknown notification channel {name!r}")
    return MultiNotifier(channels)
