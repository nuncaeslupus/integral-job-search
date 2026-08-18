"""D-1: does the Catalan corpus slice's declared scope agree across the
documents that state it? (`claude-arsenal/queue/lo-bc1d.md`)

T4b asked for ≥100 raw ads, ≈60 ES / 25 EN / 15 CA, all **remote programming**
roles. `corpus/raw/ads.jsonl` holds exactly that count and mix, but the 15
Catalan ads are not a like-for-like remote-programming sample: natively-Catalan
remote-programming ads barely exist. A full keyword sweep of Feina Activa — the
one board that publishes ads written in Catalan rather than translated into it —
returns under ten, nowhere near the 15 the slice needs. The available shortcut
(teletreballa.com republishes Feina Activa ads machine-translated into Catalan)
was rejected on principle and stays rejected: those are not verbatim originals,
and the spec's risk register forbids padding the corpus with text that is not
the real ad.

The decision (D-1, option 1) is to accept this as a fact about the Catalan
job-ad market, not a collection failure, and amend the spec rather than chase a
market that is not there: the Catalan slice is **Catalan IT ads at large**
(developer, sysadmin, data, cybersecurity, TIC consulting), stated honestly as
such, with the remote dimension mixed in rather than filtered for. Shrinking the
Catalan target (D-1, option 2) was rejected too — the slice's job is Catalan
job-ad *vocabulary* for the ontology, and a Catalan sysadmin ad teaches that
vocabulary exactly as well as a Catalan remote-developer ad would.

**Why this needs a mechanical check, not three hand-edited documents.**
Amending a spec to match reality is exactly how a spec stops meaning anything,
unless the amendment is visible everywhere someone would look for it. Three
documents state the Catalan slice's scope in three different places —
`status/plan.md`'s T4b row (the build order), `corpus/raw/README.md`'s "Known
divergence" section (the corpus's own account of itself), and this module's
`TARGET_MIX` (what `tests/test_corpus_raw.py` actually pins) — and nothing
stops a future edit to any one of them from drifting back to "remote
programming" while the other two still say otherwise. That is the same failure
class D-3 (`jobsearch.spec_consistency`) exists for: a document that is
*reconciled-looking* is not the same as a document that is reconciled, and the
gap between them is invisible to anyone who only reads one of the three. This
module is the mechanical check: it reads the real `status/plan.md` and
`corpus/raw/README.md` off disk and fails loud the moment either stops
carrying the anchor phrases below, rather than trusting three humans to keep
three files in sync by hand.

The check is deliberately anchor-phrase, not full-sentence, matching. Full-
sentence matching (D-3's approach) works there because the source and target
documents both restate a short symbolic expression (`story_failure_fraction >=
0.33`) verbatim. Here one document is a dense table cell and the other is
flowing prose — forcing one verbatim sentence into both would read as an odd
transplant in whichever is not its native shape. A short, distinctive phrase
("Catalan IT ads", "remote dimension ... mixed") is what both can carry
naturally while still being an exact, mechanical `in` check rather than a
prose-similarity heuristic that could pass on a document saying something
else entirely.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PLAN = _REPO_ROOT / "status" / "plan.md"
DEFAULT_README = _REPO_ROOT / "corpus" / "raw" / "README.md"
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "D1.json"

# The language-mix target T4b actually measures. `tests/test_corpus_raw.py`
# imports this rather than restating it, so the count the mix test pins and the
# count this module checks documents against can never independently drift —
# one of the three ways D-1 found the corpus and its documentation disagreeing.
TARGET_MIX: dict[str, int] = {"es": 60, "en": 25, "ca": 15}

# Anchor phrases a reconciled document must carry. Matched case-insensitively
# and as substrings/regexes, not as whole-sentence literals — see the module
# docstring for why. `CATALAN_SCOPE_ANCHOR` is checked against both
# `status/plan.md` and `corpus/raw/README.md`; `REMOTE_MIX_ANCHOR` only against
# the README, whose prose is where the remote dimension's status ("mixed in,
# not filtered for") is actually explained — a table cell has no room to.
CATALAN_SCOPE_ANCHOR = "catalan it ads"
# `\s+`, not a literal `" "`: prose (the README) soft-wraps at whatever column
# an editor left it at, so words an anchor phrase expects adjacent can end up
# separated by a newline instead of a space. A literal-space regex matched a
# single-line synthetic test fixture and then failed on the real, wrapped
# prose — this is the fix for that, not a hypothetical. `re.DOTALL` lets the
# `.{0,40}` gap itself cross a line break too.
CATALAN_SCOPE_RE = re.compile(r"catalan\s+it\s+ads", re.IGNORECASE)
REMOTE_MIX_ANCHOR = re.compile(r"remote\s+dimension.{0,40}mixed", re.IGNORECASE | re.DOTALL)

# An anchor is only a declaration if nothing just before it reverses it. Both
# anchors above match on their content words alone, so "the slice is **not**
# Catalan IT ads" and "the remote dimension is not mixed" satisfied them while
# stating the opposite of what they exist to assert — a drift detector that
# passes on a document contradicting the thing it checks.
#
# The realistic drift is a reversion to the old wording, which the anchors
# already catch. This closes the other direction, and is deliberately a narrow
# window rather than a grammar: a negation more than a few words back usually
# belongs to another clause, and this module does no linguistics.
_NEGATION_RE = re.compile(r"\b(?:not|never|no longer|isn't|is not|aren't|are not)\b[\s\w,]{0,24}$",
                          re.IGNORECASE)


def _affirmed(text: str, match: re.Match[str] | None) -> bool:
    """Whether `match` reads as an assertion rather than its denial."""
    if match is None:
        return False
    return _NEGATION_RE.search(text[: match.start()]) is None

_T4B_ROW_RE = re.compile(r"^\|\s*T4b\s*\|.*\|\s*$", re.MULTILINE)
_KNOWN_DIVERGENCE_RE = re.compile(r"^## Known divergence.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)


def t4b_row(plan_path: Path = DEFAULT_PLAN) -> str:
    """`status/plan.md`'s T4b row, verbatim, or `""` if the row is not found."""
    if not plan_path.is_file():
        return ""
    match = _T4B_ROW_RE.search(plan_path.read_text(encoding="utf-8"))
    return match.group(0) if match else ""


