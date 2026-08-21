"""D-20 — a constraint the candidate states must reach the filter, not just the log.

During the test session of 2026-08-20 the candidate said:

> "I can move, but in the province of Barcelona, or maximum to Girona or
> Tarragona. I want to sleep home each day."

That is the single most filtering thing anyone said in the whole session, and
none of T24's ten pinned fields could hold it. `location` took a country and an
on-site flag; `reach` took modes, not a distance; `relocation` refused
`destinations` when `willingness` was `no` — correctly, because he was not
relocating. So the sentence survived as quote text on an evidence row, and
`filter_hard_constraints` went on showing him jobs in Sevilla.

`Location.commutable_regions` is where it lives now, because `Location` already
owns "the on-site work they'll do without moving" and
`accepts_onsite_in_country` was simply that question asked too coarsely — one
bool over a whole country. Putting it there keeps the pinned set at ten rather
than growing a field per sentence.

**What this module measures is the general shape, not that one sentence.**
`unfilterable_stated_constraints` counts the constraints a candidate can state
that fail to reach the filter, and a constraint fails in either of two ways:

- **Nowhere to put it.** No pinned field can hold what was said, so it is
  recorded as prose or not at all. That is D-20 as filed.
- **Somewhere to put it that changes nothing.** A field accepts the value and
  no offer's fate depends on it. This is the one worth guarding: it looks
  answered from every angle — the field is populated, the coverage check
  passes, the candidate was asked — and the offer list is identical either
  way. It is the inert gate this project keeps rediscovering
  (`claude-arsenal/AGENTS.md`: "a gate that runs nothing passes everything"),
  wearing a constraint's clothes.

So each probe states one constraint and hands the filter two offers: one the
constraint must remove and one it must leave alone. Requiring both directions
is what makes the check meaningful — a field that removed everything would
pass a one-sided test while making the candidate's stated limit useless in the
opposite way.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from integral.candidate import (
    CONSTRAINT_FIELD_NAMES,
    Availability,
    CandidateConstraints,
    ConstraintField,
    EmploymentMode,
    LanguageLevel,
    Languages,
    Location,
    OfferFacts,
    PayCountry,
    Relocation,
    Salary,
    TaxCountry,
    WorkAuthorisation,
    filter_hard_constraints,
)
from integral.candidate import (
    Reach as ReachField,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "D-20.json"


@dataclass(frozen=True)
class Probe:
    """One thing a candidate can say, and the two offers that prove it bites.

    `said` is kept verbatim rather than paraphrased: the point of the check is
    that a real sentence reaches the filter, and a paraphrase is exactly the
    lossy step where "in the province of Barcelona" became a bool.
    """

    field: str
    said: str
    value: ConstraintField
    removes: OfferFacts
    keeps: OfferFacts


def _offer(offer_id: str, **facts: Any) -> OfferFacts:
    """An offer that no constraint objects to, before `facts` narrow it.

    The baseline matters: every probe's `keeps` offer must survive *its own*
    constraint, so anything that would trip a different field would make the
    probe pass for the wrong reason.
    """
    base: dict[str, Any] = {
        "offer_id": offer_id,
        "country": "ES",
        "delivery": "remote",
        "salary_stated": True,
        "salary_min": 60_000.0,
        "salary_max": 70_000.0,
        "salary_currency": "EUR",
    }
    return OfferFacts(**{**base, **facts})


#: One probe per pinned field. Every field the candidate can state something
#: into is exercised, so this is an audit of the whole pinned set rather than a
#: regression test for the one sentence that exposed it.
PROBES: tuple[Probe, ...] = (
    Probe(
        field="location",
        said=(
            "I can move, but in the province of Barcelona, or maximum to Girona or "
            "Tarragona. I want to sleep home each day."
        ),
        value=Location(
            state="stated",
            country="ES",
            accepts_onsite_in_country=True,
            commutable_regions=("Barcelona", "Girona", "Tarragona"),
        ),
        removes=_offer("onsite-sevilla", delivery="onsite", region="Sevilla"),
        keeps=_offer("onsite-girona", delivery="onsite", region="Girona"),
    ),
    Probe(
        field="languages",
        said="I get by in English, but I would not run a meeting in it.",
        value=Languages(
            state="stated", levels=(LanguageLevel(language="en", level="conversational"),)
        ),
        removes=_offer("needs-professional-en", english_level_required="professional"),
        keeps=_offer("needs-conversational-en", english_level_required="conversational"),
    ),
    Probe(
        field="relocation",
        said="I am not moving house for a job.",
        value=Relocation(state="stated", willingness="no"),
        removes=_offer("berlin", country="DE", delivery="onsite", requires_relocation=True),
        keeps=_offer("remote-de", country="DE"),
    ),
    Probe(
        field="salary",
        said="Below 55,000 gross I would not take it.",
        value=Salary(state="stated", floor=55_000.0, currency="EUR"),
        removes=_offer("pays-40k", salary_min=38_000.0, salary_max=42_000.0),
        keeps=_offer("pays-60k"),
    ),
    Probe(
        field="availability",
        said="I have two months' notice, so I cannot start before the first of June.",
        value=Availability(state="stated", earliest_start="2026-06-01", notice_period_days=60),
        removes=_offer("starts-in-april", latest_start_required="2026-04-01"),
        keeps=_offer("starts-in-july", latest_start_required="2026-07-01"),
    ),
    Probe(
        field="work_authorisation",
        said="I can work in Spain. Anywhere else would need sponsorship.",
        value=WorkAuthorisation(state="stated", authorised_countries=("ES",)),
        removes=_offer("us-onsite", country="US", delivery="onsite", requires_relocation=True),
        keeps=_offer("es-onsite", delivery="onsite"),
    ),
    Probe(
        field="employment_mode",
        said="Employed, on a payroll. I do not want to invoice as an autónomo.",
        value=EmploymentMode(state="stated", accepted=("employed",)),
        removes=_offer("contract-only", employment_modes_offered=("contracting",)),
        keeps=_offer("payroll", employment_modes_offered=("employed",)),
    ),
    Probe(
        field="pay_country",
        said="I need to be paid into a Spanish account.",
        value=PayCountry(state="stated", countries=("ES",)),
        removes=_offer("pays-from-uk", payroll_countries=("GB",)),
        keeps=_offer("pays-from-es", payroll_countries=("ES",)),
    ),
    Probe(
        field="tax_country",
        said="I am tax resident in Spain and staying that way.",
        value=TaxCountry(state="stated", country="ES"),
        removes=_offer("needs-pt-residency", tax_residency_required="PT"),
        keeps=_offer("needs-es-residency", tax_residency_required="ES"),
    ),
    Probe(
        field="reach",
        said="Remote only. I am not commuting anywhere.",
        value=ReachField(state="stated", modes=("remote",)),
        removes=_offer("hybrid-role", delivery="hybrid"),
        keeps=_offer("remote-role"),
    ),
)


def _constraints(probe: Probe) -> CandidateConstraints:
    """A candidate whose only stated field is this probe's.

    Every other field stays `unknown`, which `filter_hard_constraints` skips.
    So whatever happens to the two offers is attributable to this constraint
    and nothing else — the reason a probe's `keeps` offer surviving actually
    means something.
    """
    # `model_validate` rather than `CandidateConstraints(**{...})`: the field
    # name is chosen at runtime, and a dynamic keyword cannot be checked against
    # ten differently-typed attributes. This keeps the validation and satisfies
    # the type checker, instead of silencing it.
    return CandidateConstraints.model_validate({probe.field: probe.value})


def check(probe: Probe) -> list[str]:
    """Why this stated constraint fails to reach the filter, if it does."""
    result = filter_hard_constraints(_constraints(probe), [probe.removes, probe.keeps])
    reasons = []
    if probe.removes.offer_id in result.surviving:
        reasons.append(
            f"{probe.field} was stated and the offer it rules out survived "
            f"({probe.removes.offer_id}) — the value is recorded but filters nothing"
        )
    if probe.keeps.offer_id not in result.surviving:
        why = next(
            (r.reason for r in result.removed if r.offer_id == probe.keeps.offer_id), "no reason"
        )
        reasons.append(
            f"{probe.field} removed an offer it should allow ({probe.keeps.offer_id}): {why}"
        )
    return reasons


def probe_fields() -> list[dict[str, Any]]:
    """Every probe's reading, in pinned-field order."""
    order = {name: n for n, name in enumerate(CONSTRAINT_FIELD_NAMES)}
    readings = []
    for probe in sorted(PROBES, key=lambda p: order.get(p.field, len(order))):
        reasons = check(probe)
        readings.append(
            {
                "field": probe.field,
                "said": probe.said,
                "filters": not reasons,
                "removes": probe.removes.offer_id,
                "keeps": probe.keeps.offer_id,
                "reasons": reasons,
            }
        )
    return readings


