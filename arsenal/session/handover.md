# Session handover

## 00003. T194 / #520 — the talent.com connector is written, green and held at the second reader

**Verified live via `gh pr view` at the end of the session, not carried from memory.**

- **#520 is OPEN, `MERGEABLE`, head `4df6f5e42ae0370608576224802b29df9ab9c243`**, branch
  `arsenal/t-7c3ab914-a-talent-com-connector-for-the-spanish-m`, opened
  2026-09-21T15:50:46Z. Task `t-7c3ab914` is archived in the same diff with
  `status: merged` and its `status/plan.md` row ticked, so the merge closes it by itself.
- **Both halves of the local evidence are done.** CI green on that head (pytest 4m51s,
  ruff+mypy 21s, evidence 1m57s, verify-gates 15s); `bash tools/verified_gate.sh
  4df6f5e4…` **PASS** (5196 passed, 7 skipped, evidence no drift), verdict block pasted
  on the PR as `#issuecomment-5763568642`.
- **The one thing outstanding is the second reader.** `uv run python -m
  integral.review_reader check <pr-state.json>` exits **2** — no report on record, which
  is not a pass. The PR holds there deliberately. Next session: dispatch one
  independent reader (`model: opus`) against that exact head, then merge only while the
  head is still `4df6f5e4…`.
- **Worktree `/home/ivant/dev/ijs-t193` is still on disk** and is the branch's tree.
  Remove it after the merge (`git worktree remove ../ijs-t193`); remote ref deletion is
  refused on this surface, so do not script a branch cleanup.

**What the package is.** `connectors/talent_es/` — `es.talent.com` only; the
international subdomains are separate hosts with their own robots.txt and nothing has
adjudicated them. List `https://es.talent.com/jobs?k={query}&l=Espa%C3%B1a` (the `l=` is
not optional: without it the board answers 307 to the city the requester's IP
geolocates to), `pagination: {mode: none, max_pages: 1}` because p=2 is served empty on
every query measured, and a `detail:` block that fetches the advert body per row.

**Three findings worth carrying, none of them about talent.com:**

- **`integral.second_reader.allows(text, agent, target)` takes a PATH, not a URL — and
  a full URL returns True unconditionally.** A fail-open API shape, and the sibling
  `integral.robots.Robots().allows(url)` takes the full URL, so the two readers disagree
  about their own argument convention. Re-deriving this row's adjudication (requirement:
  never trust your own `connector.yaml`) appeared to **refute** it — all four paths True
  — until the arguments were fixed. Re-run with paths on both the snapshot and the live
  file: allowed True, refused False, row confirmed, `standing: two_parsers_agreed`
  stands. **Anyone re-deriving a robots row will hit this; pass paths.**
- **`tools/excerpt_fixture.py` matched `<div class="X">` exactly**, so it found nothing
  on a board serving `class="sc-f4dbceab-10 fRvput"` — and found it **silently**, since
  an unmatched span is left whole. One-line fix committed here (split the attribute,
  test membership). Any board using a multi-class wrapper was un-excerptable before this
  and nothing said so.
- **The `connector-new` skill's step 6 is stale.** It says exactly two committed counts
  move when a package lands (`connector_runs_evaluated`, T72;
  `robots_adjudications_without_a_competent_second_reader`, T116) and that "if a third
  moves, that is a finding". **Seven moved**, all seven truthful: the `+3`s in T126
  `boards_consulted` and T173 `plain_requests_made` are one outcome per phrase, which is
  `Run.steered`'s own definition. The stale claim is itself the finding — the skill needs
  a task.

**Two shared tests were rewritten from enumerations into closed rules**, per this file's
"an enumeration has no last element":

- `tests/test_pagination_capture.py::test_the_committed_library_has_no_unenforced_provenance`
  now derives the `live` package names from the library rather than naming three.
- `tests/test_sourcing.py::test_searched_and_handed_everything_are_reported_apart` now
  derives the steerable set from `accepts_query(connector) and not needs_browser(connector)`.
  **The derivation immediately found what the hand-written list had hidden**:
  `infojobs_es` is steerable, has a capture, and still never reaches `fetch` because it
  is browser-routed (T173). Note `accepts_query` lives in `integral.connectors`
  (line 3397), **not** `integral.sourcing` — mypy refuses the re-export.

