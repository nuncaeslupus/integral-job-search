"""D-1: does the Catalan corpus slice's declared scope agree across the
documents that state it? (`arsenal/tasks/_history/lo-bc1d.md`)

T4b asked for ≥100 raw ads, ≈60 ES / 25 EN / 15 CA, all **remote programming**
roles. `corpus/raw/ads.jsonl` holds exactly that count and mix, but the 15
Catalan ads are not a like-for-like remote-programming sample: natively-Catalan
remote-programming ads barely exist. A full keyword sweep of Feina Activa — the
one board that publishes ads written in Catalan rather than translated into it —
returns under ten, nowhere near the 15 the slice needs. The available shortcut
(teletreballa.com republishes Feina Activa ads machine-translated into Catalan)
was rejected on principle and stays rejected: those are not verbatim originals,
and the spec's risk register forbids padding the corpus with text that is not
the real ad.

The decision (D-1, option 1) is to accept this as a fact about the Catalan
job-ad market, not a collection failure, and amend the spec rather than chase a
market that is not there: the Catalan slice is **Catalan IT ads at large**
(developer, sysadmin, data, cybersecurity, TIC consulting), stated honestly as
such, with the remote dimension mixed in rather than filtered for. Shrinking the
Catalan target (D-1, option 2) was rejected too — the slice's job is Catalan
job-ad *vocabulary* for the ontology, and a Catalan sysadmin ad teaches that
vocabulary exactly as well as a Catalan remote-developer ad would.

**Why this needs a mechanical check, not three hand-edited documents.**
Amending a spec to match reality is exactly how a spec stops meaning anything,
unless the amendment is visible everywhere someone would look for it. Three
documents state the Catalan slice's scope in three different places —
`status/plan.md`'s T4b row (the build order), `corpus/raw/README.md`'s "Known
divergence" section (the corpus's own account of itself), and this module's
`TARGET_MIX` (what `tests/test_corpus_raw.py` actually pins) — and nothing
stops a future edit to any one of them from drifting back to "remote
programming" while the other two still say otherwise. That is the same failure
class D-3 (`integral.spec_consistency`) exists for: a document that is
*reconciled-looking* is not the same as a document that is reconciled, and the
gap between them is invisible to anyone who only reads one of the three. This
module is the mechanical check: it reads the real `status/plan.md` and
`corpus/raw/README.md` off disk and fails loud the moment either stops
carrying the anchor phrases below, rather than trusting three humans to keep
three files in sync by hand.

The check is deliberately anchor-phrase, not full-sentence, matching. Full-
sentence matching (D-3's approach) works there because the source and target
documents both restate a short symbolic expression (`story_failure_fraction >=
0.33`) verbatim. Here one document is a dense table cell and the other is
flowing prose — forcing one verbatim sentence into both would read as an odd
transplant in whichever is not its native shape. A short, distinctive phrase
("Catalan IT ads", "remote dimension ... mixed") is what both can carry
naturally while still being an exact, mechanical `in` check rather than a
prose-similarity heuristic that could pass on a document saying something
else entirely.

---

**T98 — the corpus is a measurement set, not a serving cache, and it is not one
candidate's search.** That is the other half of "what is this corpus for", so it is
measured here, and `write_provenance_evidence` records it as `status/evidence/T98.json`.

Three properties, and none survives as prose:

* **The serving ban.** No candidate is ever handed a stored advert as an offer. An
  advert is perishable and a stored one is stale by definition; reading offers out of
  a cache is what let one live session return three adverts and call the market
  exhausted. `serving_path_findings` asserts this over the *code* — the sourcing,
  offer-store, ranking and presentation modules may not reach the corpus at all.
* **The provenance.** Every row names a **draw** declared in `corpus/draws.yaml`, and
  that draw's specification must still select it. `integral.corpus.load_ads` already
  refuses a row that names no draw or carries a candidate-bound key; what it cannot do
  without the registry — is the draw *declared*, and does its stated query shape
  actually account for this row — is `provenance_faults` here.
* **The one exemption, and its bounds.** Step 5 draws corpus adverts as *stimuli*, and
  the owner ruled that measurement is not serving. `exempt_reader_findings` keeps that
  module from widening into serving, `CORPUS_MODULES` keeps a serving module from
  reaching the corpus *through* it, and `stimulus_split_findings` enforces the
  condition the ruling came with — the stimuli come from a split disjoint from the
  evaluation set. `EXEMPT_CORPUS_READERS` below carries the ruling in the owner's own
  words, beside the list a reader of the ban arrives at.

The second check is what makes provenance a filter rather than a comment. A row copied
out of a candidate's harvest can trivially be labelled `draw: t4b-programming`; it
cannot as easily come from a source, language and job family that draw declares. So the
specification is applied, not just cited, and a row it does not select is a fault.

**The import closure is deliberately not the serving set.** `rank` imports `extraction`,
which imports `harness`, which imports `corpus` — so a transitive check fails today on a
module whose corpus read is offline evaluation of the extractor, not an offer being
served. Widening the check to catch that would mean allowlisting `extraction`, which
removes the one module most able to hide the violation. The named set below is narrower
and honest about it: it is every `sourcing_*` module (discovered, so a new one is
covered the day it lands) plus the offer store and the ranked page, each scanned for a
*direct* corpus read — which is what "just read the corpus when the connectors return
nothing" would actually look like.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from integral import corpus
from integral.offers import compute_offer_id

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PLAN = _REPO_ROOT / "status" / "plan.md"
DEFAULT_README = _REPO_ROOT / "corpus" / "raw" / "README.md"
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "D1.json"

# The language-mix target T4b actually measures. `tests/test_corpus_raw.py`
# imports this rather than restating it, so the count the mix test pins and the
# count this module checks documents against can never independently drift —
# one of the three ways D-1 found the corpus and its documentation disagreeing.
TARGET_MIX: dict[str, int] = {"es": 60, "en": 25, "ca": 15}

# Anchor phrases a reconciled document must carry. Matched case-insensitively
# and as substrings/regexes, not as whole-sentence literals — see the module
# docstring for why. `CATALAN_SCOPE_ANCHOR` is checked against both
# `status/plan.md` and `corpus/raw/README.md`; `REMOTE_MIX_ANCHOR` only against
# the README, whose prose is where the remote dimension's status ("mixed in,
# not filtered for") is actually explained — a table cell has no room to.
CATALAN_SCOPE_ANCHOR = "catalan it ads"
# `\s+`, not a literal `" "`: prose (the README) soft-wraps at whatever column
# an editor left it at, so words an anchor phrase expects adjacent can end up
# separated by a newline instead of a space. A literal-space regex matched a
# single-line synthetic test fixture and then failed on the real, wrapped
# prose — this is the fix for that, not a hypothetical. `re.DOTALL` lets the
# `.{0,40}` gap itself cross a line break too.
CATALAN_SCOPE_RE = re.compile(r"catalan\s+it\s+ads", re.IGNORECASE)
REMOTE_MIX_ANCHOR = re.compile(r"remote\s+dimension.{0,40}mixed", re.IGNORECASE | re.DOTALL)

# An anchor is only a declaration if nothing just before it reverses it. Both
# anchors above match on their content words alone, so "the slice is **not**
# Catalan IT ads" and "the remote dimension is not mixed" satisfied them while
# stating the opposite of what they exist to assert — a drift detector that
# passes on a document contradicting the thing it checks.
#
# The realistic drift is a reversion to the old wording, which the anchors
# already catch. This closes the other direction, and is deliberately a narrow
# window rather than a grammar: a negation more than a few words back usually
# belongs to another clause, and this module does no linguistics.
_NEGATION_RE = re.compile(
    r"\b(?:not|never|no longer|isn't|is not|aren't|are not)\b[\s\w,]{0,24}$", re.IGNORECASE
)


def _affirmed(text: str, match: re.Match[str] | None) -> bool:
    """Whether `match` reads as an assertion rather than its denial."""
    if match is None:
        return False
    return _NEGATION_RE.search(text[: match.start()]) is None


_T4B_ROW_RE = re.compile(r"^\|\s*T4b\s*\|.*\|\s*$", re.MULTILINE)
_KNOWN_DIVERGENCE_RE = re.compile(r"^## Known divergence.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)


def t4b_row(plan_path: Path = DEFAULT_PLAN) -> str:
    """`status/plan.md`'s T4b row, verbatim, or `""` if the row is not found."""
    if not plan_path.is_file():
        return ""
    match = _T4B_ROW_RE.search(plan_path.read_text(encoding="utf-8"))
    return match.group(0) if match else ""


