"""Thin multi-provider wrapper for the app's vision-model calls.

Every AI call in this app (design understanding, the four discipline
specialists, synthesis, and finding localization) funnels through
`call_ai_chat` so provider routing and retry/error handling live in exactly
one place.

Callers always build messages in the OpenAI chat-completions shape (a
`system` message plus a `user` message whose content is text and
`image_url` data-URL parts). Groq, OpenAI, and Gemini accept that shape
directly on their chat-completions endpoints; for Anthropic it's converted
to the Messages API shape and sent through the official `anthropic` SDK.
"""
import logging
import os
import re
import time
from dataclasses import dataclass

import anthropic
import requests
from dotenv import load_dotenv

load_dotenv()

PROVIDERS = ("groq", "openai", "gemini", "anthropic")

PROVIDER_LABELS = {
    "groq": "Groq",
    "openai": "OpenAI",
    "gemini": "Google Gemini",
    "anthropic": "Anthropic",
}

# Chat-completions endpoints for the OpenAI-compatible providers.
CHAT_COMPLETIONS_URLS = {
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "openai": "https://api.openai.com/v1/chat/completions",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
}

# Vision-capable defaults, each overridable per provider from .env or per
# visitor from the Settings page.
DEFAULT_MODELS = {
    "groq": os.environ.get("GROQ_MODEL", "qwen/qwen3.8-27b"),
    "openai": os.environ.get("OPENAI_MODEL", "gpt-5-mini"),
    "gemini": os.environ.get("GEMINI_MODEL", "gemini-flash-latest"),
    "anthropic": os.environ.get("ANTHROPIC_MODEL", "claude-opus-5"),
}

# The per-call token caps callers pass are sized for Groq's tight free-tier
# per-minute quota. OpenAI, Gemini, and Anthropic default models reason
# before answering, and that reasoning counts against the same cap, so they
# get headroom to avoid cutting the visible answer off; the prompts
# themselves keep the answers short.
REASONING_TOKEN_FLOOR = 4096
ANTHROPIC_MAX_TOKENS = 16000

RATE_LIMIT_RETRY_RE = re.compile(r"try again in ([\d.]+)s", re.IGNORECASE)
MAX_RATE_LIMIT_RETRIES = 3

_default_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AIConfig:
    """Which provider, key, and model a critique runs on."""

    provider: str
    api_key: str
    model: str

    @property
    def label(self):
        return PROVIDER_LABELS.get(self.provider, self.provider)


def detect_provider(api_key):
    """Best-effort guess of a key's provider from its well-known prefix, or
    None when the prefix doesn't identify one."""
    key = (api_key or "").strip()
    if key.startswith("sk-ant-"):
        return "anthropic"
    if key.startswith("gsk_"):
        return "groq"
    if key.startswith("AIza"):
        return "gemini"
    if key.startswith("sk-"):
        return "openai"
    return None


def build_ai_config(api_key, provider=None, model=None):
    """Resolve a key plus optional provider/model into an AIConfig. Raises
    ValueError with a user-facing message when the provider can't be
    determined or isn't supported."""
    provider = (provider or "").strip().lower() or detect_provider(api_key)
    if not provider:
        raise ValueError(
            "Couldn't tell which AI provider that key belongs to. Pick the provider next to "
            "your AI API key in Settings."
        )
    if provider not in PROVIDERS:
        raise ValueError(f"Unsupported AI provider '{provider}'. Use one of: {', '.join(PROVIDERS)}.")
    return AIConfig(provider=provider, api_key=api_key, model=(model or "").strip() or DEFAULT_MODELS[provider])


def call_ai_chat(ai, messages, max_completion_tokens, logger=None):
    """Run one chat request on `ai`'s provider. Returns (reply_text,
    error_message) — exactly one of the two is set."""
    if ai.provider == "anthropic":
        return _call_anthropic(ai, messages, logger=logger)
    return _call_chat_completions(ai, messages, max_completion_tokens, logger=logger)


