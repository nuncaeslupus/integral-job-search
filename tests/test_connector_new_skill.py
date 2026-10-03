"""T197 — the `connector-new` skill must not carry a census of what a package moves.

Step 6 used to say that exactly two committed counts move when a package lands and
that "if a third moves, that is a finding". T194 moved seven and all seven were
truthful: four keys by +1 for the package, two by +3 (one `BoardOutcome` per phrase,
which is `Run.steered`'s own definition) and the provenance census. A census in
prose has no last element, and a stale one does worse than fail to help — it makes
a session distrust correct work and pay to refute it, or edit something until the
count matches.

Two tests hold the remedy down. One reads the skill for the *shape* of the claim
(any English number, digit or vague quantifier next to a key/count noun, or a
"finding" fenced by else/other/third/more than), not for today's wording. The other
measures the fact that made the claim wrong — it adds a real
package to a copy of the tree and counts how many committed keys move — so putting
a number back is red; a census reworded to avoid every number and quantifier the
detector knows is not, which is why the detector is a closed rule and not a list of
phrasings.
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

#: The host the added package fetches from, written into its manifest, its meta and
#: its robots row alike, so the row names the host the package actually reads (T144).
HOST = "zzprobe.example"


def _words(text: str) -> list[str]:
    return re.split(r"\s+", text.strip())


_UNITS = _words(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen"
)
_TENS = ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_ORDINALS = _words(
    "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth "
    "thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth "
    "twentieth thirtieth"
)
_LARGE = ["hundred", "thousand", "million", "dozen"]
_QUANTIFIERS = ["both", "pair", "couple", "several", "few"]
_COMPOUND = rf"(?:{'|'.join(_TENS)})(?:[- ](?:{'|'.join(_UNITS[1:10])}))?"
#: Every English cardinal and ordinal, any digit run, and the vague quantifiers.
#: A closed rule: a number is a number whether or not anyone thought to list it.
#: A digit run is not a number when it is the amount of a move (`+1`, `-3`) or part
#: of an identifier (`T72`), which the lookbehind and `\b` exclude.
_WORDS = "|".join([*_UNITS, *_ORDINALS, *_LARGE, *_QUANTIFIERS])
_NUMBER = rf"(?:(?<![+\-\w])\d+\b|\b(?:{_COMPOUND}|{_WORDS})\b)"
_THING = r"(?:keys?|counts?|measurements?|figures?)"
#: Words that may sit between the number and the thing without breaking the link
#: ("two committed evidence counts"), except the ones that start a new noun phrase.
_BREAKS = {"and", "or", "per", "by", "each", "package", "packages", "connector", "connectors"}
_NUMBER_THEN_THING = re.compile(
    rf"{_NUMBER}(?P<gap>(?:\s+[\w`-]+){{0,2}}?)\s+(?:of\s+)?{_THING}\b", re.IGNORECASE
)
#: "Else", "other", "third", "beyond", "besides", "more than" next to "finding": the
#: shape of "if anything else moves, that is a finding", which implies a closed set
#: without ever writing a number.
_FINDING_WITH_A_BOUNDARY = re.compile(
    r"(?=.*\bfindings?\b)(?=.*\b(?:else|other|others|third|beyond|besides|more\s+than)\b)",
    re.IGNORECASE,
)


def _numbered_thing(sentence: str) -> bool:
    for found in _NUMBER_THEN_THING.finditer(sentence):
        words = re.findall(r"[\w`-]+", found.group("gap").lower())
        if not _BREAKS.intersection(words):
            return True
    return False


def census_claims(text: str) -> list[str]:
    """Sentences that put a number on how many keys move, or fence the set closed."""
    flat = re.sub(r"\s+", " ", text)
    sentences = re.split(r"(?<=[.!?;])\s+", flat)
    return [s for s in sentences if _numbered_thing(s) or _FINDING_WITH_A_BOUNDARY.search(s)]


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
        "Sixteen keys move when a package lands.",
        "Both committed counts move; if anything else moves, that is a finding.",
        "Only `X` and `Y` move; any other key that moves is a finding.",
        "The package moves 7 keys.",
        "Expect a couple of counts to change.",
        "More than two keys are findings.",
        "A third moving key means something else is package-sensitive.",
        "Twenty-one keys move.",
    ],
)
def test_the_census_detector_recognises_the_shape_of_the_claim(claim: str) -> None:
    assert census_claims(claim)


@pytest.mark.parametrize(
    "rule",
    [
        "A key that moves by the package's own contribution is truthful.",
        "Each connector is one package, and keys move by +1 per package.",
        "A per-phrase outcome moves by +N for N phrases.",
        "A finding is a move you cannot derive from the package.",
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
    with ThreadPoolExecutor(max_workers=8) as pool:
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
    manifest.write_text(
        declared.replace("\nsite: lever\n", "\nsite: zzprobe\n").replace("lever.co", HOST),
        encoding="utf-8",
    )
    meta = root / "connectors" / package / "meta.yaml"
    meta.write_text(meta.read_text(encoding="utf-8").replace("lever.co", HOST), encoding="utf-8")
    ledger = root / "connectors" / "robots-adjudications.yaml"
    text = ledger.read_text(encoding="utf-8")
    at = text.index(f"    package: connectors/{template}\n")
    start = text.rindex("\n  - site:", 0, at) + 1
    end = text.find("\n  - site:", start)
    end = len(text) if end == -1 else end + 1
    block = text[start:end]
    assert block.count(template) >= 2
    clone = block.replace(template, package).replace("lever.co", HOST)
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
        before = _regenerate_evidence(root)
        _add_a_package(root)
        after = _regenerate_evidence(root)
    moved = _moved_keys(before, after)
    assert before, "no committed evidence was read, so nothing was measured"
    assert len(moved) > CLAIMED_BY_THE_OLD_SKILL, moved
