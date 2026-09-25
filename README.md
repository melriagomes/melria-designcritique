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

4. Open **http://localhost:5000** in your browser (use `localhost`, not `127.0.0.1` — that's the origin
   registered for Google sign-in) and sign in with your @flame.edu.in Google account. Switch between the
   "Image" and "URL" tabs to submit a screenshot/photo or a link (either a direct image URL or a webpage,
   which gets screenshotted automatically), optionally add a note, and hit Send. Each finished critique
   has **PDF · Markdown · Word** download buttons.

## Google sign-in setup

The app only lets in signed-in Google accounts from one domain (`flame.edu.in` by default). The server
verifies Google's ID token and requires a verified email in that Google Workspace domain, so personal
Gmail accounts and other organizations are rejected.

1. In the [Google Cloud Console](https://console.cloud.google.com/apis/credentials), create a project (or
   pick one), set up the **OAuth consent screen** (External is fine; add your app name and support email),
   then **Create credentials → OAuth client ID → Web application**.
2. Under **Authorized JavaScript origins**, add every place the app runs:
   `http://localhost`, `http://localhost:5000`, and your Railway URL
   (e.g. `https://melria-designcritique-production.up.railway.app`). No redirect URIs are needed.
3. Copy the **Client ID** (it ends in `.apps.googleusercontent.com`) and set these in `.env` locally and
   in Railway → your service → **Variables**:
   ```
   GOOGLE_CLIENT_ID=1234567890-abc.apps.googleusercontent.com
   SECRET_KEY=<any long random string, e.g. from: python -c "import secrets; print(secrets.token_hex(32))">
   ```
   `SECRET_KEY` signs the session cookie; without a fixed one, every restart or deploy signs everyone out.
   Optionally set `ALLOWED_EMAIL_DOMAIN` to allow a different domain.

## Persisting history on Railway

Each finished critique is saved to that account's history (`history.py`, a SQLite file) so it can be
revisited later from the **History** button in the app. Locally this file lives at `./data/history.db`
(gitignored) with no setup needed. On Railway, the filesystem is wiped on every deploy unless the data
lives on a **Volume**:

1. In the Railway dashboard, open this service → **Settings** → **Volumes** → **Add Volume**.
2. Set the **mount path** to `/data` (any path works as long as it matches step 3).
3. Add a variable in **Variables**: `DATA_DIR=/data`.
4. Redeploy. `history.py` creates `history.db` on that volume automatically on first run.

Without a volume attached, history still works between requests but is lost on the next deploy or
restart — the app degrades gracefully either way (saving to history never blocks a critique from
completing, even if the write fails).

## How it works

The backend is an **orchestrator** (`server.py`) that composes four building blocks — mirroring this
project's Claude Code skills, which follow the same shape (`ux-critic`, `graphic-critic`, etc. as
specialists; `screenshot-annotator` as a shared skill):

- `index.html` — the chat UI (vanilla HTML/CSS/JS, no build step).
- `design_reader.py` (+ `figma_reader.py`) — the **Design Reader**: resolves any submission (upload,
  direct image URL, Figma file/design/proto/board link, or arbitrary webpage) to one static image, plus
  the submitter's own context (audience/goal/note). `figma_reader.py` owns the Figma REST API integration
  specifically (token handling, URL parsing, error classification); everything else — direct image
  pass-through, downscaling to the AI provider's image limits, and Playwright screenshots of other webpages — lives in
  `design_reader.py`.
- `evidence_reporting.py` (+ `ai_client.py`) — the **specialist agents and synthesizer**: a shared
  understanding pass, five independent discipline critics (UI/UX, Graphic Design, Product Design,
  Interaction Design, Design Research, each seeing the image but never each other's output), a synthesis pass that merges
  their findings into one report, and a localization pass that grounds each numbered finding in a region
  of the image (or explicitly leaves it unmarked when the finding isn't tied to one visible spot).
  `ai_client.py` is the shared AI call every pass above uses. It runs on the app's shared Groq key by
  default, or on a visitor's own Anthropic, OpenAI, Gemini, or Groq key from the Settings page (provider
  detected from the key prefix; optional model override). Default models can be changed in `.env` with
  `GROQ_MODEL`, `OPENAI_MODEL`, `GEMINI_MODEL`, and `ANTHROPIC_MODEL`.
- `screenshot_annotator.py` — the **Screenshot Annotator**: draws the numbered callout markers the
  localization pass located, directly on the submitted image (Pillow, in-memory). This is the same
  drawing logic as the `screenshot-annotator` Claude Code skill, ported to run in-process for the deployed
  app instead of as a subprocess script.
- `history.py` — per-account **History**: saves each finished critique (source, note/audience/goals,
  Markdown, annotated image) to a SQLite file on disk, scoped to the signed-in user's email. Backed by a
  Railway Volume in production (see "Persisting history on Railway" above) so it survives deploys; a local
  `./data/history.db` otherwise. `/api/history` lists an account's past analyses, `/api/history/<id>`
  fetches one full record — both reject anything that isn't the caller's own.
- `server.py` — the **orchestrator**: the `/api/critique` route strings the above together (Design Reader
  → shared understanding → specialists → synthesis → localization → Screenshot Annotator → History) and
  returns the final Markdown report plus an annotated image when at least one finding could be located.
- Each submission is still critiqued independently — no multi-turn memory within a critique — but the
  finished result is saved to History rather than discarded, per the account that submitted it.
