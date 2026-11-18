"""t-07b591f4: the profile-site logo + text kit.

The gate for this task: the 512/420 geometry and the aspect ratio are pinned, and
one command produces the folder for a fixture profile. The second-reader round on
PR #914 added the fixtures below the geometry trio — distinct names that slugify
alike, portrait aspect, off-white and JPEG margins, blank sources, transparency,
and an issuer-less certificate — each pinning one accepted finding.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from PIL import Image

from integral import profile_kit as pk
from integral.cv_store import CVMaster, load_master
from integral.identity import ProfileStore, create_profile

MASTER = Path(__file__).resolve().parent / "fixtures" / "generation" / "master.json"
# A neutral fixture identity: a real candidate's name never lands in a public test.
NAME, HANDLE = "Ada Lovelace", "ada"


def _rect(w: int, h: int, box: tuple[int, int, int, int]) -> Image.Image:
    """White w x h with a solid red rectangle at ``box`` (the logo content)."""
    im = Image.new("RGB", (w, h), (255, 255, 255))
    im.paste((200, 0, 0), box)
    return im


def _content_bbox(im: Image.Image) -> tuple[int, int, int, int]:
    from PIL import ImageChops

    bbox = ImageChops.difference(im, Image.new("RGB", im.size, (255, 255, 255))).getbbox()
    assert bbox is not None  # every fixture has visible content
    return bbox


def _store(tmp_path: Path, raw: dict[str, object] | None = None) -> ProfileStore:
    root = tmp_path / "profiles"
    create_profile(root, NAME, handle=HANDLE, language="ca")
    store = ProfileStore(root, HANDLE)
    store.write_text(MASTER.read_text() if raw is None else json.dumps(raw), "cv", "master.json")
    return store


def _entities_for(orgs: list[str]) -> list[pk.Entity]:
    master = CVMaster.model_validate(
        {"experience": [{"title": "Role", "organisation": o} for o in orgs]}
    )
    return pk.entities(master)


def test_square_canvas_and_longest_side() -> None:
    out = pk.square_logo(_rect(800, 200, (0, 0, 800, 200)))
    assert out.size == (512, 512)
    x0, y0, x1, y1 = _content_bbox(out)
    assert (x1 - x0, y1 - y0) == (420, 105)  # longest side -> 420, aspect 4:1 kept


def test_aspect_ratio_never_distorted() -> None:
    out = pk.square_logo(_rect(600, 600, (200, 250, 400, 350)))  # inner content 200x100
    x0, y0, x1, y1 = _content_bbox(out)
    w, h = x1 - x0, y1 - y0
    assert max(w, h) == 420  # margin trimmed, longest fit to 420
    assert abs(w / h - 2.0) < 0.02  # 2:1 content stays 2:1


def test_portrait_content_fits_the_tall_side() -> None:
    # Taller-than-wide content: the height is the longest side and must hit 420,
    # the width scales from it. Pins the h > w branch the geometry trio never enters.
    out = pk.square_logo(_rect(300, 900, (100, 250, 200, 650)))  # content 100x400
    x0, y0, x1, y1 = _content_bbox(out)
    assert (x1 - x0, y1 - y0) == (105, 420)  # 1:4 kept, tall side -> 420


def test_content_is_centred() -> None:
    out = pk.square_logo(_rect(400, 400, (0, 0, 400, 400)))
    x0, y0, x1, y1 = _content_bbox(out)
    assert x0 == 512 - x1 and y0 == 512 - y1  # equal margins


def test_offwhite_and_jpeg_margins_are_trimmed() -> None:
    # A near-white canvas (250,250,250) and the ringing a JPEG leaves around content
    # are both background: the 16-per-channel tolerance trims them. Zero tolerance
    # left either one untrimmed, so the content never reached 420.
    off_white = Image.new("RGB", (1000, 1000), (250, 250, 250))
    off_white.paste((200, 0, 0), (400, 450, 600, 550))  # content 200x100
    x0, y0, x1, y1 = _content_bbox(pk.square_logo(off_white))
    assert (x1 - x0, y1 - y0) == (420, 210)

    buf = io.BytesIO()
    off_white.save(buf, "JPEG", quality=75)
    buf.seek(0)
    with Image.open(buf) as jpeg:
        x0, y0, x1, y1 = _content_bbox(pk.square_logo(jpeg))
    assert max(x1 - x0, y1 - y0) == 420  # ringing trimmed, longest side still fits
    assert abs((x1 - x0) / (y1 - y0) - 2.0) < 0.05  # 2:1 survives the round trip


def test_transparency_composites_onto_white() -> None:
    # An RGBA source with a transparent margin: compositing onto white turns the
    # margin into background that then trims away, and the canvas stays white.
    im = Image.new("RGBA", (600, 600), (0, 0, 0, 0))
    im.paste((200, 0, 0, 255), (200, 200, 400, 400))  # opaque content 200x200
    out = pk.square_logo(im)
    assert out.getpixel((0, 0)) == (255, 255, 255)  # transparent -> white, not black
    x0, y0, x1, y1 = _content_bbox(out)
    assert (x1 - x0, y1 - y0) == (420, 420)


def test_blank_source_is_not_a_logo() -> None:
    # Nothing but background, by either route, is reported rather than saved as a
    # blank square that reads as a real logo on the profile.
    with pytest.raises(pk.BlankLogo):
        pk.square_logo(Image.new("RGB", (100, 100), (255, 255, 255)))
    with pytest.raises(pk.BlankLogo):
        pk.square_logo(Image.new("RGBA", (100, 100), (0, 0, 0, 0)))


def test_distinct_names_that_slugify_alike_stay_distinct() -> None:
    # slugify is lossy three ways: non-Latin collapses to "entity", long names
    # truncate to 48 chars, and punctuation maps to the same hyphen. Dedup is by
    # name, so each pair stays two entities with two folder-safe slugs.
    for a, b in [
        ("東京大学", "北京大学"),  # both -> "entity"
        ("a" * 50 + "x", "a" * 50 + "y"),  # both -> 48 "a"s
        ("C&A", "C.A."),  # both -> "c-a"
    ]:
        ents = _entities_for([a, b])
        assert len(ents) == 2
        assert len({e.slug for e in ents}) == 2  # unique folders, not one overwriting


def test_two_roles_at_one_employer_share_the_entity(tmp_path: Path) -> None:
    raw = json.loads(MASTER.read_text())
    raw["experience"].append(
        {
            "title": "Junior dev",
            "organisation": "Cintra Logistics",
            "start": "2019",
            "end": "2021",
            "description": "First role.",
            "provenance": [],
        }
    )
    store = _store(tmp_path, raw)

    ents = pk.entities(load_master(store))
    cintra = [e for e in ents if e.slug == pk.slugify("Cintra Logistics")]
    assert len(cintra) == 1 and len(cintra[0].blocks) == 2  # one entity, two text blocks


def test_command_produces_the_folder(tmp_path: Path) -> None:
    store = _store(tmp_path)

    report = pk.build_kit(store)

    # every employer + school in the fixture, deduped, reported missing (no sources dropped)
    names = {e["name"] for e in report.entities}
    assert {"Cintra Logistics", "Ajuntament de Girona", "Universitat de Girona"} <= names
    assert set(report.missing) == {e["slug"] for e in report.entities}
    assert store.exists("profile", "logos", "issuers", "cintra-logistics", "texts.md")
    texts = store.read_text("profile", "logos", "issuers", "cintra-logistics", "texts.md")
    assert "Data migration lead" in texts  # field text drawn from the store, verbatim
    assert json.loads(store.read_text("profile", "logos", "report.json"))["search_order"]


def test_issuerless_certificate_is_reported_not_dropped(tmp_path: Path) -> None:
    raw = {
        "schema_version": 1,
        "certifications": [
            {"name": "PMP", "issuer": "PMI"},
            {"name": "Some MOOC", "issuer": None},
        ],
    }
    store = _store(tmp_path, raw)

    report = pk.build_kit(store)

    assert report.no_issuer == ["Some MOOC"]  # no logo entity, but not silently dropped
    assert {e["name"] for e in report.entities} == {"PMI"}  # the issuer became the entity


def test_dropped_raster_is_squared(tmp_path: Path) -> None:
    store = _store(tmp_path)
    slug = pk.slugify("Cintra Logistics")
    drop = store.path("profile", "logos", "_sources")
    drop.mkdir(parents=True)
    _rect(800, 200, (0, 0, 800, 200)).save(drop / f"{slug}.png")

    report = pk.build_kit(store)

    assert slug in report.squared and slug not in report.missing
    with Image.open(store.path("profile", "logos", "issuers", slug, "logo.png")) as logo:
        assert logo.size == (512, 512)


def test_blank_dropped_raster_is_reported(tmp_path: Path) -> None:
    store = _store(tmp_path)
    slug = pk.slugify("Cintra Logistics")
    drop = store.path("profile", "logos", "_sources")
    drop.mkdir(parents=True)
    Image.new("RGB", (300, 300), (255, 255, 255)).save(drop / f"{slug}.png")  # all background

    report = pk.build_kit(store)

    assert slug in report.blank and slug not in report.squared
    assert not store.exists("profile", "logos", "issuers", slug, "logo.png")  # no blank square
