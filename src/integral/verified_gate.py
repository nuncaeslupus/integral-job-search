r"""Is the local substitute for CI still a substitute? (T121)

GitHub Actions ran out of monthly minutes on 2026-09-04, four days into the
billing period, and `merge-policy` is `after-ci-and-review`. `make host-gate`
runs exactly the four checks CI ran, so it is the obvious stand-in — but run in
a session's own checkout it answers a **weaker question**, and the difference is
the whole reason this module exists:

- CI measured the **pushed commit**. A local run measures the working tree,
  which can carry uncommitted edits, staged-but-uncommitted files, or a stale
  `.pyc` whose source was restored inside the same second (`CLAUDE.md`, "A
  reverted mutation can leave the mutated bytecode running").
- CI's verdict named the commit it tested. A local run's verdict is whatever the
  session says it is, and the tested-equals-merged property was checked by hand
  twice on 2026-09-04.

`tools/verified_gate.sh` closes both: it resolves the ref to a 40-character SHA,
checks that SHA into a throwaway detached worktree, runs the gate there, and
prints a block naming the commit measured. This module asserts the script still
does that, because a substitute nobody checks is how the thing it substitutes
for stops being done at all — which is D-22's subject, one layer out.

## Reading the script's text could not establish what the script does

**Three rounds of text-matching were defeated, and the third proved the approach
wrong rather than the patterns wrong.** The history is the argument for the
design below; without it a later session reads a table of shell invocations and
"simplifies" it back to a dozen regexes.

- **Round 1.** The module searched the whole file for `make\s+host-gate`, which
  the script's own header comments contained twice. A script whose run line said
  `make lint`, and a script with the gate line deleted and `status=0` hard-coded
  so every verdict printed PASS, **both** scored `verified_gate_defects == 0`.
- **Round 2** (`316cd6c`) added `executable_text()` — a filter dropping
  comment-only lines — and grew the table from 5 patterns to 12.
- **Round 3** defeated round 2 twice over. **A1**: all twelve patterns placed
  inside one unused single-quoted string, `dead_string_never_executed='…'`,
  beside `sha=0000…`, `resolved_from="origin, fetched just now"`,
  `echo "verdict   PASS"` and `exit 0` — `verified_gate_defects: 0`,
  `properties_checked: 12`, `missing_properties: []`, over a script that
  resolves nothing, fetches nothing, creates no worktree and runs no gate.
  **A2**: the same twelve in *trailing* `# …` comments on `true` lines, which
  the filter keeps because a line carrying code is not comment-only. Same zero.

The diagnosis is not "add a thirteenth pattern":

> `executable_text()` is a `#`-line filter, not an executability test. Any inert
> but non-`#` location — a quoted string, a heredoc body, a trailing comment, a
> `case` branch, an unreachable function — satisfies all twelve properties.

Writing a bash parser would move the goalposts, not the game: the question
"which of these bytes execute" is undecidable in the general case and the
script's job is defined by what it *does*, not by what it contains.

**Which half had held up is the clue that shaped this one.** In round 1 the
mutation that completely fooled the text checker — the gate deleted, `status=0`
hard-coded — was caught by the *functional* test running the real script against
a real repository. The functional half has never been defeated. So the whole
measurement is now that half.

## What is measured: behavioural contracts, run against throwaway repositories

`CONTRACTS` is a table of named claims about what the script **does when it is
run**. Each builds a git repository in a temporary directory — one of them a
clone with a real bare `origin` — runs `tools/verified_gate.sh` against it, and
reads the verdict block, the exit status and the filesystem afterwards.
`verified_gate_defects` is the number of contracts the script fails, plus the
one documentation cross-check.

Every contract carries the mutation it kills, because a contract nobody can
break is decoration:

- **`a_failing_gate_is_reported_as_FAIL`** kills **B1** — one line `status=0`
  after `status=$?`. The gate runs, genuinely fails, and the block prints PASS
  with rc 0. No text property ever touched `status` or the verdict.
- **`the_commit_is_measured_not_the_callers_tree`** kills running the gate in
  `${repo_root}`, which is the property the whole script exists for.
- **`the_verdict_names_the_commit_it_measured`** kills a block that prints a
  fixed string where the SHA goes.
- **`nothing_survives_the_run_pass_or_fail`** kills **B2** — deleting
  `trap cleanup EXIT`, which leaves the round-2 property `worktree prune`
  matching happily while cleanup never runs. Checked after a **failing** run
  too, which is the path the leak was on.
- **`the_resolution_line_is_true`** kills **B5** — `resolved` is an echo of a
  variable nothing constrained, and hard-coding it scored zero defects.
- **`the_origin_reachability_line_is_true`** kills the same, for `on origin`.
- **`caller_relative_refs_measure_the_caller`** kills **C** — `@` is git's
  documented synonym for `HEAD` but is not the *string* `"HEAD"`, so it walked
  through the round-2 guard, and `git fetch origin -- @` succeeds and sets
  `FETCH_HEAD` to origin's **default branch**. Measured: standing on a failing
  branch, `bash tools/verified_gate.sh @` printed origin/main's SHA and PASS,
  rc 0.
- **`an_unmeasurable_ref_refuses_with_2`** kills a fall-through to a gate run
  over whatever tree the script happened to land in.
- **`the_aggregate_target_is_what_runs`** kills D-22's drift — an enumerated
  subset in place of the delegation — and, because the probe keeps repeats
  rather than collapsing to a set, running the gate **twice**, which is what
  `open_task_pr.sh` v3.2.0 did on both sides of the task-file archive.
  Observed through a probe the Makefile writes, never read out of the script.
- **`the_verdict_reports_the_command_that_ran`** kills round 1's compounding
  half — a block pasted onto a pull request claiming the aggregate while
  `make lint` ran.

**A1 dies without a rule of its own.** A script of dead strings resolves
nothing, fetches nothing and runs no gate, so it fails **8 of the 10** contracts
and scores `verified_gate_defects: 8` where round 2 scored it 0. A2 — the same
twelve patterns in trailing comments — also scores 8.

The two it does *not* fail are named here rather than rounded up, because a
reader who assumed all ten would go red would mistrust the number.
`the_commit_is_measured_not_the_callers_tree` is satisfied by a script that
prints PASS unconditionally, and `nothing_survives_the_run_pass_or_fail` by one
that creates nothing to leave behind. Neither is redundant — each is the only
contract that catches its own mutation, running the gate in `${repo_root}` and
deleting `trap cleanup EXIT` respectively — but neither can recognise a
do-nothing script alone, and none here is claimed to. The eight that do is the
argument; a contract table works as a set.

## The one thing still read rather than run

`undocumented` — `CLAUDE.md` must name the script where it tells a session how to
merge without CI. Prose that names no script, and a script no prose names, are
the two halves of D-22's original defect, and neither is a claim about
behaviour. It is a substring check and deliberately shallow: asserting the prose
*describes* the script correctly is not something a regex can do.

Nothing else matches text against the script. In particular no contract pins the
**order** of a command's flags: round 2's property 11 required
`fetch\s+--quiet\s+origin\s+--\s`, so a harmless reorder was a defect while a
dead copy of the whole table was clean — fail-closed on the cosmetic and
fail-open on the substantive, which is exactly backwards.

## The zero hides nothing

`verified_gate_defects` is a sum, so every component is reported beside it by
name — `contracts_checked_by_name` lists what ran, `failed_contracts` names what
broke and why. A metric that reads 0 while a reader cannot see *which* claims
were checked is the shape this repository has now caught five times
(`status_is_asserted` T108, `incidental_duplicate_drops` #323,
`negation_recall_hits_by_mechanism` #318,
`robots_adjudications_without_a_competent_second_reader` T116, and this task's
own first two rounds).

The denominator is a floor, `verified_gate_contracts_at_least`, written as a
**literal** the way `naming.MINIMUM_SCANNED` is. Round 2's read
`len(REQUIRED_PROPERTIES)` while the number it guarded read
`len(REQUIRED_PROPERTIES)` too, so the guard compared an expression to itself,
the floor could never fire, and deleting entries from the table shrank both
sides together (#333, F3). That fix is kept here, re-expressed over contracts.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from integral.repo_gate import AGGREGATE_TARGET

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCRIPT_PATH = _REPO_ROOT / "tools" / "verified_gate.sh"
DEFAULT_INSTRUCTIONS = _REPO_ROOT / "CLAUDE.md"
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T121.json"
DEFAULT_T161_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T161.json"

#: The verdict block's field names. `on origin` carries a space on purpose — it
#: is read back exactly as the block prints it, so a renamed field is a failure
#: rather than a silently absent check.
_BLOCK_FIELDS = ("commit", "ref", "resolved", "on origin", "measured", "command", "verdict")

_MAKE_TARGET_RE = re.compile(r"\bmake\s+([a-z][a-z0-9-]*)")

#: A gate recipe that succeeds, printing a line the script's summary grep keeps.
_PASSING = "\t@echo 'evidence: no drift'"
#: A gate recipe that genuinely fails, the way a red `make host-gate` does.
_FAILING = "\t@echo boom; exit 1"

#: Extra targets the probe Makefile carries, so a script that enumerates a
#: subset of the aggregate has something real to invoke and be caught doing.
_PROBE_EXTRA_TARGETS = ("lint", "test", "evidence", "verify-gates")


def _clean_env(**extra: str) -> dict[str, str]:
    """The ambient environment with `make`'s recursion variables stripped.

    `measure()` is itself reached from `make evidence`, which is reached from
    `make host-gate`. Without this, `MAKEFLAGS` from the outer run is inherited
    by the throwaway `make` three levels down and can change what it does — a
    contract failing for the caller's `-j` is a false defect, and a contract
    passing for one would be worse.
    """
    env = {k: v for k, v in os.environ.items() if k not in ("MAKEFLAGS", "MAKELEVEL", "MFLAGS")}
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.update(extra)
    return env


def _plain_makefile(recipe: str) -> str:
    """A Makefile whose aggregate target runs exactly `recipe`."""
    return f"{AGGREGATE_TARGET}:\n{recipe}\n"


def _probe_makefile() -> str:
    """A Makefile whose every target records that it was invoked.

    Each recipe appends its own name to `$(VG_PROBE)`, so after a run the file
    holds the targets that actually executed. That is how delegation is
    measured now: observed from outside, rather than read out of the script,
    which is what round 2 did and what a dead string satisfied.
    """
    lines = [
        f"{AGGREGATE_TARGET}:",
        f'\t@echo {AGGREGATE_TARGET} >> "$(VG_PROBE)"',
        _PASSING,
        "",
    ]
    for target in _PROBE_EXTRA_TARGETS:
        lines += [f"{target}:", f'\t@echo {target} >> "$(VG_PROBE)"', ""]
    return "\n".join(lines)


@dataclass(frozen=True)
class Run:
    """One observed execution of the script."""

    returncode: int
    stdout: str
    stderr: str
    fields: dict[str, str]

    @property
    def has_verdict_block(self) -> bool:
        return "verdict" in self.fields


def _read_block(stdout: str) -> dict[str, str]:
    """The verdict block's fields, keyed as the block prints them."""
    found: dict[str, str] = {}
    for line in stdout.splitlines():
        for key in _BLOCK_FIELDS:
            if line.startswith(key) and line[len(key) : len(key) + 1] in (" ", "\t"):
                found[key] = line[len(key) :].strip()
                break
    return found


