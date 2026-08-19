#!/usr/bin/env python3
"""T5's labelling aid — read the ad, react to what is already marked on it.

T5 (`arsenal/tasks/_history/lo-d2b2.md`) is `[HUMAN]`: a person must decide which
dimensions each of the 100 ads in `corpus/labelled/ads.jsonl` evidences, and
supply a verbatim quote for every value.

The first version of this page asked that question dimension-first: 22 cards
beside each ad, each offering a value box and a *use selection* button. That is
2,200 decisions across the corpus to record the five or six per ad that are
really there, and it required the labeller to hold all 22 dimensions in mind to
notice which ones an ad had evidenced. The reading was fast; the searching was
not.

This version inverts it. The ad arrives already marked: each pre-marked span is
highlighted in the text and carries a chip naming the dimension and the rung
proposed for it. The labeller reads once and reacts — confirm, change, delete —
and selects text only for what the marks missed. Selecting text opens a picker
grouped into five titled sections, so a dimension can be found without already
knowing its name.

Two things this page will not do:

* **It never prefills from a cue.** `extraction_macro_f1` (T15) is measured
  against this corpus, so a labeller confirming `Dimension.extraction.cues`
  output would make the gate score the extractor against itself (D-2,
  `status/plan.md`). Earlier versions guarded this by keeping cue *values* out
  of the page; this one carries no cue data at all — no patterns, no values, no
  highlighting derived from them. The marks come from
  `corpus/labelled/suggestions.json`, whose provenance is recorded and whose
  overlap with the cues is measured by `jobsearch.suggestions.cue_agreement`.
* **It never exports something nobody looked at.** A suggestion is `pending`
  until the labeller acts on it, and only confirmed or edited annotations reach
  the export. `Label.source` then records which, so "the labeller agreed with
  92% of suggestions" can be read against blind agreement on the control ads
  rather than taken on trust.

Usage:
    uv run python tools/labelling_page.py                 # -> corpus/labelled/label.html
    uv run python tools/labelling_page.py --out /tmp/x.html
    uv run python tools/labelling_page.py --no-suggestions   # blind: mark nothing

The generated file is gitignored — a build artefact of the corpus, the dimension
model and the suggestions, regenerable from them at any time. The labeller's
work lives in the browser's `localStorage` until it is exported and applied with
`harness import`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from jobsearch.dimensions import DEFAULT_DIMENSIONS_DIR, GROUPS, Dimension, load_dimensions
from jobsearch.harness import DEFAULT_STORE_PATH, LabelledAd, load_store
from jobsearch.suggestions import (
    DEFAULT_SUGGESTIONS_PATH,
    SuggestionSet,
    load_suggestions,
    validate_suggestions,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_PATH = _REPO_ROOT / "corpus" / "labelled" / "label.html"

# Section headings for the picker, in the order they are offered. Ordered by how
# often an ad settles one: an ad names its contract and location far more often
# than it says anything about mentoring, so the sections a labeller reaches for
# most sit where the thumb already is.
GROUP_TITLES: dict[str, str] = {
    "dealbreakers": "Deal-breakers",
    "terms": "Terms & load",
    "the_work": "The work itself",
    "people": "People & team",
    "growth": "Growth & meaning",
}


def _dimension_payload(dimensions: list[Dimension]) -> list[dict[str, Any]]:
    """What the page needs to *offer* a dimension: name, definition, rungs, group.

    Restricted to `side == "matched"` — the dimensions an ad's own wording can
    evidence. A `candidate_trait` is elicited from the person and a
    `candidate_fact` is compared against an ad-side requirement, so neither has
    anything to ask of a page that reads ad text.

    Note what is absent: `extraction.cues`. Not filtered down to safe fields —
    absent. The page has no cue patterns and no cue values, so no rendering path
    and no future edit to this file can derive a mark from the extractor whose
    accuracy this corpus is meant to measure.
    """
    return [
        {
            "id": dimension.id,
            "group": dimension.group,
            "label": dimension.label.en,
            "definition": " ".join(dimension.definition.split()),
            "polarity": dimension.polarity,
            "kind": dimension.kind,
            "levels": [
                {"value": level.value, "label": level.label.en, "tell": level.tell}
                for level in dimension.levels
            ],
        }
        for dimension in dimensions
        if dimension.side == "matched"
    ]


def _ad_payload(ads: list[LabelledAd]) -> list[dict[str, Any]]:
    """The ad fields the page renders, sorted by id for a stable jump list."""
    return [
        {
            "id": ad.id,
            "language": ad.language,
            "split": ad.split,
            "title": ad.title,
            "source": ad.source,
            "source_url": ad.source_url,
            "text": ad.text,
            "labels": _banked_payload(ad),
        }
        for ad in sorted(ads, key=lambda a: a.id)
    ]


def _banked_payload(ad: LabelledAd) -> list[dict[str, Any]]:
    """The labels already in the store, as the page's own annotation shape.

    Without this the page is amnesiac: every rebuild — a new suggestion set, a
    new dimension, a fix to the page itself — hands back a corpus the labeller
    has already worked through, with their decisions visible only in whatever
    `localStorage` happened to survive. The first labelling session ended
    exactly there, with the page gone and an export the page could not read
    back. The store is the durable memory; this is the page reading it.

    Each span is shipped as `(quote, nth)` rather than as offsets, for the
    reason `_suggestion_payload` gives — a Python offset counts code points and
    a JavaScript one counts UTF-16 units, and the corpus is full of astral
    emoji. `nth` disambiguates a quote that occurs more than once, so a repeated
    phrase resolves to the span that was actually labelled rather than to the
    first match, and the span stays exactly as wide as the labeller drew it.

    `labeller` and `round` travel with each span because the export rebuilds
    every row from the page's two header inputs. Without them, opening the page
    in round 2 and exporting would re-stamp round-1 labels as round 2 — and
    since `import_labels` replaces by `(ad, dimension, round)`, that writes a
    duplicate into round 2 while round 1 sits untouched, quietly corrupting the
    round-over-round self-agreement measurement.
    """
    banked: list[dict[str, Any]] = []
    for label in ad.labels:
        for span in label.spans:
            quote = ad.text[span.start : span.end]
            banked.append(
                {
                    "dimension": label.dimension,
                    "value": label.value,
                    "quote": quote,
                    "nth": ad.text[: span.start].count(quote),
                    "negated": label.negated,
                    "source": label.source,
                    "labeller": label.labeller,
                    "round": label.round,
                }
            )
    return sorted(banked, key=lambda b: (b["quote"], b["nth"]))


def _suggestion_payload(
    suggestions: SuggestionSet | None,
    ads: list[LabelledAd],
) -> dict[str, Any]:
    """Marks per ad, resolved to offsets, plus the control ads left bare.

    The quote is shipped, and the browser resolves it to offsets itself. That
    is not a stylistic choice — a Python offset is a **code-point** index and a
    JavaScript one is a **UTF-16 code-unit** index, and the corpus is full of
    emoji outside the BMP (the Manfred ads open with 📢, and 🫵🏾 is two
    surrogate pairs on its own). Every such character before a span makes the
    JS index one unit larger than the Python one, so an offset computed here
    and used there lands progressively further left the deeper into the ad it
    is — silently citing the wrong words while still looking plausible. It is
    the same failure the corpus README rules out for byte offsets, one encoding
    layer up. Passing the quote keeps each side in its own index space, exactly
    as `harness import` already does.

    What is still checked here is uniqueness, because this is where a problem
    can be reported with its reason visible. A quote that does not locate
    cleanly is dropped rather than marked at a guessed position: a missing mark
    shows up as untagged text the labeller will read anyway, while a wrong one
    reads as somebody else's judgement.
    """
    if suggestions is None:
        return {"method": "none", "control": [ad.id for ad in ads], "marks": {}, "dropped": []}

    marks: dict[str, list[dict[str, Any]]] = {}
    dropped: list[str] = []
    by_id = {ad.id: ad for ad in ads}
    for ad_id, proposed in suggestions.by_ad.items():
        ad = by_id.get(ad_id)
        if ad is None:
            continue
        placed: list[dict[str, Any]] = []
        for suggestion in proposed:
            if ad.text.count(suggestion.quote) != 1:
                dropped.append(f"{ad_id}:{suggestion.dimension}")
                continue
            placed.append(
                {
                    "dimension": suggestion.dimension,
                    "value": suggestion.value,
                    "quote": suggestion.quote,
                    "negated": suggestion.negated,
                    "confidence": suggestion.confidence,
                    "note": suggestion.note,
                }
            )
        if placed:
            marks[ad_id] = sorted(placed, key=lambda m: ad.text.index(m["quote"]))
    return {
        "method": suggestions.method,
        "control": sorted(suggestions.blind_control),
        "marks": marks,
        "dropped": sorted(dropped),
    }


def _embed_json(data: dict[str, Any]) -> str:
    """Serialise `data` for a `<script type="application/json">` block.

    The HTML tokenizer ends a `<script>` element at the first literal
    `</script` it sees, case-insensitively, regardless of the element's `type` —
    the corpus is arbitrary scraped text and nothing rules out that substring
    appearing in it. Escaping the slash is inert to `JSON.parse`, which reads
    backslash-slash as a literal `/`, and stops that substring closing the tag.
    """
    return json.dumps(data, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")


def build_page(
    ads: list[LabelledAd],
    dimensions: list[Dimension],
    suggestions: SuggestionSet | None = None,
) -> str:
    """Render the full standalone HTML page."""
    data = {
        "ads": _ad_payload(ads),
        "dimensions": _dimension_payload(dimensions),
        "groups": [{"id": group, "title": GROUP_TITLES[group]} for group in GROUPS],
        "suggestions": _suggestion_payload(suggestions, ads),
    }
    return (
        _HEAD
        + '<script type="application/json" id="jobsearch-data">'
        + _embed_json(data)
        + "</script>\n"
        + _BODY
        + "<script>\n"
        + _SCRIPT
        + "\n</script>\n"
        + _TAIL
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the T5 labelling page.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE_PATH)
    parser.add_argument("--dimensions", type=Path, default=DEFAULT_DIMENSIONS_DIR)
    parser.add_argument("--suggestions", type=Path, default=DEFAULT_SUGGESTIONS_PATH)
    parser.add_argument(
        "--no-suggestions",
        action="store_true",
        help="mark nothing — every ad is labelled cold, as the control ads are",
    )
    args = parser.parse_args(argv)

    ads = load_store(args.store)
    dimensions = load_dimensions(args.dimensions)

    suggestions = None
    if not args.no_suggestions:
        explicit = args.suggestions != DEFAULT_SUGGESTIONS_PATH
        if args.suggestions.exists():
            suggestions = load_suggestions(args.suggestions)
        elif explicit:
            # A path the operator typed and that is not there is a mistake, not a
            # request for blind mode. Blind mode has its own flag.
            print(f"suggestions file not found: {args.suggestions}", file=sys.stderr)
            return 2
        else:
            print(
                f"no {DEFAULT_SUGGESTIONS_PATH.name} yet — every ad will be blind. "
                "Pass --no-suggestions to say you meant that.",
                file=sys.stderr,
            )

    # The validator is the only thing that checks a suggestion set means what it
    # says: known dimensions, values on declared rungs, quotes that locate
    # exactly once, a control cohort that is really the cohort, and no
    # cue-derived mark on the evaluation split. Building the page without it
    # would let a broken set reach the labeller looking perfectly ordinary —
    # and a labeller confirming a contaminated mark is exactly the failure the
    # whole suggestion design exists to prevent. `_suggestion_payload` also
    # drops quotes it cannot place, so a build that skipped this check could
    # quietly ship fewer marks than the file promised.
    if suggestions is not None:
        problems = validate_suggestions(suggestions, ads, dimensions)
        if problems:
            print(
                f"{args.suggestions} has {len(problems)} violation(s); no page written:",
                file=sys.stderr,
            )
            for problem in problems:
                print(f"  {problem}", file=sys.stderr)
            return 2

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(build_page(ads, dimensions, suggestions), encoding="utf-8")

    marked = sum(len(v) for v in _suggestion_payload(suggestions, ads)["marks"].values())
    control = len(suggestions.blind_control) if suggestions else len(ads)
    print(f"{args.out}  ({len(ads)} ads, {marked} marks, {control} control ads)")
    if suggestions is None:
        print("  no suggestions applied — every ad is blind", flush=True)
    else:
        dropped = _suggestion_payload(suggestions, ads)["dropped"]
        if dropped:
            print(f"  {len(dropped)} mark(s) dropped as unlocatable: {', '.join(dropped[:5])}")
    return 0


_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>T5 labelling</title>
<style>
:root {
  color-scheme: light dark;
  --bg: #f7f7f5; --panel: #fff; --border: #d8d8d2; --text: #1c1c1a; --muted: #66665f;
  --accent: #2f6f4f; --accent-contrast: #fff; --danger: #a4302a;
  --warn-bg: #fff4e0; --warn-border: #d9a441;
  --g-dealbreakers: #b5453c; --g-terms: #9a6a1e; --g-the_work: #2f6f4f;
  --g-people: #2b5f8f; --g-growth: #6b4694;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #1b1c19; --panel: #242520; --border: #3a3b34; --text: #ecece6; --muted: #b0b0a4;
    --accent: #7fd0a3; --accent-contrast: #10241a; --danger: #e08a84;
    --warn-bg: #3a3016; --warn-border: #b98b2c;
    --g-dealbreakers: #e08a84; --g-terms: #dcb463; --g-the_work: #7fd0a3;
    --g-people: #8fb8e0; --g-growth: #bda3e0;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--text); line-height: 1.5;
  font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
header {
  position: sticky; top: 0; z-index: 30; background: var(--panel);
  border-bottom: 1px solid var(--border); padding: 0.6rem 1rem;
}
.bar { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
h1 { font-size: 1rem; margin: 0 0.5rem 0 0; }
.count { font-size: 0.85rem; color: var(--muted); }
.count b { color: var(--text); }
button {
  font: inherit; padding: 0.35rem 0.7rem; border-radius: 6px; cursor: pointer;
  border: 1px solid var(--border); background: var(--panel); color: var(--text);
}
button.primary {
  background: var(--accent); color: var(--accent-contrast); border-color: var(--accent);
}
button.danger { color: var(--danger); border-color: var(--danger); }
button:disabled { opacity: 0.45; cursor: not-allowed; }
input, select { font: inherit; padding: 0.3rem 0.4rem; border-radius: 5px;
  border: 1px solid var(--border); background: var(--panel); color: var(--text); max-width: 100%; }
main { display: grid; grid-template-columns: minmax(0,1.55fr) minmax(0,1fr);
  gap: 1rem; margin: 1rem; align-items: start; }
@media (max-width: 950px) { main { grid-template-columns: 1fr; } }
.card { background: var(--panel); border: 1px solid var(--border);
  border-radius: 10px; padding: 1rem; }
.ad-meta { font-size: 0.8rem; color: var(--muted); margin-bottom: 0.5rem; }
.ad-meta a { color: var(--accent); }
.ad-text { white-space: pre-wrap; font-size: 1rem; user-select: text; }

/* A mark in the ad text. Pending is dashed and colourless on purpose: the
   labeller must be able to tell at a glance what they have decided from what a
   machine proposed, without reading a legend. */
mark.ann {
  background: transparent; color: inherit; padding: 0.05em 0; border-radius: 3px;
  border-bottom: 2px dashed var(--muted); cursor: pointer;
}
mark.ann.confirmed { border-bottom: 2px solid var(--hue);
  background: color-mix(in srgb, var(--hue) 14%, transparent); }
mark.ann.focused { outline: 2px solid var(--hue); outline-offset: 2px; }
.chip {
  display: inline-block; vertical-align: baseline; margin-left: 0.25em;
  font-size: 0.68em; line-height: 1.5; padding: 0 0.4em; border-radius: 999px;
  background: color-mix(in srgb, var(--hue) 18%, transparent);
  color: var(--hue); border: 1px solid var(--hue); white-space: nowrap; user-select: none;
}
mark.ann:not(.confirmed) .chip { border-style: dashed; opacity: 0.75; }

.anns { list-style: none; margin: 0; padding: 0; }
.ann-row { border: 1px solid var(--border); border-left: 3px solid var(--hue);
  border-radius: 8px; padding: 0.5rem 0.6rem; margin-bottom: 0.5rem; }
.ann-row.focused { box-shadow: 0 0 0 2px var(--hue); }
.ann-row.pending { border-left-style: dashed; }
.ann-dim { font-weight: 600; font-size: 0.9rem; color: var(--hue); }
.ann-rung { font-size: 0.85rem; }
.ann-quote { font-size: 0.8rem; font-style: italic; color: var(--muted);
  margin: 0.25rem 0; overflow-wrap: anywhere; }
.ann-acts { display: flex; gap: 0.35rem; flex-wrap: wrap; }
.ann-acts button { padding: 0.2rem 0.5rem; font-size: 0.82rem; }
.state { font-size: 0.72rem; text-transform: uppercase;
  letter-spacing: 0.04em; color: var(--muted); }

/* The picker. Fixed rather than anchored to the selection: an anchored popup
   near the bottom of a long ad ends up off-screen, and on a phone it fights the
   native selection handles. */
.picker { position: fixed; inset: auto 0 0 0; z-index: 60; max-height: 72vh;
  display: none; flex-direction: column; background: var(--panel);
  border-top: 1px solid var(--border); box-shadow: 0 -4px 24px rgba(0,0,0,.22); }
.picker.open { display: flex; }
@media (min-width: 700px) {
  .picker { inset: auto auto 1.5rem 50%; transform: translateX(-50%);
    width: min(38rem, 92vw); border: 1px solid var(--border); border-radius: 12px; }
}
.picker-head { padding: 0.6rem 0.8rem; border-bottom: 1px solid var(--border); }
.picker-head .sel { font-size: 0.8rem; color: var(--muted); font-style: italic;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-bottom: 0.4rem; }
.picker-head input { width: 100%; font-size: 16px; }
.picker-body { overflow-y: auto; padding: 0.4rem 0.5rem 0.8rem; }
.grp { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em;
  color: var(--hue); margin: 0.7rem 0.3rem 0.3rem; font-weight: 600; }
.opt { display: block; width: 100%; text-align: left; border: 0; background: transparent;
  padding: 0.45rem 0.5rem; border-radius: 6px; }
.opt:hover, .opt.active { background: color-mix(in srgb, var(--hue) 14%, transparent); }
.opt .name { font-weight: 600; font-size: 0.92rem; }
.opt .def { display: block; font-size: 0.78rem; color: var(--muted); }
.opt.hidden { display: none; }
.rung .name { font-weight: 600; }
.rung .tell { display: block; font-size: 0.78rem; color: var(--muted); }
.picker-foot { padding: 0.5rem 0.8rem; border-top: 1px solid var(--border);
  display: flex; gap: 0.5rem; justify-content: space-between; align-items: center; }
.newdim { padding: 0.6rem 0.8rem; display: none; }
.newdim.open { display: block; }
.newdim label { display: block; font-size: 0.8rem; margin-bottom: 0.45rem; }
.newdim input, .newdim select { width: 100%; }

.notice { margin: 0 1rem; padding: 0.6rem 0.8rem; border-radius: 8px;
  border: 1px solid var(--warn-border); background: var(--warn-bg); font-size: 0.85rem; }
.howto { margin: 1rem; } .howto summary { cursor: pointer; font-weight: 600; }
.howto li { margin-bottom: 0.4rem; }
.glossary { margin-top: 0.8rem; }
.glossary summary { cursor: pointer; font-size: 0.85rem; color: var(--muted); }
.gloss-row { font-size: 0.8rem; padding: 0.3rem 0; border-bottom: 1px solid var(--border); }
.gloss-row b { color: var(--hue); }
textarea { width: 100%; min-height: 7rem; font-family: ui-monospace, monospace;
  font-size: 0.75rem; background: var(--bg); color: var(--text);
  border: 1px solid var(--border); border-radius: 8px; }
footer { text-align: center; font-size: 0.75rem; color: var(--muted); padding: 1rem 1rem 5rem; }
@media (max-width: 700px) {
  header { position: static; }
  button { min-height: 44px; } .ann-acts button { min-height: 38px; }
  input, select { font-size: 16px; min-height: 40px; }
  main { margin: 0.75rem; }
}
</style>
</head>
<body>
"""


