"""Corpus harness (T4) — labelled ad store, splits, labelling CLI, self-agreement.

T4b collected the ads; T5 labels them by hand. This is the machinery in
between, and everything in it exists to protect two properties the later gates
depend on:

* **Offsets survive.** A label is a dimension value *plus the span of ad text
  that evidences it* (`explained_fraction == 1.0`, T19). If a write/read cycle
  shifts an offset by one character, every explanation cites the wrong words
  and nothing downstream can tell. `roundtrip_loss` measures exactly that.
* **The splits stay disjoint.** If ads used to elicit preferences are also used
  to measure ranking, the ranking gate measures memorisation and passes
  (`elicitation_eval_overlap == 0`, T9). Assignment is therefore deterministic
  and derived from the ad id, not drawn at random each run.

The store is JSONL, one labelled ad per line, sorted by id — appends are atomic
and diffs stay readable (`status/specification.md` §5).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from jobsearch.corpus import DEFAULT_PATH as RAW_CORPUS_PATH
from jobsearch.corpus import LANGUAGES, load_ads
from jobsearch.dimensions import DEFAULT_DIMENSIONS_DIR, Dimension, Language, load_dimensions

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STORE_PATH = _REPO_ROOT / "corpus" / "labelled" / "ads.jsonl"
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T4.json"

Split = Literal["elicitation", "evaluation"]

# How a human arrived at a label. There is deliberately no `"suggested"` member:
# a machine suggestion that nobody looked at is not a label and never becomes
# one — it lives in `corpus/labelled/suggestions.json` and dies in the browser
# if it is not acted on. So every value here means a person made a judgement,
# and the three record which judgement it was:
#
#   human      typed from scratch, with no suggestion involved
#   confirmed  a suggestion the labeller read and accepted unchanged
#   edited     a suggestion whose dimension, rung or span the labeller changed
#
# The split matters because `confirmed` is the one that can hide rubber-stamping.
# Keeping it distinguishable is what lets `suggestion_confirm_rate` be compared
# against blind agreement on the control ads instead of taken on trust.
LabelSource = Literal["human", "confirmed", "edited"]

# Share of ads assigned to the evaluation split. The evaluation half feeds
# `extraction_macro_f1` (T15) and `rank_spearman` (T20); the elicitation half
# feeds reaction elicitation (T9). Neither is useful too small, and evaluation
# is the one that must not be starved, so the corpus is halved.
EVALUATION_SHARE = 0.5


class HarnessError(Exception):
    """The labelled store does not satisfy its contract."""


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Span(Strict):
    """A half-open character range into the ad text: `text[start:end]`.

    Character offsets, not bytes — Python string indices are code points, and
    the corpus is full of accented Catalan and Spanish and of emoji in the
    Manfred ads. Byte offsets would mean every accent shifts the span.
    """

    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def _end_follows_start(self) -> Span:
        if self.end <= self.start:
            raise ValueError(f"span end {self.end} must be greater than start {self.start}")
        return self

    def extract(self, text: str) -> str:
        return text[self.start : self.end]


class Label(Strict):
    """One dimension's value on one ad, with the text that evidences it.

    `negated` records that the evidence *denies* the dimension ("no on-call",
    "sense guàrdies") rather than being absent — the distinction T16 turns into
    `extraction_negation_recall`, and the one a bare score cannot carry.
    """

    dimension: str = Field(min_length=1)
    value: float = Field(ge=-1.0, le=1.0)
    spans: list[Span] = Field(min_length=1)
    negated: bool = False
    labeller: str = Field(min_length=1)
    round: int = Field(ge=1, default=1)
    source: LabelSource = "human"


class ImportRow(Strict):
    """One row of the JSON batch `harness import` applies (T5 fast path).

    The shape `tools/labelling_page.py` emits: everything `set` needs for one
    label, plus the ad it belongs to. `extra="forbid"` (via `Strict`) catches a
    row shaped by a stale copy of the page — a `span` field where `quote` is
    expected, say — as a validation error instead of a silently-ignored key.
    """

    ad_id: str = Field(min_length=1)
    dimension: str = Field(min_length=1)
    value: float = Field(ge=-1.0, le=1.0)
    quote: str = Field(min_length=1)
    negated: bool = False
    labeller: str = Field(min_length=1, default="owner")
    round: int = Field(ge=1, default=1)
    source: LabelSource = "human"


class LabelledAd(Strict):
    """A corpus ad with its split assignment and any labels placed on it."""

    id: str = Field(min_length=1)
    language: Language
    text: str = Field(min_length=1)
    source_url: str = Field(pattern=r"^https://")
    title: str = ""
    company: str = ""
    source: str = ""
    fetched_at: str = ""
    split: Split
    labels: list[Label] = Field(default_factory=list)

    @model_validator(mode="after")
    def _spans_lie_inside_the_text(self) -> LabelledAd:
        length = len(self.text)
        for label in self.labels:
            for span in label.spans:
                if span.end > length:
                    raise ValueError(
                        f"label {label.dimension!r} on {self.id}: span {span.start}-{span.end} "
                        f"runs past the end of the text ({length} characters)"
                    )
        return self

    def labels_in_round(self, round_number: int) -> dict[str, Label]:
        return {label.dimension: label for label in self.labels if label.round == round_number}


def split_rank(ad_id: str) -> int:
    """A stable pseudo-random ordering key for an ad, from its id alone."""
    return int.from_bytes(hashlib.sha256(ad_id.encode("utf-8")).digest()[:8], "big")


def assign_splits(
    ads: list[dict[str, Any]],
    existing: dict[str, Split] | None = None,
    evaluation_share: float = EVALUATION_SHARE,
) -> dict[str, Split]:
    """Assign each ad to a split, stratified by language and stable over time.

    Two properties matter more than elegance here, and a plain per-ad hash
    threshold delivers neither:

    * **Stratified.** Thresholding each id independently is binomial, and on a
      15-ad slice it lands badly — the first cut of this corpus put 1 of 15
      Catalan ads in evaluation, which would have measured Catalan extraction
      (T15) and Catalan ranking (T20) on a single ad while every count looked
      healthy in aggregate. Each language is therefore divided at its own
      target.
    * **Stable.** An ad already in the store keeps the split it was given, so
      adding ads later cannot migrate an already-labelled ad from one half to
      the other. That migration is precisely the `elicitation_eval_overlap`
      T9 forbids, arriving by the back door rather than through a bug.

    Ordering within a language is by `split_rank`, so a fresh corpus assigns
    identically on every machine and every rerun.
    """
    existing = existing or {}
    assignment: dict[str, Split] = {}
    for language in LANGUAGES:
        group = sorted(
            (ad for ad in ads if ad["language"] == language),
            key=lambda ad: split_rank(str(ad["id"])),
        )
        # Ceiling, not `round`: with an odd slice and a 0.5 share, banker's
        # rounding hands the extra ad to elicitation (25 → 12 evaluation), and
        # evaluation is the half that must not be starved — it carries
        # `extraction_macro_f1` and `rank_spearman`.
        target = math.ceil(len(group) * evaluation_share)
        held = sum(1 for ad in group if existing.get(str(ad["id"])) == "evaluation")
        for ad in group:
            ad_id = str(ad["id"])
            if ad_id in existing:
                assignment[ad_id] = existing[ad_id]
                continue
            if held < target:
                assignment[ad_id] = "evaluation"
                held += 1
            else:
                assignment[ad_id] = "elicitation"
    return assignment


def build_store(
    ads: list[dict[str, Any]] | None = None,
    existing: dict[str, Split] | None = None,
    evaluation_share: float = EVALUATION_SHARE,
) -> list[LabelledAd]:
    """Seed labelled records from the raw corpus, unlabelled, splits assigned."""
    if ads is None:
        ads = load_ads()
    assignment = assign_splits(ads, existing, evaluation_share)
    return [
        LabelledAd(
            id=str(ad["id"]),
            language=ad["language"],
            text=str(ad["text"]),
            source_url=str(ad["source_url"]),
            title=str(ad.get("title", "")),
            company=str(ad.get("company", "")),
            source=str(ad.get("source", "")),
            fetched_at=str(ad.get("fetched_at", "")),
            split=assignment[str(ad["id"])],
        )
        for ad in sorted(ads, key=lambda a: str(a["id"]))
    ]


def save_store(store: list[LabelledAd], path: Path = DEFAULT_STORE_PATH) -> None:
    """Write the store as JSONL, sorted by id, UTF-8, one ad per line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(ad.model_dump(), ensure_ascii=False, sort_keys=True)
        for ad in sorted(store, key=lambda a: a.id)
    ]
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_store(path: Path = DEFAULT_STORE_PATH) -> list[LabelledAd]:
    """Read the store, raising `HarnessError` on anything that does not fit."""
    if not path.exists():
        raise HarnessError(f"labelled store not found: {path}")
    store: list[LabelledAd] = []
    seen: set[str] = set()
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            ad = LabelledAd.model_validate_json(line)
        except ValidationError as exc:
            raise HarnessError(
                f"{path.name}:{lineno}: {exc.error_count()} problem(s): {exc}"
            ) from exc
        if ad.id in seen:
            raise HarnessError(f"{path.name}:{lineno}: duplicate ad id {ad.id!r}")
        seen.add(ad.id)
        store.append(ad)
    return store


