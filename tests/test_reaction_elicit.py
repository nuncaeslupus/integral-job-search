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
from unittest import mock

import pytest
import yaml

from integral import reaction_elicit
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
    _hostname,
    check_stimulus,
    collect_stimuli,
    connector_hosts,
    corpus_stimuli,
    evaluation_offer_ids,
    measure,
    permitted_live_sources,
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
    # Named, never counted: `probe_elicitation` records no scenario count, so
    # what is asserted here is that the probe still ran the cases the module's
    # guards exist for. A `>= 6` over a length would be satisfied by six
    # scenarios aimed at one rule.
    assert {"blocked_board", "rewritten_text", "no_url", "no_fetched_at"} <= set(probed["refusals"])
    assert "board_advert_on_its_list_host" in probed["acceptances"]


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
    assert all(_hostname(f"https://{host}") == host for h in SOURCE_HOSTS.values() for host in h)


def test_an_ats_advert_is_not_served_from_the_host_the_connector_lists_from() -> None:
    """An ATS lists from one host and serves adverts from another — declared.

    `connectors/ashby_en` lists from `api.ashbyhq.com`; the advert urls its
    payload returns are on `jobs.ashbyhq.com`. Host equality therefore refused
    every ATS advert there is, which was the other half of #558.

    The serving host is read from the package's `serves_from`, never inferred
    from the list host's domain. The measured reason is below.
    """
    check_stimulus(_live_offer(source="ashby", url="https://jobs.ashbyhq.com/acme/1"))
    check_stimulus(
        _live_offer(source="greenhouse", url="https://job-boards.greenhouse.io/acme/jobs/1")
    )
    check_stimulus(_live_offer(source="lever", url="https://jobs.lever.co/acme/1"))
    check_stimulus(_live_offer(source="rippling", url="https://ats.rippling.com/acme/jobs/1"))

    # `job-boards.eu.greenhouse.io` is the host this PR declared for a whole
    # review round with no artefact of any kind behind it — the regional
    # spelling of a host that is real, which is what made it plausible. A
    # provenance claim nobody has observed is a guess, and it is refused like
    # any other undeclared host.
    with pytest.raises(ElicitationError, match="disagree"):
        check_stimulus(
            _live_offer(source="greenhouse", url="https://job-boards.eu.greenhouse.io/acme/jobs/1")
        )

    # A board that serves from its own list host declares no `serves_from`, and
    # a subdomain of it is then somebody else's: no slack is extended to anyone.
    with pytest.raises(ElicitationError, match="disagree"):
        check_stimulus(_live_offer(url="https://jobs.remotive.com/ad/1"))
    with pytest.raises(ElicitationError, match="disagree"):
        check_stimulus(_live_offer(url="https://remotive.com.evil.test/ad"))


def test_a_sibling_of_the_list_host_that_the_ledger_refuses_is_not_admitted() -> None:
    """Why `serves_from` is declared rather than derived. Fail-open, measured.

    The first version of this fix compared the *site domain* — one label of
    slack off the list host — which reads as generous and is not. Greenhouse
    lists from `boards-api.greenhouse.io`, so one label of slack admits every
    host under `greenhouse.io`, and `connectors/ruled-out.yaml` refuses one of
    them by name: `boards.greenhouse.io`, *"the `*` group disallows the
    embedded job-board path"*, checked 2026-08-30.

    So the slack handed a candidate an advert from a host this repository is
    refused on, under a `source` that is permitted. Found by a second reader on
    #564, and the reason the rule is now a declaration: `boards.greenhouse.io`
    is refused here because **nobody declared it**, not because anybody
    remembered to exclude it.

    The check is closed rather than enumerated: no host any package declares
    may be one `ruled-out.yaml` files under `robots_refused`. A board ruled out
    tomorrow is caught without this test being edited.
    """
    with pytest.raises(ElicitationError, match="disagree"):
        check_stimulus(
            _live_offer(source="greenhouse", url="https://boards.greenhouse.io/acme/jobs/1")
        )

    ledger = yaml.safe_load((CONNECTORS_DIR / "ruled-out.yaml").read_text(encoding="utf-8"))
    # The two groups that mean *we are refused* — what robots said, and what we
    # decided. The rest of the ledger records boards we cannot parse, which is
    # not a permission and would refuse a host for the wrong reason.
    refused = {
        str(row["site"]).lower()
        for group in ("robots_refused", "policy_refused")
        for row in ledger.get(group) or []
        if isinstance(row, dict) and row.get("site")
    }
    assert "boards.greenhouse.io" in refused, "the ledger entry this test stands on has moved"
    declared = {host for hosts in SOURCE_HOSTS.values() for host in hosts}
    assert not (declared & refused)


