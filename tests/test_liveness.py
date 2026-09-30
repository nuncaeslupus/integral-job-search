"""T74 — liveness checks page identity, not only the URL.

`liveness.read_response` compared `advert_url` against `final_url` and called
that liveness, which catches a redirect but misses the case D-18 never saw: a
stored URL that still resolves, 200, to a page that is not the advert. A
fragment anchor (`.../jobs/ciso/#ikerian`) is never sent to the server, so the
URL check alone cannot tell a listing page from the vacancy it links to —
only the content can. See `integral.liveness`'s module docstring for the
three-valued vocabulary this stays inside: `live`, `dead`, `unverified`, and
page identity is one more way to reach the third.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest

from integral import liveness
from integral.connector_health import BLOCK_PAGE_MARKERS, RATE_LIMIT_SAMPLES
from integral.offers import Offer

_LISTINGS_PAGE = "<h1>Ofertas de empleo</h1><p>Explora nuestras vacantes en el sector servicios</p>"


def _advert(offer_id_seed: str, *, title: str | None, text: str = "Se busca.") -> Offer:
    return Offer(
        id="sha256:" + hashlib.sha256(offer_id_seed.encode("utf-8")).hexdigest(),
        source="examplejobs",
        title=title,
        text=text,
    )


def test_a_fragment_anchor_landing_on_a_listing_page_is_unverified() -> None:
    """The URL never changes for a fragment anchor — `#ikerian` is never sent
    to the server — so `same_page` reads it as the same page it always was.
    Only the body says otherwise: a listings page mentions nothing about the
    CISO vacancy the offer names, and that has to be enough to withhold it."""
    offer = _advert("ciso", title="CISO")

    check = liveness.read_response(
        offer.id,
        200,
        _LISTINGS_PAGE,
        advert_url="https://board.example.com/jobs/ciso/#ikerian",
        final_url="https://board.example.com/jobs/ciso/#ikerian",
        title=offer.title,
    )

    assert liveness.same_page(
        "https://board.example.com/jobs/ciso/#ikerian",
        "https://board.example.com/jobs/ciso/#ikerian",
    ), "the fragment must not itself trip the URL check — identity has to catch this"
    assert check.liveness == "unverified"
    assert "CISO" in check.reason
    assert liveness.presentable([offer], {offer.id: check})[0] == []


def test_a_page_whose_title_does_not_match_the_offer_is_unverified() -> None:
    """No redirect at all — a plain 200 at the advert's own URL — for a page
    that reads as an entirely different vacancy. Same-URL and same-status are
    not "this advert"; the page has to actually be the one offered."""
    offer = _advert("recepcionista", title="Ingeniero de Datos")

    check = liveness.read_response(
        offer.id,
        200,
        "<h1>Recepcionista</h1><p>Media jornada, turno de tarde.</p>",
        title=offer.title,
    )

    assert check.liveness == "unverified"
    assert liveness.presentable([offer], {offer.id: check})[0] == []


def test_the_advert_itself_still_reads_live() -> None:
    """The trap this task names: a title check strict enough to catch a
    listings page must not also catch the advert it is checking for. Casing,
    surrounding markup and a trailing sentence are exactly the kind of noise
    a real fetch carries, and none of them may turn a live vacancy into one
    the candidate never sees."""
    offer = _advert("albañil", title="Albañil")

    check = liveness.read_response(
        offer.id,
        200,
        "<h1>ALBAÑIL</h1><p>Se busca.  Jornada   completa.</p>",
        title=offer.title,
    )

    assert check.liveness == "live"
    assert liveness.presentable([offer], {offer.id: check})[0] == [offer]

    # And a fetch that carries no title at all keeps the old behaviour —
    # nothing to compare against is not evidence of a mismatch.
    untitled = _advert("no-title", title=None)
    untitled_check = liveness.read_response(
        untitled.id, 200, "Se busca albañil. Jornada completa.", title=untitled.title
    )
    assert untitled_check.liveness == "live"


def test_the_gate_does_not_pass_on_an_empty_input_set() -> None:
    """A zero violation count over zero evaluated pages is what the D-18
    failure class looks like reproduced inside its own gate. The evidence
    record has to carry both names the task uses for the denominator, and a
    run that checked nothing must read `unmeasured`, never a clean pass."""
    measured = liveness.measure_page_identity()
    assert measured["gate_status"] == "measured"
    assert measured["offers_presented_from_a_page_that_is_not_the_advert_evaluated"] > 0
    assert measured["pages_checked"] > 0
    assert (
        measured["offers_presented_from_a_page_that_is_not_the_advert_evaluated"]
        == measured["pages_checked"]
    )
    assert measured["offers_presented_from_a_page_that_is_not_the_advert"] == 0

    # An input set that is genuinely empty — no scenario carried a title —
    # must not read as a pass either: `gate_status` is what tells "checked
    # nothing" apart from "checked everything and found no violation".
    empty = liveness.measure_page_identity([])
    assert empty["gate_status"] == "unmeasured"
    assert empty["offers_presented_from_a_page_that_is_not_the_advert_evaluated"] == 0
    assert empty["pages_checked"] == 0


def test_page_identity_evidence_is_written_beside_d18s(tmp_path: Path) -> None:
    """The gate must never name a file no module produces — `write_evidence`
    for D-18 already exists, and T74's file has to sit beside it rather than
    replace it.

    Written under `tmp_path`, not the repository's own evidence directory: a
    test that writes into the tree it is testing fails on a read-only checkout
    and collides with a parallel worker, and neither failure would be about
    the behaviour under test."""
    written = tmp_path / "T74-test.json"

    measured = liveness.write_page_identity_evidence(written)

    assert written.exists()
    assert measured["gate_status"] == "measured"


def test_bare_invocation_writes_both_evidence_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`make evidence` derives its module list from `^def _main` and runs each
    module once with no flag to remember — a bare run has to regenerate both
    D-18's file and T74's, not just the one it always wrote before this task."""
    d18_path = tmp_path / "D-18.json"
    t74_path = tmp_path / "T74.json"
    monkeypatch.setattr(liveness, "DEFAULT_EVIDENCE_PATH", d18_path)
    monkeypatch.setattr(liveness, "DEFAULT_IDENTITY_EVIDENCE_PATH", t74_path)

    rc = liveness._main(["prog"])

    assert rc == 0
    assert d18_path.exists()
    assert t74_path.exists()


