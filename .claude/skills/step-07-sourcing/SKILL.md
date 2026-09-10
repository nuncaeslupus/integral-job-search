---
name: step-07-sourcing
description: Step 7 (`sourcing`) of the candidate process — fetches and dedupes live offers against the candidate's constraints. Do NOT use for reading what an offer's text actually means — that is step 8, which runs after this step's offers land.
---

# step-07-sourcing

The candidate gets live offers worth looking at, with the stale ones retired and nothing they have already rejected coming back.

CANARY: step-07-sourcing-loaded-2026-08-18-f42ed484-55019180c91ff6e0

**Required.** No candidate reaches a ranking without this step — §2.5 promises every *offered* step may be declined, and this is not one of those.

## When to load

Load when the candidate's session is at step 7 (`sourcing`) of the thirteen-step
process (`status/spec-v2-steps.md`) — the previous step finished, or the step runtime's
`offered()`/`decide_resumption()` (T34/T35) names `sourcing` as where this candidate should
be. Phase: **loop**.

If the runtime (`integral.step_runtime.offered`) is not offering `sourcing` for this candidate, defer to whichever step it does offer instead of running this one out of turn.

## Preconditions and inputs

`profile/constraints.json`, which decides where and what to search for. Required; runs on a schedule, on request, or when constraints change.

**Reads:** `profile/constraints.json`; `offers/*.json` and `offers/tombstones.jsonl` for dedup; connector configuration.

## Protocol — the manner, not the mechanism

- Mostly automatic, with one conversational duty: establish how far the search can travel, at the moment it becomes relevant — remote, commuting distance, relocation, and cross-border employment (employed or contracting, paid where, taxed where).
- Reach beyond the obvious portals to boards specialised in the candidate's field, and go to employers directly where the field has obvious ones.
- **Deduplication is by similarity, not by hash** — the same job at two boards is rarely byte-identical.
- Where a source needs a login, drive the candidate's **own browser session** rather than storing credentials — nothing to leak, nothing to rotate.

**Say what is happening before a silence.** Work the candidate waits through — creating their profile, running a check, saving what they have just said — is named **before** it starts, in one short line, and closed when it finishes. Acknowledge the person first, then do the work, then come back to them; never open a run of tool calls on someone who has just answered. An unexplained pause is indistinguishable from a tool that has hung, and the candidate has no way to ask.

In this step that sounds like:

```text
"Searching the boards with your constraints on — this takes a moment."
…then, once the work is finished…
"Thanks for waiting — here's what came back. …"
```

**Never:**

- Never store a credential in a connector file — authenticated sources use the candidate's own browser session.
- Never send anything but constraints (role, place, band) to a job source — no profile, episode, trait or CV content.

## Coverage — say when nothing here covers this market

Before presenting a single offer, ask what covers the candidate's market:

```bash
uv run python -m integral.connector_coverage --country ES
```

**When no connector covers the candidate's market, say so — plainly, and before the results.**
A run that falls back to a general web search looks, from the candidate's chair, exactly like a
run against their boards: seven adverts arrive either way, and only one of the two searched the
market. `examplejobs_es` is not coverage — `examplejobs.test` is a worked example of T32's
format, not a job board, and `assess_coverage` counts it as example-only for that reason.

Then offer the two things that actually exist. A disclosure with no way out of it is a dead end:

- **Build a connector for a named portal.** The candidate names the board they would use —
  InfoJobs, a sector board, an employer's careers page — and the `connector-new` skill is the
  procedure, with `connectors/examplejobs_es/` as the worked example to copy.

  **Ask before building one, and say what it costs.** It is a detour out of the search the
  candidate came for, it can take a large part of a session, and step 1 of the procedure can
  rule the board out after all of it. So name the board, say roughly what it will take, and
  wait — never start one because the results looked thin. The owner's instruction:
  *"dado que crear un conector puede consumir muchos tokens, debes decírselo antes al usuario."*
- **Drive the candidate's own browser session** on a source that needs a login, the same route
  this step already takes for authenticated sources. Nothing stored, nothing to rotate.

