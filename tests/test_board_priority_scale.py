"""`priority` means size, and the board uses one scale.

`query_status.py` already *warns* when a board mixes the size scale with an
ordering scale — but a warning is not a gate. T25 and T26 carried 70 and 60 for
weeks, outranking every sized task unconditionally, while that warning printed
every session and nothing stopped. This is the assertion the warning could not
make.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TASKS = _REPO_ROOT / "arsenal" / "tasks"
_PRIORITY_RE = re.compile(r"^priority:\s*(-?\d+)\s*$", re.MULTILINE)


def _size_priorities() -> frozenset[int]:
    """The scale the arsenal itself defines, read from it rather than copied."""
    path = _REPO_ROOT / "claude-arsenal" / "scripts" / "query_status.py"
    spec = importlib.util.spec_from_file_location("arsenal_query_status", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return frozenset(module.SIZE_PRIORITIES)


def test_every_live_task_carries_a_size_on_the_arsenal_scale() -> None:
    allowed = _size_priorities()
    # `_history/` is archived and `_migrated-history.md` is not a task.
    paths = [p for p in sorted(_TASKS.glob("*.md")) if not p.name.startswith("_")]
    assert paths, f"no task files under {_TASKS} — the scan looked in the wrong place"

    off_scale: dict[str, int] = {}
    for path in paths:
        found = _PRIORITY_RE.search(path.read_text(encoding="utf-8"))
        # A file whose priority the scan cannot read is a hole in the scan, not
        # a task that passes: the thing deciding the scope is inside the check.
        assert found is not None, f"{path.name} declares no readable priority"
        value = int(found.group(1))
        if value not in allowed:
            off_scale[path.name] = value

    assert not off_scale, (
        f"priority encodes size only — S=10, M=5, L=1, allowed {sorted(allowed, reverse=True)}. "
        f"{off_scale} encode ordering instead, and every value above 10 outranks every sized "
        "task regardless of intent. Ordering belongs in `deps`."
    )