class Harness:
    """Throwaway repositories, and the script run against them.

    Never the real repository: running the real gate takes 162 seconds and
    proves only that this tree is green, which `make host-gate` already says.
    What needs proving is the script's own behaviour, and that is cheap.
    """

    def __init__(self, script: Path, workdir: Path) -> None:
        self.script = script
        self.workdir = workdir

    def git(self, *args: str, cwd: Path) -> str:
        return subprocess.run(
            ("git", *args),
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
            env=_clean_env(),
        ).stdout.strip()

    def _identify(self, root: Path) -> None:
        self.git("config", "user.email", "t@example.invalid", cwd=root)
        self.git("config", "user.name", "t", cwd=root)
        # A machine that signs every commit cannot commit inside a throwaway
        # repo with no key for it, and that would read as a contract failure.
        self.git("config", "commit.gpgsign", "false", cwd=root)

    def repo(self, name: str, makefile: str) -> Path:
        """A one-file git repository whose aggregate target does what we say."""
        root = self.workdir / name
        root.mkdir(parents=True)
        (root / "Makefile").write_text(makefile, encoding="utf-8")
        self.git("init", "-q", "-b", "main", cwd=root)
        self._identify(root)
        self.git("add", "-A", cwd=root)
        self.git("commit", "-qm", "initial", cwd=root)
        return root

    def clone_with_an_origin(self) -> tuple[Path, str, str]:
        """A clone whose `origin` carries a **passing** gate on its default
        branch and whose checked-out `feature` branch carries a **failing** one.

        Returns `(clone, origin's main SHA, the local branch's SHA)`. The two
        differ in both commit and verdict on purpose: any contract that
        accidentally measures the wrong one says so loudly rather than
        coincidentally agreeing.
        """
        bare = self.workdir / "upstream.git"
        self.git("init", "-q", "--bare", str(bare), cwd=self.workdir)
        # `git init --bare` points HEAD at `master`; GitHub points it at the
        # default branch, and `git fetch origin HEAD` only answers with the
        # default branch when there is one — which is the whole of finding C.
        self.git("symbolic-ref", "HEAD", "refs/heads/main", cwd=bare)

        seed = self.repo("seed", _plain_makefile(_PASSING))
        self.git("remote", "add", "origin", str(bare), cwd=seed)
        self.git("push", "-q", "origin", "main", cwd=seed)
        upstream = self.git("rev-parse", "HEAD", cwd=seed)

        clone = self.workdir / "clone"
        self.git("clone", "-q", str(bare), str(clone), cwd=self.workdir)
        self._identify(clone)
        self.git("checkout", "-qb", "feature", cwd=clone)
        (clone / "Makefile").write_text(_plain_makefile(_FAILING), encoding="utf-8")
        self.git("add", "-A", cwd=clone)
        self.git("commit", "-qm", "a gate that genuinely fails", cwd=clone)
        return clone, upstream, self.git("rev-parse", "HEAD", cwd=clone)

    def run(
        self,
        root: Path,
        *args: str,
        probe: Path | None = None,
        tmpdir: Path | None = None,
    ) -> Run:
        extra: dict[str, str] = {}
        if probe is not None:
            extra["VG_PROBE"] = str(probe)
        if tmpdir is not None:
            # `mktemp` honours TMPDIR, so pointing it at an empty directory of
            # our own is how "no temp directory survives" becomes observable.
            extra["TMPDIR"] = str(tmpdir)
        done = subprocess.run(
            ["bash", str(self.script), *args],
            cwd=root,
            capture_output=True,
            text=True,
            env=_clean_env(**extra),
        )
        return Run(done.returncode, done.stdout, done.stderr, _read_block(done.stdout))

    def invoked_targets(self, probe: Path) -> list[str]:
        """Every target invocation, **in order and with repeats kept**.

        Not a set: running the aggregate twice is its own defect, and it is not
        hypothetical here. `open_task_pr.sh` v3.2.0 ran the host gate on both
        sides of the task-file archive, so the committed evidence would have had
        to hold two values at once (`CLAUDE.md`, 615 pre-archive against 614
        post). A checker that collapsed the probe to a set would call that clean.
        """
        if not probe.exists():
            return []
        return [
            line.strip() for line in probe.read_text(encoding="utf-8").splitlines() if line.strip()
        ]