def roundtrip_loss(store: list[LabelledAd], tmp_path: Path) -> list[str]:
    """Write the store, read it back, and report every difference.

    Text is compared exactly and each span is compared *by what it extracts*,
    not only by its numbers: an offset that survives as an integer but points
    at different characters is the failure this is here to catch.
    """
    save_store(store, tmp_path)
    reloaded = {ad.id: ad for ad in load_store(tmp_path)}

    losses: list[str] = []
    for original in store:
        copy = reloaded.get(original.id)
        if copy is None:
            losses.append(f"{original.id}: lost in the roundtrip")
            continue
        if copy.text != original.text:
            losses.append(f"{original.id}: text differs after the roundtrip")
        if copy.split != original.split:
            losses.append(f"{original.id}: split {original.split} became {copy.split}")
        if len(copy.labels) != len(original.labels):
            losses.append(
                f"{original.id}: {len(original.labels)} label(s) became {len(copy.labels)}"
            )
            continue
        for before, after in zip(original.labels, copy.labels, strict=True):
            if (before.dimension, before.value, before.negated, before.round) != (
                after.dimension,
                after.value,
                after.negated,
                after.round,
            ):
                losses.append(f"{original.id}: label {before.dimension!r} differs")
            for span_before, span_after in zip(before.spans, after.spans, strict=True):
                if span_before.extract(original.text) != span_after.extract(copy.text):
                    losses.append(
                        f"{original.id}: label {before.dimension!r} span "
                        f"{span_before.start}-{span_before.end} now covers different text"
                    )
    return losses