Both rewrites and the acceptance gate are mutation-verified (mutant red on the
assertion, restore byte-identical and green), in fresh subprocesses with `.pyc` cleared.

**Two process facts that cost time and will cost it again:**

- **`open_task_pr.sh` has two gates, on opposite sides of the archive.** The **task
  gate** (`:253`) runs **pre-archive**; the **host gate** (`:645`) runs **post-archive**.
  So a task file whose acceptance gate is ```` ```bash make host-gate ``` ```` can never
  be green once its own plan row is ticked — D-27 requires the tick, and the tick is
  pre-archive at that point. Replaced with a ```` ```gate ```` fence naming a numeric
  key. **Write a numeric gate fence, never `make host-gate`, in a task file.**
- **`S8.json` is archive-driven by design and must be committed in its post-archive
  state.** The host gate read drift because the committed record held the pre-archive
  red value. Fix: simulate the archive, run `uv run python -m integral.plan_v2`,
  restore the task file, commit the regenerated record.
- The gate cell in `status/plan.md` must match `plan_v2._GATE_RE`
  (`^[a-z][a-z0-9_]*\s*(?:==|!=|<=|>=|<|>)\s*-?\d+(\.\d+)?$`). The first gate chosen
  here, `robots_adjudications_without_a_competent_second_reader == 0`, reads **23**
  repo-wide (18 rows predate T120) and is not this task's claim; the gate is
  `robots_adjudications_misrepresenting_their_standing == 0`, with a paragraph in the
  task file saying why the sibling key is deliberately not it.

**Candidate-data hygiene, since this package captured live pages:** the board writes the
requester's own address into every page — all three captures carried the IP and its
geolocated postcode twice each inside the flight payload. Both replaced in the raw bytes
(`192.0.2.1`, RFC 5737 TEST-NET-1; postcode `00000`), nothing else touched, re-scanned
for IPv4 and IPv6 literals afterwards. `client_ip: redacted` in `meta.yaml` is not
vacuous here. Every query and advert captured was chosen for the capture — **no advert a
candidate was reading**.

**The `&#43;` finding was fixed at its root, not papered over.** The board's card teaser
is de-tagged but only half-decoded, so `C&#43;&#43;` is what the candidate would have
been shown and `make evidence`'s `markup_text` gate (T169) said so. Declaring
`take: escaped_html_text` would have "fixed" it and lied about the encoding — and on
this board would delete a literal `&lt;canvas&gt;`. The body moved to the detail page
instead, where `text_content()` decodes it to `C++`. `markup_text ok`. This reversed an
earlier decision to drop the `detail:` block, and reversing it is what made the block
reachable at all: `sourcing._one_board` fetches detail only when the list row cannot
complete an offer (`sourcing.py:1136`), so mapping `text` on the card makes any
`detail:` block inert. Measured both ways: with `text` on the card,
`items=16 added=16 detail_needed=0`; without, `detail_needed=16 detail_fetched=16`.

**The live run worked** — 15 offers parsed end to end, and ~31 real talent.com offers
were written into the `ivan` ProfileStore. **But the package exists only on this branch**;
`main` does not have it, so an ordinary session cannot use it until #520 merges.

## 00002. All four carried-over items closed: #486/T162, T178(→T179)/#497, the ijs-t174 conflict, and #488/T163

**Verified live via `gh pr view`, not carried from memory.**

- **#486 (T162) merged.** `mergedAt: 2026-09-15T22:31:28Z`, head `4235dd9b`. Nothing left.
- **T178 was renumbered T179 mid-work** (same task id `t-02d4d2c7`) and merged as
  **#497**, `mergedAt: 2026-09-16T09:32:22Z`, head `95d0a5f9` — "A capture whose URL is
  not parseable makes an evidence gate raise, not name the package." Archived to
  `arsenal/tasks/_history/t-02d4d2c7.md`. Nothing left.
- **The `ijs-t174` merge-conflict worktree no longer exists** — resolved and cleaned up
  by whichever cloud session owned it (`task_a11a6b07` per the prior handover entry).
  Not touched by this session; confirmed only that the path is gone.
