"""`connectors/wanted.yaml` — the backlog, and the one way it can quietly lie.

The file is prose and nothing in the sourcing path reads it. What it *can* get
wrong is listing a board `ruled-out.yaml` already refused, which sends the next
reader to spend an hour re-deriving a ruling that exists. That is the whole
reason `ruled-out.yaml` was written, so repeating it here would be the same
mistake one file over.

Everything else about this file is judgment and is not testable — which is why
the header says so rather than dressing the ranks up as a measurement.
"""

from __future__ import annotations

import yaml

from integral.connectors import DEFAULT_CONNECTORS_DIR, connector_packages, load_connector

WANTED = DEFAULT_CONNECTORS_DIR / "wanted.yaml"
RULED_OUT = DEFAULT_CONNECTORS_DIR / "ruled-out.yaml"


def _wanted() -> list[dict[str, object]]:
    wanted: list[dict[str, object]] = yaml.safe_load(WANTED.read_text(encoding="utf-8"))["wanted"]
    return wanted


def _ruled_out_sites() -> set[str]:
    document = yaml.safe_load(RULED_OUT.read_text(encoding="utf-8"))
    return {
        str(entry["site"])
        for section in document.values()
        if isinstance(section, list)
        for entry in section
        if isinstance(entry, dict) and "site" in entry
    }


def test_no_wanted_board_was_already_ruled_out() -> None:
    """The one real check. An overlap costs the next reader an hour."""
    overlap = {str(e["site"]) for e in _wanted()} & _ruled_out_sites()
    assert not overlap, f"already surveyed and refused in ruled-out.yaml: {sorted(overlap)}"


def test_no_wanted_board_already_has_a_connector() -> None:
    have = set()
    for package in connector_packages():
        try:
            have.add(load_connector(package / "connector.yaml").site)
        except Exception:
            continue
    overlap = {str(e["site"]) for e in _wanted()} & have
    assert not overlap, f"already has a connector: {sorted(overlap)}"


def test_every_entry_is_marked_unsurveyed() -> None:
    """None of these has been fetched or had its robots.txt adjudicated.

    An entry that claimed otherwise would be asserting a verdict nobody
    measured — the failure `ruled-out.yaml`'s header calls a guess with a date
    on it. Surveying a board moves it to `ruled-out.yaml` or into a package;
    it never becomes a surveyed row here.
    """
    unsurveyed = [e for e in _wanted() if e.get("surveyed") is False]
    assert len(unsurveyed) == len(_wanted())


def test_the_backlog_is_not_empty_and_names_the_uncovered_countries() -> None:
    """A floor, so an emptied file cannot pass as a satisfied backlog."""
    wanted = _wanted()
    assert len(wanted) >= 10
    covered = {"DE", "FR", "IT", "NL", "PT"}
    assert covered <= {str(e["country"]) for e in wanted}, (
        "the five countries measured at zero coverage are the reason this file exists"
    )
