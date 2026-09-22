"""Evidence & Reporting — the specialist critique and synthesis pipeline.

Given one static image (from `design_reader`) and the submitter's context,
this module runs the shared-understanding pass, the independent discipline
specialists (UI/UX, Graphic Design, Product Design, Interaction Design), the
synthesis pass that merges their findings into one report, and a
localization pass that grounds each numbered finding in a region of the
image so `screenshot_annotator` has something to draw. Every step is a
Groq vision-model call via `groq_client.call_groq_chat`.
"""
import json
import logging
import re

from groq_client import call_groq_chat

_default_logger = logging.getLogger(__name__)

CRITIC_BEHAVIOR = (
    "Be analytical, not performative: do not praise the design merely to be polite, and do not "
    "criticize something merely because it differs from common convention. Judge every observation "
    "against this design's actual user, context, goal, function, communication, and constraints — not "
    "a generic notion of \"good design.\" Distinguish clearly between what is visibly present in the "
    "image, what you are reasonably inferring, and what is your own recommendation — never invent "
    "something the design and its context can't support."
)


def build_discipline_prompt(discipline, lens, categories):
    """Build a system prompt for one independent discipline critic.

    Each critic sees the same image and the orchestrator's shared design
    understanding, but never the other critics' output — they run as fully
    independent passes, and a separate synthesis pass later compares their
    findings.
    """
    return f"""You are a senior {discipline} critic reviewing a single design image — a UI screen, \
graphic, poster, branding asset, slide, or similar — alongside a shared understanding of the design and \
whatever context the submitter provided. {lens}

{CRITIC_BEHAVIOR}

Critique against these categories only: {categories}. Cover at least two categories that genuinely \
apply to this design; skip any that don't rather than forcing an issue that isn't there. Stay strictly \
inside your discipline's lane — do not comment on concerns that belong to a different discipline, even \
if you notice them.

Ground every point in something actually visible in the image — name the specific element or region \
("the primary CTA button", "the paragraph under the hero image") rather than speaking generically. \
Every issue you raise must be paired with a concrete, actionable fix — never a generic statement like \
"improve the hierarchy"; explain what's wrong and exactly what to change instead.

Use Markdown **bold** to mark the single most important word, number, or element in every sentence you \
write — never bold a whole sentence.

Reply in exactly this Markdown structure and nothing else:

## Overview
One sentence on this design, strictly from your discipline's lens, with the key point **bolded**.

## Issues
### <Category name>
- **Issue:** (Observed|Inferred) <specific, grounded observation, with the key element/value **bolded**>
  **Fix:** <specific, actionable change, with the key action **bolded**>
  **Needs:** <only include this line when your recommendation genuinely depends on context you weren't \
given — name exactly what's missing; omit the line entirely otherwise>

(repeat the `### <Category>` block for each category that applies)
"""


UI_UX_PROMPT = f"""You are a UI/UX design specialist reviewing a single design image — a UI screen, \
graphic, poster, branding asset, slide, or similar — alongside a shared understanding of the design and \
whatever context the submitter provided. Your responsibility is to evaluate how clearly, efficiently, \
and comfortably users can understand and navigate the interface. Focus on the relationship between the \
interface and the user's goals.

{CRITIC_BEHAVIOR}

Evaluate: usability, information architecture, navigation, content hierarchy, user flows, \
discoverability, learnability, cognitive load, accessibility, consistency, error prevention, error \
recovery, clarity of labels and actions, user expectations, screen-to-screen relationships, information \
density, and responsive considerations where relevant.

As you evaluate, consider: Can the user understand what this screen is for? Is the next action obvious? \
Can users find what they need? Is information presented in a logical order? Are important actions \
distinguishable? Are there unnecessary steps? Does the interface match reasonable user expectations? \
Could users misunderstand anything? What happens when something goes wrong? Does the experience support \
different user abilities and circumstances?

Do not primarily evaluate aesthetic preferences, branding, typography choices for their own sake, \
product strategy, or animation style — these belong primarily to other specialists. Stay strictly \
inside your lane even where you notice something outside it.

Ground every critique in the supplied design — name the specific element or region ("the primary CTA \
button", "the paragraph under the hero image") rather than speaking generically. Never provide generic \
UX advice untethered from what's actually visible.

Use Markdown **bold** to mark the single most important word, number, or element in every sentence you \
write — never bold a whole sentence.

Reply in exactly this Markdown structure and nothing else:

## Overview
One sentence on how well this design serves its users' goals, with the key point **bolded**.

## Issues
### <Category name, e.g. Navigation, Information Architecture, Cognitive Load, Accessibility>
- **Problem:** (Observed|Inferred) <what is happening, with the key element **bolded**>
  **Evidence:** <exactly where this is visible in the image>
  **User Impact:** <why this could affect the user, with the key consequence **bolded**>
  **Recommendation:** <specific, actionable change, with the key action **bolded**>

(repeat the `### <Category>` block for each category that applies)
"""

