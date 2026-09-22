"""Screenshot Annotator — draws numbered callout markers on a design image.

This is the in-memory, server-side counterpart to the `screenshot-annotator`
Claude Code skill (`.claude/skills/screenshot-annotator/scripts/annotate_callouts.py`):
same drawing logic (numbered red badge + outline, sized relative to the
image, fraction-based bounding boxes so a vision model never has to guess
exact pixels), ported to operate on in-memory bytes instead of files since
the deployed app never touches disk for a request. It has no opinion on what
counts as a problem — the numbered `bbox_fraction` regions it draws are
decided upstream (`evidence_reporting`'s localization pass), mirroring how
the Claude Code skill only renders regions it's handed.
"""
import io

from PIL import Image, ImageDraw, ImageFont

MARKER_COLOR = (255, 45, 45)        # red outline / badge fill
BADGE_TEXT_COLOR = (255, 255, 255)  # white number

FONT_CANDIDATES = [
    "arialbd.ttf",
    "Arial Bold.ttf",
    "DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


def _load_font(size):
    for candidate in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def annotate_image(image_bytes, annotations):
    """Draw numbered callout markers on `image_bytes` and return new PNG bytes.

    `annotations` is a list of {"number": int, "bbox_fraction": [x1, y1, x2, y2],
    "shape": "box"|"ellipse" (optional, defaults to "box")} — each bbox_fraction
    value is a fraction (0-1) of the image's width/height, top-left origin.
    Raises if `annotations` is empty; callers should skip rendering entirely
    when there's nothing to mark rather than produce an unmarked copy.
    """
    if not annotations:
        raise ValueError("annotate_image requires at least one annotation")

    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    width, height = image.size
    draw = ImageDraw.Draw(image)

    short_side = min(width, height)
    outline_width = max(3, round(short_side * 0.004))
    badge_radius = max(16, round(short_side * 0.022))
    font = _load_font(round(badge_radius * 1.15))

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
        badge_cx = _clamp(x1, badge_radius, width - badge_radius)
        badge_cy = _clamp(y1, badge_radius, height - badge_radius)

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

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()
