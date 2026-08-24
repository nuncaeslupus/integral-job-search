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
import os
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


class UnsafePackage(Exception):
    """A package that must not be copied into a public repository."""


def _refuse_symlinks(package: Path) -> None:
    """A published package is plain files, and this is where that is enforced.

    Connector packages are **contributed by strangers** — that is the whole
    premise of the exchange — and this function copies them into a public
    repository. `Path.is_file()` follows a symlink and `shutil.copytree`
    copies what it points at, so `fixture/list.html -> ~/.ssh/id_rsa` would
    have been listed as a file, published under that name, and served from
    raw.githubusercontent.com. Nothing else in the pipeline catches it: the
    contract checker validates *names*, and a symlink can wear a permitted one.

    Rejected rather than dereferenced or preserved. A connector has no reason
    to contain one, so there is no legitimate case to keep working.

    `os.walk`, not `rglob`, because a symlinked directory pointing at an
    ancestor is a loop: `os.walk` yields each directory's entries *before*
    descending, so the loop is refused at the level above it and the scan
    terminates on a hostile package as surely as on an honest one. That
    ordering is what makes it safe — `followlinks=False` is os.walk's default
    and is passed for the reader, not for the guarantee. Stripping it changes
    no test, which is the honest description of it.
    """
    if package.is_symlink():
        raise UnsafePackage(f"{package.name} is a symlink")
    for root, dirs, files in os.walk(package, followlinks=False):
        for name in (*dirs, *files):
            path = Path(root, name)
            if path.is_symlink():
                raise UnsafePackage(f"{path.relative_to(package.parent)} is a symlink")


def _entry(package: Path) -> dict[str, Any] | None:
    _refuse_symlinks(package)
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
    try:
        entries = publish(args.library, args.out)
    except UnsafePackage as exc:
        raise SystemExit(f"publish: refusing to publish — {exc}") from exc
    for entry in entries:
        print(f"{entry['package']:<20} {entry['site']:<20} {len(entry['files'])} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
