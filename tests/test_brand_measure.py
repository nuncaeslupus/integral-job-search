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
    assert measured["generated_versions_without_a_recorded_palette_measurement"] == 3
    assert any("no recorded palette measurement" in d for d in measured["defects"])


def test_a_render_that_ignores_the_record_is_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("integral.approval.palette_for", lambda *a, **k: None)
    measured = brand_gate.measure()
    assert measured["generated_versions_without_a_recorded_palette_measurement"] == 3
    assert any("not rendered with the measured accent" in d for d in measured["defects"])


def test_a_render_with_one_fixed_accent_is_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    fixed = extract_palette({"#f46800": 1})
    monkeypatch.setattr("integral.approval.palette_for", lambda *a, **k: fixed)
    measured = brand_gate.measure()
    assert measured["generated_versions_without_a_recorded_palette_measurement"] == 2


def test_dropping_a_case_makes_the_gate_unmeasured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(brand_gate, "CASES", brand_gate.CASES[:2])
    measured = brand_gate.measure()
    assert measured["gate_status"] == "unmeasured"
    assert measured["generated_versions_without_a_recorded_palette_measurement"] == -1


def test_counts_must_be_a_flat_object_of_positive_integers() -> None:
    assert brand_measure.parse_counts('{"#fff": 3}') == {"#fff": 3}
    for bad in ("[]", '{"#fff": 0}', '{"#fff": true}', '{"#fff": "3"}', '{"#fff": 1.5}', "nope"):
        with pytest.raises(brand_measure.MeasureError):
            brand_measure.parse_counts(bad)


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
