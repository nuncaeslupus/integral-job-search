---
name: connector-new
description: Use whenever a job board has to be connected to this tool — adjudicating its robots.txt with a negative control, finding the request behind a page that renders after load, mapping its fields to the offer vocabulary, and capturing the fixture and probe a package ships. Triggers — "add a connector", "connect this board", "can we read this site". Not for repairing a connector that has stopped parsing — that is a selector change, not a new package.
metadata:
  type: capability
---

# connector-new

CANARY: connector-new-loaded-2026-09-06-29f87839-dfd5ad39b00f7693

A connector is a declaration, not code: five files that say where a board's
adverts are and how to read them. This is the order to write them in, and the
order matters — each step can rule the board out, and the cheap ones come
first.

## The five files

```
connectors/<site>_<locale>/
  connector.yaml       what to fetch and how to read it
  meta.yaml            market, language, maintainer, robots verdict
  fixture/list.html    the listing, as served
  fixture/detail.html  one advert, as served — only if the list has no body
  probe/list.html      a SECOND capture, carrying DIFFERENT offers
  probe/captured.json  when and from what URL
```

The probe is not a copy of the fixture. A probe naming the same adverts
exercises the same markup, so the rot check runs, passes, and measures nothing —
two of eighteen packages were in that state until T127 found them.

## Step 1 — probe the board before writing anything

```bash
uv run python3 ${CLAUDE_SKILL_DIR}/scripts/query_board.py \
    --listing "https://<board>/jobs?q=python" \
    --advert  "https://<board>/jobs/<one-advert>" \
    --refused "https://<board>/<a path robots must refuse>" \
    --refused "https://<board>/<and a second one>"
```

It answers the three questions that decide the rest, and exits 1 when the
board is refused. Read all of it; the second-reader line in particular.

**`--refused` is not optional.** A `True` with no `False` beside it is
indistinguishable from a matcher that says yes to everything, which is why
`connectors/ruled-out.yaml` requires a negative control from the *same* file.
Two paths the board's own `robots.txt` disallows will do.

**A `ClaudeBot` group does not rule the board out.** Under RFC 9309 a crawler
matches its own product token and falls back to `*`; ours is
`integral-job-search/0.1`. CLAUDE.md's own section says this, and the ledger
header says it twice. Only a `*`-group disallow rules a board out.

## Step 2 — if the biggest response has no adverts in it

The page fetched its rows from somewhere, and that somewhere is usually a plain
request this tool can make too. Record a browser capture and find it — use the
`har` skill, whose `--response-match` takes a string seen on the page and
returns the request that produced it.

Then read what that request actually needed. Three outcomes:

| what the capture shows | what to do |
|---|---|
| a plain URL with a query parameter | that is the listing URL; write the connector |
| fixed headers with no credential (`HX-Request`, `X-Requested-With`) | `client:` may cover it — see `Client` in `connectors.py` |
| an API key, a bearer token, a session cookie | **stop.** There is no field for a credential and there must not be one |

`foorilla.com` was ruled unreachable by eye and turned out to be the second row:
two fixed headers, no cookie, no account. The capture is what showed it.

## Step 3 — map the fields, and map only what is there

The vocabulary is closed. These twelve, plus `detail_url` on the list only:

```
title  company  url  source_ref  text
location_raw  location_country  location_remote
salary_min  salary_max  salary_currency  salary_period
```

Two grammars, one per response type:

```yaml
# markup
title: {css: "a.stretched-link"}
detail_url: {css: "a.stretched-link", attr: "hx-get"}

# JSON, in the response or embedded in the page
salary_min: baseSalary.value.minValue
```

**A field the board does not publish is left unmapped.** Guessing is the
expensive direction: a missing salary is a gap the candidate can see, and a
wrong one is a number that looks fine and ranks the offer wrongly.

**One text node holding several values** — `€50.000 - €65.000`, or a title
carrying `1.&nbsp;` in front of it — is what `take:` is for. Four members,
implemented in `connectors.py`, and the connector names one:

```yaml
salary_min:      {css: ".salary", take: "range_low"}
salary_max:      {css: ".salary", take: "range_high"}
salary_currency: {css: ".salary", take: "currency"}
title:           {css: "h2.titel", take: "last_text_node"}
```

Every member fails closed: text that is not the shape the name describes
yields nothing, never the unparsed string.

