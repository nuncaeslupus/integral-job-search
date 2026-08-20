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

Measured resident cost per turn, for whoever picks this up:

| block | chars | who owns it |
|---|---|---|
| the skill listing | ~13,000 | this repo — **the largest lever left** |
| `claude-arsenal/AGENTS.md` | 10,509 | vendored; upstream's to shorten |
| `CLAUDE.md` | 4,845 | this repo (was 8,200) |

**The skill listing is the next real saving and it is not yet taken.** Thirteen
step skills open their `description` with the same ~105-character preamble, ~1,365
characters of pure repetition charged on every turn including sessions that never
load a step skill. Trimming it needs `skill-creator` opened first (repo rule),
touches 13 files, and moves the `integral.skill_budget` measurement — so it wants
its own task and its own review, not a fold-in.

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
