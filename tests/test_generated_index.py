"""T343: cv/generated/INDEX.md is regenerated from the tree on every write path."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from integral import generated_index
from integral.cv_store import CVMaster
from integral.generate import DEFAULT_FIXTURE_MASTER, generate, link_employer
from integral.generated_index import INDEX_NAME, missing_from_index, refresh_index, render_index
from integral.identity import ProfileStore, create_profile

SRC = Path(generated_index.__file__).parent


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", handle="ada", language="en")
    return ProfileStore(root, identity.handle)


@pytest.fixture
def master() -> CVMaster:
    return CVMaster.model_validate_json(DEFAULT_FIXTURE_MASTER.read_text(encoding="utf-8"))


def _index(store: ProfileStore) -> str:
    return store.path("cv", "generated", INDEX_NAME).read_text(encoding="utf-8")


def test_generate_lists_every_version_it_writes(store: ProfileStore, master: CVMaster) -> None:
    generate(store, master, offer_id="sha256:aaa", advert="x")
    assert "`sha256:aaa` | v1 |" in _index(store)
    generate(store, master, offer_id="sha256:aaa", advert="x")
    assert "v1, v2" in _index(store)
    assert missing_from_index(store) == []


def test_link_employer_names_the_slug(store: ProfileStore, master: CVMaster) -> None:
    generate(store, master, offer_id="sha256:aaa", advert="x")
    link_employer(store, "sha256:aaa", "acme")
    assert "(`acme`)" in _index(store)


def test_relinking_the_same_offer_still_refreshes(store: ProfileStore, master: CVMaster) -> None:
    generate(store, master, offer_id="sha256:aaa", advert="x")
    link_employer(store, "sha256:aaa", "acme")
    store.path("cv", "generated", INDEX_NAME).write_text("hand kept\n", encoding="utf-8")
    link_employer(store, "sha256:aaa", "acme")
    assert "(`acme`)" in _index(store)


def test_render_is_deterministic_and_a_noop_write_changes_nothing(
    store: ProfileStore, master: CVMaster
) -> None:
    generate(store, master, offer_id="sha256:bbb", advert="x")
    generate(store, master, offer_id="sha256:aaa", advert="x")
    first = render_index(store)
    assert first == render_index(store)
    assert first.index("sha256:aaa") < first.index("sha256:bbb")
    path = refresh_index(store)
    before = path.stat().st_mtime_ns
    refresh_index(store)
    assert path.stat().st_mtime_ns == before


def test_a_hand_kept_index_is_detected_as_missing_versions(
    store: ProfileStore, master: CVMaster
) -> None:
    generate(store, master, offer_id="sha256:aaa", advert="x")
    store.path("cv", "generated", INDEX_NAME).write_text("# mine\n", encoding="utf-8")
    assert missing_from_index(store) == ["sha256:aaa/v1"]


def test_a_version_without_a_manifest_is_listed_not_dropped(
    store: ProfileStore, master: CVMaster
) -> None:
    generate(store, master, offer_id="sha256:aaa", advert="x")
    store.path("cv", "generated", "sha256:aaa", "v2").mkdir()
    assert "v2 (no manifest)" in render_index(store)


def test_the_metric_can_read_above_zero() -> None:
    measured = generated_index.measure()
    assert measured["generated_versions_missing_from_the_index"] == 0
    assert measured["constructed_skipping_write_missing"] >= 1
    assert measured["constructed_hand_kept_index_missing"] >= 1
    assert generated_index.gate_passes(measured)
    assert not generated_index.gate_passes({**measured, "cases_measured": 1})
    assert not generated_index.gate_passes(
        {**measured, "generated_versions_missing_from_the_index": 1}
    )


def _calls(func: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            target = node.func
            names.add(
                target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
            )
    return names


def _strings(func: ast.AST) -> set[str]:
    return {
        node.value
        for node in ast.walk(func)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    } | {node.id for node in ast.walk(func) if isinstance(node, ast.Name)}


def test_every_write_path_into_cv_generated_calls_refresh_index() -> None:
    """A function that creates a version, an employer link or a send folder must
    end in `refresh_index`; found by AST over every module, not from a list."""
    writers: list[str] = []
    for path in sorted(SRC.glob("*.py")):
        if path.stem == "generated_index":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for func in ast.walk(tree):
            if not isinstance(func, ast.FunctionDef):
                continue
            calls, names = _calls(func), _strings(func)
            under = "generated" in names
            makes_version = under and "mkdir" in calls and "manifest.json" in names
            makes_link = under and "symlink_to" in calls
            makes_send = "SEND_RECORD" in names and "_atomic_write_json" in calls
            if makes_version or makes_link or makes_send:
                writers.append(f"{path.stem}.{func.name}")
                assert "refresh_index" in calls, f"{path.stem}.{func.name} skips the index"
    assert {"generate.generate", "generate.link_employer", "approval.stage_send"} <= set(writers)