# --------------------------------------------------------------------------
# The contracts. Each returns None when the script honours it, or a sentence
# saying what it observed instead.
# --------------------------------------------------------------------------


def _c_failing_gate_is_FAIL(h: Harness) -> str | None:
    root = h.repo("repo", _plain_makefile(_FAILING))
    ran = h.run(root, "HEAD")
    verdict = ran.fields.get("verdict")
    if verdict != "FAIL":
        return f"a committed gate that exits 1 produced verdict {verdict!r}, not FAIL"
    if ran.returncode != 1:
        return f"a committed gate that exits 1 produced exit {ran.returncode}, not 1"
    if "failing output" not in ran.stdout:
        return "a FAIL verdict carried none of the output that caused it"
    return None


def _c_measures_the_commit(h: Harness) -> str | None:
    root = h.repo("repo", _plain_makefile(_PASSING))
    head = h.git("rev-parse", "HEAD", cwd=root)

    # Everything a local run could trip over, all at once: a tracked file edited
    # so the gate fails, an untracked file, and a bytecode cache.
    (root / "Makefile").write_text(_plain_makefile("\t@exit 1"), encoding="utf-8")
    (root / "untracked_junk.py").write_text("raise SystemExit(1)\n", encoding="utf-8")
    cache = root / "__pycache__"
    cache.mkdir()
    (cache / "stale.cpython-312.pyc").write_bytes(b"\x00not-bytecode")

    local = subprocess.run(
        ["make", AGGREGATE_TARGET], cwd=root, capture_output=True, env=_clean_env()
    )
    if local.returncode == 0:
        return (
            "the scenario is stale: the dirtied tree's own gate still passes, "
            "so this contract would prove nothing"
        )

    ran = h.run(root, head)
    if ran.returncode != 0 or ran.fields.get("verdict") != "PASS":
        return (
            f"the COMMITTED gate passes, but the run reported verdict "
            f"{ran.fields.get('verdict')!r}, exit {ran.returncode}. The tree here was "
            f"dirtied so that a gate run WHERE THE CALLER STANDS fails, so this is what "
            f"measuring the caller's tree looks like — and equally what running some "
            f"other command than the aggregate looks like, since neither reaches the "
            f"committed recipe"
        )
    return None


