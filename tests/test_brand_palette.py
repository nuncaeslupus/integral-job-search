"""T182: the accent colour is the employer's own, with a text variant that reads."""

from __future__ import annotations

import colorsys

import pytest

from integral.application_render import render_document
from integral.brand_palette import (
    AA_TEXT,
    NEUTRAL_ACCENT,
    BrandPalette,
    contrast_ratio,
    css,
    extract_palette,
    neutral_palette,
    parse_colour,
    text_variant,
    to_hex,
    trazabilidad_section,
)


def rgb(text: str) -> tuple[int, int, int]:
    value = parse_colour(text)
    assert value is not None
    return value


def oracle_ratio(a: str, b: str) -> float:
    """WCAG 2.x contrast written out from the definition, independently of the module.

    Channel -> linear light (threshold 0.04045, exponent 2.4), weights from the
    standard, ratio (L1 + 0.05) / (L2 + 0.05) with L1 the lighter.
    """
    ls = []
    for text in (a, b):
        h = text.lstrip("#")
        lin = []
        for i in (0, 2, 4):
            c = int(h[i : i + 2], 16) / 255
            lin.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
        ls.append(0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2])
    return (max(ls) + 0.05) / (min(ls) + 0.05)


DOMMA = {
    "#101637": 2440,
    "#1c296a": 310,
    "#ec504e": 120,
    "#f8f7f5": 900,
    "#bbbcca": 80,
}
ALREADY_DARK = {"#ffffff": 500, "#111111": 900, "#0b5394": 200}  # accent passes unchanged
JUST_FAILS = {"#ffffff": 500, "#111111": 900, "#1e90ff": 200}  # dodger blue, ~3.2:1
GREEN = {"#fafafa": 700, "#0a0a0a": 1000, "#2ecc71": 60}
NO_PAPER = {"#101010": 900, "#ff5c8a": 100}  # no light colour measured: paper is white
FIXTURES = [DOMMA, ALREADY_DARK, JUST_FAILS, GREEN, NO_PAPER]


# --- the contrast formula ---------------------------------------------------


def test_contrast_formula_known_values() -> None:
    assert contrast_ratio(rgb("#000000"), rgb("#ffffff")) == pytest.approx(21.0)
    assert contrast_ratio(rgb("#ffffff"), rgb("#ffffff")) == pytest.approx(1.0)
    # the task's own measurements
    # (the task says 3.7 and 4.9; the formula gives 3.61 and 5.04: the point stands)
    assert oracle_ratio("#ec504e", "#ffffff") == pytest.approx(3.6057, abs=1e-3)
    assert oracle_ratio("#c93b39", "#ffffff") == pytest.approx(5.0382, abs=1e-3)
    for a, b in [("#ec504e", "#ffffff"), ("#1e90ff", "#f8f7f5"), ("#777777", "#ffffff")]:
        assert contrast_ratio(rgb(a), rgb(b)) == pytest.approx(oracle_ratio(a, b), rel=1e-12)
        assert contrast_ratio(rgb(a), rgb(b)) == contrast_ratio(rgb(b), rgb(a))


def test_aa_boundary_is_exact_and_unrounded() -> None:
    """#767676 on white is 4.54:1 (passes), #777777 is 4.48:1 (fails): the AA edge, not tuned."""
    white = rgb("#ffffff")
    assert oracle_ratio("#767676", "#ffffff") >= AA_TEXT > oracle_ratio("#777777", "#ffffff")
    assert text_variant(rgb("#767676"), white) == rgb("#767676")  # passes: untouched
    assert text_variant(rgb("#777777"), white) == rgb("#767676")  # lightest grey that passes
    assert AA_TEXT == 4.5


# --- the text variant -------------------------------------------------------


@pytest.mark.parametrize("samples", FIXTURES)
def test_text_variant_meets_aa(samples: dict[str, int]) -> None:
    palette = extract_palette(samples)
    assert palette.source == "site"
    # measured by the independent oracle, on the paper the document is printed on
    assert oracle_ratio(palette.text_hex, to_hex(palette.paper)) >= AA_TEXT
    # and therefore on pure white as well, since paper is never darker than that
    assert oracle_ratio(palette.text_hex, "#ffffff") >= AA_TEXT


def test_text_variant_meets_aa_across_the_colour_wheel() -> None:
    """Not tuned to fixtures: every hue, saturation and lightness, on several papers."""
    papers = [rgb("#ffffff"), rgb("#f8f7f5"), rgb("#eeeeee"), rgb("#cccccc")]
    for paper in papers:
        for hue in range(0, 360, 15):
            for sat in (0.0, 0.3, 0.6, 1.0):
                for light in (0.1, 0.3, 0.5, 0.7, 0.9):
                    r, g, b = colorsys.hls_to_rgb(hue / 360, light, sat)
                    colour = (round(r * 255), round(g * 255), round(b * 255))
                    out = text_variant(colour, paper)
                    assert contrast_ratio(out, paper) >= AA_TEXT, (colour, paper, out)


def test_text_variant_is_unchanged_when_already_dark_enough() -> None:
    palette = extract_palette(ALREADY_DARK)
    assert palette.text_hex == palette.decorative_hex == "#0b5394"


def test_text_variant_is_darkened_no_further_than_needed() -> None:
    """The next brighter step along the same hue fails AA, by the independent oracle."""
    for samples in (DOMMA, JUST_FAILS, GREEN, NO_PAPER):
        palette = extract_palette(samples)
        assert palette.text_hex != palette.decorative_hex  # it did have to move
        top = max(palette.accent_text)
        brighter = tuple(round(c * (top + 1) / max(palette.accent)) for c in palette.accent)
        assert oracle_ratio(to_hex(brighter), to_hex(palette.paper)) < AA_TEXT  # type: ignore[arg-type]
        # a darkening of the same colour: channels scaled by one factor, never brighter
        factor = top / max(palette.accent)
        assert factor < 1
        for orig, now in zip(palette.accent, palette.accent_text, strict=True):
            assert abs(now - orig * factor) <= 1.0 + orig / max(palette.accent)