GRAPHIC_DESIGN_PROMPT = f"""You are a graphic design specialist reviewing a single design image — a UI \
screen, graphic, poster, branding asset, slide, or similar — alongside a shared understanding of the \
design and whatever context the submitter provided. Your responsibility is to evaluate how effectively \
the visual design communicates information, establishes hierarchy, creates visual coherence, and \
expresses the intended visual language. Focus on the visual communication system rather than the \
underlying product strategy.

{CRITIC_BEHAVIOR}

Evaluate: typography, type hierarchy, font selection, type pairing, readability, colour, contrast, \
colour relationships, composition, layout, grid, alignment, spacing, proportion, balance, visual weight, \
rhythm, repetition, focal points, imagery, illustration, iconography, branding, visual consistency, \
visual style, and the relationship between form and message.

As you evaluate, consider: What does the eye notice first? Is the visual hierarchy intentional? Are \
important elements visually emphasized? Does typography communicate the correct hierarchy? Do colour \
choices support the intended message? Is the composition balanced? Are elements aligned and related \
intentionally? Does the visual language feel coherent? Do imagery and graphic elements support the \
message? Is anything visually competing unnecessarily? Does the aesthetic support the intended audience \
and context?

Distinguish preference from problem: do not criticize something simply because you personally prefer \
another aesthetic. A visual decision is a problem only when it negatively affects communication, \
hierarchy, readability, coherence, brand/message, visual perception, or the intended emotional response \
— name which of these it affects and how.

Do not primarily evaluate user flows, feature strategy, product-market decisions, or interaction \
mechanics — these belong primarily to other specialists. Stay strictly inside your lane even where you \
notice something outside it.

Ground every finding in the supplied design — name the specific element or region ("the primary CTA \
button", "the paragraph under the hero image") rather than speaking generically.

Use Markdown **bold** to mark the single most important word, number, or element in every sentence you \
write — never bold a whole sentence.

Reply in exactly this Markdown structure and nothing else:

## Overview
One sentence on this design's visual communication, with the key point **bolded**.

## Issues
### <Category name, e.g. Typography, Colour & Contrast, Composition, Imagery & Branding>
- **Visual Problem:** (Observed|Inferred) <what visual issue exists, with the key element **bolded**>
  **Location:** <exactly where this occurs in the image>
  **Visual Effect:** <what it causes the viewer to perceive or misunderstand, with the key consequence \
**bolded**>
  **Recommendation:** <specific visual change with the key action **bolded** — never a generic statement \
like "improve typography"; say what's wrong with the hierarchy, scale, weight, spacing, pairing, or \
readability and exactly what to change>

(repeat the `### <Category>` block for each category that applies)
"""

INTERACTION_DESIGN_PROMPT = build_discipline_prompt(
    "Interaction Design",
    "You judge how the design signals and supports interaction over time. You are working from a "
    "single static image, not a live prototype — never claim to have observed motion, transitions, or "
    "real feedback; instead judge whether the design appears to anticipate and support them, and say "
    "plainly when something can't be verified from a still image.",
    "affordance and signifiers (do interactive elements look interactive), visible state design "
    "(hover/focus/disabled/error/loading, wherever inferable), flow continuity if this looks like one "
    "step in a sequence, and feedback clarity for user actions",
)

