"""T9 — reaction elicitation: where a stimulus comes from, and what it may not be.

Step 5 shows the candidate real adverts and records what they say about them.
Two things about that are load-bearing, and neither is safe as prose:

**The split.** No advert used to elicit preferences may be one the ranking is
later scored against. Share a single ad between the two and `rank_spearman`
(T20) measures memorisation, passes, and certifies a ranking that is worthless.
So `stimulus_from_ad` *refuses* an evaluation-split ad rather than skipping it —
a filter that silently drops one is indistinguishable from a filter that stopped
running.

**The provenance.** A stimulus is never invented. An imagined advert reads
plausibly and represents nothing; the same failure put eight wrong cues into the
dimension model, each with a gold example demonstrating its own error. T11's
offer id content-addresses the verbatim text, so "this is the ad that was
fetched" is checkable rather than trusted: rewrite the text and the id no longer
matches it.

`measure()` deliberately consults **neither** of those rules. It reads the
reaction rows the candidate's log actually holds, re-derives the evaluation ids
from the corpus text with the same content-addressing, and intersects the two.
A harness that constructs both sides of its own equality certifies nothing (the
lesson T46 paid for), so the number the gate reads is computed from evidence
that would still show a breach if every guard above were deleted.

## Ceilings, stated rather than implied

- The permitted-source list is a **pinned allowlist**, not a live robots.txt
  fetch. `tecnoempleo` and `remoteok` both `Disallow: /` for `ClaudeBot`, which
  was discovered after a connector had been built against one of them. A list
  makes adding a board a deliberate act; it does not make the list current.
  Upgrade path: assert `policy.robots_txt` from the connector package (T32).
- Provenance proves the text was **fetched**, never that the employer wrote it.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from integral.harness import DEFAULT_STORE_PATH, LabelledAd, load_store
from integral.identity import ProfileStore, create_profile
from integral.lifecycle import collect_offer
from integral.offers import Offer, compute_offer_id
from integral.profile import EvidenceLog, EvidenceSubject

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T9.json"

#: A corpus-drawn stimulus is not a live fetch and carries no url of its own.
CORPUS_SOURCE = "corpus"

#: Boards whose robots.txt permits us, checked before building against one.
PERMITTED_LIVE_SOURCES = frozenset(
    {"feinaactiva", "manfred", "remotive", "weworkremotely", "eures"}
)

#: Boards that name ClaudeBot with `Disallow: /`. Named, not merely omitted, so
#: that adding one back is a decision someone has to argue with a test about.
BLOCKED_SOURCES = frozenset({"tecnoempleo", "remoteok"})


class ElicitationError(Exception):
    """A stimulus that may not be shown, or a source that may not be used."""


def check_stimulus(offer: Offer) -> None:
    """Refuse anything that cannot show where it came from."""
    if offer.id != compute_offer_id(offer.text):
        raise ElicitationError(
            f"{offer.id}: id does not content-address this text — the text was rewritten "
            "after it was fetched, or the stimulus was invented"
        )
    if offer.source in BLOCKED_SOURCES:
        raise ElicitationError(f"{offer.source!r}: robots.txt disallows us on this board")
    if offer.source == CORPUS_SOURCE:
        return
    if offer.source not in PERMITTED_LIVE_SOURCES:
        raise ElicitationError(
            f"{offer.source!r} is not a permitted stimulus source — "
            f"permitted: {sorted(PERMITTED_LIVE_SOURCES)}"
        )
    if not offer.url:
        raise ElicitationError(
            f"{offer.id}: a live stimulus must carry the url it was fetched from"
        )
    if not offer.fetched_at:
        raise ElicitationError(f"{offer.id}: a live stimulus must carry fetched_at")


def stimulus_from_ad(ad: LabelledAd) -> Offer:
    """A corpus ad as a stimulus — elicitation split only.

    Refusing rather than filtering matters: `corpus_stimuli` below asks for a
    count, and a filter that quietly returns fewer looks exactly like a corpus
    that has run out.
    """
    if ad.split != "elicitation":
        raise ElicitationError(
            f"{ad.id}: split is {ad.split!r} — an evaluation-split ad is what the ranking "
            "is scored against and can never be a stimulus (elicitation_eval_overlap == 0)"
        )
    return Offer(
        id=compute_offer_id(ad.text),
        source=CORPUS_SOURCE,
        source_ref=ad.id,
        url=ad.source_url,
        fetched_at=ad.fetched_at or None,
        title=ad.title or None,
        company=ad.company or None,
        language=ad.language,
        text=ad.text,
        status="new",
    )


def stimulus_from_record(record: dict[str, Any]) -> Offer:
    """One live fetch's record as a stimulus — `tools/collect_ads.py`'s shape.

    A plain dict, deliberately: `integral.reaction_elicit` imports no part of the
    scraping stack, so this gate runs wherever the repo does and not only where
    the boards are reachable. The same reason `classify_family` lives in
    `integral.corpus` rather than in the collector (T25).

    The record's own `id` is discarded. A collector is free to key an ad however
    its board does; a stimulus is addressed by its text, and going through
    `compute_offer_id` here is what makes `check_stimulus` a real check rather
    than a comparison of the collector's id against itself.
    """
    text = record.get("text") or ""
    offer = Offer(
        id=compute_offer_id(text),
        source=str(record.get("source", "")),
        source_ref=record.get("id"),
        url=record.get("source_url"),
        fetched_at=record.get("fetched_at"),
        title=record.get("title") or None,
        company=record.get("company") or None,
        language=record.get("language"),
        text=text,
        status="new",
    )
    check_stimulus(offer)
    return offer


def corpus_stimuli(count: int, *, corpus: Sequence[LabelledAd] | None = None) -> list[Offer]:
    """The fallback source: the corpus's elicitation half, in store order."""
    ads = list(corpus) if corpus is not None else load_store(DEFAULT_STORE_PATH)
    eligible = [ad for ad in ads if ad.split == "elicitation"]
    return [stimulus_from_ad(ad) for ad in eligible[:count]]