def probe_labels(store: list[LabelledAd], dimensions: list[Dimension]) -> list[LabelledAd]:
    """Copy the store with a label placed at a real cue match on every ad.

    The committed store starts unlabelled — labelling is T5 — so a roundtrip
    over it would preserve offsets vacuously, having none to preserve. These
    probes take their offsets from genuine cue matches in genuine ad text,
    which is where the accents and emoji are, so the measurement exercises the
    thing it claims to.
    """
    import re

    probed: list[LabelledAd] = []
    for ad in store:
        labels = list(ad.labels)
        for dimension in dimensions:
            match = next(
                (
                    found
                    for cue in dimension.extraction.cues.get(ad.language, [])
                    if (found := re.search(cue.pattern, ad.text, re.IGNORECASE))
                ),
                None,
            )
            if match is None:
                continue
            labels.append(
                Label(
                    dimension=dimension.id,
                    value=0.5,
                    spans=[Span(start=match.start(), end=match.end())],
                    labeller="roundtrip-probe",
                )
            )
            break
        probed.append(ad.model_copy(update={"labels": labels}))
    return probed


def unknown_dimensions(store: list[LabelledAd], dimensions: list[Dimension]) -> list[str]:
    """Labels naming a dimension the model does not define.

    A label on `sallary_transparency` is not a small typo: it silently drops out
    of every per-dimension metric, lowering the denominator instead of failing.
    """
    known = {dimension.id for dimension in dimensions}
    return [
        f"{ad.id}: label names unknown dimension {label.dimension!r}"
        for ad in store
        for label in ad.labels
        if label.dimension not in known
    ]


