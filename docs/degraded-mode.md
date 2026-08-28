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
| The checkpoints | `scripts/run_checkpoint.py`, `src/integral/` | absent — **no repository execution**: the sandbox has no clone of this repository, and `integral` is not installable from anywhere (nothing here is published to PyPI, `docs/distribution.md` §7), so `import integral.*` cannot resolve |
| The candidate store | `$INTEGRAL_HOME/profiles/<handle>/` | absent — **no durable `$INTEGRAL_HOME`**: sandbox storage is per-conversation and does not survive it |
| The containment hook | `PreToolUse` (S3) | absent — no hooks |

Only the first is prose, and prose is the half that carries the *manner*. That
is the whole reason a degraded mode is worth having: the elicitation instrument
is the conversation (`docs/product-shape.md`), and the conversation survives.

**Two of those rows are narrower than they look.** Claude does have sandboxed
code execution and file creation, and it is not a paid-only capability, so
"there is no code here at all" would be wrong. Nor is the sandbox necessarily
offline — network access to package managers is a setting, and commonly on, so
an ordinary dependency can usually be installed. What is missing is specific and
survives both of those: the checkpoints cannot run because `integral` exists
only in this repository and is published nowhere, and the store cannot persist
because the sandbox is thrown away with the conversation. §7 records what that
leaves on the table.

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

`req` is a **required** step (§2.5 — it cannot be declined); `opt` is an
**offered** one.

| # | step | req? | what survives | what is lost | verdict |
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

Its custom instructions say: *this is a conversation about finding work, run
from a written protocol; the candidate will paste one step's protocol and their
state block at the start of each conversation; never invent a step, never claim
a gate was measured.*

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
    "residence": { "state": "stated", "value": "Barcelona, ES", "ev": "ev-000041" },
    "pay_floor":  { "state": "unknown" }
  },
  "traits": {},
  "weights": {},
  "offers": [],
  "applications": {},

  "evidence_tail": [
    { "id": "ev-000041", "recorded_at": "2026-08-28", "step": "constraints",
      "kind": "constraint", "dimensions": ["residence"], "text": "Lives in Barcelona.",
      "source": "conversation", "disclosure": "private" }
  ],
  "evidence_digest": { "count": 42, "folded_before": "ev-000030", "summary": "…" }
}
```

**`folded_before` is exclusive.** Every row with an id below it has been folded
into `summary` and is gone from `evidence_tail`; every row from it onward is
present in full. Above: 42 rows recorded, `ev-000001`–`ev-000029` folded,
`ev-000030`–`ev-000042` retained (one shown).

**Nothing outside `evidence_digest` may cite a folded id.** `constraints.*.ev`,
and every other back-reference, must name a row still in `evidence_tail` — which
is why `residence` cites `ev-000041` and not the older row it started from. Fold
late, and re-point any citation you are about to orphan.

Field rules, taken from the code rather than invented:

- `kind` ∈ `episode` | `statement` | `reaction` | `constraint` | `outcome` | `retraction`
- `source` ∈ `conversation` | `cv_document` | `offer_reaction` | `interview`
- constraint `state` ∈ `stated` | `declined` | `unknown` — never blank
- evidence ids match `^ev-\d{6,}$`
- `retracts` holds **exactly one** evidence id, as a string, and only a
  `retraction` row may set it — matching `EvidenceRow`, where it is
  `str | None`. It is never a list and never free text: two retractions are two
  rows. A reader must drop every retracted row before using the block, and a row
  already folded into `evidence_digest` can no longer be retracted at all, which
  is the third reason to fold late.

**`disclosure` stays `private` on every row, always.** This is the one field
where the obvious design is the wrong one. Nothing in `src/integral/` ever
writes `approved_for_use` onto an evidence row, and that is deliberate:
approval is not a property of a remembered sentence, it is a property of *one
sentence going into one document*. A flag on the row would be exactly the
standing permission process spec §6.2 forbids — flip it once for an application
in March and it is still flipped in June, for an employer nobody has mentioned
yet.

So degraded mode does not invent a representation for this. **`src/integral/approval.py`
is the authority, and `applications` mirrors its files rather than restating
them** — three separate records per application, not one map:

| real file | holds | in the block |
|---|---|---|
| `cv/generated/<offer_id>/v<N>/approvals.json` | `episodes` — each an `(offer_id, version, text)` approval | `applications["<offer_id>/v<N>"].approvals` |
| `cv/generated/<offer_id>/v<N>/payload.json` | `recipient`, `documents`, `claims`, `episodes`, `contact_details` | `.payload` |
| `applications/<offer_id>/v<N>.json` | `confirmed_digest`, `sent_at` — written only on send, **immutable** | `.sent` |

Copy the field names exactly. The send record's digest is `confirmed_digest`, not
`payload_digest`; `payload_digest()` is the *function* that computes it from
`payload.json`. Getting this wrong is not cosmetic — the whole reason the block
uses real field names is so it converts instead of needing a re-interview.

An approval names the **text**, never a row id and never a list position: a
position in a list the candidate edits is not a stable name for a sentence.
Inserting an unrelated episode above an approved one used to invalidate the
approval, and editing one used to leave the old approval sitting there.

The rules, all from §6.2, step 11 and `record_sent`:

- **Only step 11 writes an approval**, and only after showing the candidate the
  finished CV and letter and naming every stored claim inside them.
- **The unit is the payload, not the question.** Not "shall I apply?" but the
  actual contents — which documents, which claims, which episodes, which contact
  details, to whom. What the candidate confirms is *that* payload, by its digest.
- **Re-read the evidence at the send boundary — and here degraded mode is
  deliberately stricter than the tool, because the tool has a hole.** An earlier
  draft of this document claimed a retracted episode stops being sendable. That
  is false, and the code says so in as many words: `measure_prepared` backs an
  episode line by `approvals.json` **and nothing else** — *"an episode line is
  backed by the approval file and nothing else: the store is a thing the
  candidate edits, and routing an episode's authority through a list position
  was how reordering a story bank turned into a gate failure."* Retraction never
  touches `approvals.json`, so the approval survives it, the line stays backed,
  and `record_sent` proceeds. Approve for `v1`, retract the episode, send `v1`:
  it goes. See §7 — that is a fail-open in `approval.py`, not in this file.
  Degraded mode therefore adds the check the tool omits: before recording a send,
  walk every episode line and confirm a **surviving, unretracted, unfolded** row
  still backs it. This is the one place this document knowingly departs from the
  implementation, and it departs toward refusing.
- **Three refusals at the send boundary**, from `record_sent`: any unapproved
  disclosure refuses; a confirmation that does not name this exact payload
  refuses; an application already recorded as sent refuses, because that record
  is immutable — it is what the candidate answers questions about later.
- **A new version needs new approvals.** `v2` inherits nothing from `v1`; a
  regenerated letter is a new thing to consent to.
- **A new offer inherits nothing at all.** There is no key under which a March
  approval could be read for a June application, which is what makes "never as a
  standing permission" a shape rather than a promise.
- Recounting a failure to the tool is not consent to send it to a company.

Everything else about this mechanism stays in `approval.py`, deliberately. A doc
that restates a schema drifts from it; a doc that points at it cannot.

**`evidence_tail` plus `evidence_digest` is how the log stays bounded.** The real
tree keeps `evidence.jsonl` forever and recomputes derived state from it
(`status/plan.md`: "derived state recomputed, never migrated"). A context window
cannot hold "forever", so old rows are folded into a summary and dropped from the
block. This is lossy, and it is the second-biggest compromise after §4 — a folded
row can no longer be cited by id in step 11's traceability.

### 5.3 The per-step prompt

One conversation per step. It opens with exactly three things:

```text
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

