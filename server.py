"""Orchestrator for the design-critique chat.

Serves index.html and one API route (/api/critique). The route itself is the
orchestrator described in the project's architecture: it hands a submitted
image or URL to the **Design Reader** (`design_reader`, backed by
`figma_reader` for Figma links) to resolve one static image; runs the
**Evidence & Reporting** pipeline (`evidence_reporting`) — a shared
understanding pass, four independent discipline specialists (UI/UX, Graphic
Design, Product Design, Interaction Design), a synthesis pass, and a
localization pass; then hands the located findings to the **Screenshot
Annotator** (`screenshot_annotator`) to render one annotated image. Kept
deliberately small otherwise: no database and no conversation memory — one
request in, one critique out, per plan.md's MVP scope.

Every page and API route requires Google sign-in with an allowed-domain
account (`auth`); the signed-in user lives only in Flask's signed session
cookie. Finished critiques can be exported as PDF or Word via /api/export
(`exporter`).
"""
import base64
import html
import json
import logging
import os
import secrets
import sys
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request, send_from_directory, session

import ai_client
import auth
import design_reader
import evidence_reporting
import exporter
import figma_reader
import screenshot_annotator

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = design_reader.MAX_UPLOAD_BYTES + 1024 * 1024  # small margin for form overhead
app.logger.setLevel(logging.INFO)

# Signs the session cookie that holds the signed-in user. Without a fixed
# SECRET_KEY every restart (and every deploy) signs everyone out.
_secret_key = os.environ.get("SECRET_KEY")
if not _secret_key:
    app.logger.warning("SECRET_KEY is not set — using a random one; sessions reset on every restart.")
    _secret_key = secrets.token_hex(32)
app.secret_key = _secret_key
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    # Lax keeps other sites from making signed-in POSTs to this app.
    SESSION_COOKIE_SAMESITE="Lax",
    # HTTPS-only on Railway; plain http on localhost for development.
    SESSION_COOKIE_SECURE=os.environ.get(
        "SESSION_COOKIE_SECURE", "1" if os.environ.get("RAILWAY_ENVIRONMENT") else "0"
    ) == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)


def get_ai_config(key_override=None, provider_override=None, model_override=None):
    """Return the AIConfig (provider, key, model) to run the critique with.

    The overrides are the visitor's own AI key, provider, and optional model
    from the Settings page (sent with the request, never stored server-side);
    the key can be from Anthropic, OpenAI, Gemini, or Groq. Without a key,
    the app's shared GROQ_API_KEY is used. Raises RuntimeError with a
    user-facing message when neither is available or the key can't be
    matched to a provider."""
    if key_override:
        try:
            return ai_client.build_ai_config(key_override, provider_override, model_override)
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "No AI API key is available. Add your own AI API key (Anthropic, OpenAI, Gemini, or Groq) "
            "in Settings, or set GROQ_API_KEY in the .env file in the project root and restart the server."
        )
    return ai_client.build_ai_config(api_key, "groq")


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

Use Markdown **bold** liberally to surface the single most important takeaway in every sentence you \
write — the specific element named, the key number or hex value, the one word that changes the \
meaning of the fix. Every "Issue" and "Fix" line must have at least one bolded phrase, and the \
Overview and each item in Prioritized Fixes must bold their core point too. Never bold whole sentences \
— only the load-bearing words within them.

Reply in exactly this Markdown structure and nothing else:

## Overview
One or two sentences on the overall impression — strongest asset and biggest weakness, with the key \
words **bolded**.

## Issues
### <Category name>
- **Issue:** <specific, grounded observation, with the key element/value **bolded**>
  **Fix:** <specific, actionable change, with the key action/value **bolded**>

(repeat the `### <Category>` block for each category that applies)

## Prioritized Fixes
1. <the single highest-impact fix, restated briefly, with the key action **bolded**>
2. <next>
...
(ordered fix-first to polish-later; every item here should trace back to an issue above)
"""


def error_response(message, status=400):
    return jsonify({"error": message}), status


def current_user():
    return session.get("user")


def login_page():
    """login.html with this server's Google client ID and allowed domain filled in."""
    page = (BASE_DIR / "login.html").read_text(encoding="utf-8")
    config = {"clientId": auth.GOOGLE_CLIENT_ID, "domain": auth.ALLOWED_DOMAIN}
    # Escape "<" so the JSON can't close the <script> tag it's embedded in.
    page = page.replace("__AUTH_CONFIG__", json.dumps(config).replace("<", "\\u003c"))
    page = page.replace("__ALLOWED_DOMAIN__", html.escape(auth.ALLOWED_DOMAIN))
    return Response(page, mimetype="text/html")


def signed_in_page(filename):
    """Serve an app page to a signed-in user, or the sign-in page otherwise."""
    if not current_user():
        return login_page()
    response = send_from_directory(BASE_DIR, filename)
    # Never let a browser (or its back button) show the app to someone who
    # has since signed out.
    response.headers["Cache-Control"] = "no-store"
    return response