def split_counts(store: list[LabelledAd]) -> dict[str, dict[str, int]]:
    """Ads per split, and per language within each split."""
    counts: dict[str, dict[str, int]] = {}
    for split in ("elicitation", "evaluation"):
        members = [ad for ad in store if ad.split == split]
        counts[split] = {"total": len(members)}
        counts[split].update(
            {
                language: sum(1 for ad in members if ad.language == language)
                for language in LANGUAGES
            }
        )
    return counts


def self_agreement(store: list[LabelledAd]) -> dict[str, Any]:
    """Cohen's kappa between a labeller's first and second pass.

    The labelling protocol (`status/specification.md`, open question on the
    corpus protocol) calls for re-labelling a subset at least two weeks later
    and reporting self-agreement. Raw agreement flatters any corpus where most
    ads score zero on most dimensions, so this reports kappa over the sign of
    the value — negative / absent / positive — which corrects for the agreement
    two passes would reach by chance.

    Returns `kappa: None` when no ad has been labelled twice, which is the
    state until T5 runs. That is reported, never rounded up to 1.0.
    """
    pairs: list[tuple[int, int]] = []
    for ad in store:
        first, second = ad.labels_in_round(1), ad.labels_in_round(2)
        # Only ads actually revisited count. Within those, a dimension labelled
        # in one round and not the other is a *disagreement* — present versus
        # absent — not a pair to drop. Dropping it silently raises agreement by
        # discarding exactly the cases where the two passes differed most.
        if not second:
            continue
        for dimension in sorted(set(first) | set(second)):
            pairs.append(
                (
                    _sign(first[dimension]) if dimension in first else 0,
                    _sign(second[dimension]) if dimension in second else 0,
                )
            )

    re_labelled = sum(1 for ad in store if ad.labels_in_round(2))
    if not pairs:
        return {
            "kappa": None,
            "undefined_because": "nothing has been labelled twice",
            "compared_labels": 0,
            "raw_agreement": None,
            "re_labelled_ads": re_labelled,
        }

    observed = sum(1 for a, b in pairs if a == b) / len(pairs)
    categories = (-1, 0, 1)
    expected = sum(
        (sum(1 for a, _ in pairs if a == c) / len(pairs))
        * (sum(1 for _, b in pairs if b == c) / len(pairs))
        for c in categories
    )
    report: dict[str, Any] = {
        "compared_labels": len(pairs),
        "raw_agreement": round(observed, 4),
        "re_labelled_ads": re_labelled,
    }
    if expected == 1:
        # Both passes put every label in one category, so kappa is 0/0. Calling
        # that perfect agreement is the exact flattery kappa exists to prevent:
        # two passes that scored everything zero agree completely and have
        # established nothing. Undefined is the honest answer.
        report["kappa"] = None
        report["undefined_because"] = "every label in both rounds fell in one category"
        return report
    report["kappa"] = round((observed - expected) / (1 - expected), 4)
    return report


def _sign(label: Label) -> int:
    if label.negated or label.value < 0:
        return -1
    return 1 if label.value > 0 else 0


