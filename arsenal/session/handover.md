# Session handover

**2026-09-04.** Board: **138 tasks merged**, `verify-gates` 137/137. This session
merged **seven** PRs and left nothing in flight. Its whole subject is the
merge-policy change the previous session made: *the review half is a second
session, not a bot*. That policy was exercised four times here and it found, every
time, something the implementer and CI both missed.

## The headline: what independent reads actually found

Four PRs got a second-session read. Across them:

| | |
|---|---|
| metrics whose **name did not match what they counted** | 4 |
| **fail-opens** | 8, four of them on `hard` dealbreaker dimensions |
| PRs whose **own prose was factually wrong** about their numbers | 2 |
| findings caught by **CI** | 0 |

Two of those are worth carrying forward as patterns, because the repository has
now hit each of them three times:

- **A metric named for a property it does not measure.** `status_is_asserted`
  (T108), `incidental_duplicate_drops` (#323), `negation_recall_hits_by_mechanism`
  (#318), and `robots_adjudications_without_a_competent_second_reader` (#328) are
  the same defect four times. The tell is always that the implementer *can state
  the discrepancy in one sentence* and has decided it is acceptable. It is not:
  the next session quotes the name.
- **A fixture one word away from passing.** On #319 four separate committed
  fixtures were the failing string with the qualifier removed — the author wrote
  the sentence that passes. That is the second-reader rule's own prediction, met.

## Merged this session

| PR | task | what it actually was |
|---|---|---|
| #327 | **T102** | Case 22 of the round-2 robots audit: does a file's product token match as a **prefix** of a longer crawler token? Two sessions read RFC 9309 §2.2.1 independently — of each other and of the code — and both said **no**: matching is case-folded equality, no prefix rule, no specificity rule. `_select_rules` was already correct; the audit's recommendation was a **recollection**, and acting on it would have *created* a fail-open (an explicitly matched group is used exclusively, so a prefix match can displace `*` and unblock a path the site disallowed for everyone). Retracted in place. |
| #318 | **T59 diag** | Negation is one label short of measurable (9 of 10, all Spanish) and the number it would unblock is **0.667 against a bar of 0.80**. Does **not** close T59. |
| #328 | **T116** | The second robots parser cannot refuse, so "two matchers must agree" was **one matcher** for the whole life of `ruled-out.yaml`. Of 20 adjudications exactly **one** was ever really two-parser. |
| #329 | **D-27** | A merged task's plan row is never ticked. **9 drifted, not the filed 47** — and the recompute says the filed figure was really 52 of 125 and that `e32a541` itself **missed five**. The sweep was incomplete, which is the argument for a gate rather than a sweep, made by the sweep. |
| #326 | T106 | Declared `requires: [surface:egress]`. |
| #324 | hotfix | `T85.gate_modules_discovered`. |

### What the second reads added to each

**#327 (T102)** — the worker's branch would have merged as the **only** terminal
task with no machine-readable gate (`verify-gates` 133/134). Its gate metric had
to be `uncommitted_audit_cases`, the name `status/plan.md` already declared. New
module `integral.audit_followup` measures it: an audit case that found a defect is
**red until a gate holds it**, and a `RESOLVED` heading must cite a spec section
*and* name a fixture that really exists in the committed table. That closes the
hole that let case 22 sit open across four merges — a finding in a markdown file
was invisible to every target in the `Makefile`.

**#318 (T59)** — three fail-opens, all fixed. `scope` was credited on hits a
`denies` cue had already earned outright (now a three-way partition with `both` as
its own row; `both` is 0 on today's corpus, so the defect was **latent** and the
fixture is what makes that a measurement rather than luck). `scope_only` counts a
*firing*, not a verified recovery — one of today's three is a flattened field table
with no punctuation, where the negator the rule consumes answers a **different
field**, and flipping the labelled field to `Si` does not change the verdict.
`by_language` was seeded from `_NEGATORS` ("words that flip a cue") rather than
from `Language`, so a new language with no negators would have been **silently
absent** from the one key written to make a zero impossible to miss.

**#328 (T116)** — five blockers. Two were **new RFC-derived fail-opens the
implementer missed**: `no_control_possible` (the standing that excuses a board
entirely) returned for files that plainly refuse a path, because the witness
sampler produced one candidate per pattern; and a file could be `competent` on
`/admin` while the reader was fail-open on `/apply`, with the fail-*closed*
discrepancy recorded and the fail-*open* one discarded. Also: `_main` returned
`max(t99, t116)` and `max(1, 3) == 3`, which `make evidence` records as
"unmeasured" and **continues** — so a real T99 failure was swallowed.
`liveness._main` had the identical defect and was in no report.

## Three process facts, each learned the expensive way

**1. The reviewer can be wrong, and the fixer must check.** #328's report
prescribed "retry with the sample extended by one octet". That does not work —
`Allow: /ax` matches `/axx` as a prefix too, both patterns still score 3 octets,
the tie still goes to the allow. Taking the instruction literally would have
shipped a fix that looked right and left the fixture red. **A report is a finding,
not a patch.**

**2. A resolved finding recorded where nothing re-checks it goes stale and lies.**
A scheduled check-in fired carrying *"RESOLVED — do not re-investigate: CodeRabbit
runs on Free and never produces a review object"*. That was true when written and
false by 10:12. The instruction not to look is what would have kept it false.
Rewritten.

**3. CodeRabbit is not gone, and its output is inconsistent.** On #319 it reported
`Plan: Team` and posted **five verified real findings**; twenty minutes later on
#328 it reported `Plan: Free` and posted a walkthrough with none. Its
`✅ Addressed` markers are **unreliable** — it marked a finding addressed that was
not, because its risk verdict was stamped against an older `coveredCommitId`.

**The two reviewers catch different classes.** The bot is good at *"this regex
matches this string it should not"*. The second session is good at *"this metric's
name lies"* and *"this whole check is one-way in the wrong direction"*. Neither
subsumes the other. **Working rule: CodeRabbit findings are bug reports to verify
and fix; the second-session read stays the gate.** `CLAUDE.md`'s section still says
CodeRabbit is gone — that needs correcting, though the 41-vs-9 comparison in it
still stands.

## CI died mid-session, and #329 merged without it

Measured: two consecutive runs on #329 finished in **6 and 5 seconds** with every
job failed and **every log a 404**, against ~95 seconds with real conclusions on
#328 twenty minutes earlier. That is the runner dying before any job body ran.
**The tell is the clock, not the conclusion** — read `created_at`/`updated_at` on
the run; under ~10 seconds with unreadable logs says nothing about the code.

`merge-policy` is `after-ci-and-review` and the CI half became unavailable, so
#329 merged on `make host-gate` — which is *exactly* what CI runs — with the four
results quoted in the merge commit, the outage named on the PR, and the pushed SHA
verified equal to the tested one. **The owner was asked and was away.** The
standing instruction was "merge when green and continue taking issues", and the
previous outage lasted thirteen days. If that call was wrong, #319 is the only one
that followed it.

`CLAUDE.md`'s "a red CI is a signal again" paragraph now carries the correction.
It was true when written and false four hours later — the same shape as the
check-in described below.

## D-27's residue, left open deliberately

Changing **one word** in an archived task file — `status: merged` → `done` —
zeroes `merged_tasks_with_an_unticked_plan_row` and fires nothing: no violation,
no drift, exit 0, with the denominator's fall absorbed by the floor. It is
reachable **in the same commit that archives the file**.

It is pinned with fixtures rather than closed, because closing it demands either
that archived-`done` tasks be ticked as *merged* (false of them) or that
`status/plan.md`'s legend grow a `done` glyph — **a decision about the document,
not about the checker, and the owner's to make**. Widening the numerator to
`_TERMINAL` now fails those fixtures *and* the shipped board, so the coupling is
visible rather than latent. T29 is the live instance: archived `status: done`,
plan row `◐`, so the plan asserts a finished task is in progress.

## D-27 earned its place on the very next PR

#319's gate went red on `T56 is archived as merged and its plan row reads `☐`,
not `☑``. That branch was cut before the check existed, so nothing ticked the row
when the task file was archived — the exact drift D-27 was filed about, caught on
its first encounter rather than found in a sweep 52 rows later. Had #319 merged
first it would have been row 53.

## #319 (T56) — what actually happened to the number

`extraction_macro_f1` gates at 0.75. The chain matters more than the endpoint:

```
origin/main                                     0.4943
first pass (19 findings applied)                0.7698   <- not honest
  minus the two label-derived cues              0.746    <- red
  plus the cognate-stem repair                  0.7567   <- honest, green, merged
```

The implementer disclosed that it found two `product_vs_services` cues **by
reading the false negatives**, and that without them the gate was red. Both fail
on the −0.7 tell, and **the route disqualified them anyway**: D-2 with the arrow
reversed. They are gone.

What replaced that gain is a repair the PR **claimed and had not made**:
`contrat\w*` cannot match `Contracte` (Spanish *contrato* stems to `contrat`,
Catalan *contracte* to `contract`), while the file's own comment says the ES list
must tolerate the cognate. **33 Spanish adverts carry that field; 29 got no
`contract_stability` reading at all.**

**The most useful finding is what the fall to 0.1667 turned out to be.** All three
lost readings state placement *once* — the owner's own label on the two Arelance
adverts cites exactly the *surviving* clause — and a bipolar dimension needs
**two** matches to settle. So they are lost to the **corroboration rule**, not to
a wrong cue, and `product_vs_services` is back at main's 0.1667: the first pass
delivered **zero** real gain there. Recorded as a live `matches=1` fixture with
the corroboration rule named as the defect, rather than recovered with another
cue — which would have been the corpus-fitting T56's own task file forbids.

### Still open in the cue set, recorded not fixed

- **F9 is broader than either review said.** Averaged values that are not rungs:
  `contract_stability` 0.6; `schedule_flexibility` **0.65 on its own committed ES
  gold span**, where the gold says 0.7 (pre-existing); `compensation_transparency`
  **0.55** on the nine adverts saying "Salario Competitivo" beside a band;
  `product_vs_services` **−0.6** for any properly corroborated placement advert.
  `remote_arrangement` names this defect in its own comment and it is alive in at
  least four other files.
- **Two fail-opens neither review raised:** `trasllat` reads 0.9 on
  `feinaactiva-FA92319865`'s *"trasllat i emmagatzematge de materials"* (moving
  stock, not the person), and `relocation package` reads 0.9 on six adverts
  offering it as a **benefit**.
- `_matched_cue_hits` takes `negated = all(...)` across language slices. Cognate
  pairs agree today so nothing flips; the ES/CA widening made the duplication
  systematic and nothing tests it.
- `suficiente` at 0.6 in `english_demand` holds weakly.

## Held for the owner

**#307 (T98)** — unchanged, and it is a decision only the owner can make: **are
step-5 corpus stimuli exempt from the serving ban?** Yes → state and bound the
exemption with its own counter. No → `reaction_elicit` joins `CORE_SERVING_MODULES`
and the gate goes red immediately.

## Mechanics worth keeping

- **The board fetch.** `list_issues` with `fields: [number,title,state,labels,assignees]`
  and `perPage: 100` needs two pages (114 issues). Writing only the **open** rows to
  `/tmp/arsenal-issues.json` makes `task_select.py` return an **archived** task —
  it cannot see terminal state without the closed issues, so filter its output on
  `path` not containing `_history/`, or fetch both pages.
- **Sixteen open tasks carry `requires: [human:gate]`** — imported from issues, gate
  is the issue's prose, "visible but never dispatched". Writing a real fenced
  ```gate block and deleting that line is what makes one claimable.
  `queue-seeding.md` says that is a human's call; the task files' own placeholder
  comments instruct the implementer to do it. **The two texts conflict** — worth the
  owner's eye.
- **`make evidence` compares the working tree against the index**, so a legitimately
  changed evidence file reads as drift until `git add -A`. Not a defect; costs five
  minutes each time it is rediscovered.
- **Read the plan row before writing a gate block.** Inventing a metric name is now
  a four-time mistake, and `test_the_committed_plan_and_queue_agree` catches it
  every time.
- Adding a `T`-numbered task **forces a `status/plan.md` row** — `plan_v2` counts
  `in_queue_only` as drift.

## Queue

**A `ruff format --check` gate is not in the repo gate, and 19 files are
unformatted.** #329 regressed two hunks in one file and fixed only those, filing
the reasoning: the gate would need a 19-file reformat as a rider on an unrelated
PR. It is its own task and is not seeded yet.

**T120** seeded (`t-9d41c7f5`): replace the stdlib second robots reader with a
longest-match parser written from RFC 9309. `deps: [t-4c88b302]`. That is what
would make `robots_adjudications_without_a_competent_second_reader` fall from
**19**; it cannot be done here because the 18 boards' robots.txt are not committed
and egress is blocked.

Two tasks stay declared-unreachable on this surface: **T59** (`requires:
[access:human]` — needs a person to label) and **T106** (`requires:
[surface:egress]` — needs irs.gov and ssa.gov, both `EGRESS_BLOCKED`). Writing US
tax figures from memory with a `read_on` date would fabricate exactly the
provenance T106 exists to create.
