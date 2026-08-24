"""The sources-repository publisher, checked against the failure it exists to prevent.

`connector_exchange.install` fetches exactly the file names `manifest.json`
lists and nothing else. A hand-typed `files` list therefore fails silently: the
omitted file is simply not installed, and the candidate sees a fixture check
fail on a package that is intact upstream. So the interesting assertion is not
that the publisher writes a manifest — it is that the tree it writes survives a
real install, offline, with the same code that would run against the live repo.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from integral.connector_exchange import directory_fetcher, install, read_manifest

REPO_ROOT = Path(__file__).resolve().parents[1]
PUBLISHER = REPO_ROOT / "tools" / "publish_connectors.py"
LIBRARY = REPO_ROOT / "connectors"


def _publish(out: Path, library: Path = LIBRARY) -> list[dict[str, Any]]:
    subprocess.run(
        [sys.executable, str(PUBLISHER), "--out", str(out), "--library", str(library)],
        check=True,
        capture_output=True,
        text=True,
    )
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    return list(manifest["connectors"])


def test_the_published_tree_installs_and_verifies_offline(tmp_path: Path) -> None:
    out = tmp_path / "sources"
    out.mkdir()
    _publish(out)
    entries = read_manifest(directory_fetcher(*_paths(out)))
    assert entries, "the publisher wrote a manifest offering nothing"
    for entry in entries:
        got = install(entry, directory_fetcher(*_paths(out)), home=tmp_path / entry.package)
        assert got.verified, f"{entry.package}: {got.violations}"


def _paths(out: Path) -> tuple[Path, Path]:
    return out / "manifest.json", out / "connectors"


def test_a_fictitious_board_is_never_published(tmp_path: Path) -> None:
    """`examplejobs.test` is a worked example, not a board anyone can search.

    Publishing it would offer a candidate a connector for a site that does not
    exist. The filter is the `.test` domain rather than a list of package names
    to keep in step, so this holds for the next example too.
    """
    out = tmp_path / "sources"
    out.mkdir()
    sites = [entry["site"] for entry in _publish(out)]
    assert sites, "the library published nothing at all"
    assert not [site for site in sites if str(site).endswith(".test")]
    assert not (out / "connectors" / "examplejobs_es").exists()


def test_the_files_list_is_derived_from_the_package_not_typed(tmp_path: Path) -> None:
    """A connector that records a second page must publish it without an edit here."""
    library = tmp_path / "library"
    shutil.copytree(LIBRARY, library)
    package = next(p for p in sorted(library.iterdir()) if p.name != "examplejobs_es")
    (package / "fixture" / "list2.html").write_text("<html></html>", encoding="utf-8")

    out = tmp_path / "sources"
    out.mkdir()
    published = _publish(out, library)
    entry = next(e for e in published if e["package"] == package.name)
    assert "fixture/list2.html" in entry["files"]


def _library_with(tmp_path: Path) -> tuple[Path, Path]:
    """A copy of the real library, plus a place to publish it to."""
    library = tmp_path / "library"
    shutil.copytree(LIBRARY, library)
    out = tmp_path / "sources"
    out.mkdir()
    return library, out


def test_a_symlinked_file_inside_a_package_is_refused(tmp_path: Path) -> None:
    """The exchange takes packages from strangers, and this copies them somewhere public.

    `Path.is_file()` follows a symlink and `shutil.copytree` copies what it
    points at, so a fixture symlinked at a private file would be published
    under a permitted name. The contract checker cannot catch it: it validates
    names, and a symlink can wear a permitted one.
    """
    library, out = _library_with(tmp_path)
    secret = tmp_path / "id_rsa"
    secret.write_text("PRIVATE KEY", encoding="utf-8")
    package = library / "trabajos_es"
    (package / "fixture" / "list.html").unlink()
    (package / "fixture" / "list.html").symlink_to(secret)

    result = subprocess.run(
        [sys.executable, str(PUBLISHER), "--out", str(out), "--library", str(library)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "symlink" in (result.stdout + result.stderr)
    assert not (out / "connectors").exists(), "a package was copied before the refusal"
    assert "PRIVATE KEY" not in _tree_text(out)


def test_a_symlinked_package_directory_is_refused(tmp_path: Path) -> None:
    library, out = _library_with(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    shutil.copytree(LIBRARY / "trabajos_es", elsewhere)
    (library / "borrowed_es").symlink_to(elsewhere, target_is_directory=True)

    result = subprocess.run(
        [sys.executable, str(PUBLISHER), "--out", str(out), "--library", str(library)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "symlink" in (result.stdout + result.stderr)


def test_a_symlink_loop_terminates_rather_than_hanging(tmp_path: Path) -> None:
    """A hostile package must fail as reliably as an honest one."""
    library, out = _library_with(tmp_path)
    package = library / "trabajos_es"
    (package / "fixture" / "up").symlink_to(package, target_is_directory=True)

    result = subprocess.run(
        [sys.executable, str(PUBLISHER), "--out", str(out), "--library", str(library)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "symlink" in (result.stdout + result.stderr)


def _tree_text(root: Path) -> str:
    return "".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in root.rglob("*")
        if path.is_file()
    )