def known_divergence_section(readme_path: Path = DEFAULT_README) -> str:
    """`corpus/raw/README.md`'s "Known divergence" section, heading to the next
    heading (or end of file), or `""` if the section is not found."""
    if not readme_path.is_file():
        return ""
    match = _KNOWN_DIVERGENCE_RE.search(readme_path.read_text(encoding="utf-8"))
    return match.group(0) if match else ""


def measure(plan_path: Path = DEFAULT_PLAN, readme_path: Path = DEFAULT_README) -> dict[str, Any]:
    """D-1's gate reading: how many of the documents that declare the Catalan
    slice's scope disagree with it, as written to evidence.

    A missing row or section counts as a mismatch rather than being skipped —
    skipping it would let the file disappearing entirely read as "nothing to
    disagree with, therefore fine", the same vacuous-pass failure D-3 guards
    against with `MINIMUM_DECLARATIONS_FOUND`.
    """
    row = t4b_row(plan_path)
    section = known_divergence_section(readme_path)
    mismatches: list[dict[str, str]] = []

    if not row:
        mismatches.append({"document": "status/plan.md", "reason": "T4b row not found"})
    elif not _affirmed(row, CATALAN_SCOPE_RE.search(row)):
        mismatches.append(
            {
                "document": "status/plan.md",
                "reason": f"T4b row does not state the Catalan slice's scope "
                f"({CATALAN_SCOPE_ANCHOR!r} not stated, or negated)",
            }
        )

    if not section:
        mismatches.append(
            {
                "document": "corpus/raw/README.md",
                "reason": '"Known divergence" section not found',
            }
        )
    else:
        if not _affirmed(section, CATALAN_SCOPE_RE.search(section)):
            mismatches.append(
                {
                    "document": "corpus/raw/README.md",
                    "reason": f"Known divergence section does not state the Catalan "
                    f"slice's scope ({CATALAN_SCOPE_ANCHOR!r} not stated, or negated)",
                }
            )
        if not _affirmed(section, REMOTE_MIX_ANCHOR.search(section)):
            mismatches.append(
                {
                    "document": "corpus/raw/README.md",
                    "reason": "Known divergence section does not say the remote "
                    "dimension is mixed in rather than filtered for",
                }
            )

    return {
        "corpus_language_slice_mismatch": len(mismatches),
        "mismatches": mismatches,
        "target_mix": dict(TARGET_MIX),
    }


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    plan_path: Path = DEFAULT_PLAN,
    readme_path: Path = DEFAULT_README,
) -> dict[str, Any]:
    """Measure and record `status/evidence/D1.json`."""
    measured = measure(plan_path, readme_path)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