**A search result is never presented as a connector result.** An offer a general web search
produced is built through `build_search_offer` and carries `source: web_search` — a name
`parse_connector` refuses to let any connector claim — so what a search found stays legible as
such in the stored record and in the count the candidate is given.

**And a search hit is a pointer, not an advert.** It is where the advert *was* when the index
last looked. What turns it into an offer is fetching it at source and finding it live — see
`## Liveness` below. So a general web search discovers portals and points at vacancies; it never
collects one.

What that sounds like:

```text
"Before I show you these — I don't have a connector for the Spanish market. Nothing here talks
to InfoJobs or the sector boards directly, so what follows came from a general web search, not
from a search of the boards you'd actually use. Two things I can do about that: build a
connector for a board you name, or work through your own browser session on a site you're
logged into. Either of interest?"
```

## Boards served only to a real browser — read them through the candidate's own

Some boards show their listings only to a browser that runs their JavaScript check; the tool's
own request gets a page saying the browser could not be identified. InfoJobs does this, and its
connector says `client: browser`. `source()` never sends such a board to the plain fetch: without
pages from the candidate's browser it reports the board **skipped**, and says so.

**Never** get past the check any other way: no copying the browser's cookies or tokens into
another client, no headless browser, no browser user agent on the tool's own requests, no CAPTCHA
solving. If the candidate's browser shows a puzzle, stop and ask them to solve it themselves.

1. **What to open.** `browser_urls(constraints, aim)` lists the searches, robots already checked.
2. **Ask once, naming what will happen.** Saving a page is a download, and it needs a yes:

   ```text
   "InfoJobs only shows its listings to a real browser. I'll open these N searches in your Chrome
   and save each page to your Downloads folder, about 1.3 MB each. OK?"
   ```

3. **Open each URL in the candidate's Chrome** and wait until the listing is on screen. The first
   page stays blank for about ten seconds while the check runs. Then run this in the tab. It saves
   the rendered page with the URL on its first line, so the page can answer only that search:

   ```js
   const html = `<!-- integral-capture: ${location.href} -->\n` + document.documentElement.outerHTML;
   const a = document.createElement('a');
   a.href = URL.createObjectURL(new Blob([html], {type: 'text/html'}));
   a.download = 'integral-capture-' + Date.now() + '.html';
   document.body.appendChild(a); a.click(); a.remove();
   a.download
   ```

4. **Pass the pages in.** The files are in `$(xdg-user-dir DOWNLOAD)` (`~/Descargas` on a Spanish
   desktop), named by the value the snippet returns:
   `source(..., browser=from_captures([paths]))`. The fetch log records `via: candidate_browser`.
5. **Liveness goes through the browser too.** Open each advert with its query string removed:
   robots forbids InfoJobs' `applicationOrigin=`, so check `Robots().allows(url)` first. Capture it
   the same way, then pass `url, html = read_capture(path)` into
   `read_response(offer.id, 200, html, advert_url=<the URL opened>, final_url=url,
   title=offer.title)`.

Tell the candidate the saved pages stay in their Downloads folder and that they can delete them.

## Liveness — a search index is not a vacancy

**Real searches are run inside the portals.** A general web search is for *discovering which portals
exist* for this candidate's field, and for pointing at vacancies to go and check — never for
collecting adverts as offers. The index is a memory of a page, and the page moves on: of the seven
offers one test session produced, two answered 403 and the rest read "Puesto ocupado". Not one was a
live vacancy, and the candidate was shown all seven (D-18).

This is the same rule `## Coverage` above states from the other end: a connectorless market is
disclosed, a search hit is labelled `source: web_search`, and *neither of those makes it an offer*.
The fetch does.

**Fetch the advert's own page before it becomes an offer.** Not the search result, not the listing
row — the advert's own URL, following any redirect to its final destination. Then read the response
through `integral.liveness`:

```python
from integral.liveness import presentable, read_response, expire

check = read_response(                 # pass where the fetch LANDED, not only where it was sent:
    offer.id, status_code, body,       # a retired advert often 301s to a generic listings page,
    advert_url=offer.url,              # which answers 200 and is not the advert. A landing page
    final_url=where_it_landed,         # that is a different page reads `unverified`.
)
offer = expire(offer, check)                    # dead -> status "expired"
shown, withheld = presentable(offers, checks)   # only checked-and-live reach the candidate
```

