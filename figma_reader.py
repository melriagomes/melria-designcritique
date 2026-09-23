"""Figma Reader — resolves a figma.com file/design/proto/board URL to a static image.

Talks to Figma's REST API directly over HTTPS using a Personal Access Token
(FIGMA_API_TOKEN, sent as the `X-Figma-Token` header). This is a completely
separate credential and code path from any Figma MCP server an AI coding
agent (e.g. inside an editor) might use during development — the two are
never wired together, and this token is never shared with or read by an MCP
client. The token only ever lives server-side: it is read from the
environment and never sent to, or embedded in, anything served to the
browser (index.html makes no Figma calls of its own).

This is one of the three shared building blocks (alongside `screenshot_annotator`
and the specialist/synthesis machinery in `evidence_reporting`) that
`design_reader` and `server.py`'s orchestrator route compose together.
"""
import logging
import os
import re
from urllib.parse import parse_qs

import requests

FIGMA_API_BASE = "https://api.figma.com/v1"
FIGMA_HOSTS = {"figma.com", "www.figma.com"}
FIGMA_PATH_RE = re.compile(r"^/(file|design|proto|board)/([a-zA-Z0-9_-]+)")

_default_logger = logging.getLogger(__name__)


def get_figma_token(override=None):
    """Return the Figma personal access token to use for this request.

    `override` is the visitor's currently-active Settings key (sent with the
    request, never stored server-side), used when the pasted URL is a Figma
    link. It takes priority over the shared server-side .env value, which
    remains the default for anyone who hasn't set one.
    """
    token = override or os.environ.get("FIGMA_API_TOKEN")
    if not token:
        raise RuntimeError(
            "No Figma API token available. Add one in Settings (Figma account settings → Personal "
            "access tokens), or set FIGMA_API_TOKEN in the .env file and restart the server."
        )
    return token


def redact_token(token):
    """Never log or return the actual token — only a shape hint safe to show."""
    if not token:
        return None
    prefix = "figd_" if token.startswith("figd_") else token[:4] + "…" if len(token) > 4 else "…"
    return f"{prefix}(redacted, {len(token)} chars)"


def figma_error_detail(resp):
    """Pull Figma's own (non-secret) error message out of a response, if present."""
    try:
        body = resp.json()
    except ValueError:
        return None
    return body.get("message") or body.get("err")


def classify_figma_error(status_code, detail=None, used_own_token=False):
    """Map a Figma REST API status code to (log_label, user_facing_message).

    Never includes the token. `detail` is Figma's own response message (safe —
    it describes scopes/permissions, not credentials) and is appended when present.

    `used_own_token` distinguishes a visitor's own Settings key from this
    app's shared fallback token — the actionable advice for a 403 is
    different for each, since a Figma token (personal or shared) can only
    ever see files its owning account has access to.
    """
    if status_code == 401:
        label = "auth"
        msg = "Figma rejected the token as invalid, revoked, or malformed (HTTP 401)."
    elif status_code == 403:
        label = "permission"
        if used_own_token:
            msg = (
                "Figma denied access with your token (HTTP 403). If Figma's message below says "
                "\"Invalid token\", re-check that you copied the whole token with no missing or extra "
                "characters — re-paste it in Settings if unsure. Otherwise, check that the token has the "
                "\"File content\" read-only scope, and — if you created it through Figma's current token "
                "screen — that this file (or its project) was explicitly added to the token's file access "
                "list, since scoped tokens only see files you've granted them."
            )
        else:
            msg = (
                "This app's shared Figma token can't access this file (HTTP 403) — expected for any file "
                "it doesn't own, since a Figma token only sees what its owning account can see. To "
                "critique your own Figma file, open Settings, add your own Figma personal access token "
                "(tap the ⓘ next to \"Figma API keys\" for how), mark it active, then paste the link again."
            )
    elif status_code == 404:
        label = "not_found"
        msg = "Figma couldn't find that file (HTTP 404) — double-check the file key in the URL."
    elif status_code == 429:
        label = "rate_limit"
        msg = "Figma rate-limited this request (HTTP 429) — wait a moment and try again."
    elif status_code >= 500:
        label = "figma_outage"
        msg = f"Figma's API returned a server error (HTTP {status_code}) — try again shortly."
    else:
        label = "unknown"
        msg = f"Figma API returned HTTP {status_code}."

    if detail:
        msg = f"{msg} Figma says: {detail}"
    return label, msg


def log_figma_error(context, resp, used_own_token=False, logger=None):
    """Log a Figma API failure server-side with full (non-secret) detail, and
    return the safe, classified message to show the user."""
    log = logger or _default_logger
    detail = figma_error_detail(resp)
    label, user_msg = classify_figma_error(resp.status_code, detail, used_own_token=used_own_token)
    log.warning(
        "figma api error: context=%s status=%s label=%s endpoint=%s detail=%s",
        context, resp.status_code, label, resp.url, detail,
    )
    return user_msg