_BODY = """<header>
  <div class="bar">
    <h1>T5 labelling</h1>
    <button id="prev">&larr;</button>
    <button id="next">&rarr;</button>
    <button id="nextTodo" class="primary">next unresolved &rarr;</button>
    <span class="count" id="count"></span>
    <label class="count">as <input id="labeller" value="owner" size="7"></label>
    <label class="count">round
      <input id="round" type="number" value="1" min="1" style="width:3.4rem"></label>
    <select id="jump" style="max-width:min(20rem,50vw)"></select>
  </div>
</header>

<div class="notice" id="controlNotice" hidden></div>

<details class="howto card">
  <summary>How this works &mdash; click to collapse</summary>
  <ol>
    <li><strong>Read the ad.</strong> Some passages arrive already marked, each
      with a chip naming a dimension and the rung proposed for it. A dashed mark
      is a <em>proposal</em>; nothing dashed is counted or exported.</li>
    <li><strong>React to each mark.</strong> <kbd>Enter</kbd> confirms the
      focused one, <kbd>Backspace</kbd> deletes it, <kbd>c</kbd> changes it.
      <kbd>j</kbd>/<kbd>k</kbd> move between marks. A confirmed mark turns solid
      and is coloured by its group.</li>
    <li><strong>Select text the marks missed</strong> and pick a dimension from
      the sections that appear, then a rung. You never type a number: each
      dimension lists the named positions its scale actually has, with a line
      saying what each looks like in an ad.</li>
    <li><strong>Coin a new dimension</strong> with <em>+ new dimension</em> at
      the bottom of the picker when an ad says something none of the existing
      ones can hold. It is recorded in the export as a proposal, together with
      the ad you coined it at, so the earlier ads can be swept for it rather
      than re-read.</li>
    <li><strong>Leave the rest alone.</strong> Most ads evidence a handful of the
      22. Untouched is a real answer and the commonest one.</li>
  </ol>
  <p><strong>Where the marks come from.</strong> They are read from
    <code>corpus/labelled/suggestions.json</code> and are <em>not</em> produced by
    the extractor's own cue regexes &mdash; this page carries no cue data at all.
    Confirming the extractor's output would make <code>extraction_macro_f1</code>
    score it against itself (D-2). Some ads deliberately arrive with no marks so
    your agreement rate has a baseline; the page says so when you reach one.</p>
  <p><strong>Stopping and resuming.</strong> Work is saved in this browser as you
    go. Export when you are done and apply it with
    <code>uv run python -m jobsearch.harness import &lt;file&gt;</code>. Once applied,
    it is in the corpus: every page built after that arrives with those labels
    already placed and marked <em>banked</em>, so a lost tab costs you nothing
    since the last export. <em>restore</em> below reads an export file straight
    back into the page if you need it sooner than that.</p>
</details>

<main>
  <section class="card">
    <div class="ad-meta" id="adMeta"></div>
    <div class="ad-text" id="adText"></div>
    <details class="glossary">
      <summary>What every dimension means</summary>
      <div id="glossary"></div>
    </details>
  </section>

  <section class="card">
    <div class="bar" style="justify-content:space-between;margin-bottom:0.6rem">
      <strong id="annHead">On this ad</strong>
      <button id="confirmAll">confirm all pending</button>
    </div>
    <ul class="anns" id="anns"></ul>
    <p class="count" id="annEmpty"></p>
    <details style="margin-top:1rem">
      <summary class="count">Export &amp; restore</summary>
      <p class="count">Only annotations you confirmed or edited are included.</p>
      <textarea id="export" readonly></textarea>
      <div class="bar" style="margin-top:0.4rem">
        <button id="build" class="primary">build export</button>
        <button id="copy">copy</button>
        <button id="download">download</button>
        <span class="count" id="exportNote"></span>
      </div>
      <div class="bar" style="margin-top:0.6rem">
        <label class="count">restore from an export file
          <input id="restore" type="file" accept="application/json,.json"></label>
        <span class="count" id="restoreNote"></span>
      </div>
    </details>
  </section>
</main>

<div class="picker" id="picker">
  <div class="picker-head">
    <div class="sel" id="pickerSel"></div>
    <input id="pickerSearch" autocomplete="off"
      placeholder="type to filter, or scroll the sections">
  </div>
  <div class="picker-body" id="pickerBody"></div>
  <div class="newdim" id="newdim">
    <label>id (snake_case) <input id="ndId" placeholder="e.g. childcare_support"></label>
    <label>name <input id="ndLabel" placeholder="e.g. Childcare support"></label>
    <label>what it means <input id="ndDef" placeholder="one line a later reader can apply"></label>
    <label>section
      <select id="ndGroup"></select>
    </label>
    <label>rungs, weakest first, comma separated
      <input id="ndRungs" value="Absent, Mentioned, Concrete">
    </label>
  </div>
  <div class="picker-foot">
    <button id="pickerNew">+ new dimension</button>
    <button id="pickerClose">close</button>
  </div>
</div>

<footer id="footer"></footer>
"""

