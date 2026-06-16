import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from app.config import Settings
from app.database import get_db
from app.models import AppSettings, ReportRun, GmailConnection
from app.services.report_service import (
    run_daily_report,
    acquire_job_lock,
    release_job_lock,
)
from app.services.scheduler_service import reschedule_job
from app.services.gmail_service import get_user_email, build_gmail_service, refresh_access_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")
settings = Settings()


class SettingsUpdate(BaseModel):
    recipient_email: Optional[str] = None
    report_time: Optional[str] = None
    timezone: Optional[str] = None
    email_filter_type: Optional[str] = None
    custom_query: Optional[str] = None
    max_emails: Optional[int] = None
    ai_provider: Optional[str] = None
    ai_model: Optional[str] = None
    include_suggested_replies: Optional[bool] = None
    include_meeting_detection: Optional[bool] = None
    send_success_report: Optional[bool] = None
    send_failure_report: Optional[bool] = None
    allow_override: Optional[bool] = None


@router.get("/status")
async def get_status(db: Session = Depends(get_db)):
    gmail = db.query(GmailConnection).filter(GmailConnection.status == "connected").first()
    app_settings = db.query(AppSettings).first()
    last_run = db.query(ReportRun).order_by(ReportRun.created_at.desc()).first()

    return {
        "gmail_connected": gmail is not None,
        "google_email": gmail.google_email if gmail else None,
        "settings_configured": app_settings is not None,
        "last_run_status": last_run.status if last_run else None,
        "last_run_time": last_run.finished_at.isoformat() if last_run and last_run.finished_at else None,
        "last_report_sent": last_run.report_sent if last_run else False,
        "total_reports": db.query(ReportRun).count(),
    }


@router.get("/settings")
async def get_settings(db: Session = Depends(get_db)):
    app_settings = db.query(AppSettings).first()
    gmail = db.query(GmailConnection).first()
    if not app_settings:
        return {}
    return {
        "id": app_settings.id,
        "recipient_email": app_settings.recipient_email,
        "report_time": app_settings.report_time,
        "timezone": app_settings.timezone,
        "email_filter_type": app_settings.email_filter_type,
        "custom_query": app_settings.custom_query or "",
        "max_emails": app_settings.max_emails,
        "ai_provider": app_settings.ai_provider,
        "ai_model": app_settings.ai_model or "",
        "include_suggested_replies": app_settings.include_suggested_replies,
        "include_meeting_detection": app_settings.include_meeting_detection,
        "send_success_report": app_settings.send_success_report,
        "send_failure_report": app_settings.send_failure_report,
        "allow_override": app_settings.allow_override,
        "gmail": {
            "connected": gmail.status == "connected" if gmail else False,
            "email": gmail.google_email if gmail else None,
        }
        if gmail
        else {"connected": False, "email": None},
    }


@router.post("/settings")
async def update_settings(data: SettingsUpdate, db: Session = Depends(get_db)):
    app_settings = db.query(AppSettings).first()
    if not app_settings:
        app_settings = AppSettings()
        db.add(app_settings)

    update_data = data.model_dump(exclude_none=True)
    for key, value in update_data.items():
        if hasattr(app_settings, key):
            setattr(app_settings, key, value)

    app_settings.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(app_settings)

    if "report_time" in update_data or "timezone" in update_data:
        reschedule_job(app_settings.report_time, app_settings.timezone)

    return {"success": True, "settings": {k: getattr(app_settings, k) for k in update_data.keys()}}


@router.post("/reports/run-now")
async def run_report_now(
    force: bool = Query(False),
    db: Session = Depends(get_db),
):
    if not acquire_job_lock(db):
        raise HTTPException(status_code=409, detail="A report job is already running")
    try:
        result = run_daily_report(db, settings, force=force)
        return result
    except Exception as e:
        logger.error(f"Manual run failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        release_job_lock(db)


@router.get("/reports")
async def list_reports(db: Session = Depends(get_db)):
    reports = (
        db.query(ReportRun)
        .order_by(ReportRun.created_at.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "id": r.id,
            "run_date": str(r.run_date),
            "status": r.status,
            "emails_checked": r.emails_checked,
            "high_priority_count": r.high_priority_count,
            "needs_reply_count": r.needs_reply_count,
            "report_sent": r.report_sent,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        }
        for r in reports
    ]


@router.get("/reports/{report_id}")
async def get_report(report_id: int, db: Session = Depends(get_db)):
    report = db.query(ReportRun).filter(ReportRun.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    analyses = report.analyses
    return {
        "id": report.id,
        "run_date": str(report.run_date),
        "status": report.status,
        "emails_checked": report.emails_checked,
        "high_priority_count": report.high_priority_count,
        "needs_reply_count": report.needs_reply_count,
        "follow_up_count": report.follow_up_count,
        "meeting_count": report.meeting_count,
        "deadline_count": report.deadline_count,
        "error_message": report.error_message,
        "report_sent": report.report_sent,
        "resend_email_id": report.resend_email_id,
        "markdown_report": report.markdown_report,
        "html_report": report.html_report,
        "analyses": [
            {
                "id": a.id,
                "gmail_message_id": a.gmail_message_id,
                "sender": a.sender,
                "subject": a.subject,
                "category": a.category,
                "priority": a.priority,
                "priority_score": a.priority_score,
                "needs_reply": a.needs_reply,
                "needs_follow_up": a.needs_follow_up,
                "meeting_detected": a.meeting_detected,
                "deadline_detected": a.deadline_detected,
                "summary": a.summary,
                "recommended_action": a.recommended_action,
                "suggested_reply": a.suggested_reply,
            }
            for a in analyses
        ],
    }