def collect_stimuli(store: ProfileStore, offers: Iterable[Offer], *, at: str) -> list[str]:
    """Stimuli enter the offer store as ordinary `new` offers, via S5's one gate.

    Every stimulus is checked before *any* of them is written: a batch that
    would half-land leaves the candidate looking at adverts whose provenance
    nobody established.
    """
    batch = list(offers)
    for offer in batch:
        check_stimulus(offer)
    stored = []
    for offer in batch:
        collect_offer(store, offer, at=at)
        stored.append(offer.id)
    return stored


def evaluation_offer_ids(corpus: Sequence[LabelledAd]) -> set[str]:
    """The evaluation half, addressed the way an offer is addressed.

    The bridge is the **text**, not the corpus id: a stimulus that reached the
    store by some path this module never saw still hashes to the same value.
    """
    return {compute_offer_id(ad.text) for ad in corpus if ad.split == "evaluation"}


def reacted_offer_ids(store: ProfileStore) -> set[str]:
    """What was actually reacted to, read from the candidate's own log."""
    log = EvidenceLog(store)
    if not log.exists():
        return set()
    return {
        row.about.id
        for row in log.rows()
        if row.kind == "reaction" and row.about is not None and row.about.kind == "offer"
    }


def measure(*, store: ProfileStore, corpus: Sequence[LabelledAd] | None = None) -> dict[str, Any]:
    """`elicitation_eval_overlap` — reactions ∩ evaluation split, by text."""
    ads = list(corpus) if corpus is not None else load_store(DEFAULT_STORE_PATH)
    reacted = reacted_offer_ids(store)
    overlap = sorted(reacted & evaluation_offer_ids(ads))
    return {
        "elicitation_eval_overlap": len(overlap),
        "reactions_examined": len(reacted),
        "evaluation_ads": len(evaluation_offer_ids(ads)),
        "overlapping_offer_ids": overlap,
    }


