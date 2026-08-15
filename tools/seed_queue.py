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

The gate command in each payload is a placeholder (`make lint && make test`).
The measuring command belongs to the task and should replace it as the task is
worked, so gate_run.sh executes the check that actually produces the number.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLAN = REPO / "status/plan.md"
QUEUE = REPO / "claude-arsenal/queue/tasks.jsonl"
CREATE = REPO / ".claude/skills/queue-add/scripts/create_task.py"
PRIORITY = {"S": 10, "M": 5, "L": 1}


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
            visit(dep, stack + (tid,))
        seen.add(tid)
        out.append(by_id[tid])

    for r in rows:
        visit(r["tid"])
    return out


def payload(row: dict, gate_cmd: str) -> str:
    human = "[HUMAN]" in row["desc"]
    body = [
        f"# {row['tid']}: {row['desc']}",
        "",
        "## Acceptance gate",
        "",
        f"`{row['gate']}` — measured and recorded in the plan's Evidence log.",
        "",
        "```bash",
        gate_cmd,
        "```",
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
            "This task requires the candidate personally and cannot be completed by an",
            "agent worker. Tagged `human`. Do not claim it.",
        ]
    return "\n".join(body) + "\n"


def main() -> int:
    rows = toposort(parse_rows())
    ids: dict[str, str] = {}
    for row in rows:
        human = "[HUMAN]" in row["desc"]
        title = f"{row['tid']}: {row['desc'].replace('**[HUMAN]** ', '').replace('**', '')}"
        cmd = [
            sys.executable,
            str(CREATE),
            "--title",
            title,
            "--priority",
            str(PRIORITY.get(row["size"], 5)),
            "--workspace",
            row["service"],
            "--queue",
            str(QUEUE),
        ]
        for dep in row["deps"]:
            cmd += ["--deps", ids[dep]]
        if human:
            cmd += ["--tag", "human"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        task_id = result.stdout.strip().split()[-1]
        ids[row["tid"]] = task_id

        gate_cmd = "make lint && make test  # replace with the check that measures the gate"
        (REPO / f"claude-arsenal/queue/{task_id}.md").write_text(
            payload(row, gate_cmd), encoding="utf-8"
        )
        print(f"{row['tid']:5} -> {task_id}  [{row['service']}]{' human' if human else ''}")
    print(f"\nseeded {len(ids)} task(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
