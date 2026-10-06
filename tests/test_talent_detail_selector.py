"""T254 — the count of talent_es detail selectors on a build-generated class."""

from __future__ import annotations

from pathlib import Path

from integral.talent_detail_selector import measure, record

_PACKAGE = Path(__file__).resolve().parents[1] / "connectors" / "talent_es"


def test_the_committed_package_has_none_and_read_something() -> None:
    measured = measure()
    assert measured["talent_es_detail_selectors_on_a_generated_class"] == 0
    assert measured["talent_es_detail_selectors_read"] >= 1
    assert measured["gate_status"] == "measured"


def test_the_stale_hash_selector_is_counted_even_with_a_stated_reason(tmp_path: Path) -> None:
    package = tmp_path / "talent_es"
    package.mkdir()
    text = (_PACKAGE / "connector.yaml").read_text(encoding="utf-8")
    old = 'css: "div"\n      after_text: "Descripción del trabajo"'
    assert text.count(old) == 1
    text = text.replace(
        old, 'css: "div.sc-f4dbceab-10"\n      build_hash_accepted: "stale on purpose"'
    )
    (package / "connector.yaml").write_text(text, encoding="utf-8")
    assert measure(package)["talent_es_detail_selectors_on_a_generated_class"] == 1


def test_a_record_reads_a_floor_not_the_count_of_the_day() -> None:
    assert "talent_es_detail_selectors_read" not in record(measure())
