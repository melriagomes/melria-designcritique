/**
 * Sanity-check physical product dimensions against general human-factors
 * reference ranges commonly cited in industrial design guidance.
 *
 * Usage:
 *     ts-node ergonomics_reference_check.ts <dimensions.json>
 *     (or compile with tsc and run the resulting .js with node)
 *
 * dimensions.json is a flat object of named measurements, e.g.:
 *     {
 *       "gripDiameterMm": 62,
 *       "primaryControlSizeMm": 7,
 *       "controlSpacingMm": 9
 *     }
 *
 * These values are almost never something you can read precisely off a
 * photo — they should come from a spec sheet, stated measurements, or a
 * careful estimate anchored to a known reference object/scale visible in
 * the image (e.g. "this remote is 15cm tall, so the buttons are ~8mm").
 * Never invent a precise number from a photo with no reference scale —
 * skip the dimension (and this script) rather than guess.
 *
 * IMPORTANT — this is NOT a certified compliance tool. The reference
 * ranges below are general figures commonly cited in industrial design /
 * human-factors literature for adult users, not a substitute for
 * population-specific research or regulatory (ISO/ANSI/etc.) testing.
 * An "outOfRange" flag is a prompt to look closer and explain why, not a
 * verdict — the output says so explicitly, and the skill using this
 * script should carry that caveat into whatever it tells the user.
 */
import * as fs from "fs";

interface ReferenceRange {
  min?: number;
  max?: number;
  unit: string;
  note: string;
}

// General reference ranges — see the module-level caveat above.
const REFERENCE_RANGES: Record<string, ReferenceRange> = {
  gripDiameterMm: {
    min: 30,
    max: 50,
    unit: "mm",
    note: "Comfortable whole-hand power-grip diameter for a cylindrical form (e.g. a handle, a bottle) for adult users.",
  },
  precisionGripDiameterMm: {
    min: 8,
    max: 16,
    unit: "mm",
    note: "Comfortable precision/pinch-grip diameter (thumb + fingertips), e.g. a stylus, a small dial, a pen.",
  },
  controlSizeMm: {
    min: 10,
    unit: "mm",
    note: "Minimum comfortable bare-fingertip control/button size. Prefer 12-19mm+ for gloved, frequent, or imprecise use.",
  },
  controlSpacingMm: {
    min: 12,
    unit: "mm",
    note: "Minimum center-to-center spacing between adjacent controls, to reduce accidental mis-presses.",
  },
  handleClearanceMm: {
    min: 25,
    max: 50,
    unit: "mm",
    note: "Clearance behind a handle needed for a bare-hand grasp. Increase toward the top of the range (or beyond) for gloved use.",
  },
  oneHandedWeightKg: {
    max: 1.0,
    unit: "kg",
    note: "General upper guideline for comfortable, prolonged one-handed hold. Lower this for overhead or extended-reach use.",
  },
  twoHandedWeightKg: {
    max: 5.0,
    unit: "kg",
    note: "General upper guideline for comfortable, prolonged two-handed hold at waist-to-chest height.",
  },
};

interface CheckResult {
  key: string;
  value: number;
  unit: string;
  inRange: boolean;
  range: { min?: number; max?: number };
  note: string;
}

interface UnreferencedResult {
  key: string;
  value: unknown;
}

interface InvalidResult {
  key: string;
  value: unknown;
  reason: string;
}

function checkDimensions(dimensions: Record<string, unknown>) {
  const checked: CheckResult[] = [];
  const unreferenced: UnreferencedResult[] = [];
  const invalid: InvalidResult[] = [];

  for (const [key, rawValue] of Object.entries(dimensions)) {
    if (typeof rawValue !== "number" || !Number.isFinite(rawValue)) {
      invalid.push({ key, value: rawValue, reason: "value must be a finite number" });
      continue;
    }
    const value = rawValue;

    const ref = REFERENCE_RANGES[key];
    if (!ref) {
      unreferenced.push({ key, value });
      continue;
    }
    const belowMin = ref.min !== undefined && value < ref.min;
    const aboveMax = ref.max !== undefined && value > ref.max;
    checked.push({
      key,
      value,
      unit: ref.unit,
      inRange: !belowMin && !aboveMax,
      range: { min: ref.min, max: ref.max },
      note: ref.note,
    });
  }

  return { checked, unreferenced, invalid };
}

function main(): void {
  const inputPath = process.argv[2];
  if (!inputPath) {
    console.error("Usage: ergonomics_reference_check.ts <dimensions.json>");
    console.error(`Known dimension keys: ${Object.keys(REFERENCE_RANGES).join(", ")}`);
    process.exit(1);
  }
  if (!fs.existsSync(inputPath)) {
    console.error(`No such file: ${inputPath}`);
    process.exit(1);
  }

  const raw = fs.readFileSync(inputPath, "utf-8");
  let dimensions: unknown;
  try {
    dimensions = JSON.parse(raw);
  } catch (err) {
    console.error(`Invalid JSON in ${inputPath}: ${(err as Error).message}`);
    process.exit(1);
  }
  if (typeof dimensions !== "object" || dimensions === null || Array.isArray(dimensions)) {
    console.error("dimensions.json must be a flat JSON object of {dimensionName: numberInStatedUnit}");
    process.exit(1);
  }

  const { checked, unreferenced, invalid } = checkDimensions(dimensions as Record<string, unknown>);

  console.log(
    JSON.stringify(
      {
        disclaimer:
          "General reference ranges commonly cited in industrial design / human-factors guidance for " +
          "adult users — not certified ISO/ANSI compliance thresholds. An outOfRange flag is a prompt " +
          "to look closer and explain why, not a verdict.",
        checked,
        unreferenced,
        invalid,
      },
      null,
      2
    )
  );
}

main();
