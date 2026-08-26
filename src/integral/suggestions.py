"""Pre-marked spans a labeller reacts to, and the check that they are not the
extractor's own output (T5 fast path, D-2).

Labelling 100 ads against 22 dimensions offers a person 2,200 decisions when the
real answer per ad is a handful. Pre-marking inverts that: the ad arrives with
spans already highlighted and a rung already proposed, and the labeller confirms,
corrects or deletes. That is the whole speed-up, and it comes with one specific
way to be worthless.

**The suggestions must not come from `Dimension.extraction.cues`.**
`extraction_macro_f1` (T15) is measured against the labels this process
produces. If a labeller confirms what the cue regexes proposed, the corpus
becomes a transcript of the extractor, and the gate then measures the extractor
against itself — passing near 1.0 whatever the extractor is actually worth. This
is D-2 in `status/plan.md`, and it is why `tools/labelling_page.py` has never
pre-filled a value from a cue hit.

A `method` field could assert independence, and could equally be wrong — either
by a mistake upstream or by a later regeneration that quietly changed source. So
this module measures instead of asserting: `cue_agreement` reports what fraction
of the suggestions the cues would have produced anyway. A set claiming
`llm_read` whose agreement is near 1.0 is behaviourally cue output no matter
what it calls itself, and `probe_suggestions` records the number where it can be
reviewed.

The second instrument is `blind_control`: ads deliberately shipped with *no*
suggestions, labelled cold. Confirm rate on suggested ads can then be compared
with agreement on ads the labeller never saw a suggestion for. Without it,
"the labeller agreed with 92% of suggestions" has no baseline and cannot
distinguish good suggestions from rubber-stamping.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from integral.dimensions import (
    DEFAULT_DIMENSIONS_DIR,
    SNAKE_CASE,
    Dimension,
    load_dimensions,
)
from integral.harness import LabelledAd, load_store, split_rank

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SUGGESTIONS_PATH = _REPO_ROOT / "corpus" / "labelled" / "suggestions.json"
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T5-suggestions.json"

# Share of ads shipped with no suggestions at all, so a confirm rate has a
# baseline to be read against. Small enough not to give back the speed-up the
# suggestions bought, large enough to carry every language.
BLIND_CONTROL_SHARE = 0.15

# How the spans were proposed. `cue` is nameable on purpose — a set generated
# from the extraction regexes is a legitimate thing to build for debugging the
# extractor, and naming it honestly is better than having no word for it. What
# it is not is a source of gold: `validate_suggestions` refuses a `cue` set the
# moment it covers an ad in the evaluation split, which is the half
# `extraction_macro_f1` is measured on.
Method = Literal["llm_read", "cue"]


class SuggestionError(Exception):
    """The suggestions file does not satisfy its contract."""


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Suggestion(Strict):
    """One concept the reader found in the ad — mapped to a dimension, or not.

    `quote` rather than offsets, for the same reason `harness import` takes a
    quote: an offset typed or computed against a slightly different copy of the
    text points at the wrong words while still validating, and a verbatim quote
    either locates or is refused.

    **`dimension` is optional, and that is the whole of T57.** A reader that can
    only record what the dimension list already holds reports an unmapped count
    of 0 by construction, and `ontology_hit_rate` computed from it measures the
    briefing rather than the market. So an entry may name a concept and leave
    `dimension` null; `note` then carries what the reader called it, and
    `ontology_health.read_suggestions` counts it as **unmapped, not skipped**.
    `value` is null there too: a rung on no dimension is not a reading of
    anything.
    """

    dimension: str | None = None
    value: float | None = Field(default=None, ge=-1.0, le=1.0)
    quote: str = Field(min_length=1)
    negated: bool = False
    confidence: Literal["high", "medium", "low"] = "medium"
    note: str = ""


class SuggestionSet(Strict):
    """Every ad's proposed labels, plus the control ads left deliberately bare."""

    method: Method
    generated_at: str = Field(min_length=1)
    note: str = ""
    blind_control: list[str] = Field(default_factory=list)
    by_ad: dict[str, list[Suggestion]] = Field(default_factory=dict)
    # The **capability declaration** T57 turns into a measurement, and a roll-up
    # of the concept names behind it. `ontology_health` counts the unmapped
    # entries in `by_ad` and reads nothing here — what this key does is separate
    # "this file happens to contain no unmapped concept" from "this file could
    # not have recorded one", which are the two states the metric must never
    # confuse. It is a list rather than a bool so the staleness signal is
    # readable as names, not as a count nobody can interpret — and it defaults to
    # `None`, not `[]`, because a default of `[]` would collapse those two states
    # back together for any file written before the key existed.
    unmapped: list[str] | None = None

    def for_ad(self, ad_id: str) -> list[Suggestion]:
        return self.by_ad.get(ad_id, [])


