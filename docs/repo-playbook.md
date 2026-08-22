# Repo playbook — the parts of `CLAUDE.md` that are not needed every turn

`CLAUDE.md` is resident on **every turn of every session**, so it carries only what
a session must have in front of it at all times: the protocol, what this surface
can and cannot do, how to spend the context window, and the local gate.

Everything below is needed at *one moment* in a session — when upgrading the
bundle, when adding a skill, when parking a task — so it is a file to open, never
an import. This is the same split `claude-arsenal/AGENTS.md` makes with its
`references/` directory, and for the same reason.

## Installing and updating claude-arsenal

**The skills live in this repo, committed.** That is what makes them work
everywhere. A cloud session — Claude Code on the web, `claude --cloud`, the apps,
routines — runs on a fresh clone on another machine, never reads your
`~/.claude/`, and does not install plugins your repository asks for. Upstream
verified that against a live session rather than inferring it from docs
(`claude-arsenal#200`): with a correct declaration committed, the marketplace
public and the pinned tag returning 200 from inside the sandbox,
`known_marketplaces.json` was absent and `installed_plugins.json` empty.

`/init` is the whole update. It vendors the skills into `.claude/skills/`,
refreshes `claude-arsenal/`, and wires the skill-edit gate into
`.claude/settings.json`.

```text
/plugin marketplace update claude-arsenal   # refresh the clone FIRST
/plugin update claude-arsenal               # then the plugin
/init
```

No plugin on this machine? The same script runs straight from a clone, which is
also the way to pin a version deliberately:

```bash
git clone --depth 1 --branch v2.0.0 https://github.com/nuncaeslupus/claude-arsenal.git /tmp/arsenal
python3 /tmp/arsenal/plugins/core/skills/init/scripts/init.py --repo-path .
```

Then commit — `/init` writes, it does not commit.

**Two failure modes, both silent, both hit here on 2026-08-22.**

`/plugin update` re-reads the marketplace clone; it does not refresh it. With a
stale clone it re-installs what is already there and reports nothing. And a
failed install leaves the **old** version registered: v1.0.0 shipped
`plugins/core` with a bare-string `author` where the loader wants an object, so
`core` would not register and this machine sat on 0.1.0 from months earlier —
missing `init`, `continue`, `queue-add`, `queue-status` and `gate-check`
entirely — while the marketplace looked healthy. Check what is *registered*
rather than what you asked for:

```bash
python3 -c "import json,pathlib;d=json.load(open(pathlib.Path.home()/'.claude/plugins/installed_plugins.json'));print({k:[e['version'] for e in v] for k,v in d['plugins'].items() if 'arsenal' in k})"
```

Fixed upstream in v1.0.1 along with `make validate-manifests`, which now refuses
a manifest the loader would reject before it can be tagged.

**After any update, run `make reader` and `make evidence`.** An update can change
`create_reader.py`, which leaves the generated spec readers stale. Both are
caught by the suite — the point is that they are *expected*, and are fixed with
the repo's own tooling, never by hand. Use `reader-steps` or `reader-process`
rather than `reader` unless you changed both: `reader` stamps a fresh date into
the document you did not touch.

## The skill listing budget lives in `arsenal/config.toml`

`listing-budget = 13000` (S10). `integral.skill_budget` and `skill-creator`'s
`audit_library.py` both read that key since v0.33.0 (`claude-arsenal#143`).

`listing-budget = 11000` since T58 — down from 13,000, because v2.0.0 trimmed
seven oversized descriptions and dropped `lsp-setup` and the old `skill-creator`.
The library measures 9,231 chars over 31 skills with 1,769 spare, which is the
same headroom discipline S10 chose originally (~5 more skills), not the tightest
legal number.

`integral.skill_budget` is the gate: it refuses a budget that is not a round
multiple of 1,000 or that leaves under 400 chars of headroom, and reports `-1` —
not a clean zero — when the library is inside a budget that was overridden, fell
back, or was fitted to the measurement. **Do not silence it by raising the
number.**

The listing is resident context on every turn, and a new skill's `description` is
paid for in every session including the ones that never load it.

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
