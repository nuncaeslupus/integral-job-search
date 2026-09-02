# Session handover — 2026-09-02 ~11:00 UTC, interactive, laptop

Board: **126 merged of 147** on `main`, 19 open, 1 done, 1 blocked.
Merge policy changed today: **`after-ci-and-review`**, so CI green is now a
condition of merging and not merely a signal.

Nothing identifying the candidate is recorded here, and nothing should be. That
is the rule rather than discretion: identity, history and stated constraints
live in the local profile store, and a document in a public repository keeps
whatever it says forever.

## What landed today

| Task | PR | What it fixed |
|---|---|---|
| T99 | #289 | `connector_policy._as_date` accepted a `datetime` and an unpadded `2026-8-1` |
| T101 | #291 | A CI job could name a Makefile target that did not exist |
| T96 | #287 | A monotone filter consulted the constant, not the data — the expression collapsed to a no-op |
| T83 | #286 | Extra and duplicate attribution rows |
| T95 | #290 | An unstated salary was suppressed to `unknown`; it is shown *marked* now, and an estimate may never read as stated |
| T93 | #292 | Interview direction: recommendation and question judged independently, and a close could recommend applying because a role ranked first |
| T103 | #304 | Merge policy set to `after-ci-and-review`, gated on T101's key **and** a committed green-CI capture |
| — | #260 | Four JSON connector packages, held since 08-31 for a probe. Probes captured live 09-02; `connector_health` **unmeasured → measured**, 16 of 16 probed |
| — | #308 | 47 of 123 merged tasks carried an unticked plan row. Ticked on `main` in `e32a541`; the gate is filed, not built |

## Open PRs, and what each is waiting on

| PR | Task | State |
|---|---|---|
| #295 | T89 | Green, refreshed against main. **CodeRabbit rate-limited** — re-requested; nothing else outstanding |
| #297 | T104 | Second-reader audit done (2 blockers) and fixed; CodeRabbit then found `plan_v2` writes the floor record *before* the floor check. Fix in flight |
| #305 | D-24 | Second-reader audit found **eight fail-open inputs**. Blocking; fix in flight |
| #307 | T98 | Four CodeRabbit findings; three accepted, one rejected with a better fix. In flight |
| #312 | T92 | Fresh. CodeRabbit requested, second-reader audit running |
| #264 | getmanfred | Second-reader audit found **four blockers**. Fix in flight |

## The thing worth reading twice

**The second-reader rule earned its keep today, three times.** Every one of
those audits found defects sitting behind a green `make host-gate`, and in each
case the reason was the one CLAUDE.md names: the fixtures were derived from the
code.

- **#305** — the join between "this was retracted" and "this is approved to
  send" is byte-for-byte string equality. A trailing full stop, a curly
  apostrophe, a doubled space, different casing, NFC vs NFD, or the polished
  version of the sentence all let a withdrawn story reach an employer.
  `_carries`, which normalises shingles for exactly this, sits three functions
  above, unused. And the kind filter is `kind == "episode"` while
  `add_conversation_entry` — the only production path that writes one — stamps
  `kind="statement"`.
- **#264** — the probe is byte-identical to the fixture, which is the defect T72
  fixed, and `T72.json` had already recorded the package `healthy, probed: true`
  on a comparison that could not fail. `ticjob_es` has the same identity
  (pre-existing, filed as #311). Separately, `..` survives `quote(safe="")`, and
  the divergence it creates is measured:
  `Robots().allows(".../x/../jobs?q=python")` is `True` while the resolved
  `/jobs?q=python` is `False`.
- **#297** — the floors it introduced exit **3**, which `Makefile:58-70` maps to
  `"unmeasured (recorded)"` and continues, while the record still claimed
  `measured`. `make host-gate` was green over a board where 126 of 131 gates
  were never read.

That last shape is now the first thing to check on any new gate. `naming._main`
still has it (#309).

## Filed today, unclaimed

| # | What |
|---|---|
| #306 | D-25 — the substance sweep trusts the manifest, so a deleted line whose substance survives in a headline is invisible |
| #308 | A merged task's plan row is never ticked and nothing notices |
| #309 | `naming._main`'s floor exits 3, which `make evidence` records and continues |
| #310 | **`urllib.robotparser` returns the first matching rule, not RFC 9309's longest match** — so on any robots.txt opening with `Allow: /` it answers True to everything and never refuses. `ruled-out.yaml`'s "two matchers must agree" silently degrades to one, fail-open, in the component that exists as the independent check |
| #311 | `ticjob_es`'s probe is byte-identical to its fixture |
| #293 | T105 — `connector_contract._as_date` has T99's two weaknesses |
| #294 | Language parity |
| #296 | Rename `status_is_asserted` — two cold readers misread it the same way |
| #298–#302 | T89 deferred audit findings |

Also seeded with a plan row: **T106** (`t-6b3ce41f`) — ship a cited `taxes/US.json`
from IRS and SSA primary sources and give every tax figure a `citations` entry.
`taxes/` ships only ES and DE, both `source: generated` with every figure
asserted by one prose paragraph citing blogs. `probe_pay` refuses
`source: verified` outright and **stays** refused: that label is a claim about a
person, and T106 builds the layer underneath it, not a way past it.

## Candidate track

Step 0 was run in this session — `.active.json` is bound to it and
`run_checkpoint.py --id <handle>` exits 0. **The binding is per session**, so the
next session must run step 0 again before it can read anything under
`profiles/`; that is `read_active_handle`'s design, not a fault.

Two Spanish deliverables are drafted and **await owner review before anything
goes out**. They are in the session scratchpad, not in this repository, and they
must stay there. Three things the profile actually said, which changed both:

- The 7 pairwise choices price mission alignment and stack modernity at a
  combined **€1,309/month** — more than the net gap between €50k and €75k gross.
  A badly-fitting job has to pay roughly €25k/yr more just to break even, which
  reframes the whole US-vs-EUR question the round was about.
- **`salary.state` is `unknown`** — no floor, no target, ever given. That is the
  one thing to ask for.
- **79 of 105 saved adverts carry no salary**, and most of the 26 that do are in
  złoty. That is T92's accusation, measured on real data.

No dollar figures were shown: there is no `taxes/US.json`, and inventing one at
run time is what T106 exists to replace.

## Worktrees

`../ijs-manfred-conn` stays while #264 is open. The rest are
`.claude/worktrees/agent-*`, each held by a running fix. `../ijs-json-conn` was
removed when #260 merged.
