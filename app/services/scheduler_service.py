import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import Settings
from app.database import SessionLocal
from app.models import AppSettings
from app.services.report_service import run_daily_report, acquire_job_lock, release_job_lock

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()
_job_id = "daily_report_job"


def run_report_job():
    logger.info("Scheduled report job triggered")
    db = SessionLocal()
    try:
        if not acquire_job_lock(db):
            logger.warning("Could not acquire job lock, skipping")
            return
        settings = Settings()
        run_daily_report(db, settings, force=False)
        release_job_lock(db)
    except Exception as e:
        logger.error(f"Scheduled report job failed: {e}")
    finally:
        db.close()


def start_scheduler():
    settings = Settings()
    db = SessionLocal()
    try:
        app_settings = db.query(AppSettings).first()
        if not app_settings:
            app_settings = AppSettings()
            db.add(app_settings)
            db.commit()
            db.refresh(app_settings)

        report_time = app_settings.report_time or "08:00"
        timezone_str = app_settings.timezone or settings.DEFAULT_TIMEZONE
        hour, minute = report_time.split(":")
        cron = CronTrigger(hour=int(hour), minute=int(minute), timezone=timezone_str)

        scheduler.add_job(
            run_report_job,
            cron,
            id=_job_id,
            replace_existing=True,
        )
        scheduler.start()
        logger.info(f"Scheduler started: daily at {report_time} ({timezone_str})")
    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}")
    finally:
        db.close()


def reschedule_job(report_time: str, timezone_str: str):
    if scheduler.get_job(_job_id):
        scheduler.remove_job(_job_id)
    hour, minute = report_time.split(":")
    cron = CronTrigger(hour=int(hour), minute=int(minute), timezone=timezone_str)
    scheduler.add_job(
        run_report_job,
        cron,
        id=_job_id,
        replace_existing=True,
    )
    logger.info(f"Rescheduled daily report: {report_time} ({timezone_str})")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
