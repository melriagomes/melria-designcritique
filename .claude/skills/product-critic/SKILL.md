---
name: product-critic
description: Critiques a physical object's form, function, ergonomics, materials, and relationship with the user/environment — ergonomics and physical comfort, form and proportions, grip/reach/controls/physical affordances, material and manufacturing considerations, durability and maintenance, assembly and component relationships, physical feedback and mechanisms, safety and accessibility, environmental behavior, and whether the object's form communicates how it should be used. Overlays numbered callout markers on a photo/render and writes a matching numbered list of issues and concrete fixes to form, materials, mechanisms, ergonomics, and physical interactions. Use whenever the user shares a photo or render of a physical product, device, tool, furniture piece, or industrial-design object and asks for feedback on it — as distinct from digital-interface critique (route pure screen/app/website feedback to ux-critic or graphic-critic instead).
---

# Product Critic

Produce a photo/render annotated with numbered callout markers, paired with a numbered text list that explains each flagged physical-design issue and how to fix it. The image and the list always travel together, image first.

**This skill's lane is the physical object**, not a screen. If what's shared is a UI screenshot or webpage, that's `ux-critic` (usability) or `graphic-critic` (visual/aesthetic system) — this skill is for something with mass, materials, and a hand or body that has to interact with it in physical space.

## What to look for

- **Ergonomics and physical comfort** — does holding, wearing, or operating it strain the body?
- **Form and proportions** — do the object's proportions feel resolved, or arbitrary/unbalanced?
- **Grip, reach, controls, and physical affordances** — do surfaces/handles/controls suggest how to hold and operate the object, and are they actually reachable/graspable?
- **Material and manufacturing considerations** — does the apparent material suit the function (texture, weight, rigidity), and does the form look feasible to actually manufacture?
- **Durability and maintenance** — exposed failure points, hard-to-clean geometry, parts that look likely to wear, snap, or loosen.
- **Assembly and component relationships** — do parts meet cleanly, do seams/parting lines make sense, is there evidence of a coherent assembly sequence?
- **Physical feedback and mechanisms** — do buttons/switches/hinges/latches look like they'd give clear tactile/audible confirmation of state?
- **Safety and accessibility** — pinch points, sharp transitions, unstable bases, reach/strength assumptions that exclude some users.
- **How the object behaves in its environment** — stability, footprint, how it sits/mounts/stores, interaction with surfaces or other objects around it.
- **Form-to-function fit** — does the shape actually serve what the object needs to do, or fight it?
- **Does the form communicate use** — could someone unfamiliar with the object figure out how to pick it up and operate it correctly just by looking at it?

For each issue, anchor it to a specific visible region — not "the ergonomics could be better" but "the handle's grip section narrows to roughly the same diameter as the shaft above it, so there's no tactile cue for where to place fingers versus where the mechanism is." Ground every claim in what's actually visible in the image; be explicit when something (internal mechanism quality, actual material, wall thickness, weight) can't be verified from a photo alone rather than asserting it with false confidence.

**Prioritize and cap.** Order issues by what would most hurt real physical use, safety, or manufacturability — stop at the top 8–12.

## Step 1: Get the image

- **User attaches or references a photo/render:** use it as-is. Multiple angles of the same object are welcome — note in your critique which angle each flagged issue is visible in.
- **User gives a URL to a product page/image:** capture it using the `claude-in-chrome` browser tools if it's a live page, or use a direct image URL as-is.
- If no image is available, ask for one rather than critiquing an object you haven't seen.

## Step 2 (optional): Sanity-check dimensions with `ergonomics_reference_check.ts`

Only if you have real numbers to check — from a spec sheet, stated measurements, or a careful estimate anchored to a known reference scale visible in the image (e.g. "this remote is stated as 15cm tall, so the buttons read as roughly 8mm"). **Never invent a precise measurement from a photo with no reference scale** — skip this step entirely rather than guess a number and present it as fact.

If you do have usable numbers, write them to a flat JSON object (keys: `gripDiameterMm`, `precisionGripDiameterMm`, `controlSizeMm`, `controlSpacingMm`, `handleClearanceMm`, `oneHandedWeightKg`, `twoHandedWeightKg` — see the script for the full list) and run (path relative to this skill's own directory):

```bash
node <skill_dir>/scripts/dist/ergonomics_reference_check.js <dimensions.json>
```

(after `npm install && npm run build` in `scripts/` once — zero runtime dependencies, nothing to compile natively). This flags dimensions outside general human-factors reference ranges. **These ranges are general design-guidance figures, not certified ISO/ANSI compliance thresholds** — the script says so in its own output; carry that caveat into anything you tell the user. An `outOfRange` flag is a reason to look closer and explain the real-world consequence, never a bare pass/fail verdict.

## Step 3: Critique pass

Evaluate against the categories above, using your own visual read of the image plus any dimension-check results from Step 2.

## Step 4: Locate each issue as a fraction of the image

Same convention as every critique skill in this project: bounding boxes as `[x1, y1, x2, y2]`, each a fraction (0–1) of the image's width/height, top-left origin.

```json
[
  {"number": 1, "shape": "box", "bbox_fraction": [0.10, 0.40, 0.30, 0.55], "description": "Grip section same diameter as the shaft above it — no tactile handhold cue"}
]
```

## Step 5: Render the annotated image via `screenshot-annotator`

Invoke the `screenshot-annotator` skill with the image and the JSON array from Step 4. Don't reimplement the drawing logic here — it's shared across every critique skill in this project.

## Step 6: Write the matching text list

For each number, in the same order as the JSON:

```markdown
**1. <short title for the issue>**
- **What's off:** <concrete observation, with dimension data from Step 2 where relevant>
- **Why it matters:** <the real-world physical consequence — discomfort, mis-operation, safety risk, manufacturing difficulty>
- **Fix:** <specific, actionable change — not "improve the grip" but "taper the grip section to 32-38mm diameter with a knurled or rubberized band, distinct from the 20mm shaft above it">
```

If the user asked to "fix"/"improve"/"redesign" rather than just critique: keep the same numbered callouts at the same points, but frame each as **Current** → **Recommended** instead of a complaint, and don't generate a new render — only annotate the original image.

## Step 7: Present both together

Show the annotated image and the numbered list in the same response, image first.

## Notes

- Never fabricate an issue to hit a target count — fewer, real, well-anchored issues beat padding.
- Be honest about what a photo can't tell you: internal mechanism quality, exact material composition, wall thickness, weight, and long-term durability are often not verifiable from an image alone. Say so, and note what would need to be checked physically, rather than asserting confident claims about things you can't actually see.
- If a flagged issue is really about a digital interface on the object (e.g. a screen, an app pairing with it) rather than its physical form, that's `ux-critic`/`graphic-critic` territory — say so rather than force-fitting it here.
