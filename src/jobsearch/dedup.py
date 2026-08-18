"""Cross-source dedup by similarity over normalised text, and expiry detection (T13).

**Why precision, not recall.** The two ways this can be wrong are not
symmetric. Missing a duplicate is noise: the candidate sees the same role
twice, mildly annoying, easily ignored. Wrongly merging two distinct roles is
worse and invisible — one of them silently disappears from the candidate's
list and nothing ever tells them it happened. They cannot notice an offer they
never saw. That asymmetry is exactly why the gate is `dedup_precision >= 0.95`
(`TP / (TP + FP)` over seeded pairs, process spec §7.4 / `docs/METHODS.md`
§4.4) rather than a recall floor: a false merge is the failure this task must
almost never commit, and a missed one is the failure it is allowed to make.
The method and its threshold's calibration are registered in
`docs/METHODS.md` §2.8 and §4.6.

**What this is not.** T11's `compute_offer_id` (`jobsearch.offers`) already
content-addresses an offer by its verbatim text — two connections of the exact
same bytes collapse to the same `Offer.id` before either one reaches this
module. Process spec §7.4 gives the same split for tombstones: `text_sha256`
"catches re-collection of *the same listing* and nothing else... cross-posted
near-duplicates are a similarity problem and remain T13's, [and] the honest
summary is that the hash is the cheap half." This module is the other half —
the same ad reworded, retitled by a different portal, or with a source's own
summary or a boilerplate footer stitched on, none of which changes a single
byte-hash but all of which a person recognises as the same posting.

**Normalisation is for comparison only, and never touches the stored offer.**
`Offer.text` stays byte-for-byte verbatim (`offers.py`'s module docstring:
"extraction evidence spans are offsets into it, and a summary would invalidate
every span"). Every function below that needs a comparable form of an ad's
text computes one into a throwaway string or set — `normalise_for_comparison`
takes an `Offer` and returns a `str`; nothing here writes back into `Offer`,
and `Offer` is frozen so nothing here *could*.

**Method: k-word shingling + Jaccard similarity, stdlib only.** Word n-grams
("shingles") over normalised text, compared by Jaccard similarity of the two
shingle sets — the technique behind Broder's near-duplicate web-page detection,
chosen over `difflib.SequenceMatcher` because shingle-set overlap is
insensitive to reordering and to where in the text an edit happened (a
retitled opening line or an appended footer touches only the shingles that
cross that boundary), while `SequenceMatcher`'s longest-common-subsequence
approach is sensitive to exactly that kind of local rearrangement and is
quadratic in text length besides. No new dependency: `re` for tokenising and
plain set arithmetic for the rest.

**The hard case, and how it's handled.** Ads from the same source template
routinely share a long block verbatim — a cookie notice, an equal-opportunity
statement, "similar jobs" navigation — that has nothing to do with the role.
Naive shingle-Jaccard over raw text scores two *unrelated* ads from the same
template as near-duplicates, because the shared boilerplate dominates the
intersection. `_boilerplate_shingles` addresses this by frequency within the
batch being compared: a shingle common enough across the batch (more than half
the offers) is far more likely to be a shared template fragment than shared
*content* — genuine duplicate content is specific to one pair, not distributed
across most of an arbitrary batch — and is excluded from every pair's Jaccard
score. See `SIMILARITY_THRESHOLD` below for how the cutoff was picked, and
`tests/test_dedup.py::test_shared_boilerplate_does_not_merge_distinct_ads` for
the case this exists to fix.

**Expiry is detected here, not acted on.** §7.1 defines seven statuses and the
transitions between them, and §7.3's purge rule and §7.4's tombstones belong to
S5, not this module (see the T13 scope note in `status/plan.md` and
`claude-arsenal/queue/lo-9e33.md`). `detect_expired` only reports which offers
look expired — past `expires_at`, or dropped from a source's latest listing —
so S5 can carry out the `-> expired` transition. It never writes `Offer.status`
itself.

**Tombstones are consulted here, never written here.** §7.4: an incoming ad
matching a tombstone by `url_canonical` or `text_sha256` must not be re-added
as `new`. `url_canonical` and `text_sha256` are S5's versioned rules (a
canonical-URL choice among several sources carrying the same role; a hash over
S5's own chrome-stripped, volatile-stamp-stripped normalisation, tagged with a
rule version) — computing either one here, in addition, would give the project
two normalisation rules that could quietly disagree about what "the same ad"
means. `tombstone_match` takes those keys as already-computed arguments; it is
the seam this task leaves for S5 to fill in, not a second implementation of
S5's rule.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from jobsearch.offers import Offer, Strict

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T13.json"


class DedupError(Exception):
    """A tombstone record does not fit the §7.4 contract."""


# ---------------------------------------------------------------------------
# comparison-key normalisation — derived, and never applied to Offer.text


_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def normalise_for_comparison(text: str) -> str:
    """Lowercase, word-tokenise and rejoin — a throwaway comparison key.

    Deliberately simpler than §7.4's tombstone normalisation (which also
    strips a source's chrome, volatile stamps and tracking parameters before
    hashing): that rule exists to make one specific ad hash identically across
    re-scrapes, so it must be exact and versioned. This one only needs to make
    two similar ads compare as similar, so punctuation and casing differences
    ("Python/Django," vs "python django") are the only things worth folding —
    shingling and the boilerplate filter below do the rest of the robustness
    work. Takes and returns a plain `str`; the caller decides what `Offer`
    field it came from, and nothing here can write it back.
    """
    return " ".join(_WORD.findall(text.lower()))


# ---------------------------------------------------------------------------
# shingling + Jaccard


SHINGLE_SIZE = 8
# Broder's original w-shingling paper (near-duplicate web-page detection)
# settled on windows of 8-10 words: short enough that one reworded sentence
# doesn't erase every shingle touching it (a single edit only invalidates
# `SHINGLE_SIZE` shingles around it, not the whole document's set), long
# enough that a shingle is specific to a passage rather than a phrase common
# to any job ad ("apply now" alone is not distinctive; eight consecutive
# words almost always are, outside a shared template block).


def shingles(normalised: str, size: int = SHINGLE_SIZE) -> frozenset[str]:
    """Word `size`-grams of already-normalised text, as a set (order lost).

    Order is deliberately discarded — a retitled ad or a moved paragraph
    changes the *order* of shingles far more than their content, and Jaccard
    over sets is what makes the comparison ignore that. Text shorter than one
    shingle-width collapses to a single shingle of everything there is,
    rather than the empty set: a one-line stub ad should still be able to
    match another copy of the same one-line stub.
    """
    words = normalised.split(" ") if normalised else []
    if not words:
        return frozenset()
    if len(words) < size:
        return frozenset({normalised})
    return frozenset(" ".join(words[i : i + size]) for i in range(len(words) - size + 1))


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """`|intersection| / |union|`. Two empty sets score 0.0, not 1.0 — "both
    ads had no comparable content" is not evidence they are the same ad, and
    a 1.0 there would make an empty-body edge case masquerade as a confident
    duplicate match."""
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


_BOILERPLATE_CORPUS_FRACTION = 0.5
# A shingle carried by more than half of the batch being compared is treated
# as shared template text rather than shared content. Reasoning: genuine
# duplicate content is specific to *one pair* in a batch of unrelated ads, so
# even a batch that happens to contain several duplicate pairs should not
# push any single shingle past a bare majority — while a source's cookie
# notice or EOE statement is stamped onto every ad the source template
# renders, easily a majority of a same-source batch. Calibrated against
# `tests/test_dedup.py`'s seeded fixture (also `write_evidence`'s fixture
# below): 0.5 is the value at which every seeded non-duplicate pair — the
# same-company/different-role pair and the shared-boilerplate/different-job
# pair specifically — scores under `SIMILARITY_THRESHOLD` while every seeded
# duplicate pair stays over it.


def _boilerplate_shingles(
    shingle_sets: Sequence[frozenset[str]], *, corpus_fraction: float = _BOILERPLATE_CORPUS_FRACTION
) -> frozenset[str]:
    """Shingles common enough across a batch to be shared template text.

    Needs at least three offers to mean anything: with only two, any shingle
    the pair happens to share is definitionally in "all of them", which would
    reclassify the exact signal a genuine duplicate pair is found by as
    boilerplate and erase it. Below that population this returns the empty
    set — no filtering — rather than guess.
    """
    if len(shingle_sets) < 3:
        return frozenset()
    counts: dict[str, int] = {}
    for one_offer_shingles in shingle_sets:
        for shingle in one_offer_shingles:
            counts[shingle] = counts.get(shingle, 0) + 1
    floor = corpus_fraction * len(shingle_sets)
    return frozenset(shingle for shingle, count in counts.items() if count > floor)


SIMILARITY_THRESHOLD = 0.25
# Calibrated against `_fixture_batch` below (shared by the tests and the
# gate, so the number enforced in production is the number the tests check),
# after boilerplate filtering: the lowest seeded duplicate pair scores 0.489
# (two independent rewordings of the same Data Engineer ad) and every seeded
# non-duplicate pair — including both hard negatives, same-company/
# different-role and shared-boilerplate/different-job — scores 0.0. 0.25 sits
# near the midpoint of that gap rather than hugging either edge: comfortable
# margin below the weakest real duplicate, and a wide margin above the
# strongest confounder this fixture could produce. It is a property of *this*
# corpus and shingle width, not a universal constant — recalibrate if either
# changes materially (a much larger candidate pool, a different `SHINGLE_SIZE`).


def similarity(offer_a: Offer, offer_b: Offer) -> float:
    """Pairwise shingled-Jaccard similarity, no boilerplate filtering.

    Boilerplate filtering (`_boilerplate_shingles`) needs a batch to define
    "common" against; a bare pair has no such population, so two offers
    compared in isolation are compared on their raw shingle sets. Batch dedup
    (`find_duplicates`) is where filtering is applied — this function is the
    building block it and the tests both use for the unfiltered score.
    """
    a = shingles(normalise_for_comparison(offer_a.text))
    b = shingles(normalise_for_comparison(offer_b.text))
    return jaccard(a, b)


@dataclass(frozen=True)
class DuplicateMatch:
    """One pair `find_duplicates` judged to be the same ad. Not persisted —
    computed fresh from whatever batch is passed in, same as `revision.py`'s
    `Stale`."""

    offer_a: str
    offer_b: str
    similarity: float


def find_duplicates(
    offers: Sequence[Offer], *, threshold: float = SIMILARITY_THRESHOLD
) -> list[DuplicateMatch]:
    """Every pair in `offers` that looks like the same ad, batch-aware.

    Byte-identical crossposts never reach here as separate records — T11's
    content-addressed `Offer.id` already collapsed them (skipped below via the
    id-equality check, which only fires if a caller passes the same offer
    twice or two connections that happened to produce identical text). What
    this finds is the near-duplicate: different id, similar enough normalised
    text once shared template shingles are discounted.
    """
    prepared = [(offer, shingles(normalise_for_comparison(offer.text))) for offer in offers]
    boilerplate = _boilerplate_shingles([one_offer_shingles for _, one_offer_shingles in prepared])
    matches: list[DuplicateMatch] = []
    for (offer_a, shingles_a), (offer_b, shingles_b) in combinations(prepared, 2):
        if offer_a.id == offer_b.id:
            continue  # already the same record by T11's content-addressed id
        score = jaccard(shingles_a - boilerplate, shingles_b - boilerplate)
        if score > threshold:
            matches.append(DuplicateMatch(offer_a.id, offer_b.id, score))
    return matches


# ---------------------------------------------------------------------------
# expiry detection — reported, never acted on; §7.1's transitions are S5's


@dataclass(frozen=True)
class ExpiryFinding:
    """One offer that looks expired, and why. `detect_expired` returns these;
    it never writes `Offer.status` — the `-> expired` transition and what
    follows from it (§7.3's purge eligibility clock, §7.4's tombstone) are
    S5's, per the T13 scope note in `status/plan.md`."""

    offer_id: str
    reason: Literal["expires_at_passed", "delisted"]
    detail: str


