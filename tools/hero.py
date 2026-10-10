"""Compose the README's hero image — one dimension model, carried end to end.

Not shipped code. Writes docs/hero.svg, then rasterises it to docs/hero.png with
a headless Chromium (the README shows the PNG: GitHub's `<img>` view of an SVG
loads no fonts). Needs the Inter and DejaVu Sans Mono fonts for the PNG to match,
and Pillow to crop the screenshot (`make hero` supplies it).

The figure is the README's argument drawn: five dimensions run as lines through
the five places a job search touches, and every chip on a line is in that
dimension's own terms. The sheet carries no counts (steps, dimensions, boards)
on purpose — a PNG cannot follow the repo, so whatever changes stays off it.

Usage, from the repository root:

    make hero
    CHROMIUM=/path/to/chrome make hero
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
OUT_SVG = ROOT / "docs" / "hero.svg"
OUT_PNG = ROOT / "docs" / "hero.png"

#: The GitHub social-preview size, which the README shows scaled to its column.
W, H = 1280, 640

PAPER = "#f3eee3"
GRID = "#e4ddcd"
INK = "#1d2733"
DIM = "#6b6f76"
FRAME = "#9a958a"
TEAL = "#0f6e66"
OK = "#2f7d4f"
WARN = "#b7791f"
UNKNOWN = "#8a8f99"
SANS = "Inter, 'DejaVu Sans', sans-serif"
DISPLAY = "'Inter Display', Inter, sans-serif"
MONO = "'DejaVu Sans Mono', monospace"

STAGES = [
    ("YOU", "what you need"),
    ("THE ADVERT", "evidence, quoted"),
    ("RANKING", "Pareto, no single score"),
    ("CV & LETTER", "written in the same terms"),
    ("INTERVIEW", "what is left to ask"),
]

#: (dimension, line colour, one chip per stage). A rank chip starts with its verdict.
ROWS = [
    (
        "remote arrangement",
        "#0f6e66",
        ["hybrid", "“2 days in the office”", "✓ fits", "remote track record", "which two days?"],
    ),
    (
        "schedule flexibility",
        "#7a4fa0",
        ["school run at 16:30", "“flexible hours”", "✓ fits", "async delivery", "core hours?"],
    ),
    (
        "commute burden",
        "#c2552f",
        ["≤ 40 min door to door", "“office in the centre”", "~ 35 min", "", ""],
    ),
    (
        "collaboration mode",
        "#2f6fb0",
        ["small team", "“team of four”", "✓ fits", "pairing, reviews", "how do you pair?"],
    ),
    (
        "career progression",
        "#8a6d1f",
        [
            "lead within two years",
            "not stated",
            "? unknown",
            "mentoring shown",
            "what is the path?",
        ],
    ),
]


def text(
    x: float,
    y: float,
    s: str,
    *,
    size: float,
    fill: str = INK,
    family: str = SANS,
    weight: int = 400,
    anchor: str = "start",
    spacing: float = 0,
    italic: bool = False,
) -> str:
    style = ' font-style="italic"' if italic else ""
    return (
        f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" '
        f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}" '
        f'letter-spacing="{spacing}"{style} xml:space="preserve">{escape(s)}</text>'
    )


def sheet() -> list[str]:
    """Grid, border with zone marks, registration marks — the family's drafting sheet."""
    out = [f'<rect width="{W}" height="{H}" fill="{PAPER}"/>']
    for x in range(0, W, 20):
        width = 0.9 if x % 100 == 0 else 0.4
        out.append(
            f'<line x1="{x}" y1="0" x2="{x}" y2="{H}" stroke="{GRID}" stroke-width="{width}"/>'
        )
    for y in range(0, H, 20):
        width = 0.9 if y % 100 == 0 else 0.4
        out.append(
            f'<line x1="0" y1="{y}" x2="{W}" y2="{y}" stroke="{GRID}" stroke-width="{width}"/>'
        )
    out.append(
        f'<rect x="16" y="16" width="{W - 32}" height="{H - 32}" fill="none" stroke="{GRID}"/>'
    )
    out.append(
        f'<rect x="30" y="30" width="{W - 60}" height="{H - 60}" fill="none" '
        f'stroke="{FRAME}" stroke-width="1.5"/>'
    )
    zw = (W - 60) / 8
    for i in range(8):
        x = 30 + zw * i
        if i:
            out.append(f'<line x1="{x}" y1="16" x2="{x}" y2="30" stroke="{FRAME}"/>')
            out.append(f'<line x1="{x}" y1="{H - 30}" x2="{x}" y2="{H - 16}" stroke="{FRAME}"/>')
        for y in (27, H - 19):
            out.append(
                text(x + zw / 2, y, str(8 - i), size=9, fill=DIM, family=MONO, anchor="middle")
            )
    zh = (H - 60) / 4
    for i in range(4):
        y = 30 + zh * i
        if i:
            out.append(f'<line x1="16" y1="{y}" x2="30" y2="{y}" stroke="{FRAME}"/>')
            out.append(f'<line x1="{W - 30}" y1="{y}" x2="{W - 16}" y2="{y}" stroke="{FRAME}"/>')
        for x in (23, W - 23):
            out.append(
                text(x, y + zh / 2 + 3, "ABCD"[i], size=9, fill=DIM, family=MONO, anchor="middle")
            )
    for cx, cy in ((48, 48), (48, H - 48)):
        out += [
            f'<circle cx="{cx}" cy="{cy}" r="7" fill="none" stroke="{TEAL}"/>',
            f'<line x1="{cx - 11}" y1="{cy}" x2="{cx + 11}" y2="{cy}" stroke="{TEAL}"/>',
            f'<line x1="{cx}" y1="{cy - 11}" x2="{cx}" y2="{cy + 11}" stroke="{TEAL}"/>',
        ]
    return out


