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
from pathlib import Path

import pytest

from integral import liveness
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


def test_page_identity_evidence_is_written_beside_d18s() -> None:
    """The gate must never name a file no module produces — `write_evidence`
    for D-18 already exists, and T74's file has to sit beside it rather than
    replace it."""
    measured = liveness.write_page_identity_evidence(
        liveness.DEFAULT_IDENTITY_EVIDENCE_PATH.parent / "T74-test.json"
    )
    written = liveness.DEFAULT_IDENTITY_EVIDENCE_PATH.parent / "T74-test.json"
    try:
        assert written.exists()
        assert measured["gate_status"] == "measured"
    finally:
        written.unlink(missing_ok=True)


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
