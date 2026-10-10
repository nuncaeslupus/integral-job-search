"""T148: a document edit is verified by the document, not by the edit succeeding.

Two silent corruptions reached one letter in one session and neither failed
anything. An earlier edit had removed a paragraph, so ``text[4]`` and ``text[8]``
no longer meant what the caller believed and overwrote two paragraphs with
duplicates of others; and a filter written ``if b.get("text") is not None``
dropped the ``to`` block, leaving the letter addressed to nobody. The write, the
render and :func:`integral.ats.check_document` all passed, correctly: the text
layer was intact and parseable, and said the wrong thing.

**The contract.** An edit *names* the blocks it changes and every block it does
not name comes out byte-identical in the rendered text layer; the block count is
preserved unless the edit declares a change (``count_change``), and the
declaration must match the result. Two rules follow from it:

* A block is named by its index **and** by the text it currently renders
  (:attr:`Change.expect`). An index alone is exactly what went stale; if the
  block at that index no longer says what the caller expects, the edit is
  refused, so a position that moved cannot be written over.
* :func:`verify_edit` judges any ``before``/``after`` pair, including one a
  caller built by some other route (a filter, a comprehension): the check is
  over the artefact, never over the operation that made it.

The text layer here is the one :func:`integral.document_render.render` draws for
each block: tags removed, entities decoded, nothing normalised. The gate reads
HTML only (evidence must not depend on whether a PDF engine is installed).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from integral import document_render as dr

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T148.json"

#: The replays the gate must have run. A clean zero over a run that skipped one
#: of them certifies nothing, so :func:`measure` refuses (``unmeasured``) when a
#: name is missing. Closed set of names, not a count of the day.
REQUIRED_CONTRACTS = (
    "stale index is refused",
    "dropped block is refused",
    "legitimate replace is allowed",
    "legitimate removal is allowed",
    "undeclared count change is refused",
)


class EditRefused(ValueError):
    """The edit would leave a block the edit did not name changed, or lost."""


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag == "br":
            self.parts.append("\n")


def block_text(block: Mapping[str, Any], accent: str = "#000000") -> str:
    """The text a block contributes to the rendered text layer, byte for byte."""
    parser = _Text()
    parser.feed(dr._render_block(block, accent))
    parser.close()
    return "".join(parser.parts)


@dataclass(frozen=True)
class Change:
    """Name one block: ``index`` in the document being edited, and what it says now.

    ``block`` replaces it; ``None`` removes it (and so needs ``count_change``).
    """

    index: int
    expect: str
    block: Mapping[str, Any] | None


@dataclass(frozen=True)
class Insert:
    """A new block placed before the original block at ``index`` (len = append)."""

    index: int
    block: Mapping[str, Any]


def _blocks(document: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    blocks = document.get("blocks")
    if not isinstance(blocks, list):
        raise EditRefused("a document needs a list of blocks")
    return blocks


def verify_edit(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    changes: Sequence[Change] = (),
    inserts: Sequence[Insert] = (),
    *,
    count_change: int = 0,
) -> None:
    """Raise :class:`EditRefused` unless ``after`` is ``before`` plus exactly the named edit."""
    old, new = _blocks(before), _blocks(after)
    named = {c.index for c in changes}
    if len(named) != len(changes):
        raise EditRefused("a block is named twice")
    if any(not 0 <= c.index < len(old) for c in changes):
        raise EditRefused("an edit names a block the document does not have")
    if any(not 0 <= i.index <= len(old) for i in inserts):
        raise EditRefused("an insert names a position the document does not have")
    removed = sum(1 for c in changes if c.block is None)
    implied = len(inserts) - removed
    if implied != count_change:
        raise EditRefused(
            f"the edit declares a block-count change of {count_change} "
            f"but its operations make {implied}"
        )
    by_index = {c.index: c for c in changes}
    ahead: dict[int, list[Insert]] = {}
    for ins in inserts:
        ahead.setdefault(ins.index, []).append(ins)
    cursor = 0
    for position in range(len(old) + 1):
        for ins in ahead.get(position, []):
            if cursor >= len(new) or new[cursor] != ins.block:
                raise EditRefused(f"the inserted block at {position} is not the one requested")
            cursor += 1
        if position == len(old):
            break
        change = by_index.get(position)
        if change is None:
            if cursor >= len(new) or (
                block_text(new[cursor]) != block_text(old[position]) or new[cursor] != old[position]
            ):
                raise EditRefused(
                    f"block {position} was not named by the edit and no longer reads as it did"
                )
            cursor += 1
        elif change.block is not None:
            if cursor >= len(new) or new[cursor] != change.block:
                raise EditRefused(f"block {position} is not the replacement requested")
            cursor += 1
    if cursor != len(new):
        raise EditRefused(f"{len(new) - cursor} block(s) appear that the edit did not name")


def apply_edit(
    document: Mapping[str, Any],
    changes: Sequence[Change] = (),
    inserts: Sequence[Insert] = (),
    *,
    count_change: int = 0,
) -> dict[str, Any]:
    """The edited document, or :class:`EditRefused`; ``document`` is never modified."""
    old = _blocks(document)
    for c in changes:
        if not 0 <= c.index < len(old):
            raise EditRefused(f"block {c.index} does not exist")
        now = block_text(old[c.index])
        if now != c.expect:
            raise EditRefused(
                f"block {c.index} reads {now!r}, not the {c.expect!r} the edit expected: "
                "the index moved or the block changed"
            )
    by_index = {c.index: c for c in changes}
    ahead: dict[int, list[Mapping[str, Any]]] = {}
    for ins in inserts:
        ahead.setdefault(ins.index, []).append(ins.block)
    new: list[Mapping[str, Any]] = []
    for position in range(len(old) + 1):
        new.extend(ahead.get(position, []))
        if position == len(old):
            break
        change = by_index.get(position)
        if change is None:
            new.append(old[position])
        elif change.block is not None:
            new.append(change.block)
    edited = {**document, "blocks": new}
    verify_edit(document, edited, changes, inserts, count_change=count_change)
    try:
        dr.validate(edited)
    except dr.RenderError as exc:
        raise EditRefused(f"the edited document cannot be rendered: {exc}") from exc
    return edited


# --------------------------------------------------------------------------
# The gate: replay both defects, plus the edits that must be allowed.


def _letter() -> dict[str, Any]:
    return {
        "title": "Letter",
        "blocks": [
            {"type": "letter", "place": "Girona", "date": "7 September 2026"},
            {"type": "to", "lines": ["Hiring team", "Acme"]},
            {"type": "text", "text": "First paragraph."},
            {"type": "text", "text": "Second paragraph."},
            {"type": "text", "text": "The leap of faith."},
            {"type": "text", "text": "The honest gaps."},
            {"type": "sign", "closing": "Regards,", "name": "Ana Perez"},
        ],
    }


def _refused(run: Callable[[], object]) -> bool:
    try:
        run()
    except EditRefused:
        return True
    return False


def _contract_stale_index() -> list[str]:
    """Defect 1: remove a paragraph, then edit by the indexes of before the removal."""
    letter = _letter()
    gone = apply_edit(letter, [Change(2, block_text(letter["blocks"][2]), None)], count_change=-1)
    # The caller still believes 'The leap of faith.' lives at 4.
    stale = Change(4, block_text(letter["blocks"][4]), {"type": "text", "text": "Duplicate."})
    if not _refused(lambda: apply_edit(gone, [stale])):
        return ["an edit by a stale index overwrote a paragraph it did not name"]
    return []


def _contract_dropped_block() -> list[str]:
    """Defect 2: a filter that loses the ``to`` block."""
    letter = _letter()
    filtered = {
        **letter,
        "blocks": [b for b in letter["blocks"] if b.get("text") is not None],
    }
    found = []
    if not _refused(lambda: verify_edit(letter, filtered)):
        found.append("a filter that dropped the 'to' block was accepted")
    if "to" in {b["type"] for b in filtered["blocks"]}:
        found.append("the replay no longer drops the 'to' block, so it replays nothing")
    return found


def _contract_replace() -> list[str]:
    letter = _letter()
    target = Change(3, block_text(letter["blocks"][3]), {"type": "text", "text": "Better second."})
    try:
        out = apply_edit(letter, [target])
    except EditRefused as exc:
        return [f"a legitimate replace was refused: {exc}"]
    found = []
    if block_text(_blocks(out)[3]) != "Better second.":
        found.append("the replace did not land")
    for n in (0, 1, 2, 4, 5, 6):
        if block_text(_blocks(out)[n]) != block_text(letter["blocks"][n]):
            found.append(f"block {n} changed though the edit did not name it")
    return found


def _contract_removal() -> list[str]:
    letter = _letter()
    try:
        out = apply_edit(
            letter, [Change(2, block_text(letter["blocks"][2]), None)], count_change=-1
        )
    except EditRefused as exc:
        return [f"a declared removal was refused: {exc}"]
    return [] if len(_blocks(out)) == len(letter["blocks"]) - 1 else ["the removal did not land"]


def _contract_undeclared_count() -> list[str]:
    letter = _letter()
    found = []
    if not _refused(lambda: apply_edit(letter, [Change(2, block_text(letter["blocks"][2]), None)])):
        found.append("a removal with no declared count change was accepted")
    if not _refused(lambda: apply_edit(letter, [], [Insert(1, {"type": "text", "text": "x"})])):
        found.append("an insert with no declared count change was accepted")
    return found


_CONTRACTS: dict[str, Callable[[], list[str]]] = {
    "stale index is refused": _contract_stale_index,
    "dropped block is refused": _contract_dropped_block,
    "legitimate replace is allowed": _contract_replace,
    "legitimate removal is allowed": _contract_removal,
    "undeclared count change is refused": _contract_undeclared_count,
}


def measure() -> dict[str, Any]:
    """T148's gate reading: ``document_edit_defects`` over the replayed contracts."""
    defects: list[str] = []
    ran: list[str] = []
    for name, contract in _CONTRACTS.items():
        ran.append(name)
        defects.extend(f"{name}: {d}" for d in contract())
    if missing := [n for n in REQUIRED_CONTRACTS if n not in ran]:
        return {
            "document_edit_defects": -1,
            "gate_status": "unmeasured",
            "reasons": [f"contract(s) never run: {missing}"],
        }
    return {
        "document_edit_defects": len(defects),
        "contracts_run": sorted(ran),
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