def _call_chat_completions(ai, messages, max_completion_tokens, logger=None, _attempt=1):
    """POST one chat-completion request to an OpenAI-compatible endpoint.

    A full critique makes several calls per request (understanding, up to four
    discipline agents, synthesis, and localization), which makes this app several times
    hungrier for a per-minute token quota than a single-critique design would be,
    and on-demand/free-tier accounts have a fairly tight cap. A 429 there is a
    transient, self-resolving condition — the error message usually says exactly how
    long to wait — so it's worth a bounded retry instead of failing the whole request.
    """
    log = logger or _default_logger
    body = {"model": ai.model, "messages": messages}
    if ai.provider == "groq":
        body["max_completion_tokens"] = max_completion_tokens
    elif ai.provider == "openai":
        body["max_completion_tokens"] = max(max_completion_tokens, REASONING_TOKEN_FLOOR)
    else:  # gemini's OpenAI-compatible endpoint takes max_tokens
        body["max_tokens"] = max(max_completion_tokens, REASONING_TOKEN_FLOOR)

    try:
        resp = requests.post(
            CHAT_COMPLETIONS_URLS[ai.provider],
            headers={"Authorization": f"Bearer {ai.api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=120,
        )
    except requests.exceptions.RequestException as exc:
        return None, f"Could not reach the {ai.label} API: {exc}"

    if resp.status_code >= 400:
        try:
            payload = resp.json()
            if isinstance(payload, list):  # Gemini sometimes wraps errors in a list
                payload = payload[0] if payload else {}
            detail = payload.get("error", {}).get("message", resp.text)
        except (ValueError, AttributeError):
            detail = resp.text

        if resp.status_code == 429 and _attempt <= MAX_RATE_LIMIT_RETRIES:
            match = RATE_LIMIT_RETRY_RE.search(detail)
            wait_s = float(match.group(1)) + 0.5 if match else 2.0 * _attempt
            log.info("%s rate-limited (attempt %s) — retrying in %.1fs", ai.provider, _attempt, wait_s)
            time.sleep(wait_s)
            return _call_chat_completions(ai, messages, max_completion_tokens, logger=logger, _attempt=_attempt + 1)

        return None, f"The AI service ({ai.label}) returned an error: {detail}"

    try:
        text = resp.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        return None, f"The AI service ({ai.label}) returned an unexpected response."
    if not text:
        return None, f"The AI service ({ai.label}) returned an empty reply."
    return text, None


def _to_anthropic_messages(messages):
    """Split OpenAI-shaped messages into Anthropic's (system, messages)."""
    system_parts = []
    converted = []
    for msg in messages:
        if msg["role"] == "system":
            system_parts.append(msg["content"])
            continue
        content = msg["content"]
        if isinstance(content, str):
            converted.append({"role": msg["role"], "content": content})
            continue
        blocks = []
        for part in content:
            if part["type"] == "text":
                blocks.append({"type": "text", "text": part["text"]})
            elif part["type"] == "image_url":
                # data:<mime>;base64,<data>
                header, data = part["image_url"]["url"].split(",", 1)
                media_type = header[len("data:"):].split(";", 1)[0]
                blocks.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": data},
                })
        # Anthropic recommends images before the text that refers to them.
        blocks.sort(key=lambda b: b["type"] != "image")
        converted.append({"role": msg["role"], "content": blocks})
    return "\n\n".join(system_parts), converted


def _call_anthropic(ai, messages, logger=None):
    """Send one request through the Anthropic SDK. The SDK retries 429/5xx
    and connection errors itself."""
    log = logger or _default_logger
    system, converted = _to_anthropic_messages(messages)
    client = anthropic.Anthropic(api_key=ai.api_key, max_retries=3)
    try:
        # Server-side refusal fallbacks: if the model declines, the API re-runs
        # the same request on a fallback model inside this one call.
        response = client.beta.messages.create(
            model=ai.model,
            max_tokens=ANTHROPIC_MAX_TOKENS,
            system=system,
            messages=converted,
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError:
        return None, "The AI service (Anthropic) rejected the API key. Check it in Settings."
    except anthropic.PermissionDeniedError as exc:
        return None, f"The AI service (Anthropic) denied the request: {exc.message}"
    except anthropic.NotFoundError:
        return None, f"The AI service (Anthropic) doesn't recognize the model '{ai.model}'."
    except anthropic.RateLimitError:
        return None, "The AI service (Anthropic) is rate-limiting this key. Wait a minute and try again."
    except anthropic.BadRequestError as exc:
        return None, f"The AI service (Anthropic) returned an error: {exc.message}"
    except anthropic.APIStatusError as exc:
        return None, f"The AI service (Anthropic) returned an error ({exc.status_code}): {exc.message}"
    except anthropic.APIConnectionError as exc:
        return None, f"Could not reach the Anthropic API: {exc}"

    if response.stop_reason == "refusal":
        log.warning("anthropic refused request (%s)", response._request_id)
        return None, "The AI service (Anthropic) declined to critique this design."

    text = "".join(block.text for block in response.content if block.type == "text")
    if not text:
        return None, "The AI service (Anthropic) returned an empty reply."
    if response.stop_reason == "max_tokens":
        log.warning("anthropic reply hit max_tokens (%s)", response._request_id)
    return text, None
