---
name: read
description: Thoroughly reads and scans a file or image before answering — runs a bundled zero-dependency inspection script to surface structural metadata (an image's true format/dimensions, or a text file's line/word counts, longest-line length, and binary/encoding detection) alongside the actual content, so nothing about a file's shape or size gets missed. Use whenever asked to carefully read, scan, inspect, or thoroughly review a file or image, or whenever a file's metadata (size, dimensions, line count, whether it's binary) matters before diving into its content.
---

# Read

Read a file or image the way a careful reviewer would: know its shape before you read its content, not after. A 50,000-character single line, a 40-megapixel screenshot, or a binary file masquerading as text all change how you should approach reading it — catching that up front avoids wasted, confused, or truncated reading passes.

## Step 1: Scan for structural metadata

Run the bundled script (path is relative to this skill's own directory, wherever it's installed):

```bash
npx ts-node <skill_dir>/scripts/scan_file.ts <path>
```

(or, if it's already been compiled with `npm run build` in `scripts/`, `node <skill_dir>/scripts/dist/scan_file.js <path>`)

This has zero npm dependencies — nothing to compile natively, `npm install` in `scripts/` is instant. It reports, as JSON:

- **Image** (`kind: "image"`) — `format` (png/jpeg/gif/bmp/webp, detected by hand-parsing the file's own header bytes, not by decoding it), `width`, `height`, `megapixels`, `sizeBytes`.
- **Text** (`kind: "text"`) — `lineCount`, `wordCount`, `charCount`, `longestLineLength`, `hasVeryLongLines` (flags files like minified JS or a single giant JSON line that read differently than normal prose/code), `sizeBytes`.
- **Binary** (`kind: "binary"`) — just `sizeBytes` and a hash; the content isn't text and shouldn't be read as such.

## Step 2: Read the actual content, informed by that metadata

- **Image:** use the Read tool to view it. If `megapixels` is very large, mention that up front — a huge screenshot may need to be cropped or downscaled for downstream steps (e.g. before sending to a vision API with a pixel limit).
- **Text, normal shape:** use the Read tool as usual.
- **Text with `hasVeryLongLines: true`:** don't assume a normal line-by-line skim will surface what matters — call this out, and consider whether the task needs the whole line or just a targeted search/grep within it.
- **Text, very large `lineCount`:** read in offset/limit chunks rather than trying to pull the whole file in one pass.
- **Binary:** don't attempt to read it as text. Say what it is (from its size/hash and, if relevant, its extension) rather than dumping raw bytes.

## Step 3: Report what you found

State the file's shape (format/dimensions for an image; line/word count and any long-line flag for text) alongside your actual read of its content — not as a separate disconnected fact, but as context for what you observed (e.g. "this is a 6000×4000px screenshot — the button you're asking about is in the bottom-right quadrant").