def wordmark() -> list[str]:
    return [
        f'<text x="64" y="122" font-family="{DISPLAY}" font-size="70" font-weight="800" '
        f'letter-spacing="-2"><tspan fill="{INK}">integral</tspan>'
        f'<tspan fill="{TEAL}">-job-search</tspan></text>',
        text(68, 164, "One dimension model, carried end to end.", size=25, fill="#3b4652"),
        text(
            68,
            192,
            "A candidate-centred job search, run as a conversation in Claude Code.",
            size=15,
            fill=DIM,
        ),
    ]


def title_block() -> list[str]:
    x, y, h = 842, 62, 64
    w = 376
    half = w / 2 - 20
    # The two facts under the project row: (left edge, label, value).
    cells = [(0.0, "RUNS IN", "Claude Code"), (half, "YOUR DATA", "~/.integral-job-search")]
    out = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{PAPER}" stroke="{FRAME}" '
        f'stroke-width="1.2"/>',
        f'<line x1="{x}" y1="{y + h / 2 + 4}" x2="{x + w}" y2="{y + h / 2 + 4}" stroke="{FRAME}"/>',
    ]
    # Two rows: project across the top, the two facts underneath.
    out.append(text(x + 10, y + 14, "PROJECT", size=8, fill=DIM, family=MONO, spacing=1.5))
    out.append(text(x + 10, y + 30, "integral-job-search", size=14, weight=700, family=MONO))
    out.append(
        f'<line x1="{x + half}" y1="{y + h / 2 + 4}" x2="{x + half}" y2="{y + h}" '
        f'stroke="{FRAME}"/>'
    )
    for cx, label, value in cells:
        out.append(text(x + cx + 10, y + 47, label, size=8, fill=DIM, family=MONO, spacing=1.5))
        out.append(text(x + cx + 10, y + 61, value, size=11, family=MONO, fill=TEAL if cx else INK))
    return out


