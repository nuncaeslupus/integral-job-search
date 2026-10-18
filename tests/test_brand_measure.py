"""T342: the colour counts are recorded with a version and the document is rendered from them."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from integral import brand_gate, brand_measure
from integral.brand_palette import extract_palette

_REPO = Path(__file__).resolve().parents[1]
_SNIPPET = _REPO / "tools" / "measure_colours.js"


def test_the_gate_reads_zero_over_every_case() -> None:
    measured = brand_gate.measure()
    assert measured["gate_status"] == "measured"
    assert measured["generated_versions_without_a_recorded_palette_measurement"] == 0, measured[
        "defects"
    ]
    assert measured["generated_versions_examined_at_least"] == brand_gate.MINIMUM_VERSIONS == 3


def test_a_cli_that_records_nothing_is_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(brand_measure, "record", lambda *a, **k: None)
    measured = brand_gate.measure()
    # staging now refuses every unrecorded version, so none is read: not a clean zero
    assert measured["generated_versions_without_a_recorded_palette_measurement"] != 0
    assert any("staging refused" in d and "no palette.json" in d for d in measured["defects"])
    assert any("no recorded palette measurement" in d for d in measured["defects"])


def test_a_render_that_ignores_the_record_is_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("integral.approval.palette_for", lambda *a, **k: None)
    measured = brand_gate.measure()
    assert measured["generated_versions_without_a_recorded_palette_measurement"] != 0
    assert any("staging refused" in d for d in measured["defects"])


def test_a_render_with_one_fixed_accent_is_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    fixed = extract_palette({"#f46800": 1})
    monkeypatch.setattr("integral.approval.palette_for", lambda *a, **k: fixed)
    measured = brand_gate.measure()
    # two cases whose measured accent is another colour, and the unrecorded version staged
    assert measured["generated_versions_without_a_recorded_palette_measurement"] == 3
    assert any("not rendered with the measured accent" in d for d in measured["defects"])
    assert any("was staged" in d for d in measured["defects"])


def test_dropping_a_case_makes_the_gate_unmeasured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(brand_gate, "CASES", brand_gate.CASES[:2])
    measured = brand_gate.measure()
    assert measured["gate_status"] == "unmeasured"
    assert measured["generated_versions_without_a_recorded_palette_measurement"] == -1


def test_counts_must_be_a_flat_object_of_positive_integers() -> None:
    assert brand_measure.parse_counts('{"#ffffff": 3}') == {"#ffffff": 3}
    for bad in ("[]", '{"#ffffff": 0}', '{"#ffffff": true}', '{"#ffffff": "3"}', "nope"):
        with pytest.raises(brand_measure.MeasureError):
            brand_measure.parse_counts(bad)
    with pytest.raises(brand_measure.MeasureError):
        brand_measure.parse_counts('{"#ffffff": 1.5}')


@pytest.mark.parametrize(
    "key",
    [
        "oklch(0.705 0.213 47.604)",
        "rgb(244, 104, 0)",
        "rgba(244, 104, 0, 1)",
        "hsl(24 100% 48%)",
        "orange",
        "color(srgb 0.95 0.4 0)",
        "#fff",
        "#F46800",
        "#f46800 ",
        "f46800",
        "#f4680000",
        "",
    ],
)
def test_a_colour_key_that_is_not_lower_case_rrggbb_is_refused_not_dropped(key: str) -> None:
    with pytest.raises(brand_measure.MeasureError, match="not '#rrggbb'"):
        brand_measure.checked_counts({key: 3, "#ffffff": 9})


def test_the_cli_refuses_a_count_key_it_cannot_read_and_records_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from integral.identity import ProfileStore, create_profile

    identity = create_profile(tmp_path, "Ada Lovelace", handle="ada", language="en")
    version = tmp_path / "ada" / "cv" / "generated" / "o1" / "v1"
    ProfileStore(tmp_path, identity.handle).path("cv", "generated", "o1", "v1").mkdir(parents=True)
    counts = tmp_path / "c.json"
    counts.write_text('{"oklch(0.705 0.213 47.604)": 3, "#ffffff": 9}')
    code = brand_measure.main(
        [
            *("--site", "s", "--counts", str(counts), "--root", str(tmp_path)),
            *("--handle", "ada", "--offer", "o1", "--version", "1"),
        ]
    )
    assert code == 2 and "not '#rrggbb'" in capsys.readouterr().err
    assert not list(tmp_path.rglob("palette.json")), version


def test_a_record_of_another_schema_version_is_refused(tmp_path: Path) -> None:
    from integral.identity import ProfileStore, create_profile

    identity = create_profile(tmp_path, "Ada Lovelace", handle="ada", language="en")
    store = ProfileStore(tmp_path, identity.handle)
    where = ("cv", "generated", "o1", "v1")
    store.path(*where).mkdir(parents=True)
    body = {"site": "s", "counts": {"#f46800": 3}}
    store.write_json(
        {**body, "schema_version": brand_measure.SCHEMA_VERSION}, *where, "palette.json"
    )
    assert brand_measure.read_measurement(store, where) == ("s", {"#f46800": 3})
    for version in (brand_measure.SCHEMA_VERSION + 1, 0, "1"):
        store.write_json({**body, "schema_version": version}, *where, "palette.json")
        with pytest.raises(brand_measure.MeasureError, match="schema_version"):
            brand_measure.read_measurement(store, where)
        with pytest.raises(brand_measure.MeasureError, match="schema_version"):
            brand_measure.palette_for(store, where)
    store.write_json(body, *where, "palette.json")  # no schema_version at all
    with pytest.raises(brand_measure.MeasureError):
        brand_measure.read_measurement(store, where)


def _store_with_version(tmp_path: Path):  # type: ignore[no-untyped-def]
    from integral.identity import ProfileStore, create_profile

    identity = create_profile(tmp_path, "Ada Lovelace", handle="ada", language="en")
    store = ProfileStore(tmp_path, identity.handle)
    where = ("cv", "generated", "o1", "v1")
    store.path(*where).mkdir(parents=True)
    return store, where


def test_a_malformed_palette_json_counts_as_unmeasured(tmp_path: Path) -> None:
    store, where = _store_with_version(tmp_path)
    store.path(*where, "palette.json").write_text("{not json", encoding="utf-8")
    assert brand_measure.versions_without_measurement(store) == [where]
    store.write_json(
        {"schema_version": 1, "site": "s", "counts": {"#f46800": 3}}, *where, "palette.json"
    )
    assert brand_measure.versions_without_measurement(store) == []


def test_the_cli_refuses_to_rewrite_the_palette_of_a_version_with_a_send_folder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store, where = _store_with_version(tmp_path)
    store.path(*where, "send").mkdir()
    counts = tmp_path / "c.json"
    counts.write_text('{"#f46800": 1}')
    code = brand_measure.main(
        [
            *("--site", "s", "--counts", str(counts), "--root", str(tmp_path)),
            *("--handle", "ada", "--offer", "o1", "--version", "1"),
        ]
    )
    assert code != 0 and "send/" in capsys.readouterr().err
    assert not store.path(*where, "palette.json").exists()


@pytest.mark.parametrize("version", [True, 1.0])
def test_only_the_integer_one_is_a_schema_version(tmp_path: Path, version: object) -> None:
    store, where = _store_with_version(tmp_path)
    store.write_json(
        {"schema_version": version, "site": "s", "counts": {"#f46800": 3}}, *where, "palette.json"
    )
    with pytest.raises(brand_measure.MeasureError, match="schema_version"):
        brand_measure.read_measurement(store, where)


def test_staging_a_version_with_no_recorded_palette_is_refused(tmp_path: Path) -> None:
    from integral import approval
    from integral.cv_store import write_master
    from integral.identity import ProfileStore, create_profile
    from integral.send_set import fixture_renderer, fixture_text_reader

    identity = create_profile(tmp_path, "Ada Lovelace", handle="ada", language="en")
    store = ProfileStore(tmp_path, identity.handle)
    master = approval._probe_master()
    write_master(store, master)
    payload = approval._probe_prepare(store, master, (0,))
    where = ("cv", "generated", approval._PROBE_OFFER, f"v{payload.version}")
    assert brand_measure.versions_without_measurement(store) == [where]
    confirms = approval.payload_digest(
        approval.read_payload(store, approval._PROBE_OFFER, payload.version)
    )
    with pytest.raises(approval.ApprovalError, match=r"no palette\.json is recorded"):
        approval.stage_send(
            store,
            master,
            approval._PROBE_OFFER,
            payload.version,
            confirms=confirms,
            renderer=fixture_renderer,
            pdf_reader=fixture_text_reader,
        )
    assert not store.exists(*where, "send")


def test_the_gate_goes_red_when_an_unmeasured_version_is_not_listed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(brand_measure, "versions_without_measurement", lambda store: [])
    measured = brand_gate.measure()
    assert measured["generated_versions_without_a_recorded_palette_measurement"] > 0
    assert any("not listed as unmeasured" in d for d in measured["defects"])


def test_the_gate_goes_red_when_staging_no_longer_needs_a_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from integral import approval
    from integral.brand_palette import extract_palette

    monkeypatch.setattr(approval, "palette_for", lambda *a, **k: extract_palette({}))
    measured = brand_gate.measure()
    assert any("was staged" in d for d in measured["defects"])
    assert measured["generated_versions_without_a_recorded_palette_measurement"] > 0


def test_the_gate_goes_red_when_a_count_key_is_dropped_instead_of_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(brand_measure, "_COLOUR_KEY", __import__("re").compile(r".*"))
    measured = brand_gate.measure()
    assert any("was accepted by the CLI" in d for d in measured["defects"])


def test_the_cli_prints_the_section_and_appends_it(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    counts = tmp_path / "c.json"
    counts.write_text('{"#f46800": 40, "#ffffff": 200, "#111217": 120}')
    trace = tmp_path / "trazabilidad.md"
    trace.write_text("# Trace\n")
    code = brand_measure.main(
        ["--site", "https://x.example", "--counts", str(counts), "--trazabilidad", str(trace)]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert out.startswith("## Palette") and "`#f46800`" in out and "`#c55400`" in out
    assert trace.read_text().startswith("# Trace\n") and "`#f46800`" in trace.read_text()


def test_the_cli_refuses_bad_input_and_a_partial_recording_target(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    bad = tmp_path / "c.json"
    bad.write_text("[1]")
    assert brand_measure.main(["--site", "s", "--counts", str(bad)]) == 2
    assert "JSON object" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        brand_measure.main(["--site", "s", "--counts", str(bad), "--root", str(tmp_path)])


def test_the_cli_refuses_a_version_that_does_not_exist(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    from integral.identity import create_profile

    create_profile(tmp_path, "Ada Lovelace", handle="ada", language="en")
    counts = tmp_path / "c.json"
    counts.write_text('{"#f46800": 1}')
    code = brand_measure.main(
        [
            *("--site", "s", "--counts", str(counts), "--root", str(tmp_path)),
            *("--handle", "ada", "--offer", "nope", "--version", "1"),
        ]
    )
    assert code == 2 and "not a generated version" in capsys.readouterr().err


def _run_snippet(elements: list[dict]) -> dict[str, int]:  # type: ignore[type-arg]
    script = (
        "const fn = require(process.argv[1]);"
        "const els = JSON.parse(process.argv[2]).map(e => ({"
        "  namespaceURI: e.svg ? 'http://www.w3.org/2000/svg' : 'http://www.w3.org/1999/xhtml',"
        "  getClientRects: () => e.hidden ? [] : [1], style: e.style }));"
        "globalThis.getComputedStyle = (el) => el.style;"
        "const root = { querySelectorAll: () => els };"
        "process.stdout.write(JSON.stringify(fn(root)));"
    )
    done = subprocess.run(
        ["node", "-e", script, str(_SNIPPET), json.dumps(elements)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(done.stdout)  # type: ignore[no-any-return]


_BASE = {
    "color": "rgb(17, 18, 23)",
    "backgroundColor": "rgba(0, 0, 0, 0)",
    "fill": "rgb(0, 0, 0)",
    "stroke": "none",
    "borderTopStyle": "none",
    "borderTopWidth": "0px",
}


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_snippet_counts_each_colour_once_per_element() -> None:
    a = {**_BASE, "backgroundColor": "rgb(244, 104, 0)", "color": "rgb(244, 104, 0)"}
    b = {
        **_BASE,
        "borderTopStyle": "solid",
        "borderTopWidth": "2px",
        "borderTopColor": "rgb(244, 104, 0)",
    }
    hidden = {**_BASE, "color": "rgb(1, 2, 3)"}
    svg = {**_BASE, "fill": "rgb(9, 9, 9)", "stroke": "rgba(9, 9, 9, 0.5)"}
    got = _run_snippet(
        [{"style": a}, {"style": b}, {"style": hidden, "hidden": True}, {"style": svg, "svg": True}]
    )
    # a: one orange (colour and background are the same colour); b: ink + orange border;
    # hidden: not rendered; svg: ink + its fill; the translucent stroke is skipped.
    assert got == {"#f46800": 2, "#111217": 2, "#090909": 1}


def _within(got: dict[str, int], want: str, tolerance: int = 1) -> bool:
    (key,) = got
    return all(
        abs(int(key[i : i + 2], 16) - int(want[i : i + 2], 16)) <= tolerance for i in (1, 3, 5)
    )


# Reference values from the CSS Color 4 text and the Tailwind v4 palette, not from the
# snippet: sRGB red in oklab is (0.62796 0.22486 0.12585), in D50 lab (54.29 80.80 69.89),
# in lch (54.29 106.84 40.85); Tailwind v4 documents orange-500, oklch(70.5% 0.213 47.604),
# as about #ff6900; white is oklab(1 0 0).
_CSS_COLOUR_4 = [
    ("oklch(0.705 0.213 47.604)", "#ff6900", 2),
    ("oklch(70.5% 0.213 47.604)", "#ff6900", 2),
    ("oklch(0.705 0.213 47.604deg)", "#ff6900", 2),
    ("oklab(0.62796 0.22486 0.12585)", "#ff0000", 1),
    ("lab(54.29 80.8 69.89)", "#ff0000", 1),
    ("lch(54.29 106.84 40.85)", "#ff0000", 1),
    # CSS Color 4 percentages: lab/lch L 100% = 100, lab a/b 100% = 125, lch C 100% = 150.
    ("lab(54.29% 64.64% 55.912%)", "#ff0000", 1),
    ("lch(54.29% 71.22667% 40.85)", "#ff0000", 1),
    ("color(srgb 0.95 0.4 0)", "#f26600", 1),
    ("color(srgb-linear 1 0 0)", "#ff0000", 1),
    ("color(display-p3 1 0 0)", "#ff0000", 1),  # out of the sRGB gamut: clamped
    ("oklab(1 0 0)", "#ffffff", 1),
    ("rgb(244.5 104 0)", "#f56800", 1),
    ("rgb(244 104 0 / 1)", "#f46800", 0),
]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize(("value", "want", "tolerance"), _CSS_COLOUR_4)
def test_the_snippet_converts_css_colour_4_values_instead_of_dropping_them(
    value: str, want: str, tolerance: int
) -> None:
    got = _run_snippet([{"style": {**_BASE, "color": value}}])
    assert len(got) == 1 and _within(got, want, tolerance), (value, got)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_a_page_in_oklch_gives_the_brand_orange_not_the_default_link_blue() -> None:
    orange = {**_BASE, "backgroundColor": "oklch(0.705 0.213 47.604)"}
    got = _run_snippet(
        [
            {"style": orange},
            {"style": orange},
            {"style": {**orange, "backgroundColor": "color(srgb 0.95 0.4 0)"}},
            {"style": {**_BASE, "color": "lab(60 50 70)"}},
            {"style": {**_BASE, "color": "rgb(0, 0, 238)"}},
            {"style": {**_BASE, "color": "oklab(1 0 0)"}},
        ]
    )
    palette = extract_palette(brand_measure.checked_counts(got))
    assert palette.source == "site"
    assert palette.decorative_hex.lower() in {"#ff6900", "#fe6900", "#ff6a00", "#ff6800"}, got


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize(
    "value", ["oklch(0.5 0.1 120 / 0.5)", "rgba(0, 0, 0, 0)", "color(srgb 1 0 0 / 0.2)", "none"]
)
def test_the_snippet_still_skips_translucent_and_non_colours(value: str) -> None:
    assert _run_snippet([{"style": {**_BASE, "color": value}}]) == {}


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize(
    "value", ["color(xyz 1 1 1)", "color-mix(in srgb, red, blue)", "oklch(x y z)"]
)
def test_the_snippet_refuses_a_colour_function_it_cannot_read(value: str) -> None:
    with pytest.raises(subprocess.CalledProcessError) as raised:
        _run_snippet([{"style": {**_BASE, "color": value}}])
    assert "cannot read the computed colour" in raised.value.stderr


def test_the_send_dir_repeated_here_is_approvals() -> None:
    from integral import approval, brand_measure

    assert brand_measure._SEND_DIR == approval.SEND_DIR
