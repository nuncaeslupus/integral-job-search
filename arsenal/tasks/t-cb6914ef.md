---
id: t-cb6914ef
title: "T103: Set merge-policy to after-ci-and-review now that runners are back"
priority: 10
deps: [t-44c70ded]
tags: [CI]
workspace: BACKEND
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

```bash
test "$(python3 claude-arsenal/scripts/arsenal_config.py --get merge-policy)" = "after-ci-and-review"
```

Then the precondition the policy rests on — every job in every workflow runs a
target the Makefile actually defines, which is `t-44c70ded`'s measurement read back:

```bash
uv run --extra dev python -c '
import json, pathlib
m = json.loads(pathlib.Path("status/evidence/D-22.json").read_text())
assert m["ci_targets_missing_from_makefile"] == 0, m
print("ci targets all resolve")
'
```
