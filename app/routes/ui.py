import re
from datetime import timedelta, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AppSettings, GmailConnection, ReportRun

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


_URL_RE = re.compile(r'https?://[^\s<>"\'(){}|\\^`[\]]+')


def extract_links(text: str) -> list:
    if not text:
        return []
    return _URL_RE.findall(text)


templates.env.filters["extract_links"] = extract_links


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    app_settings = db.query(AppSettings).first()
    gmail = db.query(GmailConnection).filter(GmailConnection.status == "connected").first()
    last_run = db.query(ReportRun).order_by(ReportRun.created_at.desc()).first()

    failed_runs = db.query(ReportRun).filter(ReportRun.status == "failed").count()
    total_reports = db.query(ReportRun).filter(ReportRun.status.in_(["success", "partial_success"])).count()

    recent_reports = (
        db.query(ReportRun)
        .filter(ReportRun.created_at >= datetime.utcnow() - timedelta(days=7))
        .order_by(ReportRun.run_date.asc())
        .all()
    )
    max_emails = max([r.emails_checked for r in recent_reports] or [1])

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "gmail_connected": gmail is not None,
            "google_email": gmail.google_email if gmail else None,
            "last_run": last_run,
            "failed_runs": failed_runs,
            "total_reports": total_reports,
            "recent_reports": recent_reports,
            "max_emails": max_emails,
        },
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: Session = Depends(get_db)):
    app_settings = db.query(AppSettings).first()
    gmail = db.query(GmailConnection).first()
    if not app_settings:
        app_settings = AppSettings()
        db.add(app_settings)
        db.commit()
        db.refresh(app_settings)
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "settings": app_settings,
            "gmail": gmail,
        },
    )


@router.get("/reports", response_class=HTMLResponse)
async def reports_list(request: Request, db: Session = Depends(get_db)):
    reports = db.query(ReportRun).order_by(ReportRun.created_at.desc()).limit(50).all()
    return templates.TemplateResponse(
        "reports.html",
        {"request": request, "reports": reports},
    )


@router.get("/reports/{report_id}", response_class=HTMLResponse)
async def report_detail(request: Request, report_id: int, db: Session = Depends(get_db)):
    report = db.query(ReportRun).filter(ReportRun.id == report_id).first()
    if not report:
        return HTMLResponse("Report not found", status_code=404)
    analyses = report.analyses
    return templates.TemplateResponse(
        "report_detail.html",
        {
            "request": request,
            "report": report,
            "analyses": analyses,
        },
    )


@router.get("/reports/{report_id}/html", response_class=HTMLResponse)
async def report_html_view(report_id: int, db: Session = Depends(get_db)):
    report = db.query(ReportRun).filter(ReportRun.id == report_id).first()
    if not report or not report.html_report:
        return HTMLResponse("Report or HTML content not found", status_code=404)
    return HTMLResponse(report.html_report)
