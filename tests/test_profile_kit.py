"""t-07b591f4: the profile-site logo + text kit.

The gate for this task: the 512/420 geometry and the aspect ratio are pinned, and
one command produces the folder for a fixture profile.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from integral import profile_kit as pk
from integral.cv_store import load_master
from integral.identity import ProfileStore, create_profile

MASTER = Path(__file__).resolve().parent / "fixtures" / "generation" / "master.json"


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


def test_content_is_centred() -> None:
    out = pk.square_logo(_rect(400, 400, (0, 0, 400, 400)))
    x0, y0, x1, y1 = _content_bbox(out)
    assert x0 == 512 - x1 and y0 == 512 - y1  # equal margins


def test_command_produces_the_folder(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    create_profile(root, "Vero", handle="vero", language="ca")
    store = ProfileStore(root, "vero")
    store.write_text(MASTER.read_text(), "cv", "master.json")

    report = pk.build_kit(store)

    # every employer + school in the fixture, deduped, reported missing (no sources dropped)
    names = {e["name"] for e in report.entities}
    assert {"Cintra Logistics", "Ajuntament de Girona", "Universitat de Girona"} <= names
    assert set(report.missing) == {e["slug"] for e in report.entities}
    assert store.exists("profile", "logos", "issuers", "cintra-logistics", "texts.md")
    texts = store.read_text("profile", "logos", "issuers", "cintra-logistics", "texts.md")
    assert "Data migration lead" in texts  # field text drawn from the store, verbatim
    assert json.loads(store.read_text("profile", "logos", "report.json"))["search_order"]


def test_dropped_raster_is_squared(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    create_profile(root, "Vero", handle="vero", language="ca")
    store = ProfileStore(root, "vero")
    store.write_text(MASTER.read_text(), "cv", "master.json")
    slug = pk.slugify("Cintra Logistics")
    drop = store.path("profile", "logos", "_sources")
    drop.mkdir(parents=True)
    _rect(800, 200, (0, 0, 800, 200)).save(drop / f"{slug}.png")

    report = pk.build_kit(store)

    assert slug in report.squared and slug not in report.missing
    with Image.open(store.path("profile", "logos", "issuers", slug, "logo.png")) as logo:
        assert logo.size == (512, 512)


def test_two_roles_at_one_employer_share_the_entity(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    create_profile(root, "Vero", handle="vero", language="ca")
    store = ProfileStore(root, "vero")
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
    store.write_json(raw, "cv", "master.json")

    ents = pk.entities(load_master(store))
    cintra = [e for e in ents if e.slug == pk.slugify("Cintra Logistics")]
    assert len(cintra) == 1 and len(cintra[0].blocks) == 2  # one entity, two text blocks
