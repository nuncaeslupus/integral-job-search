"""T343: cv/generated/INDEX.md is regenerated from the tree on every write path."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from integral import generated_index
from integral.cv_store import CVMaster
from integral.generate import DEFAULT_FIXTURE_MASTER, generate, link_employer
from integral.generated_index import (
    INDEX_NAME,
    delivery_with_send,
    index_differs,
    refresh_index,
    render_index,
)
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
    assert index_differs(store) == 0


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


def test_a_hand_kept_index_is_detected(store: ProfileStore, master: CVMaster) -> None:
    generate(store, master, offer_id="sha256:aaa", advert="x")
    store.path("cv", "generated", INDEX_NAME).write_text("# mine\n", encoding="utf-8")
    assert index_differs(store) == 1


def _edit(store: ProfileStore, old: str, new: str) -> None:
    path = store.path("cv", "generated", INDEX_NAME)
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_a_wrong_link_or_send_path_or_phantom_is_detected(
    store: ProfileStore, master: CVMaster
) -> None:
    """F1/F2: the file is compared with the render, byte for byte, both ways."""
    for offer in ("sha256:aaa", "sha256:bbb"):
        generate(store, master, offer_id=offer, advert="x")
        generate(store, master, offer_id=offer, advert="x")
    link_employer(store, "sha256:aaa", "acme")
    assert index_differs(store) == 0
    good = _index(store)
    for old, new in (
        ("(`acme`)", "(`globex`)"),
        ("v1, v2", "v1, v2, v9"),
        ("| - |\n", "| `sha256:aaa/v2/send` |\n"),
    ):
        _edit(store, old, new)
        assert index_differs(store) == 1, (old, new)
        store.path("cv", "generated", INDEX_NAME).write_text(good, encoding="utf-8")
    store.path("cv", "generated", INDEX_NAME).write_text(
        good + "| - | - | `sha256:zzz` | v1 | - |\n", encoding="utf-8"
    )
    assert index_differs(store) == 1


def test_a_stored_offer_and_a_real_stage_send_fill_every_column(store: ProfileStore) -> None:
    """F3/F4/F5: employer, role and send path come from the offer and the send folder,
    and the index is final once stage_send returns (a pipe in the company is escaped)."""
    _master, offer_id, version = delivery_with_send(store)
    text = _index(store)
    assert "| Acme \\| Co | Data Engineer |" in text
    assert f"`{offer_id}/v{version}/send`" in text
    assert index_differs(store) == 0


def test_an_idempotent_stage_send_repairs_the_index(store: ProfileStore) -> None:
    """F7: the early return over an intact send/ refreshes too."""
    from integral.approval import payload_digest, read_payload, stage_send

    built, offer_id, version = delivery_with_send(store)
    store.path("cv", "generated", INDEX_NAME).write_text("hand kept\n", encoding="utf-8")
    confirms = payload_digest(read_payload(store, offer_id, version))
    stage_send(
        store, built, offer_id, version, confirms=confirms, **generated_index._FIXTURE_ENGINE
    )
    assert index_differs(store) == 0


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
    assert (
        measured["constructed_hand_edits_detected"] == measured["constructed_hand_edits_tried"] >= 4
    )
    assert measured["cases_measured"] >= 8
    assert generated_index.gate_passes(measured)
    assert not generated_index.gate_passes({**measured, "cases_measured": 1})
    assert not generated_index.gate_passes({**measured, "constructed_hand_edits_detected": 3})
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
