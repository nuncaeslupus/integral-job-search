"""T180: the candidate writes the letter first; the package records who wrote each paragraph."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from integral import application_authorship as aa
from integral.application_authorship import (
    AUTHORS,
    SECTION,
    AuthorshipError,
    check_authorship,
    check_package,
    harvest_draft,
    letter_paragraphs,
)
from integral.identity import ProfileStore, create_profile
from integral.profile import EvidenceLog

SKILL = Path(__file__).resolve().parent.parent / ".claude/skills/step-11-application/SKILL.md"

DRAFT = (
    "Vaig estar a l'altra banda d'aquesta conversa. Era la compradora a qui venien.\n\n"
    "El biaix de gènere als laboratoris em preocupa."
)
LETTER = "Estimats,\n\nVaig estar a l'altra banda d'aquesta conversa.\n\nUn tercer paràgraf."


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    root = tmp_path / "profiles"
    identity = create_profile(root, "Vero", handle="vero", language="ca")
    return ProfileStore(root, identity.handle)


def table(*rows: str) -> str:
    head = (
        "# Trazabilitat\n\n## Authorship\n\n"
        "| Paragraph | Author | Evidence | Changes |\n|---|---|---|---|\n"
    )
    return head + "\n".join(rows) + "\n"


def good(ids: list[str]) -> str:
    return table(
        "| 1 | assistant | | |",
        f"| 2 | candidate | {ids[0]} | |",
        f"| 3 | edited | {ids[2]}, {ids[1]} | tightened the second clause |",
    )


# --- the two named tests -------------------------------------------------------


def test_package_records_authorship_per_paragraph(store: ProfileStore, tmp_path: Path) -> None:
    ids = harvest_draft(store, DRAFT, recorded_at="2026-09-15T10:00:00Z")
    version = tmp_path / "v1"
    version.mkdir()
    (version / "carta.md").write_text(LETTER, encoding="utf-8")

    (version / "trazabilidad.md").write_text(good(ids), encoding="utf-8")
    assert check_package(version, store).ok

    # Each of these claims no candidate source (or no author) for some paragraph.
    a1 = "| 1 | assistant | | |"
    c2 = f"| 2 | candidate | {ids[0]} | |"
    c3 = f"| 3 | candidate | {ids[1]} | |"
    broken = {
        "no table at all": "# Trazabilitat\n",
        "paragraph 3 has no row": table(a1, c2),
        "candidate with no source": table(a1, "| 2 | candidate | | |", c3),
        "edited with no source": table(a1, c2, "| 3 | edited | | x |"),
        "edited with no change named": table(a1, c2, f"| 3 | edited | {ids[1]} | |"),
        "source is not in the log": table(a1, "| 2 | candidate | ev-009999 | |", c3),
        "assistant borrowing a source": table(f"| 1 | assistant | {ids[0]} | |", c2, c3),
        "unknown author": table("| 1 | model | | |", c2, c3),
        "duplicate row": good(ids) + "| 2 | assistant | | |\n",
        "row for a paragraph the letter lacks": good(ids) + "| 4 | assistant | | |\n",
    }
    for label, trazabilidad in broken.items():
        (version / "trazabilidad.md").write_text(trazabilidad, encoding="utf-8")
        report = check_package(version, store)
        assert not report.ok, label
        assert report.paragraphs_with_no_named_author > 0, label


def test_candidate_draft_sentences_reach_the_evidence_log(store: ProfileStore) -> None:
    ids = harvest_draft(store, DRAFT, recorded_at="2026-09-15T10:00:00Z")
    rows = {r.id: r for r in EvidenceLog(store).rows()}
    assert [rows[i].text for i in ids] == [
        "Vaig estar a l'altra banda d'aquesta conversa.",
        "Era la compradora a qui venien.",
        "El biaix de gènere als laboratoris em preocupa.",
    ]
    for row in rows.values():
        assert row.kind == "candidate_statement"
        assert row.source == "application_draft"
        assert row.step == "application"


# --- the properties behind them ------------------------------------------------


def test_harvest_is_idempotent_and_adds_only_new_sentences(store: ProfileStore) -> None:
    first = harvest_draft(store, DRAFT, recorded_at="t1")
    second = harvest_draft(store, DRAFT + " Una frase nova.", recorded_at="t2")
    assert second[:3] == first and len(second) == 4
    assert len(EvidenceLog(store).rows()) == 4


def test_a_retracted_harvest_row_no_longer_authorises_a_paragraph(store: ProfileStore) -> None:
    ids = harvest_draft(store, DRAFT, recorded_at="t")
    EvidenceLog(store).append(
        recorded_at="t2",
        step="application",
        kind="retraction",
        text="withdrawn",
        source="application_draft",
        retracts=ids[0],
    )
    report = check_authorship(LETTER, good(ids), EvidenceLog(store))
    assert not report.ok and any(ids[0] in d for d in report.defects)


def test_a_source_from_another_kind_of_row_does_not_count(store: ProfileStore) -> None:
    ids = harvest_draft(store, DRAFT, recorded_at="t")
    other = EvidenceLog(store).append(
        recorded_at="t", step="application", kind="statement", text="x", source="application_draft"
    )
    trazabilidad = table(
        "| 1 | assistant | | |",
        f"| 2 | candidate | {other.id} | |",
        f"| 3 | candidate | {ids[0]} | |",
    )
    assert not check_authorship(LETTER, trazabilidad, EvidenceLog(store)).ok


def test_paragraph_count_is_derived_from_the_letter(store: ProfileStore) -> None:
    # A fourth paragraph appears; the old three-row table must stop passing.
    ids = harvest_draft(store, DRAFT, recorded_at="t")
    assert check_authorship(LETTER, good(ids), EvidenceLog(store)).ok
    longer = LETTER + "\n\nUn quart paràgraf."
    assert not check_authorship(longer, good(ids), EvidenceLog(store)).ok
    assert letter_paragraphs("# Carta\n\nUn.\n\n## Altre\n\nDos.") == ["Un.", "Dos."]


def test_an_empty_draft_is_not_harvested(store: ProfileStore) -> None:
    with pytest.raises(AuthorshipError):
        harvest_draft(store, " \n\n ", recorded_at="t")
    assert EvidenceLog(store).rows() == []


# --- the skill states the rule, and states it as the code does ------------------

RULE = [
    "The skill never writes a letter the candidate has not written first.",
    "What the skill produces from the candidate's draft is an edit: their text with named "
    "changes, each one a sentence they can veto.",
    "A sentence the skill wrote and the candidate did not say is marked assistant in "
    "trazabilidad.md.",
    "Every sentence of the candidate's draft is harvested to the evidence log in the same pass.",
]


def _skill() -> str:
    return SKILL.read_text(encoding="utf-8")


def test_skill_carries_the_rule_verbatim_in_its_fence() -> None:
    fence = re.search(r"The rule, verbatim.*?```text\n(.*?)```", _skill(), re.S)
    assert fence is not None
    # Each rule sentence is one line in the fence; compare joined text so wrapping is free.
    assert " ".join(fence.group(1).split()) == " ".join(RULE)


def test_skill_no_longer_tells_the_session_to_draft_the_letter_first() -> None:
    text = _skill()
    # The sentence this task replaced: select, *draft*, then show.
    assert "Select from the store against what the advert asks for, draft, and show" not in text
    # Every instruction to compose a letter is a prohibition: the line says "Never" first.
    for line in text.splitlines():
        if re.search(r"(?i)\bcompose the letter\b", line):
            assert line.lstrip("- ").startswith("Never "), line
    assert "Never compose the letter before the candidate has written theirs" in text


def test_skill_names_the_identifiers_the_code_checks() -> None:
    text = _skill()
    assert SECTION in text
    for author in AUTHORS:
        assert f"`{author}`" in text
    assert 'kind="candidate_statement"' in text and 'source="application_draft"' in text
    for fn in ("harvest_draft", "check_package"):
        assert f"integral.application_authorship.{fn}" in text
        assert callable(getattr(aa, fn))
