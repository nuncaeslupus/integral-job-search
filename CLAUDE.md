<!-- claude-arsenal: auto-managed -->
## Automatic session protocol

Every session, without waiting to be asked:

1. Read `arsenal/session/handover.md` for the previous session's context.
2. List the repository's issues labelled `arsenal:task` — **open and closed** — and
   save the JSON. Use whatever GitHub access this surface has; run
   `claude-arsenal/bin/github_channel.sh --detect` to find out which. Request
   `number`, `title`, `state`, `labels`, `assignees` and **not `body`** — the bodies
   are the bulk of that fetch and nothing downstream reads them.
3. Run `python3 claude-arsenal/scripts/query_status.py --issues <that file>` for the
   board, and report anything it flags.
4. Pick up work: `python3 claude-arsenal/scripts/task_select.py --issues <that file>`
   returns the next unblocked task, then
   `bash claude-arsenal/bin/claim_task.sh <id>` takes it (see `@claude-arsenal/AGENTS.md`).
   - **Nothing returned + workspace plans exist** → seed tasks from each plan.
   - **Nothing at all** → ask what to work on.
5. Open each task's PR with `Closes #<issue>` so merging it closes the task by itself.
6. After any session with tasks: update `arsenal/session/handover.md`.

@claude-arsenal/AGENTS.md
<!-- /claude-arsenal: auto-managed -->

<!-- host-owned: not managed by claude-arsenal -->
## Reading the board — the plain `--issues` path works again

`claude-arsenal` v0.28.0 stopped keying task identity on an HTML comment, and
v0.33.0 stopped `handle_sync.py` proposing handles for archived tasks. Steps 3
and 4 of the protocol above therefore need no workaround — run them as written,
and open an issue for anything `handle_sync.py` prints (normally nothing).

```bash
# fetch with MCP list_issues, labels=["arsenal:task"], open AND closed,
# fields number/title/state/labels/assignees — NOT body; save to $ISSUES
python3 claude-arsenal/scripts/query_status.py --issues "$ISSUES"
python3 claude-arsenal/scripts/task_select.py  --issues "$ISSUES"
```

`state_from_issues` warns when issues were fetched and **none** resolved to a
task, so an empty selection can no longer look healthy.

**v0.36.0 dropped `body` from that fetch**, which on this 40-issue board is
~9k tokens down to ~1.2k: `task_id_from_issue` falls back to matching the issue
**title** against the task files' `title:`. Nothing had ever compared those two
strings before, and both sides were spelling titles differently — fourteen live
tasks silently stopped resolving. **v0.36.1 closed all of it**
(`claude-arsenal#186`), on all four fronts:

- `normalise_title` HTML-unescapes, so a title holding `<offer_id>` matches the
  `&lt;offer_id&gt;` the MCP tool returns;
- the front-matter parser decodes `\uXXXX` inside a double-quoted scalar, as a
  real YAML parser would, falling back to the literal reading when the scalar is
  not valid JSON;
- `issue_import.py` and `arsenal_migrate.py` write titles with
  `ensure_ascii=False`, so no new task file carries `\u20ac` for a euro sign;
- `handle_sync.py` warns on a **near** title match instead of proposing a
  handle, so an unresolved-but-similar issue can no longer become a duplicate.

Nothing here needs doing by hand any more. The 36 task files whose titles this
repo decoded are already correct, and both halves of the escaping problem are
fixed at the source.

`query_status.py` remains the detector for this class of failure: it names
exactly which tasks did not resolve. **Trust that list over `handle_sync.py`'s
proposals** — only one of the two is wired to an action, which is why the
near-match guard was added to the one that is.

## `make arsenal-remote` reports; `make arsenal-upgrade REF=…` upgrades

