# Repo playbook — the parts of `CLAUDE.md` that are not needed every turn

`CLAUDE.md` is resident on **every turn of every session**, so it carries only what
a session must have in front of it at all times: the protocol, what this surface
can and cannot do, how to spend the context window, and the local gate.

Everything below is needed at *one moment* in a session — when upgrading the
bundle, when adding a skill, when parking a task — so it is a file to open, never
an import. This is the same split `claude-arsenal/AGENTS.md` makes with its
`references/` directory, and for the same reason.

## Installing and updating the arsenal plugins

Upstream is a Claude Code **marketplace**, not a vendored tree (T58). There is
nothing in this repository to pull or verify; the plugins live under
`~/.claude/plugins/` and are managed from inside a session:

```text
/plugin marketplace add github:nuncaeslupus/claude-arsenal
/plugin install skill-workshop@claude-arsenal   # first — its hook gates skill edits
/plugin install core@claude-arsenal
```

**Updating takes two commands, and the first is the one that gets forgotten.**
`/plugin update claude-arsenal` re-reads the marketplace clone; it does not
refresh it. If that clone is behind, the update re-installs what is already
there and reports nothing:

```text
/plugin marketplace update claude-arsenal
/plugin update claude-arsenal
```

**A failed install leaves the old version registered and says so only once.**
v1.0.0 shipped `plugins/core` with a bare-string `author` where the loader wants
an object, so `core` would not register and the consumer stayed on whatever they
had — 0.1.0, from months earlier, missing `init`, `continue`, `queue-add`,
`queue-status` and `gate-check` entirely. Check what is actually registered
rather than what you asked for:

```bash
python3 -c "import json,pathlib;d=json.load(open(pathlib.Path.home()/'.claude/plugins/installed_plugins.json'));print({k:[e['version'] for e in v] for k,v in d['plugins'].items() if 'arsenal' in k})"
```

That bug is fixed upstream in v1.0.1 along with `make validate-manifests`, which
now refuses a manifest the loader would reject before it can be tagged.

**After any update, run `make reader` and `make evidence`.** An update can change
`create_reader.py`, which leaves the generated spec readers stale. Both are
caught by the suite — the point is that they are *expected* after an update, and
are fixed with the repo's own tooling, never by hand.

**Never reference a plugin file by a literal path.** Use
`uv run python -m integral.plugin_path <plugin> <relative-path>`. It reads
`installed_plugins.json`, so it returns the version that is actually registered;
the plugin cache also holds every version ever fetched, including ones the
loader refused, and a glob for "the newest directory" will happily return one of
those.

## The skill listing budget lives in `arsenal/config.toml`

`listing-budget = 13000` (S10). `integral.skill_budget` and `skill-creator`'s
`audit_library.py` both read that key since v0.33.0 (`claude-arsenal#143`).

`listing-budget = 5000` since T58, and the number covers **this repository's
fourteen skills only** — the thirteen step skills plus `test-mode`. The nineteen
arsenal skills that used to sit beside them are plugins now, and upstream
budgets its own with `make audit`. The library measures 3,958 chars with 1,042
spare.

`integral.skill_budget` is the gate: it refuses a budget that is not a round
multiple of 1,000 or that leaves under 400 chars of headroom, and reports `-1` —
not a clean zero — when the library is inside a budget that was overridden, fell
back, or was fitted to the measurement. **Do not silence it by raising the
number.**

The listing is resident context on every turn, and a new skill's `description` is
paid for in every session including the ones that never load it. Note the *total*
a session pays is still the host's fourteen plus every installed plugin's — this
gate covers the half this repository controls, which is the half it can fix.

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
