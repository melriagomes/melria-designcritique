# Design Critique and Advice — Agent Plan

## Context
An AI agent that takes a design — submitted as a URL link or a screenshot/photo — and gives the user a
detailed critique of it (strengths and weaknesses) along with concrete, actionable advice on how to fix
and improve it. The design can be of any type (UI/UX screen, graphic/poster, branding, product, slide, etc.).
No existing implementation in this repo yet; this plan assumes a fresh build.


## MVP

### Scope
- Accept one design per request, submitted either as a direct image upload (screenshot/photo) or a URL.
- If given a URL: resolve it to a static image — either fetch it directly (if it's already an image URL)
  or capture a screenshot of the page.
- Run the image through a single general-purpose visual-design critique using common heuristics: visual
  hierarchy, contrast, alignment, typography, spacing/whitespace, color, and basic accessibility/legibility.
- Return one structured critique report per submission: an overview assessment, categorized issues, and a
  prioritized list of specific fixes — plain text/markdown, no visual markup.
- One design type, one rubric — no attempt to detect or specialize by design discipline (UI vs. print vs.
  branding, etc.) at this stage.
- No accounts, no saved history — stateless, one-shot request/response.

### Non-goals (for MVP)
- No before/after mockup or redesign generation — advice only, never an edited version of the design.
- No multi-turn follow-up conversation — one critique per submission, no "why is this flagged?" chat.
- No discipline-specific critique frameworks (separate rubrics per design type).
- No history, accounts, or before/after comparison across revisions.
- No numeric scoring (e.g. "72/100") — qualitative critique and fix list only.
- No batch/multi-design submissions — one design per request.

### AI role & integration
The AI's job in the MVP is a single multimodal (vision + language) analysis call — there is no agentic
loop or multi-step reasoning yet; the "agent" behavior is really one well-prompted vision-language call.

Flow:
1. User submits a design (image upload or URL).
2. A preprocessing step resolves the input to a static image: pass an image upload through as-is; for a
   URL, fetch it directly if it's already an image, otherwise render and screenshot the page.
3. The resolved image plus a fixed system prompt (encoding the visual-design heuristics above) is sent to
   a multimodal model in a single prompt call — image in, structured critique text out.
4. The model's response is returned to the user largely as-is, formatted into the report structure below.
5. No memory, no tool use, no follow-up calls — the request ends after step 4.

Integration point: one direct API call to a vision-capable model, triggered synchronously by the user's
submission. No external tools, no state.

### Suggested technical approach (MVP)
No stack exists in this repo yet, so an AI coding agent needs a concrete starting point rather than an
abstract flow. Assumption, stated here so it can be corrected: a small web app —
a single-page front end (upload widget + URL input + report view) backed by one server route that calls
a vision-capable LLM (e.g. the Claude API with an image content block). No database, no auth, no queue —
the server route is stateless request-in/response-out. This keeps the MVP deployable as a single small
service (e.g. one Next.js app, or a static front end + one serverless function) without committing to
infrastructure the Final Sketch doesn't yet need.

The fixed system prompt for the critique call should explicitly enumerate the rubric categories (visual
hierarchy, contrast, alignment/grid, typography, spacing/whitespace, color, accessibility/legibility) and
instruct the model to return output in the report structure below, so formatting is a prompting concern,
not a separate parsing step.

### Outcomes for an AI coding agent to build
- [ ] User can upload an image (screenshot/photo) and receive a text critique covering at least three
  distinct design categories (e.g. hierarchy, color, typography), each with specific issues called out.
- [ ] User can submit a URL instead of a file, and the agent resolves it to an image (direct fetch if the
  URL's content-type is already an image, otherwise a rendered screenshot of the page) before producing
  the same kind of critique.
- [ ] Every issue identified in the critique is paired with at least one concrete, actionable fix
  recommendation (never just "this looks off" with no suggested remedy).
- [ ] Each fix recommendation is specific enough to act on without guessing (names the element/area and
  the change — e.g. "increase the CTA button's contrast ratio against its background" — not just
  "improve contrast").
- [ ] If the URL or image fails to load/resolve (404, non-image content-type, timeout, corrupt file), the
  user sees a clear, specific error message naming what went wrong instead of a silent failure or a
  critique of a blank/broken image.
- [ ] Uploading a file above a defined size limit or in an unsupported format (e.g. not png/jpg/webp)
  produces a clear rejection message before any model call is made, rather than an opaque API error.
- [ ] The critique report renders as distinct headed sections (overview, issues by category, prioritized
  fixes) rather than one unbroken paragraph, so it can be scanned quickly.
- [ ] The prioritized fixes list is explicitly ordered (e.g. "fix first" to "polish later"), not just a
  flat bag of suggestions, so the user knows where to start.
- [ ] Submitting the same design twice produces critiques that agree on the same major issues (allowing
  for some wording variance), so the tool reads as consistent rather than random.

## Final Version

### Vision
The agent becomes a fuller design-critique assistant: it recognizes what kind of design it's looking at
and tailors its critique accordingly, lets the user ask follow-up questions about the same critique
without resubmitting the design, shows visually where problems are (not just describes them in text),
remembers past critiques so a user can track improvement across revisions, and can compare multiple
design variants against each other in one request.

### Additional scope beyond MVP
- A discipline-detection step that classifies the design type (UI/UX screen, poster/graphic, branding/logo,
  product/industrial, slide/deck, etc.) and selects a matching critique rubric.
- Multi-turn follow-up: the user can ask clarifying questions about a critique in the same session.
- Annotated output: a visually marked-up version of the submitted image highlighting the flagged regions,
  alongside the text critique.
- Persisted history per user/project, so past critiques of the same design can be compared before/after.
- Comparative critique across 2+ submitted design variants in a single request.
- Broader input support: PDFs, multi-page files, Figma links, and interactive prototypes, in addition to
  static images and URLs.

### AI role & integration
The AI's role expands from one flat call to a small agentic pipeline with distinct steps, chained together:

1. **Classification step** — a first AI call inspects the image and identifies its design discipline,
   which selects the rubric/system prompt used in the next step. (New — MVP has no equivalent.)
2. **Critique step** — same core job as the MVP's single call, but now using the discipline-specific
   rubric chosen in step 1 instead of one generic rubric. (Carried over from MVP, now specialized.)
3. **Annotation step** — a follow-up call (either the same model prompted to return region coordinates/
   descriptions, or a separate image-generation/editing call) produces a visually marked-up version of the
   image from the critique step's flagged issues. (New.)
4. **Conversational follow-up** — the agent keeps the original image and critique in session memory, so a
   follow-up question is answered in context without the user re-submitting the design. (New — requires
   session/conversation state that MVP does not have.)
5. **Comparative step** — when multiple design variants are submitted together, all images are given to
   the model in one call with instructions to compare them directly, rather than critiquing each in
   isolation and diffing afterward. (New.)

Integration point: a router/classifier step feeds a main generation step, with an optional annotation call
and an optional comparison call depending on the request shape; conversation memory and a history store
(persisted per user/project) are required to support follow-ups and before/after comparison, neither of
which the MVP needs.

### Suggested technical approach (Final Sketch, beyond MVP)
Builds on the MVP's single service rather than replacing it: add a lightweight account/session layer
(even a simple email+magic-link or anonymous device-id scheme, not necessarily full auth) so critiques can
be tied to a user and a "design" entity that has multiple revisions over time; add a datastore (a simple
relational or document store is enough — no need for anything specialized) to persist critiques, sessions,
and revision history; the annotation step is likely most reliable implemented as the model returning
structured region data (bounding boxes + labels) that the front end draws as an overlay, rather than
asking a model to directly edit pixels.

### Outcomes for an AI coding agent to build
- Given an image, the agent first identifies the design discipline (e.g. "this is a mobile UI screen"), and the critique that follows visibly reflects discipline-specific criteria rather than the generic MVP rubric.
- Misclassification is recoverable: the user can manually override the detected discipline and get a critique re-run under the corrected rubric, without re-uploading the image.
- User can ask a follow-up question about a critique already given in the same session and receive an answer that correctly references the original image and prior critique, without re-submitting the design.
- User receives, alongside the text critique, a visually annotated version of their image with the flagged problem areas marked (e.g. boxed/highlighted regions tied to specific report items).
- Clicking or hovering a specific issue in the text report highlights its corresponding region on the annotated image, and vice versa, so the two views stay linked rather than being two disconnected outputs.
- User can view a history of past critiques for a given design and see improvement compared across revisions (before/after), including which previously flagged issues were resolved and which persist.
- User can submit two or more design variants in a single request and receive a critique that explicitly compares them against each other (stating which variant wins on which criteria), not independent critiques of each rendered side by side.
- User can submit a PDF, a multi-page file, or a Figma/prototype link, and the agent resolves it into the same critique pipeline (converting pages to images, or pulling frames from the design tool) without requiring the user to manually export images first.

## Open assumptions
- "Any type of design" is treated as: MVP uses one general-purpose visual-design rubric rather than building per-discipline rubrics up front; discipline-specific critique is deferred to the Final Version.
- A URL is treated as either a direct image link or a page to screenshot — both resolve to the same kind of static image input for the critique step; no distinction is made downstream once resolved.
- No user-account system is assumed for the MVP, since there's no persistence requirement there; an account system is assumed to be introduced as a prerequisite for the Final Version's history/comparison features.
- This repo's README currently describes a different idea ("melria-indecisionsolver" — an agent for small inconvenient indecisions). This plan is written for the design-critique idea per your explicit prompt; flagging the mismatch in case the README is simply stale rather than intentional.