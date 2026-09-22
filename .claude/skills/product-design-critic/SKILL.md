---
name: product-design-critic
description: Critiques whether a digital design serves its larger product — product purpose, value proposition, feature relevance and prioritization, end-to-end user journeys, information architecture, product logic, missing functionality, edge cases, different user scenarios, scalability, and consistency across the product. Overlays numbered callout markers on a screenshot/image and writes a matching numbered list of product-level issues and concrete fixes. Distinct from `product-critic`, which is for physical/industrial objects (ergonomics, materials) — this skill is for digital products (apps, websites, screens). Use whenever the user shares a UI/product screenshot and asks about product strategy, feature fit, user journeys, scope, or "does this make sense for the product" — as distinct from usability (route to `ux-critic`), visual aesthetics (`graphic-critic`), interaction behavior (`interaction-critic`), or a physical object (`product-critic`).
---

# Product Design Critic

Produce a screenshot annotated with numbered callout markers, paired with a numbered text list that explains each flagged product-level issue and how to fix it. The image and the list always travel together in the same response, image first.

**This skill's lane is product strategy and fit — not physical objects, and not the screen's surface-level usability or aesthetics.** A photo of a physical object is `product-critic`'s lane, not this skill's. A button being visually inconsistent is `graphic-critic`'s; a button being hard to tap is `ux-critic`'s; whether the feature that button belongs to should exist at all, or fits the product's actual user journey, is this skill's. Do not evaluate the screen in isolation when broader product context (a design brief, goals, audience, business requirements) is available — ground findings in that context.

## What to look for

Evaluate against these categories, and hold each one up against the questions beside it. Not every category will surface an issue on every piece — that's expected:

- **Product purpose and value proposition** — what problem is this product solving, and does the design actually support that problem?
- **Feature relevance and relationships** — does each feature have a clear purpose? Are there unnecessary features or steps? Do features relate to one another coherently?
- **End-to-end journeys** — does the journey make sense from beginning to end? Are there gaps between different parts of the product?
- **Information architecture and product logic** — is the structure and flow logical given what the product is trying to do?
- **User goals and business/product goals** — when goals are provided, does the design serve both; when they're not, say so rather than inventing them.
- **Feature prioritization and unnecessary complexity** — is anything over-built relative to its importance, or under-served relative to how central it is?
- **Missing functionality and edge cases** — is anything important missing? What happens for users who don't follow the ideal path?
- **Different user scenarios and scalability** — does the product behave coherently across different scenarios, and will this design still make sense as the product grows?
- **Consistency across the product** — does this screen cohere with the rest of the experience, as far as it's visible?

For each issue, anchor it to a specific element, region, or step in the flow — not "the onboarding feels off" but "step 3 of onboarding asks for a business address before the user has indicated they're a business account, forcing personal-account users through an irrelevant field." Every issue must pair with a concrete, actionable recommendation — say exactly what should exist, change, or be removed, never a generic "streamline the flow."

**Prioritize and cap.** Order issues by how much they'd hurt the product's coherence or its users' ability to accomplish their goal — stop at the top 8–12.

## Step 1: Get the image

- **User gives a URL:** capture a screenshot using the `claude-in-chrome` browser tools (load that skill first if needed), full-page/full-viewport, not pre-cropped.
- **User attaches or references an image directly:** use it as-is.
- If neither is available, ask for one rather than critiquing a product you haven't seen.

## Step 2: Ground in the provided context

Evaluate product decisions against whatever the user actually supplied — a design brief, product goals, target audience, user needs, business requirements, technical constraints. **Never invent a business goal, an audience, or a constraint that wasn't given.** If context is missing, say so explicitly in the relevant finding and critique only what's inferable from general best practice for this apparent type of product/screen, rather than asserting a business rationale you don't actually have.

## Step 3: Critique pass

Evaluate against the categories above, using the image from Step 1 and the context from Step 2. Stay out of other specialists' lanes even where you notice something there: font choices, colour palettes, pixel-level visual polish, and animation timing belong primarily to `graphic-critic` and `interaction-critic`, not this skill.

## Step 4: Locate each issue as a fraction of the image

Same convention throughout this project: bounding boxes as `[x1, y1, x2, y2]`, each a fraction (0–1) of the image's width/height, top-left origin — reliable for a vision model to estimate, unlike exact pixel guessing. A finding that's genuinely conceptual (e.g. "a whole missing screen in the journey") may have no single visible region — it's fine to leave such a finding out of the JSON array and note in the text list that it isn't tied to a specific marker.

```json
[
  {"number": 1, "shape": "box", "bbox_fraction": [0.10, 0.55, 0.90, 0.68], "description": "Business-address field shown before account type is established"}
]
```

## Step 5: Render the annotated image via `screenshot-annotator`

Invoke the `screenshot-annotator` skill, handing it the image and the JSON array from Step 4. Don't reimplement the drawing logic here — it's shared across every critique skill in this project.

## Step 6: Write the matching text list

For each number, in the same order as the JSON:

```markdown
**1. <short title for the issue>**
- **Product problem:** <what product-level issue exists, naming the specific element/step>
- **Evidence:** <exactly where this is visible in the design or flow>
- **Impact:** <why this matters to the product or user journey>
- **Recommendation:** <specific product-level change — say exactly what should exist, change, or be removed>
```

If the user asked to "fix"/"improve"/"redesign" rather than just critique: keep the same numbered callouts at the same points, but frame each as **Current** → **Recommended** instead of a complaint, and don't generate a new mockup — only annotate the original.

## Step 7: Present both together

Show the annotated image and the numbered list in the same response, image first.

## Notes

- Never fabricate a business goal, audience, or constraint that wasn't provided — say explicitly when a recommendation's validity depends on missing context.
- Never fabricate an issue to hit a target count — fewer, real, well-anchored issues beat padding.
- If a flagged issue is really about visual polish, usability, interaction behavior, or a physical object, say so and point to `graphic-critic`, `ux-critic`, `interaction-critic`, or `product-critic` respectively rather than force-fitting it here.
