"""Local backend for the design-critique chat.

Serves index.html and one API route (/api/critique) that resolves a
submitted image or URL to a static image, then sends it to a vision model
on Groq for a structured visual-design critique. Kept deliberately small:
no database, no auth, no session memory — one request in, one critique
out, per plan.md's MVP scope.
"""
import base64
import io
import logging
import mimetypes
import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from PIL import Image
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = os.environ.get("GROQ_MODEL", "qwen/qwen3.8-27b")
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_IMAGE_MIME = {"image/png", "image/jpeg", "image/webp", "image/gif"}
PAGE_LOAD_TIMEOUT_MS = 15_000
GROQ_MAX_IMAGE_PIXELS = 33_177_600  # Groq vision models reject anything larger than this

# --- Figma REST API integration -------------------------------------------
#
# This talks to Figma's REST API directly over HTTPS using a Personal Access
# Token (FIGMA_API_TOKEN, sent as the `X-Figma-Token` header). This is a
# completely separate credential and code path from any Figma MCP server an
# AI coding agent (e.g. inside an editor) might use during development — the
# two are never wired together, and this token is never shared with or read
# by an MCP client. The token only ever lives server-side: it is read from
# the environment in this file and never sent to, or embedded in, anything
# served to the browser (index.html makes no Figma calls of its own).
FIGMA_API_BASE = "https://api.figma.com/v1"
FIGMA_HOSTS = {"figma.com", "www.figma.com"}
FIGMA_PATH_RE = re.compile(r"^/(file|design|proto|board)/([a-zA-Z0-9_-]+)")

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES + 1024 * 1024  # small margin for form overhead
app.logger.setLevel(logging.INFO)


def get_api_key():
    """Return the app's own Groq API key. This runs the critique model itself,
    so it's the app's infrastructure credential — not something visitors supply."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Add it to the .env file in the project root and restart the server."
        )
    return api_key


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


SYSTEM_PROMPT = """You are a senior visual-design critic. You are given one design — a UI screen, \
graphic, poster, branding asset, slide, or similar — as an image. Critique it against these \
categories only: visual hierarchy, contrast, alignment/grid, typography, spacing/whitespace, color, \
and accessibility/legibility.

Ground every point in something actually visible in the image — name the specific element or region \
("the primary CTA button", "the paragraph under the hero image") rather than speaking generically.

Cover at least three distinct categories that genuinely apply to this design; skip categories that \
don't apply rather than forcing an issue that isn't there. Every issue you raise must be paired with a \
concrete, actionable fix — never just "this looks off." A fix is specific enough to act on without \
guessing (e.g. "increase the CTA button's text-to-background contrast to at least 4.5:1, e.g. by \
darkening the blue from #6FA8DC to #2A6BB0" — not "improve contrast").

Reply in exactly this Markdown structure and nothing else:

## Overview
One or two sentences on the overall impression — strongest asset and biggest weakness.

## Issues
### <Category name>
- **Issue:** <specific, grounded observation>
  **Fix:** <specific, actionable change>

(repeat the `### <Category>` block for each category that applies)