def measure(
    store_path: Path = DEFAULT_STORE_PATH,
    dimensions_dir: Path = DEFAULT_DIMENSIONS_DIR,
) -> dict[str, Any]:
    """Measure T4's gate over the committed store."""
    store = load_store(store_path)
    dimensions = load_dimensions(dimensions_dir)

    # A scratch file beside the store would write into the versioned corpus
    # directory — which the test suite does on every run — and two concurrent
    # measurements would share the name. Both go away with a private temp dir.
    with tempfile.TemporaryDirectory(prefix="jobsearch-roundtrip-") as scratch_dir:
        scratch = Path(scratch_dir) / "roundtrip-check.jsonl"
        losses = roundtrip_loss(store, scratch)
        losses += roundtrip_loss(probe_labels(store, dimensions), scratch)

    labelled = [ad for ad in store if ad.labels]
    return {
        "corpus_harness_roundtrip_loss": len(losses),
        "roundtrip_losses": losses,
        "ad_count": len(store),
        "labelled_ad_count": len(labelled),
        "label_count": sum(len(ad.labels) for ad in store),
        "unknown_dimension_labels": unknown_dimensions(store, dimensions),
        "splits": split_counts(store),
        "self_agreement": self_agreement(store),
    }


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    store_path: Path = DEFAULT_STORE_PATH,
) -> dict[str, Any]:
    measured = measure(store_path)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


# ── labelling CLI ───────────────────────────────────────────────────────────


def _cmd_init(args: argparse.Namespace) -> int:
    """Seed the store from the raw corpus, preserving labels *and splits*.

    Carrying the splits forward is the whole point of `assign_splits(existing=)`
    — re-seeding without them recomputes every assignment from scratch, so a
    corpus top-up moves already-labelled ads between halves and puts elicited
    ads into the evaluation set. Preserving only labels here would have left the
    stability guarantee true of the function and false of the command.
    """
    store_path = Path(args.store)
    existing = {ad.id: ad for ad in load_store(store_path)} if store_path.exists() else {}
    seeded = build_store(
        load_ads(Path(args.raw)),
        existing={ad_id: ad.split for ad_id, ad in existing.items()},
    )
    merged = [
        ad.model_copy(update={"labels": existing[ad.id].labels}) if ad.id in existing else ad
        for ad in seeded
    ]
    save_store(merged, store_path)
    counts = split_counts(merged)
    print(f"{len(merged)} ads -> {store_path}")
    print(
        f"  elicitation {counts['elicitation']['total']}"
        f"  evaluation {counts['evaluation']['total']}"
    )
    kept = sum(len(ad.labels) for ad in merged)
    print(f"  {kept} existing label(s) preserved")
    return 0


def _cmd_next(args: argparse.Namespace) -> int:
    """Print the next ad awaiting labels, with the dimension checklist."""
    store = load_store(Path(args.store))
    dimensions = load_dimensions()
    pending = [
        ad
        for ad in store
        if not ad.labels_in_round(args.round)
        and (args.split is None or ad.split == args.split)
        and (args.language is None or ad.language == args.language)
    ]
    if not pending:
        print("nothing left to label for this filter")
        return 0
    ad = pending[0]
    print(f"{ad.id}  [{ad.language}] [{ad.split}]  {ad.title}")
    print(f"{ad.source_url}\n")
    print(ad.text[: args.chars])
    if len(ad.text) > args.chars:
        print(f"\n… {len(ad.text) - args.chars} more characters (--chars to show more)")
    print(f"\n{len(pending)} ad(s) pending. Dimensions:")
    for dimension in dimensions:
        print(f"  {dimension.id:26s} {dimension.label.get(ad.language)}")
    print(f'\nlabel with:  label set {ad.id} <dimension> <value> --quote "<verbatim text>"')
    return 0


