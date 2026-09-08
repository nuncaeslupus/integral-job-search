# Pre-PR adversarial review — `t-9d41c7f5` (T120, second robots reader), v4

## Findings

```
BLOCKER | tests/test_connector_policy.py (124 changed lines) — not in the case file, not on disk, not readable anywhere
  Trigger: the packet is truncated ("4278 lines, showing the first 4000"). The
    diff ends inside status/evidence/T120.json; tests/test_connector_policy.py,
    status/plan.md, status/evidence/T125.json and status/evidence/T85.json carry
    no hunk. The change is not pushed to any branch, so `git diff` and
    `git show` cannot recover them either.
  Why: this is not a formality. src/integral/connector_policy.py:565 changes
    `_classify`'s DEFAULT reader from CPython's parser to the new one
    (`ask = READERS[DEFAULT_SECOND_READER] if reader is None else reader`, with
    DEFAULT_SECOND_READER = second_reader.NAME at :474). I reconstructed the
    change in a worktree at the stated base and ran the *base* version of that
    test file against it: 9 tests fail, and they are exactly T116's load-bearing
    ones —
      test_a_first_match_parser_on_a_permissively_opening_file_is_not_competent
      test_the_same_rules_in_the_other_order_change_the_second_readers_competence
      test_refusing_a_path_the_rfc_allows_is_not_counted_as_competence
      test_a_wildcard_and_anchored_rule_still_yields_a_negative_control
      test_every_competence_fixture_classifies_as_the_rfc_requires
      test_a_file_that_refuses_a_path_is_never_told_no_control_is_possible
      test_a_second_reader_that_allows_one_refused_path_cannot_carry_an_agreement
      test_the_honest_count_of_incompetent_second_readers_is_reported_under_its_own_name
      test_single_parser_names_which_of_its_two_findings_each_row_is
    Every one of them calls `cp._classify(fixture.robots_txt, fixture.agent)`
    with no reader argument (tests/test_connector_policy.py:241, 304, 330, 333,
    352, 367, 382, 393, 635, 697, 722 at base). The PR HAD to rewrite them. There
    are two rewrites that make them green and they are opposites: pinning
    `READERS["urllib.robotparser"]` explicitly, which preserves T116's finding, or
    flipping the expected verdicts to COMPETENT to match the new default, which
    erases it — the T116 fixture set would then assert that a first-match parser
    is competent on a permissively-opening file, which is the exact claim T116
    exists to refuse. I cannot tell which was done, and the brief's rule is that
    being unable to determine whether something is correct means BLOCK.
  Not a code finding, and cheap to clear: re-emit the packet with the full diff
    (or push the branch) and this blocker goes away on inspection of ~140 lines.
```

```
RISK | src/integral/second_reader.py:402-430 and :453 — the multi-spelling
      widening can turn a DISALLOW into an ALLOW, which the docstring says it cannot
  Trigger:
      User-agent: *
      Disallow: /out?url=
      Allow: /*http://
    against `/out?url=http://evil.com`. `second_reader.allows(...)` returns True.
    Delete the `Allow:` line and it returns False. (Measured.)
  Why: `spellings()` offers the target encoded, as-written, and decoded, and
    `allows()` matches a rule if ANY spelling matches. The docstring at :418-420
    argues this is safe — "Comparing against more spellings can only make more
    rules apply — it never makes a `Disallow` stop matching — which is the
    direction to be wrong in". The premise is true and the conclusion does not
    follow: an ALLOW rule that reaches the query through a wildcard gains the
    same extra spellings, and under §2.2.2's most-octets precedence (with the
    allow winning an equal-length tie, :457) it outranks a Disallow that does
    match. Here both patterns are 9 octets, so the spurious allow wins the tie.
    Under the strict reading the module itself takes — §2.2.2's example table
    makes the path-to-match the percent-encoded form — `Allow: /*http://` should
    not match that request at all. Net effect is fail-open, in the component
    whose whole job is to be able to refuse.
    No case in `second_reader_cases.py` or in `REGRESSION_CASES` has an *Allow*
    reaching the query through a wildcard; the two cases added for this area
    (`a_rule_reaching_the_query_through_a_wildcard`,
    `the_same_rule_against_an_already_encoded_request`) are both Disallows, so
    the gate is green over it. Either narrow the widening to disallow rules, or
    add the mirror case and take the verdict deliberately.