def test_a_host_is_validated_never_repaired() -> None:
    """A url that must be *repaired* into a hostname is refused, not repaired.

    Every case below was accepted or refused wrongly by reading `netloc`, which
    is not a host — it carries userinfo and a port, and is whatever text sat
    between the slashes. The two fail-open ones end with a permitted host's
    spelling and are not that host; the two fail-closed ones are real adverts
    from real boards (`usajobs_en` serves `…usajobs.gov:443/job/…`, which is
    why `sourcing._origin` exists).
    """
    # fail-open: neither of these is `remotive.com`, and both used to pass.
    for forged in (
        "https://evil.test\\.remotive.com/ad",
        "https://.remotive.com/ad",
        "https://remotive.com@evil.test/ad",
        "https://remotive.com_evil.test/ad",
    ):
        with pytest.raises(ElicitationError, match="disagree"):
            check_stimulus(_live_offer(url=forged))

    # fail-closed: the same host, spelled two ways a board actually serves.
    check_stimulus(_live_offer(url="https://remotive.com:443/ad/1"))
    check_stimulus(_live_offer(url="https://remotive.com./ad/1"))

    assert _hostname("https://REMOTIVE.com/ad") == "remotive.com"
    assert _hostname("https://remotive.com@evil.test/ad") == "evil.test"
    assert _hostname("not a url") is None
    assert _hostname("https://localhost/ad") is None  # single label, no site


def test_every_shipped_connector_is_a_board_the_candidate_can_react_on(tmp_path: Path) -> None:
    """#558: the permitted set is derived from `connectors/`, never pinned.

    The defect was a hand-written map of four boards that had drifted from the
    packages three separate ways at once — a key no offer carries
    (`manfred`, where every offer says `getmanfred`), a board with no package
    (`feinaactiva`), and a refusal on a ruling the package's own header
    retracts (`tecnoempleo`). A literal cannot be kept in step with a
    directory, so the directory *is* the source.

    The derivation is exercised over a **constructed** directory as well as the
    shipped one, because every assertion about the shipped packages alone is
    satisfied by whatever the shipped packages happen to be: the blocked-source
    subtraction removes nothing today (no refused board has a package), and a
    test that only compares constants to each other cannot disagree with them.
    """
    packages = sorted(CONNECTORS_DIR.glob(f"*/{CONNECTOR_FILENAME}"))
    assert packages, "no connector packages found — the derivation would be vacuous"
    assert PERMITTED_LIVE_SOURCES, "no board is reactable — the derivation is inverted"

    def _package(name: str, site: str, host: str, **extra: object) -> None:
        directory = tmp_path / name
        directory.mkdir()
        body: dict[str, object] = {
            "site": site,
            "list": {"url_pattern": f"https://{host}/jobs?page={{page}}"},
        }
        body.update(extra)
        (directory / CONNECTOR_FILENAME).write_text(yaml.safe_dump(body), encoding="utf-8")

    _package("board_en", "board", "www.board.example.org")
    _package("ats_en", "ats", "api.ats.example.org", serves_from=["jobs.ats.example.org"])
    _package("worked_es", "worked", "www.worked.test")  # RFC 2606, resolves nowhere
    _package("nolist_en", "nolist", "")
    (tmp_path / "noname_en").mkdir()
    (tmp_path / "noname_en" / CONNECTOR_FILENAME).write_text(
        yaml.safe_dump({"list": {"url_pattern": "https://www.noname.example.org/jobs"}}),
        encoding="utf-8",
    )

    built = connector_hosts(tmp_path)
    assert built == {
        "board": frozenset({"www.board.example.org"}),
        "ats": frozenset({"api.ats.example.org", "jobs.ats.example.org"}),
    }
    # A blocked board keeps its package and loses its permission — the
    # subtraction is exercised against a board that HAS one, which no shipped
    # package does, so reverting it here goes red where the shipped set cannot.
    assert frozenset(built) - BLOCKED_SOURCES == frozenset({"board", "ats"})
    assert frozenset(built) - frozenset({"ats"}) == frozenset({"board"})

    # `examplejobs` is the shipped instance of the reserved-TLD rule.
    assert "examplejobs" not in SOURCE_HOSTS
    assert (CONNECTORS_DIR / "examplejobs_es" / CONNECTOR_FILENAME).exists()
    assert len(SOURCE_HOSTS) == len(packages) - 1


