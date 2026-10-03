"""T182: take the document's accent colour from the employer's own site.

A document in the employer's palette reads as addressed to them; one in a
colour the assistant liked reads as a template. The palette is **measured, not
guessed**: the session reads ``getComputedStyle`` over the employer's pages and
passes in how many elements carry each colour (``{"#ec504e": 31, ...}``). This
module does no fetching (that is the connector layer's job, under its robots
rules); it turns those counts into roles and a contrast-safe text variant.

Roles, each chosen by frequency among the measured colours:

* **paper**: the most frequent *light* colour (relative luminance at least
  ``PAPER_MIN_LUMINANCE``) of low saturation, e.g. a cream. Else white.
* **ink**: the most frequent colour with at least ``INK_MIN_CONTRAST`` against
  the paper. Else ``#111111``.
* **accent**: the most frequent *colourful* colour (HSL saturation at least
  ``ACCENT_MIN_SATURATION``, lightness within ``ACCENT_LIGHTNESS``), neither
  paper nor ink. Dark saturated blues are ink-like and are excluded by the
  lightness floor.

The accent is chosen for large type and buttons and is often illegible as body
text, so two variants are emitted and named: ``accent`` is the **decorative**
colour, exactly as the site has it (contrast does not apply to rules), and
``accent_text`` is the **text** variant, the original colour unchanged when it
already reaches ``AA_TEXT`` on the paper, else the least-darkened colour of the
same hue (mixed toward black) that does. Contrast is WCAG 2.x relative luminance,
unrounded: 4.499 fails, as the standard has it. Paper is always light, so a
text colour that passes on the paper also passes on pure white.

If nothing usable was read, or no accent can be named, the **neutral** palette
is returned with ``source == "neutral"`` and a reason. A guessed brand colour is
worse than none.
"""

from __future__ import annotations

import colorsys
import re
from collections.abc import Mapping
from dataclasses import dataclass

AA_TEXT = 4.5
INK_MIN_CONTRAST = 7.0
PAPER_MIN_LUMINANCE = 0.8
PAPER_MAX_SATURATION = 0.2
ACCENT_MIN_SATURATION = 0.5
ACCENT_LIGHTNESS = (0.3, 0.85)

NEUTRAL_INK = "#111111"
NEUTRAL_PAPER = "#ffffff"
NEUTRAL_ACCENT = "#999999"

_HEX = re.compile(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})")
_RGB = re.compile(
    r"rgba?\(\s*(\d{1,3})\s*[, ]\s*(\d{1,3})\s*[, ]\s*(\d{1,3})\s*(?:[,/]\s*([0-9.]+%?)\s*)?\)"
)

RGB = tuple[int, int, int]


def parse_colour(text: str) -> RGB | None:
    """``#rgb``, ``#rrggbb`` or ``rgb()/rgba()`` (opaque only) as 0-255 channels, else None."""
    text = text.strip()
    if m := _HEX.fullmatch(text):
        h = m.group(1)
        h = "".join(c * 2 for c in h) if len(h) == 3 else h
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    if m := _RGB.fullmatch(text.lower()):
        channels = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if max(channels) > 255:
            return None
        alpha = m.group(4)
        if alpha is not None:
            try:
                value = float(alpha[:-1]) / 100 if alpha.endswith("%") else float(alpha)
            except ValueError:
                return None
            if value != 1:  # a translucent colour is not the colour that is seen
                return None
        return channels
    return None


