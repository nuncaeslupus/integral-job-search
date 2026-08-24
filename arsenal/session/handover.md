# Session handover — 2026-08-24, the first human sitting

A `[HUMAN]` session, not a worker loop. The candidate sat down to do T20 and the
session turned into: build the software T20 needed, discover the instrument was
wrong, and rewrite what the product thinks sourcing is.

## What merged

| PR | What | Gate |
|---|---|---|
| #153 | T20a — `integral.calibration`: the draw, the blind presentation, the recorded ordering, `rank_spearman` | `blind_ranking_leaks == 0` |
| #155 | `tools/blind_ranking_page.py` — the surface the candidate actually works in | covered by #153's gate |
| #156 | Two feature specs, sections 1–4 | none (spec) |

Board: 97 tasks — **open 6, claimed 0, merged 88**. `make host-gate` green on `main`.

## The finding that reframed the product

The candidate ranked the twenty held-out adverts. **One** went in "would apply",
one in "maybe", **eighteen** in "not for me" — nine of those rejected for a
technology they have never written.

The ranking did nothing wrong. It ordered exactly the list it was handed, and the
list was mostly not their job. **A supply failure presenting as a ranking result.**
No improvement to the dimension model, the extractor or the ranker reaches it,
because all three run downstream of the decision that produced the list.

Then the cause, found in §3.1:

```
7  sourcing      → offers/*.json                [reads: constraints.json]
```

`step_graph` refuses an acyclicity check on purpose — *"the loop is the product"* —
but the loop is 6 → 9 → 10 → 6. **Sourcing is outside it.** Constraints are settled
at step 2, before the candidate has seen a single advert, so the offer set is fixed
by the least-informed moment in the process and everything learned afterwards can
only re-rank it.

Both specs in #156 are about that. `status/specs/`:

- **`preference-directed-sourcing.md`** — an offer rejected for a reason orthogonal
  to what made it attractive is evidence about its *employer*. Recommends employer
  re-query first, model-proposed employers second behind
  `unverified_company_claims == 0`, attribute-directed search last or never.
- **`iterative-sourcing.md`** — amends the process spec: close the loop, and give
  the tool a voice in steering it. **Next action: run `design` over this one.**

## Decisions the candidate settled, that a future session must not relitigate

- **Consent, not concentration.** A cycle may narrow onto one employer *when the
  candidate chose it in conversation*. The failure is the algorithm shrinking the
  world quietly. Gate counts recorded decisions, not employer share.
- **Exhaustion is dedup-based** — "we are finding the same jobs again". No
  preference model needed, so it works on day one.
- **The tool may say the market has nothing**, once exhaustion survives both
  broadening and narrowing, and what it offers then is *a time*, not a compromise.
- **Skill mismatch is a soft penalty with a supply-dependent cut**, never a
  knockout: a stretch job is worth showing when there is nothing else.
- **Scope decisions do not expire** — they are re-surfaced for correction when the
  candidate returns.

## Two things found in the corpus, neither filed yet

- **A prompt injection in a live advert.** The ClickHouse ad (`weworkremotely`)
  contains an instruction addressed to an LLM reading it. This tool reads adverts
  with a model at extraction and again at application-drafting. **Worth a task.**
- **5 of 20 adverts state a salary number.** `rank` only reaches L2 when a salary
  exists, so most of any ranking sorts on "no number". Not a bug — the market.

## Repository renamed

The GitHub repository is now **`nuncaeslupus/integral-job-search`**; the previous
name still redirects. The **local checkout has not been renamed yet** and the owner
is doing it by hand, because six worktrees hold absolute paths — move the clone to
`~/dev/integral-job-search`, then from inside it:

```bash
git worktree repair && git worktree list
```

Note T55 rejects any document naming the old repository, which now includes real
issue URLs — link issues as bare `#154` until the rename settles.

## State

- **`ivan` profile exists** (`~/.integral-job-search/profiles/ivan`, `fiction: false`)
  and holds **only `identity.json`**. Nothing from the sitting was recorded: it was
  a tooling exercise, and the profile is to be deleted before the real one is built
  by walking steps 0–12 in order.
- **T20 (`lo-c48f`, #59) is open and unclaimed.** Held out of selection by
  `requires: [surface:human]`. It cannot complete until weights exist (step 6), and
  `measure_spearman` now refuses to certify from a `fiction` profile or one with no
  readable identity.
- **CI is still out of runner minutes** — every job fails in 2–4s with `runner_id: 0`.
  `make host-gate` locally is the real gate.
- Worktrees `js-t26-wt`, `js-t43-wt`, `js-t20-wt` still exist; `js-t20-wt` holds
  this session's branches, all merged.
