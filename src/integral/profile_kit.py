"""t-07b591f4: a per-entity logo + field-text kit for profile sites.

Filling a profile site (Manfred, LinkedIn and similar) by hand took a candidate
most of a session: every employer, school and certificate issuer wants one square
logo in a consistent style, plus the field texts to paste. This builds that folder
from ``cv/master.json``.

What it does, and what the gate pins:

* lists every entity that needs a logo — employers (``experience.organisation``),
  schools (``education.institution``) and certificate issuers
  (``certifications.issuer``) — and writes one ``texts.md`` per entity, each field
  drawn only from store entries, verbatim (so no content is translated or invented);
* squares any raster logo the operator has dropped into ``profile/logos/_sources/``
  onto a 512x512 white canvas, longest side fit to 420px, aspect ratio preserved,
  uniform margin trimmed first. An SVG dropped beside is kept as the vector.

What it deliberately does not do: find a logo on the network. Wikimedia Commons /
entity site / Wayback sourcing is non-deterministic and un-gatable — the runtime
(the model or the candidate) drops the raw file, and this does the mechanical
squaring, the texts and the folder. An entity with no source is reported in
``report.json``, never invented.

Also out of scope here, each needing data or a judgement this does not have:
``projects/`` for the candidate's own projects (``CVMaster`` has no projects
section); the credential URL (``Certification`` carries no such field);
"specializations, not the courses inside them" and "MOOCs only in Certificates"
(curation of what goes in which section, done upstream in intake); and writing the
texts "in the site's language" (they are copied from the store verbatim, in the
language they were stored).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from integral.cv_store import CVMaster, load_master
from integral.identity import IdentityError, ProfileStore
from integral.state_home import StateHomeRefused, ensure_outside_a_work_tree, profiles_root

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage

CANVAS = 512
FIT = 420
_WHITE = (255, 255, 255)

LOGOS = ("profile", "logos")
_SOURCES = (*LOGOS, "_sources")
_ISSUERS = "issuers"
# Pillow-readable raster suffixes we square; an .svg source is kept as the vector.
_RASTER = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff")
_SEARCH_ORDER = "Wikimedia Commons SVG, then the entity's own site, then the Wayback Machine."


def slugify(name: str) -> str:
    """Accent-folded, ascii, hyphen-joined — so 'Málaga' is 'malaga', not 'm-laga'."""
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")[:48] or "entity"


class BlankLogo(ValueError):
    """The source has no visible content once near-white background is trimmed."""


# A pixel within this of white (per channel) is background, not content. Zero
# tolerance trimmed only #FFFFFF, leaving off-white and JPEG-ringed logos untrimmed.
_WHITE_TOL = 16


def square_logo(im: PILImage, *, canvas: int = CANVAS, fit: int = FIT) -> PILImage:
    """Trim the near-white margin, fit the longest side to ``fit`` keeping aspect, and
    centre on a ``canvas`` x ``canvas`` white square. Transparency composites onto white.
    Raises ``BlankLogo`` when nothing but background remains."""
    from PIL import Image, ImageChops

    flat = Image.new("RGBA", im.size, (*_WHITE, 255))
    flat.alpha_composite(im.convert("RGBA"))
    rgb = flat.convert("RGB")
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, _WHITE)).convert("L")
    bbox = diff.point(lambda v: 255 if v > _WHITE_TOL else 0).getbbox()
    if not bbox:
        raise BlankLogo
    rgb = rgb.crop(bbox)
    w, h = rgb.size
    if w >= h:
        nw, nh = fit, max(1, round(h * fit / w))
    else:
        nw, nh = max(1, round(w * fit / h)), fit
    rgb = rgb.resize((nw, nh), Image.Resampling.LANCZOS)
    out = Image.new("RGB", (canvas, canvas), _WHITE)
    out.paste(rgb, ((canvas - nw) // 2, (canvas - nh) // 2))
    return out


def squarify_file(src: Path, dst_png: Path) -> None:
    """Square the raster at ``src`` into ``dst_png`` (PNG)."""
    from PIL import Image

    dst_png.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        square_logo(im).save(dst_png, "PNG")


@dataclass(frozen=True)
class Entity:
    """One thing that needs a logo and texts. ``rows`` are (label, value) field pairs,
    grouped so two roles at one employer share the entity and the logo."""

    name: str
    slug: str
    blocks: tuple[tuple[tuple[str, str], ...], ...]


def _dates(start: str | None, end: str | None) -> str:
    if start and end:
        return f"{start}\u2013{end}"
    return start or end or ""


def _unique_slug(base: str, used: dict[str, int]) -> str:
    """A folder-safe slug unique within this run. slugify is lossy — non-Latin names
    and long names collapse to one slug — so distinct entities would otherwise share a
    folder; suffix the repeats (``entity``, ``entity-2``) rather than overwrite."""
    n = used.get(base, 0) + 1
    used[base] = n
    return base if n == 1 else f"{base}-{n}"


def entities(master: CVMaster) -> list[Entity]:
    """Every employer, school and certificate issuer, in CV order. Deduped by the
    normalised **name**, not the slug: two distinct names that slugify alike stay two
    entities, while two roles at one employer share it."""
    order: list[str] = []
    by_key: dict[str, tuple[str, list[tuple[tuple[str, str], ...]]]] = {}

    def add(name: str, fields: list[tuple[str, str]]) -> None:
        name = name.strip()
        if not name:
            return
        key = name.casefold()
        if key not in by_key:
            by_key[key] = (name, [])
            order.append(key)
        by_key[key][1].append(tuple((k, v) for k, v in fields if v))

    for e in master.experience:
        add(
            e.organisation,
            [("title", e.title), ("dates", _dates(e.start, e.end)), ("description", e.description)],
        )
    for s in master.education:
        add(s.institution, [("qualification", s.qualification), ("dates", s.completed or "")])
    for c in master.certifications:
        if c.issuer and c.issuer.strip():
            add(c.issuer, [("certificate", c.name), ("obtained", c.obtained or "")])

    used: dict[str, int] = {}
    return [
        Entity(by_key[k][0], _unique_slug(slugify(by_key[k][0]), used), tuple(by_key[k][1]))
        for k in order
    ]


def _texts_md(entity: Entity) -> str:
    out = [f"# {entity.name}", ""]
    for i, block in enumerate(entity.blocks):
        if i:
            out.append("---")
        out += [f"- **{label}:** {value}" for label, value in block]
        out.append("")
    return "\n".join(out).rstrip() + "\n"


@dataclass
class Report:
    squared: list[str] = field(default_factory=list)
    vector_only: list[str] = field(default_factory=list)
    needs_logos_extra: list[str] = field(default_factory=list)
    blank: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    no_issuer: list[str] = field(default_factory=list)
    entities: list[dict[str, str]] = field(default_factory=list)

    def as_json(self) -> dict[str, object]:
        return {
            "search_order": _SEARCH_ORDER,
            "entities": self.entities,
            "squared": self.squared,
            "vector_only": self.vector_only,
            "needs_logos_extra": self.needs_logos_extra,
            "blank": self.blank,
            "missing": self.missing,
            "no_issuer": self.no_issuer,
        }


def _place_logo(store: ProfileStore, slug: str, report: Report) -> str:
    """Square a dropped raster into the entity folder, keep an .svg beside, or report
    the logo missing. Returns the logo status for this slug."""
    drop = store.path(*_SOURCES)
    raster = next((drop / f"{slug}{s}" for s in _RASTER if (drop / f"{slug}{s}").is_file()), None)
    svg = drop / f"{slug}.svg"
    dest_dir = store.path(*LOGOS, _ISSUERS, slug)
    if raster:
        try:
            squarify_file(raster, dest_dir / "logo.png")
        except ModuleNotFoundError:  # Pillow absent: install the `logos` extra
            report.needs_logos_extra.append(slug)
            return "needs_logos_extra"
        except BlankLogo:  # all background: a blank square is not a logo, report it
            report.blank.append(slug)
            return "blank"
        if svg.is_file():
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(svg, dest_dir / "logo.svg")
        report.squared.append(slug)
        return "squared"
    if svg.is_file():
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(svg, dest_dir / "logo.svg")
        report.vector_only.append(slug)
        return "vector_only"  # no rasteriser here; render the PNG from this vector
    report.missing.append(slug)
    return "missing"


def build_kit(store: ProfileStore) -> Report:
    """Write texts.md per entity, square any dropped logos, and write report.json."""
    master = load_master(store)
    report = Report()
    # A certificate with no issuer gets no logo entity; report it rather than drop it.
    report.no_issuer = [
        c.name for c in master.certifications if not (c.issuer and c.issuer.strip())
    ]
    for e in entities(master):
        store.write_text(_texts_md(e), *LOGOS, _ISSUERS, e.slug, "texts.md")
        status = _place_logo(store, e.slug, report)
        report.entities.append({"name": e.name, "slug": e.slug, "group": _ISSUERS, "logo": status})
    store.write_json(report.as_json(), *LOGOS, "report.json")
    return report


def render(report: Report) -> str:
    lines = [f"{len(report.entities)} entities -> profile/logos/{_ISSUERS}/"]
    if report.squared:
        lines.append(f"  squared:     {', '.join(report.squared)}")
    if report.vector_only:
        vec = ", ".join(report.vector_only)
        lines.append(f"  vector only: {vec} (render the PNG from the SVG)")
    if report.needs_logos_extra:
        ext = ", ".join(report.needs_logos_extra)
        lines.append(f"  not squared: {ext} (install the `logos` extra, then re-run)")
    if report.blank:
        lines.append(f"  blank src:   {', '.join(report.blank)} (source had no visible content)")
    if report.missing:
        lines.append(f"  no logo:     {', '.join(report.missing)}")
        lines.append(f"  find one: {_SEARCH_ORDER} Drop it in profile/logos/_sources/<slug>.<ext>.")
    if report.no_issuer:
        lines.append(
            f"  no issuer:   {len(report.no_issuer)} certificate(s) with no issuer, no logo"
        )
    return "\n".join(lines)


def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m integral.profile_kit")
    parser.add_argument("--id", required=True, dest="handle")
    parser.add_argument("--input-dir", default=None)
    parser.add_argument("--dev", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    try:
        flag = True if args.dev else None
        root = (
            ensure_outside_a_work_tree(args.input_dir, source="--input-dir", dev=flag)
            if args.input_dir
            else profiles_root(dev=flag)
        )
        store = ProfileStore(root, args.handle)
        store.identity()
        report = build_kit(store)
    except (StateHomeRefused, IdentityError) as exc:
        print(f"profile_kit: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report.as_json(), ensure_ascii=False) if args.as_json else render(report))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli(sys.argv[1:]))
