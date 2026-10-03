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
    MINIMUM_DISTINCT_SALARY_VERDICTS_READ,
    MINIMUM_PACKAGES_MEASURED,
    RowVerdict,
    _declared_for,
    _money_contexts,
    _packages,
    _pin_holds,
    _single_figure_agrees,
    card_band,
    card_figure,
    measure,
    record,
)
from integral.connectors import _CURRENCIES

_CONNECTORS = Path(__file__).resolve().parents[1] / "connectors"


def _verdict(
    index: int = 0, route: str = "list", list_publishes: tuple[str, ...] = ()
) -> RowVerdict:
    return RowVerdict(
        index=index, route=route, publishes=(), salary=None, list_publishes=list_publishes
    )


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
    assert _declared_for(expected, _verdict(route="detail")) == (expected["*"], True)


def test_the_wildcard_never_adjudicates_a_row_whose_card_publishes_money() -> None:
    """The card's band is list-side text; a detail fixture says nothing about it."""
    expected = {"*": {"verdict": "read"}}
    verdict = _verdict(route="detail", list_publishes=("150000",))
    assert _declared_for(expected, verdict) == (None, False)


def test_the_wildcard_is_never_consulted_for_a_list_row() -> None:
    """A `"*"` reachable from the list route would be a blanket verdict over
    rows that genuinely differ — one line refusing a whole board, which is the
    declaration-shaped answer this gate exists to refuse. Rows on the list route
    are adjudicated one at a time or not at all."""
    expected = {"*": {"verdict": "refused", "why": "everything"}}
    assert _declared_for(expected, _verdict(route="list")) == (None, False)


def test_a_row_of_its_own_outranks_the_wildcard() -> None:
    expected = {"*": {"verdict": "read"}, "4": {"verdict": "refused", "why": "this one"}}
    assert _declared_for(expected, _verdict(index=4, route="detail")) == (expected["4"], False)


# --- the live tree ---


def test_the_committed_fixtures_have_no_unread_salary() -> None:
    measured = measure()
    assert measured["boards_that_publish_a_salary_we_do_not_read"] == 0, measured["unread"]
    assert measured["salary_expectation_mismatches"] == 0, measured["mismatches"]


def test_the_floors_sit_under_the_live_populations() -> None:
    measured = measure()
    assert measured["distinct_salary_verdicts_read"] >= MINIMUM_DISTINCT_SALARY_VERDICTS_READ
    assert measured["packages_measured"] >= MINIMUM_PACKAGES_MEASURED


def test_the_record_commits_the_floors_and_not_the_censuses() -> None:
    committed = record(measure())
    assert (
        committed["distinct_salary_verdicts_read_at_least"] == MINIMUM_DISTINCT_SALARY_VERDICTS_READ
    )
    assert committed["packages_measured_at_least"] == MINIMUM_PACKAGES_MEASURED
    assert "salary_rows_read" not in committed
    assert "distinct_salary_verdicts_read" not in committed
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
    # Not asserted: `salary_expectation_mismatches`. Blinded, the shared-detail
    # rows fall back to the engine's read, which is not their card's band.
    assert blinded["salary_rows_read"] >= live["salary_rows_read"]
    assert blinded["distinct_salary_verdicts_read"] >= live["distinct_salary_verdicts_read"]
    assert blinded["packages_measured"] == live["packages_measured"]
    assert blinded["salary_rows_refused"] == 0 < live["salary_rows_refused"]
    assert record(blinded) != record(live)


