---
name: design-critique-orchestrator
description: Runs a full, multi-discipline critique of one digital design by resolving it to an image (Figma link, URL, or attached screenshot), dispatching independently to all four specialist critique skills (ux-critic, graphic-critic, product-design-critic, interaction-critic), and synthesizing their findings into one merged report — this project's Orchestrator → Design Reader → Specialist Agents → Synthesizer → Final Critique architecture. Use when the user wants a "full"/"complete"/"all-angles"/"every discipline" critique of a digital design, or asks for a design critique without naming one specific lens and a broad review is clearly wanted. For a request clearly scoped to one lens ("is this accessible", "does this look good", "does this fit our product goals", "does this feel responsive"), invoke that one specialist skill directly instead of this orchestrator.
---

# Design Critique Orchestrator

Coordinates the project's four discipline specialists so a designer gets one coherent, cross-referenced critique instead of four disconnected ones. Mirrors the architecture used by this project's deployed web app (`design_reader.py` → `evidence_reporting.py`'s specialists + synthesis → `screenshot_annotator.py`), adapted to Claude Code's own skills and the `Agent` tool instead of separate API calls.

## Step 1 — Design Reader: resolve the input to one image

- **A `figma.com` URL:** invoke the `figma-reader` skill with it. It hands back a local file path.
- **Any other URL:** load the `claude-in-chrome` skill, navigate to it, and capture a full-page/full-viewport screenshot (never pre-cropped) to a local file in your scratchpad directory.
- **An image is attached/referenced directly:** use it as-is, no resolution step needed.
- If none of the above is available, ask for one rather than guessing at a design nobody has shown you.

Also collect whatever context the user actually gave (audience, goal/purpose, a note) — pass it through verbatim to every specialist in Step 2. If none was given, don't invent any; each specialist should say "not provided" wherever that matters, exactly like a specialist working alone would.

## Step 2 — Specialist Agents: run all four, independently

Each specialist must review the **same image and context**, but must **never see another specialist's output** — that independence is what makes agreement between them meaningful in Step 3. Launch all four in a single message with four parallel `Agent` tool calls (not sequential; not a fork, since these need no shared context beyond what you hand them explicitly), one per discipline:

| Discipline | Skill to invoke |
|---|---|
| UI/UX | `ux-critic` |
| Graphic Design | `graphic-critic` |
| Product Design | `product-design-critic` |
| Interaction Design | `interaction-critic` |

For each, write a **self-contained** prompt (the agent starts with no context of this conversation) along these lines:

> Invoke the `<skill-name>` skill on the image at `<local file path>`. Context provided by the submitter: `<audience/goal/note, or "none provided">`. Produce your critique exactly as that skill specifies — the annotated image and the matching numbered list, image first. Return both in your final report.

Use `subagent_type: "general-purpose"` (or omit it) for each — a fresh agent, not a fork, since a specialist must not inherit this conversation's context or the other specialists' framing. Note in your own working notes which discipline each agent covers so you can label its findings correctly once results come back.

If a specialist has no genuine findings for this particular design (e.g. a static poster with `interaction-critic`, or a screen with no stated goals/audience for `product-design-critic`), that's a legitimate outcome — don't force one, and say so plainly in Step 3 rather than padding.

## Step 3 — Synthesizer: merge the four reports into one

Once all four have returned, compare their findings yourself (you are the synthesizer here — no separate call needed) and write one final report in this structure:

```markdown
## Overview
<what the design is, who it's for, what it's meant to accomplish, grounded in the shared context —
say plainly if audience/goal was never provided rather than inventing one>

## Key Findings
### <Category>
- **Issue:** <grounded finding, citing which discipline(s) raised it, e.g. "(UI/UX, Interaction Design)">
  **Fix:** <specific, actionable recommendation>
  **Needs:** <only when the finding depends on missing context — name exactly what's missing>

(one block per finding worth surfacing — merge duplicates raised by multiple specialists into a single
entry rather than repeating them; keep disciplinary distinctions visible rather than flattening
everything into generic advice)

## Areas of Agreement
- <where two or more specialists independently converged on the same conclusion, and why that matters>

## Areas of Disagreement
- <direct contradictions between specialists' recommendations, both sides stated plainly — never picked
for them>

## Findings by Priority
### Critical / Significant / Minor / Opportunity
<include only the tiers that actually have findings — never manufacture one to fill out the structure>
```

Ground every merged entry in something a specialist actually said — never invent agreement, disagreement, or a finding that didn't come from one of the four reports.

## Step 4 — Final Critique: present everything together

Show, in order:
1. The four specialists' annotated images, each labeled by discipline (each specialist already produced its own via `screenshot-annotator` in Step 2 — don't re-render or merge them into one).
2. The synthesized report from Step 3.

This keeps each specialist's own numbered callouts intact and unambiguous (marker "3" always means UI/UX finding 3, Graphic Design finding 3, etc. — never renumbered across disciplines), while the synthesis text is what actually ties the four views together into one critique.

## Notes

- If a specialist agent fails or times out, say so plainly in the Overview and proceed with the remaining specialists' findings — never silently drop a discipline without noting it, and never block the whole critique on one failure.
- This orchestrator is for a **full, cross-discipline** critique. A request scoped to one lens should go straight to that one skill instead — don't run all four (and burn four agents' worth of work) when the user only asked about, say, accessibility.