_TAIL = """</body>
</html>
"""


_SCRIPT = r"""
'use strict';
const DATA = JSON.parse(document.getElementById('jobsearch-data').textContent);
const DIMS = new Map(DATA.dimensions.map(d => [d.id, d]));
const ADS = DATA.ads;
const MARKS = DATA.suggestions.marks || {};
// Labels already applied to the corpus with `harness import`. They are not
// proposals: somebody already decided them, so they arrive confirmed and the
// suggestion for that dimension is dropped rather than re-offered.
const BANKED = Object.fromEntries(DATA.ads.map(a => [a.id, a.labels || []]));
const CONTROL = new Set(DATA.suggestions.control || []);
const STORE_KEY = 'jobsearch.t5.labels.v2';

let state = loadState();
let current = 0;
let focused = -1;
let picker = null;   // {kind:'new', start, end} | {kind:'change', index}
const drift = {};    // adId -> {relocated, lost}, reported to the labeller

// ── state ─────────────────────────────────────────────────────────────────────────────────────

function loadState() {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (raw) return JSON.parse(raw);
  } catch (err) { /* a corrupt or blocked store must not stop the page loading */ }
  return migrateV1();
}

// The previous page saved under `jobsearch-t5-labels-v1`, shaped
// `{adId: {dimId: {value, negated, quote, ...}}}`. Reading only the new key
// would leave that work stranded in the browser while the page looked empty,
// and the labeller could then export a replacement corpus missing everything
// they had already done. So it is carried over rather than abandoned.
//
// Carried over as **pending**, not confirmed. The old page took any float from
// -1 to 1; the scale is now a set of named rungs, so a migrated value may sit
// between two of them and there is no honest way to pick one on the labeller's
// behalf. Each one is placed on its nearest rung and put back in front of them
// to re-confirm — which is a few keystrokes per label, against losing the span
// and the judgement entirely.
function migrateV1() {
  const fresh = { byAd: {}, coined: [] };
  let raw = null;
  try { raw = localStorage.getItem('jobsearch-t5-labels-v1'); } catch (err) { return fresh; }
  if (!raw) return fresh;

  let old;
  try { old = JSON.parse(raw); } catch (err) { return fresh; }
  let carried = 0;
  for (const [adId, byDimension] of Object.entries(old || {})) {
    const ad = ADS.find(a => a.id === adId);
    if (!ad) continue;
    const anns = [];
    for (const [dimensionId, label] of Object.entries(byDimension || {})) {
      const dim = DIMS.get(dimensionId);
      if (!dim || !label || typeof label.quote !== 'string') continue;
      const at = ad.text.indexOf(label.quote);
      if (at < 0 || ad.text.indexOf(label.quote, at + 1) >= 0) continue;
      const nearest = dim.levels.reduce((best, level) =>
        Math.abs(level.value - label.value) < Math.abs(best.value - label.value) ? level : best);
      anns.push({
        dimension: dimensionId, value: nearest.value,
        start: at, end: at + label.quote.length, quote: label.quote,
        negated: !!label.negated, status: 'pending', origin: null,
        note: `carried over from the previous page (was ${label.value})`,
      });
      carried++;
    }
    if (anns.length) fresh.byAd[adId] = anns;
  }
  fresh.migrated = carried;
  return fresh;
}

function save() {
  try { localStorage.setItem(STORE_KEY, JSON.stringify(state)); }
  catch (err) { note('could not save to this browser — export before closing the tab'); }
}

// An ad is seeded from its marks the first time it is opened, never again:
// re-seeding would resurrect a proposal the labeller deliberately deleted.
function annotations(adId) {
  if (!state.byAd[adId]) {
    // Offsets are resolved here, not shipped. A Python offset counts code
    // points and a JS offset counts UTF-16 units, so an emoji outside the BMP —
    // and these ads are full of them — makes the two disagree by one unit each,
    // sliding every later span leftwards into the wrong words. Locating the
    // quote in the browser's own string keeps one index space throughout.
    const ad = ADS.find(a => a.id === adId);
    // Banked labels come first and arrive confirmed: they are decisions this
    // labeller already made and applied to the corpus, not something to react
    // to again. A suggestion for a dimension they have already decided is
    // dropped — offering it back would ask them to re-litigate their own work.
    const banked = (BANKED[adId] || []).flatMap(b => {
      const start = nthIndexOf(ad.text, b.quote, b.nth);
      if (start < 0) return [];
      return [{
        dimension: b.dimension, value: b.value, start, end: start + b.quote.length,
        quote: b.quote, negated: !!b.negated, status: 'confirmed', note: '',
        banked: b.source || 'human', labeller: b.labeller, round: b.round,
        // The snapshot is what lets a *correction* to a banked label report as
        // `edited`. Without it the stored source rides along unchanged, so
        // fixing a label that had been `confirmed` still exports as
        // `confirmed`, inflating the one number the control cohort exists to
        // make readable.
        origin: {
          dimension: b.dimension, value: b.value,
          quote: b.quote, negated: !!b.negated,
        },
      }];
    });
    const decided = new Set(banked.map(b => b.dimension));
    state.byAd[adId] = banked.concat((MARKS[adId] || []).flatMap(m => {
      if (decided.has(m.dimension)) return [];
      const start = ad.text.indexOf(m.quote);
      if (start < 0) return [];
      const end = start + m.quote.length;
      return [{
        dimension: m.dimension, value: m.value, start, end, quote: m.quote,
        negated: !!m.negated, status: 'pending', note: m.note || '',
        origin: {
          dimension: m.dimension, value: m.value,
          quote: m.quote, negated: !!m.negated,
        },
      }];
    }));
    save();
  }
  return reconcile(mergeBanked(adId));
}

// Which ads have had their banked labels folded into an already-saved state,
// this page load. Session-scoped on purpose: a banked row deleted during the
// session stays deleted while you work, and comes back on reload, which is
// honest -- the corpus still holds it, and removing it for good means removing
// it from the corpus.
const bankedMerged = new Set();

// Seeding only runs the first time an ad is opened, so an ad already carrying a
// saved state -- every ad the labeller has touched -- would never see BANKED at
// all. That is precisely the case banking exists for: work exported, imported,
// and the page rebuilt around it. So banked labels are folded into an existing
// state too, adding any dimension the state does not already hold and retiring
// the proposals it answers.
function mergeBanked(adId) {
  if (bankedMerged.has(adId)) return adId;
  bankedMerged.add(adId);
  const banked = BANKED[adId] || [];
  if (!banked.length) return adId;

  const ad = ADS.find(a => a.id === adId);
  const anns = state.byAd[adId] || [];
  const held = new Set(anns.map(a => a.dimension));
  const added = [];
  for (const b of banked) {
    if (held.has(b.dimension)) continue;
    const start = nthIndexOf(ad.text, b.quote, b.nth);
    if (start < 0) continue;
    added.push({
      dimension: b.dimension, value: b.value, start, end: start + b.quote.length,
      quote: b.quote, negated: !!b.negated, status: 'confirmed', note: '',
      banked: b.source || 'human', labeller: b.labeller, round: b.round,
      origin: {
        dimension: b.dimension, value: b.value,
        quote: b.quote, negated: !!b.negated,
      },
    });
  }
  if (!added.length) return adId;
  const decided = new Set(added.map(a => a.dimension));
  state.byAd[adId] = added.concat(anns.filter(a => !(decided.has(a.dimension) && isProposal(a))));
  save();
  return adId;
}

// An untouched suggestion: something the page put there that nobody has acted
// on. Never a label the labeller made themselves, which must survive.
function isProposal(a) {
  return a.status !== 'confirmed' && !!a.origin && !a.banked && !a.restored;
}

// Saved offsets only mean anything against the text they were taken from, and
// the store is keyed by ad id alone — so a page regenerated over a re-fetched
// corpus can hand the same id different text, and the old numbers would then
// mark, and export, whatever now sits at those positions. Previously confirmed
// work would become confidently wrong labels.
//
// Every annotation therefore carries the quote it was placed on, and is checked
// against the current text each time the ad is opened: unchanged ones pass
// untouched, ones whose words merely moved are relocated by that quote, and
// ones whose words are gone (or have become ambiguous) are dropped and reported
// to the labeller rather than silently sliced.
function reconcile(adId) {
  const ad = ADS.find(a => a.id === adId);
  const anns = state.byAd[adId] || [];
  if (!ad) return anns;

  let relocated = 0;
  const kept = [];
  for (const a of anns) {
    if (a.quote === undefined) { kept.push(a); continue; }
    if (ad.text.slice(a.start, a.end) === a.quote) { kept.push(a); continue; }
    const at = ad.text.indexOf(a.quote);
    if (at < 0 || ad.text.indexOf(a.quote, at + 1) >= 0) continue;
    kept.push({ ...a, start: at, end: at + a.quote.length });
    relocated++;
  }

  const lost = anns.length - kept.length;
  if (!relocated && !lost) return anns;   // the live array, not the copy

  // Only on real drift is the stored array replaced. Returning `kept`
  // unconditionally would hand every caller a detached copy, and an annotation
  // pushed onto it — every one the labeller creates — would be dropped on the
  // next render.
  state.byAd[adId] = kept;
  drift[adId] = { relocated, lost };
  save();
  return kept;
}

// Provenance is *derived*, never stored as a flag the UI could set wrongly: an
// annotation that still matches the proposal it came from is `confirmed`, one
// that has moved is `edited`, one with no proposal behind it is `human`.
function sourceOf(a) {
  const o = a.origin;
  // Compared on the *quote*, never on the offsets. `reconcile` moves start/end
  // whenever the corpus text shifts around an otherwise untouched span, and an
  // offset comparison would read that as the labeller having edited something
  // they never went near.
  const unchanged = !!o && o.dimension === a.dimension && o.value === a.value
    && o.quote === a.quote && !!o.negated === !!a.negated;

  // A label that arrived already decided, out of the corpus or out of a
  // restored export, keeps the provenance it was stored with, but only while it
  // still says what it said. Correct it and it is an edit, whatever it was.
  const given = a.banked || a.restored;
  if (given) return unchanged ? given : 'edited';

  if (!o) return 'human';
  return unchanged ? 'confirmed' : 'edited';
}

function rungOf(a) {
  const dim = DIMS.get(a.dimension);
  if (!dim) return null;
  return dim.levels.find(l => l.value === a.value) || null;
}

function hue(dimensionId) {
  const dim = DIMS.get(dimensionId);
  return dim ? `var(--g-${dim.group})` : 'var(--muted)';
}

// ── the quote a span exports as ───────────────────────────────────────────────────────────────

// A quote can occur more than once in an ad — "guardias" twice, a salary line
// repeated in the summary and the body. `indexOf` alone would collapse every
// such span onto the first hit and quietly re-point somebody's label at the
// wrong sentence, so the occurrence index travels with the quote.
function nthIndexOf(text, needle, nth) {
  let at = -1;
  for (let seen = 0; seen <= (nth || 0); seen++) {
    at = text.indexOf(needle, at + 1);
    if (at < 0) return -1;
  }
  return at;
}

function occurrences(text, needle) {
  if (!needle) return 0;
  return text.split(needle).length - 1;
}

// `harness import` locates a label by searching for its quote and refuses one
// that appears twice. Rather than making the labeller "extend it until unique",
// the page widens the span itself until the text pins it down. The stored
// offsets are untouched — only the exported quote grows.
function uniqueQuote(text, start, end) {
  let s = start, e = end;
  let guard = 0;
  while (occurrences(text, text.slice(s, e)) > 1 && guard++ < 4000) {
    if (s > 0) s -= 1;
    else if (e < text.length) e += 1;
    else break;
  }
  return text.slice(s, e);
}

// ── rendering ─────────────────────────────────────────────────────────────────────────────────

function esc(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function renderAd() {
  const ad = ADS[current];
  const anns = annotations(ad.id);

  document.getElementById('adMeta').innerHTML =
    `<b>${esc(ad.title || ad.id)}</b> &middot; ${esc(ad.id)} &middot; ${esc(ad.language)} &middot; `
    + `${esc(ad.split)} &middot; `
    + `<a href="${esc(ad.source_url)}" target="_blank" rel="noreferrer">source</a>`;

  const notice = document.getElementById('controlNotice');
  const messages = [];
  if (CONTROL.has(ad.id)) {
    messages.push('<b>Control ad — nothing is marked on purpose.</b> Label it as you '
      + 'read it. These ads are what your agreement rate on the marked ones is measured against; '
      + 'without them, agreeing with 92% of proposals cannot be told apart from rubber-stamping.');
  }
  if (state.migrated) {
    messages.push(`<b>${state.migrated} label(s) carried over from the previous page.</b> They are `
      + 'shown as proposals because the scale is now named rungs rather than a free number — '
      + 'each one is on its nearest rung and needs confirming.');
  }
  const moved = drift[ad.id];
  if (moved && (moved.relocated || moved.lost)) {
    messages.push(`<b>This ad's text has changed since you labelled it.</b> `
      + `${moved.relocated} mark(s) were relocated by their quote`
      + (moved.lost ? `, and ${moved.lost} could no longer be found and were removed` : '')
      + '.');
  }
  notice.hidden = messages.length === 0;
  notice.innerHTML = messages.join('<hr>');

  // Marks are laid into the text in order, and one that overlaps a mark already
  // laid down is left out of the text rather than nested — overlapping <mark>
  // elements cannot be produced from a flat string without splitting one of
  // them across the other, which puts a chip in the middle of a word. It still
  // appears in the side panel, where it is fully actionable.
  const ordered = anns.map((a, i) => ({ a, i }))
    .sort((x, y) => x.a.start - y.a.start || x.a.end - y.a.end);
  let html = '';
  let at = 0;
  const inline = new Set();
  for (const { a, i } of ordered) {
    if (a.start < at || a.start >= a.end || a.end > ad.text.length) continue;
    const dim = DIMS.get(a.dimension);
    const rung = rungOf(a);
    const chip = dim
      ? `${esc(dim.label)}: ${esc(rung ? rung.label : String(a.value))}`
      : esc(a.dimension);
    const cls = 'ann' + (a.status === 'confirmed' ? ' confirmed' : '')
      + (i === focused ? ' focused' : '');
    html += esc(ad.text.slice(at, a.start));
    html += `<mark class="${cls}" data-i="${i}" style="--hue:${hue(a.dimension)}">`
      + esc(ad.text.slice(a.start, a.end))
      + `<span class="chip">${chip}${a.negated ? ' &middot; not' : ''}</span></mark>`;
    at = a.end;
    inline.add(i);
  }
  html += esc(ad.text.slice(at));
  const el = document.getElementById('adText');
  el.innerHTML = html;
  el.querySelectorAll('mark.ann').forEach(m => {
    m.addEventListener('click', ev => {
      ev.stopPropagation(); focused = Number(m.dataset.i); render();
    });
  });
  return inline;
}

function renderAnns(inline) {
  const ad = ADS[current];
  const anns = annotations(ad.id);
  const list = document.getElementById('anns');
  list.innerHTML = '';

  anns.forEach((a, i) => {
    const dim = DIMS.get(a.dimension);
    const rung = rungOf(a);
    const li = document.createElement('li');
    li.className = 'ann-row ' + (a.status === 'confirmed' ? 'confirmed' : 'pending')
      + (i === focused ? ' focused' : '');
    li.style.setProperty('--hue', hue(a.dimension));
    li.innerHTML =
      `<div class="ann-dim">${esc(dim ? dim.label : a.dimension)}`
      + '<span class="state"> &middot; '
      + `${a.status === 'confirmed' ? sourceOf(a) : 'proposed'}`
      + `${a.banked ? ' &middot; banked' : (a.restored ? ' &middot; restored' : '')}`
      + '</span></div>'
      + '<div class="ann-rung">'
      + `${esc(rung ? rung.label : '(rung ' + a.value + ' is not in the model)')}`
      + (a.negated ? ' <span class="state">negated</span>' : '') + '</div>'
      + `<div class="ann-quote">&ldquo;${esc(ad.text.slice(a.start, a.end))}&rdquo;</div>`
      + (inline.has(i) ? '' : '<div class="state">overlaps another mark — shown here only</div>');

    const acts = document.createElement('div');
    acts.className = 'ann-acts';
    if (a.status !== 'confirmed') {
      acts.appendChild(btn('confirm', 'primary', () => { confirmAt(i); }));
    }
    acts.appendChild(btn('change', '', () => {
      focused = i; openPicker({ kind: 'change', index: i });
    }));
    acts.appendChild(btn(a.negated ? 'un-negate' : 'negate', '', () => {
      a.negated = !a.negated; save(); render();
    }));
    acts.appendChild(btn('delete', 'danger', () => {
      anns.splice(i, 1); focused = -1; save(); render();
    }));
    li.appendChild(acts);
    li.addEventListener('click', () => { focused = i; render(); });
    list.appendChild(li);
  });

  const pending = anns.filter(a => a.status !== 'confirmed').length;
  document.getElementById('annHead').textContent =
    `On this ad — ${anns.length - pending} kept, ${pending} to resolve`;
  document.getElementById('annEmpty').textContent = anns.length
    ? '' : 'Nothing marked. Select the words that evidence a dimension to add one.';
  document.getElementById('confirmAll').disabled = pending === 0;
}

function btn(text, cls, onClick) {
  const b = document.createElement('button');
  b.textContent = text;
  if (cls) b.className = cls;
  b.addEventListener('click', ev => { ev.stopPropagation(); onClick(); });
  return b;
}

function render() {
  const inline = renderAd();
  renderAnns(inline);
  const resolved = ADS.filter(a => {
    const anns = state.byAd[a.id];
    return anns !== undefined && anns.every(x => x.status === 'confirmed');
  }).length;
  document.getElementById('count').innerHTML =
    `ad <b>${current + 1}</b>/${ADS.length} &middot; <b>${resolved}</b> fully resolved`;
  document.getElementById('jump').value = String(current);
  save();
}

// ── acting on an annotation ───────────────────────────────────────────────────────────────────

function confirmAt(i) {
  const anns = annotations(ADS[current].id);
  if (!anns[i]) return;
  anns[i].status = 'confirmed';
  save();
  focused = anns.findIndex(a => a.status !== 'confirmed');
  render();
}

function nextUnresolved() {
  for (let step = 1; step <= ADS.length; step++) {
    const i = (current + step) % ADS.length;
    const anns = state.byAd[ADS[i].id];
    if (anns === undefined || anns.some(a => a.status !== 'confirmed')) {
      current = i; focused = -1; render(); return;
    }
  }
  note('every ad is resolved');
}

// ── the picker ────────────────────────────────────────────────────────────────────────────────

function openPicker(mode) {
  picker = mode;
  const ad = ADS[current];
  const el = document.getElementById('picker');
  const sel = document.getElementById('pickerSel');
  if (mode.kind === 'new') {
    sel.textContent = '“' + ad.text.slice(mode.start, mode.end) + '”';
  } else {
    const a = annotations(ad.id)[mode.index];
    sel.textContent = '“' + ad.text.slice(a.start, a.end) + '”';
  }
  document.getElementById('newdim').classList.remove('open');
  document.getElementById('pickerSearch').value = '';
  renderDimensionList();
  el.classList.add('open');
  document.getElementById('pickerSearch').focus();
}

function closePicker() {
  picker = null;
  document.getElementById('picker').classList.remove('open');
}

function renderDimensionList() {
  const body = document.getElementById('pickerBody');
  body.innerHTML = '';
  for (const group of DATA.groups) {
    const members = DATA.dimensions.filter(d => d.group === group.id);
    if (!members.length) continue;
    const head = document.createElement('div');
    head.className = 'grp';
    head.style.setProperty('--hue', `var(--g-${group.id})`);
    head.textContent = group.title;
    head.dataset.group = group.id;
    body.appendChild(head);
    for (const dim of members) {
      const b = document.createElement('button');
      b.className = 'opt';
      b.dataset.dim = dim.id;
      b.dataset.hay = (dim.label + ' ' + dim.id + ' ' + dim.definition).toLowerCase();
      b.style.setProperty('--hue', `var(--g-${dim.group})`);
      b.innerHTML = `<span class="name">${esc(dim.label)}</span>`
        + `<span class="def">${esc(dim.definition)}</span>`;
      b.addEventListener('click', () => renderRungList(dim));
      body.appendChild(b);
    }
  }
  filterList();
}

function renderRungList(dim) {
  const body = document.getElementById('pickerBody');
  body.innerHTML = '';
  const head = document.createElement('div');
  head.className = 'grp';
  head.style.setProperty('--hue', `var(--g-${dim.group})`);
  head.textContent = dim.label + ' — pick the rung the ad evidences';
  body.appendChild(head);
  for (const level of dim.levels) {
    const b = document.createElement('button');
    b.className = 'opt rung';
    b.style.setProperty('--hue', `var(--g-${dim.group})`);
    b.innerHTML = `<span class="name">${esc(level.label)}</span>`
      + `<span class="tell">${esc(level.tell)}</span>`;
    b.addEventListener('click', () => commit(dim, level));
    body.appendChild(b);
  }
  const back = document.createElement('button');
  back.className = 'opt';
  back.innerHTML = '<span class="name">&larr; back to all dimensions</span>';
  back.addEventListener('click', renderDimensionList);
  body.appendChild(back);
}

function commit(dim, level) {
  const anns = annotations(ADS[current].id);
  if (picker.kind === 'new') {
    anns.push({
      dimension: dim.id, value: level.value, start: picker.start, end: picker.end,
      quote: ADS[current].text.slice(picker.start, picker.end),
      negated: false, status: 'confirmed', origin: null,
    });
    focused = anns.length - 1;
  } else {
    const a = anns[picker.index];
    a.dimension = dim.id;
    a.value = level.value;
    a.quote = ADS[current].text.slice(a.start, a.end);
    a.status = 'confirmed';
  }
  closePicker();
  save();
  render();
}

function filterList() {
  const q = document.getElementById('pickerSearch').value.trim().toLowerCase();
  const body = document.getElementById('pickerBody');
  const opts = body.querySelectorAll('.opt[data-hay]');
  opts.forEach(o => o.classList.toggle('hidden', q !== '' && !o.dataset.hay.includes(q)));
  body.querySelectorAll('.grp[data-group]').forEach(h => {
    const any = Array.from(body.querySelectorAll(`.opt[data-dim]`))
      .some(o => !o.classList.contains('hidden')
        && DIMS.get(o.dataset.dim).group === h.dataset.group);
    h.style.display = any ? '' : 'none';
  });
}

// ── coining a dimension mid-read ──────────────────────────────────────────────────────────────

// The page is opened over `file://` and cannot write `dimensions/<id>.yaml`, so
// a coined dimension is recorded as a *proposal* in the export and materialised
// by the CLI. It carries the ad it was coined at, because every ad before that
// one was read without it existing — a fact the earlier ads have to be swept
// against rather than silently assumed clean.
function coinDimension() {
  const id = document.getElementById('ndId').value.trim();
  const label = document.getElementById('ndLabel').value.trim();
  const definition = document.getElementById('ndDef').value.trim();
  const group = document.getElementById('ndGroup').value;
  const rungs = document.getElementById('ndRungs').value
    .split(',').map(s => s.trim()).filter(Boolean);

  if (!/^[a-z][a-z0-9_]*$/.test(id)) return note('id must be snake_case');
  if (DIMS.has(id) || state.coined.some(c => c.id === id)) return note('that id already exists');
  if (!label || !definition) return note('a name and a meaning are both required');
  if (rungs.length < 2 || rungs.length > 5) return note('give it between 2 and 5 rungs');

  const levels = rungs.map((name, i) => ({
    value: Number((i / (rungs.length - 1)).toFixed(2)), label: name,
    tell: 'coined while labelling — describe what this rung looks like in an ad',
  }));
  const dim = { id, group, label, definition, polarity: 'unipolar', kind: 'soft', levels };
  state.coined.push({ ...dim, coined_at_ad: ADS[current].id, coined_at_index: current });
  DIMS.set(id, dim);
  DATA.dimensions.push(dim);
  save();
  document.getElementById('newdim').classList.remove('open');
  note(`${label} added — it will appear in the export as a proposal`);
  renderRungList(dim);
}

// ── export ────────────────────────────────────────────────────────────────────────────────────

function buildExport() {
  const labeller = document.getElementById('labeller').value.trim() || 'owner';
  const round = Number(document.getElementById('round').value) || 1;
  const labels = [];
  let skipped = 0;
  for (const ad of ADS) {
    for (const a of (state.byAd[ad.id] || [])) {
      if (a.status !== 'confirmed') { skipped++; continue; }
      // A row that arrived with its own labeller and round keeps them: the
      // header inputs describe what is being labelled *now*, and stamping them
      // onto somebody else's round-1 work would re-file it as this round's. An
      // edited row is this labeller's judgement again, so it takes the current
      // values.
      const derived = sourceOf(a);
      const inherited = (a.banked || a.restored) && derived !== 'edited';
      labels.push({
        ad_id: ad.id, dimension: a.dimension, value: a.value,
        quote: uniqueQuote(ad.text, a.start, a.end),
        negated: !!a.negated,
        labeller: inherited && a.labeller ? a.labeller : labeller,
        round: inherited && a.round ? a.round : round,
        source: derived,
      });
    }
  }
  const payload = { labels };
  if (state.coined.length) payload.proposed_dimensions = state.coined;
  document.getElementById('export').value = JSON.stringify(payload, null, 2);
  document.getElementById('exportNote').textContent =
    `${labels.length} label(s)` + (skipped ? `, ${skipped} unresolved proposal(s) left out` : '')
    + (state.coined.length ? `, ${state.coined.length} proposed dimension(s)` : '');
}

// ── restore ───────────────────────────────────────────────────────────────────────────────────

// The page's own export, read back in. Banking work with `harness import` is
// the durable answer — the next page then arrives with it already placed — but
// that round trip needs somebody at a terminal, and between two of them the
// only copy of an afternoon's labelling is a `localStorage` key that a cleared
// browser, a different machine or a downloaded-to-a-new-folder page all lose.
// This is the labeller's own way back from that, needing nothing but the file
// the download button already gave them.
function restoreFromExport(text) {
  let payload;
  try { payload = JSON.parse(text); }
  catch (err) { return { error: 'that file is not JSON' }; }
  const rows = Array.isArray(payload) ? payload : payload && payload.labels;
  if (!Array.isArray(rows)) return { error: "no 'labels' array in that file" };

  // A dimension coined in the exporting session is unknown to this page, and
  // its labels would otherwise restore as rows the picker cannot name. Carrying
  // the proposals over first keeps them nameable — and keeps them in the next
  // export, so the coinage is not lost by passing through a restore.
  for (const dim of (payload.proposed_dimensions || [])) {
    if (!dim || !dim.id || DIMS.has(dim.id)) continue;
    DIMS.set(dim.id, dim);
    DATA.dimensions.push(dim);
    state.coined.push(dim);
  }

  let restored = 0, unplaced = 0;
  for (const row of rows) {
    const ad = ADS.find(a => a.id === (row && row.ad_id));
    if (!ad || typeof row.quote !== 'string') { unplaced++; continue; }
    const start = ad.text.indexOf(row.quote);
    if (start < 0) { unplaced++; continue; }
    const end = start + row.quote.length;
    const anns = annotations(ad.id);
    const ann = {
      dimension: row.dimension, value: row.value, start, end, quote: row.quote,
      negated: !!row.negated, status: 'confirmed', note: '',
      restored: row.source || 'human',
      labeller: row.labeller, round: row.round,
      origin: {
        dimension: row.dimension, value: row.value,
        quote: row.quote, negated: !!row.negated,
      },
    };
    // A restored row answers its dimension, so any proposal still pending for
    // that dimension is retired with it, including one sitting on a different
    // span. Left standing, confirming it later would put two rows carrying two
    // different values under one (ad, dimension, round) -- which `import_labels`
    // now refuses as a conflict, taking the whole batch down with it.
    const at = anns.findIndex(a => a.dimension === row.dimension
      && a.start === start && a.end === end);
    if (at >= 0) anns[at] = ann;
    else anns.push(ann);
    state.byAd[ad.id] = anns.filter(a =>
      a === ann || !(a.dimension === row.dimension && isProposal(a)));
    restored++;
  }
  save();
  render();
  return { restored, unplaced };
}

function note(message) {
  const footer = document.getElementById('footer');
  footer.textContent = message;
  setTimeout(() => { if (footer.textContent === message) footer.textContent = FOOTER; }, 4000);
}

// ── wiring ────────────────────────────────────────────────────────────────────────────────────

const FOOTER = `${ADS.length} ads · ${DATA.dimensions.length} dimensions · marks from `
  + `${DATA.suggestions.method} · ${CONTROL.size} control ads`;

function go(delta) {
  current = (current + delta + ADS.length) % ADS.length;
  focused = -1;
  render();
}

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('footer').textContent = FOOTER;

  const jump = document.getElementById('jump');
  ADS.forEach((ad, i) => {
    const o = document.createElement('option');
    o.value = String(i);
    o.textContent = `${i + 1}. ${ad.title || ad.id} (${ad.language})`;
    jump.appendChild(o);
  });
  jump.addEventListener('change', () => { current = Number(jump.value); focused = -1; render(); });

  const ndGroup = document.getElementById('ndGroup');
  DATA.groups.forEach(g => {
    const o = document.createElement('option');
    o.value = g.id; o.textContent = g.title;
    ndGroup.appendChild(o);
  });

  const gloss = document.getElementById('glossary');
  for (const group of DATA.groups) {
    for (const dim of DATA.dimensions.filter(d => d.group === group.id)) {
      const row = document.createElement('div');
      row.className = 'gloss-row';
      row.style.setProperty('--hue', `var(--g-${dim.group})`);
      row.innerHTML = `<b>${esc(dim.label)}</b> — ${esc(dim.definition)}<br>`
        + dim.levels.map(l => `<i>${esc(l.label)}</i>: ${esc(l.tell)}`).join(' &middot; ');
      gloss.appendChild(row);
    }
  }

  document.getElementById('prev').addEventListener('click', () => go(-1));
  document.getElementById('next').addEventListener('click', () => go(1));
  document.getElementById('nextTodo').addEventListener('click', nextUnresolved);
  document.getElementById('confirmAll').addEventListener('click', () => {
    annotations(ADS[current].id).forEach(a => { a.status = 'confirmed'; });
    focused = -1; save(); render();
  });
  document.getElementById('pickerClose').addEventListener('click', closePicker);
  document.getElementById('pickerSearch').addEventListener('input', filterList);
  document.getElementById('pickerNew').addEventListener('click', () => {
    const panel = document.getElementById('newdim');
    if (panel.classList.contains('open')) coinDimension();
    else { panel.classList.add('open'); document.getElementById('ndId').focus(); }
  });
  document.getElementById('build').addEventListener('click', buildExport);
  document.getElementById('restore').addEventListener('change', ev => {
    const file = ev.target.files && ev.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const result = restoreFromExport(String(reader.result));
      document.getElementById('restoreNote').textContent = result.error
        ? result.error
        : `${result.restored} label(s) restored`
          + (result.unplaced ? `, ${result.unplaced} could not be placed` : '');
    };
    reader.readAsText(file);
  });
  document.getElementById('copy').addEventListener('click', async () => {
    buildExport();
    try {
      await navigator.clipboard.writeText(document.getElementById('export').value);
      note('copied');
    }
    catch (err) { note('clipboard blocked — select the box and copy by hand'); }
  });
  document.getElementById('download').addEventListener('click', () => {
    buildExport();
    const blob = new Blob([document.getElementById('export').value], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 't5-labels.json';
    a.click();
    URL.revokeObjectURL(a.href);
  });

  // A selection inside the ad text opens the picker. Offsets come from the
  // browser's own selection resolved against the rendered text, so the quote is
  // a substring of `ad.text` by construction and cannot fail the importer's
  // verbatim check.
  document.getElementById('adText').addEventListener('mouseup', onSelect);
  document.getElementById('adText').addEventListener('touchend', onSelect);

  document.addEventListener('keydown', ev => {
    if (ev.target.matches('input, textarea, select')) {
      if (ev.key === 'Escape') { closePicker(); ev.target.blur(); }
      return;
    }
    const anns = annotations(ADS[current].id);
    if (ev.key === 'Escape') { closePicker(); return; }
    if (ev.key === 'Enter' && focused >= 0) { ev.preventDefault(); confirmAt(focused); }
    else if ((ev.key === 'Backspace' || ev.key === 'Delete') && focused >= 0) {
      ev.preventDefault(); anns.splice(focused, 1); focused = -1; save(); render();
    }
    else if (ev.key === 'c' && focused >= 0) openPicker({ kind: 'change', index: focused });
    else if (ev.key === 'j') { focused = Math.min(focused + 1, anns.length - 1); render(); }
    else if (ev.key === 'k') { focused = Math.max(focused - 1, 0); render(); }
    else if (ev.key === 'n') nextUnresolved();
    else if (ev.key === '[') go(-1);
    else if (ev.key === ']') go(1);
  });

  render();
});

function onSelect() {
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed || sel.rangeCount === 0) return;
  const root = document.getElementById('adText');
  const range = sel.getRangeAt(0);
  if (!root.contains(range.commonAncestorContainer)) return;

  // Offsets are measured by walking the rendered DOM's text nodes and skipping
  // the chip spans, which are page furniture rather than ad text. Measuring
  // against `textContent` directly would count every chip's characters into the
  // offset and slide every span after the first mark.
  const offset = node => {
    let total = 0;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = walker.nextNode())) {
      if (n === node) return total;
      if (!n.parentElement.closest('.chip')) total += n.textContent.length;
    }
    return total;
  };
  let start = offset(range.startContainer) + range.startOffset;
  let end = offset(range.endContainer) + range.endOffset;
  const text = ADS[current].text;
  // Trim whitespace the drag picked up at either edge; a quote that starts with
  // a space is still verbatim but reads as a mis-click in the panel.
  while (start < end && /\s/.test(text[start])) start++;
  while (end > start && /\s/.test(text[end - 1])) end--;
  if (end <= start) return;
  sel.removeAllRanges();
  openPicker({ kind: 'new', start, end });
}
"""


if __name__ == "__main__":
    raise SystemExit(main())
