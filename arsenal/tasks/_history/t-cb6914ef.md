---
id: t-cb6914ef
title: "T103: Set merge-policy to after-ci-and-review now that runners are back"
priority: 10
deps: [t-44c70ded]
tags: [CI]
workspace: BACKEND
status: merged
---

Imported from issue #182. It was filed to be done *once runners return*; they
returned on 2026-09-01 — runs complete in ~56 seconds with real conclusions.

`arsenal/config.toml` says `merge-policy = "after-review"`, which was right while
every job failed in four seconds for want of a runner: requiring CI then would have
blocked every merge in the repository. That premise is gone.

**The dependency is not bookkeeping.** `after-ci-and-review` makes a red check
blocking, so it may only be set over a CI that is green for real reasons. This
repository carried a permanently-failing job for weeks (#269); flipping the policy
while that stood would have wedged the repository, and whoever unwedged it would
have had to weaken the policy to do it.

Deleting that one dead job does not satisfy the precondition — `t-44c70ded` is the
check that says no *other* job names a target that no longer exists.

## Acceptance gate

```gate
merge_policy_ignores_ci == 0
evidence: status/evidence/T103.json
key: merge_policy_ignores_ci
status-key: gate_status
```

```bash
test "$(python3 claude-arsenal/scripts/arsenal_config.py --get merge-policy)" = "after-ci-and-review"
uv run python -m integral.merge_policy --check
uv run --extra dev pytest tests/test_merge_policy.py -q
```

Both preconditions below are readings inside `integral.merge_policy`'s metric —
`merge_policy_ignores_ci` counts eight of them, and one that cannot be taken
records `gate_status: unmeasured` rather than a pass. The commands here are the
live form, run once when the PR is opened; the module re-reads T101's key on
every `make evidence` and reads the `CI` conclusion from `status/ci-conclusion.json`,
a capture `--refresh-ci` rewrites deliberately (a value fetched per run would
drift the evidence the moment CI changed colour or the machine went offline).

Then the two preconditions, because the policy is a claim about **GitHub Actions
conclusions** and not about `make ci`. `arsenal/config.toml` already draws that
distinction and it is the reason this task is not a one-line edit: a local run is
not the same assertion as a green CI, however identical the commands.

First — every job in every workflow runs a target the Makefile defines, which is
`t-44c70ded`'s measurement. `ci_targets_missing_from_makefile` does **not** exist in
`status/evidence/D-22.json` today; `t-44c70ded` adds it, and the explicit
key-presence check below is what makes the dependency fail legibly rather than as a
`KeyError` from a task that ran too early:

```bash
uv run --extra dev python -c '
import json, pathlib, sys
m = json.loads(pathlib.Path("status/evidence/D-22.json").read_text())
if "ci_targets_missing_from_makefile" not in m:
    sys.exit("D-22 does not carry that key yet — t-44c70ded (T101) has not landed")
assert m["ci_targets_missing_from_makefile"] == 0, m
print("ci targets all resolve")
'
```

Second — Actions has actually concluded green on the default branch, recently. The
premise being retired is *CI does not report*; a policy that makes CI blocking needs
evidence that it reports, not a memory that it started to:

```bash
gh run list --workflow CI --branch main --limit 1 \
    --json conclusion,createdAt --jq '
  if length == 0 then error("no CI runs on main")
  elif .[0].conclusion != "success" then error("latest CI on main: \(.[0].conclusion)")
  else "latest CI on main: success at \(.[0].createdAt)" end'
```

`--workflow CI` and not a `jq` filter over a mixed list: `--limit` is applied by
the API *before* anything selects a workflow, so five `arsenal queue` runs
pushed in quick succession — which is a normal thing to happen on `main` — would
hide the latest `CI` run and the check would report `no CI runs on main`. A
precondition that fails for a reason unrelated to its subject gets waved through
the second time it happens.
