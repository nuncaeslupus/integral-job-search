"""Raw ad corpus: read, write, and measure it.

Stdlib only, on purpose. The collector (`tools/collect_ads.py`) needs a scraping
stack; reading and validating the committed corpus must not, or the acceptance
gate stops running anywhere the boards are unreachable.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

# ponytail: src-layout repo root. Valid for an editable install, which is the only
# way this project is installed; a wheel would need the path passed in explicitly.
DEFAULT_PATH = Path(__file__).resolve().parents[2] / "corpus" / "raw" / "ads.jsonl"
LANGUAGES = ("es", "en", "ca")

# T25: a family below this many ads teaches the dimension model nothing about how that
# family is advertised, so it does not count towards the breadth the gate asserts.
MIN_ADS_PER_FAMILY = 15
DEFAULT_FAMILY_EVIDENCE = Path("status/evidence/T25.json")


# --------------------------------------------------------------- T25: job families
#
# These live here, not in the collector, for the same reason the rest of this module
# does: `tools/collect_ads.py` needs a scraping stack, and deciding what family a title
# names is part of validating the committed corpus — it has to keep working on a machine
# with no egress, or T25's gate stops running wherever the boards are unreachable.
#
# ponytail: title regexes, not a classifier. Recall over precision within a family, as
# with the collector's ROLE_RE; but a title that matches *two* families is dropped rather
# than guessed, because a miscategorised ad teaches the wrong vocabulary for both.
FAMILY_TITLE_RE: dict[str, re.Pattern[str]] = {
    "hospitality": re.compile(
        r"cambrer|camarer|cuiner|cocioner|cocinero|xef|\bchef\b|ma[iî]tre|barista|pizzer|"
        r"rentaplats|friegaplatos|ajudant de cuina|ayudante de cocina|hostaleria|hosteler|"
        r"recepcionista d[e\u2019']? ?hotel|recepcionista de hotel|sommelier|barman|"
        r"cambrera|cap de sala|govern(anta|ant)|\bcatering\b",
        re.I,
    ),
    "healthcare": re.compile(
        r"infermer|enfermer|fisioterapeuta|gerocultor|cuidador|\bmetge\b|m[eé]dic[oa]\b|"
        r"farmac[eè]utic|podol|podòleg|higienista|terapeuta|zelador|celador|"
        r"auxiliar de cl[ií]nica|\bTCAI\b|t[eè]cnic[\w/]* en emerg|logopeda|nutricionista",
        re.I,
    ),
    "trades": re.compile(
        r"electricista|lampista|fontaner|fuster|carpinter|palet[ae]\b|alba[ñn]il|soldador|"
        r"mec[àa]nic|pintor|many[àa]|cerrajer|instal·lador|instalador|llauner|calderer|"
        r"muntador|montador|frigorista|xapista|chapista|maquinista|torner|tornero",
        re.I,
    ),
    "retail": re.compile(
        r"dependent|dependient|caixer|cajer|venedor[\w/]* de botiga|vendedor[\w/]* de tienda|"
        r"reposador|reponedor|encarregat[\w/]* de botiga|encargad[\w/]* de tienda|"
        r"personal de botiga|personal de tienda|caixa de supermercat|xarcuter|charcuter|"
        r"carnisser|carnicer|peixater|pescader|fruiter|fruter[oa]\b|"
        r"auxiliar de botiga|auxiliar de tienda",
        re.I,
    ),
    "teaching": re.compile(
        r"professor|profesor|mestre\b|maestr[oa]\b|docent|educador|monitor[\w/]*|formador|"
        r"tutor\b|auxiliar d[e\u2019']? ?educaci|auxiliar de educaci|"
        r"t[eè]cnic[\w/]* d[e\u2019']? ?educaci[oó] infantil",
        re.I,
    ),
    # No bare `recepcionista` here: it also names the hospitality front-desk role, and the
    # exactly-one-match rule below would then drop every hotel receptionist ad as ambiguous.
    "administrative": re.compile(
        r"administratiu|administrativ[oa]|comptable|contable|secretari|secretari[oa]|"
        r"auxiliar administrat|back ?office|facturaci[oó]|gestor[\w/]* administrat|"
        r"aux(iliar)? de comptabilitat|auxiliar de contabilidad|arxiver|archiver",
        re.I,
    ),
}


# Feina Activa also carries the public employment service's recruitment bulletins —
# "Borsa de treball de places de …", "Convocatòria …" — which are administrative
# announcements rather than job adverts, and near-identical to one another. T4b's Catalan
# collector already excluded them (CA_NOT_ROLE_RE); the family pass has to as well, or a
# family fills with twelve copies of one bulletin and teaches the model a form no
# candidate will ever be shown.
FAMILY_NOT_RE = re.compile(
    r"borsa de treball|bolsa de trabajo|pla[çc]a d|places d|plazas? de|\bCIDO\b|"
    r"convocat[òo]ria|convocatoria|oferta pública d|oferta publica d|"
    r"procés selectiu|proceso selectivo",
    re.I,
)


def classify_family(title: str) -> str | None:
    """The one family whose title pattern matches, or None if none or more than one do."""
    if FAMILY_NOT_RE.search(title):
        return None
    hits = [family for family, pattern in FAMILY_TITLE_RE.items() if pattern.search(title)]
    return hits[0] if len(hits) == 1 else None


def load_ads(path: Path = DEFAULT_PATH) -> list[dict[str, Any]]:
    """Read the raw corpus. An entry without a source URL or job family is refused."""
    ads: list[dict[str, Any]] = []
    if not path.exists():
        return ads
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        ad = json.loads(line)
        url = str(ad.get("source_url") or "")
        # https only: every board the collector reads serves https, and the acceptance
        # test asserts it — accepting http here would let a corpus load but fail the gate.
        if not url.startswith("https://"):
            raise ValueError(f"{path}:{lineno} ad {ad.get('id')!r} has no resolvable source_url")
        if not str(ad.get("text") or "").strip():
            raise ValueError(f"{path}:{lineno} ad {ad.get('id')!r} has no text")
        # Refused at load, exactly as `source_url` is: an ad whose family nobody declared
        # would otherwise sit in the corpus counting towards no family and blocking none.
        if not str(ad.get("job_family") or "").strip():
            raise ValueError(f"{path}:{lineno} ad {ad.get('id')!r} declares no job_family")
        ads.append(ad)
    return ads


def save_ads(ads: list[dict[str, Any]], path: Path = DEFAULT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(ad, ensure_ascii=False, sort_keys=True) for ad in sorted(ads, key=_by_id)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _by_id(ad: dict[str, Any]) -> str:
    return str(ad["id"])


def language_counts(ads: list[dict[str, Any]]) -> dict[str, int]:
    return {lang: sum(1 for ad in ads if ad["language"] == lang) for lang in LANGUAGES}


def job_family_counts(ads: list[dict[str, Any]]) -> dict[str, int]:
    """Ads per declared family, ordered by name so the evidence file is stable."""
    counts: dict[str, int] = {}
    for ad in ads:
        family = str(ad["job_family"])
        counts[family] = counts.get(family, 0) + 1
    return {family: counts[family] for family in sorted(counts)}


def write_evidence(evidence: Path, ads: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Recompute T4b's measured numbers from the committed corpus."""
    if ads is None:
        ads = load_ads()
    measured = {"raw_ad_count": len(ads), "language_counts": language_counts(ads)}
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2) + "\n", encoding="utf-8")
    return measured


def write_family_evidence(
    evidence: Path = DEFAULT_FAMILY_EVIDENCE, ads: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """T25's measured numbers.

    `corpus_job_family_count` counts only families that *reach* `MIN_ADS_PER_FAMILY`.
    Counting every distinct family instead would let six one-ad families satisfy a
    `>= 6` gate — the floor that decides whether a family is real has to be inside
    the number the gate reads, not beside it in a test that could stop running.
    """
    if ads is None:
        ads = load_ads()
    counts = job_family_counts(ads)
    qualifying = [family for family, n in counts.items() if n >= MIN_ADS_PER_FAMILY]
    measured = {
        "corpus_job_family_count": len(qualifying),
        "min_ads_per_family": MIN_ADS_PER_FAMILY,
        "job_family_counts": counts,
        "families_below_floor": {f: n for f, n in counts.items() if n < MIN_ADS_PER_FAMILY},
    }
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.corpus` → T4b's and T25's gate evidence."""
    ads = load_ads()
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else Path("status/evidence/T4b.json")
    measured = write_evidence(target, ads)
    families = write_family_evidence(DEFAULT_FAMILY_EVIDENCE, ads)
    print(json.dumps({**measured, **families}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
