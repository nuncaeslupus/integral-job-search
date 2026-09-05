"""T107 — the candidate-facing string catalogue, and what its gate can honestly claim.

Three properties, in the order they matter:

1. a language with no entry falls back rather than rendering an empty page;
2. **changing the source invalidates every translation of it** — the whole
   mechanism, and the thing a promise to "remember to update the others"
   cannot deliver;
3. the gate refuses to report a pass over an empty scan.

Nothing here asserts a translation is *good*. That is not checkable and is not
claimed anywhere in this feature.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from integral import presentation, strings

_REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def catalogue() -> dict[str, Any]:
    loaded: dict[str, Any] = strings.load()
    return loaded


def test_the_shipped_catalogue_is_complete_and_current(catalogue: dict[str, Any]) -> None:
    """The committed file, not a fixture: this is the state the repo ships."""
    assert strings.missing(catalogue) == []
    assert strings.stale(catalogue) == []


def test_every_declared_language_has_every_string(catalogue: dict[str, Any]) -> None:
    for language in catalogue["languages"]:
        for key in strings.keys(catalogue):
            assert strings.text(catalogue, key, language), f"{language}:{key} is empty"


def test_changing_the_source_makes_every_translation_of_it_stale(catalogue: dict[str, Any]) -> None:
    """The rule, mechanised. Edit the English and the languages that were
    translated from the old English stop matching — no reviewer has to notice."""
    catalogue["entries"]["excluded_heading"]["en"] = "Ruled out"
    outdated = strings.stale(catalogue)
    assert "es:excluded_heading" in outdated
    assert "ca:excluded_heading" in outdated
    # And only that string: a wording change must not invalidate the catalogue.
    assert all(entry.endswith(":excluded_heading") for entry in outdated), outdated


def test_a_stale_translation_falls_back_rather_than_showing_old_wording(
    catalogue: dict[str, Any],
) -> None:
    """Confidently wrong is worse than visibly foreign. A translation of text
    that has since changed describes something the page no longer says."""
    catalogue["entries"]["excluded_heading"]["en"] = "Ruled out"
    assert strings.text(catalogue, "excluded_heading", "es") == "Ruled out"


def test_a_translation_with_no_recorded_source_counts_as_stale(catalogue: dict[str, Any]) -> None:
    """An unstamped entry is exactly the state this mechanism replaces, so it
    must not be able to opt out by omitting its provenance."""
    catalogue["entries"]["excluded_heading"]["es"] = "Descartadas"
    assert "es:excluded_heading" in strings.stale(catalogue)


def test_an_unserved_language_falls_back_and_says_which(catalogue: dict[str, Any]) -> None:
    """German has no pack. Every string falls back, and every one is named —
    silent English is the defect T107 exists to close."""
    fell_back = strings.fallbacks(catalogue, "de")
    assert set(fell_back) == set(strings.keys(catalogue))
    assert strings.fallbacks(catalogue, "es") == []


def test_the_gate_refuses_to_pass_over_an_empty_scan(tmp_path: Path) -> None:
    """A zero over nothing is what a check that never ran also reports."""
    thin = tmp_path / "catalogue.json"
    thin.write_text(
        json.dumps(
            {
                "source_language": "en",
                "languages": ["en", "es"],
                "entries": {
                    "only": {"en": "one", "es": {"text": "uno", "of": strings.digest("one")}}
                },
            }
        ),
        encoding="utf-8",
    )
    measured = strings.measure(thin)
    assert measured["gate_status"] == "unmeasured"
    assert measured["strings_scanned"] < strings.MINIMUM_STRINGS


def test_an_unreadable_catalogue_is_unmeasured_not_zero(tmp_path: Path) -> None:
    measured = strings.measure(tmp_path / "absent.json")
    assert measured["gate_status"] == "unmeasured"
    assert measured["candidate_facing_strings_without_a_translation"] == -1


def test_stamping_does_not_invent_a_translation(catalogue: dict[str, Any]) -> None:
    """`stamp` records provenance for text somebody wrote. It must never
    manufacture an entry, which would turn a missing translation into a
    present one on the strength of running a script."""
    del catalogue["entries"]["excluded_heading"]["es"]
    strings.stamp(catalogue)
    assert "es:excluded_heading" in strings.missing(catalogue)


# ---------------------------------------------------------------------------
# the seam, from the page's side


def test_the_source_language_page_is_byte_identical_to_before_the_seam() -> None:
    """The catalogue must not have changed what an English page says — every
    gate that matches exact bytes still matches."""
    assert presentation.EXCLUDED_HEADING == "Excluded"
    assert presentation.FLAG_MARKER == "[flagged — your call]"
    assert presentation.UNKNOWN == "unknown"
    assert presentation.ESTIMATED_MARKER == "(estimated — the advert did not say)"


def test_a_page_renders_in_the_candidates_language() -> None:
    offers, _ = presentation._fixture()
    ranking, _ = presentation._page(presentation._FIXTURE_WEIGHTS)
    spanish = presentation.render(ranking, offers, explanations={}, language="es")
    catalan = presentation.render(ranking, offers, explanations={}, language="ca")
    assert "sueldo:" in spanish and "ubicación:" in spanish
    assert "sou:" in catalan and "ubicació:" in catalan
    assert "location:" not in spanish


def test_the_card_column_follows_the_labels_rather_than_being_typed() -> None:
    """`ubicación` is longer than `location`; a hardcoded column renders one of
    the two ragged."""
    for language in ("en", "es", "ca"):
        page = presentation.card(presentation._fixture()[0][0], language=language)
        rows = [line for line in page.splitlines() if line.startswith("  ") and ":" in line]
        columns = {len(line) - len(line.split(":", 1)[1].lstrip()) for line in rows}
        assert len(columns) == 1, f"{language}: ragged columns {columns}"


def test_the_pay_period_is_rendered_not_passed_through() -> None:
    """Without this a Spanish card reads `EUR/year`."""
    offers, _ = presentation._fixture()
    assert "/año" in presentation._salary(offers[0], "es")
    assert "/any" in presentation._salary(offers[0], "ca")
    assert "/year" in presentation._salary(offers[0])
