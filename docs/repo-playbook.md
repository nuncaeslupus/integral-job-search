# Repo playbook — the parts of `CLAUDE.md` that are not needed every turn

`CLAUDE.md` is resident on **every turn of every session**, so it carries only what
a session must have in front of it at all times: the protocol, what this surface
can and cannot do, how to spend the context window, and the local gate.

Everything below is needed at *one moment* in a session — when upgrading the
bundle, when adding a skill, when parking a task — so it is a file to open, never
an import. This is the same split `claude-arsenal/AGENTS.md` makes with its
`references/` directory, and for the same reason.

## `make arsenal-remote` reports; `make arsenal-upgrade REF=…` upgrades

`check_update.sh` without `--check-only` performs the subtree merge **and commits**
— a history-writing side effect from a step described as a report. So
`arsenal-remote` passes `--check-only`; reading a version should not write history.
Upgrade deliberately with `make arsenal-upgrade REF=v0.x.y`, which runs all four
steps (v0.33.0 fixed `claude-arsenal#170`: it re-vendors skills after a subtree
update and refuses to report success on a stale bundle).

**After any upgrade, run `make reader` and `make evidence`.** An upgrade can change
`create_reader.py` and the bundle's asset count, which leaves the generated spec
readers and S9's evidence stale. Both are caught by the suite — the point is that
they are *expected* after an upgrade, and are fixed with the repo's own tooling,
never by hand.

## The skill listing budget lives in `arsenal/config.toml`

`listing-budget = 13000` (S10). `integral.skill_budget` and `skill-creator`'s
`audit_library.py` both read that key since v0.33.0 (`claude-arsenal#143`).

`integral.skill_budget` is the gate: it refuses a budget that is not a round
multiple of 1,000 or that leaves under 400 chars of headroom, and reports `-1` —
not a clean zero — when the library is inside a budget that was overridden, fell
back, or was fitted to the measurement. The audit's "within 10% of 13000" warning
is the budget working. After the step-skill preamble trim the library measures
11,241 chars with 1,759 spare; revisit at roughly five more skills.
**Do not silence it by raising the number.**

The listing is itself resident context — roughly 13,000 characters on every turn,
the largest single block this repo controls. A new skill's `description` is paid
for on every turn of every session, including the sessions that never load it.

## Parking a task needs the `arsenal:cancelled` label

`state_reason` is not available through these MCP tools, so upstream reads any
closed issue as `done` without it, and closing a task issue to park it silently
releases everything downstream. Prefer keeping it **open** and holding it out of
selection with `requires:` — that is what #71 does — and use the label only for
work genuinely abandoned.

## Why the board resolves issues by title

**v0.36.0 dropped `body` from the board fetch**, which on this 40-issue board is
~9k tokens down to ~1.2k: `task_id_from_issue` falls back to matching the issue
**title** against the task files' `title:`. Nothing had ever compared those two
strings before, and both sides were spelling titles differently — fourteen live
tasks silently stopped resolving. **v0.36.1 closed all of it**
(`claude-arsenal#186`), on all four fronts:

- `normalise_title` HTML-unescapes, so a title holding `<offer_id>` matches the
  `&lt;offer_id&gt;` the MCP tool returns;
- the front-matter parser decodes `\uXXXX` inside a double-quoted scalar, as a real
  YAML parser would, falling back to the literal reading when the scalar is not
  valid JSON;
- `issue_import.py` and `arsenal_migrate.py` write titles with
  `ensure_ascii=False`, so no new task file carries `€` for a euro sign;
- `handle_sync.py` warns on a **near** title match instead of proposing a handle,
  so an unresolved-but-similar issue can no longer become a duplicate.

Nothing here needs doing by hand any more. The 36 task files whose titles this repo
decoded are already correct, and both halves of the escaping problem are fixed at
the source. `query_status.py` remains the detector for this class of failure.