def known_divergence_section(readme_path: Path = DEFAULT_README) -> str:
    """`corpus/raw/README.md`'s "Known divergence" section, heading to the next
    heading (or end of file), or `""` if the section is not found."""
    if not readme_path.is_file():
        return ""
    match = _KNOWN_DIVERGENCE_RE.search(readme_path.read_text(encoding="utf-8"))
    return match.group(0) if match else ""


def measure(
    plan_path: Path = DEFAULT_PLAN, readme_path: Path = DEFAULT_README
) -> dict[str, Any]:
    """D-1's gate reading: how many of the documents that declare the Catalan
    slice's scope disagree with it, as written to evidence.

    A missing row or section counts as a mismatch rather than being skipped —
    skipping it would let the file disappearing entirely read as "nothing to
    disagree with, therefore fine", the same vacuous-pass failure D-3 guards
    against with `MINIMUM_DECLARATIONS_FOUND`.
    """
    row = t4b_row(plan_path)
    section = known_divergence_section(readme_path)
    mismatches: list[dict[str, str]] = []

    if not row:
        mismatches.append({"document": "status/plan.md", "reason": "T4b row not found"})
    elif not _affirmed(row, CATALAN_SCOPE_RE.search(row)):
        mismatches.append(
            {
                "document": "status/plan.md",
                "reason": f"T4b row does not state the Catalan slice's scope "
                f"({CATALAN_SCOPE_ANCHOR!r} not stated, or negated)",
            }
        )

    if not section:
        mismatches.append(
            {
                "document": "corpus/raw/README.md",
                "reason": '"Known divergence" section not found',
            }
        )
    else:
        if not _affirmed(section, CATALAN_SCOPE_RE.search(section)):
            mismatches.append(
                {
                    "document": "corpus/raw/README.md",
                    "reason": f"Known divergence section does not state the Catalan "
                    f"slice's scope ({CATALAN_SCOPE_ANCHOR!r} not stated, or negated)",
                }
            )
        if not _affirmed(section, REMOTE_MIX_ANCHOR.search(section)):
            mismatches.append(
                {
                    "document": "corpus/raw/README.md",
                    "reason": "Known divergence section does not say the remote "
                    "dimension is mixed in rather than filtered for",
                }
            )

    return {
        "corpus_language_slice_mismatch": len(mismatches),
        "mismatches": mismatches,
        "target_mix": dict(TARGET_MIX),
    }


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    plan_path: Path = DEFAULT_PLAN,
    readme_path: Path = DEFAULT_README,
) -> dict[str, Any]:
    """Measure and record `status/evidence/D1.json`."""
    measured = measure(plan_path, readme_path)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m jobsearch.corpus_scope [path]` → D-1's gate evidence."""
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    print(json.dumps(measured, ensure_ascii=False))
    for mismatch in measured["mismatches"]:
        print(f"{mismatch['document']}: {mismatch['reason']}", file=sys.stderr)
    return 1 if measured["mismatches"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
