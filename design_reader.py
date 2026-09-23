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
# Per-provider vision input limits. max_bytes is the raw image size, kept low
# enough that the base64-encoded copy sent in the request still fits.
IMAGE_LIMITS = {
    "groq": {"max_pixels": 33_177_600, "max_dim": None, "max_bytes": 15 * 1024 * 1024},
    "openai": {"max_pixels": None, "max_dim": None, "max_bytes": 15 * 1024 * 1024},
    "gemini": {"max_pixels": None, "max_dim": None, "max_bytes": 14 * 1024 * 1024},
    "anthropic": {"max_pixels": None, "max_dim": 8000, "max_bytes": 3_700_000},
}

_default_logger = logging.getLogger(__name__)


def looks_like_image_extension(filename):
    ext = Path(filename or "").suffix.lower()
    return ext in {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def downscale_for_provider(image_bytes, mime, provider, logger=None):
    """Shrink an image to fit `provider`'s vision-input limits (see
    IMAGE_LIMITS): Groq caps total pixels, Anthropic caps each side at 8000px
    and the file at ~5MB once base64-encoded, and every provider caps request
    size.

    Applies regardless of where the image came from (upload, direct image URL,
    Figma render, or webpage screenshot) — any of those can exceed a limit,
    most commonly a full-page screenshot of a tall webpage or a Figma render
    at 2x scale. Returns (possibly-unchanged) image_bytes and mime.
    """
    log = logger or _default_logger
    limits = IMAGE_LIMITS.get(provider, IMAGE_LIMITS["groq"])
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            width, height = img.width, img.height
            scale = 1.0
            if limits["max_pixels"] and width * height > limits["max_pixels"]:
                scale = min(scale, (limits["max_pixels"] / (width * height)) ** 0.5)
            if limits["max_dim"] and max(width, height) > limits["max_dim"]:
                scale = min(scale, limits["max_dim"] / max(width, height))
            if scale == 1.0 and len(image_bytes) <= limits["max_bytes"]:
                return image_bytes, mime

            # A small safety margin below the exact limit avoids rounding the
            # resized dimensions back up to the boundary.
            if scale < 1.0:
                scale *= 0.99
            resized = img.convert("RGB") if img.mode in ("P", "CMYK") else img
            if scale < 1.0:
                resized = resized.resize(
                    (max(1, int(width * scale)), max(1, int(height * scale))), Image.LANCZOS
                )

            out_bytes, out_mime = _encode_png(resized), "image/png"
            # Still too many bytes: switch to JPEG, then keep shrinking.
            while len(out_bytes) > limits["max_bytes"]:
                out_bytes, out_mime = _encode_jpeg(resized), "image/jpeg"
                if len(out_bytes) <= limits["max_bytes"] or min(resized.size) < 200:
                    break
                resized = resized.resize(
                    (int(resized.width * 0.8), int(resized.height * 0.8)), Image.LANCZOS
                )

            log.info(
                "downscaled image for %s: %sx%s (%s bytes) -> %sx%s %s (%s bytes)",
                provider, width, height, len(image_bytes),
                resized.width, resized.height, out_mime, len(out_bytes),
            )
            return out_bytes, out_mime
    except Exception as exc:  # noqa: BLE001 - image parsing can fail in many ways; fall back safely
        log.warning("could not inspect/downscale image (%s) — sending as-is", exc)
        return image_bytes, mime


def _encode_png(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _encode_jpeg(img):
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=85)
    return buf.getvalue()


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
