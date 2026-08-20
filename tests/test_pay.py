"""T33 — net-from-gross pay estimation, and the honesty gate over it.

The gate is `generated_tax_rules_marked_unverified == 1.0`: every generated
rule set, and every figure derived from one, has to carry a visible mark that
it is a guess rather than a checked rule — a candidate turning down an offer
on an unmarked bad net figure is a real harm (payload, owner decision
2026-08-18).
"""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from integral.pay import (
    DEFAULT_TAXES_DIR,
    Band,
    PayError,
    TaxRules,
    estimate_net_monthly,
    load_committed_rules,
    load_or_generate_rules,
    read_rules_file,
)

AS_OF = date(2026, 8, 18)


def _rules_checked_on(country: str, checked_on: str) -> TaxRules:
    return TaxRules(
        country=country,
        currency="EUR",
        source="verified",
        checked_on=checked_on,
        income_tax_bands=(
            Band(up_to=12450, rate=0.19),
            Band(up_to=None, rate=0.30),
        ),
        social_security_rate=0.0635,
        allowance=5550.0,
    )


# --- the four named honesty tests ------------------------------------------


def test_a_generated_rule_set_is_marked_generated(tmp_path: Path) -> None:
    """A rule set built for a country nobody has committed data for must
    carry `source: generated`, `generated_on`, and `generated_by` — never
    come back looking like a checked rule."""
    rules = load_or_generate_rules("ZZ", currency="EUR", taxes_dir=tmp_path, as_of=AS_OF)
    assert rules.source == "generated"
    assert rules.checked_on is None
    assert rules.generated_on == "2026-08-18"
    assert rules.generated_by


def test_a_figure_from_a_generated_rule_set_is_shown_as_approximate(tmp_path: Path) -> None:
    """Every number derived from a generated rule set must announce itself as
    approximate — the gate's whole point is that a guess is never displayed
    like a fact."""
    estimate = estimate_net_monthly(50000.0, "EUR", "ZZ", taxes_dir=tmp_path, as_of=AS_OF)
    assert estimate.approximate is True
    label = estimate.label()
    assert "generat" in label.lower() or "approx" in label.lower()


def test_a_missing_country_produces_rules_rather_than_an_error(tmp_path: Path) -> None:
    """A country the tool has never been to must not stop the search — the
    payload's rule — so a missing country produces a (marked) figure, not an
    exception."""
    estimate = estimate_net_monthly(50000.0, "EUR", "ZZ", taxes_dir=tmp_path, as_of=AS_OF)
    assert estimate.net_monthly > 0
    assert estimate.source == "generated"


def test_a_stale_verified_rule_set_is_reported(tmp_path: Path) -> None:
    """A committed rule set nobody has looked at since well before
    `STALE_AFTER_DAYS` ago must be flagged stale rather than trusted like a
    rule set checked last week."""
    path = tmp_path / "ZZ.json"
    path.write_text(
        json.dumps(_rules_checked_on("ZZ", "2023-01-01").model_dump(mode="json")),
        encoding="utf-8",
    )
    estimate = estimate_net_monthly(50000.0, "EUR", "ZZ", taxes_dir=tmp_path, as_of=AS_OF)
    assert estimate.source == "verified"
    assert estimate.stale is True
    assert "2023-01-01" in estimate.label()

    # And a rule set checked recently must not be flagged.
    fresh_path = tmp_path / "YY.json"
    fresh_path.write_text(
        json.dumps(_rules_checked_on("YY", "2026-06-01").model_dump(mode="json")),
        encoding="utf-8",
    )
    fresh_estimate = estimate_net_monthly(50000.0, "EUR", "YY", taxes_dir=tmp_path, as_of=AS_OF)
    assert fresh_estimate.stale is False


# --- reconciling generation with "unknown, never a guess" ------------------


def test_absent_country_rules_yield_unknown_not_a_guess(tmp_path: Path) -> None:
    """`load_committed_rules` — the layer that only ever answers from
    checked data — must return `None`, not a plausible-looking number, for a
    country nothing has been committed for. `load_or_generate_rules` is the
    only layer allowed to turn that absence into a figure, and it always
    marks what it produces `source: generated`; this test holds the two
    apart so generation can never quietly stand in for "we don't know"."""
    assert load_committed_rules("ZZ", taxes_dir=tmp_path) is None

    generated = load_or_generate_rules("ZZ", currency="EUR", taxes_dir=tmp_path, as_of=AS_OF)
    assert generated.source == "generated"
    # A file now exists at the same path a committed rule set would use, but
    # the committed-only lookup still refuses it — it is a persisted guess,
    # not a checked rule, and `source` is what decides that, not "a file is
    # there".
    assert load_committed_rules("ZZ", taxes_dir=tmp_path) is None


