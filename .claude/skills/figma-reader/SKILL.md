---
name: figma-reader
description: Resolves a figma.com design/file/board/slides URL to a static local image file, so critique skills (ux-critic, graphic-critic, product-design-critic, interaction-critic) or the design-critique-orchestrator can treat it exactly like any other screenshot. A reusable input-resolution primitive — it has no opinion on design quality, it only turns a Figma link into pixels on disk. Use whenever a figma.com URL is given (directly, or handed off by another skill/orchestrator) and something downstream needs an actual image rather than a link.
---

# Figma Reader

Turn a pasted `figma.com` link into one local PNG file, using this environment's Figma MCP tools rather than the REST API directly — no `FIGMA_API_TOKEN` needed here, since the Figma desktop app connection already handles auth.

This is one of this project's shared "Design Reader" building blocks: it owns *fetching the pixels*, nothing about *judging* them. A caller (a critique skill, or the `design-critique-orchestrator`) hands you a URL and gets back a file path.

## Step 1: Extract the file key and node id from the URL

A Figma URL looks like `https://www.figma.com/design/<fileKey>/<fileName>?node-id=<a>-<b>`:
- `fileKey` — the path segment right after `/design/`, `/board/`, or `/slides/`.
- `node-id` — the `node-id` query parameter, if present. It arrives hyphenated (`123-456`); the MCP tools want it colon-separated (`123:456`) — convert `-` to `:` on the first occurrence.

If the URL has no `node-id` at all, you don't have a node to screenshot yet — go to Step 2 first. If it does, skip straight to Step 3 with that node id.

## Step 2: No node id in the URL — find one

Call `mcp__plugin_figma_figma__get_metadata` with the extracted `fileKey` and no `nodeId`. With `nodeId` omitted, it returns the file's top-level pages (guid + name) instead of a full dump. Take the first page's guid as your node id.

(This mirrors "no node-id in the URL → render the file's first page" — the same fallback this project's web app uses via the Figma REST API — just reached through the MCP metadata call instead of a REST call.)

Note: `get_metadata`/`get_screenshot` only support Figma design files (`/design/` URLs) and, for screenshots specifically, also FigJam boards (`/board/`) and Slides (`/slides/`) — not Figma Make (`/make/`) files. If the URL is a Make file, say so; this skill can't resolve it.

## Step 3: Render the screenshot

Call `mcp__plugin_figma_figma__get_screenshot` with the `fileKey` and the `nodeId` from Step 1 or 2. Leave `maxDimension` at its default (1024) unless the caller specifically needs finer detail (e.g. a critique skill asked you to re-render bigger because a flagged region was too small to read) — then increase it.

The response gives back a short-lived download URL plus ready-to-use curl instructions. **Use the URL/curl path, not `enableBase64Response`** — the base64 option exists only for environments with no shell/HTTP access, which isn't the case here, and it costs far more context for no benefit.

## Step 4: Download it to a local file

Run the curl command the tool response gave you (or an equivalent `curl -o <path> "<url>"`), saving into your scratchpad directory with a descriptive name (e.g. `figma_<fileKey>_<nodeId>.png`). Confirm the file actually landed (non-zero size) before handing it onward — a failed/partial download here would otherwise surface as a confusing downstream image-decode error instead of a clear "the Figma render didn't download" one.

## Step 5: Hand back the local path

Return just the local file path to whichever skill/orchestrator asked for it — that path is now interchangeable with any other locally-resolved image (an upload, or a `claude-in-chrome` screenshot) for everything downstream.

## Notes

- This skill never renders design *judgment* — if asked to critique the Figma design rather than just fetch it, that's the caller's job (`ux-critic`, `graphic-critic`, `product-design-critic`, `interaction-critic`, or `design-critique-orchestrator` for all four at once), not this skill's.
- If the Figma desktop app isn't running, doesn't have the file open, or the MCP tools error out, say so plainly rather than guessing at a fallback — don't silently substitute a blank or placeholder image.
- A URL with a `node-id` pointing at a frame/component nested deep in the file works the same as a page-level node — this skill doesn't need to understand the file's structure beyond the one id it's given or discovers.
