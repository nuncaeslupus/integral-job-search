# Session handover — 2026-08-20 (T55 merged; token-cost pass)

## Board

- **T55 merged** as `745a155` via
  #108, closing #49. The
  package is `integral`, the distribution `integral-job-search`, and
  `integral.naming` is the gate that keeps old names from creeping back.
- **The GitHub repo has not been renamed** — that is the owner's to do, and until
  they do it the clone URL in `README.md` is aspirational. `docs/distribution.md`
  says so explicitly.
- `task_select.py` next returns **`t-20ca057d` (D-21, "a step whose gate is
  not_implemented must not report `coverage_met` and exit 0", priority 5)**.
  Unclaimed. Steps 8 and 9 certify over unbuilt gates until it lands.

## What this session changed besides T55

A token-cost pass, at the owner's request. **`CLAUDE.md` is resident on every turn
of every session**, so its length is charged per turn, not per read. It was 8,200
chars; it is now 4,845, with everything situational moved to
`docs/repo-playbook.md` — a path to open, never an import. Nothing was deleted:
the bundle-upgrade procedure, the skill-listing budget, how to park a task, and the
title-matching history all live there in full.

Measured resident cost per turn, after this session:

| block | chars | who owns it |
|---|---|---|
| the skill listing | 13,000 -> **11,241** | this repo |
| `claude-arsenal/AGENTS.md` | 10,509 | vendored — **already split**, see below |
| `CLAUDE.md` | 8,200 -> **4,845** | this repo |

`AGENTS.md` is not a target. It already does exactly what `CLAUDE.md` now does:
10,509 chars resident against 38,917 held back in `claude-arsenal/references/`,
read on demand. It is 21% resident, and it is the pattern the `CLAUDE.md` split
copied — do not file it upstream as bloat.

The skill listing came down by dropping the identical ~105-character preamble
from all thirteen step descriptions. Budget headroom went 862 -> 1,759 chars, so
the audit's "within 10% of 13000" warning clears **without** the number being
raised. No skill was deleted, and deleting one was considered and rejected:
`init.py` and `arsenal/config.toml` both say in as many words to raise the budget
rather than delete skills to fit it, and S10 already chose the 13,000 with its
~13KB/turn cost written down. For the record, since it was asked and checked —
`.claude/skills/` is host-owned, the init bundle carries no `SKILL.md`, so a
deleted skill would *not* come back at the next upgrade; and a skill can be kept
in the repo but out of the listing by moving its directory outside
`.claude/skills/`.

## A real defect found on the way, and fixed

**T55's naming sweep reported a dishonest zero.** `ALLOWLIST` opened with
`arsenal/` — correct for the ledger's archive, wrong for everything else under
that prefix. Eight **live** task files still named the old package, two of
them inside fenced acceptance-gate blocks — `lo-25b1` ran `python -m
<old>.extraction`, `lo-892b` ran `python -m <old>.connector_exchange`. Those are
commands that run when the task is worked, against a module that no longer
exists. (They are written `<old>` here on purpose: this file is scanned now, and
spelling the name out is what the counter is for.) `verify-gates` does not catch it either — it asserts a fenced
block is *present*, never that the command inside resolves. One of the eight is
`t-20ca057d`, the next task in the queue.

Fixed: the allowlist is narrowed to `arsenal/tasks/_history/` and
`arsenal/tasks/_migrated-history.md`, the nine live files are repointed, and
`test_a_live_task_file_is_counted_even_though_its_archive_is_not` closes the hole
— the previous allowlist test only ever planted a reference in `_history/`, so it
could not have failed. The sweep now reads 0 against 462 files honestly.

**Worth someone's attention:** `verify-gates` asserting presence rather than
resolvability is the general form of this. A gate block naming a module that does
not import would pass today.

## Surface facts now live in `CLAUDE.md`

The `--detect` false `rest`, the `manual POST` claim, why `open_task_pr.sh` cannot
be used here, and merging via MCP are all in `CLAUDE.md` now — they were being
re-derived from this file every session. **REST was confirmed dead this session,
not assumed**: `403 GitHub access is not enabled for this session`, straight from
the proxy. Do not probe it again.

## Left open (carried forward)

- **`claude-arsenal#182`** (false `rest`), **`#183`** (`check_update.sh` on a
  missing remote), **`#188`** (`outline.sh` parsing), **`#189`** (`context_budget.py`
  scores a missing `AGENTS.md` as 0 and passes). All still open upstream.
- **A permissions edit only the owner can make**: `Bash(gh run list:*)` and
  `Bash(gh run view:*)` in `.claude/settings.json`.
- **D-12 (`t-e1ca8374`, #83) still waits on the owner.** Resolution B has existed
  since v0.33.0 (`gate: unmeasured`).
- **`tools/profile_guard.sh` matches a candidate path mentioned in *prose***, not
  only one being opened. Still not seeded.
- **D-22's host half is actionable**: a `make gate` target running all five, for
  `host-gate` to point at.
- **Steps 5, 6, 10, 11, 12 are still `not_implemented`.**
- **One pre-existing board flag**: mixed-priority-convention — 29 tasks use the
  size scale [10, 5, 1, 0] and 2 use other values [70, 60].

## The gate, run locally (CI has no runner minutes)

`make lint` · `make test` · `make evidence` · `make verify-subtree` ·
`make verify-gates`

Latest, on this branch: **1140 passed / 1 skipped**, no evidence drift, 0 diverging
assets of 34, 61 terminal tasks with 61 gates asserted.