def test_a_blocked_board_is_refused_even_when_it_ships_a_connector() -> None:
    """`BLOCKED_SOURCES` must refuse a board that is otherwise fully derivable.

    No refused board ships a package today, so subtracting the blocked set from
    the shipped one removes nothing and every assertion over the shipped set
    stays true with the subtraction deleted. The refusal is therefore pinned
    where it can fail: against a source that IS in `SOURCE_HOSTS`, with the
    blocked set standing in for the day somebody writes remoteok a connector.
    """
    assert BLOCKED_SOURCES, "nothing is refused — the guard cannot be exercised"
    for board in BLOCKED_SOURCES:
        with pytest.raises(ElicitationError, match="robots"):
            check_stimulus(_live_offer(source=board, url="https://remotive.com/ad/1"))

    # …and it is checked BEFORE the permitted set, so a board that acquires a
    # package tomorrow is refused by this line rather than admitted by that one.
    patched = dict(SOURCE_HOSTS)
    patched["remoteok"] = frozenset({"remoteok.com"})
    with (
        mock.patch.object(reaction_elicit, "SOURCE_HOSTS", patched),
        mock.patch.object(reaction_elicit, "PERMITTED_LIVE_SOURCES", frozenset(patched)),
        pytest.raises(ElicitationError, match="robots"),
    ):
        check_stimulus(_live_offer(source="remoteok", url="https://remoteok.com/ad/1"))


def test_a_board_we_are_refused_on_is_never_permitted_even_once_it_ships_a_connector() -> None:
    """The subtraction, over the tree where it can fail.

    No board in `BLOCKED_SOURCES` ships a connector today, so over the shipped
    map `frozenset(SOURCE_HOSTS)` and `frozenset(SOURCE_HOSTS) - BLOCKED_SOURCES`
    are the same set and a test over the module constant passes with the
    subtraction deleted. Handing the function the map that does not exist yet is
    the only place the rule is observable.
    """
    blocked = sorted(BLOCKED_SOURCES)[0]
    hosts = {blocked: frozenset({"remoteok.com"}), "remotive": frozenset({"remotive.com"})}
    assert permitted_live_sources(hosts) == frozenset({"remotive"})


def test_a_host_the_grammar_only_prefix_matches_is_not_a_host() -> None:
    """The label grammar is anchored at both ends, and only one end shows it.

    `_LABEL_RE.match` and `_LABEL_RE.fullmatch` agree on every host in this
    repository, so swapping one for the other leaves the whole suite green while
    the check stops being one: `match` asks whether a label *begins* legally.
    `remotive_1` begins with `remotive`, and an underscore is not in RFC 1123
    §2.1's grammar — so under `match` an offer could name a host no resolver
    will answer for and pass provenance.
    """
    assert _hostname("https://remotive_1.com/ad") is None
    assert _hostname("https://remo tive.com/ad") is None
    assert _hostname("https://-remotive.com/ad") is None
    assert _hostname("https://remotive.com/ad") == "remotive.com"


def test_only_one_trailing_dot_is_the_same_host() -> None:
    """A root-anchored host ends in ONE dot; a run of them is not a spelling.

    `rstrip(".")` is the multi-character reading of "an absolutely-rooted host
    is the same host" and admits `remotive.com....`, which resolves nowhere.
    Trimming exactly one leaves the rest to the grammar, which has no empty
    label.
    """
    assert _hostname("https://remotive.com./ad") == "remotive.com"
    assert _hostname("https://remotive.com../ad") is None
    assert _hostname("https://remotive.com..../ad") is None


def test_a_serving_host_that_is_not_a_host_is_dropped_rather_than_recorded(
    tmp_path: Path,
) -> None:
    """`connector_hosts` reads YAML, so the model's validator never sees it.

    It is deliberately not `integral.connectors` — `corpus_scope` bounds what
    this module may import — which means a declaration the strict model would
    refuse still reaches this function. `_hostname` returns `None` for one, and
    dropping the `if host` filter puts that `None` into the set, where it can
    never equal a host and silently makes the package's whole declaration inert.
    """
    package = tmp_path / "ats_en"
    package.mkdir()
    (package / CONNECTOR_FILENAME).write_text(
        yaml.safe_dump(
            {
                "site": "ats",
                "serves_from": ["https://jobs.ats.example.org"],
                "list": {"url_pattern": "https://api.ats.org/jobs"},
            }
        ),
        encoding="utf-8",
    )
    assert connector_hosts(tmp_path) == {"ats": frozenset({"api.ats.org"})}


