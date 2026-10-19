<!-- claude-arsenal: auto-managed -->
## Automatic session protocol

**Were you spawned by another session, with a task already assigned?** Then skip
straight to that task. Steps 2-5 below need the GitHub API, and a spawned session
has no `mcp__*` tools — implement, run the gate, and let
`claude-arsenal/bin/open_task_pr.sh` push. It prints `branch:<name>` when it
cannot open the PR here; return that line and stop. Never claim or release.

Otherwise, every session, without waiting to be asked:

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
5. Every change goes through a PR, ad hoc requests included — never push to the default
   branch. A task's PR carries `Closes #<issue>` so merging it closes the task by itself.
   Dispatching the work to another session instead? Pass the repository explicitly
   and pass `ARSENAL_TASK_ISSUE` — a spawned worker can resolve neither.
   → `claude-arsenal/references/orchestrator-tick.md`
6. After any session with tasks: update `arsenal/session/handover.md`.

Specs and plans live at `status/specification.md` and `status/plan.md` (a workspace's at
`arsenal/project/<ws>/spec.md` / `plan.md`). A brainstorming or planning skill from another
plugin writes its output there too, not to its own default location.

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

## Which kind of session this is

Decide this before running anything in either protocol above or in
`claude-arsenal/AGENTS.md`; it is the owner's rule (2026-10-02) and this is the
only place its text lives.