def test_a_blank_title_matches_no_page() -> None:
    """`"" in anything` is True, so an offer with no title passed identity
    against every page — an unrelated listing verified as the advert, and
    counted toward the denominator as though it had been checked. That is this
    check failing open at the one thing it was added to do."""
    assert liveness.title_in_body("", "<h1>Completely Unrelated Listing</h1>") is False
    assert liveness.title_in_body("   ", "<h1>Completely Unrelated Listing</h1>") is False


def test_a_title_split_across_markup_still_matches() -> None:
    """The worse failure of the two, per the task: the candidate sees nothing.
    A real advert whose heading is split across tags does not *contain* its own
    plain title, so comparing raw HTML withheld a live advert — the exact
    strictness the docstring above `title_in_body` promised to avoid."""
    body = "<h1>Ingeniero <span>de</span> Datos</h1><p>Jornada completa.</p>"

    assert liveness.title_in_body("Ingeniero de Datos", body) is True
    assert liveness.title_in_body("Ingeniero de Datos", "<h1>Recepcionista</h1>") is False


def test_an_unknown_option_is_refused_rather_than_ignored() -> None:
    """`--identiy` matched neither name and was filtered out of the positional
    list too, so the call fell into the bare-invocation branch, wrote both
    evidence files and exited 0 — a typo that silently does something else and
    reports success."""
    assert liveness._main(["liveness", "--identiy"]) == 2
    assert liveness._main(["liveness", "a.json", "b.json"]) == 2


def test_a_listings_page_that_mentions_the_vacancy_is_not_the_advert() -> None:
    """Searching the whole document was a fail-open that the T74 fixtures
    passed by luck: their listings page happens not to contain the word
    `CISO`. One that does — a nav item, a card for a neighbouring role, a
    JSON-LD payload — read as the advert and was presented."""
    listings = (
        "<h1>Ofertas de empleo</h1><ul><li><a href=/jobs/ciso-madrid>CISO Madrid</a></li></ul>"
    )

    assert liveness.title_in_body("CISO", listings) is False
    assert liveness.title_in_body("CISO", "<h1>CISO</h1><p>Jornada completa.</p>") is True


