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
# ids[0], ids[1], ids[2] are the three sentences above, in order.
LETTER = (
    "Estimats,\n\n"
    "Vaig estar a l'altra banda d'aquesta conversa.\n\n"
    "El biaix de gènere als laboratoris em preocupa.\n\n"
    "Era la compradora a qui venien, i ho recordo bé."
)


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


def rows_for(ids: list[str], **override: str) -> list[str]:
    base = {
        "1": "| 1 | assistant | | |",
        "2": f"| 2 | candidate | {ids[0]} | |",
        "3": f"| 3 | candidate | {ids[2]} | |",
        "4": f"| 4 | edited | {ids[1]} | added a clause at the end |",
    }
    base.update(override)
    return [base[k] for k in sorted(base)]


def good(ids: list[str], **override: str) -> str:
    return table(*rows_for(ids, **override))


def check(store: ProfileStore, letter: str, trazabilidad: str):  # type: ignore[no-untyped-def]
    return check_authorship(letter, trazabilidad, EvidenceLog(store))


# --- the two named tests -------------------------------------------------------


def test_package_records_authorship_per_paragraph(store: ProfileStore, tmp_path: Path) -> None:
    ids = harvest_draft(store, DRAFT, recorded_at="2026-09-15T10:00:00Z")
    version = tmp_path / "v1"
    version.mkdir()
    (version / "carta.md").write_text(LETTER, encoding="utf-8")

    (version / "trazabilidad.md").write_text(good(ids), encoding="utf-8")
    assert check_package(version, store).ok

    # Each of these claims no candidate source (or no author) for some paragraph.
    broken = {
        "no table at all": "# Trazabilitat\n",
        "paragraph 4 has no row": table(*rows_for(ids)[:3]),
        "candidate with no source": good(ids, **{"2": "| 2 | candidate | | |"}),
        "edited with no source": good(ids, **{"4": "| 4 | edited | | x |"}),
        "source is not in the log": good(ids, **{"2": "| 2 | candidate | ev-009999 | |"}),
        "assistant borrowing a source": good(ids, **{"1": f"| 1 | assistant | {ids[0]} | |"}),
        "unknown author": good(ids, **{"1": "| 1 | model | | |"}),
        "duplicate row": good(ids) + "| 2 | assistant | | |\n",
        "row for a paragraph the letter lacks": good(ids) + "| 5 | assistant | | |\n",
    }
    for label, trazabilidad in broken.items():
        (version / "trazabilidad.md").write_text(trazabilidad, encoding="utf-8")
        assert not check_package(version, store).ok, label


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
    report = check(store, LETTER, good(ids))
    assert not report.ok and any(ids[0] in d for d in report.defects)


def test_a_source_from_another_kind_of_row_does_not_count(store: ProfileStore) -> None:
    ids = harvest_draft(store, DRAFT, recorded_at="t")
    other = EvidenceLog(store).append(
        recorded_at="t",
        step="application",
        kind="statement",
        text="Vaig estar a l'altra banda d'aquesta conversa.",
        source="application_draft",
    )
    assert not check(store, LETTER, good(ids, **{"2": f"| 2 | candidate | {other.id} | |"})).ok


def test_paragraph_count_is_derived_from_the_letter(store: ProfileStore) -> None:
    ids = harvest_draft(store, DRAFT, recorded_at="t")
    assert check(store, LETTER, good(ids)).ok
    assert not check(store, LETTER + "\n\nUn cinquè paràgraf.", good(ids)).ok
    assert letter_paragraphs("Un.\n\nDos.\n\n\n\nTres.") == ["Un.", "Dos.", "Tres."]


def test_an_empty_draft_is_not_harvested(store: ProfileStore) -> None:
    with pytest.raises(AuthorshipError):
        harvest_draft(store, " \n\n ", recorded_at="t")
    assert EvidenceLog(store).rows() == []


def test_the_author_set_is_closed_even_when_the_source_is_live(store: ProfileStore) -> None:
    ids = harvest_draft(store, DRAFT, recorded_at="t")
    for name in ("Claude", "model", "co-written", ""):
        row = f"| 2 | {name} | {ids[0]} | |"
        report = check(store, LETTER, good(ids, **{"2": row}))
        assert not report.ok and any("is not one of" in d for d in report.defects), name


def test_a_candidate_row_is_exactly_the_cited_sentences(store: ProfileStore) -> None:
    ids = harvest_draft(store, DRAFT, recorded_at="t")
    other = "Sóc una professional apassionada amb una sòlida trajectòria."
    cases = {
        "an unrelated paragraph": LETTER.replace(
            "El biaix de gènere als laboratoris em preocupa.", other
        ),
        "a cited sentence plus one more": LETTER.replace("em preocupa.", "em preocupa. I molt."),
        "the sentences in another order": LETTER.replace(
            "Vaig estar a l'altra banda d'aquesta conversa.",
            "Era la compradora a qui venien. Vaig estar a l'altra banda d'aquesta conversa.",
        ),
    }
    for label, letter in cases.items():
        assert not check(store, letter, good(ids)).ok, label
    # Whitespace is not a change.
    spaced = LETTER.replace("banda d'aquesta", "banda   d'aquesta")
    assert check(store, spaced, good(ids)).ok
    # Another candidate's package cites ev-000001 too: ids are per-log, so the text must agree.
    foreign = LETTER.replace("Vaig estar a l'altra banda d'aquesta conversa.", other)
    assert not check(store, foreign, good(ids)).ok


def test_an_edited_row_must_still_contain_what_it_cites(store: ProfileStore) -> None:
    ids = harvest_draft(store, DRAFT, recorded_at="t")
    unrelated = LETTER.replace(
        "Era la compradora a qui venien, i ho recordo bé.", "Cap relació amb res."
    )
    report = check(store, unrelated, good(ids))
    assert not report.ok and any("is not in it" in d for d in report.defects)