def _c_verdict_names_the_commit(h: Harness) -> str | None:
    root = h.repo("repo", _plain_makefile(_PASSING))
    head = h.git("rev-parse", "HEAD", cwd=root)
    ran = h.run(root, head)
    named = ran.fields.get("commit")
    if named != head:
        return f"the block named commit {named!r}; the commit measured was {head}"
    return None


def _c_nothing_survives(h: Harness) -> str | None:
    for label, recipe in (("passing", _PASSING), ("failing", _FAILING)):
        root = h.repo(f"repo-{label}", _plain_makefile(recipe))
        tmp = h.workdir / f"tmp-{label}"
        tmp.mkdir()
        h.run(root, "HEAD", tmpdir=tmp)

        listed = h.git("worktree", "list", cwd=root)
        if listed.count("\n"):
            return f"after a {label} run a worktree survived:\n{listed}"
        registrations = root / ".git" / "worktrees"
        if registrations.exists() and any(registrations.iterdir()):
            names = sorted(p.name for p in registrations.iterdir())
            return f"after a {label} run the .git/worktrees registration survived: {names}"
        leftover = sorted(p.name for p in tmp.iterdir() if p.name.startswith("verified-gate"))
        if leftover:
            return f"after a {label} run these temp entries survived: {leftover}"
    return None


def _c_resolution_line_is_true(h: Harness) -> str | None:
    clone, upstream, local = h.clone_with_an_origin()

    fetched = h.run(clone, "main")
    if fetched.fields.get("commit") != upstream:
        return f"`main` resolved to {fetched.fields.get('commit')!r}, not origin's {upstream}"
    if fetched.fields.get("resolved") != "origin, fetched just now":
        return (
            f"a ref genuinely fetched from origin was reported as "
            f"{fetched.fields.get('resolved')!r}"
        )

    only_local = h.run(clone, "feature")
    if only_local.fields.get("commit") != local:
        return f"`feature` resolved to {only_local.fields.get('commit')!r}, not the local {local}"
    if only_local.fields.get("resolved") != "local ref":
        return (
            f"a ref origin does not carry was reported as "
            f"{only_local.fields.get('resolved')!r} — the block claimed a fetch that failed"
        )
    return None


def _c_origin_reachability_is_true(h: Harness) -> str | None:
    clone, _upstream, _local = h.clone_with_an_origin()

    pushed = h.run(clone, "main")
    on_origin = pushed.fields.get("on origin", "")
    if not on_origin.startswith("yes") or "origin/main" not in on_origin:
        return f"a commit reachable from origin/main was reported as {on_origin!r}"

    unpushed = h.run(clone, "feature")
    on_origin = unpushed.fields.get("on origin", "")
    if not on_origin.startswith("NO"):
        return f"a commit on no origin/* ref was reported as {on_origin!r}"
    return None


def _c_caller_relative_refs(h: Harness) -> str | None:
    """`@`, `HEAD`, `HEAD~0`, `HEAD^0`, `""` and no argument all mean *here*.

    Every one of them is a way of naming the caller's own commit, and the block
    must never answer any of them with origin's default branch — the failure
    that shipped at `316cd6c` for `@` alone.
    """
    clone, upstream, local = h.clone_with_an_origin()
    for args in ((), ("",), ("HEAD",), ("@",), ("HEAD~0",), ("HEAD^0",)):
        spelled = " ".join(repr(a) for a in args) or "no argument"
        ran = h.run(clone, *args)
        named = ran.fields.get("commit")
        if named == upstream:
            return (
                f"{spelled} measured origin's default branch ({upstream}), not the caller's commit"
            )
        if named != local:
            return f"{spelled} measured commit {named!r}, not the caller's {local}"
        if ran.fields.get("verdict") != "FAIL" or ran.returncode != 1:
            return (
                f"{spelled} measured the caller's commit — whose gate genuinely fails — "
                f"but reported verdict {ran.fields.get('verdict')!r}, exit {ran.returncode}"
            )
    return None


def _c_unmeasurable_ref_refuses(h: Harness) -> str | None:
    """Exit 2 means NOTHING was measured, and it must stay unambiguous.

    Run against a clone with a real `origin`, because that is where an
    option-looking ref can be swallowed by `git fetch` and answered with some
    other commit — measured on `fd933ec`, where `--depth=1` produced a verdict
    block for a commit the caller never named.
    """
    clone, _upstream, _local = h.clone_with_an_origin()
    for ref in (
        "refs/heads/no-such-branch-anywhere",
        "--all",
        "--depth=1",
        "--upload-pack=/bin/false",
    ):
        ran = h.run(clone, ref)
        if ran.returncode != 2:
            return f"`{ref}` exited {ran.returncode}; 2 is the code that means nothing was measured"
        if ran.has_verdict_block or "PASS" in ran.stdout:
            return f"`{ref}` printed a verdict block while resolving nothing:\n{ran.stdout}"
    return None


def _c_aggregate_target_is_what_runs(h: Harness) -> str | None:
    """D-22's drift guard, observed rather than read.

    A script that enumerates `lint test evidence verify-gates` in place of the
    delegation is a second definition of the gate, free to fall behind the
    Makefile. The probe Makefile makes every target announce itself, so what
    ran is a fact about the run and not a claim about the file.
    """
    root = h.repo("repo", _probe_makefile())
    probe = h.workdir / "invoked.txt"
    ran = h.run(root, "HEAD", probe=probe)
    invoked = h.invoked_targets(probe)
    if not invoked:
        return "the run invoked no make target at all — nothing was gated"
    if invoked != [AGGREGATE_TARGET]:
        return (
            f"the run invoked {invoked}; the script must delegate to "
            f"`make {AGGREGATE_TARGET}`, exactly once, and run nothing else"
        )
    if ran.returncode != 0 or ran.fields.get("verdict") != "PASS":
        return (
            f"the aggregate target passed but the block said "
            f"{ran.fields.get('verdict')!r}, exit {ran.returncode}"
        )
    return None