Three answers, and the third is not a rounding error:

- **live** — fetched, and the body carries no closure notice. Only these reach the candidate.
- **dead** — the server says 404/410, or the body says "puesto ocupado", "oferta cerrada", "vacante
  cubierta", "position filled". Mark it `expired` and tombstone it.
- **unverified** — a 403, a timeout, or nobody fetched it. **Withheld, but not expired**: being
  blocked is not evidence the job is gone, and tombstoning a live vacancy stops it ever being offered
  again. Say the count rather than hiding it.

A **3xx** is one of these too: a retired advert is commonly redirected to a generic listings page that
renders perfectly and says nothing about the vacancy, and a `304` describes a cache rather than today.
Follow the redirect and judge what it lands on.

**Never present an unverified advert as a live offer.** The default is not "alive" — that default is
exactly how seven dead adverts reached someone looking for work. `presentable` enforces it: an offer
with no check is withheld *on the absence*, and a record already `expired` or `archived` is not
un-retired by a later `live` verdict.

**Report the withheld count.** Silently dropping four of nine looks identical to nine having been
found — and the candidate then wonders why so little came back.

What that sounds like when it happens:

```text
"Nine came back, but I could only confirm four are still open. Three had already been filled — I've
retired those — and two I couldn't reach at all, so I've left them aside rather than waste your time
on a maybe. Here are the four."
```

## Stop rule

All configured sources have been polled and results normalised. **Hard cap: a per-run offer ceiling**, so one badly-scoped query cannot deliver hundreds of adverts nobody will read.

## When declined

Not applicable to the fetch, which is required. The conversational reach question is declinable per question: an unanswered mobility question leaves the reach at its current setting.

## Outputs

`offers/<offer_id>.json` (normalised, status `new`), tombstone updates, expiry marks on offers no longer live at source.

## Boundary

**Invite forward; never close by offering to end the session.** Leaving is always allowed and
never the suggestion — the exit is offered only when the session has actually run long, or the
candidate sounds tired, and never as the standard close of this step. Naming it every time asks
someone who has answered four steps four separate times whether they would rather leave.
This governs the **exit** alone. §3.3's *offered skip* — "we can stop here and go look at real
jobs with what I have" — is a move **forward** to a provisional ranking, not a way out, and is
offered at the end of every first-run step exactly as that section requires.

What the tool says out loud when the step ends, verbatim — the settled example from the spec:

```text
"Fourteen new, six duplicates, and four have closed since last week. I'd look at them ranked rather than as a list, because the order is where the work on your preferences actually shows. Want to see them?"
```

Writes `last_activity`.

## Checkpoint — the number, not the prose

The step's acceptance gate is **`offer_schema_violations == 0`**,
owned by **T11**. That gate is a build-time measurement over evidence this step's
conversation produces; it is not computed here, and this skill's prose never asserts it passed.

What this skill checks, mechanically, before ending the step: run
`${CLAUDE_SKILL_DIR}/scripts/run_checkpoint.py --id <handle> [--input-dir <profiles-root>]`,
this skill's own checkpoint script. It reads the candidate's
`session/state.json` (T35) and profile tree (T34) and reports whether this step's *machine-visible*
half of the stop rule is met — every artefact `sourcing` produces is present, and nothing is
left outstanding in the recorded position — never by asking the model to eyeball the transcript
and decide.

Exit 0 means that half is satisfied *and* this step's acceptance gate is built, so the run
may be read as the step having passed. Exit 1 means coverage is not met (still open, or
blocked on a missing input). Exit 2 means the candidate or step could not be read. Exit 3
means coverage is met but the gate is not built, so the step cannot be certified — a
covered step is not a passed one (D-21).

The script writes its result to the candidate's own tree at `session/checkpoint-sourcing.json`, never to a shared or
global path.

## Gotchas

- An advert already stored is updated, not duplicated; one matching a tombstone by canonical URL or normalised text hash is **not re-added as new**.
- Purge runs here: offers never shortlisted and older than 60 days lose their body and keep their tombstone — reported rather than done silently.