```

```
RISK | src/integral/second_reader_cases.py — case 37 has no fail-open mirror,
      and a one-sided case-folding mutation survives the whole table
  Trigger: mutate src/integral/second_reader.py:449 to lowercase the request
    target before matching (`target = target.lower()`). `measure()` still reports
    `second_reader_verdicts_misread: 0` and `gate_status: measured` over all 55
    cases. (Measured, on a copy — nothing written to the repo.) The reader then
    answers ALLOW for `/Private/notes` under `Disallow: /Private/`.
  Why: `path_matching_is_case_sensitive` (case 37) is
    `Disallow: /Private/` against `/private/notes`, expecting ALLOW — the
    fail-closed half only. Its fail-open mirror (an uppercase rule that must
    still refuse an uppercase path) is not in the table, so the gate number that
    `status/evidence/T120.json` commits, and that `verify-gates` adjudicates
    from here on, cannot see the direction that matters. The table applies the
    paired-mirror discipline elsewhere and says so (4/5, 6/7, 17/18, 29/30); this
    is the pair it did not make. A mutation folding BOTH sides is caught by case
    37, and I verified that — this is specifically the one-sided case.
```

```
RISK | src/integral/second_reader.py:501-524, status/evidence/T120.json —
      a fail-open in the PRIMARY matcher is proved, pinned, and left with no owner
  Trigger: `repo_matcher_verdicts_against_the_rfc: 1` on
    `reserved_octets_stay_encoded_in_query`. §2.2.2's own example table gives
    `/foo/bar?baz=https://foo.bar` the path-to-match
    `/foo/bar?baz=https%3A%2F%2Ffoo.bar`, so the rule refuses it;
    `robots.allows_text` returns True. `integral.robots` is the matcher CLAUDE.md
    tells every session to adjudicate a real board with.
  Why: recording it is right and the pinning (`REPO_MATCHER_DISAGREEMENTS`,
    `test_the_same_table_is_run_against_the_repo_matcher_and_the_gap_is_pinned`)
    is better than a count. But I grepped `arsenal/tasks/` and `status/plan.md`
    for `reserved_octets` and `_CHUNK_SAFE` and found nothing: no task file, no
    plan row, no `D-N`. The pin has no expiry, so the honest outcome is a
    permanent green test asserting that a known fail-open is still there. This
    repository's own rule is that an accepted finding is committed before merge,
    not read and waved through — that is satisfied for the second reader and not
    for this. Queue it (a task file is one commit) rather than shipping it as a
    constant.
```

```
NOTE | src/integral/second_reader.py:238-247 — rules under a `User-agent:` line
      with an empty value are silently dropped, fail-open
  Trigger: `User-agent: foo\nDisallow: /a\nUser-agent:\nDisallow: /b\n`.
    `parse()` returns one group (`foo` → `/a`); `/b` is allowed for every agent,
    ours included. (Measured.)
  Why: the empty value leaves `agents` empty after the group close at :233-237,
    so the following rules hit the `if not agents: continue` at :242 — the branch
    the docstring (:199-203) documents for rules appearing *before any* UA line.
    Reaching it this way is undocumented and undecided. The line is malformed
    under §2.2's ABNF so any handling is defensible, but dropping a `Disallow` is
    the fail-open one, and this module's stated bias is the other way (compare the
    BOM treatment at :209-214, which is the same class of problem handled the
    safe way).
```

```
NOTE | src/integral/second_reader.py:141 — hex-case normalisation is not carried
      by the gate metric
  Trigger: drop `.upper()` from `out.append(octet if octet in _UNRESERVED else
    "%" + escape.upper())`. `second_reader_verdicts_misread` stays 0 and
    `gate_status` stays `measured`. (Measured.)
  Why: it is caught, by
    `test_percent_canonicalisation_resolves_only_the_unreserved_set`, so this is
    not a hole — but `status/evidence/T120.json` is what `verify-gates`
    adjudicates forever, and the committed number does not cover `%2f` vs `%2F`
    equivalence. Worth a line in the table if a case is cheap.
