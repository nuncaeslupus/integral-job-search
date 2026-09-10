"""T159 — a floor whose distance from its population is not deliberate.

A floor exists so that a clean zero over an empty or shrunken scan cannot pass as a
measurement (`naming.MINIMUM_SCANNED`'s job, repeated a dozen times across this
repository). Three shipped floors did not do that, found by hand during T122's fourth
review round rather than by anything that runs:

| module | floor | population | effect |
|---|---|---|---|
| `profile.MINIMUM_FIELDS_CHECKED` | `len(_D6_FIXTURE)` | same | `len(X)<len(X)`: never fires |
| `bodyless_post.MINIMUM_PROBES` | `8` | `len(PROBES) == 9` | first deletion breaches nothing |
| `page_placeholder.MINIMUM_PROBES` | `21` | `len(PROBES) == 25` | four deletions breach nothing |

**The rule this module enforces:** every committed floor either sits where the first
deletion breaches it, or states the margin it keeps and why. Nothing else. A floor
whose distance from its population is an accident is a floor that reports a
measurement it did not make.

## Sweeping is the hard half

Three blind spots were already found and named before this module was written, each
independently capable of re-opening the class this module exists to close:

1. **The name filter.** `MINIMUM_`/`MIN_` alone misses this repository's other two
   spellings — `*_AT_LEAST` and `*_MINIMUM` — which between them name real floors
   (`audit_followup.CASES_AT_LEAST`, `robots.FIXTURES_AT_LEAST`, `second_reader`'s
   four, `connector_policy`'s two, `connector_exchange.LEAK_NEEDLE_MINIMUM`,
   `salary_recovery.HOUSE_ESTIMATE_MINIMUM`). Round 1's `_FLOOR_NAME_RE` matched
   all four spellings; round 2 replaced it with `_CONSTANT_NAME_RE` below, which
   does not enumerate spellings at all (see "Round 2" further down).
2. **An equality fingerprint.** A candidate set built by checking whether the floor
   equals its population *by construction* cannot find a floor that is *below* its
   population with no argument for the gap — the entire class in question, and the
   shape of two of the three violations in the table above. This module instead
   computes the actual margin where the population is a fixed, in-repo collection,
   and requires a written argument only where a real gap exists (`_MARGIN_ARGUED_RE`).
3. **A comparison delegated to a helper.** `review_reader._floor(observed, minimum)`
   takes the floor as an argument and does the comparison inside its own body, so a
   sweep that looks only at `Compare` nodes mentioning the floor's name directly never
   finds the four floors that go through it. `_delegated_other_operand` below follows
   exactly one call of indirection: it finds the call site, maps the floor's argument
   position to the callee's parameter name, finds a `Compare` inside the callee body
   between that parameter and another one, and maps the *other* parameter back to
   whatever expression the caller actually passed for it.

## What "in scope" means, and what is deliberately left out

Not every `MINIMUM_`/`MIN_`/`*_AT_LEAST`/`*_MINIMUM`-named constant in this repository
guards a population in the sense this module is about. `elicit_extract.MIN_ANSWER_CHARS`,
`process_spec.MIN_ITEM_WORDS`, `step_specs.MIN_FIELD_WORDS`, `skill_budget.MIN_HEADROOM_CHARS`
and `annotation.MIN_IDENTIFYING_LENGTH` are validity thresholds on **one piece of
content** — how long a single answer or field is — not floors on how much a scan
examined. `corpus.MIN_ADS_PER_FAMILY` and `salary_recovery.HOUSE_ESTIMATE_MINIMUM` are
business-rule thresholds compared against a per-group count that is never itself the
length of a collection. None of these is compared, even through one hop of tracing, to
a `len(...)` of anything — which is the one structural fact this module uses to decide
whether a name is a *population* floor at all: **a floor joins this sweep only if the
side of its comparison it bounds can be traced, through at most a local reassignment or
one delegated call, back to a `len(...)` call.** A comparison against a bare scalar
(`words < MIN_FIELD_WORDS`, `count >= HOUSE_ESTIMATE_MINIMUM`) never reaches one, so
those names are read and set aside, not silently counted as compliant.

Within that in-scope set, two different questions are being asked, because they have
different honest answers:

- **A floor over a fixed, code-owned collection** — a tuple of probes, arrangements,
  wording cases, or a fixture this module itself lists — has a population someone
  really could shrink by one edit. For these, "sits where the first deletion breaches
  it" is checked *arithmetically*: the population is counted from the collection
  literal (directly, or through a default parameter, or through the delegated-call
  mapping), and the margin is `population - floor`. Zero or negative margin passes
  outright (a breach already fires, or fires on the very next deletion). A positive
  margin passes only if the declaration's own preceding comment argues it in writing
  (`_MARGIN_ARGUED_RE`) — matching what `salary_recovery.MINIMUM_WORDING_CASES` and
  `second_reader.STDLIB_DISAGREEMENTS_AT_LEAST` already do in prose. A floor that is
  not even a literal — `profile.MINIMUM_FIELDS_CHECKED = len(_D6_FIXTURE)` — fails this
  before arithmetic is even possible: a bound derived from the population it bounds
  moves with it and can never fire, the exact shape T122 fixed on
  `gate_reader_agreement.MINIMUM_ARRANGEMENTS_PROBED` by keeping the replacement a
  hand-written literal.
- **A floor over a population this repository does not itself enumerate** — a corpus
  scan, a labelled-evaluation split, PRs read from GitHub, a third party's own
  behaviour (`second_reader.STDLIB_DISAGREEMENTS_AT_LEAST` is pinned to
  `urllib.robotparser`, not to this repository's own table), or a scripted probe's own
  running `checks`/`asks`/`turns` tally built by `+= 1` in a loop rather than a
  collection this module can count — has no single "the first deletion" a diff in this
  repository could make in the same mechanical sense a tuple literal does. Counting
  exact margin against it structurally would be measuring the wrong thing, and T115
  (`floors_that_do_not_fail_the_gate`, #309) already owns the adjacent question of what
  happens when such a floor *is* breached. This module asks only that the declaration
  carry some explanation at all, and reports these separately
  (`dynamic_population_floors`) rather than folding them into the arithmetic count.
  That does not excuse an actual gap, though: eleven of these — every scripted-probe
  tally this sweep could trace through a cross-function return — turned out to be
  silently under their probe's real count with no explanation at all
  (`candidate.MINIMUM_CASES`, `constraints_step.MINIMUM_CHECKS`, `decline.MINIMUM_ASKS`,
  `freshness.MINIMUM_OFFERS`, `offers.MINIMUM_CHECKS`, `question_bank.MINIMUM_PROBES`,
  `retraction.MINIMUM_SCANNED`, `revision.MINIMUM_AGED`, `scoring.MINIMUM_TURNS`, and
  the two named beside `profile`/`bodyless_post`/`page_placeholder` above,
  `elicit_extract.MINIMUM_CHECKS` and `trait_sufficiency.MINIMUM_CHECKS`) — each raised
  by hand to what its own probe measures today, verified by running it rather than
  guessed, the same discipline the fixed-collection fixes above use.

## Round 2 — the classification was the defect

A second reader BLOCKED round 1 on PR #436 with one diagnosis: **only 11 of 46 swept
floors were ever checked arithmetically; everything else was classified away into a
branch where nothing could fail.** Six findings, all fail-open, all behind a green
gate. Answering them one at a time was explicitly the wrong move — enumeration has no
last element — so this round changes the *shape* of the classification instead:

1. **All fourteen floors round 1 fixed could be dropped to `1` with the metric still
   reading `0`.** The three arithmetic ones were excused by `_MARGIN_ARGUED_RE`
   matching the words `raised`/`slack` regardless of whether the number beside them was
   still true; the other eleven, classified `dynamic`, needed only *a* comment, not a
   *true* one. Fixed by `_zero_slack_claim_contradicts`: every one of the fourteen
   comments states a specific number ("Raised to what the probe carries — N, zero
   slack"), and that number is now re-extracted and compared against the floor's
   *current* value on every sweep — a keyword match cannot tell a claim that used to be
   true from one that still is, but a re-extracted number can.
2. **The name filter was still a filter.** However many spellings `_FLOOR_NAME_RE` grew,
   a name outside all of them (`bulk_filter.MUST_KEEP_ROWS`) stayed invisible.
   `_CONSTANT_NAME_RE` now accepts this repository's whole module-constant convention
   (a name starting with a letter, all caps), and what actually decides scope is
   `_is_len_derived` on the *value* — never the spelling.
   `bulk_filter.MUST_KEEP_ROWS` never appears as a direct `Compare` operand either (it
   is boxed into a dict three lines below and read back out); `_resolves_to_name` finds
   it through the same Subscript/dict-literal hops `_collection_kind` already followed
   for a population, applied to the floor's own side of the comparison.
3. **`floors_swept_at_least = 30` against 46 tolerated hiding all fourteen.** Round 2's
   broadened discovery raises the true count on its own (see below); the committed floor
   is raised to sit within a few points of it, not sixteen.
4. **The gate exempted itself.** `floor_sweep.py` was skipped by module identity, so
   `MINIMUM_FLOORS_SWEPT` was the one committed floor this rule structurally could not
   classify. Round 2 does not special-case it: `_module_constant_candidates`'s
   value-shape filter already keeps every other diagnostics constant in this module off
   the candidate list without a name-based allowlist, so nothing but the real floor is
   left to sweep.
5. **The "never wrongly clears" claim was false**, the same shape as `resolve_identity`'s
   "only ever merges" — measurably false there too. `_MARGIN_ARGUED_RE`'s own comment
   now says so plainly instead of repeating the disproved claim.
6. **The roll-call inside `MINIMUM_FLOORS_SWEPT`'s own comment named modules as
   "already compliant" that the sweep could not see at all** — `gate_reader_agreement`
   is the exemplar the task file itself cites, and it was genuinely out of scope: its
   only comparison site reads a `dict` passed to `floor_breaches` as a *parameter*, and
   round 1's tracing never followed a value across a call boundary to find out what a
   parameter actually held. Round 2 adds exactly that (`_resolve_parameter_via_callers`,
   `_resolve_subscript_param_via_callers`) — one hop, and only when every call site in the
   module binds the parameter the same way — which is what pulled
   `gate_reader_agreement.MINIMUM_ARRANGEMENTS_PROBED` in from `bounds_read_and_out_of_scope`
   for the first time, along with `MUST_KEEP_ROWS` and every other module whose own gate
   separates "build the measurement" from "check the floor" this same way (`interview`,
   `pay`, `profile_capture` among them — three more undocumented, silently-under floors
   this broadened tracing found and this task also raised, the same discipline as the
   original eleven). What it did *not* pull in —
   `gate_reader_agreement.MINIMUM_GATES_COMPARED` — combines a genuinely external count
   (`int(board["compared"])`, read from outside this repository) with `len(probes)`; no
   arithmetic shape this module supports may combine two dynamic quantities, so this one
   stays honestly out of scope. The roll-call itself is gone from this comment for the
   reason the finding names: a hand-maintained list of "compliant" module names is prose
   nothing tests, and it drifts. `status/evidence/T159.json`'s own
   `dynamic_population_floors` and `bounds_read_and_out_of_scope` are regenerated on
   every run and cannot say something the sweep does not currently believe.

`_population_for` also grew one more traced shape while this round was open:
`len(X) + N` / `len(X) - N` (`gate_reader_agreement.MINIMUM_ARRANGEMENTS_PROBED`'s own
reasoning — "the list this is read against is `len(ARRANGEMENTS) + 1`") is now counted
arithmetically rather than falling out of scope the moment a `BinOp` sits where a bare
`len(...)` used to.

## Round 3 — dynamic was an exemption, not a classification

A second reader BLOCKED round 2 with nine findings, eight fail-open, all behind a
green gate — and one root cause: round 2 broadened the sweep from 46 floors to 57,
and every one of the eleven newly-swept floors landed in `dynamic`, where no margin
was ever computed. Round 1's diagnosis — most of the sweep sits in a branch that
cannot fail — was round 2's own result too, just with a bigger denominator.

1. **The headline finding, reproduced by a second method before it was believed:**
   `_zero_slack_claim_contradicts` scanned a window that *included* the matched
   phrase, and `"zero slack"` contains the word "zero" — so `literal_value == 0`
   could never contradict the claim, for every floor this check could ever fire
   on. The accept-set was seeded by the checker's own trigger word. Fixed by
   scanning only the text *before* the phrase (never the phrase itself, never
   anything after it — closing a second misread, a trailing issue reference
   inside the old look-ahead), and stripping backtick-quoted code first (closing
   a third — a digit inside an identifier like `` `_D6_FIXTURE` ``).
2. **The closed form, not another patch to the parser.** A "dynamic" population
   was never actually uncountable for most of these floors — it was a scripted
   probe's own running tally, and this repository's own `make evidence` already
   writes that exact number to `status/evidence/*.json` a few lines from where
   the floor is read. `_committed_evidence_population` reads it — following this
   repository's own `write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH)`
   idiom structurally, including through a dispatcher function's own parameter
   when it has exactly one caller (`lifecycle.MINIMUM_SCENARIOS`'s real shape) —
   and once resolved, the floor is checked by the *identical* `_margin_finding`
   arithmetic a literal population already gets. No comment, "zero slack" or
   otherwise, can clear a real margin any longer. Refuses rather than guesses
   when an evidence path is chosen by a condition this sweep cannot evaluate
   (`profile_capture`'s own D-8-vs-T28 CLI switch resolves two *different* real
   files from the two branches of one `IfExp`) or when a parameter has more than
   one call site — both fall back to the older, weaker, but now-correct
   comment-only check rather than silently reading the wrong probe's number.
3. **The sweep's own denominator, matched by identity, checked by arithmetic.**
   Round 2 removed the module-identity exemption but still classified
   `MINIMUM_FLOORS_SWEPT` `dynamic` — no committed evidence file could ever back
   it (T100 deliberately keeps this exact census uncommitted), so it sat in the
   one branch that cannot fail. Self-exemption had moved from identity to
   classification. `measure()` no longer classifies it at all: matched against
   `_THIS_FILE` (this exact file, never a module merely *named* `floor_sweep.py`
   — this module's own test suite writes one, to prove the fix holds regardless
   of filename), deferred until this run's own `swept` is known, then checked by
   the same `_margin_finding` arithmetic as everything else.
4. **The remaining blind spots, closed as rules rather than as counts.** A
   leading underscore is now admitted into `_CONSTANT_NAME_RE`
   (`plan_v2._MIN_TASK_CELLS`, `approval._SHINGLE`,
   `extraction._CONFIRMING_MATCHES_FOR_BIPOLAR` were real, invisible floors for
   no reason but the character). `.split()`/`.splitlines()` are recognised as
   producing a real (if uncountable) population, not `unknown`. `AnnAssign`
   targets (`stdlib_disagreements: list[...] = []`) are read everywhere
   `_assignments_to_name` already read plain `Assign`. A floor's own *value* is
   resolved through a `BinOp` of two literals (`1 + 0`) or an alias to a sibling
   constant (`_FLOOR = 1` then `MINIMUM_PROBES = _FLOOR`), never only a bare
   `Constant`. And `_delegated_other_operand` is now genuinely recursive
   (`_trace_delegation`, bounded by `_MAX_DELEGATION_DEPTH`) rather than two
   hand-written hops — round 2 answered a two-hop finding with exactly two
   hops, which a three-hop chain still defeated; a fourth remedy naming a fourth
   hop would only have invited a fifth.

What this did *not* attempt: a handful of floors compared through a `len(...)`
whose own argument this sweep still cannot classify (`strings.MINIMUM_STRINGS`
against `len(keys(catalogue))`, `salary_recovery.MINIMUM_CORPUS_ADS` against
`len(load_ads())`) stay `bounds_read_and_out_of_scope` rather than being forced
into `dynamic` by relaxing what counts as a traced population — that relaxation
was tried and reverted (see PR #436's round-3 self-scan): it could not be
distinguished from a per-item scalar check (`len(value)` inside a generic
recursive walker) without risking exactly the kind of misclassification this
task exists to prevent. Named here so the next reader does not have to
re-discover it as a finding.

## Round 4 — the arithmetic branch had no floor of its own

A second reader BLOCKED round 3 with seven findings, six fail-open: **30 of the
67 swept floors reached an arithmetic check; 33 could be dropped to `0` with the
metric still `0`.** Five separate root causes, not one:

1. **The arithmetic branch itself was unfloored (F1).** Deleting every
   committed `status/evidence/*.json` file dropped 18 of 19 evidence-pinned
   floors back to `dynamic` — `floors_swept` unchanged, no breach, exit 0 —
   because nothing asserted the evidence files this module's own closed form
   depends on were there, or right, at all. Fixed the way `MINIMUM_FLOORS_SWEPT`
   already was: a second, identically-deferred self-floor,
   `MINIMUM_FLOORS_ARITHMETICALLY_CHECKED`, checked against a new
   `arithmetically_checked` count once `measure()`'s own loop has finished.
   Deleting the evidence files now visibly breaches this floor. **"Or shipping
   a wrong one" was false, corrected in round 5 (R4-1) rather than repeated
   here** — see `MINIMUM_FLOORS_ARITHMETICALLY_CHECKED`'s own comment.
2. **The one floor this task owns could not fail (F2/F3), twice over.** The
   self-floor's own comment ("Committed at 64, three points of slack") and
   `robots.FIXTURES_AT_LEAST`/`salary_recovery.MINIMUM_WORDING_CASES`'s
   raise-histories all cleared unchanged at floor `1`, because
   `_MARGIN_ARGUED_RE`'s keyword match never re-checks the *number* beside the
   word it fired on — round 1 exempted the floor by identity, round 2 by
   classification, round 3 by escape hatch. Fixed by generalising
   `_zero_slack_claim_contradicts`'s idea (re-extract the number a comment
   actually claims, compare it against what the code currently declares) to
   the two other idioms this repository uses to argue a positive margin in
   writing: `_claimed_current_value` ("Committed at N") and
   `_claimed_margin_size` ("N points of slack/margin"), both checked inside
   `_margin_finding` itself so every arithmetic floor gets the same protection
   regardless of which branch found its population. Separately, the one test
   exercising this on the live tree asserted `pinned["population"] ==
   measured["floors_swept"]` — `population` **is** `swept`, assigned three
   lines earlier, so this was `swept == swept`: the task's own headline defect,
   reproduced in the task's own suite. Replaced with an independent
   recomputation (`_margin_finding` called a second way, against the real
   comment read fresh from source).
3. **`_classify_floor` asked "can I count this?" before asking "is it already
   answered?" (F4).** Ten real floors compare a value read out of this
   repository's own `measured["key"]` evidence idiom, and `_committed_evidence_
   population` already knows how to resolve that idiom — but it was only ever
   tried once `_population_for` had already classified the comparison `dynamic`,
   and `_population_for`/`_collection_kind` has no branch for `ast.Attribute` at
   all, so `len(report.packages)` (`connector_contract.MINIMUM_PACKAGES`'s real
   shape) was ruled `out_of_scope` before evidence-pinning ever got a turn. Fixed
   by trying the evidence route whenever `_population_for` did not already
   resolve a literal count — never instead of it, so a floor this sweep can
   already count exactly from source is still checked against that fresh count,
   not a possibly-stale file. Seven of the ten are now genuinely evidence-pinned
   (`connectors`, `dedup`, `identity`, `session`, `sourcing_scope_review`,
   `sourcing_strategy`, `step_runtime`); three stay out of the sweep's reach for
   reasons independent of this fix and are raised by hand instead —
   `connector_contract.MINIMUM_PACKAGES`'s evidence path is chosen by a whole
   helper function gated on a CLI flag and turned out, once raised, to be the
   wrong fix entirely (below); `cv_store.MINIMUM_FIELDS_MEASURED`'s by
   `argparse`; `salary_recovery.MINIMUM_CORPUS_ADS`'s population is built by a
   cross-module call (`corpus.load_ads`), which this sweep's single-hop,
   same-module-only resolution correctly declines to guess at.
4. **`connector_contract.MINIMUM_PACKAGES` looked like the strongest instance in
   the repository and was not one.** Raised to 21 (this repository's own
   `connectors/` package count), it broke three tests that run the identical
   command over a smaller, *conforming* third-party directory
   (`docs/distribution.md` §5's own contributor use case). This floor's true
   population is "whatever directory this invocation was given," which varies
   by caller the same way `corpus.MIN_ADS_PER_FAMILY` does — never the length of
   one fixed, this-repository-owned collection — so it is left at `1`,
   deliberately, and documented as out of this task's scope for that reason
   rather than "fixed" into a regression. Caught by the test suite, not by
   inspection; see the self-scan on the pull request for what that means for
   the other nine.
5. **Five more constructed shapes still evade the sweep (F6)**: a tally
   returned by a helper and tuple-unpacked, a dataclass attribute, a
   walrus-bound population, a chained comparison, `len(TABLE.keys())`. Per
   CLAUDE.md ("what does not work is enumeration"), none of these gets a sixth
   traced shape — they are committed as fixtures that pin today's honest
   limit (each `bounds_read_and_out_of_scope`, counted, never silently
   miscounted as compliant), so a regression that starts treating one as
   compliant is caught, and a future fix that closes one has a red test
   telling it so.

Also closed, in `_zero_slack_claim_contradicts` itself (F7): the phrase set was
a literal alternation of three exact strings, and four more real-sounding
spellings ("no margin at all", "zero headroom", "nothing spare", the hyphenated
"zero-slack") slid past it — widened to a composition (`zero`/`nothing` + a
noun) rather than a fourth-through-seventh phrase, deliberately *not* joining
`no` to the whole noun set after that broadening collided with this
repository's own unrelated "with no margin argued for the gap" idiom in
fourteen real comments (caught by the live-tree test before push, not by
review). And the look-behind window accepted *any* number within 80
characters, so a decoy (a year, a round number) earlier in the same comment
could sit beside the real claim and clear it — narrowed to the number nearest
the phrase, which is where every genuine instance of this idiom in this
repository actually states it.

`MINIMUM_FLOORS_SWEPT: 64 -> 73` against a measured 76 (three points of slack,
the same margin every round has used for the same reason) — the increase is
F4's reclassification of seven already-in-scope-adjacent floors plus the two
new self-floors, not new discovery. `MINIMUM_FLOORS_ARITHMETICALLY_CHECKED: 36`
against a measured 39, new this round.

## Round 5 — being right is not being pinned, four rounds running

A second reader BLOCKED round 4 with seven findings — the direction stated in
the review itself: two closed rules already written elsewhere in this module
("count only what is derivable from source"; "decline rather than pick"),
not a fourth traced shape or a fifth phrase.

1. **R4-2 — the closed rule, applied to `_collection_kind`.** A `Starred`
   element in a list/tuple/set literal, or a `None` key (a `**` unpack) in a
   dict literal, is one AST node standing in for however many items its own
   operand contributes at runtime — `len(expr.elts)`/`len(expr.keys)` counted
   the node, not the items, and `(*BASE, "extra")` (`BASE` a 20-tuple) was
   sweep-counted `2` against a real `21`, cleared as compliant, and counted
   into `arithmetically_checked`. Fixed by classifying either shape `_DYNAMIC`
   rather than `_LITERAL` — the identical rule already used for a
   comprehension or a `.split()` result, applied to the one collection shape
   it had not yet reached.
2. **R4-3 — the closed rule, applied to `_compare_sites`.** More than one
   comparison site for the same floor name is resolved independently at every
   site rather than picked from `site[0]`; agreement (any site would answer
   identically) is used, disagreement is declined — the same shape three
   sibling functions in this module already use
   (`_resolve_parameter_via_callers`, `_resolve_evidence_path_expr`,
   `_evidence_calls_for`). Closes a real, live exposure, not only the reader's
   constructed fixture: `extraction.MIN_EVALUATION_LABELS_PER_DIMENSION` and
   `interview.MINIMUM_TRAIT_EPISODES`/`MINIMUM_TRAIT_OCCASIONS` each compare
   the same floor against genuinely different quantities at different sites (a
   list length at one, a per-dimension running tally at another), and whether
   they landed `dynamic` or `bounds_read_and_out_of_scope` already depended on
   source order. `MINIMUM_FLOORS_SWEPT: 76 -> 73` is this — see its own
   comment for why that is zero slack, not a narrowed margin.
3. **R4-1 — the self-floor's own claim, corrected rather than made true by
   force.** `MINIMUM_FLOORS_ARITHMETICALLY_CHECKED`'s comment claimed
   "shipping a wrong [evidence file] visibly breaches this floor"; measured,
   an *understated* wrong value does not (`margin <= 0` reads compliant,
   identically to a genuinely smaller-but-real population). Making
   `margin < 0` always a finding was tried and reverted: it also flags every
   floor legitimately set stricter than its own population for an unrelated
   reason, a real, deliberate, tested shape
   (`test_a_floor_already_breaching_its_population_needs_no_argument`). The
   report offered two fixes — "make a wrong value breach, or delete the
   claim" — and the first one costs a real invariant this module has always
   protected, so the comment states the true, narrower claim instead: an
   *overstated* wrong value is still caught (it pushes `margin` positive, the
   arithmetic every other floor gets); an understated one is indistinguishable
   from a correctly-shrunk population, and this module does not guess which.
4. **R4-5 — round 3's F2, unclosed a second time, closed the third.**
   `_MARGIN_ARGUED_RE`'s bare-keyword fallback decided compliance from
   *anywhere* in a comment, and a self-floor's own comment accretes one
   paragraph per round — deleting the sentence that actually argued this
   floor's margin left `margin`/`slack` alive in an earlier paragraph
   describing this module's own mechanism, not this floor's gap. Retiring the
   keyword fallback entirely was tried and reverted too: it breaks a real,
   intentional shape
   (`test_a_margin_argued_in_writing_is_not_flagged`,
   `second_reader.STDLIB_DISAGREEMENTS_AT_LEAST`'s "this one keeps its slack"
   on the live tree) — a floor pinned to a third party's own behaviour is
   allowed to argue its margin in free prose with no number to verify. Fixed
   by scoping the fallback to `_last_comment_paragraph`: the block after the
   last blank `#`/`#:` line, the same place every real numeric claim and every
   real free-form argument in this repository already lives.
5. **R4-6 — F3's "independent recomputation" was entailed, not independent.**
   `measure()`'s internal call to `_margin_finding` and the live-tree test's
   "second" call passed the identical six arguments derived from the
   identical source, so it could not disagree — and the `next(...)` locating
   the pinned record raised `StopIteration` before the recomputation ran on
   any tree where it would have. Fixed with a hand-written regex *in the test
   file*, never calling `_claimed_current_value`/`_claimed_margin_size` or
   anything else `_margin_finding` itself uses, so the two live-tree tests now
   check the comment's numeric claim against reality by a genuinely separate
   method — and report which half failed (not pinned, vs. pinned but stale)
   rather than raising `StopIteration`.
6. **R4-4 — a live instance of this task's own defect.**
   `cv_store.MINIMUM_CHECKS = 17` against `probe_intake`'s own measured 22 —
   five deletions breaching nothing, in a comment the *previous* round wrote
   one line below the floor it raised correctly. Raised to 22, zero slack,
   verified the same way `MINIMUM_FIELDS_MEASURED` above it was: by running
   `probe_intake` directly. Not reachable by this sweep for the identical
   reason (`_main` picks its evidence path through `argparse`).
7. **R4-7 — three more zero-slack spellings.** "nothing **to** spare" (the
   natural English of the accepted "nothing spare"), "slack: zero" (noun and
   number reversed from every other accepted spelling), "no headroom
   whatsoever" (kept as one literal three-word phrase, not a `no`-led noun-set
   join, for the same collision reasons round 4 already gave).

**Settable-to-`0`-or-`1` with the gate still exit-0**, measured against copies
of `src/integral` (152 mutations, fresh subprocess each, `PYTHONDONTWRITEBYTECODE=1`):
round 4 measured 30 of 76 (39%); this round is committed with the number this
round actually measured — see the pull request for the after-fix figure,
regenerated the same way. All of round 4's 30 survivors were the `dynamic`
branch, unconstrained by `arithmetically_checked`; R4-2 and R4-3 correct two
`arithmetic`-branch miscounts and one order-dependent scope decision, not the
`dynamic` branch's own weaker check, which the report's own framing (and
`test_a_margin_argued_in_writing_is_not_flagged`) says is a deliberate,
narrower guarantee by design — carries an explanation, never a computed
margin — not a defect this round's two closed rules were about.

## The denominator

`floors_swept` is every floor this module classified, one way or the other, and
`arithmetically_checked` (round 4) is how many of those actually reached a
computed margin rather than sitting on a comment alone. Per T100/T122, both are
committed as **literal** floors (`MINIMUM_FLOORS_SWEPT`,
`MINIMUM_FLOORS_ARITHMETICALLY_CHECKED`), never as the count of the day: derived
from the sweep's own result, either would shrink with anything the sweep stops
finding or stops being able to pin — this task's own defect, committed inside
this task's gate, which is precisely what T122's review round flagged and what
`record` below refuses to repeat.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_DIR = Path(__file__).resolve().parent
_THIS_FILE = Path(__file__).resolve()
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T159.json"

#: Round 2's fix for the reader's first finding: this repository's module-constant
#: convention (a name starting with a letter, all caps) — not a floor-specific
#: spelling. `bulk_filter.MUST_KEEP_ROWS` and `bodyless_post.PROBES_FLOOR`-shaped
#: names (neither `MINIMUM_`/`MIN_`/`_AT_LEAST`/`_MINIMUM`) are exactly what the old,
#: floor-shaped-only pattern could never see, no matter how many more spellings were
#: added to it — an enumeration of spellings has no last element. What makes a name
#: worth sweeping is what its *value* is (see `_is_len_derived` below and
#: `_module_constant_candidates`), never how it is spelled.
#:
#: Round 3: a leading underscore is still this repository's own convention — a
#: module-private constant — and round 2's pattern excluded it anyway, which is
#: the same "the name filter is still a filter" defect one character narrower.
#: `plan_v2._MIN_TASK_CELLS`, `approval._SHINGLE`,
#: `extraction._CONFIRMING_MATCHES_FOR_BIPOLAR` are real `len(...)`-compared
#: floors on `main`, invisible to round 2's pattern for no reason but the
#: underscore. The optional `_?` is the whole fix; the value-shape gate below is
#: what still keeps every non-floor private constant (a compiled regex, a path,
#: a fixture string) off the candidate list.
_CONSTANT_NAME_RE = re.compile(r"^_?[A-Z][A-Z0-9_]*$")

#: Phrasing this repository actually uses, in the floors already read while building
#: this module, to argue that a floor's margin below its population is deliberate
#: rather than an accident: `salary_recovery.MINIMUM_WORDING_CASES` ("Raised from 40
#: ... sits far below"), `gate_reader_agreement.MINIMUM_ARRANGEMENTS_PROBED` ("one unit
#: of slack"), `gate_reader_agreement.MINIMUM_GATES_COMPARED` ("sits under today's
#: total"), `audit_followup.CASES_AT_LEAST` / `connector_policy.ADJUDICATIONS_AT_LEAST`
#: ("deliberately under"), `connector_policy.PACKAGES_AT_LEAST` ("Same reasoning"),
#: `robots.FIXTURES_AT_LEAST` / `second_reader`'s four ("Raised ... to", "raised
#: again", "kept its slack", "small on purpose"), `review_reader`'s four ("the margin
#: over the observed count is unchanged").
#:
#: **This is a keyword match, and a keyword match is not a claim of correctness —
#: round 1's own docstring said the opposite ("never one it wrongly clears") and a
#: second reader measured that false: every one of the fourteen comments this task
#: wrote reads "Raised to what the probe carries — N, zero slack", and the trigger
#: words (`raised`, `slack`) stay in the text forever, including after a later edit
#: drops the floor to something the sentence no longer describes.** Regex-matched
#: prose can certify a margin that used to be true. `_zero_slack_claim_contradicts`
#: below is what actually falsifies a stale claim rather than merely detecting the
#: presence of words that once argued a true one; this pattern still gates whether
#: an *argument* was attempted at all, which a claim carrying no number at all (the
#: older, spelled-out style — "one unit of slack", "sits under today's total") has
#: no other way to state.
_MARGIN_ARGUED_RE = re.compile(
    r"\bmargin\b|\bslack\b|\braised\b|deliberately\s+(?:under|below)|"
    r"sits\s+(?:well\s+|far\s+)?(?:under|below)|\bwell\s+below\b|\bfar\s+below\b|"
    r"same\s+reasoning|on\s+purpose",
    re.IGNORECASE,
)

#: A *specific, falsifiable* form `_MARGIN_ARGUED_RE` cannot check: this task's own
#: idiom for a zero-margin claim ("N, zero slack" / "no slack" / "zero margin").
#: Unlike "sits well below" (true of a whole family of margins, never stale merely
#: because the population moved a little), "zero slack" asserts an exact equality —
#: floor equals population — and so states a number a later edit can silently
#: falsify while leaving the sentence looking exactly as true as it did the day it
#: was written.
#:
#: **Round 4 (F7, half one):** round 3's pattern was a literal alternation of three
#: exact phrases, and a second reader measured four more real-sounding spellings
#: sliding straight past it at floor `1` against a stated population of 19: "no
#: margin at all", "zero headroom", "nothing spare", and the hyphenated
#: "zero-slack". An enumeration of phrasings has no last element (CLAUDE.md); the
#: fix widens the two safe words this repository never uses for anything else
#: (`zero`, `nothing`) across the same noun set — `zero slack`/`zero margin`/
#: `zero headroom`/`zero-slack`/`nothing spare` — rather than splicing a fourth
#: exact phrase into an alternation.
#:
#: `no` is deliberately **not** joined to `margin`/`headroom`/`spare` the same
#: way: this repository's own, unrelated, pre-existing idiom for a *previous*
#: floor's defect — "with no margin argued for the gap" — appears in fourteen
#: real comments (`bulk_filter`, `candidate`, `cv_store`, `elicit_extract`,
#: `page_placeholder`, `question_bank`, `trait_sufficiency` among them), and
#: `skill_budget.py`'s "a budget with no headroom" and `profile.py`'s "no spare
#: whitespace" are two more unrelated collisions found the same way. A first
#: version of this fix joined `no` to the whole noun set and turned all of those
#: into false "zero slack" accusations against comments that were never making
#: that claim — caught before push by running the live tree's own
#: `test_the_live_tree_has_zero_findings`, which is exactly the check this
#: broadening would otherwise have broken silently for real floors nowhere near
#: this task. `no slack` (round 2's original, collision-free) and the literal
#: `no margin at all` (the report's own attack phrase, specific enough not to
#: match "no margin argued") are kept as the two `no`-led exceptions.
#:
#: **Round 5 (R4-7):** a second reader found three more real-sounding spellings
#: sliding past the round-4 pattern at floor `1` against a stated population of
#: 19 — "nothing **to** spare" (the natural English of the accepted "nothing
#: spare", broken by the inserted "to"), "slack: zero" (the noun and the number
#: in the opposite order from every other accepted spelling), and "no headroom
#: whatsoever" (a specific three-word phrase, not the bare "no headroom" this
#: module deliberately keeps out of the noun-set-wide `no` join above — the
#: same collision risk as before: `connector_policy.py`'s unrelated "no second
#: reader whatsoever" and `skill_budget.py`'s "a budget with no headroom" would
#: both be false accusations under a bare `no\s+headroom` or `no\s+\w+\s+
#: whatsoever`, so this stays the one literal three-word phrase, not a second
#: `no`-led noun-set join). "nothing spare" is widened to allow an optional
#: "to"; a `noun[:]? zero` alternative is added for the reversed order, kept
#: exactly as narrow as the forward `zero noun` form (three nouns, no `no`
#: variant) so it inherits the same collision safety rather than a fresh one.
_ZERO_SLACK_CLAIM_RE = re.compile(
    r"\bzero[\s-]+(?:slack|margin|headroom)\b|\bnothing\s+(?:to\s+)?spare\b|"
    r"\b(?:slack|margin|headroom)\s*:\s*zero\b|"
    r"\bno\s+slack\b|\bno\s+margin\s+at\s+all\b|\bno\s+headroom\s+whatsoever\b",
    re.IGNORECASE,
)

_DIGITS_RE = re.compile(r"\d+")

#: A minimal English cardinal vocabulary — this repository argues some floors in
#: words rather than digits (`profile.MINIMUM_FIELDS_CHECKED`'s own comment says
#: "Ten today", `gate_reader_agreement.MINIMUM_ARRANGEMENTS_PROBED`'s says "It is
#: thirteen, not twelve"). A digit-only check would silently miss exactly the
#: floors round 1 named in the task table.
_ONES_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_TENS_WORDS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}


def _spelled_out_numbers(text: str) -> set[int]:
    """Every cardinal number `text` states in English words — "nine", "twenty
    five" — never composing "hundred" (no zero-slack claim in this repository
    combines one with a three-digit number, and getting that composition wrong
    would be worse than not attempting it)."""
    return {value for value, _end in _spelled_out_numbers_with_positions(text)}


def _spelled_out_numbers_with_positions(text: str) -> list[tuple[int, int]]:
    """Every cardinal number `text` states in English words, paired with the
    character offset (into `text`) immediately after it — the same vocabulary as
    `_spelled_out_numbers`, kept apart so a caller can find the number *nearest*
    a matched phrase rather than merely whether some number appears anywhere in
    the text (see `_nearest_number_before`/`_nearest_number_after`, F7)."""
    matches = list(re.finditer(r"[a-z]+", text.lower()))
    found: list[tuple[int, int]] = []
    i = 0
    while i < len(matches):
        word = matches[i].group()
        if word in _TENS_WORDS:
            value = _TENS_WORDS[word]
            end = matches[i].end()
            if i + 1 < len(matches) and matches[i + 1].group() in _ONES_WORDS:
                value += _ONES_WORDS[matches[i + 1].group()]
                end = matches[i + 1].end()
                i += 1
            found.append((value, end))
        elif word in _ONES_WORDS:
            found.append((_ONES_WORDS[word], matches[i].end()))
        i += 1
    return found


def _nearest_number_before(text: str) -> int | None:
    """The value of whichever number (digit or spelled-out) ends *closest to the
    end* of `text` — used to find the number an idiom right after `text` is
    actually claiming, rather than any number that happens to appear somewhere
    earlier in the same comment.

    **Round 4 (F7, half two).** Round 3's `_zero_slack_claim_contradicts` built
    the *set* of every number in an 80-character look-behind window and asked
    only whether the floor's current value was a member — so a decoy number
    anywhere in that window (a year, an issue reference, an unrelated earlier
    count) could sit beside the real claim and clear it regardless of what the
    real claim said. Measured: `"Raised to 1 in 2026; the probe carries 19, zero
    slack."` and `"Round 1 raised this. The probe carries 19, zero slack."` both
    cleared at floor `1` — the decoy `1` (a year fragment, a round number) was in
    the accepted set beside the real claim, `19`. Every genuine instance of this
    idiom in this repository states its number *immediately* before the phrase,
    so only the nearest one — the last found scanning left to right, since the
    window is text strictly before the phrase — is the claim; everything earlier
    is history or an unrelated reference, exactly the shape a real comment full
    of round numbers and issue links already has."""
    best_end = -1
    best_value: int | None = None
    for match in _DIGITS_RE.finditer(text):
        if match.end() > best_end:
            best_end = match.end()
            best_value = int(match.group())
    for value, end in _spelled_out_numbers_with_positions(text):
        if end > best_end:
            best_end = end
            best_value = value
    return best_value


def _nearest_number_after(text: str) -> int | None:
    """The value of whichever number (digit or spelled-out) *starts closest to
    the start* of `text` — the mirror of `_nearest_number_before`, for an idiom
    (`"Committed at N"`) that states its number immediately *after* the trigger
    phrase rather than before it."""
    best_start = len(text) + 1
    best_value: int | None = None
    for match in _DIGITS_RE.finditer(text):
        if match.start() < best_start:
            best_start = match.start()
            best_value = int(match.group())
    words = list(re.finditer(r"[a-z]+", text.lower()))
    i = 0
    while i < len(words):
        word = words[i].group()
        if word in _TENS_WORDS:
            start = words[i].start()
            value = _TENS_WORDS[word]
            if i + 1 < len(words) and words[i + 1].group() in _ONES_WORDS:
                value += _ONES_WORDS[words[i + 1].group()]
                i += 1
            if start < best_start:
                best_start = start
                best_value = value
        elif word in _ONES_WORDS:
            if words[i].start() < best_start:
                best_start = words[i].start()
                best_value = _ONES_WORDS[word]
        i += 1
    return best_value


def _normalize_comment_text(comment: str) -> str:
    """`comment` with each line's `#`/`#:` prefix stripped and every line joined by
    a single space.

    Every phrase check below runs against this, never the raw comment block: a
    comment line-wraps at this repository's own ruff width, and a phrase can land
    split across two lines with a `#: ` in between — `elicit_extract.MINIMUM_CHECKS`'s
    own comment wraps "zero" and "slack" onto separate lines, and `\\bzero\\s+slack\\b`
    over the raw text sees `"zero\\n#: slack"`, where `#:` is not whitespace and the
    match fails. Read on raw text, that gap would have hidden the exact stale-claim
    contradiction this check exists to catch — silently, on one of the fourteen
    floors this very task fixed.
    """
    words: list[str] = []
    for line in comment.splitlines():
        stripped = re.sub(r"^\s*#:?\s*", "", line.strip())
        if stripped:
            words.append(stripped)
    return " ".join(words)


def _last_comment_paragraph(comment: str) -> str:
    """The final paragraph of `comment` — the run of non-blank `#`-lines after
    the last blank comment line (a bare `#`/`#:`), or the whole comment when
    it has none. Round 5 (R4-5): a self-floor's own comment accretes one
    paragraph per round, each separated from the last by a blank `#:` line
    (this module's own convention, used throughout); the "Committed at
    N"/"N points of slack"/"N, zero slack" claim — and any genuine free-form
    margin argument — always lives in the paragraph beside the declaration,
    never an earlier one recounting history. Scoping the keyword fallback in
    `_margin_finding` to this paragraph is what stops an incidental "margin"/
    "slack" in an earlier round's narrative (describing this module's own
    mechanism, not this floor's gap) from surviving deletion of the sentence
    that actually argued the current margin."""
    paragraphs: list[list[str]] = [[]]
    for line in comment.splitlines():
        if re.sub(r"^\s*#:?\s*", "", line.strip()):
            paragraphs[-1].append(line)
        elif paragraphs[-1]:
            paragraphs.append([])
    non_empty = [p for p in paragraphs if p]
    return "\n".join(non_empty[-1]) if non_empty else ""


#: A backtick-quoted code span (`` `_D6_FIXTURE` ``, `` `PROBES` ``) — stripped out
#: of the look-behind window before digit/word extraction. Round 2's reader found
#: that a digit *inside an identifier* (`_D6_FIXTURE`'s `6`) enters `claimed` and
#: falsely clears a floor set to that digit; every real "N, zero slack" comment in
#: this repository states N as plain prose outside any backtick span, so nothing
#: this check needs to see is ever lost by removing backtick spans first.
_BACKTICK_CODE_RE = re.compile(r"`[^`]*`")


def _zero_slack_claim_contradicts(comment: str, literal_value: int) -> bool:
    """True when `comment` states a "zero slack" (or "zero margin" / "no slack")
    claim beside a specific number, and that number is not the floor's own current
    value.

    This is the concrete fix for the reader's first finding: every one of this
    task's fourteen fixed floors is commented "Raised to what the probe/table
    carries — N, zero slack" — a comment written once, for the value that was true
    the day it was written. `_MARGIN_ARGUED_RE` matches the words `raised` and
    `slack` in that sentence forever, including after a later edit changes N to
    something the sentence no longer describes; this instead re-extracts the
    number the comment actually claims and compares it against what the code
    currently declares, so a floor dropped out from under a comment that still
    reads "9, zero slack" is caught even though every trigger word is still
    sitting right there.

    **Round 3 fix, the round-2 reader's headline finding.** The window round 2
    scanned included the *matched phrase itself* (`"zero slack"` contains the word
    "zero"), and `_spelled_out_numbers("zero slack") == {0}` — so `claimed` always
    contained `0`, for every comment this check can ever fire on, and a floor
    silently dropped to `0` was therefore *never* a contradiction: the accept-set
    was seeded by the checker's own trigger word. Every real instance of this
    idiom in this repository states its number **before** the phrase ("N, zero
    slack" — verified against all fourteen), never after and never inside it, so
    the window is now the text strictly *before* the match only — the trigger
    phrase itself never contributes a digit or a word again, and neither does
    anything after it (closing the sibling misread where a trailing `(T159)`
    issue reference inside the old +10 look-ahead was accepted as the claimed
    number). Backtick-quoted code is stripped before extraction, closing the
    `` `_D6_FIXTURE` `` misread the same way. The window is widened to 80
    characters to still reach a number spelled well before the phrase (`profile`'s
    "Ten today, matching `_D6_FIXTURE` exactly: zero slack" needs the full clause,
    not only the last 40 characters of it).

    Silent (returns `False`, deferring to the keyword check above) when a "zero
    slack" phrase carries no number at all — the older, spelled-out style
    (`connector_transport.MINIMUM_RECORD_KEYS_COMPARED`'s "The record carries
    twelve keys and this is twelve — no slack") already survives
    `_spelled_out_numbers`, but a claim with literally no adjacent number is not
    one this check can falsify, so it is not one it accuses either.
    """
    normalized = _normalize_comment_text(comment)
    for match in _ZERO_SLACK_CLAIM_RE.finditer(normalized):
        window = normalized[max(0, match.start() - 80) : match.start()]
        window = _BACKTICK_CODE_RE.sub(" ", window)
        claimed = _nearest_number_before(window)
        if claimed is not None and claimed != literal_value:
            return True
    return False


#: Round 4 (F2): the two other idioms this repository actually uses, beside
#: "N, zero slack", to argue a *positive* margin in writing rather than leaving
#: it silent — both seen verbatim on this task's own denominator floor
#: (`"Committed at 64, three points of slack."`). Each states a number in a
#: fixed grammatical role that `_MARGIN_ARGUED_RE`'s bare keyword match never
#: re-checks: "committed at" states the floor's own current declared value;
#: "N point(s) of slack/margin" states the margin itself. A second reader
#: measured both escaping intact when the floor was mutated to `1` — the
#: keyword ("raised", "slack") stays in the text forever, and neither claim's
#: *number* was ever compared against anything.
#:
#: Deliberately narrow, unlike `_zero_slack_claim_contradicts`'s general
#: "any number in a window" predecessor (F7): each pattern is a specific
#: grammatical slot, not "some number appeared near a keyword" — because this
#: repository also argues margins in free-form history prose
#: (`robots.FIXTURES_AT_LEAST`'s "T151 raised it to 64 ... and its THIRD round
#: to 80", `salary_recovery.MINIMUM_WORDING_CASES`'s "Raised from 40 when the
#: second-reader audit landed 54 more cases") whose numbers are not, and are not
#: claimed to be, the current declaration or the current margin — trying to
#: parse chronological narrative safely was the exact over-broad relaxation
#: round 3's own docstring already tried and reverted for populations. A
#: comment that wants this check's protection states its number in one of
#: these two fixed roles; free-form history stays covered only by the
#: (weaker, but honest about it) keyword match.
_COMMITTED_AT_RE = re.compile(r"\bcommitted\s+at\s+", re.IGNORECASE)
_POINTS_OF_MARGIN_RE = re.compile(r"\bpoints?\s+of\s+(?:slack|margin)\b", re.IGNORECASE)


def _claimed_current_value(comment: str) -> int | None:
    """The number stated immediately after a "Committed at N" claim, or `None`
    if the comment makes no such claim. `None` is silence, not clearance — a
    comment that never claims a specific current value this way is not one
    this check can falsify (`_MARGIN_ARGUED_RE`'s keyword match is what covers
    it instead)."""
    normalized = _BACKTICK_CODE_RE.sub(" ", _normalize_comment_text(comment))
    match = _COMMITTED_AT_RE.search(normalized)
    if match is None:
        return None
    return _nearest_number_after(normalized[match.end() : match.end() + 40])


def _claimed_margin_size(comment: str) -> int | None:
    """The number stated immediately before an "N point(s) of slack/margin"
    claim, or `None` if the comment makes no such claim."""
    normalized = _BACKTICK_CODE_RE.sub(" ", _normalize_comment_text(comment))
    match = _POINTS_OF_MARGIN_RE.search(normalized)
    if match is None:
        return None
    return _nearest_number_before(normalized[max(0, match.start() - 40) : match.start()])


#: String-returning method calls this module treats as producing a scalar (the length
#: of *one* piece of text), never a population. Seen guarding `elicit_extract.MIN_ANSWER_CHARS`
#: (`answer.strip()`) among others.
_SCALAR_STRING_METHODS = frozenset(
    {
        "strip",
        "lower",
        "upper",
        "casefold",
        "title",
        "capitalize",
        "format",
        "strftime",
        "get",
        "join",
    }
)

#: Functions that wrap an iterable without changing how many items are in it — seen
#: wrapping a comprehension before it is measured (`sorted(item.name for item in probes)`
#: in `gate_reader_agreement`).
_COUNT_PRESERVING_WRAPPERS = frozenset({"sorted", "list", "tuple", "set", "frozenset"})


@dataclass(frozen=True)
class FloorFinding:
    """One floor that does not refuse the first deletion of its population."""

    module: str
    name: str
    lineno: int
    reason: str
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "name": self.name,
            "line": self.lineno,
            "reason": self.reason,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class DynamicFloor:
    """An in-scope floor whose population this repository does not itself
    enumerate, and for which no committed evidence file could be resolved either
    — genuinely unpinnable, checked only for "carries some explanation" plus the
    one falsifiable claim this repository's own idiom makes (`_zero_slack_claim_
    contradicts`)."""

    module: str
    name: str
    lineno: int

    def as_dict(self) -> dict[str, Any]:
        return {"module": self.module, "name": self.name, "line": self.lineno}


@dataclass(frozen=True)
class EvidencePinnedFloor:
    """Round 3: a floor whose population this repository does not itself
    enumerate as a fixed collection, but whose *measured* value is committed to
    `status/evidence/*.json` by the same scripted probe the floor guards — so it
    is not an exemption after all, only a population read from a file instead of
    counted from a collection literal. Checked by the exact same margin rule as
    a literal population (`_margin_finding`): this is what closes the round-2
    reader's headline finding, rather than only patching the comment parser that
    finding was really about."""

    module: str
    name: str
    lineno: int
    population: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "name": self.name,
            "line": self.lineno,
            "population": self.population,
        }


@dataclass
class _ModuleInfo:
    stem: str
    path: Path
    source: str
    lines: list[str] = field(default_factory=list)
    tree: ast.Module = field(default=None)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.lines = self.source.splitlines()


def _module_infos(src_dir: Path) -> list[_ModuleInfo]:
    infos = []
    for path in sorted(src_dir.glob("*.py")):
        if path.stem == "__init__":
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        infos.append(_ModuleInfo(stem=path.stem, path=path, source=source, tree=tree))
    return infos


def _literal_int(expr: ast.expr) -> int | None:
    if (
        isinstance(expr, ast.Constant)
        and isinstance(expr.value, int)
        and not isinstance(expr.value, bool)
    ):
        return expr.value
    return None


def _resolved_floor_literal(expr: ast.expr, tree: ast.Module, depth: int = 0) -> int | None:
    """The floor's own value, resolved past two shapes a bare `_literal_int` cannot
    see (round 3, F5): a `BinOp` combining two int literals (`MINIMUM_PROBES = 1 +
    0` — neither side is `len(...)`-derived, but both are literals, so the whole
    expression is still a compile-time constant), and a name that aliases another
    module-level int constant (`_FLOOR = 1` then `MINIMUM_PROBES = _FLOOR` — a
    hand-written number one hop away, not a derived one). Both are legal,
    ordinary Python, and this repository already has the alias shape
    (`_module_level_value`'s own docstring cites `CONTROLS = _control_prs()` as
    the pattern it exists to follow).

    Never confused with `_is_len_derived`'s `len(X) + N` shape: that `BinOp` has
    one `len(...)` operand, this one has two literal-resolving operands, and a
    floor cannot be both at once (`_module_constant_candidates` tries this first,
    `_is_len_derived` second).
    """
    if depth > 5:
        return None
    literal = _literal_int(expr)
    if literal is not None:
        return literal
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, (ast.Add, ast.Sub, ast.Mult)):
        left = _resolved_floor_literal(expr.left, tree, depth + 1)
        right = _resolved_floor_literal(expr.right, tree, depth + 1)
        if left is not None and right is not None:
            if isinstance(expr.op, ast.Add):
                return left + right
            if isinstance(expr.op, ast.Sub):
                return left - right
            return left * right
        return None
    if isinstance(expr, ast.Name):
        module_value = _module_level_value(tree, expr.id)
        if module_value is not None:
            return _resolved_floor_literal(module_value, tree, depth + 1)
    return None


def _is_len_derived(expr: ast.expr, depth: int = 0) -> bool:
    """True when `expr`'s own top-level shape is a `len(...)` call, or simple
    `+`/`-` arithmetic combining one with a plain integer literal
    (`len(ARRANGEMENTS) + 1`) — the shape a *self-referential* floor takes.

    This is never true for a bare collection literal, even though `PROBES = (1, 2,
    3)` is exactly as capitalised as a floor: the population is not a count of
    itself, and round 2's broadened, spelling-independent candidate discovery
    (`_module_constant_candidates`) would otherwise sweep every fixed-collection
    constant in the repository as a "floor" whose value is not even an integer.
    """
    if depth > 3:
        return False
    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and expr.func.id == "len":
        return True
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, (ast.Add, ast.Sub)):
        left_is_len = _is_len_derived(expr.left, depth + 1)
        right_is_len = _is_len_derived(expr.right, depth + 1)
        left_is_literal = _literal_int(expr.left) is not None
        right_is_literal = _literal_int(expr.right) is not None
        return (left_is_len and right_is_literal) or (right_is_len and left_is_literal)
    return False


def _module_constant_candidates(tree: ast.Module) -> list[tuple[str, int, ast.expr]]:
    """Every module-level `NAME = <expr>` (or annotated) naming a module constant by
    this repository's own convention — a name starting with a letter, all caps —
    whose *value* is either a plain integer literal or itself a `len(...)`-derived
    expression (`_is_len_derived`).

    Round 1 gated this step on the floor's own name (`MINIMUM_`/`MIN_`/`_AT_LEAST`/
    `_MINIMUM`), which is exactly what let `bulk_filter.MUST_KEEP_ROWS` and a
    hypothetical `PROBES_FLOOR` go unswept: the name filter is still a filter,
    however many spellings it lists. Scoping by *value shape* instead is what makes
    the broadened name pattern safe: `PROBES = (1, 2, 3)` is just as capitalised as
    `MUST_KEEP_ROWS = 3`, but its value is the collection itself, not a count, so
    `_is_len_derived` (false for a bare literal) keeps it off this list — the
    module never has to special-case a name it does not recognise as a table.
    """
    found: list[tuple[str, int, ast.expr]] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        else:
            continue
        for target in targets:
            if not (isinstance(target, ast.Name) and _CONSTANT_NAME_RE.match(target.id)):
                continue
            if _resolved_floor_literal(value, tree) is not None or _is_len_derived(value):
                found.append((target.id, node.lineno, value))
    return found


#: A bare `NAME = value` (optionally annotated) line — used only to recognise a
#: sibling floor declared right above this one, so `interview.MINIMUM_TRAIT_EPISODES`
#: / `MINIMUM_TRAIT_OCCASIONS` (one shared comment above the first of the pair) reads
#: that comment for the second floor too, rather than reporting it undocumented for a
#: formatting reason that has nothing to do with whether it is argued.
_SIBLING_ASSIGNMENT_RE = re.compile(r"^[A-Z][A-Z0-9_]*\s*(?::[^=]+)?=\s*.+$")


def _comment_block_above(lines: list[str], lineno: int) -> str:
    """The contiguous `#`-prefixed lines above a 1-indexed declaration line.

    Skips back over any immediately-preceding bare constant declarations first, so a
    comment written once for a group of floors is read for each of them. Also tolerates
    a single blank line between the code and the comment — a section-header block
    followed by a blank line before the constant it introduces
    (`reader_notes.MINIMUM_PROBES`) is a real explanation, not a missing one.
    """
    i = lineno - 2  # zero-indexed line just above the declaration
    while (
        i >= 0
        and not lines[i].strip().startswith("#")
        and _SIBLING_ASSIGNMENT_RE.match(lines[i].strip())
    ):
        i -= 1
    if i >= 0 and lines[i].strip() == "" and i - 1 >= 0 and lines[i - 1].strip().startswith("#"):
        i -= 1
    collected: list[str] = []
    while i >= 0 and lines[i].strip().startswith("#"):
        collected.append(lines[i])
        i -= 1
    collected.reverse()
    return "\n".join(collected)


def _all_function_defs(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _innermost_enclosing(
    node: ast.AST, functions: list[ast.FunctionDef | ast.AsyncFunctionDef]
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """The most tightly-nested function in `functions` whose body spans `node`."""
    best: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for fn in functions:
        if (
            hasattr(fn, "lineno")
            and hasattr(node, "lineno")
            and fn.lineno <= node.lineno <= (getattr(fn, "end_lineno", None) or 10**9)
            and (best is None or fn.lineno > best.lineno)
        ):
            best = fn
    return best


def _module_level_value(tree: ast.Module, name: str) -> ast.expr | None:
    """Whatever a module-level `NAME = <expr>` (or annotated) assigns, unfiltered."""
    for node in tree.body:
        targets: list[ast.expr]
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id == name:
                return value
    return None


def _module_level_literal_collection(tree: ast.Module, name: str) -> ast.expr | None:
    value = _module_level_value(tree, name)
    if isinstance(value, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
        return value
    return None


def _param_default(
    func: ast.FunctionDef | ast.AsyncFunctionDef, param_name: str
) -> ast.expr | None:
    args = func.args
    positional = list(args.posonlyargs) + list(args.args)
    defaults = list(args.defaults)
    # Standard Python alignment: defaults line up with the *trailing* positional args.
    offset = len(positional) - len(defaults)
    for index, arg in enumerate(positional):
        if arg.arg == param_name and index >= offset:
            return defaults[index - offset]
    for kwarg, kwdefault in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        if kwarg.arg == param_name and kwdefault is not None:
            return kwdefault
    return None


def _subscript_string_key(node: ast.Subscript) -> tuple[str, str] | None:
    """`obj["key"]` → `(obj_name, "key")`, when `obj` is a bare name and the key a string."""
    if not isinstance(node.value, ast.Name):
        return None
    key_node = node.slice
    if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
        return (node.value.id, key_node.value)
    return None


def _assignments_to_name(
    func: ast.FunctionDef | ast.AsyncFunctionDef, name: str, before_lineno: int | None
) -> list[ast.expr]:
    found: list[tuple[int, ast.expr]] = []
    for node in ast.walk(func):
        # Round 3: an *annotated* assignment (`stdlib_disagreements: list[dict[str,
        # str]] = []`) is a distinct AST node from `ast.Assign` — a plain `isinstance
        # (node, ast.Assign)` gate never sees it, which is why
        # `second_reader.STDLIB_DISAGREEMENTS_AT_LEAST`'s population (built by
        # `.append()` on exactly this annotated initial binding) stayed unresolved
        # despite the append-in-a-loop shape below already knowing how to read it.
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id == name:
                found.append((node.lineno, value))
    if before_lineno is not None:
        found = [pair for pair in found if pair[0] < before_lineno] or found
    found.sort(key=lambda pair: pair[0])
    return [value for _, value in found]


def _assignments_to_subscript(
    func: ast.FunctionDef | ast.AsyncFunctionDef, key: tuple[str, str], before_lineno: int | None
) -> list[ast.expr]:
    found: list[tuple[int, ast.expr]] = []
    for node in ast.walk(func):
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Subscript):
                found_key = _subscript_string_key(target)
                if found_key == key:
                    found.append((node.lineno, value))
    if before_lineno is not None:
        found = [pair for pair in found if pair[0] < before_lineno] or found
    found.sort(key=lambda pair: pair[0])
    return [value for _, value in found]


def _appended_in_a_loop(func: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> bool:
    """True if `name.append(...)` / `.add(...)` / `.update(...)` appears anywhere in `func`."""
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"append", "add", "update", "extend"}
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == name
        ):
            return True
    return False


def _incremented_in_a_loop(func: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> bool:
    """True if `name += ...` appears anywhere in `func` — the running-count shape
    `naming.measure`'s `scanned` and `review_reader.measure`'s `reports_found` both
    use instead of a comprehension."""
    for node in ast.walk(func):
        if (
            isinstance(node, ast.AugAssign)
            and isinstance(node.op, ast.Add)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
        ):
            return True
    return False


_UNKNOWN = "unknown"
_SCALAR = "scalar"
_LITERAL = "literal"
_DYNAMIC = "dynamic"


def _resolve_parameter_via_callers(
    func: ast.FunctionDef | ast.AsyncFunctionDef, param_name: str, tree: ast.Module, depth: int
) -> tuple[str, int | None]:
    """`func`'s own `param_name` is never assigned inside `func` — a parameter with
    no default is bound by whoever *calls* `func`, not by `func` itself.

    This is the shape most of this repository's own "breach" functions take:
    `gate_reader_agreement.floor_breaches(measured)` reads
    `measured["arrangements_probed"]`, but `measured` only ever means anything at
    the three call sites that pass it, each `measured = measure(...)` a few lines
    above. Finds every call to `func` by name anywhere in the module, resolves
    what each one binds to `param_name` in *that caller's own* scope, and accepts
    the answer only when every call site agrees — a function this sweep cannot
    show has one consistent meaning for a parameter is not one it may guess at
    from the first call site it happens to find.
    """
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == func.name
    ]
    if not calls:
        return _UNKNOWN, None
    all_functions = _all_function_defs(tree)
    results: list[tuple[str, int | None]] = []
    for call in calls:
        mapping = _bind_call_arguments(call, func)
        arg_expr = mapping.get(param_name)
        if arg_expr is None:
            return _UNKNOWN, None
        caller_func = _innermost_enclosing(call, all_functions)
        results.append(_collection_kind(arg_expr, tree, caller_func, call.lineno, depth + 1))
    first = results[0]
    if first[0] in (_LITERAL, _DYNAMIC) and all(result == first for result in results):
        return first
    return _UNKNOWN, None


def _dict_value_for_key(dict_literal: ast.Dict, key_string: str) -> ast.expr | None:
    for key_node, value_node in zip(dict_literal.keys, dict_literal.values, strict=True):
        if (
            isinstance(key_node, ast.Constant)
            and key_node.value == key_string
            and value_node is not None
        ):
            return value_node
    return None


def _resolve_subscript_param_via_callers(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    param_name: str,
    key_string: str,
    tree: ast.Module,
    depth: int,
) -> tuple[str, int | None]:
    """What `param_name[key_string]` denotes, when `param_name` is one of
    `func`'s own parameters bound by whoever calls it
    (`floor_breaches(measured)` reading `measured["arrangements_probed"]`).

    Resolved separately, in *each* caller's own scope, all the way down to a
    classified `(kind, count)` — never by comparing the dict literals or the raw
    argument expressions themselves, both of which can look identical across two
    callers that mean different things (`measure(probes=PROBES)` and
    `measure_other(probes=OTHER_PROBES)` both return `{"probes_evaluated":
    len(probes)}` — the same dict shape, a different population once `probes` is
    read in each function's own scope). Only full agreement on the *final*
    classification counts.
    """
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == func.name
    ]
    if not calls:
        return _UNKNOWN, None
    all_functions = _all_function_defs(tree)
    results: list[tuple[str, int | None]] = []
    for call in calls:
        mapping = _bind_call_arguments(call, func)
        arg_expr = mapping.get(param_name)
        if arg_expr is None:
            return _UNKNOWN, None
        caller_func = _innermost_enclosing(call, all_functions)
        dict_literal, dict_func = _resolve_to_dict_literal(arg_expr, tree, caller_func)
        if dict_literal is None:
            return _UNKNOWN, None
        value_node = _dict_value_for_key(dict_literal, key_string)
        if value_node is None:
            return _UNKNOWN, None
        results.append(_collection_kind(value_node, tree, dict_func, None, depth + 1))
    first = results[0]
    if first[0] in (_LITERAL, _DYNAMIC) and all(result == first for result in results):
        return first
    return _UNKNOWN, None


def _collection_kind(
    expr: ast.expr,
    tree: ast.Module,
    func: ast.FunctionDef | ast.AsyncFunctionDef | None,
    before_lineno: int | None,
    depth: int = 0,
) -> tuple[str, int | None]:
    """Classify what `expr` denotes: a counted literal, a dynamically-built collection,
    a scalar (one piece of text), or unknown. Follows at most a few hops of local
    reassignment so this stays a sweep, not a full dataflow analysis."""
    if depth > 5:
        return _UNKNOWN, None

    if isinstance(expr, (ast.List, ast.Tuple, ast.Set)):
        # Round 5 (R4-2): `len(expr.elts)` counts AST *elements*, not runtime
        # items, and a `Starred` element is one AST node standing in for
        # however many items its own operand unpacks to at runtime -- unknown
        # from source, never `1`. A second reader measured `(*BASE, "extra")`
        # (`BASE` a 20-tuple) sweep-counted as population `2` while the real
        # length is `21`, cleared as compliant and counted toward
        # `arithmetically_checked`. The closed rule this repository already
        # states elsewhere for exactly this shape (T159's own task file: "count
        # only what is derivable from source") — any `Starred` element makes
        # the count undecidable from the literal alone, so this is `_DYNAMIC`,
        # never a silently-wrong `_LITERAL` count.
        if any(isinstance(elt, ast.Starred) for elt in expr.elts):
            return _DYNAMIC, None
        return _LITERAL, len(expr.elts)
    if isinstance(expr, ast.Dict):
        # Round 5 (R4-2): the mirror case for `{**BASE, "x": 1}` — a `**`
        # unpacking shows up as a `None` key in `expr.keys`, one AST slot for
        # however many keys `BASE` actually contributes at runtime. Measured:
        # sweep-counted population `2` against a real `9`. Same rule, same
        # reason: undecidable from source ⇒ `_DYNAMIC`.
        if any(key is None for key in expr.keys):
            return _DYNAMIC, None
        return _LITERAL, len(expr.keys)
    if isinstance(expr, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
        return _DYNAMIC, None

    if isinstance(expr, ast.IfExp):
        # `X = DEFAULT if param is None else param` — the module's own fixture unless
        # a caller overrides it. Seen in `review_reader.measure`
        # (`states = CONTROLS if controls is None else controls`). The overriding
        # branch is never staticaly known, so this is a *dynamic* population even
        # when the default branch alone would count as a literal — the sweep must
        # not claim an exact count a caller can change.
        body_kind, _ = _collection_kind(expr.body, tree, func, before_lineno, depth + 1)
        else_kind, _ = _collection_kind(expr.orelse, tree, func, before_lineno, depth + 1)
        if body_kind in (_LITERAL, _DYNAMIC) or else_kind in (_LITERAL, _DYNAMIC):
            return _DYNAMIC, None
        return _UNKNOWN, None

    if isinstance(expr, ast.Call):
        if isinstance(expr.func, ast.Name) and expr.func.id == "len" and len(expr.args) == 1:
            inner_kind, inner_count = _collection_kind(
                expr.args[0], tree, func, before_lineno, depth + 1
            )
            if inner_kind == _LITERAL:
                return _LITERAL, inner_count
            if inner_kind == _DYNAMIC:
                return _DYNAMIC, None
            return _UNKNOWN, None
        if (
            isinstance(expr.func, ast.Name)
            and expr.func.id in _COUNT_PRESERVING_WRAPPERS
            and expr.args
        ):
            inner_kind, inner_count = _collection_kind(
                expr.args[0], tree, func, before_lineno, depth + 1
            )
            if inner_kind in (_LITERAL, _DYNAMIC):
                return (_LITERAL, inner_count) if inner_kind == _LITERAL else (_DYNAMIC, None)
            return _UNKNOWN, None
        if isinstance(expr.func, ast.Attribute) and expr.func.attr in _SCALAR_STRING_METHODS:
            return _SCALAR, None
        if isinstance(expr.func, ast.Attribute) and expr.func.attr in {"split", "splitlines"}:
            # `.split()`/`.splitlines()` on one piece of text produces a genuine
            # *collection* — a list of words or lines — never a scalar, and its
            # count depends on the text's content, so it can never be counted
            # from source (`_DYNAMIC`, never `_LITERAL`). Distinct from
            # `_SCALAR_STRING_METHODS`: `approval._SHINGLE`'s population is
            # `len(_words(episode))` where `_words` returns `...split()` — before
            # this, `.split()` fell through to `_UNKNOWN` (not a wrapper, not a
            # scalar method) and the floor was invisible for a reason that had
            # nothing to do with its name.
            return _DYNAMIC, None
        if (
            isinstance(expr.func, ast.Name)
            and expr.func.id in {"set", "list", "dict", "frozenset"}
            and not expr.args
        ):
            return _LITERAL, 0
        if isinstance(expr.func, ast.Name):
            # A call to a same-module function — seen building the fixed control set a
            # delegated floor is checked against (`review_reader.CONTROLS =
            # _control_prs()`) and, with arguments, the ubiquitous `measured =
            # measure(...)` shape a `_main`/`write_evidence` reads its own gate from.
            # One hop into the callee's own `return` is enough to reach what it
            # builds; this never evaluates the call, so what the *arguments* are does
            # not matter, only what the callee's body always returns.
            callee = _top_level_function(tree, expr.func.id)
            if callee is not None:
                returns = _function_returns(callee)
                chosen = _unambiguous_return(returns)
                if chosen is not None:
                    return _collection_kind(chosen, tree, callee, None, depth + 1)
                if len(returns) > 1:
                    return _DYNAMIC, None
        return _UNKNOWN, None

    if isinstance(expr, ast.Name):
        module_literal = _module_level_literal_collection(tree, expr.id)
        if module_literal is not None:
            return _collection_kind(module_literal, tree, func, before_lineno, depth + 1)
        module_value = _module_level_value(tree, expr.id)
        if module_value is not None:
            # Not a literal collection directly (handled above), but a module-level
            # name all the same — e.g. `CONTROLS = _control_prs()`. Recurse into
            # whatever it holds rather than stopping at "not a literal".
            return _collection_kind(module_value, tree, None, None, depth + 1)
        if func is not None:
            default = _param_default(func, expr.id)
            if default is not None:
                return _collection_kind(default, tree, func, before_lineno, depth + 1)
            assignments = _assignments_to_name(func, expr.id, before_lineno)
            if assignments:
                rhs = assignments[-1]
                if (
                    isinstance(rhs, (ast.List, ast.Set))
                    and not rhs.elts
                    and _appended_in_a_loop(func, expr.id)
                ):
                    return _DYNAMIC, None
                if (
                    isinstance(rhs, ast.Constant)
                    and isinstance(rhs.value, int)
                    and not isinstance(rhs.value, bool)
                    and _incremented_in_a_loop(func, expr.id)
                ):
                    return _DYNAMIC, None
                return _collection_kind(rhs, tree, func, before_lineno, depth + 1)
            param_names = (
                {a.arg for a in func.args.posonlyargs}
                | {a.arg for a in func.args.args}
                | {a.arg for a in func.args.kwonlyargs}
            )
            if expr.id in param_names:
                return _resolve_parameter_via_callers(func, expr.id, tree, depth)
        return _UNKNOWN, None

    if isinstance(expr, ast.Subscript):
        key = _subscript_string_key(expr)
        if key is not None:
            base_name, key_string = key

            # Shape one: `obj["key"] = <expr>` somewhere earlier in the same function
            # (`committed["arrangements_probed"] = ...`).
            if func is not None:
                assignments = _assignments_to_subscript(func, key, before_lineno)
                if assignments:
                    return _collection_kind(assignments[-1], tree, func, before_lineno, depth + 1)

            # Shape two, far more common in this repository: `obj = {"key": <expr>,
            # ...}` — a dict literal, either assigned directly in this function, held
            # at module level, or built by a same-module function's `return` (the
            # `measured = measure(...)` a `_main`/`write_evidence` reads its own gate
            # from). Resolve `obj` however a bare Name would be, then read the key out
            # of whatever dict literal that resolves to, in *that* dict's own scope.
            obj_value: ast.expr | None = None
            if func is not None:
                name_assignments = _assignments_to_name(func, base_name, before_lineno)
                if name_assignments:
                    obj_value = name_assignments[-1]
            if obj_value is None:
                obj_value = _module_level_value(tree, base_name)
            if obj_value is not None:
                dict_literal, dict_func = _resolve_to_dict_literal(obj_value, tree, func)
                if dict_literal is not None:
                    value_node = _dict_value_for_key(dict_literal, key_string)
                    if value_node is not None:
                        return _collection_kind(value_node, tree, dict_func, None, depth + 1)
                return _UNKNOWN, None
            if func is not None and base_name in (
                {a.arg for a in func.args.posonlyargs}
                | {a.arg for a in func.args.args}
                | {a.arg for a in func.args.kwonlyargs}
            ):
                # `base_name` is never assigned inside `func` at all — it is one of
                # `func`'s own parameters, bound by whoever calls it
                # (`floor_breaches(measured)`'s shape). Resolved separately, in
                # *each* caller's own scope, by `_resolve_subscript_param_via_callers`.
                return _resolve_subscript_param_via_callers(
                    func, base_name, key_string, tree, depth
                )
        return _UNKNOWN, None

    return _UNKNOWN, None


def _top_level_function(
    tree: ast.Module, name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    return next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
        ),
        None,
    )


def _function_returns(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.expr]:
    return [n.value for n in ast.walk(func) if isinstance(n, ast.Return) and n.value is not None]


def _unambiguous_return(returns: list[ast.expr]) -> ast.expr | None:
    """The one return value worth following out of several.

    This repository's own gate modules commonly write `measure()` as one or more
    early bail-outs (`return _unmeasured(...)`) guarding a single substantive
    branch that builds the real result — `gate_reader_agreement.measure` returns
    four different things, three of them `_unmeasured(...)` calls for "no verifier
    at ...", "no task tree at ...", and so on. A single literal `Dict` among
    several returns is that substantive branch; two, or zero, is genuinely
    ambiguous, and this declines to guess between them.
    """
    if len(returns) == 1:
        return returns[0]
    dict_returns = [r for r in returns if isinstance(r, ast.Dict)]
    if len(dict_returns) == 1:
        return dict_returns[0]
    return None


def _resolve_to_dict_literal(
    value: ast.expr | None,
    tree: ast.Module,
    func: ast.FunctionDef | ast.AsyncFunctionDef | None,
    depth: int = 0,
) -> tuple[ast.Dict | None, ast.FunctionDef | ast.AsyncFunctionDef | None]:
    """`value` (an already-found local assignment, or `None` to fall through to a
    module-level lookup) resolved down to the `Dict` literal it ultimately holds, and
    the function whose scope that literal's *values* should be read in — the callee's,
    when `value` was a call, since a dict a function builds names its own locals."""
    if value is None or depth > 5:
        return None, None
    if isinstance(value, ast.Dict):
        return value, func
    if isinstance(value, ast.Name):
        # `return measured` where `measured = probe_constraint_survival(...)` a few
        # lines up — the callee only names its result rather than returning the call
        # (or the dict literal) directly. One more hop, in the *same* function's own
        # scope, before falling back to a module-level name.
        local = _assignments_to_name(func, value.id, None) if func is not None else []
        if local:
            return _resolve_to_dict_literal(local[-1], tree, func, depth + 1)
        return _resolve_to_dict_literal(_module_level_value(tree, value.id), tree, None, depth + 1)
    if isinstance(value, ast.IfExp):
        # `measured = measure(...) if target is None else write_evidence(...)` — try
        # the branches in order and take whichever resolves; this is reading the
        # *shape* of what gets returned, not evaluating which branch runs.
        for branch in (value.body, value.orelse):
            resolved, resolved_func = _resolve_to_dict_literal(branch, tree, func, depth + 1)
            if resolved is not None:
                return resolved, resolved_func
        return None, None
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
        callee = _top_level_function(tree, value.func.id)
        if callee is not None:
            returns = _function_returns(callee)
            chosen = _unambiguous_return(returns)
            if chosen is not None:
                # The callee might itself only delegate (`write_evidence` calling
                # `measure` and returning what it got) — recurse one more hop rather
                # than requiring the dict literal to be textually present here.
                return _resolve_to_dict_literal(chosen, tree, callee, depth + 1)
    return None, None


def _resolves_to_name(
    expr: ast.expr,
    target_name: str,
    tree: ast.Module,
    func: ast.FunctionDef | ast.AsyncFunctionDef | None,
    before_lineno: int | None,
    depth: int = 0,
) -> bool:
    """True when `expr`, traced through the same Name/Subscript/dict-literal hops
    `_collection_kind` already follows for a *population*, ultimately names the
    floor `target_name` itself.

    This is the mirror image of that tracing, needed because a floor is not always
    a bare `Compare` operand: `bulk_filter.MUST_KEEP_ROWS`'s only enforcement site
    is `measured["must_keep_rows_evaluated"] < measured["must_keep_rows_at_least"]`
    — the floor's own name appears nowhere in that `Compare`, only three lines
    above it, boxed into the dict `measured["must_keep_rows_at_least"]` reads back
    out. A sweep that only recognised `Name(id=floor)` directly on one side of a
    `Compare` could never find it, no matter how the name were spelled.
    """
    if depth > 5:
        return False
    if isinstance(expr, ast.Name):
        if expr.id == target_name:
            return True
        if func is not None:
            assignments = _assignments_to_name(func, expr.id, before_lineno)
            if assignments:
                return _resolves_to_name(
                    assignments[-1], target_name, tree, func, before_lineno, depth + 1
                )
        module_value = _module_level_value(tree, expr.id)
        if module_value is not None:
            return _resolves_to_name(module_value, target_name, tree, None, None, depth + 1)
        return False
    if isinstance(expr, ast.Subscript):
        key = _subscript_string_key(expr)
        if key is None:
            return False
        base_name, key_string = key
        obj_value: ast.expr | None = None
        if func is not None:
            name_assignments = _assignments_to_name(func, base_name, before_lineno)
            if name_assignments:
                obj_value = name_assignments[-1]
        if obj_value is None:
            obj_value = _module_level_value(tree, base_name)
        dict_literal, dict_func = _resolve_to_dict_literal(obj_value, tree, func)
        if dict_literal is not None:
            for key_node, value_node in zip(dict_literal.keys, dict_literal.values, strict=True):
                if (
                    isinstance(key_node, ast.Constant)
                    and key_node.value == key_string
                    and value_node is not None
                ):
                    return _resolves_to_name(
                        value_node, target_name, tree, dict_func, None, depth + 1
                    )
        return False
    return False


def _population_for(
    other_operand: ast.expr,
    tree: ast.Module,
    func: ast.FunctionDef | ast.AsyncFunctionDef | None,
    before_lineno: int | None,
) -> tuple[bool, int | None]:
    """`(in_scope, population)`. `in_scope` is True only if `other_operand` traces to a
    `len(...)` call, or simple `+`/`-` arithmetic on one; `population` is the concrete
    count when that reduces to a literal collection this module can count, else `None`
    for a dynamic one."""
    if (
        isinstance(other_operand, ast.Call)
        and isinstance(other_operand.func, ast.Name)
        and other_operand.func.id == "len"
        and len(other_operand.args) == 1
    ):
        kind, count = _collection_kind(other_operand.args[0], tree, func, before_lineno)
        if kind == _LITERAL:
            return True, count
        if kind == _DYNAMIC:
            return True, None
        return False, None

    if isinstance(other_operand, ast.BinOp) and isinstance(other_operand.op, (ast.Add, ast.Sub)):
        # `len(X) + N` / `len(X) - N` / `N + len(X)` —
        # `gate_reader_agreement.MINIMUM_ARRANGEMENTS_PROBED`'s own reasoning:
        # "`measure` probes `ARRANGEMENTS` *and* `UNGATED_ARRANGEMENT`, so the list
        # this is read against is `len(ARRANGEMENTS) + 1`". Traced by recursing into
        # whichever side is itself `len(...)`-derived and requiring the other side
        # to be a plain int literal — never two collections combined, which this
        # sweep has no business counting, and never accepted merely because a
        # `BinOp` sits where a bare `len(...)` used to.
        left, right = other_operand.left, other_operand.right
        left_offset = _literal_int(left)
        right_offset = _literal_int(right)
        sign = -1 if isinstance(other_operand.op, ast.Sub) else 1
        if right_offset is not None and left_offset is None:
            in_scope, population = _population_for(left, tree, func, before_lineno)
            if in_scope:
                return True, (None if population is None else population + sign * right_offset)
            return False, None
        if (
            left_offset is not None
            and right_offset is None
            and isinstance(other_operand.op, ast.Add)
        ):
            in_scope, population = _population_for(right, tree, func, before_lineno)
            if in_scope:
                return True, (None if population is None else population + left_offset)
            return False, None
        return False, None

    # Not itself a `len(...)` call — trace it (bare name or subscript) and see whether
    # it *becomes* one within a couple of hops.
    kind, count = _collection_kind(other_operand, tree, func, before_lineno)
    # `_collection_kind` on a bare Name/Subscript recurses through `len(...)` internally
    # via the Call branch above, so a result of literal/dynamic here already means the
    # traced value passed through a `len(...)` at some point *if and only if* the
    # traversal actually hit that branch. To keep the "must reach len()" rule honest
    # for the direct (non-len-wrapped) case, require the traced chain to have gone
    # through a Subscript/Name — i.e. never accept a bare literal collection compared
    # directly with no `len()` anywhere, which would be comparing a floor to a
    # container rather than to a count.
    if isinstance(other_operand, (ast.Name, ast.Subscript)):
        if kind == _LITERAL:
            return True, count
        if kind == _DYNAMIC:
            return True, None
    return False, None


def _compare_sites(
    tree: ast.Module, name: str
) -> list[tuple[ast.expr, ast.FunctionDef | ast.AsyncFunctionDef | None, int]]:
    """Every `Compare` in the module with exactly one operator where `name` is one
    side — directly, or (round 2) boxed into a dict a few lines above and read back
    out through a subscript (`_resolves_to_name`). Returns `(other_side,
    enclosing_function_or_None, lineno)` for each."""
    sites: list[tuple[ast.expr, ast.FunctionDef | ast.AsyncFunctionDef | None, int]] = []
    functions = _all_function_defs(tree)

    def enclosing(node: ast.AST) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        return _innermost_enclosing(node, functions)

    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            left, right = node.left, node.comparators[0]
            func = enclosing(node)
            if _resolves_to_name(left, name, tree, func, node.lineno):
                sites.append((right, func, node.lineno))
            elif _resolves_to_name(right, name, tree, func, node.lineno):
                sites.append((left, func, node.lineno))
    return sites


def _bind_call_arguments(
    call: ast.Call, func: ast.FunctionDef | ast.AsyncFunctionDef
) -> dict[str, ast.expr]:
    positional = list(func.args.posonlyargs) + list(func.args.args)
    mapping: dict[str, ast.expr] = {}
    for index, arg_expr in enumerate(call.args):
        if index < len(positional):
            mapping[positional[index].arg] = arg_expr
    for kw in call.keywords:
        if kw.arg is not None:
            mapping[kw.arg] = kw.value
    return mapping


def _direct_compare_in_callee(
    callee: ast.FunctionDef | ast.AsyncFunctionDef, floor_param: str, mapping: dict[str, ast.expr]
) -> ast.expr | None:
    """Inside `callee`'s own body, a `Compare` between its `floor_param` and another
    of its own parameters — mapped back to whatever expression *this* call site
    passed for that other parameter."""
    for inner in ast.walk(callee):
        if isinstance(inner, ast.Compare) and len(inner.ops) == 1:
            left, right = inner.left, inner.comparators[0]
            other_param_name: str | None = None
            if (
                isinstance(left, ast.Name)
                and left.id == floor_param
                and isinstance(right, ast.Name)
            ):
                other_param_name = right.id
            elif (
                isinstance(right, ast.Name)
                and right.id == floor_param
                and isinstance(left, ast.Name)
            ):
                other_param_name = left.id
            if other_param_name is not None and other_param_name in mapping:
                return mapping[other_param_name]
    return None


def _calls_passing(
    root: ast.AST,
    current_name: str,
    top_level_functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
) -> list[tuple[ast.Call, ast.FunctionDef | ast.AsyncFunctionDef, dict[str, ast.expr], str]]:
    """Every call anywhere under `root` to a same-module top-level function that
    passes `current_name`, unchanged, as one argument — `(call, callee, argument
    mapping, the callee's parameter name that argument binds to)` for each."""
    found: list[
        tuple[ast.Call, ast.FunctionDef | ast.AsyncFunctionDef, dict[str, ast.expr], str]
    ] = []
    for node in ast.walk(root):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        callee = top_level_functions.get(node.func.id)
        if callee is None:
            continue
        mapping = _bind_call_arguments(node, callee)
        floor_param = next(
            (
                param
                for param, expr in mapping.items()
                if isinstance(expr, ast.Name) and expr.id == current_name
            ),
            None,
        )
        if floor_param is not None:
            found.append((node, callee, mapping, floor_param))
    return found


#: Bound on delegation depth — same shape and same number as every other
#: recursive traversal in this module (`_collection_kind`, `_resolve_to_dict_
#: literal`, `_resolves_to_name`): deep enough for anything this repository's
#: own call graphs actually do, shallow enough that this stays a sweep rather
#: than a full interprocedural analysis.
_MAX_DELEGATION_DEPTH = 5


def _trace_delegation(
    callee: ast.FunctionDef | ast.AsyncFunctionDef,
    floor_param: str,
    mapping: dict[str, ast.expr],
    tree: ast.Module,
    top_level_functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    depth: int,
) -> ast.expr | None:
    """What `floor_param` (one of `callee`'s own parameters, bound by `mapping` —
    the arguments *this* call site passed) is compared against inside `callee`,
    tracing through arbitrarily many further levels of same-module delegation
    (bounded by `_MAX_DELEGATION_DEPTH`), expressed back in terms of `mapping` —
    i.e., in the original caller's own scope — however many levels deep the
    comparison actually lives.

    Round 3, F6: round 2 answered the reader's two-hop finding by writing exactly
    two hops in by hand — one `for` loop, then one more nested inside it — which
    a three-hop chain still defeats, and a fourth remedy naming a fourth hop would
    only invite a fifth. This is the closed form instead: the same one-hop lookup
    (`_direct_compare_in_callee`), called recursively, each level substituting its
    own `mapping` on the way back out. `review_reader._floor`'s real one-hop shape
    still resolves at `depth == 0` on the very first call, unchanged.
    """
    if depth > _MAX_DELEGATION_DEPTH:
        return None
    direct = _direct_compare_in_callee(callee, floor_param, mapping)
    if direct is not None:
        return direct
    for _inner_node, inner_callee, inner_mapping, inner_floor_param in _calls_passing(
        callee, floor_param, top_level_functions
    ):
        if inner_callee is callee:
            continue
        inner_other = _trace_delegation(
            inner_callee, inner_floor_param, inner_mapping, tree, top_level_functions, depth + 1
        )
        if inner_other is None:
            continue
        # `inner_other` is expressed in terms of `callee`'s own parameter names
        # whenever it names one of them directly (it was built from `mapping`s
        # belonging to calls made *inside* `callee`); substitute this level's own
        # `mapping` — the arguments the call reaching `callee` was actually
        # given — so each return from the recursion climbs back out one level,
        # however many levels the recursion went in.
        if isinstance(inner_other, ast.Name) and inner_other.id in mapping:
            inner_other = mapping[inner_other.id]
        return inner_other
    return None


def _delegated_other_operand(
    tree: ast.Module, name: str
) -> tuple[ast.expr, ast.FunctionDef | ast.AsyncFunctionDef | None, int] | None:
    """The third named blind spot: a floor passed as an argument to a same-module
    helper that does the comparison inside its own body, or delegated on through
    arbitrarily many further same-module calls before one of them does
    (`_trace_delegation`). `review_reader._floor` is the one-hop shape every
    delegated floor in this repository actually uses today."""
    top_level_functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    all_functions = _all_function_defs(tree)

    def enclosing(node: ast.AST) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        return _innermost_enclosing(node, all_functions)

    for node, callee, mapping, floor_param in _calls_passing(tree, name, top_level_functions):
        other = _trace_delegation(callee, floor_param, mapping, tree, top_level_functions, 0)
        if other is not None:
            return other, enclosing(node), node.lineno
    return None


#: This repository's own evidence-path convention, read structurally rather than
#: by name: `DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" /
#: "T24.json"` (and every `DEFAULT_..._EVIDENCE_PATH` sibling — `D8`, `S12`, …).
#: `_extract_evidence_path_literal` walks the `/`-chain of `BinOp`s a `Path`
#: built this way parses into and reads off its string segments; it never
#: imports `pathlib` semantics or evaluates anything, so a module that builds
#: its evidence path some other way is simply not recognised, not misread.
def _extract_evidence_path_literal(expr: ast.expr) -> Path | None:
    parts: list[str] = []
    node = expr
    while isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        right = node.right
        if not (isinstance(right, ast.Constant) and isinstance(right.value, str)):
            return None
        parts.append(right.value)
        node = node.left
    if (
        isinstance(node, ast.Name)
        and node.id == "_REPO_ROOT"
        and parts
        and parts[0].endswith(".json")
    ):
        parts.reverse()
        return _REPO_ROOT.joinpath(*parts)
    return None


def _resolve_evidence_path_expr(
    expr: ast.expr,
    tree: ast.Module,
    func: ast.FunctionDef | ast.AsyncFunctionDef | None,
    before_lineno: int | None,
    depth: int = 0,
) -> Path | None:
    """`expr` resolved to a literal evidence path (`_extract_evidence_path_literal`)
    through a bare Name (a module-level `DEFAULT_..._PATH` constant, or a local
    variable's own last assignment) or one branch of an `IfExp` — this
    repository's own `target = Path(argv[0]) if argv else DEFAULT_EVIDENCE_PATH`
    idiom for "the default path, unless a caller overrode it", which every
    `_main` in this repository uses before calling its own `write_evidence`."""
    if depth > 5:
        return None
    direct = _extract_evidence_path_literal(expr)
    if direct is not None:
        return direct
    if isinstance(expr, ast.Name):
        module_value = _module_level_value(tree, expr.id)
        if module_value is not None:
            resolved = _resolve_evidence_path_expr(module_value, tree, None, None, depth + 1)
            if resolved is not None:
                return resolved
        if func is not None:
            assignments = _assignments_to_name(func, expr.id, before_lineno)
            if assignments:
                return _resolve_evidence_path_expr(
                    assignments[-1], tree, func, before_lineno, depth + 1
                )
        return None
    if isinstance(expr, ast.IfExp):
        # `target = Path(argv[0]) if argv else DEFAULT_EVIDENCE_PATH` is the common
        # case: one branch is an override whose value cannot be known statically,
        # the other is the real default, and taking whichever side resolves is
        # correct. `profile_capture`'s own `default_path = DEFAULT_D8_EVIDENCE_PATH
        # if args.subject_gate else DEFAULT_EVIDENCE_PATH` is not that case: *both*
        # branches resolve, to two *different* real files, and which one is live
        # depends on a condition this sweep does not evaluate — picking either
        # would be a guess with a 50% chance of reading the wrong probe's number.
        # Refuse rather than guess when both sides resolve and disagree, the same
        # "accept only on agreement" rule `_resolve_parameter_via_callers` already
        # applies to cross-caller tracing.
        body_path = _resolve_evidence_path_expr(expr.body, tree, func, before_lineno, depth + 1)
        orelse_path = _resolve_evidence_path_expr(expr.orelse, tree, func, before_lineno, depth + 1)
        if body_path is not None and orelse_path is not None:
            return body_path if body_path == orelse_path else None
        return body_path if body_path is not None else orelse_path
    return None


def _resolve_write_evidence_path(
    call: ast.Call,
    tree: ast.Module,
    caller_func: ast.FunctionDef | ast.AsyncFunctionDef | None,
    before_lineno: int | None,
) -> Path | None:
    """When `call` invokes a same-module function, the literal evidence path this
    *particular call* writes to — this repository's `write_evidence(evidence:
    Path = DEFAULT_EVIDENCE_PATH)` shape, identified by the *default value's*
    structure (`_extract_evidence_path_literal`), never by the function's own
    name, so `write_subject_evidence`, `write_owner_evidence` and every other
    spelling this repository uses are all found the same way.

    The evidence-path parameter is resolved for *this* call site, not only from
    the callee's own default: `write_evidence(target)` — this repository's
    `--write-evidence [PATH]` idiom — passes an explicit argument for it, and
    `target` is itself `Path(argv[0]) if argv else DEFAULT_EVIDENCE_PATH` in the
    caller's own scope (`_resolve_evidence_path_expr` follows exactly that).
    Only the *unoverridden* case resolves to a literal, which is correct: a run
    given a custom path is not describing where the committed evidence lives.
    """
    if not isinstance(call.func, ast.Name):
        return None
    callee = _top_level_function(tree, call.func.id)
    if callee is None:
        return None
    args = callee.args
    positional = list(args.posonlyargs) + list(args.args)
    defaults = list(args.defaults)
    offset = len(positional) - len(defaults)
    default_by_param: dict[str, ast.expr] = {
        positional[index].arg: defaults[index - offset] for index in range(offset, len(positional))
    }
    for kwarg, kwdefault in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        if kwdefault is not None:
            default_by_param[kwarg.arg] = kwdefault
    evidence_param = next(
        (
            param
            for param, default in default_by_param.items()
            if _resolve_evidence_path_expr(default, tree, None, None) is not None
        ),
        None,
    )
    if evidence_param is None:
        return None
    mapping = _bind_call_arguments(call, callee)
    if evidence_param in mapping:
        return _resolve_evidence_path_expr(
            mapping[evidence_param], tree, caller_func, before_lineno
        )
    return _resolve_evidence_path_expr(default_by_param[evidence_param], tree, None, None)


def _evidence_calls_for(
    name: str,
    tree: ast.Module,
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    before_lineno: int | None,
    depth: int = 0,
) -> list[tuple[ast.Call, ast.FunctionDef | ast.AsyncFunctionDef, int | None]]:
    """Every call this repository's own evidence-writing idiom could resolve
    `name` (a `measured`-shaped local) back to, each paired with the function
    scope and line cutoff it should be resolved in.

    Two shapes, both real: a direct local assignment (`measured = write_evidence
    (path)`, or the `measure() if args.check else write_evidence(path)`
    ternary), and `lifecycle.MINIMUM_SCENARIOS`'s own shape — `measured` is not
    assigned in this function at all, it is `_s5_report`'s own *parameter*,
    bound by whoever calls it (`_s5_report(s5_measured)`, with `s5_measured`
    itself assigned in `_main`'s scope a few lines above). Followed only when
    `func` has exactly **one** call site in the module: with more than one, which
    caller's evidence file is the right one to read is not this sweep's to
    guess, the same "decline rather than pick" rule `_resolve_parameter_via_
    callers` already applies to cross-caller tracing.
    """
    if depth > 5:
        return []
    assignments = _assignments_to_name(func, name, before_lineno)
    if assignments:
        rhs = assignments[-1]
        if isinstance(rhs, ast.Call):
            return [(rhs, func, before_lineno)]
        if isinstance(rhs, ast.IfExp):
            # `measured = measure() if args.check else write_evidence(path)` —
            # this repository's own `--check`-vs-write idiom. Both branches name
            # the same eventual evidence file; try whichever one resolves.
            return [
                (n, func, before_lineno) for n in (rhs.body, rhs.orelse) if isinstance(n, ast.Call)
            ]
        return []
    param_names = (
        {a.arg for a in func.args.posonlyargs}
        | {a.arg for a in func.args.args}
        | {a.arg for a in func.args.kwonlyargs}
    )
    if name not in param_names:
        return []
    calls_to_func = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == func.name
    ]
    if len(calls_to_func) != 1:
        return []
    call = calls_to_func[0]
    mapping = _bind_call_arguments(call, func)
    arg_expr = mapping.get(name)
    if arg_expr is None:
        return []
    all_functions = _all_function_defs(tree)
    caller_func = _innermost_enclosing(call, all_functions)
    if caller_func is None:
        return []
    if isinstance(arg_expr, ast.Call):
        return [(arg_expr, caller_func, call.lineno)]
    if isinstance(arg_expr, ast.Name):
        return _evidence_calls_for(arg_expr.id, tree, caller_func, call.lineno, depth + 1)
    return []


def _committed_evidence_population(
    other_operand: ast.expr,
    tree: ast.Module,
    func: ast.FunctionDef | ast.AsyncFunctionDef | None,
    before_lineno: int | None,
) -> int | None:
    """The real, already-measured population a *dynamic* floor guards — not
    computed by running anything, read from this repository's own committed
    `status/evidence/*.json`, which `make evidence` regenerates from the exact
    same scripted probe the floor's comparison site reads.

    This is the closed form of the round-2 reader's own suggestion: "dynamic"
    was never a population that cannot be counted, only one this repository does
    not enumerate as an in-source collection — a scripted probe's own `checks`/
    `asks`/`turns` tally is a real number, and every one of this task's touched
    floors already has it committed a few lines away from where the floor is
    read (`measured["checks_run"] < MINIMUM_CHECKS` beside `write_evidence`
    writing exactly that dict, unmodified, to `DEFAULT_EVIDENCE_PATH`). Reading
    it turns "carries a comment that is not obviously false" into "the same
    arithmetic every literal-population floor already gets" — no comment, zero
    slack or otherwise, can clear a real margin any longer.

    Requires `other_operand` to be a direct `name["key"]` subscript (this
    repository's own `measured["..."]` idiom); a floor read some other way is
    simply not resolved here, not misread — the caller falls back to the
    weaker, comment-only check for anything this cannot pin down.
    """
    if not isinstance(other_operand, ast.Subscript) or func is None:
        return None
    key = _subscript_string_key(other_operand)
    if key is None:
        return None
    base_name, key_string = key
    calls = _evidence_calls_for(base_name, tree, func, before_lineno)
    for call, call_func, call_before_lineno in calls:
        path = _resolve_write_evidence_path(call, tree, call_func, call_before_lineno)
        if path is None or not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        value = data.get(key_string)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _margin_finding(
    module_stem: str, name: str, lineno: int, literal_value: int, population: int, comment: str
) -> FloorFinding | None:
    """The one arithmetic rule this whole module enforces, extracted so a
    committed-evidence-backed dynamic population (round 3) is checked by
    *exactly* the same logic as a counted, in-repo collection — never a second,
    looser rule for floors that merely arrived at a real number by a different
    route."""
    margin = population - literal_value
    if margin <= 0:
        # `margin < 0` (the floor already exceeds its recorded population) is
        # deliberately treated identically to `margin == 0`: a floor already
        # above what it guards already refuses every deletion, and needs no
        # written argument (`test_a_floor_already_breaching_its_population_
        # needs_no_argument`) — this holds regardless of whether the
        # population is real or (R4-1) an understated evidence value, because
        # this module cannot tell the two apart from source, and forcing a
        # finding here would flag the same "already stricter than it has to
        # be" shape this module has always accepted as safe. See
        # `MINIMUM_FLOORS_ARITHMETICALLY_CHECKED`'s own comment (round 5) for
        # what this means for its "a wrong value visibly breaches" claim.
        return None

    # Past this point margin is strictly positive, so a comment claiming "zero
    # slack" is already false regardless of what number sits beside it — the
    # margin computed a moment ago already refutes it.
    if _ZERO_SLACK_CLAIM_RE.search(_normalize_comment_text(comment)):
        return FloorFinding(
            module=module_stem,
            name=name,
            lineno=lineno,
            reason="stale_margin_claim",
            detail=(
                f"{name} is {literal_value}, population is {population} (margin {margin}), "
                "but its comment claims 'zero slack' — the keyword match alone "
                "(`raised`, `slack`) would still clear this"
            ),
        )

    # Round 4 (F2): the two other idioms this repository uses to argue a
    # *positive* margin in writing each state a number in a fixed role, and
    # each can go stale exactly like a "zero slack" claim can — a second reader
    # measured `MINIMUM_FLOORS_SWEPT`'s own "Committed at 64, three points of
    # slack" clearing unchanged at floor `1` (margin 66, comment still true by
    # `_MARGIN_ARGUED_RE`'s keyword match alone), and the same escape on
    # `robots.FIXTURES_AT_LEAST` and `salary_recovery.MINIMUM_WORDING_CASES`.
    # These two are checked against the WHOLE comment, deliberately not scoped
    # to the last paragraph the way the keyword fallback below now is: every
    # real instance of either idiom in this repository already sits in the
    # final paragraph next to the declaration, so widening costs nothing, and
    # narrowing here would just be a second copy of the same restriction.
    claimed_value = _claimed_current_value(comment)
    if claimed_value is not None:
        if claimed_value != literal_value:
            return FloorFinding(
                module=module_stem,
                name=name,
                lineno=lineno,
                reason="stale_margin_claim",
                detail=(
                    f"{name} is {literal_value}, but its comment claims it was "
                    f"'committed at {claimed_value}' — the value the comment argues for and "
                    "the value the code now declares have drifted apart"
                ),
            )
        return None

    claimed_margin = _claimed_margin_size(comment)
    if claimed_margin is not None:
        if claimed_margin != margin:
            return FloorFinding(
                module=module_stem,
                name=name,
                lineno=lineno,
                reason="stale_margin_claim",
                detail=(
                    f"{name} is {literal_value}, population is {population} (margin {margin}), "
                    f"but its comment claims {claimed_margin} point(s) of slack/margin — the "
                    "number the comment argues for and the margin actually computed have "
                    "drifted apart"
                ),
            )
        return None

    # Round 5 (R4-5): round 3's F2 was never fully closed. Neither numeric
    # idiom fired above, so this floor's compliance came down to
    # `_MARGIN_ARGUED_RE` matching *somewhere* in the whole comment — and a
    # second reader deleted exactly the sentence carrying this self-floor's
    # own "Committed at 73, three points of slack" claim and watched the gate
    # stay GREEN at floor `1`, because `margin`/`slack` remain in an *earlier*
    # paragraph of the same accreted, multi-round comment, in prose that is
    # *about* this module's own mechanism ("the one branch that never computes
    # a margin", "is this margin real") — never a claim about this floor's own
    # gap. Retiring the keyword fallback entirely (tried here first) breaks a
    # real, intentional shape this module supports on purpose
    # (`test_a_margin_argued_in_writing_is_not_flagged`,
    # `second_reader.STDLIB_DISAGREEMENTS_AT_LEAST`'s "this one keeps its
    # slack ... [no number stated]" for a floor pinned to a third party's own
    # behaviour) — a floor is allowed to argue its margin in free prose with no
    # falsifiable number at all, and that argument is not required to sit next
    # to a number this check could otherwise verify. What is not legitimate is
    # a keyword surviving *because it is describing something else entirely*,
    # several paragraphs of unrelated history away from the declaration. So
    # the fallback is scoped to `_last_comment_paragraph`: the block of
    # comment lines immediately above the declaration, after the last blank
    # `#`/`#:` separator line — the same place every real "Committed at
    # N"/"N points of slack"/"N, zero slack" claim in this repository already
    # lives, and where a genuine free-form argument belongs too, since it is
    # an argument *for this floor*, not a chronicle of every round that has
    # touched this file.
    if _MARGIN_ARGUED_RE.search(_normalize_comment_text(_last_comment_paragraph(comment))):
        return None

    return FloorFinding(
        module=module_stem,
        name=name,
        lineno=lineno,
        reason="silent_margin",
        detail=(
            f"{name} is {literal_value}, population is {population} "
            f"(margin {margin}) — the first {margin} deletion(s) breach nothing, "
            "and no comment above the declaration argues the gap"
        ),
    )


def _resolved_population_for_site(
    other: ast.expr,
    tree: ast.Module,
    func: ast.FunctionDef | ast.AsyncFunctionDef | None,
    site_lineno: int,
) -> tuple[bool, int | None]:
    """The full `(in_scope, population)` one comparison site resolves to —
    trying a literal in-repo count first and this repository's own
    committed-evidence idiom second, the same two routes `_classify_floor`
    tries for whichever single site it ends up using. Factored out so a floor
    with more than one comparison site (R4-3, round 5) can ask every site the
    identical question before deciding whether they agree, rather than
    resolving only the one site that gets used."""
    in_scope, population = _population_for(other, tree, func, site_lineno)
    if in_scope and population is not None:
        return True, population
    pinned_population = _committed_evidence_population(other, tree, func, site_lineno)
    if pinned_population is not None:
        return True, pinned_population
    return in_scope, None


def _classify_floor(
    module: _ModuleInfo, name: str, lineno: int, value_expr: ast.expr
) -> tuple[FloorFinding | None, DynamicFloor | None, EvidencePinnedFloor | None, bool, bool]:
    """Returns `(finding_if_any, dynamic_record_if_any, pinned_record_if_any,
    was_in_scope, reached_arithmetic)`. `reached_arithmetic` is true exactly
    when a real, concrete population was found — literal or evidence-pinned —
    and `_margin_finding` was actually run against it, whether or not it found
    a violation (F1: the count `MINIMUM_FLOORS_ARITHMETICALLY_CHECKED` asserts
    against)."""
    literal_value = _resolved_floor_literal(value_expr, module.tree)

    if literal_value is None:
        # Rule (a): not even a literal. Always in scope, always a violation — a bound
        # derived from the population it bounds moves with it and can never fire.
        return (
            FloorFinding(
                module=module.stem,
                name=name,
                lineno=lineno,
                reason="derived_from_its_own_population",
                detail=(
                    f"{name} is declared as {ast.dump(value_expr, annotate_fields=False)!r}, "
                    "not a literal — if its comparison site measures the same collection, "
                    "the check is `len(X) < len(X)` and can never fire"
                ),
            ),
            None,
            None,
            True,
            False,
        )

    site = _compare_sites(module.tree, name)
    other: ast.expr | None = None
    func: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    site_lineno = lineno
    if len(site) == 1:
        other, func, site_lineno = site[0]
    elif len(site) > 1:
        # Round 5 (R4-3): more than one comparison site is not "pick the
        # first" — the same refuse-rather-than-guess rule this module already
        # applies elsewhere (`_resolve_parameter_via_callers`: only when every
        # call site binds the parameter the same way; `_resolve_evidence_path_
        # expr`: refuse rather than guess when both sides resolve and
        # disagree; `_evidence_calls_for`: followed only when `func` has
        # exactly one call site). A second reader constructed one floor with
        # two comparison sites — a small sanity check and the real
        # measurement — and found the verdict (population 3 vs 12, finding
        # present vs absent) decided purely by which function `ast.walk`
        # reached first, since `site[0]` took whichever that was. Two of this
        # repository's own real floors (`extraction.
        # MIN_EVALUATION_LABELS_PER_DIMENSION`, `interview.
        # MINIMUM_TRAIT_EPISODES`/`MINIMUM_TRAIT_OCCASIONS`) had the identical
        # exposure: whether they landed `dynamic` or `bounds_read_and_out_of_
        # scope` already depended on which of their own sites came first.
        # Resolved independently, every site must agree — including on
        # whether the floor is in scope at all — before any of them is used;
        # agreement is not "picking", since any one of them would answer the
        # same, and disagreement is declined rather than guessed at.
        resolved = [_resolved_population_for_site(o, module.tree, f, ln) for o, f, ln in site]
        if all(r == resolved[0] for r in resolved):
            other, func, site_lineno = site[0]
        # else: declined — `other` stays `None`, never judged on the first.
    else:
        delegated = _delegated_other_operand(module.tree, name)
        if delegated is not None:
            other, func, site_lineno = delegated

    if other is None:
        return None, None, None, False, False

    in_scope, population = _population_for(other, module.tree, func, site_lineno)

    if in_scope and population is not None:
        # A literal, in-repo collection this sweep counted directly — the
        # original, most-trusted route, left untouched by round 4's reordering
        # below: nothing overrides a fresh AST count with a possibly-stale
        # evidence file for a floor this sweep can already count exactly.
        comment = _comment_block_above(module.lines, lineno)
        finding = _margin_finding(module.stem, name, lineno, literal_value, population, comment)
        return finding, None, None, True, True

    comment = _comment_block_above(module.lines, lineno)

    # Round 3's closed form, tried whenever `_population_for` did *not* already
    # resolve a literal count — either because it classified `other` `dynamic`
    # (a scripted probe's own running tally), or because it could not classify
    # `other` at all (round 4, F4). The second case is the reader's root-cause
    # finding: `_collection_kind` has no branch for `ast.Attribute` at all, so
    # `measured["packages_checked"] < MINIMUM_PACKAGES` — whose right side is
    # `len(report.packages)` a few lines above — was ruled `out_of_scope`
    # before evidence-pinning ever got a turn, for ten real floors
    # (`connector_contract.MINIMUM_PACKAGES`, `salary_recovery.
    # MINIMUM_CORPUS_ADS`, `dedup.MINIMUM_PAIRS`, `connectors.MINIMUM_PROBES`,
    # `step_runtime.MINIMUM_PROBES`, `session.MINIMUM_PROBES`, `cv_store.
    # MINIMUM_FIELDS_MEASURED`, `identity.MINIMUM_PROBES`, `sourcing_scope_
    # review.MINIMUM_STANDING`, `sourcing_strategy.MINIMUM_TRIGGERS`).
    #
    # This is *not* the relaxation round 3's own docstring tried and reverted
    # ("what this did not attempt"): that one taught `_collection_kind` to
    # accept a wider set of `len(...)` arguments as a countable population,
    # which could not be told apart from a per-item scalar check. This never
    # asks what `other` denotes at all — it only asks whether `other` is this
    # repository's own `measured["key"]` idiom, and if so, reads the real
    # number `make evidence` already wrote for that exact key. A scalar-check
    # constant never uses that idiom (it compares a parameter or a `.strip()`
    # result directly), so nothing about this widens what a *bare* `len(...)`
    # argument is allowed to be.
    pinned_population = _committed_evidence_population(other, module.tree, func, site_lineno)
    if pinned_population is not None:
        finding = _margin_finding(
            module.stem, name, lineno, literal_value, pinned_population, comment
        )
        pinned = (
            None
            if finding is not None
            else EvidencePinnedFloor(
                module=module.stem, name=name, lineno=lineno, population=pinned_population
            )
        )
        return finding, None, pinned, True, True

    if not in_scope:
        return None, None, None, False, False

    # No committed evidence resolves this one — a genuinely unpinnable
    # population (a third party's own behaviour, a corpus scan, two dynamic
    # quantities combined) or simply a shape this sweep does not yet trace to
    # a file. No single "first deletion" this repository could make, so this
    # is checked only for "carries some explanation", plus the one
    # falsifiable claim this repository's own idiom makes about one ("N,
    # zero slack") going stale (`_zero_slack_claim_contradicts`).
    if not comment.strip():
        return (
            FloorFinding(
                module=module.stem,
                name=name,
                lineno=lineno,
                reason="undocumented",
                detail=f"{name} guards a population this repository does not itself "
                "enumerate, and carries no comment explaining the chosen value",
            ),
            None,
            None,
            True,
            False,
        )
    if _zero_slack_claim_contradicts(comment, literal_value):
        return (
            FloorFinding(
                module=module.stem,
                name=name,
                lineno=lineno,
                reason="stale_margin_claim",
                detail=(
                    f"{name} is {literal_value}, but its comment claims 'zero slack' "
                    "against a different number — the value the comment argued for "
                    "and the value the code now declares have drifted apart"
                ),
            ),
            None,
            None,
            True,
            False,
        )
    return None, DynamicFloor(module=module.stem, name=name, lineno=lineno), None, True, False


def measure(src_dir: Path = _SRC_DIR) -> dict[str, Any]:
    """T159's gate: floors that do not refuse the first deletion of their population."""
    findings: list[FloorFinding] = []
    dynamic: list[DynamicFloor] = []
    pinned: list[EvidencePinnedFloor] = []
    swept = 0
    arithmetically_checked = 0
    excluded: list[str] = []
    self_floor: tuple[_ModuleInfo, str, int] | None = None
    arithmetic_self_floor: tuple[_ModuleInfo, str, int] | None = None

    for module in _module_infos(src_dir):
        # Round 1 excluded this module from its own sweep by identity — the reader's
        # fourth finding: "the gate exempts itself", the one committed floor this
        # rule structurally could not classify. Round 2 answered it by removing the
        # identity exemption, but `MINIMUM_FLOORS_SWEPT`'s own population
        # (`floors_swept`) only exists once this whole loop has finished — it is a
        # census T100 deliberately does *not* commit to evidence (a census key
        # committed raw would drift on every task PR, T100/T150's own finding), so
        # no evidence file could ever back it and round 2's own classification put
        # it in `dynamic`, unpinned — the reader's third/fourth finding: exemption
        # by classification rather than by identity. Round 3 does not classify it
        # at all: deferred here, checked directly below against this run's own
        # true `swept`, which is the one number that could ever answer it honestly.
        # Matched by *identity* (this exact file), never by the name "floor_sweep"
        # — a fixture module that merely happens to be *named* `floor_sweep.py`
        # (this module's own test suite writes one, to prove round 2's fix holds
        # regardless of filename) is not this module, and must be swept exactly
        # like any other, `MINIMUM_FLOORS_SWEPT`-shaped constant included.
        is_this_module = module.path.resolve() == _THIS_FILE
        for name, lineno, value_expr in _module_constant_candidates(module.tree):
            if is_this_module and name == "MINIMUM_FLOORS_SWEPT":
                self_floor = (module, name, lineno)
                swept += 1
                arithmetically_checked += 1
                continue
            if is_this_module and name == "MINIMUM_FLOORS_ARITHMETICALLY_CHECKED":
                # Round 4 (F1): the sweep's own second denominator, deferred and
                # checked the identical way `MINIMUM_FLOORS_SWEPT` already is —
                # matched by *identity*, never by name, and against a total this
                # run's own loop has not finished computing yet.
                arithmetic_self_floor = (module, name, lineno)
                swept += 1
                arithmetically_checked += 1
                continue
            finding, dynamic_record, pinned_record, in_scope, reached_arithmetic = _classify_floor(
                module, name, lineno, value_expr
            )
            if not in_scope:
                excluded.append(f"{module.stem}.{name}")
                continue
            swept += 1
            if reached_arithmetic:
                arithmetically_checked += 1
            if finding is not None:
                findings.append(finding)
            if dynamic_record is not None:
                dynamic.append(dynamic_record)
            if pinned_record is not None:
                pinned.append(pinned_record)

    if self_floor is not None:
        self_module, self_name, self_lineno = self_floor
        self_comment = _comment_block_above(self_module.lines, self_lineno)
        self_finding = _margin_finding(
            self_module.stem, self_name, self_lineno, MINIMUM_FLOORS_SWEPT, swept, self_comment
        )
        if self_finding is not None:
            findings.append(self_finding)
        else:
            pinned.append(
                EvidencePinnedFloor(
                    module=self_module.stem, name=self_name, lineno=self_lineno, population=swept
                )
            )

    if arithmetic_self_floor is not None:
        arith_module, arith_name, arith_lineno = arithmetic_self_floor
        arith_comment = _comment_block_above(arith_module.lines, arith_lineno)
        arith_finding = _margin_finding(
            arith_module.stem,
            arith_name,
            arith_lineno,
            MINIMUM_FLOORS_ARITHMETICALLY_CHECKED,
            arithmetically_checked,
            arith_comment,
        )
        if arith_finding is not None:
            findings.append(arith_finding)
        else:
            pinned.append(
                EvidencePinnedFloor(
                    module=arith_module.stem,
                    name=arith_name,
                    lineno=arith_lineno,
                    population=arithmetically_checked,
                )
            )

    return {
        "floors_that_do_not_refuse_the_first_deletion": len(findings),
        "findings": [f.as_dict() for f in sorted(findings, key=lambda f: (f.module, f.name))],
        "floors_swept": swept,
        "arithmetically_checked": arithmetically_checked,
        "dynamic_population_floors": [
            d.as_dict() for d in sorted(dynamic, key=lambda d: (d.module, d.name))
        ],
        "evidence_pinned_floors": [
            p.as_dict() for p in sorted(pinned, key=lambda p: (p.module, p.name))
        ],
        "bounds_read_and_out_of_scope": sorted(excluded),
        "gate_status": "measured",
    }


#: The denominator's floor, in the `naming.MINIMUM_SCANNED` style (T100): derived
#: from the sweep's own result it would shrink with any floor the sweep stops
#: finding, which is this task's own defect committed inside this task's gate.
#:
#: **Round 3 changed how this floor is *checked*, not only what it is checked
#: against.** Round 2 classified this floor `dynamic` like any other name-shaped
#: candidate, which put it in the one branch that never computes a margin — the
#: reader's third/fourth finding, restated: self-exemption had moved from
#: identity to classification. It is no longer classified at all: `measure()`
#: defers it, and once this run's own `swept` is known, checks it directly
#: against `MINIMUM_FLOORS_SWEPT` by the same `_margin_finding` arithmetic every
#: other floor gets — the one number that could ever answer "is this margin
#: real" honestly, since no committed evidence file backs a census T100
#: deliberately keeps uncommitted.
#:
#: Measured at 67 floors in scope after round 3's further-broadened discovery
#: (a leading underscore admitted into `_CONSTANT_NAME_RE`, `.split()`/
#: `.splitlines()` recognised as a real population, `AnnAssign` targets read
#: everywhere `Assign` already was, a floor's own value resolved through a
#: `BinOp` of two literals or an alias to a sibling constant, and delegation
#: traced to arbitrary depth rather than exactly two hops) — round 2's own count
#: was 57. Round 4 adds one more candidate to this exact loop
#: (`MINIMUM_FLOORS_ARITHMETICALLY_CHECKED`, its own deferred self-floor,
#: counted here the same way this one counts itself) and, separately, F4's
#: reordering below moves seven floors from `bounds_read_and_out_of_scope`
#: into `evidence_pinned_floors` — a reclassification, not new discovery, so it
#: raises `arithmetically_checked` without changing what counts as "in scope"
#: here. Measured at 76 after round 4.
#:
#: **Round 5 (R4-3) moves it to 73, and it is committed at exactly that —
#: zero slack, not a narrowed margin.** `_compare_sites` used to pick
#: `site[0]` whenever a floor had more than one comparison site, so three
#: floors this repository actually owns (`extraction.
#: MIN_EVALUATION_LABELS_PER_DIMENSION`, `interview.MINIMUM_TRAIT_EPISODES`/
#: `MINIMUM_TRAIT_OCCASIONS`) landed `dynamic` or `bounds_read_and_out_of_
#: scope` depending purely on which of their own multiple, genuinely
#: differently-shaped comparison sites (a list length at one site, a
#: per-dimension running tally at another) `ast.walk` reached first — the
#: same order-dependence the reader's constructed fixture demonstrated for an
#: arithmetic verdict, one level up, deciding whether a floor is swept at
#: all. Declining rather than picking correctly moves those three out of
#: scope, and `floors_swept` drops by exactly that many: 76 → 73. Zero slack
#: is not a weaker guarantee than three points of it — this module has always
#: treated `margin == 0` as fully compliant (immediate breach on the first
#: deletion) — it is what happens when a round's fix legitimately narrows the
#: population, and the committed floor already sat at the new true count.
#: Per-module detail is deliberately not repeated further than the paragraph
#: above: a hand-typed roll call of "already compliant" modules is exactly
#: the prose a second reader has twice now shown cannot be trusted.
#: `status/evidence/T159.json`'s own `dynamic_population_floors`,
#: `evidence_pinned_floors` and `bounds_read_and_out_of_scope` are regenerated
#: every run and are the only account of *which* floors are which that this
#: module stands behind.
MINIMUM_FLOORS_SWEPT = 73


#: Round 4's own denominator (F1): *how many* of the floors above actually reach
#: an arithmetic check, as opposed to sitting in `dynamic_population_floors`
#: with only a comment behind them. Before this floor existed, the arithmetic
#: branch had none of its own: a second reader deleted every committed
#: `status/evidence/*.json` file and watched 18 of 19 evidence-pinned floors
#: fall back to `dynamic` — `pinned` 19 → 1, `swept` unchanged at 67, no breach,
#: exit 0 — and, worse, a *wrong* committed value in one of those files
#: certifies a floor as compliant against a population eighteen below the real
#: one, with nothing to say so. `floors_swept` could not have caught either: it
#: counts a `dynamic` floor and an arithmetically-checked one identically.
#:
#: Checked exactly like `MINIMUM_FLOORS_SWEPT` — matched by identity, deferred
#: until `measure()`'s own loop has finished, checked by the same
#: `_margin_finding` arithmetic — so *deleting* the evidence files now visibly
#: breaches this floor instead of silently moving a number nothing asserts
#: against.
#:
#: **Round 5 (R4-1): "or shipping a wrong one" above was false, and this is the
#: correction rather than a fifth exemption.** A second reader edited
#: `status/evidence/T34.json`'s `probes_run` 13 → 1 → 0 against
#: `step_runtime.MINIMUM_PROBES = 13` and watched `arithmetically_checked` stay
#: 39 and the gate stay GREEN at every value — an *understated* wrong value
#: still resolves through `_committed_evidence_population`, still reaches
#: `_margin_finding`, still counts here, and `margin = population - literal_
#: value` comes out zero or negative, which this module has always treated as
#: compliant (the same rule `test_a_floor_already_breaching_its_population_
#: needs_no_argument` pins: a floor already at or above what it guards already
#: refuses every deletion and needs no argument). Making a negative margin a
#: finding was tried and reverted here — it would also flag every floor
#: *legitimately* set stricter than its own population for an unrelated
#: reason, which is a real, deliberate, tested shape, not a defect. So this is
#: the "delete the claim" half of the report's own two offered fixes: an
#: *overstated* wrong value (which pushes `margin` positive) is still caught
#: below, by the identical `_margin_finding` arithmetic every other floor
#: gets; an *understated* one is indistinguishable, from source, from a floor
#: correctly sized to a shrunken-but-real population, and this module does not
#: guess which. What full protection against evidence-file corruption would
#: need — an independent check that the committed number matches what
#: `make evidence` would regenerate — is `make evidence`'s own drift check,
#: not something an AST sweep over `src/integral` can add. Measured 30 before
#: round 4 (11
#: literal-population, 18 evidence-pinned, 1 deferred self-floor: `swept`
#: unchanged, but `arithmetically_checked` is the number that answers "how many
#: of those 67 reach an arithmetic check" — the exact question the reader who
#: found F1 asked, and `floors_swept` alone could never answer, since it counts
#: a `dynamic` floor and an arithmetically-checked one identically). Round 4's
#: F4 reordering (below) pulls seven more of the 76 in-scope floors from
#: `dynamic`/`bounds_read_and_out_of_scope` into `evidence_pinned_floors` —
#: `connectors.MINIMUM_PROBES`, `dedup.MINIMUM_PAIRS`, `identity.MINIMUM_PROBES`,
#: `session.MINIMUM_PROBES`, `sourcing_scope_review.MINIMUM_STANDING`,
#: `sourcing_strategy.MINIMUM_TRIGGERS`, `step_runtime.MINIMUM_PROBES` — plus 2
#: for this floor and its own self-check, and 1 more for
#: `MINIMUM_FLOORS_SWEPT`'s self-check newly counting itself here too: 39
#: today. Three more of the report's original ten
#: (`connector_contract.MINIMUM_PACKAGES`, `cv_store.MINIMUM_FIELDS_MEASURED`,
#: `salary_recovery.MINIMUM_CORPUS_ADS`) are real violations fixed by hand in
#: this same round but stay outside this count and outside the sweep's reach —
#: each resolves its evidence file through a shape genuinely beyond what
#: `_committed_evidence_population` traces (a full helper function gating on
#: CLI flags, an `argparse`-wrapped path, a cross-module call) — refusing to
#: guess through those is this module's own rule, not a gap F4 left open.
#: Committed at 36, three points of slack. Never the count of the day (T100):
#: raise it deliberately, the same discipline as `MINIMUM_FLOORS_SWEPT`, when a
#: round changes how many floors this sweep can actually check by arithmetic.
MINIMUM_FLOORS_ARITHMETICALLY_CHECKED = 36


def record(measured: dict[str, Any]) -> dict[str, Any]:
    """What is committed, out of what was measured — the two censuses (`floors_swept`,
    `arithmetically_checked`) each swapped for their own floor (T100): a raw count
    committed directly can drift silently when two branches move it for unrelated
    reasons and merge with no conflict (CLAUDE.md, "Two branches can write the same
    value for different reasons")."""
    committed = {
        key: value
        for key, value in measured.items()
        if key not in ("floors_swept", "arithmetically_checked")
    }
    committed["floors_swept_at_least"] = MINIMUM_FLOORS_SWEPT
    committed["floors_arithmetically_checked_at_least"] = MINIMUM_FLOORS_ARITHMETICALLY_CHECKED
    return committed


#: Not declared here. `EVIDENCE_SOURCES` (T150) is for a census specifically
#: sensitive to the two tree mutations that check compares against — a Markdown
#: file added, a task archived — and `naming`/`arsenal_source`/`repo_gate` are the
#: only modules whose count moves under either. `floors_swept` counts constants in
#: `src/integral/*.py`; neither mutation touches that tree, so registering here
#: would only ever report `stable` trivially, and — the concrete cost, met while
#: writing this module — `repo_gate` cannot resolve a registrant it does not
#: already import, which every module *not* declaring one already avoids.


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH, src_dir: Path | None = None
) -> dict[str, Any]:
    """Measure and record `status/evidence/T159.json`; return what was measured.

    Refuses to write only when the sweep itself examined too little to trust — a
    breach of `floors_swept`'s floor. A nonzero finding count is still written: the
    whole point of this gate is to be able to fail with the finding visible.

    `src_dir` defaults to `None`, resolved to the module-level `_SRC_DIR` *inside*
    the call rather than baked into the signature — a default parameter value is
    bound once, at import time, so a test that monkeypatches `_SRC_DIR` (to point
    `_main` at a throwaway tree) would otherwise have no effect on this function's
    own default at all.
    """
    measured = measure(_SRC_DIR if src_dir is None else src_dir)
    if measured["floors_swept"] < MINIMUM_FLOORS_SWEPT:
        return measured
    if measured["arithmetically_checked"] < MINIMUM_FLOORS_ARITHMETICALLY_CHECKED:
        return measured
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(record(measured), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return measured


def _main(argv: list[str] | None = None) -> int:
    """Write T159's evidence.

    **Exit 1, not 3** on a breach or a finding — T115's finding about this
    repository's other floors, applied here from the day this one was written: `make
    evidence` prints 3 as "unmeasured (recorded)" and carries on, which makes a floor
    that exits 3 decoration rather than a gate.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    evidence = Path(args[0]) if args else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(evidence)
    print(json.dumps(measured, ensure_ascii=False))

    if measured["floors_swept"] < MINIMUM_FLOORS_SWEPT:
        print(
            f"only {measured['floors_swept']} floor(s) swept (floor {MINIMUM_FLOORS_SWEPT}) — "
            "a clean zero over a shrunken sweep is not a measurement",
            file=sys.stderr,
        )
        return 1

    if measured["arithmetically_checked"] < MINIMUM_FLOORS_ARITHMETICALLY_CHECKED:
        print(
            f"only {measured['arithmetically_checked']} floor(s) reached an arithmetic "
            f"check (floor {MINIMUM_FLOORS_ARITHMETICALLY_CHECKED}) — a deleted committed "
            "evidence file can shrink this without changing floors_swept at all (round 5, "
            "R4-1: a *wrong-but-present* value does not shrink this count — it still "
            "resolves and still reaches arithmetic — only deletion does)",
            file=sys.stderr,
        )
        return 1

    for finding in measured["findings"]:
        print(
            f"✗ {finding['module']}.{finding['name']} ({finding['reason']}): {finding['detail']}",
            file=sys.stderr,
        )
    return 1 if measured["findings"] else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
