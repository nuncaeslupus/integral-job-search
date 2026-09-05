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

**A second independent read of the diff that answered those nineteen found
nineteen more**, and every one of them was likewise consistent with a green
`extraction_macro_f1` — 0.7698 that time. The two most expensive were not new
cues at all: `contract_stability` had a comment saying its Spanish list tolerated
the Catalan cognate and a pattern that did not (29 adverts unread), and
`product_vs_services` had gained two cues that read agency *register* rather than
placement, one of them shaped to a corpus string. Both rounds' cases are below,
in one table, marked `round 2` where the second read begins.

Three things this table records without fixing, because each is a defect in the
*resolution* rule rather than in a cue, and the fix belongs to whoever owns that
rule rather than to a vocabulary pass:

* **Averaged cue values that are not rungs.** `Contrato indefinido fijo
  discontinuo.` matches `contract_stability`'s 0.9 and 0.3 cues and averages to
  0.6; `Salario Competitivo Banda salarial entre 33.000 y 40.000` averages 0.2
  and 0.9 to 0.55; a corroborated placement advert averages -0.7 and -0.5 to
  -0.6. `remote_arrangement` names this defect in its own comment ("0.75 is not
  a rung this dimension has") and it is alive in at least four other places.
* **Corroboration discarding a reading the labeller cited.** A bipolar dimension
  needs two matches, and an advert that states placement once — which the two
  Arelance adverts and `tecnoempleo-98201f7d82b073d32d45` all do — gets none.
  That is the whole of `product_vs_services`'s fall back to `main`'s 0.1667.
* **`_matched_cue_hits` takes `negated = all(...)` across language slices.** The
  cognate pairs carry matching `negatable` flags today, so no case flips; the
  ES/CA widening made the duplication systematic and nothing tests it.
"""

from __future__ import annotations

import json
import re
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
    """One advert fragment, the value the dimension's own text requires, and why.

    `negated` and `matches` are optional and pin what the rounded value alone
    cannot say. A `None` value has two causes that are not the same defect —
    **no cue matched** and **a reading the corroboration rule withheld** — and a
    `0.0` has two more: a `denies` cue firing, and an advert stating the 0.0 rung
    outright. Left unset they assert nothing; set, they are asserted exactly like
    `expected`, so a case that means "this is suppressed on one match" cannot
    quietly become "nothing matched at all".
    """

    dimension: str
    language: Language
    text: str
    expected: float | None
    cites: str
    direction: Direction
    negated: bool | None = None
    matches: int | None = None


@dataclass(frozen=True)
class Resolution:
    """What the rules stage did with one case — the value and how it got there.

    `matches` counts raw cue hits before containment and corroboration, and is
    the only thing that separates "the cue set is silent" from "the cue set read
    something and the bipolar rule refused to settle on it".
    """

    value: float | None
    negated: bool
    spans: int
    matches: int


# A floor, never the count of the day (T100). The number of cases may only go up:
# an audit that accepted a finding and then lost its fixture is an audit that
# reports success over work no longer being done. Raise this when cases are added;
# never lower it to make a deletion pass.
MINIMUM_CASES = 113

# The floor on cases whose regression direction is fail-open. Recorded separately
# because it is the half that matters: a fail-closed bug costs a fetch, a
# fail-open bug means a `hard` dealbreaker said yes to wording that never said it.
MINIMUM_FAIL_OPEN_CASES = 64

# The floor on cases that pin `negated` or the raw match count as well as the
# value. See `AuditCase` — a `None` and a `0.0` each have two distinct causes,
# and only these cases say which one the table means.
MINIMUM_MECHANISM_PINNED_CASES = 28


CASES: tuple[AuditCase, ...] = (
    # ---------------------------------------------------------------- finding 1
    # remote_arrangement 0.5 was a strict superset of 1.0 in all three languages.
    AuditCase(
        "remote_arrangement",
        "en",
        "Fully remote — anywhere in the EU.",
        1.0,
        "1.0 tell: 'the whole role is worked away from any company site'",
        "fail-open",
    ),
    AuditCase(
        "remote_arrangement",
        "es",
        "Teletrabajo total desde cualquier lugar.",
        1.0,
        "1.0 tell: 'the whole role is worked away from any company site'",
        "fail-open",
    ),
    AuditCase(
        # Returned 0.75 before the fix — the 1.0 and 0.5 cues matched the
        # *identical* span, which `cue_findings` containment does not drop
        # (it drops a match inside a strictly longer one). 0.75 is not a rung.
        "remote_arrangement",
        "ca",
        "100% teletreball des de casa.",
        1.0,
        "1.0 label: '100% teletreball'; the 0.5 tell asks for 'a split week'",
        "fail-open",
    ),
    AuditCase(
        # Returned 0.75 before the fix: two spans, in two sentences, neither
        # containing the other.
        "remote_arrangement",
        "en",
        "Fully remote position. We are a remote company.",
        1.0,
        "1.0 tell: 'the whole role is worked away from any company site'",
        "fail-open",
    ),
    AuditCase(
        "remote_arrangement",
        "es",
        "Se ofrece teletrabajo.",
        None,
        "0.5 tell: 'a split week — a stated number of days at home or in the office'",
        "fail-open",
    ),
    AuditCase(
        "remote_arrangement",
        "en",
        "This is not a remote role.",
        None,
        "0.5 tell: 'a split week — a stated number of days at home or in the office'",
        "fail-open",
    ),
    AuditCase(
        "remote_arrangement",
        "es",
        "2 días de teletrabajo a la semana.",
        0.5,
        "0.5 tell: 'a split week — a stated number of days at home or in the office'",
        "fail-closed",
    ),
    AuditCase(
        "remote_arrangement",
        "ca",
        "Més del 50% de la jornada de teletreball.",
        0.5,
        "0.5 tell: 'a split week — a stated number of days at home or in the office'",
        "fail-closed",
    ),
    AuditCase(
        # tecnoempleo strips the per-cent sign. Six evaluation-split adverts say
        # it this way and were being read one rung down.
        "remote_arrangement",
        "es",
        "Modalidad 100 remoto, estable y a largo plazo.",
        1.0,
        "1.0 tell: 'the whole role is worked away from any company site'",
        "fail-closed",
    ),
    AuditCase(
        "remote_arrangement",
        "es",
        "Modalidad de trabajo: presencial.",
        0.0,
        "0.0 tell: 'the ad names an office, a work city, or full presence'",
        "correct",
    ),
    # ---------------------------------------------------------------- finding 2
    # A driving licence is `commute_burden`'s by that dimension's own definition.
    AuditCase(
        "travel_requirement",
        "es",
        "Imprescindible carnet de conducir y vehículo propio.",
        None,
        "commute_burden.definition: 'holding a driving licence, or providing your own "
        "vehicle. A condition on the person, distinct from `travel_requirement`, which "
        "is travel done as part of the job'",
        "fail-open",
    ),
    AuditCase(
        "commute_burden",
        "es",
        "Imprescindible carnet de conducir y vehículo propio.",
        0.9,
        "commute_burden 0.9 tell: 'a driving licence or your own vehicle is stated as required'",
        "fail-closed",
    ),
    AuditCase(
        "travel_requirement",
        "es",
        "Se ofrece plus de desplazamiento.",
        None,
        "0.4 tell: 'client visits, or periodic presence at an office, framed as now and then'",
        "fail-open",
    ),
    # ---------------------------------------------------------------- finding 3
    # `movilidad nacional` is offered as a benefit; PR #320's audit of
    # `concept_map.yaml` left "internal mobility across countries" unmapped.
    AuditCase(
        "travel_requirement",
        "es",
        "Beneficios: movilidad nacional e internacional dentro del grupo.",
        None,
        "0.9 tell: 'travel is part of the job, or the role requires moving to a stated place'",
        "fail-open",
    ),
    AuditCase(
        "travel_requirement",
        "ca",
        "Beneficis: mobilitat nacional i internacional dins del grup.",
        None,
        "0.9 tell: 'travel is part of the job, or the role requires moving to a stated place'",
        "fail-open",
    ),
    AuditCase(
        "travel_requirement",
        "es",
        "Disponibilidad para realizar 3-4 viajes al año, de 2-3 días máximo.",
        0.4,
        "0.4 tell: 'client visits, or periodic presence at an office, framed as now and then'",
        "fail-closed",
    ),
    AuditCase(
        "travel_requirement",
        "en",
        "Occasional business trips.",
        0.4,
        "0.4 tell: 'client visits, or periodic presence at an office, framed as now and then'",
        "fail-open",
    ),
    AuditCase(
        # The mild finding asking for 0.4 here is rejected: the 0.9 rung's own
        # tell opens with "travel is part of the job", which this states.
        #
        # The **expected value** was wrong, and wrong in the way this table exists
        # to catch: it said 0.8, which is not a rung `travel_requirement` has — it
        # was the cue's own value, read off the code. The committed gold for
        # "Disponibilidad para viajar" already recorded 0.9 for that same cue, so
        # the cue was disagreeing with the dimension's own gold. Cue and case now
        # both say 0.9, which is what the tell describes.
        "travel_requirement",
        "en",
        "Frequent business trips to client offices.",
        0.9,
        "0.9 tell: 'travel is part of the job, or the role requires moving to a stated place'",
        "correct",
    ),
    AuditCase(
        "travel_requirement",
        "es",
        "No se requieren desplazamientos.",
        0.0,
        "0.0 tell: 'the ad asks for no travel and names no relocation'",
        "fail-open",
    ),
    # ------------------------------------------------------------- findings 4/12
    # The deny cue was a narrow literal while the positives were widened, and
    # `_is_negated` only looks *backwards* — so a negator that follows the cue is
    # reachable by nothing but the deny cue, which must span the positive match.
    AuditCase(
        "english_demand",
        "en",
        "English skills not required.",
        0.0,
        "0.0 tell: 'the ad says English is not needed, or asks for none at all'",
        "fail-open",
    ),
    AuditCase(
        "english_demand",
        "en",
        "No advanced English is required for this role.",
        0.0,
        "0.0 tell: 'the ad says English is not needed, or asks for none at all'",
        "fail-open",
    ),
    AuditCase(
        "english_demand",
        "es",
        "No se requiere inglés.",
        0.0,
        "0.0 tell: 'the ad says English is not needed, or asks for none at all'",
        "fail-open",
    ),
    AuditCase(
        "english_demand",
        "en",
        "Fluent English is required.",
        1.0,
        "1.0 tell: 'C1/fluent/native, or English named as the working language'",
        "fail-closed",
    ),
    # ---------------------------------------------------------------- finding 5
    # *Básico* is A1/A2 — below the B1 floor the 0.6 tell states — and the 0.0
    # tell says "asks for none at all", which an ad asking for basic English does
    # not. Neither rung fits, so no cue may claim one.
    AuditCase(
        "english_demand",
        "es",
        "Inglés nivel básico.",
        None,
        "0.6 tell: 'B1/B2, or enough to read documentation and follow written threads'",
        "fail-open",
    ),
    AuditCase(
        "english_demand",
        "ca",
        "Anglès bàsic.",
        None,
        "0.6 tell: 'B1/B2, or enough to read documentation and follow written threads'",
        "fail-open",
    ),
    AuditCase(
        # The `suficiente` half of the finding is rejected: the 0.6 tell says in
        # its own words "enough to read documentation".
        "english_demand",
        "es",
        "Nivel de inglés suficiente para leer documentación.",
        0.6,
        "0.6 tell: 'B1/B2, or enough to read documentation and follow written threads'",
        "correct",
    ),
    # ---------------------------------------------------------------- finding 6
    # The 0.8 tell asks for the word *in the title*. `cue_findings` reads
    # `ad.text`, never `ad.title`, so a body-text cue cannot tell the offered role
    # from a duty line or from somebody else's job.
    AuditCase(
        "seniority_expectation",
        "es",
        "Será responsable de mantener la documentación.",
        None,
        "0.8 tell: 'senior/lead/principal in the title, or a stated floor of many years'",
        "fail-open",
    ),
    AuditCase(
        "seniority_expectation",
        "es",
        "Reportarás al jefe de equipo.",
        None,
        "0.8 tell: 'senior/lead/principal in the title, or a stated floor of many years'",
        "fail-open",
    ),
    AuditCase(
        "seniority_expectation",
        "es",
        "Buscamos un/a Jefe de Obra para la zona norte.",
        0.8,
        "0.8 tell: 'senior/lead/principal in the title, or a stated floor of many years'",
        "fail-closed",
    ),
    AuditCase(
        "seniority_expectation",
        "en",
        "Experience with lead generation campaigns.",
        None,
        "0.8 tell: 'senior/lead/principal in the title, or a stated floor of many years'",
        "fail-open",
    ),
    AuditCase(
        "seniority_expectation",
        "en",
        "Lead Data Engineer, Barcelona.",
        0.8,
        "0.8 tell: 'senior/lead/principal in the title, or a stated floor of many years'",
        "fail-closed",
    ),
    # ---------------------------------------------------------------- finding 7
    # The junior and mid rungs overlapped and averaged to 0.35, which is not a
    # rung; and *valorará* (desirable) was folded into the same alternation as
    # *requiere* (required), erasing the distinction the two rungs exist to draw.
    AuditCase(
        "seniority_expectation",
        "es",
        "Sin experiencia previa en el sector.",
        0.2,
        "0.2 tell: 'no experience required, or an explicit junior/graduate/trainee opening'",
        "fail-open",
    ),
    AuditCase(
        "seniority_expectation",
        "es",
        "Se valorará experiencia en Python.",
        None,
        "0.5 tell: 'a few years asked for, or a plain practitioner title with no seniority word'",
        "fail-open",
    ),
    AuditCase(
        "seniority_expectation",
        "es",
        "Experiencia mínima de 2 años en el puesto.",
        0.5,
        "0.5 tell: 'a few years asked for, or a plain practitioner title with no seniority word'",
        "fail-closed",
    ),
    AuditCase(
        "seniority_expectation",
        "ca",
        "Sense experiència prèvia.",
        0.2,
        "0.2 tell: 'no experience required, or an explicit junior/graduate/trainee opening'",
        "correct",
    ),
    # ---------------------------------------------------------------- finding 8
    AuditCase(
        "compensation_transparency",
        "es",
        "Se ofrecen 12 o 14 pagas.",
        None,
        "definition: 'a stated band, a figure, or nothing but competitive. A property of "
        "the ad's wording, not of the amount'; 0.9 tell: 'an actual amount or range'",
        "fail-open",
    ),
    AuditCase(
        "compensation_transparency",
        "ca",
        "Salari en 12 pagues.",
        None,
        "0.9 tell: 'an actual amount or range the reader can act on'",
        "fail-open",
    ),
    # ---------------------------------------------------------------- finding 9
    # Any euro amount anywhere scored 0.9. The English band cue was already
    # anchored as a *band*; the Spanish figure branches now are too.
    AuditCase(
        "compensation_transparency",
        "es",
        "Ayuda de 1.000 € para material de teletrabajo.",
        None,
        "0.9 tell: 'an actual amount or range the reader can act on' — of what the role pays",
        "fail-open",
    ),
    AuditCase(
        "compensation_transparency",
        "es",
        "Seguro de vida de 30.000 euros.",
        None,
        "0.9 tell: 'an actual amount or range the reader can act on' — of what the role pays",
        "fail-open",
    ),
    AuditCase(
        "compensation_transparency",
        "es",
        "Salario 35.000 € brutos anuales.",
        0.9,
        "0.9 tell: 'an actual amount or range the reader can act on'",
        "fail-closed",
    ),
    AuditCase(
        "compensation_transparency",
        "es",
        "Banda salarial de 30.000 a 40.000 €.",
        0.9,
        "0.9 tell: 'an actual amount or range the reader can act on'",
        "fail-closed",
    ),
    AuditCase(
        # The mild finding asking for more than 0.2 here is rejected: the
        # definition's second sentence settles it — this is a property of the
        # ad's wording, and the wording carries a word where a number should be.
        "compensation_transparency",
        "es",
        "Salario según convenio.",
        0.2,
        "0.2 tell: \"'competitive salary', 'salary according to experience' — a word "
        'where a number should be"',
        "correct",
    ),
    # --------------------------------------------------------------- finding 10
    # Generic joining and having-customers language scored -0.5. Every employer
    # has clients; being placed *with* them is the rung. Corroboration cannot see
    # two agreeing matches that are both wrong.
    AuditCase(
        "product_vs_services",
        "es",
        "Buscamos una persona para incorporarse a un equipo en crecimiento. Proyecto estable.",
        None,
        "-0.7 tell: 'you are placed with the employer's clients, or billed into their projects'",
        "fail-open",
    ),
    AuditCase(
        "product_vs_services",
        "es",
        "Nuestros clientes confían en nosotros. Proyecto estable y a largo plazo.",
        None,
        "-0.7 tell: 'you are placed with the employer's clients, or billed into their projects'",
        "fail-open",
    ),
    AuditCase(
        "product_vs_services",
        "en",
        "We are a product company. Hiring a Solutions Consultant. Our consultants love it.",
        None,
        "-0.7 tell: 'you are placed with the employer's clients, or billed into their projects'",
        "fail-open",
    ),
    AuditCase(
        "product_vs_services",
        "en",
        "Experience integrating SaaS platforms for our clients is a plus.",
        None,
        "0.7 tell: 'the thing you build is the thing the employer sells'",
        "fail-open",
    ),
    AuditCase(
        "product_vs_services",
        "es",
        "Somos partner estratégico de Microsoft y partner tecnológico de SAP.",
        None,
        "-0.7 tell: 'you are placed with the employer's clients, or billed into their projects'",
        "fail-open",
    ),
    AuditCase(
        # The Arelance boilerplate, verbatim, and the only case behind the
        # `nuestros candidatos` cue — which it could never isolate, because the
        # same sentence also carries `profesionales para nuestros clientes`, which
        # does the legitimate work. With the register cue gone (A1) the sentence
        # states placement **once**, and the bipolar corroboration rule withholds
        # a reading on a single match.
        #
        # `matches=1` is the load-bearing half of this case: `None` here does not
        # mean the cue set is silent, it means it read the labeller's own span and
        # refused to settle on it. The owner's label on
        # `tecnoempleo-5daa18bff2393309c941` cites exactly this clause, so the cost
        # of A1 is recorded here rather than left to be inferred from a macro-F1.
        "product_vs_services",
        "es",
        "Buscamos los mejores profesionales para nuestros clientes y ofrecemos a nuestros "
        "candidatos los mejores proyectos.",
        None,
        "-0.7 tell: 'you are placed with the employer's clients, or billed into their "
        "projects' — met once; corroboration (T59) withholds it on a single match",
        "fail-closed",
        matches=1,
    ),
    # --------------------------------------------------------------- finding 11
    AuditCase(
        "learning_support",
        "es",
        "Plan de carrera dentro de la compañía.",
        None,
        "learning_support.definition: 'What the employer puts behind learning'; "
        "career_progression.definition: 'a named path upward — levels, a career plan'",
        "fail-open",
    ),
    AuditCase(
        "learning_support",
        "en",
        "Career path and promotion criteria are defined.",
        None,
        "learning_support.definition: 'What the employer puts behind learning'; "
        "career_progression 0.8 tell: 'levels, a career plan, or stated promotion criteria'",
        "fail-open",
    ),
    AuditCase(
        "career_progression",
        "es",
        "Plan de carrera dentro de la compañía.",
        0.8,
        "career_progression 0.8 tell: 'levels, a career plan, or stated promotion criteria'",
        "fail-closed",
    ),
    AuditCase(
        "learning_support",
        "es",
        "Acceso continuo a formación técnica.",
        0.7,
        "definition: 'What the employer puts behind learning: paid training, certification "
        "budgets, conference or language classes'",
        "fail-closed",
    ),
    # ------------------------------------------------------------------- milds
    AuditCase(
        # "To be agreed with the employer" is nothing stated — which is exactly
        # how `compensation_transparency` reads the identical idiom.
        "schedule_flexibility",
        "es",
        "Horario a convenir.",
        None,
        "0.7 tell: 'asynchronous work, compressed weeks, or hours the person genuinely sets'",
        "fail-open",
    ),
    AuditCase(
        # Rejected. Since the 2021 reform a *fijo discontinuo* is legally
        # indefinido, which argues for 0.9 — but the 0.3 tell names "a season" in
        # its own words, and what this dimension measures is "how durable the
        # engagement is", which a contract that stops every year is not. The
        # error direction is fail-closed either way, and that is the cheaper one.
        "contract_stability",
        "es",
        "Contrato fijo discontinuo.",
        0.3,
        "0.3 tell: 'a contract with a stated end — a project, a cover, a season'",
        "correct",
    ),
    # ================================================================== round 2
    # A second independent read of the same diff, and CodeRabbit's line-level
    # findings on it. Same rule as everything above: every verdict is derived from
    # a `definition:` or a rung's `tell:`, never from what the cue set returns.
    # -------------------------------------------------------------------- A1
    # Two cues the -0.7/-0.5 rungs do not describe. `nuestros candidatos` is agency
    # *register* — it names no client, no project and no billing relation — and
    # four of the five head nouns in the `proyecto … dentro de …` cue (`empresa`,
    # `compañía`, `organización`, `entidad`) are what an employer calls *itself*.
    # Only the `cliente` branch states the relation the rung is.
    AuditCase(
        # The load-bearing case: two agreeing matches, both wrong, which is exactly
        # what this file's own header says corroboration cannot detect. It settled
        # at -0.5 on wording that never says whose product you would build.
        "product_vs_services",
        "es",
        "Ofrecemos a nuestros candidatos un proceso ágil. Proyecto estable dentro de "
        "una empresa líder en su sector.",
        None,
        "-0.7 tell: 'you are placed with the employer's clients, or billed into their projects'",
        "fail-open",
        matches=0,
    ),
    AuditCase(
        "product_vs_services",
        "es",
        "Ofrecemos a nuestros candidatos un proceso de selección ágil.",
        None,
        "-0.7 tell: 'you are placed with the employer's clients, or billed into their projects'",
        "fail-open",
        matches=0,
    ),
    AuditCase(
        "product_vs_services",
        "es",
        "Proyecto estable dentro de una empresa líder.",
        None,
        "-0.7 tell: 'you are placed with the employer's clients, or billed into their projects'",
        "fail-open",
        matches=0,
    ),
    AuditCase(
        "product_vs_services",
        "ca",
        "Oferim als nostres candidats un procés àgil. Projecte estable dins d'una "
        "empresa líder del sector.",
        None,
        "-0.7 tell: 'you are placed with the employer's clients, or billed into their projects'",
        "fail-open",
        matches=0,
    ),
    AuditCase(
        # And the half a deletion never proves on its own: the legitimate placement
        # cue is still there and still reads placement when an advert states it
        # twice, which is what the bipolar rule asks for.
        "product_vs_services",
        "es",
        "En Arelance buscamos los mejores profesionales para nuestros clientes. "
        "Trabajarás en las oficinas del cliente.",
        -0.5,
        "-0.7 tell: 'you are placed with the employer's clients, or billed into their projects'",
        "fail-closed",
        matches=2,
    ),
    # -------------------------------------------------------------------- A2
    # feinaactiva renders "Contracte laboral indefinit" on Spanish-body adverts,
    # and the ES list's own comment says it must tolerate the cognate. It did not:
    # Spanish *contrato* stems to `contrat`, Catalan *contracte* to `contract`, and
    # neither stem reaches the other spelling. 33 Spanish-language corpus adverts
    # carry that field and 29 got no reading at all.
    AuditCase(
        "contract_stability",
        "es",
        "Contracte laboral indefinit",
        0.9,
        "0.9 tell: 'an open-ended employment contract, stated as such'",
        "fail-closed",
    ),
    AuditCase(
        "contract_stability",
        "ca",
        "Contrato indefinido",
        0.9,
        "0.9 tell: 'an open-ended employment contract, stated as such'",
        "fail-closed",
    ),
    AuditCase(
        "contract_stability",
        "es",
        "Contracte temporal per substitució.",
        0.3,
        "0.3 tell: 'a contract with a stated end — a project, a cover, a season'",
        "fail-closed",
    ),
    AuditCase(
        "contract_stability",
        "ca",
        "Contrato temporal.",
        0.3,
        "0.3 tell: 'a contract with a stated end — a project, a cover, a season'",
        "fail-closed",
    ),
    AuditCase(
        # `feinaactiva-FA92318598` in miniature — a Spanish-language trades advert
        # whose only structured fields are Catalan. It read *nothing at all* on the
        # branch head, which is what took `D-19.trades.ads_reached` to 17 of 18.
        "contract_stability",
        "es",
        "Contracte laboral indefinit\n\nJornada intensiva",
        0.9,
        "0.9 tell: 'an open-ended employment contract, stated as such'",
        "fail-closed",
    ),
    # ---------------------------------------------------------------- A3 / F4
    # The 0.8 tell asks for the word **in the title**. A bare `staff` is a
    # headcount noun, a service ("staff augmentation") and a perk ("staff
    # discount") before it is a level name — and the same commit had already
    # narrowed `lead` to `lead <role-noun>` in the same pattern string, for
    # exactly this reason.
    AuditCase(
        "seniority_expectation",
        "en",
        "Join our staff of 200 engineers.",
        None,
        "0.8 tell: 'senior/lead/principal in the title, or a stated floor of many years'",
        "fail-open",
    ),
    AuditCase(
        "seniority_expectation",
        "en",
        "We provide staff augmentation for banks.",
        None,
        "0.8 tell: 'senior/lead/principal in the title, or a stated floor of many years'",
        "fail-open",
    ),
    AuditCase(
        "seniority_expectation",
        "en",
        "Staff discount and free lunch.",
        None,
        "0.8 tell: 'senior/lead/principal in the title, or a stated floor of many years'",
        "fail-open",
    ),
    AuditCase(
        # `remotive-2091075` lists these among the titles a sales rep should source
        # leads from — somebody else's job. `head of` still claims it, which is a
        # separate finding already recorded above; what must not happen is `Chief
        # of Staff` adding a second match to it.
        "seniority_expectation",
        "en",
        "Titles such as Head of People or Chief of Staff.",
        0.8,
        "0.8 tell: 'senior/lead/principal in the title' — reached by 'head of' alone",
        "fail-open",
        matches=1,
    ),
    AuditCase(
        "seniority_expectation",
        "en",
        "As a Staff Software Engineer you will operate across teams.",
        0.8,
        "0.8 tell: 'senior/lead/principal in the title, or a stated floor of many years'",
        "fail-closed",
    ),
    AuditCase(
        "seniority_expectation",
        "en",
        "Senior Backend Engineer, Madrid.",
        0.8,
        "0.8 tell: 'senior/lead/principal in the title, or a stated floor of many years'",
        "fail-closed",
    ),
    # ---------------------------------------------------------------- A3 / F5
    # The junior cue carried `sin experiencia previa` with `negatable: false`, so
    # an advert *refusing* candidates without experience read as a junior opening.
    AuditCase(
        "seniority_expectation",
        "es",
        "No se valorarán perfiles sin experiencia previa en el sector.",
        -0.2,
        "0.2 tell: 'no experience required, or an explicit junior/graduate/trainee "
        "opening' — this advert denies it, and a negated match is evidence against",
        "fail-open",
        negated=True,
    ),
    AuditCase(
        # The same defect in Catalan, and there it is live: `feinaactiva-FA92320052`
        # says this and also states "Experiència 2 anys".
        "seniority_expectation",
        "ca",
        "No s'entrevistarà candidats sense experiència.",
        -0.2,
        "0.2 tell: 'no experience required, or an explicit junior/graduate/trainee "
        "opening' — this advert denies it, and a negated match is evidence against",
        "fail-open",
        negated=True,
    ),
    AuditCase(
        # And the one that must not flip: the negator is the cue's own first word,
        # with nothing before it to govern the match.
        "seniority_expectation",
        "ca",
        "Experiència en restauració o sense experiència.",
        0.2,
        "0.2 tell: 'no experience required, or an explicit junior/graduate/trainee opening'",
        "correct",
        negated=False,
    ),
    # ---------------------------------------------------------------- A3 / F6
    # This PR rewrote travel's denial cues and did not extend them to relocation,
    # so `No relocation is required` scored the top rung of a `hard` dimension.
    # The denial is carried by the 0.0 cue rather than by `negatable`, because
    # this dimension already answers a stated denial with its 0.0 rung — which the
    # 0.0 tell names in its own words — and -0.9 is not a rung it has.
    AuditCase(
        "travel_requirement",
        "en",
        "No relocation is required.",
        0.0,
        "0.0 tell: 'the ad asks for no travel and names no relocation'",
        "fail-open",
        negated=True,
    ),
    AuditCase(
        "travel_requirement",
        "es",
        "No se requiere traslado.",
        0.0,
        "0.0 tell: 'the ad asks for no travel and names no relocation'",
        "fail-open",
        negated=True,
    ),
    AuditCase(
        "travel_requirement",
        "ca",
        "No es requereix trasllat.",
        0.0,
        "0.0 tell: 'the ad asks for no travel and names no relocation'",
        "fail-open",
        negated=True,
    ),
    AuditCase(
        # Unchanged, and pinned so the denial above cannot swallow it.
        "travel_requirement",
        "en",
        "Relocation to Barcelona is required.",
        0.9,
        "0.9 tell: 'travel is part of the job, or the role requires moving to a stated place'",
        "fail-closed",
        negated=False,
    ),
    # ---------------------------------------------------------------- A3 / F8
    # The English 0.4 rung had no numeric-frequency alternative though both its ES
    # and CA twins do — and the Spanish equivalent of this sentence is already a
    # committed fixture at 0.4, twenty cases above.
    AuditCase(
        "travel_requirement",
        "en",
        "The role involves 3-4 business trips a year of 2-3 days each.",
        0.4,
        "0.4 tell: 'client visits, or periodic presence at an office, framed as now and then'",
        "fail-open",
    ),
    # ---------------------------------------------------------------- A4 / F2
    # `a convenir` on its own is a schedule clause as often as a pay clause;
    # `feinaactiva-FA92319777` says "Horari a convenir" and nothing about money.
    # The audit table already held this exact string — tested against
    # `schedule_flexibility`, not against the dimension it broke.
    AuditCase(
        "compensation_transparency",
        "es",
        "Horario a convenir.",
        None,
        "definition: 'Whether the ad states what the role pays'; 0.2 tell: 'a word "
        "where a number should be'",
        "fail-open",
        matches=0,
    ),
    AuditCase(
        "compensation_transparency",
        "ca",
        "Horari a convenir.",
        None,
        "definition: 'Whether the ad states what the role pays'; 0.2 tell: 'a word "
        "where a number should be'",
        "fail-open",
        matches=0,
    ),
    AuditCase(
        # `feinaactiva-FA92317986`, verbatim — the legitimate use, kept.
        "compensation_transparency",
        "ca",
        "Sou: A convenir",
        0.2,
        "0.2 tell: \"'competitive salary', 'salary according to experience' — a word "
        'where a number should be"',
        "fail-closed",
    ),
    AuditCase(
        "compensation_transparency",
        "es",
        "Retribución a convenir según valía y experiencia aportada.",
        0.2,
        "0.2 tell: \"'competitive salary', 'salary according to experience' — a word "
        'where a number should be"',
        "correct",
    ),
    # ---------------------------------------------------------------- A4 / F3
    # Finding 9 above anchored the *bare* euro figure and left the annual one
    # unanchored, so any yearly amount in an advert was read as the salary. Every
    # one of the twelve corpus adverts this branch reaches says `brutos`/`bruts`;
    # none of the three below does, and none of them is about pay. The two
    # fixtures finding 9 committed are these same sentences with the qualifier
    # removed — they passed, and the realistic forms did not.
    AuditCase(
        "compensation_transparency",
        "es",
        "Ayuda de 1.000 euros anuales para material.",
        None,
        "0.9 tell: 'an actual amount or range the reader can act on' — of what the role pays",
        "fail-open",
        matches=0,
    ),
    AuditCase(
        "compensation_transparency",
        "es",
        "Presupuesto de 1.000 euros anuales para formación.",
        None,
        "0.9 tell: 'an actual amount or range the reader can act on' — of what the role pays",
        "fail-open",
        matches=0,
    ),
    AuditCase(
        "compensation_transparency",
        "es",
        "Seguro de vida de 30.000 euros anuales.",
        None,
        "0.9 tell: 'an actual amount or range the reader can act on' — of what the role pays",
        "fail-open",
        matches=0,
    ),
    AuditCase(
        # `feinaactiva-09202622315`, verbatim: the recall this must not cost.
        "compensation_transparency",
        "ca",
        "Sou: 1.850 € bruts mensuals per 14 pagues.",
        0.9,
        "0.9 tell: 'an actual amount or range the reader can act on'",
        "fail-closed",
    ),
    AuditCase(
        "compensation_transparency",
        "es",
        "Banda salarial entre 33.000 y 40.000 brutos anuales.",
        0.9,
        "0.9 tell: 'an actual amount or range the reader can act on'",
        "fail-closed",
    ),
    # ---------------------------------------------------------------- A4 / F7
    # `learning_support` 0.5 names "'continuous learning' or 'professional
    # development'"; `career_progression` 0.5 names "'opportunities to grow' with
    # no criteria attached to it" — which is what *growth* is. Identical in shape
    # to the `plan de carrera` finding already above, left standing one
    # alternative away from it.
    AuditCase(
        "learning_support",
        "es",
        "Ofrecemos crecimiento profesional.",
        None,
        "learning_support 0.5 tell: \"'continuous learning' or 'professional development' "
        'with nothing attached"; career_progression 0.5 tell: "\'opportunities to grow\'"',
        "fail-open",
        matches=0,
    ),
    AuditCase(
        "career_progression",
        "es",
        "Ofrecemos crecimiento profesional.",
        0.5,
        "career_progression 0.5 tell: \"'opportunities to grow' with no criteria attached to it\"",
        "fail-closed",
    ),
    AuditCase(
        "learning_support",
        "en",
        "We offer professional growth.",
        None,
        "learning_support 0.5 tell: \"'continuous learning' or 'professional development' "
        'with nothing attached"; career_progression 0.5 tell: "\'opportunities to grow\'"',
        "fail-open",
        matches=0,
    ),
    AuditCase(
        "career_progression",
        "en",
        "We offer professional growth.",
        0.5,
        "career_progression 0.5 tell: \"'opportunities to grow' with no criteria attached to it\"",
        "fail-closed",
    ),
    AuditCase(
        "learning_support",
        "ca",
        "Oferim creixement professional.",
        None,
        "learning_support 0.5 tell: \"'continuous learning' or 'professional development' "
        'with nothing attached"; career_progression 0.5 tell: "\'opportunities to grow\'"',
        "fail-open",
        matches=0,
    ),
    AuditCase(
        "career_progression",
        "ca",
        "Oferim creixement professional.",
        0.5,
        "career_progression 0.5 tell: \"'opportunities to grow' with no criteria attached to it\"",
        "fail-closed",
    ),
    AuditCase(
        # And what the learning 0.5 tell *does* name, which must stay where it is.
        "learning_support",
        "en",
        "We offer professional development.",
        0.5,
        "learning_support 0.5 tell: \"'continuous learning' or 'professional development' "
        'with nothing attached"',
        "fail-closed",
    ),
    # -------------------------------------------------------------------- B1
    # A regression this PR introduced: `vehículo propio` moved into
    # `commute_burden` (correctly) beside licence cues that never consulted the
    # negator, at 0.9 on a `hard` dimension. `_NEGATORS` already covers `no`,
    # `sin`, `nunca` / `no`, `sense`, `mai`, and every negator here precedes the
    # match, so `negatable` reaches it and `denies` is not needed.
    AuditCase(
        "commute_burden",
        "es",
        "No se requiere carnet de conducir.",
        -0.9,
        "0.9 tell: 'a driving licence or your own vehicle is stated as required' — "
        "this advert states the opposite",
        "fail-open",
        negated=True,
    ),
    AuditCase(
        "commute_burden",
        "ca",
        "No es requereix carnet de conduir.",
        -0.9,
        "0.9 tell: 'a driving licence or your own vehicle is stated as required' — "
        "this advert states the opposite",
        "fail-open",
        negated=True,
    ),
    AuditCase(
        "commute_burden",
        "en",
        "No driving licence is required.",
        -0.9,
        "0.9 tell: 'a driving licence or your own vehicle is stated as required' — "
        "this advert states the opposite",
        "fail-open",
        negated=True,
    ),
    AuditCase(
        # The residency rung is deliberately untouched, and pinned so it stays so.
        "commute_burden",
        "es",
        "Residencia en la zona.",
        0.5,
        "0.5 tell: 'living in the area is required or preferred'",
        "correct",
        negated=False,
    ),
    AuditCase(
        "commute_burden",
        "ca",
        "Permís de conduir: B",
        0.9,
        "0.9 tell: 'a driving licence or your own vehicle is stated as required'",
        "correct",
        negated=False,
    ),
    # -------------------------------------------------------------------- B2
    # The 0.2 rung's tell names `'competitive salary'` as its own example, in its
    # own words. The cues scored 0.1, which is not a rung this dimension has.
    AuditCase(
        "compensation_transparency",
        "en",
        "We offer a competitive salary.",
        0.2,
        "0.2 tell: \"'competitive salary', 'salary according to experience' — a word "
        'where a number should be"',
        "fail-closed",
    ),
    AuditCase(
        "compensation_transparency",
        "es",
        "Salario competitivo.",
        0.2,
        "0.2 tell: \"'competitive salary', 'salary according to experience' — a word "
        'where a number should be"',
        "fail-closed",
    ),
    AuditCase(
        "compensation_transparency",
        "ca",
        "Salari competitiu.",
        0.2,
        "0.2 tell: \"'competitive salary', 'salary according to experience' — a word "
        'where a number should be"',
        "fail-closed",
    ),
    # -------------------------------------------------------------------- B3
    # One modifier, two answers, in one file: `viajes puntuales` scored 0.8 while
    # `desplazamientos puntuales` scored 0.4 four lines away, and the 0.4 tell is
    # "framed as now and then" — which is what *puntual* means.
    AuditCase(
        "travel_requirement",
        "es",
        "Viajes puntuales a clientes.",
        0.4,
        "0.4 tell: 'client visits, or periodic presence at an office, framed as now and then'",
        "fail-open",
    ),
    AuditCase(
        "travel_requirement",
        "ca",
        "Viatges puntuals a clients.",
        0.4,
        "0.4 tell: 'client visits, or periodic presence at an office, framed as now and then'",
        "fail-open",
    ),
    AuditCase(
        "travel_requirement",
        "es",
        "Desplazamientos puntuales a clientes.",
        0.4,
        "0.4 tell: 'client visits, or periodic presence at an office, framed as now and then'",
        "correct",
    ),
    AuditCase(
        # `frecuentes` stays at the top rung — that tell opens "travel is part of
        # the job", which a frequent trip schedule is.
        "travel_requirement",
        "es",
        "Viajes frecuentes por Europa.",
        0.9,
        "0.9 tell: 'travel is part of the job, or the role requires moving to a stated place'",
        "correct",
    ),
    AuditCase(
        "travel_requirement",
        "ca",
        "Viatges freqüents per Europa.",
        0.9,
        "0.9 tell: 'travel is part of the job, or the role requires moving to a stated place'",
        "correct",
    ),
    # -------------------------------------------------------------------- B4
    # The 0.4 tell is "flexible start and finish, or an intensive summer, inside a
    # fixed frame" — the phrase almost verbatim. The 0.7 rung asks for
    # asynchronous work, compressed weeks, or hours the person genuinely sets.
    AuditCase(
        "schedule_flexibility",
        "es",
        "Entrada y salida flexible.",
        0.4,
        "0.4 tell: 'flexible start and finish, or an intensive summer, inside a fixed frame'",
        "fail-open",
    ),
    AuditCase(
        "schedule_flexibility",
        "ca",
        "Entrada i sortida flexible.",
        0.4,
        "0.4 tell: 'flexible start and finish, or an intensive summer, inside a fixed frame'",
        "fail-open",
    ),
    AuditCase(
        # And what 0.7 is for, unchanged.
        "schedule_flexibility",
        "es",
        "Horario flexible.",
        0.7,
        "0.7 tell: 'asynchronous work, compressed weeks, or hours the person genuinely sets'",
        "correct",
    ),
    # ------------------------------------------------------------------- F10
    # `talking_clients` was the tenth dimension this PR widened and the only one
    # the first independent read passed as clean. That was true of its ES and CA
    # halves; the **English** half was added in the same commit and was never
    # cleared. `help\s?desk` at 1.0 read a ticketing tool as an account role.
    AuditCase(
        "talking_clients",
        "en",
        "Helpdesk ticketing experience required.",
        None,
        "1.0 tell: 'the role IS the interface — account management, solutions "
        "engineering, support, training or pre-sales'",
        "fail-open",
        matches=0,
    ),
    AuditCase(
        "talking_clients",
        "en",
        "Help desk agent for our support team.",
        1.0,
        "1.0 tell: 'the role IS the interface — account management, solutions "
        "engineering, support, training or pre-sales'",
        "fail-closed",
    ),
    AuditCase(
        # The ES/CA half the first read cleared — pinned rather than assumed.
        "talking_clients",
        "es",
        "Atención al público en tienda.",
        1.0,
        "1.0 tell: 'the role IS the interface — account management, solutions "
        "engineering, support, training or pre-sales'",
        "correct",
    ),
)


def _dimension(dimensions: list[Dimension], dimension_id: str) -> Dimension:
    for dimension in dimensions:
        if dimension.id == dimension_id:
            return dimension
    raise KeyError(f"no dimension {dimension_id!r} in the committed model")


def _raw_match_count(case: AuditCase, dimension: Dimension) -> int:
    """Cue hits before containment and corroboration — a count, never a verdict.

    Deliberately not a second implementation of `cue_findings`: it applies no
    containment, no sign check and no corroboration, so it cannot disagree with
    the stage about *what the answer is*. It only says whether the stage had
    anything to work from.
    """
    return sum(
        1
        for cue in dimension.extraction.cues.get(case.language, [])
        for match in re.finditer(cue.pattern, case.text, re.IGNORECASE)
        if match.end() > match.start()
    )


def resolve(case: AuditCase, dimensions: list[Dimension]) -> Resolution:
    """What the rules stage actually does with `case`."""
    dimension = _dimension(dimensions, case.dimension)
    ad = NormalisedAd(offer_id="cue-audit", language=case.language, text=case.text)
    score = cue_findings(ad, dimension)
    return Resolution(
        value=None if score is None else round(score.value, 4),
        negated=False if score is None else score.negated,
        spans=0 if score is None else len(score.spans),
        matches=_raw_match_count(case, dimension),
    )


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
        wrong: list[str] = []
        if got.value != case.expected:
            wrong.append(f"value {got.value!r}")
        if case.negated is not None and got.negated != case.negated:
            wrong.append(f"negated {got.negated!r} (expected {case.negated!r})")
        if case.matches is not None and got.matches != case.matches:
            wrong.append(f"raw cue matches {got.matches} (expected {case.matches})")
        if wrong:
            failures.append(
                f"{case.dimension}[{case.language}] {case.text!r}: "
                f"{case.cites} requires {case.expected!r}, cue set returns "
                f"{', '.join(wrong)} ({case.direction})"
            )
    fail_open = [case for case in cases if case.direction == "fail-open"]
    pinned = [case for case in cases if case.negated is not None or case.matches is not None]
    return {
        "cue_audit_cases": len(cases),
        "cue_audit_cases_at_least": MINIMUM_CASES,
        "cue_audit_fail_open_cases": len(fail_open),
        "cue_audit_fail_open_cases_at_least": MINIMUM_FAIL_OPEN_CASES,
        # A rounded value cannot tell a denial from a rung-0 statement, nor a
        # silent cue set from a reading corroboration withheld. These are the
        # cases that say which, and the count is a floor for the same reason the
        # others are: dropping the distinction is how the table stops meaning
        # what it says.
        "cue_audit_cases_pinning_mechanism": len(pinned),
        "cue_audit_cases_pinning_mechanism_at_least": MINIMUM_MECHANISM_PINNED_CASES,
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