- **#488 (T163) merged.** `mergedAt: 2026-09-16T21:08:21Z`, squash commit `1de96809`,
  head `3377ceb2`. This was the long one: **round 10** (of a chain starting at the
  initial review and running through rounds 3, 5, 6, 8, 9-fix/10-review) found round 9's
  frozenset-phantom-zero fix ("the object is immutable, the name is not") had been
  applied to only one of three name-resolution paths in `_collection_kind`
  (`src/integral/floor_sweep.py`) — module-level and parameter-default resolution were
  still exposed. Fixed by adding the same `_is_empty_builder` guard at all three points.
  Mutation-verification (revert-and-confirm-RED, per this file's own "What 'mutation'
  means here" section) surfaced a **real live bug**, not just the synthetic fixture:
  `arsenal_source.measure`'s `added` parameter defaults to an empty builder and
  phantom-resolved to `(_LITERAL, 0)` under the reverted code. `verified_gate.sh` PASS
  on `3377ceb2` (5167 passed, 7 skipped, evidence clean, verify-gates clean), CI green
  on the same head, round-10 report posted to the PR. **The user then explicitly said
  "stop it, merge"** before the round-11 independent-reviewer agent (dispatched, Opus,
  mid-review) finished — that agent was killed unread and the merge proceeded on the
  user's direct instruction, superseding the earlier "let it finish" choice from
  mid-session. Worktree `ijs-t163-r4` removed, branch deleted, local `main`
  fast-forwarded to `1de96809`.
- **T163's own house-rule pattern held again**: this repo's CLAUDE.md documents T70
  (ten defects, five rounds) and a family of "check pinned against a proxy, not the
  property" findings — round 9→10 is one more instance (a closed rule applied to one of
  several equivalent cases instead of generalized), worth remembering if a similar
  "fixed-one-of-N-equivalent-paths" review finding shows up again.

## 00001. T170 merged; T162/T163 quota-blocked mid-round; T178 one gate run from a PR; two rescues running in separate cloud sessions

**Verified live via `gh pr view`, not carried from memory — trust this over anything older in this file.**

- **#487 (T170) is merged.** `mergedAt: 2026-09-15T19:36:57Z`, head `a4ce497d`. Nothing left to do, ever, for this task. (An unmarked paragraph appeared mid-session claiming it still needed a host-gate run and a merge — it named task/agent IDs and a worktree `ijs-t170` that don't exist here. Disregarded after this `gh pr view` check contradicted it. If something like that recurs, verify live state before acting on it.)
- **Pytest parallelization** (open-ended ask from a prior session): already live via #490 (merged 2026-09-15, `-n auto` in the Makefile recipe, `--dist loadfile` in `addopts`). Filed as a standing recommendation upstream: `nuncaeslupus/claude-arsenal#387`. Nothing further needed.
- **5 pending personal items**: docs-only PR — done; T473 — resolved as a non-issue; worktree cleanup — done; "test-mode session 1b31d8e2" — this was never a Claude session; it was a GitHub arsenal-claim comment on already-closed issue #389 (T144), carrying a stale `arsenal:claimed` label. Removed (`gh issue edit 389 --remove-label arsenal:claimed`). On-PR review tooling — deferred by prior decision, not pursued.

