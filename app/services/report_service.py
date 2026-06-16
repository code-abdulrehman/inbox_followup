import json
import logging
from datetime import datetime, timezone, date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models import ReportRun, EmailAnalysis, JobLock, AppSettings, GmailConnection
from app.services.gmail_service import (
    build_gmail_service,
    fetch_emails,
    build_gmail_query,
    get_user_email,
    refresh_access_token,
)
from app.services.ai_service import analyze_email, batch_analyze_emails
from app.config import Settings

logger = logging.getLogger(__name__)


JOB_LOCK_DURATION_MINUTES = 30


def acquire_job_lock(db: Session, job_name: str = "daily_report") -> bool:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    lock = db.query(JobLock).filter(JobLock.job_name == job_name).first()
    if lock:
        if lock.status == "locked" and lock.locked_until > now:
            logger.warning(f"Job {job_name} is already locked until {lock.locked_until}")
            return False
        lock.status = "locked"
        lock.locked_until = now + timedelta(
            minutes=JOB_LOCK_DURATION_MINUTES
        )
        lock.updated_at = now
    else:
        lock = JobLock(
            job_name=job_name,
            status="locked",
            locked_until=now
            + timedelta(minutes=JOB_LOCK_DURATION_MINUTES),
        )
        db.add(lock)
    db.commit()
    logger.info(f"Acquired lock for job {job_name}")
    return True


def release_job_lock(db: Session, job_name: str = "daily_report"):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    lock = db.query(JobLock).filter(JobLock.job_name == job_name).first()
    if lock:
        lock.status = "released"
        lock.locked_until = now
        lock.updated_at = now
        db.commit()
        logger.info(f"Released lock for job {job_name}")


def check_duplicate_report(db: Session, run_date: date, job_name: str = "daily_report") -> bool:
    existing = (
        db.query(ReportRun)
        .filter(
            ReportRun.run_date == run_date,
            ReportRun.status.in_(["success", "partial_success", "running"]),
        )
        .first()
    )
    return existing is not None


