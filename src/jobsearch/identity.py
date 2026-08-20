"""Identity: the per-user tree, handle resolution, and the leak guard (S3).

Process specification §6 says no path under `profiles/` is read or written
before a handle is resolved, and §6.1 gives the resolution order. This module
is the mechanical half of that sentence. Three things live here, and each one
exists because the prose version of it is unenforceable:

* **`ProfileStore`** — every store operation goes through one object that was
  constructed with a handle, and it resolves every path beneath that handle's
  tree. There is no function here that takes a bare path, so "read the wrong
  person's evidence" is not an operation a caller can express by accident. A
  path that escapes the tree raises `ProfileLeak` rather than returning
  something plausible.
* **`resolve_handle`** — the four-step order of §6.1 as a pure function that
  returns *what to do next*, never a handle it picked on the candidate's
  behalf. Case 2 (exactly one profile) returns `confirm`, not that profile:
  silently assuming the only profile is how one person's evidence ends up in
  another person's history, and because the log is append-only that is a mess
  to unpick rather than a mistake to undo.
* **`guard_decision`** — the rule the `PreToolUse` hook applies, kept here as a
  tested function rather than in the hook script, so the thing that can refuse
  a tool call is covered by the same suite as everything else.

The gate is `cross_user_leaks == 0` (§6.1), and it is measured rather than
asserted: `probe_leaks` builds a two-profile tree and points each profile's
operations at the other's files, counting the ones that were *not* refused.
A run that measures nothing is a failure, not a pass over an empty set.
"""

from __future__ import annotations

import errno
import json
import os
import re
import sys
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jobsearch.corpus import LANGUAGES
from jobsearch.state_home import StateHomeRefused, profiles_root

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "S3.json"


def default_profiles_root() -> Path:
    """The roster root, resolved from `$INTEGRAL_HOME` — never a repository path.

    A function rather than the module constant this replaced (T51). The
    constant was `_REPO_ROOT / "profiles"`, which put a candidate's tree inside
    the clone and left `.gitignore` as the only thing keeping it out of a
    commit; `jobsearch.state_home` makes that a refusal instead. It stays lazy
    because resolution can *fail* — importing this module must not raise just
    because the ambient environment points somewhere it should not.
    """
    return profiles_root()

# Directory-safe and stable: lowercase ASCII, digits and single hyphens. The
# handle is a directory name on three operating systems and a key in every
# derived file, so it is deliberately narrower than what a person might type —
# `derive_handle` does the narrowing, and the candidate is shown the result.
HANDLE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$")
Handle = str

# Names that would collide with the roster level of the tree or with a shell's
# idea of a relative path. `profiles/.active.json` lives at the roster level, so
# a handle may not begin with a dot either.
_RESERVED_HANDLES = frozenset({"active", "identity", "all", "new", "none", "shared"})

Language = Literal["en", "es", "ca"]

# The file at the roster level that records who this session identified. It is
# not inside any handle's tree, because reading it is what tells the guard which
# tree is allowed — a chicken-and-egg the tree layout would otherwise create.
ACTIVE_FILE = ".active.json"

# Read freely at the roster level so §6.1 case 3 can list display names before a
# handle exists. Nothing else under a handle is readable pre-identification.
ROSTER_FILE = "identity.json"


class IdentityError(Exception):
    """Identification could not be completed, or a profile is malformed."""


