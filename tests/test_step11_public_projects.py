"""T313 — step 11 surfaces a candidate's public project only as an approved episode.

Decision: no new mechanism. A public project in `cv/master.json` is an `episode`
with the link in `text`; the existing per-use approval is the only route to an
employer, and the link must survive it byte for byte. Metric:
`candidate_public_projects_never_linked_at_step_11`. Step 3's evidence-log episodes
do not reach `cv/master.json` yet; that path is a follow-up, not covered here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from integral.approval import PersonalDetails, prepare
from integral.claim_trace import FIXTURE_SOURCE, seed_fixture_source
from integral.cv_store import CVMaster, Episode, Skill, write_master
from integral.identity import ProfileStore, create_profile

SKILL = Path(".claude/skills/step-11-application/SKILL.md")
LINK = "https://github.com/ada/ledger-sync"
PROJECT = f"Built ledger-sync, an open-source reconciliation tool in Python: {LINK}"
OTHER = "Cut the nightly billing run from six hours to forty minutes by rewriting reconciliation."
ADVERT = "We are hiring a data engineer. You will own a PostgreSQL estate."
DETAILS = PersonalDetails(
    full_name="Ada Lovelace",
    email="ada@example.invalid",
    phone="+34 600 111 222",
    postal_address="3 Carrer Nou, 17001 Girona",
    date_of_birth="1815-12-10",
)

RULE = (
    "A public project is offered, never added: when the advert is in software or data "
    "and the story bank holds an episode whose text carries a link, propose it for this "
    "posting and company.\n"
    "It goes in the letter only as an approved episode, with the link exactly as the "
    "candidate gave it; a declined or unanswered proposal sends nothing."
)


@pytest.fixture
def setup(tmp_path: Path) -> tuple[ProfileStore, CVMaster]:
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", handle="ada", language="en")
    store = ProfileStore(root, identity.handle)
    master = CVMaster(
        skills=(Skill(provenance=(FIXTURE_SOURCE,), name="PostgreSQL", level="strong"),),
        episodes=(
            Episode(provenance=(FIXTURE_SOURCE,), kind="achievement", text=PROJECT),
            Episode(provenance=(FIXTURE_SOURCE,), kind="achievement", text=OTHER),
        ),
    )
    write_master(store, master)
    seed_fixture_source(store, master)
    return store, master


def _documents(store: ProfileStore, offer_id: str, version: int) -> str:
    where = store.path("cv", "generated", offer_id, f"v{version}")
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(where.glob("*.md")))


def _prepare(store: ProfileStore, master: CVMaster, approved: tuple[int, ...]) -> str:
    payload = prepare(
        store,
        master,
        offer_id="girona-1",
        advert=ADVERT,
        recipient="hiring team",
        details=DETAILS,
        asks=("PostgreSQL",),
        approved_episodes=approved,
    )
    return _documents(store, payload.offer_id, payload.version)


def test_an_approved_public_project_reaches_the_letter_with_its_link_intact(
    setup: tuple[ProfileStore, CVMaster],
) -> None:
    store, master = setup
    written = _prepare(store, master, approved=(0,))
    assert LINK in written
    assert PROJECT in written


def test_an_unapproved_public_project_is_never_written(
    setup: tuple[ProfileStore, CVMaster],
) -> None:
    store, master = setup
    written = _prepare(store, master, approved=(1,))
    assert LINK not in written
    assert "ledger-sync" not in written


def test_the_public_project_rule_is_stated_in_the_skill() -> None:
    text = SKILL.read_text(encoding="utf-8")
    section = text.split("## Public projects", 1)[1].split("\n## ", 1)[0]
    assert RULE in section
