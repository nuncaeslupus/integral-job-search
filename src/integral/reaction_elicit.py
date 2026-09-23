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

## Why this module may read the corpus at all

T98 bans serving a candidate from the corpus: a stored advert is stale by
definition, and answering a search from stale rows is what let one live session
return three adverts and call the market exhausted. This module reads the corpus
anyway, and the owner ruled on 2026-09-04 that it is exempt — *"reacting to an
advert can never contaminate the labels it is scored against"*. A stimulus is
measurement, not a search result.

The exemption is bounded, and the bounds are measured in
`integral.corpus_scope` — `EXEMPT_CORPUS_READERS` and the comment above it are
where the ruling and its three conditions are written down. Two of them
constrain this file directly: it may import `integral.offers` and
`integral.lifecycle` and nothing else on the serving path, and the pool it draws
from must stay disjoint from the evaluation split. Both are counted into
`corpus_measurement_set_violations`, so widening this module into general
serving fails T98's gate rather than passing quietly.

## Ceilings, stated rather than implied

- The permitted set is **derived from the shipped connector packages**, not a
  live robots.txt fetch. A package is evidence that somebody adjudicated the
  board (`connectors/robots-adjudications.yaml`) and built against it; it is
  not evidence that the adjudication is current. What the derivation buys is
  that it cannot go stale *relative to the connectors* — which the hand-written
  list it replaces had done three separate ways: a board keyed under a name no
  offer carries, a board with no connector at all, and a board refused on a
  ruling its own package retracts. Upgrade path is still a live check
  (`integral.robots`), which is a fetch and so cannot sit inside a validator.
- The advert host is checked against the connector's **list** host with one
  label of slack, because an ATS lists and serves from different hosts of the
  same site. `_site_domain` states that rule and its ceiling.
- Provenance proves the text was **fetched**, never that the employer wrote it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from integral.harness import DEFAULT_STORE_PATH, LabelledAd, load_store
from integral.identity import ProfileStore, create_profile
from integral.lifecycle import collect_offer
from integral.offers import Offer, compute_offer_id
from integral.profile import EvidenceLog, EvidenceSubject

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T9.json"

#: A corpus-drawn stimulus is not a live fetch and carries no url of its own.
CORPUS_SOURCE = "corpus"

#: Boards refused on their own robots.txt, named rather than merely omitted so
#: that adding one back is a decision someone has to argue with a test about.
#:
#: `tecnoempleo` was here and has been removed, because the ruling it encoded
#: was retracted before this line was written and nothing carried the
#: retraction here. `connectors/ruled-out.yaml` lists the board under
#: `corrected` — *"a Claude-agent group does not bind integral-job-search/0.1"*
#: — `connectors/tecnoempleo_es/connector.yaml` opens with that retraction in
#: full, and `robots-adjudications.yaml` carries an adjudication against the
#: package. A pinned list that outlives its own ledger is the defect #558 is
#: about, one board rather than the whole set.
#:
#: `remoteok` stays, and it has no connector package, so the check below would
#: refuse it anyway — this line is what refuses it on the day somebody writes
#: one. What the ledger actually refuses is its `?action=get_jobs` endpoint
#: under `restated_for_every_named_agent`, not its listing pages.
BLOCKED_SOURCES = frozenset({"remoteok"})

CONNECTORS_DIR = _REPO_ROOT / "connectors"
CONNECTOR_FILENAME = "connector.yaml"


#: One label of a hostname, per RFC 1123 §2.1: letters, digits and interior
#: hyphens. Written as a grammar the whole label must match — an allowlist
#: applied as a *deletion filter* welds decoration onto the thing it filters,
#: which is how CLAUDE.md's `resolve_identity` cleared five review rounds while
#: reading `nuncaeslupus (OWNER)` as somebody other than `nuncaeslupus`.
_LABEL_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?")

#: RFC 2606 §2 reserves these for documentation and testing, so a host under one
#: of them resolves nowhere and the package listing from it is a worked example
#: rather than a board anyone can be shown an advert from. Derived from the RFC
#: rather than by naming `examplejobs`, so the next committed example is out too.
RESERVED_TLDS = frozenset({"test", "example", "invalid", "localhost"})


