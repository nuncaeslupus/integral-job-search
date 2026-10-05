"""T192: the digest of a candidate's other generated documents, and the skill that runs it."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import pytest

from integral import prior_documents as pd
from integral.application_authorship import TRACE_FILE
from integral.approval import PersonalDetails, prepare
from integral.cv_store import CVMaster, add_conversation_entry
from integral.generate import Claim, Manifest, generate
from integral.identity import ProfileStore, create_profile
from integral.offers import Offer, compute_offer_id, save_offer
from integral.profile import EvidenceLog, rebuild

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
    letter: str | None = None,
    cv: str | None = "## Summary\n",
    manifest: str | None = None,
) -> Path:
    """A version whose documents the manifest fully traces, unless `letter` says otherwise."""
    where = store.path("cv", "generated", offer_id, f"v{number}")
    where.mkdir(parents=True)
    claims = tuple(
        Claim(document="letter.md", text=t, section="episodes", entry_index=i)
        for i, t in enumerate(episodes)
    )
    body = Manifest(offer_id=offer_id, version=number, claims=claims).model_dump_json()
    (where / "manifest.json").write_text(body if manifest is None else manifest, encoding="utf-8")
    text = letter if letter is not None else "\n".join(["Dear hiring team,", *episodes]) + "\n"
    (where / "letter.md").write_text(text, encoding="utf-8")
    if cv is not None:
        (where / "cv.md").write_text(cv, encoding="utf-8")
    return where


def by_id(result: pd.Digest) -> dict[str, pd.OfferDigest]:
    return {o.offer_id: o for o in result.offers}


def test_no_generated_documents_is_not_an_error(store: ProfileStore) -> None:
    result = pd.digest(store)
    assert result.offers == () and result.skipped == ()
    assert "nothing to reuse" in pd.render(result)


def test_every_offer_is_digested_with_names_versions_documents_and_episodes(
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
    assert g.documents == ((1, ("cv.md", "letter.md")), (2, ("cv.md", "letter.md")))
    assert [(e.text, e.story_id) for e in g.cited_episodes] == [
        (STORY_A, "e1"),
        (STORY_B, "e2"),
    ]  # an episode disclosed twice counts once
    assert found[COHERE].cited_episodes == ()
    assert g.undetermined == () and found[COHERE].undetermined == ()
    text = pd.render(result)
    assert "story-bank episodes cited: 2" in text and "story-bank episodes cited: 0" in text
    assert "Grafana — Backend engineer" in text and "v1: cv.md, letter.md" in text
    assert "UNDETERMINED" not in text


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


def test_an_episode_is_listed_without_any_story_row_and_a_row_only_annotates(
    store: ProfileStore,
) -> None:
    stories(store, {"id": "e1", "text": STORY_A})
    offer(store, GRAFANA, "Grafana", "Backend")
    version(store, GRAFANA, 1, episodes=(STORY_B, f"  {STORY_A}  "))
    found = by_id(pd.digest(store))[GRAFANA]
    # B is listed with no id; A resolves through its stripped text.
    assert [(e.text, e.story_id) for e in found.cited_episodes] == [
        (STORY_A, "e1"),
        (STORY_B, None),
    ]


def test_a_story_row_resolves_through_the_approval_normalisation(store: ProfileStore) -> None:
    nfd = unicodedata.normalize("NFD", "Reduï el cost un 40% sense perdre qualitat.")
    stories(store, {"id": "e9", "text": nfd})
    offer(store, GRAFANA, "Grafana", "Backend")
    version(store, GRAFANA, 1, episodes=("Reduï  el cost un 40% sense perdre qualitat.",))
    (episode,) = by_id(pd.digest(store))[GRAFANA].cited_episodes
    assert episode.story_id == "e9"


def test_an_approved_episode_not_in_the_manifest_is_still_listed(store: ProfileStore) -> None:
    offer(store, GRAFANA, "Grafana", "Backend")
    where = version(store, GRAFANA, 1)
    approvals = {
        "offer_id": GRAFANA,
        "version": 1,
        "episodes": [{"offer_id": GRAFANA, "version": 1, "text": STORY_B}],
    }
    (where / "approvals.json").write_text(json.dumps(approvals), encoding="utf-8")
    (episode,) = by_id(pd.digest(store))[GRAFANA].cited_episodes
    assert episode.text == STORY_B


def test_a_malformed_approvals_file_skips_the_version_by_name(store: ProfileStore) -> None:
    offer(store, GRAFANA, "Grafana", "Backend")
    version(store, GRAFANA, 1).joinpath("approvals.json").write_text("{", encoding="utf-8")
    result = pd.digest(store)
    assert result.offers == () and [s.where for s in result.skipped] == [
        f"cv/generated/{GRAFANA}/v1"
    ]


def test_an_episode_built_through_the_real_flow_is_listed(store: ProfileStore) -> None:
    """The master episode and the story row are different stores; neither text is copied here."""
    master = add_conversation_entry(
        store,
        CVMaster(),
        "experience",
        {"title": "Backend developer", "organisation": "Cintra", "start": "2021", "end": "2025"},
        said="I was a backend developer at Cintra, 2021 to 2025.",
        recorded_at="2026-01-01T09:00:00+00:00",
    )
    master = add_conversation_entry(
        store,
        master,
        "episodes",
        {"kind": "achievement", "text": STORY_A},
        said="Once I cut the billing run from six hours to forty minutes.",
        recorded_at="2026-01-01T09:05:00+00:00",
    )
    # The step-3 row the story bank derives from is the candidate's own telling.
    EvidenceLog(store).append(
        recorded_at="2026-01-01T09:06:00+00:00",
        step="history",
        kind="episode",
        text="Once I cut the billing run from six hours to forty minutes.",
        source="conversation",
    )
    store.write_text(rebuild(store)["stories.jsonl"], "profile", "stories.jsonl")
    offer(store, GRAFANA, "Grafana", "Backend")
    prepare(
        store,
        master,
        offer_id=GRAFANA,
        advert="backend postgres",
        recipient="hiring team",
        details=PersonalDetails(full_name="Vero"),
        approved_episodes=(0,),
    )
    result = pd.digest(store)
    assert result.skipped == () and result.stories_read == 1
    (episode,) = by_id(result)[GRAFANA].cited_episodes
    assert episode.text == STORY_A
    assert episode.story_id is None  # the two stores do not agree, and the episode is listed anyway
    assert "story-bank episodes cited: 1" in pd.render(result)


def test_documents_the_manifest_does_not_trace_make_the_episodes_undetermined(
    store: ProfileStore,
) -> None:
    offer(store, GRAFANA, "Grafana", "Backend")
    where = version(store, GRAFANA, 1)
    (where / "carta.md").write_text(f"Estimats,\n\n{STORY_A}\n", encoding="utf-8")
    found = by_id(pd.digest(store))[GRAFANA]
    assert found.cited_episodes == ()
    assert found.undetermined == (f"cv/generated/{GRAFANA}/v1/carta.md",)
    text = pd.render(pd.digest(store))
    assert "story-bank episodes cited: 0 listed, UNDETERMINED" in text
    assert f"{GRAFANA}/v1/carta.md" in text


def test_every_markdown_document_but_the_trace_is_read(store: ProfileStore) -> None:
    offer(store, GRAFANA, "Grafana", "Backend")
    where = version(store, GRAFANA, 1)
    (where / "carta.md").write_text("## How I work\n", encoding="utf-8")
    (where / "carta_en.md").write_text("## Cómo trabajo\n", encoding="utf-8")
    (where / TRACE_FILE).write_text("## Authorship\n| 1 | candidate |\n", encoding="utf-8")
    found = by_id(pd.digest(store))[GRAFANA]
    assert found.sections == ("Cómo trabajo", "How I work")  # no "Authorship"
    assert found.documents == ((1, ("carta.md", "carta_en.md", "cv.md", "letter.md")),)


def test_a_version_holding_only_the_trace_file_is_skipped(store: ProfileStore) -> None:
    offer(store, GRAFANA, "Grafana", "Backend")
    where = version(store, GRAFANA, 1, cv=None)
    (where / "letter.md").unlink()
    (where / TRACE_FILE).write_text("## Authorship\n", encoding="utf-8")
    result = pd.digest(store)
    assert result.offers == () and result.skipped[0].where == f"cv/generated/{GRAFANA}/v1"


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


def test_malformed_stories_are_skipped_by_name_and_annotate_nothing(store: ProfileStore) -> None:
    offer(store, GRAFANA, "Grafana", "Backend")
    version(store, GRAFANA, 1, episodes=(STORY_A,))
    stories(store, {"id": "e1", "text": STORY_A}, '{"id": 1}', "[]")
    result = pd.digest(store)
    assert [e.story_id for e in by_id(result)[GRAFANA].cited_episodes] == ["e1"]
    assert [s.where for s in result.skipped] == [
        "profile/stories.jsonl row 2",
        "profile/stories.jsonl row 3",
    ]
    stories(store, "{broken")
    result = pd.digest(store)
    # The episode is still listed; only its id is lost, and the file is named.
    assert [e.story_id for e in by_id(result)[GRAFANA].cited_episodes] == [None]
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


RULE = (
    "Propose reuse; never apply it silently.\n"
    "A story-bank episode carried over from another offer's documents needs a fresh per-use "
    "approval for this posting and company; the earlier approval does not travel.\n"
    "An episode count the digest marks UNDETERMINED is not zero: read the named documents.\n"
)
BULLETS = [
    "- Where an earlier offer's framing, section or phrasing looks good, say which one and why, "
    "and propose carrying it over **adapted to this posting and this company** — never pasted. "
    "The candidate decides. Every claim in the new document still traces to a store entry, and "
    'the letter is still the candidate\'s own words (see "The letter is an edit").',
    "- The digest ends with a `SKIPPED` list and **exit 1** when any manifest, document, offer "
    "record or story row could not be read. Say which items, by name, before relying on the "
    "rest; never treat an unlisted offer as one with nothing to reuse.",
    "- No generated documents yet is a normal first run: say nothing about it and draft.",
]
SECTION_BODY = (
    "\n"
    "Run the digest **before drafting any CV or letter**, so work the candidate has "
    "already polished for another offer is weighed rather than rebuilt from zero:\n"
    "\n"
    "```bash\n"
    "python -m integral.prior_documents --id <handle> [--input-dir <profiles-root>]\n"
    "```\n"
    "\n"
    "It walks every `cv/generated/<offer_id>/v<N>/manifest.json` and the document "
    "text beside it, for **all** of the candidate's offers, and prints per offer: "
    "company and title, how many versions exist, which documents each holds and any "
    'other file it did not read, the **sections beyond the standard set** (a "How I '
    'work" block, say), and the **story-bank episodes cited**. A script does this so '
    "the session does not re-read N full documents.\n"
    "\n"
    "The reuse rule, stated once and pinned by its own test, so change it only by "
    "changing the rule:\n"
    "\n"
    "```text\n"
    "Propose reuse; never apply it silently.\n"
    "A story-bank episode carried over from another offer's documents needs a fresh "
    "per-use approval for this posting and company; the earlier approval does not "
    "travel.\n"
    "An episode count the digest marks UNDETERMINED is not zero: read the named "
    "documents.\n"
    "```\n"
    "\n"
    "- Where an earlier offer's framing, section or phrasing looks good, say which "
    "one and why, and propose carrying it over **adapted to this posting and this "
    "company** — never pasted. The candidate decides. Every claim in the new "
    "document still traces to a store entry, and the letter is still the candidate's "
    'own words (see "The letter is an edit").\n'
    "- The digest ends with a `SKIPPED` list and **exit 1** when any manifest, "
    "document, offer record or story row could not be read. Say which items, by "
    "name, before relying on the rest; never treat an unlisted offer as one with "
    "nothing to reuse.\n"
    "- No generated documents yet is a normal first run: say nothing about it and "
    "draft.\n"
    ""
)
NEVER_BULLET = (
    "- Never include a story-bank episode without per-use approval — recounting a failure "
    "to the tool was never consent to send it to a company."
)


def test_skill_carries_the_carry_over_rule_verbatim_in_its_fence() -> None:
    fence = re.search(r"The reuse rule, stated once.*?```text\n(.*?)```", _section(), re.S)
    assert fence, "the digest section has no verbatim rule fence"
    assert fence.group(1) == RULE
    # The rule is stated once, in the fence. The bullets are pinned too, so a bullet cannot
    # restate it in other words (a keyword scan would be a proxy: "need not ask again").
    bullets = [line for line in _section().splitlines() if line.startswith("- ")]
    assert bullets == BULLETS


def test_the_original_never_bullet_still_sits_in_the_never_list() -> None:
    found = re.search(r"\*\*Never:\*\*\n\n(.*?)\n\n## ", _skill(), re.S)
    assert found, "the skill has no Never list"
    assert NEVER_BULLET in found.group(1).splitlines()


def test_the_whole_digest_section_is_pinned_verbatim() -> None:
    """Not only its fence and bullets: a paragraph appended to the section is pinned too."""
    assert _section() == SECTION_BODY


# --- documents the manifest does not trace ---------------------------------------


def test_a_real_generated_version_with_one_untraced_line_is_undetermined(
    store: ProfileStore,
) -> None:
    master = CVMaster.model_validate_json(MASTER.read_text(encoding="utf-8"))
    offer(store, GRAFANA, "Grafana", "Backend")
    generate(store, master, offer_id=GRAFANA, advert="python postgres")
    assert by_id(pd.digest(store))[GRAFANA].undetermined == ()  # fully traced as written
    letter = store.path("cv", "generated", GRAFANA, "v1", "letter.md")
    letter.write_text(letter.read_text(encoding="utf-8") + "One more thing I care about.\n")
    assert by_id(pd.digest(store))[GRAFANA].undetermined == (
        f"cv/generated/{GRAFANA}/v1/letter.md",
    )


def test_a_line_traced_only_by_a_claim_for_another_document_is_undetermined(
    store: ProfileStore,
) -> None:
    offer(store, GRAFANA, "Grafana", "Backend")
    where = version(store, GRAFANA, 1, letter="Dear hiring team,\n" + STORY_A + "\n")
    claim = Claim(document="cv.md", text=STORY_A, section="episodes", entry_index=0)
    body = Manifest(offer_id=GRAFANA, version=1, claims=(claim,)).model_dump_json()
    (where / "manifest.json").write_text(body, encoding="utf-8")
    found = by_id(pd.digest(store))[GRAFANA]
    assert found.undetermined == (f"cv/generated/{GRAFANA}/v1/letter.md",)
    assert "UNDETERMINED" in pd.render(pd.digest(store))


def test_an_approvals_file_naming_another_version_skips_it_by_name(store: ProfileStore) -> None:
    offer(store, GRAFANA, "Grafana", "Backend")
    where = version(store, GRAFANA, 1)
    other = {"offer_id": GRAFANA, "version": 2, "episodes": []}
    (where / "approvals.json").write_text(json.dumps(other), encoding="utf-8")
    result = pd.digest(store)
    assert result.offers == ()
    assert [s.where for s in result.skipped] == [f"cv/generated/{GRAFANA}/v1"]
    assert "v2" in result.skipped[0].reason


def test_files_that_are_not_read_are_named_not_hidden(store: ProfileStore) -> None:
    offer(store, GRAFANA, "Grafana", "Backend")
    where = version(store, GRAFANA, 1)
    for name in ("carta.txt", "cv.MD", "cv.html"):
        (where / name).write_text("x", encoding="utf-8")
    (where / "payload.json").write_text("{}", encoding="utf-8")  # a machine file, not a document
    found = by_id(pd.digest(store))[GRAFANA]
    assert found.unread_files == ((1, ("carta.txt", "cv.MD", "cv.html")),)
    assert "v1 also holds, not read: carta.txt, cv.MD, cv.html" in pd.render(pd.digest(store))


# --- what the digest must survive and say -----------------------------------------


def test_a_symlinked_offer_or_version_directory_is_refused_by_name(
    store: ProfileStore, tmp_path: Path
) -> None:
    offer(store, GRAFANA, "Grafana", "Backend")
    version(store, GRAFANA, 1)
    root = store.path("cv", "generated")
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (root / COHERE).symlink_to(outside, target_is_directory=True)
    (root / GRAFANA / "v2").symlink_to(root / GRAFANA / "v1", target_is_directory=True)
    result = pd.digest(store)
    assert {s.where: s.reason for s in result.skipped} == {
        f"cv/generated/{COHERE}": "not an offer directory",
        f"cv/generated/{GRAFANA}/v2": "not a v<N> version",
    }
    assert by_id(result)[GRAFANA].versions == (1,)


@pytest.mark.parametrize("target", ["manifest.json", "letter.md"])
def test_a_symlink_out_of_the_tree_is_reported_not_a_crash(
    store: ProfileStore, tmp_path: Path, target: str
) -> None:
    offer(store, GRAFANA, "Grafana", "Backend")
    where = version(store, GRAFANA, 1)
    secret = tmp_path / "secret.txt"
    secret.write_text("{}", encoding="utf-8")
    (where / target).unlink()
    (where / target).symlink_to(secret)
    result = pd.digest(store)
    assert result.offers == ()
    assert [s.reason.split(":")[0] for s in result.skipped] == ["ProfileLeak"]


def test_a_symlinked_stories_file_is_reported_not_a_crash(
    store: ProfileStore, tmp_path: Path
) -> None:
    outside = tmp_path / "stories.jsonl"
    outside.write_text("{}\n", encoding="utf-8")
    store.path("profile").mkdir(parents=True, exist_ok=True)
    (store.path("profile") / "stories.jsonl").symlink_to(outside)
    result = pd.digest(store)
    assert [s.where for s in result.skipped] == ["profile/stories.jsonl"]


def test_a_recursion_error_reading_a_manifest_is_reported(
    store: ProfileStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    offer(store, GRAFANA, "Grafana", "Backend")
    version(store, GRAFANA, 1)

    def boom(*_: object, **__: object) -> None:
        raise RecursionError("too deep")

    monkeypatch.setattr(Manifest, "model_validate_json", boom)
    result = pd.digest(store)
    assert result.offers == ()
    assert [s.where for s in result.skipped] == [f"cv/generated/{GRAFANA}/v1/manifest.json"]
    assert "RecursionError" in result.skipped[0].reason


def test_an_empty_offer_directory_and_a_file_in_place_of_generated_are_reported(
    store: ProfileStore,
) -> None:
    root = store.path("cv", "generated")
    (root / GRAFANA).mkdir(parents=True)
    result = pd.digest(store)
    assert [(s.where, s.reason) for s in result.skipped] == [
        (f"cv/generated/{GRAFANA}", "empty offer directory")
    ]
    (root / GRAFANA).rmdir()
    root.rmdir()
    root.write_text("not a directory", encoding="utf-8")
    result = pd.digest(store)
    assert [(s.where, s.reason) for s in result.skipped] == [("cv/generated", "not a directory")]
