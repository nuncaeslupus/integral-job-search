"""T180: the candidate writes the letter first, and the package records who wrote each paragraph.

Step 11 edits the candidate's own letter and never composes one. Two mechanical
halves are checkable, and this module is both of them:

* ``harvest_draft`` appends every sentence of the candidate's draft to
  ``profile/evidence.jsonl`` as ``kind="candidate_statement"``,
  ``source="application_draft"`` — the draft is the densest ground truth the
  process gets, so it is recorded in the pass that reads it.
* ``check_authorship`` reads ``carta.md`` and the ``## Authorship`` table of
  ``trazabilidad.md`` and fails unless **every** paragraph of the letter has
  exactly one row naming its author from a closed set, and every row that
  claims the candidate's words cites live ``candidate_statement`` evidence.

The rule is closed rather than enumerated: the set of paragraphs is *derived
from the letter*, so a paragraph added later is demanded a row without anyone
remembering to list it. Whether the letter reads aloud without flinching is not
checkable here and this module does not claim it is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from integral.identity import ProfileStore
from integral.profile import EvidenceLog

AUTHORS = ("candidate", "edited", "assistant")
# The trace of a version's documents, not a document (prior_documents skips it by this name).
TRACE_FILE = "trazabilidad.md"
SECTION = "## Authorship"
# A change cell must name a change. These say there is none, in the languages the
# candidates write in; anything else with a word in it is taken as a name.
NO_CHANGE = frozenset(
    {"none", "na", "n a", "nil", "nothing", "no change", "no changes", "ninguno", "cap"}
)
# An `edited` paragraph is the candidate's sentence with changes, so it must still
# contain most of what it cites; below this share it is a different sentence.
EDITED_KEEPS = 0.5
_WORD = re.compile(r"[^\W\d_]+")
_EVIDENCE_ID = re.compile(r"ev-\d{6,}")
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")
_CELL_SPLIT = re.compile(r"(?<!\\)\|")


class AuthorshipError(ValueError):
    """A draft that cannot be harvested."""


def letter_paragraphs(letter_md: str) -> list[str]:
    """The letter's paragraphs: every non-blank, blank-line separated block.

    Headings are not exempt. A heading is text somebody wrote about the candidate,
    so it needs an author like any sentence; ``check_authorship`` refuses the letter
    that has one instead, because the candidate's letter has none to preserve.
    """
    blocks = re.split(r"\n[ \t]*\n", letter_md.replace("\r\n", "\n"))
    return [block.strip() for block in blocks if block.strip()]


def draft_sentences(draft: str) -> list[str]:
    """Each sentence of the candidate's draft, in order, whitespace collapsed."""
    sentences = []
    for block in re.split(r"\n[ \t]*\n", draft.replace("\r\n", "\n")):
        for part in _SENTENCE_END.split(" ".join(block.split())):
            if part.strip():
                sentences.append(part.strip())
    return sentences


def harvest_draft(store: ProfileStore, draft: str, *, recorded_at: str) -> list[str]:
    """Append the draft's sentences as ``candidate_statement`` rows; return their ids.

    Idempotent: a sentence already live in the log from a draft is returned, not
    appended again, so re-reading a draft after a revision adds only what is new.
    """
    sentences = draft_sentences(draft)
    if not sentences:
        raise AuthorshipError("the candidate's draft has no sentences to harvest")
    log = EvidenceLog(store)
    suppressed = log.suppressed_ids()
    known = {
        row.text: row.id
        for row in log.rows()
        if row.kind == "candidate_statement"
        and row.source == "application_draft"
        and row.id not in suppressed
    }
    ids = []
    for sentence in sentences:
        if sentence in known:
            ids.append(known[sentence])
            continue
        row = log.append(
            recorded_at=recorded_at,
            step="application",
            kind="candidate_statement",
            text=sentence,
            source="application_draft",
        )
        known[sentence] = row.id
        ids.append(row.id)
    return ids


@dataclass(frozen=True)
class AuthorshipReport:
    paragraphs: int
    rows: int
    defects: tuple[str, ...] = field(default_factory=tuple)

    @property
    def paragraphs_with_no_named_author(self) -> int:
        return len(self.defects)

    @property
    def ok(self) -> bool:
        return not self.defects