def _hostname(url: str) -> str | None:
    """The host a url names, or `None` when it does not validly name one.

    A **validator, not a transform** — the distinction CLAUDE.md's
    `resolve_identity` section took five review rounds to reach. Anything that
    would have to be *repaired* into a hostname is refused instead, because the
    repair is the step that turns somebody else's host into one of ours.
    Measured on this module's own predecessor: `https://evil.test\\.remotive.com/ad`
    and `https://.remotive.com/ad` both end with a permitted host's spelling,
    are neither of them that host, and both were accepted.

    `urlparse().hostname` rather than `.netloc`, which is not a host — it
    carries userinfo and a port. `usajobs_en` serves adverts as
    `https://www.usajobs.gov:443/job/…` (`sourcing._origin` exists for that
    spelling), so reading the netloc refused a real board's every advert, while
    `https://permitted.example@evil.test/` read as one long host that ends the
    right way.
    """
    try:
        host = urlparse(url).hostname
    except ValueError:
        return None
    if not host:
        return None
    host = host.rstrip(".")  # an absolutely-rooted host is the same host
    labels = host.split(".")
    if len(labels) < 2 or any(not _LABEL_RE.fullmatch(label) for label in labels):
        return None
    return host


def connector_hosts(directory: Path = CONNECTORS_DIR) -> dict[str, frozenset[str]]:
    """Each shipped connector's site name against every host it may serve from.

    A board with a connector package is a board somebody adjudicated robots for
    and built against (`connectors/robots-adjudications.yaml`); a board without
    one is a board nobody checked. So the permitted set is *derived* from the
    packages rather than hand-listed beside them — which is the whole of #558:
    reactions were reaching four named boards while the candidate's store held
    offers from twenty-four, and adding a connector was two edits instead of
    one. The hand-written map had also drifted: it keyed Manfred as `manfred`
    while every offer that board has ever produced carries `getmanfred`, and it
    kept `feinaactiva`, which has no connector and so can produce no live offer
    at all.

    An ATS lists from one host and serves its adverts from another —
    `connectors/ashby_en` lists from `api.ashbyhq.com` and its payload returns
    urls on `jobs.ashbyhq.com` — so the list host alone refused every ATS advert
    there is, which was the other half of #558. Those hosts come from the
    package's **`serves_from`** declaration and are never inferred from the list
    host's domain. Inferring them is fail-open, and was measured to be: one
    label of slack off `boards-api.greenhouse.io` admits `boards.greenhouse.io`,
    a host `connectors/ruled-out.yaml` refuses outright (*"the `*` group
    disallows the embedded job-board path"*, checked 2026-08-30). A declaration
    cannot reach it, because nobody declared it.

    Read out of the YAML rather than through `integral.connectors`, because
    T98 bounds what this module may reach on the serving path
    (`corpus_scope.EXEMPT_CORPUS_READERS`) and three fields of one file is a
    smaller dependency than the connector runtime.
    """
    hosts: dict[str, frozenset[str]] = {}
    for package in sorted(directory.glob(f"*/{CONNECTOR_FILENAME}")):
        declared = yaml.safe_load(package.read_text(encoding="utf-8"))
        site = declared.get("site")
        listed = _hostname((declared.get("list") or {}).get("url_pattern") or "")
        if not site or not listed:
            continue
        if listed.rsplit(".", 1)[-1] in RESERVED_TLDS:
            continue
        served = {_hostname(f"https://{host}") for host in declared.get("serves_from") or []}
        hosts[site] = frozenset({listed} | {host for host in served if host})
    return hosts


#: Where a live stimulus may come from, and which host its url must name.
SOURCE_HOSTS = connector_hosts()


def permitted_live_sources(hosts: Mapping[str, frozenset[str]] = SOURCE_HOSTS) -> frozenset[str]:
    """A board is permitted when it has a connector and is not one we are refused.

    Takes the host map rather than closing over the module's, because no board
    we are refused on ships a connector today — so on the shipped tree the
    subtraction is a no-op, and a test over the module constant passes whether
    or not it is there. It is not dead: `check_stimulus` refuses a blocked
    source before it ever reaches the permitted set, but `probe_elicitation`
    records that set verbatim, and a blocked board whose connector lands next
    week would be published there as permitted. The parameter is what lets a
    test hand this the tree that does not exist yet.
    """
    return frozenset(hosts) - BLOCKED_SOURCES


