import json
import logging
import time
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


def _call_with_retry(url: str, payload: dict, headers: dict, timeout: int, max_retries: int = 3) -> Optional[str]:
    for attempt in range(max_retries):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
            if resp.status_code == 429:
                wait = (attempt + 1) * 2
                logger.warning(f"Rate limited (429), retrying in {wait}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                wait = (attempt + 1) * 3
                logger.warning(f"Timeout, retrying in {wait}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait)
                continue
            logger.error(f"NVIDIA AI call timed out after {max_retries} attempts")
            return None
        except Exception as e:
            logger.error(f"NVIDIA AI call failed: {e}")
            return None
    return None


def call_nvidia_api(payload: dict, settings: Settings, timeout: int = 120) -> Optional[str]:
    if not settings.NVIDIA_API_KEY:
        return None
    headers = {
        "Authorization": f"Bearer {settings.NVIDIA_API_KEY}",
        "Content-Type": "application/json",
    }
    return _call_with_retry(settings.NVIDIA_BASE_URL, payload, headers, timeout)


def call_openrouter_api(payload: dict, settings: Settings, timeout: int = 120) -> Optional[dict]:
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
            timeout=timeout,
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


def _call_batch_api(
    email_chunk: list,
    chunk_index: int,
    settings: Settings,
    ai_provider: str,
) -> Optional[list]:
    email_texts = []
    for i, email in enumerate(email_chunk):
        idx = chunk_index + i
        email_texts.append(
            f"[Email {idx}]\nFrom: {email.get('sender', '')}\nSubject: {email.get('subject', '')}\nSnippet: {email.get('snippet', '')[:300]}\nBody: {email.get('body_preview', '')[:500]}"
        )

    user_content = f"Analyze these {len(email_chunk)} emails and return a JSON array:\n\n" + "\n\n".join(email_texts)

    payload = {
        "model": settings.NVIDIA_MODEL if ai_provider == "nvidia" else settings.OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": BATCH_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.1,
        "max_tokens": 4096,
    }

    if ai_provider == "nvidia":
        content = call_nvidia_api(payload, settings)
        if content:
            result = parse_batch_response(content, len(email_chunk))
            if result:
                return result
        if not content and settings.OPENROUTER_API_KEY:
            logger.info("NVIDIA chunk failed, trying OpenRouter")
            content = call_openrouter_api(payload, settings)
            if content:
                result = parse_batch_response(content, len(email_chunk))
                if result:
                    return result
    elif ai_provider == "openrouter":
        content = call_openrouter_api(payload, settings)
        if content:
            result = parse_batch_response(content, len(email_chunk))
            if result:
                return result
        if not content and settings.NVIDIA_API_KEY:
            logger.info("OpenRouter chunk failed, trying NVIDIA")
            content = call_nvidia_api(payload, settings)
            if content:
                result = parse_batch_response(content, len(email_chunk))
                if result:
                    return result
    return None


def batch_analyze_emails(
    emails: list,
    settings: Settings,
    ai_provider: str = "nvidia",
) -> Optional[list]:
    if not emails:
        return []

    CHUNK_SIZE = 5
    CHUNK_DELAY = 1.5
    all_results = []
    total_chunks = (len(emails) + CHUNK_SIZE - 1) // CHUNK_SIZE

    for chunk_idx in range(total_chunks):
        start = chunk_idx * CHUNK_SIZE
        end = min(start + CHUNK_SIZE, len(emails))
        chunk = emails[start:end]

        logger.info(f"AI batch chunk {chunk_idx + 1}/{total_chunks} ({len(chunk)} emails)")
        result = _call_batch_api(chunk, start, settings, ai_provider)

        if result:
            all_results.extend(result)
        else:
            logger.warning(f"AI chunk {chunk_idx + 1} failed, using rule-based fallback for these {len(chunk)} emails")
            for i, email in enumerate(chunk):
                rule_result = analyze_email_rule_based(email)
                rule_result["index"] = start + i
                rule_result["_analysis_method"] = "rule_based"
                all_results.append(rule_result)

        if chunk_idx < total_chunks - 1:
            time.sleep(CHUNK_DELAY)

    if all_results:
        for r in all_results:
            if "_analysis_method" not in r:
                r["_analysis_method"] = "ai"
        return all_results
    return None


_MARKETING_DOMAINS = [
    "marketing", "newsletter", "mailer", "mail.brighttalk", "mail.codecademy",
    "mail.health.harvard", "itr.mail.codecademy", "email.snapchat",
    "vanillaforums.email", "ideas.pinterest", "mail.boot.dev",
]


_IMPORTANT_DOMAINS = ["linkedin.com", "github.com", "try-iii.com"]


def _is_marketing_email(sender: str) -> bool:
    idx = sender.lower().find("@")
    if idx == -1:
        return False
    domain = sender.lower()[idx + 1:]
    if any(domain == d or domain.endswith("." + d) for d in _IMPORTANT_DOMAINS):
        return False
    for m in _MARKETING_DOMAINS:
        if m in domain:
            return True
    local = sender.lower()[:idx]
    if any(p in local for p in ["noreply", "no-reply", "no_reply"]):
        return True
    return False


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

    is_marketing = _is_marketing_email(sender)

    meeting_urls = ["meet.google.com", "zoom.us/j/", "teams.microsoft.com/meet", "calendar.google.com", "calendly.com"]
    meeting_phrases = ["join us for", "meeting invite", "calendar invite", "meeting link", "standup", "stand-up", "catch up", "get together", "daily stand", "weekly sync"]
    meeting_keywords = ["meeting", "calendar", "invite", "schedule"]

    has_personal_meeting_url = any(u in text for u in meeting_urls)
    has_meeting_subject = any(w in subject for w in meeting_keywords)
    has_meeting_phrase = any(p in text for p in meeting_phrases)

    if any(w in subject for w in ["invoice", "billing", "payment", "receipt"]):
        category = "invoice"
        priority = "high"
        priority_score = 7
        needs_reply = True
        recommended_action = "Review and process invoice"
        reason = "Invoice-related email detected"
    elif has_personal_meeting_url:
        category = "meeting"
        priority = "high"
        priority_score = 8
        meeting_detected = True
        needs_reply = True
        recommended_action = "Join the meeting"
        reason = "Personal meeting link detected"
    elif has_meeting_subject and not is_marketing:
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
