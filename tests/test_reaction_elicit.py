"""T9 — where a stimulus may come from, and what it may not be.

The gate is `elicitation_eval_overlap == 0`: no advert used to elicit
preferences is ever one the ranking is later scored against. Without the split,
`rank_spearman` (T20) measures memorisation and passes while the ranking is
worthless.

Two rules protect that, and both are tested here rather than asserted in prose:
the selector refuses the evaluation split, and the measurement that says so
reads the *recorded reactions* and re-derives the evaluation ids from the corpus
text — it never asks the selector what it did.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from integral.harness import LabelledAd, Split
from integral.identity import ProfileStore, create_profile
from integral.offers import Offer, compute_offer_id, load_offer
from integral.profile import EvidenceLog, EvidenceSubject
from integral.reaction_elicit import (
    BLOCKED_SOURCES,
    CONNECTOR_FILENAME,
    CONNECTORS_DIR,
    CORPUS_SOURCE,
    PERMITTED_LIVE_SOURCES,
    SOURCE_HOSTS,
    ElicitationError,
    _site_domain,
    check_stimulus,
    collect_stimuli,
    corpus_stimuli,
    evaluation_offer_ids,
    measure,
    stimulus_from_ad,
)

_AT = "2026-08-23T21:00:00+00:00"
_TEXT = "Buscamos cocinero para restaurante en Girona. " * 12


def _ad(ad_id: str, split: Split, text: str = _TEXT) -> LabelledAd:
    return LabelledAd(
        id=ad_id,
        language="es",
        text=text,
        source_url="https://feinaactiva.gencat.cat/ad/1",
        source="feinaactiva",
        fetched_at=_AT,
        split=split,
    )


def _live_offer(text: str = _TEXT, **over: object) -> Offer:
    fields: dict[str, object] = {
        "id": compute_offer_id(text),
        "source": "remotive",
        "url": "https://remotive.com/ad/1",
        "fetched_at": _AT,
        "text": text,
        "status": "new",
    }
    fields.update(over)
    return Offer(**fields)  # type: ignore[arg-type]


def _store(tmp_path: Path) -> ProfileStore:
    identity = create_profile(tmp_path, "Perico de Prueba", handle="perico", fiction=True)
    return ProfileStore(tmp_path, identity.handle)


# --- the split ---------------------------------------------------------------


def test_elicitation_never_draws_from_evaluation_split() -> None:
    """The named test: an evaluation-split ad is refused, not filtered out."""
    with pytest.raises(ElicitationError, match="evaluation"):
        stimulus_from_ad(_ad("ad-eval", "evaluation"), evaluation_ids=frozenset())

    stimulus = stimulus_from_ad(_ad("ad-elic", "elicitation"), evaluation_ids=frozenset())
    assert stimulus.source == CORPUS_SOURCE
    assert stimulus.text == _TEXT


def test_the_overlap_measure_reads_evidence_not_the_selector(tmp_path: Path) -> None:
    """Plant a reaction the selector would never have made; the measure must see it.

    A measurement whose only input is the rule that produced the data returns 0
    whatever the code does. This one re-derives the evaluation ids from corpus
    *text* and intersects them with what was actually reacted to, so bypassing
    the selector does not bypass the measurement.
    """
    store = _store(tmp_path)
    log = EvidenceLog(store)
    evaluated = _ad("ad-eval", "evaluation")
    corpus = [_ad("ad-elic", "elicitation", "Otro anuncio distinto. " * 25), evaluated]

    log.append(
        recorded_at=_AT,
        step="reactions",
        kind="reaction",
        text="No me dice nada.",
        source="offer_reaction",
        about=EvidenceSubject(kind="offer", id=compute_offer_id(evaluated.text)),
    )

    overlap = measure(store=store, corpus=corpus)
    assert overlap["elicitation_eval_overlap"] == 1, overlap


def test_evaluation_ids_are_derived_from_text_not_from_the_split_field(tmp_path: Path) -> None:
    """The bridge between a corpus id and an offer id is the text itself."""
    evaluated = _ad("ad-eval", "evaluation")
    assert evaluation_offer_ids([evaluated]) == {compute_offer_id(evaluated.text)}
    assert evaluation_offer_ids([_ad("ad-elic", "elicitation")]) == set()


# --- provenance --------------------------------------------------------------


def test_no_stimulus_is_invented() -> None:
    """An imagined advert reads plausibly and represents nothing."""
    # The id content-addresses the text, so a stimulus whose text was rewritten
    # after the fetch no longer matches what was fetched.
    with pytest.raises(ElicitationError, match="content-address"):
        check_stimulus(_live_offer(text="Un anuncio inventado. " * 25, id=compute_offer_id(_TEXT)))

    # A live stimulus with nowhere it came from is indistinguishable from one
    # the model wrote.
    with pytest.raises(ElicitationError, match="url"):
        check_stimulus(_live_offer(url=None))
    with pytest.raises(ElicitationError, match="fetched_at"):
        check_stimulus(_live_offer(fetched_at=None))

    check_stimulus(_live_offer())


def test_a_board_that_blocks_us_is_not_a_stimulus_source() -> None:
    """robots.txt is checked before a board is used, not after building on it."""
    assert not BLOCKED_SOURCES & PERMITTED_LIVE_SOURCES
    for blocked in sorted(BLOCKED_SOURCES):
        with pytest.raises(ElicitationError, match="robots"):
            check_stimulus(_live_offer(source=blocked))

    with pytest.raises(ElicitationError, match="not a permitted"):
        check_stimulus(_live_offer(source="some_board_nobody_checked"))


# --- the offer store ---------------------------------------------------------


def test_live_stimuli_enter_the_offer_store_as_new(tmp_path: Path) -> None:
    """Not a parallel universe of adverts — ordinary offers, ordinary lifecycle."""
    store = _store(tmp_path)
    offer = _live_offer()

    stored = collect_stimuli(store, [offer], at=_AT)

    assert stored == [offer.id]
    assert load_offer(store, offer.id).status == "new"


def test_a_stimulus_that_fails_provenance_never_reaches_the_store(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(ElicitationError):
        collect_stimuli(store, [_live_offer(url=None)], at=_AT)
    assert not list((store.home / "offers").glob("*.json"))


# --- the live number ---------------------------------------------------------


def test_the_recorded_measurement_reports_no_overlap() -> None:
    """What the gate reads, over the probes the module runs."""
    from integral.reaction_elicit import probe_elicitation

    probed = probe_elicitation()
    assert probed["elicitation_eval_overlap"] == 0
    # The planted-reaction scenario proves the number above can be non-zero.
    assert probed["overlap_detected_when_planted"] == 1
    assert probed["scenarios"] >= 6


# --- the live path -----------------------------------------------------------


def test_a_fetched_record_becomes_a_checked_stimulus() -> None:
    """`tools/collect_ads.py`'s record shape, without importing the scraper."""
    from integral.reaction_elicit import stimulus_from_record

    record = {
        "id": "remotive-991",
        "source": "remotive",
        "source_url": "https://remotive.com/ad/991",
        "fetched_at": _AT,
        "language": "ca",
        "title": "Cuiner/a",
        "company": "Restaurant Girona",
        "text": _TEXT,
    }

    stimulus = stimulus_from_record(record)

    # Addressed by its text, never by the id the board happened to use.
    assert stimulus.id == compute_offer_id(_TEXT)
    assert stimulus.source_ref == "remotive-991"
    assert stimulus.status == "new"

    # A record from a board that blocks us never becomes a stimulus, however
    # well-formed the rest of it is.
    with pytest.raises(ElicitationError, match="robots"):
        stimulus_from_record({**record, "source": "remoteok"})