# --- the calibrated reference ----------------------------------------------


def test_net_estimate_within_ten_percent_of_reference() -> None:
    """Compared against a published reference for the committed ES rules.

    Reference: calculadornomina.es reports EUR 40,000 gross/year (single
    filer, no dependants, general regime, 12 payments) nets to
    EUR 2,523/month
    (https://calculadornomina.es/bruto-neto/40000-euros-brutos-anuales/,
    retrieved 2026-08-18). This tool's committed `taxes/ES.json` (2024/2025
    general IRPF scale + 6.35% employee social security, see its `notes`)
    should land within 10% of that reference for the same gross figure.
    """
    reference_monthly = 2523.0
    estimate = estimate_net_monthly(40000.0, "EUR", "ES", as_of=AS_OF)
    assert estimate.source == "generated"
    assert abs(estimate.net_monthly - reference_monthly) / reference_monthly <= 0.10


def test_no_shipped_rule_file_claims_a_check_nobody_performed() -> None:
    """Every rule set committed to `taxes/` is marked `generated`, because no
    person has yet checked one against a real tax code.

    This is the failure the gate cannot see. `probe_pay` measures that
    *generated* rule sets are marked, so a file mislabelled `verified` passes
    it untouched — and `verified` is exactly the label that sets
    `NetEstimate.approximate` to `False`. The rule sets shipped here were
    assembled from published summaries, and say so at length in their own
    `notes` ("Rough estimate only", "a rough approximation, not a
    payroll-accurate one"); labelling them `verified` would have shown every
    Spanish and German net figure as a checked one while the file itself said
    otherwise. A candidate turning down an offer on that number is the harm.

    When somebody does check a country against its tax code, they flip that
    file and this test with it — deliberately, which is the point.
    """
    shipped = sorted(DEFAULT_TAXES_DIR.glob("*.json"))
    assert shipped, "no committed rule sets found — the check would pass vacuously"
    for path in shipped:
        rules = read_rules_file(path)
        assert rules.source == "generated", (
            f"{path.name} claims source=verified; no person has checked it"
        )


# --- supporting mechanics ---------------------------------------------------


def test_marking_matches_source_is_enforced_by_the_schema() -> None:
    """A generated rule set with no generated_on/generated_by, or a verified
    one with no checked_on, cannot be constructed at all — the marking is a
    property of the type, not a convention a caller could forget."""
    with pytest.raises(ValidationError):
        TaxRules(
            country="ZZ",
            currency="EUR",
            source="generated",
            income_tax_bands=(Band(up_to=None, rate=0.2),),
            social_security_rate=0.1,
        )
    with pytest.raises(ValidationError):
        TaxRules(
            country="ZZ",
            currency="EUR",
            source="verified",
            income_tax_bands=(Band(up_to=None, rate=0.2),),
            social_security_rate=0.1,
        )
    with pytest.raises(ValidationError):
        # A verified rule set carrying generated_on is a contradiction too.
        TaxRules(
            country="ZZ",
            currency="EUR",
            source="verified",
            checked_on="2026-08-18",
            generated_on="2026-08-18",
            income_tax_bands=(Band(up_to=None, rate=0.2),),
            social_security_rate=0.1,
        )


def test_a_previously_generated_rule_set_is_reused_not_regenerated(tmp_path: Path) -> None:
    """`load_or_generate_rules` writes the file and uses it — a second call
    for the same country must reuse what was written, not mint a new
    generated_on date."""
    first = load_or_generate_rules("ZZ", currency="EUR", taxes_dir=tmp_path, as_of=AS_OF)
    later = date(2026, 9, 1)
    second = load_or_generate_rules("ZZ", currency="EUR", taxes_dir=tmp_path, as_of=later)
    assert second.generated_on == first.generated_on


def test_out_of_scope_is_named_in_every_estimate(tmp_path: Path) -> None:
    """Dependants, joint assessment, sub-modelled regional variation and
    pension arrangements are out of scope — the estimate must say so rather
    than implying a precision the calculation does not have."""
    estimate = estimate_net_monthly(50000.0, "EUR", "ZZ", taxes_dir=tmp_path, as_of=AS_OF)
    for term in ("dependants", "joint assessment", "regional variation", "pension"):
        assert term in estimate.out_of_scope


def test_currency_mismatch_between_offer_and_rules_is_refused(tmp_path: Path) -> None:
    """A rule set in one currency compared against an offer stated in
    another is a silent conversion nobody asked for — refused, not guessed."""
    load_or_generate_rules("ZZ", currency="EUR", taxes_dir=tmp_path, as_of=AS_OF)
    with pytest.raises(PayError):
        estimate_net_monthly(50000.0, "USD", "ZZ", taxes_dir=tmp_path, as_of=AS_OF)


