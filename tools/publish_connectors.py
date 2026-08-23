"""Assemble the sources repository's published tree from `connectors/`.

The exchange installs a connector by reading `manifest.json` and then fetching
exactly the file names it lists (`connector_exchange.install`). So a hand-typed
`files` list is a silent failure waiting: a file left out is omitted from the
installed copy, and the fixture check then fails on a package that is fine
here. Deriving the list from the package on disk is why this is a script and
not a document.

Writes `manifest.json` and `connectors/` into `--out` and touches nothing else,
so it can be run into a clone of the sources repository as a plain refresh.

    uv run python tools/publish_connectors.py --out /path/to/integral-connectors
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIBRARY = _REPO_ROOT / "connectors"

# `.test` is reserved by RFC 2606 and `examplejobs.test` uses it deliberately:
# that package is a worked example, not a board anyone can search. Publishing it
# would offer a candidate a connector for a site that does not exist, so the
# filter is the site's own domain rather than a list of names to keep in step.
FICTITIOUS_TLD = ".test"


def _entry(package: Path) -> dict[str, Any] | None:
    meta = yaml.safe_load((package / "meta.yaml").read_text(encoding="utf-8"))
    site = str(meta["site"])
    if site.endswith(FICTITIOUS_TLD):
        return None
    return {
        "package": package.name,
        "site": site,
        "country": str(meta["country"]),
        "language": str(meta["language"]),
        "contributor": str(meta["maintainer"]),
        "last_verified": str(meta["last_verified"]),
        "files": sorted(
            path.relative_to(package).as_posix() for path in package.rglob("*") if path.is_file()
        ),
    }


def publish(library: Path, out: Path) -> list[dict[str, Any]]:
    entries = [e for e in (_entry(p) for p in sorted(library.iterdir()) if p.is_dir()) if e]
    target = out / "connectors"
    if target.exists():
        shutil.rmtree(target)
    for entry in entries:
        shutil.copytree(library / entry["package"], target / entry["package"])
    (out / "manifest.json").write_text(
        json.dumps({"manifest_version": 1, "connectors": entries}, indent=2) + "\n",
        encoding="utf-8",
    )
    return entries


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="the sources repository clone")
    parser.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
    args = parser.parse_args()
    for entry in publish(args.library, args.out):
        print(f"{entry['package']:<20} {entry['site']:<20} {len(entry['files'])} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
