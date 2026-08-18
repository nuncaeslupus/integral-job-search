"""Net-from-gross pay estimation, per country, generated when absent (T33).

Comparing a Spanish offer and a German one on gross salary is exactly the
comparison that misleads (payload, owner decision 2026-08-18; spec-v2-steps
§"Establish where they live" and §"The shape of an offer on screen"). A
candidate needs a rough **monthly net**, in their own currency, for every
offer — not two gross numbers that are not directly comparable at all. The
formula this module implements is registered at
`docs/METHODS.md#45-net-from-gross-pay-estimation`.

Two rule sources, tried in order (`load_or_generate_rules`):

1. **Committed** — `taxes/<COUNTRY>.json` (or `<COUNTRY>-<REGION>.json`),
   checked by a person against a real tax code, `source: verified`. **No rule
   set shipped in this repository is `verified` yet**: the ES and DE files
   were assembled from published summaries, not checked against the tax code,
   so they are marked `generated` and every figure from them reads as
   approximate. `verified` is a claim about a person having done the work, and
   nothing else may wear it — see `probe_pay`'s shipped-file check.
2. **Generated** — when a country is absent, the tool works out a rough rule
   set, writes it to the same directory, and uses it, `source: generated`. A
   search must never stop because we have not been to that country before.

**The gate is about honesty, not accuracy.** A generated rule set is a
model's best recollection of a tax code — it may be wrong, out of date, or
subtly incomplete, and a candidate turning down an offer on a bad net figure
is a real harm. So `TaxRules._marking_matches_source` makes the two sources
mutually exclusive *by construction*: a `generated` rule set cannot be built
without `generated_on`/`generated_by`, and cannot carry `checked_on` — there
is no way to hand back an unmarked guess. `NetEstimate.approximate` and
`.label()` carry that mark through to every number this module produces, so
nothing derived from a generated rule set is ever shown like a checked one.

Committed rules also go stale (`is_stale`): rates change every year, and a
rule set nobody has looked at since before `STALE_AFTER_DAYS` ago should say
so rather than being trusted like a fresh one.

**Out of scope**, named rather than silently ignored (`OUT_OF_SCOPE_NOTE`):
dependants, joint assessment, regional variation below the level modelled,
and pension arrangements. Every `NetEstimate` carries the notice so a caller
cannot show the number without it.

**No model is called here.** T33's payload is explicit that "generation"
means the mechanism and the marking, not a live call — `default_generator`
is stdlib arithmetic behind a loudly-labelled placeholder, wired up exactly
like a real generator would be. `RuleGenerator` is the seam a real one plugs
into later, via the `generator=` parameter, without touching any caller.
"""

from __future__ import annotations

import json
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TAXES_DIR = _REPO_ROOT / "taxes"
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T33.json"

COUNTRY_PATTERN = r"^[A-Z]{2}$"
CURRENCY_PATTERN = r"^[A-Z]{3}$"
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"

# A committed rule set is trusted as fresh for this many days after its
# `checked_on` date. Chosen because rates change every year (payload) — a
# rule set nobody has looked at since before this window should say so,
# rather than being shown next to a rule set checked last week with no
# visible difference.
STALE_AFTER_DAYS = 365

# Named rather than silently dropped: personal circumstances that move a real
# net figure a lot, and that this module never asks about or models.
OUT_OF_SCOPE: tuple[str, ...] = (
    "dependants",
    "joint assessment",
    "regional variation below the level this rule set models",
    "pension arrangements",
)
OUT_OF_SCOPE_NOTE = (
    "This estimate ignores " + ", ".join(OUT_OF_SCOPE) + " — treat it as a rough "
    "monthly figure, not a payslip."
)

Source = Literal["verified", "generated"]


class PayError(Exception):
    """A tax-rule file, or a rule set built in memory, does not fit T33's schema."""


