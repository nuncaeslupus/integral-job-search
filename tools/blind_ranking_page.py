#!/usr/bin/env python3
"""T20's blind sitting — sort twenty adverts into three named blocks, and say why.

T20 (`arsenal/tasks/lo-c48f.md`) is `[HUMAN]`: the candidate ranks twenty
held-out adverts by hand, blind, and `rank_spearman >= 0.60` says whether the
system agrees with them. `integral.calibration` draws the twenty and presents
them; this is the surface the candidate actually reads and works in.

A flat 1-to-20 is the wrong instrument for the job. Twenty adverts is far more
than anybody holds in mind at once, and the first pass through a job board is
not a ranking at all — it is a triage, and most of what it decides is
*out*. So the page offers three blocks the candidate names themselves, an
unsorted pool everything starts in, and ordering **within** a block. The
ordering T20 correlates is the three blocks read top to bottom, which is a total
order over the twenty and needs no extra work from the person producing it.

The notes box is the other half, and it is not decoration. An advert discarded
for a stack the candidate has never written is a **knockout**, not a low score;
an advert discarded despite good pay and full remote says which dimensions are
even reachable before the trade-offs start. An order alone cannot say either.
`integral.calibration.record` keeps the notes beside the ordering for that
reason, and T10 fitting a weight from the rank would otherwise read a knockout
as "worth less money", which is not what the candidate said.

**This page carries the advert and nothing else.** It is built from
`calibration.presentation()`, whose payload is closed to `PAGE_KEYS`, and
`build_page` asserts that before rendering — no score, no salary-equivalent
total, no rank position, no explanation, and no ordering recorded by an earlier
pass. That is T20a's gate (`blind_ranking_leaks == 0`), and the reason for it is
that a leak does not make T20 fail: it makes T20 pass while measuring the
anchor the candidate was shown instead of the judgement they made.

Usage:
    uv run python tools/blind_ranking_page.py                 # -> corpus/blind-ranking.html
    uv run python tools/blind_ranking_page.py --out /tmp/x.html

The generated file is gitignored — a build artefact of the corpus, regenerable
at any time. The candidate's work lives in the browser's `localStorage` until
they copy the export out, and the export is applied with
`integral.calibration.record`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from integral import calibration

_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_PATH = _REPO_ROOT / "corpus" / "blind-ranking.html"

# The candidate renames these in the page; they are a starting point, not a
# vocabulary. Three because that is what a first pass actually separates —
# would, might, no — and a fourth would invite ranking inside the triage.
DEFAULT_BLOCK_NAMES = ("Would apply", "Maybe", "Not for me")


def _embed_json(data: dict[str, Any]) -> str:
    """Serialise `data` for a `<script type="application/json">` block.

    The HTML tokenizer ends a `<script>` element at the first literal
    `</script` it sees, whatever the element's `type` — the corpus is scraped
    text and nothing rules that substring out of it. Escaping the slash is
    inert to `JSON.parse` and stops the substring closing the tag.
    """
    return json.dumps(data, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")


_STYLE = """
:root{color-scheme:light dark;--line:#8883;--dim:#8889;--ink:CanvasText}
*{box-sizing:border-box}
body{max-width:60rem;margin:0 auto;padding:1.5rem 1rem 8rem;
 font:15px/1.55 -apple-system,Segoe UI,Roboto,sans-serif}
h1{font-size:1.4rem;margin:0 0 .2rem}
.lede{color:var(--dim);margin:0 0 1.2rem}
.bar{position:sticky;top:0;z-index:5;background:Canvas;border-bottom:1px solid var(--line);
 padding:.6rem 0;margin-bottom:1rem;display:flex;gap:1rem;align-items:center;flex-wrap:wrap}
.bar b{font-variant-numeric:tabular-nums}
.block{margin:0 0 2rem;border:1px solid var(--line);border-radius:.6rem;overflow:hidden}
.block>header{padding:.5rem .75rem;background:var(--line);display:flex;gap:.6rem;align-items:center}
.block>header input{font:inherit;font-weight:700;background:transparent;border:0;
 color:var(--ink);flex:1;padding:.15rem .3rem;border-radius:.3rem}
.block>header input:focus{outline:2px solid #8886;background:Canvas}
.count{color:var(--dim);font-size:.85rem;font-variant-numeric:tabular-nums}
.card{border-top:1px solid var(--line);padding:.6rem .75rem}
.card:first-child{border-top:0}
.row{display:flex;gap:.6rem;align-items:baseline;flex-wrap:wrap}
.badge{background:var(--line);border-radius:.35rem;padding:.05rem .45rem;font-size:.85rem;
 font-variant-numeric:tabular-nums}
.title{font-weight:600}
.co{color:var(--dim);font-size:.88rem}
.acts{margin-left:auto;display:flex;gap:.3rem;flex-wrap:wrap}
button{font:inherit;font-size:.82rem;padding:.15rem .5rem;border:1px solid var(--line);
 border-radius:.35rem;background:transparent;color:var(--ink);cursor:pointer}
button:hover{background:var(--line)}
button[disabled]{opacity:.3;cursor:default}
textarea{width:100%;margin-top:.5rem;font:inherit;font-size:.88rem;padding:.4rem .5rem;
 border:1px solid var(--line);border-radius:.35rem;background:transparent;color:var(--ink);
 resize:vertical}
.advert{white-space:pre-wrap;word-wrap:break-word;font-size:15px;line-height:1.7;max-width:44rem;
 background:#8881;padding:.9rem 1rem;border-radius:.4rem;margin:.6rem 0 0;max-height:34rem;
 overflow:auto}
.heading{display:flex;gap:.6rem;align-items:baseline;cursor:pointer;flex:1;min-width:14rem;
 border-radius:.3rem;padding:.1rem .2rem}
.heading:hover{background:#8881}
.heading:focus-visible{outline:2px solid #8886}
.arrow{color:var(--dim);font-size:.8rem;width:.8rem}
.card{cursor:grab}
.card.dragging{opacity:.4}
.card.over-top{box-shadow:inset 0 3px 0 -1px currentColor}
.card.over-bottom{box-shadow:inset 0 -3px 0 -1px currentColor}
.notes{display:grid;grid-template-columns:1fr 1fr;gap:.5rem}
@media (max-width:44rem){.notes{grid-template-columns:1fr}}
.note.liked:focus{outline:2px solid #16a34a66}
.note.disliked:focus{outline:2px solid #dc262666}
.legacy{color:var(--dim);font-size:.82rem;margin:.4rem 0 0}
#export{min-height:7rem;font:12px/1.5 ui-monospace,monospace}
.warn{color:#b45309}
"""

_BODY = """
<h1>Twenty held-out adverts</h1>
<p class="lede">Sort them into the three blocks — rename the blocks to whatever
they actually mean to you — then order them <em>within</em> each block, best at
the top. The final order is the three blocks read top to bottom. Say why in the
notes boxes whenever there is a why, and keep the two apart: what drew you in is
a place to search next, what put you off is something to stop returning. One box
for both collapses them into a string nothing can pull apart again.</p>
<div class="bar">
  <b><span id="left">0</span> unsorted</b>
  <button id="reset">Start over</button>
  <button id="copy">Copy result</button>
  <span id="status" class="count"></span>
</div>
<div id="lists"></div>
<h2 style="font-size:1rem">Result</h2>
<p class="count">Copy this and paste it back into the session.
  <button id="copy-here">Copy result</button></p>
<textarea id="export" readonly></textarea>
"""

_SCRIPT = """
const DATA = JSON.parse(document.getElementById('integral-data').textContent);
const KEY = 'integral-t20-blind-ranking-v1';
const POOL = 'unsorted';
const BY_ID = Object.fromEntries(DATA.pages.map(p => [p.offer_id, p]));

function fresh() {
  return {
    names: DATA.block_names.slice(),
    lists: {unsorted: DATA.pages.map(p => p.offer_id), b0: [], b1: [], b2: []},
    notes: {},
    open: {},
  };
}

let state = load();
let dragging = null;

function load() {
  let raw = null;
  try { raw = localStorage.getItem(KEY); } catch (err) { return fresh(); }
  if (!raw) return fresh();
  let saved;
  try { saved = JSON.parse(raw); } catch (err) { return fresh(); }
  const base = fresh();
  if (!saved || typeof saved !== 'object' || !saved.lists) return base;
  // Rebuild from the ids this page was built with, so a saved session from an
  // older draw cannot resurrect an advert that is no longer in the twenty.
  const seen = new Set();
  const clean = {};
  for (const key of Object.keys(base.lists)) {
    clean[key] = (saved.lists[key] || []).filter(id => BY_ID[id] && !seen.has(id));
    clean[key].forEach(id => seen.add(id));
  }
  clean[POOL] = clean[POOL].concat(DATA.pages.map(p => p.offer_id).filter(id => !seen.has(id)));
  return {
    names: Array.isArray(saved.names) && saved.names.length === 3 ? saved.names : base.names,
    lists: clean,
    notes: migrate(saved.notes),
    open: saved.open && typeof saved.open === 'object' ? saved.open : {},
  };
}

function migrate(saved) {
  // v1 stored one string per advert. Nothing can split it into liked/disliked
  // except its author, so it is preserved under `legacy` and shown read-only.
  if (!saved || typeof saved !== 'object') return {};
  const out = {};
  for (const [id, value] of Object.entries(saved)) {
    if (!BY_ID[id]) continue;
    if (typeof value === 'string') { if (value.trim()) out[id] = {legacy: value}; }
    else if (value && typeof value === 'object') out[id] = value;
  }
  return out;
}

function save() {
  try { localStorage.setItem(KEY, JSON.stringify(state)); }
  catch (err) { document.getElementById('status').textContent = 'could not save locally'; }
}

function listOf(id) {
  return Object.keys(state.lists).find(key => state.lists[key].includes(id));
}

function move(id, target) {
  const from = listOf(id);
  if (from === target) return;
  state.lists[from].splice(state.lists[from].indexOf(id), 1);
  state.lists[target].push(id);
  render();
}

function place(id, target, anchor, before) {
  const from = listOf(id);
  state.lists[from].splice(state.lists[from].indexOf(id), 1);
  const list = state.lists[target];
  // Read the anchor's index *after* the removal: dragging an item downward
  // inside its own list shifts every index below it by one, and computing the
  // insertion point first drops it one place short every time.
  const at = anchor === null ? list.length : list.indexOf(anchor);
  list.splice(at < 0 ? list.length : at + (before ? 0 : 1), 0, id);
  render();
}

function shift(id, delta) {
  const key = listOf(id);
  const list = state.lists[key];
  const at = list.indexOf(id);
  const to = at + delta;
  if (to < 0 || to >= list.length) return;
  list.splice(at, 1);
  list.splice(to, 0, id);
  render();
}

function el(tag, attrs, children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (key === 'text') node.textContent = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (value !== null && value !== false) node.setAttribute(key, value);
  }
  (children || []).forEach(child => node.appendChild(child));
  return node;
}

function card(id, key, index, length) {
  const page = BY_ID[id];
  const acts = el('div', {class: 'acts'});
  if (key !== POOL) {
    acts.appendChild(el('button', {
      text: '\\u25b2', title: 'up', disabled: index === 0 ? '' : false,
      onclick: () => shift(id, -1),
    }));
    acts.appendChild(el('button', {
      text: '\\u25bc', title: 'down', disabled: index === length - 1 ? '' : false,
      onclick: () => shift(id, 1),
    }));
  }
  ['b0', 'b1', 'b2', POOL].forEach(target => {
    if (target === key) return;
    acts.appendChild(el('button', {
      text: target === POOL ? '\\u21ba pool' : '\\u2192 ' + state.names[Number(target[1])],
      onclick: () => move(id, target),
    }));
  });

  // The whole heading is the disclosure control. The first version had a
  // button reading "read", which was taken for "mark as read" — a state, not
  // an action, and the opposite of what it did.
  const toggle = () => { state.open[id] = !state.open[id]; render(); };
  const arrow = el('span', {
    class: 'arrow', text: state.open[id] ? '\\u25be' : '\\u25b8', 'aria-hidden': 'true',
  });
  const heading = el('span', {class: 'heading', role: 'button', tabindex: '0', onclick: toggle}, [
    arrow,
    el('span', {class: 'badge', text: String(page.position)}),
    el('span', {class: 'title', text: page.title || '\\u2014'}),
    el('span', {class: 'co', text: (page.company || '\\u2014') + ' \\u00b7 ' + page.language}),
  ]);
  heading.addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); toggle(); }
  });

  const row = el('div', {class: 'row'}, [heading, acts]);

  const said = state.notes[id] || {};
  const box = (side, placeholder) => {
    const ta = el('textarea', {
      rows: '2', class: 'note ' + side, placeholder: placeholder,
      'aria-label': side,
      oninput: event => {
        const now = state.notes[id] || (state.notes[id] = {});
        now[side] = event.target.value;
        save();
        refreshExport();
      },
    });
    ta.value = said[side] || '';
    return ta;
  };
  const notes = el('div', {class: 'notes'}, [
    box('liked', '\\u2713 what drew you in (remote, the product, the pay\\u2026)'),
    box('disliked',
        '\\u2717 what put you off (a stack you do not know, hybrid, consultor\\u00eda\\u2026)'),
  ]);

  const parts = [row, notes];
  // A note typed before the boxes were split cannot be divided by anything but
  // the person who wrote it, so it is shown verbatim rather than guessed at.
  if (said.legacy) parts.push(el('p', {class: 'legacy', text: 'earlier note: ' + said.legacy}));
  if (state.open[id]) parts.push(el('div', {class: 'advert', text: page.text}));
  const node = el('div', {class: 'card', draggable: 'true', 'data-id': id}, parts);
  node.addEventListener('dragstart', event => {
    dragging = id;
    event.dataTransfer.effectAllowed = 'move';
    // Firefox refuses to start a drag without payload.
    event.dataTransfer.setData('text/plain', id);
    node.classList.add('dragging');
  });
  node.addEventListener('dragend', () => { dragging = null; render(); });
  node.addEventListener('dragover', event => {
    if (!dragging || dragging === id) return;
    event.preventDefault();
    const box = node.getBoundingClientRect();
    node.classList.remove('over-top', 'over-bottom');
    node.classList.add(event.clientY < box.top + box.height / 2 ? 'over-top' : 'over-bottom');
  });
  node.addEventListener('dragleave', () => node.classList.remove('over-top', 'over-bottom'));
  node.addEventListener('drop', event => {
    event.preventDefault();
    const before = node.classList.contains('over-top');
    node.classList.remove('over-top', 'over-bottom');
    if (dragging && dragging !== id) place(dragging, listOf(id), id, before);
  });
  return node;
}

function block(key, title) {
  const list = state.lists[key];
  const header = el('header', {});
  if (key === POOL) {
    header.appendChild(el('b', {text: title}));
  } else {
    const name = el('input', {value: state.names[Number(key[1])], 'aria-label': 'block name'});
    name.addEventListener('input', event => {
      state.names[Number(key[1])] = event.target.value;
      save();
      refreshExport();
    });
    header.appendChild(name);
  }
  header.appendChild(el('span', {class: 'count', text: list.length + ' of 20'}));
  const node = el('section', {class: 'block'}, [header]);
  list.forEach((id, index) => node.appendChild(card(id, key, index, list.length)));
  // An empty block has no card to aim at, so the block takes the drop itself.
  node.addEventListener('dragover', event => {
    if (dragging) event.preventDefault();
  });
  node.addEventListener('drop', event => {
    if (!dragging) return;
    if (event.target.closest('.card')) return;
    event.preventDefault();
    place(dragging, key, null, false);
  });
  return node;
}

function ordering() {
  return ['b0', 'b1', 'b2'].flatMap(key => state.lists[key]);
}

function nameProblem() {
  // The names are keys in the exported object, so two the same silently
  // overwrite one another and a whole block's ids vanish while `ordering` still
  // looks complete. `calibration.record` refuses that partition, but the
  // candidate should hear it here, where they can still fix it.
  const trimmed = state.names.map(name => (name || '').trim());
  if (trimmed.some(name => !name)) return 'every block needs a name';
  if (new Set(trimmed).size !== trimmed.length) return 'two blocks share a name';
  return null;
}

function result() {
  const blocks = {};
  ['b0', 'b1', 'b2'].forEach((key, index) => {
    blocks[state.names[index].trim()] = state.lists[key];
  });
  const notes = {};
  Object.keys(state.notes).forEach(id => {
    if (!BY_ID[id]) return;
    const said = {};
    ['liked', 'disliked'].forEach(side => {
      const text = (state.notes[id][side] || '').trim();
      if (text) said[side] = text;
    });
    if (Object.keys(said).length) notes[id] = said;
  });
  return {ordering: ordering(), blocks: blocks, notes: notes};
}

function refreshExport() {
  const left = state.lists[POOL].length;
  document.getElementById('left').textContent = String(left);
  const problem = nameProblem();
  const payload = result();
  payload.complete = left === 0 && !problem;
  document.getElementById('export').value = JSON.stringify(payload, null, 2);
  document.getElementById('status').className = left || problem ? 'count warn' : 'count';
  document.getElementById('status').textContent = problem
    ? problem
    : left
      ? 'incomplete — ' + left + ' still in the pool'
      : 'all twenty placed';
}

function render() {
  const host = document.getElementById('lists');
  host.textContent = '';
  host.appendChild(block(POOL, 'Unsorted'));
  ['b0', 'b1', 'b2'].forEach(key => host.appendChild(block(key)));
  save();
  refreshExport();
}

async function copyResult() {
  const text = document.getElementById('export').value;
  try { await navigator.clipboard.writeText(text); }
  catch (err) { document.getElementById('export').select(); }
  document.getElementById('status').textContent = 'copied';
}

// Two of them: the sticky bar is where you are while sorting, the result box is
// where you are when you have finished, and reaching back up for the button is
// the moment the page feels awkward.
document.getElementById('copy').addEventListener('click', copyResult);
document.getElementById('copy-here').addEventListener('click', copyResult);

document.getElementById('reset').addEventListener('click', () => {
  state = fresh();
  render();
});

render();
"""


def build_page(pages: list[dict[str, Any]], block_names: tuple[str, ...]) -> str:
    """Render the standalone page from a `calibration.presentation()` payload."""
    for page in pages:
        # The gate, enforced where the page is built rather than trusted: this
        # generator can only render what `presentation()` handed it, so a score
        # cannot arrive here by a route nobody checked.
        stray = set(page) - calibration.PAGE_KEYS
        if stray:
            raise ValueError(f"a blind page may not carry {sorted(stray)}")
    data = {"pages": pages, "block_names": list(block_names)}
    return (
        '<!doctype html><meta charset="utf-8">\n'
        "<title>Blind ranking — twenty held-out adverts</title>\n"
        f"<style>{_STYLE}</style>\n"
        '<script type="application/json" id="integral-data">'
        + _embed_json(data)
        + "</script>\n"
        + _BODY
        + "<script>\n"
        + _SCRIPT
        + "\n</script>\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build T20's blind ranking page.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args(argv)

    # Deliberately no `--store`. `calibration.record` re-derives the drawn set
    # from `DEFAULT_STORE_PATH` to validate what comes back, so a page built
    # from a different store would export ids `record` then rejects as unknown —
    # an hour of the candidate's reading that cannot be saved. One store, no flag.
    pages = calibration.presentation(calibration.draw())["pages"]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(build_page(pages, DEFAULT_BLOCK_NAMES), encoding="utf-8")
    print(f"{args.out} — {len(pages)} adverts, {args.out.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
