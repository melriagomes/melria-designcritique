---
name: interaction-critic
description: Critiques how an interface behaves over time, not how it looks — affordances (can users tell what's interactive?), feedback after actions, transitions/animations/state changes, interaction sequences and flow, discoverability of controls, system status and responses, loading/success/error/empty/disabled states, microinteractions, timing and continuity between states, and error prevention/recovery. Advises on how interactions should behave, what should happen before/during/after an action, and how motion and feedback can make an experience clearer and more responsive. Use whenever the user asks about interaction behavior, feedback, animations, transitions, loading/error states, or "does this feel responsive/predictable" for a live URL or app — as distinct from a static visual/usability snapshot (route pure look-and-feel or single-screenshot usability questions to graphic-critic or ux-critic instead).
---

# Interaction Critic

This skill's subject is **behavior over time** — what happens before, during, and after a user acts — not a single static frame. A screenshot alone can't show whether a button gives feedback when pressed, whether a loading state appears, or whether a transition is jarring or smooth. Get that time dimension before critiquing, or be explicit about what you couldn't observe.

**Lane check:** if the request is really "does this screen look good/usable" with nothing to observe changing over time, that's `ux-critic` (usability) or `graphic-critic` (aesthetics), not this skill. This skill earns its keep specifically on sequences, transitions, and responses to action.

## What to look for

- **Affordances** — can a user tell what's interactive just by looking (before touching anything)?
- **Feedback after actions** — does something visibly/audibly acknowledge that an action registered?
- **Transitions, animations, and state changes** — are they smooth, purposeful, and appropriately paced, or jarring/absent/gratuitous?
- **Interaction sequences and flow** — does a multi-step process feel coherent step to step?
- **Discoverability of controls** — would a first-time user find the control they need without hunting?
- **System status and responses** — does the interface communicate what's happening at all times, especially mid-process?
- **Loading, success, error, empty, and disabled states** — does each exist, and does it communicate clearly what's going on and what to do next?
- **Microinteractions** — small responsive touches (hover states, toggles, input validation-as-you-type) that add or fail to add clarity.
- **Timing, motion, and continuity between states** — do delays get appropriate feedback, and does motion help the user track what changed?
- **Predictability and intentionality** — does the interaction behave the way its affordances promised, consistently?
- **Error prevention and recovery** — are mistakes hard to make, and easy to undo/recover from when they happen?

For each issue, anchor it to a specific, observed moment — not "the feedback could be better" but "after clicking 'Save', nothing changes on screen for roughly 2 seconds before the page silently reloads — there's no spinner, disabled-state, or other acknowledgment that the click registered, so a user is likely to click again." Never assert behavior you didn't actually observe.

**Prioritize and cap.** Order issues by how much they'd undermine a user's confidence that the system is responding correctly — stop at the top 8–12.

## Step 1: Observe the interaction sequence

- **Live URL:** use the `claude-in-chrome` browser tools (load that skill first if needed) to actually perform the interaction — click, type, submit, trigger the states relevant to the request. Capture a screenshot at each meaningful moment: before the action, immediately after (mid-transition/loading), and once it settles (success/error/empty/disabled). Note the rough elapsed time between screenshots if you can observe it (e.g. how long a spinner stayed visible) — this feeds Step 2.
- **User provides a sequence already** (ordered screenshots, GIF frames, or a described flow): use those directly, in order.
- **Only a single static screenshot is available, with no way to trigger or observe transitions:** say so plainly. Critique what a static frame *can* tell you (visible affordance cues, whether a loading/error/empty state is shown in this particular frame) and be explicit that timing, feedback, and transition quality can't be assessed without actually observing the interaction.

## Step 2 (optional): Check timing against Nielsen's thresholds with `timing_reference_check.ts`

Only if you actually observed timestamps (from Step 1's live walkthrough, or timestamps visible in a provided recording). **Never invent timing you didn't witness** — skip this step rather than guess at durations.

Write the observed events to a JSON array, in order:

```json
[
  {"label": "user clicks Save", "atMs": 0},
  {"label": "page reloads with no visible feedback", "atMs": 2100}
]
```

Then run (path relative to this skill's own directory):

```bash
node <skill_dir>/scripts/dist/timing_reference_check.js <sequence.json>
```

(after `npm install && npm run build` in `scripts/` once — zero runtime dependencies). It classifies each gap against Jakob Nielsen's classic 0.1s/1s/10s response-time thresholds and returns standard guidance for that band (e.g. a 1–10s gap essentially requires a loading indicator). Use this to ground timing-related findings in an established reference rather than a vague "that felt slow."

## Step 3: Critique pass

Evaluate against the categories above, using what you actually observed in Step 1 and any timing data from Step 2.

## Step 4: Locate each issue as a fraction of the relevant frame

Pick whichever captured screenshot best shows each issue (the "before" frame for a missing affordance, the settled frame for a missing success state, etc.). Same convention as every critique skill in this project: bounding box as `[x1, y1, x2, y2]`, each a fraction (0–1) of that frame's width/height.

```json
[
  {"number": 1, "shape": "box", "bbox_fraction": [0.40, 0.70, 0.60, 0.80], "description": "Save button — no visible pressed/loading state after click"}
]
```

If different issues live on different frames, group entries by which frame they belong to — you'll invoke `screenshot-annotator` once per frame.

## Step 5: Render annotated frame(s) via `screenshot-annotator`

For each frame that has flagged issues, invoke the `screenshot-annotator` skill with that frame and its JSON array of entries. Don't reimplement the drawing logic here — it's shared across every critique skill in this project. If multiple frames are annotated, present them in the sequence they occurred, each labeled with which moment it captures (e.g. "before," "mid-action," "after").

## Step 6: Write the matching text list

For each number, in the same order as presented:

```markdown
**1. <short title for the issue>**
- **What happens now:** <concrete observation of the actual behavior/timing>
- **Why it's a problem:** <which interaction principle it violates and the real consequence — confusion, repeated clicks, lost trust, etc.>
- **What should happen instead:** <specific before/during/after prescription — not "add feedback" but "on click, immediately disable the button and show a spinner in its place; on success, replace it with a brief checkmark state for ~800ms before returning to normal">
```

If the user asked to "fix"/"improve"/"redesign" rather than just critique: keep the same numbered callouts, but frame each as **Current behavior** → **Recommended behavior** instead of a complaint.

## Step 7: Present everything together

Show the annotated frame(s) and the numbered list in the same response, images first (in sequence order if more than one), list matching by number.

## Notes

- Never fabricate a transition, timing, or state you didn't actually observe or weren't given — say what you couldn't check rather than inventing plausible-sounding behavior.
- Never fabricate an issue to hit a target count — fewer, real, well-anchored issues beat padding.
- If a flagged issue turns out to be purely visual (e.g. a color/contrast problem with nothing to do with timing or state) rather than behavioral, that's `graphic-critic`/`ux-critic` territory — say so rather than force-fitting it here.
