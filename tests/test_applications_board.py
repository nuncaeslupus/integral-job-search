"""T240: the applications board shows every sent application, and says what it does not know.

Expected values come from the task's text (what each column is, and that "not on record"
is not "lacks"), not from running the writer.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from integral import applications_board as board
from integral import report_style
from integral.approval import sends_without_confirmation
from integral.identity import ProfileStore, create_profile
from integral.lifecycle import record_application_status
from integral.profile import EvidenceLog, SkillStance
from integral.revision import classify, stale_artefacts

NOW = "2026-10-05T09:00:00+00:00"


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", handle="ada", language="en")
    return ProfileStore(root, identity.handle)


def _offer(store: ProfileStore, offer_id: str, **fields: Any) -> None:
    record = {
        "id": offer_id,
        "source": "manual",
        "company": "Cintra Logistics",
        "title": "Data engineer",
        "url": "https://boards.example/jobs/1",
        "fetched_at": "2026-09-20T10:00:00Z",
        "text": "advert",
        "status": "applied",
    }
    record.update(fields)
    store.write_json(record, "offers", f"{offer_id}.json")


def _sent(store: ProfileStore, offer_id: str, sent_at: str, version: int = 1) -> None:
    store.write_json(
        {"offer_id": offer_id, "version": version, "confirmed_digest": "d", "sent_at": sent_at},
        "applications",
        offer_id,
        f"v{version}.json",
    )


def _extraction(store: ProfileStore, offer_id: str, skills: list[tuple[str, str]] | None) -> None:
    payload: dict[str, Any] = {"offer_id": offer_id, "language": "en"}
    if skills is not None:
        payload["skills"] = [
            {"skill": s, "role": r, "span": {"start": 0, "end": 1, "quote": "x"}} for s, r in skills
        ]
    store.write_json(payload, "extractions", f"{offer_id}.json")


def _manifest(
    store: ProfileStore, offer_id: str, *, claims: list[str], gaps: list[str], version: int = 1
) -> None:
    store.write_json(
        {
            "offer_id": offer_id,
            "version": version,
            "claims": [
                {"document": "cv.md", "text": t, "section": "skills", "entry_index": i}
                for i, t in enumerate(claims)
            ],
            "gaps": gaps,
        },
        "cv",
        "generated",
        offer_id,
        f"v{version}",
        "manifest.json",
    )


def _rows(store: ProfileStore) -> dict[str, board.Row]:
    return {r.offer_id: r for r in board.collect(store).rows}


def _page(store: ProfileStore) -> str:
    return board.render(board.collect(store), generated_at=NOW)


# --- the list: every sent application, with the columns the candidate asked for -----


def test_a_sent_application_shows_employer_role_dates_status_and_both_links(
    store: ProfileStore,
) -> None:
    _offer(store, "a1", status="expired")
    _sent(store, "a1", "2026-09-22T08:30:00+00:00")
    record_application_status(store, "a1", status="interview", at="2026-10-01T00:00:00Z")
    board.record_tracking(store, "a1", "https://track.example/x", reported_at=NOW)
    row = _rows(store)["a1"]
    assert (row.employer, row.role) == ("Cintra Logistics", "Data engineer")
    assert (row.date, row.date_kind) == ("2026-09-22", board.SENT)
    assert row.status == "interview"
    assert row.source_status == "expired"
    assert row.last_seen == "2026-09-20"
    assert row.advert_url == "https://boards.example/jobs/1"
    assert row.tracking_url == "https://track.example/x"
    page = _page(store)
    assert 'href="https://boards.example/jobs/1"' in page
    assert 'href="https://track.example/x"' in page


def test_every_application_on_disk_is_on_the_board(store: ProfileStore) -> None:
    """The gate's count: applications on disk that the page does not show."""
    _offer(store, "sent-one")
    _sent(store, "sent-one", "2026-09-01T00:00:00Z")
    _offer(store, "status-only")
    record_application_status(store, "status-only", status="applied", at="2026-09-05T00:00:00Z")
    _sent(store, "no-offer-record", "2026-09-02T00:00:00Z")  # the offer file is gone
    store.write_text("{not json", "applications", "bad-status", "status.json")  # unreadable
    _sent(store, "bad-status", "2026-09-03T00:00:00Z")
    on_disk = {p.name for p in store.path("applications").iterdir()}
    on_board = {r.offer_id for r in board.collect(store).rows}
    assert on_disk - on_board == set()
    rows = _rows(store)
    assert any("offer is missing" in n for n in rows["no-offer-record"].notes)
    assert rows["no-offer-record"].employer == board.NOT_RECORDED
    assert any("status.json could not be read" in n for n in rows["bad-status"].notes)


