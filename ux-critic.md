# ux-critic — Skill Functions

`ux-critic` is a Claude Code skill (installed at `~/.claude/skills/ux-critic/`) that runs a structured
UX/UI critique on a screenshot, image, or live webpage, and produces both a visually annotated image and
a matching written report. It triggers whenever a URL or screenshot/image of an app or website is shared
along with a request for a UX review, critique, feedback, or improvement suggestions.

## Functions

### 1. Input handling
- **URL input** — captures a screenshot of the live page using browser automation (the `claude-in-chrome`
  tools), then treats that screenshot as the subject of analysis.
- **Image input** — uses an attached/referenced image directly, no browser step needed.

### 2. Critique pass
Evaluates the image against ten UX heuristics, grounding every finding in a specific, visible region
rather than generic advice:
- Visual hierarchy
- Information architecture
- Spacing / alignment
- Typography
- Color contrast & accessibility
- Tap/click target sizing
- Consistency
- Feedback / affordance
- Error prevention
- Cognitive load

### 3. Issue localization
For each flagged issue, estimates a bounding box as a **fraction of the image's width/height** (not raw
pixels) — a vision model judging "about a third of the way down, left column" is reliable; guessing exact
pixel coordinates is not. These fractions get converted to real pixel coordinates by the rendering script.

### 4. Visual output — annotated callouts
Runs the bundled script `scripts/annotate_callouts.py` (Python + Pillow) to draw numbered callout markers
on a copy of the image: a red outline (box or ellipse) around each flagged region, plus a numbered red
badge at its corner. The script handles font fallback, scaling stroke/badge size to the image's
resolution, and clamping badges so they never fall off-canvas.

### 5. Text output — matching numbered list
Produces a numbered list, 1:1 with the callout markers, in **critique mode**:
- **What's wrong** — the concrete observation
- **Why it's a problem** — which heuristic it violates and the real consequence for a user
- **Fix** — a specific, actionable change

### 6. Improve mode
When asked to "fix" or "improve" rather than just critique, reuses the exact same numbered callouts at
the same locations, but reframes each entry as a change rather than a complaint:
- **Current** — what's there now
- **Recommended** — precisely what to change it to, and why

No new mockup image is generated in this mode — only the original image gets annotated.

### 7. Prioritization and capping
Orders issues most-impactful-first and caps the list at the top 8–12 issues, so the critique stays
actionable rather than an overwhelming, unranked dump of nitpicks.

### 8. Combined presentation
Always pairs the annotated image with its corresponding numbered text list in the same response, image
first, so a marker on the image and its explanation in the list can be found by number without
cross-referencing effort.