```

```
NOTE | docs/rfc9309-second-reader-cases.md, Conventions section — off-by-one
      pointer into its own index
  Trigger: the Conventions bullet says "Cases 24–26 are built so the two
    readings are *tested*: 24 makes them agree, 25 and 26 make them diverge".
    The index numbers them 23 (`wildcard_specificity_readings_agree`), 24 and 25
    (the two `..._diverge` rows); 26 is `pct_unreserved_encoded_in_rule`.
  Why: `src/integral/second_reader_cases.py:39` states it correctly ("cases
    23-25"), so this is the doc's prose only. Flagged because the numbers are how
    a later reader finds the derivation of a contested verdict, not as style.
```

```
NOTE | the stated intent's quoted evidence does not match the committed evidence
  Trigger: the task payload quotes
    `robots_adjudications_without_a_competent_second_reader: 19 (of 20 rows)`.
    `status/evidence/T116.json` at the base commit holds **20**, over 22 rows
    (19 `single_parser` + 1 `no_negative_control_possible` + 2
    `two_parsers_agreed`). The diff moves it 20 → 19.
  Why: no bearing on the change — the intent plainly describes this diff and I
    reviewed against it — but the number it cites as the problem statement was
    already stale, and the PR's own delta (one board re-adjudicated, one row
    moved) is what makes 20 → 19 correct.
```

```
NOTE | no injected reviewer instructions in either data block
  I scanned the intent and the diff for a forged `…7797181629990ac1bb0ca3d4`
  marker, for text addressing the reviewer, and for "approved / ignore the check
  / clear this" phrasings. There are none. The docstrings argue for their
  decisions at length, which is this repository's house style, but nothing in
  them instructs a reader to skip anything.
