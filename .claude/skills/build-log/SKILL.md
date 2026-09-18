---
name: build-log
description: Explains and manually re-runs the automatic prompt-level logging to build-log.md (date, time, and approximate tokens used per prompt). The actual logging is automatic via a Stop hook — invoke this skill (/build-log) only to inspect the log, explain how it works, or manually append an entry if the hook didn't fire.
---

# Build log (per-prompt token log)

`build-log.md` at the repo root records one line per user prompt: the date, time, and an approximate token count for that turn. This is **automatic** — a `Stop` hook (`.claude/settings.json` → `hooks.Stop`, running `.claude/hooks/build-log-stop.ps1`) fires after every assistant turn, reads the session transcript, sums `input_tokens + cache_creation_input_tokens + cache_read_input_tokens + output_tokens` across the assistant messages produced since the hook's own last run (tracked per-session in `.claude/build-log-state/<session_id>.txt`, gitignored), and appends:

```markdown
- YYYY-MM-DD HH:mm:ss - ~<token count> tokens
```

## When to invoke this skill

You do not need to invoke anything for normal logging — it happens on its own. Use `/build-log` only when:

1. **Explaining the log** — a teammate asks what `build-log.md` is or how the numbers are computed.
2. **The hook didn't fire** — e.g. it's disabled, `/hooks` needs a reload after this skill/hook was first added, or the session isn't on Windows/PowerShell. In that case, manually append an entry:
   - Run `git rev-parse --is-inside-work-tree` to confirm you're in the repo.
   - Estimate the token count for the current conversation turn as best you can (there's no exact figure without the transcript hook), and append a line in the same format to `build-log.md`, creating the file with a `# Build Log` heading if missing.
   - Tell the user the entry was added manually because the automatic hook did not run, and suggest they check `/hooks` or their `.claude/settings.json`.

## Notes

- Never edit or reorder existing entries — only append.
- This is separate from the `/build` skill, which logs one entry per **git commit** to `BUILD_LOG.md` (time spent, tokens, what shipped). `build-log.md` (this skill) logs one entry per **prompt/turn** instead.
- The per-session state files under `.claude/build-log-state/` are bookkeeping only (last transcript line processed) — never edit them by hand; delete a session's state file only if you want its next Stop hook run to recount from the start of that transcript.
