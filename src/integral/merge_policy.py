"""T103 — the configured merge policy makes a red CI blocking.

`arsenal/config.toml` carried ``merge-policy = "after-review"`` for as long as
GitHub Actions had no runner minutes here: every job failed in three to five
seconds with no runner ever assigned, so ``after-ci`` would have been either a
block on every merge for the duration or a rule everyone learned to wave
through. Runners returned on 2026-09-01 — runs complete in ~56 seconds with
real conclusions — and the value is now ``after-ci-and-review``.

The gate is ``merge_policy_ignores_ci == 0``, and it is deliberately not a
one-line read of that key. Two things the plan row insists on shape this
module:

* **The policy is a claim about GitHub Actions conclusions, not about ``make
  ci``.** A local run of the identical commands is a different assertion, so a
  green ``make host-gate`` is no evidence at all for this one. The reading has
  to come from what Actions concluded on the default branch.
* **A strict policy over a CI that cannot be green wedges the repository.**
  This repo carried a permanently-failing job for weeks (#269, fixed by T101);
  flipping the policy while that stood would have blocked every merge, and
  unwedging it would have meant weakening the policy again. So T101's
  ``ci_targets_missing_from_makefile`` and the latest ``CI`` conclusion on
  ``main`` are *readings inside the metric*, not prose beside it.

Hence the denominator: eight readings, each answering the same question — does
a red check actually stop a merge here?

1. the configured policy makes a red check blocking;
2. -6. five controls, one per documented policy value, that the classifier
   must read correctly (a reader that has broken counts as a violation, so the
   number moves when the reader breaks and not only when the config does);
7. every ``make`` target a CI job names is a rule the Makefile defines (T101) —
   a job calling a target that does not exist cannot report on the code, so a
   policy "requiring CI" would be requiring nothing;
8. the latest ``CI`` run on ``main`` concluded ``success``.

A reading that *cannot be taken* is not a zero. An unreadable config, a
``status/evidence/D-22.json`` that does not yet carry T101's key, or a missing
CI capture each make ``gate_status`` ``"unmeasured"`` — the explicit
key-presence check is what makes the dependency on T101 fail legibly instead of
as a ``KeyError`` from a task that ran too early.

**The CI conclusion is a committed capture, refreshed deliberately.** ``make
evidence`` regenerates every record and refuses a diff, so a conclusion fetched
from the network on each run would drift the moment CI changed colour or the
machine went offline — and the target that exists to catch a stale number would
be the one nobody could keep green. ``status/ci-conclusion.json`` holds the
reading with the date it was taken, exactly as T72's connector probes do, and
``--refresh-ci`` is what rewrites it. What that does not buy is freshness:
nothing forces a refresh, so ``captured_at`` is the only warning a reader gets
that a policy is standing on an old observation.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = _REPO_ROOT / "arsenal" / "config.toml"
DEFAULT_D22_PATH = _REPO_ROOT / "status" / "evidence" / "D-22.json"
DEFAULT_CAPTURE_PATH = _REPO_ROOT / "status" / "ci-conclusion.json"
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T103.json"

CONFIG_KEY = "merge-policy"

#: T101's key in D-22's record. Named here rather than inlined because its
#: *absence* is a distinct verdict from its value, and both are quoted in the
#: reasons this module prints.
CI_TARGETS_KEY = "ci_targets_missing_from_makefile"

WORKFLOW = "CI"
BRANCH = "main"

#: Every value `arsenal/config.toml` documents, paired with whether a red check
#: stops a merge under it. `never` is in the blocking column because nothing
#: merges under it at all — it is stricter than this gate asks for, not looser.
CONTROL_POLICIES: tuple[tuple[str, bool], ...] = (
    ("always", False),
    ("after-review", False),
    ("after-ci", True),
    ("after-ci-and-review", True),
    ("never", True),
)


def a_red_check_blocks(policy: str) -> bool:
    """Whether a failing GitHub check stops a merge under `policy`.

    An unrecognised value reads as *not* blocking. That is the fail-closed
    direction: a typo in the setting must fail this gate rather than pass it by
    being unclassifiable.
    """
    return policy in {"after-ci", "after-ci-and-review", "never"}


def configured_policy(config: Path = DEFAULT_CONFIG_PATH) -> str | None:
    """`arsenal/config.toml`'s `merge-policy`, or `None` if it cannot be read.

    `UnicodeError` is in the tuple with the parse errors because
    `read_text(encoding="utf-8")` raises `UnicodeDecodeError` for a file that
    is not valid UTF-8, and that is neither an `OSError` nor a parse error — it
    would have taken the command down instead of reporting `unmeasured`. The
    same applies to the two JSON readers below (#304 review). A file this
    module cannot decode is a file it cannot read, and every reader here has
    one answer for that.
    """
    try:
        payload = tomllib.loads(config.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        return None
    value = payload.get(CONFIG_KEY)
    return value if isinstance(value, str) else None


def ci_targets_missing(d22: Path = DEFAULT_D22_PATH) -> int | None:
    """T101's count, or `None` when the record cannot answer yet.

    `None` covers both "D-22 is unreadable" and "D-22 does not carry the key",
    which is the case that matters: until `t-44c70ded` lands there is no
    reading, and this gate has to say so rather than raise.
    """
    try:
        record = json.loads(d22.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    value = record.get(CI_TARGETS_KEY) if isinstance(record, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def read_capture(capture: Path = DEFAULT_CAPTURE_PATH) -> dict[str, Any] | None:
    """The committed CI observation, or `None` if there is not a usable one."""
    try:
        record = json.loads(capture.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(record, dict):
        return None
    if record.get("workflow") != WORKFLOW or record.get("branch") != BRANCH:
        # A capture of some other workflow or branch answers a different
        # question; treating it as this one's answer is the whole hazard.
        return None
    if not isinstance(record.get("captured_at"), str):
        return None
    return record


def refresh_capture(capture: Path = DEFAULT_CAPTURE_PATH) -> dict[str, Any]:
    """Fetch the latest `CI` conclusion on `main` and write it to `capture`.

    `--workflow CI` and not a `jq` filter over a mixed list: `--limit` is
    applied by the API *before* anything selects a workflow, so a handful of
    `arsenal queue` runs pushed in quick succession — normal on `main` — would
    hide the latest `CI` run and the reading would report that there are none.
    A precondition that fails for a reason unrelated to its subject gets waved
    through the second time it happens.
    """
    result = subprocess.run(
        [
            "gh",
            "run",
            "list",
            "--workflow",
            WORKFLOW,
            "--branch",
            BRANCH,
            "--limit",
            "1",
            "--json",
            "conclusion,createdAt,databaseId",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    runs = json.loads(result.stdout)
    if not runs:
        raise RuntimeError(f"no {WORKFLOW} runs on {BRANCH} to capture")
    run = runs[0]
    record = {
        "workflow": WORKFLOW,
        "branch": BRANCH,
        "conclusion": run.get("conclusion"),
        "run_id": run.get("databaseId"),
        "run_created_at": run.get("createdAt"),
        "captured_at": datetime.now(UTC).date().isoformat(),
    }
    capture.parent.mkdir(parents=True, exist_ok=True)
    capture.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return record


def measure(
    config: Path = DEFAULT_CONFIG_PATH,
    d22: Path = DEFAULT_D22_PATH,
    capture: Path = DEFAULT_CAPTURE_PATH,
) -> dict[str, Any]:
    """T103's reading: `merge_policy_ignores_ci` over its eight readings."""
    policy = configured_policy(config)
    missing_targets = ci_targets_missing(d22)
    observation = read_capture(capture)
    conclusion = observation.get("conclusion") if observation else None
    captured_at = observation.get("captured_at") if observation else None
    run_id = observation.get("run_id") if observation else None

    record: dict[str, Any] = {
        "merge_policy": policy,
        "merge_policy_ignores_ci": 0,
        "merge_policy_ignores_ci_evaluated": 0,
        "policy_reader_controls": [name for name, _ in CONTROL_POLICIES],
        "policy_reader_control_failures": [],
        CI_TARGETS_KEY: missing_targets,
        "latest_ci_conclusion_on_main": conclusion,
        "latest_ci_run_on_main_captured_at": captured_at,
        "latest_ci_run_on_main_id": run_id,
        "readings_that_say_ci_does_not_block": [],
        "gate_status": "unmeasured",
    }

    unreadable: list[str] = []
    if policy is None:
        unreadable.append(f"{config.name} carries no readable `{CONFIG_KEY}`")
    if missing_targets is None:
        unreadable.append(
            f"{d22.name} does not carry `{CI_TARGETS_KEY}` yet — t-44c70ded (T101) has not landed"
        )
    if observation is None:
        unreadable.append(
            f"no captured `{WORKFLOW}` conclusion for `{BRANCH}` at {capture.name}; "
            "run `python -m integral.merge_policy --refresh-ci`"
        )
    if unreadable:
        record["unmeasured_reason"] = "; ".join(unreadable)
        return record

    assert policy is not None and missing_targets is not None  # narrowed by `unreadable`

    control_failures = [
        name for name, blocks in CONTROL_POLICIES if a_red_check_blocks(name) is not blocks
    ]
    says_no: list[str] = []
    if not a_red_check_blocks(policy):
        says_no.append(f"merge-policy is `{policy}`, under which a red check does not stop a merge")
    says_no += [f"the policy reader misreads the control `{name}`" for name in control_failures]
    if missing_targets:
        says_no.append(
            f"{missing_targets} CI step(s) run a `make` target the Makefile does not define, "
            "so those jobs cannot report on the code"
        )
    if conclusion != "success":
        says_no.append(f"the latest {WORKFLOW} run on {BRANCH} concluded {conclusion!r}")

    record["merge_policy_ignores_ci"] = len(says_no)
    record["merge_policy_ignores_ci_evaluated"] = 1 + len(CONTROL_POLICIES) + 2
    record["policy_reader_control_failures"] = control_failures
    record["readings_that_say_ci_does_not_block"] = says_no
    record["gate_status"] = "measured"
    return record


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    config: Path = DEFAULT_CONFIG_PATH,
    d22: Path = DEFAULT_D22_PATH,
    capture: Path = DEFAULT_CAPTURE_PATH,
) -> dict[str, Any]:
    """Measure and record `status/evidence/T103.json`."""
    measured = measure(config, d22, capture)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.merge_policy [--check] [--refresh-ci]`.

    Exit 3 is "unmeasured" — the verdict `make evidence` records rather than
    treats as a failure. Exit 1 is a reading that says a red check does not
    stop a merge here.
    """
    parser = argparse.ArgumentParser(description="T103: the merge policy makes a red CI blocking")
    parser.add_argument(
        "--check", action="store_true", help="measure and report only; do not write the evidence"
    )
    parser.add_argument(
        "--refresh-ci",
        action="store_true",
        help=(
            f"re-fetch the latest {WORKFLOW} conclusion on {BRANCH} with `gh` and rewrite "
            "status/ci-conclusion.json — a deliberate act that shows up in a diff"
        ),
    )
    args = parser.parse_args(argv[1:])

    if args.refresh_ci:
        print(json.dumps(refresh_capture(), ensure_ascii=False))

    measured = measure() if args.check else write_evidence()
    print(json.dumps(measured, ensure_ascii=False))
    if measured["gate_status"] == "unmeasured":
        print(measured["unmeasured_reason"], file=sys.stderr)
        return 3
    for reason in measured["readings_that_say_ci_does_not_block"]:
        print(reason, file=sys.stderr)
    return 1 if measured["merge_policy_ignores_ci"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
