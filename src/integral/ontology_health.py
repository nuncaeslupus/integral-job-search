"""T17 — `ontology_hit_rate`: how much of what the adverts say the model covers.

`mapped ÷ (mapped + unmapped)` over the concepts an advert-reading pass stated
(`docs/METHODS.md`). It doubles as the **staleness signal**: a sustained drop
means the market moved and the dimension model needs new questions
(`status/specification.md` §5.3).

Two things make it honest, and both live here rather than in a reviewer's head.

**Nothing is discarded on the way to the ratio.** `concepts_read` is counted from
the source's own entries and the buckets are counted from the classifier, so a
reader that quietly filters out what it cannot name makes the two disagree and
`discarded_concepts` goes non-zero. That is the gate, because the failure the
metric exists to catch is a silent drop — not a low ratio.

**A source that cannot report an unmapped concept produces no number at all.**
`corpus/labelled/suggestions.json` was read by a pass handed the dimension list
and asked to fill it in, so its unmapped count is 0 by construction and a hit
rate of 1.0 from it would measure how the pass was briefed. D-2's third outcome
applies: `ontology_hit_rate: null` beside `ontology_status: "unmeasured"`, which
is not a pass and not a fail. The threshold half is T57, which waits for a read
pass over a corpus wide enough to fall outside the model (T25, T26 — and D-19,
which already found 0 of 25 dimensions settling on a construction ad).

A source declares the capability by carrying a top-level `unmapped` key. It is
declared rather than inferred because "this file happens to contain no unmapped
concept" and "this file could not have recorded one" are the two states the
metric must never confuse.

Candidate-side `extractions/<offer_id>.json` is the other source of
`unmapped_concepts`, and it is deliberately not read: it lives under
`INTEGRAL_HOME`, not in the repository, and a committed evidence file must not be
a function of one machine's candidate data.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from integral.dimensions import DEFAULT_DIMENSIONS_DIR, Dimension, load_dimensions

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SUGGESTIONS_PATH = _REPO_ROOT / "corpus" / "labelled" / "suggestions.json"
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T17.json"


class OntologyHealthError(Exception):
    """Raised when a concept source cannot be read at all."""


class ConceptSource(BaseModel):
    """One file's worth of stated concepts, already split into the two buckets."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    concepts_read: int
    mapped: list[str]
    unmapped: list[str]
    unmapped_capable: bool


def known_dimension_ids(dimensions: list[Dimension]) -> set[str]:
    return {dimension.id for dimension in dimensions}


def read_suggestions(path: Path, known: set[str]) -> ConceptSource:
    """The corpus read pass as a concept source.

    An entry naming no dimension is **unmapped, not skipped**: the reader found
    something in the advert and had nowhere to put it, which is precisely the
    event the metric counts. It is identified by its quote so the review this
    task exists to feed has the advert's own words to read.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:  # pragma: no cover - a missing corpus is not this gate's
        raise OntologyHealthError(f"{path}: no concept source to read") from exc

    entries = [entry for suggestions in payload["by_ad"].values() for entry in suggestions]
    mapped: list[str] = []
    unmapped: list[str] = []
    for entry in entries:
        dimension = entry.get("dimension")
        if dimension in known:
            mapped.append(dimension)
        else:
            unmapped.append(dimension or entry.get("quote", "<unquoted>"))
    return ConceptSource(
        name=str(path.relative_to(_REPO_ROOT)) if path.is_relative_to(_REPO_ROOT) else path.name,
        concepts_read=len(entries),
        # Occurrences, not distinct names: the ratio weights a concept by how
        # often the adverts say it, which is what makes a drop a market signal
        # rather than a vocabulary edit.
        mapped=sorted(mapped),
        unmapped=sorted(unmapped),
        unmapped_capable="unmapped" in payload,
    )


def tally(sources: list[ConceptSource]) -> dict[str, Any]:
    """Add the sources up, and refuse the ratio when no source could contradict it."""
    read = sum(source.concepts_read for source in sources)
    mapped = sum(len(source.mapped) for source in sources)
    unmapped = sum(len(source.unmapped) for source in sources)
    capable = [source for source in sources if source.unmapped_capable]

    measurable = bool(capable) and mapped + unmapped > 0
    return {
        "ontology_hit_rate": round(mapped / (mapped + unmapped), 4) if measurable else None,
        "ontology_status": "measured" if measurable else "unmeasured",
        "concepts_read": read,
        "mapped_concepts": mapped,
        "unmapped_concepts": unmapped,
        # The staleness signal itself: what the adverts said that the model has
        # no question for. Named, because a count nobody can read is not a signal.
        "unmapped_concept_names": sorted({name for s in sources for name in s.unmapped}),
        "discarded_concepts": read - mapped - unmapped,
        "sources": [
            {
                "name": source.name,
                "concepts_read": source.concepts_read,
                "mapped": len(source.mapped),
                "unmapped": len(source.unmapped),
                "unmapped_capable": source.unmapped_capable,
            }
            for source in sources
        ],
    }


def measure(
    suggestions_path: Path = DEFAULT_SUGGESTIONS_PATH,
    dimensions_dir: Path = DEFAULT_DIMENSIONS_DIR,
) -> dict[str, Any]:
    """T17's gate over the committed sources."""
    known = known_dimension_ids(load_dimensions(dimensions_dir))
    measured = tally([read_suggestions(suggestions_path, known)])
    measured["known_dimensions"] = len(known)
    return measured


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    suggestions_path: Path = DEFAULT_SUGGESTIONS_PATH,
) -> dict[str, Any]:
    """Measure and record `status/evidence/T17.json`."""
    measured = measure(suggestions_path)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """Write T17's gate evidence.

    Exit 1 when a concept was read and then landed in neither bucket — the silent
    discard this module exists to make impossible. **Exit 0 while the rate is
    unmeasured**, for the same reason `integral.extraction` does: no source can
    yet contradict a 1.0, and that is a fact about the corpus, not a defect in
    the code. It is loud on stderr instead.
    """
    args = [arg for arg in argv[1:] if not arg.startswith("--")]
    measured = write_evidence(Path(args[0]) if args else DEFAULT_EVIDENCE_PATH)

    if measured["discarded_concepts"]:
        print(
            f"discarded_concepts: {measured['discarded_concepts']} of "
            f"{measured['concepts_read']} concepts were read and then counted in neither "
            "bucket — an unmapped concept is being dropped on the way to the ratio.",
            file=sys.stderr,
        )
        return 1

    if measured["ontology_status"] == "unmeasured":
        print(
            "ontology_hit_rate: UNMEASURED — "
            f"{measured['concepts_read']} concepts read, none from a source that declares "
            "it can report an unmapped concept, so a rate would measure how the read pass "
            "was briefed. Not a pass and not a fail (D-2); the threshold is T57.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
