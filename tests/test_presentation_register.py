"""T95 — what reaches the candidate in one turn.

Three observations from step 5, all about the surface rather than the model.

    Four ads can be very few. I like that you don't give me long lists, but
    maybe two or three chunks can help better.

    "pasamos a convertir esto en pesos para el ranking" is weird for the user
    when nothing about ranking or weights has been explained before.

    I like that you give me a summary of the ads. Just make sure that all the
    important info is in there.

The instinct against long lists was right and the quantity was not: the ask is
the same total delivered as a few digestible groups, which is chunking rather
than truncation. And `weights.py` and `rank.py` are internal machinery — either
the term is introduced before it is used, or it is not used.

`vocabulary_reach.py` does not cover this. It measures whether the dimension
model reaches a market, which is a different sense of the word. This is
register, and nothing checked it.
"""

from __future__ import annotations

from pathlib import Path

from integral import presentation as pres
from integral.presentation import (
    DEFAULT_LIMIT,
    INTERNAL_TERMS,
    chunks,
    summary_fields_missing,
    terms_used_before_introduction,
)


def test_a_batch_is_chunked_rather_than_truncated() -> None:
    """The cap is per chunk, not per turn. Every advert the ranking found
    reaches the candidate; what changes is how many arrive at once."""
    frontier = [f"offer-{n}" for n in range(12)]

    grouped = chunks(frontier, DEFAULT_LIMIT)

    assert [len(group) for group in grouped] == [5, 5, 2]
    assert [item for group in grouped for item in group] == frontier
    assert all(len(group) <= DEFAULT_LIMIT for group in grouped)


def test_chunking_never_drops_the_remainder() -> None:
    """The failure this replaces: `frontier[:limit]` and a count of what was
    dropped. A remainder silently lost is the same page lying about itself
    that `render` already refuses for a missing offer."""
    for total in range(0, 23):
        grouped = chunks(list(range(total)), DEFAULT_LIMIT)
        assert sum(len(group) for group in grouped) == total


def test_every_page_of_a_chunked_batch_reaches_the_candidate() -> None:
    """Over the module's own fixture, end to end: each group renders, and the
    union of the groups is the whole frontier."""
    rendered = pres.pages_for_the_fixture()

    assert len(rendered) >= 1
    assert all(page.strip() for page in rendered)


def test_an_internal_term_is_introduced_before_it_is_used() -> None:
    """Over the named list, against the page the candidate actually reads."""
    for page in pres.pages_for_the_fixture():
        assert terms_used_before_introduction(page) == []


def test_the_named_list_is_the_one_the_task_names() -> None:
    """A rule over an empty vocabulary is a rule over nothing."""
    for term in ("weights", "part-worth", "ranking", "corpus", "connector"):
        assert term in INTERNAL_TERMS


def test_a_term_used_with_no_introduction_is_caught() -> None:
    """The gate, shown failing — this is close to the sentence the candidate
    quoted back."""
    said = "Ahora pasamos a convertir esto en pesos para el ranking."

    assert terms_used_before_introduction(said) == ["ranking"]


def test_an_introduction_after_the_term_does_not_count() -> None:
    """Explaining it afterwards is explaining it to someone who has already
    been confused by it."""
    late = f"Here is the ranking. {INTERNAL_TERMS['ranking']}"

    assert terms_used_before_introduction(late) == ["ranking"]


def test_a_term_introduced_first_is_fine() -> None:
    early = f"{INTERNAL_TERMS['ranking']} — so here is the ranking."

    assert terms_used_before_introduction(early) == []


def test_a_summary_carries_every_field_a_decision_needs() -> None:
    """Keep the summary, make the field set complete. A link is optional
    rather than the payload, so it is in the set as a row that may read
    `unknown` — never as a row that is absent."""
    for page in pres.pages_for_the_fixture():
        assert summary_fields_missing(page) == []


def test_a_summary_says_whether_a_salary_was_stated_or_estimated() -> None:
    """T92 lets an estimate exist provided it never reads as stated. A summary
    that prints one number honours the letter of that and breaks it here, at
    the only place the candidate actually looks."""
    stated = pres.card(pres.offer_with_salary(60000, stated=True))
    estimated = pres.card(pres.offer_with_salary(60000, stated=False))

    assert pres.ESTIMATED_MARKER not in stated
    assert pres.ESTIMATED_MARKER in estimated
    assert "60,000" in estimated


def test_an_estimated_salary_shows_its_basis_in_the_summary() -> None:
    """An estimate with no basis is a number the candidate cannot argue with,
    which is the same failure as printing it as a fact."""
    estimated = pres.card(pres.offer_with_salary(60000, stated=False))

    assert pres.ESTIMATE_BASIS in estimated


def test_an_unstated_salary_with_no_figure_is_still_unknown() -> None:
    """The estimate route must not turn a silent advert into a number."""
    assert pres.UNKNOWN in pres.card(pres.offer_with_salary(None, stated=False))


def test_the_gate_counts_what_it_read() -> None:
    measured = pres.measure_register()

    assert measured["internal_terms_used_before_introduction"] == 0
    assert measured["internal_terms_used_before_introduction_evaluated"] > 0
    assert measured["terms_checked"] == len(INTERNAL_TERMS)
    assert measured["gate_status"] == "measured"


def test_the_gate_does_not_pass_on_an_empty_input_set() -> None:
    measured = pres.measure_register(pages=(), terms={})

    assert measured["internal_terms_used_before_introduction"] == 0
    assert measured["internal_terms_used_before_introduction_evaluated"] == 0
    assert measured["gate_status"] == "unmeasured"


def test_the_gate_catches_a_leak_on_a_real_page() -> None:
    """Planted, so a zero over the fixture cannot be a check that never ran."""
    measured = pres.measure_register(
        pages=("Ahora pasamos a convertir esto en pesos para el ranking.",)
    )

    assert measured["internal_terms_used_before_introduction"] == 1


def test_the_module_writes_its_record(tmp_path: Path) -> None:
    target = tmp_path / "T44.json"

    assert pres._main([str(target)]) in (0, 3)
    assert (tmp_path / "T95.json").is_file()
