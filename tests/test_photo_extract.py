"""T183 — the candidate's photo comes out of their own CV; none is ever asked for.

Fixture PDFs are written byte by byte (uncompressed RGB image XObjects), so no
imaging library is needed and every image's pixel size is known by construction.
The spec is the task file: largest raster on page 1, short side >= 200px,
aspect in [0.6, 1.4]; no photo is a normal outcome.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from integral import cv_store
from integral.identity import ProfileStore, create_profile
from integral.photo_extract import _Listed, choose, extract_photo

pytestmark = pytest.mark.skipif(shutil.which("pdfimages") is None, reason="poppler not installed")

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
STENCIL = -1  # third tuple element: an /ImageMask stencil rather than a picture


def _pdf(pages: list[list[tuple[int, int, int]]]) -> bytes:
    """Pages of (width, height, smask_side) images; 0 = no soft mask, STENCIL = ImageMask."""
    objs: list[bytes] = []

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)

    catalog = add(b"")
    pages_obj = add(b"")
    page_ids = []
    for images in pages:
        xobjs, drawing = [], b""
        for n, (w, h, smask_side) in enumerate(images):
            if smask_side == STENCIL:
                bits = bytes([0xAA]) * (((w + 7) // 8) * h)
                oid = add(
                    b"<< /Type /XObject /Subtype /Image /Width %d /Height %d "
                    b"/ImageMask true /BitsPerComponent 1 /Length %d >>\nstream\n"
                    % (w, h, len(bits))
                    + bits
                    + b"\nendstream"
                )
                xobjs.append(b"/Im%d %d 0 R" % (n, oid))
                drawing += b"q 100 0 0 100 10 10 cm /Im%d Do Q\n" % n
                continue
            data = bytes([(37 * n) % 256, 90, 160]) * (w * h)
            smask_ref = b""
            if smask_side:
                mask = bytes([200]) * (smask_side * smask_side)
                mask_id = add(
                    b"<< /Type /XObject /Subtype /Image /Width %d /Height %d "
                    b"/ColorSpace /DeviceGray /BitsPerComponent 8 /Length %d >>\nstream\n"
                    % (smask_side, smask_side, len(mask))
                    + mask
                    + b"\nendstream"
                )
                smask_ref = b"/SMask %d 0 R " % mask_id
            oid = add(
                b"<< /Type /XObject /Subtype /Image /Width %d /Height %d "
                b"/ColorSpace /DeviceRGB /BitsPerComponent 8 %s/Length %d >>\nstream\n"
                % (w, h, smask_ref, len(data))
                + data
                + b"\nendstream"
            )
            xobjs.append(b"/Im%d %d 0 R" % (n, oid))
            drawing += b"q 100 0 0 100 10 10 cm /Im%d Do Q\n" % n
        content = add(b"<< /Length %d >>\nstream\n" % len(drawing) + drawing + b"endstream")
        page_ids.append(
            add(
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents %d 0 R "
                b"/Resources << /XObject << %s >> >> >>" % (content, b" ".join(xobjs))
            )
        )
    objs[catalog - 1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    kids = b" ".join(b"%d 0 R" % i for i in page_ids)
    objs[pages_obj - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(page_ids))
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out


def _write(tmp_path: Path, name: str, pages: list[list[tuple[int, int, int]]]) -> Path:
    path = tmp_path / name
    path.write_bytes(_pdf(pages))
    return path


def test_photo_is_extracted_from_a_source_cv(tmp_path: Path) -> None:
    # a small icon, the photo, and a wide banner smaller in area than the photo
    cv = _write(tmp_path, "cv.pdf", [[(32, 32, 0), (240, 300, 0), (400, 60, 0)]])
    photo = extract_photo(cv)
    assert photo is not None and photo.startswith(PNG_MAGIC)
    # the extracted file is the 240x300 one: PNG IHDR width/height
    assert int.from_bytes(photo[16:20], "big") == 240
    assert int.from_bytes(photo[20:24], "big") == 300


def test_a_logo_only_pdf_extracts_nothing(tmp_path: Path) -> None:
    wide_logo = _write(tmp_path, "wide.pdf", [[(600, 120, 0)]])
    tiny_logo = _write(tmp_path, "tiny.pdf", [[(150, 150, 0)]])
    assert extract_photo(wide_logo) is None
    assert extract_photo(tiny_logo) is None


def test_no_images_and_unreadable_pdf_are_none_not_errors(tmp_path: Path) -> None:
    assert extract_photo(_write(tmp_path, "text.pdf", [[]])) is None
    junk = tmp_path / "junk.pdf"
    junk.write_bytes(b"not a pdf")
    assert extract_photo(junk) is None
    assert extract_photo(tmp_path / "missing.pdf") is None


def test_a_bigger_off_shape_image_beats_a_small_square_icon(tmp_path: Path) -> None:
    # fail-closed: the banner is largest and fails the aspect test, so the 210px
    # icon must NOT be promoted to "the photo".
    cv = _write(tmp_path, "cv.pdf", [[(210, 210, 0), (900, 300, 0)]])
    assert extract_photo(cv) is None


def test_only_page_one_is_considered(tmp_path: Path) -> None:
    cv = _write(tmp_path, "cv.pdf", [[], [(240, 300, 0)]])
    assert extract_photo(cv) is None


def test_a_soft_mask_is_not_a_photo_and_does_not_shift_the_file(tmp_path: Path) -> None:
    # the photo's soft mask is bigger than the photo and listed after it; the photo
    # is still the image taken, and the mask is never returned.
    cv = _write(tmp_path, "cv.pdf", [[(240, 300, 500)]])
    photo = extract_photo(cv)
    assert photo is not None
    assert int.from_bytes(photo[16:20], "big") == 240


def _width(png: bytes | None) -> int:
    assert png is not None and png.startswith(PNG_MAGIC)
    return int.from_bytes(png[16:20], "big")


def test_a_stencil_listed_before_the_photo_does_not_shift_the_file(tmp_path: Path) -> None:
    # pdfimages numbers output files by listing row, stencils included.
    cv = _write(tmp_path, "cv.pdf", [[(600, 600, STENCIL), (240, 300, 0)]])
    png = extract_photo(cv)
    assert _width(png) == 240
    assert int.from_bytes(png[20:24], "big") == 300  # type: ignore[index]


def test_a_soft_mask_listed_before_the_photo_does_not_shift_the_file(tmp_path: Path) -> None:
    # a small image with its own soft mask lists two rows (image, smask) first.
    cv = _write(tmp_path, "cv.pdf", [[(50, 50, 50), (240, 300, 0)]])
    png = extract_photo(cv)
    assert _width(png) == 240
    assert int.from_bytes(png[20:24], "big") == 300  # type: ignore[index]


def test_an_oserror_during_extraction_is_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cv = _write(tmp_path, "cv.pdf", [[(240, 300, 0)]])

    def boom(*_a: object, **_k: object) -> None:
        raise OSError("no space left on device")

    monkeypatch.setattr("integral.photo_extract.tempfile.TemporaryDirectory", boom)
    assert extract_photo(cv) is None


def test_a_filename_starting_with_a_dash_is_a_path_not_an_option(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write(tmp_path, "-j", [[(240, 300, 0)]])
    assert _width(extract_photo(Path("-j"))) == 240


def test_two_images_tied_for_largest_are_ambiguous(tmp_path: Path) -> None:
    cv = _write(tmp_path, "cv.pdf", [[(240, 300, 0), (240, 300, 0)]])
    assert extract_photo(cv) is None


@pytest.mark.parametrize(
    ("w", "h", "expected"),
    [
        (200, 200, True),  # exactly on the size floor
        (199, 300, False),  # one pixel under it
        (300, 500, True),  # aspect 0.6 exactly
        (299, 500, False),
        (420, 300, True),  # aspect 1.4 exactly
        (421, 300, False),
    ],
)
def test_the_floors_are_inclusive_at_the_stated_values(w: int, h: int, expected: bool) -> None:
    assert (choose([_Listed(0, "image", w, h)]) is not None) is expected


def test_intake_stores_the_photo_beside_the_source_and_reports_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cv_store, "_extract_pdf_text", lambda _p: "Ana Perez\nana@example.com\n")
    store = _store(tmp_path)
    with_photo = _write(tmp_path, "with.pdf", [[(240, 300, 0)]])
    result = cv_store.import_document(store, with_photo)
    assert result.status == "imported" and result.photo == f"{result.doc_id}.photo.png"
    stored = store.path("cv", "source", result.photo).read_bytes()
    assert stored.startswith(PNG_MAGIC)

    logo = _write(tmp_path, "logo.pdf", [[(600, 120, 0)]])
    result = cv_store.import_document(store, logo)
    assert result.status == "imported" and result.photo is None
    assert not list(store.path("cv", "source").glob(f"{result.doc_id}.photo*"))


def _store(tmp_path: Path) -> ProfileStore:
    identity = create_profile(tmp_path / "profiles", "Ana Probe", handle="ana-probe")
    return ProfileStore(tmp_path / "profiles", identity.handle)