def figure() -> list[str]:
    left, label_w = 64, 190
    cols = [left + label_w + 90 + i * 200 for i in range(len(STAGES))]
    top, row_h = 290, 54
    out = [
        text(
            left,
            top - 52,
            "THE SAME TERMS AT EVERY STEP",
            size=10,
            fill=TEAL,
            family=MONO,
            spacing=2,
        )
    ]
    for cx, (name, sub) in zip(cols, STAGES, strict=True):
        out.append(
            text(cx, top - 30, name, size=11, weight=700, family=MONO, anchor="middle", spacing=1.5)
        )
        out.append(text(cx, top - 14, sub, size=11, fill=DIM, anchor="middle", italic=True))
        out.append(
            f'<line x1="{cx}" y1="{top - 4}" x2="{cx}" y2="{top + row_h * len(ROWS) - 14}" '
            f'stroke="{FRAME}" stroke-dasharray="2 4"/>'
        )
    for r, (dim, colour, chips) in enumerate(ROWS):
        y = top + 18 + r * row_h
        out.append(text(left, y + 4, dim, size=13, weight=600, family=MONO, fill=colour))
        out.append(
            f'<line x1="{left + label_w - 4}" y1="{y}" x2="{cols[-1] + 90}" y2="{y}" '
            f'stroke="{colour}" stroke-width="2.4" stroke-linecap="round" opacity="0.85"/>'
        )
        for c, (cx, chip) in enumerate(zip(cols, chips, strict=True)):
            if not chip:
                out.append(
                    f'<circle cx="{cx}" cy="{y}" r="3.5" fill="{PAPER}" stroke="{colour}" '
                    f'stroke-width="1.6"/>'
                )
                continue
            out += chip_at(cx, y, chip, colour, rank=c == 2, quote=c == 1)
    return out


def chip_at(cx: float, y: float, chip: str, colour: str, *, rank: bool, quote: bool) -> list[str]:
    fill, ink = PAPER, INK
    if rank:
        verdict = {"✓": OK, "~": WARN, "?": UNKNOWN}[chip[0]]
        fill, ink = verdict, "#ffffff"
    width = max(64.0, len(chip) * 6.2 + 24)
    out = [
        f'<rect x="{cx - width / 2}" y="{y - 12}" width="{width}" height="24" rx="12" '
        f'fill="{fill}" stroke="{colour if not rank else fill}" stroke-width="1.4"/>'
    ]
    out.append(
        text(
            cx,
            y + 4.5,
            chip,
            size=12,
            fill=ink,
            anchor="middle",
            italic=quote,
            weight=600 if rank else 400,
        )
    )
    return out


def svg() -> str:
    parts = sheet() + wordmark() + title_block() + figure()
    body = "\n  ".join(parts)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}">\n  {body}\n</svg>\n'
    )


def chromium() -> str:
    for candidate in (
        os.environ.get("CHROMIUM"),
        "/opt/pw-browsers/chromium",
        shutil.which("chromium"),
        shutil.which("google-chrome"),
    ):
        if candidate and Path(candidate).exists():
            return candidate
    sys.exit("hero: no Chromium found; set CHROMIUM=/path/to/chrome")


def main() -> None:
    OUT_SVG.write_text(svg())
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "hero.html"
        page.write_text(f'<html><body style="margin:0;overflow:hidden">{svg()}</body></html>')
        subprocess.run(
            [
                chromium(),
                "--headless=new",
                "--no-sandbox",
                "--hide-scrollbars",
                "--force-device-scale-factor=2",
                f"--window-size={W},{H + 200}",
                f"--screenshot={OUT_PNG}",
                page.as_uri(),
            ],
            check=True,
            capture_output=True,
        )
    # Headless Chromium's viewport is shorter than its window: shoot tall, then crop.
    from PIL import Image  # type: ignore[import-not-found, unused-ignore]

    with Image.open(OUT_PNG) as shot:
        shot.crop((0, 0, W * 2, H * 2)).save(OUT_PNG, optimize=True)
    print(f"wrote {OUT_SVG.relative_to(ROOT)} and {OUT_PNG.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
