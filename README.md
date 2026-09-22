# Design Critique Agent

A local chat-style web app: send it an image or a URL and it sends back a structured visual-design
critique (overview, issues by category, prioritized fixes). See `plan.md` for the full MVP/Final Sketch
plan this was built against.

## Run it locally

1. **Add your Groq API key.** Open `.env` in the project root and fill in:
   ```
   GROQ_API_KEY=gsk_...
   ```
   (Get a key from https://console.groq.com/keys — keep it out of any commit; `.env` is already
   gitignored. Vision-capable models on Groq are scarce and change over time — `qwen/qwen3.8-27b` is
   confirmed working as of this build; if it stops working, check https://console.groq.com/docs/vision
   for a current vision-capable model id and set `GROQ_MODEL` in `.env` to override it.)

   **Optional — Figma links.** To critique a Figma file/frame link directly (instead of only a plain
   webpage or uploaded image), add a Figma personal access token:
   ```
   FIGMA_API_TOKEN=figd_...
   ```
   (Generate one from Figma → account settings → Personal access tokens. Figma pages are login-walled,
   so without this token a pasted `figma.com` link will fail with a clear error instead of silently
   screenshotting a login page.)

2. **Install dependencies** (already done in this environment, listed here for reference):
   ```
   pip install -r requirements.txt
   playwright install chromium
   ```

3. **Start the server:**
   ```
   python server.py
   ```

4. Open **http://127.0.0.1:5000** in your browser. Switch between the "Image" and "URL" tabs to submit
   a screenshot/photo or a link (either a direct image URL or a webpage, which gets screenshotted
   automatically), optionally add a note, and hit Send.

## How it works

The backend is an **orchestrator** (`server.py`) that composes four building blocks — mirroring this
project's Claude Code skills, which follow the same shape (`ux-critic`, `graphic-critic`, etc. as
specialists; `screenshot-annotator` as a shared skill):

- `index.html` — the chat UI (vanilla HTML/CSS/JS, no build step).
- `design_reader.py` (+ `figma_reader.py`) — the **Design Reader**: resolves any submission (upload,
  direct image URL, Figma file/design/proto/board link, or arbitrary webpage) to one static image, plus
  the submitter's own context (audience/goal/note). `figma_reader.py` owns the Figma REST API integration
  specifically (token handling, URL parsing, error classification); everything else — direct image
  pass-through, downscaling for Groq's size limit, and Playwright screenshots of other webpages — lives in
  `design_reader.py`.
- `evidence_reporting.py` (+ `groq_client.py`) — the **specialist agents and synthesizer**: a shared
  understanding pass, four independent discipline critics (UI/UX, Graphic Design, Product Design,
  Interaction Design, each seeing the image but never each other's output), a synthesis pass that merges
  their findings into one report, and a localization pass that grounds each numbered finding in a region
  of the image (or explicitly leaves it unmarked when the finding isn't tied to one visible spot).
  `groq_client.py` is the shared Groq chat-completions call (with rate-limit retry) every pass above uses.
- `screenshot_annotator.py` — the **Screenshot Annotator**: draws the numbered callout markers the
  localization pass located, directly on the submitted image (Pillow, in-memory). This is the same
  drawing logic as the `screenshot-annotator` Claude Code skill, ported to run in-process for the deployed
  app instead of as a subprocess script.
- `server.py` — the **orchestrator**: the `/api/critique` route strings the above together (Design Reader
  → shared understanding → specialists → synthesis → localization → Screenshot Annotator) and returns the
  final Markdown report plus an annotated image when at least one finding could be located.
- Stateless by design (per `plan.md`'s MVP scope): each submission is critiqued independently, no saved
  history or multi-turn memory yet.