class Strict(BaseModel):
    """Unknown keys are an error everywhere in this schema — see `dimensions.Strict`.

    A typo'd field in a committed rule file must fail loudly rather than be
    silently ignored while the number it was meant to change stays wrong.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


class Band(Strict):
    """One marginal-rate slice: `(previous band's up_to, up_to]` at `rate`.

    `up_to` is `None` on exactly the last band — the open-ended top slice —
    so a schedule with no ceiling still has a definite shape instead of an
    implicit "whatever is left over" the model would have to special-case.
    """

    up_to: float | None = Field(default=None, gt=0)
    rate: float = Field(ge=0.0, le=1.0)


class TaxRules(Strict):
    """One country's (or region's) net-from-gross rule set — committed or generated.

    The `source` split is the whole point of T33: `verified` rules were
    checked by a person against a real tax code and carry `checked_on`;
    `generated` rules are a model's best recollection and carry
    `generated_on` / `generated_by` instead. `_marking_matches_source` makes
    the two mutually exclusive by construction, not by convention — a rule
    set cannot be built at all with one source's fields under the other
    source's label, which is what makes
    `generated_tax_rules_marked_unverified` a property of the schema rather
    than a hope about every call site that builds one.
    """

    country: str = Field(pattern=COUNTRY_PATTERN)
    region: str | None = None
    currency: str = Field(pattern=CURRENCY_PATTERN)
    source: Source
    checked_on: str | None = Field(default=None, pattern=DATE_PATTERN)
    generated_on: str | None = Field(default=None, pattern=DATE_PATTERN)
    generated_by: str | None = None
    income_tax_bands: tuple[Band, ...] = Field(min_length=1)
    social_security_rate: float = Field(ge=0.0, le=1.0)
    social_security_cap: float | None = Field(default=None, gt=0)
    # The "obvious allowance" the payload asks for — a flat amount deducted
    # from gross before the bands apply (e.g. Spain's mínimo del
    # contribuyente). Country-specific nuance beyond a flat figure is out of
    # scope; see the module docstring and each committed file's `notes`.
    allowance: float = Field(default=0.0, ge=0.0)
    notes: str = ""

    @model_validator(mode="after")
    def _marking_matches_source(self) -> TaxRules:
        if self.source == "verified":
            if self.checked_on is None:
                raise ValueError("a verified rule set must carry checked_on")
            if self.generated_on is not None or self.generated_by is not None:
                raise ValueError(
                    "a verified rule set must not carry generated_on/generated_by — "
                    "that would let a checked rule set read as a guess"
                )
        else:
            if self.generated_on is None or not self.generated_by:
                raise ValueError(
                    "a generated rule set must carry generated_on and generated_by — "
                    "an unmarked guess is exactly what T33's gate exists to catch"
                )
            if self.checked_on is not None:
                raise ValueError(
                    "a generated rule set must not carry checked_on — nobody checked it"
                )
        return self

    @model_validator(mode="after")
    def _bands_are_ordered_and_end_open(self) -> TaxRules:
        bands = self.income_tax_bands
        if any(band.up_to is None for band in bands[:-1]):
            raise ValueError("only the last income tax band may be open-ended (up_to=None)")
        if bands[-1].up_to is not None:
            raise ValueError("the last income tax band must be open-ended (up_to=None)")
        # The `is not None` filter drops nothing here — the check above
        # already raised if any of these were `None` — it exists only to
        # narrow the type for mypy without duplicating the validation.
        bounds: list[float] = [band.up_to for band in bands[:-1] if band.up_to is not None]
        if bounds != sorted(bounds):
            raise ValueError("income tax bands must be in ascending order of up_to")
        return self


def is_stale(rules: TaxRules, as_of: date) -> bool:
    """Whether a *verified* rule set is older than `STALE_AFTER_DAYS`.

    Staleness is a property of a checked rule set going out of date, not of a
    generated one — a generated rule set is never "fresh" in the first
    place, so it is always shown as approximate rather than as newly stale;
    see `NetEstimate.label`.
    """
    if rules.source != "verified" or rules.checked_on is None:
        return False
    checked = date.fromisoformat(rules.checked_on)
    return (as_of - checked).days > STALE_AFTER_DAYS


# ---------------------------------------------------------------------------
# generation — the seam, and a clearly-labelled default that calls no model


RuleGenerator = Callable[[str, "str | None", str, date], TaxRules]


def default_generator(country: str, region: str | None, currency: str, as_of: date) -> TaxRules:
    """The out-of-the-box generator: stdlib maths behind a loud placeholder.

    T33's payload is explicit that generation here is about the *mechanism
    and the marking*, not about calling a model — "do not call a model" — so
    this default never reaches out anywhere. It is wired up exactly like a
    real generator would be, so one can be swapped in later via
    `load_or_generate_rules(..., generator=...)` without touching any caller.
    """
    where = f"{country}/{region}" if region else country
    return TaxRules(
        country=country,
        region=region,
        currency=currency,
        source="generated",
        generated_on=as_of.isoformat(),
        generated_by="jobsearch.pay.default_generator (flat placeholder — no model was called)",
        income_tax_bands=(Band(up_to=None, rate=0.25),),
        social_security_rate=0.10,
        notes=(
            f"No committed tax rules exist yet for {where}. This is a flat 25% income "
            "tax / 10% social security placeholder standing in until a real rule set "
            "is generated or committed — treat any figure from it as very rough."
        ),
    )


# ---------------------------------------------------------------------------
# storage — committed rules on disk, generated ones written beside them


def _rule_path(taxes_dir: Path, country: str, region: str | None) -> Path:
    name = f"{country}-{region}.json" if region else f"{country}.json"
    return taxes_dir / name


def read_rules_file(path: Path) -> TaxRules:
    """Read one rule file, turning every failure into `PayError` — a loader
    raises; `estimate_net_monthly` and friends are what report."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PayError(f"{path}: cannot be read: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PayError(f"{path}: not valid JSON: {exc}") from exc
    try:
        return TaxRules.model_validate(raw)
    except ValidationError as exc:
        raise PayError(f"{path}: {exc}") from exc