PERMITTED_LIVE_SOURCES = permitted_live_sources()


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
    if urlparse(offer.url).scheme != "https":
        raise ElicitationError(f"{offer.id}: a live stimulus must be fetched over https")
    permitted = SOURCE_HOSTS[offer.source]
    host = _hostname(offer.url)
    if host not in permitted:
        raise ElicitationError(
            f"{offer.id}: source {offer.source!r} serves its adverts from "
            f"{sorted(permitted)} — but the url names {host!r}, and the source and the "
            "url disagree about where this came from"
        )


def stimulus_from_ad(ad: LabelledAd, *, evaluation_ids: frozenset[str] | set[str]) -> Offer:
    """A corpus ad as a stimulus — elicitation split only.

    Refusing rather than filtering matters: `corpus_stimuli` below asks for a
    count, and a filter that quietly returns fewer looks exactly like a corpus
    that has run out.

    `evaluation_ids` is **required**, with no default. The split field is
    metadata about a row; the offer id is the ad's *text*. Two corpus rows with
    different ids and identical text land on the same offer id, so an ad marked
    `elicitation` can carry an evaluation ad's content — and `measure` would
    then report the breach only after the candidate had already reacted to it.
    A default of `frozenset()` would make this check vacuous for every caller
    that forgot it, which is the failure mode the check is here to prevent.
    """
    if ad.split != "elicitation":
        raise ElicitationError(
            f"{ad.id}: split is {ad.split!r} — an evaluation-split ad is what the ranking "
            "is scored against and can never be a stimulus (elicitation_eval_overlap == 0)"
        )
    offer_id = compute_offer_id(ad.text)
    if offer_id in evaluation_ids:
        raise ElicitationError(
            f"{ad.id}: marked {ad.split!r}, but its text is byte-identical to an "
            "evaluation-split ad — the ranking is scored against this content "
            "whatever this row is labelled"
        )
    return Offer(
        id=offer_id,
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
    evaluation = evaluation_offer_ids(ads)
    eligible = [ad for ad in ads if ad.split == "elicitation"]
    return [stimulus_from_ad(ad, evaluation_ids=evaluation) for ad in eligible[:count]]


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

    def must_refuse(label: str, because: str, attempt: Any) -> None:
        """A refusal counts only when the rule the label names is what refused.

        `because` is a fragment of the message that rule raises, and it is the
        whole difference between this probe and one that cannot fail. Every
        check here runs behind the ones before it, so a scenario aimed at a
        later rule is answered by an earlier one whenever the later rule is
        deleted — the refusal still arrives, the count is unmoved, and the
        mutant survives a green probe. Measured on `blocked_board`: emptying
        `BLOCKED_SOURCES` left that label recorded, because a board nobody
        ships a connector for is not a permitted source either.
        """
        try:
            attempt()
        except ElicitationError as refused:
            if because not in str(refused):
                raise AssertionError(
                    f"{label}: refused, but by another rule — expected a message carrying "
                    f"{because!r}, got {str(refused)!r}"
                ) from refused
            refusals.append(label)
        else:  # pragma: no cover - a passing probe never reaches this
            raise AssertionError(f"{label}: expected a refusal, none was raised")

    evaluation = evaluation_offer_ids(corpus)
    must_refuse(
        "evaluation_split_ad",
        "can never be a stimulus",
        lambda: stimulus_from_ad(corpus[1], evaluation_ids=evaluation),
    )
    live = Offer(
        id=compute_offer_id(text),
        source="remotive",
        url="https://remotive.com/ad/1",
        fetched_at=at,
        text=text,
        status="new",
    )
    must_refuse(
        "rewritten_text",
        "does not content-address this text",
        lambda: check_stimulus(live.model_copy(update={"text": other})),
    )
    must_refuse(
        "no_url",
        "must carry the url it was fetched from",
        lambda: check_stimulus(live.model_copy(update={"url": None})),
    )
    must_refuse(
        "no_fetched_at",
        "must carry fetched_at",
        lambda: check_stimulus(live.model_copy(update={"fetched_at": None})),
    )
    must_refuse(
        "blocked_board",
        "robots.txt disallows us on this board",
        lambda: check_stimulus(live.model_copy(update={"source": "remoteok"})),
    )
    must_refuse(
        "unchecked_board",
        "is not a permitted stimulus source",
        lambda: check_stimulus(live.model_copy(update={"source": "nobody"})),
    )
    must_refuse(
        "url_host_disagrees_with_source",
        "disagree about where this came from",
        lambda: check_stimulus(live.model_copy(update={"url": "https://unapproved.example/ad"})),
    )
    must_refuse(
        "plain_http",
        "must be fetched over https",
        lambda: check_stimulus(live.model_copy(update={"url": "http://remotive.com/ad/1"})),
    )
    # Four hosts that end with a permitted host's spelling and are not it. The
    # first two were ACCEPTED while this check read `netloc`; the third is what
    # a board that serves from its list host must not extend slack to; and
    # `boards.greenhouse.io` is the measured fail-open that a *derived* host set
    # admits — `connectors/ruled-out.yaml` refuses that host by name, while one
    # label of slack off `boards-api.greenhouse.io` reaches it.
    for label, forged in (
        ("url_host_is_a_backslash_away_from_the_source", "https://evil.test\\.remotive.com/ad"),
        ("url_host_has_an_empty_leading_label", "https://.remotive.com/ad"),
        ("url_host_merely_suffixed_with_the_source", "https://remotive.com.evil.test/ad"),
        ("url_host_is_an_undeclared_subdomain", "https://jobs.remotive.com/ad/1"),
    ):
        must_refuse(
            label,
            "disagree about where this came from",
            lambda url=forged: check_stimulus(live.model_copy(update={"url": url})),
        )
    must_refuse(
        "url_host_is_a_ledger_refused_sibling_of_the_list_host",
        "disagree about where this came from",
        lambda: check_stimulus(
            live.model_copy(
                update={
                    "source": "greenhouse",
                    "url": "https://boards.greenhouse.io/acme/jobs/1",
                }
            )
        ),
    )
    must_refuse(
        "worked_example_package_is_not_a_live_board",
        "is not a permitted stimulus source",
        lambda: check_stimulus(
            live.model_copy(
                update={"source": "examplejobs", "url": "https://www.examplejobs.test/ad/1"}
            )
        ),
    )
    accepted: list[str] = []

    def must_accept(label: str, offer: Offer) -> None:
        check_stimulus(offer)
        accepted.append(label)

    must_accept("board_advert_on_its_list_host", live)
    # A real board's real spelling, refused while this read `netloc`:
    # `usajobs_en` serves `https://www.usajobs.gov:443/job/…`, which is why
    # `sourcing._origin` fills the default port in.
    must_accept(
        "board_advert_carrying_an_explicit_default_port",
        live.model_copy(update={"url": "https://remotive.com:443/ad/1"}),
    )
    # The case #558 was filed for: an ATS lists from `api.ashbyhq.com` and
    # serves adverts from `jobs.ashbyhq.com`, so host equality refused every
    # one of the hundred such offers in the candidate store that filed it. The
    # serving host is DECLARED in each package's `serves_from`, never derived.
    for label, source, url in (
        ("ats_advert_on_a_declared_serving_host", "ashby", "https://jobs.ashbyhq.com/acme/1"),
        (
            "ats_advert_on_a_declared_regional_serving_host",
            "greenhouse",
            "https://job-boards.eu.greenhouse.io/acme/jobs/1",
        ),
        ("ats_advert_on_a_declared_serving_host_lever", "lever", "https://jobs.lever.co/acme/1"),
    ):
        must_accept(label, live.model_copy(update={"source": source, "url": url}))

    twinned = [
        corpus[0],
        corpus[1].model_copy(update={"text": text}),
    ]
    must_refuse(
        "duplicate_text_across_splits",
        "byte-identical to an evaluation-split ad",
        lambda: corpus_stimuli(1, corpus=twinned),
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
        # The scenarios are recorded by NAME and never also as a count. A count
        # of two lists sitting beside them in the same object cannot disagree
        # with them, so it corroborates nothing — and it is census-shaped, so
        # two branches each adding one scenario write the same number, merge
        # with no conflict, and land a record that is wrong about a tree
        # neither of them measured. Names collide loudly. `permitted_live_sources`
        # is kept for the same reason its own count is not: the list is the
        # record, and two branches shipping different connectors conflict.
        "refusals": sorted(refusals),
        "acceptances": sorted(accepted),
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
