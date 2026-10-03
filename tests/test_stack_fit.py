"""T219 — the candidate's CV stack reaches the ranking, and statements override it.

The correctness cases live in `tests/fixtures/stack_fit/cases.json`, written by
a session other than the implementer from the task's spec; each one runs here
as its own test so a failure names the case and the rule it cites. The tests
below that are about wiring — the store, the log, `rank` — are the
implementer's.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from integral import stack_fit
from integral.cv_store import CVMaster, write_master
from integral.identity import ProfileStore, create_profile
from integral.profile import (
    EvidenceLog,
    EvidenceRow,
    EvidenceSubject,
    ProfileRevision,
    SkillStance,
)
from integral.rank import Candidate, rank

CASES: list[dict[str, Any]] = json.loads(stack_fit.DEFAULT_CASES_PATH.read_text(encoding="utf-8"))[
    "cases"
]


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_second_reader_case(case: dict[str, Any]) -> None:
    assert stack_fit.disagreements([case]) == []


def test_the_case_file_is_above_its_floor() -> None:
    assert len(CASES) >= stack_fit.MINIMUM_CASES


def test_the_gate_is_measured_and_clean() -> None:
    measured = stack_fit.measure()
    assert measured["gate_status"] == "measured"
    assert measured["stack_fit_cases_disagreeing"] == 0
    assert measured["cv_records_unread_by_ranking"] == 0


def test_an_emptied_case_file_is_unmeasured_not_clean(tmp_path: Path) -> None:
    empty = tmp_path / "cases.json"
    empty.write_text('{"cases": []}', encoding="utf-8")
    measured = stack_fit.measure(empty)
    assert measured["gate_status"] == "unmeasured"
    assert measured["stack_fit_cases_disagreeing"] == -1


def _store(tmp_path: Path, master: dict[str, Any]) -> ProfileStore:
    identity = create_profile(tmp_path, "Stack Test", handle="stack-test")
    store = ProfileStore(tmp_path, identity.handle)
    write_master(store, CVMaster.model_validate(master))
    return store


def _offer(store: ProfileStore, offer_id: str, title: str, text: str) -> None:
    store.write_json({"id": offer_id, "title": title, "text": text}, "offers", f"{offer_id}.json")


def test_the_reported_session_python_candidate_against_a_go_offer(tmp_path: Path) -> None:
    """The 2026-09-30 shape: a Python-strong CV, an offer naming Go, TypeScript, Kubernetes."""
    store = _store(
        tmp_path,
        {
            "skills": [
                {"name": "Python", "level": "expert"},
                {"name": "Java", "level": "working"},
                {"name": "Kubernetes", "level": "basic"},
            ],
            "episodes": [{"kind": "achievement", "text": "Built an agentic triage tool."}],
        },
    )
    log = EvidenceLog(store)
    log.append(
        recorded_at="2026-09-30T10:00:00Z",
        step="ranking",
        kind="statement",
        text="Kubernetes no sé cómo funciona",
        source="conversation",
        skill=SkillStance(technology="kubernetes", level="none"),
    )
    _offer(store, "go-shop", "Platform engineer", "We use Go, TypeScript and Kubernetes.")
    _offer(store, "agents", "AI engineer", "Python and AI agents in production.")
    fits = stack_fit.fits_for_store(store, ["go-shop", "agents", "not-stored"])
    assert set(fits) == {"go-shop", "agents"}
    assert fits["go-shop"]["verdict"] == "mismatch"
    assert fits["go-shop"]["weak"] == ["kubernetes"]
    assert fits["go-shop"]["sources"]["kubernetes"].startswith("ev-")
    assert fits["go-shop"]["missing"] == ["go", "typescript"]
    assert fits["agents"]["verdict"] == "partial"
    assert fits["agents"]["used"] == ["ai_agents"]
    assert "no consta en tu CV: Go, TypeScript" in stack_fit.summary_line(fits["go-shop"])


def test_a_retracted_statement_stops_overriding(tmp_path: Path) -> None:
    store = _store(tmp_path, {"skills": [{"name": "Java", "level": "working"}]})
    log = EvidenceLog(store)
    hate = log.append(
        recorded_at="2026-09-30T10:00:00Z",
        step="ranking",
        kind="statement",
        text="odio Java",
        source="conversation",
        skill=SkillStance(technology="java", averse=True),
    )
    _offer(store, "j", "Backend", "Java 21.")
    assert stack_fit.fits_for_store(store, ["j"])["j"]["verdict"] == "mismatch"
    log.append(
        recorded_at="2026-09-30T10:05:00Z",
        step="ranking",
        kind="retraction",
        text="lo retiro",
        source="conversation",
        retracts=hate.id,
    )
    assert stack_fit.fits_for_store(store, ["j"])["j"]["verdict"] == "match"


def test_a_skill_stance_is_only_a_statement() -> None:
    with pytest.raises(ValidationError):
        EvidenceRow(
            id="ev-000001",
            recorded_at="2026-09-30T10:00:00Z",
            step="ranking",
            kind="reaction",
            text="x",
            source="conversation",
            skill=SkillStance(technology="java", averse=True),
        )
    with pytest.raises(ValidationError):
        SkillStance(technology="java")


def test_a_row_without_a_stance_is_written_as_before(tmp_path: Path) -> None:
    store = _store(tmp_path, {})
    row = EvidenceLog(store).append(
        recorded_at="2026-09-30T10:00:00Z",
        step="ranking",
        kind="statement",
        text="hola",
        source="conversation",
    )
    assert "skill" not in json.loads(row.canonical())


def test_rank_carries_the_fit_and_moves_nothing() -> None:
    candidates = [
        Candidate(offer_id="a", salary_per_month=None, scores={}),
        Candidate(offer_id="b", salary_per_month=4000.0, scores={}),
    ]
    kwargs: dict[str, Any] = {
        "dimensions": (),
        "revision": ProfileRevision.of_nothing(),
        "weights": None,
        "at": "2026-09-30T10:00:00Z",
    }
    fits = {"a": {"verdict": "match"}, "b": {"verdict": "mismatch"}}
    plain = rank(candidates, **kwargs)
    stated = rank(candidates, stack=fits, **kwargs)
    assert "stack_fit" not in plain
    assert stated["stack_fit"] == fits
    assert stated["pareto"] == plain["pareto"] == ["b", "a"]


def test_an_unresolvable_stance_raises_instead_of_going_unread() -> None:
    assert stack_fit.resolve_technology("K8S") == "kubernetes"
    assert stack_fit.resolve_technology("amazon_web_services") == "aws"
    with pytest.raises(stack_fit.StackFitError):
        stack_fit.resolve_technology("node")


_LAST_JOB = "At my last job I built LLM agent harnesses and AI agents for prompt tooling."


def _history_episode(store: ProfileStore, text: str = _LAST_JOB) -> EvidenceRow:
    return EvidenceLog(store).append(
        recorded_at="2026-09-30T10:00:00Z",
        step="history",
        kind="episode",
        text=text,
        source="conversation",
    )


def test_work_told_in_a_history_episode_is_not_missing(tmp_path: Path) -> None:
    """T245: the evidence log holds the work; `master.json` never received it."""
    store = _store(tmp_path, {"skills": [{"name": "Python", "level": "expert"}]})
    _offer(store, "ai", "AI engineer", "Python, LLM and AI agents in production.")
    assert stack_fit.fits_for_store(store, ["ai"])["ai"]["missing"] == ["ai_agents", "llm"]
    row = _history_episode(store)
    fit = stack_fit.fits_for_store(store, ["ai"])["ai"]
    assert fit["missing"] == []
    assert fit["used"] == ["ai_agents", "llm"]
    assert fit["sources"]["llm"] == f"log:{row.id}"


def test_a_retracted_history_episode_no_longer_counts(tmp_path: Path) -> None:
    store = _store(tmp_path, {"skills": [{"name": "Python", "level": "expert"}]})
    _offer(store, "ai", "AI engineer", "Python and AI agents.")
    row = _history_episode(store)
    assert stack_fit.fits_for_store(store, ["ai"])["ai"]["missing"] == []
    EvidenceLog(store).append(
        recorded_at="2026-09-30T10:05:00Z",
        step="history",
        kind="retraction",
        text="forget that",
        source="conversation",
        retracts=row.id,
    )
    assert stack_fit.fits_for_store(store, ["ai"])["ai"]["missing"] == ["ai_agents"]


def test_a_stance_row_is_not_read_as_prose(tmp_path: Path) -> None:
    """ "no sé Kubernetes" must not credit Kubernetes as used."""
    store = _store(tmp_path, {"skills": [{"name": "Python", "level": "expert"}]})
    _offer(store, "k", "Platform", "Kubernetes.")
    EvidenceLog(store).append(
        recorded_at="2026-09-30T10:00:00Z",
        step="ranking",
        kind="statement",
        text="Kubernetes no sé cómo funciona",
        source="conversation",
        skill=SkillStance(technology="kubernetes", level="none"),
    )
    fit = stack_fit.fits_for_store(store, ["k"])["k"]
    assert fit["weak"] == ["kubernetes"]
    assert fit["used"] == []


def test_a_master_episode_whose_log_row_was_retracted_is_skipped(tmp_path: Path) -> None:
    store = _store(tmp_path, {})
    row = _history_episode(store)
    master = CVMaster.model_validate(
        {
            "episodes": [
                {
                    "kind": "achievement",
                    "text": _LAST_JOB,
                    "provenance": [{"kind": "conversation_turn", "evidence_id": row.id}],
                }
            ]
        }
    )
    assert "llm" in stack_fit.candidate_stack(master)
    assert "llm" not in stack_fit.candidate_stack(master, (), frozenset({row.id}))


def test_the_store_path_honours_a_retraction_of_a_master_episodes_log_row(tmp_path: Path) -> None:
    store = _store(tmp_path, {})
    row = _history_episode(store, "Shipped a gateway in Go.")
    write_master(
        store,
        CVMaster.model_validate(
            {
                "episodes": [
                    {
                        "kind": "achievement",
                        "text": "Shipped a gateway in Go.",
                        "provenance": [{"kind": "conversation_turn", "evidence_id": row.id}],
                    }
                ]
            }
        ),
    )
    _offer(store, "g", "Backend", "We write Go services.")
    assert stack_fit.fits_for_store(store, ["g"])["g"]["missing"] == []
    EvidenceLog(store).append(
        recorded_at="2026-09-30T10:05:00Z",
        step="history",
        kind="retraction",
        text="forget that",
        source="conversation",
        retracts=row.id,
    )
    assert stack_fit.fits_for_store(store, ["g"])["g"]["missing"] == ["go"]


_OFFER_ID = "sha256:" + "a" * 64
_NOT_WORK_DONE = [
    ("statement", "I have never used Kubernetes.", "kubernetes"),
    ("statement", "No he tocado Kubernetes en mi vida.", "kubernetes"),
    ("statement", "I would like to learn Rust next.", "rust"),
    ("statement", "I refuse to work with PHP again.", "php"),
    ("reaction", "That reads like a Go shop and I would hate it.", "go"),
    ("constraint", "No PHP shops.", "php"),
    ("outcome", "Rejected: they wanted Rust.", "rust"),
]


@pytest.mark.parametrize(("kind", "text", "technology"), _NOT_WORK_DONE)
def test_a_row_that_is_not_work_done_never_credits_a_technology(
    tmp_path: Path, kind: Any, text: str, technology: str
) -> None:
    store = _store(tmp_path, {"skills": [{"name": "Python", "level": "expert"}]})
    spelled = {"kubernetes": "Kubernetes", "rust": "Rust", "php": "PHP", "go": "Golang"}
    _offer(store, "o", "Engineer", f"We use {spelled[technology]} daily.")
    _offer(store, "other", "Other", "Golang and Kubernetes.")
    EvidenceLog(store).append(
        recorded_at="2026-09-30T10:00:00Z",
        step="feedback",
        kind=kind,
        text=text,
        source="offer_reaction",
        about=EvidenceSubject(kind="offer", id=_OFFER_ID),
    )
    fits = stack_fit.fits_for_store(store, ["o", "other"])
    for fit in fits.values():
        assert fit["used"] == []
        assert fit["match"] == []
    assert technology in fits["o"]["missing"]


def test_a_step_ten_reason_credits_nothing_on_any_offer(tmp_path: Path) -> None:
    store = _store(tmp_path, {})
    _offer(store, "a", "Engineer", "Kubernetes and LLM work.")
    _offer(store, "b", "Engineer", "LLM platform.")
    EvidenceLog(store).append(
        recorded_at="2026-09-30T10:00:00Z",
        step="feedback",
        kind="statement",
        text="asks for Kubernetes and LLM experience, which I don't have",
        source="offer_reaction",
        about=EvidenceSubject(kind="offer", id=_OFFER_ID),
    )
    fits = stack_fit.fits_for_store(store, ["a", "b"])
    assert fits["a"]["missing"] == ["kubernetes", "llm"]
    assert fits["b"]["missing"] == ["llm"]


def test_a_retraction_matched_only_by_text_withdraws_a_master_episode(tmp_path: Path) -> None:
    said = "Shipped a gateway in Go for two years."
    store = _store(tmp_path, {"episodes": [{"kind": "achievement", "text": said}]})
    _offer(store, "g", "Backend", "We write Go services.")
    assert stack_fit.fits_for_store(store, ["g"])["g"]["missing"] == []
    row = EvidenceLog(store).append(
        recorded_at="2026-09-30T10:00:00Z",
        step="intake",
        kind="statement",
        text=said,
        source="conversation",
    )
    EvidenceLog(store).append(
        recorded_at="2026-09-30T10:05:00Z",
        step="intake",
        kind="retraction",
        text="forget that",
        source="conversation",
        retracts=row.id,
    )
    assert stack_fit.fits_for_store(store, ["g"])["g"]["missing"] == ["go"]


def test_candidate_stack_accepts_a_one_shot_iterator(tmp_path: Path) -> None:
    """Both passes over the rows (prose, then stance) must see them."""
    store = _store(tmp_path, {})
    episode = _history_episode(store)
    stance = EvidenceLog(store).append(
        recorded_at="2026-09-30T10:01:00Z",
        step="ranking",
        kind="statement",
        text="odio Java",
        source="conversation",
        skill=SkillStance(technology="java", averse=True),
    )
    held = stack_fit.candidate_stack(CVMaster.model_validate({}), iter([episode, stance]))
    assert "llm" in held
    assert held["java"].averse


def test_an_aversion_only_row_is_not_credited_as_a_mention(tmp_path: Path) -> None:
    store = _store(tmp_path, {"skills": [{"name": "Python", "level": "expert"}]})
    _offer(store, "k", "Platform", "Kubernetes.")
    row = EvidenceLog(store).append(
        recorded_at="2026-09-30T10:00:00Z",
        step="ranking",
        kind="statement",
        text="odio Kubernetes",
        source="conversation",
        skill=SkillStance(technology="kubernetes", averse=True),
    )
    fit = stack_fit.fits_for_store(store, ["k"])["k"]
    assert fit["averse"] == ["kubernetes"]
    assert fit["sources"]["kubernetes"] == row.id
