"""The skill listing budget this project actually accepts (S10).

Every loaded skill's `description` sits in the model's context on **every turn
of every session**, so the sum of them is a running cost rather than a lint
preference. `skill-creator`'s `audit_library.py` caps that sum at
`LISTING_BUDGET_CHARS = 8000`. Thirteen step skills (S7) pushed this library
past it, and the owner's decision (2026-08-18) was **option 1: raise the
budget** — every step description stays visible, and the cap is revisited each
time the library grows.

What was blocked was never the decision; it was *where the raised number
lives*. Upstream's constant is hardcoded with no override
(`claude-arsenal` issue #143), and **`vendor/` must not be patched** — a
subtree edit is reverted by the next `git subtree pull`, silently, which is the
exact failure S9 exists to remove and which `make verify-subtree` would fail on
in the meantime. So the number lives *here*, in the repository whose cost it
is, and this module measures against it.

**Three properties, because a raised threshold is only honest if all three
hold.** They are the same three the upstream issue asks for, implemented on
this side of the boundary:

1. **The number is declared, not fitted.** `LISTING_BUDGET_CHARS` below is a
   round figure a person chose, with the reasoning written next to it.
   `check_declaration` refuses a budget that is not a whole multiple of
   `BUDGET_GRANULARITY` or that leaves less than `MIN_HEADROOM_CHARS` — so a
   budget quietly reset to whatever the library happened to measure fails
   mechanically instead of passing as a clean 0. *That* is the failure
   `audit_library`'s hardcoded constant cannot have and a configurable one
   invites.

2. **The effective number and its source are printed.** `measure` records
   `listing_budget_chars` **and** `budget_source`, and `--budget` /
   `JOBSEARCH_LISTING_BUDGET_CHARS` mark the reading `override`. Committed
   evidence carries `budget_source: "declared"`, and
   `test_committed_evidence_was_measured_against_the_declared_budget` asserts
   it — so the gate can never be satisfied by an environment variable set for
   one run.

3. **The upstream default is still reported.** `overage_against_upstream_default`
   keeps the 8,000-char reading visible next to ours, so "we are over
   upstream's cap, deliberately, by this much" stays a fact anyone can read
   rather than something the raise made invisible.

**The per-skill cost formula is upstream's, mirrored deliberately.**
`_budget_breakdown` in `audit_library.py` charges `len(description) +
len(skill_dir_name) + 4` per skill. Restating it here means the two can drift;
`test_the_measurement_agrees_with_the_upstream_audit` runs the real audit and
asserts the totals are equal, so a formula change upstream shows up as a failing
test rather than as two numbers nobody compares. A gate that restates a rule
agrees with prose the code has stopped following (D-11).

The gate is `skill_listing_budget_overage_chars == 0`, and **the three
properties above are folded into that one number** rather than left beside it.
The fenced gate `verify_gates` asserts reads this key and nothing else, so a
bare `total - budget` would let an override — or a budget fitted to the
measurement — report a clean zero while every guarantee here went unchecked
outside the test suite. A library inside an unsoundly declared budget reports
`-1`: not a pass, and not a silent one either.

S10's other requirement — that the saving cannot come from dropping a step — is
`jobsearch.step_skills`' `steps_with_a_skill_fraction`, which is measured there
and asserted here in `measure` so one reading answers both halves.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SKILLS_DIR = _REPO_ROOT / ".claude" / "skills"
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "S10.json"

# ---------------------------------------------------------------------------
# the declared budget

# **13,000 characters, chosen 2026-08-20.** The library measures 11,686 across
# 32 skills, and test mode (S11) is the 33rd. 13,000 accepts the thirteen step
# skills at their current width and leaves room for roughly three more skills
# before the question has to be asked again — which is the point of a budget
# that is revisited rather than one that is fitted.
#
# What this costs, stated plainly so nobody has to reconstruct it: about 13KB
# of context on every turn of every session, in exchange for the model being
# able to see what all thirteen steps are for. The step skills are deliberately
# adjacent — knowing that step 9 exists is part of knowing step 8 is the wrong
# one to load — and a dispatcher that hid twelve of them would have bought the
# characters back by removing exactly that.
LISTING_BUDGET_CHARS = 13_000

# `audit_library.py`'s constant, quoted rather than imported: `.claude/skills/`
# is regenerated by `make update-skills` and importing across that boundary
# would make this module fail to load whenever the library is mid-rebuild. The
# equality is asserted by test, not assumed.
UPSTREAM_DEFAULT_BUDGET_CHARS = 8_000

# A declared budget is a round number a person picked. Requiring it keeps the
# knob from being turned to the measurement: 11,686 is not a multiple of 1,000,
# so "set it to whatever we measure" cannot pass this check.
BUDGET_GRANULARITY = 1_000

# And a budget with no headroom is a budget that will be raised again next
# week. 400 chars is about one more skill's description at this library's
# average width (~365).
MIN_HEADROOM_CHARS = 400

ENV_OVERRIDE = "JOBSEARCH_LISTING_BUDGET_CHARS"

BudgetSource = Literal["declared", "override"]


class SkillBudgetError(Exception):
    """The library could not be read, or a budget is not a usable budget."""


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SkillCost(Strict):
    """One skill's contribution to the per-turn listing cost."""

    skill: str
    description_chars: int
    listing_chars: int