def _cmd_set(args: argparse.Namespace) -> int:
    """Record one label, locating the span by searching for a verbatim quote.

    The quote is looked up in the ad text rather than typed as offsets: offsets
    typed by hand are how a corpus acquires spans that point at the wrong words
    while still validating.
    """
    store_path = Path(args.store)
    store = load_store(store_path)
    by_id = {ad.id: ad for ad in store}
    ad = by_id.get(args.ad_id)
    if ad is None:
        print(f"no ad {args.ad_id!r} in {store_path}", file=sys.stderr)
        return 2

    located = locate_quote(ad, args.quote)
    if isinstance(located, str):
        print(located, file=sys.stderr)
        return 2
    start, end = located

    known = {dimension.id: dimension for dimension in load_dimensions()}
    dimension = known.get(args.dimension)
    if dimension is None:
        print(f"unknown dimension {args.dimension!r}", file=sys.stderr)
        return 2
    # The same rung check `import` applies. A CLI that accepted an off-rung
    # value would be a way around the labelling vocabulary, and the corpus
    # would end up holding values macro-F1 has no class for.
    if dimension.level_for(args.value) is None:
        rungs = ", ".join(f"{level.value} ({level.label.en})" for level in dimension.levels)
        print(
            f"value {args.value} is not a declared level of {args.dimension!r} — "
            f"pick one of: {rungs}",
            file=sys.stderr,
        )
        return 2

    label = Label(
        dimension=args.dimension,
        value=args.value,
        spans=[Span(start=start, end=end)],
        negated=args.negated,
        labeller=args.labeller,
        round=args.round,
    )
    kept = [
        existing
        for existing in ad.labels
        if not (existing.dimension == args.dimension and existing.round == args.round)
    ]
    updated = ad.model_copy(update={"labels": [*kept, label]})
    save_store([updated if other.id == ad.id else other for other in store], store_path)
    print(f"{ad.id}: {args.dimension} = {args.value} (round {args.round}) @ {start}-{end}")
    return 0


def locate_quote(ad: LabelledAd, quote: str) -> tuple[int, int] | str:
    """Find `quote` in `ad.text`, or the reason it cannot be used as a span.

    The one search `set` and `import` must agree on byte-for-byte: an absent
    quote and an ambiguous one are refused identically by both entry points,
    so a labeller cannot get a different answer from the CLI than from the
    page's batch. Returns `(start, end)` on success, or a human-readable
    refusal reason — never raises, so a caller validating a whole batch can
    keep going through every row instead of stopping at the first bad one.
    """
    start = ad.text.find(quote)
    if start < 0:
        return f"quote does not appear in {ad.id} — copy it verbatim from the text"
    if ad.text.find(quote, start + 1) >= 0:
        return f"quote appears more than once in {ad.id} — extend it until it is unique"
    return start, start + len(quote)


