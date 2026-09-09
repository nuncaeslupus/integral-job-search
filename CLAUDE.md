<!-- claude-arsenal: auto-managed -->
## Automatic session protocol

Every session, without waiting to be asked:

1. Read `arsenal/session/handover.md` for the previous session's context.
2. List the repository's issues labelled `arsenal:task` — **open and closed** — and
   save the JSON. Use whatever GitHub access this surface has; run
   `claude-arsenal/bin/github_channel.sh --detect` to find out which. Request
   `number`, `title`, `state`, `labels`, `assignees` and **not `body`** — the bodies
   are the bulk of that fetch and nothing downstream reads them.
3. Run `python3 claude-arsenal/scripts/query_status.py --issues <that file>` for the
   board, and report anything it flags.
4. Pick up work: `python3 claude-arsenal/scripts/task_select.py --issues <that file>`
   returns the next unblocked task, then
   `bash claude-arsenal/bin/claim_task.sh <id>` takes it (see `@claude-arsenal/AGENTS.md`).
   - **Nothing returned + workspace plans exist** → seed tasks from each plan.
   - **Nothing at all** → ask what to work on.
5. Open each task's PR with `Closes #<issue>` so merging it closes the task by itself.
6. After any session with tasks: update `arsenal/session/handover.md`.

@claude-arsenal/AGENTS.md
<!-- /claude-arsenal: auto-managed -->

