---
name: detailed-plan
description: Turns an idea into a detailed plan for building it as an AI agent — a clearly separated MVP scope vs. the final fully-functioning version, plus a dedicated breakdown of what role(s) the AI plays and how it's integrated into the agent's architecture and flow. Invoke as /detailed-plan <idea>, or /detailed-plan alone to infer the idea from the current conversation. Writes the plan to plan.md at the repo root.
---

# Detailed plan (AI agent idea → build plan)

Produce a single planning document that turns an idea into a concrete plan for building it as an AI agent: what the Minimum Viable Product is, what the fully-realized final version looks like, and — specifically — where and how AI is used inside the agent's flow. This skill is about AI *agents* specifically (a system with some autonomy/decision-making, not just a script), so always include the AI role/integration breakdown even if the idea as described sounds like a plain feature.

Never ask the user clarifying questions before producing the plan. Make the best reasonable inferences from the idea, `args`, and any repo context (existing files, README, other plan docs). If something is genuinely unknowable (e.g. a business constraint only the user has), state the assumption inline in the "Open assumptions" section rather than blocking on a question.

## Steps

1. **Determine the idea.** Use `args` if given. If empty, infer the idea from what the user is currently discussing in the conversation, or from the most recently touched relevant file. State the idea you used at the top of the plan so the user can correct it after the fact.

2. **Output file.** Write to `plan.md` at the repo root. If it doesn't exist, create it. If it exists and already holds a plan for a different idea, ask yourself whether this is a revision of the same idea (overwrite/update in place) or a genuinely new idea (in that case, still write to `plan.md` — this project keeps one active plan there — but preserve nothing from the old content once the new plan is written, since `plan.md` tracks the current plan, not a history).

3. **Research before writing.** Skim the repo for context relevant to the idea (related source files, existing docs, package.json/tech stack, other skills already built in `.claude/skills/`) so the plan is grounded in what actually exists, not generic boilerplate.

4. **Write the plan** to `plan.md` with this structure:

   ```markdown
   # <Idea> — Agent Plan

   ## Context
   <1-3 sentences: what this agent is, the problem it solves, current state if any>

   ## MVP
   ### Scope
   <the smallest version that is genuinely usable/demoable as an agent — bullet list of what's IN>

   ### Non-goals (for MVP)
   <bullet list of what's explicitly deferred to the final version, to prevent scope creep>

   ### AI role & integration
   <specifically for the MVP: which task(s) the AI actually performs (e.g. classification, generation,
   summarization, decision-making, planning, tool selection); which point(s) in the flow it sits at
   (input → [AI step] → action/output — draw this out step by step); what it takes as input and
   produces as output at that step; and how the rest of the system calls it (direct API call,
   agent loop with tools, a single prompt vs. multi-step reasoning). Keep this to the AI's actual
   job, not a restatement of the scope bullets.>

   ### Outcomes for an AI coding agent to build
   <a checklist of concrete, verifiable deliverables — each phrased as an observable result
   ("user does X and sees Y", "given input A, the agent produces B"), not a task description,
   so a builder knows when it's done and can self-verify. Order roughly by build sequence.>
   - [ ] ...
   - [ ] ...

   ## Final Version
   ### Vision
   <the fully-realized agent — what it looks/feels/behaves like when complete, including any
   autonomy, memory, or multi-step reasoning the MVP didn't have>

   ### Additional scope beyond MVP
   <bullet list of what's added on top of the MVP>

   ### AI role & integration
   <same style as the MVP section, but for the full version — call out anything that changes about
   the AI's role (e.g. MVP used a single prompt call, final version uses a multi-step agent loop
   with tool use and memory across sessions). Be explicit about what's new vs. carried over from
   the MVP.>

   ### Outcomes for an AI coding agent to build
   <same style checklist as above, for the full version>
   - [ ] ...
   - [ ] ...

   ## Open assumptions
   <anything you had to guess rather than ask about, so the user can correct it>
   ```

5. **Confirm.** Tell the user the plan was written to `plan.md` and give a one-line summary of the MVP vs. final version split, plus a one-line summary of the AI's role.

## Notes

- The "AI role & integration" sections are the point of this skill — never skip or shortchange them. If the idea doesn't obviously need AI (e.g. it's a plain CRUD feature), still identify the smallest genuine AI decision-making or generation step it could plausibly have, or flag in "Open assumptions" that the idea may not need to be an AI agent at all.
- "Outcomes for an AI coding agent to build" must be testable/observable, not restatements of the scope bullets.
- Keep the MVP genuinely minimal — if in doubt, cut it from the MVP and put it in the Final Version instead.
- This skill only reads repo files for context and writes `plan.md`; it never edits other files or runs builds.
