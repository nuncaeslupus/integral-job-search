---
id: t-44c70ded
title: "T101: A CI job can name a Makefile target that does not exist"
priority: 5
tags: [CI]
workspace: BACKEND
---

Imported from issue #269. **Its steps 1 and 3 are already done** — PR #267 deleted
the dead `verify-subtree` job and retired the runner-outage section of `CLAUDE.md`.
What is left is the half that stops it happening again.

`integral.repo_gate` (D-22) exists so that a gate the documentation requires has
something that runs it. It reads every `make <target>` out of `CLAUDE.md`, asserts
the target is a real rule, and asserts it is reached from `host-gate`. That is why a
fifth line added to the CLAUDE.md list cannot quietly go unrun.

`DEFAULT_INSTRUCTIONS` is `CLAUDE.md` and nothing else. **No check reads
`.github/workflows/`.** So the identical hole one file over stayed open, and a job
fell through it: `a4e9541` (T58, #123) removed the `verify-subtree` target when the
bundle stopped being a subtree, and left the job calling it. It failed on every run
from then until 2026-09-01 — invisible, because for most of that window the runner
outage failed every job for an unrelated reason.

**The two directions are not the same check, and only one of them is this task.**

- *A target named in CI must exist* — a broken build step. This is the fault above,
  and it is what the gate below asserts.
- *A target that exists must be named in CI* — a target nobody runs. Tempting to add
  in the same pass and **wrong**: `format`, `clean`, `build`, `publish`, `sync`,
  `help`, `reader` and `labelling-round` are all deliberately not CI steps, so the
  assertion would be false on a correct repository from its first run, and the fix
  would be an allowlist edited every time a target is added. Assert the direction
  that has a defect behind it.

A step is `run: make x`, `run: make x y`, or a multi-line `run: |` block with `make`
on some line of it. Parse the YAML — a regex over the file text reads the word `make`
out of comments, and this repository's workflow comments discuss Make targets at
length. The comment that named `verify-subtree` in four surviving jobs is exactly
the input that would make a regex report a violation that is not there.

## Acceptance gate

```bash
uv run --extra dev pytest tests/test_repo_gate.py -q
uv run --extra dev python -m integral.repo_gate
```

Then the property, demonstrated against the fault this task came from — a workflow
naming a target the Makefile does not define must be **reported**, not ignored:

```bash
uv run --extra dev python -c '
import tempfile, pathlib, textwrap
from integral.repo_gate import ci_make_targets_missing
d = pathlib.Path(tempfile.mkdtemp())
(d / "Makefile").write_text("lint:\n\truff check .\n")
wf = d / ".github" / "workflows"
wf.mkdir(parents=True)
(wf / "ci.yml").write_text(textwrap.dedent("""
    jobs:
      lint:
        steps:
          # verify-subtree used to run here — a comment, not a step
          - run: make lint
      dead:
        steps:
          - run: make verify-subtree
"""))
missing = ci_make_targets_missing(d)
assert missing == ["verify-subtree"], missing
print("reported:", missing)
'
```

- `test_a_workflow_naming_an_absent_target_is_reported`
- `test_a_target_named_only_in_a_comment_is_not_read_as_a_step` — the regex trap.
- `test_a_multi_line_run_block_is_read`
- `test_a_target_the_makefile_defines_but_ci_never_runs_is_not_a_violation` — the
  direction this task deliberately does not assert.
