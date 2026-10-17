"""T338's gate: `send/` holds the whole sendable set, not only the approved Markdown.

`send_folders_missing_a_sendable_document` counts, over constructed candidates, the
staged `send/` folders that lack any of the four files a delivery needs, or hold one
that is wrong:

* `<First>-<Last>-CV.pdf` and `<First>-<Last>-Cover-Letter.pdf`, named from the
  display name in `identity.json`;
* `<First>-<Last>-Application.pdf`, the two joined with the **letter first**;
* `Cover-Letter.txt`, the letter as text with no Markdown markers left.

The expected names below are written out literally per candidate rather than derived
by `send_set.derived_names`: a bound computed from the code it bounds cannot fail. The
engine is `send_set.fixture_renderer`, so the reading does not depend on whether the
optional PDF extra is installed on the machine that runs it.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

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
from integral.send_set import fixture_renderer, letter_text

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T338.json"

# (display name, handle, the stem its files must carry) — the stem is stated, not derived.
CANDIDATES = (
    ("Ada Lovelace", "ada", "Ada-Lovelace"),
    ("Núria Ferrer i Puig", "nuria", "Nuria-Puig"),
    ("Cher", "cher", "Cher"),
)
# floor on the folders examined: a zero-length scan must not read as a clean zero
# The population is CANDIDATES, three constructed candidates; dropping one breaches it.
# arsenal-floor-margin: MINIMUM_FOLDERS value=3
MINIMUM_FOLDERS = 3
# The generated letter is plain prose, so no staged folder reaches the marker stripping.
# This text does, and its stripped form is stated, not computed.
_MARKED_LETTER = "# Dear team\n\nI **led** the move.\n\n- one\n* two\n"
_PLAIN_LETTER = "Dear team\n\nI led the move.\n\n- one\n- two\n"

_PAGE_SEPARATOR = b"\n%%PAGE\n"
_HEADER = b"%PDF-fixture\n"


def _folder_defects(display: str, handle: str, stem: str, root: Path) -> tuple[bool, list[str]]:
    """`(examined, defects)`: whether staging produced a folder to read, and what was wrong."""
    identity = create_profile(root, display, handle=handle, language="en")
    store = ProfileStore(root, identity.handle)
    master = _probe_master()
    write_master(store, master)
    payload = _probe_prepare(store, master, (0,))
    try:
        folder = stage_send(
            store,
            master,
            _PROBE_OFFER,
            payload.version,
            confirms=payload_digest(read_payload(store, _PROBE_OFFER, payload.version)),
            renderer=fixture_renderer,
        )
    except ApprovalError as exc:
        return False, [f"{handle}: staging refused: {exc}"]
    found: list[str] = []
    wanted = (f"{stem}-CV.pdf", f"{stem}-Cover-Letter.pdf", f"{stem}-Application.pdf")
    for name in (*wanted, "Cover-Letter.txt"):
        if not (folder / name).is_file():
            found.append(f"{handle}: {name} is missing from send/")
    if found:
        return True, found
    cv = (folder / wanted[0]).read_bytes().removeprefix(_HEADER)
    letter_pdf = (folder / wanted[1]).read_bytes().removeprefix(_HEADER)
    if (folder / wanted[2]).read_bytes() != _HEADER + letter_pdf + _PAGE_SEPARATOR + cv:
        found.append(f"{handle}: the combined PDF is not the letter followed by the CV")
    text = (folder / "Cover-Letter.txt").read_text(encoding="utf-8")
    if "**" in text or any(line.startswith("#") for line in text.splitlines()):
        found.append(f"{handle}: Cover-Letter.txt still carries Markdown markers")
    if (folder / "cv.pdf").exists():
        found.append(f"{handle}: a file named cv.pdf is in send/")
    found.extend(f"{handle}: {d}" for d in verify_send(store, _PROBE_OFFER, payload.version))
    return True, found


def measure() -> dict[str, Any]:
    """`send_folders_missing_a_sendable_document` over the constructed candidates."""
    defects: list[str] = []
    bad = examined = 0
    if letter_text(_MARKED_LETTER) != _PLAIN_LETTER:
        defects.append("letter_text left Markdown markers in, or changed the wording")
        bad += 1
    with tempfile.TemporaryDirectory() as scratch:
        for display, handle, stem in CANDIDATES:
            read, found = _folder_defects(display, handle, stem, Path(scratch) / handle)
            examined += read
            bad += bool(found)
            defects.extend(found)
    if examined < MINIMUM_FOLDERS:
        return {
            "send_folders_missing_a_sendable_document": -1,
            "gate_status": "unmeasured",
            "reasons": [f"{examined} send folders examined; the floor is {MINIMUM_FOLDERS}"],
        }
    return {
        "send_folders_missing_a_sendable_document": bad,
        "send_folders_examined_at_least": MINIMUM_FOLDERS,
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
