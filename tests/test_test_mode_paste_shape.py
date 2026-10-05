"""T190: length alone no longer makes a turn a paste; structure does.

Fail-open is the dangerous direction: reading `[[...]]` inside a real paste as
meta. So the fixtures are weighted toward real pastes, and each verdict is
justified by the SKILL's rule (a paste is advert or CV text; brackets, bullets
and headings are what adverts are made of), never by running the code.
"""

from __future__ import annotations

import sys
import unicodedata
from collections.abc import Callable

import pytest

from integral.test_mode import PASTE_CHARS, detect_guard, parse_turn

NOTE = "[[the question order felt wrong]]"

# The task's own reproduction: conversational prose, two URLs, a note.
REPRO = (
    "Vale, he mirado las dos ofertas que me enviaste, la de https://example.invalid/jobs/114 "
    "y la de https://example.invalid/jobs/220, y la verdad es que me quedo con la primera "
    "porque queda más cerca de casa y el horario encaja con el de mi pareja. La segunda "
    "paga algo mejor pero me obligaría a cambiar de ciudad, y ahora mismo no quiero. "
    + NOTE
    + " Gracias por la ayuda, de verdad, me has aclarado bastante las ideas."
)

ADVERT_MULTILINE = (
    "Técnico/a de mantenimiento\n"
    "Buscamos un/a técnico/a para nuestra planta de Martorell.\n"
    "Requisitos:\n"
    "Experiencia en automoción y carné B\n"
    "Residencia en el área metropolitana\n"
    "Ofrecemos contrato indefinido, salario según convenio y formación continua. "
    "Incorporación inmediata, turnos rotativos. Enviar CV indicando la referencia "
    "REF-2026-114 y esperar nuestra respuesta en un plazo máximo de dos semanas."
)

PASTES = {
    "multiline advert, no brackets": ADVERT_MULTILINE,
    "advert with bullets": (
        "Se busca camarero/a. Funciones:\n- Atender mesas\n- Preparar café\n- Cerrar caja\n"
        "- Limpieza del local\nOfrecemos contrato de 30 horas semanales y propinas. " * 2
    ),
    "advert with markdown headings": (
        "## Sobre el puesto\nTrabajarás con un equipo pequeño y muy cercano.\n"
        "## Requisitos\nGanas de aprender y buena actitud con el cliente final.\n"
        "## Ofrecemos\nContrato indefinido, jornada completa y formación pagada por la empresa. "
        * 2
    ),
    "CV": (
        "Ana Pérez García\nTécnica de mantenimiento\nana.perez@example.invalid\n"
        "2018-2022 Seat, Martorell: mantenimiento preventivo de líneas de montaje.\n"
        "2022-2025 Gestamp: responsable de turno de noche con seis personas a cargo.\n"
        "Formación: FP2 Mantenimiento Industrial. Idiomas: catalán, castellano, inglés B2. " * 2
    ),
    "flattened advert with tags": (
        "[Barcelona] [Híbrido] Técnico/a de mantenimiento Buscamos un/a técnico/a para nuestra "
        "planta Requisitos Experiencia en automoción Carné B Residencia en el área metropolitana "
        "Ofrecemos contrato indefinido salario según convenio y formación continua Incorporación "
        "inmediata Enviar CV indicando la referencia"
    ),
    "flattened advert with inline bullets": (
        "Se busca camarero/a • Atender mesas • Preparar café • Cerrar caja • Limpieza del local "
        "• Contrato de treinta horas semanales • Propinas • Horario de tarde • Incorporación "
        "inmediata • Enviar CV a la dirección indicada en la web de la empresa antes de fin de mes"
    ),
    "flattened advert with no punctuation at all": (
        "Técnico de mantenimiento planta Martorell requisitos experiencia en automoción carné B "
        "residencia en el área metropolitana ofrecemos contrato indefinido salario según convenio "
        "formación continua incorporación inmediata turnos rotativos enviar CV indicando la "
        "referencia y esperar respuesta en el plazo máximo de dos semanas desde el envío"
    ),
    "flattened advert with pipes": (
        "Técnico/a de mantenimiento | Martorell | Indefinido. Buscamos un/a técnico/a para nuestra "
        "planta. Se valorará experiencia en automoción. Ofrecemos salario según convenio y "
        "formación continua. Imprescindible carné B. Incorporación inmediata, turnos rotativos."
    ),
    "flattened advert with a contact address": (
        "Buscamos un/a técnico/a para nuestra planta. Se valorará experiencia en automoción. "
        "Ofrecemos contrato indefinido y salario según convenio. Imprescindible carné B y "
        "residencia en el área metropolitana. Incorporación inmediata. Enviar CV a "
        "rrhh@example.invalid indicando la referencia de la oferta que le interese al candidato."
    ),
}