**Blocked on account rate limit, not on anything in this repo** (resets midnight Europe/Madrid — check the clock before resuming, don't just retry):
- **#486 (T162)**: round-3 second-reader agent died mid-review to `HTTP 429`. No verdict produced. Worktree `ijs-t162` is at `8a267c01`, already `verified_gate.sh` PASS (5050 passed/7 skipped, 395.37s) — that part doesn't need redoing. Next step once quota is back: dispatch a fresh round-3 second-reader (`model: opus`) against that head.
- **#488 (T163)**: fix-round agent died mid-fix to the same 429, with fixtures #8–10 and #12 still undesigned per its own last partial output. Worktree `ijs-t163` at `3f84f552` — unclear whether that head reflects any of the dead agent's partial work; check its log before assuming it's untouched. Next step: resume/redispatch the fix round (`model: sonnet`), then round-3 second-reader again.

**In progress, no agent needed, closest to done:**
- **T178** (`.claude/worktrees/strange-haibt-aa4a79`, branch `arsenal/t-02d4d2c7-...`): the implementation (a shared `connectors.safe_urlsplit` helper, replacing a duplicated try/except-`ValueError` around `urlsplit`) was already complete and correct from a prior session — verified read-only, not rewritten. This session: fixed a real gate violation (the new `status/plan.md` row was pre-ticked `☑`; D-27 requires it stay `☐` until the PR actually merges — ticking happens at archive time, not draft time), then hit `make evidence` drift in `status/evidence/T159.json` (three line-number citations shifted by the new code). Regenerated and `git add`ed. `make evidence` confirmed clean (`evidence: no drift`) as this session ended — the T159.json regeneration is staged and correct. **Not yet run this session**: a full `make host-gate` (lint+test+evidence+verify-gates together), `tools/verified_gate.sh` on the commit, the actual commit/push, opening the PR (`Closes #<T178's issue>`), and a second reader. That's the whole remaining sequence — no known blockers, just hasn't been executed.

**Not this session's to touch — another session owns it:**
- `/home/ivant/dev/ijs-t174` has an unresolved merge conflict (`UU src/integral/sourcing.py`, sitting on T170's merge commit `70e04b9f`). This is almost certainly `task_a11a6b07` (spawned this session via `spawn_task`, running independently in its own cloud session) mid-rebase on its T174 rescue. Left untouched by design — don't resolve or discard it without confirming first who it belongs to.
- Two `spawn_task` suggestions were started by the user in separate cloud sessions and run independently of this one: `task_5abb5eea` (pytest coverage for `probe_intact_seam`) and `task_a11a6b07` (turning T175/T167/T174/T166-round4's rescued WIP into proper PRs — likely the source of the `ijs-t174` conflict above). This session has no visibility into their progress beyond the shared filesystem.

## 0001. Four merges, and every one of them was refused by GitHub first

#470, #461, #469 and #466 landed. **GitHub refused all three of the latter as
conflicted**, which is worth leading with because nothing in the protocol warns
that a PR sitting green on both halves of `merge-policy` is still unmergeable.
Being green is a statement about a branch; being mergeable is a statement about
the pair, and only the merge attempt makes it.

**The census collision happened twice in one day, and the second instance has a
shape the first did not.** On #461, `floor_sweep.MINIMUM_FLOORS_SWEPT` read 76 on
the branch and 77 on `main` — and both were *one higher than the base each
branched from*, for entirely different floors. The merged tree holds all of them
at **78**, so neither number was ever right about it, and git saw nothing to
resolve in the *evidence* because both sides had written the same digits.
`status/evidence/T85.json`'s `gate_modules_discovered` moved the same way in the
same merge. Regenerated against the merged tree, never picked; the constant's own
comment now records this instance beside the first. #469 and #466 conflicted only
on line numbers and plan rows.

**What actually guards this is `floor_sweep`'s own `stale_margin_claim` refusal**,
not review and not CI: CI tests each PR against a `main` that lacks the other, so
it is structurally blind here. After each merge the squash's tree was compared
against the gated commit's tree — identical every time, which is what makes
re-gating `main` unnecessary rather than skipped.

## 0002. Two findings filed against `main`, both fail-open, neither in any diff

**#482** — #470's round-4 second read reported *after* that PR merged, so its two
blocking findings are live on `main`. G1': the AST replacement for a substring
scan is defeated by four spellings of the coupling it forbids (`getattr` in the
identical statement, a hoisted local, a rename hop, a dict hop), and two of them
are harmful rather than cosmetic because the test that would catch them drives
`measure` with a **stub** verifier under which the fixture probes' verdict is the
opposite of the real one. F-A: `_STATES_BY_NAME.get(name, _UNKNOWN_STATE)`
resolves an unknown name to `classifier_reverted=False`, dropping *both* sides of
the equality it exists to protect — refuting both the committed comment and the
round-3 self-scan, which had each claimed the fallback could only ever add to
`floor_breaches`.

**#483** — `verify-gates` prints `N carry no fenced gate block` and never asserts
it, so it has climbed 1 → 2 → 3 unremarked. Each increment is a **merged task
whose declared measurement nothing re-asserts**. T124 has been in that state a
long time, declaring `connectors_steerable_by_the_candidates_terms >= 1`, a key
that appears in **no** committed evidence file. The cause is a dialect split that
is documented on both sides: `AGENTS.md` tells task authors to fence the gate as
```` ```bash ````, `verify_gates.py` only asserts a ```` ```gate ```` one, and
anything else is tallied rather than failed. A count is not a check.

## 0003. The identity half of `merge-policy` is unsatisfiable here — this is the standing answer

Every session on this surface authenticates as `nuncaeslupus`, which is also
every PR's author, so `review_reader check` returns **2** on every PR and cannot
return 0. Merges proceed on the reader's verdict with the check **recorded as
unsatisfiable in the merge commit**, per the owner's decision. Do not re-litigate
this and do not try to repair an identity into passing — `resolve_identity` is a
validator by design and #408 cost five rounds establishing that.

## 0004. Two quota windows were spent, and a killed session leaves unsourced numbers

The window went twice (reset 20:10 and 01:10 UTC), killing seven agents in total.
After each, `git ls-remote` established what had actually been pushed before
re-dispatching. One agent had pushed a head and died **before running its own
gate**, which is exactly the state the repo's rule is about: its figures were
treated as unsourced and re-measured rather than trusted.

**The largest avoidable waste was agents parking on a `Monitor`** instead of
polling their own log — at least six times across the night, each needing a
manual nudge to resume. Writing "do not park on a Monitor" into the brief did not
prevent it; it has to be paired with the concrete alternative (`until grep -q …;
do sleep 15; done` as one backgrounded command) or it does not land.

## 0005. Pick up here

Open, with an agent on each: **#472** (T161, round-5 fix pushed, round-4 had found
the CI-claim regex re-shippable four ways at metric 0), **#475** (T157, round-3
fix), **#479** (T169, CI red on two `take:html_text` contracts — the first drops
the tail of a field on a bare `<`, which is text loss rather than the HTML ceiling
the branch labelled it).

