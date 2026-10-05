"""T165: the committed polarity adjudications - one verdict and its reason for every bound
the floor census does not simply read off the AST.

`ADJUDICATIONS` maps `module.NAME` to `(verdict, reason)`, verdict one of `floor`,
`ceiling`, `neither`.

It exists because `floor_sweep._bound_polarity` places a comparison only by its operator
and the syntactic place its truth is consumed, and that cannot see what a guard's body
*means*. A name it reads as undetermined, or one it decides and a reader overrules, is
judged here by reading the code, with the reason. T159 ruled 133 names out of scope and
never judged them; each is a key here, and `floor_sweep` reports an out-of-scope name with
no entry. Every reason names the comparison (or the absence of one) that decides it, so a
reader can re-derive the verdict.
"""

from __future__ import annotations

ADJUDICATIONS: dict[str, tuple[str, str]] = {
    "annotation.EGRESS_SAMPLE": (
        "neither",
        (
            "A default argument value (`def f(x=NAME)`), never compared in this "
            "module: a parameter's default is a setting, not a bound the code "
            "checks a population against."
        ),
    ),
    "annotation.MIN_IDENTIFYING_LENGTH": (
        "floor",
        (
            "`len(value) >= MIN_IDENTIFYING_LENGTH` makes a value count as "
            "identifying only from that length up: a minimum length. The AST rule "
            "votes it a ceiling because the guard's true branch does work; the "
            "register overrules it."
        ),
    ),
    "approval.MINIMUM_DISCLOSURE_PROBES": (
        "floor",
        (
            "Listed in a `(measured key, floor)` table whose consumer reports a "
            "failure when `measured[key] < floor`; a minimum on a count of probes "
            "or comparisons, breached by deleting one."
        ),
    ),
    "approval.MINIMUM_INTACT_SEAM_CHECKS": (
        "floor",
        (
            "A denominator floor: the gate refuses (exits non-zero or reports "
            "`unmeasured`) when the measured count falls below it, so deleting a "
            "member of the guarded population is what breaches it. Out of the T159 "
            "census only because its comparand is resolved at runtime or from a key "
            "this sweep does not trace."
        ),
    ),
    "approval.MINIMUM_INTACT_SEAM_STATES": (
        "floor",
        (
            "A denominator floor: the gate refuses (exits non-zero or reports "
            "`unmeasured`) when the measured count falls below it, so deleting a "
            "member of the guarded population is what breaches it. Out of the T159 "
            "census only because its comparand is resolved at runtime or from a key "
            "this sweep does not trace."
        ),
    ),
    "approval.MINIMUM_MANIFEST_DISCLOSURES_COMPARED": (
        "floor",
        (
            "Listed in a `(measured key, floor)` table whose consumer reports a "
            "failure when `measured[key] < floor`; a minimum on a count of probes "
            "or comparisons, breached by deleting one."
        ),
    ),
    "approval.MINIMUM_PARAPHRASE_CHECKS": (
        "floor",
        (
            "Listed in a `(measured key, floor)` table whose consumer reports a "
            "failure when `measured[key] < floor`; a minimum on a count of probes "
            "or comparisons, breached by deleting one."
        ),
    ),
    "approval.MINIMUM_PARAPHRASE_STATES": (
        "floor",
        (
            "Listed in a `(measured key, floor)` table whose consumer reports a "
            "failure when `measured[key] < floor`; a minimum on a count of probes "
            "or comparisons, breached by deleting one."
        ),
    ),
    "approval.MINIMUM_PROBES": (
        "floor",
        (
            "Listed in a `(measured key, floor)` table whose consumer reports a "
            "failure when `measured[key] < floor`; a minimum on a count of probes "
            "or comparisons, breached by deleting one."
        ),
    ),
    "approval.MINIMUM_RETRACTED_APPROVALS_EVALUATED": (
        "floor",
        (
            "Listed in a `(measured key, floor)` table whose consumer reports a "
            "failure when `measured[key] < floor`; a minimum on a count of probes "
            "or comparisons, breached by deleting one."
        ),
    ),
    "approval.MINIMUM_RETRACTION_PROBES": (
        "floor",
        (
            "Listed in a `(measured key, floor)` table whose consumer reports a "
            "failure when `measured[key] < floor`; a minimum on a count of probes "
            "or comparisons, breached by deleting one."
        ),
    ),
    "approval.SCHEMA_VERSION": (
        "neither",
        (
            "A format version compared for equality (`!=`) or written into records: "
            "it identifies a format, it bounds no count."
        ),
    ),
    "approval._RECORDED_SENDS": (
        "ceiling",
        (
            "`position < _RECORDED_SENDS` takes only the first few prepared "
            "applications through the send boundary: a limit on how many are "
            "processed, breached by adding more, not by deleting. The AST rule "
            "votes floor because the guard's true branch does work; the register "
            "overrules it."
        ),
    ),
    "approval._SHINGLE": (
        "ceiling",
        (
            "`len(words) <= _SHINGLE` bounds the length of a match window from "
            "above: a text of at most this many words is compared whole, a longer "
            "one is cut into windows of exactly this size. Adding words never "
            "breaches it; it is a size, not a count of anything a deletion could "
            "shrink."
        ),
    ),
    "bodyless_post.MINIMUM_PACKAGES": (
        "floor",
        (
            "A denominator floor: the gate refuses (exits non-zero or reports "
            "`unmeasured`) when the measured count falls below it, so deleting a "
            "member of the guarded population is what breaches it. Out of the T159 "
            "census only because its comparand is resolved at runtime or from a key "
            "this sweep does not trace."
        ),
    ),
    "bulk_filter.PROBE_BATCH": (
        "neither",
        (
            "A default argument value (`def f(x=NAME)`), never compared in this "
            "module: a parameter's default is a setting, not a bound the code "
            "checks a population against."
        ),
    ),
    "calibration.TWENTY": (
        "neither",
        (
            "A default argument value (`def f(x=NAME)`), never compared in this "
            "module: a parameter's default is a setting, not a bound the code "
            "checks a population against."
        ),
    ),
    "connector_contract.MINIMUM_PACKAGES": (
        "floor",
        (
            "A denominator floor: the gate refuses (exits non-zero or reports "
            "`unmeasured`) when the measured count falls below it, so deleting a "
            "member of the guarded population is what breaches it. Out of the T159 "
            "census only because its comparand is resolved at runtime or from a key "
            "this sweep does not trace."
        ),
    ),
    "connector_contract._RUN_WINDOW": (
        "ceiling",
        (
            "`_RUN_WINDOW >= _RUN_WINDOW_CEILING` guards it from above, and it is "
            "the width of a text window read around a match: a size limit, not a "
            "count of anything."
        ),
    ),
    "connector_contract._RUN_WINDOW_CEILING": (
        "ceiling",
        (
            "An upper limit: the code refuses, truncates or stops once the quantity "
            "exceeds it (`n > LIMIT` / `n >= LIMIT` / `<= LIMIT` kept whole), so it "
            "is breached by adding, never by deleting."
        ),
    ),
    "connector_exchange.LEAK_NEEDLE_MINIMUM": (
        "floor",
        (
            "A string is a leak needle only from this length up (`len(s) >= "
            "LEAK_NEEDLE_MINIMUM`, and the same count as the regex lower "
            "repetition): a minimum length."
        ),
    ),
    "connector_health.MAX_PROBE_ATTEMPTS": (
        "ceiling",
        (
            "The number of times a `for _ in range(...)` retries before giving up: "
            "an upper limit on attempts."
        ),
    ),
    "connector_policy.ADJUDICATIONS_AT_LEAST": (
        "floor",
        (
            "`floored = checked >= ADJUDICATIONS_AT_LEAST and len(packages) >= "
            "PACKAGES_AT_LEAST` is the measurement's own `satisfied` flag: a lower "
            "bound on adjudications and on packages scanned."
        ),
    ),
    "connector_salary_audit.MINIMUM_DISTINCT_SALARY_VERDICTS_READ": (
        "floor",
        (
            "Carries a `population=` margin marker and is recorded as the committed "
            "`*_at_least` floor of a measured count: a lower bound, with the margin "
            "stated."
        ),
    ),
    "connector_salary_audit.MINIMUM_PACKAGES_MEASURED": (
        "floor",
        (
            "Carries a `population=` margin marker and is recorded as the committed "
            "`*_at_least` floor of a measured count: a lower bound, with the margin "
            "stated."
        ),
    ),
    "connector_salary_audit._MIN_REASON": (
        "floor",
        (
            "`len(reason) >= _MIN_REASON` is the acceptance test for a recorded "
            "reason: a minimum length."
        ),
    ),
    "connector_salary_audit._WINDOW": (
        "neither",
        (
            "The width of a text window or slice (`text[max(0, i - WIDTH):i]`, a "
            "shingle size, an excerpt cut): a size parameter of an algorithm, "
            "compared against nothing."
        ),
    ),
    "connector_transport.MINIMUM_CREDENTIAL_CASES": (
        "floor",
        (
            "A denominator floor: the gate refuses (exits non-zero or reports "
            "`unmeasured`) when the measured count falls below it, so deleting a "
            "member of the guarded population is what breaches it. Out of the T159 "
            "census only because its comparand is resolved at runtime or from a key "
            "this sweep does not trace."
        ),
    ),
    "connector_transport.MINIMUM_GET_PACKAGES": (
        "floor",
        (
            "A denominator floor: the gate refuses (exits non-zero or reports "
            "`unmeasured`) when the measured count falls below it, so deleting a "
            "member of the guarded population is what breaches it. Out of the T159 "
            "census only because its comparand is resolved at runtime or from a key "
            "this sweep does not trace."
        ),
    ),
    "connector_transport.MINIMUM_LEDGER_ENTRIES": (
        "floor",
        (
            "A denominator floor: the gate refuses (exits non-zero or reports "
            "`unmeasured`) when the measured count falls below it, so deleting a "
            "member of the guarded population is what breaches it. Out of the T159 "
            "census only because its comparand is resolved at runtime or from a key "
            "this sweep does not trace."
        ),
    ),
    "connector_transport.MINIMUM_RECORD_KEYS_COMPARED": (
        "floor",
        (
            "A denominator floor: the gate refuses (exits non-zero or reports "
            "`unmeasured`) when the measured count falls below it, so deleting a "
            "member of the guarded population is what breaches it. Out of the T159 "
            "census only because its comparand is resolved at runtime or from a key "
            "this sweep does not trace."
        ),
    ),
    "connectors.DEFAULT_STALE_AFTER_DAYS": (
        "neither",
        (
            "A default argument value (`def f(x=NAME)`), never compared in this "
            "module: a parameter's default is a setting, not a bound the code "
            "checks a population against."
        ),
    ),
    "connectors.MAX_EMPLOYERS": (
        "ceiling",
        (
            "An upper limit: the code refuses, truncates or stops once the quantity "
            "exceeds it (`n > LIMIT` / `n >= LIMIT` / `<= LIMIT` kept whole), so it "
            "is breached by adding, never by deleting."
        ),
    ),
    "corpus.MIN_ADS_PER_FAMILY": (
        "floor",
        (
            "A job family counts only with at least this many adverts (`n >= "
            "MIN_ADS_PER_FAMILY` qualifies, `n < ...` is listed as below the "
            "floor): a minimum count per family."
        ),
    ),
    "corpus_scope.MINIMUM_CORPUS_ROWS": (
        "floor",
        (
            "A denominator floor: the gate refuses (exits non-zero or reports "
            "`unmeasured`) when the measured count falls below it, so deleting a "
            "member of the guarded population is what breaches it. Out of the T159 "
            "census only because its comparand is resolved at runtime or from a key "
            "this sweep does not trace."
        ),
    ),
    "corpus_scope.MINIMUM_EVALUATION_POOL": (
        "floor",
        (
            "A denominator floor: the gate refuses (exits non-zero or reports "
            "`unmeasured`) when the measured count falls below it, so deleting a "
            "member of the guarded population is what breaches it. Out of the T159 "
            "census only because its comparand is resolved at runtime or from a key "
            "this sweep does not trace."
        ),
    ),
    "corpus_scope.MINIMUM_SERVING_MODULES": (
        "floor",
        (
            "A denominator floor: the gate refuses (exits non-zero or reports "
            "`unmeasured`) when the measured count falls below it, so deleting a "
            "member of the guarded population is what breaches it. Out of the T159 "
            "census only because its comparand is resolved at runtime or from a key "
            "this sweep does not trace."
        ),
    ),
    "corpus_scope.MINIMUM_STIMULUS_POOL": (
        "floor",
        (
            "A denominator floor: the gate refuses (exits non-zero or reports "
            "`unmeasured`) when the measured count falls below it, so deleting a "
            "member of the guarded population is what breaches it. Out of the T159 "
            "census only because its comparand is resolved at runtime or from a key "
            "this sweep does not trace."
        ),
    ),
    "cue_audit.MINIMUM_CASES": (
        "floor",
        (
            "Recorded as the committed `*_at_least` floor of a measured count (or "
            "paired with its measured key in a floor table); every consumer refuses "
            "a count below it, so deleting a member of the population breaches it."
        ),
    ),
    "cue_audit.MINIMUM_CITABLE_FIELDS_CITED": (
        "floor",
        (
            "Recorded as the committed `*_at_least` floor of a measured count (or "
            "paired with its measured key in a floor table); every consumer refuses "
            "a count below it, so deleting a member of the population breaches it."
        ),
    ),
    "cue_audit.MINIMUM_CITATIONS_CHECKED": (
        "floor",
        (
            "Recorded as the committed `*_at_least` floor of a measured count (or "
            "paired with its measured key in a floor table); every consumer refuses "
            "a count below it, so deleting a member of the population breaches it."
        ),
    ),
    "cue_audit.MINIMUM_FAIL_OPEN_CASES": (
        "floor",
        (
            "Recorded as the committed `*_at_least` floor of a measured count (or "
            "paired with its measured key in a floor table); every consumer refuses "
            "a count below it, so deleting a member of the population breaches it."
        ),
    ),
    "cue_audit.MINIMUM_MECHANISM_PINNED_CASES": (
        "floor",
        (
            "Recorded as the committed `*_at_least` floor of a measured count (or "
            "paired with its measured key in a floor table); every consumer refuses "
            "a count below it, so deleting a member of the population breaches it."
        ),
    ),
    "cv_store.MINIMUM_FIELDS_MEASURED": (
        "floor",
        (
            "A denominator floor: the gate refuses (exits non-zero or reports "
            "`unmeasured`) when the measured count falls below it, so deleting a "
            "member of the guarded population is what breaches it. Out of the T159 "
            "census only because its comparand is resolved at runtime or from a key "
            "this sweep does not trace."
        ),
    ),
    "cv_store.SCHEMA_VERSION": (
        "neither",
        (
            "A format version compared for equality (`!=`) or written into records: "
            "it identifies a format, it bounds no count."
        ),
    ),
    "cv_store._DOC_ID_WIDTH": (
        "neither",
        ("A zero-padding width in an id format string (`:0{WIDTH}d`): formatting, not a bound."),
    ),
    "cv_store._MAX_DOC_ID_RESERVE_ATTEMPTS": (
        "ceiling",
        (
            "The number of times a `for _ in range(...)` retries before giving up: "
            "an upper limit on attempts."
        ),
    ),
    "decline.DECLINES_BEFORE_STEP_SILENCE": (
        "neither",
        (
            "Declared (value 1) and never read: documents that one decline silences "
            "a step; it is not compared anywhere."
        ),
    ),
    "decline.DECLINES_BEFORE_TOTAL_SILENCE": (
        "ceiling",
        (
            "An upper limit: the code refuses, truncates or stops once the quantity "
            "exceeds it (`n > LIMIT` / `n >= LIMIT` / `<= LIMIT` kept whole), so it "
            "is breached by adding, never by deleting."
        ),
    ),
    "dedup.SHINGLE_SIZE": (
        "neither",
        (
            "The width of a text window or slice (`text[max(0, i - WIDTH):i]`, a "
            "shingle size, an excerpt cut): a size parameter of an algorithm, "
            "compared against nothing."
        ),
    ),
    "elicit_extract.MAX_ANSWER_CHARS": (
        "ceiling",
        (
            "An upper limit: the code refuses, truncates or stops once the quantity "
            "exceeds it (`n > LIMIT` / `n >= LIMIT` / `<= LIMIT` kept whole), so it "
            "is breached by adding, never by deleting."
        ),
    ),
    "elicit_extract.MIN_ANSWER_CHARS": (
        "floor",
        (
            "`len(stripped) < MIN_ANSWER_CHARS` rejects the answer as implausibly "
            "short: a minimum length, breached by deleting characters."
        ),
    ),
    "elicit_extract.NEGATION_WINDOW_CHARS": (
        "neither",
        (
            "The width of a text window or slice (`text[max(0, i - WIDTH):i]`, a "
            "shingle size, an excerpt cut): a size parameter of an algorithm, "
            "compared against nothing."
        ),
    ),
    "exclusion_live_round._CONTROL_CAP": (
        "ceiling",
        (
            "A slice length (`[:_CONTROL_CAP]`, `[:_PER_EXCLUSION]`) that caps how "
            "many adverts are served: an upper limit on a selection."
        ),
    ),
    "exclusion_live_round._PER_EXCLUSION": (
        "ceiling",
        (
            "A slice length (`[:_CONTROL_CAP]`, `[:_PER_EXCLUSION]`) that caps how "
            "many adverts are served: an upper limit on a selection."
        ),
    ),
    "extraction.MIN_EVALUATION_LABELS_PER_DIMENSION": (
        "floor",
        (
            "A dimension is measurable only with at least this many negation labels "
            "(`len(negated_labels) >= ...`); fewer leaves it unmeasured."
        ),
    ),
    "extraction._NEGATION_WINDOW": (
        "neither",
        (
            "The width of a text window or slice (`text[max(0, i - WIDTH):i]`, a "
            "shingle size, an excerpt cut): a size parameter of an algorithm, "
            "compared against nothing."
        ),
    ),
    "floor_sweep.MINIMUM_BOUNDS_READ_FOR_POLARITY": (
        "floor",
        (
            "`bounds_read >= MINIMUM_BOUNDS_READ_FOR_POLARITY` is the polarity "
            "gate's own `measured` flag: a lower bound on the bounds it read, "
            "breached by the census losing one. Out of the T159 census only "
            "because `bounds_read` is a sum of two lengths, which that sweep "
            "does not combine."
        ),
    ),
    "floor_sweep.MINIMUM_PROSE_MUTATION_SCENARIOS": (
        "floor",
        (
            "A denominator floor: the gate refuses (exits non-zero or reports "
            "`unmeasured`) when the measured count falls below it, so deleting a "
            "member of the guarded population is what breaches it. Out of the T159 "
            "census only because its comparand is resolved at runtime or from a key "
            "this sweep does not trace."
        ),
    ),
    "floor_sweep._MAX_DELEGATION_DEPTH": (
        "ceiling",
        (
            "An upper limit: the code refuses, truncates or stops once the quantity "
            "exceeds it (`n > LIMIT` / `n >= LIMIT` / `<= LIMIT` kept whole), so it "
            "is breached by adding, never by deleting."
        ),
    ),
    "freshness.DEFAULT_ELAPSED_DAYS": (
        "neither",
        (
            "A default argument value (`def f(x=NAME)`), never compared in this "
            "module: a parameter's default is a setting, not a bound the code "
            "checks a population against."
        ),
    ),
    "gate_reader_agreement.MINIMUM_GATES_COMPARED": (
        "floor",
        (
            "A denominator floor: the gate refuses (exits non-zero or reports "
            "`unmeasured`) when the measured count falls below it, so deleting a "
            "member of the guarded population is what breaches it. Out of the T159 "
            "census only because its comparand is resolved at runtime or from a key "
            "this sweep does not trace."
        ),
    ),
    "generate.GENERATION_CAP": (
        "ceiling",
        (
            "`version > GENERATION_CAP` raises: the number of regeneration rounds "
            "an offer may have is capped, and it is breached by adding a version, "
            "not by deleting one."
        ),
    ),
    "generate.SCHEMA_VERSION": (
        "neither",
        (
            "A format version compared for equality (`!=`) or written into records: "
            "it identifies a format, it bounds no count."
        ),
    ),
    "interview.MAX_EXTRA_EPISODE_ATTEMPTS": (
        "ceiling",
        (
            "`n > MAX_EXTRA_EPISODE_ATTEMPTS` skips the question: the attempt "
            "counter running past it is the breach, so it is breached by addition."
        ),
    ),
    "interview.MINIMUM_TRAIT_EPISODES": (
        "floor",
        (
            "A trait dimension is not settled until it has at least this many "
            "episodes / occasions (`< MINIMUM...` keeps asking): a minimum on "
            "evidence gathered, breached by having fewer."
        ),
    ),
    "interview.MINIMUM_TRAIT_OCCASIONS": (
        "floor",
        (
            "A trait dimension is not settled until it has at least this many "
            "episodes / occasions (`< MINIMUM...` keeps asking): a minimum on "
            "evidence gathered, breached by having fewer."
        ),
    ),
    "interview_direction.MINIMUM_NON_SOFTWARE_ARTEFACT_FIELDS": (
        "floor",
        (
            "Only ever read as `assert len(found) >= MINIMUM_...` in the test that "
            "pins the population (tests/), never in src: a lower bound on a counted "
            "population."
        ),
    ),
    "interview_direction.MINIMUM_OPEN_TALK_STEPS": (
        "floor",
        (
            "Only ever read as `assert len(found) >= MINIMUM_...` in the test that "
            "pins the population (tests/), never in src: a lower bound on a counted "
            "population."
        ),
    ),
    "interview_log.SCHEMA_VERSION": (
        "neither",
        (
            "A format version compared for equality (`!=`) or written into records: "
            "it identifies a format, it bounds no count."
        ),
    ),
    "interview_log._ID_WIDTH": (
        "neither",
        ("A zero-padding width in an id format string (`:0{WIDTH}d`): formatting, not a bound."),
    ),
    "language_set.MINIMUM_LANGUAGE_DECLARATIONS": (
        "floor",
        (
            "`resolved >= MINIMUM_LANGUAGE_DECLARATIONS` is the measurement's "
            "`measured` flag: a minimum on declarations resolved."
        ),
    ),
    "lesson_triage.MAX_TEXT_BYTES": (
        "ceiling",
        (
            "An upper limit: the code refuses, truncates or stops once the quantity "
            "exceeds it (`n > LIMIT` / `n >= LIMIT` / `<= LIMIT` kept whole), so it "
            "is breached by adding, never by deleting."
        ),
    ),
    "lesson_triage.MIN_REASON_WORDS": (
        "floor",
        (
            "`len(tokens(reason)) < MIN_REASON_WORDS` raises: a reason must say why "
            "in at least this many words."
        ),
    ),
    "lesson_triage.MIN_RULE_WORDS": (
        "floor",
        (
            "`len(tokens(rule)) < MIN_RULE_WORDS` raises, and `size >= "
            "MIN_RULE_WORDS` gates the shingle comparison on a rule being at least "
            "that long: a minimum word count both times. The AST rule votes the "
            "second site as a ceiling because the guard's true branch does work; "
            "the register overrules it."
        ),
    ),
    "lesson_triage.SHINGLE": (
        "neither",
        (
            "The width of a text window or slice (`text[max(0, i - WIDTH):i]`, a "
            "shingle size, an excerpt cut): a size parameter of an algorithm, "
            "compared against nothing."
        ),
    ),
    "lifecycle.PURGE_HORIZON_DAYS": (
        "ceiling",
        (
            "`age >= timedelta(days=PURGE_HORIZON_DAYS)` purges an offer once it is "
            "older than this: a limit on age, breached by time passing, not by "
            "deleting."
        ),
    ),
    "lifecycle.TOMBSTONE_HASH_VERSION": (
        "neither",
        (
            "A format version compared for equality (`!=`) or written into records: "
            "it identifies a format, it bounds no count."
        ),
    ),
    "metric_naming.MINIMUM_CATEGORY_NAMED_RECORDED": (
        "floor",
        (
            "A denominator floor: the gate refuses (exits non-zero or reports "
            "`unmeasured`) when the measured count falls below it, so deleting a "
            "member of the guarded population is what breaches it. Out of the T159 "
            "census only because its comparand is resolved at runtime or from a key "
            "this sweep does not trace."
        ),
    ),
    "metric_naming.MINIMUM_METRICS_CLASSIFIED": (
        "floor",
        (
            "A denominator floor: the gate refuses (exits non-zero or reports "
            "`unmeasured`) when the measured count falls below it, so deleting a "
            "member of the guarded population is what breaches it. Out of the T159 "
            "census only because its comparand is resolved at runtime or from a key "
            "this sweep does not trace."
        ),
    ),
    "mock_interview.MAX_QUESTIONS": (
        "ceiling",
        (
            "An upper limit: the code refuses, truncates or stops once the quantity "
            "exceeds it (`n > LIMIT` / `n >= LIMIT` / `<= LIMIT` kept whole), so it "
            "is breached by adding, never by deleting."
        ),
    ),
    "mock_interview.SCHEMA_VERSION": (
        "neither",
        (
            "A format version compared for equality (`!=`) or written into records: "
            "it identifies a format, it bounds no count."
        ),
    ),
    "mock_interview._ID_WIDTH": (
        "neither",
        ("A zero-padding width in an id format string (`:0{WIDTH}d`): formatting, not a bound."),
    ),
    "pagination_capture.MINIMUM_DUPLICATE_KEY_PROBES": (
        "floor",
        (
            "A denominator floor: the gate refuses (exits non-zero or reports "
            "`unmeasured`) when the measured count falls below it, so deleting a "
            "member of the guarded population is what breaches it. Out of the T159 "
            "census only because its comparand is resolved at runtime or from a key "
            "this sweep does not trace."
        ),
    ),
    "pagination_capture.MINIMUM_URL_SIDE_PROBES": (
        "floor",
        (
            "A denominator floor: the gate refuses (exits non-zero or reports "
            "`unmeasured`) when the measured count falls below it, so deleting a "
            "member of the guarded population is what breaches it. Out of the T159 "
            "census only because its comparand is resolved at runtime or from a key "
            "this sweep does not trace."
        ),
    ),
    "pay.STALE_AFTER_DAYS": (
        "ceiling",
        (
            "`(as_of - checked).days > STALE_AFTER_DAYS` marks a rule set stale "
            "once it is older than this: a limit on age, breached by time passing, "
            "not by deleting anything. The AST rule reads the `return <compare>` as "
            "satisfied and votes floor; the register overrules it."
        ),
    ),
    "pay_normalise.MINIMUM_REFUSAL_STATES": (
        "floor",
        (
            "`shortfall = max(0, MINIMUM_REFUSAL_STATES - "
            'refusals["states_checked"])` is the amount by which the checked states '
            "fall short of it: a lower bound on states checked."
        ),
    ),
    "photo_extract.MIN_SHORT_SIDE": (
        "floor",
        (
            "`min(width, height) < MIN_SHORT_SIDE` rejects the photo: a minimum "
            "pixel size, breached by shrinking it."
        ),
    ),
    "photo_extract._TIMEOUT_SECONDS": (
        "neither",
        (
            "A subprocess timeout passed as an argument; the runtime enforces it, "
            "no comparison in this code."
        ),
    ),
    "plan_milestones.MINIMUM_MERGED_RESOLVED": (
        "floor",
        (
            "Recorded as the committed `*_at_least` floor of a measured count (or "
            "paired with its measured key in a floor table); every consumer refuses "
            "a count below it, so deleting a member of the population breaches it."
        ),
    ),
    "plan_milestones.MINIMUM_ROW_LABELS": (
        "floor",
        (
            "Recorded as the committed `*_at_least` floor of a measured count (or "
            "paired with its measured key in a floor table); every consumer refuses "
            "a count below it, so deleting a member of the population breaches it."
        ),
    ),
    "plan_v2.MINIMUM_BOARD_SIZE": (
        "floor",
        (
            "A denominator floor: the gate refuses (exits non-zero or reports "
            "`unmeasured`) when the measured count falls below it, so deleting a "
            "member of the guarded population is what breaches it. Out of the T159 "
            "census only because its comparand is resolved at runtime or from a key "
            "this sweep does not trace."
        ),
    ),
    "plan_v2.MINIMUM_MERGED_TASKS": (
        "floor",
        (
            "A denominator floor: the gate refuses (exits non-zero or reports "
            "`unmeasured`) when the measured count falls below it, so deleting a "
            "member of the guarded population is what breaches it. Out of the T159 "
            "census only because its comparand is resolved at runtime or from a key "
            "this sweep does not trace."
        ),
    ),
    "presentation.DEFAULT_LIMIT": (
        "neither",
        (
            "A default argument value (`def f(x=NAME)`), never compared in this "
            "module: a parameter's default is a setting, not a bound the code "
            "checks a population against."
        ),
    ),
    "presentation_log.PASS_OVER_THRESHOLD": (
        "neither",
        (
            "A default argument value (`def f(x=NAME)`), never compared in this "
            "module: a parameter's default is a setting, not a bound the code "
            "checks a population against."
        ),
    ),
    "prior_documents._SNIPPET": (
        "ceiling",
        (
            "An upper limit: the code refuses, truncates or stops once the quantity "
            "exceeds it (`n > LIMIT` / `n >= LIMIT` / `<= LIMIT` kept whole), so it "
            "is breached by adding, never by deleting."
        ),
    ),
    "process_spec.MIN_ITEM_WORDS": (
        "floor",
        ("`words < MIN_ITEM_WORDS` reports the item as too short: a minimum word count."),
    ),
    "profile._ID_WIDTH": (
        "neither",
        ("A zero-padding width in an id format string (`:0{WIDTH}d`): formatting, not a bound."),
    ),
    "profile_standing.MAX_ITEMS": (
        "ceiling",
        (
            "An upper limit: the code refuses, truncates or stops once the quantity "
            "exceeds it (`n > LIMIT` / `n >= LIMIT` / `<= LIMIT` kept whole), so it "
            "is breached by adding, never by deleting."
        ),
    ),
    "repo_gate.MINIMUM_EVIDENCE_KEYS_COMPARED": (
        "floor",
        (
            "Recorded as the committed `*_at_least` floor of a measured count (or "
            "paired with its measured key in a floor table); every consumer refuses "
            "a count below it, so deleting a member of the population breaches it."
        ),
    ),
    "repo_gate.MINIMUM_EVIDENCE_SOURCES_COMPARED": (
        "floor",
        (
            "Recorded as the committed `*_at_least` floor of a measured count (or "
            "paired with its measured key in a floor table); every consumer refuses "
            "a count below it, so deleting a member of the population breaches it."
        ),
    ),
    "repo_gate.MINIMUM_FILES_FORMATTED": (
        "floor",
        (
            "Recorded as the committed `*_at_least` floor of a measured count (or "
            "paired with its measured key in a floor table); every consumer refuses "
            "a count below it, so deleting a member of the population breaches it."
        ),
    ),
    "repo_gate.MINIMUM_PYTHON_FILES_FORMATTED": (
        "floor",
        (
            "Recorded as the committed `*_at_least` floor of a measured count (or "
            "paired with its measured key in a floor table); every consumer refuses "
            "a count below it, so deleting a member of the population breaches it."
        ),
    ),
    "review_reader.MAXIMUM_LOGIN_LENGTH": (
        "ceiling",
        (
            "The longest login GitHub allows (39 characters): a validity limit on "
            "length, pinned with controls at 39 and 40, breached by adding "
            "characters."
        ),
    ),
    "salary_period.MINIMUM_PERIOD_CONTRACTS": (
        "floor",
        (
            "A denominator floor: the gate refuses (exits non-zero or reports "
            "`unmeasured`) when the measured count falls below it, so deleting a "
            "member of the guarded population is what breaches it. Out of the T159 "
            "census only because its comparand is resolved at runtime or from a key "
            "this sweep does not trace."
        ),
    ),
    "salary_recovery.HOUSE_ESTIMATE_MINIMUM": (
        "floor",
        (
            "A house estimate is formed only from at least this many observations "
            "(`count >= HOUSE_ESTIMATE_MINIMUM`): a minimum sample size."
        ),
    ),
    "salary_recovery.MINIMUM_CORPUS_ADS": (
        "floor",
        (
            "A denominator floor: the gate refuses (exits non-zero or reports "
            "`unmeasured`) when the measured count falls below it, so deleting a "
            "member of the guarded population is what breaches it. Out of the T159 "
            "census only because its comparand is resolved at runtime or from a key "
            "this sweep does not trace."
        ),
    ),
    "scoring.BATCH_THRESHOLD": (
        "neither",
        (
            "A default argument value (`def f(x=NAME)`), never compared in this "
            "module: a parameter's default is a setting, not a bound the code "
            "checks a population against."
        ),
    ),
    "session_kind.MINIMUM_SESSION_KIND_CASES": (
        "floor",
        (
            "A denominator floor: the gate refuses (exits non-zero or reports "
            "`unmeasured`) when the measured count falls below it, so deleting a "
            "member of the guarded population is what breaches it. Out of the T159 "
            "census only because its comparand is resolved at runtime or from a key "
            "this sweep does not trace."
        ),
    ),
    "skill_budget.BUDGET_GRANULARITY": (
        "neither",
        ("A divisor (`budget % BUDGET_GRANULARITY == 0`): a modulus, not a limit."),
    ),
    "skill_budget.FALLBACK_BUDGET_CHARS": (
        "neither",
        (
            "A value reported or returned as the budget in force (and subtracted "
            "from a total to report the overage); the budget is a quantity recorded "
            "here, not enforced by a comparison against this constant."
        ),
    ),
    "skill_budget.MIN_HEADROOM_CHARS": (
        "floor",
        (
            "`headroom < MIN_HEADROOM_CHARS` flags a budget that leaves too little "
            "spare room: a minimum on spare characters."
        ),
    ),
    "skill_budget.UPSTREAM_DEFAULT_BUDGET_CHARS": (
        "neither",
        (
            "A value reported or returned as the budget in force (and subtracted "
            "from a total to report the overage); the budget is a quantity recorded "
            "here, not enforced by a comparison against this constant."
        ),
    ),
    "sourcing.DETAIL_FETCH_CEILING": (
        "ceiling",
        (
            "`detail_fetched >= DETAIL_FETCH_CEILING` stops opening advert pages: a "
            "per-run budget of fetches, spent by adding fetches."
        ),
    ),
    "sourcing.MINIMUM_BOARDS": (
        "floor",
        (
            "Declared as a minimum number of boards; no comparison reads it in src "
            "or tests today, so it bounds nothing yet, but what it is named for and "
            "set to is a lower bound (one board) on a counted population."
        ),
    ),
    "sourcing.OFFER_CEILING": (
        "ceiling",
        (
            "An upper limit: the code refuses, truncates or stops once the quantity "
            "exceeds it (`n > LIMIT` / `n >= LIMIT` / `<= LIMIT` kept whole), so it "
            "is breached by adding, never by deleting."
        ),
    ),
    "sourcing.PHRASE_CEILING": (
        "ceiling",
        (
            "How many of the candidate's phrases one run may search; phrases past "
            "it are kept for the next run: an upper limit, named for what it is."
        ),
    ),
    "sourcing._FLOOD_GATE_ROWS": (
        "neither",
        (
            "The size of a synthetic fixture the flood probe builds (rows per page, "
            "pages per board, rows at which the gate trips); a quantity the test "
            "generates, not a limit the code enforces on a population."
        ),
    ),
    "sourcing._FLOOD_PAGES": (
        "neither",
        (
            "The size of a synthetic fixture the flood probe builds (rows per page, "
            "pages per board, rows at which the gate trips); a quantity the test "
            "generates, not a limit the code enforces on a population."
        ),
    ),
    "sourcing._FLOOD_PAGE_ROWS": (
        "neither",
        (
            "The size of a synthetic fixture the flood probe builds (rows per page, "
            "pages per board, rows at which the gate trips); a quantity the test "
            "generates, not a limit the code enforces on a population."
        ),
    ),
    "sourcing_exclusions.MINIMUM_PRESENTATIONS": (
        "floor",
        (
            "Only ever read as `assert len(found) >= MINIMUM_...` in the test that "
            "pins the population (tests/), never in src: a lower bound on a counted "
            "population."
        ),
    ),
    "sourcing_exclusions._MIN_STEM": (
        "floor",
        (
            "A stem is cut further only while it keeps at least this many "
            "characters (`len(base) - len(plural) >= _MIN_STEM`): a minimum "
            "remaining length. The AST rule votes it a ceiling because the guard's "
            "true branch does work; the register overrules it."
        ),
    ),
    "stack_fit.MINIMUM_CASES": (
        "floor",
        (
            '`"measured" if len(cases) >= MINIMUM_CASES else "unmeasured"`: the '
            "count of cases must reach it for the gate to read as measured."
        ),
    ),
    "step_gates.UNCERTIFIABLE": (
        "neither",
        ("A process exit code returned to the shell, not a bound."),
    ),
    "step_gates.VOCABULARY_SILENT": (
        "neither",
        ("A process exit code returned to the shell, not a bound."),
    ),
    "step_specs.MIN_FIELD_WORDS": (
        "floor",
        (
            "`words < MIN_FIELD_WORDS` rejects a field too short to tell an answer "
            "from a heading: a minimum word count."
        ),
    ),
    "strings.MINIMUM_STRINGS": (
        "floor",
        (
            "A denominator floor: the gate refuses (exits non-zero or reports "
            "`unmeasured`) when the measured count falls below it, so deleting a "
            "member of the guarded population is what breaches it. Out of the T159 "
            "census only because its comparand is resolved at runtime or from a key "
            "this sweep does not trace."
        ),
    ),
    "task_gate.MINIMUM_EMITTED_FIELDS_SCANNED": (
        "floor",
        (
            "Recorded as the committed `*_at_least` floor of a measured count (or "
            "paired with its measured key in a floor table); every consumer refuses "
            "a count below it, so deleting a member of the population breaches it."
        ),
    ),
    "task_gate.MINIMUM_GATES_READ": (
        "floor",
        (
            "Recorded as the committed `*_at_least` floor of a measured count (or "
            "paired with its measured key in a floor table); every consumer refuses "
            "a count below it, so deleting a member of the population breaches it."
        ),
    ),
    "task_gate.MINIMUM_PRESENCE_RECORDING_FIELDS": (
        "floor",
        (
            "Recorded as the committed `*_at_least` floor of a measured count (or "
            "paired with its measured key in a floor table); every consumer refuses "
            "a count below it, so deleting a member of the population breaches it."
        ),
    ),
    "task_gate.MINIMUM_RECORD_KEYS_COMPARED": (
        "floor",
        (
            "`measured[...] < MINIMUM_RECORD_KEYS_COMPARED` fails the gate: a lower "
            "bound on keys compared. The AST rule cannot agree between its two "
            "sites, so it reads the name as undetermined."
        ),
    ),
    "task_gate.MINIMUM_STATUS_KEY_GATES": (
        "floor",
        (
            "Recorded as the committed `*_at_least` floor of a measured count (or "
            "paired with its measured key in a floor table); every consumer refuses "
            "a count below it, so deleting a member of the population breaches it."
        ),
    ),
    "test_mode.PASTE_CHARS": (
        "floor",
        (
            "A turn is treated as a paste only from this length up (`len(text) >= "
            "PASTE_CHARS and _looks_pasted(text)`): a minimum length. The AST rule "
            "votes it a ceiling because the guard's true branch does work; the "
            "register overrules it."
        ),
    ),
    "topic_scope._HEADING_LIMIT": (
        "ceiling",
        (
            "An upper limit: the code refuses, truncates or stops once the quantity "
            "exceeds it (`n > LIMIT` / `n >= LIMIT` / `<= LIMIT` kept whole), so it "
            "is breached by adding, never by deleting."
        ),
    ),
    "trait_sufficiency.MINIMUM_TRAITS": (
        "floor",
        (
            "A denominator floor: the gate refuses (exits non-zero or reports "
            "`unmeasured`) when the measured count falls below it, so deleting a "
            "member of the guarded population is what breaches it. Out of the T159 "
            "census only because its comparand is resolved at runtime or from a key "
            "this sweep does not trace."
        ),
    ),
    "verified_gate.MINIMUM_CONTRACTS": (
        "floor",
        (
            "A denominator floor: the gate refuses (exits non-zero or reports "
            "`unmeasured`) when the measured count falls below it, so deleting a "
            "member of the guarded population is what breaches it. Out of the T159 "
            "census only because its comparand is resolved at runtime or from a key "
            "this sweep does not trace."
        ),
    ),
    "voice._EXCERPT": (
        "neither",
        (
            "The width of a text window or slice (`text[max(0, i - WIDTH):i]`, a "
            "shingle size, an excerpt cut): a size parameter of an algorithm, "
            "compared against nothing."
        ),
    ),
    "weights.MAX_CHOICES": (
        "ceiling",
        (
            "The most forced pairwise choices step 6 asks for; declared with no "
            "comparison in this module, but named and used as an upper limit on "
            "questions asked."
        ),
    ),
}
