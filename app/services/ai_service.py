import json
import logging
from typing import Optional

import requests

from app.config import Settings

logger = logging.getLogger(__name__)


SINGLE_SYSTEM_PROMPT = """You are an email analysis assistant. Analyze the email and return a JSON object with these fields:
- category: one of "job_opportunity", "client", "meeting", "invoice", "newsletter", "spam", "personal", "support", "unknown"
- priority: one of "high", "medium", "low"
- priority_score: integer 0-10
- needs_reply: boolean
- needs_follow_up: boolean
- meeting_detected: boolean
- deadline_detected: boolean
- summary: brief 1-2 sentence summary
- recommended_action: clear next action
- suggested_reply: short reply draft or empty string
- reason: why this priority/action was selected

Return ONLY valid JSON, no additional text."""


BATCH_SYSTEM_PROMPT = """You are an email batch analysis assistant. Analyze ALL the emails below and return a JSON ARRAY of objects.
Each object must have these fields:
- index: the email number (starting from 0)
- category: one of "job_opportunity", "client", "meeting", "invoice", "newsletter", "spam", "personal", "support", "unknown"
- priority: one of "high", "medium", "low"
- priority_score: integer 0-10
- needs_reply: boolean
- needs_follow_up: boolean
- meeting_detected: boolean
- deadline_detected: boolean
- summary: brief 1-2 sentence summary
- recommended_action: clear next action
- suggested_reply: short reply draft or empty string
- reason: why this priority/action was selected

Return ONLY a valid JSON array, no additional text."""