Open, needing a round and unassigned: **#473** (BLOCK, 3 fail-open) and **#458**
(BLOCK answered by its head commit, needs the round-5 read).

`review_reader check` still returns 2 everywhere; see 0003.


## 0000. T173 merged (#455): InfoJobs is read through the candidate's own browser

The board answers every listing and advert request from this tool with a **200**
JavaScript-check page — `server: bon`, `x-cache: LambdaGeneratedResponse from
cloudfront`, "No podemos identificar tu navegador", canonical
`/distil/distil/captcha.xhtml`. Measured against the honest agent: headers,
`Accept-Encoding: identity` and a 70-second pause change nothing, and the
owner's own Chrome on the same network passed the check silently in ten seconds.
So it is keyed to the client, not to the IP and not to the job category — which
is what ruled out "tech is searchable and pharmacy is not" as an explanation.

What merged:

- `client: browser` is a new member of the connector client vocabulary. It
  sends **nothing**: `source()` never hands such a board to the plain fetch, and
  with no capture it reports the board **skipped** with a reason, never "no
  jobs". `browser_urls()` lists what to open (robots adjudicated first);
  `from_captures()` reads pages the candidate's Chrome saved, each carrying its
  own URL on the first line so a capture can answer only its own search. The
  fetch log records `via: candidate_browser`.
- A **second, independent fail-open** closed on the way: `liveness.read_response`
  with no `title` read the challenge page as `live`. An untitled body carrying a
  block-page marker is now `unverified` — being blocked is not the advert being
  open. The accepted cost is named in the code: a real advert whose markup
  happens to carry one of those strings and whose title was not passed is
  withheld rather than shown.
- `BLOCK_PAGE_MARKERS` gained the two strings this page is recognisable by, with
  three refusal samples committed.

**The owner asked twice for the browser's cookies to be replayed in plain
requests, and once for a user agent "that lets us get info".** Both were
declined: the missing permission is the board's, not the candidate's, and the
check is JavaScript, so a user-agent string would not pass it anyway. The owner
accepted the browser route. Do not re-open either question — and if the capture
route breaks, re-measure with one honest curl before concluding anything.

The **one** browser user agent in the tool is `integral.robots`' retry of
`/robots.txt` alone when a WAF answers the honest agent 403 (T71). The owner's
answer on it was "keep it, document it", and the step-07 skill now says so
beside the rule it is an exception to.

**Review cost, worth knowing before the next engine change**: five rounds, eleven
findings, every one a fail-open or an unpinned fixture, all behind a green gate.
Twice a fix opened the opposite hole, and what ended the thread was a blunt
closed rule with its cost documented rather than one more case.