def blind_control(ads: list[LabelledAd], share: float = BLIND_CONTROL_SHARE) -> list[str]:
    """Pick the control ads: stratified by language, stable, derived from the id.

    Stratified for the reason `assign_splits` is: a flat hash threshold over a
    15-ad Catalan slice lands badly, and a control set that happens to hold no
    Catalan ad cannot tell you anything about labelling Catalan cold. Derived
    from the id so that regenerating the suggestions never moves an ad in or out
    of the control set — an ad that was labelled blind and later gets a
    suggestion has already given up the only thing it was for.
    """
    chosen: list[str] = []
    for language in sorted({ad.language for ad in ads}):
        slice_ids = sorted(ad.id for ad in ads if ad.language == language)
        count = math.ceil(len(slice_ids) * share)
        chosen.extend(sorted(slice_ids, key=split_rank)[:count])
    return sorted(chosen)


def validate_suggestions(
    suggestions: SuggestionSet,
    store: list[LabelledAd],
    dimensions: list[Dimension],
) -> list[str]:
    """Everything wrong with the set, as reviewable strings. Never raises.

    Reports rather than raising because the caller is a gate that has to record
    a number: a validator that crashes on the first problem records nothing and
    hides the other twelve.
    """
    problems: list[str] = []
    by_id = {ad.id: ad for ad in store}
    by_dimension = {dimension.id: dimension for dimension in dimensions}

    # The declared control set must BE the computed cohort, not merely a subset
    # of real ad ids. Checking only what the file happens to list lets an empty
    # `blind_control` pass with zero violations — a clean result over nothing,
    # which is the one outcome a gate in this repository may never produce. The
    # blind baseline is the whole reason a confirm rate means anything, so an
    # undersized cohort silently removes the comparison while the probe still
    # reports success.
    expected = set(blind_control(store))
    declared = set(suggestions.blind_control)
    for ad_id in sorted(expected - declared):
        problems.append(
            f"{ad_id} belongs to the blind-control cohort but is not declared — "
            "a confirm rate has no baseline to be read against without it"
        )
    for ad_id in sorted(declared - expected):
        problems.append(
            f"{ad_id} is declared blind-control but is not in the computed cohort — "
            "the cohort is derived from the ad id so it stays stable across regeneration"
        )

    for ad_id in sorted(suggestions.blind_control):
        if ad_id not in by_id:
            problems.append(f"blind_control names {ad_id!r}, which is not in the store")
        if suggestions.for_ad(ad_id):
            problems.append(
                f"{ad_id} is in blind_control but carries suggestions — a control ad "
                "labelled against a suggestion is no longer a baseline"
            )

    for ad_id, proposed in sorted(suggestions.by_ad.items()):
        ad = by_id.get(ad_id)
        if ad is None:
            problems.append(f"suggestions for {ad_id!r}, which is not in the store")
            continue
        if suggestions.method == "cue" and ad.split == "evaluation":
            problems.append(
                f"{ad_id}: a cue-derived suggestion on an evaluation-split ad — "
                "extraction_macro_f1 is measured on this half and would be scoring "
                "the extractor against its own output (D-2)"
            )
        for index, suggestion in enumerate(proposed):
            where = f"{ad_id}[{index}] {suggestion.dimension or suggestion.note or '<unnamed>'}"
            # An entry with no dimension is the deliberate one T57 needs, so it
            # is checked for what it *must* carry rather than reported as an
            # unknown dimension. `note` is required there because an unmapped
            # concept nobody named is not a staleness signal, it is a gap in
            # the file; and a rung on no dimension is not a reading of anything.
            if suggestion.dimension is None:
                if not suggestion.note.strip():
                    problems.append(f"{where}: unmapped entry with no note naming the concept")
                if suggestion.value is not None:
                    problems.append(f"{where}: unmapped entry carries a rung value")
            elif (dimension := by_dimension.get(suggestion.dimension)) is None:
                problems.append(f"{where}: unknown dimension")
                continue
            elif suggestion.value is None:
                problems.append(f"{where}: mapped entry with no rung value")
            elif dimension.level_for(suggestion.value) is None:
                rungs = sorted(level.value for level in dimension.levels)
                problems.append(f"{where}: value {suggestion.value} is not a rung {rungs}")
            occurrences = ad.text.count(suggestion.quote)
            if occurrences == 0:
                problems.append(f"{where}: quote does not appear in the ad text")
            elif occurrences > 1:
                problems.append(f"{where}: quote appears {occurrences} times — extend it")
    return problems