class Declaration(Strict):
    """Whether the declared budget reads as chosen rather than as fitted."""

    budget_chars: int
    source: BudgetSource
    is_round: bool
    headroom_chars: int
    reasons: tuple[str, ...] = ()

    @property
    def passes(self) -> bool:
        return not self.reasons


# ---------------------------------------------------------------------------
# reading the library


def _frontmatter(skill_md: Path) -> dict[str, Any]:
    """The skill's YAML front matter, or `{}` — upstream's parse, same rules.

    Mirrors `audit_library._load_frontmatter`: a file that does not open with
    `---` has no front matter, an unterminated block has none, and a YAML error
    is not an exception here. A skill that cannot be *parsed* simply costs
    nothing, which is what upstream counts, and counting it differently would
    put our total and the audit's out of step for a file neither can read.

    A file that cannot be **read** is a different thing entirely, and is raised
    rather than swallowed. The caller has already established the file exists,
    so an `OSError` here means the library could not be measured — and a
    measurement missing a skill reports a smaller total, which is a *false zero
    overage*: the gate passing precisely because it could not see its input.
    Upstream propagates the same failure, so this also keeps the two agreeing.
    """
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError as exc:
        raise SkillBudgetError(f"{skill_md} exists but could not be read: {exc}") from exc
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}
    try:
        data = yaml.safe_load(text[4:end])
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def listing_cost(description: str, skill_name: str) -> int:
    """What one skill costs the listing, by upstream's formula.

    `len(description) + len(name) + 4` — the four characters standing in for
    the separator and newline of a listing line. Named rather than inlined so
    the test that compares this module with `audit_library` has one function to
    point at when the formula changes.
    """
    return len(description) + len(skill_name) + 4


def skill_costs(skills_dir: Path = DEFAULT_SKILLS_DIR) -> list[SkillCost]:
    """Every skill's listing cost, in directory order.

    Walks the library rather than a list: a skill that exists costs context
    whether or not anybody remembered to enumerate it, so the measurement has
    to come from the filesystem. A directory with no `SKILL.md`, or with no
    string `description`, contributes nothing — again matching upstream.
    """
    skills_dir = Path(skills_dir)
    if not skills_dir.is_dir():
        raise SkillBudgetError(f"no skills library at {skills_dir}")
    costs: list[SkillCost] = []
    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        description = _frontmatter(skill_md).get("description")
        if not isinstance(description, str):
            continue
        costs.append(
            SkillCost(
                skill=skill_dir.name,
                description_chars=len(description),
                listing_chars=listing_cost(description, skill_dir.name),
            )
        )
    return costs


# ---------------------------------------------------------------------------
# the budget itself


