/**
 * Extract a dominant color palette from an image and compute real WCAG
 * contrast ratios between the top colors — grounding the graphic-critic
 * skill's color/contrast/harmony judgments in actual numbers instead of
 * eyeballing.
 *
 * Usage:
 *     ts-node color_palette.ts <image>
 *     (or compile with tsc and run the resulting .js with node)
 *
 * Supports PNG and JPEG (the two formats screenshots/exports almost always
 * use). Uses `pngjs` and `jpeg-js` — both pure-JS decoders, no native
 * compilation, unlike a full canvas library. This script only decodes pixels
 * and reports color statistics; it draws nothing (that's screenshot-annotator's
 * job) and passes no judgment on whether a palette is "good" (that's the
 * skill's job, informed by this data).
 *
 * Output (JSON):
 *   {
 *     width, height,
 *     dominantColors: [{ hex, percentage }, ...]   // most-to-least common
 *     contrastRatios: [{ colorA, colorB, ratio, passesAA, passesAAA }, ...]
 *   }
 */
import * as fs from "fs";
import * as path from "path";
import { PNG } from "pngjs";
import * as jpeg from "jpeg-js";

const TOP_COLOR_COUNT = 6;
const QUANTIZE_STEP = 24; // group similar colors together; smaller = more distinct buckets
const MAX_SAMPLED_PIXELS = 200_000; // subsample large images for speed

interface DecodedImage {
  width: number;
  height: number;
  data: Buffer | Uint8Array; // RGBA, 4 bytes per pixel
}

function decodeImage(filePath: string): DecodedImage {
  const buf = fs.readFileSync(filePath);
  const ext = path.extname(filePath).toLowerCase();

  if (ext === ".png" || (buf.length > 8 && buf[0] === 0x89 && buf[1] === 0x50)) {
    const png = PNG.sync.read(buf);
    return { width: png.width, height: png.height, data: png.data };
  }
  if (ext === ".jpg" || ext === ".jpeg" || (buf.length > 2 && buf[0] === 0xff && buf[1] === 0xd8)) {
    const decoded = jpeg.decode(buf, { useTArray: true });
    return { width: decoded.width, height: decoded.height, data: decoded.data };
  }
  throw new Error(
    `Unsupported image format for ${filePath} — only PNG and JPEG are supported. ` +
      "Convert the image to PNG first if it's a different format."
  );
}

function quantize(value: number): number {
  return Math.min(255, Math.round(value / QUANTIZE_STEP) * QUANTIZE_STEP);
}

function toHex(r: number, g: number, b: number): string {
  const h = (n: number) => n.toString(16).padStart(2, "0");
  return `#${h(r)}${h(g)}${h(b)}`;
}

function extractDominantColors(img: DecodedImage) {
  const totalPixels = img.width * img.height;
  const step = Math.max(1, Math.floor(Math.sqrt(totalPixels / MAX_SAMPLED_PIXELS)));

  const buckets = new Map<string, { rSum: number; gSum: number; bSum: number; count: number }>();
  let sampledPixels = 0;

  for (let y = 0; y < img.height; y += step) {
    for (let x = 0; x < img.width; x += step) {
      const idx = (y * img.width + x) * 4;
      const r = img.data[idx];
      const g = img.data[idx + 1];
      const b = img.data[idx + 2];
      const a = img.data[idx + 3];
      if (a !== undefined && a < 128) continue; // skip mostly-transparent pixels

      const key = `${quantize(r)}_${quantize(g)}_${quantize(b)}`;
      const bucket = buckets.get(key) ?? { rSum: 0, gSum: 0, bSum: 0, count: 0 };
      bucket.rSum += r;
      bucket.gSum += g;
      bucket.bSum += b;
      bucket.count += 1;
      buckets.set(key, bucket);
      sampledPixels++;
    }
  }

  const ranked = [...buckets.values()].sort((a, b) => b.count - a.count).slice(0, TOP_COLOR_COUNT);

  return ranked.map((bucket) => ({
    hex: toHex(
      Math.round(bucket.rSum / bucket.count),
      Math.round(bucket.gSum / bucket.count),
      Math.round(bucket.bSum / bucket.count)
    ),
    percentage: Math.round((bucket.count / sampledPixels) * 1000) / 10,
  }));
}

// WCAG 2.x relative luminance + contrast ratio.
function relativeLuminance(hex: string): number {
  const r = parseInt(hex.slice(1, 3), 16) / 255;
  const g = parseInt(hex.slice(3, 5), 16) / 255;
  const b = parseInt(hex.slice(5, 7), 16) / 255;
  const linearize = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * linearize(r) + 0.7152 * linearize(g) + 0.0722 * linearize(b);
}

function contrastRatio(hexA: string, hexB: string): number {
  const lA = relativeLuminance(hexA);
  const lB = relativeLuminance(hexB);
  const lighter = Math.max(lA, lB);
  const darker = Math.min(lA, lB);
  return Math.round(((lighter + 0.05) / (darker + 0.05)) * 100) / 100;
}

function computeContrastRatios(colors: { hex: string; percentage: number }[]) {
  const pairs: { colorA: string; colorB: string; ratio: number; passesAA: boolean; passesAAA: boolean }[] = [];
  for (let i = 0; i < colors.length; i++) {
    for (let j = i + 1; j < colors.length; j++) {
      const ratio = contrastRatio(colors[i].hex, colors[j].hex);
      pairs.push({
        colorA: colors[i].hex,
        colorB: colors[j].hex,
        ratio,
        passesAA: ratio >= 4.5, // WCAG AA for normal text
        passesAAA: ratio >= 7, // WCAG AAA for normal text
      });
    }
  }
  return pairs.sort((a, b) => b.ratio - a.ratio);
}

function main(): void {
  const filePath = process.argv[2];
  if (!filePath) {
    console.error("Usage: color_palette.ts <image>");
    process.exit(1);
  }
  if (!fs.existsSync(filePath)) {
    console.error(`No such file: ${filePath}`);
    process.exit(1);
  }

  const img = decodeImage(filePath);
  const dominantColors = extractDominantColors(img);
  const contrastRatios = computeContrastRatios(dominantColors);

  console.log(
    JSON.stringify(
      { width: img.width, height: img.height, dominantColors, contrastRatios },
      null,
      2
    )
  );
}

main();