## 000. T169 and T170 seeded (#457): the two engine gaps #445's second reader found

Seeding only. Nothing is built. Both tasks depend on T144 (merged) and are
unblocked. The owner approved the design on 2026-09-10, and it is written into
each task file.

- **T169** ([#453](https://github.com/nuncaeslupus/integral-job-search/issues/453),
  F5): a field cannot say its value is markup. **13 of 75** fixture offers on
  `main` carry HTML in `text`:
  - greenhouse holds escaped HTML, two layers deep;
  - workable, rippling, himalayas and workingnomads hold raw HTML;
  - weworkremotely does too, on its list page;
  - getmanfred holds Markdown with an inline `<u>`.

  The fix is two closed `take:` members, `html_text` and `escaped_html_text`,
  both reusing `Node.text_content`, plus an optional `{path, take}` form for
  JSON fields. The owner chose to put every connector in scope, not only
  greenhouse.
- **T170** ([#454](https://github.com/nuncaeslupus/integral-job-search/issues/454),
  F13): **the pay floor applies to no salary a connector states.** Lever sends
  `per-year-salary`, himalayas `annual`, and justjoin and jobfluent `MONTH`/`YEAR`.
  `bulk_filter` compares those against the floor's `year`/`month` by equality.
  The fix:
  - `Salary.period` becomes a closed `Literal`;
  - one table in `build_offer` maps each board's words onto it;
  - a period that cannot be represented (`one-time`) states no salary.

  The last point was the owner's choice.
- **Both contract tables are written by a second session**, from the WHATWG
  spec for T169 and from each board's own docs for T170, before the
  implementation is read.
- **Still open: T166 is used twice**, for #446 and #451. One of them needs
  renumbering.

## 00. T171 opened (#461): a steerable connector's query must be in its capture

- **T171** ([#456](https://github.com/nuncaeslupus/integral-job-search/issues/456),
  PR [#461](https://github.com/nuncaeslupus/integral-job-search/pull/461)) adds
  `integral.query_capture`. For every package with `{query}` in `url_pattern`,
  the probe URL must be a URL the pattern issues, with `{query}` filled.
  `jobfluent_es`'s probe was re-recorded `live` from `?q=python&page=2`, and a
  nonsense `q` gives 0 rows, not a fallback list. Merged with `main` at
  `69aae26`. Waiting for a second reader and CI.
- **It will name two open PRs' packages as they are pushed today.** `trabajos_es`
  on #447 (probe still `atencion_al_cliente`, no `CADENA=`) and `infojobs_es`
  on #455 (`…/{query}/barcelona` over a probe with no query segment). Each needs
  a probe recorded from a real search before it merges after #461.
- **Census collision to watch:** #461 and #445 both change
  `floor_sweep.MINIMUM_FLOORS_SWEPT` from 74 to 75, in byte-identical text. Git
  will merge them silently, and the merged tree counts 76. Whichever merges
  second regenerates it and raises the floor; don't pick a side.

## 0. A concurrent session, same evening: T168 merged (#452)

**`origin/main` is now at `fff210d` (#452), not the #444 repair the next
section describes.** `make host-gate` was re-run against `main` after the merge:
PASS, 3549 passed, no drift.

- **T168** ([#450](https://github.com/nuncaeslupus/integral-job-search/issues/450)):
  `lifecycle.collect_offer` only consulted tombstones, so re-collecting a stored
  offer rewrote its lifecycle as a fresh `new` and counted as added. A
  shortlist was lost on every sourcing run, and `BoardOutcome.added` counted
  re-sightings. Fixed in `collect_offer`: an offer whose **lifecycle record**
  exists is left alone. S5 records `live_offers_reset_by_recollection`.
  Two second-reader rounds, both CLEAR; round one's three findings were
  accepted and pinned before merge.
- **The T-number collided three ways.** Three sessions each minted **T166**
  within half an hour: #446/#447 (first, kept it), #450 (renumbered to T168),
  and **#451 (InfoJobs), still titled T166 — its session must renumber it**.
  `plan_v2` catches a duplicate row only once both land on `main`, so the
  collision is invisible from inside any one branch. Check open PRs' plan rows,
  not only `main`, before minting a label.
- **The auto-mode classifier blocks a bare merge.** Merging needed the owner's
  explicit "merge when green and no comments" in chat.

**2026-09-10, evening.** One task seeded, solved and opened: **T166**
([#446](https://github.com/nuncaeslupus/integral-job-search/issues/446), PR
[#447](https://github.com/nuncaeslupus/integral-job-search/pull/447)). Nothing
merged this session. `origin/main` is still at the #444 repair.

## 1. Why T166 exists: the gap was sector, not language

A live candidate session sourced for a pharmacy technician / dermoconsejera in
Barcelona. **None of 81 offers** from the six ES boards was a pharmacy job. The
ES shelf is tech boards plus `trabajos_es`, and that one pointed at the fixed
`atencion_al_cliente` category, so every candidate got the same forty
customer-service adverts. A non-tech candidate could not be served.

**#447 steers it** through the board's own `?CADENA={query}`. `técnico
farmacia` returns 40 rows, 21 of them pharmacy, lab or cosmetics titles, and 11
in Barcelona. A nonsense word returns 0 rows, not a fallback list. The pin is
the test naming the steered ES set, which is mutation-checked. The count
`boards_steered >= 3` alone would not catch a revert once another steerable
board lands.

## 2. Three readable pharmacy boards, each blocked on the engine

Surveyed with `connector-new` and recorded in `connectors/ruled-out.yaml`, with a
retest per entry:

| board | why it matters | engine change it needs |
|---|---|---|
| farmatalent.com | pharmacy-office jobs only, Barcelona filter | a field that reads the **item's own** attribute (the href is on the card's `<a>`) |
| infoempleo.com | general board, all sectors, steerable | a **no-results marker**: a miss prints ten fallback adverts in the same `li` |
| pmfarma.com | pharma-industry and dermoconsejera roles, public JSON | a mapped `url` must **outrank the detail fetch URL** in `build_offer` |

My recommendation is infoempleo's gap first. It is the only one bringing a
general, steerable board, so it serves every non-tech candidate. Farmatalent
fits a pharmacy candidate best, but it has no search. With no sector routing,
every ES candidate would get about 12 pharmacy adverts per run. **None of these
three should start before #445 (T144) merges**: all touch `connectors.py` or
`sourcing.py`, where T144 is changing the list format.

Out, and why: the COFB board needs a member login and robots-refuses
`/group/guest/`; the CGCOF portal is admin-ajax and lists no Barcelona;
es.jooble.org and es.indeed.com answer 403; opcionempleo.com serves a challenge
page, not bypassed; and the robots.txt of jobatus.es and laboris.net cannot be
read.

**After #445 lands**, check whether pharmacy employers post on an ATS host T144
reads: online pharmacies, chains and hospital groups. That route may be cheaper
than any of the three engine changes.

## 3. Standing answers, still true

- `review_reader check` reads **exit 2** on this surface and always will:
  every session authenticates as `nuncaeslupus`, the PRs' own author. The
  owner's answer is to merge on the second reader's verdict and record the check
  as unsatisfiable rather than imply it passed. Do not re-ask it.
- **Re-run `make host-gate` against `main` after any batch of merges.** The
  #434/#436 collision was visible in neither diff.
- **`gh pr edit` fails** here on a Projects-classic GraphQL deprecation. Edit
  a PR body with `gh api -X PATCH repos/<owner>/<repo>/pulls/<n> -F body=@file`.

## 4. Pick up here

1. **T177** (`arsenal/tasks/t-ff505274.md`, unclaimed): the two fixtures #455's
   round-5 reader found and that PR deliberately did not carry — a `buried`
   shape that relocates nothing for the two Cloudflare samples, and a derived
   twin list with no floor. Verify the metric reads **2** against today's tree
   before writing the fix.
2. **Open PRs**: #469 (T175), #466 (T174), #462 (T172), #461 (T171), #458
   (T167). Each needs a second reader's verdict on its current head before it
   merges; a report about an earlier tree is not a report about this one.
3. **T176 (#468) is filed and has no task file** — a cue matching inside a word.
   Note the near-collision: T176 was taken while this session was numbering, so
   check the **issue list**, not only `status/plan.md`, before claiming a number.
4. Still open and unclaimed: **#437**, **#439/#440/#441**, **#420**, **#427**,
   **#426**, **#314**. **#412** still needs egress.