def effective_budget(
    budget: int | None = None, env: dict[str, str] | None = None
) -> tuple[int, BudgetSource]:
    """The budget in force, and where it came from.

    Precedence is explicit argument, then environment, then the declared
    constant. The *source* is returned alongside rather than inferred by the
    caller, because the whole complaint against upstream's constant was that a
    threshold whose value and origin are invisible is one nobody can tell has
    been quietly raised. A reading that cannot say where its number came from
    is the same problem with an extra step.
    """
    if budget is not None:
        return _validated(budget), "override"
    raw = (env if env is not None else dict(os.environ)).get(ENV_OVERRIDE)
    if raw:
        try:
            return _validated(int(raw)), "override"
        except ValueError as exc:
            raise SkillBudgetError(f"{ENV_OVERRIDE} is not an integer: {raw!r}") from exc
    return LISTING_BUDGET_CHARS, "declared"


def _validated(budget: int) -> int:
    if budget <= 0:
        raise SkillBudgetError(f"a listing budget must be positive, not {budget}")
    return budget


def check_declaration(budget: int, source: BudgetSource, total: int) -> Declaration:
    """Does this budget read as a number somebody chose?

    Two mechanical properties, and neither is about the library being small:

    * **round** — a whole multiple of `BUDGET_GRANULARITY`. A budget set to the
      current total (11,686, say) fails this, which is precisely the "raised to
      whatever we happened to measure" move that makes a configurable cap
      weaker than a hardcoded one;
    * **headroom** — at least `MIN_HEADROOM_CHARS` spare. A budget the library
      exactly fills is one that will be raised again on the next skill, and a
      threshold raised on demand has stopped being a threshold.

    Reported as a `Declaration` rather than raised, because a budget that fails
    these is still a number worth printing next to the shortfall it explains.
    """
    reasons: list[str] = []
    is_round = budget % BUDGET_GRANULARITY == 0
    if not is_round:
        reasons.append(
            f"budget {budget} is not a multiple of {BUDGET_GRANULARITY} — "
            "a declared budget is a number a person chose, not one fitted to a measurement"
        )
    headroom = budget - total
    if headroom < MIN_HEADROOM_CHARS:
        reasons.append(
            f"budget {budget} leaves {headroom} chars of headroom over a total of {total}, "
            f"below the {MIN_HEADROOM_CHARS} a further skill needs"
        )
    return Declaration(
        budget_chars=budget,
        source=source,
        is_round=is_round,
        headroom_chars=headroom,
        reasons=tuple(reasons),
    )


# ---------------------------------------------------------------------------
# the gate reading