def cue_agreement(
    suggestions: SuggestionSet,
    store: list[LabelledAd],
    dimensions: list[Dimension],
) -> dict[str, Any]:
    """How much of the set the extraction regexes would have produced anyway.

    The measurement that makes independence checkable instead of declared. For
    each suggestion, does one of its *own* dimension's cues, in the ad's
    language, fire somewhere inside the suggested quote? A set whose every span
    is cue-reachable is the extractor's output under another name, whatever its
    `method` says — and the corpus built by confirming it would make
    `extraction_macro_f1` a measurement of the extractor against itself.

    A high number is a signal to read, not an automatic failure: cues do fire on
    genuine market language, so some overlap is expected and healthy. It is
    reported for that reason, and the interesting quantity is the *complement* —
    `cue_unreachable`, the suggestions the extractor could not have reached,
    which are the ones carrying new information into the gold set.
    """
    by_id = {ad.id: ad for ad in store}
    by_dimension = {dimension.id: dimension for dimension in dimensions}
    reachable = 0
    total = 0
    unreachable_examples: list[str] = []

    for ad_id, proposed in sorted(suggestions.by_ad.items()):
        ad = by_id.get(ad_id)
        if ad is None:
            continue
        for suggestion in proposed:
            # An unmapped entry names a concept the model has no home for, so it
            # has no cue set to be reachable by and cannot belong in this
            # denominator. Counting it would drag the agreement ratio down for a
            # reason that has nothing to do with cue independence.
            if suggestion.dimension is None:
                continue
            dimension = by_dimension.get(suggestion.dimension)
            if dimension is None:
                continue
            total += 1
            cues = dimension.extraction.cues.get(ad.language, [])
            if any(re.search(cue.pattern, suggestion.quote, re.IGNORECASE) for cue in cues):
                reachable += 1
            elif len(unreachable_examples) < 10:
                unreachable_examples.append(f"{ad_id}:{suggestion.dimension}")

    return {
        "suggestion_count": total,
        "suggestion_cue_agreement": round(reachable / total, 4) if total else 0.0,
        "cue_unreachable": total - reachable,
        "cue_unreachable_examples": unreachable_examples,
    }


