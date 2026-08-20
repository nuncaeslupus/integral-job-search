# Session handover — 2026-08-20 (D-13 merged; bundle on v0.36.1)

## Read this first

- **D-13 merged** as `bc802f9` via
  [#105](https://github.com/nuncaeslupus/job-search/pull/105), closing #97.
  Task archived at `arsenal/tasks/_history/t-bd59e70b.md`.
- **The bundle is on v0.36.0**, open as a PR on `claude/continue-3avmas`.

`task_select.py` now returns **`lo-9f72` (T55, "Rename the project to
integral-job-search", priority 5)**. The handover before this one said the
remaining divergences were "all priority 10" — **that was wrong.** Only D-17 is
10, and it is blocked on `lo-a22a` (T44). D-16, D-18, D-20, D-21 and D-22 are
priority 5; D-19 is 1. Read the selector, never the D-label order.

## The board fetch dropped `body` — and what that broke

**v0.36.0 is "make context cost a budgeted, enforced constraint"**, and it lands
both context issues this repo filed today. The fetch is now
`number/title/state/labels/assignees` — **~9k tokens down to ~1.2k** — because
`task_id_from_issue` falls back to matching the issue **title** against the task
files' `title:`. The injected protocol block in `CLAUDE.md` says so now.

**Nothing had ever compared those two strings before, and both sides were
spelling titles differently.** Fourteen live tasks silently stopped resolving.

**v0.36.1 closed all of it** (`claude-arsenal#186`) — and closed more than the
half this session reported at first. Verified in the vendored source, not taken
from the release note:

- `normalise_title` HTML-unescapes (the MCP tool escapes `<`, `>`, `&`);
- the front-matter parser decodes `\uXXXX` in a double-quoted scalar;
- `issue_import.py` and `arsenal_migrate.py` write with `ensure_ascii=False`,
  so **the writers no longer emit escapes** — the "decode it by hand if you see
  one" instruction an earlier draft of `CLAUDE.md` carried is obsolete;
- `handle_sync.py` warns on a near title match rather than proposing a handle.

The 36 task files this repo decoded are correct and stay decoded. Verified on
the real board: no unresolved tasks, and `handle_sync.py` reports every task has
an issue handle.

**`query_status.py` is the detector for this class of failure** — it names
exactly which tasks did not resolve. Trust that list over `handle_sync.py`'s,
which proposes a new issue for whatever it cannot resolve: on a bad fold that
means duplicate handles for tasks that already have one.

## Five issues filed upstream, two already shipped

| issue | what | status |
|---|---|---|
| [#181](https://github.com/nuncaeslupus/claude-arsenal/issues/181) | the fetch pulls every body for one id per issue (~9k) — proposed a title fallback | **shipped in v0.36.0** |
| [#184](https://github.com/nuncaeslupus/claude-arsenal/issues/184) | no cheap way to read a precedent module's shape | **shipped** as `bin/outline.sh` |
| [#186](https://github.com/nuncaeslupus/claude-arsenal/issues/186) | the title fallback loses titles containing `<`, `>`, `&` | **shipped in v0.36.1** |
| [#188](https://github.com/nuncaeslupus/claude-arsenal/issues/188) | `outline.sh`: bare `function name {` missed, JS control flow printed as declarations, column-zero assignments in a body | open |
| [#189](https://github.com/nuncaeslupus/claude-arsenal/issues/189) | `context_budget.py`: a missing `AGENTS.md` scores 0 and passes the gate; unguarded reads crash | open |
| [#182](https://github.com/nuncaeslupus/claude-arsenal/issues/182) | `--detect` prints a false `rest`: the proxy answers `/rate_limit` itself | open |
| [#183](https://github.com/nuncaeslupus/claude-arsenal/issues/183) | `check_update.sh` calls a missing remote "the bundle was copied, not a subtree" | open |

**#183 is confirmed by this session's own upgrade**: `make arsenal-remote` added
the remote and the subtree then merged cleanly. The bundle always was a subtree;
only the remote was missing, exactly as the issue says.

**Use `claude-arsenal/bin/outline.sh <file>`** before reading a module whole.
That is what #184 bought, and this session paid ~6k learning why.

## D-13, and the shape that appeared four times

A fifth cross-cutting rule — **"Say what is happening before a silence"** — in
`status/spec-v2-steps.md` *and* §5.4 of `status/spec-v2-process.md`, carried by
all thirteen step skills with a worked example each, measured by
`jobsearch.step_narration` over four limbs.

**The rule was absent, not broken.** §5.4's *say why* governs the subject of a
step and says nothing about the seconds spent executing inside it.

Qodo's review found three real defects. **All three, plus one found before the
review, are one shape:**

> **A requirement stated in prose and checked by its own name is not checked.**

1. limb 3's subject detection searched the prose for "creates their profile" —
   and matched all thirteen skills, because the shared rule sentence names
   profile creation. Twelve false offenders.
2. the rule's own heading carries a subject token *and* the governor `before`,
   so a Protocol section stripped to nothing but the heading passed limb 1.
3. twelve of thirteen examples opened a silence and never closed it — the rule
   requires both halves, and nothing measured the closing one.
4. the spec-drift test asserted the rule's *title* appeared in both documents,
   so either could gut the requirement and still pass.

**Expect a fifth.** When adding a check, ask what the *conforming* text will
contain, and whether that text alone would satisfy the check.

One review finding was **not** fixed: Qodo wants
`test_<what>_<condition>_<expected_result>` naming, which
`.claude/skills/execution/SKILL.md:71` does state. Answered on the thread — the
file's ~40 tests all use the prose form, `status/plan.md` prescribes one of the
new names verbatim, and the convention belongs to task payloads. The owner
merged over it, so it stands; a repo-wide rename would need its own task and
would touch the plan rows `make verify-gates` reads.

## Context economy — measured, since the owner asked

| item | cost | note |
|---|---|---|
| task-issue fetch | **~1.2k** | was ~9k — v0.36.0's title fallback |
| MCP tool schemas (github + CCR) | ~12k resident | most of github's 60 tools are deferred |
| system tools + prompt | ~30k | fixed |
| `handover.md` | ~2k | **not** worth shrinking; it stops re-derivation |
| `AGENTS.md` + `CLAUDE.md` | ~6k | already won by #177's chunking |

**Gmail/Calendar/Drive are deleted** — `ListConnectors` returns `[]`. That
carry-forward item is closed; do not re-add it.

`claude-arsenal` is attached via `add_repo` for issue filing and **deliberately
not cloned** — the API is all a filing session needs.

## CI is still out of runner minutes

Confirmed on every head of #105 — `d4ff6d2`, `e97aa72`, `eca6bd6` — five checks
failed each time, `runner_id: 0`, empty `runner_name`, jobs completing **2–4
seconds** after they start. No runner is ever assigned. Not the diff.

All five gates run locally before each push:

```bash
make lint && make test && make evidence && make verify-subtree && make verify-gates
```

Latest: `make test` 1126 passed / 1 skipped · `make evidence` no drift ·
`make verify-subtree` 0 diverging, **34** assets · `make verify-gates` 60
terminal tasks, 60 gates asserted, 0 without a fenced block.

## Surface facts

- **`github_channel.sh --detect` prints `rest`, and `rest` does not work here**
  (filed as #182). Use the MCP tools and hand-write the JSON the scripts read.
- **`claim_task.sh` returns `manual POST`**; `create_branch` on
  `arsenal/claims/<id>` is the compare-and-swap. 201 = won, 422 = lost.
- **`open_task_pr.sh` still cannot be used** — it cuts a branch off the default
  branch, and this surface restricts pushes to the session's designated branch.
  Archive, `Closes #<issue>` in both commit and PR body, and the PR by hand.
- **Merging works** via the MCP `merge_pull_request` tool.

## Left open (carried forward)

- **`claude-arsenal#188` and `#189`** are open, both found by Qodo reviewing the
  upgrade and both verified before filing. `#189` is the sharper one: a bundle
  missing `AGENTS.md` scores zero resident tokens and reports "Within budget",
  and `--fail-over` is now wired into upstream CI.
- **A permissions edit only the owner can make**: `Bash(gh run list:*)` and
  `Bash(gh run view:*)` in `.claude/settings.json`.
- **`tools/profile_guard.sh` matches a candidate path mentioned in *prose***,
  not only one being opened. Still not seeded.
- **D-12 (`t-e1ca8374`, #83) still waits on the owner.** Resolution B has
  existed since v0.33.0 (`gate: unmeasured`).
- **`claude-arsenal#180`** — `open_task_pr.sh` reads `host-gate` from the git
  root and runs it in the cwd. Inert here while `host-gate` is unset.
- **D-22's host half is actionable**: a `make gate` target running all five, for
  `host-gate` to point at.
- **Steps 5, 6, 10, 11, 12 are still `not_implemented`**, and steps 8 and 9
  certify over unbuilt gates until D-21 lands.
- **One pre-existing board flag**: mixed-priority-convention — 29 tasks use the
  size scale [10, 5, 1, 0] and 2 use other values [70, 60].
