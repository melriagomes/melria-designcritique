/**
 * Thoroughly scan a file or image and report structural metadata as JSON.
 *
 * Usage:
 *     ts-node scan_file.ts <path>
 *     (or compile with tsc and run the resulting .js with node)
 *
 * This is a pure Node.js script with zero runtime dependencies — no native
 * modules, nothing to compile. Image dimensions are read by hand-parsing
 * PNG/JPEG/GIF/BMP/WEBP headers directly (a handful of bytes each), not by
 * decoding the image, so there's nothing here that needs a C++ toolchain.
 *
 * Output shape:
 *   Image:  { kind: "image", format, width, height, sizeBytes, sha256 }
 *   Text:   { kind: "text", sizeBytes, lineCount, wordCount, charCount,
 *             longestLineLength, hasVeryLongLines, encoding, sha256 }
 *   Binary: { kind: "binary", sizeBytes, sha256 }
 *
 * The intent is to surface, up front, exactly the things a quick visual
 * skim of a file misses — true dimensions on an image, or line/length
 * shape on a text file (e.g. a single 50,000-character minified line that
 * would otherwise blow past a normal reading window) — before the actual
 * content is read.
 */
import * as fs from "fs";
import * as crypto from "crypto";
import * as path from "path";

const VERY_LONG_LINE_THRESHOLD = 2000; // characters

type ImageFormat = "png" | "jpeg" | "gif" | "bmp" | "webp";

interface ImageDimensions {
  format: ImageFormat;
  width: number;
  height: number;
}

function sha256(buf: Buffer): string {
  return crypto.createHash("sha256").update(buf).digest("hex");
}

function readPngDimensions(buf: Buffer): ImageDimensions | null {
  const sig = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  if (buf.length < 24 || !buf.subarray(0, 8).equals(sig)) return null;
  return { format: "png", width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) };
}

function readGifDimensions(buf: Buffer): ImageDimensions | null {
  if (buf.length < 10) return null;
  const header = buf.toString("ascii", 0, 6);
  if (header !== "GIF87a" && header !== "GIF89a") return null;
  return { format: "gif", width: buf.readUInt16LE(6), height: buf.readUInt16LE(8) };
}

function readBmpDimensions(buf: Buffer): ImageDimensions | null {
  if (buf.length < 26 || buf[0] !== 0x42 || buf[1] !== 0x4d) return null; // "BM"
  const width = buf.readInt32LE(18);
  const height = Math.abs(buf.readInt32LE(22)); // negative height = top-down bitmap
  return { format: "bmp", width, height };
}

function readJpegDimensions(buf: Buffer): ImageDimensions | null {
  if (buf.length < 4 || buf[0] !== 0xff || buf[1] !== 0xd8) return null; // SOI marker
  let offset = 2;
  while (offset + 9 < buf.length) {
    if (buf[offset] !== 0xff) {
      offset++; // resync — some encoders pad between markers
      continue;
    }
    const marker = buf[offset + 1];
    // SOF0-SOF15 markers carry dimensions, except DHT(C4)/JPG(C8)/DAC(CC)
    const isSof = marker >= 0xc0 && marker <= 0xcf && marker !== 0xc4 && marker !== 0xc8 && marker !== 0xcc;
    if (isSof) {
      const height = buf.readUInt16BE(offset + 5);
      const width = buf.readUInt16BE(offset + 7);
      return { format: "jpeg", width, height };
    }
    if (marker === 0xd8 || marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) {
      offset += 2; // markers with no payload length
      continue;
    }
    const segmentLength = buf.readUInt16BE(offset + 2);
    offset += 2 + segmentLength;
  }
  return null;
}

function readWebpDimensions(buf: Buffer): ImageDimensions | null {
  if (buf.length < 30 || buf.toString("ascii", 0, 4) !== "RIFF" || buf.toString("ascii", 8, 12) !== "WEBP") {
    return null;
  }
  const chunkType = buf.toString("ascii", 12, 16);
  if (chunkType === "VP8X") {
    const width = 1 + (buf[24] | (buf[25] << 8) | (buf[26] << 16));
    const height = 1 + (buf[27] | (buf[28] << 8) | (buf[29] << 16));
    return { format: "webp", width, height };
  }
  if (chunkType === "VP8 ") {
    const width = buf.readUInt16LE(26) & 0x3fff;
    const height = buf.readUInt16LE(28) & 0x3fff;
    return { format: "webp", width, height };
  }
  if (chunkType === "VP8L") {
    const b0 = buf[21], b1 = buf[22], b2 = buf[23], b3 = buf[24];
    const width = 1 + (((b1 & 0x3f) << 8) | b0);
    const height = 1 + (((b3 & 0x0f) << 10) | (b2 << 2) | ((b1 & 0xc0) >> 6));
    return { format: "webp", width, height };
  }
  return null;
}

function readImageDimensions(buf: Buffer): ImageDimensions | null {
  return (
    readPngDimensions(buf) ||
    readJpegDimensions(buf) ||
    readGifDimensions(buf) ||
    readBmpDimensions(buf) ||
    readWebpDimensions(buf)
  );
}

function looksBinary(buf: Buffer): boolean {
  const sampleSize = Math.min(buf.length, 8000);
  for (let i = 0; i < sampleSize; i++) {
    if (buf[i] === 0) return true; // NUL byte is the standard "this is binary" signal
  }
  return false;
}

function scanText(buf: Buffer, sizeBytes: number) {
  const text = buf.toString("utf-8");
  const lines = text.split(/\r\n|\r|\n/);
  const lineCount = text.length === 0 ? 0 : lines.length;
  const wordCount = text.split(/\s+/).filter(Boolean).length;
  const longestLineLength = lines.reduce((max, line) => Math.max(max, line.length), 0);

  return {
    kind: "text" as const,
    sizeBytes,
    lineCount,
    wordCount,
    charCount: text.length,
    longestLineLength,
    hasVeryLongLines: longestLineLength > VERY_LONG_LINE_THRESHOLD,
    encoding: "utf-8",
    sha256: sha256(buf),
  };
}

function scanFile(filePath: string) {
  const resolved = path.resolve(filePath);
  const buf = fs.readFileSync(resolved);
  const sizeBytes = buf.length;

  const imageDims = readImageDimensions(buf);
  if (imageDims) {
    return {
      kind: "image" as const,
      format: imageDims.format,
      width: imageDims.width,
      height: imageDims.height,
      megapixels: Math.round((imageDims.width * imageDims.height) / 1_000_000 * 100) / 100,
      sizeBytes,
      sha256: sha256(buf),
    };
  }

  if (looksBinary(buf)) {
    return { kind: "binary" as const, sizeBytes, sha256: sha256(buf) };
  }

  return scanText(buf, sizeBytes);
}

function main(): void {
  const filePath = process.argv[2];
  if (!filePath) {
    console.error("Usage: scan_file.ts <path>");
    process.exit(1);
  }
  if (!fs.existsSync(filePath)) {
    console.error(`No such file: ${filePath}`);
    process.exit(1);
  }
  const result = scanFile(filePath);
  console.log(JSON.stringify(result, null, 2));
}

main();