def load_suggestions(path: Path = DEFAULT_SUGGESTIONS_PATH) -> SuggestionSet:
    """Read and shape the file, or raise `SuggestionError` naming the problem."""
    if not path.exists():
        raise SuggestionError(f"suggestions file not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SuggestionError(f"{path.name}: cannot be read as JSON: {exc}") from exc
    try:
        return SuggestionSet.model_validate(raw)
    except Exception as exc:
        raise SuggestionError(f"{path.name}: {exc}") from exc


def probe_suggestions(
    suggestions_path: Path = DEFAULT_SUGGESTIONS_PATH,
    evidence_path: Path = DEFAULT_EVIDENCE_PATH,
) -> dict[str, Any]:
    """Write the reviewable numbers for a suggestion set to evidence."""
    store = load_store()
    dimensions = load_dimensions()
    suggestions = load_suggestions(suggestions_path)
    problems = validate_suggestions(suggestions, store, dimensions)
    measured: dict[str, Any] = {
        "method": suggestions.method,
        "generated_at": suggestions.generated_at,
        "suggestion_violations": len(problems),
        "violations": problems[:40],
        "ads_with_suggestions": len(suggestions.by_ad),
        "blind_control_count": len(suggestions.blind_control),
        **cue_agreement(suggestions, store, dimensions),
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(measured, indent=2) + "\n", encoding="utf-8")
    return measured


def write_proposals(
    export: dict[str, Any],
    dimensions_dir: Path = DEFAULT_DIMENSIONS_DIR,
) -> list[Path]:
    """Materialise a labelling export's `proposed_dimensions` as reviewable stubs.

    The labelling page runs over `file://` and cannot write to the repository, so
    a dimension coined mid-read travels in the export and is written here. The
    result is deliberately a **stub**, not a finished dimension: it carries the
    id, name, group and rungs the labeller chose, and leaves `elicitation`,
    `extraction` and each rung's `tell` as `TODO` markers that
    `integral.dimensions` will refuse to load until a person fills them in.

    That refusal is the point. Coining a dimension changes the model's spine and
    every gate that counts dimensions reads it; a stub that loaded cleanly would
    let an ad-hoc idea become part of the measured model without anyone
    deciding it should be.
    """
    written: list[Path] = []
    for proposal in export.get("proposed_dimensions") or []:
        dimension_id = str(proposal.get("id", "")).strip()
        if not SNAKE_CASE.match(dimension_id):
            raise SuggestionError(f"proposed dimension id {dimension_id!r} is not snake_case")
        path = dimensions_dir / f"{dimension_id}.yaml"
        if path.exists():
            raise SuggestionError(f"{path} already exists — refusing to overwrite a dimension")
        levels = proposal.get("levels") or []
        if not 2 <= len(levels) <= 5:
            raise SuggestionError(f"{dimension_id}: needs between 2 and 5 rungs, got {len(levels)}")

        body = [
            f"# Coined while labelling {proposal.get('coined_at_ad', 'an ad')}.",
            "#",
            "# This file does NOT load as written: `methods_ref` below is deliberately",
            "# `#TODO`, which fails the anchor pattern, so `load_dimensions` refuses the",
            "# whole model until a person finishes this. That refusal is the point —",
            "# coining a dimension changes the model's spine and every gate that counts",
            "# dimensions reads it, so an idea had while reading one ad must not become",
            "# part of the measured model just because a file appeared.",
            "#",
            "# To finish: replace every TODO, write extraction cues and at least one gold",
            "# example, and point methods_ref at the section of docs/METHODS.md that",
            "# documents how this dimension is measured.",
            f"id: {dimension_id}",
            "kind: soft",
            f"polarity: {proposal.get('polarity', 'unipolar')}",
            f"group: {proposal.get('group', 'the_work')}",
            "label:",
            f"  en: {json.dumps(proposal.get('label', dimension_id))}",
            "  es: TODO",
            "  ca: TODO",
            f"definition: {json.dumps(proposal.get('definition', 'TODO'))}",
            "levels:",
        ]
        for level in levels:
            body += [
                f"  - value: {level['value']}",
                "    label:",
                f"      en: {json.dumps(level.get('label', 'TODO'))}",
                "      es: TODO",
                "      ca: TODO",
                f"    tell: {json.dumps(level.get('tell', 'TODO'))}",
            ]
        body += [
            "elicitation:",
            "  questions:",
            f"    - id: {dimension_id[:3]}_q1",
            "      text:",
            "        en: TODO",
            "        es: TODO",
            "        ca: TODO",
            "extraction:",
            "  cues: {}",
            "  gold: []",
            "methods_ref: METHODS.md#TODO",
            "",
        ]
        path.write_text("\n".join(body), encoding="utf-8")
        written.append(path)
    return written


def _main(argv: list[str] | None = None) -> int:
    """Measure the suggestion set (the gate), or write dimension proposals.

    Named `_main` rather than `main` on purpose: `make evidence` used to derive
    its module list by grepping for `^def _main`, run each one, and refuse any
    diff in `status/evidence/`. Under the old name this module was invisible to
    that loop, so `T5-suggestions.json` was a committed number nothing ever
    re-measured — the exact failure the target's own comment warns about.
    `make evidence` now discovers modules by the evidence path they construct
    (T85) rather than this naming convention, but the no-argument run is still
    `check`, so nothing here needed to change to stay reached.
    """
    parser = argparse.ArgumentParser(description="Suggestion-set checks and proposals.")
    sub = parser.add_subparsers(dest="command")

    check = sub.add_parser("check", help="measure a suggestion set (the default)")
    check.add_argument("--suggestions", type=Path, default=DEFAULT_SUGGESTIONS_PATH)
    check.add_argument("evidence", type=Path, nargs="?", default=DEFAULT_EVIDENCE_PATH)

    propose = sub.add_parser(
        "propose", help="write dimension stubs from a labelling export's proposed_dimensions"
    )
    propose.add_argument("export", type=Path, help="the JSON the labelling page exported")
    propose.add_argument("--dimensions", type=Path, default=DEFAULT_DIMENSIONS_DIR)

    # `argv or ["check"]` would have discarded sys.argv whenever argv is None —
    # which is every real CLI invocation — making `propose` unreachable from the
    # command line while its unit tests, which call `write_proposals` directly,
    # stayed green. Resolve argv first, then default the subcommand only when one
    # was genuinely not given, so the older `… <evidence-path>` form still works.
    raw = list(sys.argv[1:] if argv is None else argv)
    if not raw or raw[0] not in {"check", "propose"}:
        raw = ["check", *raw]
    args = parser.parse_args(raw)

    if args.command == "propose":
        try:
            export = json.loads(args.export.read_text(encoding="utf-8"))
            written = write_proposals(export, args.dimensions)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"{args.export}: cannot be read as JSON: {exc}", file=sys.stderr)
            return 2
        except SuggestionError as exc:
            print(exc, file=sys.stderr)
            return 2
        if not written:
            print("no proposed dimensions in that export", file=sys.stderr)
            return 1
        for path in written:
            print(f"wrote {path} — fill in every TODO before it will load")
        return 0

    try:
        measured = probe_suggestions(args.suggestions, args.evidence)
    except SuggestionError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(json.dumps(measured))
    return 1 if measured["suggestion_violations"] else 0


if __name__ == "__main__":
    raise SystemExit(_main())
