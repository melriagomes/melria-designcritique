#!/usr/bin/env python3
"""Overlay numbered callout markers on a UI screenshot.

Usage:
    python annotate_callouts.py <input_image> <annotations.json> <output_image>

annotations.json is a JSON array of objects:
    {
        "number": 1,
        "shape": "box" | "ellipse",       # optional, defaults to "box"
        "bbox_fraction": [x1, y1, x2, y2]  # each in [0, 1], relative to image
                                            # width/height, top-left origin
    }

Coordinates are fractions of the image's width/height (not raw pixels)
because a vision model estimating "where" a problem is on a screenshot is
far more reliable at judging position as a fraction of the image ("about a
third of the way down, spanning the left column") than at guessing exact
pixel numbers. This script does the fraction-to-pixel conversion.
"""
import argparse
import json
import sys

from PIL import Image, ImageDraw, ImageFont

MARKER_COLOR = (255, 45, 45)      # red outline / badge fill
BADGE_TEXT_COLOR = (255, 255, 255)  # white number

FONT_CANDIDATES = [
    "arialbd.ttf",
    "Arial Bold.ttf",
    "DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


def load_font(size):
    for candidate in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def draw_callouts(input_path, annotations, output_path):
    image = Image.open(input_path).convert("RGB")
    width, height = image.size
    draw = ImageDraw.Draw(image)

    short_side = min(width, height)
    outline_width = max(3, round(short_side * 0.004))
    badge_radius = max(16, round(short_side * 0.022))
    font = load_font(round(badge_radius * 1.15))

    for ann in annotations:
        number = ann["number"]
        shape = ann.get("shape", "box")
        fx1, fy1, fx2, fy2 = ann["bbox_fraction"]

        x1, y1 = fx1 * width, fy1 * height
        x2, y2 = fx2 * width, fy2 * height
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))

        if shape == "ellipse":
            draw.ellipse([x1, y1, x2, y2], outline=MARKER_COLOR, width=outline_width)
        else:
            draw.rectangle([x1, y1, x2, y2], outline=MARKER_COLOR, width=outline_width)

        # Badge sits at the top-left corner of the region, nudged so it
        # stays fully on-canvas even when the region touches an edge.
        badge_cx = clamp(x1, badge_radius, width - badge_radius)
        badge_cy = clamp(y1, badge_radius, height - badge_radius)

        draw.ellipse(
            [
                badge_cx - badge_radius,
                badge_cy - badge_radius,
                badge_cx + badge_radius,
                badge_cy + badge_radius,
            ],
            fill=MARKER_COLOR,
            outline=(255, 255, 255),
            width=max(2, outline_width - 1),
        )

        label = str(number)
        text_bbox = draw.textbbox((0, 0), label, font=font)
        text_w = text_bbox[2] - text_bbox[0]
        text_h = text_bbox[3] - text_bbox[1]
        draw.text(
            (badge_cx - text_w / 2 - text_bbox[0], badge_cy - text_h / 2 - text_bbox[1]),
            label,
            fill=BADGE_TEXT_COLOR,
            font=font,
        )

    image.save(output_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_image")
    parser.add_argument("annotations_json", help="Path to a JSON file (see module docstring for schema)")
    parser.add_argument("output_image")
    args = parser.parse_args()

    with open(args.annotations_json, "r", encoding="utf-8") as f:
        annotations = json.load(f)

    if not isinstance(annotations, list) or not annotations:
        print("annotations_json must contain a non-empty JSON array", file=sys.stderr)
        sys.exit(1)

    for ann in annotations:
        if "number" not in ann or "bbox_fraction" not in ann:
            print(f"Each annotation needs 'number' and 'bbox_fraction': {ann}", file=sys.stderr)
            sys.exit(1)
        if len(ann["bbox_fraction"]) != 4:
            print(f"'bbox_fraction' must have 4 values [x1,y1,x2,y2]: {ann}", file=sys.stderr)
            sys.exit(1)

    draw_callouts(args.input_image, annotations, args.output_image)
    print(f"Wrote {args.output_image} with {len(annotations)} callout(s)")


if __name__ == "__main__":
    main()
