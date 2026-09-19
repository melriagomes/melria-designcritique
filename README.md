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

- `index.html` — the chat UI (vanilla HTML/CSS/JS, no build step).
- `server.py` — a small Flask backend: resolves the submission to a static image (pass-through for an
  upload or a direct image URL; a Figma REST API render for a `figma.com` file/design/proto/board link,
  using the `node-id` in the URL when present, otherwise the file's first page; a Playwright-rendered
  screenshot for any other webpage URL), sends it to a vision model on Groq with a fixed critique rubric,
  and returns the critique text.
- Stateless by design (per `plan.md`'s MVP scope): each submission is critiqued independently, no saved
  history or multi-turn memory yet.