def test_a_status_only_application_shows_the_day_noted_and_says_so(store: ProfileStore) -> None:
    _offer(store, "n1")
    record_application_status(store, "n1", status="applied", at="2026-09-05T12:00:00Z")
    _offer(store, "s1")
    _sent(store, "s1", "2026-09-04T12:00:00Z")
    rows = _rows(store)
    assert (rows["n1"].date, rows["n1"].date_kind) == ("2026-09-05", board.NOTED)
    assert (rows["s1"].date, rows["s1"].date_kind) == ("2026-09-04", board.SENT)
    page = _page(store)
    assert "Noted (not the send date)" in page
    assert page.count("Noted (not the send date)") == 1  # the sent one is not labelled that way
    assert "<dt>Sent</dt>" in page


def test_the_earliest_send_is_the_sent_date(store: ProfileStore) -> None:
    _offer(store, "two")
    _sent(store, "two", "2026-09-10T00:00:00Z", version=2)
    _sent(store, "two", "2026-09-08T00:00:00Z", version=1)
    assert _rows(store)["two"].date == "2026-09-08"


def test_a_draft_that_was_never_sent_is_counted_not_listed(store: ProfileStore) -> None:
    _offer(store, "d1")
    record_application_status(store, "d1", status="drafted", at="2026-09-05T00:00:00Z")
    result = board.collect(store)
    assert result.rows == ()
    assert result.left_out == {"d1": "only drafted, never sent"}
    assert "1 drafted application(s) not shown" in board.render(result, generated_at=NOW)


def test_a_drafted_status_over_a_send_record_is_still_a_sent_application(
    store: ProfileStore,
) -> None:
    _offer(store, "d2")
    _sent(store, "d2", "2026-09-06T00:00:00Z")
    record_application_status(store, "d2", status="drafted", at="2026-09-07T00:00:00Z")
    assert "d2" in _rows(store)


def test_an_empty_profile_says_nothing_was_sent(store: ProfileStore) -> None:
    assert "No application has been sent" in _page(store)


# --- the fit columns: from the extraction and the manifest -----------------------------


def test_a_skill_the_generation_found_no_entry_for_is_not_on_record_never_lacks(
    store: ProfileStore,
) -> None:
    _offer(store, "f1")
    _sent(store, "f1", "2026-09-01T00:00:00Z")
    _extraction(
        store,
        "f1",
        [("PostgreSQL", "required"), ("Kubernetes", "required"), ("Terraform", "plus")],
    )
    _manifest(store, "f1", claims=["PostgreSQL (strong)"], gaps=["Kubernetes"])
    fit = _rows(store)["f1"].fit
    assert fit.asked == ("PostgreSQL", "Kubernetes")  # a "plus" was not asked for
    assert fit.holds == ("PostgreSQL",)
    assert fit.not_on_record == ("Kubernetes",)
    assert fit.lacks == ()


def test_lacks_needs_the_candidate_to_have_said_none(store: ProfileStore) -> None:
    _offer(store, "f2")
    _sent(store, "f2", "2026-09-01T00:00:00Z")
    _extraction(store, "f2", [("Kubernetes", "required"), ("Docker", "required")])
    _manifest(store, "f2", claims=[], gaps=["Kubernetes", "Docker"])
    EvidenceLog(store).append(
        recorded_at="2026-09-30T10:00:00Z",
        step="ranking",
        kind="statement",
        text="Kubernetes no sé cómo funciona",
        source="conversation",
        skill=SkillStance(technology="kubernetes", level="none"),
    )
    fit = _rows(store)["f2"].fit
    assert fit.lacks == ("Kubernetes",)
    assert fit.not_on_record == ("Docker",)


def test_a_skill_with_no_manifest_is_not_on_record(store: ProfileStore) -> None:
    _offer(store, "f3")
    _sent(store, "f3", "2026-09-01T00:00:00Z")
    _extraction(store, "f3", [("Go", "required")])
    fit = _rows(store)["f3"].fit
    assert (fit.holds, fit.lacks, fit.not_on_record) == ((), (), ("Go",))


def test_a_term_inside_another_word_is_not_a_hold(store: ProfileStore) -> None:
    _offer(store, "f4")
    _sent(store, "f4", "2026-09-01T00:00:00Z")
    _extraction(store, "f4", [("Java", "required")])
    _manifest(store, "f4", claims=["JavaScript (strong)"], gaps=[])
    assert _rows(store)["f4"].fit.holds == ()


def test_the_newest_manifest_version_is_the_one_read(store: ProfileStore) -> None:
    _offer(store, "f5")
    _sent(store, "f5", "2026-09-01T00:00:00Z")
    _extraction(store, "f5", [("Rust", "required")])
    _manifest(store, "f5", claims=[], gaps=["Rust"], version=1)
    _manifest(store, "f5", claims=["Rust (working)"], gaps=[], version=2)
    assert _rows(store)["f5"].fit.holds == ("Rust",)


