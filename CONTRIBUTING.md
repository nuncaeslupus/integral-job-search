# Contributing a connector or a language pack

Two kinds of contribution are wanted here, and both are **data, not code**: a
connector package under `connectors/`, and a language's strings in
`strings/catalogue.json`. Neither needs a change under `src/`, and a pull
request that mixes one with the other is much harder for one person to review.

The tool can build the connector bundle for you — it discloses exactly which
files would be sent, asks once, and writes the bundle to
`~/.integral-job-search/outbox/` along with the `gh pr create` command. It never
sends anything itself. The pull request body is generated from your
`meta.yaml`, so whatever you record there is what a reviewer reads.

## The failure mode that matters: a probe that repeats its fixture

A connector package carries two captures of the same board:

- `fixture/list.html` — the read the connector's selectors were written against.
- `probe/list.html` — a **second, separate** read, used to check the parser has
  not rotted against markup it has not already seen.

If the probe names the same offers as the fixture, that check compares the same
markup twice. It cannot fail. A parser that broke on anything new would still
be reported healthy, and nothing in the diff looks wrong.

This is not hypothetical and it is not caught by looking:

- `ticjob_es` shipped a probe that was **byte-identical** to its fixture.
- `getmanfred_es` shipped one **14 bytes** from its fixture — an honest capture
  from a later day, truncated to the same three offers. Its `meta.yaml` argued
  the near-equality was fine because the capture was genuine. The capture was
  genuine and the check still compared nothing.

Both were found by measurement, not by review, and both had passed every gate
for weeks. `connector_health.probe_divergence` now reports it, and
`status/evidence/T127.json` records the count.

**So capture the probe differently on purpose.** Any one of these is enough:

- a different query (`tecnoempleo_es` uses `?te=python` for the fixture and
  page 2 of the same search for the probe);
- a later day, keeping offers the fixture does not have;
- a different page of the same listing.

The rule the check applies: **at least one offer in the probe must not appear
in the fixture.** One is the boundary, not a percentage — a probe that adds a
single advert does compare something.

## What a package must record

`meta.yaml` is the provenance, and the pull request body is rendered from it:

| key | what it must say |
|---|---|
| `site`, `country`, `language`, `maintainer` | who and where |
| `last_verified` | the day every URL, selector and count was measured live |
| `policy.listings` | `public` only if an anonymous client gets the full text |
| `policy.robots_txt` | `respected`, argued from the board's actual `robots.txt` |
| `policy.authentication` | `none` — a connector that needs credentials is out of scope |
| `fixture.provenance` | `sampled`. **Never an advert a candidate was reading** |
| `fixture.bodies` | `excerpted` if ad text was cut, with the cut described |
| `fixture.client_ip` | `redacted`, and say whether anything was actually removed |

Two things a fixture must never be: an advert someone was looking at (the set of
ads a person opens carries their field, level, city and the fact that they are
looking, and a public repository carries that forever), and a page re-serialised
by a parser (that repairs the markup the fixture exists to preserve — cut in the
raw bytes, on tag boundaries).

## Before you open the pull request

```bash
uv run --extra dev pytest tests/test_connector_contract.py -k <your_package>
uv run --extra dev pytest tests/test_probe_divergence.py
```

The first is the acceptance gate `install()` runs before the connector is used.
The second is the check described above.

## Language packs

`strings/catalogue.json` holds one entry per candidate-facing string, keyed in
English as the source language. A translation carries the text and an `of`
field — the sha256 of the source it was made from — so a source string that
changes leaves every translation of it visibly stale rather than silently wrong:

```json
"card_pay": { "en": "pay",
              "es": {"text": "sueldo", "of": "9350872d…"},
              "ca": {"text": "sou",    "of": "9350872d…"} }
```

`uv run python -m integral.strings --stamp` fills the hashes in. Run
`uv run --extra dev pytest tests/test_strings.py` before opening the pull
request; it reports any key you missed and any translation gone stale.

**Advert text is never translated.** The tool cites evidence spans from the ad,
so an ad written in Spanish is shown in Spanish whatever language the interface
is in. A language pack translates what the *tool* says, nothing else.

## Scope

A pull request adding a connector or a language pack should touch **only**
`connectors/<package>/` or `strings/`. If you think a change under `src/` is
needed to support your board, open an issue first — that is a change to the
connector schema, and it needs a different conversation.
