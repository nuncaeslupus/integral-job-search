"""T342's gate: a generated version's accent is the employer's measured colour, on record.

`generated_versions_without_a_recorded_palette_measurement` counts, over constructed
generated versions, the ones where the step-11 flow leaves a defect:

* no `palette.json` is recorded for the version (`brand_measure.versions_without_measurement`);
* the sendable PDFs do not carry the accent the measured counts give, written out
  literally per fixture below (not derived by `brand_palette`, which would be the code
  judging itself), or carry another fixture's accent;
* a site that could not be read does not fall back to the neutral accent, and
  `trazabilidad_section` does not say so;
* `verify_send` finds a defect in the folder staged from the record.

The flow is driven through the shipped CLI (`brand_measure.main`), so a CLI that stops
recording is counted. The engine is `send_set.fixture_renderer`, which keeps each page's
HTML, so the accent is read out of the rendered style rather than assumed.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from integral import brand_measure
from integral.approval import (
    _PROBE_OFFER,
    ApprovalError,
    _probe_master,
    _probe_prepare,
    payload_digest,
    read_payload,
    stage_send,
    verify_send,
)
from integral.cv_store import write_master
from integral.identity import ProfileStore, create_profile
from integral.send_set import fixture_renderer, fixture_text_reader

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T342.json"

# (handle, site, measured counts, the decorative accent the document must carry). The
# accent is stated, not derived. The last site could not be read: neutral grey.
CASES: tuple[tuple[str, str, dict[str, int], str], ...] = (
    ("ada", "https://orange.example", {"#f46800": 40, "#ffffff": 200, "#111217": 120}, "#f46800"),
    ("nuria", "https://red.example", {"rgb(228, 0, 43)": 30, "rgb(255, 255, 255)": 90}, "#e4002b"),
    ("cher", "https://closed.example", {}, "#999999"),
)
# floor on the versions examined: a zero-length scan must not read as a clean zero
# The population is CASES, three constructed versions; dropping one breaches it.
# arsenal-floor-margin: MINIMUM_VERSIONS value=3
MINIMUM_VERSIONS = 3


def _version_defects(
    handle: str, site: str, counts: dict[str, int], accent: str, root: Path
) -> tuple[bool, list[str]]:
    """`(examined, defects)` for one constructed version."""
    identity = create_profile(root, handle.title(), handle=handle, language="en")
    store = ProfileStore(root, identity.handle)
    master = _probe_master()
    write_master(store, master)
    payload = _probe_prepare(store, master, (0,))
    counts_file = root / f"{handle}-counts.json"
    counts_file.write_text(json.dumps(counts), encoding="utf-8")
    trace = root / f"{handle}-trazabilidad.md"
    argv = ["--site", site, "--counts", str(counts_file), "--trazabilidad", str(trace)]
    argv += ["--root", str(root), "--handle", identity.handle, "--offer", _PROBE_OFFER]
    argv += ["--version", str(payload.version)]
    with contextlib.redirect_stdout(io.StringIO()):
        brand_measure.main(argv)
    found: list[str] = []
    if brand_measure.versions_without_measurement(store):
        found.append(f"{handle}: the version has no recorded palette measurement")
    if not trace.exists() or f"`{accent}`" not in trace.read_text(encoding="utf-8"):
        found.append(f"{handle}: the trazabilidad section does not name the accent {accent}")
    if not counts and "**neutral**" not in (
        trace.read_text(encoding="utf-8") if trace.exists() else ""
    ):
        found.append(f"{handle}: an unreadable site is not recorded as neutral")
    try:
        folder = stage_send(
            store,
            master,
            _PROBE_OFFER,
            payload.version,
            confirms=payload_digest(read_payload(store, _PROBE_OFFER, payload.version)),
            renderer=fixture_renderer,
            pdf_reader=fixture_text_reader,
        )
    except ApprovalError as exc:
        return False, [*found, f"{handle}: staging refused: {exc}"]
    others = {case[3] for case in CASES} - {accent}
    for pdf in sorted(folder.glob("*.pdf")):
        style = pdf.read_bytes().decode("utf-8", "replace")
        if f"border-bottom-color: {accent};" not in style:
            found.append(f"{handle}: {pdf.name} is not rendered with the measured accent {accent}")
        for other in sorted(others):
            if other in style:
                found.append(f"{handle}: {pdf.name} carries {other}, which was not measured here")
    found.extend(
        f"{handle}: {d}"
        for d in verify_send(store, _PROBE_OFFER, payload.version, pdf_reader=fixture_text_reader)
    )
    return True, found


def measure() -> dict[str, Any]:
    """`generated_versions_without_a_recorded_palette_measurement` over the constructed versions."""
    defects: list[str] = []
    bad = examined = 0
    with tempfile.TemporaryDirectory() as scratch:
        for handle, site, counts, accent in CASES:
            read, found = _version_defects(handle, site, counts, accent, Path(scratch) / handle)
            examined += read
            bad += bool(found)
            defects.extend(found)
    if examined < MINIMUM_VERSIONS:
        return {
            "generated_versions_without_a_recorded_palette_measurement": -1,
            "gate_status": "unmeasured",
            "reasons": [f"{examined} versions examined; the floor is {MINIMUM_VERSIONS}"],
        }
    return {
        "generated_versions_without_a_recorded_palette_measurement": bad,
        "generated_versions_examined_at_least": MINIMUM_VERSIONS,
        "gate_status": "measured",
        "defects": defects,
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main() -> int:
    measured = write_evidence()
    print(json.dumps({k: v for k, v in measured.items() if k != "defects"}, ensure_ascii=False))
    if measured["gate_status"] == "unmeasured":
        for reason in measured["reasons"]:
            print(reason, file=sys.stderr)
        return 3
    for defect in measured["defects"]:
        print(defect, file=sys.stderr)
    return 1 if measured["defects"] else 0


if __name__ == "__main__":
    raise SystemExit(_main())