def detect_expired(
    offers: Sequence[Offer],
    *,
    now: datetime,
    still_listed: Mapping[str, frozenset[str]] | None = None,
) -> list[ExpiryFinding]:
    """Which offers look expired, by §7.1's two routes: past `expires_at`, or
    dropped from a source's most recent listing.

    `still_listed` maps a source name to the `source_ref`s that source listed
    on its latest completed collection pass. A source absent from the mapping
    is treated as "no completed pass this round to compare against" and is
    silently skipped for the delisting check — a source that has not been
    re-collected says nothing about whether an ad is still there, and treating
    silence as delisting would expire every offer on the first missed run.
    `still_listed=None` skips the delisting check entirely, for callers with
    only `expires_at` to go on (T12's single connector, for instance).
    """
    findings: list[ExpiryFinding] = []
    for offer in offers:
        expired_by_date = False
        if offer.expires_at is not None:
            try:
                expires = datetime.fromisoformat(offer.expires_at.replace("Z", "+00:00"))
            except ValueError:
                pass  # malformed expires_at is a schema problem, not this function's to judge
            else:
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=now.tzinfo)
                if expires <= now:
                    detail = f"expired at {offer.expires_at}"
                    findings.append(ExpiryFinding(offer.id, "expires_at_passed", detail))
                    expired_by_date = True
        if expired_by_date or still_listed is None:
            continue
        listed = still_listed.get(offer.source)
        if listed is not None and offer.source_ref is not None and offer.source_ref not in listed:
            findings.append(
                ExpiryFinding(
                    offer.id, "delisted", f"{offer.source} no longer lists {offer.source_ref!r}"
                )
            )
    return findings