def call_nvidia_api(payload: dict, settings: Settings) -> Optional[dict]:
    if not settings.NVIDIA_API_KEY:
        return None
    try:
        headers = {
            "Authorization": f"Bearer {settings.NVIDIA_API_KEY}",
            "Content-Type": "application/json",
        }
        resp = requests.post(
            settings.NVIDIA_BASE_URL,
            json=payload,
            headers=headers,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return content
    except Exception as e:
        logger.error(f"NVIDIA AI call failed: {e}")
        return None


def call_openrouter_api(payload: dict, settings: Settings) -> Optional[dict]:
    if not settings.OPENROUTER_API_KEY:
        return None
    try:
        headers = {
            "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        }
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return content
    except Exception as e:
        logger.error(f"OpenRouter AI call failed: {e}")
        return None


def call_ai(payload: dict, settings: Settings, provider: str) -> Optional[dict]:
    if provider == "nvidia":
        return call_nvidia_api(payload, settings)
    elif provider == "openrouter":
        return call_openrouter_api(payload, settings)
    return None


def parse_single_response(content: str) -> Optional[dict]:
    try:
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        result = json.loads(content)
        return {
            "category": result.get("category", "unknown"),
            "priority": result.get("priority", "low"),
            "priority_score": result.get("priority_score", 0),
            "needs_reply": bool(result.get("needs_reply", False)),
            "needs_follow_up": bool(result.get("needs_follow_up", False)),
            "meeting_detected": bool(result.get("meeting_detected", False)),
            "deadline_detected": bool(result.get("deadline_detected", False)),
            "summary": result.get("summary", ""),
            "recommended_action": result.get("recommended_action", ""),
            "suggested_reply": result.get("suggested_reply", ""),
            "reason": result.get("reason", ""),
        }
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning(f"Failed to parse single AI response: {e}")
        return None


def parse_batch_response(content: str, email_count: int) -> Optional[list]:
    try:
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        results = json.loads(content)
        if not isinstance(results, list):
            logger.warning("Batch response is not a list")
            return None

        parsed = []
        for item in results:
            parsed.append({
                "index": item.get("index", len(parsed)),
                "category": item.get("category", "unknown"),
                "priority": item.get("priority", "low"),
                "priority_score": item.get("priority_score", 0),
                "needs_reply": bool(item.get("needs_reply", False)),
                "needs_follow_up": bool(item.get("needs_follow_up", False)),
                "meeting_detected": bool(item.get("meeting_detected", False)),
                "deadline_detected": bool(item.get("deadline_detected", False)),
                "summary": item.get("summary", ""),
                "recommended_action": item.get("recommended_action", ""),
                "suggested_reply": item.get("suggested_reply", ""),
                "reason": item.get("reason", ""),
            })
        return parsed
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning(f"Failed to parse batch AI response: {e}")
        return None


def batch_analyze_emails(
    emails: list,
    settings: Settings,
    ai_provider: str = "nvidia",
) -> Optional[list]:
    if not emails:
        return []

    email_texts = []
    for i, email in enumerate(emails):
        email_texts.append(
            f"[Email {i}]\nFrom: {email.get('sender', '')}\nSubject: {email.get('subject', '')}\nSnippet: {email.get('snippet', '')[:300]}\nBody: {email.get('body_preview', '')[:500]}"
        )

    user_content = f"Analyze these {len(emails)} emails and return a JSON array:\n\n" + "\n\n".join(email_texts)

    payload = {
        "model": settings.NVIDIA_MODEL if ai_provider == "nvidia" else settings.OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": BATCH_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.1,
        "max_tokens": 4096,
    }

    result = None
    used_provider = "none"

    if ai_provider == "nvidia":
        content = call_nvidia_api(payload, settings)
        if content:
            result = parse_batch_response(content, len(emails))
            if result:
                used_provider = "nvidia"
        if not result and settings.OPENROUTER_API_KEY:
            logger.info("NVIDIA batch failed, trying OpenRouter")
            content = call_openrouter_api(payload, settings)
            if content:
                result = parse_batch_response(content, len(emails))
                if result:
                    used_provider = "openrouter"
    elif ai_provider == "openrouter":
        content = call_openrouter_api(payload, settings)
        if content:
            result = parse_batch_response(content, len(emails))
            if result:
                used_provider = "openrouter"
        if not result and settings.NVIDIA_API_KEY:
            logger.info("OpenRouter batch failed, trying NVIDIA")
            content = call_nvidia_api(payload, settings)
            if content:
                result = parse_batch_response(content, len(emails))
                if result:
                    used_provider = "nvidia"

    if result:
        for r in result:
            r["_analysis_method"] = "ai"
            r["_used_provider"] = used_provider
        return result
    return None


def analyze_email_rule_based(email: dict) -> dict:
    sender = (email.get("sender", "") or "").lower()
    subject = (email.get("subject", "") or "").lower()
    snippet = (email.get("snippet", "") or "").lower()
    body = (email.get("body_preview", "") or "").lower()
    text = f"{subject} {snippet} {body}"

    category = "unknown"
    priority = "low"
    priority_score = 0
    needs_reply = False
    needs_follow_up = False
    meeting_detected = False
    deadline_detected = False
    summary = email.get("snippet", "")[:100]
    recommended_action = "Review email"
    suggested_reply = ""
    reason = "Rule-based analysis"

    if any(w in subject for w in ["invoice", "billing", "payment", "receipt"]):
        category = "invoice"
        priority = "high"
        priority_score = 7
        needs_reply = True
        recommended_action = "Review and process invoice"
        reason = "Invoice-related email detected"
    elif any(w in subject for w in ["meeting", "calendar", "invite", "schedule"]):
        category = "meeting"
        priority = "high"
        priority_score = 7
        meeting_detected = True
        needs_reply = True
        recommended_action = "Check calendar and respond"
        reason = "Meeting-related email detected"
    elif any(w in subject for w in ["job", "interview", "hiring", "offer", "recruit"]):
        category = "job_opportunity"
        priority = "high"
        priority_score = 8
        needs_reply = True
        recommended_action = "Respond to job opportunity"
        reason = "Job opportunity detected"
    elif any(w in subject for w in ["unsubscribe", "newsletter", "weekly"]):
        category = "newsletter"
        priority = "low"
        priority_score = 1
        recommended_action = "Read when free or unsubscribe"
        reason = "Newsletter detected"
    elif any(w in text for w in ["urgent", "asap", "deadline", "due date"]):
        priority = "high"
        priority_score = 9
        needs_reply = True
        deadline_detected = True
        recommended_action = "Urgent - respond immediately"
        reason = "Urgent keywords detected"
    elif any(w in sender for w in ["support", "help"]):
        category = "support"
        priority = "medium"
        priority_score = 5
        needs_reply = True
        recommended_action = "Provide support response"
        reason = "Support email detected"
    elif any(w in subject for w in ["hello", "hi", "thank", "regarding", "question"]):
        category = "personal"
        priority = "medium"
        priority_score = 4
        needs_reply = True
        recommended_action = "Respond to personal email"
        reason = "Personal email detected"
    elif any(w in subject for w in ["client", "project", "proposal"]):
        category = "client"
        priority = "high"
        priority_score = 8
        needs_reply = True
        recommended_action = "Respond to client"
        reason = "Client-related email detected"

    return {
        "category": category,
        "priority": priority,
        "priority_score": priority_score,
        "needs_reply": needs_reply,
        "needs_follow_up": needs_follow_up,
        "meeting_detected": meeting_detected,
        "deadline_detected": deadline_detected,
        "summary": summary,
        "recommended_action": recommended_action,
        "suggested_reply": suggested_reply,
        "reason": reason,
    }


def analyze_email(
    email: dict, settings: Settings, use_suggested_replies: bool = True, ai_provider: str = "nvidia"
) -> dict:
    result = None
    used_provider = "none"

    payload = {
        "model": settings.NVIDIA_MODEL if ai_provider == "nvidia" else settings.OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": SINGLE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Analyze this email:\nFrom: {email.get('sender', '')}\nSubject: {email.get('subject', '')}\nSnippet: {email.get('snippet', '')}\nBody: {email.get('body_preview', '')[:800]}",
            },
        ],
        "temperature": 0.1,
        "max_tokens": 600,
    }

    if ai_provider == "nvidia":
        content = call_nvidia_api(payload, settings)
        if content:
            result = parse_single_response(content)
            if result:
                used_provider = "nvidia"
        if not result and settings.OPENROUTER_API_KEY:
            logger.info("NVIDIA failed, trying OpenRouter fallback")
            content = call_openrouter_api(payload, settings)
            if content:
                result = parse_single_response(content)
                if result:
                    used_provider = "openrouter"
    elif ai_provider == "openrouter":
        content = call_openrouter_api(payload, settings)
        if content:
            result = parse_single_response(content)
            if result:
                used_provider = "openrouter"
        if not result and settings.NVIDIA_API_KEY:
            logger.info("OpenRouter failed, trying NVIDIA fallback")
            content = call_nvidia_api(payload, settings)
            if content:
                result = parse_single_response(content)
                if result:
                    used_provider = "nvidia"

    if not result:
        logger.warning("All AI providers failed, using rule-based fallback")
        result = analyze_email_rule_based(email)
        result["_analysis_method"] = "rule_based"
    else:
        result["_analysis_method"] = "ai"

    result["_used_provider"] = used_provider

    if not use_suggested_replies:
        result["suggested_reply"] = ""

    return result