class ProfileLeak(Exception):
    """An operation tried to resolve a path outside its own profile's tree.

    Raised, never returned: a leak that a caller can ignore is a leak. It is
    also what `probe_leaks` counts, so the gate and the runtime failure mode
    are the same event.
    """


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Identity(Strict):
    """`profiles/<handle>/identity.json` — process spec §6.

    The display name is what the candidate gave; the handle is derived from it
    and is the only thing that ever appears in a path. A full legal name is not
    required and is never asked for as an opening (§6.1).
    """

    handle: str = Field(pattern=HANDLE.pattern, min_length=1, max_length=32)
    display_name: str = Field(min_length=1, max_length=200)
    language: Language
    locale: str = Field(pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    created_at: str
    # S11: this candidate was invented to exercise a step, not interviewed.
    # Defaulted rather than required so every profile written before test mode
    # existed still loads, and *false* by default rather than optional: a
    # profile that does not say it is fiction is a person. The mark is enforced
    # by `list_identities`, which is the reader — a mark nothing checks is
    # decoration.
    fiction: bool = False

    def summary(self) -> str:
        """How the tool refers to this person out loud."""
        suffix = " — simulated" if self.fiction else ""
        return f"{self.display_name} ({self.handle}){suffix}"


# ---------------------------------------------------------------------------
# handles


def derive_handle(display_name: str) -> Handle:
    """Turn what a person typed into a directory-safe handle.

    Accents are folded rather than stripped to nothing, because "Núria" and
    "Nuria" are the same person's answer to the same question and the second
    should not silently become a different profile from the first.
    """
    folded = unicodedata.normalize("NFKD", display_name.strip().lower())
    ascii_only = "".join(ch for ch in folded if not unicodedata.combining(ch))
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-")[:32].strip("-")
    if not slug or not HANDLE.match(slug) or slug in _RESERVED_HANDLES:
        raise IdentityError(
            f"cannot derive a handle from {display_name!r} — ask for something to use instead"
        )
    return slug


def _validate_handle(handle: str) -> Handle:
    if not HANDLE.match(handle) or handle in _RESERVED_HANDLES:
        raise IdentityError(f"not a usable handle: {handle!r}")
    return handle


# ---------------------------------------------------------------------------
# the store


class ProfileStore:
    """Every read and write under one candidate's tree, and nothing else.

    Constructed with a handle, so a caller that has not identified anybody has
    no object to call. `path` is the single choke point, and it refuses three
    different escapes:

    * an **absolute or climbing component** — `..`, or a path that starts at
      the root;
    * a **symlink anywhere beneath the tree** that points out of it;
    * a **symlink standing in for the handle directory itself**. This one is
      the subtle case: resolving `<root>/<handle>` before using it as the
      containment root means a `profiles/ada` that is really a link to
      `profiles/nuria` makes Núria's directory Ada's authorised home, and every
      later check then passes. So `home` is composed from the *resolved root*
      and the literal handle, and is never resolved further.
    """

    def __init__(self, root: Path, handle: Handle) -> None:
        self.root = Path(root)
        self.handle = _validate_handle(handle)
        # The root may legitimately sit behind links (`/tmp` on macOS), so it is
        # resolved; the handle component never is — see the class docstring.
        self.home = self.root.resolve(strict=False) / self.handle

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ProfileStore(root={self.root!s}, handle={self.handle!r})"

    def path(self, *parts: str) -> Path:
        """Resolve `parts` beneath this profile's tree, or refuse."""
        self._refuse_a_symlinked_home()
        if not parts:
            return self.home
        for part in parts:
            if Path(part).is_absolute():
                raise ProfileLeak(f"absolute path in a store operation: {part!r}")
        candidate = self.home.joinpath(*parts).resolve(strict=False)
        if candidate != self.home and self.home not in candidate.parents:
            raise ProfileLeak(f"{candidate} is outside the tree of {self.handle!r}")
        return candidate

    def _refuse_a_symlinked_home(self) -> None:
        """A handle directory that is a link is not this candidate's tree.

        Checked on every operation rather than once in the constructor: a store
        outlives the moment it was built, and the whole point of the check is
        that the directory can be replaced by something else.
        """
        if self.home.is_symlink():
            raise ProfileLeak(
                f"{self.home} is a symbolic link, so it is not {self.handle!r}'s own tree"
            )

    def _open_leaf(self, target: Path, mode: str) -> Any:
        """Open the final component without following a link at that name.

        `O_NOFOLLOW` where the platform has it. This does not close the general
        check-then-open race — see the note on `ProfileLeak` — but it does stop
        the static case, where a file inside the tree has quietly been a link
        to somewhere else all along.
        """
        flags = getattr(os, "O_NOFOLLOW", 0)
        if not flags:  # pragma: no cover - platform dependent
            return target.open(mode, encoding="utf-8")
        base = os.O_RDONLY
        if mode == "a":
            base = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        elif mode == "w":
            base = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        try:
            descriptor = os.open(target, base | flags, 0o600)
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.EMLINK}:
                raise ProfileLeak(f"{target} is a symbolic link, not a file in this tree") from exc
            raise
        return os.fdopen(descriptor, mode, encoding="utf-8")

    # -- reads ------------------------------------------------------------

    def exists(self, *parts: str) -> bool:
        return self.path(*parts).exists()

    def read_text(self, *parts: str) -> str:
        target = self.path(*parts)
        try:
            with self._open_leaf(target, "r") as stream:
                content: str = stream.read()
        except FileNotFoundError as exc:
            raise IdentityError(f"{'/'.join(parts)} does not exist for {self.handle!r}") from exc
        return content

    def read_json(self, *parts: str) -> Any:
        """Malformed JSON is an `IdentityError`, not a `JSONDecodeError`.

        Callers that step around a broken profile — `list_identities` is the
        one that matters — catch this module's errors. A decoder exception
        escaping through them turns "skip the half-written profile" into a
        crash at the roster level, which is the tool's opening move.
        """
        raw = self.read_text(*parts)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise IdentityError(f"{self.handle}/{'/'.join(parts)} is not JSON: {exc}") from exc

    def read_jsonl(self, *parts: str) -> Iterator[Any]:
        for number, line in enumerate(self.read_text(*parts).splitlines(), start=1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise IdentityError(f"{'/'.join(parts)}:{number} is not JSON: {exc}") from exc

    # -- writes -----------------------------------------------------------

    def write_text(self, content: str, *parts: str) -> Path:
        target = self.path(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._open_leaf(target, "w") as stream:
            stream.write(content)
        return target

    def write_json(self, payload: Any, *parts: str) -> Path:
        return self.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", *parts
        )

    def append_jsonl(self, row: Any, *parts: str) -> Path:
        target = self.path(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._open_leaf(target, "a") as stream:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        return target

    # -- identity ---------------------------------------------------------

    def identity(self) -> Identity:
        try:
            return Identity.model_validate(self.read_json(ROSTER_FILE))
        except ValidationError as exc:
            raise IdentityError(f"{self.handle}/{ROSTER_FILE} is malformed: {exc}") from exc


# ---------------------------------------------------------------------------
# the roster and the four-step resolution


def list_identities(root: Path, *, include_fiction: bool = False) -> list[Identity]:
    """Every *real* profile that exists, in handle order.

    A directory without a readable `identity.json` is skipped rather than
    guessed at: the roster is what the tool reads names out of, and a half
    written profile has no name to read.

    **A simulated candidate is not in the roster** (S11). Test mode may invent
    a candidate in order to exercise a step that no real run has reached yet,
    and the profile it leaves behind is marked `fiction: true`. Excluding it
    here — in the reader, defaulted on — is what makes the mark mean something:
    every existing caller stops counting fiction without being changed, which
    is the opposite of a flag each of them must remember to check.
    `include_fiction=True` is for the test-mode tooling that has to see its own
    work, and it has to be asked for by name.
    """
    root = Path(root)
    if not root.is_dir():
        return []
    found: list[Identity] = []
    for child in sorted(root.iterdir()):
        if child.name.startswith("."):
            continue
        if child.is_symlink() or not child.is_dir():
            # `is_dir()` follows links, so a `profiles/ada -> profiles/nuria`
            # would list Núria's identity under Ada's name. A link is not a
            # profile; the roster is the one place that has to say so out loud.
            continue
        try:
            identity = ProfileStore(root, child.name).identity()
        except (IdentityError, ProfileLeak):
            continue
        if identity.fiction and not include_fiction:
            continue
        found.append(identity)
    return found


Outcome = Literal["resolved", "confirm", "choose", "create"]


@dataclass(frozen=True)
class Resolution:
    """What §6.1 says to do next — never a handle chosen on the candidate's behalf.

    `handle` is set only for `resolved`. For `confirm` it is `candidate`: the
    profile to *offer*, which the caller must have confirmed before it builds a
    store. Keeping them in different fields is the whole point — a caller
    cannot read a suggestion as a decision.
    """

    outcome: Outcome
    reason: str
    handle: Handle | None = None
    candidate: Identity | None = None
    choices: tuple[Identity, ...] = ()

    @property
    def is_resolved(self) -> bool:
        return self.outcome == "resolved"

    def store(self, root: Path) -> ProfileStore:
        """The store for a resolved handle; anything else refuses."""
        if self.outcome != "resolved" or self.handle is None:
            raise IdentityError(
                f"no handle is resolved yet ({self.outcome}: {self.reason}) — "
                "nothing under profiles/ may be read or written"
            )
        return ProfileStore(root, self.handle)


def resolve_handle(
    root: Path,
    *,
    named: str | None = None,
    confirmed: bool = False,
    include_fiction: bool = False,
) -> Resolution:
    """The §6.1 resolution order, as far as it can go without asking.

    1. the candidate names themselves, or a handle is supplied explicitly;
    2. exactly one profile exists → name it and ask for confirmation;
    3. otherwise ask who this is, listing the display names it has;
    4. no match → offer to create a profile, which is an explicit act.

    `confirmed=True` is the caller reporting that the human answered yes to the
    offer this function made last time. It is the only way case 2 becomes a
    resolution, which is what makes case 2 a confirmation rather than a default.

    `include_fiction=True` lets a **test-mode** session resolve the simulated
    candidate it created (S11). Excluding fiction from the roster is right, and
    is what makes the mark mean something — but resolution reads the roster
    too, so excluding it here as well left a simulated profile unreachable even
    when its handle was supplied by name, and a simulated run could not enter
    the step flow it exists to exercise. The flag is off by default and has to
    be asked for, so a real candidate's session can never be resolved onto an
    invented profile by accident.
    """
    identities = list_identities(root, include_fiction=include_fiction)

    if named:
        wanted = named.strip()
        matches = [
            identity
            for identity in identities
            if identity.handle == wanted or identity.display_name.casefold() == wanted.casefold()
        ]
        if len(matches) == 1:
            return Resolution(
                outcome="resolved",
                reason=f"named {wanted!r}",
                handle=matches[0].handle,
                candidate=matches[0],
            )
        if len(matches) > 1:
            # Two people who answer to the same display name. §6.1: ask for
            # something to tell them apart rather than inventing a suffix.
            return Resolution(
                outcome="choose",
                reason=f"{len(matches)} profiles answer to {wanted!r}",
                choices=tuple(matches),
            )
        return Resolution(
            outcome="create",
            reason=f"no profile matches {wanted!r}",
            choices=tuple(identities),
        )

    if len(identities) == 1:
        only = identities[0]
        if confirmed:
            return Resolution(
                outcome="resolved",
                reason=f"confirmed {only.summary()}",
                handle=only.handle,
                candidate=only,
            )
        return Resolution(
            outcome="confirm",
            reason=f"one profile exists — offer {only.summary()} and wait for a yes",
            candidate=only,
        )

    if identities:
        return Resolution(
            outcome="choose",
            reason=f"{len(identities)} profiles exist — ask which one this is",
            choices=tuple(identities),
        )

    return Resolution(outcome="create", reason="no profile exists yet")


def create_profile(
    root: Path,
    display_name: str,
    *,
    language: Language = "es",
    locale: str | None = None,
    handle: str | None = None,
    now: datetime | None = None,
    fiction: bool = False,
) -> Identity:
    """Create a profile — always an explicit act (§6.1 case 4).

    A handle that already exists is refused rather than suffixed: two people
    who would collide are asked for something to tell them apart, and a
    `-2` invented here is a name nobody chose and nobody recognises.

    `fiction=True` records that this candidate was invented to exercise a step
    (S11). It is written into `identity.json` at creation, because that is the
    only moment anybody knows: a profile cannot be discovered to have been
    simulated afterwards, so a mark that could be added later would be one that
    could be forgotten.
    """
    chosen = _validate_handle(handle) if handle else derive_handle(display_name)
    root = Path(root)
    if language not in LANGUAGES:
        raise IdentityError(f"unsupported language {language!r}; known: {', '.join(LANGUAGES)}")
    root.mkdir(parents=True, exist_ok=True)
    try:
        # Exclusive, so two sessions creating the same handle at once cannot
        # both pass a check and then have one overwrite the other's identity —
        # which would silently merge two people into one history.
        (root / chosen).mkdir(exist_ok=False)
    except FileExistsError as exc:
        raise IdentityError(
            f"a profile named {chosen!r} already exists — "
            "ask for something to tell the two apart"
        ) from exc
    stamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat(timespec="seconds")
    identity = Identity(
        handle=chosen,
        display_name=display_name.strip(),
        language=language,
        locale=locale or language,
        created_at=stamp,
        fiction=fiction,
    )
    store = ProfileStore(root, chosen)
    payload = json.dumps(identity.model_dump(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    descriptor = os.open(store.path(ROSTER_FILE), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(payload)
    return identity


def read_active_handle(root: Path, *, session_id: str | None) -> Handle | None:
    """Who *this session* identified, or `None` — which means nothing may be read.

    The marker is bound to the session that wrote it. Without that binding the
    file is a standing authorisation: the next session, for the next person on
    a shared laptop, inherits whoever was identified last and reaches their
    tree before saying hello. §6.1 requires identification at the start of
    *every* session, so a marker from a different session is no marker at all.
    """
    if not session_id:
        # No session to compare against: treat it as nobody identified. The
        # safe direction — the store still works, only the guard tightens.
        return None
    marker = Path(root) / ACTIVE_FILE
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict) or payload.get("session_id") != session_id:
        return None
    handle = payload.get("handle")
    if not isinstance(handle, str) or not HANDLE.match(handle):
        return None
    return handle


def write_active_handle(
    root: Path, handle: Handle, *, session_id: str, now: datetime | None = None
) -> Path:
    """Record the resolved handle for this session, stamped with the session id."""
    _validate_handle(handle)
    if not session_id:
        raise IdentityError("an active handle must be bound to a session")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    marker = root / ACTIVE_FILE
    stamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat(timespec="seconds")
    marker.write_text(
        json.dumps(
            {"handle": handle, "session_id": session_id, "identified_at": stamp}, indent=2
        )
        + "\n",
        encoding="utf-8",
    )
    return marker


# ---------------------------------------------------------------------------
# the PreToolUse guard


@dataclass(frozen=True)
class Decision:
    """The guard's answer about one path."""

    allowed: bool
    reason: str


# Whether a call would only look, or could change something. The distinction
# matters at exactly one place — `identity.json` is the roster the tool reads
# names out of before anybody is identified, and reading it is harmless while
# writing it rewrites who the tool thinks exists.
Intent = Literal["read", "write"]

# Bash is `write` because a command can be `rm`. Being wrong in that direction
# refuses a shell read of somebody else's roster entry, which costs nothing.
_WRITING_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit", "Bash"})


def intent_of(tool_name: str) -> Intent:
    return "write" if tool_name in _WRITING_TOOLS else "read"


def guard_decision(
    target: Path | str,
    *,
    root: Path,
    active: Handle | None,
    intent: Intent = "read",
) -> Decision:
    """May this path be touched, given who the session identified?

    The rules, in the order they are applied:

    1. outside `profiles/` — not this guard's business;
    2. the roster directory itself — allowed, so the tool can list who exists;
    3. roster metadata (`profiles/.active.json` and any other dotfile at that
       level) — allowed, because writing it *is* the act of identifying, and
       the session binding in `read_active_handle` is what makes a tampered
       marker inert rather than an authorisation;
    4. a handle **directory** — treated as that handle's, not as roster level.
       This is what stops `rm -rf profiles/<somebody-else>` from passing as a
       roster-level operation;
    5. `profiles/<h>/identity.json` **being read** — allowed for every `h`,
       because §6.1 case 3 lists the display names it has, and that is where
       they are. Writing it is not: that rewrites another person's roster
       entry, and no part of resolution needs to;
    6. anything else under a handle with nobody identified — refused, which is
       §6's "before reading, not merely before writing";
    7. under the identified handle — allowed;
    8. under another handle — refused.

    Rule 5 is the one that keeps `test_correct_operation_never_trips_the_hook`
    honest: without it the tool cannot perform its own opening move.
    """
    root = Path(root).resolve(strict=False)
    candidate = Path(target)
    if not candidate.is_absolute():
        candidate = (root.parent / candidate).resolve(strict=False)
    else:
        candidate = candidate.resolve(strict=False)

    if candidate != root and root not in candidate.parents:
        return Decision(True, "outside the profile tree")

    relative = candidate.relative_to(root) if candidate != root else Path()
    parts = relative.parts
    if not parts:
        return Decision(True, "the roster directory, which resolution has to list")
    if len(parts) == 1 and parts[0].startswith("."):
        return Decision(True, "roster metadata, which identification itself writes")

    handle = parts[0]
    if parts[1:] == (ROSTER_FILE,) and intent == "read":
        return Decision(True, "identity.json is the roster resolution reads names from")
    if active is None:
        return Decision(
            False, "no candidate is identified yet; §6.1 — identification precedes reads"
        )
    if handle == active:
        return Decision(True, f"inside the tree of {active!r}")
    return Decision(False, f"{relative} belongs to {handle!r}, not to {active!r}")


# Everything from a `profiles/` segment onward, wherever it appears in a shell
# command. The prefix is deliberately discarded rather than matched: the shell
# expands `"$PWD/profiles/nuria/…"` and `"$(pwd)/profiles/nuria/…"` into this
# tree, and a scanner that read `PWD/profiles/nuria` as a literal relative path
# would place it outside `profiles/` and wave it through. Treating every
# `profiles/<x>/…` token as a path under the roster is the safe direction: the
# cost is refusing a command that names an unrelated directory called
# `profiles/`, and the alternative is missing the one that matters.
_BASH_PROFILE_PATH = re.compile(r"profiles/[\w.-]+(?:/[\w.-]+)*")


def paths_in_tool_call(tool_name: str, tool_input: dict[str, Any]) -> list[str]:
    """Which paths a `PreToolUse` payload is about.

    File tools name their path in a field. `Bash` does not, so its command
    string is scanned for anything that looks like a path under `profiles/`;
    everything else in the command is left alone, so an unrelated command
    yields no paths and is never refused.

    The shell is not parsed, and it cannot be — this is a heuristic, and the
    store-side `ProfileLeak` is the enforcing layer. What the heuristic must
    not do is *silently* let something through, so it errs towards matching.
    """
    if tool_name == "Bash":
        command = tool_input.get("command")
        if not isinstance(command, str):
            return []
        return [match.group(0) for match in _BASH_PROFILE_PATH.finditer(command)]
    found: list[str] = []
    for key in ("file_path", "path", "notebook_path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            found.append(value)
    return found


def guard_tool_call(
    tool_name: str,
    tool_input: dict[str, Any],
    *,
    root: Path,
    active: Handle | None,
) -> Decision:
    """The guard over a whole `PreToolUse` payload: refused if any path is."""
    intent = intent_of(tool_name)
    for raw in paths_in_tool_call(tool_name, tool_input):
        decision = guard_decision(raw, root=root, active=active, intent=intent)
        if not decision.allowed:
            return Decision(False, f"{raw}: {decision.reason}")
    return Decision(True, "no path under profiles/ that belongs to somebody else")


def hook_main(stdin_text: str, *, root: Path | None = None) -> tuple[int, str]:
    """The `PreToolUse` hook body: JSON in, (exit code, message) out.

    Exit 2 is Claude Code's "block this call and tell the model why"; 0 lets it
    through. A payload this hook cannot parse lets the call through — a guard
    that fails closed on its own bug would make the tool unusable, and the
    store-side `ProfileLeak` is the real enforcement.
    """
    try:
        roster = Path(root) if root is not None else default_profiles_root()
    except StateHomeRefused as exc:
        # There is no store here to protect: the resolver refused the only root
        # this hook could have guarded. Allowing the call matches the posture
        # in this function's docstring — the store-side `ProfileLeak` is the
        # real enforcement, and a guard that blocked every tool call because it
        # could not find a tree would make the session unusable.
        return 0, f"profile guard: no candidate store to guard — {exc}"
    try:
        payload = json.loads(stdin_text)
    except json.JSONDecodeError as exc:
        return 0, f"profile guard: unreadable hook payload ({exc})"
    if not isinstance(payload, dict):
        return 0, "profile guard: hook payload is not an object"
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_name, str) or not isinstance(tool_input, dict):
        return 0, "profile guard: hook payload names no tool"
    session_id = payload.get("session_id")
    decision = guard_tool_call(
        tool_name,
        tool_input,
        root=roster,
        active=read_active_handle(
            roster, session_id=session_id if isinstance(session_id, str) else None
        ),
    )
    if decision.allowed:
        return 0, ""
    return 2, f"profile guard refused this call — {decision.reason}"


# ---------------------------------------------------------------------------
# the gate


@dataclass(frozen=True)
class ProbeReport:
    """What the gate measured: how many probes ran, and which ones got through."""

    probes_run: int
    leaks: tuple[str, ...]


def probe_leaks(root: Path) -> ProbeReport:
    """Point each profile's operations at the other's tree and count what got through.

    This is the gate's measurement, and it is deliberately adversarial: the
    probes are the mistakes a caller actually makes — a relative climb, an
    absolute path, a symlink planted between the trees, a handle that was never
    identified. Every one must raise; a probe that returns a value is a leak,
    named in the returned list.
    """
    root = Path(root)
    first = create_profile(root, "Probe One", handle="probe-one")
    second = create_profile(root, "Probe Two", handle="probe-two")
    store = ProfileStore(root, first.handle)
    other = ProfileStore(root, second.handle)
    other.write_text("second's secret\n", "profile", "evidence.jsonl")

    leaks: list[str] = []
    probes = 0

    def must_refuse(label: str, operation: Any) -> None:
        nonlocal probes
        probes += 1
        try:
            operation()
        except (ProfileLeak, IdentityError, OSError):
            return
        leaks.append(label)

    def must_be_refused_by_the_guard(label: str, decision: Decision) -> None:
        nonlocal probes
        probes += 1
        if decision.allowed:
            leaks.append(label)

    must_refuse(
        "relative climb into the other tree",
        lambda: store.read_text("..", second.handle, "profile", "evidence.jsonl"),
    )
    must_refuse(
        "absolute path into the other tree",
        lambda: store.read_text(str(other.path("profile", "evidence.jsonl"))),
    )
    must_refuse(
        "write through a relative climb",
        lambda: store.write_text("x", "..", second.handle, "profile", "planted.jsonl"),
    )
    must_refuse(
        "append through a relative climb",
        lambda: store.append_jsonl({"x": 1}, "..", second.handle, "profile", "evidence.jsonl"),
    )
    must_refuse("climb clean out of profiles/", lambda: store.read_text("..", "..", "README.md"))

    link = root / first.handle / "borrowed"
    try:
        link.symlink_to(root / second.handle)
    except (OSError, NotImplementedError):  # pragma: no cover - platform dependent
        link = None  # type: ignore[assignment]
    if link is not None:
        must_refuse(
            "symlink pointing at the other tree",
            lambda: store.read_text("borrowed", "profile", "evidence.jsonl"),
        )

    # And the guard the hook applies, over the same shapes.
    must_be_refused_by_the_guard(
        "guard allowed a read with nobody identified",
        guard_decision(
            root / second.handle / "profile" / "evidence.jsonl", root=root, active=None
        ),
    )
    must_be_refused_by_the_guard(
        "guard allowed a read under another handle",
        guard_decision(
            root / second.handle / "profile" / "evidence.jsonl", root=root, active=first.handle
        ),
    )
    must_be_refused_by_the_guard(
        "guard allowed a shell command naming another handle's tree",
        guard_tool_call(
            "Bash",
            {"command": f"cat profiles/{second.handle}/profile/evidence.jsonl"},
            root=root,
            active=first.handle,
        ),
    )
    must_be_refused_by_the_guard(
        "guard allowed a write to another handle's identity.json",
        guard_tool_call(
            "Edit",
            {"file_path": str(root / second.handle / ROSTER_FILE)},
            root=root,
            active=first.handle,
        ),
    )
    must_be_refused_by_the_guard(
        "guard allowed the deletion of another handle's whole tree",
        guard_tool_call(
            "Bash",
            {"command": f"rm -rf profiles/{second.handle}"},
            root=root,
            active=first.handle,
        ),
    )
    must_be_refused_by_the_guard(
        "guard allowed a shell expansion that lands in another handle's tree",
        guard_tool_call(
            "Bash",
            {"command": f'cat "$PWD/profiles/{second.handle}/profile/evidence.jsonl"'},
            root=root,
            active=first.handle,
        ),
    )

    # A marker written by another session is not this session's authorisation.
    write_active_handle(root, second.handle, session_id="another-session")
    probes += 1
    if read_active_handle(root, session_id="this-session") is not None:
        leaks.append("an active handle carried over from a different session")

    # And a handle directory that is really a link to the other tree.
    impostor_home = root / "probe-three"
    try:
        impostor_home.symlink_to(root / second.handle)
    except (OSError, NotImplementedError):  # pragma: no cover - platform dependent
        pass
    else:
        must_refuse(
            "a symlink standing in for the handle directory",
            lambda: ProfileStore(root, "probe-three").read_text("profile", "evidence.jsonl"),
        )

    return ProbeReport(probes_run=probes, leaks=tuple(leaks))


# Below this, a run has skipped so much that its zero means nothing. Only the
# two symlink probes may be absent (a platform without symlinks), so the floor
# is every other probe.
MINIMUM_PROBES = 12


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH, *, workspace: Path | None = None
) -> dict[str, Any]:
    """Measure `cross_user_leaks` in a throwaway two-profile tree and record it.

    The measurement never runs against `profiles/` itself: the probes create
    profiles and plant a symlink, and doing that to a real candidate's tree to
    produce a number would be its own kind of leak.
    """
    import tempfile

    if workspace is not None:
        report = probe_leaks(Path(workspace))
    else:
        with tempfile.TemporaryDirectory(prefix="jobsearch-s3-") as tmp:
            report = probe_leaks(Path(tmp) / "profiles")
    measured: dict[str, Any] = {
        "cross_user_leaks": len(report.leaks),
        "probes_run": report.probes_run,
        "leaks": list(report.leaks),
    }
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """Two entry points, one module.

        python -m jobsearch.identity            → measure S3's gate, write evidence
        python -m jobsearch.identity --hook     → the PreToolUse guard, JSON on stdin
    """
    if "--hook" in argv[1:]:
        code, message = hook_main(sys.stdin.read())
        if message:
            print(message, file=sys.stderr)
        return code

    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["probes_run"] < MINIMUM_PROBES:
        # A pass over nothing is not a pass: zero leaks out of zero attempts is
        # exactly what a broken probe suite reports.
        print(
            f"only {measured['probes_run']} probes ran (floor {MINIMUM_PROBES}) — "
            "nothing was measured",
            file=sys.stderr,
        )
        return 3
    for leak in measured["leaks"]:
        print(f"cross-user leak: {leak}", file=sys.stderr)
    return 1 if measured["leaks"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
