# Session handover — 2026-08-18 (T51 session)

## State

**T51 is done against PR #36 — but the session's real finding was in the queue,
not in the code.**

| what | where |
|------|-------|
| T51 — `$INTEGRAL_HOME` resolver, candidate state refused inside any git work tree | PR #36 (open) |
| 17 stale queue rows advanced to `merged` | `arsenal-queue` commit `6c271e8` |
| S10 (`lo-5efb`) recorded `blocked` — it is waiting on an upstream change, not on work here | `arsenal-queue` commit `f48627c` |

## Read this first: the ledger had drifted, and the loop was about to re-do merged work

`queue_eval.sh` handed out **S7 (`lo-9ff0`) — merged in PR #23 in July.** It was
not a fluke. Comparing `origin/main`'s `tasks.jsonl` against `arsenal-queue`'s
found **17 rows** that main records as `merged` (PRs #23, #24, #25, #27, #28)
and the coordination branch still recorded as `open`, plus one (`lo-2293`,
T29) that the coordination branch had `done` and main still has `open`.

The cause is structural, not a slip: **`queue_sync.sh` ports rows that are
*absent* and by design "never touches existing claim/release state."** So a
status recorded on main — by a laptop session running `reconcile_merged.sh`, or
by session-end housekeeping that commits `tasks.jsonl` — never reaches the
coordination branch, and nothing detects it. `queue_doctor.sh` reported **0
findings** both before and after: it audits one ledger for internal
consistency, and cross-branch divergence is outside what it looks at.

**Both are worth an upstream issue** (`claude-arsenal`): a `queue_sync.sh
--reconcile-status` that advances a row when the default branch's status is
strictly further along the lifecycle, and a `queue_doctor.sh` check that
compares the two ledgers at all. Until then, **diff the two ledgers by hand at
session start** — the reconcile script used here is a dozen lines and worth
carrying upstream rather than rewriting.

`lo-2293` (T29) is still `open` on main while the coordination branch says
`done`. A laptop session should run `reconcile_merged.sh` and commit the
result, which also flips it to `merged`.

## T51, in one paragraph

`jobsearch.state_home` resolves the store root from `$INTEGRAL_HOME`, then
`$XDG_DATA_HOME/integral-job-search`, then `~/.integral-job-search` — and
**refuses any path inside a git work tree**, with `--dev` / `INTEGRAL_DEV=1` as
the single explicit escape. Containment walks the resolved path's own ancestry
rather than comparing against this repository (a store inside *any* checkout is
the failure), and `.git` is tested with `exists()` because a linked work tree
and a submodule carry it as a file. Every call site now resolves through it:
`identity.DEFAULT_PROFILES_ROOT` became the lazy `default_profiles_root()`, and
the thirteen step checkpoints default `--input-dir` to the resolver. Gate:
`state_paths_inside_a_repo == 0` over `paths_checked = 22` (8 probes + 14 call
sites). Spec §6 now states where the tree actually roots.

## Two lessons worth carrying

1. **Evidence must be a function of the repository, not of the run.** T51's
   probes build a throwaway git work tree, and `mkdtemp`'s name landed in the
   committed evidence — so CI's "evidence is current" failed on a repository
   nobody had touched. It passed locally only because `make evidence` compares
   with `git diff`, which **does not see untracked files**: the check has no
   teeth until the evidence is committed. Temp paths are now redacted to
   `<tmp>`, with a test that two measurements are equal.
2. **An audit that reads source has to read *code*.** The call-site scanner
   first reported `identity.py`'s own paragraph explaining what T51 removed as
   an instance of it. `tokenize` now blanks comments and docstrings — but
   deliberately *not* ordinary string literals, because the construction being
   hunted ends in one (`… / "profiles"`). And a file that cannot be tokenised
   is a finding, never a silent pass: `SiteCheck.passes` reads "no recorded
   reason", after the flag-based version let an unparseable file through clean.

3. **A guarantee enforced on one path, while a second path walks around it.**
   Review (Qodo) found both halves of this, and both were real. The thirteen
   checkpoints took `--input-dir` as a bare `Path`, so `--input-dir ./profiles`
   wrote a candidate's session file into the clone with nobody passing `--dev` —
   the resolver was airtight and the flag beside it was not. Worse, **the gate
   had the same hole one level up**: the audit asked only "does this file
   resolve through the resolver?", which all thirteen satisfied while every one
   of them took the flag unguarded, so it measured 0 over a live leak. The
   containment rule is now a function (`ensure_outside_a_work_tree`) both ways
   in must call, and a site that accepts an explicit root must name it.
   The second half: the leak count read the dev escape as "the variable is
   present" while `dev_mode` authorises only `1/true/yes/on`, and the exit
   status keyed on the metric while `shortfalls` was already populated and
   ignored — so a demonstrably broken gate could exit 0. **When adding a gate,
   ask what a *second* way in would do to it.**

## Queue state

`queue_batch.sh` now offers, in order: **T25 (`lo-1af2`, `[LAPTOP]`)** — skip in
a cloud session — then **T14 (`lo-3100`)**, **T52 (`lo-b2de`, now unblocked by
T51)**, **T53 (`lo-803e`)**, **T55 (`lo-9f72`, the rename)**.

S10 is `blocked`, not open: `LISTING_BUDGET_CHARS = 8000` is still a module
constant in the vendored `audit_library.py` with no override, so
`claude-arsenal` issue #143 has to land first. Confirmed against the subtree
this session — do not re-dispatch it.

## Still the owner's

Whether the sources repository is public from the start, and whether this
repository is public. Neither gates any task above.

## Next action

Watch PR #36 to green and merge, then **T52** (first-run bootstrap — T51 is its
dependency and just landed) or **T55** (the rename, best done before T52–T54
build on the old name).