def _c_command_line_reports_what_ran(h: Harness) -> str | None:
    """The block is pasted onto a pull request, so its `command` line is a claim
    made to a reviewer. It must match what the probe saw execute."""
    root = h.repo("repo", _probe_makefile())
    probe = h.workdir / "invoked.txt"
    ran = h.run(root, "HEAD", probe=probe)
    # Compared as sets here, unlike the contract above: this one is about the
    # block telling the truth about WHICH targets ran, and "ran it twice" is the
    # other contract's business.
    invoked = sorted(set(h.invoked_targets(probe)))
    reported = sorted(set(_MAKE_TARGET_RE.findall(ran.fields.get("command", ""))))
    if not reported:
        return f"the block's `command` line names no make target: {ran.fields.get('command')!r}"
    if reported != invoked:
        return (
            f"the block reported `make {' '.join(reported)}` but the run invoked "
            f"{invoked} — a verdict pasted onto a pull request claiming work it did not do"
        )
    return None


@dataclass(frozen=True)
class Contract:
    """One claim about what the script does when it is run."""

    name: str
    why: str
    check: Callable[[Harness], str | None]


CONTRACTS: tuple[Contract, ...] = (
    Contract(
        "a_failing_gate_is_reported_as_FAIL",
        "one line `status=0` after `status=$?` makes a genuinely failing gate print PASS "
        "with exit 0; no text property ever touched `status` or the verdict",
        _c_failing_gate_is_FAIL,
    ),
    Contract(
        "the_commit_is_measured_not_the_callers_tree",
        "the working tree is not what a reviewer merges — uncommitted edits, untracked "
        "files and a stale bytecode cache must not reach the run",
        _c_measures_the_commit,
    ),
    Contract(
        "the_verdict_names_the_commit_it_measured",
        "a verdict that does not say what it measured cannot be checked against the "
        "pull-request head later, which is the one rule CLAUDE.md calls easy to skip",
        _c_verdict_names_the_commit,
    ),
    Contract(
        "nothing_survives_the_run_pass_or_fail",
        "deleting `trap cleanup EXIT` leaves a `worktree prune` line in the file and no "
        "cleanup at all; the leak is on the FAILING path, which is why both are run",
        _c_nothing_survives,
    ),
    Contract(
        "the_resolution_line_is_true",
        "`resolved` is an echo of a variable nothing constrained; hard-coding it "
        "`origin, fetched just now` scored zero defects while nothing was fetched",
        _c_resolution_line_is_true,
    ),
    Contract(
        "the_origin_reachability_line_is_true",
        "a PASS pasted for a commit nobody can fetch is not evidence about a merge",
        _c_origin_reachability_is_true,
    ),
    Contract(
        "caller_relative_refs_measure_the_caller",
        '`@` is git\'s synonym for HEAD but is not the string "HEAD", and '
        "`git fetch origin -- @` answers with origin's DEFAULT BRANCH: at 316cd6c, "
        "`verified_gate.sh @` on a failing branch printed origin/main's SHA and PASS",
        _c_caller_relative_refs,
    ),
    Contract(
        "an_unmeasurable_ref_refuses_with_2",
        "exit 2 must keep meaning NOTHING was measured; falling through to a gate run "
        "over whatever tree the script landed in is the fail-open direction",
        _c_unmeasurable_ref_refuses,
    ),
    Contract(
        "the_aggregate_target_is_what_runs",
        "an enumerated subset is a second definition of the gate, free to fall behind "
        "the Makefile — D-22's subject, and here observed through the Makefile itself",
        _c_aggregate_target_is_what_runs,
    ),
    Contract(
        "the_verdict_reports_the_command_that_ran",
        "round 1's compounding half: the block printed the aggregate's name "
        "unconditionally, so a script running `make lint` pasted a verdict claiming it "
        "had run the aggregate",
        _c_command_line_reports_what_ran,
    ),
)

#: A literal, on purpose — `naming.MINIMUM_SCANNED`'s form, and for its reason.
#: Written as `len(CONTRACTS)` it would be compared at the guard below against a
#: count derived from `CONTRACTS` too, so the floor would be `x < x`:
#: unreachable, and deleting half the table would move both sides together.
#: #333, F3, kept through the redesign. Raise this when the table grows;
#: `test_the_floor_is_a_literal_the_table_cannot_drag` refuses a shrunken table.
MINIMUM_CONTRACTS = 10


def run_contracts(
    script_path: Path = DEFAULT_SCRIPT_PATH,
    contracts: Sequence[Contract] | None = None,
) -> tuple[list[str], list[str]]:
    """`(failures as "name — what was observed", the names actually run)`.

    The second element is produced by this loop, not by `len(CONTRACTS)` — that
    is what makes it independent of the floor it is compared against.

    A contract that raises is a **failure**, not a skip. `git` or `make` missing,
    a scenario that cannot be built, a script that hangs the harness: each of
    those means the substitute was not shown to work, and reporting zero defects
    over it is the vacuous pass this whole task is about.
    """
    # Resolved here, not in the signature: a default bound at definition time
    # cannot be narrowed or shrunk by a caller (or by the floor's own test), and
    # a floor that no test can reach is #333's F3 in a second costume.
    if contracts is None:
        contracts = CONTRACTS
    failures: list[str] = []
    ran: list[str] = []
    with tempfile.TemporaryDirectory(prefix="verified-gate-contracts-") as raw:
        base = Path(raw)
        for contract in contracts:
            ran.append(contract.name)
            workdir = base / contract.name
            workdir.mkdir(parents=True)
            try:
                observed = contract.check(Harness(script_path, workdir))
            except Exception as exc:
                observed = f"the contract could not be run: {exc!r}"
            if observed is not None:
                failures.append(f"{contract.name} — {observed}  [{contract.why}]")
    return failures, ran


