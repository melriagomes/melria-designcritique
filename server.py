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
deliberately small otherwise: no database, no auth, no session memory — one
request in, one critique out, per plan.md's MVP scope.
"""
import base64
import logging
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

import design_reader
import evidence_reporting
import figma_reader
import screenshot_annotator

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = design_reader.MAX_UPLOAD_BYTES + 1024 * 1024  # small margin for form overhead
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
    audience = (request.form.get("audience") or "").strip()
    goals = (request.form.get("goals") or "").strip()
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
        api_key = get_api_key()
    except RuntimeError as exc:
        return error_response(str(exc), status=500)

    image_bytes, mime = design_reader.downscale_for_groq(image_bytes, mime, logger=app.logger)
    data_url = f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"

    context_block = design_reader.build_context_block(audience, goals, note)

    # --- Evidence & Reporting: shared understanding pass --------------------
    # Decides which disciplines are actually relevant (never assume every
    # specialist must weigh in) so specialists don't each have to rediscover
    # the design from scratch.
    understanding_raw, understanding_err = evidence_reporting.run_understanding_pass(
        api_key, context_block, data_url, logger=app.logger
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
    # endpoint now makes up to 7 Groq calls per critique (1 understanding pass +
    # up to 4 agents + 1 synthesis + 1 localization) instead of 1, and
    # on-demand/free-tier Groq accounts have a fairly tight per-minute token
    # quota — concurrent image-bearing calls reliably burst past it, where
    # sequential calls (plus the rate-limit retry in call_groq_chat) naturally
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
            label, prompt, api_key, agent_user_text, data_url, logger=app.logger
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

    final_text, err = evidence_reporting.run_synthesis_pass(api_key, synthesis_user_text, logger=app.logger)
    if err:
        return error_response(err, status=502)

    # --- Evidence & Reporting: localization, then Screenshot Annotator ------
    # Number the synthesized findings, ask which ones tie to a visible region
    # and where, and render an annotated image from whatever was located. Both
    # steps degrade gracefully to no annotation rather than failing the request.
    numbered_text, findings = evidence_reporting.number_key_findings(final_text)
    located = evidence_reporting.run_localization_pass(api_key, data_url, findings, logger=app.logger)

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
