"""T56's second-reader fixtures — one committed case per finding of the cue audit.

`extraction_macro_f1` cannot adjudicate a cue. It is binary over "the advert
asserts this dimension" (`extraction._dimension_f1`), so it sees *whether* a cue
fired and never *which rung it chose*; and eight of the eleven scored dimensions
carry no class-0 evaluation label, which `extraction.measure` records as
`dimensions_with_no_negative_class`. On those, over-firing cannot lower the
score at all. A cue that reads `Fully remote` as hybrid, or a driving licence as
a work trip, is invisible to it — 0.774 was consistent with every one of the
nineteen findings the independent read of T56's diff reported.

So the findings are held here instead, as inputs with the verdict the dimension's
**own text** requires. Each case cites the sentence it was decided from — a
`definition:` or a rung's `tell:`, quoted from `dimensions/*.yaml` — and never
what the extractor returns: deciding correctness by execution is the circularity
the second-reader rule exists to break (`CLAUDE.md`, "Fixtures for a
correctness-critical gate are written by a second session").

`expected=None` is a verdict, not a gap. It means **no cue may settle this
advert**: the wording states nothing any rung describes, so `cue_findings`
returning `None` is the honest answer and stage 3 asks the model. Its own
docstring is the authority — "no cue matched means *the model must be asked*, and
a zero would mean the advert says this dimension is absent, a claim no regex is
entitled to make".

`direction` records what a regression would cost. `fail-open` is a cue claiming
something the advert does not say; on a `hard` dimension that is a dealbreaker
fired on a candidate who should have passed. `fail-closed` is a reading the
advert supports and the cue misses, which costs a place in the ranking. Twelve of
the nineteen findings were fail-open and one fail-closed, and the audit weights
them in that order.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from integral.dimensions import DEFAULT_DIMENSIONS_DIR, Dimension, Language, load_dimensions
from integral.extraction import NormalisedAd, cue_findings

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T56.json"

Direction = Literal["fail-open", "fail-closed", "correct"]


@dataclass(frozen=True)
class AuditCase:
    """One advert fragment, the value the dimension's own text requires, and why."""

    dimension: str
    language: Language
    text: str
    expected: float | None
    cites: str
    direction: Direction


# A floor, never the count of the day (T100). The number of cases may only go up:
# an audit that accepted a finding and then lost its fixture is an audit that
# reports success over work no longer being done. Raise this when cases are added;
# never lower it to make a deletion pass.
MINIMUM_CASES = 54

# The floor on cases whose regression direction is fail-open. Recorded separately
# because it is the half that matters: a fail-closed bug costs a fetch, a
# fail-open bug means a `hard` dealbreaker said yes to wording that never said it.
MINIMUM_FAIL_OPEN_CASES = 34