def test_editing_a_list_card_band_turns_the_audit_red(tmp_path: Path) -> None:
    """`foorilla_en`'s cards publish their own band; the shared detail page does
    not. A card edited to say a different band must fail its row's `list_says`,
    which a `"*"` over the shared detail fixture could never notice."""
    import shutil

    shutil.copytree(_CONNECTORS, tmp_path / "connectors")
    fixture = tmp_path / "connectors" / "foorilla_en" / "fixture"
    data = json.loads((fixture / "salary.json").read_text(encoding="utf-8"))
    assert "150K-190K" in data["rows"]["0"]["list_says"]
    band = "CAD 150K-190K"
    html = (fixture / "list.html").read_text(encoding="utf-8")
    assert band in html
    (fixture / "list.html").write_text(html.replace(band, "1 USD - 2 USD", 1), encoding="utf-8")

    measured = measure(tmp_path / "connectors")
    assert any("foorilla_en [0]" in entry for entry in measured["mismatches"])


def test_the_wildcard_covers_only_rows_whose_card_publishes_nothing() -> None:
    measured = measure(_CONNECTORS)
    assert measured["rows_adjudicated_by_a_wildcard"] == 7


def _copy_connectors(tmp_path: Path) -> Path:
    import shutil

    shutil.copytree(_CONNECTORS, tmp_path / "connectors")
    return tmp_path / "connectors"


def test_distinct_verdicts_are_counted_as_tuples_not_rows() -> None:
    """R2. The key is the number of distinct `(package, min, max, currency,
    period)` verdicts, recomputed here straight from the committed entries. A
    key reverted to a row count (`read_rows`, or rows minus wildcard rows)
    equals 102 or 95 where this is 78, so it cannot pass."""
    measured = measure(_CONNECTORS)
    tuples = set()
    for path in _CONNECTORS.glob("*/fixture/salary.json"):
        for entry in json.loads(path.read_text(encoding="utf-8"))["rows"].values():
            if entry["verdict"] == "read":
                tuples.add(
                    (path.parts[-3], entry["min"], entry["max"], entry["currency"], entry["period"])
                )
    assert measured["distinct_salary_verdicts_read"] == len(tuples)
    assert measured["distinct_salary_verdicts_read"] < measured["salary_rows_read"]


def test_the_record_commits_the_distinct_verdict_floor() -> None:
    committed = record(measure(_CONNECTORS))
    assert committed["distinct_salary_verdicts_read_at_least"] == (
        MINIMUM_DISTINCT_SALARY_VERDICTS_READ
    )
    assert "rows_read_through_a_substituted_detail" in committed


@pytest.mark.parametrize(
    ("text", "band"),
    [
        ("[SE] CAD 150K-190K Vancouver", (150000.0, 190000.0, "CAD")),
        ("Full-time $70k \u2013 $76k \u2022 No equity", (70000.0, 76000.0, "USD")),
        ("[SE] CAD 42K Toronto", None),  # one figure is not a band
        ("USD 1K-2K or EUR 3K-4K", None),  # two different bands: nothing said
        ("10 - 20 employees", None),  # no currency, not money
        # N1: formats the old slice could not cut out, each a real fixture row.
        ("Jornada completa 45.000 \u20ac - 55.000 \u20ac Anadida", (45000.0, 55000.0, "EUR")),
        ("Salary: \u00a335,681 to \u00a339,424 per annum", (35681.0, 39424.0, "GBP")),
        ("[MI] 174K-252K USD Mountain View", (174000.0, 252000.0, "USD")),
        # N3: a word starting with M/K is not a magnitude.
        ("USD 174,000-252,000 Mountain View", (174000.0, 252000.0, "USD")),
        ("EUR 40.000-50.000 Madrid", (40000.0, 50000.0, "EUR")),
        ("EUR 40.000-50.000 Kiel", (40000.0, 50000.0, "EUR")),
        # B2: a non-ASCII letter ends the token too.
        ("EUR 40.000-50.000 M\u00e1laga", (40000.0, 50000.0, "EUR")),
        ("EUR 40.000-50.000 M\u00f3stoles", (40000.0, 50000.0, "EUR")),
        ("EUR 40.000-50.000 \u00c1vila", (40000.0, 50000.0, "EUR")),
        # Escaped markup between the figures is not a reason to see no band.
        (
            "&lt;span&gt;$320,000&lt;/span&gt;&amp;mdash;&lt;span&gt;$405,000 USD&lt;/span&gt;",
            (320000.0, 405000.0, "USD"),
        ),
    ],
)
def test_card_band_reads_the_card_with_the_engines_own_take(
    text: str, band: tuple[float, float, str] | None
) -> None:
    assert card_band(text) == band


