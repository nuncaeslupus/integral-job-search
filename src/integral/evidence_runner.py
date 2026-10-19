"""Run every evidence module concurrently (`make evidence`).

The module list is derived, never listed: any `src/integral/*.py` with a
`__main__` that mentions evidence is run, exactly as the Makefile's shell
pipeline selected them before this driver replaced its serial loop.

Exit 3 from a module is "unmeasured": a verdict, not a failure, because the
record is still written. Any other non-zero is a failure; every failure is
reported, not just the first. Status lines print in sorted module order so the
output does not depend on which process finished first.

Concurrency is safe because the modules do not depend on each other's output.
The one file two modules write is `status/evidence/T203.json`
(`sourcing_exclusions` runs `exclusion_live_round` as a subprocess, and the
latter writes it too); both write identical bytes, and nothing reads it during
the run. Jobs default to `os.cpu_count()`; `EVIDENCE_JOBS` overrides.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_SRC = Path(__file__).resolve().parent
_MARKER = re.compile(r'status/evidence|"evidence"|EVIDENCE')

UNMEASURED = 3
# This driver mentions evidence and has a `__main__`, so the marker would find it
# and it would run itself without end.
SELF = Path(__file__).stem


def discover(src: Path = _SRC) -> list[str]:
    """Modules with a `__main__` that mention evidence, sorted by name."""
    found = []
    for path in sorted(src.glob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.stem != SELF and "__main__" in text and _MARKER.search(text):
            found.append(path.stem)
    return found


def status_line(returncode: int) -> str:
    if returncode == 0:
        return "ok"
    if returncode == UNMEASURED:
        return "unmeasured (recorded)"
    return "GATE FAILED"


def jobs() -> int:
    raw = os.environ.get("EVIDENCE_JOBS", "")
    try:
        n = int(raw)
    except ValueError:
        n = 0
    return n if n > 0 else (os.cpu_count() or 1)


def _run(module: str) -> tuple[str, int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", f"integral.{module}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    return module, proc.returncode, proc.stderr


def run_all(modules: list[str], n_jobs: int) -> list[tuple[str, int, str]]:
    with ThreadPoolExecutor(max_workers=max(1, n_jobs)) as pool:
        results = list(pool.map(_run, modules))
    return sorted(results, key=lambda r: r[0])


def main() -> int:
    results = run_all(discover(), jobs())
    failed = 0
    for module, code, err in results:
        print(f"  {module:<18} {status_line(code)}")
        if status_line(code) == "GATE FAILED":
            failed += 1
            if err.strip():
                print(err.rstrip(), file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
