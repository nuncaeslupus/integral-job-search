"""T184: a heading-less document gets one annotatable section per paragraph."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from integral import reader_sections
from integral.reader_sections import paragraphs, sectioned

LETTER = """# Carta de presentación

Estimada Sra. Ejemplo,

Le escribo para presentar mi candidatura al puesto de analista en Acme Ficticia.

Durante tres años coordiné un equipo de cuatro personas en un almacén de pruebas,
y reduje los retrasos de entrega a la mitad.

Le escribo para presentar mi candidatura de nuevo, con otras palabras.


Quedo a su disposición para una entrevista.

Atentamente,
Persona Inventada
"""

LETTER_PARAGRAPHS = [
    "Estimada Sra. Ejemplo,",
    "Le escribo para presentar mi candidatura al puesto de analista en Acme Ficticia.",
    "Durante tres años coordiné un equipo de cuatro personas en un almacén de pruebas,\n"
    "y reduje los retrasos de entrega a la mitad.",
    "Le escribo para presentar mi candidatura de nuevo, con otras palabras.",
    "Quedo a su disposición para una entrevista.",
    "Atentamente,\nPersona Inventada",
]

HEADED = "# Spec\n\nIntro.\n\n## One\n\nA.\n\n## Two\n\nB.\n"


def _sections(out: str) -> list[tuple[str, str]]:
    """(heading, body) per `##` section of `out`, cut the way the generator cuts."""
    got: list[tuple[str, list[str]]] = []
    in_code = False
    for line in out.split("\n"):
        if line.strip().startswith("```"):
            in_code = not in_code
        if not in_code and (m := re.match(r"^## (.*)$", line)):
            got.append((m.group(1), []))
        elif got:
            got[-1][1].append(line)
    return [(h, "\n".join(b).strip()) for h, b in got]


def test_headingless_document_gets_one_section_per_paragraph() -> None:
    out = sectioned(LETTER)
    sections = _sections(out)
    assert len(sections) == len(LETTER_PARAGRAPHS) == 6
    assert out.startswith("# Carta de presentación\n")
    assert [body for _, body in sections] == LETTER_PARAGRAPHS
    assert sections[0][0] == "1. Estimada Sra. Ejemplo,"
    assert sections[1][0] == "2. Le escribo para presentar mi candidatura…"


def test_a_headed_document_is_passed_through_unchanged() -> None:
    assert sectioned(HEADED) == HEADED
    # Byte-identical includes the line endings: CRLF is not normalised here.
    crlf = HEADED.replace("\n", "\r\n")
    assert sectioned(crlf).encode() == crlf.encode()
    # Two `###` count too, exactly as the generator counts them.
    assert sectioned("# T\n\n### a\n\nx\n\n### b\n\ny\n") == "# T\n\n### a\n\nx\n\n### b\n\ny\n"


def test_exactly_one_heading_is_still_split_and_its_text_is_kept_as_a_label() -> None:
    doc = "# T\n\n## Saludo\n\nHola.\n\nAdiós.\n"
    assert _sections(sectioned(doc)) == [("1. Saludo", "Hola."), ("2. Adiós.", "Adiós.")]
    # No `##` is left inside any body, so the generator cuts no extra section.
    assert all("\n## " not in "\n" + b for _, b in _sections(sectioned(doc)))
    assert _sections(sectioned("## Solo\n")) == [("1. Solo", "")]


def test_same_opening_words_get_distinct_labels() -> None:
    labels = [h for h, _ in _sections(sectioned(LETTER))]
    assert labels[1].split(". ", 1)[1] == labels[3].split(". ", 1)[1]  # same words...
    assert len(set(labels)) == len(labels)  # ...distinct labels


def test_crlf_blank_runs_and_whitespace_only_paragraphs() -> None:
    doc = "uno\r\n\r\n\r\n   \t \r\n\r\ndos\r\ntres\r\n"
    assert [b for _, b in _sections(sectioned(doc))] == ["uno", "dos\ntres"]
    assert "\r" not in sectioned(doc)
    assert _sections(sectioned("   \n\n \n")) == []


def test_heading_inside_a_fence_is_not_a_heading() -> None:
    doc = "Antes.\n\n```\n## no es\n\n## ni esto\n```\n\nDespués.\n"
    got = _sections(sectioned(doc))
    # Two fenced `##` lines would be >= 2 headings if miscounted: pass-through.
    assert [b for _, b in got] == ["Antes.", "```\n## no es\n\n## ni esto\n```", "Después."]


def test_labels_strip_markup_and_survive_short_or_empty_openings() -> None:
    doc = "**Hola** _mundo_ [link](http://x) `code` uno dos tres cuatro\n\n- Ítem\n\n***\n\n>\n"
    labels = [h for h, _ in _sections(sectioned(doc))]
    assert labels == [
        "1. Hola mundo linkhttp://x code uno dos…",
        "2. Ítem",
        "3. paragraph",
        "4. paragraph",
    ]


def test_text_is_never_lost_or_reordered() -> None:
    for doc in (
        LETTER,
        LETTER.replace("\n", "\r\n"),
        "solo una línea",
        "a\n\n\n\nb\n\n```\nc\n\nd\n```\ne\n\nf",
        "# T\n\n  indented  \n\n\ttab\n",
    ):
        _, original = paragraphs(doc)
        bodies = [b for _, b in _sections(sectioned(doc))]
        assert bodies == [b.strip() for _, b in original]
        flat = re.sub(r"\s+", " ", re.sub(r"^# .*$", "", doc, count=1, flags=re.MULTILINE))
        assert re.sub(r"\s+", " ", " ".join(bodies)).strip() == flat.strip()


def test_a_rule_only_paragraph_is_dropped_and_nothing_else() -> None:
    assert [b for _, b in _sections(sectioned("a\n\n---\n\nb\n"))] == ["a", "b"]


@pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv to supply `markdown`")
def test_the_real_generator_cuts_one_section_per_paragraph(tmp_path: Path) -> None:
    src = tmp_path / "carta.md"
    src.write_text(LETTER, encoding="utf-8")
    # Baseline: the generator on the raw letter yields ONE section.
    raw_dir, new_dir = tmp_path / "raw", tmp_path / "wrapped"
    raw_dir.mkdir()
    gen = [
        "uv", "run", "--with", "markdown", "python3", str(reader_sections.CREATE_READER),
    ]  # fmt: skip
    base = subprocess.run(
        [*gen, "--input", str(src), "--output-dir", str(raw_dir), "--name", "T"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert base.returncode == 0, base.stderr
    raw_html = (raw_dir / "carta-reader.html").read_text(encoding="utf-8")
    assert raw_html.count('<article class="sec"') == 1

    wrapped = subprocess.run(
        [
            sys.executable, "-m", "integral.reader_sections",
            "--input", str(src), "--output-dir", str(new_dir), "--name", "T",
        ],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert wrapped.returncode == 0, wrapped.stderr
    html = (new_dir / "carta-reader.html").read_text(encoding="utf-8")
    # The generator's own markers: one article and one note box per section.
    assert html.count('<article class="sec"') == len(LETTER_PARAGRAPHS)
    assert html.count('<textarea class="note-ta"') == len(LETTER_PARAGRAPHS)
    bodies = re.findall(r'<div class="sec-body">(.*?)</div>', html, flags=re.DOTALL)
    assert len(bodies) == len(LETTER_PARAGRAPHS)
    for body, para in zip(bodies, LETTER_PARAGRAPHS, strict=True):
        assert para.split("\n", 1)[0].split(",")[0] in body
    ids = re.findall(r'<article class="sec" id="([^"]+)"', html)
    assert len(set(ids)) == len(ids)
    assert src.read_text(encoding="utf-8") == LETTER  # the original is never rewritten