**No regex, and no new member without a task.** The grammar is deliberately too
small to smuggle anything through. A board needing a fifth member is an
engine change with its own gate — not a widening of this file.

## Step 4 — capture the fixture and the probe

- **Fixture**: the listing as served, plus one advert page if the list rows
  carry no `text`.
- **Probe**: the same board, later or under a different query, carrying **at
  least one offer the fixture does not**. Measured, never assumed:

```bash
uv run python3 -c "
import re, sys
a, b = (open(p).read() for p in sys.argv[1:])
pat = r'<the detail_url pattern for this board>'
x, y = set(re.findall(pat, a)), set(re.findall(pat, b))
print('shared', len(x & y), 'of', len(y))" fixture/list.html probe/list.html
```

**Never capture an advert a candidate was reading.** The set of ads a person
opens carries their field, level, city and the fact that they are looking, and
a fixture in a public repository carries that for ever.

## Step 5 — the two records the library requires

`meta.yaml` carries `country` (`ES`, `GLOBAL`, …), `language`, `maintainer`,
`last_verified`, the `policy:` block, and the `fixture:` provenance.

`connectors/robots-adjudications.yaml` gets one row, and its `standing` is the
part to get right — `query_board.py`'s second-reader line names which:

| the second reader | `standing` |
|---|---|
| refused at least one path | `two_parsers_agreed` |
| ran and answered True to everything | `single_parser`, with that as the `reason` |
| could not be run at all | `single_parser`, with *that* as the reason |

The last two are different findings and the record must say which. CPython's
parser returns the first matching rule rather than RFC 9309's longest match, so
on any file opening with `Allow: /` it cannot refuse — and an agreement with a
parser that cannot disagree is not an agreement.

## Step 6 — prove it parses, then gate it

```bash
uv run python3 -c "
from pathlib import Path
from integral.connectors import load_connector, parse_list_page, parse_detail_page, build_offer
p = Path('connectors/<name>')
c = load_connector(p)
rows = parse_list_page(c, (p/'fixture/list.html').read_text())
print(len(rows), 'rows'); print(rows[0])
d = parse_detail_page(c, (p/'fixture/detail.html').read_text()) if c.detail else {}
print(build_offer(c, list_fields=rows[0], detail_fields=d, url='https://…'))"
```

Then `make host-gate`. Two committed counts move when a package lands and both
must be **checked, not bumped**: `connector_runs_evaluated` (T72) and
`robots_adjudications_without_a_competent_second_reader` (T116). If a third
moves, that is a finding — something else is package-sensitive.

## Step 7 — run it against the live board, not its fixture

A package that parses its own capture perfectly can still return nothing.
`foorilla_en` shipped green and then produced **50 rows, 40 advert fetches and
0 offers** on the first live run, because the advert page needed its own
client headers and answered 200 with the site's shell. The fixture could not
have shown that: it is the response, not the request.

```bash
uv run python3 -c "
from datetime import UTC, datetime
from integral.connector_coverage import installed_packages
from integral.identity import ProfileStore, default_profiles_root
from integral.robots import Robots
from integral.sourcing import DEFAULT_CONNECTORS_DIR, _one_board
p = next(x for x in installed_packages(DEFAULT_CONNECTORS_DIR) if x.name == '<name>')
print(_one_board(ProfileStore(default_profiles_root(), '<handle>'), p,
      'python', phrases=('python',), fetch=<a live fetcher>,
      at=datetime.now(UTC).isoformat(timespec='seconds'),
      directory=DEFAULT_CONNECTORS_DIR, page_count=1, robots=Robots()))"
```

`items` far above `added` with `detail_fetched` non-zero is this failure. `drop_reason` names the field that went missing.

## When to stop and file an engine gap instead

Four of these were found in one afternoon, so it is the normal outcome, not a
failure:

- the board serves a charset the connector cannot declare → `charset:`
- the body is on the advert's page and nothing fetches it → T130
- one text node holds a range → `take:` (T132)
- the listing needs fixed headers → `client:` (T133)

Each is a task with its own gate. **Do not work around one in a connector
file** — a selector chosen to dodge an engine gap is a package that breaks the
day the gap is closed, and nothing records why it was written that way.

## Boundary

This skill builds a **new** package. A connector that parsed yesterday and
returns nothing today is rot, not a new board: read
`connector_health.assess_package`, which compares the fixture against the probe
and names what stopped matching.
