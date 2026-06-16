from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Boolean,
    DateTime,
    Date,
    ForeignKey,
)
from sqlalchemy.orm import relationship

from app.database import Base


class AppSettings(Base):
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, index=True)
    recipient_email = Column(String(255), nullable=False, default="")
    report_time = Column(String(10), nullable=False, default="08:00")
    timezone = Column(String(50), nullable=False, default="Asia/Karachi")
    email_filter_type = Column(String(50), nullable=False, default="today_unread")
    custom_query = Column(Text, nullable=True, default="")
    max_emails = Column(Integer, nullable=False, default=50)
    ai_provider = Column(String(50), nullable=False, default="nvidia")
    ai_model = Column(String(100), nullable=False, default="")
    include_suggested_replies = Column(Boolean, default=True)
    include_meeting_detection = Column(Boolean, default=True)
    send_success_report = Column(Boolean, default=True)
    send_failure_report = Column(Boolean, default=True)
    allow_override = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class GmailConnection(Base):
    __tablename__ = "gmail_connections"

    id = Column(Integer, primary_key=True, index=True)
    google_email = Column(String(255), nullable=False, default="")
    access_token = Column(Text, nullable=False, default="")
    refresh_token = Column(Text, nullable=False, default="")
    token_expiry = Column(DateTime, nullable=True)
    scopes = Column(Text, nullable=False, default="")
    status = Column(String(50), nullable=False, default="disconnected")
    connected_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ReportRun(Base):
    __tablename__ = "report_runs"

    id = Column(Integer, primary_key=True, index=True)
    run_date = Column(Date, nullable=False)
    status = Column(
        String(50),
        nullable=False,
        default="running",
    )
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    finished_at = Column(DateTime, nullable=True)
    emails_checked = Column(Integer, default=0)
    high_priority_count = Column(Integer, default=0)
    needs_reply_count = Column(Integer, default=0)
    follow_up_count = Column(Integer, default=0)
    meeting_count = Column(Integer, default=0)
    deadline_count = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    report_sent = Column(Boolean, default=False)
    resend_email_id = Column(String(255), nullable=True)
    markdown_report = Column(Text, nullable=True)
    html_report = Column(Text, nullable=True)
    json_summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    analyses = relationship(
        "EmailAnalysis",
        back_populates="report_run",
        cascade="all, delete-orphan",
    )


class EmailAnalysis(Base):
    __tablename__ = "email_analyses"

    id = Column(Integer, primary_key=True, index=True)
    report_run_id = Column(
        Integer,
        ForeignKey("report_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    gmail_message_id = Column(String(100), nullable=False)
    thread_id = Column(String(100), nullable=True)
    sender = Column(String(255), nullable=True)
    subject = Column(Text, nullable=True)
    email_date = Column(DateTime, nullable=True)
    snippet = Column(Text, nullable=True)
    category = Column(String(50), nullable=False, default="unknown")
    priority = Column(String(20), nullable=False, default="low")
    priority_score = Column(Integer, default=0)
    needs_reply = Column(Boolean, default=False)
    needs_follow_up = Column(Boolean, default=False)
    meeting_detected = Column(Boolean, default=False)
    deadline_detected = Column(Boolean, default=False)
    summary = Column(Text, nullable=True)
    recommended_action = Column(Text, nullable=True)
    suggested_reply = Column(Text, nullable=True)
    reason = Column(Text, nullable=True)
    raw_ai_response = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    report_run = relationship("ReportRun", back_populates="analyses")


class JobLock(Base):
    __tablename__ = "job_locks"

    id = Column(Integer, primary_key=True, index=True)
    job_name = Column(String(100), unique=True, nullable=False)
    locked_until = Column(DateTime, nullable=False)
    status = Column(String(50), nullable=False, default="locked")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
