---
name: screenshot-annotator
description: Takes a screenshot of an image or URL, marks the specific regions where problems occur with numbered callout markers, and pairs each marker with a description. A reusable visual-annotation primitive — it does not decide what's wrong on its own; it renders whatever numbered problem regions and descriptions it's given (typically by another skill, like ux-critic, that already did that analysis) or, if invoked directly with a plain request to "mark"/"point out"/"highlight" specific issues on an image or page, does its own lightweight visual read to find and locate them.
---

# Screenshot Annotator

Turn "here's an image/URL and here's what's wrong with it" into one annotated screenshot with numbered markers, paired 1:1 with a numbered list of descriptions. This skill owns the *rendering* half of that job — capturing the image and drawing the markers — not necessarily the *judgment* half of deciding what counts as a problem (a caller like `ux-critic` supplies that; used standalone, do your own quick visual read to locate what was asked about).

## Step 1: Get the image

- **A URL was given:** capture a screenshot using the `claude-in-chrome` browser tools (load the `claude-in-chrome` skill first if it isn't already active, then navigate and take a screenshot). Prefer full-page/full-viewport over a cropped capture — cropping first risks cutting off a region worth marking. Save it to a file.
- **An image was given directly** (attached, referenced, or an already-resolved local file path from a caller): use it as-is.
- **A caller already resolved the image itself** (e.g. `ux-critic` captured it during its own critique pass) and hands you a local file path directly: skip capturing again, just use that path.

## Step 2: Get the list of problem regions

Two ways this list gets populated:

- **Invoked by another skill/caller** that already identified the problems: it hands you the number, a short description, and a bounding box per issue. Use those as given — don't second-guess or re-derive them.
- **Invoked directly** (a user just asks you to mark/highlight/point out specific things on an image, without another skill's analysis behind it): look at the image yourself and locate the requested regions.

Either way, build a JSON array, one entry per marker, in numbered order:

```json
[
  {"number": 1, "shape": "box", "bbox_fraction": [0.05, 0.10, 0.35, 0.16], "description": "short description of what's flagged here"},
  {"number": 2, "shape": "ellipse", "bbox_fraction": [0.42, 0.30, 0.58, 0.38], "description": "..."}
]
```

`bbox_fraction` is `[x1, y1, x2, y2]`, each a fraction (0–1) of the image's width/height, top-left origin — not raw pixels. A vision model judging "about a third of the way down, spanning the left column" is reliable; guessing exact pixel coordinates on a resized image is not, which is why the rendering script takes fractions and converts them itself. Use `"shape": "box"` for anything rectangular and `"ellipse"` only when a circular/blob marker reads more naturally; default to `"box"`.

Write just `number`, `shape`, and `bbox_fraction` to a separate `annotations.json` file for the rendering script (Step 3) — keep `description` alongside for Step 4's text list, but the script itself doesn't need it.

## Step 3: Render the annotated image

Run the bundled script (path relative to this skill's own directory, wherever it's installed):

```bash
python <skill_dir>/scripts/annotate_callouts.py <input_image> <annotations.json> <output_image>
```

(or the TypeScript version, functionally identical: `node <skill_dir>/scripts/dist/annotate_callouts.js <input_image> <annotations.json> <output_image>`, after `npm install && npm run build` in `scripts/` — the Python version needs no build step and is the simpler default.)

This draws the outline for each shape plus a numbered red badge at its top-left corner, handling font fallback, edge-clamping so badges never fall off-canvas, and scaling stroke/badge size to the image's resolution. Don't hand-roll this drawing logic elsewhere — this script is the one place it lives.

## Step 4: Return both together

Hand back (to the caller, or directly to the user if invoked standalone):
- The annotated image, image first.
- A numbered list, in the same order as the markers, each with its `description`.

A marker with no matching description (or vice versa) defeats the point — a reader should be able to glance at the image, find marker `4`, and read exactly what it refers to with no cross-referencing effort.

## Notes

- This skill has no opinion on *what* counts as a problem. If invoked standalone for something more involved than a few explicitly-requested regions (e.g. "find everything wrong with this UI"), that's a signal the caller wants `ux-critic` instead — say so rather than improvising heuristic judgment this skill doesn't own.
- If the screenshot is very tall and markers cluster awkwardly, say so and either focus on the most relevant section or note that a viewport-height crop would read more clearly next time — but still render the full pass on what was captured.
