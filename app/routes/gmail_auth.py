import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import get_db
from app.models import GmailConnection
from app.services.gmail_service import get_auth_url, exchange_code, get_user_email, build_gmail_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/gmail")
settings = Settings()


@router.get("/connect")
async def gmail_connect():
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=400,
            detail="Google OAuth not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env",
        )
    auth_url = get_auth_url(settings)
    return {"auth_url": auth_url}


@router.get("/callback")
async def gmail_callback(code: str = Query(""), db: Session = Depends(get_db)):
    if not code:
        raise HTTPException(status_code=400, detail="No authorization code provided")

    token_data = exchange_code(settings, code)
    if not token_data:
        raise HTTPException(status_code=400, detail="Failed to exchange authorization code")

    try:
        expiry = None
        if token_data.get("token_expiry"):
            try:
                expiry = datetime.fromisoformat(token_data["token_expiry"])
            except (ValueError, TypeError):
                expiry = None

        existing = db.query(GmailConnection).first()
        if existing:
            existing.access_token = token_data["access_token"]
            if token_data.get("refresh_token"):
                existing.refresh_token = token_data["refresh_token"]
            existing.token_expiry = expiry
            existing.scopes = token_data.get("scopes", "")
            existing.status = "connected"
            existing.updated_at = datetime.now(timezone.utc)

            service = build_gmail_service(
                token_data["access_token"],
                token_data.get("refresh_token", existing.refresh_token),
                settings.GOOGLE_CLIENT_ID,
                settings.GOOGLE_CLIENT_SECRET,
            )
            user_email = get_user_email(service)
            if user_email:
                existing.google_email = user_email
        else:
            service = build_gmail_service(
                token_data["access_token"],
                token_data.get("refresh_token", ""),
                settings.GOOGLE_CLIENT_ID,
                settings.GOOGLE_CLIENT_SECRET,
            )
            user_email = get_user_email(service)

            conn = GmailConnection(
                google_email=user_email or "",
                access_token=token_data["access_token"],
                refresh_token=token_data.get("refresh_token", ""),
                token_expiry=expiry,
                scopes=token_data.get("scopes", ""),
                status="connected",
            )
            db.add(conn)

        db.commit()
    except Exception as e:
        logger.error(f"Failed to save Gmail connection: {e}")
        raise HTTPException(status_code=500, detail="Failed to save Gmail connection")

    return RedirectResponse(url="/", status_code=302)


@router.get("/status")
async def gmail_status(db: Session = Depends(get_db)):
    gmail = db.query(GmailConnection).first()
    if not gmail or gmail.status != "connected":
        return {"connected": False}
    return {
        "connected": True,
        "google_email": gmail.google_email,
        "connected_at": gmail.connected_at.isoformat() if gmail.connected_at else None,
    }


@router.post("/disconnect")
async def gmail_disconnect(db: Session = Depends(get_db)):
    gmail = db.query(GmailConnection).first()
    if gmail:
        gmail.status = "disconnected"
        gmail.access_token = ""
        gmail.updated_at = datetime.now(timezone.utc)
        db.commit()
    return {"success": True}
