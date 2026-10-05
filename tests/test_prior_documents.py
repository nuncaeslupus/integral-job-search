"""T192: the digest of a candidate's other generated documents, and the skill that runs it."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from integral import prior_documents as pd
from integral.cv_store import CVMaster
from integral.generate import Claim, Manifest, generate
from integral.identity import ProfileStore, create_profile
from integral.offers import Offer, compute_offer_id, save_offer

SKILL = Path(__file__).resolve().parent.parent / ".claude/skills/step-11-application/SKILL.md"
MASTER = Path(__file__).resolve().parent / "fixtures" / "generation" / "master.json"

STORY_A = "Cut the nightly billing run from six hours to forty minutes."
STORY_B = "Shipped a schema change without a backfill and left invoicing wrong."
GRAFANA = compute_offer_id("grafana advert")
COHERE = compute_offer_id("cohere advert")


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    root = tmp_path / "profiles"
    identity = create_profile(root, "Vero", handle="vero", language="ca")
    return ProfileStore(root, identity.handle)


def stories(store: ProfileStore, *rows: dict[str, str] | str) -> None:
    lines = [r if isinstance(r, str) else json.dumps(r) for r in rows]
    store.write_text("\n".join(lines) + "\n", "profile", "stories.jsonl")


def offer(store: ProfileStore, offer_id: str, company: str, title: str) -> None:
    save_offer(store, Offer(id=offer_id, source="manual", company=company, title=title, text="x"))


def version(
    store: ProfileStore,
    offer_id: str,
    number: int,
    *,
    episodes: tuple[str, ...] = (),
    letter: str = "Dear team,\n",
    cv: str | None = "## Summary\nx\n",
    manifest: str | None = None,
) -> Path:
    where = store.path("cv", "generated", offer_id, f"v{number}")
    where.mkdir(parents=True)
    claims = tuple(
        Claim(document="letter.md", text=t, section="episodes", entry_index=i)
        for i, t in enumerate(episodes)
    )
    body = Manifest(offer_id=offer_id, version=number, claims=claims).model_dump_json()
    (where / "manifest.json").write_text(body if manifest is None else manifest, encoding="utf-8")
    (where / "letter.md").write_text(letter, encoding="utf-8")
    if cv is not None:
        (where / "cv.md").write_text(cv, encoding="utf-8")
    return where


def by_id(result: pd.Digest) -> dict[str, pd.OfferDigest]:
    return {o.offer_id: o for o in result.offers}


def test_no_generated_documents_is_not_an_error(store: ProfileStore) -> None:
    result = pd.digest(store)
    assert result.offers == () and result.skipped == ()
    assert "nothing to reuse" in pd.render(result)


def test_every_offer_is_digested_with_names_versions_and_cited_stories(
    store: ProfileStore,
) -> None:
    stories(store, {"id": "e1", "text": STORY_A}, {"id": "e2", "text": STORY_B})
    offer(store, GRAFANA, "Grafana", "Backend engineer")
    offer(store, COHERE, "Cohere", "Platform engineer")
    version(store, GRAFANA, 1, episodes=(STORY_A,))
    version(store, GRAFANA, 2, episodes=(STORY_A, STORY_B))
    version(store, COHERE, 1)
    result = pd.digest(store)
    assert result.skipped == ()
    found = by_id(result)
    assert set(found) == {GRAFANA, COHERE}
    g = found[GRAFANA]
    assert (g.company, g.title, g.versions) == ("Grafana", "Backend engineer", (1, 2))
    assert [i for i, _ in g.cited_stories] == ["e1", "e2"]  # a story cited twice counts once
    assert found[COHERE].cited_stories == ()
    text = pd.render(result)
    assert "stories cited: 2" in text and "stories cited: 0" in text
    assert "Grafana — Backend engineer" in text


def test_a_section_beyond_the_generated_set_is_distinguishing(store: ProfileStore) -> None:
    offer(store, GRAFANA, "Grafana", "Backend")
    version(
        store,
        GRAFANA,
        1,
        cv="# Vero\n## Summary\nx\n## How I work\ny\n```\n## Not a heading\n```\n",
        letter="### Why Grafana\nz\n",
    )
    assert by_id(pd.digest(store))[GRAFANA].sections == ("How I work", "Why Grafana")


def test_an_episode_claim_matching_no_story_is_shown_not_dropped(store: ProfileStore) -> None:
    stories(store, {"id": "e1", "text": STORY_A})
    offer(store, GRAFANA, "Grafana", "Backend")
    version(store, GRAFANA, 1, episodes=(STORY_B,))
    found = by_id(pd.digest(store))[GRAFANA]
    assert found.cited_stories == () and found.unmatched_episode_claims == (STORY_B,)
    assert "episode claims matching no story: 1" in pd.render(pd.digest(store))


@pytest.mark.parametrize(
    ("manifest", "reason"),
    [
        ("{nope", "ValidationError"),
        ("", "ValidationError"),
        ('{"offer_id": 3}', "ValidationError"),
        (Manifest(offer_id="other", version=1).model_dump_json(), "not this directory"),
        (Manifest(offer_id=GRAFANA, version=7).model_dump_json(), "v7"),
    ],
)
def test_a_bad_manifest_is_skipped_by_name_and_the_cli_would_fail(
    store: ProfileStore, manifest: str, reason: str
) -> None:
    offer(store, GRAFANA, "Grafana", "Backend")
    offer(store, COHERE, "Cohere", "Platform")
    version(store, GRAFANA, 1, manifest=manifest)
    version(store, COHERE, 1)  # the good one is still digested
    result = pd.digest(store)
    assert [o.offer_id for o in result.offers] == [COHERE]
    assert [s.where for s in result.skipped] == [f"cv/generated/{GRAFANA}/v1/manifest.json"]
    assert reason in result.skipped[0].reason
    assert f"{GRAFANA}/v1/manifest.json" in pd.render(result)


def test_a_missing_manifest_is_skipped_by_name(store: ProfileStore) -> None:
    offer(store, GRAFANA, "Grafana", "Backend")
    version(store, GRAFANA, 1).joinpath("manifest.json").unlink()
    result = pd.digest(store)
    assert result.offers == ()
    assert [s.where for s in result.skipped] == [f"cv/generated/{GRAFANA}/v1/manifest.json"]


def test_a_version_with_no_document_text_is_skipped(store: ProfileStore) -> None:
    offer(store, GRAFANA, "Grafana", "Backend")
    where = version(store, GRAFANA, 1)
    where.joinpath("letter.md").unlink()
    where.joinpath("cv.md").unlink()
    result = pd.digest(store)
    assert result.offers == ()
    assert result.skipped[0].where == f"cv/generated/{GRAFANA}/v1"


def test_a_bad_version_does_not_hide_a_good_one_of_the_same_offer(store: ProfileStore) -> None:
    offer(store, GRAFANA, "Grafana", "Backend")
    version(store, GRAFANA, 1, manifest="{")
    version(store, GRAFANA, 2)
    result = pd.digest(store)
    assert by_id(result)[GRAFANA].versions == (2,)
    assert len(result.skipped) == 1


def test_strays_under_generated_are_reported_not_ignored(store: ProfileStore) -> None:
    offer(store, GRAFANA, "Grafana", "Backend")
    version(store, GRAFANA, 1)
    root = store.path("cv", "generated")
    (root / "notes.txt").write_text("x", encoding="utf-8")
    (root / GRAFANA / "draft").mkdir()
    (root / GRAFANA / "v0").mkdir()  # v0 is not a version
    found = {s.where for s in pd.digest(store).skipped}
    assert found == {
        "cv/generated/notes.txt",
        f"cv/generated/{GRAFANA}/draft",
        f"cv/generated/{GRAFANA}/v0",
    }


def test_an_unreadable_offer_record_is_named_but_the_documents_still_show(
    store: ProfileStore,
) -> None:
    version(store, GRAFANA, 1)  # no offers/<id>.json at all
    result = pd.digest(store)
    assert by_id(result)[GRAFANA].company is None
    assert [s.where for s in result.skipped] == [f"offers/{GRAFANA}.json"]


def test_malformed_stories_are_skipped_by_name_and_cite_nothing(store: ProfileStore) -> None:
    offer(store, GRAFANA, "Grafana", "Backend")
    version(store, GRAFANA, 1, episodes=(STORY_A,))
    stories(store, {"id": "e1", "text": STORY_A}, '{"id": 1}', "[]")
    result = pd.digest(store)
    assert [i for i, _ in by_id(result)[GRAFANA].cited_stories] == ["e1"]
    assert [s.where for s in result.skipped] == [
        "profile/stories.jsonl row 2",
        "profile/stories.jsonl row 3",
    ]
    stories(store, "{broken")
    result = pd.digest(store)
    assert by_id(result)[GRAFANA].cited_stories == ()
    assert [s.where for s in result.skipped] == ["profile/stories.jsonl"]


def test_it_reads_what_generate_really_writes(store: ProfileStore) -> None:
    master = CVMaster.model_validate_json(MASTER.read_text(encoding="utf-8"))
    offer(store, GRAFANA, "Grafana", "Backend")
    generate(store, master, offer_id=GRAFANA, advert="python postgres")
    generate(store, master, offer_id=GRAFANA, advert="python postgres")
    result = pd.digest(store)
    assert result.skipped == ()
    assert by_id(result)[GRAFANA].versions == (1, 2)
    assert by_id(result)[GRAFANA].sections == ()  # generate's own headings are the standard set


def test_the_output_is_deterministic(store: ProfileStore) -> None:
    stories(store, {"id": "e1", "text": STORY_A})
    for oid, name in ((COHERE, "Cohere"), (GRAFANA, "Grafana")):
        offer(store, oid, name, "x")
        version(store, oid, 1, episodes=(STORY_A,))
    assert pd.render(pd.digest(store)) == pd.render(pd.digest(store))
    assert [o.offer_id for o in pd.digest(store).offers] == sorted([COHERE, GRAFANA])


# --- the CLI ---------------------------------------------------------------------


def test_cli_exits_zero_when_clean_and_one_when_anything_was_skipped(
    store: ProfileStore, capsys: pytest.CaptureFixture[str]
) -> None:
    offer(store, GRAFANA, "Grafana", "Backend")
    version(store, GRAFANA, 1)
    argv = ["--id", store.handle, "--input-dir", str(store.root), "--dev"]
    assert pd._cli(argv) == 0
    assert "Grafana" in capsys.readouterr().out
    version(store, COHERE, 1, manifest="{")
    assert pd._cli([*argv, "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["skipped"][0]["where"] == f"cv/generated/{COHERE}/v1/manifest.json"
    assert [o["offer_id"] for o in payload["offers"]] == [GRAFANA]


def test_cli_refuses_an_unknown_handle(store: ProfileStore) -> None:
    assert pd._cli(["--id", "nobody", "--input-dir", str(store.root), "--dev"]) == 2


# --- the skill runs the digest, and keeps the approval rule ----------------------

_SECTION = r"## Before drafting — look at what already exists\n(.*?)\n## "


def _skill() -> str:
    return SKILL.read_text(encoding="utf-8")


def _section() -> str:
    found = re.search(_SECTION, _skill(), re.S)
    assert found, "the skill has no section for the digest"
    return found.group(1)


def test_skill_runs_the_digest_before_drafting() -> None:
    body = _section()
    assert "python -m integral.prior_documents --id <handle>" in body
    assert "before drafting any CV or letter" in body
    assert "adapted to this posting and this company" in body
    assert "SKIPPED" in body and "exit 1" in body
    # It sits before the protocol that drafts, not after it.
    assert _skill().index("## Before drafting") < _skill().index("## Protocol")


def test_skill_keeps_per_use_approval_for_carried_over_episodes() -> None:
    assert "Never include a story-bank episode without per-use approval" in _skill()
    body = _section()
    assert "per-use approval" in body
    assert "another offer's documents" in body
    # The names the code prints are the names the skill uses.
    assert "stories cited" in body and "sections beyond the standard set" in body