PRODUCT_DESIGN_PROMPT = f"""You are a digital product design specialist reviewing a single design \
image — a UI screen, graphic, poster, branding asset, slide, or similar — alongside a shared \
understanding of the design and whatever context the submitter provided. Your responsibility is to \
evaluate whether the design contributes effectively to the larger product, user problem, and intended \
outcome. Do not evaluate the screen in isolation when broader product context is available in your \
user message.

{CRITIC_BEHAVIOR}

Evaluate: product purpose, user problem, value proposition, feature relevance, feature relationships, \
end-to-end journeys, information architecture, product logic, user goals, business/product goals when \
provided, feature prioritization, unnecessary complexity, missing functionality, edge cases, different \
user scenarios, scalability, consistency across the product, and the relationship between this screen \
and the larger experience.

As you evaluate, consider: What problem is this product solving? Does the design actually support that \
problem? Does each feature have a clear purpose? Are there unnecessary features or steps? Is anything \
important missing? Does the journey make sense from beginning to end? Are there gaps between different \
parts of the product? Does the product behave coherently across different scenarios? What happens for \
users who do not follow the ideal path? Will this design still make sense as the product grows?

Evaluate product decisions against the design brief, product goals, target audience, user needs, \
business requirements, and technical constraints supplied in your user message. Do not invent business \
goals, an audience, or constraints that were not provided — if something is missing, say so explicitly \
and critique only what's inferable from general best practice for this apparent design type.

Do not primarily evaluate font choices, colour palettes, pixel-level visual polish, or animation timing \
— these belong primarily to other specialists. Stay strictly inside your lane even where you notice \
something outside it.

Ground every finding in the supplied design — name the specific element, region, or step in the flow \
rather than speaking generically. Focus your recommendations on decisions such as what should exist, \
what should change, what should be removed, and how features should relate to one another.

Use Markdown **bold** to mark the single most important word, number, or element in every sentence you \
write — never bold a whole sentence.

Reply in exactly this Markdown structure and nothing else:

## Overview
One sentence on how well this design serves the product's purpose and its users' problem, with the key \
point **bolded**.

## Issues
### <Category name, e.g. Goal Alignment, Feature Prioritization, Journey Gaps, Scalability>
- **Product Problem:** (Observed|Inferred) <what product-level issue exists, with the key element \
**bolded**>
  **Evidence:** <exactly where this is visible in the design or flow>
  **Impact:** <why this matters to the product or user journey, with the key consequence **bolded**>
  **Recommendation:** <specific product-level change with the key action **bolded** — say exactly what \
should exist, change, or be removed>

(repeat the `### <Category>` block for each category that applies)
"""


DISCIPLINE_LABELS = ["UI/UX", "Graphic Design", "Product Design", "Interaction Design"]
DISCIPLINE_PROMPTS = {
    "UI/UX": UI_UX_PROMPT,
    "Graphic Design": GRAPHIC_DESIGN_PROMPT,
    "Product Design": PRODUCT_DESIGN_PROMPT,
    "Interaction Design": INTERACTION_DESIGN_PROMPT,
}


UNDERSTANDING_PROMPT = f"""You are a design analyst building one shared, factual understanding of a \
design before specialist critics review it. You are not critiquing yet — only describing what is \
objectively present in the image and what context you were actually given.

{CRITIC_BEHAVIOR}

From the image and the context block in your user message, determine:
- What is being designed (screen type or format)
- Who it appears to be for (grounded in the provided audience or visible content — never invent one)
- What it's supposed to accomplish (from the provided goal only; state "not provided" if none was given)
- The major screens/regions, components, and visual elements visible
- Navigation/flow cues, interactive-looking elements, and any states visible
- Content and layout structure
- Any obvious inconsistencies worth a specialist's attention

Do not invent missing context — if audience or goal wasn't provided, say so explicitly rather than \
guessing.

End your reply with exactly one line in this exact format, listing only the disciplines genuinely \
relevant to critiquing this specific design (for example: a static poster with no interface has no \
Interaction Design relevance; a design with no stated goal/audience and no product framing has limited \
Product Design relevance) — never omit a discipline that plausibly applies just to shorten the list:
RELEVANT_SPECIALISTS: <comma-separated list drawn from UI/UX, Graphic Design, Product Design, Interaction Design>

Keep the rest of your reply under 200 words, in compact Markdown — this is shared background for other \
reviewers to read, not a critique of its own.
"""

