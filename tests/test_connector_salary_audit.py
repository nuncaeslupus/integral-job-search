"""T200 — the gate that says every board publishing a salary is one we read.

The point of every case here is the task file's warning: the gate is
satisfiable by declaring things rather than reading them, so what needs pinning
is not that it reports zero today but that each of the ways of reaching zero
dishonestly still reports a defect.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from integral import connector_salary_audit
from integral.connector_salary_audit import (
    MINIMUM_PACKAGES_MEASURED,
    MINIMUM_SALARY_ROWS_READ,
    RowVerdict,
    _declared_for,
    _money_contexts,
    _packages,
    measure,
    record,
)
from integral.connectors import _CURRENCIES

_CONNECTORS = Path(__file__).resolve().parents[1] / "connectors"


def _verdict(index: int = 0, route: str = "list") -> RowVerdict:
    return RowVerdict(index=index, route=route, publishes=(), salary=None)


# --- the money detector is derived from the currency table, not listed here ---


@pytest.mark.parametrize("token", sorted(_CURRENCIES))
def test_every_currency_the_repo_knows_is_money_next_to_a_figure(token: str) -> None:
    """Generated from `_CURRENCIES`, so a currency added later is covered here
    on the same commit that adds it. A list of currencies written out in this
    file would pass forever while the table grew past it — which is the
    enumeration failure every review round in this repository has ended on."""
    assert _money_contexts(f"Salario {token} 45000 anuales")


def test_a_currency_with_no_figure_near_it_is_not_a_published_salary() -> None:
    """The other half of the rule. A filter dropdown, a footer, a country list:
    a page naming a currency has not thereby published a band, and counting it
    as one would make the gate demand a refusal for every such page."""
    assert _money_contexts("Salaries are quoted in EUR. Apply through the portal.") == ()


def test_one_figure_named_many_times_is_one_published_salary() -> None:
    """Ashby's row is a JSON payload that repeats its band in eight places. The
    scan reports spans, not matches, so the report names the figure once."""
    # Escaped rather than written literally: the en dash is Ashby's, and a
    # literal one trips RUF001 on a character this test is specifically about.
    band = "\u20ac30K \u2013 \u20ac45K"
    payload = json.dumps({"summary": band, "tier": band, "code": "EUR"})
    assert len(_money_contexts(payload)) == 1


# --- the shared-detail wildcard is the substitution, and it is bounded ---


def test_the_wildcard_stands_in_for_a_shared_detail_fixture() -> None:
    expected = {"*": {"verdict": "read", "min": 1.0}}
    assert _declared_for(expected, _verdict(route="detail")) == expected["*"]


def test_the_wildcard_is_never_consulted_for_a_list_row() -> None:
    """A `"*"` reachable from the list route would be a blanket verdict over
    rows that genuinely differ — one line refusing a whole board, which is the
    declaration-shaped answer this gate exists to refuse. Rows on the list route
    are adjudicated one at a time or not at all."""
    expected = {"*": {"verdict": "refused", "why": "everything"}}
    assert _declared_for(expected, _verdict(route="list")) is None


def test_a_row_of_its_own_outranks_the_wildcard() -> None:
    expected = {"*": {"verdict": "read"}, "4": {"verdict": "refused", "why": "this one"}}
    assert _declared_for(expected, _verdict(index=4, route="detail")) == expected["4"]


# --- the live tree ---


def test_the_committed_fixtures_have_no_unread_salary() -> None:
    measured = measure()
    assert measured["boards_that_publish_a_salary_we_do_not_read"] == 0, measured["unread"]
    assert measured["salary_expectation_mismatches"] == 0, measured["mismatches"]


def test_the_floors_sit_under_the_live_populations() -> None:
    measured = measure()
    assert measured["salary_rows_read"] >= MINIMUM_SALARY_ROWS_READ
    assert measured["packages_measured"] >= MINIMUM_PACKAGES_MEASURED


def test_the_record_commits_the_floors_and_not_the_censuses() -> None:
    committed = record(measure())
    assert committed["salary_rows_read_at_least"] == MINIMUM_SALARY_ROWS_READ
    assert committed["packages_measured_at_least"] == MINIMUM_PACKAGES_MEASURED
    assert "salary_rows_read" not in committed
    assert "packages_measured" not in committed
    assert "rows_measured" not in committed


def test_every_declared_refusal_says_why_in_a_sentence() -> None:
    """A refusal is the one verdict that lets a row out of the gate without
    anything being read, so the reason has to be a written argument somebody
    can disagree with — not a restatement that the code returned None.

    This checks the *shape* and says so: length is a proxy, and a padded
    sentence satisfies it. What it actually catches is the generated
    placeholder — `tmp/t200_expect.py` writes `"TODO <the quoted window>"` for
    every unread row precisely so an unadjudicated one cannot reach a commit.
    Judging the argument is a second reader's job, and no assertion replaces
    it; the seven live refusals are named for that reader in the PR body."""
    for directory in _packages(_CONNECTORS):
        path = directory / "fixture" / "salary.json"
        if not path.exists():
            continue
        for index, row in json.loads(path.read_text(encoding="utf-8"))["rows"].items():
            if row["verdict"] != "refused":
                continue
            why = row["why"]
            assert len(why) >= 80, f"{directory.name} [{index}]: {why!r}"


def test_deleting_a_refusal_turns_the_gate_red(tmp_path: Path) -> None:
    """The mutation this whole module is for. `trabajos_es` row 17 publishes
    "18.000 €" and nothing reads it; what keeps the gate green is the written
    refusal. Remove the refusal and the row must come back as a defect — if it
    does not, the expectations are decorative and the gate is measuring its own
    declarations."""
    import shutil

    shutil.copytree(_CONNECTORS, tmp_path / "connectors")
    path = tmp_path / "connectors" / "trabajos_es" / "fixture" / "salary.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["rows"]["17"]
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    measured = measure(tmp_path / "connectors")
    assert measured["boards_that_publish_a_salary_we_do_not_read"] == 1
    assert any("trabajos_es [17]" in entry for entry in measured["unread"])


def test_a_refusal_written_over_a_row_we_actually_read_is_a_mismatch(tmp_path: Path) -> None:
    """The opposite direction, and the one a floor cannot see. Answering a gap
    by refusing it instead of reading it leaves `salary_rows_read` where it was,
    so the mismatch key is what makes a stale refusal visible."""
    import shutil

    shutil.copytree(_CONNECTORS, tmp_path / "connectors")
    path = tmp_path / "connectors" / "trabajos_es" / "fixture" / "salary.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["rows"]["9"] = {"verdict": "refused", "why": "x" * 80}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    measured = measure(tmp_path / "connectors")
    assert measured["salary_expectation_mismatches"] == 1
    assert any("trabajos_es [9]" in entry for entry in measured["mismatches"])


def test_a_band_read_wrongly_is_a_mismatch(tmp_path: Path) -> None:
    """And the third direction: the numbers themselves. A connector edited so it
    reads 15.000 where the advert says 18.000 keeps every count in this record
    identical, and only the declared figures catch it."""
    import shutil

    shutil.copytree(_CONNECTORS, tmp_path / "connectors")
    path = tmp_path / "connectors" / "trabajos_es" / "fixture" / "salary.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["rows"]["9"]["min"] = 1.0
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    measured = measure(tmp_path / "connectors")
    assert measured["salary_expectation_mismatches"] == 1


def test_a_dead_money_detector_is_caught_by_the_refusal_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The headline metric is blind to its own detector; one committed key is not.

    `boards_that_publish_a_salary_we_do_not_read` counts rows that publish and
    read nothing, so a detector that sees money nowhere drives it to zero while
    reading exactly as much as before — the shape CLAUDE.md calls a metric
    independent of its own inputs. `salary_rows_read` cannot catch it (the read
    branch runs first) and neither can `packages_measured`.

    What catches it is `salary_rows_refused`, committed as an exact count: the
    refusal branch sits behind `if not verdict.publishes`, so a dead detector
    takes it to zero and `make evidence` goes red. This pins that, because being
    true of today's code is not the same as being held down.
    """
    live = measure(_CONNECTORS)
    monkeypatch.setattr(connector_salary_audit, "_money_contexts", lambda text: ())
    blinded = measure(_CONNECTORS)

    assert blinded["boards_that_publish_a_salary_we_do_not_read"] == 0
    assert blinded["salary_expectation_mismatches"] == 0
    assert blinded["salary_rows_read"] == live["salary_rows_read"]
    assert blinded["packages_measured"] == live["packages_measured"]
    assert blinded["salary_rows_refused"] == 0 < live["salary_rows_refused"]
    assert record(blinded) != record(live)