def load_committed_rules(
    country: str,
    region: str | None = None,
    *,
    taxes_dir: Path = DEFAULT_TAXES_DIR,
) -> TaxRules | None:
    """The rules for a country/region *if they are committed* — `None`, never
    a guess, when they are not.

    This is the layer `test_absent_country_rules_yield_unknown_not_a_guess`
    holds to a strict `None`. Only `load_or_generate_rules` is allowed to
    turn an absence into a number, and everything it produces that way
    carries `source: generated` — never something indistinguishable from
    this function's answer. A file on disk that was itself generated by a
    previous run does not count as committed either: `source` decides, not
    "a file happens to exist at this path".
    """
    path = _rule_path(taxes_dir, country, region)
    if not path.exists() and region is not None:
        path = _rule_path(taxes_dir, country, None)
    if not path.exists():
        return None
    rules = read_rules_file(path)
    return rules if rules.source == "verified" else None


def load_or_generate_rules(
    country: str,
    region: str | None = None,
    *,
    currency: str,
    taxes_dir: Path = DEFAULT_TAXES_DIR,
    generator: RuleGenerator = default_generator,
    as_of: date | None = None,
) -> TaxRules:
    """Committed rules first; a generated, marked, persisted rule set when
    the country/region is absent.

    Never fails on a missing country — the payload's rule: "a search should
    never stop because we have not been to that country before". A
    previously generated file for the same country/region is reused rather
    than re-generated (and re-dated) on every call, which is what "writes
    the file, and uses it" means literally.
    """
    as_of = as_of or date.today()
    committed = load_committed_rules(country, region, taxes_dir=taxes_dir)
    if committed is not None:
        return committed

    path = _rule_path(taxes_dir, country, region)
    if path.exists():
        existing = read_rules_file(path)
        if existing.source == "generated":
            return existing

    rules = generator(country, region, currency, as_of)
    if rules.source != "generated":
        # A generator that hands back anything else is claiming to be a
        # committed source without having gone through the commit — refused,
        # not silently trusted and written to disk as if it were checked.
        raise PayError(
            f"rule generator for {country} returned source={rules.source!r}, "
            "not 'generated' — a generator may never claim to be verified"
        )
    taxes_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(rules.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return rules


# ---------------------------------------------------------------------------
# the calculation


def _apply_bands(taxable: float, bands: Sequence[Band]) -> float:
    """Progressive marginal tax over ordered bands, each covering
    `(previous up_to, up_to]`."""
    tax = 0.0
    lower = 0.0
    for band in bands:
        upper = taxable if band.up_to is None else min(band.up_to, taxable)
        if upper > lower:
            tax += (upper - lower) * band.rate
        lower = taxable if band.up_to is None else band.up_to
        if band.up_to is None or lower >= taxable:
            break
    return tax


def compute_net_annual(gross_annual: float, rules: TaxRules) -> float:
    """Gross minus progressive income tax on `(gross - allowance)` minus flat,
    capped social security on gross. Documented at
    `docs/METHODS.md#45-net-from-gross-pay-estimation`."""
    taxable = max(gross_annual - rules.allowance, 0.0)
    income_tax = _apply_bands(taxable, rules.income_tax_bands)
    ss_base = gross_annual
    if rules.social_security_cap is not None:
        ss_base = min(ss_base, rules.social_security_cap)
    social_security = ss_base * rules.social_security_rate
    return gross_annual - income_tax - social_security


@dataclass(frozen=True)
class NetEstimate:
    """One offer's rough monthly net, and everything needed to display it
    honestly rather than as a bare, precise-looking number."""

    country: str
    region: str | None
    currency: str
    gross_annual: float
    net_annual: float
    net_monthly: float
    source: Source
    # True whenever the underlying rule set is a guess — never merely a hope
    # that the caller remembers to check `source` itself before displaying.
    approximate: bool
    checked_on: str | None
    generated_on: str | None
    generated_by: str | None
    stale: bool
    out_of_scope: str

    def label(self) -> str:
        """The one line a caller shows next to the figure — never a bare number.

        §"The shape of an offer on screen is specified, not improvised":
        the bullets a candidate reads must say what the number is and is
        not, in plain words, every time it is shown.
        """
        figure = f"~{self.net_monthly:,.0f} {self.currency}/mo net"
        if self.source == "generated":
            return (
                f"{figure} (APPROXIMATE, generated {self.generated_on} by "
                f"{self.generated_by} — not a checked rule)"
            )
        if self.stale:
            return f"{figure} (rates last checked {self.checked_on} — may be out of date)"
        return f"{figure} (rates checked {self.checked_on})"


def estimate_net_monthly(
    gross_annual: float,
    currency: str,
    country: str,
    region: str | None = None,
    *,
    taxes_dir: Path = DEFAULT_TAXES_DIR,
    generator: RuleGenerator = default_generator,
    as_of: date | None = None,
) -> NetEstimate:
    """A rough monthly net for one offer, in the candidate's own currency.

    Looks up committed rules, generates and persists them when absent
    (`load_or_generate_rules`), computes the figure, and returns it already
    carrying every mark `label()` needs — a caller cannot accidentally show
    the number without also being handed whether it is approximate or stale.
    """
    as_of = as_of or date.today()
    rules = load_or_generate_rules(
        country, region, currency=currency, taxes_dir=taxes_dir, generator=generator, as_of=as_of
    )
    if rules.currency != currency:
        where = f"{country}/{region}" if region else country
        raise PayError(
            f"{where} tax rules are in {rules.currency}, but the offer is in {currency} — "
            "currency conversion is out of scope for T33"
        )
    net_annual = compute_net_annual(gross_annual, rules)
    return NetEstimate(
        country=country,
        region=region,
        currency=currency,
        gross_annual=gross_annual,
        net_annual=net_annual,
        net_monthly=net_annual / 12,
        source=rules.source,
        approximate=(rules.source == "generated"),
        checked_on=rules.checked_on,
        generated_on=rules.generated_on,
        generated_by=rules.generated_by,
        stale=is_stale(rules, as_of),
        out_of_scope=OUT_OF_SCOPE_NOTE,
    )


# ---------------------------------------------------------------------------
# the gate


def _dishonest_generator(country: str, region: str | None, currency: str, as_of: date) -> TaxRules:
    """A generator that claims to be verified — must be refused, not trusted."""
    return TaxRules(
        country=country,
        region=region,
        currency=currency,
        source="verified",
        checked_on=as_of.isoformat(),
        income_tax_bands=(Band(up_to=None, rate=0.2),),
        social_security_rate=0.1,
    )


def _is_refused(error: type[Exception], attempt: Callable[[], Any]) -> bool:
    """Run an adversarial construction; `True` only if it raised `error` —
    mirrors `offers._expect_rejected`, inverted to a boolean `check()` wants."""
    try:
        attempt()
    except error:
        return True
    return False


def probe_pay(taxes_dir: Path) -> dict[str, Any]:
    """Generate rules for several absent countries and check every one is
    marked, every figure derived from one reads as approximate, and the mark
    survives being written to disk and read back — the leak this gate exists
    to catch is a generated rule set that looks committed on the next run.

    Adversarial in the same spirit as `candidate.probe_hard_filter`: it also
    tries to sneak an unmarked or mismarked rule set past the schema and the
    loader, and checks that both refuse it rather than accepting it quietly.
    """
    as_of = date(2026, 8, 18)
    checked = 0
    unmarked: list[str] = []

    def check(condition: bool, message: str) -> None:
        nonlocal checked
        checked += 1
        if not condition:
            unmarked.append(message)

    for country in ("IT", "PT", "NL"):
        rules = load_or_generate_rules(country, currency="EUR", taxes_dir=taxes_dir, as_of=as_of)
        estimate = estimate_net_monthly(
            50000.0, "EUR", country, taxes_dir=taxes_dir, as_of=as_of
        )

        check(rules.source == "generated", f"{country}: rule set was not marked source=generated")
        check(
            rules.checked_on is None,
            f"{country}: a generated rule set carries a verified checked_on date",
        )
        check(
            bool(rules.generated_on) and bool(rules.generated_by),
            f"{country}: generated rule set is missing generated_on/generated_by",
        )
        check(
            estimate.approximate,
            f"{country}: a figure from a generated rule set was not flagged approximate",
        )
        label = estimate.label()
        check(
            "generat" in label.lower() or "approx" in label.lower(),
            f"{country}: the displayed figure does not read as approximate/generated: {label!r}",
        )

        # The mark must survive a write and a re-read — a generated rule set
        # that looks committed on reload is exactly the leak T33 exists to
        # prevent.
        reloaded = read_rules_file(_rule_path(taxes_dir, country, None))
        check(
            reloaded.source == "generated",
            f"{country}: the generated mark did not survive being written and reread",
        )

    # The shipped rule sets themselves. Everything above runs in a temporary
    # directory, so a file committed to `taxes/` under a `verified` label it
    # has not earned passes every check above untouched — and `verified` is
    # precisely the label that clears `NetEstimate.approximate`. Nobody has
    # checked one of these against a tax code, so none of them may claim it.
    for shipped in sorted(DEFAULT_TAXES_DIR.glob("*.json")):
        check(
            read_rules_file(shipped).source == "generated",
            f"{shipped.name}: shipped rule set claims source=verified, but no "
            "person has checked it against a tax code",
        )

    # A generator that tries to hand back "verified" must be refused, not
    # silently written to disk and used as if it were checked.
    check(
        _is_refused(
            PayError,
            lambda: load_or_generate_rules(
                "ZZ",
                currency="EUR",
                taxes_dir=taxes_dir,
                generator=_dishonest_generator,
                as_of=as_of,
            ),
        ),
        "a generator claiming 'verified' for an ungenerated country was accepted",
    )

    # The schema itself, not just the loader, must refuse an unmarked guess:
    # a generated rule set with no generated_on/generated_by cannot be built
    # at all.
    check(
        _is_refused(
            ValidationError,
            lambda: TaxRules(
                country="ZZ",
                currency="EUR",
                source="generated",
                income_tax_bands=(Band(up_to=None, rate=0.2),),
                social_security_rate=0.1,
            ),
        ),
        "a generated rule set with no generated_on/generated_by was accepted",
    )

    # The flag is not stuck on: a verified rule set stays verified.
    verified = TaxRules(
        country="XV",
        currency="EUR",
        source="verified",
        checked_on=as_of.isoformat(),
        income_tax_bands=(Band(up_to=None, rate=0.2),),
        social_security_rate=0.1,
    )
    check(verified.source == "verified", "a verified rule set round-tripped as something else")

    return {
        "generated_tax_rules_marked_unverified": (
            (checked - len(unmarked)) / checked if checked else 0.0
        ),
        "checks_run": checked,
        "unmarked": unmarked,
    }


MINIMUM_CHECKS = 10


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure `generated_tax_rules_marked_unverified` in a throwaway
    directory and record it."""
    with tempfile.TemporaryDirectory(prefix="jobsearch-t33-") as tmp:
        measured = probe_pay(Path(tmp) / "taxes")
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return measured


def _main(argv: list[str]) -> int:
    """`python -m jobsearch.pay [path]` → T33's gate evidence."""
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["checks_run"] < MINIMUM_CHECKS:
        print(
            f"only {measured['checks_run']} checks were run (floor {MINIMUM_CHECKS}) — "
            "a clean fraction over nothing is not a measurement",
            file=sys.stderr,
        )
        return 3
    for issue in measured["unmarked"]:
        print(issue, file=sys.stderr)
    return 1 if measured["unmarked"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