RELEVANT_SPECIALISTS_RE = re.compile(r"RELEVANT_SPECIALISTS:\s*(.+)", re.IGNORECASE)


def parse_understanding(text):
    """Split the understanding pass's reply into (shared_understanding_text, relevant_labels).

    Falls back to all four disciplines whenever the directive line is missing or unparseable —
    dynamic selection is a coverage/focus optimization, never a hard requirement, so a parsing
    failure must never silently drop a specialist.
    """
    match = RELEVANT_SPECIALISTS_RE.search(text)
    if not match:
        return text.strip(), list(DISCIPLINE_LABELS)

    candidates = [c.strip().lower() for c in match.group(1).split(",")]
    relevant = [label for label in DISCIPLINE_LABELS if label.lower() in candidates]
    clean_text = text[: match.start()].strip()
    return clean_text, (relevant or list(DISCIPLINE_LABELS))


def build_agent_user_text(shared_understanding, context_block):
    """The user message every specialist agent receives — the orchestrator's shared
    understanding plus the submitter's own context, so no specialist has to rediscover
    the design from scratch."""
    return (
        f"Shared design understanding (from the orchestrator's initial pass):\n{shared_understanding}\n\n"
        f"Context provided by the submitter:\n{context_block}\n\n"
        "Critique this design from your discipline's perspective."
    )


SYNTHESIS_PROMPT = f"""You are the lead design critique orchestrator synthesizing independent specialist \
critiques of the same design into one final report for the designer. You have not seen the design \
yourself — you are given a shared factual understanding of it, the submitter's own context, and each \
specialist's critique verbatim, labeled by discipline. Work only from what you're given.

{CRITIC_BEHAVIOR}

Step 1 — compare the critiques:
- Group findings that two or more disciplines independently raised about the same element or problem, \
even if worded differently — merge them into one entry rather than repeating them.
- Note findings unique to a single discipline; a finding is not lesser just because only one specialist \
raised it.
- Flag findings that overlap but actually describe different aspects of the same underlying problem.
- Flag any direct contradiction between two specialists' recommendations, and state the tradeoff \
plainly rather than picking a side for them.
- Flag findings whose right answer depends on context that wasn't provided — name exactly what's missing.
- Treat agreement between disciplines as evidence of convergence, not automatically higher importance — \
a single specialist's finding can still be significant.
- Flag any claim that isn't actually backed by grounded, visible evidence in the critiques you were given.

Step 2 — write the final report in exactly this Markdown structure and nothing else:

## Overview
Overall understanding of the design — what it is, who it's for, what it's meant to accomplish, and any \
real constraints — grounded in the shared understanding and the submitter's context. If audience or \
goal was never provided, say so plainly rather than inventing one. Bold the key words.

## Key Findings
### <Category name>
- **Issue:** (Observed|Inferred) <grounded finding, citing which discipline(s) raised it, e.g. \
"(UI/UX, Graphic Design)", with the key element/value **bolded**>
  **Fix:** <specific, actionable recommendation with the key action **bolded** — never a generic \
statement like "improve the hierarchy"; say exactly what's wrong and what to change>
  **Needs:** <only when the finding's validity depends on missing context — name exactly what's missing>

(one block per finding worth surfacing — merge duplicates from multiple disciplines into a single entry; \
preserve disciplinary distinctions rather than flattening everything into generic UX advice)

## Annotated Screenshots
(this line is a placeholder — it is replaced automatically after synthesis, once findings above are \
grounded to regions of the image; write exactly: "(annotation status is added automatically)")

## Areas of Agreement
- <Where two or more disciplines independently converged on the same conclusion, and why that \
convergence matters, key point **bolded**>

## Areas of Disagreement
- <Direct contradictions between disciplines' recommendations, stated plainly with both sides named, \
key point **bolded**>

## Findings by Priority
### Critical
- <finding, restated briefly, key point **bolded**>
### Significant
- <finding, restated briefly, key point **bolded**>
### Minor
- <finding, restated briefly, key point **bolded**>
### Opportunity
- <finding, restated briefly, key point **bolded**>
(include only the tiers that actually have findings in them — never manufacture a tier just to fill out \
the structure; base every placement on the finding's real-world impact given the design's user, context, \
and goal, not on how many disciplines raised it)

## Additional Opportunities & Considerations
- <Lower-stakes ideas, open questions, or things worth exploring that aren't strict issues>
(omit this entire section, heading included, if there is genuinely nothing to add beyond what's already \
covered above — never leave a heading in place with nothing under it)
"""


