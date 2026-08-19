#!/usr/bin/env python3
"""T5's labelling aid — a self-contained HTML page that makes hand-labelling fast.

T5 (`claude-arsenal/queue/lo-d2b2.md`) is `[HUMAN]`: a person, not an agent,
must decide which of the 22 matched dimensions (`src/jobsearch/dimensions.py`,
`docs/dimension-catalogue.md`) each of the 100 ads in
`corpus/labelled/ads.jsonl` evidences, and must supply a verbatim quote for
every value (`corpus/labelled/README.md`). Typing accented Catalan and
Spanish quotes into a terminal 300+ times is the actual bottleneck — a
mistyped quote is silently rejected by `harness set` (`ad.text.find` returns
-1), so every retry is a round trip through the shell.

This tool removes the typing, not the judgement. It renders the corpus and
the dimension model into one `file://`-openable HTML page with no network
dependency, so the labeller reads the ad, drags the mouse over the words that
evidence a dimension, and the page reads the *browser's own selection* back
as the quote — a substring of `text` by construction, so it can never fail
`harness set`'s verbatim check. `harness import` (in `jobsearch.harness`)
then applies everything the page accumulated in one atomic batch, instead of
one `set` invocation per label.

**Cue highlighting is navigation, not labelling.** The page marks where a
dimension's extraction regex (`Dimension.extraction.cues`) matches the ad
text, purely so the labeller's eye lands on the right paragraph. It never
selects a dimension, never fills a value, and never fills a quote — the page
says so in its own UI, not only here, because D-2 (`status/plan.md`) already
records that v0's cue-derived gold is not independent of the extraction
model, and `extraction_macro_f1` (T15) is measured against this corpus's
labels. A page that pre-filled from a cue would let the labeller rubber-stamp
the model's own regex as ground truth, and the gate would then measure the
model against itself — passing meaninglessly regardless of how good or bad
the extractor actually is. `test_cue_highlight_never_prefills_a_value` in
`tests/test_labelling_aid.py` is the property test for this.

Usage:
    uv run python tools/labelling_page.py                 # writes corpus/labelled/label.html
    uv run python tools/labelling_page.py --out /tmp/x.html

The generated file is gitignored (`.gitignore`) — it is a build artefact of
the corpus and the dimension model, regenerable from either at any time, and
carries no state of its own: the labeller's actual work lives in the browser's
`localStorage` until it is exported and applied with `harness import`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from jobsearch.dimensions import DEFAULT_DIMENSIONS_DIR, Dimension, load_dimensions
from jobsearch.harness import DEFAULT_STORE_PATH, LabelledAd, load_store

_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_PATH = _REPO_ROOT / "corpus" / "labelled" / "label.html"


def _dimension_payload(dimensions: list[Dimension]) -> list[dict[str, Any]]:
    """The subset of each dimension the page needs: label, definition, cues.

    Restricted to `side == "matched"` — the 22 dimensions an ad's own wording
    can evidence. `candidate_fact` and `candidate_trait` dimensions (none
    currently in the committed model, but the schema allows them) are elicited
    from the person, never extracted from an ad, so a labelling page over ad
    text has nothing to ask about them.
    """
    return [
        {
            "id": dimension.id,
            "label": {
                "en": dimension.label.en,
                "es": dimension.label.es,
                "ca": dimension.label.ca,
            },
            "definition": dimension.definition,
            "polarity": dimension.polarity,
            "cues": {
                language: [
                    {"pattern": cue.pattern, "negatable": cue.negatable} for cue in cues
                ]
                for language, cues in dimension.extraction.cues.items()
            },
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
        }
        for ad in sorted(ads, key=lambda a: a.id)
    ]


def _embed_json(data: dict[str, Any]) -> str:
    """Serialise `data` for a `<script type="application/json">` block.

    The HTML tokenizer ends a `<script>` element at the first literal
    `</script` it sees, case-insensitively, regardless of the element's
    `type` — the ad corpus is arbitrary scraped text and nothing rules out
    that substring appearing in it. Escaping the slash (`<\\/script`) is inert
    to `JSON.parse`, which does not treat backslash-slash as anything but a
    literal `/`, and prevents that same substring from ever closing the tag
    early.
    """
    return json.dumps(data, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")


def build_page(ads: list[LabelledAd], dimensions: list[Dimension]) -> str:
    """Render the full standalone HTML page."""
    data = {
        "ads": _ad_payload(ads),
        "dimensions": _dimension_payload(dimensions),
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


_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>T5 labelling aid</title>
<style>
:root {
  color-scheme: light dark;
  --bg: #f7f7f5;
  --panel: #ffffff;
  --border: #d8d8d2;
  --text: #1c1c1a;
  --muted: #66665f;
  --accent: #2f6f4f;
  --accent-contrast: #ffffff;
  --warn-bg: #fff4e0;
  --warn-border: #d9a441;
  --mark-bg: #ffe9a8;
  --mark-border: #d9a441;
  --danger: #a4302a;
  --done-bg: #e4f2e8;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #1b1c19;
    --panel: #242520;
    --border: #3a3b34;
    --text: #ecece6;
    --muted: #b0b0a4;
    --accent: #7fd0a3;
    --accent-contrast: #10241a;
    --warn-bg: #3a3016;
    --warn-border: #b98b2c;
    --mark-bg: #5a4a1a;
    --mark-border: #b98b2c;
    --danger: #e08a84;
    --done-bg: #1f3226;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.45;
}
header {
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border);
  background: var(--panel);
  position: sticky;
  top: 0;
  z-index: 5;
}
header h1 { font-size: 1.05rem; margin: 0 0 0.4rem 0; }
.progress { font-size: 0.85rem; color: var(--muted); margin-bottom: 0.5rem; }
.controls { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; }
.controls label {
  font-size: 0.8rem; color: var(--muted); display: flex; gap: 0.3rem; align-items: center;
}
.controls input[type="text"], .controls input[type="number"], .controls select {
  font: inherit; padding: 0.2rem 0.35rem; border: 1px solid var(--border);
  border-radius: 4px; background: var(--panel); color: var(--text);
}
button {
  font: inherit; padding: 0.3rem 0.7rem; border-radius: 5px; border: 1px solid var(--border);
  background: var(--panel); color: var(--text); cursor: pointer;
}
button.primary {
  background: var(--accent); color: var(--accent-contrast); border-color: var(--accent);
}
button:disabled { opacity: 0.5; cursor: not-allowed; }
.notice {
  margin: 0.75rem 1rem; padding: 0.6rem 0.8rem; border: 1px solid var(--warn-border);
  background: var(--warn-bg); border-radius: 6px; font-size: 0.85rem;
}
main {
  display: grid; grid-template-columns: minmax(280px, 1fr) minmax(320px, 1fr);
  gap: 1rem; margin: 0 1rem 1rem 1rem;
}
@media (max-width: 900px) { main { grid-template-columns: 1fr; } }
.ad-pane, .dims-pane, .export {
  background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
  padding: 0.9rem; max-height: 75vh; overflow-y: auto;
}
.ad-meta { font-size: 0.82rem; color: var(--muted); margin-bottom: 0.5rem; }
.ad-meta a { color: var(--accent); }
.ad-hint { font-size: 0.78rem; color: var(--muted); margin-bottom: 0.5rem; }
.ad-text {
  white-space: pre-wrap; font-size: 0.95rem; user-select: text;
}
mark.cue-hit {
  background: var(--mark-bg); border-bottom: 2px solid var(--mark-border);
  border-radius: 2px; padding: 0 1px; cursor: help;
}
.dims-pane h2 { font-size: 0.95rem; margin-top: 0; }
.dim-card {
  border: 1px solid var(--border); border-radius: 6px; padding: 0.55rem 0.65rem;
  margin-bottom: 0.6rem;
}
.dim-card.has-label { background: var(--done-bg); }
.dim-head { display: flex; justify-content: space-between; align-items: baseline; gap: 0.5rem; }
.dim-label { font-weight: 600; }
.dim-id { font-size: 0.72rem; color: var(--muted); font-family: ui-monospace, monospace; }
.dim-def { font-size: 0.8rem; color: var(--muted); margin: 0.15rem 0 0.4rem 0; }
.dim-controls {
  display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; margin-bottom: 0.3rem;
}
.dim-controls label { font-size: 0.78rem; display: flex; gap: 0.25rem; align-items: center; }
.val-input { width: 4.5rem; font: inherit; padding: 0.15rem 0.3rem; border: 1px solid var(--border);
  border-radius: 4px; background: var(--panel); color: var(--text); }
.quote-display {
  font-size: 0.82rem; font-style: italic; padding: 0.3rem 0.4rem; border-radius: 4px;
  background: var(--bg); border: 1px dashed var(--border); min-height: 1.3em;
}
.quote-error { font-size: 0.78rem; color: var(--danger); min-height: 1em; }
.export textarea {
  width: 100%; min-height: 8rem; font-family: ui-monospace, monospace; font-size: 0.78rem;
  background: var(--bg); color: var(--text); border: 1px solid var(--border); border-radius: 6px;
}
.export-actions { display: flex; gap: 0.5rem; margin-top: 0.4rem; flex-wrap: wrap; }
.copy-status { font-size: 0.8rem; color: var(--muted); }
.howto {
  margin: 1rem 1rem 0 1rem; padding: 0.75rem 1rem; border: 1px solid var(--border);
  border-radius: 8px; background: var(--panel); font-size: 0.9rem; line-height: 1.5;
}
.howto summary { cursor: pointer; font-weight: 500; }
.howto ol { margin: 0.75rem 0 0.5rem 0; padding-left: 1.4rem; }
.howto li { margin-bottom: 0.5rem; }
.howto p { margin: 0.5rem 0 0 0; }
footer { text-align: center; font-size: 0.75rem; color: var(--muted); padding: 1rem; }
</style>
</head>
<body>
"""