def generate_html_report(analyses: list, report_run: ReportRun) -> str:
    high_priority = [a for a in analyses if a.priority == "high"]
    needs_reply = [a for a in analyses if a.needs_reply]
    needs_follow_up = [a for a in analyses if a.needs_follow_up]
    meetings = [a for a in analyses if a.meeting_detected]
    deadlines = [a for a in analyses if a.deadline_detected]
    low_priority = [a for a in analyses if a.priority == "low" and a.category == "newsletter"]

    rows_html = ""
    for a in analyses:
        priority_badge = {
            "high": '<span class="badge badge-high">High</span>',
            "medium": '<span class="badge badge-medium">Medium</span>',
            "low": '<span class="badge badge-low">Low</span>',
        }.get(a.priority, a.priority)

        rows_html += f"""<tr>
            <td>{a.sender or ''}</td>
            <td>{a.subject or ''}</td>
            <td>{priority_badge}</td>
            <td>{a.category or ''}</td>
            <td>{a.summary or ''}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Inbox FollowUp Daily Report - {report_run.run_date}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; color: #333; }}
h1, h2, h3 {{ color: #1a1a2e; }}
.summary-cards {{ display: flex; gap: 12px; flex-wrap: wrap; margin: 20px 0; }}
.card {{ background: #f8f9fa; border-radius: 8px; padding: 16px; flex: 1; min-width: 140px; border: 1px solid #e9ecef; }}
.card .number {{ font-size: 28px; font-weight: bold; color: #1a1a2e; }}
.card .label {{ font-size: 12px; color: #6c757d; text-transform: uppercase; }}
.badge {{ display: inline-block; padding: 3px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; }}
.badge-high {{ background: #fce4ec; color: #c62828; }}
.badge-medium {{ background: #fff3e0; color: #e65100; }}
.badge-low {{ background: #e8f5e9; color: #2e7d32; }}
table {{ width: 100%; border-collapse: collapse; margin: 16px 0; }}
th {{ text-align: left; padding: 10px 8px; background: #f8f9fa; border-bottom: 2px solid #dee2e6; font-size: 13px; text-transform: uppercase; color: #495057; }}
td {{ padding: 10px 8px; border-bottom: 1px solid #e9ecef; font-size: 14px; }}
.section {{ background: #fff; border: 1px solid #e9ecef; border-radius: 8px; padding: 20px; margin: 16px 0; }}
.footer {{ margin-top: 30px; padding: 16px; background: #f8f9fa; border-radius: 8px; font-size: 12px; color: #6c757d; }}
</style>
</head>
<body>
<h1>Inbox FollowUp Daily Report</h1>
<p>Date: {report_run.run_date} | Status: {report_run.status.replace('_', ' ').title()} | Emails Checked: {report_run.emails_checked}</p>

<div class="summary-cards">
<div class="card"><div class="number">{report_run.emails_checked}</div><div class="label">Total Emails</div></div>
<div class="card"><div class="number">{report_run.high_priority_count}</div><div class="label">High Priority</div></div>
<div class="card"><div class="number">{report_run.needs_reply_count}</div><div class="label">Need Reply</div></div>
<div class="card"><div class="number">{report_run.follow_up_count}</div><div class="label">Follow Ups</div></div>
<div class="card"><div class="number">{report_run.meeting_count}</div><div class="label">Meetings</div></div>
<div class="card"><div class="number">{report_run.deadline_count}</div><div class="label">Deadlines</div></div>
</div>

<div class="section">
<h2>High Priority Emails ({len(high_priority)})</h2>
<table><thead><tr><th>Sender</th><th>Subject</th><th>Priority</th><th>Category</th><th>Summary</th></tr></thead><tbody>
{"".join(f'<tr><td>{a.sender or ""}</td><td>{a.subject or ""}</td><td><span class="badge badge-high">High</span></td><td>{a.category or ""}</td><td>{a.summary or ""}</td></tr>' for a in high_priority) or '<tr><td colspan="5">None</td></tr>'}
</tbody></table></div>

<div class="section">
<h2>Emails Needing Reply ({len(needs_reply)})</h2>
<table><thead><tr><th>Sender</th><th>Subject</th><th>Priority</th><th>Category</th><th>Summary</th></tr></thead><tbody>
{"".join(f'<tr><td>{a.sender or ""}</td><td>{a.subject or ""}</td><td>{"High" if a.priority == "high" else "Medium"}</td><td>{a.category or ""}</td><td>{a.summary or ""}</td></tr>' for a in needs_reply) or '<tr><td colspan="5">None</td></tr>'}
</tbody></table></div>

<div class="section">
<h2>Follow-ups Needed ({len(needs_follow_up)})</h2>
<table><thead><tr><th>Sender</th><th>Subject</th><th>Summary</th><th>Action</th></tr></thead><tbody>
{"".join(f'<tr><td>{a.sender or ""}</td><td>{a.subject or ""}</td><td>{a.summary or ""}</td><td>{a.recommended_action or ""}</td></tr>' for a in needs_follow_up) or '<tr><td colspan="4">None</td></tr>'}
</tbody></table></div>

<div class="section">
<h2>Meeting Requests ({len(meetings)})</h2>
<table><thead><tr><th>Sender</th><th>Subject</th><th>Summary</th><th>Action</th></tr></thead><tbody>
{"".join(f'<tr><td>{a.sender or ""}</td><td>{a.subject or ""}</td><td>{a.summary or ""}</td><td>{a.recommended_action or ""}</td></tr>' for a in meetings) or '<tr><td colspan="4">None</td></tr>'}
</tbody></table></div>

<div class="section">
<h2>Deadlines ({len(deadlines)})</h2>
<table><thead><tr><th>Sender</th><th>Subject</th><th>Summary</th><th>Action</th></tr></thead><tbody>
{"".join(f'<tr><td>{a.sender or ""}</td><td>{a.subject or ""}</td><td>{a.summary or ""}</td><td>{a.recommended_action or ""}</td></tr>' for a in deadlines) or '<tr><td colspan="4">None</td></tr>'}
</tbody></table></div>

<div class="section">
<h2>Low Priority / Newsletters ({len(low_priority)})</h2>
<table><thead><tr><th>Sender</th><th>Subject</th><th>Summary</th></tr></thead><tbody>
{"".join(f'<tr><td>{a.sender or ""}</td><td>{a.subject or ""}</td><td>{a.summary or ""}</td></tr>' for a in low_priority) or '<tr><td colspan="3">None</td></tr>'}
</tbody></table></div>

<div class="footer">
<p>Generated by Inbox FollowUp | {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>
</div>
</body></html>"""
    return html