# --- the decorative variant -------------------------------------------------


def test_decorative_variant_is_the_unmodified_brand_colour() -> None:
    expected = {
        id(DOMMA): "#ec504e",
        id(ALREADY_DARK): "#0b5394",
        id(JUST_FAILS): "#1e90ff",
        id(GREEN): "#2ecc71",
        id(NO_PAPER): "#ff5c8a",
    }
    for samples in FIXTURES:
        palette = extract_palette(samples)
        assert palette.decorative_hex == expected[id(samples)]
        assert palette.accent == rgb(expected[id(samples)])
    # the text variant differs where AA demands it; the rule colour never follows it
    domma = extract_palette(DOMMA)
    assert domma.text_hex != domma.decorative_hex
    sheet = css(domma)
    assert f"border-bottom-color: {domma.decorative_hex}" in sheet
    assert domma.text_hex in sheet and "#ec504e" in sheet


def test_roles_follow_element_frequency() -> None:
    palette = extract_palette(DOMMA)
    assert (to_hex(palette.ink), to_hex(palette.paper), palette.decorative_hex) == (
        "#101637",
        "#f8f7f5",
        "#ec504e",
    )
    # the secondary blue and lilac-grey are neither accent nor ink
    assert [c for c, _ in palette.measured][:2] == ["#101637", "#f8f7f5"]
    # a more frequent colourful colour wins the accent role
    both = extract_palette({**DOMMA, "#2ecc71": 5000})
    assert both.decorative_hex == "#2ecc71"


def test_equivalent_spellings_pool_their_counts_and_order_is_irrelevant() -> None:
    a = extract_palette({"rgb(236, 80, 78)": 70, "#ec504e": 60, "#111": 100, "#fff": 10})
    b = extract_palette({"#fff": 10, "#111": 100, "#ec504e": 60, "rgb(236,80,78)": 70})
    assert a == b
    assert ("#ec504e", 130) in a.measured


def test_unusable_colour_values_are_ignored_not_guessed() -> None:
    for bad in ("transparent", "rgba(236, 80, 78, 0.5)", "rgb(300, 0, 0)", "red", "#12345", ""):
        assert parse_colour(bad) is None, bad
    assert rgb("rgba(236, 80, 78, 1)") == (236, 80, 78)
    noisy = {**DOMMA, "transparent": 9999, "rgba(236, 80, 78, 0.5)": 9999, "#00ff00": 0}
    assert extract_palette(noisy) == extract_palette(DOMMA)


# --- falling back ------------------------------------------------------------


@pytest.mark.parametrize(
    "samples",
    [None, {}, {"transparent": 40, "rgba(0, 0, 0, 0)": 900}, {"#ec504e": 0, "#101637": -3}],
)
def test_unreadable_site_falls_back_and_says_so(samples: dict[str, int] | None) -> None:
    palette = extract_palette(samples)
    assert palette.source == "neutral"
    assert "could not be read" in palette.reason
    assert palette.decorative_hex == NEUTRAL_ACCENT
    assert palette.measured == ()
    assert palette.accent_text_contrast >= AA_TEXT  # the neutral text colour is also AA-safe
    note = trazabilidad_section(palette, "https://example.test")
    assert "neutral" in note and "could not be read" in note
    assert "No brand colour is used" in note


def test_a_site_with_no_accent_falls_back_rather_than_guessing_one() -> None:
    greys = {"#ffffff": 800, "#111111": 900, "#888888": 300, "#cccccc": 100}
    palette = extract_palette(greys)
    assert palette.source == "neutral"
    assert "no accent" in palette.reason
    assert palette == neutral_palette(palette.reason, palette.measured)
    # the measurement is still recorded, so the candidate can see what was read
    assert ("#111111", 900) in palette.measured


# --- the record --------------------------------------------------------------


def test_trazabilidad_records_the_measurement_and_which_colour_is_which() -> None:
    palette = extract_palette(DOMMA)
    note = trazabilidad_section(palette, "https://domma.example/\n`x`")
    assert "`https://domma.example/ x`" in note  # one line, no stray backtick
    assert "Source: **site**" in note
    assert "decorative" in note and f"`{palette.decorative_hex}`" in note
    assert f"`{palette.text_hex}`" in note
    assert f"{oracle_ratio(palette.text_hex, to_hex(palette.paper)):.2f}:1" in note
    for colour, count in DOMMA.items():
        assert f"| `{colour}` | {count} |" in note


# --- the document ------------------------------------------------------------


def test_palette_reaches_the_document_without_adding_an_at_rule() -> None:
    palette = extract_palette(DOMMA)
    base = render_document("# H\n\n## S\n\ntext", title="t")
    themed = render_document("# H\n\n## S\n\ntext", title="t", palette=palette)
    assert base != themed
    assert palette.text_hex in themed and palette.decorative_hex in themed
    extra = css(palette)
    assert "@" not in extra and "{" not in extra.replace("{", "", extra.count("{"))
    assert extra.count("{") == extra.count("}")
    assert render_document("# H", title="t", palette=None) == render_document("# H", title="t")


def test_palette_is_a_value_object() -> None:
    palette = extract_palette(DOMMA)
    assert isinstance(palette, BrandPalette)
    with pytest.raises(AttributeError):
        palette.source = "x"  # type: ignore[misc]
