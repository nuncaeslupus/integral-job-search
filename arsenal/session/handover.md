# Session handover — 2026-08-26 ~08:30 UTC, orchestrator takeover + second fleet round

Board: **103 gates on `main`**, 124 tasks. `main` at `0033160`. Two of five PRs merged;
every merge was gate-verified by the orchestrator on that exact commit, never on a
worker's word.

| PR | task | threads | state |
|---|---|---|---|
| [#226](https://github.com/nuncaeslupus/integral-job-search/pull/226) | T81 keyword coverage | resolved | **merged** `0033160`; #210 auto-closed |
| [#228](https://github.com/nuncaeslupus/integral-job-search/pull/228) | T85 evidence reach | none | **merged** `7adf423`; #217 auto-closed |
| [#221](https://github.com/nuncaeslupus/integral-job-search/pull/221) | T72 connector health | 1 held | gate now `unmeasured` per owner's decision; must NOT close #203. **Needs the combined `evidence` recipe below — main now carries T85's discovery half.** |
| [#225](https://github.com/nuncaeslupus/integral-job-search/pull/225) | claude-arsenal v2.4.22 | 1 parked | CodeRabbit holds it open until upstream ships `claude-arsenal#253` |
| [#227](https://github.com/nuncaeslupus/integral-job-search/pull/227) | T70 robots | 3 open | **NOT merge-ready — still fails open. Owner decision.** |

The merge authorisation is the one in the previous handover and still stands: squash, when
the PR is not held, every CodeRabbit thread reads `is_resolved: true`, and `make host-gate`
was run on that branch by the orchestrator. Both merges met all three. The predicted
`D12.json` conflict did **not** materialise on #226 — `main` merged cleanly and only
`make evidence` regeneration was needed.

## The finding that matters more than any individual fix

**Seven-plus real defects across four PRs today, every one a check that could not report
its own inability to run, every one behind a green `make host-gate`.**

- T72: the probe compared a fixture with itself; rot was undetectable while the evidence
  said `measured`.
- T70: no adversarial fixture — five review rounds found a ReDoS (measured hanging past
  60s), two encoding asymmetries, two precedence errors, and three more still open.
- T85: the reach check raised a traceback instead of reporting `unmeasured`.

**Eight of T70's ten findings were introduced by the orchestrator's own fixes**, each
pushed after verifying the previous defect, adding fixtures and seeing a green gate. That
is not carelessness per round; it is what happens when one author writes both the code and
the fixtures that judge it. Percent-encoding equivalence for robots matching has a long
tail (`%`, `?`, `$`, `*`, empty delimiters, unreserved octets, product tokens) and it was
met one review at a time.

**Proposed process change, awaiting the owner:** adversarial fixtures for a task written by
a session *other* than the implementer, derived from the spec rather than the code, before
review. More care did not fix this — four careful rounds did not.

## Decisions the owner made this session

1. **T72: the honest fix.** Probe reads `probe/list.html`, a separately captured read that
   does not exist here, so the gate is `unmeasured`. T72 is **un-archived and open**;
   `Closes #203` was removed from the PR body and must be omitted from the squash message.
   Finishes when someone captures `connectors/trabajos_es/probe/list.html` on the laptop.
2. **Fleet: three workers** — T70, T81, T85, all completed and pushed.

## Decisions still owed

1. **The `.claude/settings.json` paste** — here *and* in `nuncaeslupus/opos`, which carries
   an identical block. See "auto mode" below. A session cannot apply it.
2. **#225's parked thread** — blocks that PR indefinitely under the all-threads-resolved
   rule, by CodeRabbit's own choice.
3. **Merge #228 first?** It triggers #221's conflict (see below).
4. **The adversarial-fixture process change.**
5. **T70's scope** — patch it further, or accept that a correct RFC 9309 matcher is larger
   than the task assumed. Same shape as T72's decision.

## The #221 / #228 conflict — do NOT resolve mechanically

Both rewrite the `Makefile`'s `evidence` recipe, and each keeps only half of what the
merged result needs. PR #228 replaces module *discovery* — the derived `grep -l '^def
_main'` list becomes `repo_gate --list-evidence-modules`, which is the whole point of
T85 — but keeps the old `|| GATE FAILED` handling. PR #221 keeps the old discovery and
replaces that handling, so a module reporting exit 3 records as `unmeasured`, without
which T72's honest gate cannot be recorded at all.

Taking either side wholesale silently undoes the other, **and neither loss fails a
test**, because each branch's own fixtures pass on its own change. The correct merged
recipe keeps both:

```make
@for m in $$(uv run python -m integral.repo_gate --list-evidence-modules); do \
	printf '  %-18s ' "$$m"; \
	uv run python -m integral.$$m >/dev/null; status=$$?; \
	case $$status in \
		0) echo ok ;; \
		3) echo "unmeasured (recorded)" ;; \
		*) echo "GATE FAILED"; exit 1 ;; \
	esac; \
done
```

PRs #221, #227 and #228 all touch `status/evidence/D12.json`/`T55.json`; regenerate with
`make evidence`, never hand-edit.

## Capability findings — three contradict the previous handover

- **A spawned worker CAN open its own PR.** #226 was opened by
  `session_016QzEMD7VNkJv5JbMU352Qx` itself. The prior handover recorded as *measured* that
  a child has no GitHub API and that `open_task_pr.sh`'s last step 403s. **Falsified for PR
  creation.** The whole orchestrator/worker split rests on that invariant — re-measure it.
- **A worker also schedules its own check-ins.** `trig_01KzrSNDviGWcZTkmL4dEnFZ` is
  self-bound to that worker to babysit #226 — so two agents may act on one PR.
- **A self-bound routine keeps its `mcp__*` tools.** The 08:16 tick fired into this live
  session with every tool intact. *Limit:* the container was alive throughout, so a cold
  resume is still unmeasured. Do not round that up.
- **Auto mode has a second permission gate.** `permissions.allow` is not what prompts:
  `create_session` and `get_session` were both allow-listed and both prompted anyway. The
  classifier is configured under a top-level `autoMode` key (`allow`/`soft_deny`/
  `hard_deny`, `"$defaults"` inherits). It also **hard-blocks a session editing
  `.claude/settings.json`** — four attempts, three tools, including the sanctioned
  `update-config` skill. That is correct and must not be routed around.
- **Three `create_session` calls in one message are all denied; one per message all
  succeed.** Dispatch workers one call at a time.

## Costs

T85 alone was **$8.73** against a ~$5.45 estimate; T70 and T81 unmeasured but comparable.
A separate orchestrator is running in `nuncaeslupus/opos` on the same account, sharing
CodeRabbit's 10-reviews/hour ceiling — which is part of why reviews stalled here.

## Unchanged and still true

CI is red repository-wide: `runner_id: 0`, no runner assigned, ~3s per job, red on `main`.
**Measured again today** — the check *"task PR closes its task"* failed on #227, whose body
carries `Closes #209`, which could only pass with a runner. Never gate merging on it.

Commit before gating (`make evidence` compares committed evidence). Never put an
angle-bracket placeholder in a GitHub body. Vendored `claude-arsenal/` and
`.claude/skills/` are refreshed by `/init`, never hand-edited — CodeRabbit has now
recorded that as a learning.

Skip `lo-4b17` (T59), `lo-6f53` (T56), `lo-7c14` (T57). Next unblocked: `t-854ae281` (T75),
`t-921a4ef5` (T74), `t-9e5a05a0` (T82).

## Upstream

`claude-arsenal` **#253** filed today: v2.4.22's skew-probe fallback still picks a winner
among ambiguous candidates instead of declining. #245–#251 remain open; **#249's proposed
fix is falsified** — this repo already carries all ten entries and still prompts (see auto
mode above), and that is commented on the issue. Deduplicate by content before filing more.
