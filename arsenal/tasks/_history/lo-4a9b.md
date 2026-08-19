---
id: lo-4a9b
title: "S9: convert claude-arsenal from a vendored copy to a git subtree"
priority: 30
workspace: SOLO
tags: [infra]
status: merged
pr: https://github.com/nuncaeslupus/job-search/pull/24
---

Owner request, 2026-08-18: *"I'd like to have it as a subtree, not as a
version-vendored copied code. The goal is to use it later as a sub-repo inside
this one."*

## What was measured, not assumed

The upstream repository `nuncaeslupus/claude-arsenal` was cloned and compared
against the vendored bundle (HEAD `f84b4eff…`, which is exactly the `ARSENAL_SHA`
the Makefile pins). Findings:

- **25 of the 26 vendored files are byte-identical to upstream.** The only
  difference is `session/handover.md`, which is a template upstream and live
  host state here. There is no drift to reconcile.
- Upstream's bundle does **not** live at the repository root. It lives at
  `plugins/core/skills/init/assets/` and is *assembled* into `claude-arsenal/`
  by the init skill and `scripts/vendor-skills.sh`.
- `claude-arsenal/queue/` (65 tracked files: the ledger and every task payload)
  and `claude-arsenal/session/handover.md` are **host-owned state living inside
  the same directory** as the vendored bundle.

## Why a subtree at `claude-arsenal/` cannot work

Two independent blockers, neither of them a session or tooling limitation —
this fails identically on a laptop:

1. **`git subtree` maps a prefix onto the upstream repository *root*.** There is
   no way to map `plugins/core/skills/init/assets/` onto `claude-arsenal/`. A
   `git subtree add --prefix=claude-arsenal arsenal <ref>` would drop the entire
   marketplace repo — `plugins/`, `docs/`, its own `Makefile`, `pyproject.toml`,
   `uv.lock`, `.github/` — into `claude-arsenal/`, and not one path the session
   protocol calls (`claude-arsenal/bin/queue_branch.sh`, `bin/gate_run.sh`,
   `scripts/update_task_row.py`) would exist.
2. **A subtree prefix must hold only upstream content.** The queue ledger and
   payloads are the single most important host-owned state in this repository
   and they live inside the candidate prefix. Every `git subtree pull` would
   fight 65 files upstream has never heard of.

## The conversion that does work

Subtree upstream at a **separate prefix**, and keep the assembled bundle where
the protocol expects it:

```
vendor/claude-arsenal/        ← git subtree of the upstream repo (real history)
claude-arsenal/bin,agents,…   ← assembled from vendor/, as today
claude-arsenal/queue,session/ ← host-owned, untouched by any subtree operation
```

Steps:

1. `git subtree add --prefix=vendor/claude-arsenal arsenal v0.23.1 --squash`
   (`--squash` keeps this repo's history readable; drop it if full upstream
   history is wanted for `git log`/`bisect` across the boundary).
2. Repoint `make update-skills` at `vendor/claude-arsenal` instead of cloning
   into a temporary directory.
3. **Delete the `ARSENAL_SHA` pin.** It exists only because `update-skills`
   executes `vendor-skills.sh` straight out of a fetched checkout and a tag can
   be moved by anyone with upstream push access. A subtree records the exact
   commit in its merge, so the pin becomes redundant — that is the concrete win
   here, not tidiness.
4. Upgrades become `git subtree pull --prefix=vendor/claude-arsenal arsenal <tag>`
   followed by re-running the assembly, replacing the clone-and-copy path.
5. Keep `make arsenal-remote` — a subtree still needs the remote, and a remote
   is local config that no clone inherits.

## What is already done (do not redo)

- The `arsenal` remote is wired up and `make arsenal-remote` makes it one
  command per clone. `check_update.sh` is no longer inert and currently reports
  the bundle **current with the newest tag**.

## Acceptance gate

`vendor/claude-arsenal` is a real subtree (its add/pull commits are in
`git log`), the assembled bundle under `claude-arsenal/bin` and
`claude-arsenal/scripts` is byte-identical to `vendor/`'s assets, `ARSENAL_SHA`
is gone from the Makefile, and no host-owned file under `claude-arsenal/queue/`
or `claude-arsenal/session/` sits inside a subtree prefix.

```bash
uv run pytest tests/test_arsenal_subtree.py -q
uv run python tools/verify_arsenal_subtree.py --write-evidence
```

```gate
vendored_files_diverging_from_subtree == 0
evidence: status/evidence/S9.json
key: vendored_files_diverging_from_subtree
```

## Tests

`test_every_bundle_file_matches_the_subtree_source` — the assembled bundle is a
function of `vendor/`, so a hand-edit to `claude-arsenal/bin/*.sh` is caught
rather than silently surviving the next upgrade;
`test_no_host_owned_path_is_inside_a_subtree_prefix` — the queue and session
directories must stay outside, or an upgrade eats the ledger;
`test_the_makefile_no_longer_pins_a_bare_sha`.

## Location

`Makefile`, `vendor/claude-arsenal/` (new), `tools/verify_arsenal_subtree.py`
(new), `tests/test_arsenal_subtree.py` (new)