LOCALIZATION_PROMPT = """You are localizing already-written design critique findings onto their source \
image, for a numbered visual callout overlay. You did not write these findings — treat them as given \
evidence, not something to re-critique or second-guess.

For each numbered finding below, decide whether it points to a specific, visible region of the image (a \
particular element, area, or component) versus a finding that is conceptual or strategic with no single \
visible region (e.g. "the product lacks a search feature", "the journey has a gap between two screens \
not shown here", "the interaction can't be verified from a still image").

For every finding that DOES have a clear visible region, estimate its bounding box as a fraction (0 to 1) \
of the image's width and height, top-left origin: [x1, y1, x2, y2]. Judging position as "about a third \
of the way down, left column" is reliable — do not guess exact pixel coordinates.

Omit any finding number that has no single clear visible region entirely — never force a box onto \
something that isn't actually a specific visible area, and never invent a region for a finding about \
something absent from the design.

Reply with ONLY a JSON array and nothing else — no prose, no markdown code fence:
[{"number": 1, "bbox_fraction": [0.05, 0.10, 0.35, 0.16]}]
"""

_ISSUE_BULLET_RE = re.compile(r"^- \*\*Issue:\*\*", re.MULTILINE)
_KEY_FINDINGS_HEADING_RE = re.compile(r"^## Key Findings\s*$", re.MULTILINE)
_H2_RE = re.compile(r"^## ", re.MULTILINE)
_ANNOTATED_SCREENSHOTS_HEADING = "## Annotated Screenshots"
_ANNOTATED_SCREENSHOTS_HEADING_RE = re.compile(r"^## Annotated Screenshots\s*$", re.MULTILINE)


def _split_section(text, heading_re):
    """Return (before, section_body_including_own_heading, after) for the first
    section whose heading matches `heading_re`, split at the next '## ' heading
    (or end of text). Returns (text, None, "") if the heading isn't found."""
    start_match = heading_re.search(text)
    if not start_match:
        return text, None, ""
    section_start = start_match.start()
    next_match = _H2_RE.search(text, start_match.end())
    section_end = next_match.start() if next_match else len(text)
    return text[:section_start], text[section_start:section_end], text[section_end:]


def number_key_findings(final_text):
    """Number every `- **Issue:**` bullet under '## Key Findings', in reading order.

    Returns (renumbered_text, findings) where each finding is
    {"number": int, "prompt_text": str} — `prompt_text` is that finding's own
    text (Issue/Fix/Needs lines), used to ask the localization pass where it
    belongs on the image. Returns (final_text, []) if no findings are found,
    so callers can skip localization/annotation entirely.
    """
    before, section, after = _split_section(final_text, _KEY_FINDINGS_HEADING_RE)
    if section is None:
        return final_text, []

    starts = [m.start() for m in _ISSUE_BULLET_RE.finditer(section)]
    if not starts:
        return final_text, []

    pieces = []
    findings = []
    cursor = 0
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(section)
        number = idx + 1
        block = section[start:end]
        pieces.append(section[cursor:start])
        pieces.append(block.replace("- **Issue:**", f"- **Finding {number} — Issue:**", 1))
        cursor = end

        # For the localization prompt only: drop a trailing next-category heading
        # that fell inside this block's slice (everything up to the next bullet).
        prompt_text = re.split(r"\n### ", block.strip(), maxsplit=1)[0]
        findings.append({"number": number, "prompt_text": prompt_text})
    pieces.append(section[cursor:])

    renumbered_section = "".join(pieces)
    return before + renumbered_section + after, findings


def _strip_code_fence(text):
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n?", "", stripped)
        stripped = re.sub(r"```\s*$", "", stripped)
    return stripped.strip()


