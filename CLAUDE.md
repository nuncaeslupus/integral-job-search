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

**In a cloud session it prints `rest`, and REST does not work there**: the proxy
answers `403 GitHub access is not enabled for this session` (`claude-arsenal#182`).
Don't probe it again — the MCP GitHub tools are the *API* channel, so every GitHub
API step is performed with them, and the board JSON the scripts read is written to
disk by hand from the tool result. In that session, and only there:

- `claim_task.sh` returns `manual POST`; `create_branch` on `arsenal/claims/<id>`
  is the compare-and-swap. **201 = won, 422 = lost.**
- **`open_task_pr.sh` works — `git push` is not restricted.** This file used to say
  pushes were confined to the session's designated branch, and that was simply wrong:
  a real push of a fresh branch returns exit 0 (measured 2026-08-25, not a `--dry-run`
  — dry runs skip the receive hooks and prove nothing here). So the script cuts its
  branch off `origin/main`, runs the gate, commits and pushes exactly as it does on
  the laptop. Only its **last** step fails, because that step alone uses REST. Pass
  `ARSENAL_TASK_ISSUE=<n>` — a 403 channel cannot resolve the issue number either —
  let it push, then open the PR with the MCP tool. `Closes #<issue>` goes in **both**
  the commit message and the PR body.
- **Remote ref deletion is blocked.** `git push --delete` reports
  `send-pack: unexpected disconnect` and then `Everything up-to-date`, and the ref is
  still there. Never script a branch cleanup here: it looks like a failure and is
  actually a no-op.
- Merging works via the MCP `merge_pull_request` tool.

## No session this one spawns can reach the GitHub API — the fleet is shaped by this

**A spawned session has no `mcp__*` tools.** This holds for both ways of making one,
and it is the single most expensive thing to rediscover:

- A Routine with `create_new_session_on_fire` says so at creation: *"this trigger
  stores no MCP connectors, so the sessions it fires will run without connector
  tools"*, and the fired session's `allowed_tools` carry no `mcp__*` entry.
- A `create_session` child carries no such warning but behaves identically — measured
  2026-08-25, two children reported *"GitHub access denied (403); no MCP tools
  available to fetch task board"* and blocked. **Do not assume a child inherits the
  parent's connectors.** It does not.

With REST already 403, a spawned session's only channel to GitHub is plain `git`.
That is enough to fetch, to read claim refs
(`git ls-remote origin 'refs/heads/arsenal/claims/*'`), to derive terminal state from
`arsenal/tasks/_history/*.md` (each archived file carries `status: merged`, and
`effective_state` reads it), and to **push a branch**. It is not enough to read
issues, label or assign one, open a PR, or merge.

So the split is forced, and it is the one `worker-loop.md` already specifies —
*"workers never claim or release: the orchestrator owns the claim"*:

| | holds the GitHub API | does the work |
|---|---|---|
| **Orchestrator** — an interactive session, woken by a **self-bound** routine (omit `create_new_session_on_fire`) | yes | fetch the board, claim with `create_branch` (201 won / 422 lost), dispatch children, open each PR, merge after review |
| **Child** — one per task, via `create_session` | no | worktree, implement, `make host-gate`, `ARSENAL_TASK_ISSUE=<n> open_task_pr.sh` up to and including the push, then stop |

A child is told its task id, issue number and branch name by the orchestrator, so it
never needs to resolve any of them. It ends when its task does, which is what keeps an
unattended run from ever needing to compact: the only long-lived context is the
orchestrator's, and everything it must remember is in GitHub, not in the window.

Steps 3 and 4 of the protocol need no workaround on either surface — **in an
orchestrator session**, run them as written; a child runs neither. Since the fetch drops `body`, issues resolve to tasks by **title**;
v0.36.1 made that robust and `query_status.py` names anything that still fails to
resolve. Trust that list over `handle_sync.py`'s proposals — only one of the two is
wired to an action.

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
