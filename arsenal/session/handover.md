# Session handover — 2026-08-28 ~22:30 UTC, interactive, laptop

Board: **116 gates on `main`** (`dfe66a0`), 129 tasks — 115 merged, 10 open,
1 blocked, 1 done, 2 cancelled, 0 claimed. Those sum to 129: `query_status.py`
counts `blocked` separately from `open`, so an "open + merged" reading of this
board is short by four. `make host-gate` exit 0: ruff clean, mypy clean over 172 files,
`evidence: no drift`, `verify-gates: 116 terminal task(s); 116 gate(s) asserted,
0 carry no fenced gate block`. `query_status.py` reports **no problems**.

The session was asked whether the tool is ready for a live candidate session,
and to clear whatever needed a laptop or a browser first.

## Answer: yes, sourcing is ready

**T72 merged** ([#256](https://github.com/nuncaeslupus/integral-job-search/pull/256),
closes #203) and archived ([#257](https://github.com/nuncaeslupus/integral-job-search/pull/257)).
`trabajos.com` — the only real board — is **verified healthy against live
markup**: 40 baseline items, 40 probe items, `silent_connector_failures: 0`,
`gate_status: measured`. Live `robots.txt` re-checked and it matches
`meta.yaml`'s claim exactly: four disallowed paths, none of them the listing
read, no AI-agent rule.

The detector is not a tautology — renaming `listado2014` → `listado2099` in the
probe flips it to `broken` with *"40 row(s) recorded previously, 0 now"*.

## What finished T72, and the design fork behind it

The module could only report `measured` on a machine holding an uncommitted
`probe/list.html`, and it is in `repo_gate --list-evidence-modules` — so
`make evidence` regenerates it on every clone, CI run and cloud session, where
the probe is absent and the answer is `unmeasured`. **No committed number could
satisfy both.** Measured both ways before touching anything.

The owner chose: **commit the probe, with `probe/captured.json` recording when
it was taken.** The date is read from that file and never from mtime — a
checkout does not preserve mtimes, so deriving it there would give every clone a
different answer and drift `make evidence` on a file nobody edited. Baseline and
probe stay two captures from two different days, so the comparison still means
something; what changed is that *how current is it* is now a date in a diff.

**What this does not buy, and the docstring says so:** nothing forces a refresh.
A probe left alone certifies a board that may since have rotted. The rejected
alternative — `unmeasured` past N days — turns `main` red on a timer for
everyone until someone with a laptop recaptures.

## The probe leaked a home IP, and the guard could not see it

`trabajos.com` writes `<!-- IP: … - CODPAIS:100 -->` into every response, and it
is the **client's** address. `meta.yaml` already recorded that the fixture was
redacted for this reason and
`test_no_committed_fixture_carries_an_ip_address` existed to enforce it — but it
scanned `fixture/*.html`, so the capture in `probe/` walked past it.
`tools/publish_connectors.py` `copytree`s the whole package into the **public**
sources repository. It would have been published.

Redacted in raw bytes; the guard now scans **every recorded page in every
package**. Its own docstring had argued *"the next board will write it somewhere
else"* — what happened is the same board wrote it in the next directory over.

## Four defects, three review rounds — the second-reader rule again

CodeRabbit went 🟡 → 🟡 → ⚪ Minimal. Every finding was in code written this
session, behind a green gate:

1. A regular file named `probe` passed rule 1 — `probe` joined `OPTIONAL_ENTRIES`
   and inherited the exemption from "unexpected entry" without inheriting the
   type check `fixture` has.
2. Every non-empty string was accepted as a capture date; `{"captured_at":
   "unknown"}` was emitted beside `gate_status: measured`.
3. `strptime("%Y-%m-%d")` accepts unpadded components, so `2026-8-28` passed.
   **The round-2 commit's comment claimed "one spelling or none" and did not
   deliver it** — a guarantee written into prose without a test. Fixed by
   round-tripping the parsed date.

Plus the IP leak, which no reviewer caught — it was found by reading
`meta.yaml` before committing. All three CodeRabbit fixes were verified RED
against the previous commit before landing.

## Board defects fixed this session

- **#254 reopened.** PR #255 was queue-only but wrote `Closes #254`, so merging
  closed D-25's own handle while the task sits unstarted.
- **#253 retitled** to `D-24: A retracted episode stays sendable — approval
  outlives its evidence`. The protocol fetch drops issue bodies, so the
  `arsenal-task:` line is unreachable and the board resolves by **title** —
  which did not match. It resolves now.
- **T72's task file archived by hand** (#257). `open_task_pr.sh` still cannot
  open a PR in this repo (`claude-arsenal#256`), so #256 was branched,
  committed, pushed and opened manually — and nothing performed the archive
  step. **Check for this after any hand-opened PR.**

## Plugins updated — the bundle re-vendor is the NEXT session's first job

`claude plugin update` is a **non-interactive CLI** and it works; `/plugin
update` typed at the model does nothing. All three are now **2.5.0** on disk:

| plugin | scope | was | now |
|---|---|---|---|
| `core@claude-arsenal` | user | 1.1.0 | 2.5.0 |
| `core@claude-arsenal` | project | 1.1.0 | 2.5.0 |
| `skill-workshop@claude-arsenal` | user | 1.1.0 | 2.5.0 |

Both `core` entries were **`failed to load`** before this — a hook schema error,
`hooks.SessionStart[0].hooks: expected array, received undefined`. Worth
confirming that cleared after the restart.

**The vendored bundle is still 2.4.23.** It was deliberately not re-vendored
here: `.claude/skills/init/scripts/init.py` is the 2.4.23 copy, so running it
would have vendored 2.4.23 over itself — a no-op, not an upgrade. The upgrade
needs the restarted session's loaded 2.5.0 skill. The 2.5.0 script is on disk at
`~/.claude/plugins/cache/claude-arsenal/core/2.5.0/skills/init/scripts/init.py`
if the restart does not pick it up. That re-vendor is a real diff and wants its
own gate and PR.

## For the live session

The owner is the candidate; **test-mode on** was agreed, because D-25's gate
needs observations carrying provenance and `test-mode` (S11) is the instrument.
No `profiles/` directory exists yet, so this is the first candidate.

- **Have the CV to hand** — step 1 captures it with provenance.
- **T20's blind ranking must happen before step 9.** `rank_spearman >= 0.60` is
  scored against a manual ranking of 20 held-out ads; seeing the tool's ordering
  first contaminates it. The command exists (T20a built it) and writes `null`
  for want of the rankings.
- Expect the reading step to be visibly mediocre: `extraction_macro_f1` is
  **0.4943** against a 0.75 target, `scored_n: 161`, label floor met at 206.

Four tasks carry `requires: [surface:human]`: **T69, T20, D-23, D-25**.

## The connector system — asked and answered

**Solid, not fast.** The docstrings reason about failure modes that were
actually hit, not imagined ones: the annotator's output is frozen data so the
gate cannot recompute both sides and agree with itself; item count sits *inside*
the T12 F1 so parsing 20 of 40 offers perfectly cannot score well. Three real
weaknesses, filed here rather than as tasks — the owner chose "go live" over
queueing them:

1. **Coverage is the ceiling, and it is not a code problem.** One real board.
   `tecnoempleo` and `remoteok` are `Disallow: /` for ClaudeBot; `weworkremotely`,
   `remotive`, `getmanfred`, `feinaactiva` and EURES serve listings as JSON APIs
   or JS apps, so a CSS-selector engine has structurally nothing to select. Four
   of the five sources the 208-ad corpus came from are unreachable by this
   design. Breadth needs a second connector *kind*, not better selectors.
2. **`connectors.py` hand-rolls a CSS engine and a DOM tree** — ~280 of its 1238
   lines — to keep the T12 gate dependency-free, while lxml and BeautifulSoup are
   already a dev extra for the annotator. Largest correctness surface in the
   system, and it exists to avoid a dependency that is already in the file.
3. The probe freshness model, above.

## Next

1. **Re-vendor the bundle to 2.5.0** and open a PR for it (step 0b).
2. `task_select.py` returns **T73** (`t-52bb1ec0`, priority 10, dep T72 now
   merged) — a rate-limited run is inconclusive, never broken. Codeable, no
   human needed. It and T83 were blocked on T72 until today.
3. The live session itself.

## Loose ends, neither urgent

- Two stale worktrees from an earlier session, **both clean, no uncommitted
  work**: `/home/ivant/dev/ijs-t87` (`chore/seed-t87`) and
  `/home/ivant/dev/ijs-t87b` (`task/t-57cd25d8`). Left alone rather than removed.
- CI is still the documented private-repo billing signature: every job red in
  5–6 s, `runner_id: 0`. `merge-policy` is `after-review` for exactly this
  reason; both merges today were on CodeRabbit's verdict, not CI's.
