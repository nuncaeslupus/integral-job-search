"""T203 — the topics a candidate ruled out reach a real sourcing round.

`integral.sourcing_exclusions` (T90) was correct and tested and imported by
nothing on the serving path, so adverts on a topic a candidate had ruled out in
words still reached his list (#561). `sourcing.source` now removes them; this
module is the measurement that says so over a **real** `source()` run, serving
real adverts from the committed corpus against exclusions recorded with
`record_exclusion`, then reading the offer store back.

It is a corpus reader, so it is deliberately **not** on the serving path:
`sourcing_exclusions` starts it as a subprocess (`python -m
integral.sourcing_exclusions` is the task's gate) and never imports it.

Not an `EVIDENCE_SOURCES` entry, on purpose: T150 requires every registered
source to be moved by a mutation of the tree, and this measurement reads a fixed
corpus, so registering it would fail that rule for a reason that is no defect.
`floor_sweep`'s `MINIMUM_FLOORS_SWEPT` carries the same precedent.

Known ceiling, stated rather than solved: an exclusion is matched as words, so a
figurative use of the topic ("first line of defense") in an advert on some other
subject is removed by a candidate who ruled out defence. That trades a wrongly
removed offer for a wrongly shown one, and the removal is recorded and visible in
the round's `EXCLUDED` line, so it can be seen and corrected.
"""

from __future__ import annotations

import html
import json
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

from integral.corpus_scope import DEFAULT_LABELLED_ADS
from integral.identity import ProfileStore
from integral.sourcing_exclusions import (
    Candidate,
    Exclusion,
    candidate_of,
    record_exclusion,
    ruled_out_by,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T203.json"

#: What a candidate ruled out, in generic words: the `about`, what they said,
#: and the other surface forms the recording session supplies in Spanish,
#: English and Catalan (`Exclusion.terms`). Not a blocklist the tool owns: it is
#: the fixture that stands in for one recorded statement, and **each row must
#: trip something in the corpus** — asserted as `exclusions_never_tripped == 0`,
#: so a row a broken matcher can no longer find turns the gate red.
LIVE_ROUND_EXCLUSIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("sector:banca", "no me interesa la banca", ("banking", "bank", "bancari")),
    ("sector:fintech", "ya tuve bastante de fintechs", ()),
    (
        "sector:e-commerce",
        "no me gusta el e-commerce",
        ("comercio electronico", "comerc electronic"),
    ),
    (
        "topic:comprar y vender",
        "no me gusta todo lo que sea comprar y vender",
        ("compraventa", "buying and selling", "marketplace"),
    ),
    ("sector:defensa", "defensa no", ("defense", "defence")),
    (
        "sector:ciberseguridad",
        "no me interesa la ciberseguridad",
        ("cybersecurity", "ciberseguretat"),
    ),
)

# Denominators, asserted so a zero over an empty population is `unmeasured`.
# Each floor has its own comment: the sweep reads one marker per floor.

#: Served adverts that trip an exclusion. 28 on the committed corpus today; the
#: floor sits below that so a corpus refresh is not a red gate while a scan that
#: served almost nothing still is.
#: arsenal-floor-margin: MINIMUM_EXCLUDED_SERVED value=20
MINIMUM_EXCLUDED_SERVED = 20

#: Served adverts that trip none — 25 today, the controls that must arrive, among
#: them adverts holding a topic's letters without its word (`bancarrota`).
#: arsenal-floor-margin: MINIMUM_UNEXCLUDED_SERVED value=20
MINIMUM_UNEXCLUDED_SERVED = 20

#: Distinct exclusions that tripped at least one served advert. A literal, not
#: `len(LIVE_ROUND_EXCLUSIONS)`: a bound derived from what it bounds never
#: fires. The exact claim, that **every** row trips, is the separate metric
#: `exclusions_never_tripped`.
#: arsenal-floor-margin: MINIMUM_EXCLUSIONS_TRIPPED value=6
MINIMUM_EXCLUSIONS_TRIPPED = 6

_PER_EXCLUSION = 8
_CONTROL_CAP = 25
_CORPUS_QUERY = "engineer"


