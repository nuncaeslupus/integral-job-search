"""T218 — topics stated before T203 are visible to step 7 until they are recorded.

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
from integral.candidate import CONSTRAINT_FIELD_NAMES
from integral.identity import IdentityError, ProfileStore, create_profile
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
    identity = create_profile(root, "T218 Probe", handle="t218-probe", fiction=True)
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
        # From #598's second second-reader report (F1): each missed before.
        "tampoco apuestas",
        "rechazo el tabaco",
        "todo menos banca",
        "salvo defensa",
        "excepto apuestas",
        "vetado: tabaco",
        "defensa: fuera",
        "I can\u2019t stand adtech",
        "I cannot work in betting",
        "anything but banking",
        "reject defence",
        "tampoc apostes",
        "sense banca",
        "exclou la banca",
        "excloc la banca",
        "excluyo la banca",
        "rebutjo el tabac",
        "m'avorreix el retail",
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
    spec = importlib.util.spec_from_file_location("_t218_step_7_checkpoint", _STEP_7_CHECKPOINT)
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
    spec = importlib.util.spec_from_file_location("_t218_main_checkpoint", _STEP_7_CHECKPOINT)
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
        sys.modules.pop("_t218_main_checkpoint", None)
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
        sys.modules.pop("_t218_main_checkpoint", None)
    assert code == 2
    assert "could not be computed" in capsys.readouterr().err


def test_the_checkpoint_counts_what_is_recorded_and_quiets_to_a_note(root: Path) -> None:
    store = _profile(root, _PRE_T203)
    record_exclusion(store, Exclusion(about="sector:bancos", stated_at_cycle=1, words="bancos"))
    record_exclusion(store, Exclusion(about="sector:fintech", stated_at_cycle=1, words="fintechs"))
    result = _drive_step_7_checkpoint(root, store.handle)
    assert result["exclusions_recorded"] == 2
    assert result["exclusion_backfill_warning"].startswith("note:")


# Round 2 of the second reader: step 2 writes a `constraint` row for each of T24's
# pinned fields on every profile, and no topic can cover one — so listing them
# left the backfill loop unable to reach exit 0.


#: One value per pinned field that step 2 could replay (`FIELD_MODELS[f](state="stated", **v)`).
_STATED: dict[str, dict[str, Any]] = {
    "languages": {"levels": [{"language": "es", "level": "native"}]},
    "location": {"country": "ES"},
    "relocation": {"willingness": "no"},
    "salary": {"floor": 40000, "currency": "EUR"},
    "availability": {"earliest_start": "2026-11-01"},
    "work_authorisation": {"authorised_countries": ["ES"]},
    "employment_mode": {"accepted": ["employed"]},
    "pay_country": {"countries": ["ES"]},
    "tax_country": {"country": "ES"},
    "reach": {"modes": ["remote"]},
}


def test_the_stated_fixture_covers_every_pinned_field() -> None:
    assert set(_STATED) == set(CONSTRAINT_FIELD_NAMES)


def _pinned_row(
    n: int, fields: list[str], quote: Any, value: Any = None, **extra: Any
) -> dict[str, Any]:
    if value is None:
        value = {k: v for f in fields if f in _STATED for k, v in _STATED[f].items()}
    text = json.dumps({"quote": quote, "value": value}, ensure_ascii=False)
    return _row(n, "constraints", text, dimensions=fields, **extra)


@pytest.mark.parametrize("field", CONSTRAINT_FIELD_NAMES)
@pytest.mark.parametrize("quote", ["Barcelona, 40k brutos", "no menos de 40k, no me reubico"])
def test_a_pinned_field_row_is_never_a_topic(root: Path, field: str, quote: str) -> None:
    store = _profile(root, [_pinned_row(1, [field], quote)])
    assert unrecorded_statements(store) == ()
    assert backfill_warning(store) is None


def test_a_row_naming_a_pinned_field_and_another_dimension_is_still_listed(root: Path) -> None:
    store = _profile(root, [_pinned_row(1, ["salary", "sector"], "nada de banca")])
    assert [r.evidence_id for r in unrecorded_statements(store)] == ["ev-000001"]


def test_the_backfill_closes_on_a_profile_that_finished_step_2(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = [
        _pinned_row(1, ["salary"], "no menos de 40k brutos"),
        _pinned_row(2, ["location"], "vivo en Barcelona"),
        _pinned_row(3, ["relocation"], "no me reubico"),
        _row(4, "constraints", "defensa, apuestas"),
    ]
    store = _profile(root, rows)
    argv = ["prog", "unrecorded", "--handle", store.handle, "--root", str(root)]
    assert se._main(argv) == 1
    listed = [json.loads(line)["evidence_id"] for line in capsys.readouterr().out.splitlines()]
    assert listed == ["ev-000004"]
    for topic in ("defensa", "apuestas"):
        record_exclusion(store, Exclusion(about=f"sector:{topic}", stated_at_cycle=1, words=topic))
    assert se._main(argv) == 0


def test_the_unrecorded_cli_exits_2_on_a_corrupt_exclusions_file(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = _profile(root, _PRE_T203[:1])
    store.write_json({"bad": 1}, *se.EXCLUSIONS_FILE)
    assert se._main(["prog", "unrecorded", "--handle", store.handle, "--root", str(root)]) == 2
    assert "could not be computed" in capsys.readouterr().err


def test_the_unrecorded_cli_exits_2_on_a_corrupt_evidence_log(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = _profile(root, _PRE_T203[:1])
    store.path("profile", "evidence.jsonl").write_text("{not json\n", encoding="utf-8")
    assert se._main(["prog", "unrecorded", "--handle", store.handle, "--root", str(root)]) == 2
    assert "could not be computed" in capsys.readouterr().err


# Round 3: the skip is for step 2's own write, never for a dimension tag alone.


@pytest.mark.parametrize(
    "row",
    [
        _row(1, "constraints", "defensa, apuestas, tabacos, bancos", dimensions=["reach"]),
        _row(
            1,
            "identify",
            "Vivo en Barcelona, pero nada de banca",
            kind="statement",
            dimensions=["location"],
        ),
        _row(
            1,
            "constraints",
            json.dumps({"quote": "nada de banca", "value": "banca"}),
            dimensions=["salary"],
        ),
        _row(
            1,
            "identify",
            json.dumps({"quote": "nada de banca", "value": {"city": "Barcelona"}}),
            kind="statement",
            dimensions=["location"],
        ),
    ],
)
def test_a_topic_row_merely_tagged_with_a_pinned_field_is_still_listed(
    root: Path, row: dict[str, Any]
) -> None:
    store = _profile(root, [row])
    assert [r.evidence_id for r in unrecorded_statements(store)] == ["ev-000001"]
    warning = backfill_warning(store)
    assert warning is not None and warning.startswith("WARNING")


@pytest.mark.parametrize("corrupt", ["directory", "not-utf8"])
def test_the_unrecorded_cli_exits_2_on_an_unreadable_exclusions_file(
    root: Path, capsys: pytest.CaptureFixture[str], corrupt: str
) -> None:
    store = _profile(root, _PRE_T203[:1])
    path = store.path(*se.EXCLUSIONS_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    if corrupt == "directory":
        path.mkdir()
    else:
        path.write_bytes(b"\xff\xfe[]")
    assert se._main(["prog", "unrecorded", "--handle", store.handle, "--root", str(root)]) == 2
    assert "could not be computed" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# T220 — a tagged row that rules out no kind of work is acknowledged, never recorded

_COMMUTE = "No quiero desplazarme más de 30 minutos."


def _ack(n: int, dimension: str = "commute", words: str = _COMMUTE) -> se.Acknowledgement:
    return se.Acknowledgement(evidence_id=f"ev-{n:06d}", dimension=dimension, words=words)


def test_a_commute_row_is_listed_until_it_is_acknowledged(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # integral.feedback's own fixture shape: a constraint outside T24's pinned fields.
    store = _profile(root, [_row(44, "constraints", _COMMUTE, dimensions=["commute"])])
    argv = ["prog", "unrecorded", "--handle", store.handle, "--root", str(root)]
    assert se._main(argv) == 1
    capsys.readouterr()
    ack = ["prog", "acknowledge", "--handle", store.handle, "--root", str(root)]
    ack += ["--evidence-id", "ev-000044", "--dimension", "commute", "--words", _COMMUTE]
    assert se._main(ack) == 0
    assert se._main(argv) == 0
    assert backfill_warning(store) is None


def test_a_statement_row_with_a_cue_is_acknowledgeable_too(root: Path) -> None:
    store = _profile(
        root, [_row(1, "identify", _COMMUTE, kind="statement", dimensions=["commute"])]
    )
    assert len(unrecorded_statements(store)) == 1
    se.record_acknowledgement(store, _ack(1))
    assert unrecorded_statements(store) == ()


@pytest.mark.parametrize(
    ("row", "ack", "said"),
    [
        # the bare topic list T218 exists for: untagged, so never acknowledgeable
        (_row(1, "constraints", "defensa, apuestas"), _ack(1, words="defensa, apuestas"), "no dim"),
        # words not the row's own, even by one character or by trailing space
        (
            _row(1, "constraints", _COMMUTE, dimensions=["commute"]),
            _ack(1, words=_COMMUTE[:-1]),
            "words",
        ),
        (
            _row(1, "constraints", _COMMUTE, dimensions=["commute"]),
            _ack(1, words=_COMMUTE + " "),
            "words",
        ),
        # a dimension the row does not carry
        (
            _row(1, "constraints", _COMMUTE, dimensions=["commute"]),
            _ack(1, dimension="sector"),
            "not one",
        ),
    ],
)
def test_an_acknowledgement_that_does_not_fit_the_row_is_refused(
    root: Path, row: dict[str, Any], ack: se.Acknowledgement, said: str
) -> None:
    store = _profile(root, [row])
    with pytest.raises(IdentityError, match=said):
        se.record_acknowledgement(store, ack)
    assert [r.evidence_id for r in unrecorded_statements(store)] == ["ev-000001"]


def test_a_row_tagged_with_a_topic_facet_cannot_be_acknowledged(root: Path) -> None:
    store = _profile(root, [_row(1, "constraints", "nada de banca", dimensions=["sector"])])
    record_exclusion(store, Exclusion(about="sector:tabaco", stated_at_cycle=1, words="tabaco"))
    with pytest.raises(IdentityError, match="facet"):
        se.record_acknowledgement(store, _ack(1, dimension="sector", words="nada de banca"))
    assert [r.evidence_id for r in unrecorded_statements(store)] == ["ev-000001"]


def test_an_acknowledgement_is_rechecked_on_every_read(root: Path) -> None:
    # Acknowledged while no `sector` exclusion existed; once one is recorded the
    # facet is a topic and the row is listed again, without touching the file.
    store = _profile(root, [_row(1, "constraints", "nada de banca", dimensions=["sector"])])
    se.record_acknowledgement(store, _ack(1, dimension="sector", words="nada de banca"))
    assert unrecorded_statements(store) == ()
    record_exclusion(store, Exclusion(about="Sector:tabaco", stated_at_cycle=1, words="tabaco"))
    assert [r.evidence_id for r in unrecorded_statements(store)] == ["ev-000001"]


def test_a_hand_written_acknowledgement_is_held_to_the_same_rule(root: Path) -> None:
    rows = [
        _row(1, "constraints", "defensa, apuestas"),
        _row(2, "constraints", _COMMUTE, dimensions=["commute"]),
    ]
    store = _profile(root, rows)
    # Written past `record_acknowledgement`: an untagged row, wrong words for the other.
    store.write_json(
        [
            {"evidence_id": "ev-000001", "dimension": "commute", "words": "defensa, apuestas"},
            {"evidence_id": "ev-000002", "dimension": "commute", "words": "no quiero desplazarme"},
        ],
        *se.ACKNOWLEDGEMENTS_FILE,
    )
    assert [r.evidence_id for r in unrecorded_statements(store)] == ["ev-000001", "ev-000002"]


def test_an_acknowledgement_covers_only_its_own_row(root: Path) -> None:
    rows = [
        _row(1, "constraints", _COMMUTE, dimensions=["commute"]),
        _row(2, "constraints", _COMMUTE, dimensions=["commute"]),
    ]
    store = _profile(root, rows)
    se.record_acknowledgement(store, _ack(1))
    assert [r.evidence_id for r in unrecorded_statements(store)] == ["ev-000002"]


def test_a_retracted_row_cannot_be_acknowledged(root: Path) -> None:
    rows = [
        _row(1, "constraints", _COMMUTE, dimensions=["commute"]),
        _row(2, "constraints", "retiro eso", kind="retraction", retracts="ev-000001"),
    ]
    with pytest.raises(IdentityError, match="not a live evidence row"):
        se.record_acknowledgement(_profile(root, rows), _ack(1))


def test_a_row_outside_the_statement_steps_cannot_be_acknowledged(root: Path) -> None:
    store = _profile(root, [_row(1, "history", _COMMUTE, dimensions=["commute"])])
    with pytest.raises(IdentityError, match="statement step"):
        se.record_acknowledgement(store, _ack(1))


def test_the_acknowledge_cli_exits_2_with_the_reason(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = _profile(root, [_row(9, "constraints", "defensa, apuestas")])
    argv = ["prog", "acknowledge", "--handle", store.handle, "--root", str(root)]
    argv += ["--evidence-id", "ev-000009", "--dimension", "commute", "--words", "defensa, apuestas"]
    assert se._main(argv) == 2
    assert "record each topic" in capsys.readouterr().err
    assert not store.exists(*se.ACKNOWLEDGEMENTS_FILE)


def test_a_corrupt_acknowledgements_file_makes_unrecorded_exit_2(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = _profile(root, [_row(1, "constraints", _COMMUTE, dimensions=["commute"])])
    store.write_json({"not": "a list"}, *se.ACKNOWLEDGEMENTS_FILE)
    argv = ["prog", "unrecorded", "--handle", store.handle, "--root", str(root)]
    assert se._main(argv) == 2
    assert "could not be computed" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# T221 N1-N3 — the checkpoint's error paths, and what counts as step 2's write


def _checkpoint_main(root: Path, handle: str) -> int:
    try:
        module = _load_checkpoint_module()
        return int(module.main(["--id", handle, "--input-dir", str(root), "--dev"]))
    finally:
        sys.modules.pop("_t218_main_checkpoint", None)


def test_a_non_utf8_evidence_log_makes_the_checkpoint_main_exit_2(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = _profile(root, _PRE_T203[:1])
    store.path("profile", "evidence.jsonl").write_bytes(b'{"id": "\xff\xfe"}\n')
    assert _checkpoint_main(root, store.handle) == 2
    assert "could not be computed" in capsys.readouterr().err


def test_an_unreadable_exclusions_file_makes_the_checkpoint_main_exit_2(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The same state the `unrecorded` CLI exits 2 on; SKILL.md says the two agree.
    store = _profile(root, _PRE_T203[:1])
    store.path(*se.EXCLUSIONS_FILE).mkdir(parents=True)
    assert _checkpoint_main(root, store.handle) == 2
    assert "could not be computed" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("quote", "value"),
    [
        (5, None),  # a quote that is not words
        ("nada de banca", {}),  # a value step 2 could never have written
        ("nada de banca", {"stated": True}),  # not a field of Salary
        ("nada de banca", {"floor": 40000}),  # Salary stated without its currency
        ("nada de banca", {"floor": 40000, "currency": "EUR", "evidence": ["ev-000009"]}),
    ],
)
def test_a_payload_step_2_could_not_have_written_is_still_listed(
    root: Path, quote: Any, value: Any
) -> None:
    store = _profile(root, [_pinned_row(1, ["salary"], quote, value)])
    assert [r.evidence_id for r in unrecorded_statements(store)] == ["ev-000001"]