_BODY = """<header>
  <h1>T5 labelling aid</h1>
  <div class="progress" id="progress"></div>
  <div class="controls">
    <label>Labeller <input type="text" id="labellerName" value="owner" size="8"></label>
    <label>Round <input type="number" id="roundNum" value="1" min="1" style="width:3.5rem"></label>
    <label>Split
      <select id="splitFilter">
        <option value="">all</option>
        <option value="elicitation">elicitation</option>
        <option value="evaluation">evaluation</option>
      </select>
    </label>
    <label>Language
      <select id="langFilter">
        <option value="">all</option>
        <option value="es">es</option>
        <option value="en">en</option>
        <option value="ca">ca</option>
      </select>
    </label>
    <label>Jump to <select id="jumpSelect"></select></label>
    <button id="prevBtn">&larr; prev</button>
    <button id="nextBtn">next &rarr;</button>
    <button id="nextUnlabelledBtn" class="primary">next unlabelled &rarr;</button>
  </div>
</header>

<details class="howto" open>
  <summary><strong>How to label an ad</strong> &mdash; click to collapse</summary>
  <ol>
    <li><strong>Read the ad</strong> on the left. Decide for yourself what it
      says; do not start from the highlights (see the note below).</li>
    <li><strong>Find a dimension it evidences</strong> in the right-hand list.
      Each card shows the dimension&rsquo;s name and its definition. Most ads
      evidence only a handful of the 22 &mdash; <em>you are not meant to fill in
      every card.</em> Leave a dimension untouched when the ad says nothing
      about it.</li>
    <li><strong>Select the words that prove it</strong> with the mouse, in the
      ad text, then click <em>use selection</em> on that dimension&rsquo;s card.
      The quote is taken from the browser&rsquo;s own selection, so it is always
      an exact substring of the ad and can never fail the importer&rsquo;s
      verbatim check. Select the evidence itself, not the whole paragraph.</li>
    <li><strong>Enter a value</strong> from &minus;1 to 1. The sign is what
      matters most: <code>1</code> = the ad strongly evidences this dimension,
      <code>0.5</code> = weakly or partially, <code>&minus;1</code> = it
      evidences the opposite. Steps of 0.05 are allowed; do not agonise over
      the second decimal.</li>
    <li><strong>Tick <em>negated</em></strong> when the ad <em>denies</em> the
      dimension in words &mdash; &ldquo;sense gu&agrave;rdies&rdquo;, &ldquo;no
      on-call&rdquo;. That is different from the ad simply not mentioning it
      (leave it blank) and it is measured separately, so it is worth getting
      right.</li>
    <li><strong>Move on</strong> with <em>next unlabelled</em>. A dimension
      counts as done only when it has <em>both</em> a quote and a value &mdash;
      that is what the <em>Dimensions (n/22 on this ad)</em> heading counts.
      The counter in the header measures something different and looser: how
      many <em>ads</em> carry at least one label, so an ad you have barely
      started already counts there. Neither number is a target.</li>
  </ol>
  <p><strong>Stopping and resuming.</strong> Your work is saved in this
    browser as you go &mdash; closing the tab does not lose it (clearing
    browser data does). There is no &ldquo;submit&rdquo;: when you want to hand
    work over, scroll to <em>Export</em> at the bottom, click <em>copy
    JSON</em>, and send that blob. You can do that after five ads or after a
    hundred, and again later; importing is idempotent.</p>
  <p><strong>If you are unsure about an ad</strong>, skip it rather than
    guessing. An honest gap is fixable later; a guessed label silently becomes
    ground truth that every extraction score is measured against.</p>
</details>

<div class="notice">
  <strong>Highlights are navigation, not labels.</strong> The shaded words show
  where a dimension's extraction regex matches this ad &mdash; they point your eye
  at the right paragraph and nothing more. They never choose a dimension, never
  set a value, and never fill a quote for you: v0's cue-derived gold is not
  independent of the extraction model (D-2), and this corpus is what
  <code>extraction_macro_f1</code> is measured against. Copying a highlight
  straight into a label would make that gate check the model against itself.
  Read the ad, decide for yourself, then select the words that actually
  evidence your decision.
</div>

<main>
  <section class="ad-pane">
    <div class="ad-meta" id="adMeta"></div>
    <div class="ad-hint">Select text with the mouse below, then click &ldquo;use
      selection&rdquo; on the dimension it evidences.</div>
    <div class="ad-text" id="adText"></div>
  </section>
  <section class="dims-pane">
    <h2>Dimensions (<span id="dimDoneCount"></span>/<span id="dimTotalCount"></span>
      on this ad)</h2>
    <div id="dimsList"></div>
  </section>
</main>

<section class="export" style="margin:0 1rem 1.5rem 1rem;">
  <h2>Export</h2>
  <div id="exportSummary" class="ad-hint"></div>
  <textarea id="exportBlob" readonly spellcheck="false"></textarea>
  <div class="export-actions">
    <button id="copyBtn" class="primary">copy JSON</button>
    <button id="clearBtn">clear all local progress</button>
    <span class="copy-status" id="copyStatus"></span>
  </div>
  <p class="ad-hint">Paste the copied blob into a file and run
    <code>uv run python -m jobsearch.harness import &lt;file&gt;</code>, or run it
    with <code>-</code> and paste on stdin. Progress here lives in this browser's
    local storage until you export and import it — closing the tab does not
    lose it, clearing browser data does.</p>
</section>

<footer>generated by tools/labelling_page.py &mdash; no data leaves this page</footer>
"""

