"""Thin wrapper around Groq's chat-completions API.

Every AI call in this app (design understanding, the four discipline
specialists, synthesis, and finding localization) funnels through
`call_groq_chat` so retry/error handling lives in exactly one place.
"""
import logging
import os
import re
import time

import requests
from dotenv import load_dotenv

load_dotenv()

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = os.environ.get("GROQ_MODEL", "qwen/qwen3.8-27b")

RATE_LIMIT_RETRY_RE = re.compile(r"try again in ([\d.]+)s", re.IGNORECASE)
MAX_RATE_LIMIT_RETRIES = 3

_default_logger = logging.getLogger(__name__)


def call_groq_chat(api_key, messages, max_completion_tokens, logger=None, _attempt=1):
    """POST one chat-completion request to Groq. Returns (reply_text, error_message) —
    exactly one of the two is set.

    A full critique makes several Groq calls per request (understanding, up to four
    discipline agents, synthesis, and localization), which makes this app several times
    hungrier for Groq's per-minute token quota than a single-critique design would be,
    and on-demand/free-tier accounts have a fairly tight cap. A 429 there is a
    transient, self-resolving condition — Groq's own error message tells us exactly how
    long to wait — so it's worth a bounded retry instead of failing the whole request.
    """
    log = logger or _default_logger
    try:
        resp = requests.post(
            GROQ_API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": GROQ_MODEL,
                "max_completion_tokens": max_completion_tokens,
                "messages": messages,
            },
            timeout=60,
        )
    except requests.exceptions.RequestException as exc:
        return None, f"Could not reach the Groq API: {exc}"

    if resp.status_code >= 400:
        try:
            detail = resp.json().get("error", {}).get("message", resp.text)
        except ValueError:
            detail = resp.text

        if resp.status_code == 429 and _attempt <= MAX_RATE_LIMIT_RETRIES:
            match = RATE_LIMIT_RETRY_RE.search(detail)
            wait_s = float(match.group(1)) + 0.5 if match else 2.0 * _attempt
            log.info("groq rate-limited (attempt %s) — retrying in %.1fs", _attempt, wait_s)
            time.sleep(wait_s)
            return call_groq_chat(api_key, messages, max_completion_tokens, logger=logger, _attempt=_attempt + 1)

        return None, f"The AI service returned an error: {detail}"

    return resp.json()["choices"][0]["message"]["content"], None
