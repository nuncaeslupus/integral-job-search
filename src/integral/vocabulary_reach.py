"""D-19's gate: a step whose vocabulary settled nothing cannot report understanding.

Found during the test session of 2026-08-20, with a Barcelona construction worker
as the candidate. `extraction.extract()` settled **0 of 25** dimensions on all
seven adverts — `dimensions/` is entirely software-sector — so step 8 wrote a file
per offer, every dimension listed under `unsettled`, and reported coverage met.
Step 9 then ranked by hand, which its own skill forbids.

The decision D-19 asked for was between widening the model per sector and refusing
honestly when no dimension applies. Widening by a corpus sweep was retired by the
owner on 2026-08-19 — dimensions are coined when a live session turns one up — so
this is the refusal, and `VOCABULARY_SILENT` is what carries it.

**The refusal must not depend on the acceptance gate.** Step 8's gate
(`extraction_macro_f1 >= 0.75`, owned by T56) is `not_implemented`, so D-21 already
keeps that checkpoint off 0 — but for an unrelated reason, and only by accident.
The day T56 builds the gate, D-21 stops covering this and a silent vocabulary would
certify. Claim 2 below is that independence, asserted rather than assumed.

The gate is the name `status/plan.md` settled for it —
`markets_with_no_applicable_dimension_reported_as_extracted == 0` — and it counts two
things that would each let a market be reported as understood when it was not:

1. **Markets the model does not reach, that the step would still report as extracted.**
   Reach is measured per `job_family` over the committed corpus, which carries seven
   of them including `trades`.
2. **Claims about the refusal that do not hold.** These count even when no market
   currently needs the refusal — otherwise the metric is a clean zero resting on the
   corpus happening to be covered, and would go on reading zero after the refusal
   broke. That is the failure mode D-21 was filed for, one level up.

A claim that cannot be evaluated counts rather than being skipped: a measurement that
drops its hard cases is the clean zero this repository keeps finding in its own history.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from integral.corpus import load_ads
from integral.dimensions import DEFAULT_DIMENSIONS_DIR, load_dimensions
from integral.extraction import NormalisedAd, rules_stage
from integral.identity import ProfileStore
from integral.step_gates import UNCERTIFIABLE, VOCABULARY_SILENT, checkpoint_exit
from integral.step_runtime import ProfileView, settled_extractions

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "D-19.json"
CHECKPOINT_SCRIPT = (
    _REPO_ROOT / ".claude" / "skills" / "step-08-understanding" / "scripts" / "run_checkpoint.py"
)
#: The key the checkpoint must compute for the shared decision to see it at all.
DECISION_KEY = "vocabulary_settled"


def _met(runnable: bool, coverage: bool, certifiable: bool, **extra: Any) -> dict[str, Any]:
    return {
        "runnable": runnable,
        "coverage_met": coverage,
        "certifiable": certifiable,
        **extra,
    }


def _claim_silent_is_refused_when_the_gate_is_built() -> str | None:
    code = checkpoint_exit(_met(True, True, True, vocabulary_settled=False))
    if code != VOCABULARY_SILENT:
        return f"a silent vocabulary with a built gate exited {code}, not {VOCABULARY_SILENT}"
    return None


def _claim_the_refusal_does_not_depend_on_the_gate() -> str | None:
    code = checkpoint_exit(_met(True, True, False, vocabulary_settled=False))
    if code != VOCABULARY_SILENT:
        return (
            f"a silent vocabulary with an unbuilt gate exited {code}, not {VOCABULARY_SILENT} — "
            "the refusal is riding on D-21 rather than standing on its own"
        )
    return None


def _claim_a_reaching_vocabulary_still_passes() -> str | None:
    code = checkpoint_exit(_met(True, True, True, vocabulary_settled=True))
    if code != 0:
        return f"a vocabulary that settled a dimension exited {code}, not 0"
    return None


def _claim_a_step_that_never_ran_is_untouched() -> str | None:
    # `None` is "there is nothing to judge yet", and must fall through to D-21's
    # answer rather than being read as a refusal.
    code = checkpoint_exit(_met(True, True, False, vocabulary_settled=None))
    if code != UNCERTIFIABLE:
        return f"an unrun step exited {code}, not {UNCERTIFIABLE} — `None` is being read as False"
    return None


def _claim_settled_extractions_reads_the_real_shape() -> str | None:
    with tempfile.TemporaryDirectory() as tmp:
        store = ProfileStore(Path(tmp), "probe")
        store.write_json({"handle": "probe"}, "identity.json")
        # Exactly what D-19 saw: a file per offer, every dimension unsettled.
        store.write_json(
            {"offer_id": "silent", "language": "es", "scores": [], "unsettled": ["on_call_load"]},
            "extractions",
            "silent.json",
        )
        view = ProfileView(store)
        settled, read = settled_extractions(view)
        if (settled, read) != (0, 1):
            return f"a wholly unsettled extraction read as {(settled, read)}, not (0, 1)"

        store.write_json(
            {
                "offer_id": "reaching",
                "language": "es",
                "scores": [{"dimension": "on_call_load", "value": 0.6}],
                "unsettled": [],
            },
            "extractions",
            "reaching.json",
        )
        settled, read = settled_extractions(ProfileView(store))
        if (settled, read) != (1, 2):
            return f"one settling extraction of two read as {(settled, read)}, not (1, 2)"
    return None


def _claim_the_checkpoint_computes_the_key() -> str | None:
    """Static: step 8's checkpoint must put `vocabulary_settled` in the payload it returns.

    The decision function can only refuse over a key somebody computed, so a
    correct `checkpoint_exit` and a checkpoint that never sets it would measure
    a refusal that never fires — which is the shape of every clean zero D-21
    found. Read from the source rather than by running it, because running it
    needs a whole candidate tree and would test the fixture as much as the code.
    """
    try:
        tree = ast.parse(CHECKPOINT_SCRIPT.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        return f"{CHECKPOINT_SCRIPT.name} could not be read: {exc}"

    # The key must appear as a **dict key inside `checkpoint()`**, not merely
    # somewhere in the file. Matching any string constant would be satisfied by
    # the word in a docstring, so the claim would hold over a checkpoint that
    # never computes it — a check that cannot fail, which is the exact defect
    # this module exists to refuse.
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "checkpoint":
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Dict) and any(
                isinstance(key, ast.Constant) and key.value == DECISION_KEY
                for key in inner.keys
                if key is not None
            ):
                return None
        return f"{CHECKPOINT_SCRIPT.name}: checkpoint() builds no {DECISION_KEY!r} key"
    return f"{CHECKPOINT_SCRIPT.name} has no checkpoint() to read"


CLAIMS = {
    "silent_is_refused_when_the_gate_is_built": _claim_silent_is_refused_when_the_gate_is_built,
    "the_refusal_does_not_depend_on_the_gate": _claim_the_refusal_does_not_depend_on_the_gate,
    "a_reaching_vocabulary_still_passes": _claim_a_reaching_vocabulary_still_passes,
    "a_step_that_never_ran_is_untouched": _claim_a_step_that_never_ran_is_untouched,
    "settled_extractions_reads_the_real_shape": _claim_settled_extractions_reads_the_real_shape,
    "the_checkpoint_computes_the_key": _claim_the_checkpoint_computes_the_key,
}


def market_reach() -> dict[str, dict[str, int]]:
    """Per `job_family`, how far the committed dimension model reaches into it.

    The rules stage alone, deliberately: stage 3 asks a model for whatever the
    cues left unsettled, so counting it would measure the model's willingness to
    answer rather than whether this vocabulary has any words for this trade. D-19
    is about the words.
    """
    dimensions = load_dimensions(DEFAULT_DIMENSIONS_DIR)
    reach: dict[str, dict[str, Any]] = {}
    for ad in load_ads():
        family = str(ad.get("job_family") or "unknown")
        scores = rules_stage(
            NormalisedAd(offer_id=str(ad["id"]), language=ad["language"], text=ad["text"]),
            dimensions,
        )
        row = reach.setdefault(family, {"ads": 0, "ads_reached": 0, "dimensions": set()})
        row["ads"] += 1
        if scores:
            row["ads_reached"] += 1
        row["dimensions"].update(score.dimension for score in scores)
    return {
        family: {
            "ads": row["ads"],
            "ads_reached": row["ads_reached"],
            "applicable_dimensions": len(row["dimensions"]),
        }
        for family, row in sorted(reach.items())
    }


def _reported_as_extracted_despite_no_reach(families: list[str]) -> list[str]:
    """Of the markets the model cannot reach, those the step would still report as read."""
    silent = _met(True, True, True, vocabulary_settled=False)
    return [] if checkpoint_exit(silent) == VOCABULARY_SILENT else list(families)


def measure() -> dict[str, Any]:
    """D-19's gate reading, as it is written to evidence."""
    shortfalls = []
    for name, claim in CLAIMS.items():
        try:
            reason = claim()
        except Exception as exc:  # a claim that crashed is a claim that did not hold
            reason = f"the claim could not be evaluated: {exc!r}"
        if reason:
            shortfalls.append({"claim": name, "reason": reason})

    try:
        reach = market_reach()
    except Exception as exc:
        reach = {}
        shortfalls.append({"claim": "market_reach", "reason": f"reach could not be read: {exc!r}"})
    unreached = [family for family, row in reach.items() if row["applicable_dimensions"] == 0]
    reported = _reported_as_extracted_despite_no_reach(unreached)

    return {
        "markets_with_no_applicable_dimension_reported_as_extracted": len(reported)
        + len(shortfalls),
        "markets_measured": len(reach),
        "markets_with_no_applicable_dimension": unreached,
        "market_reach": reach,
        "claims_checked": len(CLAIMS),
        "vocabulary_silent_exit_code": VOCABULARY_SILENT,
        "shortfalls": shortfalls,
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", nargs="?", default=DEFAULT_EVIDENCE_PATH, type=Path)
    args = parser.parse_args(argv[1:])

    measured = write_evidence(args.evidence)
    print(json.dumps(measured, ensure_ascii=False))
    for shortfall in measured["shortfalls"]:
        print(f"{shortfall['claim']}: {shortfall['reason']}", file=sys.stderr)
    return 1 if measured["markets_with_no_applicable_dimension_reported_as_extracted"] else 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