def test_the_page_title_element_also_states_identity() -> None:
    """An advert whose heading is an image or a styled div still declares
    itself in `<title>`; refusing that would withhold live adverts."""
    assert liveness.title_in_body("CISO", "<title>CISO - Acme</title><p>x</p>") is True


def test_a_match_may_not_span_two_identity_fields() -> None:
    """`<title>` and `<h1>` are separate claims. Concatenating them would let a
    phrase neither contains be assembled across the join."""
    assert liveness.title_in_body("Acme CISO", "<title>Acme</title><h1>CISO</h1>") is False


def test_with_no_title_a_marker_anywhere_withholds_and_a_title_restores() -> None:
    """T173's accepted fail-closed cost (#455 rounds 1-3). With no title, a real
    advert whose markup carries `h-captcha` is withheld as `unverified`;
    given its title, the identity check decides and it is `live`."""
    advert = (
        "<html><head><title>Research Fellow - jobs.ac.uk</title></head><body>"
        '<h1>Research Fellow</h1><div class="h-captcha" data-sitekey="x"></div>'
        "<p>You will design our API rate limiting.</p></body></html>"
    )
    assert liveness.read_response("b", 200, advert).liveness == "unverified"
    assert liveness.read_response("b", 200, advert, title="Research Fellow").liveness == "live"


def _named_innocuously(body: str) -> str:
    """A block page given a site-name `<title>` and no `<h1>` — what a restyle
    of any challenge page can look like (#455 round 3, N3)."""
    demoted = body.replace("<h1", "<h2").replace("</h1>", "</h2>")
    if "<head>" in demoted:
        return demoted.replace("<head>", "<head><title>Acme Empleo</title>", 1)
    return demoted.replace("<html>", "<html><head><title>Acme Empleo</title></head>", 1)


#: Inert page text, long enough that a scan cut short at any plausible length
#: never reaches what follows it (#455 round 4, N5). No block marker in it.
_PADDING = "<p>Ofertas de empleo en Barcelona, actualizadas cada día.</p>" * 400


def _buried(body: str) -> str:
    """The same refusal with its words after ~24 KB of an ordinary page."""
    for anchor in ("<body>", "<html>"):
        if anchor in body:
            return body.replace(anchor, anchor + _PADDING, 1)
    return _PADDING + body


_SHAPES: dict[str, Callable[[str], str]] = {
    "as recorded": lambda body: body,
    "named innocuously": _named_innocuously,
    "buried": _buried,
}


@pytest.mark.parametrize("shape", list(_SHAPES))
@pytest.mark.parametrize(
    ("case", "status", "body"),
    RATE_LIMIT_SAMPLES,
)
def test_no_known_refusal_reads_as_a_live_advert(
    case: str, status: int | None, body: str, shape: str
) -> None:
    """#455 rounds 2 and 3 (N1, N3). Every entry in `RATE_LIMIT_SAMPLES` *is* a
    refusal, so served as recorded — a 200 where no status was recorded —,
    restyled with an innocuous site-name title and its `<h1>` demoted, and
    buried after a long ordinary page, none of them may be presented as an
    open vacancy when no title is given.
    Derived from the sample list, so a refusal added there later is covered."""
    assert not any(m in _PADDING.casefold() for m in BLOCK_PAGE_MARKERS)
    page = _SHAPES[shape](body)
    check = liveness.read_response("r", status if status is not None else 200, page)
    assert check.liveness != "live", (case, shape, check.reason)


#: Jobfluent's site-wide report button, verbatim from
#: https://www.jobfluent.com/es/empleos/ai-engineer-barcelona-f28af3 (2026-09-30).
_JOBFLUENT_REPORT_BUTTON = (
    '<div class="not-available row"><a class="btn btn-danger btn-sm" '
    'href="/es/offers/f28af3/report-filled">Oferta no disponible? Dínoslo!</a></div>'
)


def test_a_live_jobfluent_advert_is_not_read_dead_by_its_report_button() -> None:
    """FAIL-CLOSED, measured: 15 of 15 live Jobfluent adverts read `dead`."""
    page = f"<h1>AI Engineer</h1><p>Barcelona, jornada completa.</p>{_JOBFLUENT_REPORT_BUTTON}"
    check = liveness.read_response("j", 200, page, title="AI Engineer")
    assert check.liveness == "live", check.reason
    assert liveness.expire(_advert("j", title="AI Engineer"), check).status != "expired"