def test_an_entry_copied_from_the_engines_read_over_a_different_card_is_a_mismatch(
    tmp_path: Path,
) -> None:
    """R1, the exact defect: an entry whose `list_says` matches its card but
    whose money is another advert's. Row 1's card says USD 174K-252K; declaring
    the shared page's CAD 150K-190K beside it must be red."""
    directory = _copy_connectors(tmp_path)
    path = directory / "foorilla_en" / "fixture" / "salary.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    row = data["rows"]["1"]
    assert (row["min"], row["currency"]) == (174000.0, "USD")
    row.update(min=150000.0, max=190000.0, currency="CAD")
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    mismatches = measure(directory)["mismatches"]
    assert any("foorilla_en [1]" in entry for entry in mismatches), mismatches


def test_a_single_figure_card_cannot_be_declared_read(tmp_path: Path) -> None:
    directory = _copy_connectors(tmp_path)
    path = directory / "foorilla_en" / "fixture" / "salary.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    row = data["rows"]["34"]
    assert row["verdict"] == "refused"
    data["rows"]["34"] = {
        "verdict": "read",
        "min": 150000.0,
        "max": 190000.0,
        "currency": "CAD",
        "period": None,
        "list_says": row["list_says"],
    }
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    measured = measure(directory)
    assert measured["boards_that_publish_a_salary_we_do_not_read"] == 1


def test_a_connector_reverted_to_the_top_of_a_band_cannot_be_certified_by_a_copy(
    tmp_path: Path,
) -> None:
    """wellfound_en row 0's card says $70k-$76k. Strip the connector's list
    salary fields and the engine goes back to recovering `Salary: $76,000` from
    the body, 76000 with no minimum. An entry that copies that read agrees with
    the engine, so only the card can call it wrong — and it must."""
    import re

    directory = _copy_connectors(tmp_path)
    yaml_path = directory / "wellfound_en" / "connector.yaml"
    text = yaml_path.read_text(encoding="utf-8")
    stripped = re.sub(
        r"    salary_(min|max|currency):\n      css: \"span\.pl-1\.text-xs\"\n"
        r"      take: \"[a-z_]+\"\n",
        "",
        text,
    )
    assert stripped != text
    yaml_path.write_text(stripped, encoding="utf-8")
    path = directory / "wellfound_en" / "fixture" / "salary.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["rows"]["0"].update(min=76000.0, max=None, period="year")
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    mismatches = measure(directory)["mismatches"]
    assert any("wellfound_en [0]" in entry and "card publishes" in entry for entry in mismatches)


def test_foorillas_rows_are_counted_as_read_through_a_substituted_detail() -> None:
    """47 of foorilla's 48 banded cards disagree with the one shared advert page
    (row 0's own card is the 48th); wellfound, which reads its card, adds none."""
    assert measure(_CONNECTORS)["rows_read_through_a_substituted_detail"] == 47


@pytest.mark.parametrize(
    ("text", "figure"),
    [
        ("[SE] CAD 42K Toronto", (42000.0, "CAD")),
        ("[MI] RON 100K Bucharest", (100000.0, "RON")),
        ("Starting at $143,913 Per year (GS 14-15)", (143913.0, "USD")),
        ("18.000 \u20ac De duracion determinada", (18000.0, "EUR")),
        ("CAD 150K-190K Vancouver", None),  # a band is `card_band`'s, not a figure
        # B3: a band written without a dash is not one figure.
        ("\u20ac40.000 a 50.000", None),
        ("Entre 30.000 y 40.000 \u20ac", None),
        ("EUR 40.000 / 50.000", None),
        ("EUR 40.000 hasta 50.000 por a\u00f1o", None),
        # ...and a grade beside a salary still is one figure
        ("Starting at $108,592 Per year (GS 14-15)", (108592.0, "USD")),
        ("USD 1K or EUR 3K", None),  # two figures: nothing to hold a read against
        ("GS 14-15, 12 staff", None),  # no currency
    ],
)
def test_card_figure_reads_a_lone_figure(
    text: str, figure: tuple[float, str | None] | None
) -> None:
    assert card_figure(text) == figure