def test_an_advert_not_yet_read_for_skills_says_so_and_compares_nothing(
    store: ProfileStore,
) -> None:
    _offer(store, "f6")
    _sent(store, "f6", "2026-09-01T00:00:00Z")
    _extraction(store, "f6", None)
    assert not _rows(store)["f6"].fit.read
    assert "has not been read from it yet" in _page(store)
    _offer(store, "f7")
    _sent(store, "f7", "2026-09-01T00:00:00Z")  # no extraction file at all
    assert not _rows(store)["f7"].fit.read


def test_an_advert_that_requires_nothing_is_read_and_empty(store: ProfileStore) -> None:
    _offer(store, "f8")
    _sent(store, "f8", "2026-09-01T00:00:00Z")
    _extraction(store, "f8", [])
    fit = _rows(store)["f8"].fit
    assert fit.read and fit.asked == ()
    assert "no required skill named" in _page(store)


# --- the tracking link: stored beside the immutable records ---------------------------


def test_a_tracking_link_is_appended_and_the_newest_wins_without_touching_the_send_record(
    store: ProfileStore,
) -> None:
    _offer(store, "t1")
    _sent(store, "t1", "2026-09-01T00:00:00Z")
    before = store.path("applications", "t1", "v1.json").read_bytes()
    board.record_tracking(store, "t1", "https://track.example/old", reported_at=NOW)
    board.record_tracking(store, "t1", "https://track.example/new", reported_at=NOW)
    assert store.path("applications", "t1", "v1.json").read_bytes() == before
    assert board.tracking_links(store) == {"t1": "https://track.example/new"}
    assert len(store.path(*board.TRACKING_PARTS).read_text().splitlines()) == 2


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "data:text/html,x", "ftp://x.example/a", "track.example", ""]
)
def test_a_tracking_link_that_is_not_a_web_address_is_refused(
    store: ProfileStore, url: str
) -> None:
    _offer(store, "t2")
    _sent(store, "t2", "2026-09-01T00:00:00Z")
    with pytest.raises(board.BoardError):
        board.record_tracking(store, "t2", url, reported_at=NOW)
    assert not store.path(*board.TRACKING_PARTS).exists()


def test_a_tracking_link_for_an_application_that_does_not_exist_is_refused(
    store: ProfileStore,
) -> None:
    with pytest.raises(board.BoardError):
        board.record_tracking(store, "ghost", "https://track.example/x", reported_at=NOW)


def test_a_malformed_tracking_row_is_skipped_not_fatal(store: ProfileStore) -> None:
    _offer(store, "t3")
    _sent(store, "t3", "2026-09-01T00:00:00Z")
    store.write_text(
        'not json\n{"offer_id": "t3"}\n{"offer_id": "t3", "url": "https://track.example/ok"}\n',
        *board.TRACKING_PARTS,
    )
    assert _rows(store)["t3"].tracking_url == "https://track.example/ok"


# --- the page is the shared style, and a stored address is never followed blindly ------


def test_the_page_is_the_shared_shell_and_offline(store: ProfileStore) -> None:
    _offer(store, "p1")
    _sent(store, "p1", "2026-09-01T00:00:00Z")
    page = _page(store)
    assert page.startswith("<!doctype html>\n")
    assert report_style.CSP in page
    assert report_style.LIGHT_TOKENS in page and report_style.DARK_TOKENS in page
    assert report_style.external_references(page) == []
    assert '<section class="card">' in page and '<dl class="facts">' in page


def test_hostile_stored_values_are_escaped_and_a_script_address_is_not_a_link(
    store: ProfileStore,
) -> None:
    _offer(
        store,
        "h1",
        company="<script>alert(1)</script>",
        title='"><img src=x onerror=1>',
        url="javascript:alert(1)",
    )
    _sent(store, "h1", "2026-09-01T00:00:00Z")
    _extraction(store, "h1", [("<b>x</b>", "required")])
    page = _page(store)
    assert "<script>alert" not in page and "<img src=x" not in page and "<b>x</b>" not in page
    assert "&lt;script&gt;" in page
    assert "javascript:alert(1)" in page  # shown as text
    assert 'href="javascript' not in page
    assert not re.search(r"<a [^>]*javascript", page)


def test_link_and_markup_in_the_shared_style() -> None:
    assert report_style.link("https://a.example/?q=1&r=2") == (
        '<a href="https://a.example/?q=1&amp;r=2" rel="noopener noreferrer">'
        "https://a.example/?q=1&amp;r=2</a>"
    )
    assert report_style.link("not recorded") == "not recorded"
    assert report_style.link("javascript:x", "go") == "go"
    assert report_style.link('https://a.example/"onmouseover="x') == (
        "https://a.example/&quot;onmouseover=&quot;x"
    )
    rendered = report_style.facts([("k", "<i>"), ("l", report_style.link("https://a.example"))])
    assert "&lt;i&gt;" in rendered and '<a href="https://a.example"' in rendered