`check_update.sh` without `--check-only` performs the subtree merge **and
commits** — a history-writing side effect from a step described as a report. So
`arsenal-remote` passes `--check-only`; reading a version should not write
history. Upgrade deliberately with `make arsenal-upgrade REF=v0.x.y`, which runs
all four steps (v0.33.0 fixed `claude-arsenal#170`: it re-vendors skills after a
subtree update and refuses to report success on a stale bundle).

**After any upgrade, run `make reader` and `make evidence`.** An upgrade can
change `create_reader.py` and the bundle's asset count, which leaves the
generated spec readers and S9's evidence stale. Both are caught by the suite —
the point is that they are *expected* after an upgrade, and are fixed with the
repo's own tooling, never by hand.

## The skill listing budget lives in `arsenal/config.toml`

`listing-budget = 13000` (S10). `integral.skill_budget` and `skill-creator`'s
`audit_library.py` both read that key since v0.33.0 (`claude-arsenal#143`).

`integral.skill_budget` is the gate: it refuses a budget that is not a round
multiple of 1,000 or that leaves under 400 chars of headroom, and reports `-1` —
not a clean zero — when the library is inside a budget that was overridden, fell
back, or was fitted to the measurement. The audit's "within 10% of 13000"
warning is the budget working: 862 chars spare, revisit at roughly three more
skills. **Do not silence it by raising the number.**

**Parking a task needs the `arsenal:cancelled` label.** `state_reason` is not
available through these MCP tools, so upstream reads any closed issue as `done`
without it, and closing a task issue to park it silently releases everything
downstream. Prefer keeping it **open** and holding it out of selection with
`requires:` — that is what #71 does — and use the label only for work genuinely
abandoned.

## Searching this repository without burning the context window

`.rgignore` excludes the vendored and generated trees — `vendor/`,
`claude-arsenal/bin|scripts/`, the generated spec readers — from every
ripgrep-backed search, for the same reason `pyproject.toml` excludes them from
ruff and mypy: they are not ours to change, a fix inside one is reverted by the
next refresh, and `vendor/claude-arsenal/docs/research/` alone is a 2.9MB
document whose lines run to thousands of words each. Search one deliberately
with `rg -u --no-ignore-vcs` or by naming its directory.

**The corpus is the expensive one, and it is not excluded**, because it is real
project data worth searching. `corpus/raw/ads.jsonl` and
`corpus/labelled/ads.jsonl` are 100 lines each, and a line is a whole job
advert — the longest is **15,640 characters**. One content match returns the
entire advert, so an unbounded content search across both files can return
100KB in a single result. Against the corpus:

- count or list files first (`rg -c`, `rg -l`, or `output_mode` other than
  `content`), and only then read the specific record;
- read a record with `python3 -c` and `json.loads`, projecting the fields you
  need, rather than grepping the raw line;
- if you do need content mode, pass `-o` so only the match comes back, or a
  small `head_limit`.

The same applies to `corpus/labelled/suggestions.json` and any generated
`status/evidence/*.json` with a `readings`/`checks` array: project the key you
want, do not print the file.

## Known environment state

**GitHub Actions is out of runner minutes until the next billing period
(noted 2026-08-19).** Every job on every workflow run fails in 3–5 seconds with
`runner_id: 0` and `runner_name: ""` — no runner is ever assigned. This affects
`main` as much as any branch: run #142 on `ba7c980` (main's own HEAD) failed
identically, while the last green run was #137. It is not caused by any diff.

Do not treat a red CI on this repository as a signal about the code, and do not
push speculative "fixes" for it. Diagnose it once by checking a failed job for
`runner_id: 0` plus a sub-5-second duration; if both hold, it is this.

**Run the gate locally instead** — these are exactly what CI would run, and all
five must pass before a merge:

```bash
make lint           # ruff + strict mypy
make test           # pytest
make evidence       # regenerate every measurement, fail on drift
make verify-subtree # the arsenal bundle matches its subtree
make verify-gates   # every done/merged task can still show its measurement
```

Remove this section once runs are completing with real durations again.
