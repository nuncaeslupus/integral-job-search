#!/usr/bin/env python3
"""Seed the arsenal queue from status/plan.md.

Parses the Implementation tasks table, topologically sorts it so --deps can be
given real task IDs, calls create_task.py per row, and writes a payload file
carrying the gate as a fenced bash block plus the named RED-first tests.

NOT idempotent. Task IDs are freshly minted on every run, so this seeds an
empty queue — it does not reconcile an existing one. Re-running against a
populated queue appends a second copy of every task. To reseed, clear
claude-arsenal/queue/ first, and expect the IDs to change; any work already
claimed or released against the old IDs is lost.

Each payload carries two blocks, and both are load-bearing: a ```gate block that
asserts the metric against its threshold from a committed evidence file, and a
```bash block that regenerates that file. Without the bash block a stale evidence
file passes unchallenged; without the gate block any command exiting 0 counts as
a pass whatever it measured. Tasks with no command in GATE_CMD get a block that
exits 1 — an unmeasured gate must fail, not pass quietly.

Run with --refresh-payloads to rewrite payload bodies for the tasks already in
the queue without minting new IDs.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLAN = REPO / "status/plan.md"
QUEUE = REPO / "claude-arsenal/queue/tasks.jsonl"
CREATE = REPO / ".claude/skills/queue-add/scripts/create_task.py"
PRIORITY = {"S": 10, "M": 5, "L": 1}

# Size-derived priority ranks small work first, which is the arsenal default and
# is wrong here: it would let a Medium fan-out task (T6, priority 5) be selected
# ahead of Large critical-path work (T3, priority 1) the moment T2 lands, and the
# selector sorts strictly by priority descending. The critical path is what
# unblocks the human bottleneck, so it gets its own band above every size score.
CRITICAL_PATH = {"T1": 100, "T2": 95, "T3": 90, "T4": 90, "T4b": 85}

# `tags` are informational at selection time — queue_batch.sh only filters on them
# when LOOP_TAGS is set, so a `human` tag does NOT stop a worker claiming the task.
# `requires` is enforced by default against the surface profile's capabilities, and
# no surface declares `surface:human`, so this is what actually keeps a worker off.
# (`laptop` is different: release.sh enforces it at release time via
# CLAUDE_CODE_REMOTE, so the tag alone is sufficient there.)
HUMAN_CAPABILITY = "surface:human"

# Per-task command that regenerates the task's evidence file. Filled in as each
# task's measurement becomes real; anything absent gets a block that fails loudly
# rather than one that passes for the wrong reason.
GATE_CMD = {
    "T1": "make gate",
}


def parse_rows() -> list[dict]:
    rows: list[dict] = []
    in_table = False
    for line in PLAN.read_text(encoding="utf-8").splitlines():
        if line.startswith("| T# | Description |"):
            in_table = True
            continue
        if in_table:
            if not line.startswith("|"):
                break
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 7 or set(cells[0]) <= {"-", ":"}:
                continue
            tid, desc, service, size, deps, gate, tests = cells[:7]
            if not re.match(r"^T\d+[a-z]?$", tid):
                continue
            rows.append(
                {
                    "tid": tid,
                    "desc": desc,
                    "service": service,
                    "size": size,
                    "deps": [] if deps == "—" else [d.strip() for d in deps.split(",")],
                    "gate": gate.strip("`"),
                    "tests": tests,
                }
            )
    return rows


def toposort(rows: list[dict]) -> list[dict]:
    by_id = {r["tid"]: r for r in rows}
    out: list[dict] = []
    seen: set[str] = set()

    def visit(tid: str, stack: tuple[str, ...] = ()) -> None:
        if tid in seen:
            return
        if tid in stack:
            raise SystemExit(f"cycle through {tid}")
        for dep in by_id[tid]["deps"]:
            if dep not in by_id:
                raise SystemExit(f"{tid} depends on unknown {dep}")
            visit(dep, (*stack, tid))
        seen.add(tid)
        out.append(by_id[tid])

    for r in rows:
        visit(r["tid"])
    return out


def payload(row: dict) -> str:
    human = "[HUMAN]" in row["desc"]
    laptop = "[LAPTOP]" in row["desc"]
    metric = row["gate"].split()[0]
    body = [
        f"# {row['tid']}: {row['desc']}",
        "",
        "## Acceptance gate",
        "",
        "```gate",
        row["gate"],
        f"evidence: status/evidence/{row['tid']}.json",
        f"key: {metric}",
        "```",
        "",
        "```bash",
        GATE_CMD.get(
            row["tid"],
            f'echo "no gate command defined for {row["tid"]} — replace this line with the '
            f'command that writes status/evidence/{row["tid"]}.json" >&2; exit 1',
        ),
        "```",
        "",
        "The two blocks do different jobs and both are required. The `bash` block",
        f"regenerates `status/evidence/{row['tid']}.json`; the `gate` block asserts the",
        "number in it against the threshold. Without the first, a stale or hand-written",
        "evidence file passes unchallenged; without the second, a command that exits 0",
        "counts as a gate whatever it measured.",
        "",
        "The default command fails on purpose. A task whose measurement is undefined has",
        "not passed its gate — it has not been measured. Replace it as part of the work.",
        "",
        "## Tests",
        "",
        "Write these RED before any production code:",
        "",
        row["tests"],
        "",
        "## Location",
        "",
        f"Service: **{row['service']}** · Size: {row['size']}",
        "",
        f"Design: `status/plan.md` ({row['tid']}) · Spec: `status/specification.md` "
        "§5 contracts · Methods: `docs/METHODS.md`",
    ]
    if human:
        body += [
            "",
            "## Human-owned",
            "",
            "Requires the candidate personally. Carries `requires: [surface:human]`, a",
            "capability no surface declares, so the selector excludes it by default — the",
            "`human` tag alone would not, since tags only filter when LOOP_TAGS is set.",
        ]
    if laptop:
        body += [
            "",
            "## Laptop-only",
            "",
            "Needs egress to job boards, which the cloud session's policy denies (403 at",
            "the proxy). Tagged `laptop`; release.sh refuses `done` from a cloud session",
            "via CLAUDE_CODE_REMOTE, so a cloud worker cannot falsely complete it.",
        ]
    return "\n".join(body) + "\n"


def refresh_payloads() -> int:
    """Rewrite payload bodies for the tasks already in the queue, keeping their IDs.

    Seeding is destructive — it mints new IDs and orphans any claim already made
    against the old ones. When only the payload text needs to change, this maps
    each plan row to the task that already carries it and rewrites just that file.
    """
    rows = {r["tid"]: r for r in parse_rows()}
    written = 0
    for line in QUEUE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        task = json.loads(line)
        m = re.match(r"^(T\d+[a-z]?):", task["title"])
        if not m or m.group(1) not in rows:
            print(f"  ! no plan row for {task['id']} ({task['title'][:40]})", file=sys.stderr)
            continue
        (REPO / f"claude-arsenal/queue/{task['payload']}").write_text(
            payload(rows[m.group(1)]), encoding="utf-8"
        )
        written += 1
    print(f"refreshed {written} payload(s); task IDs unchanged")
    return 0


def main() -> int:
    if "--refresh-payloads" in sys.argv:
        return refresh_payloads()
    rows = toposort(parse_rows())
    ids: dict[str, str] = {}
    for row in rows:
        human = "[HUMAN]" in row["desc"]
        title = f"{row['tid']}: {row['desc'].replace('**[HUMAN]** ', '').replace('**', '')}"
        laptop = "[LAPTOP]" in row["desc"]
        priority = CRITICAL_PATH.get(row["tid"], PRIORITY.get(row["size"], 5))
        cmd = [
            sys.executable,
            str(CREATE),
            "--title",
            title,
            "--priority",
            str(priority),
            "--workspace",
            row["service"],
            "--queue",
            str(QUEUE),
        ]
        for dep in row["deps"]:
            cmd += ["--deps", ids[dep]]
        if human:
            cmd += ["--tag", "human", "--requires", HUMAN_CAPABILITY]
        if laptop:
            cmd += ["--tag", "laptop"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        task_id = result.stdout.strip().split()[-1]
        ids[row["tid"]] = task_id

        (REPO / f"claude-arsenal/queue/{task_id}.md").write_text(payload(row), encoding="utf-8")
        marks = "".join(m for m, on in ((" human", human), (" laptop", laptop)) if on)
        print(f"{row['tid']:5} -> {task_id}  p{priority:<3} [{row['service']}]{marks}")
    print(f"\nseeded {len(ids)} task(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
