"""T197 — the `connector-new` skill must not carry a census of what a package moves.

Step 6 used to say that exactly two committed counts move when a package lands and
that "if a third moves, that is a finding". T194 moved seven and all seven were
truthful: four keys by +1 for the package, two by +3 (one `BoardOutcome` per phrase,
which is `Run.steered`'s own definition) and the provenance census. A census in
prose has no last element, and a stale one does worse than fail to help — it makes
a session distrust correct work and pay to refute it, or edit something until the
count matches.

Two tests hold the remedy down. One reads the skill for the *shape* of the claim
(a number, then "counts/keys move", or "a third is a finding"), not for today's
wording. The other measures the fact that made the claim wrong — it adds a real
package to a copy of the tree and counts how many committed keys move — so putting
a number back is red whatever number it is.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from integral import arsenal_source, repo_gate

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / ".claude" / "skills" / "connector-new" / "SKILL.md"

#: The count the skill used to claim. Not a threshold: the measured count must
#: differ from it, and separately no number may be claimed at all.
CLAIMED_BY_THE_OLD_SKILL = 2

_NUMBER = (
    r"(?:\d+|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"first|second|third|fourth|fifth|sixth|seventh)"
)
_MOVERS = r"(?:counts?|keys?|numbers?|figures?|measurements?|records?|values?)"
_VERBS = r"(?:move|moves|moved|change|changes|changed|shift|shifts|shifted|drift|drifts)"
_CENSUS_SHAPES = (
    # "Two committed counts move", "exactly 7 keys move", "three evidence keys change".
    re.compile(
        rf"\b{_NUMBER}\s+(?:[\w-]+\s+){{0,3}}?{_MOVERS}\s+(?:[\w-]+\s+){{0,2}}?{_VERBS}\b",
        re.IGNORECASE,
    ),
    # "if a third moves, that is a finding" / "a third key is a finding".
    re.compile(
        rf"\b{_NUMBER}\b[^.]{{0,40}}?\b(?:that|it|this)\s+is\s+a\s+finding\b"
        rf"|\b{_NUMBER}\s+(?:[\w-]+\s+){{0,2}}?is\s+a\s+finding\b",
        re.IGNORECASE,
    ),
    # "exactly N" / "only N" with a movement verb in the same sentence.
    re.compile(rf"\b(?:exactly|only|just)\s+{_NUMBER}\b[^.]*?\b{_VERBS}\b", re.IGNORECASE),
)


def census_claims(text: str) -> list[str]:
    """Sentences in `text` that state how many committed keys move."""
    flat = re.sub(r"\s+", " ", text)
    sentences = re.split(r"(?<=[.!?])\s+", flat)
    return [s for s in sentences if any(shape.search(s) for shape in _CENSUS_SHAPES)]


def test_the_skill_names_no_census_of_moved_keys() -> None:
    assert census_claims(SKILL.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(
    "claim",
    [
        "Two committed counts move when a package lands.",
        "If a third moves, that is a finding.",
        "Exactly 7 keys move for one package.",
        "three evidence keys change when a connector is added",
        "Only two counts move, and both must be checked.",
    ],
)
def test_the_census_detector_recognises_the_shape_of_the_claim(claim: str) -> None:
    assert census_claims(claim)


@pytest.mark.parametrize(
    "rule",
    [
        "A key that moves by the package's own contribution is truthful.",
        "Each connector is one package, and keys move by +1 per package.",
        "Find which keys are package-sensitive with the registry, then explain each move.",
    ],
)
def test_the_census_detector_leaves_the_rule_alone(rule: str) -> None:
    assert census_claims(rule) == []


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


def _copy_tracked_tree(destination: Path) -> None:
    for relative in arsenal_source.tracked_files(REPO):
        source = REPO / relative
        if not source.is_file():
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    _git(destination, "init", "-q")
    _git(destination, "add", "-A")
    _git(destination, "commit", "-q", "-m", "base")


def _regenerate_evidence(root: Path) -> dict[str, dict[str, object]]:
    """Run every evidence-writing module against `root`; return what they wrote.

    The module list is `repo_gate.evidence_writing_modules`, the discovery
    `make evidence` uses, so a module added tomorrow is measured too. Each runs in
    a fresh subprocess pointed at the copy's own `src/`.
    """
    env = {**os.environ, "PYTHONPATH": str(root / "src"), "PYTHONDONTWRITEBYTECODE": "1"}

    def run(module: str) -> tuple[str, int, str]:
        done = subprocess.run(
            [sys.executable, "-m", f"integral.{module}"],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        return module, done.returncode, done.stderr[-400:]

    # Each module writes its own record, so they are independent of one another.
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, repo_gate.evidence_writing_modules()))
    for module, code, stderr in results:
        # A module's own verdict (0 pass, 3 unmeasured, 1 red) is not this test's
        # subject: `plan_v2` goes red on the host's task state, not on a package. What
        # would invalidate the measurement is a module that crashed before writing.
        assert "Traceback" not in stderr, f"{module} (exit {code}): {stderr}"
    return {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((root / "status" / "evidence").glob("*.json"))
    }


def _add_a_package(root: Path) -> None:
    """One new package: a clone of an existing one, with its robots adjudication."""
    template, package = "lever_en", "zzprobe_en"
    shutil.copytree(root / "connectors" / template, root / "connectors" / package)
    manifest = root / "connectors" / package / "connector.yaml"
    declared = manifest.read_text(encoding="utf-8")
    assert "\nsite: lever\n" in declared  # the loader requires `site` to match the name
    manifest.write_text(declared.replace("\nsite: lever\n", "\nsite: zzprobe\n"), encoding="utf-8")
    ledger = root / "connectors" / "robots-adjudications.yaml"
    text = ledger.read_text(encoding="utf-8")
    at = text.index(f"    package: connectors/{template}\n")
    start = text.rindex("\n  - site:", 0, at) + 1
    end = text.find("\n  - site:", start)
    end = len(text) if end == -1 else end + 1
    block = text[start:end]
    assert block.count(template) >= 2
    clone = block.replace(template, package).replace("api.lever.co", "api.zzprobe.example")
    ledger.write_text(text[:end] + clone + text[end:], encoding="utf-8")
    _git(root, "add", "-A")


def _moved_keys(
    before: dict[str, dict[str, object]], after: dict[str, dict[str, object]]
) -> list[str]:
    moved: list[str] = []
    for name in sorted(before.keys() | after.keys()):
        old, new = before.get(name, {}), after.get(name, {})
        moved.extend(
            f"{name}:{key}"
            for key in sorted(old.keys() | new.keys())
            if old.get(key) != new.get(key)
        )
    return moved


def test_a_new_package_moves_more_keys_than_the_skill_ever_claimed() -> None:
    with tempfile.TemporaryDirectory(prefix="t197-") as scratch:
        root = Path(scratch)
        _copy_tracked_tree(root)
        # `make evidence` refuses drift, so the committed records are the baseline.
        before = {
            path.name: json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((root / "status" / "evidence").glob("*.json"))
        }
        _add_a_package(root)
        after = _regenerate_evidence(root)
    moved = _moved_keys(before, after)
    assert before, "no committed evidence was read, so nothing was measured"
    assert len(moved) > CLAIMED_BY_THE_OLD_SKILL, moved
