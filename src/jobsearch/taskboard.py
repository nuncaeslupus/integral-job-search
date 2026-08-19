"""Read the task board that replaced `claude-arsenal/queue/tasks.jsonl`.

claude-arsenal v0.26.0 moved the queue out of a JSONL ledger on a coordination
branch and into one markdown file per task, with the fields in YAML-ish front
matter and the payload as the body. Two directories hold them here:

- `arsenal/tasks/` — live work. These files carry no `status`; a task's real
  state comes from its GitHub issue, so anything found here is `open` as far as
  this module is concerned.
- `arsenal/tasks/_history/` — work that finished before the migration, in the
  same format plus the `status` and `pr` it ended with.

The second directory exists because the migration does not preserve finished
tasks: it writes their id, title and PR into a prose file and drops the payload
carrying the fenced ``gate`` block, along with their `deps`. Two checks in this
repository read exactly those fields — `tools/verify_gates.py` re-asserts every
terminal task's gate, and `jobsearch.plan_v2` compares the plan's `Depends`
column against the board's. Both would have gone quiet rather than red, which is
the worse failure: a check that silently stops checking still exits 0.

Rows come back in the shape the JSONL ledger used, so callers written against
the old board keep working — `deps` as `[{"id": …, "type": "blocks"}]` rather
than a bare list, and `payload` as a path that exists.

The parser is deliberately small and takes no YAML dependency: the writer is
`arsenal_migrate.task_markdown`, whose output is a fixed handful of scalar,
list and quoted-string fields. A real YAML parser would accept far more than
that function can emit, which buys nothing and hides a malformed file.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TASKS_DIR = _REPO_ROOT / "arsenal" / "tasks"
DEFAULT_HISTORY_DIR = DEFAULT_TASKS_DIR / "_history"

_INT_FIELDS = frozenset({"priority", "issue", "max-attempts"})
_LIST_FIELDS = frozenset({"deps", "requires", "tags"})


def parse_front_matter(text: str) -> dict[str, Any]:
    """The front-matter block of one task file, or `{}` if it has none.

    A file whose first line is not `---`, or that never closes the block, has
    no front matter — returning `{}` rather than raising lets a caller report
    the file by name instead of dying on the first malformed one.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    try:
        end = lines.index("---", 1)
    except ValueError:
        return {}
    meta: dict[str, Any] = {}
    for line in lines[1:end]:
        key, _, raw = line.partition(":")
        key, raw = key.strip(), raw.strip()
        if not key or not raw:
            continue
        if key in _LIST_FIELDS:
            inner = raw.removeprefix("[").removesuffix("]")
            meta[key] = [item.strip() for item in inner.split(",") if item.strip()]
        elif key in _INT_FIELDS:
            meta[key] = int(raw) if re.fullmatch(r"-?\d+", raw) else 0
        elif raw.startswith('"'):
            try:
                meta[key] = json.loads(raw)
            except json.JSONDecodeError:
                meta[key] = raw.strip('"')
        else:
            meta[key] = raw
    return meta


def _row(path: Path, *, default_status: str) -> dict[str, Any] | None:
    meta = parse_front_matter(path.read_text(encoding="utf-8"))
    if not meta.get("id"):
        return None
    return {
        "id": str(meta["id"]),
        "title": str(meta.get("title", "")),
        "status": str(meta.get("status", default_status)),
        "priority": meta.get("priority", 0),
        "deps": [{"id": dep, "type": "blocks"} for dep in meta.get("deps", [])],
        "requires": meta.get("requires", []),
        "tags": meta.get("tags", []),
        "workspace": meta.get("workspace"),
        "pr": meta.get("pr"),
        "payload": str(path),
    }


def load_board(
    tasks_dir: Path = DEFAULT_TASKS_DIR,
    history_dir: Path | None = DEFAULT_HISTORY_DIR,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Every task on the board, and a violation for each file that is not one.

    A file that will not parse is reported rather than skipped, for the reason
    the ledger readers gave: a board reduced to the entries that happened to be
    readable stops checking whatever the unreadable one described, and says
    nothing about having done so.
    """
    rows: list[dict[str, Any]] = []
    violations: list[str] = []
    sources = [(tasks_dir, "open")]
    if history_dir is not None:
        sources.append((history_dir, "merged"))
    for directory, default_status in sources:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.md")):
            if path.name.startswith("_"):
                continue  # `_migrated-history.md` is prose, not a task
            row = _row(path, default_status=default_status)
            if row is None:
                violations.append(f"{path.name} has no `id` in its front matter")
                continue
            rows.append(row)
    return rows, violations
