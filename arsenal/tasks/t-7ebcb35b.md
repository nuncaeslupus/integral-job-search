---
id: t-7ebcb35b
title: "T269: Liveness: an interrogative closure marker reads as a closure, killing live adverts"
priority: 5
requires: [human:gate]
---

Imported from issue #542

## What happens

`integral.liveness.read_response` scans the body for closure phrases
("oferta no disponible", "puesto ocupado", "vacante cubierta", …). jobfluent
puts a **report-this-advert button on every live advert page**:

```html
<div class="not-available row">
  <a class="btn btn-danger btn-lg" href="/es/offers/498ea9/report-filled">
    Oferta no disponible? Dínoslo!
  </a>
</div>
```

That is a *question offered to the reader*, not a statement about the vacancy.
The matcher reads it as a closure and returns `dead`.

## Measured

A live sourcing round on 2026-09-22 checked 52 adverts. Nineteen came back
`dead` — **every one of them jobfluent, i.e. 100% of that board**, and the most
on-target adverts in the run. Fetched by hand:

```
https://www.jobfluent.com/es/empleos/agentic-ai-engineer-barcelona-498ea9
HTTP 200, 72064 bytes, advert live, apply button present
verdict: dead   reason: "the advert's own page says 'oferta no disponible'"
```

The nineteen were restored to `new` in the affected profile by hand. Two older
jobfluent offers in the same store are still `expired` and are probably the same
bug from an earlier run; they were left alone because nothing distinguishes them
from a genuine closure without re-fetching.

## Why this is the bad direction

`dead` **tombstones** the offer, and the skill says so explicitly: a tombstoned
advert is never offered again. `unverified` withholds and is recoverable; `dead`
is not. So a false `dead` is permanent, silent, and removes exactly the adverts
a specialised board is best at.

## The change

A closure phrase decides nothing on its own — what settles it is whether the
page *asserts* the closure. At minimum the marker must not fire when it is:

- inside an `<a>`/`<button>`, or any element whose activation reports something;
- followed by `?` / `¿…?` — an interrogative is not an assertion;
- accompanied on the same page by live-advert evidence (an apply control, a
  structured `JobPosting` with no `validThrough` in the past).

Resist fixing this by adding a jobfluent-shaped exception to the phrase list.
That is the enumeration the repo has already paid for twice: the next board
words its report button differently and the same hole reopens with nothing to
catch it. The closed rule is *"a closure marker inside an interactive control,
or phrased as a question, is not the page asserting a closure"*.

## Acceptance gate

```bash
uv run pytest tests/test_liveness.py -q
```

Fixtures must include the real jobfluent markup above (live page → `live`), a
genuine closure on the same board (→ `dead`), and the interrogative form in
each supported language. Weight fail-open over fail-closed as the house rule
says — but note that here the *fail-closed* direction is the destructive one,
because it tombstones.

## Acceptance gate

<!-- This task came from an issue, so its "gate" is prose. Write a real check
     below, then DELETE the `requires: [human:gate]` line in the front matter.
     Until that line is gone the selector will not offer this task, which is
     deliberate: a prose gate runs nothing, and a gate that runs nothing passes
     everything. -->

```bash
# arsenal:gate-placeholder — replace with the real check; it may land in this task's own PR
false
```
