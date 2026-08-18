# How this is distributed

**Status: decided, 2026-08-18.** This answers the question specification v2
left open at §11.5 ("how this is distributed") and the packaging half of
`docs/product-shape.md`. It is the remaining scope of **T29**.

The decision is deliberately small. Everything here can be reversed later
*because* of the one structural rule in §2 — which is the only part that is
expensive to retrofit and therefore the only part that must be right now.

---

## 1. It is installed by cloning

```
git clone <repo>
cd <repo>
claude
```

Then the candidate talks. No install step in the README, no package manager
invoked by hand, no plugin registry.

This works because **cloning already delivers both halves of the tool**:

- the thirteen step skills are Markdown under `.claude/skills/`, and Claude Code
  loads project skills from the directory it starts in;
- the checkpoint code is `src/`, and its dependencies are declared in
  `pyproject.toml`.

The one thing a clone does not do is install those dependencies, so **the tool
installs them itself** — a `SessionStart` hook checks whether the environment is
present and current and runs `uv sync` when it is not, and step 0 re-checks
before it needs the code, so a session whose hook did not fire still works. If
`uv` itself is absent the tool says so and offers the one-line installer rather
than failing at an import.

The candidate is told what is being installed the first time it happens. A tool
that silently runs a package manager on someone's machine is not one they can
trust with their working history.

## 2. Candidate state lives outside the clone — the rule everything rests on

`profiles/<handle>/` is **not** inside the repository. It resolves from
`$INTEGRAL_HOME`, defaulting to `~/.integral-job-search/` (respecting
`$XDG_DATA_HOME` where set).

**The resolver refuses to return any path inside a git work tree.** Not a
warning — a refusal, with a `--dev` escape for work on the tool itself. This
turns "the candidate's data never reaches a repository" from a `.gitignore` line
into a property of the code, which is the difference between a convention and a
mechanism, and it is testable the same way `cross_user_leaks == 0` is testable.

What that one rule buys:

| | |
|---|---|
| Upgrading | `git pull` cannot touch the profile, because the profile is not there |
| Privacy | The candidate cannot accidentally commit their history; it is not in the tree to stage |
| Multi-user | Two people on one machine, two home directories, one clone (spec §6) |
| Later packaging | A plugin, a wheel, or a UI becomes a delivery change rather than a migration |

`.gitignore` keeps `profiles/` ignored regardless. Two mechanisms for one
promise is correct here; the ignore rule is the cheap belt behind the braces.

## 3. Why not a plugin — yet

A Claude Code plugin and a clone are the same architecture delivered two ways,
once §2 holds. The differences that survive are small:

| | clone | plugin |
|---|---|---|
| Works from | the clone directory | any directory |
| Upgrade | `git pull` | `/plugin update` |
| Dependencies | the repo is right there | nothing installs them for you |

That last row decides it for now: a plugin delivers the prose and leaves the
Python unresolved, so it needs a bootstrap that the clone gets for free. Start
with the clone; add the plugin when the friction of `cd`-ing to a directory is
worth the packaging work. **It is repackaging, not redesign.**

This is also the lesson of `claude-arsenal` issue #144, learned once already:
what is distributed must be a whole repository whose root *is* the thing, and no
host-owned state may live inside the distributed prefix. A clone of this
repository satisfies both by construction.

## 4. Job sites live in their own repository

Scrapers ("connectors") are not in this repository. They get their own, and
enter here as an ordinary dependency.

The reasons are structural, not tidiness:

- **Different clock.** A connector breaks when someone else's markup changes.
  The profile engine does not. Separate repositories mean separate release
  cadence and a broken connector never blocks a fix to the interview.
- **Different risk.** Fetching, robots.txt, rate limits and terms of service all
  live on that side of the line. The core tool has no scraping code to defend.
- **Different audience.** A normalised job-listing reader is useful to people who
  will never use this tool. That repository can be public and social; this one
  need not be.

The boundary already exists and is already gated: the normalised offer schema,
measured by `offer_schema_violations == 0` (T11). A connector's only obligation
is to produce records that satisfy it.

## 5. Every connector has the same shape

This is what makes the rest possible — the conformance test, the safety checks,
the staleness check, and an agent writing a new one all depend on there being
exactly one shape to write and to read.