def is_documented(instructions: str, script_path: Path = DEFAULT_SCRIPT_PATH) -> bool:
    """Does `CLAUDE.md` name the script?

    One direction only, and deliberately shallow: asserting that the prose
    *describes* it correctly is not something a regex can do, and a check that
    pretends to would be worse than none.
    """
    return script_path.name in instructions


def measure(
    script_path: Path = DEFAULT_SCRIPT_PATH,
    instructions: Path = DEFAULT_INSTRUCTIONS,
    contracts: Sequence[Contract] | None = None,
) -> dict[str, Any]:
    """Count the ways the local substitute has stopped substituting."""
    if not script_path.exists():
        return {
            "verified_gate_defects": -1,
            "verified_gate_contracts_checked": 0,
            "verified_gate_contracts_at_least": MINIMUM_CONTRACTS,
            # `measured`, not `unmeasured`: the check RAN and its answer is "the
            # script is gone". `unmeasured` is this repository's word for a check
            # that cannot be scored yet, it is signalled by exit 3, and
            # `make evidence` records it and CONTINUES — so writing it here said,
            # in the repo's own vocabulary, the opposite of what `_main` decided
            # (it returns 1). #333, F5.
            "gate_status": "measured",
            "contracts_checked_by_name": [],
            "failed_contracts": [],
            "undocumented": [],
        }
    failed, checked = run_contracts(script_path, contracts)
    undocumented = (
        []
        if instructions.exists()
        and is_documented(instructions.read_text(encoding="utf-8"), script_path)
        else [f"CLAUDE.md does not name {script_path.name}"]
    )
    return {
        "verified_gate_defects": len(failed) + len(undocumented),
        "verified_gate_contracts_checked": len(checked),
        "verified_gate_contracts_at_least": MINIMUM_CONTRACTS,
        "gate_status": "measured" if checked else "unmeasured",
        "contracts_checked_by_name": checked,
        "failed_contracts": failed,
        "undocumented": undocumented,
    }


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    script_path: Path = DEFAULT_SCRIPT_PATH,
    instructions: Path = DEFAULT_INSTRUCTIONS,
) -> dict[str, Any]:
    """Measure and record `status/evidence/T121.json`."""
    measured = measure(script_path, instructions)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


# ---------------------------------------------------------------------------
# T161 — the block must not assert what it did not measure about CI
#
# `tools/verified_gate.sh` printed, in every verdict block, a hardcoded
# sentence: "CI is unavailable; this is the substitute CLAUDE.md names". That
# was true during the 2026-09-04 runner outage and false from 2026-09-07,
# when the repository went public and Actions became unmetered — so every
# block pasted on a pull request since carried a false claim about CI's
# state, some of them beside a green `CI` check on the same head minutes
# apart. The block exists so a reader can see the checking happened; a claim
# in it that the run never grounded is this repository's own named defect
# family (a check — here, an evidence artefact — asserting a property it did
# not observe), inside the one file whose whole job is to be trustworthy
# about what was measured.
#
# The fix is scoped, per the task: either measure what the block says about
# CI, or say nothing about it. This repository has no live CI channel to
# query from a sandboxed throwaway worktree (no `gh`, no network), so the
# script now says nothing — CLAUDE.md already states the two are
# complementary (this script over the committed head, CI over the PR's merge
# ref), and the block can state its own scope without asserting anything
# about the other half.
#
# What is measured is therefore not "is the claim true" — there must be no
# claim left to be true or false — but "does the emitted block make ANY
# unearned assertion about CI's availability or result". Behavioural, in this
# module's established idiom (see the module docstring): the check never
# reads the script's source, only the TEXT the script prints when it is
# actually run, because reading the source was defeated three times by
# comments, an unused string literal and trailing comments — none of which
# can hide inside the text a reviewer actually reads on the pull request.
#
# A CI-state assertion is "CI", a verb of being/having, and a state word, all
# within one short span — "CI is unavailable", "CI has failed", "CI was
# green". A sentence that only *names* CI to state this script's own scope
# ("this makes no claim about CI, which measures the merge ref separately")
# carries no such verb-plus-state-word triple and does not match. The
# regex is intentionally loose on the state-word list — a script that starts
# claiming CI is "flaky" or "stale" instead of "unavailable" should still
# be caught, and a false negative here is fail-open, exactly the direction
# CLAUDE.md weights against.
#
# Two alternatives, not one, for the same fail-open reason: a verb-carrying
# form ("CI is unavailable", "CI has failed") over a wide window, AND a
# verb-less adjacency form ("CI: unavailable", "CI — down") over a much
# tighter one. The regression this task fixes used the first shape, but the
# next rewrite of this line need not, and a check that only recognises today's
# grammar is
# the same "add a thirteenth pattern" mistake the module docstring already
# names for the script's own source — repeated one layer up if this were
# single-shaped too. The tight window on the second alternative is what keeps
# it from flagging a scope sentence that merely names CI and a state word
# nearby in a longer, unrelated clause.
_CI_STATE_ASSERTION_RE = re.compile(
    r"\bci\b(?:"
    r"[^.\n]{0,60}?\b(?:is|was|are|were|has|have|had)\b[^.\n]{0,40}?"
    r"\b(?:unavailable|available|down|up|broken|working|green|red|"
    r"passing|passed|failing|failed|skipped|disabled|enabled|required|succeeded|ran)\b"
    r"|"
    r"[^.\n]{0,20}?\b(?:unavailable|available|down|up|broken|working|green|red|"
    r"passing|passed|failing|failed|skipped|disabled|enabled|required|succeeded|ran)\b"
    r")",
    re.IGNORECASE,
)