def test_the_split_is_a_fact_about_the_text_not_about_the_label() -> None:
    """Two rows, different corpus ids, identical text — one of them evaluation.

    The offer id addresses the *text*, so the `elicitation` row here carries
    content the ranking is scored against. Catching it at admission matters:
    `measure` would report the breach, but only after the candidate had already
    reacted to it.
    """
    shared = "Mismo texto exacto en dos filas distintas. " * 20
    corpus = [_ad("ad-elic", "elicitation", shared), _ad("ad-eval", "evaluation", shared)]

    with pytest.raises(ElicitationError, match="byte-identical"):
        stimulus_from_ad(corpus[0], evaluation_ids=evaluation_offer_ids(corpus))

    # And the path the candidate actually goes through refuses it too.
    with pytest.raises(ElicitationError, match="byte-identical"):
        corpus_stimuli(1, corpus=corpus)


def test_a_url_that_disagrees_with_its_source_is_refused() -> None:
    """`source` is a claim; the host the text came from is the check on it."""
    with pytest.raises(ElicitationError, match="disagree"):
        check_stimulus(_live_offer(url="https://unapproved.example/ad"))

    with pytest.raises(ElicitationError, match="https"):
        check_stimulus(_live_offer(url="http://remotive.com/ad/1"))

    # Every permitted source names the host its ads come from — a source with no
    # known host cannot be permitted, because the check would have nothing to
    # compare against. The permitted set is the shipped connectors minus the
    # boards we are refused, derived rather than pinned (#558), so a connector
    # added tomorrow is reactable without anyone editing a list.
    assert frozenset(SOURCE_HOSTS) - BLOCKED_SOURCES == PERMITTED_LIVE_SOURCES
    assert all(SOURCE_HOSTS[source] for source in PERMITTED_LIVE_SOURCES)


