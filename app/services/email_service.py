import logging
from typing import Optional

import requests

from app.config import Settings

logger = logging.getLogger(__name__)


def send_report_email(
    settings: Settings,
    to_email: str,
    subject: str,
    html_content: str,
    text_content: Optional[str] = None,
) -> dict:
    if not settings.RESEND_API_KEY:
        logger.error("Resend API key not configured")
        return {"success": False, "error": "Resend API key not configured"}

    if not settings.RESEND_FROM_EMAIL:
        logger.error("Resend from email not configured")
        return {"success": False, "error": "Resend from email not configured"}

    try:
        payload = {
            "from": settings.RESEND_FROM_EMAIL,
            "to": [to_email],
            "subject": subject,
            "html": html_content,
        }
        if text_content:
            payload["text"] = text_content

        headers = {
            "Authorization": f"Bearer {settings.RESEND_API_KEY}",
            "Content-Type": "application/json",
        }

        resp = requests.post(
            "https://api.resend.com/emails",
            json=payload,
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        email_id = data.get("id", "")
        logger.info(f"Report email sent successfully: {email_id}")
        return {"success": True, "email_id": email_id}
    except requests.RequestException as e:
        error_msg = f"Resend API request failed: {str(e)}"
        logger.error(error_msg)
        return {"success": False, "error": error_msg}
    except Exception as e:
        error_msg = f"Failed to send email via Resend: {str(e)}"
        logger.error(error_msg)
        return {"success": False, "error": error_msg}
