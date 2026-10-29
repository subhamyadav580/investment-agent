import hashlib
from datetime import datetime, timedelta


def deduplication_key(company_id: int, rule_id: str, fingerprint: str) -> str:
    return hashlib.sha256(f"{company_id}|{rule_id}|{fingerprint}".encode()).hexdigest()


def in_quiet_period(last_triggered_at: datetime | None, now: datetime, quiet_hours: int) -> bool:
    if last_triggered_at is None or quiet_hours <= 0:
        return False
    if last_triggered_at.tzinfo is None and now.tzinfo is not None:  # SQLite drops tzinfo
        last_triggered_at = last_triggered_at.replace(tzinfo=now.tzinfo)
    return now - last_triggered_at < timedelta(hours=quiet_hours)
