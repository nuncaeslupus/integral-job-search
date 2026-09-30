"""T217 — topics stated before T203 are visible to step 7 until they are recorded.

A profile begun before `source()` read `search/exclusions.json` holds its
ruled-out topics only as evidence rows, so its exclusions filter nothing and
nothing looked wrong. These fixtures are invented candidates; no real profile
is read.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from integral import sourcing_exclusions as se
from integral.identity import ProfileStore, create_profile
from integral.sourcing_exclusions import (
    Exclusion,
    backfill_warning,
    record_exclusion,
    states_a_refusal,
    unrecorded_statements,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_STEP_7_CHECKPOINT = (
    _REPO_ROOT / ".claude" / "skills" / "step-07-sourcing" / "scripts" / "run_checkpoint.py"
)


def _row(n: int, step: str, text: str, kind: str = "constraint", **extra: Any) -> dict[str, Any]:
    return {
        "id": f"ev-{n:06d}",
        "recorded_at": "2026-09-01T10:00:00Z",
        "step": step,
        "kind": kind,
        "text": text,
        "source": "conversation",
        **extra,
    }


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "profiles"


def _profile(root: Path, rows: list[dict[str, Any]]) -> ProfileStore:
    identity = create_profile(root, "T217 Probe", handle="t217-probe", fiction=True)
    store = ProfileStore(root, identity.handle)
    for row in rows:
        store.append_jsonl(row, "profile", "evidence.jsonl")
    return store


_PRE_T203 = [
    _row(9, "constraints", "defensa, apuestas, tabacos, bancos"),
    _row(26, "constraints", "no me gusta todo lo que sea comprar y vender (e-commerce, etc.)"),
    _row(30, "identify", "ya tuve bastante de fintechs", kind="statement"),
    _row(31, "constraints", "no m'interessa la ciberseguretat"),
    _row(40, "constraints", "Vivo en Barcelona y trabajo en remoto", kind="statement"),
    _row(41, "history", "No me gustaba la banca en mi anterior trabajo", kind="episode"),
]


def test_a_pre_t203_profile_is_warned_with_every_stating_row(root: Path) -> None:
    store = _profile(root, _PRE_T203)
    ids = [row.evidence_id for row in unrecorded_statements(store)]
    # Row 40 refuses nothing; row 41 is history, not a statement of what rules a job out.
    assert ids == ["ev-000009", "ev-000026", "ev-000030", "ev-000031"]
    warning = backfill_warning(store)
    assert warning is not None and warning.startswith("WARNING")
    assert "records nothing" in warning


def test_the_backfill_closes_the_warning_one_topic_at_a_time(root: Path) -> None:
    store = _profile(root, _PRE_T203)
    record_exclusion(
        store, Exclusion(about="sector:bancos", stated_at_cycle=1, words="bancos", terms=("bank",))
    )
    left = [row.evidence_id for row in unrecorded_statements(store)]
    assert left == ["ev-000026", "ev-000030", "ev-000031"]
    partial = backfill_warning(store)
    assert partial is not None and partial.startswith("note:")
    for about, words, terms in (
        ("sector:e-commerce", "comprar y vender", ("ecommerce",)),
        ("sector:fintech", "ya tuve bastante de fintechs", ()),
        ("topic:ciberseguridad", "no m'interessa", ("ciberseguretat", "cybersecurity")),
    ):
        record_exclusion(store, Exclusion(about=about, stated_at_cycle=1, words=words, terms=terms))
    assert unrecorded_statements(store) == ()
    assert backfill_warning(store) is None


def test_a_retracted_statement_is_not_asked_for(root: Path) -> None:
    rows = [
        _row(1, "constraints", "nada de consultoras"),
        _row(2, "constraints", "retiro lo de consultoras", kind="retraction", retracts="ev-000001"),
    ]
    assert unrecorded_statements(_profile(root, rows)) == ()


def test_a_profile_with_no_evidence_says_nothing(root: Path) -> None:
    store = _profile(root, [])
    assert unrecorded_statements(store) == ()
    assert backfill_warning(store) is None


@pytest.mark.parametrize(
    "text",
    [
        "no quiero banca",
        "not interested in adtech",
        "prefiero evitar el gambling",
        "I'd rule out defence",
        "estic farta del retail",
        "nothing to do with betting",
        "Descartado: tabaco",
    ],
)
def test_the_cue_hears_a_refusal_in_es_en_ca(text: str) -> None:
    assert states_a_refusal(text)


@pytest.mark.parametrize(
    "text",
    [
        "I don\u2019t want to work in banking",
        "I don\u2018t want to work in banking",
        "odio la banca",
        "paso de la banca",
        "detesto la publicidad",
        "me niego a trabajar en defensa",
        "ning\u00fan inter\u00e9s en defensa",
        "cero inter\u00e9s en la ciberseguridad",
        "Tabaco: jam\u00e1s",
        "estoy quemado de las fintechs",
        "cap interès en la banca",
        "I hate adtech",
        "dislike ad tech",
        "Stay away from gambling",
        "I'm done with fintech",
        "sick of fintech",
        "fed up with ecommerce",
        "I refuse to work for defence contractors",
        "ruling out defence",
    ],
)
def test_the_cue_hears_the_wider_wordings_and_curly_apostrophes(text: str) -> None:
    assert states_a_refusal(text)


@pytest.mark.parametrize("text", ["Vivo en Barcelona", "Busco un rol de backend en Python"])
def test_the_cue_is_silent_on_a_plain_statement(text: str) -> None:
    assert not states_a_refusal(text)


def test_the_unrecorded_cli_exits_1_until_the_backfill_is_done(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = _profile(root, _PRE_T203[:1])
    argv = ["prog", "unrecorded", "--handle", store.handle, "--root", str(root)]
    assert se._main(argv) == 1
    out = capsys.readouterr()
    assert json.loads(out.out.splitlines()[0])["evidence_id"] == "ev-000009"
    assert "WARNING" in out.err
    for topic in ("defensa", "apuestas", "tabacos", "bancos"):
        record_exclusion(store, Exclusion(about=f"sector:{topic}", stated_at_cycle=1, words=topic))
    assert se._main(argv) == 0


def _drive_step_7_checkpoint(root: Path, handle: str) -> dict[str, Any]:
    spec = importlib.util.spec_from_file_location("_t217_step_7_checkpoint", _STEP_7_CHECKPOINT)
    assert spec is not None and spec.loader is not None
    module: Any = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            spec.loader.exec_module(module)
            return dict(module.checkpoint(root, handle))
    finally:
        sys.modules.pop(spec.name, None)


def test_the_step_7_checkpoint_carries_the_warning(root: Path) -> None:
    store = _profile(root, _PRE_T203)
    result = _drive_step_7_checkpoint(root, store.handle)
    assert result["exclusions_recorded"] == 0
    assert [r["evidence_id"] for r in result["unrecorded_exclusion_statements"]] == [
        "ev-000009",
        "ev-000026",
        "ev-000030",
        "ev-000031",
    ]
    assert result["exclusion_backfill_warning"].startswith("WARNING")


def test_a_constraint_row_with_no_cue_is_listed_but_a_statement_row_is_not(root: Path) -> None:
    rows = [
        _row(1, "constraints", "defensa, apuestas, tabacos, bancos"),
        _row(2, "constraints", "Vivo en Barcelona", kind="statement"),
    ]
    store = _profile(root, rows)
    assert [r.evidence_id for r in unrecorded_statements(store)] == ["ev-000001"]
    warning = backfill_warning(store)
    assert warning is not None and warning.startswith("WARNING") and "ev-000001" in warning


def test_the_unrecorded_cli_fails_for_a_handle_with_no_profile(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root.mkdir()
    assert se._main(["prog", "unrecorded", "--handle", "nobody-here", "--root", str(root)]) != 0
    assert "nobody-here" in capsys.readouterr().err


def _load_checkpoint_module() -> Any:
    spec = importlib.util.spec_from_file_location("_t217_main_checkpoint", _STEP_7_CHECKPOINT)
    assert spec is not None and spec.loader is not None
    module: Any = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_checkpoint_main_prints_the_warning_to_stderr(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = _profile(root, _PRE_T203)
    try:
        module = _load_checkpoint_module()
        module.main(["--id", store.handle, "--input-dir", str(root), "--dev"])
    finally:
        sys.modules.pop("_t217_main_checkpoint", None)
    assert capsys.readouterr().err.startswith("WARNING")


def test_a_corrupt_evidence_log_makes_the_checkpoint_main_exit_2(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = _profile(root, _PRE_T203[:1])
    store.path("profile", "evidence.jsonl").write_text("{not json\n", encoding="utf-8")
    try:
        module = _load_checkpoint_module()
        code = module.main(["--id", store.handle, "--input-dir", str(root), "--dev"])
    finally:
        sys.modules.pop("_t217_main_checkpoint", None)
    assert code == 2
    assert "could not be computed" in capsys.readouterr().err
