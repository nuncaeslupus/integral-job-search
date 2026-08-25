# Session handover — 2026-08-25, the trap is disarmed and the subset is closed

Two PRs open, both green locally, both waiting on review: **#194** (arsenal v2.4.16)
and **#195** (T56's scorer + the §3 decision). `main` untouched.

Board: 107 tasks — open 5, claimed 0, merged 99, done 1, cancelled 2.

## The decision is made — §3 is closed, not open

**The owner accepted the proposed five, cold, before any label was placed:**
`remote_arrangement`, `compensation_transparency`, `contract_stability`,
`schedule_flexibility`, `seniority_expectation`. It is written into
`status/specs/labelling-round.md` §3 with the date, and it is **closed**: no dimension
joins or leaves on the strength of a score. If five is the wrong size the answer is to
say so and start the round over — adding a sixth after seeing a number is D-2's failure
in a different hat.

`collaboration_mode` is out for this round. Not unfindable — that inference would come
from cue firings, which are what the labels are meant to judge — but the only dimension
with no pre-mark, so the only one costing a blind read per label.

**So the round can start — and it is eleven adverts, not forty-five reads.**

45 labels exactly: each of the five holds one already, so nine each. But labels are placed
per *advert*, and T57's re-seed pre-marked the evaluation split heavily — 31 to 56 marks
per dimension across 73 evaluation ads, none of them a control:

| dimension | pre-marks on evaluation ads | labels still needed |
|---|---|---|
| `remote_arrangement` | 37 | 9 |
| `compensation_transparency` | 48 | 9 |
| `contract_stability` | 50 | 9 |
| `schedule_flexibility` | 31 | 9 |
| `seniority_expectation` | 56 | 9 |

Three evaluation ads pre-mark all five at once, thirteen mark four. A greedy cover over
those — read the ads that carry the most of the five first — **floors all five dimensions
in 11 adverts** with no shortfall. Every mark is confirm / change / delete, and the page
carries no cue data at all, so nothing here scores the extractor against itself.

Do not spend the round on `blind_control` (32 ads): they are deliberately unmarked so that
blind agreement can be read against confirmed agreement. They are a different measurement,
not cheap labels.

## The trap is gone — label ten is now safe

`measure()`'s placeholder raised the moment any dimension crossed
`MIN_EVALUATION_LABELS_PER_DIMENSION`. It sits on `make evidence` → `make host-gate` →
`open_task_pr.sh`, so the first tenth label would have broken **every PR in the repo**,
discovered at label ten with nine already spent. Implemented in #195.

How it scores, and why — each of these is a choice a later reader will want the reason for:

| decision | why |
|---|---|
| prediction is the **rules stage** alone | stage 3 asks a model; an evidence file cannot make that call. Same as `negation_recall` |
| a dimension no cue settles predicts class **0** | a *miss*, not an exclusion — excluding it scores the cue set against exactly the adverts the cue set already reaches |
| binary over "the advert asserts this", class 0 negative on both polarities | METHODS.md's `2PR/(P+R)`; a bipolar sign error costs one FP **and** one FN |
| `f1` is `None`, not `0.0`, with no positive either side | no ratio exists, and 1.0 would let a dimension nobody could get wrong lift the mean. Named in `dimensions_without_positives`, dropped from the average |

Evidence is substantively unchanged — still `null`, still `unmeasured`, the two new keys
empty. That is the point: it now says *"scoring ran and found nothing to score"*.

## #194 — the update, and the bug that made it urgent

`.claude/skills/*` sat at **2.4.0** while `claude-arsenal/` was at **2.4.9**. Step 0(b) of
the protocol runs `init.py --repo-path . --silent` and calls it a report — this session it
**downgraded the bundle by twelve files**, including `AGENTS.md`, `open_task_pr.sh` and
`task_select.py`. `AGENTS.md` promises the script writes nothing when the installed bundle
is newer. It wrote anyway. Reverted with `git checkout`; skills refreshed to v2.4.16 here.

**That removes the skew, not the missing guard.** Filed upstream as
[`claude-arsenal#237`](https://github.com/nuncaeslupus/claude-arsenal/issues/237). The
finding is sharper than "the guard is broken": the #220 guard first shipped in **v2.4.5**,
and it lives in `init.py` — the very file a pre-2.4.5 host is running a stale copy of. The
protection is on the wrong side of the version boundary, so every host that needs it is by
definition too old to have it. The fix has to move to `check_update.sh`, which is
bundle-side and therefore *newer* in exactly the dangerous case. #237 also carries the
subtree-advice finding below.

**`check_update.sh`'s suggested `git subtree merge` cannot work in this repo.** The bundle
ships inside `plugins/core/skills/init/assets/`, not at the tag root, so the subtree was
never added and never can be. `init.py` **is** the installer; refreshing
`.claude/skills/init` from the tag and re-running it is the update path. Use
`--check-only` to detect, then that. Do not chase the subtree advice again.

Seven releases, two that matter here: **#230** (every path out of `_history/` puts the task
file back) and **#233** (gates run where they were read from — a gate resolved against the
wrong root passes by *not running*, which is what D-22 exists to catch).

