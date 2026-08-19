<!-- claude-arsenal: auto-managed -->
## Automatic session protocol

Every session, without waiting to be asked:

1. Read `claude-arsenal/project/overview.md` (project + workspace index).
2. Read `claude-arsenal/session/handover.md` for last session activity.
3. Run `claude-arsenal/bin/queue_eval.sh`.
   - **Tasks available** → start worker loop (see `@claude-arsenal/AGENTS.md`).
   - **Queue empty + workspace plans exist** → seed from each workspace's plan, then workers.
   - **Queue empty + `status/plan.md` exists** → seed from it, then workers.
   - **Nothing** → ask what to work on.
4. After any session with tasks: update workspace handover + global session handover.

@claude-arsenal/AGENTS.md

<!-- host-owned: not managed by claude-arsenal -->
## Known environment state

**GitHub Actions is out of runner minutes until the next billing period
(noted 2026-08-19).** Every job on every workflow run fails in 3–5 seconds with
`runner_id: 0` and `runner_name: ""` — no runner is ever assigned. This affects
`main` as much as any branch: run #142 on `ba7c980` (main's own HEAD) failed
identically, while the last green run was #137. It is not caused by any diff.

Do not treat a red CI on this repository as a signal about the code, and do not
push speculative "fixes" for it. Diagnose it once by checking a failed job for
`runner_id: 0` plus a sub-5-second duration; if both hold, it is this.

**Run the gate locally instead** — these are exactly what CI would run, and all
five must pass before a merge:

```bash
make lint           # ruff + strict mypy
make test           # pytest
make evidence       # regenerate every measurement, fail on drift
make verify-subtree # the arsenal bundle matches its subtree
make verify-gates   # every done/merged task can still show its measurement
```

Remove this section once runs are completing with real durations again.