def _grown(body: str) -> str:
    """Repeat a fixture until it is long enough to be eligible; the structure is
    preserved, so the verdict is about shape and not about the length."""
    while len(body) < PASTE_CHARS:
        body = body + " " + body
    return body


PASTES = {name: _grown(body) for name, body in PASTES.items()}


@pytest.mark.parametrize("name", sorted(PASTES))
def test_a_real_paste_with_a_marker_in_it_stays_a_paste(name: str) -> None:
    body = PASTES[name]
    assert len(body) >= PASTE_CHARS
    turn = body + " " + NOTE
    parsed = parse_turn(turn)
    assert parsed.guard == "long-turn"
    assert parsed.notes == ()
    assert parsed.visible == turn
    assert parsed.unparsed_markers == 1


@pytest.mark.parametrize("name", sorted(PASTES))
def test_a_marker_in_the_middle_of_a_real_paste_stays_a_paste(name: str) -> None:
    body = PASTES[name]
    middle = len(body) // 2
    cut = body.index(" ", middle)
    turn = body[:cut] + " " + NOTE + body[cut:]
    parsed = parse_turn(turn)
    assert parsed.guard == "long-turn"
    assert parsed.notes == ()
    assert parsed.unparsed_markers == 1


def test_the_task_reproduction_is_captured() -> None:
    assert len(REPRO) >= PASTE_CHARS
    assert REPRO.count("https://") == 2
    parsed = parse_turn(REPRO)
    assert parsed.guard == "none"
    assert [note.text for note in parsed.notes] == ["the question order felt wrong"]
    assert parsed.unparsed_markers == 0
    assert NOTE not in parsed.visible


def test_a_note_cannot_hide_structure_or_manufacture_it() -> None:
    """A tester's note is stripped before the shape is judged, so a note that
    contains brackets or symbols neither makes prose look pasted nor lets a
    paste hide behind it."""
    prose = REPRO.replace(NOTE, "[[odd [bracket] | and a bullet • here]]")
    assert detect_guard(prose) == "none"
    assert detect_guard(ADVERT_MULTILINE + " [[note]]") == "long-turn"


def test_a_short_turn_is_unchanged_by_shape() -> None:
    assert detect_guard("Turnos [[rotativos]] [Remote]") == "none"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda t: t + " [Remote]",  # single-bracket tag
        lambda t: t + " | Madrid",  # layout glyph
        lambda t: t + " escribe a rrhh@example.invalid.",  # contact address
        lambda t: t + "\n- Uno.\n- Dos.",  # bullet lines, each a full sentence
        lambda t: t + "\n1. Uno.",  # enumerator, a full sentence
        lambda t: t + "\n# Uno.",  # heading marker, a full sentence
        lambda t: t + "\nRequisitos",  # heading line
        lambda t: t + " " + "palabra " * 41,  # unpunctuated run
        lambda t: "\n".join([t, "Uno.", "Dos.", "Tres."]),  # too many lines
    ],
)
def test_each_structure_signal_alone_flips_prose_to_paste(
    mutation: Callable[[str], str],
) -> None:
    assert detect_guard(REPRO) == "none"
    assert detect_guard(mutation(REPRO)) == "long-turn"


def test_currency_in_prose_is_not_structure() -> None:
    assert detect_guard(REPRO.replace("paga algo mejor", "paga unos 2.000 € brutos")) == "none"


def test_a_typed_two_paragraph_answer_with_sentences_is_read() -> None:
    assert detect_guard(REPRO.replace(" Gracias", "\nGracias")) == "none"


BOARD_URLS = (
    "https://www.infojobs.net/barcelona/tecnico/of-i1234?applicationOrigin=search-new&utm_source=a+b"
    " y https://medium.com/@autor/post~1?ref=x"
)


def test_board_urls_with_query_strings_are_not_structure() -> None:
    turn = REPRO.replace(
        "https://example.invalid/jobs/114",
        "https://www.infojobs.net/of-i1?applicationOrigin=search-new&utm_source=a+b",
    )
    turn = turn.replace(
        "https://example.invalid/jobs/220", "https://medium.com/@autor/post~1?ref=x"
    )
    assert "utm_source" in turn and "?" in turn
    assert detect_guard(turn) == "none"
    assert [n.text for n in parse_turn(turn).notes] == ["the question order felt wrong"]