## Prioritized Fixes
1. <the single highest-impact fix, restated briefly>
2. <next>
...
(ordered fix-first to polish-later; every item here should trace back to an issue above)
"""


def error_response(message, status=400):
    return jsonify({"error": message}), status


def looks_like_image_extension(filename):
    ext = Path(filename or "").suffix.lower()
    return ext in {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def downscale_for_groq(image_bytes, mime):
    """Shrink an image to fit Groq's max-pixel limit for vision models.

    Applies regardless of where the image came from (upload, direct image URL,
    Figma render, or webpage screenshot) — any of those can exceed the limit,
    most commonly a full-page screenshot of a tall webpage or a Figma render
    at 2x scale. Returns (possibly-unchanged) image_bytes and mime.
    """
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            pixels = img.width * img.height
            if pixels <= GROQ_MAX_IMAGE_PIXELS:
                return image_bytes, mime

            # A small safety margin below the exact limit avoids rounding the
            # resized dimensions back up to the boundary.
            scale = (GROQ_MAX_IMAGE_PIXELS / pixels) ** 0.5 * 0.99
            new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
            resized = img.convert("RGB") if img.mode in ("P", "CMYK") else img
            resized = resized.resize(new_size, Image.LANCZOS)

            buf = io.BytesIO()
            resized.save(buf, format="PNG")
            app.logger.info(
                "downscaled oversized image for groq: %sx%s (%s px) -> %sx%s (%s px)",
                img.width, img.height, pixels, new_size[0], new_size[1], new_size[0] * new_size[1],
            )
            return buf.getvalue(), "image/png"
    except Exception as exc:  # noqa: BLE001 - image parsing can fail in many ways; fall back safely
        app.logger.warning("could not inspect/downscale image (%s) — sending as-is", exc)
        return image_bytes, mime


def resolve_uploaded_image(file_storage):
    mime = file_storage.mimetype
    if mime not in ALLOWED_IMAGE_MIME and not looks_like_image_extension(file_storage.filename):
        return None, None, f"Unsupported image type ({mime or 'unknown'}). Use PNG, JPG, WEBP, or GIF."

    data = file_storage.read()
    if not data:
        return None, None, "That image file appears to be empty."
    if len(data) > MAX_UPLOAD_BYTES:
        return None, None, "That image is larger than the 10MB limit."

    if mime not in ALLOWED_IMAGE_MIME:
        guessed, _ = mimetypes.guess_type(file_storage.filename or "")
        mime = guessed or "image/png"

    return data, mime, None


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
                "(tap the ⓘ next to \"Your API keys\" for how), mark it active, then paste the link again."
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


def log_figma_error(context, resp, used_own_token=False):
    """Log a Figma API failure server-side with full (non-secret) detail, and
    return the safe, classified message to show the user."""
    detail = figma_error_detail(resp)
    label, user_msg = classify_figma_error(resp.status_code, detail, used_own_token=used_own_token)
    app.logger.warning(
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
    debugging (logs, or the `--figma-diagnose` CLI below), never returned
    to a browser client.
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


def resolve_figma_url_to_image(file_key, node_id, figma_token_override=None):
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
            return None, None, log_figma_error(f"files/{file_key}", file_resp, used_own_token=used_own_token)
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
        return None, None, log_figma_error(f"images/{file_key}", image_resp, used_own_token=used_own_token)

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


def resolve_url_to_image(url, access_token_override=None):
    """Resolve any pasted URL to an image, using `access_token_override` (the
    visitor's currently-active Settings key) to authenticate the fetch when
    the target needs it.

    A figma.com link uses that key exactly as before — sent as the
    `X-Figma-Token` header to Figma's REST API. Any other URL sends it as a
    standard `Authorization: Bearer <token>` header on the direct fetch and
    the page render, so a visitor's own protected site (or any API requiring
    bearer-token auth) works the same way a public one does. When no key is
    set, requests go out unauthenticated exactly as before.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None, None, "That doesn't look like a valid http(s) URL."

    figma_target = parse_figma_url(parsed)
    if figma_target:
        return resolve_figma_url_to_image(*figma_target, figma_token_override=access_token_override)

    headers = {"User-Agent": "Mozilla/5.0 (design-critique-agent)"}
    if access_token_override:
        headers["Authorization"] = f"Bearer {access_token_override}"

    try:
        resp = requests.get(
            url,
            timeout=10,
            headers=headers,
            stream=True,
        )
    except requests.exceptions.Timeout:
        return None, None, "Timed out trying to reach that URL."
    except requests.exceptions.ConnectionError as exc:
        return None, None, f"Could not reach that URL ({exc.__class__.__name__})."
    except requests.exceptions.RequestException as exc:
        return None, None, f"Could not fetch that URL: {exc}"

    if resp.status_code >= 400:
        return None, None, f"That URL returned HTTP {resp.status_code}."

    content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()

    if content_type in ALLOWED_IMAGE_MIME:
        data = resp.raw.read(MAX_UPLOAD_BYTES + 1, decode_content=True)
        if len(data) > MAX_UPLOAD_BYTES:
            return None, None, "The image at that URL is larger than the 10MB limit."
        return data, content_type, None

    # Not a direct image link — render the page and screenshot it instead.
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                if access_token_override:
                    page.set_extra_http_headers({"Authorization": f"Bearer {access_token_override}"})
                page.goto(url, wait_until="load", timeout=PAGE_LOAD_TIMEOUT_MS)
                screenshot = page.screenshot(full_page=True, type="png")
            finally:
                browser.close()
    except PlaywrightTimeoutError:
        return None, None, "That page took too long to load (timed out after 15s)."
    except PlaywrightError as exc:
        return None, None, f"Could not render that page: {exc}"

    return screenshot, "image/png", None