def generate_markdown_report(analyses: list, report_run: ReportRun) -> str:
    lines = []
    lines.append(f"# Inbox FollowUp Daily Report — {report_run.run_date}")
    lines.append(f"**Status:** {report_run.status.replace('_', ' ').title()}")
    lines.append(f"**Emails Checked:** {report_run.emails_checked}")
    lines.append("")

    high_priority = [a for a in analyses if a.priority == "high"]
    needs_reply = [a for a in analyses if a.needs_reply]
    needs_follow_up = [a for a in analyses if a.needs_follow_up]
    meetings = [a for a in analyses if a.meeting_detected]
    deadlines = [a for a in analyses if a.deadline_detected]
    low_priority = [a for a in analyses if a.priority == "low" and a.category == "newsletter"]

    lines.append("## Executive Summary")
    lines.append(f"- Total: {report_run.emails_checked} | High: {report_run.high_priority_count} | Need Reply: {report_run.needs_reply_count} | Follow-ups: {report_run.follow_up_count} | Meetings: {report_run.meeting_count} | Deadlines: {report_run.deadline_count}")
    lines.append("")

    if high_priority:
        lines.append("## High Priority Emails")
        for a in high_priority:
            lines.append(f"- **{a.subject}** from {a.sender} — {a.summary}")
        lines.append("")

    if needs_reply:
        lines.append("## Emails Needing Reply")
        for a in needs_reply:
            lines.append(f"- **{a.subject}** from {a.sender} — {a.summary}")
        lines.append("")

    if needs_follow_up:
        lines.append("## Follow-ups Needed")
        for a in needs_follow_up:
            lines.append(f"- **{a.subject}** from {a.sender} — Action: {a.recommended_action}")
        lines.append("")

    if meetings:
        lines.append("## Meeting Requests")
        for a in meetings:
            lines.append(f"- **{a.subject}** from {a.sender}")
        lines.append("")

    if deadlines:
        lines.append("## Deadlines")
        for a in deadlines:
            lines.append(f"- **{a.subject}** from {a.sender}")
        lines.append("")

    if low_priority:
        lines.append("## Low Priority / Newsletters")
        for a in low_priority:
            lines.append(f"- {a.subject} from {a.sender}")
        lines.append("")

    if report_run.error_message:
        lines.append("## Errors / Warnings")
        lines.append(f"- {report_run.error_message}")
        lines.append("")

    lines.append(f"---\n_Generated by Inbox FollowUp_")
    return "\n".join(lines)


def generate_json_summary(analyses: list, report_run: ReportRun) -> str:
    summary = {
        "run_date": str(report_run.run_date),
        "status": report_run.status,
        "emails_checked": report_run.emails_checked,
        "high_priority_count": report_run.high_priority_count,
        "needs_reply_count": report_run.needs_reply_count,
        "follow_up_count": report_run.follow_up_count,
        "meeting_count": report_run.meeting_count,
        "deadline_count": report_run.deadline_count,
        "report_sent": report_run.report_sent,
        "analyses": [
            {
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
            }
            for a in analyses
        ],
    }
    return json.dumps(summary, indent=2)