_DROP = object()


def _edit_entry(tmp_path: Path, package: str, row: str, **changes: object) -> Path:
    directory = _copy_connectors(tmp_path)
    path = directory / package / "fixture" / "salary.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for key, value in changes.items():
        if value is _DROP:
            data["rows"][row].pop(key, None)
        else:
            data["rows"][row][key] = value
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return directory


def test_no_row_that_reads_a_salary_leaves_its_card_money_uncompared() -> None:
    """T215's key. Driven to zero over the committed tree, and the count of rows
    that carry a declared reason is exact so it cannot grow unseen."""
    measured = measure(_CONNECTORS)
    assert measured["rows_read_whose_card_money_was_not_compared"] == 0, measured["uncompared"]
    assert measured["rows_read_with_a_declared_uncomparable_card"] == 5
    assert "rows_read_whose_card_money_was_not_compared" in record(measured)


@pytest.mark.parametrize(
    ("package", "row", "changes"),
    [
        # N1's probe: the engine reads 45000-45000, the entry is copied to match.
        ("jobfluent_es", "2", {"min": 45000.0, "max": 45000.0}),
        ("infojobs_es", "0", {"max": 51000.0}),
        ("jobsacuk_en", "0", {"min": 35000.0}),
        ("tecnoempleo_es", "0", {"max": 37000.0}),
        # a single-figure card is compared too
        ("usajobs_en", "0", {"min": 143914.0}),
        ("usajobs_en", "0", {"min": None, "max": 143913.0}),
    ],
)
def test_an_entry_that_disagrees_with_a_card_the_old_slice_missed_is_red(
    tmp_path: Path, package: str, row: str, changes: dict[str, object]
) -> None:
    directory = _edit_entry(tmp_path, package, row, **changes)
    measured = measure(directory)
    assert measured["salary_expectation_mismatches"] >= 1, measured["mismatches"]
    assert any(f"{package} [{row}]" in entry for entry in measured["mismatches"])


def test_an_uncomparable_card_without_a_reason_is_counted_not_skipped(tmp_path: Path) -> None:
    directory = _edit_entry(tmp_path, "getmanfred_es", "0", card_uncomparable=_DROP)
    measured = measure(directory)
    assert measured["rows_read_whose_card_money_was_not_compared"] == 1
    assert measured["rows_read_with_a_declared_uncomparable_card"] == 4
    assert any("getmanfred_es [0]" in entry for entry in measured["uncompared"])


def test_a_token_reason_does_not_declare_a_card_uncomparable(tmp_path: Path) -> None:
    directory = _edit_entry(tmp_path, "getmanfred_es", "0", card_uncomparable="x")
    assert measure(directory)["rows_read_whose_card_money_was_not_compared"] == 1


@pytest.mark.parametrize(
    ("declared", "agrees"),
    [
        ({"min": 42000.0, "max": None, "currency": "CAD"}, True),
        ({"min": None, "max": 42000.0, "currency": "CAD"}, True),  # side is the engine's call
        ({"min": 42000.0, "max": None, "currency": None}, True),  # no currency declared: a gap
        ({"min": 43000.0, "max": None, "currency": "CAD"}, False),  # wrong figure
        ({"min": 42000.0, "max": 42000.0, "currency": "CAD"}, False),  # a band from one figure
        ({"min": None, "max": None, "currency": "CAD"}, False),  # nothing read
        ({"min": 42000.0, "max": None, "currency": "USD"}, False),  # wrong currency
    ],
)
def test_a_declared_read_must_match_the_one_figure_the_card_prints(
    declared: dict[str, object], agrees: bool
) -> None:
    assert _single_figure_agrees(declared, (42000.0, "CAD")) is agrees


