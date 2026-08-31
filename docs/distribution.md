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
  fixture/           one recorded response, saved verbatim
    list.html          required — the listing page the conformance check reads
    detail.html        optional — recorded when the connector declares a detail page
  meta.yaml          site, country, language, maintainer handle, last_verified
```

Declarative only: a `connector.yaml` can be read and understood in a minute and
cannot do anything that was not declared. A package carries no executable code
at all, and a `parse.py` inside one is refused by rule 1 like any other
unexpected file.

**This shape used to advertise an optional `parse.py`** — described here as the
escape hatch "for sites that need it". Nothing ever executed it. A connector for
a site the declarative form cannot express could be written, could pass the
whole conformance check, and could not work: `connectors.py` interprets
`connector.yaml` and matches selectors, and there is no import machinery
anywhere in `src/integral`. A promise a contributor can act on and the tool
cannot keep is worse than no promise, so the promise is withdrawn (D-10, #78).

Withdrawn rather than implemented, because implementing it honestly is not a
parser. Executing contributed code needs process-level isolation — a separate
interpreter, no network namespace, a read-only filesystem, CPU and memory caps
— and the AST allowlist under rules 3 and 4 is admission lint, not a sandbox: a
static allowlist cannot bound what Python does once it runs. That is a
milestone of work to keep a hatch nothing currently needs, and the one
committed connector has no `parse.py`.

Sites the declarative grammar cannot reach — JS-rendered pages are already
outside it, see `connectors.py`, "What the format does not cover" — are met by
growing the grammar, when there is a real site to grow it against.

The withdrawal is measured, not just written down: `integral.connector_shape`
counts the executable mechanisms this section advertises that no runtime
executes, and records it as `advertised_connector_mechanisms_without_a_runtime`
in `status/evidence/D10.json`. Re-advertising a `parse.py` here without also
building the runtime for it fails that gate, rather than failing a contributor
some months later.

Six rules, short enough to be one command that a contributor's agent and CI
both run, so a green local check is not a different judgement from a green CI:

```bash
uv run python -m integral.connector_contract --connectors <dir>
```

`--connectors` is what makes it the contributor's command as well as ours: it
runs over their directory, on their machine, and reaches the identical verdict.
It is implemented in `src/integral/connector_contract.py` (T53), records
`connector_contract_violations` into `status/evidence/T53.json`, and exits **3**
rather than 0 when it found no package to check — an empty directory and a
conforming one both report zero violations, and only the exit code separates
them.

1. One connector, one directory, exactly the files above.
2. A fixture is present, and the connector's output over that fixture satisfies
   the offer schema offline.
3. No network of its own — only the HTTP client the runner provides, which owns
   rate limiting, robots.txt, timeouts and the user agent.
4. No filesystem writes, no subprocess, no environment or credential reads.

   Rules 3 and 4 now hold **structurally**: rule 1 admits no Python module, and
   data cannot open a socket. The static AST allowlist that used to enforce them
   over `parse.py` is retained as a second line — it fires on a module smuggled
   in past rule 1 — but it is no longer what holds them, which matters because
   it was never strong enough to be.
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

**Going out — and when.** Having written or repaired a connector, the tool
offers to contribute it. *Offers*, not immediately: the moment matters as much
as the wording, and the two rules below decide it.

**Never during a step.** A candidate opened this to find work. A contribution
prompt in the middle of sourcing or ranking interrupts their search to serve the
project, which inverts whose session it is. The offer belongs at a session
boundary — after the search work of that session is done — and nowhere else.

**Not on the run that wrote it.** A freshly written connector has been proven
against exactly one capture, taken minutes ago. Its fixture and its probe are
the same day, so the rot stage (T72) has nothing to compare across time and
`connector_health` cannot yet distinguish "works" from "worked once". Every
connector written on 2026-08-30 carried that caveat in its own `meta.yaml`, in
the contributors' own words: *"the probe has no elapsed time behind it yet —
that only gets teeth at the next refresh."* Publishing at that point asks
someone to put their name on something nobody has shown survives a day.

So the condition is: **the connector has produced offers in a later session than
the one that wrote it** — a second run, against markup the site has had a chance
to change, with its probe refreshed. That is the first moment the library learns
anything from the contribution that it did not already assume.

In the meantime it lives in `$INTEGRAL_HOME/connectors/<site>_<locale>/`,
complete and fully in use. **Nothing is withheld pending a decision to share**:
the candidate's own searches read it exactly as they read a borrowed one, and a
connector never contributed is not a lesser connector. If they later accept and
have no GitHub account, the prepared bundle waits in
`$INTEGRAL_HOME/outbox/<site>/` (see the three options below) — which is also
where it sits if they simply never decide.

**Asked once, per connector, ever.** A decline is recorded against that
connector and the question does not return — not next session, not after the
connector proves itself again. See "Declining is a complete, correct outcome"
below; this is the mechanism that makes that promise true rather than polite.

The offer states plainly, before anything is sent:

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

- ~~**The name.**~~ **Settled: `integral-job-search`** (2026-08-18), and
  **T55 swept it** (2026-08-20): the package is `integral`, the distribution is
  `integral-job-search`, and `integral.naming` counts what is left of the old
  name so a half-finished rename cannot pass unnoticed. `integral` alone is taken
  on PyPI by an unrelated numerical-integration package; since nothing here is
  published to PyPI that constrains only a future decision to publish, and
  `integral-job-search` is free there in any case.
  **One half is not the repository's to do**: renaming the GitHub repository is
  an owner action, and the clone URL in `README.md` names the new one. GitHub
  redirects the old path once the rename happens; until it does, that URL is the
  one thing here that does not yet resolve.
- ~~**Whether the sources repository is public from the start.**~~ **Settled:
  public** (2026-08-23). Private was never actually reversible at no cost:
  §6's incoming half reads `manifest.json` over plain HTTPS with **no account**,
  and a private repository has no unauthenticated raw URL, so starting private
  would have meant either shipping a token or having no incoming half at all.
  What goes in it is connectors and nothing else — the packages are generated
  from `connectors/` by `tools/publish_connectors.py`, which derives each
  `files` list from the package on disk, and the fictitious `examplejobs.test`
  example is filtered out by its own domain rather than by a list of names.
  `nuncaeslupus/integral-connectors` **exists and is public** as of 2026-08-23,
  publishing `trabajos_es`. Creating it was an owner action, like the rename
  above, but nothing here ever waited on it: the tree is generated and installs
  offline in `tests/test_publish_connectors.py`. Confirmed once against the live
  repository — `https_fetcher` reads the manifest unauthenticated and `install`
  verifies the package — and that check stays out of the gate on purpose, so a
  quiet Saturday at GitHub cannot turn into a failing build here.
- **Whether this repository is public.** Independent of the above, and not
  needed until someone other than the owner installs it.

## 8. What this does not change

Nothing in specification v2's process, tree or gates. §6's `profiles/<handle>/`
layout is unchanged — only where its root resolves from. No step gains or loses
a step; no gate is redefined. The spec anticipated exactly this: "the tree in §6
does not depend on the answer".