def require_sign_in(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            return error_response("You've been signed out. Refresh the page to sign in again.", status=401)
        return view(*args, **kwargs)

    return wrapped


@app.route("/")
def index():
    return signed_in_page("index.html")


@app.route("/settings")
def settings_page():
    return signed_in_page("settings.html")


@app.route("/api/auth/google", methods=["POST"])
def google_sign_in():
    credential = (request.get_json(silent=True) or {}).get("credential")
    try:
        user = auth.verify_google_credential(credential, logger=app.logger)
    except auth.SignInError as exc:
        return error_response(str(exc), status=exc.status)
    session.clear()
    session.permanent = True
    session["user"] = user
    app.logger.info("signed in: %s", user["email"])
    return jsonify({"user": user})


@app.route("/api/auth/logout", methods=["POST"])
def sign_out():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/me")
@require_sign_in
def me():
    return jsonify({"user": current_user()})


@app.route("/api/export", methods=["POST"])
@require_sign_in
def export():
    """Turn a finished critique (its Markdown reply and annotated image, as
    the browser received them) into a downloadable PDF or Word file."""
    payload = request.get_json(silent=True) or {}
    fmt = payload.get("format")
    markdown = payload.get("markdown") or ""
    if fmt not in ("pdf", "docx"):
        return error_response("Choose PDF or Word for the export.")
    if not markdown.strip():
        return error_response("There's no critique to export.")
    image_bytes, mime = exporter.decode_image_data_url(payload.get("image"))

    filename = f"design-critique-{datetime.now():%Y-%m-%d-%H%M}.{fmt}"
    try:
        if fmt == "pdf":
            data = exporter.to_pdf(markdown, image_bytes, mime)
            content_type = "application/pdf"
        else:
            data = exporter.to_docx(markdown, image_bytes)
            content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    except Exception as exc:  # noqa: BLE001 - report any rendering failure as a clean error
        app.logger.exception("export to %s failed", fmt)
        return error_response(f"Couldn't create the {fmt.upper()} file: {exc}", status=500)

    return Response(
        data,
        mimetype=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.route("/api/critique", methods=["POST"])
@require_sign_in
def critique():
    image_file = request.files.get("image")
    url = (request.form.get("url") or "").strip()
    note = (request.form.get("note") or "").strip()
    audience = (request.form.get("audience") or "").strip()
    goals = (request.form.get("goals") or "").strip()
    # The visitor's currently-active Figma key from the Settings page (browser
    # localStorage), sent with this request only and never written to disk
    # server-side. Empty means "not set" — Figma URLs then fall back to the
    # shared .env token.
    access_token_override = (request.form.get("access_token") or "").strip() or None
    # The visitor's own AI key (plus its provider and optional model) from
    # Settings, handled the same way. Empty means "use the shared GROQ_API_KEY".
    ai_api_key_override = (request.form.get("ai_api_key") or "").strip() or None
    ai_provider_override = (request.form.get("ai_provider") or "").strip() or None
    ai_model_override = (request.form.get("ai_model") or "").strip() or None

    has_image = image_file is not None and image_file.filename
    has_url = bool(url)

    if has_image and has_url:
        return error_response("Submit either an image or a URL for a single critique, not both.")
    if not has_image and not has_url:
        return error_response("Attach an image or enter a URL before sending.")

    # --- Design Reader: resolve the submission to one static image ---------
    if has_image:
        image_bytes, mime, err = design_reader.resolve_uploaded_image(image_file)
    else:
        image_bytes, mime, err = design_reader.resolve_url_to_image(
            url, access_token_override=access_token_override, logger=app.logger
        )

    if err:
        return error_response(err)

    try:
        ai = get_ai_config(ai_api_key_override, ai_provider_override, ai_model_override)
    except RuntimeError as exc:
        return error_response(str(exc), status=500)
    app.logger.info("running critique on %s (%s)", ai.provider, ai.model)

    image_bytes, mime = design_reader.downscale_for_provider(image_bytes, mime, ai.provider, logger=app.logger)
    data_url = f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"

    context_block = design_reader.build_context_block(audience, goals, note)

    # --- Evidence & Reporting: shared understanding pass --------------------
    # Decides which disciplines are actually relevant (never assume every
    # specialist must weigh in) so specialists don't each have to rediscover
    # the design from scratch.
    understanding_raw, understanding_err = evidence_reporting.run_understanding_pass(
        ai, context_block, data_url, logger=app.logger
    )
    if understanding_err:
        # The understanding pass is a focus/coverage optimization, not a hard
        # requirement — fall back to running every specialist rather than failing
        # the whole request over it.
        app.logger.warning("understanding pass failed: %s", understanding_err)
        shared_understanding = "(Shared understanding pass unavailable — each specialist is reviewing independently.)"
        relevant_labels = list(evidence_reporting.DISCIPLINE_LABELS)
    else:
        shared_understanding, relevant_labels = evidence_reporting.parse_understanding(understanding_raw)

    agent_user_text = evidence_reporting.build_agent_user_text(shared_understanding, context_block)

    # --- Evidence & Reporting: independent discipline specialists -----------
    # Delegate to only the relevant discipline agents, each independently (none
    # sees another's output). Run sequentially rather than in parallel: this
    # endpoint now makes up to 7 AI calls per critique (1 understanding pass +
    # up to 4 agents + 1 synthesis + 1 localization) instead of 1, and
    # on-demand/free-tier accounts (Groq's especially) have a fairly tight per-minute token
    # quota — concurrent image-bearing calls reliably burst past it, where
    # sequential calls (plus the rate-limit retry in ai_client) naturally
    # spread the load and recover.
    agents = [
        (label, evidence_reporting.DISCIPLINE_PROMPTS[label])
        for label in evidence_reporting.DISCIPLINE_LABELS
        if label in relevant_labels
    ]

    critiques = {}
    failures = {}
    for label, prompt in agents:
        _, text, err = evidence_reporting.run_discipline_agent(
            label, prompt, ai, agent_user_text, data_url, logger=app.logger
        )
        if err:
            failures[label] = err
            app.logger.warning("discipline agent failed: %s: %s", label, err)
        else:
            critiques[label] = text

    if not critiques:
        first_error = next(iter(failures.values()))
        return error_response(f"All critique agents failed: {first_error}", status=502)

    # --- Evidence & Reporting: synthesis -------------------------------------
    synthesis_context_lines = [context_block, f"Shared design understanding:\n{shared_understanding}"]
    skipped = [label for label in evidence_reporting.DISCIPLINE_LABELS if label not in relevant_labels]
    if skipped:
        synthesis_context_lines.append(
            "Not run (judged not relevant to this design by the initial understanding pass): "
            + ", ".join(skipped)
        )
    if failures:
        synthesis_context_lines.append(
            "Not included below (a technical failure, not a design finding): " + ", ".join(failures)
        )
    synthesis_context = "\n\n".join(synthesis_context_lines)

    critiques_block = "\n\n".join(
        f"=== {label} critique ===\n{critiques[label]}"
        for label in evidence_reporting.DISCIPLINE_LABELS
        if label in critiques
    )

    synthesis_user_text = (
        f"{synthesis_context}\n\n"
        f"Independent specialist critiques to compare and synthesize:\n\n{critiques_block}"
    )

    final_text, err = evidence_reporting.run_synthesis_pass(ai, synthesis_user_text, logger=app.logger)
    if err:
        return error_response(err, status=502)

    # --- Evidence & Reporting: localization, then Screenshot Annotator ------
    # Number the synthesized findings, ask which ones tie to a visible region
    # and where, and render an annotated image from whatever was located. Both
    # steps degrade gracefully to no annotation rather than failing the request.
    numbered_text, findings = evidence_reporting.number_key_findings(final_text)
    located = evidence_reporting.run_localization_pass(ai, data_url, findings, logger=app.logger)

    annotated_image_data_url = None
    if located:
        try:
            annotated_bytes = screenshot_annotator.annotate_image(image_bytes, located)
            annotated_image_data_url = (
                f"data:image/png;base64,{base64.b64encode(annotated_bytes).decode('ascii')}"
            )
        except Exception as exc:  # noqa: BLE001 - rendering can fail in many ways; never break the critique over it
            app.logger.warning("screenshot annotation failed: %s", exc)
            located = []

    if annotated_image_data_url:
        located_numbers = sorted(item["number"] for item in located)
        note = (
            "The image above is annotated — marker **N** corresponds to **Finding N** under Key "
            "Findings. "
        )
        skipped_numbers = [f["number"] for f in findings if f["number"] not in located_numbers]
        if skipped_numbers:
            skipped_list = ", ".join(str(n) for n in skipped_numbers)
            note += (
                f"Finding(s) {skipped_list} aren't tied to a single visible region (conceptual/strategic "
                "or not verifiable from a still image), so they aren't marked."
            )
    elif findings:
        note = (
            "No findings in this critique were tied to a single, clearly visible region, so no annotated "
            "image is included this time."
        )
    else:
        note = "No numbered findings were produced for this critique, so there's nothing to annotate."

    final_text = evidence_reporting.replace_annotated_screenshots_section(numbered_text, note)

    response = {"reply": final_text}
    if annotated_image_data_url:
        response["annotated_image"] = annotated_image_data_url
    return jsonify(response)


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
            target = figma_reader.parse_figma_url(parsed)
            if not target:
                print("That doesn't look like a figma.com file/design/proto/board URL.")
                return
            file_key, _node_id = target
        else:
            file_key = arg.strip()

    diag = figma_reader.figma_diagnostics(file_key)
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