def _table_rows(trazabilidad_md: str) -> list[list[str]]:
    lines = trazabilidad_md.replace("\r\n", "\n").splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.strip() == SECTION), None)
    if start is None:
        return []
    rows: list[list[str]] = []
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if stripped.startswith("#"):
            break
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in _CELL_SPLIT.split(stripped.strip("|"))]
        if all(re.fullmatch(r":?-{3,}:?", c) for c in cells if c) and any(cells):
            if rows:
                rows.pop()  # the row above a separator is the header, not a paragraph's
            continue
        rows.append(cells)
    return rows


def _squash(text: str) -> str:
    return " ".join(text.split())


def _names_a_change(cell: str) -> bool:
    words = [w.casefold() for w in _WORD.findall(cell)]
    return bool(words) and " ".join(words) not in NO_CHANGE


def _shared(cited: str, paragraph: str) -> float:
    """The share of the cited sentence's words that the paragraph still contains."""
    want = [w.casefold() for w in _WORD.findall(cited)]
    have = {w.casefold() for w in _WORD.findall(paragraph)}
    return sum(w in have for w in want) / len(want) if want else 0.0


def check_authorship(
    letter_md: str, trazabilidad_md: str, evidence: EvidenceLog | None
) -> AuthorshipReport:
    """Fail unless every letter paragraph has one row, an author, and a resolvable source.

    Row format: ``| <paragraph number, from 1> | <author> | <evidence ids> | <changes> |``.
    ``candidate`` and ``edited`` must cite live ``candidate_statement`` rows from an
    application draft; ``edited`` must also name its changes; ``assistant`` must cite
    nothing (a sentence the candidate did not say cannot borrow a source).
    """
    paragraphs = letter_paragraphs(letter_md)
    rows = _table_rows(trazabilidad_md)
    defects: list[str] = []
    by_number: dict[int, list[list[str]]] = {}
    for cells in rows:
        head = cells[0] if cells else ""
        if not re.fullmatch(r"[0-9]+", head):
            defects.append(f"row {cells!r} does not start with a paragraph number")
            continue
        by_number.setdefault(int(head), []).append(cells)
    live: dict[str, tuple[str, str]] = {}
    if evidence is not None:
        gone = evidence.suppressed_ids()
        live = {
            r.id: (r.source, r.text)
            for r in evidence.rows()
            if r.kind == "candidate_statement" and r.id not in gone
        }
    for n in range(1, len(paragraphs) + 1):
        found = by_number.get(n, [])
        if len(found) != 1:
            defects.append(f"paragraph {n}: {len(found)} authorship rows, need exactly 1")
            continue
        cells = found[0] + [""] * 4
        author, source, changes = cells[1].lower(), cells[2], cells[3]
        ids = _EVIDENCE_ID.findall(source)
        if author not in AUTHORS:
            defects.append(f"paragraph {n}: author {cells[1]!r} is not one of {AUTHORS}")
        elif author == "assistant":
            if source.strip():
                defects.append(f"paragraph {n}: an assistant paragraph cannot cite a source")
        else:
            if not ids:
                defects.append(f"paragraph {n}: {author} but no candidate source named")
            for ev in ids:
                if live.get(ev, ("", ""))[0] != "application_draft":
                    defects.append(f"paragraph {n}: {ev} is not a live candidate draft statement")
            cited = [live[ev][1] for ev in ids if ev in live]
            body = _squash(paragraphs[n - 1])
            if author == "candidate" and cited and body != _squash(" ".join(cited)):
                defects.append(
                    f"paragraph {n}: candidate, but it is not exactly the cited sentences"
                )
            if author == "edited":
                if not _names_a_change(changes):
                    defects.append(f"paragraph {n}: edited but no change named")
                for ev in ids:
                    if ev in live and _shared(live[ev][1], body) < EDITED_KEEPS:
                        defects.append(f"paragraph {n}: edited, but {ev} is not in it")
    defects += [
        f"carta.md line {line!r} is a heading; the candidate's letter has none"
        for line in letter_md.splitlines()
        if line.lstrip().startswith("#")
    ]
    extra = sorted(set(by_number) - set(range(1, len(paragraphs) + 1)))
    defects += [f"authorship row for paragraph {n}, which the letter does not have" for n in extra]
    if not paragraphs:
        defects.append("the letter has no paragraphs")
    return AuthorshipReport(len(paragraphs), len(rows), tuple(defects))


def check_package(version_dir: Path, store: ProfileStore) -> AuthorshipReport:
    """``check_authorship`` over one ``cv/generated/<offer_id>/v<N>/`` directory."""
    return check_authorship(
        (version_dir / "carta.md").read_text(encoding="utf-8"),
        (version_dir / TRACE_FILE).read_text(encoding="utf-8"),
        EvidenceLog(store),
    )