CASES: tuple[AuditCase, ...] = (
    # ---------------------------------------------------------------- finding 1
    # remote_arrangement 0.5 was a strict superset of 1.0 in all three languages.
    AuditCase(
        "remote_arrangement", "en", "Fully remote — anywhere in the EU.", 1.0,
        "1.0 tell: 'the whole role is worked away from any company site'",
        "fail-open",
    ),
    AuditCase(
        "remote_arrangement", "es", "Teletrabajo total desde cualquier lugar.", 1.0,
        "1.0 tell: 'the whole role is worked away from any company site'",
        "fail-open",
    ),
    AuditCase(
        # Returned 0.75 before the fix — the 1.0 and 0.5 cues matched the
        # *identical* span, which `cue_findings` containment does not drop
        # (it drops a match inside a strictly longer one). 0.75 is not a rung.
        "remote_arrangement", "ca", "100% teletreball des de casa.", 1.0,
        "1.0 label: '100% teletreball'; the 0.5 tell asks for 'a split week'",
        "fail-open",
    ),
    AuditCase(
        # Returned 0.75 before the fix: two spans, in two sentences, neither
        # containing the other.
        "remote_arrangement", "en", "Fully remote position. We are a remote company.", 1.0,
        "1.0 tell: 'the whole role is worked away from any company site'",
        "fail-open",
    ),
    AuditCase(
        "remote_arrangement", "es", "Se ofrece teletrabajo.", None,
        "0.5 tell: 'a split week — a stated number of days at home or in the office'",
        "fail-open",
    ),
    AuditCase(
        "remote_arrangement", "en", "This is not a remote role.", None,
        "0.5 tell: 'a split week — a stated number of days at home or in the office'",
        "fail-open",
    ),
    AuditCase(
        "remote_arrangement", "es", "2 días de teletrabajo a la semana.", 0.5,
        "0.5 tell: 'a split week — a stated number of days at home or in the office'",
        "fail-closed",
    ),
    AuditCase(
        "remote_arrangement", "ca", "Més del 50% de la jornada de teletreball.", 0.5,
        "0.5 tell: 'a split week — a stated number of days at home or in the office'",
        "fail-closed",
    ),
    AuditCase(
        # tecnoempleo strips the per-cent sign. Six evaluation-split adverts say
        # it this way and were being read one rung down.
        "remote_arrangement", "es", "Modalidad 100 remoto, estable y a largo plazo.", 1.0,
        "1.0 tell: 'the whole role is worked away from any company site'",
        "fail-closed",
    ),
    AuditCase(
        "remote_arrangement", "es", "Modalidad de trabajo: presencial.", 0.0,
        "0.0 tell: 'the ad names an office, a work city, or full presence'",
        "correct",
    ),
    # ---------------------------------------------------------------- finding 2
    # A driving licence is `commute_burden`'s by that dimension's own definition.
    AuditCase(
        "travel_requirement", "es", "Imprescindible carnet de conducir y vehículo propio.", None,
        "commute_burden.definition: 'holding a driving licence, or providing your own "
        "vehicle. A condition on the person, distinct from `travel_requirement`, which "
        "is travel done as part of the job'",
        "fail-open",
    ),
    AuditCase(
        "commute_burden", "es", "Imprescindible carnet de conducir y vehículo propio.", 0.9,
        "commute_burden 0.9 tell: 'a driving licence or your own vehicle is stated as required'",
        "fail-closed",
    ),
    AuditCase(
        "travel_requirement", "es", "Se ofrece plus de desplazamiento.", None,
        "0.4 tell: 'client visits, or periodic presence at an office, framed as now and then'",
        "fail-open",
    ),
    # ---------------------------------------------------------------- finding 3
    # `movilidad nacional` is offered as a benefit; PR #320's audit of
    # `concept_map.yaml` left "internal mobility across countries" unmapped.
    AuditCase(
        "travel_requirement", "es",
        "Beneficios: movilidad nacional e internacional dentro del grupo.", None,
        "0.9 tell: 'travel is part of the job, or the role requires moving to a stated place'",
        "fail-open",
    ),
    AuditCase(
        "travel_requirement", "ca",
        "Beneficis: mobilitat nacional i internacional dins del grup.", None,
        "0.9 tell: 'travel is part of the job, or the role requires moving to a stated place'",
        "fail-open",
    ),
    AuditCase(
        "travel_requirement", "es",
        "Disponibilidad para realizar 3-4 viajes al año, de 2-3 días máximo.", 0.4,
        "0.4 tell: 'client visits, or periodic presence at an office, framed as now and then'",
        "fail-closed",
    ),
    AuditCase(
        "travel_requirement", "en", "Occasional business trips.", 0.4,
        "0.4 tell: 'client visits, or periodic presence at an office, framed as now and then'",
        "fail-open",
    ),
    AuditCase(
        # The mild finding asking for 0.4 here is rejected: the 0.8/0.9 rung's own
        # tell opens with "travel is part of the job", which this states.
        "travel_requirement", "en", "Frequent business trips to client offices.", 0.8,
        "0.9 tell: 'travel is part of the job, or the role requires moving to a stated place'",
        "correct",
    ),
    AuditCase(
        "travel_requirement", "es", "No se requieren desplazamientos.", 0.0,
        "0.0 tell: 'the ad asks for no travel and names no relocation'",
        "fail-open",
    ),
    # ------------------------------------------------------------- findings 4/12
    # The deny cue was a narrow literal while the positives were widened, and
    # `_is_negated` only looks *backwards* — so a negator that follows the cue is
    # reachable by nothing but the deny cue, which must span the positive match.
    AuditCase(
        "english_demand", "en", "English skills not required.", 0.0,
        "0.0 tell: 'the ad says English is not needed, or asks for none at all'",
        "fail-open",
    ),
    AuditCase(
        "english_demand", "en", "No advanced English is required for this role.", 0.0,
        "0.0 tell: 'the ad says English is not needed, or asks for none at all'",
        "fail-open",
    ),
    AuditCase(
        "english_demand", "es", "No se requiere inglés.", 0.0,
        "0.0 tell: 'the ad says English is not needed, or asks for none at all'",
        "fail-open",
    ),
    AuditCase(
        "english_demand", "en", "Fluent English is required.", 1.0,
        "1.0 tell: 'C1/fluent/native, or English named as the working language'",
        "fail-closed",
    ),
    # ---------------------------------------------------------------- finding 5
    # *Básico* is A1/A2 — below the B1 floor the 0.6 tell states — and the 0.0
    # tell says "asks for none at all", which an ad asking for basic English does
    # not. Neither rung fits, so no cue may claim one.
    AuditCase(
        "english_demand", "es", "Inglés nivel básico.", None,
        "0.6 tell: 'B1/B2, or enough to read documentation and follow written threads'",
        "fail-open",
    ),
    AuditCase(
        "english_demand", "ca", "Anglès bàsic.", None,
        "0.6 tell: 'B1/B2, or enough to read documentation and follow written threads'",
        "fail-open",
    ),
    AuditCase(
        # The `suficiente` half of the finding is rejected: the 0.6 tell says in
        # its own words "enough to read documentation".
        "english_demand", "es", "Nivel de inglés suficiente para leer documentación.", 0.6,
        "0.6 tell: 'B1/B2, or enough to read documentation and follow written threads'",
        "correct",
    ),
    # ---------------------------------------------------------------- finding 6
    # The 0.8 tell asks for the word *in the title*. `cue_findings` reads
    # `ad.text`, never `ad.title`, so a body-text cue cannot tell the offered role
    # from a duty line or from somebody else's job.
    AuditCase(
        "seniority_expectation", "es", "Será responsable de mantener la documentación.", None,
        "0.8 tell: 'senior/lead/principal in the title, or a stated floor of many years'",
        "fail-open",
    ),
    AuditCase(
        "seniority_expectation", "es", "Reportarás al jefe de equipo.", None,
        "0.8 tell: 'senior/lead/principal in the title, or a stated floor of many years'",
        "fail-open",
    ),
    AuditCase(
        "seniority_expectation", "es", "Buscamos un/a Jefe de Obra para la zona norte.", 0.8,
        "0.8 tell: 'senior/lead/principal in the title, or a stated floor of many years'",
        "fail-closed",
    ),
    AuditCase(
        "seniority_expectation", "en", "Experience with lead generation campaigns.", None,
        "0.8 tell: 'senior/lead/principal in the title, or a stated floor of many years'",
        "fail-open",
    ),
    AuditCase(
        "seniority_expectation", "en", "Lead Data Engineer, Barcelona.", 0.8,
        "0.8 tell: 'senior/lead/principal in the title, or a stated floor of many years'",
        "fail-closed",
    ),
    # ---------------------------------------------------------------- finding 7
    # The junior and mid rungs overlapped and averaged to 0.35, which is not a
    # rung; and *valorará* (desirable) was folded into the same alternation as
    # *requiere* (required), erasing the distinction the two rungs exist to draw.
    AuditCase(
        "seniority_expectation", "es", "Sin experiencia previa en el sector.", 0.2,
        "0.2 tell: 'no experience required, or an explicit junior/graduate/trainee opening'",
        "fail-open",
    ),
    AuditCase(
        "seniority_expectation", "es", "Se valorará experiencia en Python.", None,
        "0.5 tell: 'a few years asked for, or a plain practitioner title with no seniority word'",
        "fail-open",
    ),
    AuditCase(
        "seniority_expectation", "es", "Experiencia mínima de 2 años en el puesto.", 0.5,
        "0.5 tell: 'a few years asked for, or a plain practitioner title with no seniority word'",
        "fail-closed",
    ),
    AuditCase(
        "seniority_expectation", "ca", "Sense experiència prèvia.", 0.2,
        "0.2 tell: 'no experience required, or an explicit junior/graduate/trainee opening'",
        "correct",
    ),
    # ---------------------------------------------------------------- finding 8
    AuditCase(
        "compensation_transparency", "es", "Se ofrecen 12 o 14 pagas.", None,
        "definition: 'a stated band, a figure, or nothing but competitive. A property of "
        "the ad's wording, not of the amount'; 0.9 tell: 'an actual amount or range'",
        "fail-open",
    ),
    AuditCase(
        "compensation_transparency", "ca", "Salari en 12 pagues.", None,
        "0.9 tell: 'an actual amount or range the reader can act on'",
        "fail-open",
    ),
    # ---------------------------------------------------------------- finding 9
    # Any euro amount anywhere scored 0.9. The English band cue was already
    # anchored as a *band*; the Spanish figure branches now are too.
    AuditCase(
        "compensation_transparency", "es",
        "Ayuda de 1.000 € para material de teletrabajo.", None,
        "0.9 tell: 'an actual amount or range the reader can act on' — of what the role pays",
        "fail-open",
    ),
    AuditCase(
        "compensation_transparency", "es", "Seguro de vida de 30.000 euros.", None,
        "0.9 tell: 'an actual amount or range the reader can act on' — of what the role pays",
        "fail-open",
    ),
    AuditCase(
        "compensation_transparency", "es", "Salario 35.000 € brutos anuales.", 0.9,
        "0.9 tell: 'an actual amount or range the reader can act on'",
        "fail-closed",
    ),
    AuditCase(
        "compensation_transparency", "es", "Banda salarial de 30.000 a 40.000 €.", 0.9,
        "0.9 tell: 'an actual amount or range the reader can act on'",
        "fail-closed",
    ),
    AuditCase(
        # The mild finding asking for more than 0.2 here is rejected: the
        # definition's second sentence settles it — this is a property of the
        # ad's wording, and the wording carries a word where a number should be.
        "compensation_transparency", "es", "Salario según convenio.", 0.2,
        "0.2 tell: \"'competitive salary', 'salary according to experience' — a word "
        "where a number should be\"",
        "correct",
    ),
    # --------------------------------------------------------------- finding 10
    # Generic joining and having-customers language scored -0.5. Every employer
    # has clients; being placed *with* them is the rung. Corroboration cannot see
    # two agreeing matches that are both wrong.
    AuditCase(
        "product_vs_services", "es",
        "Buscamos una persona para incorporarse a un equipo en crecimiento. Proyecto estable.",
        None,
        "-0.7 tell: 'you are placed with the employer's clients, or billed into their projects'",
        "fail-open",
    ),
    AuditCase(
        "product_vs_services", "es",
        "Nuestros clientes confían en nosotros. Proyecto estable y a largo plazo.", None,
        "-0.7 tell: 'you are placed with the employer's clients, or billed into their projects'",
        "fail-open",
    ),
    AuditCase(
        "product_vs_services", "en",
        "We are a product company. Hiring a Solutions Consultant. Our consultants love it.",
        None,
        "-0.7 tell: 'you are placed with the employer's clients, or billed into their projects'",
        "fail-open",
    ),
    AuditCase(
        "product_vs_services", "en",
        "Experience integrating SaaS platforms for our clients is a plus.", None,
        "0.7 tell: 'the thing you build is the thing the employer sells'",
        "fail-open",
    ),
    AuditCase(
        "product_vs_services", "es",
        "Somos partner estratégico de Microsoft y partner tecnológico de SAP.", None,
        "-0.7 tell: 'you are placed with the employer's clients, or billed into their projects'",
        "fail-open",
    ),
    AuditCase(
        "product_vs_services", "es",
        "Buscamos los mejores profesionales para nuestros clientes y ofrecemos a nuestros "
        "candidatos los mejores proyectos.", -0.5,
        "-0.7 tell: 'you are placed with the employer's clients, or billed into their projects'",
        "fail-closed",
    ),
    # --------------------------------------------------------------- finding 11
    AuditCase(
        "learning_support", "es", "Plan de carrera dentro de la compañía.", None,
        "learning_support.definition: 'What the employer puts behind learning'; "
        "career_progression.definition: 'a named path upward — levels, a career plan'",
        "fail-open",
    ),
    AuditCase(
        "learning_support", "en", "Career path and promotion criteria are defined.", None,
        "learning_support.definition: 'What the employer puts behind learning'; "
        "career_progression 0.8 tell: 'levels, a career plan, or stated promotion criteria'",
        "fail-open",
    ),
    AuditCase(
        "career_progression", "es", "Plan de carrera dentro de la compañía.", 0.8,
        "career_progression 0.8 tell: 'levels, a career plan, or stated promotion criteria'",
        "fail-closed",
    ),
    AuditCase(
        "learning_support", "es", "Acceso continuo a formación técnica.", 0.7,
        "definition: 'What the employer puts behind learning: paid training, certification "
        "budgets, conference or language classes'",
        "fail-closed",
    ),
    # ------------------------------------------------------------------- milds
    AuditCase(
        # "To be agreed with the employer" is nothing stated — which is exactly
        # how `compensation_transparency` reads the identical idiom.
        "schedule_flexibility", "es", "Horario a convenir.", None,
        "0.7 tell: 'asynchronous work, compressed weeks, or hours the person genuinely sets'",
        "fail-open",
    ),
    AuditCase(
        # Rejected. Since the 2021 reform a *fijo discontinuo* is legally
        # indefinido, which argues for 0.9 — but the 0.3 tell names "a season" in
        # its own words, and what this dimension measures is "how durable the
        # engagement is", which a contract that stops every year is not. The
        # error direction is fail-closed either way, and that is the cheaper one.
        "contract_stability", "es", "Contrato fijo discontinuo.", 0.3,
        "0.3 tell: 'a contract with a stated end — a project, a cover, a season'",
        "correct",
    ),
)


