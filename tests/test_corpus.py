"""T4 — the corpus harness: roundtrip fidelity, splits, self-agreement.

Written RED before `integral.harness` existed, per the task payload. The named
test is `test_corpus_roundtrip_preserves_text_and_offsets`; the rest cover the
split guarantee T9 will depend on and the self-agreement report the labelling
protocol calls for.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from integral.corpus import load_ads
from integral.dimensions import load_dimensions
from integral.harness import (
    DEFAULT_STORE_PATH,
    HarnessError,
    Label,
    LabelledAd,
    Span,
    assign_splits,
    build_store,
    load_store,
    measure,
    measure_labels,
    probe_labels,
    roundtrip_loss,
    save_store,
    self_agreement,
    split_counts,
    unknown_dimensions,
)
from integral.harness import (
    _main as main,
)

# Accents, an emoji and a line break — the three things that move offsets if
# anything in the write/read cycle re-encodes rather than preserves.
TRICKY = "Es busca enginyer/a 🏖️ amb anglès (B2)\nSense guàrdies. Formació contínua."


def ad(text: str = TRICKY, ad_id: str = "test-1", labels: list[Label] | None = None) -> LabelledAd:
    return LabelledAd(
        id=ad_id,
        language="ca",
        text=text,
        source_url="https://example.invalid/1",
        split="evaluation",
        labels=labels or [],
    )


def test_corpus_roundtrip_preserves_text_and_offsets(tmp_path: Path) -> None:
    """Writing then reading an ad preserves text byte-for-byte and label offsets.

    The span is placed on "guàrdies", which sits after both an emoji and an
    accented word: if the store re-encoded anything, the offsets would still be
    integers and would still validate, but they would cover different
    characters. That is what is asserted — what the span *extracts*, not what
    it contains.
    """
    start = TRICKY.index("guàrdies")
    label = Label(
        dimension="on_call_load",
        value=0.0,
        spans=[Span(start=start, end=start + len("guàrdies"))],
        negated=True,
        labeller="test",
    )
    store = [ad(labels=[label])]

    assert roundtrip_loss(store, tmp_path / "store.jsonl") == []

    reloaded = load_store(tmp_path / "store.jsonl")
    assert reloaded[0].text == TRICKY
    assert reloaded[0].labels[0].spans[0].extract(reloaded[0].text) == "guàrdies"
    assert reloaded[0].labels[0].negated is True


def test_committed_store_roundtrips_without_loss() -> None:
    """The real store, and every ad in it carrying a probe label, survives intact."""
    measured = measure(DEFAULT_STORE_PATH)

    assert measured["corpus_harness_roundtrip_loss"] == 0, measured["roundtrip_losses"]
    assert measured["ad_count"] == len(load_ads())


def test_probe_labels_take_their_offsets_from_real_ad_text() -> None:
    """The committed store is unlabelled until T5, so the gate probes with real cues.

    Without this the roundtrip would preserve offsets vacuously, having none to
    preserve — a gate that passes because it measured nothing.
    """
    store = load_store(DEFAULT_STORE_PATH)
    probed = probe_labels(store, load_dimensions())

    labelled = [a for a in probed if a.labels]
    assert len(labelled) > len(store) // 2, "probes reach too little of the corpus to be a check"
    for item in labelled:
        for span in item.labels[0].spans:
            assert span.extract(item.text).strip(), "probe span covers no text"


def test_a_span_running_past_the_end_of_the_text_is_rejected() -> None:
    """An offset outside the text is refused at construction, not at read time."""
    with pytest.raises(ValueError, match="runs past the end"):
        ad(
            labels=[
                Label(
                    dimension="on_call_load",
                    value=0.5,
                    spans=[Span(start=0, end=len(TRICKY) + 10)],
                    labeller="test",
                )
            ]
        )


def test_split_assignment_is_deterministic() -> None:
    """The same corpus assigns identically on every run and every machine."""
    assert [a.split for a in build_store()] == [a.split for a in build_store()]


def test_each_language_is_halved_between_the_splits() -> None:
    """Every language is divided at its own target, not thresholded per ad.

    Thresholding each id independently is binomial, and the first cut of this
    corpus put 1 of 15 Catalan ads in evaluation — which would have measured
    Catalan extraction (T15) and Catalan ranking (T20) on a single ad while the
    aggregate counts looked healthy. Each language slice is checked, because
    the aggregate is what hid it.
    """
    counts = split_counts(load_store(DEFAULT_STORE_PATH))

    for language, total in (("es", 60), ("en", 25), ("ca", 15)):
        evaluation = counts["evaluation"][language]
        elicitation = counts["elicitation"][language]
        assert evaluation + elicitation == total
        assert abs(evaluation - elicitation) <= 1, (
            f"{language} is split {elicitation}/{evaluation}, not halved"
        )


def test_an_existing_split_assignment_is_never_reassigned() -> None:
    """Adding ads later must not migrate an ad already in the store.

    An ad that moves from the elicitation half to the evaluation half after it
    has been used to elicit preferences puts memorised ads into the ranking
    gate — `elicitation_eval_overlap` arriving by the back door rather than
    through a bug. So prior assignments are held fixed and only new ads are
    placed.
    """
    ads = load_ads()
    before = {a["id"]: assign_splits(ads)[a["id"]] for a in ads}

    newcomers = [
        {"id": f"newcomer-{i}", "language": "ca", "text": "…", "source_url": "https://x.invalid"}
        for i in range(10)
    ]
    after = assign_splits([*ads, *newcomers], existing=before)

    assert {ad_id: after[ad_id] for ad_id in before} == before
    assert all(after[str(ad["id"])] in ("elicitation", "evaluation") for ad in newcomers)


def test_init_preserves_existing_splits_when_the_corpus_grows(tmp_path: Path) -> None:
    """The CLI must carry splits forward, not just labels.

    `assign_splits` supports this and `test_an_existing_split_assignment_is_
    never_reassigned` proves the function honours it — but the function is not
    the thing anyone runs. Re-seeding without passing the existing assignments
    recomputes every split from scratch, so a corpus top-up migrates ads
    between halves and the stability guarantee is true of the code and false of
    the command. Review caught that; this closes it at the level it broke.
    """
    raw = tmp_path / "raw.jsonl"
    store = tmp_path / "store.jsonl"

    def raw_ad(index: int, language: str) -> dict[str, object]:
        return {
            "id": f"ad-{language}-{index}",
            "language": language,
            "text": f"ad body {index}",
            "source_url": f"https://example.invalid/{language}/{index}",
        }

    first_batch = [raw_ad(i, "ca") for i in range(6)]
    raw.write_text(
        "\n".join(json.dumps(a, ensure_ascii=False) for a in first_batch) + "\n", encoding="utf-8"
    )
    assert main(["--store", str(store), "init", "--raw", str(raw)]) == 0
    before = {a.id: a.split for a in load_store(store)}

    grown = [*first_batch, *(raw_ad(i, "ca") for i in range(6, 20))]
    raw.write_text(
        "\n".join(json.dumps(a, ensure_ascii=False) for a in grown) + "\n", encoding="utf-8"
    )
    assert main(["--store", str(store), "init", "--raw", str(raw)]) == 0
    after = {a.id: a.split for a in load_store(store)}

    assert {ad_id: after[ad_id] for ad_id in before} == before
    assert len(after) == 20


def test_evaluation_receives_the_ceiling_half_of_an_odd_slice() -> None:
    """25 English ads split 12/13, not 13/12.

    `round(25 * 0.5)` is 12 under banker's rounding, which quietly hands the
    spare ad to elicitation — and evaluation is the half carrying
    `extraction_macro_f1` and `rank_spearman`.
    """
    counts = split_counts(load_store(DEFAULT_STORE_PATH))

    assert counts["evaluation"]["en"] == 13
    assert counts["elicitation"]["en"] == 12


def test_a_dimension_labelled_in_one_round_only_counts_as_disagreement() -> None:
    """Present in round 1, absent in round 2 is a disagreement, not a skipped pair.

    Comparing only the dimensions both rounds share discards exactly the cases
    where the two passes differed most, so agreement rises the more the
    labeller changed their mind.
    """
    dropped = ad(
        labels=[
            Label(
                dimension="on_call_load",
                value=0.8,
                spans=[Span(start=0, end=2)],
                labeller="owner",
                round=1,
            ),
            Label(
                dimension="remote_arrangement",
                value=0.8,
                spans=[Span(start=0, end=2)],
                labeller="owner",
                round=2,
            ),
        ]
    )

    report = self_agreement([dropped])

    assert report["compared_labels"] == 2
    assert report["raw_agreement"] == 0.0


def test_an_ad_never_revisited_is_left_out_of_the_agreement() -> None:
    """Round-1-only ads are unrevisited, not disagreed with."""
    report = self_agreement(
        [
            ad(
                ad_id="once",
                labels=[
                    Label(
                        dimension="on_call_load",
                        value=0.8,
                        spans=[Span(start=0, end=2)],
                        labeller="owner",
                    )
                ],
            )
        ]
    )

    assert report["compared_labels"] == 0
    assert report["undefined_because"] == "nothing has been labelled twice"


def test_invalid_cli_input_exits_cleanly_instead_of_raising(tmp_path: Path) -> None:
    """`--round 0` reaches Pydantic, not argparse — it must not print a traceback."""
    store = tmp_path / "store.jsonl"
    save_store([ad(ad_id="x", text="Sense guàrdies aquí")], store)

    code = main(
        [
            "--store",
            str(store),
            "set",
            "x",
            "on_call_load",
            "0.0",
            "--quote",
            "Sense guàrdies",
            "--round",
            "0",
        ]
    )

    assert code == 2


def test_the_two_splits_are_disjoint_and_cover_the_corpus() -> None:
    """Every ad is in exactly one split — the property T9 gates on."""
    store = load_store(DEFAULT_STORE_PATH)
    elicitation = {a.id for a in store if a.split == "elicitation"}
    evaluation = {a.id for a in store if a.split == "evaluation"}

    assert elicitation & evaluation == set()
    assert elicitation | evaluation == {a.id for a in store}


def test_a_label_naming_an_unknown_dimension_is_reported() -> None:
    """A misspelled dimension drops out of per-dimension metrics rather than failing."""
    store = [
        ad(
            labels=[
                Label(
                    dimension="sallary_transparency",
                    value=0.5,
                    spans=[Span(start=0, end=2)],
                    labeller="test",
                )
            ]
        )
    ]

    problems = unknown_dimensions(store, load_dimensions())

    assert len(problems) == 1
    assert "sallary_transparency" in problems[0]


def test_duplicate_ad_ids_in_the_store_are_refused(tmp_path: Path) -> None:
    """Two rows for one ad would let a label silently shadow another."""
    path = tmp_path / "store.jsonl"
    save_store([ad(ad_id="dup")], path)
    path.write_text(path.read_text(encoding="utf-8") * 2, encoding="utf-8")

    with pytest.raises(HarnessError, match="duplicate"):
        load_store(path)


def test_the_two_undefined_agreement_states_are_distinguishable() -> None:
    """ "Nothing re-labelled" and "re-labelled but degenerate" are different states.

    Both report `kappa: None`, and a caller that reads only that field would
    tell a labeller who has just re-done forty ads to go and do them — so the
    reason is carried alongside, and the CLI prints it.
    """
    nothing = self_agreement(
        [
            ad(
                labels=[
                    Label(
                        dimension="on_call_load",
                        value=0.5,
                        spans=[Span(start=0, end=2)],
                        labeller="o",
                    )
                ]
            )
        ]
    )
    degenerate = self_agreement(
        [
            ad(
                labels=[
                    Label(
                        dimension="on_call_load",
                        value=0.0,
                        spans=[Span(start=0, end=2)],
                        labeller="o",
                        round=1,
                    ),
                    Label(
                        dimension="on_call_load",
                        value=0.0,
                        spans=[Span(start=0, end=2)],
                        labeller="o",
                        round=2,
                    ),
                ]
            )
        ]
    )

    assert nothing["kappa"] is degenerate["kappa"] is None
    assert nothing["undefined_because"] != degenerate["undefined_because"]
    assert nothing["re_labelled_ads"] == 0
    assert degenerate["re_labelled_ads"] == 1


def test_self_agreement_is_undefined_until_something_is_labelled_twice() -> None:
    """Reported as `None`, never rounded up to perfect agreement."""
    report = self_agreement(
        [
            ad(
                labels=[
                    Label(
                        dimension="on_call_load",
                        value=0.5,
                        spans=[Span(start=0, end=2)],
                        labeller="test",
                    )
                ]
            )
        ]
    )

    assert report["kappa"] is None
    assert report["compared_labels"] == 0


def test_self_agreement_corrects_for_chance() -> None:
    """Kappa, not raw agreement — most dimensions are absent on most ads.

    Two passes that both score everything zero agree completely and have
    learned nothing; kappa reports that as 0, raw agreement as 1.0.
    """

    def two_rounds(ad_id: str, first: float, second: float) -> LabelledAd:
        return ad(
            ad_id=ad_id,
            labels=[
                Label(
                    dimension="on_call_load",
                    value=first,
                    spans=[Span(start=0, end=2)],
                    labeller="owner",
                    round=1,
                ),
                Label(
                    dimension="on_call_load",
                    value=second,
                    spans=[Span(start=0, end=2)],
                    labeller="owner",
                    round=2,
                ),
            ],
        )

    all_zero = [two_rounds(f"z{i}", 0.0, 0.0) for i in range(4)]
    report = self_agreement(all_zero)
    assert report["raw_agreement"] == 1.0
    assert report["kappa"] is None, "kappa is 0/0 here and must not be reported as agreement"
    assert "one category" in report["undefined_because"]

    mixed = [two_rounds("a", 0.8, 0.8), two_rounds("b", 0.0, 0.0), two_rounds("c", 0.8, 0.0)]
    report = self_agreement(mixed)
    assert report["compared_labels"] == 3
    assert 0.0 < report["kappa"] < 1.0


def test_label_evidence_counts_labels_per_dimension_not_spans(tmp_path: Path) -> None:
    """`labels_by_dimension` counts judgements, not the spans evidencing them.

    D-2 makes T15 refuse `extraction_macro_f1` for any dimension below a label
    floor, so the floor has to be counted in the unit a human actually decides
    in. One label carrying three spans of the same ad is one judgement; counting
    spans would let a single well-evidenced ad clear a floor on its own.
    """
    store = tmp_path / "ads.jsonl"
    save_store(
        [
            ad(
                ad_id="test-1",
                labels=[
                    Label(
                        dimension="on_call_load",
                        value=0.8,
                        spans=[Span(start=0, end=2), Span(start=3, end=5), Span(start=6, end=8)],
                        labeller="owner",
                        source="confirmed",
                    )
                ],
            )
        ],
        store,
    )

    measured = measure_labels(store)

    assert measured["labels_by_dimension"]["on_call_load"] == 1
    assert measured["label_count"] == 1
    assert measured["span_count"] == 3
    assert measured["labels_by_source"] == {"confirmed": 1}


def test_label_evidence_names_the_dimensions_nobody_has_labelled(tmp_path: Path) -> None:
    """A dimension with no label is named, not left to be inferred from absence.

    The list is what tells a reader of `status/evidence/T5.json` which
    dimensions `extraction_macro_f1` cannot be computed for at all — the
    difference between a gate that failed and one that was never measurable.
    """
    store = tmp_path / "ads.jsonl"
    save_store([ad(labels=[])], store)

    measured = measure_labels(store)

    assert measured["label_count"] == 0
    assert "on_call_load" in measured["dimensions_without_labels"]
    assert measured["corpus_size"] == 1


def test_bare_harness_run_writes_both_files_for_the_store_it_was_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No subcommand writes T4 *and* T5, and both honour `--store`.

    This is the shape `make evidence` invokes: the target greps `^def _main`
    and runs each module with no arguments. While this one required a
    subcommand it stayed outside that loop, and `T4.json` sat committed at
    `label_count: 0` against a store holding 39 of them.

    `--store` is a top-level flag, and the bare run reaches its two gates by
    re-dispatching. Rebuilding that argv without the flag would measure the
    committed corpus instead of the one named — writing numbers about the wrong
    file while exiting 0, which is the failure mode evidence files cannot have.
    """
    store = tmp_path / "ads.jsonl"
    save_store([ad(ad_id="only-one")], store)
    t4, t5 = tmp_path / "T4.json", tmp_path / "T5.json"
    monkeypatch.setattr("integral.harness.DEFAULT_EVIDENCE_PATH", t4)
    monkeypatch.setattr("integral.harness.LABEL_EVIDENCE_PATH", t5)

    assert main(["--store", str(store)]) == 0

    assert json.loads(t4.read_text())["ad_count"] == 1
    measured = json.loads(t5.read_text())
    assert measured["corpus_size"] == 1
    assert measured["labelled_ad_count"] == 0


def test_bare_run_reports_the_worse_of_its_two_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty store exits non-zero rather than writing two files and passing.

    Both gates treat an empty corpus as unmeasured (exit 3), and the bare run
    takes the maximum, so one failing gate cannot be hidden by the other
    succeeding.
    """
    store = tmp_path / "ads.jsonl"
    save_store([], store)
    monkeypatch.setattr("integral.harness.DEFAULT_EVIDENCE_PATH", tmp_path / "T4.json")
    monkeypatch.setattr("integral.harness.LABEL_EVIDENCE_PATH", tmp_path / "T5.json")

    assert main(["--store", str(store)]) == 3