def test_an_ats_advert_is_not_served_from_the_host_the_connector_lists_from() -> None:
    """One label of slack, because an ATS lists and serves from different hosts.

    `connectors/ashby/connector.yaml` lists from `api.ashbyhq.com`; the advert
    url that comes back in that payload is on `jobs.ashbyhq.com`. Requiring
    host equality refused every ATS advert there is — which is half of #558 —
    so the check compares the site domain, one label of slack and no more.
    """
    assert _site_domain("api.ashbyhq.com") == "ashbyhq.com"
    assert _site_domain("job-boards.eu.greenhouse.io") == "eu.greenhouse.io"
    assert _site_domain("remotive.com") == "remotive.com"

    check_stimulus(_live_offer(source="ashby", url="https://jobs.ashbyhq.com/acme/1"))
    check_stimulus(_live_offer(url="https://jobs.remotive.com/ad/1"))

    # A host that merely *ends with* the source's name is somebody else's.
    with pytest.raises(ElicitationError, match="disagree"):
        check_stimulus(_live_offer(url="https://remotive.com.evil.test/ad"))


def test_the_slack_is_one_label_and_stops_there() -> None:
    """The ceiling, and the harm it would do, pinned rather than asserted.

    This is not a public-suffix lookup. A list host of exactly three labels
    whose last two are themselves a public suffix reduces to that suffix and
    would admit every sibling under it — **fail-open**, and the one direction
    that matters. `jobsacuk` lists from `www.jobs.ac.uk`, so it keeps
    `jobs.ac.uk`; the same board listed one label shorter would keep `ac.uk`.

    What is checked here is the harm rather than the shape: no two shipped
    connectors may reduce to the same domain, and none may reduce to a suffix
    of another's. Either would let one board's advert clear under a different
    board's `source`, which is the whole of what this comparison prevents — and
    it is what an over-reduced host does first.
    """
    assert _site_domain("www.jobs.ac.uk") == "jobs.ac.uk"
    assert _site_domain("jobs.ac.uk") == "ac.uk"

    domains = sorted(_site_domain(host) for host in SOURCE_HOSTS.values())
    assert len(set(domains)) == len(domains)
    for domain in domains:
        assert not [other for other in domains if other != domain and other.endswith(f".{domain}")]


def test_every_shipped_connector_is_a_board_the_candidate_can_react_on() -> None:
    """#558: the permitted set is derived from `connectors/`, never pinned.

    The defect was a hand-written map of four boards that had drifted from the
    packages three separate ways at once — a key no offer carries, a board with
    no package, and a refusal on a ruling the package's own header retracts. A
    literal cannot be kept in step with a directory, so the check is that the
    directory *is* the source: every shipped connector answers for a board, and
    only a board we are refused is missing from the permitted set.
    """
    packages = list(CONNECTORS_DIR.glob(f"*/{CONNECTOR_FILENAME}"))
    assert packages, "no connector packages found — the derivation would be vacuous"
    assert len(SOURCE_HOSTS) == len(packages)
