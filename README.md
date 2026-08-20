# integral-job-search

Candidate-centred integral job search: one dimension model, carried end to end.

Job tools match skills against requirements and stop. This one carries a single
vocabulary — how social the office is, whether "remote" means remote, whether the
schedule survives a school run — across every stage: the questions asked, the
evidence read out of an advert, the ranking, the CV, the interview.

## Using it

```
git clone https://github.com/nuncaeslupus/integral-job-search.git
cd integral-job-search
claude
```

Then talk. There is no command to learn and nothing to install by hand — the
first session says what it is installing and does it once.

It runs as a conversation in thirteen steps, from working out who you are through
to logging an interview. A step ends when a checkpoint script says it does, not
when it feels finished. You can stop and resume across sessions.

Requires [Claude Code](https://claude.com/claude-code), Python 3.12+, and
[uv](https://docs.astral.sh/uv/).

## Your data stays yours

Nothing you say is written inside this repository. Your profile lives in
`~/.integral-job-search/` (or `$INTEGRAL_HOME`), and the resolver *refuses* any
path inside a git work tree rather than warning about it — see
[docs/distribution.md](docs/distribution.md) §2.

## Working on the tool

```
make sync     # install, with dev dependencies
make ci       # everything CI runs, in CI's order
make help     # every target
```

- [status/specification.md](status/specification.md) — the argument
- [docs/METHODS.md](docs/METHODS.md) — every technique and formula
- [docs/product-shape.md](docs/product-shape.md) — why a conversation, not a CLI
- [docs/distribution.md](docs/distribution.md) — how it is installed and where state lives

MIT licensed.
