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


def test_a_board_blocked_on_the_engine_has_its_writeup() -> None:
    """The invariant that actually protects this file.

    `blocked_on_engine` says a board passed robots and served its adverts, and
    that only this repository stands in the way. That is a strong claim and it
    is worthless without the evidence, which lives in `ruled-out.yaml` under an
    `engine_gap_*` section. A row here with no writeup there is a board nobody
    can act on and nobody can check — the shape of an entry that quietly
    becomes false.
    """
    document = yaml.safe_load(WANTED.read_text(encoding="utf-8"))
    blocked = {str(e["site"]) for e in document.get("blocked_on_engine", [])}
    assert blocked, "the two boards this survey found are the reason this list exists"

    ruled_out = yaml.safe_load(RULED_OUT.read_text(encoding="utf-8"))
    written_up = {
        str(entry["site"])
        for name, section in ruled_out.items()
        if name.startswith("engine_gap") and isinstance(section, list)
        for entry in section
        if isinstance(entry, dict) and "site" in entry
    }
    assert blocked <= written_up, f"claimed blocked with no writeup: {sorted(blocked - written_up)}"


def test_the_backlog_is_not_empty() -> None:
    """A floor, so an emptied file cannot pass as a satisfied backlog.

    Deliberately low, and lower than it was. The 2026-09-06 survey turned nine
    of fourteen entries into rulings, which is the file working rather than the
    file shrinking — but a floor that tracks the list downwards protects
    nothing, so this one asserts only that the backlog and the engine-blocked
    list have not both gone empty.
    """
    document = yaml.safe_load(WANTED.read_text(encoding="utf-8"))
    assert len(document["wanted"]) + len(document.get("blocked_on_engine", [])) >= 4


def test_the_countries_with_no_candidate_left_are_named() -> None:
    """FR and NL ran out of candidates, and silence would read as coverage.

    Every board this file listed for them is refused — robots, an empty shell,
    an Oracle login, a 403. A reader scanning the rows would see no FR entry
    and conclude nobody had looked. The header has to say it, because the
    absence of a row cannot.
    """
    header = WANTED.read_text(encoding="utf-8")
    assert "FR and NL are exhausted" in header
    for country in ("DE", "PT", "IT", "EU"):
        rows = yaml.safe_load(header)
        listed = {str(e["country"]) for e in rows["wanted"]} | {
            str(e["country"]) for e in rows.get("blocked_on_engine", [])
        }
        assert country in listed, f"{country} has zero connectors and no candidate row"