def test_write_report_refuses_anything_the_shell_did_not_produce(store: ProfileStore) -> None:
    with pytest.raises(ValueError):
        report_style.write_report(store, "<html></html>", "reports", "x.html")
    with pytest.raises(ValueError):
        report_style.write_report(store, report_style.page("t", "b"), "reports", "x.txt")
    with pytest.raises(ValueError):
        report_style.write_report(store, report_style.page("t", "b"))
    assert not store.path("reports").exists()


# --- a home in the profile tree --------------------------------------------------------


def test_the_board_and_links_leave_the_application_audit_and_the_staleness_report_alone(
    store: ProfileStore,
) -> None:
    _offer(store, "r1")
    _sent(store, "r1", "2026-09-01T00:00:00Z")
    audit_before = sends_without_confirmation(store)
    stale_before = [s.artefact for s in stale_artefacts(store)]
    board.record_tracking(store, "r1", "https://track.example/x", reported_at=NOW)
    path = board.write_board(store)
    assert path == store.path(*board.BOARD_PARTS)
    assert sends_without_confirmation(store) == audit_before
    assert [s.artefact for s in stale_artefacts(store)] == stale_before
    assert not any("reports" in a or "tracking" in a for a in stale_before)
    assert not list(store.path("applications").rglob("*.html"))


def test_both_new_folders_are_placed_not_left_to_the_authored_default() -> None:
    assert classify("tracking/links.jsonl") == "historical"
    assert classify("reports/applications.html") == "historical"
    assert classify("unplaced/applications.html") == "authored"  # the default being avoided


def test_the_board_regenerates_over_itself(store: ProfileStore) -> None:
    _offer(store, "g1")
    _sent(store, "g1", "2026-09-01T00:00:00Z")
    first = board.write_board(store, now=None)
    _offer(store, "g2", company="Second Co")
    _sent(store, "g2", "2026-09-02T00:00:00Z")
    board.write_board(store)
    assert first.read_text().count('<section class="card">') == 2


# --- the command ------------------------------------------------------------------------


def test_the_command_writes_the_board_and_can_record_a_link_first(
    store: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    _offer(store, "c1")
    _sent(store, "c1", "2026-09-01T00:00:00Z")
    root = str(store.path().parent)
    args = ["--id", "ada", "--input-dir", root]
    assert board._main([*args, "--track", "c1", "https://track.example/c"]) == 0
    assert capsys.readouterr().out.strip() == str(store.path(*board.BOARD_PARTS))
    assert "https://track.example/c" in store.path(*board.BOARD_PARTS).read_text()
    assert board._main([*args, "--track", "c1", "javascript:1"]) == 2
    assert board._main([*args, "--track", "missing", "https://track.example/c"]) == 2


@pytest.mark.parametrize(
    "record",
    [
        "{not json",
        '{"offer_id": "u1", "version": 1}',
        '{"sent_at": 5}',
        '{"sent_at": ""}',
        '{"sent_at": "   "}',
        '{"sent_at": "yesterday"}',
    ],
    ids=str,
)
def test_an_unreadable_send_record_under_a_drafted_status_is_still_a_sent_application(
    store: ProfileStore, record: str
) -> None:
    _offer(store, "u1")
    store.write_text(record, "applications", "u1", "v1.json")
    record_application_status(store, "u1", status="drafted", at="2026-09-07T00:00:00Z")
    result = board.collect(store)
    assert [r.offer_id for r in result.rows] == ["u1"]
    assert result.left_out == {}
    assert any("send record could not be read" in n for n in result.rows[0].notes)
    assert "never sent" not in board.render(result, generated_at=NOW)
    assert result.rows[0].date != ""  # never a blank date


def test_a_legacy_sent_json_with_no_stamp_under_drafted_is_still_a_sent_application(
    store: ProfileStore,
) -> None:
    _offer(store, "u2")
    store.write_text('{"sent_at": ""}', "applications", "u2", "sent.json")
    record_application_status(store, "u2", status="drafted", at="2026-09-07T00:00:00Z")
    assert [r.offer_id for r in board.collect(store).rows] == ["u2"]


def test_the_planned_deletion_names_the_new_folders(store: ProfileStore) -> None:
    from integral.retraction import plan_deletion

    _offer(store, "x1")
    _sent(store, "x1", "2026-09-01T00:00:00Z")
    board.record_tracking(store, "x1", "https://track.example/x", reported_at=NOW)
    board.write_board(store)
    areas = plan_deletion(store.path().parent, "ada").areas
    assert "tracking links" in areas and "reports" in areas
