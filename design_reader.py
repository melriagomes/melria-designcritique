"""Design Reader — resolves any submission (upload, direct image URL, Figma
link, or webpage) into one static image, plus the submitter's own context.

This is the app's "Design Reader" step: everything downstream (the
specialist agents and synthesis in `evidence_reporting`) works from the
static image and context block this module produces, regardless of which of
the three input paths (Figma / direct image / rendered webpage) it came
from.
"""
import io
import logging
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

import figma_reader

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_IMAGE_MIME = {"image/png", "image/jpeg", "image/webp", "image/gif"}
PAGE_LOAD_TIMEOUT_MS = 15_000
GROQ_MAX_IMAGE_PIXELS = 33_177_600  # Groq vision models reject anything larger than this

_default_logger = logging.getLogger(__name__)


def looks_like_image_extension(filename):
    ext = Path(filename or "").suffix.lower()
    return ext in {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def downscale_for_groq(image_bytes, mime, logger=None):
    """Shrink an image to fit Groq's max-pixel limit for vision models.

    Applies regardless of where the image came from (upload, direct image URL,
    Figma render, or webpage screenshot) — any of those can exceed the limit,
    most commonly a full-page screenshot of a tall webpage or a Figma render
    at 2x scale. Returns (possibly-unchanged) image_bytes and mime.
    """
    log = logger or _default_logger
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
            log.info(
                "downscaled oversized image for groq: %sx%s (%s px) -> %sx%s (%s px)",
                img.width, img.height, pixels, new_size[0], new_size[1], new_size[0] * new_size[1],
            )
            return buf.getvalue(), "image/png"
    except Exception as exc:  # noqa: BLE001 - image parsing can fail in many ways; fall back safely
        log.warning("could not inspect/downscale image (%s) — sending as-is", exc)
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


def resolve_url_to_image(url, access_token_override=None, logger=None):
    """Resolve any pasted URL to an image.

    `access_token_override` is the visitor's currently-active Figma key from
    Settings. It's only used for figma.com links — sent as the
    `X-Figma-Token` header to Figma's REST API (via `figma_reader`). Every
    other URL is fetched unauthenticated, so a Figma token is never handed
    to a third-party site.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None, None, "That doesn't look like a valid http(s) URL."

    figma_target = figma_reader.parse_figma_url(parsed)
    if figma_target:
        return figma_reader.resolve_figma_url_to_image(
            *figma_target, figma_token_override=access_token_override, logger=logger
        )

    headers = {"User-Agent": "Mozilla/5.0 (design-critique-agent)"}

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
                page.goto(url, wait_until="load", timeout=PAGE_LOAD_TIMEOUT_MS)
                screenshot = page.screenshot(full_page=True, type="png")
            finally:
                browser.close()
    except PlaywrightTimeoutError:
        return None, None, "That page took too long to load (timed out after 15s)."
    except PlaywrightError as exc:
        return None, None, f"Could not render that page: {exc}"

    return screenshot, "image/png", None


def build_context_block(audience, goals, note):
    lines = []
    if audience:
        lines.append(f"Intended audience: {audience}")
    if goals:
        lines.append(f"Design goal: {goals}")
    if note:
        lines.append(f"Submitter's note: {note}")
    return "\n".join(lines) if lines else "No audience, goal, or note was provided for this submission."