# ------------------------------------------------------------------ T98: the corpus
# is a measurement set, not a serving cache

DEFAULT_T98_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T98.json"
DEFAULT_DRAWS = _REPO_ROOT / "corpus" / "draws.yaml"
DEFAULT_RAW_ADS = _REPO_ROOT / "corpus" / "raw" / "ads.jsonl"
DEFAULT_LABELLED_ADS = _REPO_ROOT / "corpus" / "labelled" / "ads.jsonl"
DEFAULT_SRC_DIR = _REPO_ROOT / "src" / "integral"

# What a draw specification must state to be re-issuable without a person in the loop.
# `purpose` is in the list because a draw nobody can say the point of is a harvest with
# a name; the three axes are what a connector is actually pointed at.
DRAW_SPEC_FIELDS: tuple[str, ...] = (
    "id",
    "drawn_at",
    "purpose",
    "languages",
    "job_families",
    "sources",
)

# The offer-serving path: where an advert reaches a candidate. Every `sourcing_*` module
# is discovered rather than listed, so a new one is inside the scan the day it lands;
# these are the rest of the path, and a missing one makes the reading `unmeasured`
# rather than quietly shrinking the scan — a renamed module dropping out unnoticed is
# the clean-zero-over-an-empty-set failure this whole file exists to refuse.
CORE_SERVING_MODULES: tuple[str, ...] = (
    "dedup",
    "explain",
    "feedback",
    "freshness",
    "lifecycle",
    "offers",
    "presentation",
    "rank",
)

# ---------------------------------------------------------------------------------
# The one exemption to the serving ban, and the three things that bound it.
#
# Step 5 (`integral.reaction_elicit`) draws corpus adverts as **stimuli**: adverts shown
# to the candidate so that a reaction can be captured. That reads the corpus, and it is
# not serving. The owner ruled on 2026-09-04, and the reason is recorded here — beside
# the list a reader of the ban actually arrives at — rather than only in the task file:
#
#     "reacting to an advert can never contaminate the labels it is scored against."
#
# Showing an advert to elicit a reaction is *measurement*. Nothing about a stimulus is a
# claim that this job suits this person, so the perishability argument that bans serving
# — a stored advert is stale by definition, and answering a candidate's search from stale
# rows is what let one live session return three adverts and call the market exhausted —
# does not reach it. `reaction_elicit` therefore does **not** join `CORE_SERVING_MODULES`.
#
# An unbounded exemption is a hole with a comment next to it, so three checks bound this
# one, and each is measured rather than promised:
#
# 1. **Stimuli only, never onward.** The exempt module may depend on the offer *record*
#    (`integral.offers`) and on the store transition that admits one
#    (`integral.lifecycle`) — a stimulus is written into the candidate's offer store as
#    an ordinary `new` offer, and there is no other way to do that. It may depend on
#    nothing else on the serving path: nothing that orders, presents, explains, ages or
#    sources offers. An edit importing `integral.rank` or `integral.presentation` into
#    it — the exact shape of "while we have these adverts, show them as matches" — is
#    counted as `exempt_reader_serving_imports`.
# 2. **No laundering.** `integral.reaction_elicit` is itself a corpus module *for
#    everyone else*, so a serving module importing it reaches the corpus through it and
#    is counted as `serving_path_corpus_reads` like any direct read. Without that, the
#    exemption is a one-import detour around the whole ban.
# 3. **A disjoint split.** An advert a candidate has reacted to is no longer clean
#    held-out data for any metric computed over the evaluation split, so the stimulus
#    pool must be disjoint from that split — `stimulus_pool_evaluation_overlaps` and
#    `corpus_text_collisions` below.
#
# The exemption is one module, by name. Widening it is an edit to this line, which is the
# point: a second exempt reader has to be argued for rather than slipped in.
EXEMPT_CORPUS_READERS: tuple[str, ...] = ("reaction_elicit",)