@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/settings")
def settings_page():
    return send_from_directory(BASE_DIR, "settings.html")


@app.route("/api/critique", methods=["POST"])
def critique():
    image_file = request.files.get("image")
    url = (request.form.get("url") or "").strip()
    note = (request.form.get("note") or "").strip()
    # The visitor's currently-active key from the Settings page (browser
    # localStorage), sent with this request only and never written to disk
    # server-side. Empty means "not set" — Figma URLs then fall back to the
    # shared .env token, and other URLs are fetched unauthenticated.
    access_token_override = (request.form.get("access_token") or "").strip() or None

    has_image = image_file is not None and image_file.filename
    has_url = bool(url)

    if has_image and has_url:
        return error_response("Submit either an image or a URL for a single critique, not both.")
    if not has_image and not has_url:
        return error_response("Attach an image or enter a URL before sending.")

    if has_image:
        image_bytes, mime, err = resolve_uploaded_image(image_file)
    else:
        image_bytes, mime, err = resolve_url_to_image(url, access_token_override=access_token_override)

    if err:
        return error_response(err)

    user_text = "Critique this design." if not note else f"Critique this design. Note from the user: {note}"

    try:
        api_key = get_api_key()
    except RuntimeError as exc:
        return error_response(str(exc), status=500)

    image_bytes, mime = downscale_for_groq(image_bytes, mime)

    data_url = f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"
    try:
        resp = requests.post(
            GROQ_API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": GROQ_MODEL,
                "max_completion_tokens": 800,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_text},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    },
                ],
            },
            timeout=60,
        )
    except requests.exceptions.RequestException as exc:
        return error_response(f"Could not reach the Groq API: {exc}", status=502)

    if resp.status_code >= 400:
        try:
            detail = resp.json().get("error", {}).get("message", resp.text)
        except ValueError:
            detail = resp.text
        return error_response(f"The AI service returned an error: {detail}", status=502)

    reply_text = resp.json()["choices"][0]["message"]["content"]
    return jsonify({"reply": reply_text})


@app.errorhandler(413)
def too_large(_exc):
    return error_response("That upload is larger than the 10MB limit.", status=413)


def _run_figma_diagnose_cli(arg):
    """`python server.py --figma-diagnose [<figma-url-or-file-key>]`

    Standalone, read-only check of the Figma REST integration — does not
    start the Flask server. Prints token presence, the authenticated
    account (if the token's scopes allow that lookup), and whether the
    given file is accessible. Never prints the token itself.
    """
    file_key = None
    if arg:
        parsed = urlparse(arg)
        if parsed.scheme in ("http", "https"):
            target = parse_figma_url(parsed)
            if not target:
                print("That doesn't look like a figma.com file/design/proto/board URL.")
                return
            file_key, _node_id = target
        else:
            file_key = arg.strip()

    diag = figma_diagnostics(file_key)
    print(f"token present:          {diag['token_present']}")
    print(f"token (redacted):       {diag['token_redacted']}")
    print(f"authenticated account:  {diag['authenticated_account']}")
    if file_key:
        print(f"file access ({file_key}): {diag['file_access']}")
    else:
        print("file access:            (pass a Figma URL or file key as an argument to check)")


if __name__ == "__main__":
    # Local development entry point only. In production (Railway), Gunicorn
    # imports this module directly as `server:app` (see Procfile) and never
    # executes this block, so it has no effect on and cannot conflict with
    # the production server. Debug mode defaults off here too, so running
    # `python server.py` without opting in never starts the dev server in
    # debug mode by accident.
    if len(sys.argv) > 1 and sys.argv[1] == "--figma-diagnose":
        _run_figma_diagnose_cli(sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        debug = os.environ.get("FLASK_DEBUG", "0") == "1"
        app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=debug)