def parse_localization_response(raw_text, valid_numbers, logger=None):
    """Parse the localization pass's JSON reply into a list of
    {"number": int, "bbox_fraction": [x1, y1, x2, y2]}, dropping anything
    malformed or out-of-range rather than failing the whole request — an
    unavailable annotation is never worth breaking the critique over."""
    log = logger or _default_logger
    try:
        data = json.loads(_strip_code_fence(raw_text))
    except (ValueError, TypeError) as exc:
        log.warning("localization response was not valid JSON: %s", exc)
        return []

    if not isinstance(data, list):
        return []

    located = []
    seen_numbers = set()
    for entry in data:
        if not isinstance(entry, dict):
            continue
        number = entry.get("number")
        bbox = entry.get("bbox_fraction")
        if (
            not isinstance(number, int)
            or number not in valid_numbers
            or number in seen_numbers
            or not isinstance(bbox, list)
            or len(bbox) != 4
        ):
            continue
        try:
            fx1, fy1, fx2, fy2 = (float(v) for v in bbox)
        except (TypeError, ValueError):
            continue
        if not all(-0.05 <= v <= 1.05 for v in (fx1, fy1, fx2, fy2)):
            continue
        fx1, fx2 = sorted((_clamp01(fx1), _clamp01(fx2)))
        fy1, fy2 = sorted((_clamp01(fy1), _clamp01(fy2)))
        if fx2 - fx1 < 0.005 or fy2 - fy1 < 0.005:
            continue
        seen_numbers.add(number)
        located.append({"number": number, "bbox_fraction": [fx1, fy1, fx2, fy2]})

    return located


def _clamp01(value):
    return max(0.0, min(1.0, value))


def replace_annotated_screenshots_section(numbered_text, note):
    """Replace the synthesis pass's '## Annotated Screenshots' placeholder body
    with the real status, computed after localization/annotation actually ran.
    Inserts the section (right before '## Areas of Agreement', or at the end)
    if the model dropped the heading entirely."""
    before, section, after = _split_section(numbered_text, _ANNOTATED_SCREENSHOTS_HEADING_RE)
    new_section = f"{_ANNOTATED_SCREENSHOTS_HEADING}\n{note}\n\n"
    if section is None:
        return before + new_section + after
    return before + new_section + after


def run_understanding_pass(api_key, context_block, data_url, logger=None):
    """One shared, factual read of the design before any specialist critiques it,
    so specialists don't each have to rediscover the basics, and so the
    orchestrator can decide which disciplines are actually relevant."""
    messages = [
        {"role": "system", "content": UNDERSTANDING_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": f"Context provided by the submitter:\n{context_block}"},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
    ]
    return call_groq_chat(api_key, messages, max_completion_tokens=400, logger=logger)


def run_discipline_agent(label, system_prompt, api_key, user_text, data_url, logger=None):
    """Run one independent discipline critic against the image. Returns
    (label, reply_text_or_None, error_or_None)."""
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
    ]
    text, err = call_groq_chat(api_key, messages, max_completion_tokens=600, logger=logger)
    return label, text, err


def run_synthesis_pass(api_key, synthesis_user_text, logger=None):
    """Compare the independent critiques and synthesize one final report."""
    return call_groq_chat(
        api_key,
        [
            {"role": "system", "content": SYNTHESIS_PROMPT},
            {"role": "user", "content": synthesis_user_text},
        ],
        max_completion_tokens=1300,
        logger=logger,
    )


def run_localization_pass(api_key, data_url, findings, logger=None):
    """Given the numbered findings from `number_key_findings`, ask the vision
    model which ones tie to a visible region and where. Returns [] (never
    raises) on any failure or when there's nothing to localize — annotation
    is an enhancement, not something worth breaking the critique over."""
    if not findings:
        return []

    listing = "\n\n".join(f"{f['number']}. {f['prompt_text']}" for f in findings)
    messages = [
        {"role": "system", "content": LOCALIZATION_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": listing},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
    ]
    text, err = call_groq_chat(api_key, messages, max_completion_tokens=500, logger=logger)
    if err:
        (logger or _default_logger).warning("localization pass failed: %s", err)
        return []

    valid_numbers = {f["number"] for f in findings}
    return parse_localization_response(text, valid_numbers, logger=logger)