@pytest.mark.parametrize(
    "page",
    [
        "<p>¿Oferta no disponible? Avísanos.</p>",  # the phrase is the question
        "<P>Position filled?</P>",
        "<p>Oferta no disponible ?</p>",  # whitespace before the mark
        "<p>¿Oferta no disponible, dices?</p>",  # ¿…? span around the phrase
        "<A HREF=/r>Oferta no disponible?\n Dínoslo!</A>",
    ],
)
def test_a_phrase_that_is_itself_a_question_states_no_closure(page: str) -> None:
    assert liveness.dead_phrase_in(page) is None


@pytest.mark.parametrize(
    "page",
    [
        "<h1>Albañil</h1><p>PUESTO OCUPADO</p>",
        f"<p>Oferta no disponible.</p>{_JOBFLUENT_REPORT_BUTTON}",
        f"{_JOBFLUENT_REPORT_BUTTON}<p>Esta oferta ya no está disponible</p>",
        "<p>¿Buscas trabajo? Vacante cubierta.</p>",  # the question is another sentence
        "Puesto <b>ocupado</b>",  # split by inline markup
        # the same phrase asked first and stated after: every occurrence counts
        f"{_JOBFLUENT_REPORT_BUTTON}<p>Oferta no disponible.</p>",
        # a `¿` span ends at a sentence break, on either side of the phrase
        "<h1>¿Buscas empleo</h1><p>Oferta cerrada. ¿Te ayudamos?</p>",
        "<p>¿Dudas? Vacante cubierta, pero puedes ver otras ofertas?</p>",
        # #599 second reader, F1-F4: a closure stated, THEN a question. Fail-open
        # under a rule that skipped any sentence ending in `?`.
        "<h1>Dev</h1><h2>Position filled</h2><p>Looking for something similar?</p>",
        "<p>Esta oferta ya no está disponible, ¿quieres ver ofertas similares?</p>",
        "<p>This job is no longer available - why not browse similar jobs?</p>",
        "<title>Oferta cerrada</title><h1>¿Buscas empleo?</h1>",
        # F5/F6: a closure inside a link is still a statement, and markup that
        # never closes cannot swallow one.
        '<a href="/similar"><div>Esta oferta ya no está disponible. Ver similares</div></a>',
        '<a name="top"><p>Oferta cerrada.</p><a href="/x">Inicio</a>',
        # F7: a closure stated only in an attribute still counts, as on main.
        '<meta name="description" content="Oferta cerrada"><h1>Dev</h1>',
    ],
)
def test_a_stated_closure_still_reads_dead(page: str) -> None:
    assert liveness.read_response("d", 200, page).liveness == "dead"


#: The sentence breaks that bound a `¿…?` span. Each is tried alone, on each
#: side it matters, so no one of them can be dropped unnoticed (#599 round 2).
#: `¿` before the phrase and `?` after it are not listed: a later `¿` restarts
#: the span and the first `?` closes it, so dropping either changes nothing.
_OPEN_SIDE_BREAKS = (".", "!", "?", "¡")
_CLOSE_SIDE_BREAKS = (".", "!", "¡", "¿")


def test_an_unbroken_inverted_question_span_is_a_question() -> None:
    assert liveness.dead_phrase_in("¿Hola, oferta cerrada, dices?") is None


@pytest.mark.parametrize("brk", _OPEN_SIDE_BREAKS)
def test_a_break_between_the_open_mark_and_the_phrase_ends_the_question(brk: str) -> None:
    assert liveness.dead_phrase_in(f"¿Hola{brk} oferta cerrada, dices?") == "oferta cerrada"


@pytest.mark.parametrize("brk", _CLOSE_SIDE_BREAKS)
def test_a_break_between_the_phrase_and_the_close_mark_ends_the_question(brk: str) -> None:
    assert liveness.dead_phrase_in(f"¿Oferta cerrada{brk} vale?") == "oferta cerrada"


def test_an_unclosed_angle_bracket_does_not_make_the_scan_quadratic() -> None:
    import time

    start = time.perf_counter()
    liveness.dead_phrase_in("<a " * 200_000)
    assert time.perf_counter() - start < 5