def import_labels(
    store: list[LabelledAd],
    rows: list[dict[str, Any]],
    dimensions: Mapping[str, Dimension],
) -> tuple[list[LabelledAd], list[dict[str, Any]]]:
    """Validate a whole batch, then apply it — or apply nothing.

    Two passes over `rows`, on purpose. The first only reads: it shapes each
    row through `ImportRow` and locates its quote, and touches nothing in
    `store`. Only if every row passed does the second pass build the updated
    store and return it; a single bad row anywhere in the batch means the
    first pass's returned store is the *original*, unmodified list, and the
    caller (`_cmd_import`) never calls `save_store` on it. This is what keeps
    a partially-bad paste from partially applying — the alternative, applying
    each row as it validates, would leave whatever validated before the first
    failure sitting in the file with no record of which rows those were.

    Later rows targeting the same `(ad_id, dimension, round)` as an earlier
    row in the *same* batch win, matching `set`'s overwrite-in-place
    behaviour — so importing the same export twice, or a corrected re-export,
    never grows the label list, which is the idempotency the task calls for.

    Returns `(updated_store_or_original, results)`. `results` has one entry
    per row, each `{"index", "ad_id", "dimension", "status", "reason"?,
    "start"?, "end"?}` with `status` one of `"applied"` or `"refused"`.
    """
    by_id = {ad.id: ad for ad in store}
    results: list[dict[str, Any]] = []
    located: list[tuple[int, ImportRow, int, int]] = []
    all_valid = True

    for index, raw_row in enumerate(rows):
        try:
            row = ImportRow.model_validate(raw_row)
        except ValidationError as exc:
            all_valid = False
            problems = "; ".join(
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors()
            )
            results.append({"index": index, "status": "refused", "reason": problems})
            continue

        base = {"index": index, "ad_id": row.ad_id, "dimension": row.dimension}
        ad = by_id.get(row.ad_id)
        if ad is None:
            all_valid = False
            reason = f"no ad {row.ad_id!r} in the store"
            results.append({**base, "status": "refused", "reason": reason})
            continue
        dimension = dimensions.get(row.dimension)
        if dimension is None:
            all_valid = False
            results.append(
                {**base, "status": "refused", "reason": f"unknown dimension {row.dimension!r}"}
            )
            continue
        if dimension.level_for(row.value) is None:
            all_valid = False
            rungs = ", ".join(
                f"{level.value} ({level.label.en})" for level in dimension.levels
            )
            results.append(
                {
                    **base,
                    "status": "refused",
                    "reason": (
                        f"value {row.value} is not a declared level of {row.dimension!r} — "
                        f"pick one of: {rungs}"
                    ),
                }
            )
            continue

        located_span = locate_quote(ad, row.quote)
        if isinstance(located_span, str):
            all_valid = False
            results.append({**base, "status": "refused", "reason": located_span})
            continue

        start, end = located_span
        located.append((index, row, start, end))
        results.append({**base, "status": "applied", "start": start, "end": end})

    if not all_valid:
        return store, results

    updated_by_id = dict(by_id)
    for _index, row, start, end in located:
        ad = updated_by_id[row.ad_id]
        label = Label(
            dimension=row.dimension,
            value=row.value,
            spans=[Span(start=start, end=end)],
            negated=row.negated,
            labeller=row.labeller,
            round=row.round,
            source=row.source,
        )
        kept = [
            existing
            for existing in ad.labels
            if not (existing.dimension == row.dimension and existing.round == row.round)
        ]
        updated_by_id[row.ad_id] = ad.model_copy(update={"labels": [*kept, label]})

    return list(updated_by_id.values()), results


