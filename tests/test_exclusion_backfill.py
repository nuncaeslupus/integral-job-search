"""T218 — topics stated before T203 are visible to step 7 until they are recorded.

A profile begun before `source()` read `search/exclusions.json` holds its
ruled-out topics only as evidence rows, so its exclusions filter nothing and
nothing looked wrong. These fixtures are invented candidates; no real profile
is read.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from integral import sourcing_exclusions as se
from integral.candidate import CONSTRAINT_FIELD_NAMES
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


@pytest.mark.parametrize("corrupt", ["not-json", "not-utf8", "exclusions-directory"])
def test_a_corrupt_evidence_log_makes_the_checkpoint_main_exit_2(
    root: Path, capsys: pytest.CaptureFixture[str], corrupt: str
) -> None:
    store = _profile(root, _PRE_T203[:1])
    if corrupt == "not-json":
        store.path("profile", "evidence.jsonl").write_text("{not json\n", encoding="utf-8")
    elif corrupt == "not-utf8":
        store.path("profile", "evidence.jsonl").write_bytes(b"\xff\xfe{}\n")
    else:
        # The `unrecorded` CLI exits 2 on this same file; the checkpoint must too.
        path = store.path(*se.EXCLUSIONS_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.mkdir()
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


#: One value per pinned field that `candidate.FIELD_MODELS` accepts as `stated`,
#: the shape `constraints_step._encode_stated` writes.
_STATED_VALUE: dict[str, dict[str, Any]] = {
    "languages": {"levels": [{"language": "es", "level": "native"}]},
    "location": {"country": "ES", "accepts_onsite_in_country": True},
    "relocation": {"willingness": "no"},
    "salary": {"floor": 40000, "currency": "EUR"},
    "availability": {"notice_period_days": 30, "earliest_start": "2026-11-01"},
    "work_authorisation": {"authorised_countries": ["ES"]},
    "employment_mode": {"accepted": ["employed"]},
    "pay_country": {"countries": ["ES"]},
    "tax_country": {"country": "ES"},
    "reach": {"modes": ["remote"]},
}


def test_every_pinned_field_has_a_stated_value() -> None:
    assert set(_STATED_VALUE) == set(CONSTRAINT_FIELD_NAMES)


def _pinned_row(n: int, fields: list[str], quote: str) -> dict[str, Any]:
    value = _STATED_VALUE.get(fields[0], {})
    text = json.dumps({"quote": quote, "value": value}, ensure_ascii=False)
    return _row(n, "constraints", text, dimensions=fields)


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


# Round 4: the skip needs step 2's write to state its field — a string quote and
# a value `FIELD_MODELS` accepts. Each of these decodes to the old shape and is
# still a row nobody recorded, so it stays listed.


@pytest.mark.parametrize(
    "payload",
    [
        {"quote": 7, "value": _STATED_VALUE["salary"]},
        {"quote": None, "value": _STATED_VALUE["salary"]},
        {"value": _STATED_VALUE["salary"]},
        {"quote": "nada de banca", "value": {}},
        {"quote": "nada de banca", "value": {"stated": True}},
        {"quote": "nada de banca", "value": {"sector": "banca"}},
        {"quote": "nada de banca", "value": {"state": "stated"}},
        {"quote": "nada de banca", "value": _STATED_VALUE["location"]},
        [{"quote": "nada de banca", "value": _STATED_VALUE["salary"]}],
    ],
)
def test_a_pinned_shape_that_states_no_field_is_still_listed(root: Path, payload: Any) -> None:
    row = _row(1, "constraints", json.dumps(payload), dimensions=["salary"])
    store = _profile(root, [row])
    assert [r.evidence_id for r in unrecorded_statements(store)] == ["ev-000001"]


def test_a_two_field_row_must_state_every_field_it_is_tagged_with(root: Path) -> None:
    text = json.dumps({"quote": "40k, y nada de banca", "value": _STATED_VALUE["salary"]})
    store = _profile(root, [_row(1, "constraints", text, dimensions=["salary", "reach"])])
    assert [r.evidence_id for r in unrecorded_statements(store)] == ["ev-000001"]


@pytest.mark.parametrize("field", CONSTRAINT_FIELD_NAMES)
@pytest.mark.parametrize("text", ["", "  ", "no menos de 40k, no me reubico"])
def test_step_2s_real_write_is_never_listed(root: Path, field: str, text: str) -> None:
    # Driven through `constraints_step.resolve` itself, not a hand-built row:
    # `CandidateTurn.text` defaults to "", so a blank quote is a real write.
    from integral.constraints_step import CandidateTurn, resolve
    from integral.profile import EvidenceLog

    store = _profile(root, [])
    turn = CandidateTurn(field=field, action="state", value=_STATED_VALUE[field], text=text)
    resolve(store, [turn], now="2026-10-01T10:00:00Z")
    rows = [r for r in EvidenceLog(store).effective_rows() if field in r.dimensions]
    assert rows, "resolve wrote no row for the field"
    assert unrecorded_statements(store) == ()


# T221: a listed row on one non-topic dimension closes by acknowledgement —
# its whole text, re-checked against the live row on every read — and a topic
# row never does.

_COMMUTE = "No quiero desplazarme más de 30 minutos."


def _ack_cli(store: ProfileStore, root: Path, evidence: str, words: str) -> int:
    argv = ["prog", "acknowledge", "--handle", store.handle, "--root", str(root)]
    return se._main([*argv, "--evidence", evidence, "--words", words])


def _unrecorded_cli(store: ProfileStore, root: Path) -> int:
    return se._main(["prog", "unrecorded", "--handle", store.handle, "--root", str(root)])


def test_a_non_topic_row_closes_and_stays_visible(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = _profile(root, [_row(1, "constraints", _COMMUTE, dimensions=["commute_burden"])])
    assert _unrecorded_cli(store, root) == 1
    capsys.readouterr()
    assert _ack_cli(store, root, "ev-000001", "  No quiero desplazarme\nmás de 30 minutos. ") == 0
    assert unrecorded_statements(store) == ()
    assert [r.evidence_id for r in se.acknowledged_statements(store)] == ["ev-000001"]
    assert _unrecorded_cli(store, root) == 0
    assert 'acknowledged: ev-000001 "No quiero' in capsys.readouterr().err
    assert _drive_step_7_checkpoint(root, store.handle)["acknowledged_exclusion_statements"]


@pytest.mark.parametrize(
    ("row", "words"),
    [
        # the bare topic list (T218's canonical case): no tag
        (_row(1, "constraints", "defensa, apuestas"), "defensa, apuestas"),
        # #610 B1: a topic row tagged with a pinned field
        (_row(1, "constraints", "defensa, apuestas", dimensions=["reach"]), "defensa, apuestas"),
        # a facet name on a profile with nothing recorded: not a dimension id
        (_row(1, "constraints", "nada de banca", dimensions=["sector"]), "nada de banca"),
        # each topic dimension the owner named
        (
            _row(1, "constraints", "nada de defensa", dimensions=["mission_alignment"]),
            "nada de defensa",
        ),
        (
            _row(1, "constraints", "nada de fintech", dimensions=["domain_knowledge"]),
            "nada de fintech",
        ),
        (
            _row(1, "constraints", "no consultoras", dimensions=["product_vs_services"]),
            "no consultoras",
        ),
        (_row(1, "constraints", "no startups", dimensions=["company_stage"]), "no startups"),
        (
            _row(
                1,
                "constraints",
                "No quiero trabajar en productos de IA.",
                dimensions=["ai_in_the_work"],
            ),
            "No quiero trabajar en productos de IA.",
        ),
        # two tags
        (
            _row(1, "constraints", _COMMUTE, dimensions=["commute_burden", "schedule_flexibility"]),
            _COMMUTE,
        ),
        # #610 F1: exact ids only — never folded into one. `EvidenceRow` already
        # refuses a tag outside `[a-z][a-z0-9_]*`, so case and padding cannot reach here.
        (_row(1, "constraints", _COMMUTE, dimensions=["commute"]), _COMMUTE),
        (_row(1, "constraints", _COMMUTE, dimensions=["commute_burdens"]), _COMMUTE),
        # words that are not the whole text
        (
            _row(1, "constraints", "30 minutos, y nada de banca", dimensions=["commute_burden"]),
            "30 minutos",
        ),
        (_row(1, "constraints", _COMMUTE, dimensions=["commute_burden"]), "a"),
        (_row(1, "constraints", _COMMUTE, dimensions=["commute_burden"]), _COMMUTE + " Y banca."),
    ],
)
def test_an_acknowledgement_is_refused_and_the_row_stays_listed(
    root: Path, capsys: pytest.CaptureFixture[str], row: dict[str, Any], words: str
) -> None:
    store = _profile(root, [row])
    assert _ack_cli(store, root, "ev-000001", words) == 2
    assert "acknowledge:" in capsys.readouterr().err
    assert not store.exists(*se.ACKNOWLEDGEMENTS_FILE)
    assert [r.evidence_id for r in unrecorded_statements(store)] == ["ev-000001"]


def test_only_a_listed_row_can_be_acknowledged(root: Path) -> None:
    rows = [
        _pinned_row(1, ["salary"], "40k"),
        _row(2, "history", _COMMUTE, kind="episode", dimensions=["commute_burden"]),
    ]
    store = _profile(root, rows)
    for evidence in ("ev-000001", "ev-000002", "ev-999999"):
        assert _ack_cli(store, root, evidence, "40k" if evidence == "ev-000001" else _COMMUTE) == 2


def _hand_written(store: ProfileStore, **overrides: str) -> None:
    ack = {
        "evidence_id": "ev-000001",
        "words": _COMMUTE,
        "text_sha256": hashlib.sha256(_COMMUTE.encode("utf-8")).hexdigest(),
        **overrides,
    }
    store.write_json([ack], *se.ACKNOWLEDGEMENTS_FILE)


@pytest.mark.parametrize(
    ("dimensions", "overrides"),
    [
        (["commute_burden"], {"text_sha256": "0" * 64}),  # the row changed since
        (["commute_burden"], {"words": "30 minutos"}),  # not the whole text
        (["commute_burden"], {"evidence_id": "ev-000002"}),  # another row
        (["mission_alignment"], {}),  # a topic dimension
        ([], {}),  # untagged
    ],
)
def test_a_hand_written_acknowledgement_is_re_checked_on_read(
    root: Path, dimensions: list[str], overrides: dict[str, str]
) -> None:
    rows = [
        _row(1, "constraints", _COMMUTE, dimensions=dimensions),
        _row(2, "constraints", "defensa, apuestas"),
    ]
    store = _profile(root, rows)
    _hand_written(store, **overrides)
    assert "ev-000001" in [r.evidence_id for r in unrecorded_statements(store)]
    assert se.acknowledged_statements(store) == ()


def test_the_hand_written_control_does_close(root: Path) -> None:
    store = _profile(root, [_row(1, "constraints", _COMMUTE, dimensions=["commute_burden"])])
    _hand_written(store)
    assert unrecorded_statements(store) == ()


def test_an_acknowledgement_closes_its_row_and_no_other(root: Path) -> None:
    rows = [
        _row(1, "constraints", _COMMUTE, dimensions=["commute_burden"]),
        _row(2, "constraints", _COMMUTE, dimensions=["commute_burden"]),
    ]
    store = _profile(root, rows)
    assert _ack_cli(store, root, "ev-000001", _COMMUTE) == 0
    assert [r.evidence_id for r in unrecorded_statements(store)] == ["ev-000002"]


@pytest.mark.parametrize("payload", ['{"not": "a list"}', '[{"evidence_id": "ev-000001"}]'])
def test_an_unreadable_acknowledgements_file_exits_2(
    root: Path, capsys: pytest.CaptureFixture[str], payload: str
) -> None:
    store = _profile(root, [_row(1, "constraints", _COMMUTE, dimensions=["commute_burden"])])
    path = store.path(*se.ACKNOWLEDGEMENTS_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    assert _unrecorded_cli(store, root) == 2
    assert "could not be computed" in capsys.readouterr().err


def test_the_owner_s_topic_dimensions_are_real_ids_and_never_acknowledgeable() -> None:
    from integral.dimensions import load_dimensions

    ids = {d.id for d in load_dimensions()}
    assert ids >= se.TOPIC_DIMENSIONS
    assert not se.TOPIC_DIMENSIONS & se.acknowledgeable_dimensions()
    assert not set(CONSTRAINT_FIELD_NAMES) & se.acknowledgeable_dimensions()
    assert "commute_burden" in se.acknowledgeable_dimensions()


#: Every state the backfill must be able to close, each with the closure step 7's
#: SKILL.md prescribes for it. A floor, so a shrinking list cannot read as a pass.
_CLOSABLE_STATES = 4


def test_backfill_rows_that_can_never_close_is_zero(root: Path) -> None:
    from integral.constraints_step import CandidateTurn, resolve

    states: list[tuple[list[dict[str, Any]], str | None]] = [
        ([_row(1, "constraints", _COMMUTE, dimensions=["commute_burden"])], _COMMUTE),
        (
            [_row(1, "constraints", "Nada de guardias.", dimensions=["on_call_load"])],
            "Nada de guardias.",
        ),
        ([_row(1, "constraints", "defensa, apuestas")], None),  # closed by `record`
        ([], None),  # step 2's real write with a blank quote, below
    ]
    never_close = 0
    for n, (rows, words) in enumerate(states):
        store = _profile(root / str(n), rows)
        if not rows:
            turn = CandidateTurn(field="salary", action="state", value=_STATED_VALUE["salary"])
            resolve(store, [turn], now="2026-10-01T10:00:00Z")
        elif words is not None:
            se.record_acknowledgement(store, "ev-000001", words)
        else:
            for topic in ("defensa", "apuestas"):
                record_exclusion(
                    store, Exclusion(about=f"sector:{topic}", stated_at_cycle=1, words=topic)
                )
        never_close += len(unrecorded_statements(store))
    assert len(states) >= _CLOSABLE_STATES
    assert never_close == 0


def test_a_pinned_field_in_the_dimension_files_is_still_not_acknowledgeable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Defensive today (no pinned field is a `dimensions/*.yaml` id); pinned so
    # the day one becomes an id, a topic row tagged with it stays listed (#610 B1).
    import integral.dimensions as dims

    real = dims.load_dimensions()
    fake = [real[0].model_copy(update={"id": "reach"}), *real]
    monkeypatch.setattr(dims, "load_dimensions", lambda: fake)
    se.acknowledgeable_dimensions.cache_clear()
    try:
        assert "reach" not in se.acknowledgeable_dimensions()
    finally:
        se.acknowledgeable_dimensions.cache_clear()


# T220: refusals stated in steps 5, 6 and 10 — measured on #598's head, each row
# was skipped and the candidate kept seeing what they had refused. The steps are
# read from the process spec's `states_refusals`, never listed in the module.

_OFFER_ABOUT = {"kind": "offer", "id": f"sha256:{'0' * 64}"}

#: step, row kind, words, the exclusion that records it — the three measured rows.
_LATER_STEP_REFUSALS = [
    ("feedback", "reaction", "no me enseñéis más bancos", ("sector:bancos", "bancos", ("bank",))),
    ("reactions", "reaction", "nada de apuestas", ("sector:apuestas", "apuestas", ("betting",))),
    (
        "preferences",
        "statement",
        "no quiero consultoras",
        ("sector:consultoras", "consultoras", ("consultancy",)),
    ),
]


@pytest.mark.parametrize(("step", "kind", "words", "recorded"), _LATER_STEP_REFUSALS)
def test_a_refusal_in_a_later_step_is_listed_until_recorded(
    root: Path, step: str, kind: str, words: str, recorded: tuple[str, str, tuple[str, ...]]
) -> None:
    store = _profile(root, [_row(1, step, words, kind=kind)])
    listed = unrecorded_statements(store)
    assert [(r.evidence_id, r.step) for r in listed] == [("ev-000001", step)]
    warning = backfill_warning(store)
    assert warning is not None and warning.startswith("WARNING") and "ev-000001" in warning
    about, quote, terms = recorded
    record_exclusion(store, Exclusion(about=about, stated_at_cycle=1, words=quote, terms=terms))
    assert unrecorded_statements(store) == ()
    assert backfill_warning(store) is None


@pytest.mark.parametrize("kind", ["statement", "episode", "reaction"])
def test_a_refusal_in_an_unrelated_step_is_still_skipped(root: Path, kind: str) -> None:
    store = _profile(root, [_row(1, "history", "no quiero consultoras", kind=kind)])
    assert unrecorded_statements(store) == ()
    assert backfill_warning(store) is None


@pytest.mark.parametrize(("step", "kind", "words", "recorded"), _LATER_STEP_REFUSALS)
def test_a_reaction_to_one_advert_is_not_a_topic_refusal(
    root: Path, step: str, kind: str, words: str, recorded: tuple[str, str, tuple[str, ...]]
) -> None:
    # The choice, pinned both ways: the same words, once about one advert (skipped:
    # no `record` could close it) and once unattached (listed).
    attached = _profile(root / "a", [_row(1, step, words, kind=kind, about=_OFFER_ABOUT)])
    assert unrecorded_statements(attached) == ()
    free = _profile(root / "b", [_row(1, step, words, kind=kind)])
    assert [r.evidence_id for r in unrecorded_statements(free)] == ["ev-000001"]


def test_the_backfill_steps_are_the_ones_the_spec_declares() -> None:
    from integral.process_spec import load_steps

    steps = load_steps().steps
    assert set(se.statement_steps()) == {s.id for s in steps if s.states_refusals}
    # The three the task names, plus step 0 and 2 — and never the story or trait steps.
    assert set(se.statement_steps()) == {
        "identify",
        "constraints",
        "reactions",
        "preferences",
        "feedback",
    }
    # A step taking free text about the candidate must say whether it can state a
    # refusal: an undeclared one would be skipped exactly as steps 5, 6 and 10 were.
    assert [s.id for s in steps if s.states_refusals is None] == []
