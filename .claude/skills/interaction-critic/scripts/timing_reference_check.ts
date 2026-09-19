/**
 * Classify the gaps in an observed interaction sequence against Nielsen's
 * classic response-time thresholds (0.1s / 1s / 10s), and report the
 * standard guidance for each gap.
 *
 * Usage:
 *     ts-node timing_reference_check.ts <sequence.json>
 *     (or compile with tsc and run the resulting .js with node)
 *
 * sequence.json is a JSON array of observed events, in order, each with a
 * label and a timestamp in milliseconds relative to the start of the
 * interaction (the first event should normally be 0):
 *     [
 *       {"label": "user clicks submit", "atMs": 0},
 *       {"label": "loading spinner appears", "atMs": 900},
 *       {"label": "success message shown", "atMs": 4200}
 *     ]
 *
 * These timestamps should come from something actually observed (a live
 * interaction walked through step by step, or timestamps visible in a
 * screen recording) — never invent timing you didn't witness. If you
 * only have a static screenshot with no way to observe transitions,
 * skip this script entirely rather than guessing at durations.
 *
 * Reference: Jakob Nielsen's "Response Times: The 3 Important Limits"
 * (a long-standing, widely cited UX research finding, not this script's
 * own invention) — 0.1s feels instantaneous, 1.0s is the limit for the
 * user's flow of thought staying uninterrupted, 10s is the limit for
 * keeping their attention on the task at all.
 */
import * as fs from "fs";

interface TimedEvent {
  label: string;
  atMs: number;
}

type Band = "instantaneous" | "noticeable-but-uninterrupted" | "needs-loading-indicator" | "risks-task-abandonment";

const BAND_GUIDANCE: Record<Band, string> = {
  "instantaneous":
    "Under 100ms — perceived as an immediate, direct response. No special feedback is needed beyond the result itself.",
  "noticeable-but-uninterrupted":
    "100ms–1s — the user will notice the delay but their flow of thought isn't interrupted. A subtle feedback cue (e.g. a pressed/active state) is good practice but not mandatory for a single action.",
  "needs-loading-indicator":
    "1s–10s — the user's attention on the task is at risk without feedback. A loading indicator (spinner, skeleton, progress cue) is effectively required here, or the delay will read as the system being unresponsive or broken.",
  "risks-task-abandonment":
    "Over 10s — risks the user abandoning the task or losing trust that anything is happening. Needs a percent-done or step-based progress indicator, an estimated time, and ideally a way to keep working elsewhere or cancel.",
};

function classify(durationMs: number): Band {
  if (durationMs < 100) return "instantaneous";
  if (durationMs < 1000) return "noticeable-but-uninterrupted";
  if (durationMs <= 10000) return "needs-loading-indicator";
  return "risks-task-abandonment";
}

interface IntervalResult {
  fromLabel: string;
  toLabel: string;
  durationMs: number;
  band: Band;
  guidance: string;
}

function analyzeSequence(events: TimedEvent[]) {
  const intervals: IntervalResult[] = [];
  for (let i = 0; i < events.length - 1; i++) {
    const durationMs = events[i + 1].atMs - events[i].atMs;
    const band = classify(Math.max(0, durationMs));
    intervals.push({
      fromLabel: events[i].label,
      toLabel: events[i + 1].label,
      durationMs,
      band,
      guidance: BAND_GUIDANCE[band],
    });
  }

  const totalDurationMs = events.length > 0 ? events[events.length - 1].atMs - events[0].atMs : 0;
  const flaggedIntervals = intervals.filter((iv) => iv.band !== "instantaneous" && iv.band !== "noticeable-but-uninterrupted");

  return { intervals, totalDurationMs, flaggedIntervals };
}

function isValidEvent(e: unknown): e is TimedEvent {
  if (typeof e !== "object" || e === null) return false;
  const rec = e as Record<string, unknown>;
  return typeof rec.label === "string" && typeof rec.atMs === "number" && Number.isFinite(rec.atMs);
}

function main(): void {
  const inputPath = process.argv[2];
  if (!inputPath) {
    console.error("Usage: timing_reference_check.ts <sequence.json>");
    process.exit(1);
  }
  if (!fs.existsSync(inputPath)) {
    console.error(`No such file: ${inputPath}`);
    process.exit(1);
  }

  const raw = fs.readFileSync(inputPath, "utf-8");
  let events: unknown;
  try {
    events = JSON.parse(raw);
  } catch (err) {
    console.error(`Invalid JSON in ${inputPath}: ${(err as Error).message}`);
    process.exit(1);
  }
  if (!Array.isArray(events) || events.length === 0) {
    console.error("sequence.json must be a non-empty JSON array of {label, atMs} events");
    process.exit(1);
  }
  for (const e of events) {
    if (!isValidEvent(e)) {
      console.error(`Each event needs a string 'label' and numeric 'atMs': ${JSON.stringify(e)}`);
      process.exit(1);
    }
  }
  const sorted = [...(events as TimedEvent[])].sort((a, b) => a.atMs - b.atMs);
  if (JSON.stringify(sorted) !== JSON.stringify(events)) {
    console.error("Events must be given in chronological order (ascending atMs).");
    process.exit(1);
  }

  const { intervals, totalDurationMs, flaggedIntervals } = analyzeSequence(events as TimedEvent[]);

  console.log(
    JSON.stringify(
      {
        reference: "Nielsen's classic response-time thresholds: 0.1s instantaneous, 1s flow-uninterrupted limit, 10s attention limit.",
        totalDurationMs,
        intervals,
        flaggedIntervals,
      },
      null,
      2
    )
  );
}

main();
