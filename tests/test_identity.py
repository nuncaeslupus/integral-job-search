"""S3 — the per-user tree, handle resolution, and the leak guard.

The gate is `cross_user_leaks == 0`, and the point of these tests is that the
number is produced by *attempts that were refused* rather than by a promise.
Three properties carry the task:

* an operation cannot touch another person's tree, by any of the routes a
  caller actually takes — a relative climb, an absolute path, a symlink;
* one existing profile is offered for confirmation and never selected silently,
  which is process spec §6.1 case 2 and the reason the append-only log does not
  get somebody else's history in it;
* correct operation never trips the hook — a guard that blocks the tool's own
  opening move gets switched off, and then it guards nothing.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from integral.identity import (
    ACTIVE_FILE,
    MINIMUM_PROBES,
    ROSTER_FILE,
    Decision,
    Identity,
    IdentityError,
    ProfileLeak,
    ProfileStore,
    create_profile,
    derive_handle,
    guard_decision,
    guard_tool_call,
    hook_main,
    list_identities,
    paths_in_tool_call,
    probe_leaks,
    read_active_handle,
    resolve_handle,
    write_active_handle,
    write_evidence,
)

FIXED = datetime(2026, 8, 18, 9, 0, tzinfo=UTC)


@pytest.fixture
def two_profiles(tmp_path: Path) -> tuple[Path, Identity, Identity]:
    root = tmp_path / "profiles"
    first = create_profile(root, "Ada Lovelace", language="en", now=FIXED)
    second = create_profile(root, "Núria Puig", language="ca", now=FIXED)
    ProfileStore(root, second.handle).write_text("second's secret\n", "profile", "evidence.jsonl")
    return root, first, second


# --- the tree cannot be crossed -------------------------------------------


def test_an_operation_cannot_touch_another_users_tree(
    two_profiles: tuple[Path, Identity, Identity],
) -> None:
    root, first, second = two_profiles
    store = ProfileStore(root, first.handle)
    with pytest.raises(ProfileLeak):
        store.read_text("..", second.handle, "profile", "evidence.jsonl")


def test_store_operation_under_another_handle_is_refused(
    two_profiles: tuple[Path, Identity, Identity],
) -> None:
    root, first, second = two_profiles
    store = ProfileStore(root, first.handle)
    absolute = str(root / second.handle / "profile" / "evidence.jsonl")
    with pytest.raises(ProfileLeak):
        store.read_text(absolute)
    with pytest.raises(ProfileLeak):
        store.write_text("planted", "..", second.handle, "profile", "planted.jsonl")
    with pytest.raises(ProfileLeak):
        store.append_jsonl({"x": 1}, "..", second.handle, "profile", "evidence.jsonl")
    # And nothing was created on the way to the refusal.
    assert not (root / second.handle / "profile" / "planted.jsonl").exists()


def test_a_symlink_between_the_trees_does_not_open_a_route(
    two_profiles: tuple[Path, Identity, Identity],
) -> None:
    """The trees sit side by side under a directory the candidate can write to.

    A link planted in one and pointing at the other is the realistic version of
    the crossing, and a path check that does not resolve symlinks misses it.
    """
    root, first, second = two_profiles
    link = root / first.handle / "borrowed"
    try:
        link.symlink_to(root / second.handle)
    except (OSError, NotImplementedError):  # pragma: no cover - platform dependent
        pytest.skip("symlinks unavailable on this platform")
    with pytest.raises(ProfileLeak):
        ProfileStore(root, first.handle).read_text("borrowed", "profile", "evidence.jsonl")


def test_a_store_operation_stays_inside_its_own_tree(
    two_profiles: tuple[Path, Identity, Identity],
) -> None:
    root, first, _ = two_profiles
    store = ProfileStore(root, first.handle)
    store.append_jsonl({"kind": "note", "text": "hola"}, "profile", "evidence.jsonl")
    assert list(store.read_jsonl("profile", "evidence.jsonl")) == [{"kind": "note", "text": "hola"}]
    assert store.path("profile", "evidence.jsonl").parent.parent.name == first.handle


# --- identification precedes everything -----------------------------------


def test_no_user_identified_refuses_to_read_or_write(tmp_path: Path) -> None:
    """§6 — before reading, not merely before writing.

    The failure must be a refusal, not a default to the first handle found, so
    the unresolved resolution refuses to hand back a store at all.
    """
    root = tmp_path / "profiles"
    create_profile(root, "Ada Lovelace", language="en", now=FIXED)
    resolution = resolve_handle(root)
    with pytest.raises(IdentityError):
        resolution.store(root)
    assert (
        guard_decision(
            root / "ada-lovelace" / "profile" / "evidence.jsonl", root=root, active=None
        ).allowed
        is False
    )


def test_single_existing_profile_is_confirmed_not_assumed(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    only = create_profile(root, "Ada Lovelace", language="en", now=FIXED)

    offered = resolve_handle(root)
    assert offered.outcome == "confirm"
    assert offered.handle is None, "a suggestion must not arrive in the field callers act on"
    assert offered.candidate == only
    assert only.display_name in offered.reason

    confirmed = resolve_handle(root, confirmed=True)
    assert confirmed.outcome == "resolved"
    assert confirmed.store(root).handle == only.handle


def test_naming_yourself_resolves_by_handle_or_display_name(
    two_profiles: tuple[Path, Identity, Identity],
) -> None:
    root, first, _ = two_profiles
    assert resolve_handle(root, named=first.handle).handle == first.handle
    assert resolve_handle(root, named="ada lovelace").handle == first.handle


def test_several_profiles_are_listed_rather_than_guessed(
    two_profiles: tuple[Path, Identity, Identity],
) -> None:
    root, first, second = two_profiles
    resolution = resolve_handle(root)
    assert resolution.outcome == "choose"
    assert {identity.handle for identity in resolution.choices} == {first.handle, second.handle}
    assert resolution.handle is None


def test_an_unknown_name_offers_to_create_rather_than_matching_the_closest(
    two_profiles: tuple[Path, Identity, Identity],
) -> None:
    root, _, _ = two_profiles
    resolution = resolve_handle(root, named="Adam Lovelace")
    assert resolution.outcome == "create"
    assert resolution.handle is None


def test_no_profiles_at_all_offers_to_create_one(tmp_path: Path) -> None:
    resolution = resolve_handle(tmp_path / "profiles")
    assert resolution.outcome == "create"
    assert resolution.choices == ()


def test_a_colliding_handle_asks_rather_than_inventing_a_suffix(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    create_profile(root, "Ada Lovelace", language="en", now=FIXED)
    with pytest.raises(IdentityError, match="tell the two apart"):
        create_profile(root, "Ada Lovelace", language="en", now=FIXED)
    assert not (root / "ada-lovelace-2").exists()


def test_accents_fold_rather_than_splitting_one_person_into_two() -> None:
    assert derive_handle("Núria Puig") == derive_handle("Nuria Puig") == "nuria-puig"


def test_a_name_with_no_usable_handle_is_refused_not_silently_emptied() -> None:
    with pytest.raises(IdentityError):
        derive_handle("!!!")


def test_a_half_written_profile_is_skipped_rather_than_guessed_at(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    create_profile(root, "Ada Lovelace", language="en", now=FIXED)
    (root / "mystery" / "profile").mkdir(parents=True)
    (root / "broken").mkdir()
    (root / "broken" / "identity.json").write_text("{oops", encoding="utf-8")
    assert [identity.handle for identity in list_identities(root)] == ["ada-lovelace"]


def test_the_active_handle_round_trips_and_an_unwritable_marker_reads_as_nobody(
    tmp_path: Path,
) -> None:
    root = tmp_path / "profiles"
    assert read_active_handle(root, session_id="s1") is None
    write_active_handle(root, "ada-lovelace", session_id="s1", now=FIXED)
    assert read_active_handle(root, session_id="s1") == "ada-lovelace"
    (root / ACTIVE_FILE).write_text("not json", encoding="utf-8")
    assert read_active_handle(root, session_id="s1") is None


def test_identification_does_not_carry_over_into_the_next_session(tmp_path: Path) -> None:
    """§6.1 requires identification at the start of *every* session.

    An unbound marker is a standing authorisation: the next person to sit down
    at a shared laptop reaches the previous candidate's tree before the tool
    has said hello.
    """
    root = tmp_path / "profiles"
    write_active_handle(root, "ada-lovelace", session_id="yesterday", now=FIXED)
    assert read_active_handle(root, session_id="today") is None
    assert read_active_handle(root, session_id=None) is None
    assert (
        guard_decision(
            root / "ada-lovelace" / "profile" / "evidence.jsonl",
            root=root,
            active=read_active_handle(root, session_id="today"),
        ).allowed
        is False
    )


# --- the hook --------------------------------------------------------------


def test_correct_operation_never_trips_the_hook(
    two_profiles: tuple[Path, Identity, Identity],
) -> None:
    """A guard that blocks the tool's own work gets switched off, and guards nothing.

    Everything here is something the tool does in normal operation: reading the
    roster before anybody is identified, working inside the identified tree,
    and touching files that have nothing to do with `profiles/`.
    """
    root, first, second = two_profiles
    allowed = [
        # §6.1 case 3 lists the display names it has — before identification.
        guard_decision(root / first.handle / "identity.json", root=root, active=None),
        guard_decision(root / second.handle / "identity.json", root=root, active=first.handle),
        guard_decision(root / ACTIVE_FILE, root=root, active=None),
        guard_decision(root, root=root, active=None),
        # ordinary work inside the identified tree
        guard_decision(
            root / first.handle / "profile" / "evidence.jsonl", root=root, active=first.handle
        ),
        guard_decision(root / first.handle / "cv" / "master.json", root=root, active=first.handle),
        # and everything that is not a profile at all
        guard_decision(root.parent / "src" / "integral" / "identity.py", root=root, active=None),
        guard_decision("README.md", root=root, active=first.handle),
    ]
    refused = [decision for decision in allowed if not decision.allowed]
    assert refused == [], f"the hook blocked correct operation: {refused}"


def test_the_hook_refuses_a_read_under_another_handle(
    two_profiles: tuple[Path, Identity, Identity],
) -> None:
    root, first, second = two_profiles
    decision = guard_decision(
        root / second.handle / "profile" / "evidence.jsonl", root=root, active=first.handle
    )
    assert decision == Decision(
        False,
        f"{second.handle}/profile/evidence.jsonl belongs to '{second.handle}', "
        f"not to '{first.handle}'",
    )


def test_a_shell_command_naming_another_handles_tree_is_refused(
    two_profiles: tuple[Path, Identity, Identity],
) -> None:
    root, first, second = two_profiles
    blocked = guard_tool_call(
        "Bash",
        {"command": f"cat profiles/{second.handle}/profile/evidence.jsonl"},
        root=root,
        active=first.handle,
    )
    assert not blocked.allowed
    fine = guard_tool_call("Bash", {"command": "uv run pytest -q"}, root=root, active=first.handle)
    assert fine.allowed


def test_a_bash_command_mentioning_no_path_yields_no_paths() -> None:
    assert paths_in_tool_call("Bash", {"command": "make lint"}) == []
    assert paths_in_tool_call("Bash", {}) == []
    assert paths_in_tool_call("Read", {"file_path": "/x/y"}) == ["/x/y"]


def test_the_hook_blocks_with_exit_two_and_explains_itself(
    two_profiles: tuple[Path, Identity, Identity],
) -> None:
    root, first, second = two_profiles
    write_active_handle(root, first.handle, session_id="s1", now=FIXED)
    payload = json.dumps(
        {
            "session_id": "s1",
            "tool_name": "Read",
            "tool_input": {"file_path": str(root / second.handle / "profile" / "evidence.jsonl")},
        }
    )
    code, message = hook_main(payload, root=root)
    assert code == 2
    assert second.handle in message


def test_an_unparseable_hook_payload_lets_the_call_through(tmp_path: Path) -> None:
    """The guard is a second line, not the only one.

    Failing closed on the hook's own bug would make the tool unusable, and the
    store still raises `ProfileLeak` on the operation itself.
    """
    for payload in ("not json", "[]", '{"tool_name": 3}'):
        code, _ = hook_main(payload, root=tmp_path / "profiles")
        assert code == 0


# --- the gate --------------------------------------------------------------


def test_the_probe_suite_finds_no_leaks_and_measures_something(tmp_path: Path) -> None:
    report = probe_leaks(tmp_path / "profiles")
    assert report.leaks == ()
    assert report.probes_run >= MINIMUM_PROBES


def test_the_gate_records_the_measurement_it_made(tmp_path: Path) -> None:
    evidence = tmp_path / "S3.json"
    measured = write_evidence(evidence)
    assert measured["cross_user_leaks"] == 0
    assert measured["probes_run"] >= MINIMUM_PROBES
    assert json.loads(evidence.read_text(encoding="utf-8")) == measured


def test_the_gate_never_probes_the_real_profiles_tree(tmp_path: Path) -> None:
    """The probes create profiles and plant a symlink.

    Doing that to a real candidate's tree in order to produce a number would be
    its own kind of leak, so the measurement runs in a throwaway directory.
    """
    real = tmp_path / "profiles"
    real.mkdir()
    write_evidence(tmp_path / "S3.json")
    assert list(real.iterdir()) == []


# --- the review round on #22 ----------------------------------------------
#
# Each of these is a hole Qodo found in the first version of the guard, kept as
# a named regression rather than as a line in a commit message.


def test_another_handles_identity_file_may_be_read_but_never_written(
    two_profiles: tuple[Path, Identity, Identity],
) -> None:
    """Resolution reads the roster; nothing about it needs to rewrite it.

    Allowing the write turns "list the display names it has" into "replace who
    the tool thinks exists", which is a worse outcome than the read it was
    granted for.
    """
    root, first, second = two_profiles
    target = root / second.handle / ROSTER_FILE
    assert guard_decision(target, root=root, active=first.handle, intent="read").allowed
    assert not guard_decision(target, root=root, active=first.handle, intent="write").allowed
    assert not guard_decision(target, root=root, active=None, intent="write").allowed
    assert not guard_tool_call(
        "Edit", {"file_path": str(target)}, root=root, active=first.handle
    ).allowed


def test_a_profile_directory_is_not_roster_level(
    two_profiles: tuple[Path, Identity, Identity],
) -> None:
    """`rm -rf profiles/<somebody-else>` is not a roster operation.

    A rule that waves through everything one component deep waves through the
    deletion of a whole tree, which is the largest cross-user action there is.
    """
    root, first, second = two_profiles
    assert not guard_decision(root / second.handle, root=root, active=first.handle).allowed
    assert not guard_tool_call(
        "Bash", {"command": f"rm -rf profiles/{second.handle}"}, root=root, active=first.handle
    ).allowed
    assert guard_decision(root / first.handle, root=root, active=first.handle).allowed
    assert guard_decision(root, root=root, active=None).allowed


def test_a_shell_expansion_does_not_walk_past_the_scanner(
    two_profiles: tuple[Path, Identity, Identity],
) -> None:
    """`$PWD/profiles/<other>/…` expands into this tree at execution time.

    Reading the matched text as a literal relative path puts it outside
    `profiles/` and lets it through, which is the opposite of what the shell
    then does.
    """
    root, first, second = two_profiles
    for command in (
        f'cat "$PWD/profiles/{second.handle}/profile/evidence.jsonl"',
        f'cat "$(pwd)/profiles/{second.handle}/profile/evidence.jsonl"',
        f"cat ~/integral-job-search/profiles/{second.handle}/profile/evidence.jsonl",
        f"cat ../integral-job-search/profiles/{second.handle}/profile/evidence.jsonl",
    ):
        decision = guard_tool_call("Bash", {"command": command}, root=root, active=first.handle)
        assert not decision.allowed, command


def test_a_symlink_standing_in_for_the_handle_directory_is_refused(tmp_path: Path) -> None:
    """The subtle one: the containment root itself is the link.

    Resolving `<root>/<handle>` before using it as the boundary makes the other
    person's directory this store's authorised home, and every later check then
    passes rather than fails.
    """
    root = tmp_path / "profiles"
    real = create_profile(root, "Núria Puig", language="ca", now=FIXED)
    ProfileStore(root, real.handle).write_text("private\n", "profile", "evidence.jsonl")
    try:
        (root / "ada-lovelace").symlink_to(root / real.handle)
    except (OSError, NotImplementedError):  # pragma: no cover - platform dependent
        pytest.skip("symlinks unavailable on this platform")

    impostor = ProfileStore(root, "ada-lovelace")
    with pytest.raises(ProfileLeak, match="symbolic link"):
        impostor.read_text("profile", "evidence.jsonl")
    with pytest.raises(ProfileLeak, match="symbolic link"):
        impostor.write_text("planted", "profile", "evidence.jsonl")
    # And the roster does not report the link as a second person.
    assert [identity.handle for identity in list_identities(root)] == [real.handle]


def test_two_creators_of_one_handle_cannot_both_win(tmp_path: Path) -> None:
    """A non-atomic check-then-create merges two people into one history."""
    root = tmp_path / "profiles"
    first = create_profile(root, "Ada Lovelace", language="en", now=FIXED)
    with pytest.raises(IdentityError, match="tell the two apart"):
        create_profile(root, "Ada Lovelace", language="en", now=FIXED)
    assert ProfileStore(root, first.handle).identity().display_name == "Ada Lovelace"

    # The directory existing at all is enough — even with no identity yet, the
    # handle is taken, and the loser must not overwrite the winner's file.
    (root / "grace-hopper").mkdir()
    with pytest.raises(IdentityError, match="tell the two apart"):
        create_profile(root, "Grace Hopper", language="en", now=FIXED)
