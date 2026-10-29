"""Background worker: python -m app.jobs.worker

Schedules (cron, in SCHEDULER_TIMEZONE, configurable via env):
- weekly universe screening       WEEKLY_SCREENING_CRON
- daily watchlist monitoring      DAILY_MONITORING_CRON (announcements, thresholds, thesis checks)
- research queue draining         RESEARCH_QUEUE_CRON
- failed-alert delivery retries   ALERT_RETRY_CRON
- exchange price files sync       PRICE_SYNC_CRON (only with MARKET_DATA_PROVIDER=exchange_bhavcopy)
- event-driven discovery          EVENT_DISCOVERY_CRON (results, order wins, acquisitions ... from filings)
"""

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.jobs import scheduled_jobs

logger = logging.getLogger(__name__)


def build_scheduler() -> BlockingScheduler:
    s = get_settings()
    scheduler = BlockingScheduler(timezone=s.scheduler_timezone)
    jobs = [
        (scheduled_jobs.weekly_screening_job, s.weekly_screening_cron),
        (scheduled_jobs.daily_monitoring_job, s.daily_monitoring_cron),
        (scheduled_jobs.research_queue_job, s.research_queue_cron),
        (scheduled_jobs.alert_retry_job, s.alert_retry_cron),
        (scheduled_jobs.price_sync_job, s.price_sync_cron),
        (scheduled_jobs.event_discovery_job, s.event_discovery_cron),
    ]
    for fn, cron in jobs:
        scheduler.add_job(
            fn,
            CronTrigger.from_crontab(cron, timezone=s.scheduler_timezone),
            id=fn.__name__,
            max_instances=1,  # never overlap a job with itself
            coalesce=True,  # collapse missed runs into one
            misfire_grace_time=3600,
        )
    return scheduler


def main() -> None:
    s = get_settings()
    configure_logging(s.log_level, s.log_json)
    scheduler = build_scheduler()
    for job in scheduler.get_jobs():
        logger.info("scheduled job", extra={"job": job.id, "trigger": str(job.trigger)})
    scheduler.start()


if __name__ == "__main__":
    main()
