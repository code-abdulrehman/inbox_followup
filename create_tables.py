#!/usr/bin/env python3
"""
Create all database tables for Inbox FollowUp.
Run this after setting up PostgreSQL and creating the database.
Usage: python create_tables.py
"""
from app.database import engine, Base
from app.models import AppSettings, GmailConnection, ReportRun, EmailAnalysis, JobLock

if __name__ == "__main__":
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("Tables created successfully!")
    print("Tables: app_settings, gmail_connections, report_runs, email_analyses, job_locks")