def ci_state_assertions(text: str) -> tuple[str, ...]:
    """Every span in `text` asserting CI's availability or result.

    Matched against emitted TEXT — a script's actual stdout for one real run —
    never against `tools/verified_gate.sh`'s source. See the section above for
    why: source-matching is what three prior rounds defeated.
    """
    return tuple(match.group(0) for match in _CI_STATE_ASSERTION_RE.finditer(text))


@dataclass(frozen=True)
class CiClaimScenario:
    """One real run of the script, whose printed text is scanned for
    ungrounded CI assertions. Each scenario is a distinct case a verdict
    block is pasted from in practice, so a fix that happens to clear one
    wording only for PASS, say, is still caught on the others."""

    name: str
    why: str
    stdout: Callable[[Harness], str]


def _ci_claims_on_a_passing_run(h: Harness) -> str:
    """The ordinary case — most blocks pasted on a pull request are this one."""
    root = h.repo("repo", _plain_makefile(_PASSING))
    return h.run(root, "HEAD").stdout


def _ci_claims_on_a_failing_run(h: Harness) -> str:
    """A FAIL block still must not assert a CI state this run never checked."""
    root = h.repo("repo", _plain_makefile(_FAILING))
    return h.run(root, "HEAD").stdout


def _ci_claims_on_a_pushed_commit(h: Harness) -> str:
    """The exact case named in the task: a block pasted beside a green `CI`
    check on the SAME head must not separately assert anything about CI —
    reachable from origin is a fact this run *did* observe (`on origin`);
    CI's own state is not."""
    clone, _upstream, _local = h.clone_with_an_origin()
    return h.run(clone, "main").stdout


CI_CLAIM_SCENARIOS: tuple[CiClaimScenario, ...] = (
    CiClaimScenario(
        "ci_claims_on_a_passing_run",
        "the ordinary case: a PASS block must not assert a CI state this run never checked",
        _ci_claims_on_a_passing_run,
    ),
    CiClaimScenario(
        "ci_claims_on_a_failing_run",
        "a FAIL block still must not claim anything about CI, which this run never observed",
        _ci_claims_on_a_failing_run,
    ),
    CiClaimScenario(
        "ci_claims_on_a_pushed_commit",
        "the case the task names: a block pasted beside a green CI check on the same head "
        "must not separately assert CI is unavailable, or anything else about it",
        _ci_claims_on_a_pushed_commit,
    ),
)

#: A literal, on purpose — `MINIMUM_CONTRACTS`'s form and reason repeated:
#: written as `len(CI_CLAIM_SCENARIOS)` the floor below would compare a count
#: derived from the table against itself, `x < x`, unreachable, and deleting
#: a scenario would move both sides together. #333, F3; T100/T122's convention.
MINIMUM_CI_CLAIM_SCENARIOS = 3


def measure_ci_claims(
    script_path: Path = DEFAULT_SCRIPT_PATH,
    scenarios: Sequence[CiClaimScenario] | None = None,
) -> dict[str, Any]:
    """T161's gate: `verdict_block_claims_about_ci_that_are_not_measured`.

    Runs the script for real, once per scenario, against a throwaway
    repository — never reads its source — and counts every span
    `ci_state_assertions` finds across all of them. Before the fix this was
    non-zero (the hardcoded sentence appears in every run's block); the fix
    is that the block stops asserting anything about CI, so a fixed script
    scores 0 here not because nothing was checked but because there is
    nothing left to find.

    A scenario that cannot even be run (git or make missing, the harness
    itself broken) is not "no claims found" — recording zero over a check
    that did not run is the vacuous pass this whole task is about — so it is
    recorded as a claim of its own, keeping the metric non-zero rather than
    silently dropping a third of the denominator.
    """
    if not script_path.exists():
        return {
            "verdict_block_claims_about_ci_that_are_not_measured": -1,
            "ci_claim_scenarios_checked": 0,
            "ci_claim_scenarios_at_least": MINIMUM_CI_CLAIM_SCENARIOS,
            "gate_status": "measured",
            "ci_claim_scenarios_checked_by_name": [],
            "ci_claims_found": [],
        }
    if scenarios is None:
        scenarios = CI_CLAIM_SCENARIOS
    found: list[str] = []
    checked: list[str] = []
    with tempfile.TemporaryDirectory(prefix="verified-gate-ci-claims-") as raw:
        base = Path(raw)
        for scenario in scenarios:
            checked.append(scenario.name)
            workdir = base / scenario.name
            workdir.mkdir(parents=True)
            try:
                stdout = scenario.stdout(Harness(script_path, workdir))
            except Exception as exc:
                found.append(f"{scenario.name}: the scenario could not be run: {exc!r}")
                continue
            for assertion in ci_state_assertions(stdout):
                found.append(f"{scenario.name}: {assertion!r}")
    return {
        "verdict_block_claims_about_ci_that_are_not_measured": len(found),
        "ci_claim_scenarios_checked": len(checked),
        "ci_claim_scenarios_at_least": MINIMUM_CI_CLAIM_SCENARIOS,
        "gate_status": "measured" if checked else "unmeasured",
        "ci_claim_scenarios_checked_by_name": checked,
        "ci_claims_found": found,
    }


def write_t161_evidence(
    evidence: Path = DEFAULT_T161_EVIDENCE_PATH,
    script_path: Path = DEFAULT_SCRIPT_PATH,
) -> dict[str, Any]:
    """Measure and record `status/evidence/T161.json`."""
    measured = measure_ci_claims(script_path)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


@dataclass(frozen=True)
class Options:
    """A parsed command line, or the reason it was refused."""

    script: Path | None = None
    instructions: Path | None = None
    target: Path | None = None
    error: str | None = None


_VALUE_FLAGS = ("--script", "--instructions")