def _repoint_himalayas_max(tmp_path: Path) -> Path:
    """The engine now reads 70-70 from the list row: its `salary_max` field is
    pointed at `minSalary`. The card (JSON, `maxSalary` 90) is untouched."""
    directory = _copy_connectors(tmp_path)
    path = directory / "himalayas_en" / "connector.yaml"
    text = path.read_text(encoding="utf-8")
    assert "salary_max: maxSalary" in text
    path.write_text(
        text.replace("salary_max: maxSalary", "salary_max: minSalary"), encoding="utf-8"
    )
    return directory


def test_an_engine_misread_copied_into_a_json_card_entry_is_red(tmp_path: Path) -> None:
    """B1. himalayas_en row 0: a JSON card, `USD` more than 40 characters from a
    digit, so `list_publishes` is empty and the row used to fall out of the card
    check. Engine reads 70-70 and the entry is copied to match: must be red."""
    directory = _repoint_himalayas_max(tmp_path)
    path = directory / "himalayas_en" / "fixture" / "salary.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["rows"]["0"].update(min=70.0, max=70.0)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    measured = measure(directory)
    assert any("himalayas_en [0]" in entry for entry in measured["mismatches"]), measured


def test_a_list_row_that_reads_money_is_counted_without_a_money_window(tmp_path: Path) -> None:
    directory = _edit_entry(tmp_path, "himalayas_en", "0", card_uncomparable=_DROP)
    measured = measure(directory)
    assert measured["rows_read_whose_card_money_was_not_compared"] == 1
    assert any("himalayas_en [0]" in entry for entry in measured["uncompared"])


@pytest.mark.parametrize(
    "changes",
    [{"card_figures": _DROP}, {"card_figures": []}, {"card_figures": [70.0, 91.0]}],
)
def test_a_waiver_must_pin_figures_that_are_on_the_card(
    tmp_path: Path, changes: dict[str, object]
) -> None:
    directory = _edit_entry(tmp_path, "himalayas_en", "0", **changes)
    measured = measure(directory)
    assert measured["salary_expectation_mismatches"] >= 1, measured


def test_the_cli_exits_nonzero_on_an_uncompared_row(monkeypatch: pytest.MonkeyPatch) -> None:
    clean = measure(_CONNECTORS)
    dirty = {**clean, "rows_read_whose_card_money_was_not_compared": 1}
    monkeypatch.setattr(connector_salary_audit, "write_evidence", lambda *a, **k: dirty)
    assert connector_salary_audit._main(["audit"]) == 1
    monkeypatch.setattr(connector_salary_audit, "write_evidence", lambda *a, **k: clean)
    assert connector_salary_audit._main(["audit"]) == 0


def test_a_pin_must_be_on_the_card_and_equal_the_read() -> None:
    """`_pin_holds` directly: the entry and its pin may agree with each other and
    with nothing the card prints, which only the on-the-card half can refuse."""
    card = frozenset({70.0, 90.0})
    assert _pin_holds({"min": 70.0, "max": 90.0}, [70.0, 90.0], card)
    assert _pin_holds({"min": None, "max": 90.0}, [90.0], card)
    assert not _pin_holds({"min": 70.0, "max": 91.0}, [70.0, 91.0], card)  # 91 not printed
    assert not _pin_holds({"min": 70.0, "max": 70.0}, [70.0, 90.0], card)  # read is not the pin
    assert not _pin_holds({"min": 70.0, "max": 90.0}, [], card)
    assert not _pin_holds({"min": 70.0, "max": 90.0}, None, card)
