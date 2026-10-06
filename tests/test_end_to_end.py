"""T149 — the first complete run, frozen as a replay over a fictional candidate.

Every claim here is pinned by reverting the one line that makes it true.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from integral import candidate, liveness
from integral import end_to_end as e2e
from integral.application_render import render_document
from integral.approval import Payload, payload_digest, read_payload, verify_send
from integral.cv_store import CVMaster
from integral.identity import ProfileStore
from integral.prior_documents import digest as prior_digest
from integral.process_spec import StepList, load_steps

FIXTURE = e2e.load_fixture()


def _run(
    tmp_path: Path, fixture: e2e.Fixture = FIXTURE, steps: StepList | None = None
) -> e2e.Replay:
    return e2e.replay(tmp_path / "profiles", fixture, steps)


def _store(tmp_path: Path) -> ProfileStore:
    return ProfileStore(tmp_path / "profiles", FIXTURE.candidate.handle)


def _revision(fixture: e2e.Fixture, n: int, **update: Any) -> e2e.Fixture:
    revisions = tuple(r.model_copy(update=update) if r.n == n else r for r in fixture.revisions)
    return fixture.model_copy(update={"revisions": revisions})


def _master() -> CVMaster:
    return CVMaster.model_validate_json(
        (e2e._REPO_ROOT / FIXTURE.master).read_text(encoding="utf-8")
    )


def test_the_committed_run_replays_clean(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.defects == []
    assert result.steps_replayed == len(FIXTURE.sequence) == e2e.MINIMUM_STEPS_REPLAYED
    assert result.revisions_replayed == len(FIXTURE.revisions) == e2e.MINIMUM_REVISIONS_REPLAYED


def test_the_run_is_out_of_canonical_order_and_revisits(tmp_path: Path) -> None:
    order = [run.step for run in FIXTURE.sequence]
    assert order.index("reactions") > order.index("ranking")  # reactions after ranking
    assert [run.step for run in FIXTURE.sequence if run.revisit] == ["constraints", "ranking"]
    graph = {step.id for step in load_steps().steps}
    assert graph - set(order) == {"preferences", "feedback", "interview_log"}


def test_a_step_run_before_its_input_exists_is_named(tmp_path: Path) -> None:
    skipped = FIXTURE.model_copy(
        update={
            "sequence": tuple(
                r for r in FIXTURE.sequence if not (r.step == "constraints" and not r.revisit)
            )
        }
    )
    defects = _run(tmp_path, skipped).defects
    assert any(d.startswith("sourcing/collect: ran without constraints") for d in defects)


def test_a_step_whose_output_the_detector_cannot_see_is_named(tmp_path: Path) -> None:
    unresolved = FIXTURE.model_copy(
        update={"constraints": {**FIXTURE.constraints, "relocation": {"state": "pending"}}}
    )
    defects = _run(tmp_path, unresolved).defects
    assert any("constraints/first_pass: wrote constraints" in d for d in defects)
    assert any(d.startswith("sourcing/collect: ran without constraints") for d in defects)


def test_a_graph_edit_that_stops_a_step_producing_is_noticed(tmp_path: Path) -> None:
    steps = load_steps()
    edited = steps.model_copy(
        update={
            "steps": [
                s.model_copy(update={"produces": []}) if s.id == "understanding" else s
                for s in steps.steps
            ]
        }
    )
    defects = _run(tmp_path, steps=edited).defects
    assert any("understanding/extraction: writes ['extractions']" in d for d in defects)


def test_ranking_never_carries_an_expired_offer(tmp_path: Path) -> None:
    _run(tmp_path)
    store = _store(tmp_path)
    ranking = next(r for r in FIXTURE.sequence if r.stage == "reranked_after_reactions")
    path = store.path("rankings", e2e._ranking_name(ranking))
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["pareto"].append(e2e._offer_ids(FIXTURE)["lleida-closed"])
    path.write_text(json.dumps(payload), encoding="utf-8")
    seen = e2e.Replay()
    e2e._seams(seen, store, FIXTURE, ranking)
    assert any("which is expired" in d for d in seen.defects)
    assert any("expired offer lleida-closed reached the ranking" in d for d in seen.defects)


def test_a_liveness_pass_that_retires_nothing_is_named(tmp_path: Path) -> None:
    _run(tmp_path)
    store = _store(tmp_path)
    liveness = next(r for r in FIXTURE.sequence if r.stage == "liveness")
    seen = e2e.Replay()
    e2e._seams(seen, store, FIXTURE, liveness)
    assert seen.defects == []
    collect = next(r for r in FIXTURE.sequence if r.stage == "collect")
    e2e._write(store, FIXTURE, collect, _master())  # every offer is "new" again
    e2e._seams(seen, store, FIXTURE, liveness)
    assert any("still 'new'" in d for d in seen.defects)


def test_a_filtering_pass_that_screens_nothing_out_is_named(tmp_path: Path) -> None:
    _run(tmp_path)
    store = _store(tmp_path)
    filtering = next(r for r in FIXTURE.sequence if r.stage == "filtering")
    collect = next(r for r in FIXTURE.sequence if r.stage == "collect")
    e2e._write(store, FIXTURE, collect, _master())
    seen = e2e.Replay()
    e2e._seams(seen, store, FIXTURE, filtering)
    assert any("filtered offer sevilla-onsite is still 'new'" in d for d in seen.defects)


def test_an_extraction_naming_no_stored_offer_is_named(tmp_path: Path) -> None:
    _run(tmp_path)
    store = _store(tmp_path)
    extraction = next(r for r in FIXTURE.sequence if r.step == "understanding")
    ids = e2e._offer_ids(FIXTURE)
    name = f"{ids['girona-data'].replace(':', '-')}.json"
    store.write_json({"offer_id": "sha256:" + "0" * 64, "scores": {}}, "extractions", name)
    seen = e2e.Replay()
    e2e._seams(seen, store, FIXTURE, extraction)
    assert any("extraction for girona-data names no stored offer" in d for d in seen.defects)


def test_a_revision_that_changed_nothing_is_named(tmp_path: Path) -> None:
    r2 = next(r for r in FIXTURE.revisions if r.n == 2)
    same = _revision(
        FIXTURE,
        3,
        asks=r2.asks,
        approved_episodes=(),
        recipient=r2.recipient,
        expect=r2.expect.model_copy(update={"version": 3}),
    )
    defects = _run(tmp_path, same).defects
    assert any("revision 3 (girona-data v3): changed nothing" in d for d in defects)


def test_a_revision_that_is_not_what_the_fixture_says_is_named(tmp_path: Path) -> None:
    r5 = next(r for r in FIXTURE.revisions if r.n == 5)
    wrong = _revision(
        FIXTURE, 5, expect=r5.expect.model_copy(update={"cv_skills": ("PostgreSQL", "Docker")})
    )
    defects = _run(tmp_path, wrong).defects
    assert any("revision 5" in d and "cv_skills is ['PostgreSQL']" in d for d in defects)


def test_a_voice_correction_governs_the_next_offers_draft(tmp_path: Path) -> None:
    defects = _run(tmp_path, _revision(FIXTURE, 5, voice=None)).defects
    assert any("revision 5" in d and "voice_omitted" in d for d in defects)
    assert any("revision 7" in d and "cv_skills is ['Python', 'Docker']" in d for d in defects)


def test_the_to_block_reaches_the_file_the_candidate_confirms(tmp_path: Path) -> None:
    _run(tmp_path)
    store = _store(tmp_path)
    ids = e2e._offer_ids(FIXTURE)
    sent = next(r for r in FIXTURE.revisions if r.n == FIXTURE.sent.revision)
    payload = read_payload(store, ids[sent.offer], sent.expect.version)
    assert payload.recipient == sent.recipient
    other = payload.model_copy(update={"recipient": "someone else"})
    assert payload_digest(other) != payload_digest(payload)


def test_the_sent_revision_is_staged_verified_recorded_and_alone(tmp_path: Path) -> None:
    _run(tmp_path)
    store = _store(tmp_path)
    ids = e2e._offer_ids(FIXTURE)
    sent = next(r for r in FIXTURE.revisions if r.n == FIXTURE.sent.revision)
    offer, version = ids[sent.offer], sent.expect.version
    assert verify_send(store, offer, version) == []
    assert sorted(
        p.name for p in store.path("cv", "generated", offer, f"v{version}", "send").iterdir()
    ) == [
        "cv.md",
        "letter.md",
    ]
    assert store.exists("applications", offer, f"v{version}.json")
    assert len(list(store.path("applications").glob("*/*.json"))) == 1


def test_a_send_that_never_happened_is_named(tmp_path: Path) -> None:
    unsent = FIXTURE.model_copy(update={"sent": e2e.Sent(revision=99)})
    assert any(
        "no revision was marked as the one sent" in d for d in _run(tmp_path, unsent).defects
    )


def test_the_fixture_is_about_a_fictional_candidate(tmp_path: Path) -> None:
    _run(tmp_path)
    identity = json.loads(_store(tmp_path).path("identity.json").read_text(encoding="utf-8"))
    assert identity["fiction"] is True
    assert FIXTURE.master == "tests/fixtures/generation/master.json"
    text = e2e.DEFAULT_FIXTURE_PATH.read_text(encoding="utf-8")
    assert "@" not in text  # no address of any kind, real or invented, lives in the fixture


def test_a_replay_that_walked_too_little_is_unmeasured_not_clean(tmp_path: Path) -> None:
    short = tmp_path / "short.json"
    data = json.loads(e2e.DEFAULT_FIXTURE_PATH.read_text(encoding="utf-8"))
    data["revisions"] = data["revisions"][:3]
    data["sent"] = {"revision": 3}
    short.write_text(json.dumps(data), encoding="utf-8")
    evidence = tmp_path / "T149.json"
    assert e2e._main(["end_to_end", str(evidence), str(short)]) == 3
    written = json.loads(evidence.read_text(encoding="utf-8"))
    assert written["end_to_end_replay_defects"] == -1
    assert written["end_to_end_replay_status"] == "unmeasured"


def test_a_to_block_that_does_not_survive_the_disk_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = read_payload

    def lossy(store: ProfileStore, offer_id: str, version: int) -> Payload:
        return real(store, offer_id, version).model_copy(update={"recipient": "nobody"})

    monkeypatch.setattr(e2e, "read_payload", lossy)
    defects = _run(tmp_path).defects
    assert any("revision 1" in d and "the `to` block on disk reads 'nobody'" in d for d in defects)


def test_a_revision_the_next_one_cannot_see_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = prior_digest
    offer = e2e._offer_ids(FIXTURE)["girona-data"]

    def forgetful(store: ProfileStore) -> Any:
        shutil.rmtree(store.path("cv", "generated", offer, "v2"))
        return real(store)

    monkeypatch.setattr(e2e, "prior_digest", forgetful)
    defects = _run(tmp_path).defects
    assert any(
        "girona-data: the next revision would see versions [1, 3], not [1, 2, 3]" in d
        for d in defects
    )
    assert not any("skipped" in d for d in defects)


def test_a_render_that_loses_the_style_sheet_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(e2e, "render_document", lambda markdown, **kw: "<html>" + markdown)
    defects = _run(tmp_path).defects
    assert any("cv.md was rendered without the committed style sheet" in d for d in defects)


def test_a_render_that_reaches_outside_the_page_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = render_document
    monkeypatch.setattr(
        e2e,
        "render_document",
        lambda markdown, **kw: real(markdown, **kw) + '<link rel="stylesheet" href="x.css">',
    )
    defects = _run(tmp_path).defects
    assert any(
        "letter.md renders with something outside the one self-contained page" in d for d in defects
    )


def test_an_artefact_no_detector_can_see_is_named(tmp_path: Path) -> None:
    steps = load_steps()
    edited = steps.model_copy(
        update={
            "steps": [
                s.model_copy(update={"produces": [*s.produces, "invented_artefact"]})
                if s.id == "identify"
                else s
                for s in steps.steps
            ]
        }
    )
    defects = _run(tmp_path, steps=edited).defects
    assert any("names artefacts no detector can see: ['invented_artefact']" in d for d in defects)


def test_the_committed_evidence_is_what_the_replay_measures() -> None:
    measured = e2e.measure()
    committed = json.loads(e2e.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))
    assert committed == measured
    assert committed["end_to_end_replay_defects"] == 0
    assert committed["end_to_end_replay_status"] == "measured"


# ---------------------------------------------------------------------------
# the second reader's fixtures on #775 (F1-F6): each stage is judged from what the
# stage before left on disk, with the real code, and the labels are only the
# expectation.


def _sequence(fixture: e2e.Fixture, runs: list[e2e.StepRun]) -> e2e.Fixture:
    return fixture.model_copy(update={"sequence": tuple(runs)})


def _index(stage: str) -> int:
    return next(i for i, r in enumerate(FIXTURE.sequence) if r.stage == stage)


def test_an_application_before_the_first_ranking_is_named(tmp_path: Path) -> None:
    runs = list(FIXTURE.sequence)
    application = runs.pop(_index("documents"))
    runs.insert(_index("first_ranking"), application)
    assert len(runs) == len(FIXTURE.sequence) == 14
    defects = _run(tmp_path, _sequence(FIXTURE, runs)).defects
    assert "application/documents: no ranking is on disk to draft for" in defects
    assert any("revision 1" in d and "no ranking on disk names" in d for d in defects)


def test_an_application_for_an_offer_no_ranking_names_is_named(tmp_path: Path) -> None:
    # The fixture's labels say nothing about this offer being ranked at all; the
    # real ranking over what is on disk did not carry it, so drafting for it is named.
    revision = _revision(FIXTURE, 12, offer="lleida-closed")
    defects = _run(tmp_path, revision).defects
    assert any("revision 12" in d and "no ranking on disk names" in d for d in defects)


def test_a_run_that_never_retires_or_screens_names_both_offers(tmp_path: Path) -> None:
    runs = list(FIXTURE.sequence)
    for stage in ("liveness", "filtering"):  # still 14 steps, nothing retires anything
        i = next(i for i, r in enumerate(runs) if r.stage == stage)
        runs[i] = runs[i].model_copy(update={"stage": f"recollect_{stage}"})
    defects = _run(tmp_path, _sequence(FIXTURE, runs)).defects
    assert any("lleida-closed" in d for d in defects)
    assert any("sevilla-onsite" in d for d in defects)


def test_a_liveness_reader_that_sees_no_closure_is_noticed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(liveness, "dead_phrase_in", lambda text: None)
    defects = _run(tmp_path).defects
    assert any(
        "sourcing/liveness: expired offer lleida-closed is still 'new'" in d for d in defects
    )


def test_the_closed_advert_really_reads_as_closed_to_the_real_reader() -> None:
    closed = next(s for s in FIXTURE.offers if s.slug == "lleida-closed")
    assert liveness.dead_phrase_in(closed.text) is not None
    for spec in FIXTURE.offers:
        if spec.outcome != "expired":
            assert liveness.dead_phrase_in(spec.text) is None, spec.slug


def test_a_constraint_screen_that_removes_nothing_is_noticed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = candidate.filter_hard_constraints

    def lenient(constraints: Any, offers: Any) -> Any:
        result = real(constraints, offers)
        return result.__class__(
            surviving=tuple(o.offer_id for o in offers),
            removed=(),
            outstanding_fields=result.outstanding_fields,
            unplaced=(),
        )

    monkeypatch.setattr(e2e, "filter_hard_constraints", lenient)
    defects = _run(tmp_path).defects
    assert any("filtered offer sevilla-onsite is still 'new'" in d for d in defects)


def test_the_screen_reads_the_stored_constraints_not_the_label(tmp_path: Path) -> None:
    # Nothing in the labels changes: the candidate simply no longer holds the
    # constraint that rules the Sevilla offer out, so the real screen keeps it.
    kept = FIXTURE.model_copy(
        update={
            "constraints": {k: v for k, v in FIXTURE.constraints.items() if k != "relocation"},
            "constraints_revisited": {},
        }
    )
    defects = _run(tmp_path, kept).defects
    assert any("filtered offer sevilla-onsite is still 'new'" in d for d in defects)


def test_an_offer_whose_facts_the_screen_clears_is_named(tmp_path: Path) -> None:
    spec = next(s for s in FIXTURE.offers if s.slug == "sevilla-onsite")
    plain = spec.model_copy(update={"requires_relocation": False, "delivery": "remote"})
    offers = tuple(plain if s.slug == spec.slug else s for s in FIXTURE.offers)
    defects = _run(tmp_path, FIXTURE.model_copy(update={"offers": offers})).defects
    assert any("sevilla-onsite" in d for d in defects)


def test_a_ranking_is_built_from_the_extractions_on_disk(tmp_path: Path) -> None:
    _run(tmp_path)
    store = _store(tmp_path)
    ids = e2e._offer_ids(FIXTURE)
    expected = {ids[s.slug] for s in FIXTURE.offers if s.outcome == "ranked"}
    assert e2e.ranked_offers(store) == expected
    paths = sorted(store.path("rankings").glob("*.json"))
    assert len(paths) == 2
    for path in paths:
        assert set(json.loads(path.read_text(encoding="utf-8"))["pareto"]) == expected


def test_a_send_folder_edited_after_staging_is_refused(tmp_path: Path) -> None:
    _run(tmp_path)
    store = _store(tmp_path)
    ids = e2e._offer_ids(FIXTURE)
    sent = next(r for r in FIXTURE.revisions if r.n == FIXTURE.sent.revision)
    offer, version = ids[sent.offer], sent.expect.version
    letter = store.path("cv", "generated", offer, f"v{version}", "send", "letter.md")
    letter.write_text(letter.read_text(encoding="utf-8") + "\nAn unapproved sentence.\n")
    assert verify_send(store, offer, version) != []


def test_a_verifier_that_passes_a_tampered_send_is_noticed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(e2e, "verify_send", lambda *a, **k: [])
    defects = _run(tmp_path).defects
    assert any("still verifies" in d for d in defects)


def test_application_swapped_with_collect_is_named_not_a_traceback(tmp_path: Path) -> None:
    runs = list(FIXTURE.sequence)
    a, c = _index("documents"), _index("collect")
    runs[a], runs[c] = runs[c], runs[a]
    defects = _run(tmp_path, _sequence(FIXTURE, runs)).defects  # must not raise
    assert any(d.startswith("application/documents") for d in defects)
    assert (
        "application/documents: ran without offers, which the step before did not hand over"
        in defects
    )


def test_a_revisit_that_is_the_first_visit_is_named(tmp_path: Path) -> None:
    runs = [
        r.model_copy(update={"revisit": True}) if r.step == "identify" else r
        for r in FIXTURE.sequence
    ]
    defects = _run(tmp_path, _sequence(FIXTURE, runs)).defects
    assert any("identify/greeting: marked as a revisit of identify" in d for d in defects)


def test_every_guess_the_header_promises_to_mark_is_marked() -> None:
    assert "`assumed`" in FIXTURE.provenance
    assert all(r.assumed for r in FIXTURE.revisions)
    assert FIXTURE.sent.assumed
