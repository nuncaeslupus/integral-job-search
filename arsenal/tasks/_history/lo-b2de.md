---
id: lo-b2de
title: "T52: First-run bootstrap — the tool installs its own dependencies, and says so"
priority: 5
deps: [lo-4b79]
workspace: PROFILE
tags: [m4]
status: merged
pr: https://github.com/nuncaeslupus/job-search/pull/37
---

## Acceptance gate

```gate
unbootstrapped_first_runs == 0
evidence: status/evidence/T52.json
key: unbootstrapped_first_runs
```

```bash
uv run --extra dev pytest tests/test_bootstrap.py -q
uv run --extra dev python -m jobsearch.bootstrap --check
```

## What this is

`docs/distribution.md` §1: the install is `git clone`, `cd`, `claude`. The clone
delivers the skills and the code but not the installed dependencies, so the tool
installs them itself.

Two layers, because either alone leaves a hole:

1. a `SessionStart` hook that checks whether the environment is present and
   current and runs `uv sync` when it is not — silent when there is nothing to
   do, so it costs a returning candidate nothing;
2. a check inside step 0, before the first call into the code, for the session
   whose hook did not fire (a surface that does not run hooks, a clone opened a
   different way). The bootstrap must be idempotent for this reason.

`uv` itself may be absent: detect it and offer the one-line installer, or fall
back to `venv` + `pip`. Failing at an `ImportError` is the outcome this
forbids — a candidate cannot be expected to read a traceback.

**The candidate is told the first time it happens**, and told what is being
installed. A tool that silently runs a package manager on someone's machine is
not one they should trust with their working history.

## Tests

`test_a_clone_without_dependencies_installs_them_before_step_zero` in
`tests/test_bootstrap.py`; `test_bootstrap_is_silent_when_the_environment_is_current`;
`test_a_missing_package_manager_is_reported_not_raised`;
`test_the_first_install_is_announced_to_the_candidate`.

## Location

Service: **PROFILE** · Size: M · Depends: T51

Design: `docs/distribution.md` §1