def figma_diagnostics(file_key=None):
    """Safe, read-only diagnostic for the Figma REST integration.

    Checks (1) whether FIGMA_API_TOKEN is set, (2) which Figma account it
    authenticates as (if the token's scopes allow that lookup), and (3)
    whether a specific file_key is accessible with it. Never includes the
    token itself — only a redacted shape hint. Intended for server-side
    debugging (logs, or the `--figma-diagnose` CLI in server.py), never
    returned to a browser client.
    """
    token = os.environ.get("FIGMA_API_TOKEN")
    result = {
        "token_present": bool(token),
        "token_redacted": redact_token(token),
        "authenticated_account": None,
        "file_access": None,
    }
    if not token:
        return result

    headers = {"X-Figma-Token": token}

    try:
        me_resp = requests.get(f"{FIGMA_API_BASE}/me", headers=headers, timeout=10)
    except requests.exceptions.RequestException as exc:
        result["authenticated_account"] = f"unavailable ({exc.__class__.__name__})"
    else:
        if me_resp.status_code == 200:
            me = me_resp.json()
            result["authenticated_account"] = {"email": me.get("email"), "handle": me.get("handle")}
        else:
            label, _ = classify_figma_error(me_resp.status_code, figma_error_detail(me_resp))
            result["authenticated_account"] = (
                f"unavailable (HTTP {me_resp.status_code}, {label} — this token may not carry the "
                "current_user:read scope, which is unrelated to file-reading access)"
            )

    if file_key:
        try:
            file_resp = requests.get(
                f"{FIGMA_API_BASE}/files/{file_key}", headers=headers, params={"depth": 1}, timeout=10
            )
        except requests.exceptions.RequestException as exc:
            result["file_access"] = f"unavailable ({exc.__class__.__name__})"
        else:
            if file_resp.status_code == 200:
                result["file_access"] = "ok"
            else:
                label, _ = classify_figma_error(file_resp.status_code, figma_error_detail(file_resp))
                result["file_access"] = f"denied (HTTP {file_resp.status_code}, {label})"

    return result


def parse_figma_url(parsed):
    """Return (file_key, node_id) for a figma.com file/design/proto/board URL, else None.

    `node-id` in the URL uses a hyphen (e.g. "12-34"); the REST API expects a colon
    ("12:34"), so it's translated here.
    """
    if parsed.netloc.lower() not in FIGMA_HOSTS:
        return None
    match = FIGMA_PATH_RE.match(parsed.path)
    if not match:
        return None

    file_key = match.group(2)
    node_id = None
    raw_node_id = parse_qs(parsed.query).get("node-id", [None])[0]
    if raw_node_id:
        node_id = raw_node_id.replace("-", ":", 1) if ":" not in raw_node_id else raw_node_id
    return file_key, node_id


def resolve_figma_url_to_image(file_key, node_id, figma_token_override=None, logger=None):
    try:
        token = get_figma_token(figma_token_override)
    except RuntimeError as exc:
        return None, None, str(exc)

    used_own_token = bool(figma_token_override)
    headers = {"X-Figma-Token": token}

    if not node_id:
        try:
            file_resp = requests.get(
                f"{FIGMA_API_BASE}/files/{file_key}",
                headers=headers,
                params={"depth": 1},
                timeout=15,
            )
        except requests.exceptions.RequestException as exc:
            return None, None, f"Could not reach the Figma API: {exc}"
        if file_resp.status_code >= 400:
            return None, None, log_figma_error(
                f"files/{file_key}", file_resp, used_own_token=used_own_token, logger=logger
            )
        pages = file_resp.json().get("document", {}).get("children", [])
        if not pages:
            return None, None, "That Figma file has no pages to render."
        node_id = pages[0]["id"]

    try:
        image_resp = requests.get(
            f"{FIGMA_API_BASE}/images/{file_key}",
            headers=headers,
            params={"ids": node_id, "format": "png", "scale": 2},
            timeout=20,
        )
    except requests.exceptions.RequestException as exc:
        return None, None, f"Could not reach the Figma API: {exc}"

    if image_resp.status_code >= 400:
        return None, None, log_figma_error(
            f"images/{file_key}", image_resp, used_own_token=used_own_token, logger=logger
        )

    payload = image_resp.json()
    if payload.get("err"):
        return None, None, f"Figma couldn't render that node: {payload['err']}"

    image_url = (payload.get("images") or {}).get(node_id)
    if not image_url:
        return None, None, (
            "Figma didn't return a rendered image for that link — the node-id may be stale "
            "or the frame may be empty."
        )

    try:
        png_resp = requests.get(image_url, timeout=20)
    except requests.exceptions.RequestException as exc:
        return None, None, f"Could not download the rendered Figma image: {exc}"
    if png_resp.status_code >= 400:
        return None, None, f"Could not download the rendered Figma image (HTTP {png_resp.status_code})."

    return png_resp.content, "image/png", None