def measure(
    skills_dir: Path = DEFAULT_SKILLS_DIR,
    budget: int | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """S10's gate reading, as it is written to evidence.

    `skill_listing_budget_overage_chars` is the gate key. Everything else in
    the payload exists so the zero can be read rather than trusted: the budget
    in force, where it came from, the measured total, the headroom left, the
    same total against upstream's 8,000, and every skill's individual cost so
    the next person deciding what to trim has the breakdown in front of them
    instead of a single number and an argument.
    """
    try:
        costs = skill_costs(skills_dir)
        in_force, source = effective_budget(budget, env)
    except SkillBudgetError as exc:
        # A failure to read is evidence to report, never a crash to propagate —
        # the same shape `step_skills.measure` uses, and the reason `make
        # evidence` can distinguish "measured badly" from "did not run".
        return {
            "skill_listing_budget_overage_chars": -1,
            "listing_budget_chars": 0,
            "budget_source": "declared",
            "description_chars_total": 0,
            "skills_counted": 0,
            "headroom_chars": 0,
            "upstream_default_budget_chars": UPSTREAM_DEFAULT_BUDGET_CHARS,
            "overage_against_upstream_default": 0,
            "budget_declaration_reasons": [str(exc)],
            "steps_with_a_skill_fraction": 0.0,
            "per_skill": [],
        }

    total = sum(cost.listing_chars for cost in costs)
    declaration = check_declaration(in_force, source, total)

    # S10's second test: whichever option was taken, the saving must not have
    # come from dropping a step. Read from the module that owns that number
    # rather than recomputed, so the two cannot disagree.
    from jobsearch.step_skills import measure as measure_step_skills

    steps = measure_step_skills(skills_dir=skills_dir)

    # The gate key is zero **only** when the library is inside a soundly
    # declared budget. Reporting a bare `total - in_force` would let an
    # override, or a budget fitted to the measurement, produce a clean zero —
    # and the fenced S10 gate asserts that number and nothing else, so every
    # roundness, headroom and provenance guarantee would have been enforced by
    # the tests and the CLI while `verify_gates` waved it through. A guarantee
    # the terminal gate does not check is a guarantee that decays.
    overage = max(0, total - in_force)
    sound = source == "declared" and declaration.passes
    return {
        "skill_listing_budget_overage_chars": overage if (overage or sound) else -1,
        "listing_budget_chars": in_force,
        "budget_source": source,
        "description_chars_total": total,
        "skills_counted": len(costs),
        "headroom_chars": declaration.headroom_chars,
        "upstream_default_budget_chars": UPSTREAM_DEFAULT_BUDGET_CHARS,
        "overage_against_upstream_default": max(0, total - UPSTREAM_DEFAULT_BUDGET_CHARS),
        "budget_declaration_reasons": list(declaration.reasons),
        "steps_with_a_skill_fraction": steps["steps_with_a_skill_fraction"],
        "per_skill": [cost.model_dump(mode="json") for cost in costs],
    }


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    skills_dir: Path = DEFAULT_SKILLS_DIR,
    budget: int | None = None,
) -> dict[str, Any]:
    """Measure and record `status/evidence/S10.json`."""
    measured = measure(skills_dir, budget)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m jobsearch.skill_budget [--check] [--budget N]` → S10's gate.

    Exit 0 when the library is inside the budget in force *and* that budget
    reads as declared rather than fitted; 1 otherwise. The two are one exit
    code on purpose: a zero overage bought by a budget nobody chose is not a
    pass, and splitting them would let the weaker half be reported alone.
    """
    parser = argparse.ArgumentParser(description="Measure the skill listing budget (S10).")
    parser.add_argument(
        "--check",
        action="store_true",
        help="measure and report only; do not write the evidence file",
    )
    parser.add_argument(
        "--write-evidence",
        nargs="?",
        const=str(DEFAULT_EVIDENCE_PATH),
        default=str(DEFAULT_EVIDENCE_PATH),
        metavar="PATH",
        help="write evidence JSON to PATH (default: status/evidence/S10.json)",
    )
    parser.add_argument(
        "--skills-dir",
        default=str(DEFAULT_SKILLS_DIR),
        metavar="DIR",
        help="skills library root to measure (default: .claude/skills)",
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=None,
        metavar="CHARS",
        help=(
            "measure against CHARS instead of the declared budget; marks the reading "
            f"as an override (also settable with {ENV_OVERRIDE})"
        ),
    )
    args = parser.parse_args(argv[1:])
    skills_dir = Path(args.skills_dir)

    if args.check:
        measured = measure(skills_dir, args.budget)
    else:
        measured = write_evidence(Path(args.write_evidence), skills_dir, args.budget)

    print(json.dumps(measured, ensure_ascii=False))

    # The effective budget and its source, on every run. This is the line the
    # upstream issue asks for: a raise nobody can see is a raise nobody can
    # question.
    print(
        f"listing budget: {measured['listing_budget_chars']} chars "
        f"({measured['budget_source']}); library totals "
        f"{measured['description_chars_total']} over {measured['skills_counted']} skills; "
        f"headroom {measured['headroom_chars']}",
        file=sys.stderr,
    )
    if measured["overage_against_upstream_default"]:
        print(
            f"deliberately {measured['overage_against_upstream_default']} chars above "
            f"upstream's {UPSTREAM_DEFAULT_BUDGET_CHARS}-char default — see S10",
            file=sys.stderr,
        )
    for reason in measured["budget_declaration_reasons"]:
        print(f"budget declaration: {reason}", file=sys.stderr)
    if measured["skill_listing_budget_overage_chars"] > 0:
        print(
            f"over budget by {measured['skill_listing_budget_overage_chars']} chars",
            file=sys.stderr,
        )
    if measured["skill_listing_budget_overage_chars"] == -1:
        print(
            "the library is inside its budget, but that budget was not soundly declared — "
            "reported as unmeasured rather than as a pass",
            file=sys.stderr,
        )
    return 1 if measured["skill_listing_budget_overage_chars"] != 0 else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