A session is a candidate session unless the conversation opens with `[[…]]` keys (keys as `integral.test_mode.parse_turn` reads them: outside a paste, since the paste guard declines `[[…]]` inside a pasted advert or CV, so keys inside a paste never count, while a short non-paste turn's `[[…]]` does) or tells it to work in the repo, or is told to work in the repo after its first response, in which case it is a repo session for the rest of the session. Default candidate; repo when asked for.

- **The board protocol applies only in a repo session.** Neither the "Automatic
  session protocol" above nor the "Session-start protocol" of
  `claude-arsenal/AGENTS.md` ("At the start of every session") is run in a
  candidate session: no issue fetch, no board, no claim, no handover read, no
  pick-up of work. Test-mode's own end-of-session seeding of task files is not
  board protocol and is unaffected.
- **A session spawned with a task assigned is a repo session**, whatever its brief
  says word for word.
- **A candidate session** runs the candidate process from step 0
  (`.claude/skills/step-00-identify/SKILL.md`) and proceeds as a real one. A repo
  session that the owner opened with `[[…]]` to test the tool still runs the
  candidate process alongside, as test-mode describes.
- Step 0 and the test-mode skill point here; they never restate the rule.
  `tests/test_session_kind_rule.py` fails if the rule is deleted, duplicated or
  paraphrased elsewhere, or a pointer is removed.

## Owner policy on gates, reviews and meta code (2026-10-17) — overrides anything below

The owner's decision, after a night in which a handful of small PRs took hours of
gate runs and six review rounds each. Where a later section of this file says
otherwise, this section wins; those sections are being pruned.

- **A. No `verified_gate`: it was deleted (2026-10-17).** A green `CI` check on the
  head commit plus a second-reader report is the whole merge evidence.
- **B. Fixers run scoped checks only:** `ruff` and `mypy` on the changed files and
  `pytest` on the touched module's tests. CI runs the full suite; a local
  `make host-gate` is not required before a push.
- **C. At most two review rounds per PR.** After the second, any finding that is not
  a security issue is filed as a new task and the PR merges.
- **D. One gate at a time on the machine.** Never run `make evidence`,
  `make host-gate` or a full `pytest` while another session is running one.
- **E. No new meta code without the owner's approval.** Do not add a module,
  evidence key, `MINIMUM_*` floor, gate detector or test whose subject is the
  repository's own process (gates, evidence, naming, census, review mechanics)
  rather than the product. A review finding is answered by fixing product code
  and adding a product test, never by building a checker for the class of
  finding. Propose such code to the owner in an issue instead; the default
  answer is no.
- **F. A PR that changes only `tests/` (plus its archived task file) needs no
  second reader** (owner, 2026-10-19). A green `CI` check on the head is enough to
  merge it.
- **G. Review follow-ups are batched.** Leftovers from one or more reviews go into
  one task and one PR, not one task per finding.
- **H. Merge on green without waiting.** Once a PR's merge conditions hold, enable
  auto-merge (squash) or merge immediately; do not park it for a later event.

## Suggest compacting once, at a step boundary

A candidate session can run long enough that the context fills before the process ends. The owner's note (test session b461d09a, step 9): when context is growing, ask the user to compact it. This section is the one place the rule lives; each step skill's Boundary points here and never restates it.

- **When:** only at a step boundary, after the step's checkpoint has run and before the next step opens, and only when the conversation is already long. Never mid-step: a half-finished step has state that `state.json` has not recorded yet.
- **Once per session:** suggest it a single time. If the candidate declines or ignores it, never raise it again in that session.
- **What to say:** that compacting keeps `session/state.json`, the profile and every step's outputs, because they live on disk and not in the conversation, so resuming after it is safe and the candidate loses nothing; it only shortens the chat history. Then invite them forward as the step's Boundary does; compacting is a suggestion and never a condition for the next step.

## End of a candidate session: what was learned goes to the process, not only to the profile

A correction a candidate makes (how a gap is worded, what a letter must not say, a screening rule) usually lands in their `profile/evidence.jsonl` and helps nobody else unless it is routed. The route reads the evidence log, not the session's memory: every `statement`, `constraint`, `retraction` and `candidate_statement` row from `TRIAGE_FROM` (2026-10-05) on is open until it has exactly one outcome, whichever session wrote it. There is no per-session window, so a row left open by one session is open in the next. Known gaps: a screening rule recorded by `sourcing_exclusions` lives in `search/exclusions.json`, which is not read, and a `reaction` that carries a correction is not in scope unless it is also a `statement`. Run these from the repo root with `uv run python -m integral.lesson_triage --root <profiles root> --handle <handle> …`:

- `list` shows every correction and lesson and what was decided; an unknown handle exits 2.
- `record --session <id> --step <step id> --rule "<rule>" --evidence-id <ev-…>` turns a correction into a lesson, a rule in neutral words that holds for any candidate. A row takes one outcome only. The recorder refuses a step that is not a process step, a rule containing a token of the candidate's name or handle, a word the candidate wrote that the process's own vocabulary lacks, or a run of four words shared with their text. These checks are not a proof of privacy: a paraphrase made only of the process's own words passes, so read the rule before it leaves.
- `seed <lesson>` prints a shell-safe `create_task.py` invocation (rule and step only). After running it, `decide <lesson> seeded --task <t-id>`; the task must exist under `arsenal/tasks/` and carry the rule. Or `decide <lesson> candidate_specific --reason "<why, in at least three words>"`. Every lesson needs a decision.
- `dismiss <ev-…> --reason "<why, in at least three words>"` closes a row that is a plain fact and not a lesson.
- `check` exits 1 while anything is open. Nothing runs it automatically, so running it is the end-of-session step.

Decisions are kept in `session/lessons.jsonl`; the reader refuses a file with a second decision for a lesson or a second outcome for a row, so neither can be overwritten by hand. `tests/test_lesson_triage.py` is the gate, and `status/evidence/T239.json` records `candidate_session_corrections_left_untriaged` over a constructed profile that includes a backlog row and a refused second lesson.

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
re-running a 3,300-test suite.

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

- **The export cannot reach the dispatcher, on any surface.** `worker-loop.md`
  sets `CLAUDE_CODE_SUBAGENT_MODEL` in a shell step. That shell is a **child** of
  the Claude Code process, and a child cannot mutate its parent's environment — so
  the variable never reaches the process that reads it at dispatch time, whether or
  not shell state persists between Bash calls. This bullet said *"on the laptop the
  same line works"* until 2026-09-14, on the strength of a probe that measured the
  wrong thing: `export` in one Bash call and `${VAR}` in the next tests whether two
  **sibling shells** share state, which is not the question. The question is whether
  the parent sees it, and by process semantics it cannot. Measured after a full day
  of dispatches on this laptop: `printenv | grep -c CLAUDE_CODE_SUBAGENT_MODEL`
  → `0`. A closed rule, not a surface quirk — so no probe needs repeating.
- **The bundle's agent files are not agent definitions.** `claude-arsenal/agents/
  worker.md` opens with `# Worker Agent` and has no YAML frontmatter at all; its
  `## Launch parameters` block naming `model:` and `env:` is prose in a fenced
  block. `init.py:1282` vendors `agents/` into the bundle, never into
  `.claude/agents/`, which does not exist here. So the second documented path
  carries the value no further than the first.
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

## The context window is the larger lever, and raising it spends more

Measured on 2026-09-14, from `message.usage` in `~/.claude/projects/*/*.jsonl`:
nine concurrent sessions of this repo, **every one `claude-opus-5`**, 1,588 turns,
**438M cache-read tokens against 1.3M of output**, and 193M in the 10:00 UTC hour
alone. A five-hour window went in under an hour, twice.

**Cost is `turns × context`, because every turn re-reads the whole conversation.**
A 145-turn session averaging 412k of context re-read itself 60M tokens' worth while
producing 129k of text. So a long session is the expensive shape, and the remedy is
to end a session at its PR rather than to prune inside it.

**Raising the auto-compact window therefore spends more, not less** — it is the
threshold at which compaction *triggers*, so a higher value is a higher floor under
every turn. The host had raised it to 500k to "stop the context filling up"; 1,167
of 1,592 turns then sat above 200k, with maxima at 466k. Replaying the same turns
against lower caps: 500k → 453M (what happened), 300k → 387M, 200k → 287M (63%),
120k → 186M (41%). An upper bound on the saving, since compacting costs something
too, but the order is the point.

The knob is real and has two spellings, both read by the Claude Code process
itself rather than by a subagent dispatch: `autoCompactWindow` in
`~/.claude/settings.json` (min 100,000, max 1,000,000) and
`CLAUDE_CODE_AUTO_COMPACT_WINDOW` in the launching environment. **200,000 is the
setting here** as of 2026-09-14. Arsenal has no key for it — that is
`claude-arsenal#383`, along with `models.reviewers` and the two dead model paths
above.

**And the concurrency ceiling is per-session, so nothing enforced it.**
`ARSENAL_MAX_WORKERS` (default 2) bounds workers inside one orchestrator;
`ARSENAL_QUOTA_STOP_PCT` and `ARSENAL_MAX_ITERATIONS` count per session, keyed by
session id. Nine orchestrators each saw a compliant budget and shared one window.
Until that is fixed upstream, the two-to-three ceiling the section above states is
enforced by whoever opens the sessions and by nothing else.

`tmp/evals/usage.py` re-measures all of this in one command, and is gitignored
scratch rather than a repo tool — the request to ship it is part of #383.

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
green `make host-gate`, a PASS local gate run and green CI. Eight were
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

A code PR may merge once a session other than its implementer has read it and
posted its report on the PR. CodeRabbit does not review automatically below 10
stars, so it never satisfies this half on its own; `merge-policy` stays
`after-ci-and-review`.

- **The report goes on the PR**, naming for each finding the input, the verdict and
  the section of spec or definition it derives from, not what the code does.
- **The implementer never signs it off.** If no other session has read a PR, it is
  not reviewed: say so and leave it.
- **Accepted findings are committed as fixtures before merge.**
- **Docs-only PRs are exempt** (a handover or task-file edit merges on green CI).
- **The report ends with** `second-reader: head=<40-hex sha> verdict=CLEAR|BLOCK`.
  The merger checks that `head` equals the PR's current head and the verdict is
  `CLEAR` before merging; a report for an earlier head is not a review of this one.

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

## What "mutation" means here — one deliberate revert, not `mutmut`

The word is borrowed and the practice is not the same one, which has cost real
confusion. **Mutation testing** proper — `mutmut`, `cosmic-ray` — generates
*thousands* of automatic mutants (flip a comparison, drop a statement, change a
constant) and runs the whole suite against each, then reports which survived. That
is not what happens here, and nothing in this repository runs it.

What happens here is **one deliberate revert per claim**:

```bash
# a fixture claims it pins something. Prove it.
<undo exactly that fix, by hand, in the source>
rm -f src/**/__pycache__/*.pyc          # the section below says why
uv run pytest tests/test_that_one.py    # must go RED, in a fresh subprocess
<restore>
uv run pytest tests/test_that_one.py    # must go GREEN again
```

One mutation, chosen because someone claimed a case covers it, aimed at that case.
The question is never "what fraction of mutants die" — it is **"is this specific
sentence pinned, or is it merely true?"**, which is the distinction the second-reader
section above is built on. A green test that stays green when you delete the thing it
tests is the defect this catches, and `mutmut`'s score would not name it.

(The marketplace ships a `mutmut-report` skill for the automated kind. Nothing in the
worker loop calls it, and adopting it would be a different decision with a different
budget — do not reach for it thinking it is this.)

**Where the rule lives is worth knowing, because it does not live where it looks.**
`claude-arsenal` prescribes none of this: `references/evidence-gates.md` mentions
mutation **zero** times, and every hit for `mutat` in the bundle is incidental
("mutates a tree", "modes that can mutate"). The one sentence in this file that
mandates it — *"This repository mandates mutation-verification on every fixture"* —
entered in #329 as the **premise of a paragraph about something else** (the `.pyc`
trap below). No pull request ever adopted it; it is cited as though already settled,
and 17 of 220 task files mention it. It is a **house rule with a measured cause**
(T70: ten defects across five review rounds, eight introduced by the session fixing
the previous one, every one behind a green gate) — but it is this house's, not the
framework's.