def test_a_url_does_not_hide_structure_around_it() -> None:
    assert (
        detect_guard(
            REPRO.replace("https://example.invalid/jobs/114", "https://x.invalid/a [Remote]")
        )
        == "long-turn"
    )
    assert detect_guard(REPRO + " | Madrid") == "long-turn"


def test_a_sentence_just_past_forty_words_is_still_typed() -> None:
    assert detect_guard(REPRO.replace("queda más cerca", "queda bastante más cerca")) == "none"
    assert (
        detect_guard(
            REPRO.replace("queda más cerca", "queda muchísimo bastante más cerca de verdad")
        )
        == "none"
    )


def test_a_clause_comma_resets_the_run_but_nothing_else_does() -> None:
    words = " ".join(["palabra"] * 60)
    assert detect_guard(REPRO + " " + words) == "long-turn"
    assert (
        detect_guard(REPRO + " " + words.replace("palabra palabra", "palabra, palabra", 30))
        == "none"
    )


@pytest.mark.parametrize(
    "opener", ["\u00bf", "\u00a1", "\u201c", "\u00ab", "(", '"', "\u00bf\u00a1"]
)
def test_a_line_opening_with_spanish_or_quote_punctuation_is_typed(opener: str) -> None:
    closer = {"\u201c": "\u201d", "\u00ab": "\u00bb", "(": ")", '"': '"'}.get(
        opener, "?" if "\u00bf" in opener else "!"
    )
    turn = REPRO.replace("Vale, he mirado", f"{opener}Vale, he mirado", 1).replace(
        "Gracias por la ayuda,", f"Gracias por la ayuda{closer}", 1
    )
    assert detect_guard(turn) == "none"
    spanish = f"{opener}Y si miramos también la de Tarragona?\n" + REPRO
    assert detect_guard(spanish) == "none"


def test_a_line_that_is_only_an_opener_is_a_paste() -> None:
    assert detect_guard(REPRO + "\n\u00bf") == "long-turn"


def _bullet_like() -> list[str]:
    chars = ["\u00b7"]
    for code in range(sys.maxunicode + 1):
        if code > 0xFFFF:
            break
        char = chr(code)
        if "BULLET" in unicodedata.name(char, ""):
            chars.append(char)
    return chars


def test_the_bullet_population_is_derived_from_unicode_not_listed() -> None:
    chars = _bullet_like()
    assert "\u2022" in chars and "\u00b7" in chars
    assert len(chars) >= 8


@pytest.mark.parametrize("char", _bullet_like(), ids=lambda c: f"U+{ord(c):04X}")
def test_every_bullet_glyph_alone_flips_prose_to_paste(char: str) -> None:
    assert detect_guard(REPRO) == "none"
    assert detect_guard(REPRO + " " + char + " Madrid.") == "long-turn"


@pytest.mark.parametrize(
    "separator", ["-", "\N{EN DASH}", "\N{EM DASH}", "/", "\N{MIDDLE DOT}", "|"]
)
def test_a_lone_separator_token_does_not_reset_the_run(separator: str) -> None:
    flat = PASTES["flattened advert with no punctuation at all"]
    spaced = f" {separator} ".join(flat.split())
    assert len(spaced) >= PASTE_CHARS
    turn = spaced + " " + NOTE
    parsed = parse_turn(turn)
    assert parsed.guard == "long-turn"
    assert parsed.notes == ()
    assert parsed.unparsed_markers == 1


@pytest.mark.parametrize("separator", ["-", "\N{EN DASH}", "/"])
def test_separators_between_prose_words_still_leave_the_run_unreset(separator: str) -> None:
    words = " ".join(["palabra"] * 60)
    assert (
        detect_guard(REPRO + f" {separator} " + words.replace(" ", f" {separator} ")) == "long-turn"
    )


@pytest.mark.parametrize(
    "lead",
    [("(1)", "(2)", "(3)"), ("(a)", "(b)", "(c)"), ("1)", "2)", "3)")],
)
def test_a_parenthesised_list_is_a_list(lead: tuple[str, str, str]) -> None:
    """The opener skip strips `(`; the enumerator test must see what is left."""
    sentence = " Atender las mesas del local, preparar el café y cerrar la caja al final."
    items = "\n".join(f"{mark}{sentence * 3}" for mark in lead)
    assert len(items) >= PASTE_CHARS
    assert len(items.splitlines()) == 3  # under the line-count limit: only the lead can decide
    turn = items.replace("Atender", f"Atender {NOTE}", 1)
    assert detect_guard(turn) == "long-turn"
    assert parse_turn(turn).notes == ()
