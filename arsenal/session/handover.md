# Session handover

**2026-09-04 (evening).** Board: **140 tasks merged**, `verify-gates` 140/140,
2767 tests. This session merged **13** PRs and left nothing in flight. Two things
changed about how work gets checked here, and both are load-bearing for the next
session.

## 1. There is no CI, and the substitute has to be named in the merge commit

The account spent its **2000 monthly Actions minutes in four days** and ran dry
today. Runs still fire and still fail — in **4 to 6 seconds**, with every log a
404. That is the runner dying before any job body ran, and it says nothing about
the code. **Read `created_at` and `updated_at`, not the conclusion.**

`tools/verified_gate.sh <sha>` is the substitute, and CLAUDE.md now says so. It
resolves the ref, checks that commit into a throwaway detached worktree, clears
bytecode, runs `make host-gate` and prints a verdict block. Three rules, and the
third is the one that gets skipped:

- paste the block on the PR;
- quote the four results in the merge commit;
- **merge only while the head is still the SHA the block names.**

Both merges today did all three. #307 and #338 each carry their block and their
numbers in the squash message.

## 2. The second-reader rule now costs four or five rounds, and earns them

`merge-policy` is still `after-ci-and-review` and CodeRabbit is gone (Free plan:
walkthroughs only, no findings). Every review round today was an independent
session. The measured result:

| PR | rounds | findings fixed with a committed fixture |
|---|---|---|
| #307 (T98) | 5 | 8 |
| #338 (T109) | 4 | 9 |

**Every round found something, including rounds reviewing the previous round's
fix.** What each round found, though, changed shape — and that is the useful
part:

- **Rounds 1–2 found defects in shipped behaviour.** #338's F1 was live: a
  top-level key literally named `Filters.inner` rendered identically to the
  nested pair `Filters` → `inner`, so the second-occurrence check compared two
  different positions as equal and sent the literal text `{page}` on the wire.
- **Rounds 3–5 found defects in the *previous round's fixtures*.** Nothing in
  shipped behaviour. `corpus_scope.py` was AST-identical for two rounds and
  `connectors.py` byte-identical for one before each merged.

**The stopping rule used, and it is a proposal not a ruling:** merge when a
round's findings are confined to fixtures and prose, the shipped behaviour is
provably unchanged from a commit an earlier read cleared, and every named
finding is fixed and mutation-verified. The owner was asked to confirm this and
has not yet answered — the question stands.

### The three failure shapes worth carrying forward

Each was met more than once today, by me, in the act of fixing the previous one.

1. **A fixture that passes in the exact state it was written to catch.** #307's
   F1 asserted a message was in `unmeasured_reason`, which joins breaches and
   untrusted readings — so it held whichever list the floor was appended to, and
   the classification was the whole point.
2. **A fixture parametrised over the thing it pins.** #307's F2: widening
   `STIMULUS_STRUCTURAL_DEPENDENCIES` left the suite green *and added two
   passing tests*. The widening manufactured its own certificate.
3. **A finding answered with a fixture on the wrong function.** #307's fifth
   round: the deferred-import claim lives on `exempt_reader_findings`, and both
   fixtures I added drove the *other* scanner. Mutating the one the docstring
   talks about stayed green across 2722 tests.

And one rule that keeps recurring: **an assertion taken over an all-zero reading
holds for any subset of what it sums.** `corpus_measurement_set_violations` was
asserted over the real corpus, where all five components are zero — so dropping
three of the five was green. Each component is driven non-zero on its own now.

## What is open

| | |
|---|---|
| **#336** T122 | the two gate readers disagree about what declaring a gate means, and the disagreement resolves to pass |
| **#337** T123 | a metric named after a category is satisfiable by there being none of them |
| **#339** (queue) | 28 elicitation-split adverts from a robots-blocked board are reachable as stimuli — `check_stimulus` early-returns for `source == "corpus"` |
| **#340** (queue) | `build_list_urls` ignores `pagination.start` with no test noticing; a 0-indexed board's URLs silently start at page 1 |
| **#124** T59 | reopened — it was closed-as-completed while its task file is live and `requires: [access:human]`. Needs a person at the keyboard to label. |

#339 and #340 carry the `arsenal:queue` label, so **run step 4b** (`issue_import.py
--apply`) before selecting work, or `handle_sync.py` will propose duplicates.

## Small things that cost time today

- **`open_task_pr.sh` runs `make evidence`, which diffs against the index.** A
  legitimately-changed committed evidence file therefore reads as drift and the
  script refuses. `git add -A` first, then run it — the script's own `git add -A`
  is idempotent.
- **`uv sync --all-extras` in a worktree breaks `make lint`.** It installs
  `pypdf`, which makes `cv_store.py`'s `type: ignore[import-not-found]` unused
  and mypy fails. Use `uv sync --extra dev` — that is what CI ran.
- **A `pkill` on pytest does not kill its bash parent**, which keeps running the
  4-minute gate. Kill the shell.