# What an exempt reader may touch on the serving path, and nothing else may. Both are
# structural: `Offer` and `compute_offer_id` are the record a stimulus *is*, and
# `collect_offer` is the one transition that admits it to the store. Neither ranks,
# orders, filters or presents anything.
STIMULUS_STRUCTURAL_DEPENDENCIES: tuple[str, ...] = ("offers", "lifecycle")

# Reading any of these *is* reading the corpus, whichever name it arrives under.
# `integral.corpus_scope` is in the set because this module reads both stores itself —
# `_read_rows`, `provenance_faults`, and `DEFAULT_RAW_ADS` as a plain path — so leaving
# it out made the detector blind to the shortest route through itself, and the ban's own
# count would have stayed at zero while a serving module used it. Fail-open. Every exempt
# reader is in it for the same reason: the exemption is for the module itself, never for
# a serving module that imports it.
CORPUS_MODULES = frozenset(
    {"integral.corpus", "integral.corpus_scope", "integral.harness"}
    | {f"integral.{name}" for name in EXEMPT_CORPUS_READERS}
)
_CORPUS_PATH_RE = re.compile(r"corpus/(?:raw|labelled)")

# Floors, not counts of the day (T100's lesson): the evidence records what the scan must
# at least have covered, so an archive, a rename or a growing corpus never rewrites the
# committed number — and a scan that has shrunk below the floor reports `unmeasured`
# instead of a clean zero over nothing.
MINIMUM_CORPUS_ROWS = 400
MINIMUM_SERVING_MODULES = 12

# The exemption's reach, and the set it must stay disjoint from. Two floors, not one,
# because the disjointness reading has **two** vacuous passes and a floor on one side
# refuses only one of them: an empty stimulus pool overlaps nothing, and an empty
# evaluation split is overlapped by nothing. Either produces a clean zero over an empty
# set, which is the reading this pair exists to refuse.
MINIMUM_STIMULUS_POOL = 80
MINIMUM_EVALUATION_POOL = 80


def load_draws(path: Path = DEFAULT_DRAWS) -> dict[str, dict[str, Any]]:
    """The declared draw specifications, by id.

    A draw missing any of `DRAW_SPEC_FIELDS`, declared twice, or carrying a
    candidate-bound key is refused outright rather than reported: an unusable
    specification in the registry is worse than none, because every row naming it then
    reads as accounted for.
    """
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    draws: dict[str, dict[str, Any]] = {}
    for entry in document.get("draws") or []:
        identifier = str(entry.get("id") or "")
        missing = [field for field in DRAW_SPEC_FIELDS if not entry.get(field)]
        if missing:
            raise ValueError(f"{path}: draw {identifier!r} declares no {', '.join(missing)}")
        bound = sorted(corpus.CANDIDATE_BOUND_KEYS & set(entry))
        if bound:
            raise ValueError(
                f"{path}: draw {identifier!r} is bound to a candidate ({', '.join(bound)}) "
                f"— a draw that cannot be stated without naming a person is a search"
            )
        if identifier in draws:
            raise ValueError(f"{path}: draw {identifier!r} is declared twice")
        draws[identifier] = dict(entry)
    return draws


