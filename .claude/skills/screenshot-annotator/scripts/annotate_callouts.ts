/**
 * Overlay numbered callout markers on a UI screenshot.
 *
 * Usage:
 *     ts-node annotate_callouts.ts <input_image> <annotations.json> <output_image>
 *     (or compile with tsc and run the resulting .js with node)
 *
 * annotations.json is a JSON array of objects:
 *     {
 *         "number": 1,
 *         "shape": "box" | "ellipse",       // optional, defaults to "box"
 *         "bbox_fraction": [x1, y1, x2, y2]  // each in [0, 1], relative to image
 *                                             // width/height, top-left origin
 *     }
 *
 * Coordinates are fractions of the image's width/height (not raw pixels)
 * because a vision model estimating "where" a problem is on a screenshot is
 * far more reliable at judging position as a fraction of the image ("about a
 * third of the way down, spanning the left column") than at guessing exact
 * pixel numbers. This script does the fraction-to-pixel conversion.
 *
 * This is a TypeScript/Node port of annotate_callouts.py, using
 * `@napi-rs/canvas` (prebuilt native binding, no compiler/GTK required)
 * as the Pillow equivalent. Behavior mirrors the Python version so either
 * can be used interchangeably by the skill.
 */
import * as fs from "fs";
import * as path from "path";
import { createCanvas, loadImage, GlobalFonts, Canvas, SKRSContext2D } from "@napi-rs/canvas";

type Shape = "box" | "ellipse";

interface Annotation {
  number: number | string;
  shape?: Shape;
  bbox_fraction: [number, number, number, number];
}

const MARKER_COLOR = "rgb(255, 45, 45)"; // red outline / badge fill
const BADGE_TEXT_COLOR = "rgb(255, 255, 255)"; // white number

const FONT_CANDIDATES = [
  "C:\\Windows\\Fonts\\arialbd.ttf",
  "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
  "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
];

let registeredFontFamily: string | null = null;

function ensureFontRegistered(): string {
  if (registeredFontFamily) return registeredFontFamily;
  for (const candidate of FONT_CANDIDATES) {
    if (fs.existsSync(candidate)) {
      GlobalFonts.registerFromPath(candidate, "CalloutBadgeFont");
      registeredFontFamily = "CalloutBadgeFont";
      return registeredFontFamily;
    }
  }
  // Fall back to whatever generic sans-serif the system resolver can find.
  registeredFontFamily = "sans-serif";
  return registeredFontFamily;
}

function clamp(value: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, value));
}

async function drawCallouts(
  inputPath: string,
  annotations: Annotation[],
  outputPath: string
): Promise<void> {
  const image = await loadImage(inputPath);
  const width = image.width;
  const height = image.height;

  const canvas: Canvas = createCanvas(width, height);
  const ctx: SKRSContext2D = canvas.getContext("2d");
  ctx.drawImage(image, 0, 0, width, height);

  const shortSide = Math.min(width, height);
  const outlineWidth = Math.max(3, Math.round(shortSide * 0.004));
  const badgeRadius = Math.max(16, Math.round(shortSide * 0.022));
  const fontFamily = ensureFontRegistered();
  const fontSize = Math.round(badgeRadius * 1.15);
  ctx.font = `bold ${fontSize}px "${fontFamily}"`;
  ctx.textBaseline = "middle";
  ctx.textAlign = "center";

  for (const ann of annotations) {
    const shape: Shape = ann.shape ?? "box";
    let [fx1, fy1, fx2, fy2] = ann.bbox_fraction;

    let x1 = fx1 * width;
    let y1 = fy1 * height;
    let x2 = fx2 * width;
    let y2 = fy2 * height;
    if (x1 > x2) [x1, x2] = [x2, x1];
    if (y1 > y2) [y1, y2] = [y2, y1];

    ctx.lineWidth = outlineWidth;
    ctx.strokeStyle = MARKER_COLOR;

    if (shape === "ellipse") {
      const cx = (x1 + x2) / 2;
      const cy = (y1 + y2) / 2;
      const rx = (x2 - x1) / 2;
      const ry = (y2 - y1) / 2;
      ctx.beginPath();
      ctx.ellipse(cx, cy, Math.max(rx, 0.01), Math.max(ry, 0.01), 0, 0, Math.PI * 2);
      ctx.stroke();
    } else {
      ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
    }

    // Badge sits at the top-left corner of the region, nudged so it stays
    // fully on-canvas even when the region touches an edge.
    const badgeCx = clamp(x1, badgeRadius, width - badgeRadius);
    const badgeCy = clamp(y1, badgeRadius, height - badgeRadius);

    ctx.beginPath();
    ctx.arc(badgeCx, badgeCy, badgeRadius, 0, Math.PI * 2);
    ctx.fillStyle = MARKER_COLOR;
    ctx.fill();
    ctx.lineWidth = Math.max(2, outlineWidth - 1);
    ctx.strokeStyle = "rgb(255, 255, 255)";
    ctx.stroke();

    ctx.fillStyle = BADGE_TEXT_COLOR;
    ctx.fillText(String(ann.number), badgeCx, badgeCy + 1);
  }

  const buffer = canvas.toBuffer("image/png");
  fs.writeFileSync(outputPath, buffer);
}

function isValidAnnotation(ann: unknown): ann is Annotation {
  if (typeof ann !== "object" || ann === null) return false;
  const record = ann as Record<string, unknown>;
  if (!("number" in record) || !("bbox_fraction" in record)) return false;
  const bbox = record.bbox_fraction;
  return Array.isArray(bbox) && bbox.length === 4;
}

async function main(): Promise<void> {
  const [inputImage, annotationsJsonPath, outputImage] = process.argv.slice(2);

  if (!inputImage || !annotationsJsonPath || !outputImage) {
    console.error(
      "Usage: annotate_callouts.ts <input_image> <annotations.json> <output_image>"
    );
    process.exit(1);
  }

  const raw = fs.readFileSync(path.resolve(annotationsJsonPath), "utf-8");
  const annotations: unknown = JSON.parse(raw);

  if (!Array.isArray(annotations) || annotations.length === 0) {
    console.error("annotations_json must contain a non-empty JSON array");
    process.exit(1);
  }

  for (const ann of annotations) {
    if (!isValidAnnotation(ann)) {
      console.error(`Each annotation needs 'number' and 'bbox_fraction': ${JSON.stringify(ann)}`);
      process.exit(1);
    }
  }

  await drawCallouts(inputImage, annotations as Annotation[], outputImage);
  console.log(`Wrote ${outputImage} with ${(annotations as Annotation[]).length} callout(s)`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
