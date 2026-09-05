"""T107 — the candidate-facing strings, and whether each language actually has them.

The defect this closes: `presentation.py` shipped its labels as English string
constants with no translation seam at all, in a product whose default profile
language is `es`. A Spanish candidate read an English results page and nothing
reported it — the silent-feature shape, not a partial one, because "the Spanish
candidate got the English string" produced no error, no warning and no number.

Three separable things live here, and only the third is a judgement:

1. **Completeness** — does every language have every string? Countable.
2. **Staleness** — was each translation made from *the English that is there
   now*? Countable, because each entry records `of`: the sha256 of the source
   text it was translated from. Edit the English and every translation of it
   stops matching, so "when we change a report we update all the languages"
   stops being a promise somebody has to keep and becomes a check that fails.
3. **Quality** — is the German good German? **Not countable, and not claimed.**
   No gate here says a translation is correct. A contributed pack records who
   made it and when, and that is the whole of what can honestly be offered.

The gate is `candidate_facing_strings_without_a_translation == 0` over a real
denominator with a floor, for the same reason `naming.MINIMUM_SCANNED` exists:
a zero over an empty scan is what a check that never ran also reports.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOGUE = _REPO_ROOT / "strings" / "catalogue.json"
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T107.json"

#: Keys that are bookkeeping rather than something a candidate reads.
_METADATA_KEYS = frozenset({"note"})

#: A run that measured fewer strings than this measured nothing. The library
#: had 21 entries when this landed; the floor sits below that so adding a
#: string never trips it, and deleting most of them does.
MINIMUM_STRINGS = 15


class StringsError(Exception):
    """The catalogue could not be read, or does not say what it must."""


def digest(text: str) -> str:
    """The sha256 a translation records against the source it was made from."""
    return sha256(text.encode("utf-8")).hexdigest()


def load(path: Path = DEFAULT_CATALOGUE) -> dict[str, Any]:
    try:
        catalogue = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StringsError(f"the catalogue could not be read: {exc}") from exc
    if not isinstance(catalogue, dict):
        raise StringsError("the catalogue is not an object")
    loaded: dict[str, Any] = catalogue
    for required in ("source_language", "languages", "entries"):
        if required not in loaded:
            raise StringsError(f"the catalogue has no {required!r}")
    if loaded["source_language"] not in loaded["languages"]:
        raise StringsError("the source language is not among the declared languages")
    return loaded


def keys(catalogue: Mapping[str, Any]) -> list[str]:
    return sorted(catalogue["entries"])


def source_text(catalogue: Mapping[str, Any], key: str) -> str:
    """The English (or whatever `source_language` says) for `key`."""
    entry = catalogue["entries"].get(key)
    if entry is None:
        raise StringsError(f"no such string: {key!r}")
    source = entry.get(catalogue["source_language"])
    if not isinstance(source, str):
        raise StringsError(f"{key!r} has no source text")
    return source


def _translation(entry: Mapping[str, Any], language: str) -> str | None:
    """The raw value recorded for `language`, whichever shape it is written in.

    A bare string is a translation with no `of` — which `stale` then reports,
    rather than this function silently treating it as current.
    """
    value = entry.get(language)
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        text = value.get("text")
        return text if isinstance(text, str) else None
    return None


def _recorded_source(entry: Mapping[str, Any], language: str) -> str | None:
    value = entry.get(language)
    if isinstance(value, Mapping):
        of = value.get("of")
        return of if isinstance(of, str) else None
    return None


def text(catalogue: Mapping[str, Any], key: str, language: str) -> str:
    """What to show, in `language` — falling back to the source when there is
    nothing fresh to show instead.

    The fallback is deliberately **silent in the string** and loud in
    `fallbacks()`. Splicing "(untranslated)" into the value would corrupt the
    exact bytes the page's own checks match on, and would put an apology in the
    middle of a sentence. The caller asks `fallbacks()` once and tells the
    candidate once.
    """
    if language == catalogue["source_language"]:
        return source_text(catalogue, key)
    entry = catalogue["entries"].get(key)
    if entry is None:
        raise StringsError(f"no such string: {key!r}")
    translated = _translation(entry, language)
    if translated is None:
        return source_text(catalogue, key)
    recorded = _recorded_source(entry, language)
    if recorded is not None and recorded != digest(source_text(catalogue, key)):
        # Translated from an English that has since changed. The old wording is
        # a worse answer than the current source, because it is confidently
        # wrong rather than visibly foreign.
        return source_text(catalogue, key)
    return translated


def fallbacks(catalogue: Mapping[str, Any], language: str) -> list[str]:
    """Which keys `language` cannot serve — missing or stale, both fall back."""
    if language == catalogue["source_language"]:
        return []
    return [
        key
        for key in keys(catalogue)
        if text(catalogue, key, language) == source_text(catalogue, key)
        and _translation(catalogue["entries"][key], language) != source_text(catalogue, key)
    ]


def missing(catalogue: Mapping[str, Any]) -> list[str]:
    """`<language>:<key>` for every declared language with no text at all."""
    return [
        f"{language}:{key}"
        for language in catalogue["languages"]
        if language != catalogue["source_language"]
        for key in keys(catalogue)
        if _translation(catalogue["entries"][key], language) is None
    ]


def stale(catalogue: Mapping[str, Any]) -> list[str]:
    """`<language>:<key>` for every translation made from different English.

    A translation with no `of` at all counts as stale, not as current: an
    unrecorded provenance is exactly the state this mechanism replaces, and
    treating it as fresh would let one unstamped entry opt out of the rule.
    """
    out = []
    for language in catalogue["languages"]:
        if language == catalogue["source_language"]:
            continue
        for key in keys(catalogue):
            entry = catalogue["entries"][key]
            if _translation(entry, language) is None:
                continue  # counted by `missing`, not twice
            recorded = _recorded_source(entry, language)
            if recorded != digest(source_text(catalogue, key)):
                out.append(f"{language}:{key}")
    return out


def stamp(catalogue: dict[str, Any]) -> dict[str, Any]:
    """Record the current source digest against every translation.

    Run after translating, never to make a red gate green: stamping an entry
    nobody re-translated records that stale text was made from the new English,
    which is the one lie this file exists to prevent.
    """
    for key in keys(catalogue):
        entry = catalogue["entries"][key]
        source = digest(source_text(catalogue, key))
        for language in catalogue["languages"]:
            if language == catalogue["source_language"]:
                continue
            translated = _translation(entry, language)
            if translated is None:
                continue
            entry[language] = {"text": translated, "of": source}
    return catalogue


def measure(path: Path = DEFAULT_CATALOGUE) -> dict[str, Any]:
    """T107's gate reading."""
    try:
        catalogue = load(path)
    except StringsError as exc:
        return {
            "candidate_facing_strings_without_a_translation": -1,
            "stale_translations": -1,
            "candidate_facing_strings_evaluated": 0,
            "gate_status": "unmeasured",
            "reasons": [str(exc)],
        }
    absent = missing(catalogue)
    outdated = stale(catalogue)
    languages = [lang for lang in catalogue["languages"] if lang != catalogue["source_language"]]
    evaluated = len(keys(catalogue)) * len(languages)
    measured: dict[str, Any] = {
        "candidate_facing_strings_without_a_translation": len(absent),
        "stale_translations": len(outdated),
        "candidate_facing_strings_evaluated": evaluated,
        "strings_scanned": len(keys(catalogue)),
        "languages_served": languages,
        "source_language": catalogue["source_language"],
        "gate_status": "measured",
        "missing": absent,
        "stale": outdated,
    }
    if len(keys(catalogue)) < MINIMUM_STRINGS:
        measured["gate_status"] = "unmeasured"
        measured["reasons"] = [
            f"only {len(keys(catalogue))} string(s) scanned (floor {MINIMUM_STRINGS}) — "
            "a pass over nothing is not a pass"
        ]
    return measured


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str] | None = None) -> int:
    """`python -m integral.strings [--stamp] [path]` → T107's gate evidence."""
    args = list(sys.argv[1:] if argv is None else argv[1:])
    if "--stamp" in args:
        args.remove("--stamp")
        catalogue = load()
        DEFAULT_CATALOGUE.write_text(
            json.dumps(stamp(catalogue), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"stamped {len(keys(catalogue))} string(s)")
        return 0
    positional = [arg for arg in args if not arg.startswith("--")]
    measured = write_evidence(Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["gate_status"] == "unmeasured":
        for reason in measured.get("reasons", ()):
            print(reason, file=sys.stderr)
        return 3
    for entry in (*measured["missing"], *measured["stale"]):
        print(f"untranslated or stale: {entry}", file=sys.stderr)
    return 1 if measured["missing"] or measured["stale"] else 0


if __name__ == "__main__":
    raise SystemExit(_main())