# ---------------------------------------------------------------------------
# tombstones — consulted here, written by S5


class Tombstone(Strict):
    """§7.4's tombstone shape, verbatim. Carries no ad body — that is the
    point of purging, and this module never adds one."""

    offer_id: str
    url: str | None = None
    url_canonical: str | None = None
    text_sha256: str | None = None
    first_seen: str
    purged_at: str
    last_status: str
    resightings: int = Field(ge=0)
    last_resighting: str | None = None


def load_tombstones(path: Path) -> list[Tombstone]:
    """Read `offers/tombstones.jsonl`, one tombstone per line. Raises
    `DedupError` on anything that does not fit §7.4's shape — a loader raises
    when what it's given cannot become the thing it promises, same rule as
    `offers.load_offer`."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DedupError(f"cannot read tombstones at {path}: {exc}") from exc
    tombstones: list[Tombstone] = []
    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            tombstones.append(Tombstone.model_validate(payload))
        except Exception as exc:
            raise DedupError(f"{path}:{line_number} is not a valid tombstone: {exc}") from exc
    return tombstones


def tombstone_match(
    tombstones: Sequence[Tombstone],
    *,
    url_canonical: str | None = None,
    text_sha256: str | None = None,
) -> Tombstone | None:
    """Whether an incoming ad matches a purge tombstone, so collection does
    not re-add it as `new` (§7.4).

    `url_canonical` and `text_sha256` are supplied by the caller — S5's rules,
    not recomputed here; see the module docstring. Passing neither always
    returns `None` rather than matching everything: an unmatchable candidate
    is not evidence of a match. This only *finds* the tombstone; incrementing
    `resightings`, dropping the candidate, and handling an explicit revival
    (§7.4: "if the candidate pastes or asks for a tombstoned ad, it is
    restored as `new`... the tombstone survives") are S5's to do with the
    result.
    """
    if url_canonical is None and text_sha256 is None:
        return None
    for tombstone in tombstones:
        if url_canonical is not None and tombstone.url_canonical == url_canonical:
            return tombstone
        if text_sha256 is not None and tombstone.text_sha256 == text_sha256:
            return tombstone
    return None


# ---------------------------------------------------------------------------
# the gate


MINIMUM_PAIRS = 15
# "A precision of 1.0 over two pairs is not a measurement" (payload). 15 is
# comfortably above what any two- or three-ad fixture could produce and is
# met by the seeded batch below (7 offers -> C(7,2) = 21 judged pairs) with
# room to add offers later without a rewrite.


def _fixture_batch() -> tuple[list[Offer], frozenset[frozenset[str]]]:
    """A small labelled batch: which offer-id pairs are true duplicates.

    Shared by `probe_dedup` (the gate) and importable by tests, so the gate's
    number and the tests' assertions are checked against the same fixture
    rather than two fixtures drifting apart. Composition, by design:

    * a 3-way crosspost cluster (`t13-1a/1b/1c`) — reworded title, reworded
      body, and a shared-boilerplate footer appended, all naming the same
      Backend Engineer role at Acme — 3 true-duplicate pairs;
    * a 2-way crosspost cluster (`t13-2a/2b`) for a different role at a
      different company, also carrying the *same* boilerplate footer as
      `t13-1c` — 1 true-duplicate pair, and the hard negative: `1c` and `2a`/
      `2b` share a long block verbatim yet must not merge;
    * `t13-3`, a distinct role at the *same company* as the first cluster —
      the other hard negative (`test_distinct_roles_at_same_company_are_not_merged`);
    * `t13-4`, an unrelated ad with nothing in common with the rest.

    Every other pair among these seven is an implicit true negative.
    """
    boilerplate = (
        "Equal opportunity employer. We celebrate diversity and are committed "
        "to creating an inclusive environment for all employees. By applying "
        "you consent to our processing of your data for recruitment purposes "
        "in accordance with our privacy policy. This posting may use cookies "
        "and similar tracking technology to measure engagement with similar "
        "job recommendations shown after this listing."
    )
    backend_body = (
        "We are looking for a Backend Engineer to join our platform team. "
        "You will design and build services in Python and Django, own our "
        "core billing pipeline, and work closely with product to ship "
        "reliable APIs. We use PostgreSQL, Celery and run everything on "
        "Kubernetes. You should be comfortable with REST API design, "
        "database schema migrations and on-call rotations. Experience with "
        "event-driven architecture is a plus. Remote friendly, flexible "
        "hours, and a strong emphasis on code review and testing."
    )
    backend_body_reworded = (
        "Great opportunity for a Backend Engineer to join a growing team. "
        "You will design and build services in Python and Django, own our "
        "core billing pipeline, and work closely with product to ship "
        "reliable APIs. We use PostgreSQL, Celery and run everything on "
        "Kubernetes. You should be comfortable with REST API design, "
        "database schema migrations and on-call rotations. Experience with "
        "event-driven architecture is a plus. Competitive salary and a "
        "generous learning budget for the right candidate."
    )
    data_body = (
        "We are hiring a Data Engineer to build and maintain our analytics "
        "pipelines. You will work with Spark and Airflow to move data from "
        "our production systems into the warehouse, design dimensional "
        "models, and partner with analysts on data quality. Experience with "
        "streaming ingestion, dbt and cloud data warehouses is preferred. "
        "You should be comfortable writing complex SQL, tuning query "
        "performance and documenting data lineage for a growing team."
    )
    data_body_reworded = (
        "Exciting opening for a Data Engineer on our growing team. "
        "You will work with Spark and Airflow to move data from "
        "our production systems into the warehouse, design dimensional "
        "models, and partner with analysts on data quality. Experience with "
        "streaming ingestion, dbt and cloud data warehouses is preferred. "
        "You should be comfortable writing complex SQL, tuning query "
        "performance and documenting data lineage. Hybrid working available "
        "for local candidates."
    )
    frontend_body = (
        "We need a Frontend Engineer to own our customer-facing React "
        "application. You will build accessible, responsive UI components, "
        "work with designers on interaction details, and profile and "
        "improve rendering performance. TypeScript, CSS architecture and "
        "browser testing experience required. You'll collaborate with "
        "backend engineers on API contracts but the day-to-day is entirely "
        "front-of-stack: component libraries, visual regression testing and "
        "accessibility audits."
    )
    sales_body = (
        "We are seeking a Sales Manager to lead our regional sales team. "
        "You will set quarterly targets, coach account executives, and "
        "build relationships with enterprise customers across the region. "
        "Experience with CRM tooling, forecasting and running a pipeline "
        "review is required. Frequent regional travel expected. This is a "
        "leadership role reporting directly to the VP of Sales, with "
        "quota-carrying responsibility for the whole territory."
    )

    offers = [
        Offer(
            id=f"sha256:{1:064x}",
            source="portal-a",
            title="Backend Engineer",
            company="Acme",
            text=backend_body,
        ),
        Offer(
            id=f"sha256:{2:064x}",
            source="portal-b",
            title="Backend Developer (Python/Django)",
            company="Acme SL",
            text=backend_body_reworded,
        ),
        Offer(
            id=f"sha256:{3:064x}",
            source="portal-c",
            title="Backend Engineer - Acme",
            company="Acme",
            text=backend_body + " " + boilerplate,
        ),
        Offer(
            id=f"sha256:{4:064x}",
            source="portal-a",
            title="Data Engineer",
            company="Nimbus",
            text=data_body + " " + boilerplate,
        ),
        Offer(
            id=f"sha256:{5:064x}",
            source="portal-d",
            title="Data Engineer (Analytics)",
            company="Nimbus Analytics",
            text=data_body_reworded + " " + boilerplate,
        ),
        Offer(
            id=f"sha256:{6:064x}",
            source="portal-a",
            title="Frontend Engineer",
            company="Acme",
            text=frontend_body + " " + boilerplate,
        ),
        Offer(
            id=f"sha256:{7:064x}",
            source="portal-e",
            title="Sales Manager",
            company="Regional Retail Group",
            text=sales_body,
        ),
    ]
    duplicate_pairs = frozenset(
        frozenset(pair)
        for pair in (
            (offers[0].id, offers[1].id),
            (offers[0].id, offers[2].id),
            (offers[1].id, offers[2].id),
            (offers[3].id, offers[4].id),
        )
    )
    return offers, duplicate_pairs


def probe_dedup() -> dict[str, Any]:
    """Measure `dedup_precision` over the seeded fixture, and report what
    went wrong if anything did. `failures` records false positives — a false
    negative (a missed duplicate) hurts recall, which this gate does not
    measure, and is not treated as a module failure; it is still visible in
    `predicted_positive` vs. `duplicate_pairs_seeded` for a human to notice.
    """
    offers, duplicate_pairs = _fixture_batch()
    total_pairs = len(offers) * (len(offers) - 1) // 2
    matches = find_duplicates(offers)
    predicted = {frozenset((match.offer_a, match.offer_b)) for match in matches}

    true_positives = predicted & duplicate_pairs
    false_positives = predicted - duplicate_pairs
    missed = duplicate_pairs - predicted

    failures = [
        f"false positive: {sorted(pair)} flagged as a duplicate but is not one"
        for pair in sorted(false_positives, key=sorted)
    ]

    precision = len(true_positives) / len(predicted) if predicted else 0.0

    return {
        "dedup_precision": precision,
        "pairs_judged": total_pairs,
        "duplicate_pairs_seeded": len(duplicate_pairs),
        "predicted_positive": len(predicted),
        "true_positives": len(true_positives),
        "false_positives": len(false_positives),
        "missed_duplicates": len(missed),
        "failures": failures,
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure `dedup_precision` over the fixture and record it."""
    measured = probe_dedup()
    if measured["failures"]:
        # A false positive elsewhere must not be reported behind a clean
        # precision number computed some other way.
        measured["dedup_precision"] = (
            0.0 if not measured["predicted_positive"] else measured["dedup_precision"]
        )
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m jobsearch.dedup [path]` -> T13's gate evidence."""
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["pairs_judged"] < MINIMUM_PAIRS:
        print(
            f"only {measured['pairs_judged']} pair(s) were judged (floor {MINIMUM_PAIRS}) — "
            "a precision of 1.0 over two pairs is not a measurement",
            file=sys.stderr,
        )
        return 3
    for failure in measured["failures"]:
        print(failure, file=sys.stderr)
    return 1 if measured["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