def draw_queries(spec: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    """The (source, language, job family) triples a draw asks for.

    Sorted, and derived from the specification alone, so the same specification always
    names the same work — which is the whole of what "reproducible" means here. A
    session harvest has no such expansion: it is whatever came back.
    """
    return sorted(
        (str(source), str(language), str(family))
        for source in spec["sources"]
        for language in spec["languages"]
        for family in spec["job_families"]
    )


def draw_selects(spec: Mapping[str, Any], ad: Mapping[str, Any]) -> bool:
    """Whether re-issuing this specification would have asked for this row."""
    return (ad.get("source"), ad.get("language"), ad.get("job_family")) in set(draw_queries(spec))


def _read_rows(path: Path) -> list[dict[str, Any]]:
    """Every JSONL row, unvalidated.

    Deliberately not `corpus.load_ads`: that refuses a row with no draw, and a
    measurement that cannot read the violating row cannot count it.
    """
    if not path.is_file():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def provenance_faults(
    raw_path: Path = DEFAULT_RAW_ADS,
    labelled_path: Path = DEFAULT_LABELLED_ADS,
    draws_path: Path = DEFAULT_DRAWS,
) -> tuple[list[dict[str, str]], int]:
    """Every corpus row that cannot be traced to a declared draw, and how many
    **distinct** rows were examined to find them.

    Five ways a row fails, in the order they are checked — a row is reported once:

    0. its identifier already named another row in the same store;
    1. it names no draw at all;
    2. it is bound to a candidate (`corpus.CANDIDATE_BOUND_KEYS`);
    3. the draw it names is not declared in the registry;
    4. the declared specification would not have asked for it — the check that stops a
       harvested row from passing by copying a legitimate draw's label.

    The labelled store is examined too, by a different rule: it carries no draw of its
    own because `harness.build_store` seeds it *from* the raw corpus, so its provenance
    is its raw row. A labelled id with no raw row behind it came from somewhere else.

    The count returned is of distinct identifiers per store, not of JSONL lines, and
    that is what `MINIMUM_CORPUS_ROWS` is a floor on. Counting lines made the floor
    satisfiable by duplication: one valid row copied four hundred times produced no
    fault and cleared it, so a denominator advertised as four hundred adverts could be
    one advert. A floor a corpus can meet without containing anything measures nothing.
    """
    draws = load_draws(draws_path)
    faults: list[dict[str, str]] = []
    raw = _read_rows(raw_path)

    raw_seen: set[str] = set()
    for ad in raw:
        identifier = str(ad.get("id") or "?")
        named = str(ad.get("draw") or "").strip()
        bound = sorted(corpus.CANDIDATE_BOUND_KEYS & set(ad))
        if identifier in raw_seen:
            faults.append(
                {
                    "row": identifier,
                    "where": "raw",
                    "reason": "the raw store already carries a row under this id",
                }
            )
        elif not named:
            faults.append({"row": identifier, "where": "raw", "reason": "names no draw"})
        elif bound:
            faults.append(
                {
                    "row": identifier,
                    "where": "raw",
                    "reason": f"bound to a candidate ({', '.join(bound)})",
                }
            )
        elif named not in draws:
            faults.append(
                {
                    "row": identifier,
                    "where": "raw",
                    "reason": f"names draw {named!r}, which corpus/draws.yaml does not declare",
                }
            )
        elif not draw_selects(draws[named], ad):
            faults.append(
                {
                    "row": identifier,
                    "where": "raw",
                    "reason": f"draw {named!r} does not ask for "
                    f"{ad.get('source')}/{ad.get('language')}/{ad.get('job_family')}",
                }
            )
        raw_seen.add(identifier)

    raw_ids = {str(ad.get("id")) for ad in raw}
    labelled = _read_rows(labelled_path)
    labelled_seen: set[str] = set()
    for ad in labelled:
        identifier = str(ad.get("id") or "?")
        if identifier in labelled_seen:
            faults.append(
                {
                    "row": identifier,
                    "where": "labelled",
                    "reason": "the labelled store already carries a row under this id",
                }
            )
        elif identifier not in raw_ids:
            faults.append(
                {
                    "row": identifier,
                    "where": "labelled",
                    "reason": "no raw-corpus row behind it, so no draw produced it",
                }
            )
        labelled_seen.add(identifier)

    # Rows, across both stores — an advert present in raw and in labelled counts once
    # in each, so 208 distinct adverts read as 416. That is what the name says and what
    # the floor is set against (`corpus_rows_evaluated_at_least`), but the headroom is
    # thinner than it looks: 400 is cleared by 208 adverts, not by 400 of them
    # (#307 second-reader F6).
    return faults, len(raw_seen) + len(labelled_seen)


def serving_path_modules(src_dir: Path = DEFAULT_SRC_DIR) -> list[str]:
    """The modules that put an advert in front of a candidate as an offer."""
    discovered = {path.stem for path in src_dir.glob("sourcing_*.py")}
    return sorted(discovered | set(CORE_SERVING_MODULES))


def _imported_module(node: ast.ImportFrom) -> str:
    """The absolute module a `from … import` names, with `integral` put back.

    A relative import is the same read under a shorter name: `from .corpus import
    load_ads` sets `module` to `"corpus"` and `level` to `1`, and reading it as
    written finds nothing in `CORPUS_MODULES`. That was fail-open in the check that
    enforces the serving ban — the ban's own count would stay at zero while a serving
    module read the corpus directly.

    Every serving module sits directly in `src/integral/`, so `level == 1` is the only
    relative form that can reach a sibling; `level >= 2` leaves the package and cannot
    be `integral.corpus` under another name.
    """
    if node.level == 0:
        return node.module or ""
    if node.level > 1:
        return ""
    return f"integral.{node.module}" if node.module else "integral"


def _corpus_reads(source: str) -> list[str]:
    """How this module reaches the corpus, if it does — by import or by path."""
    reasons: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            module = _imported_module(node)
            if module in CORPUS_MODULES:
                reasons.append(f"imports from {module}")
            elif module == "integral":
                for alias in node.names:
                    if f"integral.{alias.name}" in CORPUS_MODULES:
                        reasons.append(f"imports integral.{alias.name}")
        elif isinstance(node, ast.Import):
            reasons.extend(
                f"imports {alias.name}" for alias in node.names if alias.name in CORPUS_MODULES
            )
    if _CORPUS_PATH_RE.search(source):
        reasons.append("names a corpus/ path")
    return sorted(set(reasons))


def serving_path_findings(
    src_dir: Path = DEFAULT_SRC_DIR,
) -> tuple[list[dict[str, str]], list[str]]:
    """Every serving-path module that reads the corpus, and every one that is missing.

    A missing module is returned separately because it is not a violation — it is a
    reason to distrust the whole reading, and `measure_provenance` turns it into
    `unmeasured` rather than folding it into a count of zero.
    """
    findings: list[dict[str, str]] = []
    absent: list[str] = []
    for name in serving_path_modules(src_dir):
        path = src_dir / f"{name}.py"
        if not path.is_file():
            absent.append(name)
            continue
        for reason in _corpus_reads(path.read_text(encoding="utf-8")):
            findings.append({"module": name, "reason": reason})
    return findings, absent


def exempt_reader_findings(
    src_dir: Path = DEFAULT_SRC_DIR,
) -> tuple[list[dict[str, str]], list[str]]:
    """Bound 1: every serving-path module an exempt corpus reader imports, and every
    exempt reader that is not in the tree.

    This is the check that keeps the exemption narrow. `reaction_elicit` is allowed to
    read the corpus *because it makes stimuli*, and the observable difference between a
    stimulus and a served offer is what the module does with it afterwards. Importing
    `integral.rank`, `integral.presentation`, `integral.explain` or a `sourcing_*` module
    is that difference arriving as a two-line edit — the exemption widened into general
    serving, with the ban's own count still reading zero because the exempt module is not
    scanned by `serving_path_findings`.

    `STIMULUS_STRUCTURAL_DEPENDENCIES` is what a stimulus structurally needs and is
    listed rather than inferred: `offers` gives the record and its content-addressed id,
    `lifecycle` admits it to the store. Allowing the two by name and refusing the other
    six-plus is what makes this a boundary rather than a shrug.

    An exempt reader absent from the tree is returned separately, exactly as an absent
    serving module is: it makes the reading untrusted rather than a violation, because a
    renamed exempt module scanned as nothing is a clean zero over an empty set.

    **The stated ceiling.** This reads `import` and `from … import` statements out of
    the AST, plus corpus path literals out of the source text, and that is the whole of
    it. A dynamic import — `importlib.import_module("integral.rank")`,
    `__import__(...)`, `sys.modules[...]` — reaches the same module and is not seen
    here; nor is a corpus path assembled from parts (`Path("corpus") / "raw"`).
    Measured, not assumed: every spelling the fixtures below drive was pushed past
    this scan and past `serving_path_corpus_reads` (#307 second-reader F4), and every
    static form was caught — absolute and relative, `import` and `from … import`, the
    laundering route through `reaction_elicit`, and a deferred import inside a function
    body, which `ast.walk` reaches. No count is quoted here on purpose: the first
    version of this paragraph said "18", a re-read counted 25, a third counted 30, and a
    number in prose that three readers disagree about is a number nothing checks. The
    fixtures are the record. What survives is deliberate evasion — a dynamic
    `importlib.import_module`, `__import__`, `sys.modules[...]`, or a corpus path
    assembled from parts — which this check is not built to stop: it is admission
    lint against the two-line edit, the same posture
    `_literal_body_violations` takes toward a credential key. Said out loud here so
    the ceiling is a known property rather than a hole somebody finds later.
    """
    findings: list[dict[str, str]] = []
    absent: list[str] = []
    permitted = set(STIMULUS_STRUCTURAL_DEPENDENCIES)
    out_of_bounds = {
        f"integral.{name}" for name in serving_path_modules(src_dir) if name not in permitted
    }
    for name in EXEMPT_CORPUS_READERS:
        path = src_dir / f"{name}.py"
        if not path.is_file():
            absent.append(name)
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            reached: set[str] = set()
            if isinstance(node, ast.ImportFrom):
                module = _imported_module(node)
                if module in out_of_bounds:
                    reached.add(module)
                elif module == "integral":
                    reached |= {
                        f"integral.{alias.name}"
                        for alias in node.names
                        if f"integral.{alias.name}" in out_of_bounds
                    }
            elif isinstance(node, ast.Import):
                reached |= {alias.name for alias in node.names if alias.name in out_of_bounds}
            findings.extend(
                {
                    "module": name,
                    "reason": f"imports {reach}, which is on the serving path and is not "
                    f"one of {sorted(permitted)}",
                }
                for reach in sorted(reached)
            )
    return findings, absent


def stimulus_split_findings(
    labelled_path: Path = DEFAULT_LABELLED_ADS,
) -> tuple[list[dict[str, str]], list[dict[str, str]], int, int]:
    """Bound 3: every advert reachable as a stimulus that the evaluation split also
    holds, every corpus text carried by more than one row, and the size of each side.

    The owner's exemption is conditional — *"the stimuli must come from a split disjoint
    from the evaluation set"* — and this is the condition, measured over the store rather
    than asserted at the moment a candidate is shown something. `reaction_elicit` already
    refuses an evaluation-split ad per call; that check fires only for an advert somebody
    actually drew. This one fires over the whole reachable pool, before anyone draws.

    **The bridge is the text, not the split field.** `corpus_stimuli` selects on
    `split == "elicitation"`, but an offer is addressed by `compute_offer_id(text)` —
    the same function `reaction_elicit` and the T9 gate use, deliberately not a second
    implementation of the same hash. Two rows with different corpus ids and identical
    text land on one offer id, so a row *marked* elicitation can carry an evaluation
    advert's content and contaminate a metric quoted as held-out. That is the fail-open
    direction and it is the one this counts.

    `corpus_text_collisions` is the same defect one step earlier: a text under two ids is
    the mechanism by which a future re-split puts one copy either side. It is reported
    separately rather than folded in, because a collision inside one split is not yet a
    contamination and a reader must be able to tell the two apart.

    Returns `(overlaps, collisions, stimulus_pool, evaluation_pool)`. The two sizes are
    what `MINIMUM_STIMULUS_POOL` and `MINIMUM_EVALUATION_POOL` are floors on: a zero from
    an empty pool and a zero from a disjoint one are the same number and not the same
    verdict.
    """
    rows = _read_rows(labelled_path)
    evaluation: dict[str, str] = {}
    stimulus: dict[str, str] = {}
    by_text: dict[str, list[str]] = {}
    seen_ids: set[str] = set()
    for row in rows:
        identifier = str(row.get("id") or "?")
        offer_id = compute_offer_id(str(row.get("text") or ""))
        if identifier not in seen_ids:
            by_text.setdefault(offer_id, []).append(identifier)
            seen_ids.add(identifier)
        if row.get("split") == "evaluation":
            evaluation.setdefault(offer_id, identifier)
        elif row.get("split") == "elicitation":
            stimulus.setdefault(offer_id, identifier)

    overlaps = [
        {
            "row": stimulus[offer_id],
            "where": "labelled",
            "reason": f"reachable as a stimulus, and its text is also evaluation-split row "
            f"{evaluation[offer_id]} — a reaction to it contaminates every metric "
            f"computed over the evaluation split",
        }
        for offer_id in sorted(set(stimulus) & set(evaluation))
    ]
    collisions = [
        {
            "row": ", ".join(sorted(ids)),
            "where": "labelled",
            "reason": "these rows carry byte-identical text, so a re-split can place one "
            "copy in each half",
        }
        for _, ids in sorted(by_text.items())
        if len(ids) > 1
    ]
    return overlaps, collisions, len(stimulus), len(evaluation)


def measure_provenance(
    raw_path: Path = DEFAULT_RAW_ADS,
    labelled_path: Path = DEFAULT_LABELLED_ADS,
    draws_path: Path = DEFAULT_DRAWS,
    src_dir: Path = DEFAULT_SRC_DIR,
) -> dict[str, Any]:
    """T98's gate reading: rows the declared draws do not account for, serving-path
    modules that read the corpus, and the bounds on the one exemption to that ban."""
    faults, rows_examined = provenance_faults(raw_path, labelled_path, draws_path)
    findings, absent = serving_path_findings(src_dir)
    exempt_findings, exempt_absent = exempt_reader_findings(src_dir)
    overlaps, collisions, stimulus_pool, evaluation_pool = stimulus_split_findings(labelled_path)
    scanned = len(serving_path_modules(src_dir)) - len(absent)

    # Two verdicts wear the same word and must not share an exit code. A scan that
    # *could not run* — a serving-path module absent from the tree — is untrusted,
    # and `make evidence` records that as "unmeasured (recorded)" and continues. A
    # scan that ran, counted, and came back **under a floor** is a finding, and
    # exit 3 would let `make evidence` sail past it: a corpus shrinking below
    # MINIMUM_CORPUS_ROWS would leave the gate green (#307 review). They are kept in
    # separate lists so the exit code reads a structure rather than grepping the
    # message — the reason text is for a person, and a code path that parses it
    # breaks the next time somebody rewords it.
    untrusted: list[str] = []
    breached: list[str] = []
    if rows_examined < MINIMUM_CORPUS_ROWS:
        breached.append(
            f"{rows_examined} corpus rows examined, below the {MINIMUM_CORPUS_ROWS} floor"
        )
    if absent:
        untrusted.append(f"serving-path modules not found: {', '.join(absent)}")
    if exempt_absent:
        untrusted.append(f"exempt corpus readers not found: {', '.join(exempt_absent)}")
    if scanned < MINIMUM_SERVING_MODULES:
        breached.append(
            f"{scanned} serving-path modules scanned, below the {MINIMUM_SERVING_MODULES} floor"
        )
    # Both sides of the disjointness reading, because zero overlaps is what an empty
    # stimulus pool and an empty evaluation split each produce. A floor on one alone
    # leaves the other as a vacuous pass over the exemption's own condition.
    if stimulus_pool < MINIMUM_STIMULUS_POOL:
        breached.append(
            f"{stimulus_pool} adverts reachable as stimuli, below the {MINIMUM_STIMULUS_POOL} floor"
        )
    if evaluation_pool < MINIMUM_EVALUATION_POOL:
        breached.append(
            f"{evaluation_pool} evaluation-split adverts compared, below the "
            f"{MINIMUM_EVALUATION_POOL} floor"
        )
    unmeasured = breached + untrusted

    measured: dict[str, Any] = {
        # The declared gate's key, and it is the sum because `gate_evidence.py` asserts
        # exactly one. T98 states two properties and the block declared only the first,
        # so a serving-cache regression — the half the task is named after — passed
        # T98's own gate with `corpus_rows_without_a_draw_specification` still at zero.
        # Every count stays below, because a violation you cannot name is one nobody can
        # act on, and a sum whose components are not reported is a zero that hides what
        # it is made of — the defect this repository has now caught four times. Five
        # components, five keys, and the sum is what makes any one of them fail the
        # gate. The arithmetic itself is under test component by component, because
        # asserting it over the real corpus — where all five are zero — holds for any
        # subset of them, and `_main` now decides its exit code from this key alone.
        "corpus_measurement_set_violations": (
            len(faults) + len(findings) + len(exempt_findings) + len(overlaps) + len(collisions)
        ),
        "corpus_rows_without_a_draw_specification": len(faults),
        "serving_path_corpus_reads": len(findings),
        "exempt_reader_serving_imports": len(exempt_findings),
        "stimulus_pool_evaluation_overlaps": len(overlaps),
        "corpus_text_collisions": len(collisions),
        "gate_status": "unmeasured" if unmeasured else "measured",
        "floor_breaches": len(breached),
        # The reasons, not only the count. `unmeasured_reason` joins breaches and
        # untrusted readings into one string, so a fixture asserting a message is in
        # *that* proves only that the message exists somewhere — not that it was
        # classified as a breach, which is the whole distinction (a breach exits 1, an
        # untrusted reading exits 3 and `make evidence` continues). Moving the
        # corpus-row floor from `breached` to `untrusted` left the suite green until
        # this key existed to assert against (#307 second-reader F1).
        "floor_breach_reasons": breached,
        "corpus_rows_evaluated_at_least": MINIMUM_CORPUS_ROWS,
        "serving_path_modules_scanned_at_least": MINIMUM_SERVING_MODULES,
        # The exemption's reach, as a measured quantity rather than a claim: how many
        # adverts `reaction_elicit` can put in front of a candidate. A floor, not the
        # count of the day (T100), so a re-drawn corpus does not rewrite the record —
        # and a pool that has collapsed below it makes the disjointness zero
        # `unmeasured` instead of clean.
        "stimulus_reachable_adverts_at_least": MINIMUM_STIMULUS_POOL,
        "evaluation_adverts_compared_at_least": MINIMUM_EVALUATION_POOL,
        "exempt_corpus_readers": list(EXEMPT_CORPUS_READERS),
        "declared_draws": sorted(load_draws(draws_path)),
        "faults": faults,
        "serving_path_findings": findings,
        "exempt_reader_findings": exempt_findings,
        "stimulus_split_findings": overlaps + collisions,
    }
    if unmeasured:
        measured["unmeasured_reason"] = "; ".join(unmeasured)
    return measured


def write_provenance_evidence(
    evidence: Path = DEFAULT_T98_EVIDENCE_PATH,
    raw_path: Path = DEFAULT_RAW_ADS,
    labelled_path: Path = DEFAULT_LABELLED_ADS,
    draws_path: Path = DEFAULT_DRAWS,
    src_dir: Path = DEFAULT_SRC_DIR,
) -> dict[str, Any]:
    """Measure and record `status/evidence/T98.json`."""
    measured = measure_provenance(raw_path, labelled_path, draws_path, src_dir)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _report(lines: Sequence[str]) -> None:
    for line in lines:
        print(line, file=sys.stderr)


def _main(argv: list[str]) -> int:
    """`python -m integral.corpus_scope [path]` → D-1's and T98's gate evidence."""
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    provenance = write_provenance_evidence()
    print(json.dumps({**measured, **provenance}, ensure_ascii=False))

    _report([f"{m['document']}: {m['reason']}" for m in measured["mismatches"]])
    _report([f"{f['where']} {f['row']}: {f['reason']}" for f in provenance["faults"]])
    _report([f"{f['module']}: {f['reason']}" for f in provenance["serving_path_findings"]])
    # The exempt reader's own breaches and the disjointness findings are two of the five
    # components of `corpus_measurement_set_violations`, and this reported neither and
    # exited 0 over both — a contaminated stimulus pool printed nothing and passed
    # (#307 second-reader F3). `make host-gate` still caught it through the evidence
    # diff, but only while the evidence was not being regenerated in the same change,
    # which is exactly the reseed flow this task creates.
    _report([f"{f['module']}: {f['reason']}" for f in provenance["exempt_reader_findings"]])
    _report(
        [f"{f['where']} {f['row']}: {f['reason']}" for f in provenance["stimulus_split_findings"]]
    )

    # The declared gate key, not a hand-listed subset of what it sums. A subset is how
    # two of five components went unreported; naming the sum means a sixth component
    # added later cannot be forgotten here.
    if (
        measured["mismatches"]
        or provenance["corpus_measurement_set_violations"]
        or provenance["floor_breaches"]
    ):
        return 1
    # Exit 3 is `make evidence`'s "unmeasured": the check ran and found it cannot be
    # scored, which is a verdict to record rather than a failure to stop on. A floor
    # breach is *not* that — the scan ran and came back short — so it exits 1 above,
    # because `Makefile:58-70` maps 3 to "unmeasured (recorded)" and continues.
    return 3 if provenance["gate_status"] == "unmeasured" else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
