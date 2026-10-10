"""T148: an edit is judged by the document it leaves, not by the write succeeding."""

from __future__ import annotations

from typing import Any

import pytest

from integral import document_edit as de


def _letter() -> dict[str, Any]:
    return de._letter()


def _blocks(doc: dict[str, Any]) -> list[Any]:
    return list(doc["blocks"])


def test_the_gate_reads_zero_and_ran_every_contract() -> None:
    measured = de.measure()
    assert measured["gate_status"] == "measured"
    assert measured["document_edit_defects"] == 0, measured["defects"]
    assert set(de.REQUIRED_CONTRACTS) <= set(measured["contracts_run"])


def test_stale_index_after_a_removal_is_refused() -> None:
    letter = _letter()
    gone = de.apply_edit(
        letter, [de.Change(2, de.block_text(_blocks(letter)[2]), None)], count_change=-1
    )
    stale = de.Change(4, de.block_text(_blocks(letter)[4]), {"type": "text", "text": "Dup."})
    with pytest.raises(de.EditRefused, match="index moved"):
        de.apply_edit(gone, [stale])


def test_a_filter_that_drops_the_addressee_is_refused() -> None:
    letter = _letter()
    filtered = {**letter, "blocks": [b for b in letter["blocks"] if b.get("text") is not None]}
    with pytest.raises(de.EditRefused):
        de.verify_edit(letter, filtered)


def test_a_legitimate_replace_changes_only_the_named_block() -> None:
    letter = _letter()
    change = de.Change(3, de.block_text(_blocks(letter)[3]), {"type": "text", "text": "New."})
    out = de.apply_edit(letter, [change])
    assert de.block_text(_blocks(out)[3]) == "New."
    assert [b for i, b in enumerate(_blocks(out)) if i != 3] == [
        b for i, b in enumerate(_blocks(letter)) if i != 3
    ]
    assert de.block_text(_blocks(letter)[3]) == "Second paragraph."  # input untouched


def test_an_unnamed_block_that_changed_is_refused_even_when_the_count_holds() -> None:
    letter = _letter()
    tampered = {**letter, "blocks": [*_blocks(letter)]}
    tampered["blocks"][4] = {"type": "text", "text": "Second paragraph."}
    with pytest.raises(de.EditRefused, match="not named"):
        de.verify_edit(letter, tampered)


def test_a_change_to_a_non_text_field_of_an_unnamed_block_is_refused() -> None:
    cv = {
        "title": "t",
        "blocks": [{"type": "project", "name": "n", "text": "x", "href": "https://a.test/"}],
    }
    other = {
        "title": "t",
        "blocks": [{"type": "project", "name": "n", "text": "x", "href": "https://b.test/"}],
    }
    with pytest.raises(de.EditRefused):
        de.verify_edit(cv, other)


def test_count_change_must_be_declared_and_match() -> None:
    letter = _letter()
    remove = de.Change(2, de.block_text(_blocks(letter)[2]), None)
    with pytest.raises(de.EditRefused, match="declares"):
        de.apply_edit(letter, [remove])
    with pytest.raises(de.EditRefused, match="declares"):
        de.apply_edit(letter, [remove], count_change=-2)
    with pytest.raises(de.EditRefused, match="declares"):
        de.apply_edit(letter, [], [de.Insert(1, {"type": "text", "text": "x"})])
    out = de.apply_edit(letter, [], [de.Insert(7, {"type": "text", "text": "x"})], count_change=1)
    assert de.block_text(_blocks(out)[-1]) == "x"


def test_insert_in_the_middle_keeps_everything_else() -> None:
    letter = _letter()
    out = de.apply_edit(letter, [], [de.Insert(2, {"type": "text", "text": "new"})], count_change=1)
    assert [de.block_text(b) for b in _blocks(out)][:2] == [
        de.block_text(b) for b in _blocks(letter)
    ][:2]
    assert _blocks(out)[2]["text"] == "new"
    assert _blocks(out)[3:] == _blocks(letter)[2:]


def test_a_verifier_that_misses_a_dropped_block_would_be_caught_by_the_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(de, "verify_edit", lambda *a, **k: None)
    monkeypatch.setattr(de, "_refused", lambda run: False)
    assert de.measure()["document_edit_defects"] > 0


def test_a_missing_contract_is_unmeasured_not_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    trimmed = dict(de._CONTRACTS)
    trimmed.pop("dropped block is refused")
    monkeypatch.setattr(de, "_CONTRACTS", trimmed)
    measured = de.measure()
    assert measured["gate_status"] == "unmeasured"
    assert measured["document_edit_defects"] == -1


def test_an_unrenderable_result_is_refused() -> None:
    letter = _letter()
    change = de.Change(3, de.block_text(_blocks(letter)[3]), {"type": "nope"})
    with pytest.raises(de.EditRefused):
        de.apply_edit(letter, [change])


