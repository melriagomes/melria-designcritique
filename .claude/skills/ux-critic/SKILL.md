---
name: ux-critic
description: Runs a structured UX/UI critique of a screenshot, image, or live webpage — evaluating visual hierarchy, information architecture, spacing/alignment, typography, color contrast, accessibility, tap/click target sizing, consistency, feedback/affordance, error prevention, and cognitive load — then overlays numbered callout markers on the image and writes a matching numbered list of problems and concrete fixes. Use this whenever the user shares a URL or attaches/references a screenshot or image of an app, website, or UI screen and asks for a UX review, design critique, feedback, "what's wrong with this", or improvement suggestions — even if they never say the words "UX" or "critique". Also covers "fix"/"improve" requests, which reuse the same numbered callouts but describe before → after changes instead of just problems.
---

# UX Critic

Produce a screenshot annotated with numbered callout markers, paired with a numbered text list that explains each flagged issue and how to fix it. The image and the list always travel together in the same response — a callout with no matching text entry (or vice versa) defeats the point.

## Why this shape of output works

A written critique without visual anchoring forces the reader to hunt for what "the CTA in the header" even refers to. A screenshot with unlabeled red boxes forces them to guess why a box is there. Numbering both and keeping them 1:1 lets someone glance at the image, find marker `4`, and read exactly what's wrong there and what to do about it — no cross-referencing required.

## Step 1: Get the image

- **User gives a URL:** capture a screenshot of the live page using the `claude-in-chrome` browser tools (load the `claude-in-chrome` skill first if it isn't already active, then navigate to the URL and take a screenshot). Prefer a full-page or full-viewport capture over a cropped one — cropping before the critique risks cutting off the exact regions worth flagging. Save the screenshot to a file so the annotation script can read it.
- **User attaches or references an image directly:** use it as-is, no browser involved.
- If neither a working URL nor an image is available, ask for one rather than guessing at a design that hasn't been shown to you.

## Step 2: Critique pass

Look at the image and evaluate it against these heuristics. Not every heuristic will surface an issue on every screen — that's expected:

- **Visual hierarchy** — does the most important element actually look the most important?
- **Information architecture** — is content grouped and ordered the way a user's task would need it?
- **Spacing / alignment** — inconsistent gutters, misaligned edges, cramped or lopsided padding.
- **Typography** — size/weight contrast, line length, readability, too many competing styles.
- **Color contrast & accessibility** — text-to-background contrast, color as the only signal for state/error.
- **Tap/click target sizing** — interactive elements too small or too close together, especially for touch.
- **Consistency** — the same kind of element (button, link, icon) styled or behaving differently in different places.
- **Feedback / affordance** — does it look clickable if it's clickable? Is there a visible response to actions?
- **Error prevention** — destructive or irreversible actions without confirmation, ambiguous inputs.
- **Cognitive load** — too many simultaneous choices/options, unclear next step.

For each problem you decide to flag, anchor it to a specific region of the image — not "the typography could be better" but "the body text at the top-left, under the logo, is set at roughly the same size and weight as the nav links, so nothing reads as more important than anything else." Vague, ungrounded advice is the failure mode this skill exists to avoid.

**Prioritize and cap.** Order issues most-impactful-first (what would most hurt a real user's ability to complete their task), and stop at the top 8–12. A screen with 40 nitpicks buried under equal weight is less useful than a screen with the 8 things that actually matter, ranked.

## Step 3: Locate each issue as a fraction of the image

For every flagged issue, estimate a bounding box around the offending element **as a fraction of the image's width and height** — e.g. `[0.05, 0.10, 0.35, 0.16]` for something spanning roughly the left third, starting 10% down and ending 16% down. Judging position as "about a third of the way down, spanning the left column" is something a vision model does reliably; guessing exact pixel coordinates on a resized image is not — that's why the script (Step 4) takes fractions and converts them itself.

Build a JSON array, one entry per issue, in numbered order:

```json
[
  {"number": 1, "shape": "box", "bbox_fraction": [0.05, 0.10, 0.35, 0.16]},
  {"number": 2, "shape": "ellipse", "bbox_fraction": [0.42, 0.30, 0.58, 0.38]}
]
```

Use `"shape": "box"` for anything rectangular (buttons, cards, text blocks, nav bars) and `"ellipse"` only when a circular/blob marker reads more naturally (e.g. a small icon). Default to `"box"` when unsure. Write this array to a JSON file.

## Step 4: Render the annotated image

Run the bundled script (path is relative to this skill's own directory, wherever it's installed):

```bash
python <skill_dir>/scripts/annotate_callouts.py <input_image> <annotations.json> <output_image>
```

This draws the outline for each shape plus a numbered red badge at its top-left corner, and saves the result. Don't hand-roll this drawing logic — the script already handles font fallback, edge-clamping so badges never fall off-canvas, and scaling stroke/badge size to the image's resolution.

## Step 5: Write the matching text list

**Critique mode** (default — user asked for a review/critique/feedback): for each number, in the same order as the JSON:

```markdown
**1. <short title for the issue>**
- **What's wrong:** <concrete observation>
- **Why it's a problem:** <the heuristic it violates and the real consequence for a user>
- **Fix:** <specific, actionable change — not "improve the contrast" but "darken the body text from #999 to at least #595959 to clear WCAG AA against the white background">
```

**Improve mode** (user asked to "fix", "improve", or "redesign" rather than just critique): keep the exact same numbered callouts located at the same points, but frame each entry as a change rather than a complaint — and do not generate a new mockup image, only annotate the original:

```markdown
**1. <short title for the change>**
- **Current:** <what's there now>
- **Recommended:** <precisely what to change it to, and why that's better>
```

## Step 6: Present both together

Show the annotated image and the numbered list in the same response, image first. If the medium doesn't support inline images, at minimum state the output image's path right next to the list so the two are easy to line up.

## Notes

- If the screenshot is very tall (e.g. a full scrollable page) and issues cluster in a way that makes markers hard to read at a glance, it's fine to say so and either focus the critique on the most important section or note that a viewport-height crop would read more clearly next time — but still deliver the full numbered pass on what you captured.
- Never fabricate an issue to hit a target count. Fewer, real, well-anchored issues beat padding the list to look thorough.