def test_a_dishonest_generator_is_refused_by_the_loader(tmp_path: Path) -> None:
    """A generator that hands back `source: verified` is claiming to be a
    committed source without going through the commit — the loader must
    refuse it rather than writing it to disk as if it were checked."""

    def dishonest(country: str, region: str | None, currency: str, as_of: date) -> TaxRules:
        return TaxRules(
            country=country,
            currency=currency,
            source="verified",
            checked_on=as_of.isoformat(),
            income_tax_bands=(Band(up_to=None, rate=0.2),),
            social_security_rate=0.1,
        )

    with pytest.raises(PayError):
        load_or_generate_rules(
            "ZZ", currency="EUR", taxes_dir=tmp_path, generator=dishonest, as_of=AS_OF
        )


# --- review-finding regressions ---------------------------------------------


def test_country_and_region_are_validated_before_any_filesystem_access(tmp_path: Path) -> None:
    """A `country`/`region` that climbs out of `taxes_dir` must be refused by
    every entry point that resolves a rule path — never followed to read an
    arbitrary file, and never followed to write one outside the directory.

    Without validating in `_rule_path` itself, `country="../../etc"` would
    let `load_committed_rules` read whatever JSON file happens to sit at the
    traversed path, and `load_or_generate_rules` — with a caller-supplied
    `generator` — would *write* a generated rule set there. Both must raise
    `PayError`, not return `None` (which would misreport an attack as "no
    rules for that country") and not write anything outside `tmp_path`.
    """
    taxes_dir = tmp_path / "taxes"
    taxes_dir.mkdir()
    outside_marker = tmp_path / "escaped.json"

    for traversal_country, traversal_region in (
        ("../../etc", None),
        ("..", None),
        ("ES", "../../etc"),
        ("ES", ".."),
        ("es", None),  # lowercase must not slip past COUNTRY_PATTERN either
    ):
        with pytest.raises(PayError):
            load_committed_rules(traversal_country, traversal_region, taxes_dir=taxes_dir)
        with pytest.raises(PayError):
            load_or_generate_rules(
                traversal_country,
                traversal_region,
                currency="EUR",
                taxes_dir=taxes_dir,
                as_of=AS_OF,
            )
        with pytest.raises(PayError):
            estimate_net_monthly(
                50000.0,
                "EUR",
                traversal_country,
                traversal_region,
                taxes_dir=taxes_dir,
                as_of=AS_OF,
            )

    assert not outside_marker.exists(), "a traversal attempt wrote outside taxes_dir"
    assert list(taxes_dir.iterdir()) == [], "a traversal attempt wrote inside taxes_dir too"


def test_negative_nan_and_infinite_gross_are_refused(tmp_path: Path) -> None:
    """A gross salary that is negative, `NaN`, or infinite must never reach
    the arithmetic or be handed back as a `NetEstimate`.

    A negative gross flows into the social-security term and yields a
    negative net that reads as a plausible (if unfortunate) figure. `NaN`
    is worse: it propagates into `net_monthly` *and* into `label()`'s
    formatted string, so a candidate would see "nan EUR/mo net" next to a
    real offer. Both are refused before rules are even loaded.
    """
    for bad_gross in (-1.0, -50000.0, math.nan, math.inf, -math.inf):
        with pytest.raises(PayError):
            estimate_net_monthly(bad_gross, "EUR", "ZZ", taxes_dir=tmp_path, as_of=AS_OF)


def test_duplicate_band_bound_is_refused(tmp_path: Path) -> None:
    """A repeated `up_to` bound must be refused at construction, not silently
    accepted as a zero-width band that contributes nothing.

    `bounds != sorted(bounds)` is a non-strict check: `[10, 10, 20]` equals
    its own sorted form, so it slips past that comparison. `_apply_bands`
    would then compute a `(10, 10]` interval whose `upper <= lower`, tax
    nothing over it, and silently understate the figure — this schema is the
    trusted source for numbers shown to a candidate, so malformed data must
    fail at load, not at display.
    """
    with pytest.raises(ValidationError):
        TaxRules(
            country="ZZ",
            currency="EUR",
            source="verified",
            checked_on="2026-08-18",
            income_tax_bands=(
                Band(up_to=10_000.0, rate=0.10),
                Band(up_to=10_000.0, rate=0.20),
                Band(up_to=None, rate=0.30),
            ),
            social_security_rate=0.1,
        )

    # A descending pair must be refused for the same reason.
    with pytest.raises(ValidationError):
        TaxRules(
            country="ZZ",
            currency="EUR",
            source="verified",
            checked_on="2026-08-18",
            income_tax_bands=(
                Band(up_to=20_000.0, rate=0.10),
                Band(up_to=10_000.0, rate=0.20),
                Band(up_to=None, rate=0.30),
            ),
            social_security_rate=0.1,
        )