def test_a_reserved_tld_is_refused_on_a_serving_host_too(tmp_path: Path) -> None:
    """The rule is about hosts, and the list host is not the only one.

    `examplejobs_es` — the shipped worked example — carries the reserved TLD in
    both its list host and anything it serves from, so checking only the list
    host was true of the shipped tree by luck. A package listing from a real
    host and declaring a documentation one is where the two readings differ, and
    a set half of which resolves nowhere is not a provenance claim.
    """
    package = tmp_path / "half_en"
    package.mkdir()
    (package / CONNECTOR_FILENAME).write_text(
        yaml.safe_dump(
            {
                "site": "half",
                "serves_from": ["jobs.half.example"],
                "list": {"url_pattern": "https://api.half.org/jobs"},
            }
        ),
        encoding="utf-8",
    )
    assert connector_hosts(tmp_path) == {}


def test_every_declared_serving_host_is_observed_in_its_own_packages_capture() -> None:
    """The closed rule behind `serves_from`, and the one that deletes a guess.

    `job-boards.eu.greenhouse.io` was declared on `greenhouse_en` for a whole
    review round with nothing behind it anywhere in the repository — no fixture,
    no probe, no adjudication row, no ledger entry. It was a derivation written
    back in by hand after the derivation was removed, and no test could tell it
    from the three hosts that were real.

    So a declared host must be one this package has been SEEN serving from: it
    appears in a capture committed under the package's own directory. That is
    the artefact the connector contract already requires, it cannot be satisfied
    by writing more YAML, and it refuses the eu host by construction. Note this
    is not "it appears in `robots-adjudications.yaml`" — `job-boards.greenhouse.io`
    is corroborated by its capture and by no row, so that rule would delete a
    host that is real.
    """
    declared = {
        package.name: yaml.safe_load((package / CONNECTOR_FILENAME).read_text(encoding="utf-8"))
        for package in sorted(CONNECTORS_DIR.iterdir())
        if (package / CONNECTOR_FILENAME).exists()
    }
    serving = {
        name: tuple(body.get("serves_from") or ()) for name, body in declared.items() if body
    }
    assert [name for name, hosts in serving.items() if hosts], "no package declares a serving host"

    for name, hosts in serving.items():
        captures = [
            capture.read_text(encoding="utf-8", errors="replace")
            for capture in sorted((CONNECTORS_DIR / name).rglob("*"))
            if capture.is_file() and capture.suffix in {".html", ".json", ".txt"}
        ]
        for host in hosts:
            assert any(host in capture for capture in captures), (
                f"{name} declares it serves adverts from {host!r}, and no capture committed "
                "under its own directory has ever seen it do that"
            )


def test_the_two_host_grammars_agree_on_every_declared_host() -> None:
    """`connectors` and `reaction_elicit` spell the same grammar twice.

    They must: `reaction_elicit` may not import `integral.connectors` (the
    `corpus_scope` bound), and the questions differ — one validates a bare host
    a package declares, the other extracts one from a url. Two copies drift, so
    the agreement is pinned rather than trusted: every host the strict model
    accepts must be the host `_hostname` reads back out of a url naming it.
    """
    from integral.connectors import load_connectors

    declared = [host for connector in load_connectors() for host in connector.serves_from]
    assert declared, "no package declares a serving host — the agreement is vacuous"
    assert all(_hostname(f"https://{host}/ad") == host for host in declared)


def test_a_refusal_raised_by_a_different_rule_does_not_count_as_this_one() -> None:
    """`refused_by` is what makes the probe falsifiable, so it is itself pinned.

    Every check in `check_stimulus` runs behind the ones before it, so a
    scenario aimed at a later rule is answered by an earlier one the moment the
    later rule is deleted — same exception type, same recorded label, dead
    mutant, green probe. `because` is the whole of the difference, and a check
    that makes a probe falsifiable and is not itself falsifiable is the same
    defect one level up.
    """

    def refuse() -> None:
        raise ElicitationError("refused because the source is one robots refuses us")

    assert reaction_elicit.refused_by("blocked_board", "robots refuses", refuse) == "blocked_board"

    with pytest.raises(AssertionError, match="refused, but by another rule"):
        reaction_elicit.refused_by("no_url", "carries no url", refuse)

    with pytest.raises(AssertionError, match="expected a refusal"):
        reaction_elicit.refused_by("no_url", "carries no url", lambda: None)