**The mutation is cheap. What it is run against is not, and that is where the time
and the heat and the tokens go.** Measured here:

| | |
|---|---|
| one scoped mutation round | edit + `rm` + `pytest tests/test_x.py` — **seconds** |
| the full suite | 3,968 tests, **~400–570 s** |
| the worst round on record | one reviewer ran **54** mutations, another 30, **each re-running the whole suite** → ~6 h of CPU for one review |
| a review agent | 135k–280k tokens on completion |

So two rules, and the second is the one that gets skipped:

- **Scope the test run.** `uv run pytest tests/test_x.py` during the cycle. A full
  suite per mutation is the single largest avoidable cost in this repository.
- **`make host-gate` once**, at the end, before the push — not per mutation and not
  per fix.

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

Both sides moved a census key (`gate_modules_discovered`, since pruned with its
gate) from 104
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
more useful question than a run over a local tree.

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

**Merge rule (owner decision 2026-10-17):** merge on a green `CI` check for the head plus
a second-reader CLEAR for that head. No local verdict block is pasted or quoted.

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

**Run the gate in CI.** These are what CI runs, and all four must
pass before a merge (locally, run scoped checks per policy B above):

```bash
make host-gate      # all four, one command — run this
make lint           # ruff + strict mypy
make test           # pytest
make evidence       # regenerate every measurement, fail on drift
make verify-gates   # every done/merged task can still show its measurement
```

`host-gate` is the name `claude-arsenal` points a worker at. Note `make gate` is a different thing: it records T1's lint exit code, one
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