def _dimension(dimensions: list[Dimension], dimension_id: str) -> Dimension:
    for dimension in dimensions:
        if dimension.id == dimension_id:
            return dimension
    raise KeyError(f"no dimension {dimension_id!r} in the committed model")


def resolve(case: AuditCase, dimensions: list[Dimension]) -> float | None:
    """What the rules stage actually returns for `case`, or `None` if nothing settles it."""
    ad = NormalisedAd(offer_id="cue-audit", language=case.language, text=case.text)
    score = cue_findings(ad, _dimension(dimensions, case.dimension))
    return None if score is None else round(score.value, 4)


def audit(
    cases: tuple[AuditCase, ...] = CASES,
    dimensions_dir: Path = DEFAULT_DIMENSIONS_DIR,
) -> dict[str, Any]:
    """Every case, run against the committed dimension model.

    A failure names the case, what its citation requires, and what the cue set
    returns — in that order, because the first two are the finding and the third
    is only the symptom.
    """
    dimensions = load_dimensions(dimensions_dir)
    failures: list[str] = []
    for case in cases:
        got = resolve(case, dimensions)
        if got != case.expected:
            failures.append(
                f"{case.dimension}[{case.language}] {case.text!r}: "
                f"{case.cites} requires {case.expected!r}, cue set returns {got!r} "
                f"({case.direction})"
            )
    fail_open = [case for case in cases if case.direction == "fail-open"]
    return {
        "cue_audit_cases": len(cases),
        "cue_audit_cases_at_least": MINIMUM_CASES,
        "cue_audit_fail_open_cases": len(fail_open),
        "cue_audit_fail_open_cases_at_least": MINIMUM_FAIL_OPEN_CASES,
        "cue_audit_failures": len(failures),
        "cue_audit_failing_cases": failures,
        "cue_audit_dimensions": sorted({case.dimension for case in cases}),
    }


def write_evidence(evidence_path: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    audited = audit()
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        json.dumps(audited, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return audited


def _main(argv: list[str]) -> int:
    """Write T56's cue-audit evidence. Exit 1 on any failing case."""
    args = [arg for arg in argv[1:] if not arg.startswith("--")]
    audited = write_evidence(Path(args[0]) if args else DEFAULT_EVIDENCE_PATH)
    for failure in audited["cue_audit_failing_cases"]:
        print(f"✗ {failure}", file=sys.stderr)
    print(json.dumps(audited, ensure_ascii=False))
    return 1 if audited["cue_audit_failures"] else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