> **That protocol is the ORCHESTRATOR's, not every session's.** It is injected by
> `/init` and says "every session", which was true when every session was
> interactive. It is not true now: a **spawned child reads this same file** and
> cannot perform steps 2, 4 or 5 — it has no GitHub API at all (see "No session this
> one spawns can reach the GitHub API" below). A child that tries them blocks, which
> is exactly what happened to three workers on 2026-08-25.
>
> So a child runs **only** step 1 (read handover, optional) and the work itself. Its
> orchestrator hands it the task id, issue number and title, and it stops after
> pushing. Do not edit the block above to say so — it is auto-managed and `/init`
> will overwrite it; this note is the host-owned place to record it.

## The GitHub channel depends on the surface — detect it, don't assume

`bash claude-arsenal/bin/github_channel.sh --detect` answers this, and its answer
differs per surface. Run it; trust it over any memory of what worked last time.

**On this laptop it prints `gh`, and `gh` auth is live.** Use it for every GitHub
step of the protocol. `claim_task.sh` and `open_task_pr.sh` work as documented —
no workaround is needed, and reaching for one costs a session real time.

**In a cloud session it prints `rest`, and REST now WORKS there — reads and writes
both.** This paragraph said the opposite until 2026-09-08, and said "don't probe it
again", which is the instruction that would have kept it wrong. Re-measured on that
date against the live proxy:

```text
github_channel.sh --detect                      rest
GET  /repos/.../issues/417                      200
POST (open_task_pr.sh's own last step)          opened PR #421 unaided
DELETE /repos/.../git/refs/heads/probe/…        403
git push --delete probe/…                       silent no-op, ref survives
```

**Going public is what changed it** — the same single cause behind CI having minutes
again, and the `claude-arsenal#182` 403 was a private-repository symptom. So the
split is now by **method**, not by channel: GET and POST are through, and only the
destructive verbs are refused.

What that changes in practice:

- **`open_task_pr.sh` runs end to end, last step included.** It resolves the issue,
  cuts the branch off `origin/main`, runs the gate, commits, pushes **and opens the
  pull request**. Measured on T155: the script opened #421 by itself from a spawned
  worker with no MCP tools at all. `ARSENAL_TASK_ISSUE=<n>` is still worth passing
  when the caller already knows the number — it skips a lookup — but it is no longer
  load-bearing, and the "let it push, then open the PR with the MCP tool" two-step is
  no longer needed. The script writes only the **title** into the commit message, so
  a substantive message still has to be amended on afterwards.
- `claim_task.sh` may return `manual POST` on this surface anyway; `create_branch` on
  `arsenal/claims/<id>` remains the compare-and-swap either way. **201 = won,
  422 = lost.**
- **Remote ref deletion is still blocked, and now by two routes.** `git push --delete`
  reports `send-pack: unexpected disconnect`, then `Everything up-to-date`, then exits
  **0** with the ref still there; REST `DELETE` answers 403. Never script a branch
  cleanup here — it looks like a failure and is actually a no-op, and there is no
  working substitute. `refs/heads/probe/channel-remeasure` is the artefact of this
  measurement and could not be removed afterwards, which is the evidence.
- Merging works, via the MCP `merge_pull_request` tool or REST.

**The MCP GitHub tools remain the right channel for an orchestrator**, because they
are the only one a session has without reaching for a token. But REST being alive
matters for the half of the fleet that has no MCP tools at all: see the next section,
whose conclusion this narrows rather than overturns.

## No session this one spawns has `mcp__*` tools — and that is now a smaller fact than it was

**A spawned session has no `mcp__*` tools.** That much is still true, holds for both
ways of making one, and is worth stating first — but read to the end of this section
before concluding anything about what a child can do, because the heading here said
*"cannot reach the GitHub API"* until 2026-09-08 and that conclusion is now wrong:

- A Routine with `create_new_session_on_fire` says so at creation: *"this trigger
  stores no MCP connectors, so the sessions it fires will run without connector
  tools"*, and the fired session's `allowed_tools` carry no `mcp__*` entry.
- A `create_session` child carries no such warning but behaves identically — measured
  2026-08-25, two children reported *"GitHub access denied (403); no MCP tools
  available to fetch task board"* and blocked. **Do not assume a child inherits the
  parent's connectors.** It does not.

**That premise held only while REST was 403, and it no longer is.** A spawned session
has two channels, not one: plain `git`, and REST. `git` alone is enough to fetch, to
read claim refs (`git ls-remote origin 'refs/heads/arsenal/claims/*'`), to derive
terminal state from `arsenal/tasks/_history/*.md` (each archived file carries
`status: merged`, and `effective_state` reads it), and to **push a branch**. REST adds
what `git` could not do: read issues, label and assign, **open a pull request**, merge.

The measurement that changed this: on 2026-09-08 a `create_session`-equivalent worker
with no `mcp__*` tools ran `open_task_pr.sh` and the script **opened #421 itself**.
Its last step is REST, and it went through.

**The split below is therefore no longer forced by the channel — but keep it anyway,
for the reason `worker-loop.md` gives rather than the one this file used to give:**
*"workers never claim or release: the orchestrator owns the claim."* A claim is a
compare-and-swap that decides which of several sessions does a task, and it belongs to
whichever session can see all of them. Nothing about REST changes that, and a worker
that starts claiming for itself recreates the double-claims the ref exists to prevent.

| | holds the GitHub API | does the work |
|---|---|---|
| **Orchestrator** — an interactive session, woken by a **self-bound** routine (omit `create_new_session_on_fire`) | yes | fetch the board, claim with `create_branch` (201 won / 422 lost), dispatch children, review, merge |
| **Child** — one per task, via `create_session` | REST only, and only for its own task | worktree, implement, `make host-gate`, `open_task_pr.sh` **through to the opened PR**, then stop |

What genuinely changed for a child is the last column: it now finishes at an open pull
request rather than at a push, so the orchestrator no longer has to open one on its
behalf. Two things follow. The script writes only the **title** into the commit
message, so a child that wants a substantive one amends it after the script returns.
And the child should still be **told** its task id, issue number and branch name — it
can now resolve them, but a child that never has to guess cannot guess wrong, and it
ends when its task does, which is what keeps an unattended run from ever needing to
compact.

Steps 3 and 4 of the protocol need no workaround on either surface — **in an
orchestrator session**, run them as written; a child runs neither. Since the fetch drops `body`, issues resolve to tasks by **title**;
v0.36.1 made that robust and `query_status.py` names anything that still fails to
resolve. Trust that list over `handle_sync.py`'s proposals — only one of the two is
wired to an action.

## Two to three concurrent workers, not five — the quota is shared and the pipeline serialises anyway

**Run 2–3 agents at once.** The account's usage window is a rolling five hours
shared by the orchestrator *and* every session it spawns, and it is easy to spend
without noticing: on 2026-09-08/09 it was exhausted **twice**, and the second
exhaustion idled the run for **nine hours**.

The arithmetic, so the number is not a guess. Each agent reported **135k–280k
tokens** on completion; twenty-odd runs is roughly **3–4M**. The orchestrator's own
context was barely touched — this is entirely the fleet. And the work is expensive
by nature rather than by waste: one reviewer ran 54 mutations, another 30, each
re-running a 3,300-test suite, and `verified_gate.sh` checks out a clean tree and
runs the whole gate again.

**Higher concurrency buys less than it looks like it should**, because the loop is
implement → review → fix → re-review and each stage waits on the last. Five agents
running means four PRs in different stages plus idle capacity, not five times the
throughput. Three is enough to keep every stage fed.

Three cheaper habits, each measured here:

- **Match the model to the role.** A second reader deriving cases from a spec and
  running its own mutations earns the strongest model available. A round that
  re-applies a named mutation table and pastes a verdict block does not.
- **Scope the test run.** `uv run pytest tests/test_x.py` during a mutation cycle;
  `make host-gate` once, at the end, before the push. A full suite per mutation is
  the single largest avoidable cost.
- **Re-review only what changed.** When a prior independent session has verified
  the engineering and the new diff is prose, say so in the brief and ask for the
  narrow check — but require the reviewer to *prove* the diff is what it claims
  (an AST comparison with docstrings stubbed, not an eyeball), because if it is
  not, the carried-over verdict is about a different tree.

**A killed session leaves unsourced numbers behind, and that is a correctness
problem rather than lost time.** When the limit bit mid-round, the next worker
correctly refused to trust the dead session's uncommitted figures and said so in
the task file — and the same unreproducible measurement still shipped in a module
docstring two files away, refuted by that very commit. **Nothing tests prose.**
After any mid-round kill, treat every number the dead session left as unsourced
until regenerated, and grep the diff for figures stated as measured that no
committed artefact supports.

**Namespace scratch per agent.** The scratchpad is shared: a concurrent session
overwrote another agent's `mutate.py` mid-run, so one mutation round executed the
wrong script against the wrong worktree. With several agents in mutate-restore
cycles that is a live way to certify work nobody did. Never trust a scratch file
you did not just write.

## Name the model on every dispatch — `models.workers` cannot reach this surface

**Implementers get `model: "sonnet"`. A second reader gets `model: "opus"`. Write
it on the `Agent` call itself, every time.** Not because the config is wrong —
`arsenal/config.toml` now says exactly this for the half it can express — but
because nothing carries that value to the dispatch here, and the failure is
silent in the expensive direction.

On 2026-09-08/09 roughly twenty agents ran on Opus against a configuration whose
`models.workers` resolved to `sonnet`, for 3–4M tokens and two exhausted quota
windows. Nothing was misconfigured. Three separate things have to be true for the
configured value to arrive, and on this surface none of them is:

- **The export cannot survive.** `worker-loop.md` sets
  `CLAUDE_CODE_SUBAGENT_MODEL` in a shell step. Cloud Bash calls do not share
  shell state — measured here: `export ARSENAL_PROBE_XYZ=persisted` in one call,
  `${ARSENAL_PROBE_XYZ:-<unset>}` in the next, prints `<unset>`. The variable is
  gone before any dispatch reads it. On the laptop the same line works, which is
  why this is worth writing down rather than assuming.
- **An explicit `model:` outranks it anyway.** The `Agent` tool's parameter takes
  precedence over the configured default subagent model, so a session that names
  a model wins over the config every time and is told nothing.
- **Omitting `model:` does not fall back to `sonnet`.** With no env var and no
  agent-definition model, a subagent **inherits the parent's** — an Opus
  orchestrator dispatches Opus workers by default. So both the documented path
  and the do-nothing path yield Opus, and only naming `sonnet` yields Sonnet.

**The reviewer half is not expressible at all.** `MODEL_KEYS` is
`("models.orchestrator", "models.workers")`;
`arsenal_config.py --get models.reviewers` exits 2 on an unknown key, and an
unknown key written into `[models]` is tolerated on read but reaches nothing. The
bundle's `agents/` holds `worker.md` and `reviewer.md`, and that reviewer is the
**pre-PR** one spawned by `adversarial_review.sh` from a case file — the on-PR
second reader `merge-policy` requires has no agent definition and no model key
anywhere in the bundle. It exists only in this file's prose, which is why the
model it runs on has to be named here too. Both gaps are upstream's
(`claude-arsenal`), not fixable in this repo.

**And this cannot be pinned.** No gate can observe which model a subagent ran on;
the token report arrives after the spend. By the standard the section below sets
out, that makes this a rule stated and unpinned in its own instance — the eighth
face of the family, and honestly named rather than dressed up. The only thing
working for it is that this file is in context on every turn and the remedy is
one parameter.

## Fixtures for a correctness-critical gate are written by a second session

A gate that a worker writes alongside its own implementation judges that implementation
by the author's own reading of the spec. When the reading is wrong, the code and the
fixtures are wrong together, and the gate is green.

That is not hypothetical here. **T70 took ten defects across five review rounds, and
eight of the ten were introduced by the session fixing the previous one** — each pushed
after adding fixtures and watching `make host-gate` pass. Percent-encoding equivalence
for robots matching has a long tail (`%`, `?`, `$`, `*`, empty delimiters, unreserved
octets, product tokens) and it was met one round at a time, because every round's
fixtures were derived from the code that had just been written.

So for any task whose gate can pass while the code is wrong — parsers, matchers,
normalisers, anything comparing two encodings of the same thing — a **session other than
the implementer** writes adversarial fixtures, and:

- it reads the **spec first** and derives its cases from that text, before opening the
  implementation, so the cases are not a description of what the code already does;
- it justifies each expected verdict by citing the spec, never by running the code —
  deciding correctness by execution is the exact circularity this exists to break;
- it weights **fail-open** over fail-closed. A fail-closed bug costs a fetch; a fail-open
  bug means the check said yes to something it was built to refuse.

It reports; it does not push. The report names, for each case: the input, the verdict the
spec requires, **the section it is citing**, what the implementation actually returns, and
whether a failure is fail-open or fail-closed.

**Every accepted case is then committed into the gate's own fixtures before the PR
merges** — not merely answered in a comment. A report that is read and waved through
leaves the code exactly as unprotected as it was, and the next regression re-opens the
same hole with nothing to catch it. The measured denominator must rise: if the audit
accepted twelve cases, the evidence counts twelve more than it did.

That requirement is the section's own subject turned on itself. "The implementer's PR
waits for the report" is satisfiable without a single independent case ever running —
which is a process that reports success over work it did not do, exactly what this exists
to stop. **Caught by review on the PR that introduced this section**, which is the
argument for the section, made twice.

**"More care" is not the alternative and does not work** — four careful rounds did not
catch what the fifth did. The fix is a second reader, not a more diligent first one.

**A green gate is necessary and is not sufficient.** Every one of those ten defects was
behind one.

### What the second reader keeps finding: being right is not being pinned

Seventeen review rounds across four pull requests on 2026-09-08/09 produced
seventeen findings and **no empty round**. All were fail-open; all were behind a
green `make host-gate`, a PASS `verified_gate.sh` block and green CI. Eight were
the same defect, and three of the four pull requests had a round whose finding
sat **inside the remedy written for the previous round**.

Stated once, it is:

> **A check pinned against a proxy for the property, rather than against the
> property.**

The faces it wore, so it is recognisable next time — a gate certifying coverage
it does not have (collapsing two constructed orders to one left 137 tests green,
because the test compared state *names*); a metric independent of its own inputs
(severing either half left it at 0 with 68 tests green); a floor counting labels
rather than the things labelled; **a bound derived from the thing it bounds**
(`MINIMUM_FIELDS_CHECKED = len(X)` compared against `len(X)` — false for every X,
a guard that has never fired and cannot); a bound one short of its population, so
the first deletion breaches nothing; an invariant whose population never reaches
the branch it is about (reverting one of two fixed sites survived the whole gate
at exit 0 and permitted 38 refused requests); **a fixture whose execution path
never arrives** (the mutant reverting the fix survived because another guard
answered first and the test only reached the code through the aggregate — green
fixture, live defect, invisible to reading); and a rule stated, mandated for
others in the same diff, and unpinned in its own instance.

**The lesson generalises past gates.** T155's argument for excluding a field from
its distinctness key was *correct* — the reviewer checked the data and confirmed
it — and nothing tested it, so the next tidier refactor would have walked
straight through. A true sentence in a docstring, a correct constant, an accurate
comment: none of them is a check. **Being right in fact is not the same as being
pinned.**

**What works, and it is cheap.** Before pushing a fix, go looking for this family
in the diff you are about to ship, and report what you found — *including
"nothing, and here is where I looked"*. That found four real defects in one
night, every one by the implementer rather than a reviewer, and a self-caught
finding costs one push instead of a whole review cycle. The best of them: a task
about markers that read as evidence and are not, whose own evidence file carried
a `fail_open` count arithmetically identical to its metric — two numbers that
could not disagree, the second corroborating nothing.

**What does not work is enumeration.** Every round that answered a finding with
one more case got another finding. The rounds that ended a thread replaced the
enumeration with a closed rule: a twin derived from `dataclasses.fields` so a
field added later is varied without anyone remembering to; a stub wrong in every
direction at once; an encode set derived from RFC 3986's `reserved` production
rather than listed. An enumeration has no last element.

## The review half of `merge-policy` is a second session, not a bot

**CodeRabbit came back when the repository went public on 2026-09-07**, and the
paragraph this replaces said it was gone for good. What is true now: it is
installed on the OSS tier, it does **not** review automatically below 10 stars
(its own comment on #398 says so, and its commit status reads *"Review skipped:
manual review required for this OSS repository"*), and a `@coderabbitai review`
comment triggers it by hand.

**That changes nothing below.** A bot that has to be asked is not a standing
reviewer; this repository has swapped review bots four times; and the measured
comparison in this section is why the second-session read is the *primary*
reviewer rather than the fallback, not a stopgap for the days the bot was away.
Trigger it when a diff is worth a second opinion. It does not satisfy the review
half on its own, and `merge-policy` stays `after-ci-and-review`.

**A code PR may merge once a session other than its implementer has read it and
reported on the PR.** That is the same discipline the section above already requires
for a correctness-critical gate, applied to the whole diff rather than to fixtures —
and on the evidence it is the stronger reviewer, not the fallback. Measured on the
PRs open when the bot left: the independent read of `concept_map.yaml` found **41**
placements wrong in the fail-open direction, and the read of the cue vocabulary found
**19**, against CodeRabbit's **9** on the same PR that carried the 41.

Three rules keep it from becoming prose nobody reads:

- **The report goes on the PR**, naming for each finding the input, the verdict, and
  the section of spec or definition it is derived from. A verdict argued from what the
  code does is the circularity this exists to break.
- **The implementer never signs it off.** If no other session has read a PR, it is not
  reviewed — say so and leave it, exactly as `open_task_pr.sh` refuses a PR that would
  close nothing.
- **Accepted findings are committed as fixtures before merge**, per the section above.
  A report that is read and waved through leaves the code as unprotected as it was.

**Docs-only PRs are exempt** — a handover or a task-file edit merges on green CI. The
rule is about diffs that can be wrong in a way a test does not already catch.

`D-28` (`claude-arsenal#313`) is re-scoped to this: not "read CodeRabbit's signal" but
"a merge must not proceed until a second-reader report exists for the head commit".
That is a checkable condition, which the bot's never was — **and it now has a
reader**, so the rule above is no longer only prose.

**End the report with the marker, and check it before merging.** The marker is
emitted, never typed: prose saying "reviewed" passes a scan that matches words and
fails on a thorough review that does not use them.

```bash
uv run python -m integral.review_reader emit --head <40-hex head sha>   # the reader pastes this last line
uv run python -m integral.review_reader check <pr-state.json>           # the merger runs this
```

`check` reads a small JSON capture — `number`, `author`, `head_sha`, `files`,
`comments[{author, body}]` — written to disk from a GitHub tool result, the same
way the board JSON is, so it works on a surface whose REST channel answers 403.
Its exit codes are `adversarial_review.sh`'s, and for the same reason: **0** a
second reader cleared *this* head (or the PR is docs-only and exempt), **1** a
second reader said BLOCK, **2** no report on record, **3** a report exists but for
another commit. **2 and 3 are not passes** — a review of an earlier tree is not a
review of this one, which is what #320 cost nine unworked findings. A marker
written by the PR's own author never counts, including one they quote from
somebody else's report — and one whose author did not resolve at all counts for
nobody: an identity that cannot be shown to differ from the implementer's does
not rule self-review out.

**How an author becomes an identity is one rule: the string must already BE a
login.** #408 took **five** review rounds, and each of the first four normalised
one more layer of decoration and stopped — a blank author, then case, then
invisible padding, then visible padding (`@nuncaeslupus`, `nuncaeslupus.`,
`(nuncaeslupus)`, the fullwidth `ｎｕｎｃａｅｓｌｕｐｕｓ`, `nunca es lupus`), every
one of them clearing that account's own PR through this very CLI at exit 0. So
the rule is now stated as a **validator**, not a transform:

> `resolve_identity` trims outer whitespace, requires the whole string to match
> `[A-Za-z0-9](?:-?[A-Za-z0-9])*`, and casefolds. **Anything else returns
> `None`** — unresolvable, exit 2 — and is never repaired into an identity.

**The paragraph this replaces was wrong, and the way it was wrong is the lesson.**
Round 4's rule was *NFKC-fold, then delete everything outside `[A-Za-z0-9-]`*,
defended here as safe because "the transform only ever *merges* strings … so
every collision pushes toward `blocked`". Both halves are false:

- **An allowlist applied as a deletion filter enumerates by complement.** It
  removes only decoration made of characters *outside* the alphabet; decoration
  made of characters *inside* it is **welded onto the login**, and a weld is a
  different identity, which reads as somebody else and clears the PR.
  `nuncaeslupus (OWNER)` — a `gh` association badge, one step past round 4's own
  accepted `(nuncaeslupus)` — became `nuncaeslupusowner`: exit 0,
  `merge_may_proceed: true`, on a PR authored by `nuncaeslupus`.
- **The transform did not only merge.** Its own worked example refutes it:
  `resolve_identity("straße")` returned `strae`, **not** `strasse`. Deletion
  shortens and NFKC lengthens (`™`→`TM`, `№`→`No`, `Ⅷ`→`VIII`), so it **split**
  too — and every split is **fail-open**, because a split moves a writer away
  from the author and toward "somebody else". `²`, `Ⅷ`, `™`, `Ⓐ`, `½` and `㎏`
  each resolved alone to a distinct identity and cleared the head at exit 0.

The discriminator is therefore not whether the output *looks* like a login (`2`
looks no worse than `reviewer`) but whether normalisation had to **rewrite the
input into something else**. Validation cannot: it returns the login GitHub
itself would case-fold, or nothing. `nunca-es-lupus` is the control that the
strictness has not gone too far — the hyphen is in the grammar, so a hyphenated
login is a different, real account and still clears at exit 0.

`status/evidence/D28.json` is the gate: `merges_allowed_without_a_review_of_the_head`
over forty-seven constructed states — including the PR-**author**-side mirrors no
round before the fifth had, which is structurally why each stopped one layer
short — with `-1` and `review_reader_status: unmeasured` rather than a clean zero
when the scan resolves nothing.

## Work each task in a linked worktree — that is the whole branch protocol

`open_task_pr.sh` cuts the branch off `origin/main` itself, commits, pushes and opens
the PR. **Leave the edits uncommitted and let it do that.** A branch made and committed
by hand first has to be unwound (`git reset --mixed HEAD~1`, back to `main`) before the
script will run, which is a confusing five minutes for no gain.

It also refuses `git add -A` outside a **linked** git worktree, because on a shared
checkout that sweeps whatever else happens to be in the tree. One command satisfies it,
and the same one works whether this session is alone or one of several:

```bash
git worktree add --detach ../ijs-<task-id> origin/main   # work here
# …edit, run `make host-gate`, then open_task_pr.sh from inside it…
git worktree remove ../ijs-<task-id>
```

Parallel workers get this from `isolation: worktree`; a single interactive session has to
ask for it, and asking costs one line.

**Neither escape hatch is the answer on this laptop.** `ARSENAL_ALLOW_SHARED_ADD=1` is for
a bespoke setup, and writing `arsenal/session/worktree_isolation` by hand records that
worktrees are *unavailable* — `worktree_probe.sh` prints `available` here, so that file
would be a false record, and `task_select.py` reads it to clamp every future round to one
task. The probe writes it itself when it is true; nothing else should.

## `tools/verified_gate.sh` — the local verdict block, run whatever CI is doing

Actions ran dry on 2026-09-04 — 2000 monthly minutes in four days — and for three
days this script *replaced* the CI half of `merge-policy`. **It has minutes again
as of 2026-09-07** (measured below), so the script is no longer a substitute for
anything. It stays required anyway, and the reason is the one it was always worth
running for rather than the outage: it measures the **committed** commit, and the
working tree a session happens to have is not what a reviewer merges.

`merge-policy` stays `after-ci-and-review`. Both halves are live again; this is
what the local half runs:

```bash
bash tools/verified_gate.sh <branch-or-sha>     # prints a verdict block
```

It resolves the ref to a 40-character SHA, checks **that commit** out into a
throwaway detached worktree, clears bytecode, and runs `make host-gate` there. It
delegates — it never lists targets — so it cannot fall behind the Makefile, and
`integral.repo_gate`'s sibling `integral.verified_gate` (T121) asserts that it
still does all of the above.

**How that assertion works is the part worth knowing, because three rounds of
the obvious answer were defeated.** `integral.verified_gate` does not read the
script's text. Round 1 searched the file for `make\s+host-gate`, which the
script's own header comments carried twice, so a script running `make lint` and
a script with the gate deleted and `status=0` hard-coded both scored
`verified_gate_defects == 0`. Round 2 added a comment-stripper and twelve
patterns; round 3 put all twelve inside one unused single-quoted string, and
again in *trailing* comments, and scored 0 both times over a script that
resolved nothing and ran nothing. A `#`-line filter is not an executability
test, and no thirteenth pattern fixes that.

So the measurement is **behavioural**: ten named contracts, each of which builds
a throwaway git repository — one a clone with a real bare `origin` — runs the
script against it, and reads the verdict block, the exit status and the
filesystem afterwards. `verified_gate_defects` is the number of contracts the
script fails. Editing a comment cannot break it; hard-coding a PASS cannot pass
it. The one thing still read rather than run is that **this file names the
script**, which is D-22's prose half and not a claim about behaviour.

The practical consequence for anyone editing `tools/verified_gate.sh`: run
`uv run python -m integral.verified_gate` and read `failed_contracts`. It names
what broke and what it observed, not which regex stopped matching.

**Give it the ref.** With no argument it measures the local `HEAD`, which is
usually right and is never the *pushed* commit by construction — and the block's
`resolved` and `on origin` lines say which of the two you got, so read them before
pasting. (Until the second-reader round on #333 the no-argument form fetched
`HEAD` from origin, which git answers with the **default branch**: standing on a
branch whose gate genuinely failed, a bare run printed `main`'s SHA and `PASS`.
The fix was a blacklist of the one string `"HEAD"`, and `@` — git's documented
synonym for it — walked straight through: the same green verdict about `main`,
reached by a different spelling. Only a plain ref name is now asked of the
remote; `@`, `HEAD~0`, `HEAD^0`, `@{u}` and `""` all resolve locally.)

Why a clean checkout rather than just running `make host-gate` where you stand:
the working tree is **not what a reviewer merges**. Uncommitted edits, a staged
file, and the `.pyc` trap below can each make a local run green over code that is
not being shipped.

Three rules, and the third is the one that is easy to skip:

- **Paste the verdict block onto the pull request.** CI's value was never only
  the checking; it was that anyone could see it had happened.
- **Quote the four results in the merge commit.** A merge whose evidence lives in
  one session's scrollback is a merge nobody can audit afterwards.
- **Merge only while the head is still the SHA the block names.** A push after
  the block was produced makes it evidence about a commit nobody is merging.
  This was done by hand twice on 2026-09-04 and is exactly the kind of step that
  gets skipped once it stops feeling new.

**A docs-only PR still needs it.** #331 merged on a local run during the outage;
the point of the script is that "local run" stops meaning "whatever tree the
session happened to have".

## A reverted mutation can leave the mutated bytecode running

This repository mandates mutation-verification on every fixture — revert the fix,
watch the case go red, restore, watch it go green. That cycle has a silent failure
mode, met on #329 and worth one paragraph here because it points the **wrong way**.

CPython validates a cached `.pyc` against the source's mtime at **seconds**
resolution and its **size**. A mutation that swaps two string literals of equal
total length, reverted inside the same second, changes neither — so the restore
re-runs the *mutated* bytecode. On #329 that showed as three tests red over a
working tree `git status` called clean, with `inspect.getsource` printing the
correct source while the wrong code object ran.

The symmetric case is the dangerous one: the same accident can leave a **fixed**
tree reporting green over code that was never restored, which is a mutation test
certifying work it did not do — the exact class of failure the discipline exists
to catch. So delete `src/**/__pycache__/*.pyc` after every write in a
mutate-restore cycle, and never conclude a mutation round from a run whose source
edit and test invocation fell in the same second.

**There is a third direction, and clearing `__pycache__` does not close it.** A
module already **resident in the interpreter** is not re-read at all, whatever is
on disk. Measured twice on 2026-09-09, independently, on #425: a driver whose
import order left the pre-mutation module loaded scored `metric=11` — identical
to the head — where a fresh subprocess scored `1`. The mutant was dead and the
run said it survived.

That points the opposite way to the two cases above, and it is worse to act on.
The `.pyc` failures hide a real defect; this one **manufactures a finding that
does not exist** — a session then reports a hole, files a task, or blocks a pull
request over code that is correct. A reviewer nearly did, and caught it only by
re-measuring a surprising number a second way.

So **run each measurement in a fresh subprocess**, not merely with the cache
cleared, and treat any mutation result that matches the unmutated head *exactly*
as unproven until a second method agrees. `PYTHONDONTWRITEBYTECODE=1` addresses
the disk half and does nothing for this one.

## Two branches can write the same value for different reasons, and git will not see it

`make evidence` regenerates every measurement, so an evidence key that moves is
normally either a real change or a conflict. There is a third case, met on
2026-09-09 merging #425.

Both sides moved `status/evidence/T85.json`'s `gate_modules_discovered` from 104
to **105** — the branch because it added `gate_reader_agreement.py`, main because
#423 had added `capture_provenance.py`. Two different modules, **the same
resulting text**. Git saw identical content on both sides, merged it silently
with no conflict, and the merged tree measures **106**.

Nothing about that is a mistake either side made. It is a property of a **census**
key: its value names a count rather than the thing counted, so two additions
collide at the number. `make host-gate` caught it, the fix is to **regenerate,
never pick a side** — and the reason to write it down is that the silence is the
hazard. A merge with no conflict reads as a merge with nothing to check.

Twenty-two committed evidence keys are census-shaped and could take the same path;
fifty are already committed as floors, which cannot (a floor is a literal, so both
sides changing it *is* a conflict). That asymmetry is one more argument for the
floor convention T100 and T122 arrived at from other directions.

## Spending the context window deliberately

`.rgignore` excludes the generated trees from every ripgrep-backed search, for the
same reason `pyproject.toml` excludes them from ruff and mypy: they are not ours to
change. Search one deliberately with `rg -u --no-ignore-vcs`.

**The arsenal skills are committed here, and that is deliberate.** `/init`
vendors them into `.claude/skills/` and marks each with `.arsenal-vendored`;
your own skills are left alone. Do not replace them with a plugin declaration:
a cloud session runs on a fresh clone, never sees `~/.claude/`, and **installs
no plugins the repo asks for** — upstream verified that against a live session
(`claude-arsenal#200`). What a cloud session loads is what was committed. Refresh
them by re-running `/init`, never by hand-editing a vendored file.

**The corpus is not excluded, and it is the expensive one.** A line of
`corpus/{raw,labelled}/ads.jsonl` is a whole advert — the longest is 15,640
characters — so one content match returns the whole thing. Count or list first
(`rg -c`, `rg -l`, any `output_mode` but `content`), then read the one record with
`python3 -c` and `json.loads`, projecting only the fields you need. Same for
`suggestions.json` and any `status/evidence/*.json`: project the key, never print
the file.

Three more costs, each measured here:

- **`rg -l` with no path scans ~500 files.** Name a directory.
- **Reading a module to learn its shape costs its whole length.** Use
  `bash claude-arsenal/bin/outline.sh <file>`; reserve a full read for code you are
  about to change.
- **A review bot's PR summary lands in context whole** — Qodo's on #108 was ~14k
  tokens and changed nothing. Skim it for findings and move on.

## Known environment state

**This repository is PUBLIC as of 2026-09-07**, and that one change is behind
every environment fact below. The API says so — `visibility: public`, `private:
false`, MIT — and the paragraph this replaces was still describing the private
repository's constraints. **Actions is free and unmetered on public
repositories**, which is what this section itself had predicted would fix the
outage: *"Going public would fix this."* It did.

So **GitHub Actions has runner minutes again — a red CI is a signal again. Read
it.** Measured 2026-09-07 23:20 UTC: two `pull_request` runs of the `CI` workflow
concluding **`success`**, in **95 and 133 seconds**. Against the same workflow's
last `push main` runs the day before — 4, 5, 5 and 9 seconds, every one
`failure` — that is the difference between a runner that ran the jobs and a
runner that died before any job body did.

The CI half of `merge-policy` is therefore satisfiable by GitHub again: a task PR
merges on a **green `CI` check** plus a second-reader report, and a red one is
about the code until the clock below says otherwise.

**What that check is green *about* is not the head commit.** `ci.yml` fires on
`pull_request`, and `actions/checkout@v4` with no `ref:` checks out
`refs/pull/<n>/merge` — the PR merged into its base, a commit that exists in
nobody's clone. So CI answers "does this change work *once merged*", which is the
more useful question and is **not** the one `tools/verified_gate.sh` answers. The
two are complementary rather than redundant, which is why both are required.

**Do not read the cause as a billing period turning over.** That was the guess
this session made from the run durations alone, and it is wrong in the way that
matters: a rollover is a date that recurs, and going public is a decision that
holds. Minutes are not being spent, so they cannot run out again — the next
`0 seconds remaining` would have to come from somewhere new.

**The way to tell is the clock, not the conclusion**, and that test outlives any
particular outage. Read `created_at` and `updated_at` on the run: a whole run
under ~10 seconds with unreadable logs is the runner dying; a run of a minute or
more is a verdict. Measured on #329 — 6 and 5 seconds with every log a 404,
against ~95 seconds with real conclusions on #328 twenty minutes earlier.

`tools/verified_gate.sh <ref>` is **not** retired by that, and the section above
says why: it measures the committed commit rather than whatever tree the session
happens to have, which is a different assertion from CI's and the one a reviewer
can re-run by hand. So the discipline is unchanged — verdict block on the pull
request, the four results quoted in the merge commit, and merge only while the
head is still the SHA the block names. Do **not** reach for a bare
`make host-gate` in the working tree instead. What changed is only that the block
is no longer the *whole* evidence: a green `CI` check is required beside it, and
the two assert different things — CI over the PR's **merge ref**, the block over
the **committed head**.

**Going public was the fix, and it has been taken** — the same decision as the
corpus and the contribution guard (#352). The old note here said it "would fix
this" and left it as something somebody might one day do; it is done, so what is
worth carrying forward is the size of the effect rather than the argument for it.
2000 minutes went in four days on the private repository. On this one the meter
is off.

**This section has now been wrong three times, which is the point** — and this
paragraph is the third rewrite, not the correction that ends them. It said
"Actions has runner minutes again — a red CI is a signal again. Read it." That
was true when written on 2026-09-01 and false by 2026-09-04, and it stood for a
further day telling every session to trust a signal that had stopped existing.
Then it said the opposite, and that was false by 2026-09-07 — the paragraph above
is the first sentence again, restored by measurement rather than by memory.
The same shape as the check-in that fired one morning saying *"RESOLVED — do not
re-investigate: CodeRabbit runs on Free and never produces a review object"* —
true when written, false by 10:12, and whose instruction not to look is what
would have kept it false. A recorded environment fact is a snapshot, not a
standing truth. **Re-measure before trusting this paragraph too** — it is the one
sentence here with a perfect record of going stale. `gh run list --json
conclusion,createdAt,updatedAt` is the whole check and costs one command; on a
surface with no `gh`, the MCP `actions_list` answers it, with `created_at` and
`updated_at` on each run giving the clock.

**And measure the cause, not only the symptom.** This session read two green runs
and wrote "the billing period turned over" — a plausible story for the right
observation, and false. The repository's visibility was one API field away and
settles it. A run's duration says whether CI is reporting; it never says why.

**Run the gate locally as well.** These are what CI runs, and all four must
pass before a merge:

```bash
make host-gate      # all four, one command — run this
make lint           # ruff + strict mypy
make test           # pytest
make evidence       # regenerate every measurement, fail on drift
make verify-gates   # every done/merged task can still show its measurement
```

**`open_task_pr.sh` could not open a PR in this repo until bundle v3.3.0, and the
first fix announced for it was announced without being made.** The fault:
`T55.files_scanned` counts files under `arsenal/tasks/` and the archive moves one
of them into `_history/`, which the count excludes. v3.2.0 ran the host gate
**twice** — once before the archive and once after — so the committed evidence
would have had to hold two values at once. Measured here on 2026-09-01 against the
v3.2.0 script:

```text
pre-archive = 615    post-archive = 614
```

The **v3.1.14** changelog had already stated that the gate "now runs once, over the
archived tree". Both `bash -c "${host_gate}"` calls were still in the file, and the
advice it said was gone was still at `:636`. That entry was believed here, and the
CLAUDE.md section it produced was wrong for the length of one pull request
(`claude-arsenal#336`, closed on the v3.3.0 measurement).

**In v3.3.0 it is real.** The gate is read at `:220` and run once at `:645`, after
the archive, and the file says why at `:225-238`: the archived tree is the one the
PR ships, so it is the only tree whose measurement means anything. One
`bash -c "${host_gate}"` in the script.

So the helper is the way to open a task PR again, and **it has now been exercised
end to end** — #282 (T97) and #283 (T73). Every PR from #257 to #268 was opened by
hand (`gh pr create`, archiving the task file in the same commit); nothing needs
to be.

The repair that is ours rather than upstream's outlived the fix, because a
denominator committed as an exact value drifts on every task PR whichever side of
the archive measures it. `files_scanned` is not a measurement — it exists to stop a
clean zero resting on an empty scan, and a **floor** does that job without moving.
(Counting `_history/` instead would make the number archive-invariant and
immediately break `old_name_references == 0`: archived rows legitimately carry the
old name, which is why `naming.py` allowlists that directory.) That was **T100**,
and it is done: `status/evidence/T55.json` now records `files_scanned_at_least`,
the floor `naming.MINIMUM_SCANNED` asserts, and never the count of the day.

**So there is no longer a pre-PR workaround, and re-deriving one is the mistake.**
Between #282 and T100 the sequence was `git mv` the task file into `_history/`,
`make evidence`, `git mv` it back, `git add` — which left `make host-gate` red on
the working tree by construction before every task PR, turning the one command this
file tells sessions to trust into one where red was expected. If a task PR ever
fails on evidence drift again, the finding is that something *new* is
archive-sensitive: `status/evidence/T100.json` names it, because
`archive_sensitive_evidence_keys` compares the whole committed record across a
simulated archive rather than trusting that one key was the only one.

**Adding a file is the other half of that, and it was the second instance.**
`T125.files_checked` counted every file `ruff format` reads, which since ruff 0.16
includes **Markdown**, so a pull request of nine task files and no Python at all moved
it 453 → 462 — and two branches could each read 465 while their merge ref read 467.
That is **T150**: the count is committed as the floor `files_checked_at_least`
(`repo_gate.MINIMUM_FILES_FORMATTED`), and `status/evidence/T150.json`'s
`unstable_evidence_keys` compares each registered record across **both** mutations —
a file added and a task file archived. T100's check could only ever see the second.

**The mutation is applied to the tree, not to the number, and that distinction is the
whole check.** The first version of T150's gate transformed the *measurement*:
`{**measured, key: population + 1}` for a hand-written `key`. Two keys were ever
written, and they were the two already known to be broken, so the check could
re-confirm the fixes it shipped with and could not discover a third — while the third,
`T58.bundle_files`, sat committed on `main` and the gate reported a clean zero over it.
The added-file mutation now **writes a real Markdown file** into every top-level
directory that already holds Markdown, hands those paths to every registered
measurement, and deletes them again; one added file therefore moves every population
derived from it at once, exactly as a real pull request does. A key nobody named moves
with the rest. Caught by the second reader on the pull request that introduced the
gate, who added a second census key to a committed record and watched it report
`stable`.

Two consequences worth knowing before editing any of this:

- **The registry is discovered, not listed.** A module joins by declaring
  `EVIDENCE_SOURCES = (("T55", measure, record),)` beside the code that counts;
  `repo_gate` finds those declarations by parsing the source (never `importlib` —
  `src/integral/` may not load code, and the connector contract depends on that) and
  resolves them through `sys.modules`. A module that declares one and is not imported
  by `repo_gate` makes the gate `unmeasured` and says so by name.
- **Every registered source must be moved by some mutation, and both denominators are
  asserted** (`MINIMUM_EVIDENCE_KEYS_COMPARED`, `MINIMUM_EVIDENCE_SOURCES_COMPARED`).
  Pooled across the registry, one source's coverage could degrade to nothing — deleted,
  emptied, or blind to the tree — while another kept the run reading `measured` with
  both mutations advertised. The only trace was a denominator nobody read.

**`ruff format` reads two unrelated populations, so there are two floors.** Markdown is
242 files and grows about nine per task-seeding pull request; Python is 227. A single
total floor of 300 is satisfied by Markdown alone within six or seven such PRs, at which
point a scan that read **no Python at all** scores a clean pass — and even today it does
not catch losing `src/` (469 − 104 = 365). `MINIMUM_PYTHON_FILES_FORMATTED` says the
thing the conflated total cannot.

**One evidence key is now archive-*driven* by design, and it is not that finding.**
Since D-27, `S8.json`'s `merged_tasks_with_an_unticked_plan_row` requires every task
archived in `arsenal/tasks/_history/` with `status: merged` to carry a ticked `☑` row
in `status/plan.md`. So **ticking the row is part of archiving the task**: a task PR
that moves its file and leaves the plan alone turns `make evidence` red, by
construction. That red is the check working — tick the row in the same commit. The
denominator `merged_tasks_compared` is committed as a floor for T100's reason above,
so it does not move.

`host-gate` is the name `claude-arsenal` points a worker at, and
`integral.repo_gate` checks that every target listed here is real and is
reached by it — so a fifth line added above cannot quietly go unrun (D-22).
Note `make gate` is a different thing: it records T1's lint exit code, one
check, and is not the repo gate.

## A `ClaudeBot` disallow does not bind this tool — and this has been re-litigated twice

**The rule, in one line: a group named for a training crawler is not a group
named for this tool, and only a `*`-group disallow rules a board out.**

Under RFC 9309 a crawler matches the group for its own product token and falls
back to `User-agent: *`. Our token is `integral-job-search/0.1`. So a
`ClaudeBot` / `GPTBot` / `CCBot` / `Google-Extended` group **does not bind us**
and must not be read as if it did. Those bans target bulk training crawls; a
connector fetch is *one candidate's search*, run for a person who asked for it.
Some operators spell the distinction out themselves — academictransfer.com
disallows `ClaudeBot` while its robots.txt says AI assistants may access pages
for search and reference answers.

The owner has stated this position directly, and it is quoted in
`connector_policy.py`'s own docstring:

> It is the user who will use the scraper, not you, and most of them did not
> allow massive scraping for AI, but they allow it for making some searches.

**Adjudicate with the repo's matcher, never by reading the file.**

```bash
uv run python3 -c "from integral.robots import Robots, USER_AGENT; print(USER_AGENT); print(Robots().allows('<url>'))"
```

Two things a `True` still does not settle, both already written out at length in
`connectors/ruled-out.yaml`'s header — read it before ruling any board out:

- **`restated_for_every_named_agent`** — a path the `*` group leaves alone but
  which the *same file* disallows for **every** named AI agent, under its own
  plain-language caption. That is a permission read out of an omission, and the
  bar is deliberately high: the same path, in the same file, for every named
  agent — not a Claude-shaped subset. `remoteok.com`'s `?action=get_jobs` under
  `# AJAX endpoints` is the one board that meets it, and **its listing pages are
  allowed** — the refusal is about that endpoint, not about the board.
- **Whose call it was.** `robots_refused` is what the board said; `policy_refused`
  is what *we* decided about a board the matcher allows. T99 requires an owner's
  decision, dated, next to any `policy_refused` entry — a session recording its
  own judgement there is the defect wearing the fix's clothes.

**Why this section exists rather than only the ledger header.** The reasoning
above was already correct and already written down — in a module docstring and
in a YAML header. It was still restated wrongly to the candidate on 2026-09-06
("RemoteOK prohibits ClaudeBot and every AI agent it names, so it is out"),
because neither of those files is read *before* a session forms an opinion.
CLAUDE.md is in context on every turn; the ledger is not. That asymmetry, not
the argument, is what needed fixing.

## Read on demand — `docs/repo-playbook.md`

Installing and updating the arsenal plugins, the skill-listing budget, parking a
task, and the board's title-matching history live there. Each is needed at one moment in a
session, not on every turn, so it is a path to open — not an import.
