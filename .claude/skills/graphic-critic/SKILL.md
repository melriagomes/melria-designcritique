---
name: graphic-critic
description: Critiques the visual communication and aesthetic system of a design — typography, color, composition, visual hierarchy, imagery/illustration/icons, brand consistency, grid/rhythm, and whether the visual style matches its intended mood/audience/message. Overlays numbered callout markers on the image and writes a matching numbered list of aesthetic issues and concrete fixes, aimed at making the design more visually coherent, expressive, polished, memorable, and intentional. Use whenever the user shares a design (screenshot, poster, branding asset, slide, illustration, or UI visual) and asks about its look, visual style, aesthetics, typography, color, composition, or "does this look good" / "how could this look better visually" — as distinct from usability feedback (route pure interaction/usability questions to ux-critic instead).
---

# Graphic Critic

Produce a screenshot annotated with numbered callout markers, paired with a numbered text list that explains each flagged aesthetic issue and how to fix it. The image and the list always travel together in the same response, image first.

**This skill's lane is the visual/aesthetic system, not usability.** A button being visually inconsistent with the rest of the UI's style is this skill's concern; a button being too small to tap reliably is `ux-critic`'s. The same screen can get both critiques, but keep the two separate — don't let "this looks bad" and "this is hard to use" blur into each other. If a request is really about usability, interaction, or task-completion friction, that's `ux-critic`, not this skill.

## What to look for

Evaluate the design against these categories. Not every category will surface an issue on every piece — that's expected:

- **Typography** — font choice, hierarchy between text roles, pairing (do the fonts used actually work together), readability (size, weight, line length, line height).
- **Color** — palette choice, contrast, harmony (do the hues relate intentionally — complementary, analogous, monochrome — or clash), consistency of use across the piece.
- **Composition** — balance, spacing, alignment, visual weight distribution (does one area overpower or unbalance the rest).
- **Visual hierarchy and focal points** — is there a clear entry point for the eye, and does it lead where it should.
- **Imagery, illustration, icons, and graphic elements** — quality, style consistency, whether they reinforce or fight the rest of the piece.
- **Consistency of visual language and branding** — do recurring elements (colors, shapes, iconography, type) actually recur consistently, or drift.
- **Grid, proportions, rhythm, and repetition** — is there an underlying structure, and is it honored or broken without reason.
- **Mood/audience/message fit** — does the visual style (playful vs. serious, minimal vs. dense, warm vs. clinical) actually match what the piece is trying to communicate and to whom.

For each issue, anchor it to a specific region — not "the color palette feels off" but "the CTA's orange (roughly #E8703A) sits against a magenta header (#C13584) with no shared hue relationship, so the two most attention-grabbing elements compete instead of one leading the eye." Ground every claim in what's actually visible.

**Prioritize and cap.** Order issues by how much they'd hurt the piece's visual coherence, polish, or intended impression — stop at the top 8–12.

## Step 1: Get the image

- **User gives a URL:** capture a screenshot using the `claude-in-chrome` browser tools (load that skill first if needed), full-page/full-viewport, not pre-cropped.
- **User attaches or references an image directly:** use it as-is.
- If neither is available, ask for one rather than critiquing a design you haven't seen.

## Step 2: Ground color claims with `color_palette.ts`

Before writing any Color-category findings, run the bundled script (path relative to this skill's own directory):

```bash
node <skill_dir>/scripts/dist/color_palette.js <image>
```

(after `npm install && npm run build` in `scripts/` once; supports PNG and JPEG). It reports the actual dominant colors (as hex, with their share of the image) and real WCAG contrast ratios between every pair of dominant colors — use these numbers instead of eyeballing hex values or guessing at contrast. This is data-gathering only; the judgment of whether a palette is *harmonious*, *on-mood*, or *on-brand* is still yours to make by looking at the image, not something the script decides.

## Step 3: Critique pass

Evaluate against the categories above, using both your own visual read of the image and the palette data from Step 2 where relevant (Color category, and any contrast-adjacent Typography readability calls).

## Step 4: Locate each issue as a fraction of the image

Same convention throughout this project: bounding boxes as `[x1, y1, x2, y2]`, each a fraction (0–1) of the image's width/height, not raw pixels — reliable for a vision model to estimate, unlike exact pixel guessing.

Build a JSON array, one entry per issue, with a short description:

```json
[
  {"number": 1, "shape": "box", "bbox_fraction": [0.05, 0.10, 0.35, 0.16], "description": "CTA orange vs. header magenta — no shared hue relationship"}
]
```

## Step 5: Render the annotated image via `screenshot-annotator`

Invoke the `screenshot-annotator` skill, handing it the image and the JSON array from Step 4. It captures/uses the image and draws the numbered markers — don't reimplement that drawing logic here; it already lives in one shared place used by every critique skill in this project.

## Step 6: Write the matching text list

For each number, in the same order as the JSON:

```markdown
**1. <short title for the issue>**
- **What's off:** <concrete observation, with actual hex/measurement data from Step 2 where it's a color claim>
- **Why it matters:** <which aesthetic category it falls under and what impression/coherence it costs the piece>
- **Fix:** <specific, actionable change — not "improve the palette" but "shift the CTA to a warm coral (#E8703A → #D9634E) that sits within 30° of the header's hue on the color wheel instead of directly opposing it">
```

If the user asked to "fix"/"improve"/"redesign" rather than just critique: keep the same numbered callouts at the same points, but frame each as **Current** → **Recommended** instead of a complaint, and don't generate a new mockup — only annotate the original.

## Step 7: Present both together

Show the annotated image and the numbered list in the same response, image first.

## Notes

- Never fabricate an issue to hit a target count — fewer, real, well-anchored issues beat padding.
- If a flagged issue is really a usability problem wearing an aesthetic costume (e.g. "the button is invisible" turning out to be about tap-target size, not color), say so and point to `ux-critic` rather than force-fitting it here.
