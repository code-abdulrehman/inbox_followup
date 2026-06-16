import logging
import pickle
from datetime import datetime, timezone, timedelta
from typing import Optional

import google.auth.transport.requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import Settings

logger = logging.getLogger(__name__)


SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def get_google_flow(settings: Settings) -> Flow:
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
            }
        },
        scopes=SCOPES,
    )
    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI
    return flow


def get_auth_url(settings: Settings) -> str:
    flow = get_google_flow(settings)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
    )
    return auth_url


def exchange_code(settings: Settings, code: str) -> Optional[dict]:
    try:
        flow = get_google_flow(settings)
        flow.fetch_token(code=code)
        credentials = flow.credentials
        return {
            "access_token": credentials.token,
            "refresh_token": credentials.refresh_token or "",
            "token_expiry": credentials.expiry.isoformat() if credentials.expiry else None,
            "scopes": " ".join(credentials.scopes),
        }
    except Exception as e:
        logger.error(f"Failed to exchange auth code: {e}")
        return None


def refresh_access_token(
    refresh_token: str,
    client_id: str,
    client_secret: str,
) -> Optional[str]:
    try:
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=SCOPES,
        )
        creds.refresh(Request())
        return creds.token
    except Exception as e:
        logger.error(f"Failed to refresh access token: {e}")
        return None


def build_gmail_service(access_token: str, refresh_token_value: str, client_id: str, client_secret: str):
    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token_value,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("gmail", "v1", credentials=creds)


def get_user_email(service) -> Optional[str]:
    try:
        profile = service.users().getProfile(userId="me").execute()
        return profile.get("emailAddress")
    except HttpError as e:
        logger.error(f"Failed to get user email: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error getting user email: {e}")
        return None


def build_gmail_query(filter_type: str, custom_query: str = "", exclude_email: str = "") -> str:
    today = datetime.now(timezone.utc)
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)
    today_str = today.strftime("%Y/%m/%d")
    yesterday_str = yesterday.strftime("%Y/%m/%d")
    tomorrow_str = tomorrow.strftime("%Y/%m/%d")

    if filter_type == "today_all":
        query = f"after:{yesterday_str} before:{tomorrow_str}"
    elif filter_type == "today_unread":
        query = f"after:{yesterday_str} before:{tomorrow_str} is:unread"
    elif filter_type == "today_read":
        query = f"after:{yesterday_str} before:{tomorrow_str} -is:unread"
    elif filter_type == "important":
        query = f"after:{yesterday_str} is:important"
    elif filter_type == "starred":
        query = f"after:{yesterday_str} is:starred"
    elif filter_type == "custom_query":
        query = custom_query
    else:
        query = f"after:{yesterday_str} is:unread"

    if exclude_email:
        query = f"{query} -from:{exclude_email}"

    return query


def fetch_emails(service, query: str, max_results: int = 50) -> list:
    emails = []
    try:
        result = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        messages = result.get("messages", [])
        for msg in messages:
            try:
                msg_data = (
                    service.users()
                    .messages()
                    .get(userId="me", id=msg["id"], format="metadata")
                    .execute()
                )
                headers = {h["name"].lower(): h["value"] for h in msg_data.get("payload", {}).get("headers", [])}

                body_preview = get_body_preview(service, msg["id"])

                email = {
                    "message_id": msg["id"],
                    "thread_id": msg_data.get("threadId", ""),
                    "sender": headers.get("from", ""),
                    "recipients": headers.get("to", ""),
                    "subject": headers.get("subject", "(No Subject)"),
                    "date": headers.get("date", ""),
                    "snippet": msg_data.get("snippet", ""),
                    "body_preview": body_preview,
                    "labels": ",".join(msg_data.get("labelIds", [])),
                    "has_attachments": any(
                        part.get("filename")
                        for part in msg_data.get("payload", {}).get("parts", [])
                        if part.get("filename")
                    ),
                }
                emails.append(email)
            except HttpError as e:
                logger.warning(f"Failed to fetch message {msg['id']}: {e}")
                continue
            except Exception as e:
                logger.warning(f"Unexpected error fetching message {msg['id']}: {e}")
                continue
    except HttpError as e:
        logger.error(f"Failed to list messages: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error listing messages: {e}")
        raise
    return emails


def get_body_preview(service, message_id: str, max_chars: int = 1200) -> str:
    try:
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        payload = msg.get("payload", {})
        parts = payload.get("parts", [])

        text_content = ""
        if parts:
            for part in parts:
                if part.get("mimeType") == "text/plain":
                    data = part.get("body", {}).get("data", "")
                    if data:
                        import base64
                        text_content += base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        else:
            data = payload.get("body", {}).get("data", "")
            if data:
                import base64
                text_content = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

        text_content = text_content.strip()
        if len(text_content) > max_chars:
            text_content = text_content[:max_chars] + "..."

        return text_content
    except Exception as e:
        logger.warning(f"Failed to get body for {message_id}: {e}")
        return ""
