# integral-job-search

<!-- claude-arsenal:attribution: added by claude-arsenal's /init. Delete this block to drop it (it is not put back), or set `attribution = false` in the arsenal config.toml. -->
[![Built with claude-arsenal](https://img.shields.io/badge/built%20with-claude--arsenal-d97756)](https://github.com/nuncaeslupus/claude-arsenal)
<!-- /claude-arsenal:attribution -->

[![CI](https://github.com/nuncaeslupus/integral-job-search/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/nuncaeslupus/integral-job-search/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

<p align="center">
  <img src="https://raw.githubusercontent.com/nuncaeslupus/integral-job-search/main/docs/hero.png" width="100%" alt="integral-job-search: five dimensions such as remote arrangement and commute burden drawn as lines through five stages, from what you need, through the advert's quoted evidence, the ranking, the CV and the interview, each stage written in the same terms">
</p>

**A candidate-centred job search that runs as a conversation in Claude Code, judging every offer in terms of what you actually need.**

Job tools match skills against requirements and stop. This one carries a single
dimension model (how social the office is, whether "remote" means remote,
whether the schedule survives a school run) through every stage: the questions
it asks you, the evidence it quotes from each advert, the ranking, the CV and
letter, and the interview. Each step ends when a checkpoint script says so, not
when it feels finished.

## Quick start

Requires [Claude Code](https://claude.com/claude-code), Python 3.12+ and
[uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/nuncaeslupus/integral-job-search.git
cd integral-job-search
claude
```

Then talk. There is no command to learn: a SessionStart hook installs the
dependencies on first run and says so. You can stop and resume across sessions.

No Claude Code? [docs/simulation-prompt.md](docs/simulation-prompt.md) simulates
the conversation in a plain Claude chat. It saves nothing and measures nothing.

## Example

Step 0 resolves who you are with one script call before any profile is touched.
On a fresh data directory:

```console
$ uv run python -m integral.step0_open open
{"outcome": "create", "handle": null, "say": "I don't have a profile for you yet — what would you like to be called?", "last_activity": null, "offered": []}
```

Claude relays `say` to you verbatim. Every later step works the same way: the
skill drives the conversation, and a script records the result and decides
whether the step is done.

Every stage reads the same dimension files. An excerpt of
`dimensions/commute_burden.yaml`:

```yaml
id: commute_burden
kind: hard
group: requirements
definition: >
  What the advert requires of you in order to reach the work at all: living locally,
  holding a driving licence, or providing your own vehicle. ...
levels:
  - value: 0.0
    tell: "nothing is said about where you live or how you get there"
  - value: 0.5
    tell: "living in the area is required or preferred"
  - value: 0.9
    tell: "a driving licence or your own vehicle is stated as required"
elicitation:
  questions:
    - id: cb_q1
      text:
        en: >
          Describe the commute of the job you liked most and the one you liked least —
          what did getting there actually cost you each day?
```

The `tell` lines are what extraction looks for in an advert, and the question is
what the conversation asks you. The model has 41 dimensions, labelled in English, Spanish
and Catalan ([dimensions/README.md](dimensions/README.md)).

## Use with AI agents

The product is a Claude Code project; the agent is the interface.

- **Step skills.** `.claude/skills/step-00-identify` through
  `step-12-interview-log` are the thirteen steps: identify, intake, constraints,
  history, traits, reactions, preferences, sourcing, understanding, ranking,
  feedback, application, interview log. Each names the `uv run python -m
  integral.<module>` commands that record its result and close its gate.
- **Connector skills.** `connector-new` connects a job board (robots.txt
  adjudication, finding the request behind a page that renders after load,
  field mapping, fixture and probe). `har` turns a browser HAR capture into a
  scraper.
- **Connector exchange.** Connectors install from
  [integral-connectors](https://github.com/nuncaeslupus/integral-connectors)
  over plain HTTPS and must pass their fixture check before first use. Contributing
  one back is consent-gated: the tool discloses the files, asks once, and writes
  the bundle and a `gh pr create` command to the outbox; it never sends anything.
- **Hooks.** `.claude/settings.json` runs `tools/bootstrap_hook.sh` at session
  start (dependency install) and `tools/profile_guard.sh` before file and shell
  tools (keeps candidate data out of the repository).
- **Test mode.** The `test-mode` skill runs a session as a test: `[[…]]` notes
  about the tool travel alongside an otherwise real candidate conversation.
- **Logins.** Sources that need a login are read through the candidate's own
  browser session; no credential is ever stored in a connector.

## How it works

- **One vocabulary, end to end.** Elicitation, extraction, ranking, CV and
  interview are projections of the files in `dimensions/`.
- **Evidence, not guesses.** Extracted values carry verbatim spans from the
  advert; each ranked position cites its reason from the ad.
- **Preferences as prices.** Step 6 turns your reactions to real adverts into
  salary-equivalent weights through forced pairwise choices.
- **Gated steps.** Each step has a checkpoint script and a measured threshold.
- **Polite sourcing.** robots.txt is checked per fetch and cannot fail open;
  connector health has three verdicts (`healthy`, `broken`, `inconclusive`).
- **Nothing sent without you.** Step 11 prepares the documents or the text to
  paste; you press send.

## Your data stays yours

Nothing you say is written inside this repository. Your profile lives in
`$INTEGRAL_HOME`, else `$XDG_DATA_HOME/integral-job-search`, else
`~/.integral-job-search/` on Linux (the platform user-data directory on macOS
and Windows). The resolver refuses any path inside a git work tree rather than
warning about it ([docs/distribution.md](docs/distribution.md) §2).

## Limitations

- **Sourcing is the thinnest part.** How many real offers reach you depends on
  whether your boards have connectors; [CONTRIBUTING.md](CONTRIBUTING.md) covers
  adding one.
- It has been run end to end by its author, to a sent application. Expect to be
  an early user.

## Documentation

- [status/specification.md](status/specification.md) — the specification
- [docs/METHODS.md](docs/METHODS.md) — every technique and formula
- [docs/product-shape.md](docs/product-shape.md) — why a conversation, not a CLI
- [docs/distribution.md](docs/distribution.md) — installation and where state lives
- [docs/dimension-catalogue.md](docs/dimension-catalogue.md) — the dimension model
- [CONTRIBUTING.md](CONTRIBUTING.md) — adding a connector or a language pack

## Development

```bash
make sync     # install with dev dependencies
make ci       # lint, tests, evidence and gate checks, in CI's order
make help     # every target
```

## Related projects

- [claude-arsenal](https://github.com/nuncaeslupus/claude-arsenal) — spec-driven Claude Code workflow and gated task queue.
- [drawspec](https://github.com/nuncaeslupus/drawspec) — declarative diagram spec → clean SVG/PNG/text, writable by LLMs; MCP server included.
- [doc-control](https://github.com/nuncaeslupus/doc-control) — lets AI agents edit Word documents as tracked changes.
- [literary-critic](https://github.com/nuncaeslupus/literary-critic) — LLM manuscript analysis the way a professional editor would.
- [integral-connectors](https://github.com/nuncaeslupus/integral-connectors) — the job-board connectors this tool installs.

## Acknowledgements

The failure-handling layer is adapted from
[`MadsLorentzen/ai-job-search`](https://github.com/MadsLorentzen/ai-job-search)
(MIT, © 2026 Mads Lorentzen): robots handling that cannot fail open, a
three-verdict connector health check, liveness that reads page identity, the
eligibility gate and its quoted reasons, and the ATS text-layer contract. What
was taken, and what was assessed and not adopted, is recorded in
[`docs/METHODS.md` §2.9](docs/METHODS.md).

## License

[MIT](LICENSE).