def parse_args(argv: Sequence[str]) -> Options:
    """Refuse anything not understood, rather than dropping it.

    Two residues of #333's F4 were still here after the flag's value stopped
    being taken as a positional:

    - `args.index(name)` removed only the **first** occurrence, so
      `--script A --script B` left `B` standing as the positional — the evidence
      path — and the run overwrote it with JSON, exit 0, no warning. A repeated
      flag is now refused outright: silently honouring one of two contradictory
      values is how the first bug got its exit 0.
    - `--script=PATH`, and any misspelling, began with `-` and so was stripped
      from the positionals *and* never recognised as a flag. `own_tree` stayed
      True, so the run measured **this** repository and wrote the real
      `status/evidence/T121.json` — a caller who mistypes got a green answer
      about a file they never named. Unknown options now exit 2.

    A second positional is refused for the same reason: the old code took
    `positional[0]` and dropped the rest without saying so.
    """
    seen: dict[str, Path] = {}
    positional: list[str] = []
    rest = list(argv)
    while rest:
        token = rest.pop(0)
        if token in _VALUE_FLAGS:
            if token in seen:
                return Options(error=f"{token} given twice; it takes one path")
            if not rest:
                return Options(error=f"{token} needs a path")
            seen[token] = Path(rest.pop(0))
            continue
        if token.startswith("-"):
            joined = " or ".join(f"`{f} PATH`" for f in _VALUE_FLAGS)
            return Options(
                error=f"unknown option {token!r} — this takes an evidence path, {joined}"
            )
        positional.append(token)
    if len(positional) > 1:
        return Options(error=f"one evidence path at most, got {positional}")

    script = seen.get("--script")
    instructions = seen.get("--instructions")
    own_tree = script is None and instructions is None
    # Naming a script or an instructions file other than this repository's makes
    # the evidence path default to *nothing*: a measurement of some other tree is
    # not evidence about this repository, so it is printed and not recorded
    # unless the caller also said where. `naming --repo` sets that precedent.
    target = Path(positional[0]) if positional else (DEFAULT_EVIDENCE_PATH if own_tree else None)
    return Options(script, instructions, target)


def _main(argv: list[str]) -> int:
    """Write T121's gate evidence. Exit 1 while the substitute has a defect.

    python -m integral.verified_gate [evidence-path]
        [--script PATH] [--instructions PATH]
    """
    options = parse_args(argv[1:])
    if options.error is not None:
        print(f"verified-gate: {options.error}", file=sys.stderr)
        return 2

    script_path = options.script if options.script is not None else DEFAULT_SCRIPT_PATH
    instructions = (
        options.instructions if options.instructions is not None else DEFAULT_INSTRUCTIONS
    )

    measured = (
        measure(script_path, instructions)
        if options.target is None
        else write_evidence(options.target, script_path=script_path, instructions=instructions)
    )
    for key in ("failed_contracts", "undocumented"):
        for item in measured[key]:
            print(f"✗ {key}: {item}", file=sys.stderr)
    print(json.dumps(measured, ensure_ascii=False))

    # T161's evidence rides along with T121's, on the one invocation
    # `make evidence` actually makes: no `--script`/`--instructions` override,
    # and the evidence path left at its default. Naming a script or an
    # instructions file other than this repository's already makes `options.target`
    # `None` above (a measurement of some other tree is not evidence about this
    # one), so `options.target == DEFAULT_EVIDENCE_PATH` alone is enough here — it
    # is unreachable unless `own_tree` was also true when `parse_args` set it.
    ci_measured: dict[str, Any] | None = None
    if options.target == DEFAULT_EVIDENCE_PATH:
        # `DEFAULT_T161_EVIDENCE_PATH` passed explicitly, not left to the
        # function's own default: a default argument is bound once at def
        # time, so a caller (a test, or a future host) that repoints the
        # module-level constant would otherwise still write to the original
        # path — the exact residue #333's F4 already found in this module
        # once, for `DEFAULT_EVIDENCE_PATH` itself.
        ci_measured = write_t161_evidence(DEFAULT_T161_EVIDENCE_PATH, script_path=script_path)
        for item in ci_measured["ci_claims_found"]:
            print(f"✗ ci_claims_found: {item}", file=sys.stderr)
        print(json.dumps(ci_measured, ensure_ascii=False))

    # The floor last and below the finding, the precedence `naming` sets: a real
    # defect outranks a thin denominator. -1 is "the script is gone", which is
    # the maximal defect and not an honest "cannot measure yet" — so it fails
    # rather than reporting unmeasured.
    if measured["verified_gate_defects"] < 0:
        print(
            f"verified-gate: {script_path.name} does not exist — the substitute "
            "CLAUDE.md tells sessions to merge on is missing entirely",
            file=sys.stderr,
        )
        return 1
    if measured["verified_gate_defects"] > 0:
        return 1
    if ci_measured is not None:
        claims = ci_measured["verdict_block_claims_about_ci_that_are_not_measured"]
        if claims != 0:
            # Covers both directions: claims > 0 is a live regression (the
            # hardcoded sentence, or one like it, is back); claims < 0 mirrors
            # T121's missing-script case above and must fail the same way
            # rather than read as an honest "unmeasured".
            print(
                f"verdict_block_claims_about_ci_that_are_not_measured: {claims} "
                "— the emitted block asserts something about CI this run did not "
                "observe",
                file=sys.stderr,
            )
            return 1
    if measured["verified_gate_contracts_checked"] < MINIMUM_CONTRACTS:
        print(
            f"verified_gate_contracts_checked: {measured['verified_gate_contracts_checked']} "
            f"is below the floor of {MINIMUM_CONTRACTS} — zero defects over that few "
            "contracts is not a measurement",
            file=sys.stderr,
        )
        return 3
    if (
        ci_measured is not None
        and ci_measured["ci_claim_scenarios_checked"] < MINIMUM_CI_CLAIM_SCENARIOS
    ):
        print(
            f"ci_claim_scenarios_checked: {ci_measured['ci_claim_scenarios_checked']} is "
            f"below the floor of {MINIMUM_CI_CLAIM_SCENARIOS} — zero unmeasured CI claims "
            "over that few scenarios is not a measurement",
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