def _unmeasured(reason: str, readings: list[dict[str, Any]]) -> dict[str, Any]:
    """The shape a reading that could not happen takes: `-1`, never `0`."""
    return {
        "unfilterable_stated_constraints": -1,
        "fields_probed": len(readings),
        "fields_pinned": len(CONSTRAINT_FIELD_NAMES),
        "unfilterable": [reason],
        "readings": readings,
    }


def measure() -> dict[str, Any]:
    """D-20's gate reading: `unfilterable_stated_constraints`."""
    try:
        readings = probe_fields()
    except Exception as exc:  # a probe that cannot be built is evidence, not a crash
        return _unmeasured(f"a probe could not be constructed: {exc}", [])

    probed = {reading["field"] for reading in readings}
    missing = [name for name in CONSTRAINT_FIELD_NAMES if name not in probed]
    if missing:
        # A pinned field with no probe is an unmeasured field, and reporting 0
        # while one exists would say "every stated constraint filters" on the
        # strength of not having asked about some of them.
        return _unmeasured(
            f"pinned field(s) with no probe: {', '.join(missing)} — nothing checked them",
            readings,
        )

    unfilterable = [r for r in readings if not r["filters"]]
    return {
        "unfilterable_stated_constraints": len(unfilterable),
        "fields_probed": len(readings),
        "fields_pinned": len(CONSTRAINT_FIELD_NAMES),
        "unfilterable": [reason for r in unfilterable for reason in r["reasons"]],
        "readings": readings,
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure and record `status/evidence/D-20.json`."""
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.stated_constraints [--check]`.

    Without arguments it writes the evidence file, so `make evidence` — whose
    module list is derived from `^def _main` — regenerates D-20's number with
    no flag to remember.
    """
    parser = argparse.ArgumentParser(
        description="D-20's gate: every stated constraint reaches the hard filter"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="measure and report only; do not write the evidence file",
    )
    parser.add_argument(
        "--write-evidence",
        nargs="?",
        const=str(DEFAULT_EVIDENCE_PATH),
        default=str(DEFAULT_EVIDENCE_PATH),
        metavar="PATH",
        help="write evidence JSON to PATH (default: status/evidence/D-20.json)",
    )
    args = parser.parse_args(argv[1:])

    measured = measure() if args.check else write_evidence(Path(args.write_evidence))
    print(json.dumps(measured, ensure_ascii=False))
    for reason in measured["unfilterable"]:
        print(reason, file=sys.stderr)
    if measured["unfilterable_stated_constraints"] == -1:
        return 3
    return 1 if measured["unfilterable_stated_constraints"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