```

## What the change does deliver

Stated against the intent's four items, all verified by running, not by reading:

1. **A spec-derived second reader.** `src/integral/second_reader.py` implements
   §2.2.1 group selection (case-folded equality, no prefix rule — T102's
   settlement is intact and `select()` combines duplicate groups and falls back
   to `*` only when no group names us), §2.2.2 most-octets precedence with the
   allow winning ties, and §2.2.3 `*`/`$`. The non-regex matcher (`matches()`,
   :316-375) is the right call and is defended by an actual timing test
   (`test_a_hostile_pattern_cannot_hang_the_matcher`, 400 wildcards against a
   5000-octet target, under 1s) — robots.txt is third-party input.
2. **An independent fixture table.** This is the claim most worth attacking and
   it holds up. I wrote a script that re-parses all 49 cases out of
   `docs/rfc9309-second-reader-cases.md` and compares `id`, `robots_txt`,
   `agent`, `path`, `expected`, `direction` and `confidence` against
   `second_reader_cases.CASES`: 49/49 present, same order, **zero mismatches**.
   The transcription is faithful, so the "written by a session that had not read
   `src/`" claim is at least not falsified by a quiet edit to an `expected`. The
   six implementer-derived cases are kept in a separate tuple in the *other*
   module and labelled, which is the honest arrangement.
3. **The competence check stays.** `_classify` keeps its four verdicts and is now
   dispatched per row through `READERS`, so a pre-T120 row is still measured
   against `urllib.robotparser` — the reader it actually consulted. The seven new
   `_CompetenceFixture` rows include three where the new reader must *not*
   improve on the stdlib (bare `Disallow:`, equivalent rules, another agent's
   group), which is the check that stops competence being bought with false
   refusals. `RobotsAdjudication.problems()` refuses a `two_parsers_agreed`
   naming an unknown reader outright rather than defaulting — the right
   direction.
4. **One board re-adjudicated.** I ran `_classify` over the committed
   foorilla.com file: `competent`, 22 controls tried, 22 RFC-refused, 22 refused
   by the new reader, **0 false allows and 0 false refusals** — the ledger's
   "22 of 22" is accurate, not rhetorical. The stdlib allows both control paths
   (`/hiring/companies/`, `/hiring/jobs/x/apply/`), so the standing change is
   real. T116 20 → 19 follows arithmetically.

Gate and evidence: `uv run python -m integral.second_reader` exits 0 with
`second_reader_verdicts_misread: 0`, `gate_status: measured`. I regenerated
`status/evidence/T120.json` from the code and it is **byte-identical** to the
(partial) hunk in the packet, 25 lines, so that file is confirmed despite the
truncation. `make evidence` regenerates exactly T116/T125/T85 with the deltas the
file list implies (T125 467→471, T85 100→101), so those three unread hunks are
confirmed by reproduction. `make lint` is clean (ruff format, ruff check, mypy
strict, 218 files). `make verify-gates` passes: 157 terminal tasks, 156 gates
asserted. `integral.repo_gate --list-evidence-modules` discovers `second_reader`,
so the new evidence is inside the `make evidence` run rather than beside it.
The full suite minus the unreadable file: **2876 passed, 10 skipped**.
`tests/test_second_reader.py`: 23 passed, and the gate block's three named tests
are all collected.

**Mutation round.** I did not take the gate's zero on trust. I built 16 mutants of
`second_reader.py` in a throwaway copy (never in the repo, and never a
mutate-restore cycle, so the `.pyc` trap CLAUDE.md documents cannot apply) and
re-ran `measure()` on each. Killed: tie-break inverted (1), first-match-in-file-
order (8), interior `*` requiring one character (1), unanchored substring match
(1), always using the `*` group (5), no comment stripping (1), decoding every
escape rather than the unreserved set (2), no query-data encoding (2), product-
token prefix rule reintroduced (1), case-folding both sides (1). Survivors are
the two written up as RISK/NOTE above (one-sided target case-folding; hex
upper-casing). That is a table with real teeth — and, on the evidence of the
kills, `first_match_order` alone takes 8 cases, which is precisely the failure
T116 measured in the stdlib.

## What I actually checked

I fetched the packet branch, extracted the diff, created a detached worktree at
the stated base `f2633eac8346` under `/tmp`, applied every hunk the packet
carries (all but the truncated tail), and worked there; I removed the worktree
afterwards and `git status` in the repository is clean — nothing was written into
the tree under review. Beyond the diff I opened
`src/integral/second_reader.py` and `tests/test_second_reader.py` in full, all
1115 lines of `docs/rfc9309-second-reader-cases.md` mechanically (the comparison
script above) plus its header and index by eye, the headers and dataclass of
`second_reader_cases.py`, the whole `connector_policy.py` and
`connector_procedure.py` diffs, the `robots-adjudications.yaml` diff, and the
T116/T125/T85 evidence deltas. I grepped for every caller of `_classify` and
`second_reader_allows` across `src/` and `tests/` (that is how the blocker
surfaced), for `second_reader`/`T120` in `Makefile`, `scripts/`, `tools/`, and
for a follow-up task on the `integral.robots` disagreement in `arsenal/tasks/`
and `status/plan.md`. I could not read the 278 truncated diff lines covering
`tests/test_connector_policy.py`, `status/plan.md`, `status/evidence/T125.json`
and `status/evidence/T85.json`; I reproduced the last three from the code and
they match, and `status/plan.md`'s single changed line is consistent with ticking
T120's row at `status/plan.md:390` (D-27) but I did not see it.

The engineering here is strong and the independence claim survives the only test
that can falsify it from outside. The block is the packet, not the code — with
one substantive question behind it that only those 124 lines can answer.

VERDICT: BLOCK — `tests/test_connector_policy.py`'s 124 changed lines are absent from the truncated packet and unrecoverable, and they are exactly where the change to `_classify`'s default reader could have quietly inverted T116's competence fixtures (9 of that file's tests fail against the new code at base); everything I could read is sound, so re-emitting the full diff should clear this, with the query-spelling fail-open (RISK 1), the missing case-sensitivity mirror (RISK 2) and the unqueued `integral.robots` fail-open (RISK 3) deserving an answer either way.