def _plainly(text: str) -> str:
    """Accent-folded, lowercased. Deliberately *not* `matches`: it picks the
    adverts to serve, and choosing the population with the function under test
    would let a broken `matches` shrink its own denominator."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def measure_live_round(corpus: Path = DEFAULT_LABELLED_ADS) -> dict[str, Any]:
    """`stated_exclusions_not_applied_to_a_live_round`, over the real path.

    Serves real adverts (`corpus/labelled/ads.jsonl`) through `sourcing.source`
    against exclusions recorded with `record_exclusion`, then reads the offer
    store. Four counts, each aimed at one way the wiring fails:

    * `stated_exclusions_not_applied_to_a_live_round` — an offer that trips an
      exclusion is **in the store**. The call is missing, or the producer's
      rows are never read.
    * `unexcluded_offers_removed` — an advert tripping nothing did **not**
      arrive. The remedy over-reaches into #552's over-rejection.
    * `removals_not_reported` — what was left out differs from what the
      outcomes say was left out. A silent removal is the resurfacing's mirror.
    * `exclusions_never_tripped` — a fixture row that matched **no** advert the
      corpus says it applies to. The matcher is broken for that row (a facet, a
      hyphen, an ending) and the other rows keep the run green without it.
    """
    from integral.candidate import Aim, CandidateConstraints, Location, Reach
    from integral.connectors import ListRequest
    from integral.identity import create_profile
    from integral.offers import load_offer
    from integral.robots import Robots
    from integral.sourcing import _FLOOD_CONNECTOR, GLOBAL, Response, source

    exclusions = tuple(
        Exclusion(about=about, stated_at_cycle=1, words=words, terms=terms)
        for about, words, terms in LIVE_ROUND_EXCLUSIONS
    )
    ads = [json.loads(line) for line in corpus.read_text(encoding="utf-8").splitlines() if line]

    def says(ad: dict[str, Any], exclusion: Exclusion) -> bool:
        haystack = _plainly(f"{ad.get('title') or ''} {ad.get('company') or ''} {ad['text']}")
        return any(_plainly(w) in haystack for w in (exclusion.value, *exclusion.terms))

    # Served **per exclusion**, so every row has adverts of its own: pooled, one
    # frequent topic fills the cap and a row nothing serves goes unnoticed.
    served: list[dict[str, Any]] = []
    for exclusion in exclusions:
        served += [ad for ad in ads if says(ad, exclusion) and ad not in served][:_PER_EXCLUSION]
    served += [ad for ad in ads if not any(says(ad, e) for e in exclusions)][:_CONTROL_CAP]

    cards = "".join(
        f'<div class="job"><a href="/jobs/{html.escape(ad["id"])}">x</a>'
        f'<span class="title">{html.escape(ad.get("title") or ad["id"])}</span>'
        f'<span class="company">{html.escape(ad.get("company") or "-")}</span>'
        f'<span class="text">{html.escape(ad["text"])}</span></div>'
        for ad in served
    )
    page = f"<html><body>{cards}</body></html>"

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        directory = root / "connectors"
        package = directory / "corpus_en"
        package.mkdir(parents=True)
        (package / "connector.yaml").write_text(
            _FLOOD_CONNECTOR.replace("SITE", "corpus").replace(
                "jobs?page={page}", "jobs?q={query}&page={page}"
            ),
            encoding="utf-8",
        )
        (package / "meta.yaml").write_text(
            f"site: corpus.integral.local\ncountry: {GLOBAL}\nlanguage: en\n", encoding="utf-8"
        )
        create_profile(root, "Fixture", handle="fixture", language="es", fiction=True)
        store = ProfileStore(root, "fixture")
        for exclusion in exclusions:
            record_exclusion(store, exclusion)

        def fetch(request: ListRequest) -> Response:
            return Response(200, page)

        run = source(
            store,
            CandidateConstraints(
                location=Location(
                    state="stated",
                    country="ES",
                    accepts_onsite_in_country=True,
                    commutable_regions=("Barcelona",),
                ),
                reach=Reach(state="stated", modes=("remote",)),
            ),
            Aim(state="stated", terms=(_CORPUS_QUERY,)),
            fetch=fetch,
            at="2026-01-01T00:00:00+00:00",
            directory=directory,
            robots=Robots(fetch=lambda url: "User-agent: *\nAllow: /\n"),
        )
        stored = {
            offer.url: offer
            for path in Path(store.path("offers")).glob("*.json")
            if not path.name.startswith("_")
            for offer in (load_offer(store, path.stem),)
        }

    by_url = {f"https://corpus.integral.local/jobs/{ad['id']}": ad for ad in served}

    def tripped(ad: dict[str, Any]) -> tuple[str, ...]:
        return ruled_out_by(
            Candidate(
                offer_id=ad["id"],
                title=ad.get("title"),
                text=ad["text"],
                employer=ad.get("company"),
            ),
            exclusions,
        )

    excluded_served = [url for url, ad in by_url.items() if tripped(ad)]
    unexcluded_served = [url for url in by_url if url not in excluded_served]
    not_applied = [
        url for url, offer in stored.items() if ruled_out_by(candidate_of(offer), exclusions)
    ]
    removed_unexcluded = [url for url in unexcluded_served if url not in stored]
    reported = sum(outcome.excluded for outcome in run.outcomes)
    removed = len(by_url) - len(stored)
    tripped_abouts = {about for url in excluded_served for about in tripped(by_url[url])}
    never_tripped = [e.about for e in exclusions if e.about not in tripped_abouts]

    failures: list[str] = []
    if len(excluded_served) < MINIMUM_EXCLUDED_SERVED:
        failures.append(f"only {len(excluded_served)} served adverts trip an exclusion")
    if len(unexcluded_served) < MINIMUM_UNEXCLUDED_SERVED:
        failures.append(f"only {len(unexcluded_served)} served adverts trip none")
    if len(tripped_abouts) < MINIMUM_EXCLUSIONS_TRIPPED:
        failures.append(f"only {len(tripped_abouts)} exclusions tripped anything")
    measured: dict[str, Any] = {
        "stated_exclusions_not_applied_to_a_live_round": len(not_applied),
        "unexcluded_offers_removed": len(removed_unexcluded),
        "removals_not_reported": abs(removed - reported),
        "exclusions_never_tripped": len(never_tripped),
        "excluded_offers_served_at_least": MINIMUM_EXCLUDED_SERVED,
        "unexcluded_offers_served_at_least": MINIMUM_UNEXCLUDED_SERVED,
        "exclusions_tripped_at_least": MINIMUM_EXCLUSIONS_TRIPPED,
        "gate_status": "unmeasured" if failures else "measured",
        "failures": failures,
        "never_tripped": never_tripped,
        "not_applied": not_applied,
        "unexcluded_removed": removed_unexcluded,
        # T229. A `skill:` exclusion holds only on a step-8 reading, and a served
        # corpus advert has none, so this round cannot apply it. Said, so a
        # round carrying one never reads as having checked the skill.
        "skill_exclusions_not_applied": [
            e.about for e in exclusions if e.facet.strip().lower() == "skill"
        ],
        "_observed": {
            "excluded_served": len(excluded_served),
            "unexcluded_served": len(unexcluded_served),
            "exclusions_tripped": len(tripped_abouts),
            "stored": len(stored),
            "stored_urls": sorted(stored),
            "reported_excluded": reported,
        },
    }
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.exclusion_live_round [path]` → `status/evidence/T203.json`.

    Exit 0 measured and all four metrics zero, 1 a metric is not, 3 unmeasured.
    """
    measured = measure_live_round()
    committed = {k: v for k, v in measured.items() if not k.startswith("_")}
    evidence = Path(argv[1]) if len(argv) > 1 else EVIDENCE_PATH
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(committed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(committed, ensure_ascii=False))
    for failure in measured["failures"]:
        print(failure, file=sys.stderr)
    if (
        measured["stated_exclusions_not_applied_to_a_live_round"]
        or measured["unexcluded_offers_removed"]
        or measured["removals_not_reported"]
        or measured["exclusions_never_tripped"]
    ):
        return 1
    if measured["gate_status"] == "unmeasured":
        print("UNMEASURED — the served population was too small to say.", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
