"""Pay transparency (directive 2023/970): ask for the range, never give current pay."""

from __future__ import annotations

from pathlib import Path

import pytest

from integral.candidate import OfferFacts
from integral.form_answers import FormAnswer, answer_defects
from integral.identity import ProfileStore, create_profile
from integral.pay_transparency import RANGE_PROMPT, range_prompt
from integral.profile import EvidenceLog

NO_RANGE = OfferFacts(offer_id="o1", country="ES", delivery="remote")
WITH_RANGE = NO_RANGE.model_copy(
    update={"salary_stated": True, "salary_min": 40000, "salary_max": 50000}
)


@pytest.mark.parametrize("lang", ["es", "en", "ca"])
def test_no_range_advert_prompts_in_each_language(lang: str) -> None:
    text = range_prompt(NO_RANGE, lang)  # type: ignore[arg-type]
    assert text == RANGE_PROMPT[lang] and "2023/970" in text  # type: ignore[index]
    assert len({RANGE_PROMPT[k] for k in ("es", "en", "ca")}) == 3


@pytest.mark.parametrize("lang", ["es", "en", "ca"])
def test_advert_with_a_range_does_not_prompt(lang: str) -> None:
    assert range_prompt(WITH_RANGE, lang) is None  # type: ignore[arg-type]


def _row(store: ProfileStore, kind: str, text: str) -> str:
    return (
        EvidenceLog(store)
        .append(
            recorded_at="2026-10-17T09:00:00Z",
            step="constraints",
            kind=kind,  # type: ignore[arg-type]
            text=text,
            source="conversation",
        )
        .id
    )


@pytest.mark.parametrize(
    ("question", "current"),
    [
        ("What is your current salary?", "My current salary is 38000 euros."),
        ("¿Cuál es tu salario actual?", "Mi salario actual es 38000 euros."),
        ("Quin és el teu sou actual?", "El meu sou actual és 38000 euros."),
    ],
)
def test_current_pay_question_refuses_a_current_pay_row(
    tmp_path: Path, question: str, current: str
) -> None:
    store = ProfileStore(tmp_path / "p", create_profile(tmp_path / "p", "Ada", handle="a").handle)
    floor = _row(store, "constraint", "My salary floor is 45000 euros.")
    bad = _row(store, "statement", current)
    live = {r.id: r for r in EvidenceLog(store).effective_rows()}
    ok = FormAnswer(
        question=question, text="My salary floor is 45000 euros.", evidence_ids=(floor,)
    )
    assert not [d for d in answer_defects(ok, live, ()) if d.startswith("pay:")]
    leak = FormAnswer(question=question, text=current, evidence_ids=(bad,))
    assert any(d.startswith("pay:") for d in answer_defects(leak, live, ()))