**A retracted episode stays sendable — a fail-open in `approval.py`, found
while writing this and not yet fixed.** This is not a degraded-mode question and
it does not go away if this document is never adopted.

`measure_prepared` backs an episode line by `approvals.json` alone:

```python
if claim.section == "episodes":
    if claim.text in approved:      # approvals.json; the evidence log is not consulted
        backed[(claim.document, claim.text)] += 1
    continue
```

Nothing invalidates an approval when its evidence is retracted — `approval.py`
never mentions retraction, `retraction.py` never mentions approval, and the
backing check above never reaches the log. So: approve an episode for
`<offer>/v1`, retract it, then send `v1` — `record_sent` re-measures, finds the
line backed, and records the send. The retraction does not reach the document.

It is narrow (the window is between approving a version and sending it, which
`record_sent`'s own docstring acknowledges as real: *"a file can change between
drafting and sending"*) and it is **fail-open**, which §6.2 weights above
everything: the check said yes to precisely what it exists to refuse. The
episode-backed-only-by-approval rule is deliberate and correct for its own
reason — list positions were unstable — so the fix is not to reinstate a store
lookup, but to invalidate or re-confirm approvals when a retraction lands.

Owned by **T46**, needs a failing test first. Recorded here rather than fixed
because it is outside this document's diff, and recorded at all because an
earlier draft of §5.2 asserted the opposite and was believed for three commits.

Three smaller ones:

- **Whether the ephemeral sandbox can give back a real coverage check.** §1 notes
  that code execution exists, dependencies are usually installable, and only
  *this repository* is missing. §4's coverage half asks nothing of this
  repository — it reads keys off the state block and checks a list is empty. A
  single self-contained validator script, pasted with the step, could therefore
  compute `coverage_met` instead of the model eyeballing it, which is the one
  piece of measurement this mode need not have given up. It would still not be a
  gate. Worth a spike before anyone writes the generator in the next bullet.
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
