"""T25 acceptance tests: the corpus covers job families beyond remote programming."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from integral.corpus import (
    MIN_ADS_PER_FAMILY,
    classify_family,
    job_family_counts,
    load_ads,
    write_family_evidence,
)

REQUIRED_FAMILIES = 6


def _ad(ad_id: str, family: str | None) -> dict[str, Any]:
    ad = {
        "id": ad_id,
        "source_url": f"https://example.invalid/{ad_id}",
        "language": "es",
        "text": "x" * 500,
    }
    if family is not None:
        ad["job_family"] = family
    return ad


def _corpus(tmp_path: Path, ads: list[dict[str, Any]]) -> Path:
    path = tmp_path / "ads.jsonl"
    path.write_text(
        "\n".join(json.dumps(ad, ensure_ascii=False) for ad in ads) + "\n", encoding="utf-8"
    )
    return path


def test_corpus_covers_at_least_six_job_families() -> None:
    counts = job_family_counts(load_ads())
    below = {family: n for family, n in counts.items() if n < MIN_ADS_PER_FAMILY}
    assert not below, f"families below the {MIN_ADS_PER_FAMILY}-ad floor: {below}"
    assert len(counts) >= REQUIRED_FAMILIES, (
        f"{len(counts)} job families, need >= {REQUIRED_FAMILIES}: {counts}"
    )


def test_every_ad_declares_a_job_family(tmp_path: Path) -> None:
    """An ad without a family is refused at load, exactly as one without a source URL is."""
    path = _corpus(tmp_path, [_ad("a", "programming"), _ad("b", None)])
    with pytest.raises(ValueError, match="declares no job_family"):
        load_ads(path)


def test_a_blank_job_family_is_refused_too(tmp_path: Path) -> None:
    """The field being present is not the check — an empty string declares nothing."""
    path = _corpus(tmp_path, [_ad("a", "programming"), _ad("b", "   ")])
    with pytest.raises(ValueError, match="declares no job_family"):
        load_ads(path)


def test_the_gate_number_counts_only_families_that_reach_the_floor(tmp_path: Path) -> None:
    """The floor has to be inside the number the gate reads.

    Six families, one of them a single ad. A `corpus_job_family_count` defined as
    "distinct families" would say 6 and the `>= 6` gate would pass on a corpus that
    teaches nothing about the sixth family. This pins the definition that cannot.
    """
    ads = [
        _ad(f"{family}-{i}", family)
        for family in ("programming", "hospitality", "healthcare", "trades", "retail")
        for i in range(MIN_ADS_PER_FAMILY)
    ]
    ads.append(_ad("teaching-0", "teaching"))
    measured = write_family_evidence(tmp_path / "T25.json", load_ads(_corpus(tmp_path, ads)))

    assert len(measured["job_family_counts"]) == 6
    assert measured["corpus_job_family_count"] == 5
    assert measured["families_below_floor"] == {"teaching": 1}


def test_the_gate_number_rises_when_the_short_family_reaches_the_floor(tmp_path: Path) -> None:
    """The companion to the test above: the number is not simply stuck one short."""
    ads = [
        _ad(f"{family}-{i}", family)
        for family in ("programming", "hospitality", "healthcare", "trades", "retail", "teaching")
        for i in range(MIN_ADS_PER_FAMILY)
    ]
    measured = write_family_evidence(tmp_path / "T25.json", load_ads(_corpus(tmp_path, ads)))

    assert measured["corpus_job_family_count"] == 6
    assert measured["families_below_floor"] == {}


# --------------------------------------------------------------- the classifier

# Every ad's family comes from its title, so what `classify_family` refuses is what
# decides whether a family count means anything. Each case below is a mistake the
# first collection run actually made.


@pytest.mark.parametrize(
    ("title", "family"),
    [
        ("CAMBRER/A DE SALA", "hospitality"),
        ("Venedor/a de botiga", "retail"),
        ("Encarregat/da de botiga", "retail"),
        ("Tècnic/a en emergències sanitàries", "healthcare"),
        ("INSTAL·LADORS/ES ELECTRICISTES-LAMPISTES", "trades"),
        ("Professor/a d'anglès", "teaching"),
        ("ADMINISTRATIU/IVA DE COMPTABILITAT", "administrative"),
    ],
)
def test_a_gendered_title_still_names_its_family(title: str, family: str) -> None:
    """Catalan and Spanish ads are titled "Venedor/a", "Encarregat/da", "Tècnic/a".

    A pattern needing a following word (`venedor... de botiga`) has to let the gender
    suffix through. Before it did, every such title fell through unclassified and the
    retail sweep returned 11 ads against a floor of 15.
    """
    assert classify_family(title) == family


@pytest.mark.parametrize(
    "title",
    [
        "Borsa de treball de places de Tècnic superior Professor",
        "1 plaça d'Auxiliar administratiu  CIDO",
        "Convocatòria de 3 places de mestre",
        "Proceso selectivo para 2 plazas de auxiliar",
    ],
)
def test_a_recruitment_bulletin_is_not_a_job_advert(title: str) -> None:
    """The public employment service publishes hiring bulletins alongside real ads.

    They are near-identical administrative boilerplate: 12 of the first teaching
    sweep's 18 were one of these, which would have filled the family with a form no
    candidate is ever shown while the count read a healthy 18.
    """
    assert classify_family(title) is None


def test_a_title_naming_two_families_is_left_unclassified() -> None:
    """Guessing between two families teaches the wrong vocabulary for both, so the ad
    is dropped instead. School-canteen posts really are advertised like this."""
    assert classify_family("Cuiner/a i monitor/a de menjador escolar") is None
    assert classify_family("Recepcionista d'hotel i auxiliar administratiu") is None


def test_a_programming_title_names_no_family_here() -> None:
    """The family patterns must not swallow the slice T4b already collected."""
    assert classify_family("Programador/a Python Senior") is None
    assert classify_family("Comercial de vendes") is None