```
connectors/<site-id>/
  connector.yaml     what to fetch and how to map it to the offer schema
  parse.py           optional, only for sites the declarative form cannot express
  fixture/           one recorded response, saved verbatim
  meta.yaml          site, country, language, maintainer handle, last_verified
```

Declarative first: a `connector.yaml` can be read and understood in a minute and
cannot do anything that was not declared. `parse.py` is the exception for sites
that need it, not the default.

Six rules, short enough to be one command (`make check-connector`) that a
contributor's agent and CI both run, so a green local check is not a different
judgement from a green CI:

1. One connector, one directory, exactly the files above.
2. A fixture is present, and the connector's output over that fixture satisfies
   the offer schema offline.
3. No network of its own — only the HTTP client the runner provides, which owns
   rate limiting, robots.txt, timeouts and the user agent (checked statically).
4. No filesystem writes, no subprocess, no environment or credential reads
   (same check).
5. `meta.yaml` is complete, including `last_verified`.
6. Policy: public listings only; robots.txt respected; no authentication,
   paywall or captcha bypass.

CI runs against fixtures only and never reaches the network — deterministic, and
nobody's pull request turns the project's CI into a scraping proxy.

### The fixture is a sampled listing, never the candidate's own

When the tool writes or repairs a connector it fetches **a listing sampled from
the site for this purpose**, and records that. It does **not** record an advert
the candidate was looking at.

The reason is not privacy of the advert — job adverts are public. It is that the
set of adverts a person is reading is itself information about them: their
field, their level, their city, the fact that they are looking at all. A fixture
committed to a public repository carries whatever it was made from, forever. So
the fixture-making fetch is a separate, deliberate one, and the recorded file is
scrubbed of anything the fetch carried about who asked for it.

## 6. The exchange, and consent

**Coming in.** When the tool needs a site it does not have a connector for, it
reads the sources repository's manifest over plain HTTPS — no account, no
authentication — and says what it found:

> There is already a connector for `example.de`, contributed in March and last
> verified in July. Shall I use it, or write a fresh one?

If the candidate accepts, it is installed into `$INTEGRAL_HOME/connectors/` —
the user's directory, never the clone — and its fixture test is run locally
**before** its first use. A connector that has gone stale fails there, and the
tool offers to repair it, which is the same work as writing one.

**Going out.** Having written or repaired a connector, the tool offers to
contribute it. The offer states plainly, before anything is sent:

- exactly which files would go (the connector, the sampled fixture, the metadata);
- that the contribution is public and carries their GitHub username;
- that **nothing about them, their profile or their search is included**;
- that declining costs them nothing.

If they accept and are authenticated, the agent does the whole of it: fork,
branch, pull request, and the CI re-runs the test their machine already passed.

**Declining is a complete, correct outcome.** Not a fallback, not a nag. The
connector stays installed and working for them, the tool does not ask again for
that connector, and someone else will contribute one eventually. A person
looking for work does not owe the project a pull request, and the tool must
never make them feel that they do. This is the non-insistence rule of process
spec §5.4 applied to contribution: **it is better to have fewer connectors than
to press someone who said no.**

**Without a GitHub account**, in order of friction:

1. The agent walks them through `gh auth login` — a browser device code, about
   two minutes, and no git knowledge is needed afterwards because the agent does
   the rest.
2. The agent opens a prefilled issue form in their browser; they press Submit.
   Still an account, but no git at all.
3. Neither: the bundle is written to `$INTEGRAL_HOME/outbox/<site>/` with a note
   on where it can be sent. Zero infrastructure, and it may simply sit there.

There is deliberately **no anonymous submission endpoint**. It is the only
option that would require running and defending a service, and it is not worth
building before the volume exists to justify it.

## 7. Still open

- **The name.** "integral" is the direction — `integral-job-search` or similar.
  Not settled, and nothing above depends on it. `integral` alone is taken on
  PyPI (an unrelated numerical-integration package); since nothing here is
  published to PyPI, that constrains only a future decision to publish.
- **Whether the sources repository is public from the start.** Public is the
  obvious end state; starting private costs nothing and is reversible.
- **Whether this repository is public.** Independent of the above, and not
  needed until someone other than the owner installs it.

## 8. What this does not change

Nothing in specification v2's process, tree or gates. §6's `profiles/<handle>/`
layout is unchanged — only where its root resolves from. No step gains or loses
a step; no gate is redefined. The spec anticipated exactly this: "the tree in §6
does not depend on the answer".