def test_out_of_range_and_duplicate_names_are_refused() -> None:
    letter = _letter()
    with pytest.raises(de.EditRefused):
        de.apply_edit(letter, [de.Change(99, "", None)], count_change=-1)
    same = de.Change(3, de.block_text(_blocks(letter)[3]), {"type": "text", "text": "a"})
    with pytest.raises(de.EditRefused):
        de.verify_edit(letter, letter, [same, same])


def test_a_dropped_last_block_and_an_appended_block_are_refused() -> None:
    letter = _letter()
    short = {**letter, "blocks": _blocks(letter)[:-1]}
    longer = {**letter, "blocks": [*_blocks(letter), {"type": "text", "text": "stray"}]}
    for after in (short, longer):
        with pytest.raises(de.EditRefused):
            de.verify_edit(letter, after)


def test_stale_index_is_refused_by_verify_edit_itself() -> None:
    letter = _letter()
    gone = de.apply_edit(
        letter, [de.Change(2, de.block_text(_blocks(letter)[2]), None)], count_change=-1
    )
    dup = {"type": "text", "text": "Duplicate."}
    written = {**gone, "blocks": [*_blocks(gone)[:4], dup, *_blocks(gone)[5:]]}
    with pytest.raises(de.EditRefused, match="index moved"):
        de.verify_edit(gone, written, [de.Change(4, "The leap of faith.", dup)])


def test_same_count_overwrite_of_unnamed_blocks_names_the_first_one() -> None:
    letter = _letter()
    blocks = _blocks(letter)
    blocks[4], blocks[5] = blocks[2], blocks[3]
    with pytest.raises(de.EditRefused, match="block 4"):
        de.verify_edit(_letter(), {**letter, "blocks": blocks})


def test_dropping_only_the_addressee_names_block_one() -> None:
    letter = _letter()
    blocks = [b for b in _blocks(letter) if b["type"] != "to"]
    with pytest.raises(de.EditRefused, match="block 1"):
        de.verify_edit(letter, {**letter, "blocks": blocks})


def test_duplicate_names_are_refused_by_their_own_guard() -> None:
    letter = _letter()
    text3 = de.block_text(_blocks(letter)[3])
    a, b = {"type": "text", "text": "A"}, {"type": "text", "text": "B"}
    after = {**letter, "blocks": [*_blocks(letter)[:3], b, *_blocks(letter)[4:]]}
    with pytest.raises(de.EditRefused, match="twice"):
        de.verify_edit(letter, after, [de.Change(3, text3, a), de.Change(3, text3, b)])


def test_insert_position_out_of_range_is_refused() -> None:
    letter = _letter()
    with pytest.raises(de.EditRefused, match="position"):
        de.apply_edit(letter, [], [de.Insert(99, {"type": "text", "text": "x"})], count_change=1)


def test_a_named_replacement_that_is_not_the_requested_block_is_refused() -> None:
    letter = _letter()
    text3 = de.block_text(_blocks(letter)[3])
    other = {
        **letter,
        "blocks": [*_blocks(letter)[:3], {"type": "text", "text": "B"}, *_blocks(letter)[4:]],
    }
    with pytest.raises(de.EditRefused, match="replacement"):
        de.verify_edit(letter, other, [de.Change(3, text3, {"type": "text", "text": "A"})])


def test_an_inserted_block_that_is_not_the_requested_one_is_refused() -> None:
    letter = _letter()
    other = {
        **letter,
        "blocks": [*_blocks(letter)[:2], {"type": "text", "text": "B"}, *_blocks(letter)[2:]],
    }
    with pytest.raises(de.EditRefused, match="inserted block"):
        de.verify_edit(
            letter, other, [], [de.Insert(2, {"type": "text", "text": "A"})], count_change=1
        )


def test_a_changed_title_or_extra_top_level_key_is_refused() -> None:
    letter = _letter()
    with pytest.raises(de.EditRefused, match="top-level"):
        de.verify_edit(letter, {**letter, "title": "Other"})
    with pytest.raises(de.EditRefused, match="top-level"):
        de.verify_edit(letter, {**letter, "extra": 1})


def test_an_unrenderable_result_is_refused_by_render_validation() -> None:
    letter = _letter()
    change = de.Change(3, de.block_text(_blocks(letter)[3]), {"type": "nope"})
    with pytest.raises(de.EditRefused, match="cannot be rendered"):
        de.apply_edit(letter, [change])


def test_every_required_contract_is_registered_and_reports_a_defect_when_blind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = dict(de._CONTRACTS)
    for name in de.REQUIRED_CONTRACTS:
        assert name in original
        patched = dict(original)
        patched[name] = lambda: ["sentinel"]
        monkeypatch.setattr(de, "_CONTRACTS", patched)
        assert de.measure()["document_edit_defects"] == 1
