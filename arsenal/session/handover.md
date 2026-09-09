# Session handover

**2026-09-08 → 09.** Six PRs merged: #418, #421, #422, #423, #424, #425 (and
#428, this one). Four were code PRs and each took **four or five review rounds**.
`origin/main` is at the T122 merge.

An unattended run: one orchestrator holding the GitHub API, workers in linked
worktrees, and a second-reader session per pull request — re-dispatched after
every fix push, because a review of an earlier tree is not a review of this one.

## 1. The number this session exists to record

**Seventeen second-reader rounds. Every single one found something real.** Not
one round came back empty, and no round was cleared to end a loop.

| PR | task | rounds | what the last round still found |
|---|---|---|---|
| #421 | T155 | 4 | three too-fine distinctness keys surviving all 148 tests |
| #422 | T151 | 4 | a figure from a rate-limited session shipped as measured |
| #423 | T153 | 4 | the same shape one step out from **both** of the previous round's fixes |
| #425 | T122 | 5 | the floor's literal-ness argued in the docstring, mandated by T158, pinned by nothing |

Every finding was **fail-open**. Every one sat behind a green `make host-gate`,
a PASS `verified_gate.sh` block, and green CI.

CLAUDE.md says a green gate is necessary and not sufficient. Last session
measured that at 6-of-6 green, 5-of-6 defective. This session measured what
happens when you keep reading: **the defect survives its own fix, repeatedly.**

## 2. One defect family, eight instances, and it is now nameable

The same thing was found eight times across four independent PRs. Several times
it was found **inside the remedy written for the previous instance**.

> **A check pinned against a proxy for the property, rather than against the
> property.**

Its faces, each measured here:

1. **A gate certifying coverage it does not have.** T155's floor claimed "both
   comment orders" while collapsing them to one order left 137 tests green — the
   order test compared state *names*, and its `endswith("first")` filter was a
   no-op because both suffixes end in "first".
2. **A metric independent of its own inputs.** T122: severing either the fixture
   half or the board half left the metric at 0 with 68 tests green.
3. **A floor counting labels, not things.** T155 round two — and then round three
   found the key counted only two of the four fields `read` consumes.
4. **A bound derived from the thing it bounds.** `profile.MINIMUM_FIELDS_CHECKED
   = len(_D6_FIXTURE)` compared against `len(_D6_FIXTURE)`: `len(X) < len(X)`,
   **false for every X**. That floor has never fired and cannot. Filed as T159.
5. **A bound one short of its population.** T122's floor was 12 against a probed
   set of 13, so the first deleted fixture breached nothing — the guard named as
   holding a disclosed residue was silent.
6. **An invariant whose population never reaches the code it is about.** T151
   fixed precedence in two branches and pinned one: reverting the anchored branch
   survived the full green gate at exit 0 with no drift, permitting 38 requests
   the head refuses.
7. **A fixture whose execution path never arrives.** T153: a mutant reverting the
   fix survived because `_borrowed_package` answered first and the test only ever
   reached the code through `measure()`. Green fixture, live defect, one call
   layer apart. **Invisible to reading; only mutation shows it.**
8. **A rule stated, mandated for others, and unpinned in its own instance.** T122
   wrote "commit the floor as a literal" into T158 *in the same diff*, argued it
   correctly in its own docstring — and the exact form it rejects passed all 50
   tests and restored the fail-open.

**The generalisation, and it is the thing to carry forward:**

> **Being right in fact is not the same as being pinned.**

T155's argument for excluding `pr.number` was *correct* — the reviewer checked
the data and confirmed it — and nothing tested it, so the next tidier refactor
would have walked straight through. Same for T122's literal rule. Same for a
docstring citing a rule that does not exist (found four times in `T155.json`'s
shipped evidence).

**What worked against it:** attaching *"before you push, go looking for this
family in what you are about to ship, and report what you found — including
'nothing, and here is where I looked'"* to every fix brief. It paid off **four
times**, each time found by the *implementer* rather than a reviewer — which is
cheaper, since a self-caught finding costs one push instead of a review cycle.
The best of them: T153 found its own `Finding.direction` defaulted to
`"fail-open"` and was never set otherwise, so the committed `fail_open` count was
arithmetically identical to the metric — two numbers that cannot disagree, the
second corroborating nothing. Inside the diff written to name that defect.