def to_hex(rgb: RGB) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def relative_luminance(rgb: RGB) -> float:
    """WCAG 2.x relative luminance (sRGB linearised, 0.2126 R + 0.7152 G + 0.0722 B)."""

    def lin(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: RGB, b: RGB) -> float:
    hi, lo = sorted((relative_luminance(a), relative_luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _hls(rgb: RGB) -> tuple[float, float, float]:
    return colorsys.rgb_to_hls(*(c / 255 for c in rgb))


def text_variant(colour: RGB, paper: RGB, minimum: float = AA_TEXT) -> RGB:
    """``colour`` if it reaches ``minimum`` on ``paper``, else its lightest darkening that does.

    Darkening mixes the colour toward black (every channel scaled by one factor, so the
    hue and the channel proportions are kept), one 8-bit step of the brightest channel at
    a time from the original downwards; the first step that passes is the least darkened.
    ``paper`` must be lighter than any text on it, so that black reaches ``minimum``
    (``extract_palette`` ensures it).
    """
    if contrast_ratio(colour, paper) >= minimum:
        return colour
    top = max(colour)
    for level in range(top - 1, -1, -1):
        r, g, b = (round(c * level / top) for c in colour)
        if contrast_ratio((r, g, b), paper) >= minimum:
            return (r, g, b)
    return (0, 0, 0)


@dataclass(frozen=True)
class BrandPalette:
    source: str  # "site" or "neutral"
    reason: str  # why neutral, or what was read
    ink: RGB
    paper: RGB
    accent: RGB  # decorative: rules, borders. Exactly the site's colour.
    accent_text: RGB  # text: >= AA_TEXT on paper
    measured: tuple[tuple[str, int], ...] = ()  # (hex, element count), most frequent first

    @property
    def decorative_hex(self) -> str:
        return to_hex(self.accent)

    @property
    def text_hex(self) -> str:
        return to_hex(self.accent_text)

    @property
    def accent_text_contrast(self) -> float:
        return contrast_ratio(self.accent_text, self.paper)


def neutral_palette(reason: str, measured: tuple[tuple[str, int], ...] = ()) -> BrandPalette:
    ink, paper, accent = (parse_colour(c) for c in (NEUTRAL_INK, NEUTRAL_PAPER, NEUTRAL_ACCENT))
    assert ink and paper and accent
    return BrandPalette(
        "neutral", reason, ink, paper, accent, text_variant(accent, paper), measured
    )


def _tally(samples: Mapping[str, int]) -> list[tuple[RGB, int]]:
    counts: dict[RGB, int] = {}
    for key, n in samples.items():
        rgb = parse_colour(key) if isinstance(key, str) else None
        if rgb is None or isinstance(n, bool) or not isinstance(n, int) or n <= 0:
            continue
        counts[rgb] = counts.get(rgb, 0) + n
    # most frequent first; ties by hex so the answer never depends on input order
    return sorted(counts.items(), key=lambda kv: (-kv[1], to_hex(kv[0])))


def extract_palette(samples: Mapping[str, int] | None) -> BrandPalette:
    """Roles from ``{colour: element count}``; neutral, with the reason, when it cannot."""
    ranked = _tally(samples or {})
    measured = tuple((to_hex(rgb), n) for rgb, n in ranked)
    if not ranked:
        return neutral_palette("the site could not be read: no usable colours measured")

    paper = next(
        (
            rgb
            for rgb, _ in ranked
            if relative_luminance(rgb) >= PAPER_MIN_LUMINANCE
            and _hls(rgb)[2] <= PAPER_MAX_SATURATION
        ),
        (255, 255, 255),
    )
    ink = next(
        (rgb for rgb, _ in ranked if contrast_ratio(rgb, paper) >= INK_MIN_CONTRAST),
        parse_colour(NEUTRAL_INK),
    )
    assert ink is not None
    low, high = ACCENT_LIGHTNESS
    accent = next(
        (
            rgb
            for rgb, _ in ranked
            if rgb not in (paper, ink)
            and _hls(rgb)[2] >= ACCENT_MIN_SATURATION
            and low <= _hls(rgb)[1] <= high
        ),
        None,
    )
    if accent is None:
        return neutral_palette("no accent colour found among the measured colours", measured)
    return BrandPalette(
        "site",
        f"{len(ranked)} distinct colours measured by element count",
        ink,
        paper,
        accent,
        text_variant(accent, paper),
        measured,
    )


def css(palette: BrandPalette) -> str:
    """Plain declarations only: the print-CSS checker refuses any at-rule but print/page."""
    return (
        f"body {{ color: {to_hex(palette.ink)}; background: {to_hex(palette.paper)};"
        " -webkit-print-color-adjust: exact; print-color-adjust: exact; }\n"
        f"h1, h3 {{ color: {palette.text_hex}; }}\n"
        f"h2 {{ color: {palette.text_hex}; border-bottom-color: {palette.decorative_hex}; }}\n"
    )


def trazabilidad_section(palette: BrandPalette, site: str) -> str:
    """The measurement as Markdown for ``trazabilidad.md``, so no session re-derives it."""
    site = re.sub(r"[`\s]+", " ", site).strip() or "(no site given)"
    lines = [
        "## Palette",
        "",
        f"- Site: `{site}`",
        f"- Source: **{palette.source}**: {palette.reason}",
    ]
    if palette.source == "neutral":
        lines.append("- No brand colour is used: a guessed colour is worse than none.")
    lines += [
        f"- Paper: `{to_hex(palette.paper)}`; ink: `{to_hex(palette.ink)}`",
        f"- Accent, decorative (rules, borders; exact): `{palette.decorative_hex}`",
        f"- Accent, text (darkened only as far as needed): `{palette.text_hex}`, "
        f"{palette.accent_text_contrast:.2f}:1 on paper (WCAG AA body text needs {AA_TEXT}:1)",
    ]
    if palette.measured:
        lines += ["", "| Colour | Elements |", "|---|---|"]
        lines += [f"| `{c}` | {n} |" for c, n in palette.measured]
    return "\n".join(lines) + "\n"
