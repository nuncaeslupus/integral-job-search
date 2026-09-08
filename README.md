# integral-job-search

[![CI](https://github.com/nuncaeslupus/integral-job-search/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/nuncaeslupus/integral-job-search/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Candidate-centred integral job search: one dimension model, carried end to end.

Job tools match skills against requirements and stop. This one carries a single
vocabulary — how social the office is, whether "remote" means remote, whether the
schedule survives a school run — across every stage: the questions asked, the
evidence read out of an advert, the ranking, the CV, the interview.

**Where it is.** Usable, and used — it has been run end to end by its author, to
a sent application. The thirteen steps all exist and all have gates. What is
thinnest is **sourcing**: connectors exist for a handful of boards, so how many
real offers reach you depends on whether your field is one of them, and
[CONTRIBUTING.md](CONTRIBUTING.md) is about adding one. Expect to be the second
person using this, not the thousandth.

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

No Claude Code? [docs/simulation-prompt.md](docs/simulation-prompt.md) is a
prompt that simulates the conversation in a plain Claude chat. It saves nothing
and measures nothing, and it is not a replacement.

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

## Acknowledgements

The failure-handling layer of this tool is adapted from
[`MadsLorentzen/ai-job-search`](https://github.com/MadsLorentzen/ai-job-search)
(MIT, © 2026 Mads Lorentzen) — how a job board actually fails, written down by
someone who spent five weeks finding out. Robots handling that cannot fail
open, a connector health check with three verdicts rather than two, liveness
that reads page identity, the eligibility gate and its quoted reasons, the ATS
text-layer contract: each began as a report from that project.

What was taken, where each piece lives, and what the borrowing does **not**
extend to are recorded one row at a time in
[`docs/METHODS.md` §2.9](docs/METHODS.md). Its matching layer was assessed and
**not** adopted, and that judgement is recorded there too.

MIT requires notice retention for copied code, not attribution for ideas. Most
of the above is the second kind; this section is a commitment rather than a
licence obligation.