## #124 was closed again and has been reopened again

Second time. `open_task_pr.sh` writes `Closes #<issue>` into the **commit message**, which
survives a squash, so a partial PR opened with that script closes its task issue anyway.
**#195 was opened by hand for exactly this reason** — plain `git push` + `gh pr create`,
`Refs #117` not `Closes`, and the task file left live. Do that for every partial PR until
the script grows a flag. The T56 claim was released after opening, so the board shows
nobody holding it.

## Next session

The round is unblocked and nothing machine-side is in its way. In order:

1. **T59 does not close by widening the corpus either — that was checked, and the
   answer is no.** See the section below; it replaces the previous handover's
   recommendation, which was made without classifying the misses.
2. **The 45 labels.** Five dimensions, confirm-and-move. Label ten is safe now.
3. **T57 closes by adding dimensions, not by remapping.** 648 unmapped concepts; the top
   four themes — credentials (83), pay structure (54), place/mobility (41), working-time
   shape (37) — are the corpus saying the model was built for programming ads and does not
   reach the families T25 added. That table is the shortlist.

**T20 and T69 still need the owner in person** — a blind ranking of 20 held-out ads, and
the exhaustion signal watched on a live cycle. `measure_spearman` refuses a fiction.


---

## T59 re-examined — widening the corpus cannot close it, and here is the proof

The previous handover offered "widen the corpus" as one of three ways out. It is not
one. Every miss was classified this session and **none of the seven is a sampling
failure**, so more adverts add more of the same three shapes.

First, two corrections to the record:

* **There are no "108 unstored raw ads."** `corpus/raw/ads.jsonl` and
  `corpus/labelled/ads.jsonl` are both 208 lines with *identical* id sets — T57's
  re-seed brought them all in. The 108 figure was about ads with no *suggestions*,
  not ads outside the store. That widening path does not exist.
* **Recall is 2/9, not "9 of 10 labels".** `T16.json` says `negation_recall_hits: 2`
  against a floor of 10 and a gate of 0.80. Reaching the floor would produce a
  **measured failure around 0.2**, not a pass. That is still worth having — a measured
  failure is diagnosable and `unmeasured` is not — but nobody should expect the floor
  to turn this green.

### The seven misses, classified

| n | shape | example | more corpus helps? |
|---|---|---|---|
| 3 | the denial is encoded as a **dedicated zero-valued, non-negatable cue** — `sin\s+viajes\|no\s+viajes`, `gesti[óo]n\s+de\s+equipos\s+no` — so the rules stage gets the **answer right** (class 0) and represents it as *absence* rather than *denial*. `negation_recall` checks `found.negated`, so a correct extraction scores as a miss | `Viajes o guardias No`, `Sin viajes ni guardias.` | no |
| 2 | a **bipolar** dimension matched **one** cue, and one keyword does not settle a bipolar dimension by design — so an unambiguous denial goes unsettled | `sin sprints tradicionales` matching `scrum\|sprint\|kanban` | no |
| 2 | the phrasing is **not in the cue set at all** | `No hay horarios fijos ni dailies` | no |

Three things follow, and each is a decision rather than a task:

1. **Do not "fix" this by scoring class agreement instead of the `negated` flag.** It
   would take recall from 2/9 to 5/9 in one line and it is the tautology T59 exists to
   refuse: you could then score ~1.0 by writing a `no X` cue per dimension and never
   exercising the negation machinery at all.
2. **The zero-valued denial cues are the actual root cause, and the fix is a deletion.**
   A cue matching `sin viajes` should resolve to `value=0.0, negated=True` — which is
   exactly what a person wrote — instead of a bare `0.0`. Catalan already nearly does
   it right: `viatges` is a `negatable=True` cue, so `sense viatges` is reachable by the
   general scope rule, and the extra `sense\s+viatges` special case is redundant. Spanish
   has the special case and no bare-`viajes` negatable cue. Making the general machinery
   carry denials, and dropping the special cases, is the change — it is dimension-model
   surgery and belongs beside T57's dimension work.
3. **A negated single match is stronger evidence than a positive single match.** The
   two-match rule for bipolar dimensions is right for positives — one `sprint` does not
   establish a process culture — and wrong for denials: `sin sprints tradicionales` is
   unambiguous. That asymmetry is not encoded anywhere today and is what turns misses
   4 and 5 into hits.

**Widening the corpus is still safe and still available**, just not for this. `assign_splits`
keeps every existing ad's split, so adding ads cannot migrate a labelled ad across the
boundary (T9's `elicitation_eval_overlap`, guarded by construction). The collector's
sources are public and reachable — `getmanfred` answered 200 this session. Measured yield
is **9 denials per 105 evaluation ads**, so a denominator of 20 needs roughly 256 more
adverts. Worth doing for T56's breadth or T57's vocabulary; not worth doing for T59.
