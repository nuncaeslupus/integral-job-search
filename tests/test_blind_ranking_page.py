"""T20's blind sitting page — what it carries, and what it must never carry."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from integral import calibration

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "blind_ranking_page", _REPO_ROOT / "tools" / "blind_ranking_page.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _embedded(page: str) -> dict[str, Any]:
    match = re.search(
        r'<script type="application/json" id="integral-data">(.*?)</script>', page, re.S
    )
    assert match
    payload = json.loads(match.group(1).replace("<\\/", "</"))
    assert isinstance(payload, dict)
    return payload


def test_the_page_carries_the_advert_and_nothing_the_system_thinks() -> None:
    tool = _module()
    pages = calibration.presentation(calibration.draw())["pages"]
    data = _embedded(tool.build_page(pages, tool.DEFAULT_BLOCK_NAMES))

    assert len(data["pages"]) == calibration.TWENTY
    for page in data["pages"]:
        assert set(page) == calibration.PAGE_KEYS
    assert data["block_names"] == list(tool.DEFAULT_BLOCK_NAMES)
    # The same detector T20a's gate runs, applied to what the page embeds.
    assert calibration.leaks({"pages": data["pages"]}, system_order=[]) == []


def test_a_page_built_from_a_leaky_payload_is_refused() -> None:
    tool = _module()
    pages = calibration.presentation(calibration.draw())["pages"]
    pages[0] = {**pages[0], "salary_equivalent_total": 3200.0}
    with pytest.raises(ValueError, match="salary_equivalent_total"):
        tool.build_page(pages, tool.DEFAULT_BLOCK_NAMES)


def test_the_page_is_self_contained() -> None:
    tool = _module()
    page = tool.build_page(
        calibration.presentation(calibration.draw())["pages"], tool.DEFAULT_BLOCK_NAMES
    )
    # No network: the sitting has to work on a laptop with the wifi off, and a
    # remote asset is one more thing that can show the candidate something.
    # Checked as *fetches*, not as the substring "http" — the adverts are
    # scraped text and are full of URLs nobody loads.
    for fetcher in ("src=", "<link", "@import", "fetch(", "XMLHttpRequest"):
        assert fetcher not in page

    # The advert text is scraped and may contain the one substring that would
    # close the data block early.
    assert "</script>" not in _embedded(page)["pages"][0]["text"]


def test_the_export_is_the_three_blocks_read_top_to_bottom() -> None:
    tool = _module()
    page = tool.build_page(
        calibration.presentation(calibration.draw())["pages"], tool.DEFAULT_BLOCK_NAMES
    )
    # The ordering T20 correlates is a concatenation, not a second thing the
    # candidate has to produce — asserted on the source so a change to it is a
    # deliberate one.
    assert "return ['b0', 'b1', 'b2'].flatMap(key => state.lists[key]);" in page
    assert "payload.complete = left === 0 && !problem;" in page


def test_the_page_refuses_to_call_itself_complete_on_a_name_collision() -> None:
    tool = _module()
    page = tool.build_page(
        calibration.presentation(calibration.draw())["pages"], tool.DEFAULT_BLOCK_NAMES
    )
    # Block names are keys in the export, so two the same overwrite one another
    # and a block's ids vanish while `ordering` still looks complete.
    # `calibration.record` refuses that partition; the page must not offer it.
    assert "function nameProblem()" in page
    assert "two blocks share a name" in page
    assert "every block needs a name" in page
    assert "payload.complete = left === 0 && !problem;" in page


def test_the_page_is_built_from_the_same_store_record_validates_against() -> None:
    # No `--store` flag: `record` re-derives the drawn set from the default
    # store to validate what comes back, so a page built from another store
    # would export ids it then rejects as unknown — an hour of reading that
    # cannot be saved. Asserted on the parser, not on the file's prose.
    source = (_REPO_ROOT / "tools" / "blind_ranking_page.py").read_text()
    assert 'add_argument("--store"' not in source