def run_daily_report(
    db: Session,
    settings: Settings,
    force: bool = False,
    run_id: Optional[str] = None,
) -> dict:
    from app.services.run_logger import add_log

    errors = []
    failure_step = None
    emails = []
    analyses = []
    today = date.today()

    app_settings = db.query(AppSettings).first()
    allow_override = app_settings.allow_override if app_settings else False

    if not force and not allow_override and check_duplicate_report(db, today):
        msg = "Duplicate report: today's report already exists. Enable 'Allow Override' in Settings or use scheduler only."
        logger.warning(msg)
        if run_id:
            add_log(run_id, "warning", "duplicate", msg)
        return {"status": "skipped", "message": msg}

    report_run = ReportRun(
        run_date=today,
        status="running",
        started_at=datetime.now(timezone.utc),
    )
    db.add(report_run)
    db.commit()
    db.refresh(report_run)

    if run_id:
        add_log(run_id, "info", "init", f"Report run #{report_run.id} created for {today}", progress=5)

    try:
        app_settings = db.query(AppSettings).first()
        if not app_settings:
            app_settings = AppSettings()
            db.add(app_settings)
            db.commit()
            db.refresh(app_settings)

        gmail_conn = db.query(GmailConnection).filter(
            GmailConnection.status == "connected"
        ).first()
        if not gmail_conn:
            raise Exception("No Gmail connection found. Connect Gmail first.")

        try:
            if run_id:
                add_log(run_id, "info", "gmail", "Fetching emails from Gmail...", progress=10)

            access_token = gmail_conn.access_token
            if not access_token and gmail_conn.refresh_token:
                access_token = refresh_access_token(
                    gmail_conn.refresh_token,
                    settings.GOOGLE_CLIENT_ID,
                    settings.GOOGLE_CLIENT_SECRET,
                )
                if access_token:
                    gmail_conn.access_token = access_token
                    db.commit()

            service = build_gmail_service(
                access_token,
                gmail_conn.refresh_token,
                settings.GOOGLE_CLIENT_ID,
                settings.GOOGLE_CLIENT_SECRET,
            )
            user_email = get_user_email(service)
            if user_email and not gmail_conn.google_email:
                gmail_conn.google_email = user_email
                db.commit()

            include_suggested_replies = app_settings.include_suggested_replies
            include_meeting_detection = app_settings.include_meeting_detection

            has_nvidia = bool(settings.NVIDIA_API_KEY)
            has_openrouter = bool(settings.OPENROUTER_API_KEY)

            if not has_nvidia and not has_openrouter:
                effective_provider = "none"
                ai_warning = "No AI provider configured. Set NVIDIA_API_KEY or OPENROUTER_API_KEY in .env for AI analysis. Using rule-based fallback."
                logger.warning(ai_warning)
                errors.append(ai_warning)
            elif app_settings.ai_provider == "nvidia" and has_nvidia:
                effective_provider = "nvidia"
                ai_warning = ""
            elif app_settings.ai_provider == "openrouter" and has_openrouter:
                effective_provider = "openrouter"
                ai_warning = ""
            elif has_nvidia:
                effective_provider = "nvidia"
                ai_warning = f"Selected provider '{app_settings.ai_provider}' not configured, using NVIDIA."
                logger.warning(ai_warning)
            elif has_openrouter:
                effective_provider = "openrouter"
                ai_warning = f"Selected provider '{app_settings.ai_provider}' not configured, using OpenRouter."
                logger.warning(ai_warning)
            else:
                effective_provider = "none"
                ai_warning = "No AI provider configured."
                errors.append(ai_warning)

            query = build_gmail_query(
                app_settings.email_filter_type,
                app_settings.custom_query,
                exclude_email=settings.RESEND_FROM_EMAIL,
            )
            emails = fetch_emails(service, query, app_settings.max_emails)
            report_run.emails_checked = len(emails)
            db.commit()

            if run_id:
                add_log(run_id, "success", "gmail", f"Fetched {len(emails)} emails", progress=25)
        except Exception as e:
            failure_step = "gmail"
            error_msg = f"Gmail fetch failed: {str(e)}"
            logger.error(error_msg)
            errors.append(error_msg)
            if run_id:
                add_log(run_id, "error", "gmail", error_msg, progress=25)
            raise

        if emails:
            batch_results = None
            if effective_provider != "none":
                if run_id:
                    add_log(run_id, "info", "ai", f"Running AI analysis via {effective_provider}...", progress=30)
                try:
                    batch_results = batch_analyze_emails(emails, settings, effective_provider)
                    if batch_results:
                        logger.info(f"Batch AI analysis succeeded for {len(batch_results)} emails")
                        if run_id:
                            add_log(run_id, "success", "ai", f"AI analyzed {len(batch_results)} emails", progress=60)
                except Exception as e:
                    logger.warning(f"Batch AI analysis failed: {e}")
                    if run_id:
                        add_log(run_id, "warning", "ai", f"AI analysis failed, falling back to rule-based: {str(e)}", progress=40)
            else:
                if run_id:
                    add_log(run_id, "info", "ai", "No AI provider configured, using rule-based analysis", progress=30)

            if batch_results:
                for i, email_data in enumerate(emails):
                    try:
                        ai_result = batch_results[i] if i < len(batch_results) else analyze_email_rule_based(email_data)
                        if not ai_result.get("_analysis_method"):
                            ai_result["_analysis_method"] = "ai"
                        analysis = EmailAnalysis(
                            report_run_id=report_run.id,
                            gmail_message_id=email_data["message_id"],
                            thread_id=email_data.get("thread_id", ""),
                            sender=email_data.get("sender", ""),
                            subject=email_data.get("subject", ""),
                            email_date=datetime.now(timezone.utc),
                            snippet=email_data.get("snippet", "")[:500],
                            category=ai_result["category"],
                            priority=ai_result["priority"],
                            priority_score=ai_result["priority_score"],
                            needs_reply=ai_result["needs_reply"],
                            needs_follow_up=ai_result["needs_follow_up"],
                            meeting_detected=ai_result["meeting_detected"] if include_meeting_detection else False,
                            deadline_detected=ai_result["deadline_detected"],
                            summary=ai_result.get("summary", "")[:300],
                            recommended_action=ai_result.get("recommended_action", ""),
                            suggested_reply=ai_result.get("suggested_reply", ""),
                            reason=ai_result.get("reason", ""),
                            raw_ai_response=json.dumps(ai_result),
                        )
                        db.add(analysis)
                        analyses.append(analysis)
                    except Exception as e:
                        error_msg = f"AI batch mapping failed for email {email_data.get('message_id', '')}: {str(e)}"
                        logger.warning(error_msg)
                        errors.append(error_msg)
            else:
                if effective_provider != "none":
                    logger.info("Batch AI failed, skipping per-email AI calls — using rule-based fallback")
                    if run_id:
                        add_log(run_id, "info", "ai", "Skipping per-email AI calls, using rule-based to avoid rate limits", progress=45)
                effective_provider = "none"
                for i, email_data in enumerate(emails):
                    try:
                        ai_result = analyze_email(email_data, settings, include_suggested_replies, effective_provider)
                        analysis = EmailAnalysis(
                            report_run_id=report_run.id,
                            gmail_message_id=email_data["message_id"],
                            thread_id=email_data.get("thread_id", ""),
                            sender=email_data.get("sender", ""),
                            subject=email_data.get("subject", ""),
                            email_date=datetime.now(timezone.utc),
                            snippet=email_data.get("snippet", "")[:500],
                            category=ai_result["category"],
                            priority=ai_result["priority"],
                            priority_score=ai_result["priority_score"],
                            needs_reply=ai_result["needs_reply"],
                            needs_follow_up=ai_result["needs_follow_up"],
                            meeting_detected=ai_result["meeting_detected"] if include_meeting_detection else False,
                            deadline_detected=ai_result["deadline_detected"],
                            summary=ai_result.get("summary", "")[:300],
                            recommended_action=ai_result.get("recommended_action", ""),
                            suggested_reply=ai_result.get("suggested_reply", ""),
                            reason=ai_result.get("reason", ""),
                            raw_ai_response=json.dumps(ai_result),
                        )
                        db.add(analysis)
                        analyses.append(analysis)
                    except Exception as e:
                        error_msg = f"AI analysis failed for email {email_data.get('message_id', '')}: {str(e)}"
                        logger.warning(error_msg)
                        errors.append(error_msg)

        if run_id:
            add_log(run_id, "info", "report", "Generating report...", progress=70)

        db.commit()
        db.refresh(report_run)

        all_analyses = (
            db.query(EmailAnalysis)
            .filter(EmailAnalysis.report_run_id == report_run.id)
            .all()
        )

        report_run.high_priority_count = sum(1 for a in all_analyses if a.priority == "high")
        report_run.needs_reply_count = sum(1 for a in all_analyses if a.needs_reply)
        report_run.follow_up_count = sum(1 for a in all_analyses if a.needs_follow_up)
        report_run.meeting_count = sum(1 for a in all_analyses if a.meeting_detected)
        report_run.deadline_count = sum(1 for a in all_analyses if a.deadline_detected)

        report_run.markdown_report = generate_markdown_report(all_analyses, report_run)
        report_run.html_report = generate_html_report(all_analyses, report_run)
        report_run.json_summary = generate_json_summary(all_analyses, report_run)

        if errors:
            report_run.status = "partial_success"
            report_run.error_message = "; ".join(errors[:5])
        else:
            report_run.status = "success"

        report_run.finished_at = datetime.now(timezone.utc)
        db.commit()

        if run_id:
            add_log(run_id, "success", "report", f"Report generated: {report_run.emails_checked} emails, {report_run.high_priority_count} high priority", progress=80)

        try:
            should_send = (
                (report_run.status == "success" and app_settings.send_success_report)
                or (report_run.status == "partial_success" and app_settings.send_success_report)
            )
            if should_send and app_settings.recipient_email:
                from app.services.email_service import send_report_email

                if run_id:
                    add_log(run_id, "info", "email", "Sending report email...", progress=85)

                send_result = send_report_email(
                    settings=settings,
                    to_email=app_settings.recipient_email,
                    subject=f"Inbox FollowUp Daily Report — {report_run.run_date}",
                    html_content=report_run.html_report,
                    text_content=report_run.markdown_report,
                )
                if send_result.get("success"):
                    report_run.report_sent = True
                    report_run.resend_email_id = send_result.get("email_id")
                    if run_id:
                        add_log(run_id, "success", "email", f"Report emailed to {app_settings.recipient_email}", progress=95)
                else:
                    error_msg = f"Failed to send report: {send_result.get('error', '')}"
                    errors.append(error_msg)
                    if run_id:
                        add_log(run_id, "error", "email", error_msg, progress=90)

            if not should_send and app_settings.recipient_email:
                report_run.status = "generated_but_not_sent"

            db.commit()
        except Exception as e:
            failure_step = "resend"
            error_msg = f"Resend email failed: {str(e)}"
            logger.error(error_msg)
            errors.append(error_msg)
            report_run.error_message = "; ".join(errors[-3:])
            if run_id:
                add_log(run_id, "error", "email", error_msg, progress=90)
            db.commit()

    except Exception as e:
        if not failure_step:
            failure_step = "unknown"
        error_msg = f"Report generation failed at step '{failure_step}': {str(e)}"
        logger.error(error_msg)
        errors.append(error_msg)
        report_run.status = "failed"
        report_run.error_message = "; ".join(errors[-3:])
        report_run.finished_at = datetime.now(timezone.utc)
        db.commit()

        if run_id:
            add_log(run_id, "error", failure_step, error_msg, progress=100)

        app_settings = db.query(AppSettings).first()
        if app_settings and app_settings.send_failure_report and app_settings.recipient_email:
            try:
                from app.services.email_service import send_report_email

                send_result = send_report_email(
                    settings=settings,
                    to_email=app_settings.recipient_email,
                    subject=f"Inbox FollowUp Report Failed — {today}",
                    html_content=f"<h1>Report Failed</h1><p>Step: {failure_step}</p><p>Error: {error_msg}</p>",
                    text_content=f"Report Failed\nStep: {failure_step}\nError: {error_msg}",
                )
                if send_result.get("success"):
                    report_run.report_sent = True
                    report_run.resend_email_id = send_result.get("email_id")
                    db.commit()
            except Exception as e2:
                logger.error(f"Failed to send failure report: {e2}")

    if run_id:
        add_log(run_id, "success", "complete", f"Report finished: {report_run.status}", progress=100)

    return {
        "status": report_run.status,
        "report_run_id": report_run.id,
        "emails_checked": report_run.emails_checked,
        "errors": errors,
    }