def _cmd_import(args: argparse.Namespace) -> int:
    """Apply the JSON batch `tools/labelling_page.py` emits, in one write.

    Exactly as strict as `set`, run over every row before anything is
    written: the same verbatim-quote search (`locate_quote`), the same
    refusal of an absent or ambiguous quote, the same unknown-dimension
    check. `import_labels` does the validate-then-apply split; this is the
    CLI shell around it — read the file (or stdin), report per row, and only
    call `save_store` once, when nothing was refused.
    """
    store_path = Path(args.store)
    store = load_store(store_path)

    raw_text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(
        encoding="utf-8"
    )
    try:
        rows = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        print(f"not valid JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(rows, list):
        print("expected a JSON array of label rows", file=sys.stderr)
        return 2

    known = {dimension.id: dimension for dimension in load_dimensions()}
    updated, results = import_labels(store, rows, known)

    refused = [r for r in results if r["status"] == "refused"]
    applied = [r for r in results if r["status"] == "applied"]

    for result in results:
        if result["status"] == "applied":
            print(
                f"row {result['index']}: {result['ad_id']} {result['dimension']} "
                f"applied @ {result['start']}-{result['end']}"
            )
        else:
            label_bit = ""
            if "ad_id" in result:
                label_bit = f"{result['ad_id']} {result.get('dimension', '')} "
            print(
                f"row {result['index']}: {label_bit}refused — {result['reason']}", file=sys.stderr
            )

    if refused:
        print(
            f"{len(refused)} row(s) refused, {len(applied)} row(s) would have applied — "
            "nothing written",
            file=sys.stderr,
        )
        return 2

    save_store(updated, store_path)
    print(f"{len(applied)} label(s) applied to {store_path}")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    measured = measure(Path(args.store))
    print(json.dumps(measured, ensure_ascii=False, indent=2))
    return 0


def _cmd_agreement(args: argparse.Namespace) -> int:
    report = self_agreement(load_store(Path(args.store)))
    if report["kappa"] is None:
        # Two different states arrive here and must not be conflated: nothing
        # re-labelled yet, and re-labelled but degenerate. Telling a labeller
        # who has just re-done 40 ads that nothing was labelled twice would send
        # them back to redo work already on disk.
        print(
            f"self-agreement undefined — {report['undefined_because']} "
            f"({report['compared_labels']} label pair(s) across "
            f"{report['re_labelled_ads']} re-labelled ad(s))"
        )
        return 0
    print(
        f"self-agreement over {report['compared_labels']} label pair(s) on "
        f"{report['re_labelled_ads']} ad(s): kappa {report['kappa']}, "
        f"raw {report['raw_agreement']}"
    )
    return 0


def _cmd_gate(args: argparse.Namespace) -> int:
    measured = write_evidence(Path(args.evidence), Path(args.store))
    summary = {k: v for k, v in measured.items() if k != "roundtrip_losses"}
    print(json.dumps(summary, ensure_ascii=False))
    if measured["ad_count"] == 0:
        print("labelled store is empty — nothing measured", file=sys.stderr)
        return 3
    for loss in measured["roundtrip_losses"]:
        print(loss, file=sys.stderr)
    for problem in measured["unknown_dimension_labels"]:
        print(problem, file=sys.stderr)
    return 1 if measured["roundtrip_losses"] or measured["unknown_dimension_labels"] else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m jobsearch.harness", description=__doc__)
    parser.add_argument("--store", default=str(DEFAULT_STORE_PATH))
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="seed the store from the raw corpus")
    init.add_argument("--raw", default=str(RAW_CORPUS_PATH))
    init.set_defaults(func=_cmd_init)

    nxt = sub.add_parser("next", help="show the next ad awaiting labels")
    nxt.add_argument("--split", choices=["elicitation", "evaluation"])
    nxt.add_argument("--language", choices=list(LANGUAGES))
    nxt.add_argument("--round", type=int, default=1)
    nxt.add_argument("--chars", type=int, default=1500)
    nxt.set_defaults(func=_cmd_next)

    put = sub.add_parser("set", help="record a label")
    put.add_argument("ad_id")
    put.add_argument("dimension")
    put.add_argument("value", type=float)
    put.add_argument("--quote", required=True, help="verbatim ad text evidencing the value")
    put.add_argument("--negated", action="store_true")
    put.add_argument("--labeller", default="owner")
    put.add_argument("--round", type=int, default=1)
    put.set_defaults(func=_cmd_set)

    imp = sub.add_parser(
        "import", help="apply a JSON batch of labels (from tools/labelling_page.py)"
    )
    imp.add_argument("file", help="path to a JSON array of label rows, or - for stdin")
    imp.set_defaults(func=_cmd_import)

    status = sub.add_parser("status", help="print the full harness measurement")
    status.set_defaults(func=_cmd_status)

    agreement = sub.add_parser("agreement", help="report self-agreement between labelling rounds")
    agreement.set_defaults(func=_cmd_agreement)

    gate = sub.add_parser("gate", help="write status/evidence/T4.json")
    gate.add_argument("--evidence", default=str(DEFAULT_EVIDENCE_PATH))
    gate.set_defaults(func=_cmd_gate)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result: int = args.func(args)
    except HarnessError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except ValidationError as exc:
        # `--round 0` and friends reach Pydantic, not argparse. A labeller who
        # mistypes a flag should get a line of error, not a stack trace.
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        print(f"invalid input — {problems}", file=sys.stderr)
        return 2
    return result


if __name__ == "__main__":
    raise SystemExit(main())