@pytest.mark.parametrize(
    "cell", ["", " ", "-", "—", "\u2013", "none", "None", "NONE", "N/A", "n/a", "No changes", "..."]
)
def test_an_edited_row_must_name_a_change(store: ProfileStore, cell: str) -> None:
    ids = harvest_draft(store, DRAFT, recorded_at="t")
    row = f"| 4 | edited | {ids[1]} | {cell} |"
    assert not check(store, LETTER, good(ids, **{"4": row})).ok


def test_a_heading_in_the_letter_is_refused(store: ProfileStore) -> None:
    ids = harvest_draft(store, DRAFT, recorded_at="t")
    for heading in ("# Sóc la millor candidata.", "#Compromís", "### Motivació"):
        report = check(store, heading + "\n\n" + LETTER, good(ids))
        assert not report.ok and any("heading" in d for d in report.defects), heading


def test_a_non_ascii_digit_paragraph_number_is_a_defect_not_a_crash(store: ProfileStore) -> None:
    ids = harvest_draft(store, DRAFT, recorded_at="t")
    assert not check(store, LETTER, good(ids) + "| ² | assistant | | |\n").ok


# --- the skill states the rule, and states it as the code does ------------------

RULE = [
    "The skill never writes a letter the candidate has not written first.",
    "What the skill produces from the candidate's draft is an edit: their text with named "
    "changes, each one a sentence they can veto.",
    "A sentence the skill wrote and the candidate did not say is marked assistant in "
    "trazabilidad.md.",
    "Every sentence of the candidate's draft is harvested to the evidence log in the same pass.",
]

_LETTER = re.compile(r"\b(letter|carta)\b", re.I)
_OWNED = re.compile(
    r"\b(your|their|candidate'?s?|own|tu|teu|teva|vostra)\b|\b(?:the )?candidate", re.I
)
_SESSION_VERB = re.compile(
    r"\b(draft(?:s|ed|ing)?|compos(?:e|es|ed|ing)|writ(?:e|es|ing)|wrote|generat(?:e|es|ed|ing)"
    r"|produc(?:e|es|ed|ing)|prepar(?:e|es|ed|ing)|build(?:s|ing)?|put(?:s|ting)? together)\b",
    re.I,
)
_PROHIBITION = re.compile(r"\b(never|not|no letter|declin\w*|do not|don'?t)\b", re.I)


def authorship_violations(text: str) -> list[str]:
    """Lines of a skill that have the session produce a letter that is not the candidate's.

    The property, not a spelling: in the spoken examples, *any* mention of the letter
    must be of the candidate's (`your letter`); in instructions, a line that has the
    session draft, write or build a letter must either own it to the candidate or
    forbid it. The rule's own fence is exempt: it is the prohibition.
    """
    out: list[str] = []
    in_fence = False
    fence_lang = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            fence_lang = line[3:].strip() if in_fence else ""
            continue
        if not in_fence:
            line = re.sub(r"`[^`]*`", "", line)  # a path or identifier is not an instruction
        if not _LETTER.search(line):
            continue
        if in_fence:
            if fence_lang != "text":
                continue
            for sentence in re.split(r"(?<=[.!?])\s+", line):
                unowned = _LETTER.search(sentence) and not _OWNED.search(sentence)
                if unowned and "never writes" not in sentence:
                    out.append(sentence)
        elif (
            _SESSION_VERB.search(line) and not _OWNED.search(line) and not _PROHIBITION.search(line)
        ):
            out.append(line)
    return out


def _skill() -> str:
    return SKILL.read_text(encoding="utf-8")


def test_skill_carries_the_rule_verbatim_in_its_fence() -> None:
    fence = re.search(r"The rule, verbatim.*?```text\n(.*?)```", _skill(), re.S)
    assert fence is not None
    # Each rule sentence is one line in the fence; compare joined text so wrapping is free.
    assert " ".join(fence.group(1).split()) == " ".join(RULE)


def test_nothing_in_the_skill_has_the_session_write_the_letter_first() -> None:
    assert authorship_violations(_skill()) == []
    # And the prohibition itself is there: an instruction line that forbids composing it.
    assert any(
        _SESSION_VERB.search(ln) and _LETTER.search(ln) and re.match(r"\s*- Never\b", ln)
        for ln in _skill().splitlines()
    )
    assert "Select from the store against what the advert asks for, draft, and show" not in _skill()


def test_the_closed_rule_would_have_caught_the_text_it_replaced() -> None:
    old = (
        "```text\n"
        '"Drafting the CV and the letter for this one — this takes a moment."\n'
        '"Thanks for waiting — here\'s the draft. …"\n'
        "```\n"
        "```text\n"
        "\"That's the CV and letter for the Girona role. I've led with the migration work.\"\n"
        "```\n"
        "1. Draft the letter from the store, then show it.\n"
        "- The skill writes a covering letter for the offer.\n"
    )
    found = authorship_violations(old)
    assert len(found) == 4, found
    # And the owned forms it was replaced with pass.
    assert (
        authorship_violations(
            '```text\n"Going through your letter for this one — this takes a moment."\n```\n'
            "- Never write the letter before the candidate has.\n"
            "- Edit the candidate's letter; do not compose one.\n"
        )
        == []
    )


def test_skill_names_the_identifiers_the_code_checks() -> None:
    text = _skill()
    assert SECTION in text
    for author in AUTHORS:
        assert f"`{author}`" in text
    assert 'kind="candidate_statement"' in text and 'source="application_draft"' in text
    for fn in ("harvest_draft", "check_package"):
        assert f"integral.application_authorship.{fn}" in text
        assert callable(getattr(aa, fn))
