# Running without Claude Code — the degraded mode

**Status: proposed, 2026-08-28.** This answers "can someone without a Claude
subscription use this?" The honest answer is *most of the conversation, none of
the measurement*, and this document says exactly which is which so that nobody
has to find out one step at a time.

It is **proposed**, not decided, because §7 asks the owner one question that
`status/plan.md` has already answered in the other direction.

---

## 1. What the real tool needs, and what a chat has

The tool as built requires [Claude Code](https://claude.com/claude-code), which
requires a paid plan or API billing. It is not available on the free tier at
all. Four mechanisms carry the design, and a claude.ai conversation has one:

| mechanism | where it lives | in a free chat |
|---|---|---|
| The thirteen step protocols | `.claude/skills/step-*/SKILL.md` | **prose — pasteable** |
| The checkpoints | `scripts/run_checkpoint.py`, `src/integral/` | absent — no execution |
| The candidate store | `$INTEGRAL_HOME/profiles/<handle>/` | absent — no writable disk |
| The containment hook | `PreToolUse` (S3) | absent — no hooks |

Only the first is prose, and prose is the half that carries the *manner*. That
is the whole reason a degraded mode is worth having: the elicitation instrument
is the conversation (`docs/product-shape.md`), and the conversation survives.

## 2. The context tax decides the shape

Free-tier context and message allowances are small, so the binding constraint is
**what gets re-sent on every turn**. Measured against this tree:

| what | ~tokens | charged |
|---|---|---|
| All thirteen step skills | **23,600** | every message, if uploaded to a Project |
| `status/spec-v2-steps.md` | 14,600 | every message |
| `docs/METHODS.md` | 8,600 | every message |
| `dimensions/*.yaml`, in full | 23,600 | every message |
| **Everything, as Project knowledge** | **~70,000** | **every message** |
| | | |
| One step skill | **~1,700** | once, in the conversation that needs it |
| `dimensions/` compact digest (29 dims, with `tell`s) | 3,100 | step 8 only |
| `dimensions/` lean digest (no `tell`s) | 1,200 | steps 5, 9 |

Uploading the protocol into a Project costs roughly **forty times** what the
current step needs. So degraded mode does not upload the protocol. It loads one
step at a time — which is not a concession, it is this repo's existing
discipline: `claude-arsenal/AGENTS.md` keeps its references as "plain paths,
never `@` imports", and `CLAUDE.md` has a whole section on spending the window
deliberately. The weaker surface makes that rule matter more, not less.

**The boilerplate is factored out once.** Four blocks appear in **13/13** step
skills — the "say what is happening before a silence" rule, the "invite forward,
never close by offering to end the session" boundary, the mechanical-checkpoint
paragraph, and the acceptance-gate paragraph. Two of those describe machinery
that does not exist here. The other two are the manner, and they belong in the
Project's custom instructions, written once, instead of thirteen times.

## 3. What survives, step by step

This is the table to argue with. **Faithful** means a candidate would not be able
to tell from inside the conversation. **Degraded** means the step happens but
something load-bearing is estimated rather than computed. **Manual** means the
work moves to the candidate.

| # | step | | what survives | what is lost | verdict |
|---|---|---|---|---|---|
| 0 | identify | req | the greeting, the resolution order, the three-attempt cap | the `PreToolUse` containment hook — isolation becomes "one Project per person" | **faithful**, unenforced |
| 1 | intake | opt | CV upload (free tier takes files), claims-with-provenance, the 12-question cap | provenance is a recorded field, not a validated one | **faithful** |
| 2 | constraints | req | every field `stated`/`declined`/`unknown`, the 14-question cap | nothing material | **faithful** |
| 3 | history | opt | episodes, the 8-episode/18-question cap, the halfway check-in | nothing material | **faithful** |
| 4 | traits | opt | scoring from evidence, `insufficient` with a count, prose phrasing | the two-episodes-on-two-occasions floor depends on the state block's dates being kept honestly | **faithful**, if maintained |
| 5 | reactions | opt | reacting to real adverts, evidence rows of kind `reaction` | no live stimulus fetch, no corpus elicitation split — so the elicitation/eval separation cannot be enforced | **degraded** |
| 6 | preferences | opt | forced pairwise choices, salary-equivalent framing | part-worths are *estimated by the model*, not fitted; no roundtrip check | **degraded** |
| 7 | sourcing | req | — | connectors, robots.txt, rate limiting, normalisation, tombstone dedup, expiry | **manual** — the candidate pastes adverts, or web search substitutes |
| 8 | understanding | req | dimension values with verbatim evidence spans | the staged pipeline. Everything falls to the model, which is the one thing step 8 is designed to avoid, and it is the most expensive step here | **degraded**, costly |
| 9 | ranking | req | the ordered list, one cited reason per position | nothing material — a missing citation is visible on the page | **faithful** |
| 10 | feedback | opt | reactions and outcomes, the re-rank, the twice-only prompt cap | nothing material | **faithful** |
| 11 | application | opt | CV and letter content, claim-by-claim traceability, the three-round cap | no DOCX or PDF; output is text or an artifact | **faithful**, plain formats |
| 12 | interview_log | opt | preparation, questions, outcome, lessons | nothing material | **faithful** |

**Nine faithful, three degraded, one manual.** The losses are not scattered —
they land exactly where compiled code does the work: fetching (7), extracting
(8), and fitting (6). Everything that is *dialogue* survives, which is the half
the design says matters most.

## 4. Coverage without gates — the boundary that must not blur

Every step skill carries two different checks, and this repo is unusually strict
about not confusing them (D-21, and the exit codes in every
`run_checkpoint.py`):

- **Coverage** — "is every artefact this step produces present, and is nothing
  left outstanding in the recorded position?" It is a structural question about
  files.
- **The acceptance gate** — `constraint_field_resolution == 1.0`,
  `extraction_macro_f1 >= 0.75`, and eleven others. It measures whether those
  artefacts are any *good*, and it is a build-time measurement over a corpus.

**Coverage is reproducible here. Gates are not, for any of the thirteen.**

Coverage survives because it only ever asked whether a key exists and whether a
list is empty — a reader can answer that from the state block in §5, and the
answer is as true there as on disk. Gates do not survive because they measure
against a labelled corpus with code, and a chat has neither.

So degraded mode implements `coverage_met` and reports the gate as
**`unmeasured`** — never as passed. That word is already the repo's
(`claude-arsenal/references/evidence-gates.md`), and using it keeps a degraded
run legible next to a real one instead of quietly flattering it.

This is the single most important line in this document. The project's own
history is the argument: **T70 took ten defects across five review rounds, eight
of them introduced by the session fixing the previous one**, every one of them
behind a green gate. A mode with no gates at all must be loud about it, because
the failure it invites — a confident answer nothing checked — is the exact
failure the gates exist to catch.

## 5. The layout

Three pieces. Nothing is installed.

### 5.1 The Project — small, and it stays small

One Claude Project per person (free tier allows five). Its knowledge holds only
what nearly every step needs:

- the manner block from §2 — the two conversational rules, ~300 tokens;
- `dimensions-lean.json` — the compact digest, ~1,200 tokens;
- nothing else. **No step skills. No spec. No METHODS.**

Its custom instructions say: *this is a job-search conversation run from a
written protocol; the candidate will paste one step's protocol and their state
block at the start of each conversation; never invent a step, never claim a gate
was measured.*

### 5.2 The state block — a strict subset of the real schema

One JSON object the candidate carries between conversations. **Its field names
are the real ones**, so a degraded profile can later be converted into a real
`profiles/<handle>/` tree rather than re-interviewed. That is the property worth
protecting; everything else here is convenience.

```json
{
  "schema": "integral-degraded/1",
  "handle": "marcos",
  "display_name": "Marcos",
  "language": "es",
  "locale": "es-ES",
  "created_at": "2026-08-28",

  "current_step": "constraints",
  "position": { "covered": ["residence", "currency"], "outstanding": ["pay_floor"] },
  "completed_steps": ["identify", "intake"],
  "declined_steps": [],
  "profile_revision": 3,

  "claimed_facts": { "roles": [], "languages": [] },
  "constraints": {
    "residence": { "state": "stated", "value": "Barcelona, ES", "ev": "ev-000004" },
    "pay_floor":  { "state": "unknown" }
  },
  "traits": {},
  "weights": {},
  "offers": [],

  "evidence_tail": [
    { "id": "ev-000004", "recorded_at": "2026-08-28", "step": "constraints",
      "kind": "constraint", "dimensions": ["residence"], "text": "Lives in Barcelona.",
      "source": "conversation", "disclosure": "private" }
  ],
  "evidence_digest": { "count": 42, "folded_before": "ev-000030", "summary": "…" }
}
```

Field rules, taken from the code rather than invented:

- `kind` ∈ `episode` | `statement` | `reaction` | `constraint` | `outcome` | `retraction`
- `source` ∈ `conversation` | `cv_document` | `offer_reaction` | `interview`
- `disclosure` ∈ `private` | `approved_for_use` — private by default, and it stays
  private without a per-use approval (§6.2)
- constraint `state` ∈ `stated` | `declined` | `unknown` — never blank
- evidence ids match `^ev-\d{6,}$`
- a `retraction` row names what it suppresses; nothing else may

**`evidence_tail` plus `evidence_digest` is how the log stays bounded.** The real
tree keeps `evidence.jsonl` forever and recomputes derived state from it
(`status/plan.md`: "derived state recomputed, never migrated"). A context window
cannot hold "forever", so old rows are folded into a summary and dropped from the
block. This is lossy, and it is the second-biggest compromise after §4 — a folded
row can no longer be cited by id in step 11's traceability.

### 5.3 The per-step prompt

One conversation per step. It opens with exactly three things:

```
[paste: .claude/skills/step-NN-<name>/SKILL.md — minus its Checkpoint and Gate sections]
[paste: the state block]

Run this step. At the end, give me: (a) the updated state block as one JSON
code block, (b) any new evidence rows, and (c) a coverage line —
covered / outstanding / gate: unmeasured.
```

Stripping the Checkpoint and Gate sections is not tidying: they instruct the
model to run a script that is not there. Left in, they invite the one thing §4
forbids — a claim that a gate was met.

## 6. What this must never do

- **Never report a gate as passed.** `unmeasured` is the only honest word, and it
  goes in every step's closing line.
- **Never present estimated part-worths (step 6) as fitted.** Say the number is
  indicative.
- **Never claim isolation between candidates.** Two people sharing one Project
  share everything in it. The real tool refuses this at the tool layer; here it
  is an instruction, and an instruction is not a mechanism.
- **Never let a folded evidence row be cited** as though its id still resolves.

## 7. Still open — the owner's call

**`status/plan.md` lists "An interactive UI" as out of scope**: *"Step 9's card is
a filled template rendered to text or a page. Anything with state of its own
waits."* This document stays inside that line — it is prose and a paste
procedure, and it renders to text.

An HTML artifact holding the state block in `localStorage` would remove the
copy-paste entirely, and artifacts are available on the free tier. It is also
plainly "something with state of its own". So it is **not** proposed here. If it
is wanted, the out-of-scope line is what has to change first, deliberately, and
not as a side effect of shipping a degraded mode.

Two smaller ones:

- **Whether the parity table in §3 is right.** It was derived by reading all
  thirteen skills and the runtime, but it has not been run end to end with a real
  candidate. It is a claim to test, not a measurement — treat it the way this
  repo treats any unmeasured claim.
- **Where the digests live.** `dimensions-lean.json` and the manner block are
  generated projections of files already here. They should be generated by a
  script and checked, not maintained by hand, or they drift the first time a
  dimension changes.

## 8. What this does not change

Nothing in the real tool. No step, no gate, no schema. `docs/distribution.md`
stays the distribution decision for anyone who can run Claude Code; this is a
strictly poorer path for people who cannot, and it is written down so that its
poverty is visible rather than discovered.