def probe_elicitation() -> dict[str, Any]:
    """Every rule above, exercised — including one scenario built to breach it.

    The planted reaction is the point. Without it the recorded `0` is equally
    consistent with a measurement that cannot return anything else.
    """
    at = "2026-08-23T21:00:00+00:00"
    text = "Es busca cuiner/a per a restaurant a Girona. " * 12
    other = "Se busca dependiente para tienda en Lleida. " * 12
    corpus = [
        LabelledAd(
            id="ad-elic",
            language="ca",
            text=text,
            source_url="https://feinaactiva.gencat.cat/ad/1",
            source="feinaactiva",
            fetched_at=at,
            split="elicitation",
        ),
        LabelledAd(
            id="ad-eval",
            language="es",
            text=other,
            source_url="https://feinaactiva.gencat.cat/ad/2",
            source="feinaactiva",
            fetched_at=at,
            split="evaluation",
        ),
    ]

    refusals: list[str] = []

    def must_refuse(label: str, attempt: Any) -> None:
        try:
            attempt()
        except ElicitationError:
            refusals.append(label)
        else:  # pragma: no cover - a passing probe never reaches this
            raise AssertionError(f"{label}: expected a refusal, none was raised")

    must_refuse("evaluation_split_ad", lambda: stimulus_from_ad(corpus[1]))
    live = Offer(
        id=compute_offer_id(text),
        source="feinaactiva",
        url="https://feinaactiva.gencat.cat/ad/1",
        fetched_at=at,
        text=text,
        status="new",
    )
    must_refuse("rewritten_text", lambda: check_stimulus(live.model_copy(update={"text": other})))
    must_refuse("no_url", lambda: check_stimulus(live.model_copy(update={"url": None})))
    must_refuse(
        "no_fetched_at", lambda: check_stimulus(live.model_copy(update={"fetched_at": None}))
    )
    must_refuse(
        "blocked_board", lambda: check_stimulus(live.model_copy(update={"source": "tecnoempleo"}))
    )
    must_refuse(
        "unchecked_board", lambda: check_stimulus(live.model_copy(update={"source": "nobody"}))
    )

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        honest = ProfileStore(
            root, create_profile(root, "Honest Run", handle="honest", fiction=True).handle
        )
        stimulus = corpus_stimuli(1, corpus=corpus)[0]
        collect_stimuli(honest, [stimulus], at=at)
        EvidenceLog(honest).append(
            recorded_at=at,
            step="reactions",
            kind="reaction",
            text="Massa hores per aquest sou.",
            source="offer_reaction",
            about=EvidenceSubject(kind="offer", id=stimulus.id),
        )
        honest_reading = measure(store=honest, corpus=corpus)

        planted = ProfileStore(
            root, create_profile(root, "Planted Run", handle="planted", fiction=True).handle
        )
        EvidenceLog(planted).append(
            recorded_at=at,
            step="reactions",
            kind="reaction",
            text="Este sí me interesa.",
            source="offer_reaction",
            about=EvidenceSubject(kind="offer", id=compute_offer_id(other)),
        )
        planted_reading = measure(store=planted, corpus=corpus)

    return {
        "elicitation_eval_overlap": honest_reading["elicitation_eval_overlap"],
        "overlap_detected_when_planted": planted_reading["elicitation_eval_overlap"],
        "reactions_examined": honest_reading["reactions_examined"],
        "refusals": sorted(refusals),
        "scenarios": len(refusals) + 2,
        "permitted_live_sources": sorted(PERMITTED_LIVE_SOURCES),
        "blocked_sources": sorted(BLOCKED_SOURCES),
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    probed = probe_elicitation()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(probed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return probed


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", nargs="?", default=str(DEFAULT_EVIDENCE_PATH), type=Path)
    args = parser.parse_args(argv)
    probed = write_evidence(args.evidence)
    print(f"elicitation_eval_overlap: {probed['elicitation_eval_overlap']}")
    print(f"overlap_detected_when_planted: {probed['overlap_detected_when_planted']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv[1:]))
