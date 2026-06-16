import logging
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.database import engine, Base, SessionLocal
from app.models import AppSettings, ReportRun, JobLock
from app.config import Settings
from app.routes import ui, api, gmail_auth
from app.services.scheduler_service import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Inbox FollowUp application...")
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if not db.query(AppSettings).first():
            default_settings = AppSettings(
                recipient_email="",
                report_time="08:00",
                timezone=Settings().DEFAULT_TIMEZONE,
                email_filter_type="today_unread",
                max_emails=50,
                ai_provider="nvidia",
                include_suggested_replies=True,
                include_meeting_detection=True,
                send_success_report=True,
                send_failure_report=True,
            )
            db.add(default_settings)
            db.commit()
            logger.info("Created default settings")
    except Exception as e:
        logger.warning(f"Could not create default settings: {e}")

    try:
        stuck = db.query(ReportRun).filter(ReportRun.status == "running").all()
        for r in stuck:
            r.status = "failed"
            r.error_message = "Server was restarted while this report was running."
            r.finished_at = datetime.now(timezone.utc)
        if stuck:
            db.commit()
            logger.info(f"Marked {len(stuck)} stuck running report(s) as failed")

        db.query(JobLock).delete()
        db.commit()
        logger.info("Cleared all job locks")
    except Exception as e:
        logger.warning(f"Could not clean up stuck state: {e}")
    finally:
        db.close()

    start_scheduler()
    yield
    stop_scheduler()
    logger.info("Inbox FollowUp application stopped.")


app = FastAPI(
    title="Inbox FollowUp",
    description="AI-powered email automation dashboard. Fetches Gmail emails, analyzes with AI, and sends daily reports.",
    version="1.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(ui.router)
app.include_router(api.router)
app.include_router(gmail_auth.router)