**What did not work: enumeration.** Every round that answered a finding with one
more case got another finding. The rounds that ended a thread replaced the
enumeration with a closed rule — T155's twin derived from `dataclasses.fields`
(so a field added later is varied without anyone remembering to), T122's stub
verifier wrong in every direction at once, T151's per-region derivation from RFC
3986's `reserved` production. **An enumeration has no last element.**

## 3. Environment: three facts corrected, two hazards new

**REST works in a cloud session now — and "don't probe it again" is what kept
that hidden.** Corrected in #424 with the measurement. GET and POST are through,
`DELETE` is 403, `git push --delete` still exits 0 having done nothing. Going
public is the cause. Corroborated three times by workers with no `mcp__*` tools
each having `open_task_pr.sh` open its own PR; two flagged it unprompted as
contradicting their brief. **The two-step (push, then open the PR with the MCP
tool) is gone.**

**The `.pyc` trap fires in BOTH directions.** CLAUDE.md documents it as leaving a
*fixed* tree green over unrestored code. Measured here twice, independently, in
reverse: a stale import made a **killed mutant look like a survivor**
(`metric=11` resident, `1` in a fresh subprocess). That manufactures a **false
finding** rather than hiding a real one. **Measure in a fresh subprocess**, not
just with `__pycache__` cleared.

**A merge hazard git cannot see.** Both the T122 branch and main independently
moved `T85.json`'s `gate_modules_discovered` 104 → 105 — for *different* modules
— writing **identical text**. Git merged it silently; the merged tree measures
**106**. `make host-gate` caught it. Two branches making the same textual change
for different reasons is invisible by construction. 22 committed evidence keys
are census-shaped and could take the same path.

**The shared scratchpad is contended.** A concurrent session overwrote another
agent's `mutate.py` mid-run, so one mutation round executed the wrong script
against the wrong worktree. With four agents running mutation cycles at once this
is a live way to certify work that was never done. **Namespace scratch per agent;
never trust a scratch file you did not just write.**

## 4. The rate limit, and the pacing that caused it

The account's 5-hour window was exhausted **twice** (resets 20:50 and 01:50 UTC),
the second costing **nine hours of wall clock**. Cause: 4–5 concurrent Opus
agents, each reporting 135k–280k tokens, roughly 3–4M across ~20 runs. The
orchestrator's own context was barely touched.

The work is expensive by nature — one reviewer ran 54 mutations, another 30, each
re-running a 3,300-test suite. But the same findings were available for less:
**2–3 concurrent agents** (the pipeline serialises on review→fix→re-review
anyway), Opus for reviewers but not for mechanical rounds, and scoped `pytest`
rather than full `make host-gate` on every cycle.

**The crash caused a correctness problem, not just lost time.** A worker was
killed mid-round; the next correctly refused to trust its uncommitted numbers and
said so in the task file — and the same unreproducible "91 of 4,830" figure still
shipped in a module docstring two files away. **Nothing tests prose.** Only a
spot-check found it. If a session is killed mid-round, treat every number it left
behind as unsourced until regenerated.

## 5. Open, and what to pick up

**D-30** (`t-f0f2b642`) — `integral.robots` and `integral.second_reader` disagree
on **150 of 1,836** contested wildcard triples (8.2%), skewed **7:1** toward the
primary matcher being the more permissive side, while
`repo_matcher_verdicts_against_the_rfc` honestly reads **0** across all of it: the
metric's population never reaches the disagreement. RFC 9309's example table
returns *Undefined* for a wildcard rule, so neither reading is refuted. Pinned
`LOW`-confidence in the reader's regression cases only — **never in the
independent case table**, which is the separation T120 exists to protect.

**T159** and **T160** (this PR) — the floor family above, and both literal-pins
missing a rebinding one block deep.

**T158** — T122's detector still reads 0 over a fully-reverted defect when two
signals are removed together; the remedy is a redesign deliberately kept out of
that round.

**T156**, **T157** — the T114 residuals (a paraphrase past the eight-word
shingle; `payload.json` reporting a story as withheld while a headline carries
it).

**T152** still needs a session with egress — this environment's proxy answers 403
to the CONNECT for python.org, and fabricating the capture was correctly refused.

**One known ungated task:** `t-62612ae0` (T124) carries an executable `bash` gate
but no ```` ```gate ```` block and no evidence file. Both readers agree it has no
fence, so it is a genuine gap rather than a reader disagreement — do not
re-investigate that part.