_TAIL = "</body>\n</html>\n"

_SCRIPT = r"""
(function () {
  "use strict";

  var DATA = JSON.parse(document.getElementById("jobsearch-data").textContent);
  var ADS = DATA.ads;
  var DIMENSIONS = DATA.dimensions;

  var LABELS_KEY = "jobsearch-t5-labels-v1";
  var UI_KEY = "jobsearch-t5-ui-v1";

  function loadJSON(key, fallback) {
    try {
      var raw = window.localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (err) {
      return fallback;
    }
  }
  function saveJSON(key, value) {
    window.localStorage.setItem(key, JSON.stringify(value));
  }

  // { adId: { dimId: {value, negated, quote, labeller, round} } }
  var labels = loadJSON(LABELS_KEY, {});
  var ui = loadJSON(UI_KEY, {});

  var splitFilter = document.getElementById("splitFilter");
  var langFilter = document.getElementById("langFilter");
  var jumpSelect = document.getElementById("jumpSelect");
  var labellerInput = document.getElementById("labellerName");
  var roundInput = document.getElementById("roundNum");

  splitFilter.value = ui.split || "";
  langFilter.value = ui.lang || "";
  labellerInput.value = ui.labeller || "owner";
  roundInput.value = ui.round || 1;

  var filtered = [];
  var currentAdId = ui.currentAdId || (ADS.length ? ADS[0].id : null);

  function applyFilters() {
    var split = splitFilter.value;
    var lang = langFilter.value;
    filtered = ADS.filter(function (ad) {
      return (!split || ad.split === split) && (!lang || ad.language === lang);
    });
    if (!filtered.length) { filtered = ADS.slice(); }
    if (!filtered.some(function (a) { return a.id === currentAdId; })) {
      currentAdId = filtered.length ? filtered[0].id : null;
    }
    populateJumpSelect();
  }

  function populateJumpSelect() {
    jumpSelect.innerHTML = "";
    filtered.forEach(function (ad) {
      var opt = document.createElement("option");
      opt.value = ad.id;
      opt.textContent = ad.id + "  [" + ad.language + "/" + ad.split + "]" +
        (isAdDone(ad.id) ? "  ✓" : "");
      jumpSelect.appendChild(opt);
    });
    jumpSelect.value = currentAdId;
  }

  function escapeHtml(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function countOccurrences(haystack, needle) {
    if (!needle) { return 0; }
    var count = 0, pos = 0, idx;
    while ((idx = haystack.indexOf(needle, pos)) !== -1) {
      count += 1;
      pos = idx + 1;
    }
    return count;
  }

  function currentAd() {
    for (var i = 0; i < filtered.length; i++) {
      if (filtered[i].id === currentAdId) { return filtered[i]; }
    }
    return filtered[0] || null;
  }

  function adLabels(adId) {
    if (!labels[adId]) { labels[adId] = {}; }
    return labels[adId];
  }

  function isDimLabelled(adId, dimId) {
    var entry = (labels[adId] || {})[dimId];
    return !!(
      entry && entry.quote &&
      entry.value !== null && entry.value !== undefined && entry.value !== ""
    );
  }

  function isAdDone(adId) {
    return DIMENSIONS.some(function (d) { return isDimLabelled(adId, d.id); });
  }

  function touch(adId, dimId, patch) {
    var entry = adLabels(adId)[dimId] || {};
    Object.assign(entry, patch, {
      labeller: labellerInput.value || "owner",
      round: parseInt(roundInput.value, 10) || 1,
    });
    adLabels(adId)[dimId] = entry;
    saveJSON(LABELS_KEY, labels);
  }

  function clearEntry(adId, dimId) {
    if (labels[adId]) { delete labels[adId][dimId]; }
    saveJSON(LABELS_KEY, labels);
  }

  // ---- cue highlighting (navigation only — see the page's own notice) ----

  function cueMatches(ad) {
    var ranges = [];
    DIMENSIONS.forEach(function (dim) {
      var cues = (dim.cues && dim.cues[ad.language]) || [];
      cues.forEach(function (cue) {
        var re;
        try {
          re = new RegExp(cue.pattern, "gi");
        } catch (err) {
          return; // a pattern JS cannot compile is skipped, not fatal
        }
        var m;
        while ((m = re.exec(ad.text)) !== null) {
          if (m[0].length === 0) { re.lastIndex += 1; continue; }
          ranges.push({
            start: m.index, end: m.index + m[0].length,
            dim: dim.id, label: dim.label[ad.language] || dim.id,
          });
          if (!re.global) { break; }
        }
      });
    });
    ranges.sort(function (a, b) { return a.start - b.start || b.end - a.end; });
    var merged = [];
    var lastEnd = -1;
    ranges.forEach(function (r) {
      if (r.start >= lastEnd) {
        merged.push(r);
        lastEnd = r.end;
      }
    });
    return merged;
  }

  function renderAdText(ad) {
    var container = document.getElementById("adText");
    var ranges = cueMatches(ad);
    var html = "";
    var pos = 0;
    ranges.forEach(function (r) {
      html += escapeHtml(ad.text.slice(pos, r.start));
      html += '<mark class="cue-hit" title="cue: ' + escapeHtml(r.label) +
        ' (' + escapeHtml(r.dim) + ') — navigation only, not a label">';
      html += escapeHtml(ad.text.slice(r.start, r.end)) + "</mark>";
      pos = r.end;
    });
    html += escapeHtml(ad.text.slice(pos));
    container.innerHTML = html;
  }

  // ---- rendering ----

  function renderMeta(ad) {
    var idx = filtered.indexOf(ad) + 1;
    document.getElementById("adMeta").innerHTML =
      "<strong>" + escapeHtml(ad.id) + "</strong> &middot; " + escapeHtml(ad.language) +
      " &middot; " + escapeHtml(ad.split) + " &middot; " + escapeHtml(ad.title || "") +
      "<br><a href=\"" + escapeHtml(ad.source_url) + "\" target=\"_blank\" rel=\"noreferrer\">" +
      escapeHtml(ad.source_url) + "</a> (" + (idx) + "/" + filtered.length + " in this filter)";
  }

  function renderProgress() {
    var totalDone = ADS.filter(function (a) { return isAdDone(a.id); }).length;
    document.getElementById("progress").textContent =
      totalDone + " / " + ADS.length + " ad(s) with at least one label recorded";
  }

  function renderDimCard(dim, ad) {
    var card = document.querySelector('.dim-card[data-dim="' + dim.id + '"]');
    if (!card) { return; }
    var entry = (labels[ad.id] || {})[dim.id] || {};
    card.classList.toggle("has-label", isDimLabelled(ad.id, dim.id));
    var hasValue = entry.value !== undefined && entry.value !== null;
    card.querySelector(".val-input").value = hasValue ? entry.value : "";
    card.querySelector(".negated-input").checked = !!entry.negated;
    card.querySelector(".quote-display").textContent = entry.quote
      ? ("“" + entry.quote + "”")
      : "(no quote captured yet)";
    card.querySelector(".quote-error").textContent = "";
    updateDimDoneCount();
  }

  function updateDimDoneCount() {
    var ad = currentAd();
    if (!ad) { return; }
    var done = DIMENSIONS.filter(function (d) { return isDimLabelled(ad.id, d.id); }).length;
    document.getElementById("dimDoneCount").textContent = String(done);
    document.getElementById("dimTotalCount").textContent = String(DIMENSIONS.length);
  }

  function buildDimsList(ad) {
    var list = document.getElementById("dimsList");
    list.innerHTML = "";
    DIMENSIONS.forEach(function (dim) {
      var card = document.createElement("div");
      card.className = "dim-card";
      card.setAttribute("data-dim", dim.id);
      card.innerHTML =
        '<div class="dim-head"><span class="dim-label">' +
        escapeHtml(dim.label[ad.language] || dim.id) +
        '</span><span class="dim-id">' + escapeHtml(dim.id) + "</span></div>" +
        '<div class="dim-def">' + escapeHtml(dim.definition) + "</div>" +
        '<div class="dim-controls">' +
        '<label>value <input type="number" class="val-input" min="-1" max="1" ' +
        'step="0.05" placeholder="&ndash;"></label>' +
        '<label><input type="checkbox" class="negated-input"> negated (denies it)</label>' +
        '<button type="button" class="capture-btn">use selection</button>' +
        '<button type="button" class="clear-btn">clear</button>' +
        "</div>" +
        '<div class="quote-display"></div>' +
        '<div class="quote-error"></div>';
      list.appendChild(card);

      card.querySelector(".val-input").addEventListener("input", function (e) {
        var raw = e.target.value;
        var value = raw === "" ? null : Math.max(-1, Math.min(1, parseFloat(raw)));
        touch(currentAd().id, dim.id, { value: value });
        renderDimCard(dim, currentAd());
        renderProgress();
        populateJumpSelect();
        renderExport();
      });
      card.querySelector(".negated-input").addEventListener("change", function (e) {
        touch(currentAd().id, dim.id, { negated: e.target.checked });
        renderExport();
      });
      card.querySelector(".capture-btn").addEventListener("click", function () {
        captureSelection(dim);
      });
      card.querySelector(".clear-btn").addEventListener("click", function () {
        clearEntry(currentAd().id, dim.id);
        renderDimCard(dim, currentAd());
        renderProgress();
        populateJumpSelect();
        renderExport();
      });
    });
  }

  function captureSelection(dim) {
    var ad = currentAd();
    var card = document.querySelector('.dim-card[data-dim="' + dim.id + '"]');
    var errEl = card.querySelector(".quote-error");
    errEl.textContent = "";
    var sel = window.getSelection ? window.getSelection() : null;
    var text = sel ? sel.toString() : "";
    if (!text) {
      errEl.textContent = "select some text in the ad first";
      return;
    }
    var occurrences = countOccurrences(ad.text, text);
    if (occurrences === 0) {
      errEl.textContent = "that selection is not an exact match of the ad text — " +
        "select again without crossing outside the ad";
      return;
    }
    if (occurrences > 1) {
      errEl.textContent = "that text appears " + occurrences +
        " times in this ad — extend the selection until it is unique";
      return;
    }
    touch(ad.id, dim.id, { quote: text });
    renderDimCard(dim, ad);
    renderProgress();
    populateJumpSelect();
    renderExport();
  }

  function render() {
    var ad = currentAd();
    if (!ad) { return; }
    currentAdId = ad.id;
    ui.currentAdId = currentAdId;
    ui.split = splitFilter.value;
    ui.lang = langFilter.value;
    ui.labeller = labellerInput.value;
    ui.round = roundInput.value;
    saveJSON(UI_KEY, ui);

    renderMeta(ad);
    renderAdText(ad);
    buildDimsList(ad);
    DIMENSIONS.forEach(function (dim) { renderDimCard(dim, ad); });
    renderProgress();
    jumpSelect.value = ad.id;
    renderExport();
  }

  function step(delta) {
    var idx = filtered.findIndex(function (a) { return a.id === currentAdId; });
    if (idx === -1) { idx = 0; }
    idx = (idx + delta + filtered.length) % filtered.length;
    currentAdId = filtered[idx].id;
    render();
  }

  function nextUnlabelled() {
    var idx = filtered.findIndex(function (a) { return a.id === currentAdId; });
    for (var step_ = 1; step_ <= filtered.length; step_++) {
      var candidate = filtered[(idx + step_) % filtered.length];
      if (!isAdDone(candidate.id)) {
        currentAdId = candidate.id;
        render();
        return;
      }
    }
    // everything in this filter is done; stay put
  }

  // ---- export ----

  function buildExportRows() {
    var rows = [];
    Object.keys(labels).forEach(function (adId) {
      var perAd = labels[adId] || {};
      Object.keys(perAd).forEach(function (dimId) {
        var entry = perAd[dimId];
        var missing = !entry || !entry.quote ||
          entry.value === null || entry.value === undefined || entry.value === "";
        if (missing) {
          return;
        }
        rows.push({
          ad_id: adId,
          dimension: dimId,
          value: Number(entry.value),
          quote: entry.quote,
          negated: !!entry.negated,
          labeller: entry.labeller || "owner",
          round: entry.round || 1,
        });
      });
    });
    rows.sort(function (a, b) {
      return a.ad_id < b.ad_id ? -1 : a.ad_id > b.ad_id ? 1 : (a.dimension < b.dimension ? -1 : 1);
    });
    return rows;
  }

  function renderExport() {
    var rows = buildExportRows();
    document.getElementById("exportSummary").textContent =
      rows.length + " label(s) ready to import, across " +
      new Set(rows.map(function (r) { return r.ad_id; })).size + " ad(s).";
    document.getElementById("exportBlob").value = JSON.stringify(rows, null, 2);
  }

  document.getElementById("copyBtn").addEventListener("click", function () {
    var blob = document.getElementById("exportBlob");
    blob.select();
    blob.setSelectionRange(0, blob.value.length);
    var status = document.getElementById("copyStatus");
    var done = false;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(blob.value).then(function () {
        status.textContent = "copied";
      }).catch(function () {
        done = document.execCommand && document.execCommand("copy");
        status.textContent = done ? "copied" : "select-and-copy manually (Ctrl/Cmd-C)";
      });
    } else {
      done = document.execCommand && document.execCommand("copy");
      status.textContent = done ? "copied" : "select-and-copy manually (Ctrl/Cmd-C)";
    }
  });

  document.getElementById("clearBtn").addEventListener("click", function () {
    var sure = window.confirm(
      "Clear ALL locally recorded labels on this page? This cannot be undone."
    );
    if (!sure) { return; }
    labels = {};
    saveJSON(LABELS_KEY, labels);
    render();
  });

  splitFilter.addEventListener("change", function () { applyFilters(); render(); });
  langFilter.addEventListener("change", function () { applyFilters(); render(); });
  jumpSelect.addEventListener("change", function () { currentAdId = jumpSelect.value; render(); });
  labellerInput.addEventListener("change", function () {
    ui.labeller = labellerInput.value; saveJSON(UI_KEY, ui);
  });
  roundInput.addEventListener("change", function () {
    ui.round = roundInput.value; saveJSON(UI_KEY, ui);
  });
  document.getElementById("prevBtn").addEventListener("click", function () { step(-1); });
  document.getElementById("nextBtn").addEventListener("click", function () { step(1); });
  document.getElementById("nextUnlabelledBtn").addEventListener("click", nextUnlabelled);

  applyFilters();
  render();
})();
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate the T5 labelling aid — a standalone HTML page over the corpus."
    )
    parser.add_argument("--store", default=str(DEFAULT_STORE_PATH), help="labelled corpus store")
    parser.add_argument(
        "--dimensions-dir", default=str(DEFAULT_DIMENSIONS_DIR), help="dimension model directory"
    )
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT_PATH), help="output HTML path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ads = load_store(Path(args.store))
    dimensions = load_dimensions(Path(args.dimensions_dir))
    page = build_page(ads, dimensions)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page, encoding="utf-8")
    print(f"{len(ads)} ad(s), {len(dimensions)} dimension(s) -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
