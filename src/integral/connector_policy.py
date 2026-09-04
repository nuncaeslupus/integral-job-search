"""T99 — a refusal that is ours, not the board's, needs an owner's decision.

`connectors/ruled-out.yaml` separates two kinds of ruling, and the separation
is the file's own idea: `robots_refused` is what the board said, adjudicated by
the audited RFC 9309 matcher, and `policy_refused` is what **we** decided about
a board the matcher allows. Collapsing them "would let a judgement call be read
later as a measurement, which is the one thing this file exists to prevent".

That is right, and it was not enough. A judgement kept apart from a measurement
is still a judgement with nobody's name on it. `policy_refused` grew its first
entry — remoteok.com — written by the implementing session on its own reading
of the operator's intent, and the owner had already stated the opposite
position in the same session:

    It is the user who will use the scraper, not you, and most of them did not
    allow massive scraping for AI, but they allow it for making some searches.

The ledger's own header says the same thing two hundred lines earlier: *"those
bans target bulk training crawls; a connector is one candidate's search."* So
the file contradicted its own stated rule, and nothing could see it, because
**nothing read this file** — the header said so outright. This module is the
first reader.

**The defect is the same whichever way the disagreement resolves.** A policy
that silently removes boards from a candidate's reach needs a decision recorded
next to it, saying whose call it was and when. So what is measured here is the
record, not the verdict:

* who decided, and it must be the **owner** — a session recording its own
  judgement in that field would satisfy a check that only asked whether the
  field was filled in, which is this task's defect wearing the fix's clothes;
* **when**, because a judgement made in one session reads a month later exactly
  like a settled position;
* whether the refusal is about **volume or access**, which are different
  refusals with different consequences: one throttles a connector, the other
  deletes a board from the candidate's reach;
* and, for a board the matcher allows, the **rule cited** — since the citation
  is the whole of the argument.

What this does not do: decide whether any particular board should be fetched.
That is the owner's, and this module's only claim is that the answer is written
down where it can be argued with.

---

T116 — the second reader in "two matchers must agree" could not say no.

The same ledger admits a path only when the repo's own audited matcher and a
second, independent parser agree, plus a negative control so a `True` is
distinguishable from a matcher that says yes to everything. The second parser
is stdlib `urllib.robotparser`.

**CPython's `robotparser` returns the first matching rule in file order, not
RFC 9309 §2.2.2's longest match.** `Entry.allowance` iterates `rulelines` and
returns on the first `applies_to` hit. So on any robots.txt opening with
`Allow: /` it answers `True` for every path in the file — including every path
a later, longer `Disallow` covers. It cannot refuse, so it cannot disagree, so
its agreement carries no information at all. Measured on two live boards while
capturing the #260 probes: himalayas.app and nofluffjobs.com both open that way
and `robotparser` never returned `False` on either file, while the repo matcher
refused four paths across them.

That is fail-open in the exact component that exists as the independent check.
Nothing was fetched that should not have been — the repo matcher is strictly
the stricter of the two and it carried the verdicts — so the hole is in the
evidence rather than in the behaviour, which is precisely the kind that goes on
being true for as long as nobody asks the second reader to prove it can refuse.

So competence is measured here rather than assumed, in two halves:

* **the mechanism**, over `COMPETENCE_FIXTURES` — constructed robots.txt
  documents whose classification is derived from RFC 9309's text, never from
  running either parser. `_classify` samples the file's OWN `Disallow` patterns
  (§2.2.3's `*` and `$` are the whole of the translation back into paths), asks
  both readers, and reports `competent` only when the second reader refuses a
  path RFC 9309 also refuses **and allows none that it refuses**. Refusing a
  path the RFC *allows* is not competence — it is the same parser being wrong
  in the other direction — and one fixture exists for exactly that.
* **the record**, over `connectors/robots-adjudications.yaml` — every
  adjudication this repository stands on, each carrying a `standing` of
  `two_parsers_agreed`, `single_parser`, or `no_negative_control_possible`. A
  `two_parsers_agreed` that cannot name a path the second reader refused on
  that same file is the defect, and is what the gate counts.

Two counting decisions, both taken in the fail-open direction because that is
the direction that hurts here. A shipped connector package with no entry at all
is counted, not skipped: it is a fetch admitted with no second reader
whatsoever, and excluding it would make the metric reachable by deleting rows.
And the denominator is floored, so a scan that finds nothing reports
`unmeasured` rather than a clean zero.

**Two metrics, because one name was carrying two meanings.**

`robots_adjudications_without_a_competent_second_reader` is the plan's name for
this task and it says something specific: how many adjudications do not stand
on a second reader that could refuse. The first implementation gave that name
to a *structural* count — rows failing their own checks, malformed controls
accepted, packages with no row, fixtures misclassified — which reads **0** while
**19 of the 20 rows have no competent second reader at all**. A zero under that
name teaches the next session the opposite of the truth, which is `T108`'s
`status_is_asserted` and `#323`'s `incidental_duplicate_drops` a third time.

The defence offered was that the task's Scope excludes it. It does not: Scope's
second bullet is *"or replace the stdlib as the second reader with one that
implements longest-match, and keep the competence check anyway"*, so the literal
metric is reachable in principle and the name was never a synonym for the
structural one.

So the name keeps its meaning and loses the gate:

* `robots_adjudications_without_a_competent_second_reader` — **19** today, of
  20 rows. One row (usajobs.gov) stands on a second reader that demonstrably
  refuses on its own file; every other row is an honest `single_parser` or the
  one file admitting no control at all. What would reduce it is not better
  bookkeeping: it is a second reader that implements §2.2.2's longest match,
  run over each board's robots.txt. That is a task of its own, seeded as
  `t-9d41c7f5`, and it needs those files — 18 of which are not committed here
  and cannot be fetched, egress being blocked.
* `robots_adjudications_misrepresenting_their_standing` — **0**, and the gate.
  It counts records that claim more than the file under them supports, which is
  the property this module can actually enforce and the one a regression would
  break. The four inputs are ways one record misstates its standing: a row
  whose claim it does not establish (including one its own committed
  `robots_txt` contradicts), a malformed control accepted, a shipped package
  with no row — the record standing silently for a fetch it never adjudicated —
  and a competence fixture the classifier gets wrong, which is the machine that
  assigns standings being broken.

An honest `single_parser` is **not** a misrepresentation. The task's own scope
says so — "where it cannot, the adjudication is single-parser and must be
recorded as such rather than counted as agreement" — and a gate that counted it
could only reach zero by re-running every board with a parser that does not
exist yet, which would make the gate unpassable and therefore unread. What is
forbidden is *calling it an agreement*. What is now also refused is *reporting
zero of them*.
"""

from __future__ import annotations

import json
import sys
import urllib.robotparser
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from integral import robots
from integral.gate_exit import worst

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEDGER_PATH = _REPO_ROOT / "connectors" / "ruled-out.yaml"
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T99.json"
DEFAULT_ADJUDICATIONS_PATH = _REPO_ROOT / "connectors" / "robots-adjudications.yaml"
DEFAULT_T116_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T116.json"
DEFAULT_PACKAGES_DIR = _REPO_ROOT / "connectors"

#: The one value that counts as a decision. Anything else — a session, a
#: reviewer, a bot — is a judgement being recorded, not a call being made.
OWNER = "owner"

#: What a refusal can be about. `volume` throttles how much a connector may
#: fetch; `access` removes the board. The owner's stated position distinguishes
#: exactly these two, and the first entry written did not.
REFUSAL_KINDS = ("volume", "access")


class PolicyLedgerError(Exception):
    """The ledger could not be read — never silently a clean run."""


@dataclass(frozen=True)
class PolicyRefusal:
    """One `policy_refused` row, read for the record it carries."""

    site: str
    refuses: str
    robots_verdict: str
    rule_cited: str
    decided_by: str
    decided_on: date | None
    decision: str

    @classmethod
    def from_mapping(cls, payload: Any) -> PolicyRefusal:
        """Read one row, tolerating everything — the reading is the check.

        A missing key becomes an empty value rather than an exception, so a
        malformed row is *counted* instead of aborting the run over the rows
        after it. A ledger that stops at its first bad entry reports a smaller
        number than the truth.
        """
        if not isinstance(payload, dict):
            return cls("", "", "", "", "", None, "")
        return cls(
            site=str(payload.get("site") or "").strip(),
            refuses=str(payload.get("refuses") or "").strip(),
            robots_verdict=str(payload.get("robots_verdict") or "").strip(),
            rule_cited=str(payload.get("rule_cited") or "").strip(),
            decided_by=str(payload.get("decided_by") or "").strip(),
            decided_on=_as_date(payload.get("decided_on")),
            decision=str(payload.get("decision") or "").strip(),
        )

    def problems(self) -> list[str]:
        """Everything missing from this row's record. Empty is the goal."""
        where = self.site or "(a row naming no site)"
        found: list[str] = []
        if not self.site:
            found.append(
                "a policy refusal naming no site cannot be argued with, retested "
                "or overturned"
            )
        if self.decided_by != OWNER:
            found.append(
                f"{where}: decided_by is {self.decided_by or 'unset'!r}, not {OWNER!r} — "
                "a policy refusal is the owner's call, and a session recording its own "
                "judgement here is the defect this check exists for"
            )
        if self.decided_on is None:
            found.append(f"{where}: no decided_on date — an undated call reads as settled")
        if not self.decision:
            found.append(f"{where}: no decision text — nothing says what was actually decided")
        if self.refuses not in REFUSAL_KINDS:
            found.append(
                f"{where}: refuses is {self.refuses or 'unset'!r}; it must say "
                f"{' or '.join(REFUSAL_KINDS)} — throttling a connector and deleting a "
                "board are different refusals"
            )
        if self.robots_verdict == "allowed" and not self.rule_cited:
            found.append(
                f"{where}: allowed by robots and refused with no rule cited — the "
                "citation is the whole of the argument"
            )
        return found


def _as_date(value: Any) -> date | None:
    """A canonical `YYYY-MM-DD` date, or `None`. PyYAML parses a bare date.

    Two shapes that look like dates are refused, because this ledger is read
    years later and a record that is not canonical is not the same record.
    A `datetime` is a `date` subtype, so a YAML timestamp passes an
    `isinstance` check written for a day; and `strptime` accepts an unpadded
    `2026-8-1`. So the timestamp is rejected before the subtype check, and a
    string is kept only when it round-trips through `date.isoformat()`.
    """
    if isinstance(value, datetime):
        return None
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    try:
        parsed = datetime.strptime(trimmed, "%Y-%m-%d").date()
    except ValueError:
        return None
    return parsed if parsed.isoformat() == trimmed else None


def refusals(ledger: Path = DEFAULT_LEDGER_PATH) -> list[PolicyRefusal]:
    """Every `policy_refused` row in the ledger."""
    try:
        payload = yaml.safe_load(ledger.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise PolicyLedgerError(f"{ledger}: could not be read: {exc}") from exc
    if not isinstance(payload, dict):
        raise PolicyLedgerError(f"{ledger}: is not a mapping")
    rows = payload.get("policy_refused") or []
    if not isinstance(rows, list):
        raise PolicyLedgerError(f"{ledger}: policy_refused is not a list")
    return [PolicyRefusal.from_mapping(row) for row in rows]


#: Rows that are malformed by construction, put through the same reader on
#: every run. One live entry is a thin denominator and a rule true of one row
#: is nearly a rule true of nothing — and each control names a way the record
#: could look complete while saying nothing.
MALFORMED_CONTROLS: tuple[tuple[str, dict[str, Any]], ...] = (
    (
        "no decision at all",
        {"site": "a.test", "refuses": "access", "robots_verdict": "allowed",
         "rule_cited": "x"},
    ),
    (
        "the implementing session recorded as the decider",
        {"site": "b.test", "refuses": "access", "robots_verdict": "allowed",
         "rule_cited": "x", "decided_by": "implementing session",
         "decided_on": "2026-08-31", "decision": "the intent is legible"},
    ),
    (
        "an owner decision with no date",
        {"site": "c.test", "refuses": "volume", "robots_verdict": "allowed",
         "rule_cited": "x", "decided_by": "owner", "decision": "throttle it"},
    ),
    (
        "volume and access not distinguished",
        {"site": "d.test", "robots_verdict": "allowed", "rule_cited": "x",
         "decided_by": "owner", "decided_on": "2026-08-31", "decision": "no"},
    ),
    (
        "allowed by robots, refused with no rule cited",
        {"site": "e.test", "refuses": "access", "robots_verdict": "allowed",
         "decided_by": "owner", "decided_on": "2026-08-31", "decision": "no"},
    ),
    (
        "a row naming no board",
        {"refuses": "access", "robots_verdict": "allowed", "rule_cited": "x",
         "decided_by": "owner", "decided_on": "2026-08-31", "decision": "no"},
    ),
    (
        "a YAML timestamp where the day was the record",
        {"site": "f.test", "refuses": "access", "robots_verdict": "allowed",
         "rule_cited": "x", "decided_by": "owner",
         "decided_on": datetime(2026, 8, 31, 14, 30), "decision": "no"},
    ),
    (
        "an unpadded date that is not what the ledger says it holds",
        {"site": "g.test", "refuses": "volume", "robots_verdict": "allowed",
         "rule_cited": "x", "decided_by": "owner", "decided_on": "2026-8-1",
         "decision": "throttle it"},
    ),
)


def measure(
    ledger: Path = DEFAULT_LEDGER_PATH,
    *,
    controls: tuple[tuple[str, dict[str, Any]], ...] = MALFORMED_CONTROLS,
) -> dict[str, Any]:
    """T99's gate: `policy_refusals_without_an_owner_decision`.

    The live rows and the constructed controls go through one reader. A
    control that comes back clean is counted as a violation of its own,
    because the only way that happens is the check having been lost.
    """
    live = refusals(ledger)
    violations = [problem for refusal in live for problem in refusal.problems()]
    incomplete = sum(1 for refusal in live if refusal.problems())

    accepted = [
        name
        for name, payload in controls
        if not PolicyRefusal.from_mapping(payload).problems()
    ]
    violations += [f"accepted a malformed control: {name}" for name in accepted]

    checked = len(live) + len(controls)
    return {
        "policy_refusals_without_an_owner_decision": incomplete + len(accepted),
        # Both names, as every gate in this increment carries.
        "policy_refusals_without_an_owner_decision_evaluated": checked,
        "policy_refusals_checked": checked,
        "live_refusals": len(live),
        "controls_checked": len(controls),
        "gate_status": "measured" if checked else "unmeasured",
        "sites": sorted(r.site for r in live if r.site),
        "violations": violations,
    }


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH, ledger: Path = DEFAULT_LEDGER_PATH
) -> dict[str, Any]:
    """Measure and record `status/evidence/T99.json`."""
    measured = measure(ledger)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


# ---------------------------------------------------------------------------
# T116 — is the second reader competent on this file?
# ---------------------------------------------------------------------------

#: The three standings an adjudication may carry. Only the first is an
#: agreement; the other two are honest records of not having one.
TWO_PARSERS_AGREED = "two_parsers_agreed"
SINGLE_PARSER = "single_parser"
NO_NEGATIVE_CONTROL_POSSIBLE = "no_negative_control_possible"
STANDINGS = (TWO_PARSERS_AGREED, SINGLE_PARSER, NO_NEGATIVE_CONTROL_POSSIBLE)

#: What `_classify` can find about a second reader on one file.
COMPETENT = "competent"
#: It refused a path RFC 9309 refuses, and ALLOWED another one — so it is a
#: second opinion on some of this file and fail-open on the rest. Competence is
#: a property of a (file, target) pair before it is a property of a file, and
#: this verdict is what keeps a per-file `competent` from being read as a claim
#: about every target on it.
PARTIALLY_COMPETENT = "partially_competent"
INCOMPETENT = "incompetent"
NO_CONTROL_POSSIBLE = "no_control_possible"
CLASSIFICATIONS = (COMPETENT, PARTIALLY_COMPETENT, INCOMPETENT, NO_CONTROL_POSSIBLE)

#: Which standings a row may carry, given what `_classify` says about the
#: robots.txt it snapshots. `single_parser` is permitted under every
#: classification because it claims nothing — under-claiming is never the
#: defect. `two_parsers_agreed` needs full competence, and
#: `no_negative_control_possible` needs a file on which no control exists.
STANDINGS_FOR_CLASSIFICATION: dict[str, tuple[str, ...]] = {
    COMPETENT: (TWO_PARSERS_AGREED, SINGLE_PARSER),
    PARTIALLY_COMPETENT: (SINGLE_PARSER,),
    INCOMPETENT: (SINGLE_PARSER,),
    NO_CONTROL_POSSIBLE: (NO_NEGATIVE_CONTROL_POSSIBLE, SINGLE_PARSER),
}

#: The literal that says a second reader was never run, as opposed to run and
#: unable to refuse. `single_parser` covered both and the two are different
#: findings; this is the discriminator, and it is validated rather than assumed.
NOT_RUN = "not_run"

#: The second readers this repository knows how to name. A free-text field here
#: makes `second_reader: "checked it myself"` indistinguishable from a parser.
KNOWN_SECOND_READERS = ("urllib.robotparser",)

#: The denominator's floor. A count of the day would move whenever a connector
#: is added and make every such PR an evidence drift; a floor says what the
#: scan guaranteed without moving (T100). It is deliberately under what the
#: repository carries — its job is to stop a clean zero resting on an empty
#: scan, not to track the total.
ADJUDICATIONS_AT_LEAST = 25

#: Shipped packages the coverage check must have found. Same reasoning.
PACKAGES_AT_LEAST = 15


class AdjudicationLedgerError(Exception):
    """The adjudication record could not be read — never silently a clean run."""


@dataclass(frozen=True)
class Competence:
    """What one second reader could and could not refuse on one robots.txt."""

    verdict: str
    #: Concrete request targets sampled from the file's own `Disallow` lines.
    controls_tried: tuple[str, ...]
    #: Of those, the ones RFC 9309 refuses to this agent.
    rfc_refused: tuple[str, ...]
    #: Of *those*, the ones the second reader also refused. Non-empty is the
    #: whole of competence.
    second_reader_refused: tuple[str, ...]
    #: Paths the second reader refused that RFC 9309 allows. Not competence —
    #: the opposite error — and kept so the two are never confused.
    second_reader_false_refusals: tuple[str, ...]
    #: Paths RFC 9309 refuses that the second reader ALLOWED. The fail-open
    #: discrepancy, and the one that decides whether an agreement on this file
    #: means anything: it was computed and discarded, while its fail-closed
    #: mirror above was recorded — backwards, on a repository whose stated
    #: weighting is fail-open over fail-closed.
    second_reader_false_allows: tuple[str, ...]


def second_reader_allows(text: str, agent: str, target: str) -> bool:
    """Stdlib `urllib.robotparser`'s verdict for `target`, over text in hand.

    The independent reader, called exactly as the ledger's rule calls it. Its
    first-match behaviour is not corrected here — correcting it would delete
    the independence that is the point of having it — it is measured.
    """
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(text.splitlines())
    return parser.can_fetch(agent, target)


def _classify(text: str, agent: str) -> Competence:
    """Can this second reader refuse anything on this file?

    The controls are the file's own `Disallow` patterns, turned back into
    request targets: a negative control has to be a path *this* file asks to be
    refused, or it is a control over some other document. §2.2.1 selects the
    group first, so a `Disallow: /` written for another crawler is never
    offered as a control for us — it is not a restriction on this agent.

    Competence is the second reader refusing at least one path RFC 9309 also
    refuses. Refusing a path the RFC allows does not count and is recorded
    separately: a parser wrong in the fail-closed direction looks exactly like
    a competent one to a check that only asks whether some `False` came back.

    **Competence is per target before it is per file**, which is why there are
    four verdicts and not three:

        User-agent: *
        Disallow: /admin
        Allow: /
        Disallow: /apply

    §2.2.2 refuses both `/admin` and `/apply` — each disallow is six octets
    against the allow's one. A first-match reader refuses `/admin` (it meets it
    first) and **allows** `/apply` (its first match there is `Allow: /`). One
    `competent` for the whole file would let a row claim `two_parsers_agreed`
    on the strength of `/admin` while the adjudicated target is `/apply`, where
    the second reader is fail-open. So a reader that refuses one refused path
    and allows another is `partially_competent`, which no agreement may rest
    on.

    Each pattern is sampled through its whole witness family and stops at the
    first target the group refuses (`robots.sample_paths`): one witness per
    pattern let a competing `Allow` capture it and made a file that refuses
    `/ay` report that no negative control was possible at all.
    """
    tried: list[str] = []
    rfc_refused: list[str] = []
    agreed: list[str] = []
    false_refusals: list[str] = []
    false_allows: list[str] = []
    for pattern in robots.disallow_patterns(text, agent):
        for target in robots.sample_paths(pattern):
            if target in tried:
                continue
            tried.append(target)
            rfc_allows = robots.allows_text(text, agent, target)
            second_allows = second_reader_allows(text, agent, target)
            if not rfc_allows:
                rfc_refused.append(target)
                (false_allows if second_allows else agreed).append(target)
                # This pattern has produced its negative control; the rest of
                # its family witnesses the same rule and says the same thing.
                break
            if not second_allows:
                false_refusals.append(target)
    if not rfc_refused:
        verdict = NO_CONTROL_POSSIBLE
    elif not agreed:
        verdict = INCOMPETENT
    elif false_allows:
        verdict = PARTIALLY_COMPETENT
    else:
        verdict = COMPETENT
    return Competence(
        verdict=verdict,
        controls_tried=tuple(tried),
        rfc_refused=tuple(rfc_refused),
        second_reader_refused=tuple(agreed),
        second_reader_false_refusals=tuple(false_refusals),
        second_reader_false_allows=tuple(false_allows),
    )


@dataclass(frozen=True)
class _CompetenceFixture:
    """One constructed robots.txt, with the classification RFC 9309 requires.

    `expected` is derived from the RFC's text, never from running either
    parser — that circularity is what let T70 take ten defects across five
    review rounds. `section` records which part of the RFC the verdict was
    read off, so a later reader can check the derivation rather than the code.
    """

    name: str
    robots_txt: str
    agent: str
    expected: str
    section: str
    why: str


#: The mechanism's fixtures. Every `expected` below was written down from RFC
#: 9309's text before either parser was run over the document beside it.
COMPETENCE_FIXTURES: tuple[_CompetenceFixture, ...] = (
    _CompetenceFixture(
        name="a_permissive_opener_hides_every_longer_disallow",
        robots_txt="""
User-agent: *
Allow: /
Disallow: /apply
""",
        agent="integral-job-search/0.1",
        expected=INCOMPETENT,
        section="RFC 9309 §2.2.2",
        why=(
            "§2.2.2: 'The most specific match found MUST be used. The most specific "
            "match is the match that has the most octets.' `/apply` matches both "
            "rules; the disallow is six octets to the allow's one, so RFC 9309 "
            "refuses it. A first-match reader returns the `Allow: /` it meets first "
            "and refuses nothing anywhere in this file — the exact shape measured on "
            "himalayas.app and nofluffjobs.com, and fail-open."
        ),
    ),
    _CompetenceFixture(
        name="the_same_rules_in_the_other_order_let_the_second_reader_refuse",
        robots_txt="""
User-agent: *
Disallow: /apply
Allow: /
""",
        agent="integral-job-search/0.1",
        expected=COMPETENT,
        section="RFC 9309 §2.2.2",
        why=(
            "The same two rules, so §2.2.2 gives `/apply` the same verdict — order "
            "is not part of the rule. A first-match reader now meets the disallow "
            "first and refuses. Paired with the fixture above deliberately: one "
            "file's second reader is competent and the other's is not, on identical "
            "rule sets, which is why competence can never be assumed from the "
            "reader's identity."
        ),
    ),
    _CompetenceFixture(
        name="a_bare_disallow_admits_no_negative_control",
        robots_txt="""
User-agent: *
Disallow:
""",
        agent="integral-job-search/0.1",
        expected=NO_CONTROL_POSSIBLE,
        section="RFC 9309 §2.2.2 (empty-pattern)",
        why=(
            "§2.2.2's grammar admits an empty pattern, and an empty pattern has no "
            "octets to match against the path, so the rule restricts nothing; with "
            "no match found in the group the URI is allowed. No path on this file is "
            "refused to this agent by any correct parser, so no negative control can "
            "exist. www.workingnomads.com's whole robots.txt is this document."
        ),
    ),
    _CompetenceFixture(
        name="an_ordinary_file_lets_the_second_reader_refuse",
        robots_txt="""
User-agent: *
Disallow: /admin/
Allow: /jobs/
""",
        agent="integral-job-search/0.1",
        expected=COMPETENT,
        section="RFC 9309 §2.2.2",
        why=(
            "`/admin/x` matches the disallow and nothing else, so §2.2.2 refuses it "
            "under any precedence rule at all. The baseline: on a file like this the "
            "second reader really is a second opinion, and the fixture exists so a "
            "regression that made `_classify` always answer `incompetent` would fail "
            "rather than look conservative."
        ),
    ),
    _CompetenceFixture(
        name="refusing_a_path_the_rfc_allows_is_not_competence",
        robots_txt="""
User-agent: *
Disallow: /jobs
Allow: /jobs
""",
        agent="integral-job-search/0.1",
        expected=NO_CONTROL_POSSIBLE,
        section="RFC 9309 §2.2.2 (equivalent rules)",
        why=(
            "§2.2.2: 'If an allow rule and a disallow rule are equivalent, then the "
            "allow rule SHOULD be used.' So `/jobs` is ALLOWED and this file refuses "
            "nothing — no control is possible. A first-match reader returns the "
            "disallow it meets first and says `False`. A competence check that only "
            "asked whether some `False` came back would score this file as the "
            "second reader's best showing, on the one path where it is wrong."
        ),
    ),
    _CompetenceFixture(
        name="a_disallow_for_another_agent_is_not_our_negative_control",
        robots_txt="""
User-agent: OtherBot
Disallow: /

User-agent: *
Disallow:
""",
        agent="integral-job-search/0.1",
        expected=NO_CONTROL_POSSIBLE,
        section="RFC 9309 §2.2.1",
        why=(
            "§2.2.1 selects one group by product token, and a crawler obeys that "
            "group only; with no token matching ours the `*` group applies, and it "
            "carries a bare `Disallow:`. `OtherBot`'s `Disallow: /` is not a "
            "restriction on us, so offering it as our negative control would "
            "manufacture a refusal out of a group we are not in."
        ),
    ),
    _CompetenceFixture(
        name="an_end_anchored_wildcard_rule_still_yields_a_control",
        robots_txt="""
User-agent: *
Allow: /
Disallow: /*.pdf$
""",
        agent="integral-job-search/0.1",
        expected=INCOMPETENT,
        section="RFC 9309 §2.2.3",
        why=(
            "§2.2.3 gives `*` 'any sequence of characters' and `$` 'end of URL', so "
            "`/x.pdf` is a path this file disallows, and §2.2.2 gives the longer "
            "pattern precedence over `Allow: /`. Present so the sampling that turns "
            "a pattern back into a path is exercised on both metacharacters rather "
            "than only on literal prefixes — a sampler that dropped this rule would "
            "silently report `no_control_possible` and look like good news."
        ),
    ),
    _CompetenceFixture(
        name="a_competing_allow_captures_the_only_witness_a_pattern_produced",
        robots_txt="""
User-agent: *
Disallow: /a*
Allow: /ax
""",
        agent="integral-job-search/0.1",
        expected=INCOMPETENT,
        section="RFC 9309 §2.2.3",
        why=(
            "§2.2.3 gives `*` 'any sequence of characters', so `Disallow: /a*` covers "
            "`/ay`, and `Allow: /ax` — a literal — does not match `/ay` at all. One "
            "matching rule, so §2.2.2 refuses `/ay`: a negative control DOES exist on "
            "this file. The stdlib reader has no wildcard support, matches `/a*` as a "
            "literal prefix, finds no rule applying to `/ay` and allows it — so the "
            "verdict is `incompetent`, not `no_control_possible`. The sampler used to "
            "produce exactly one witness per pattern, `/ax`, which §2.2.2 ALLOWS on "
            "the equal-length tie ('if an allow rule and a disallow rule are "
            "equivalent, then the allow rule SHOULD be used'), and the file therefore "
            "reported that no parser could ever refuse anything on it. That is the "
            "standing which excuses a board entirely, handed to a file that plainly "
            "refuses a path — the worst direction to be wrong in."
        ),
    ),
    _CompetenceFixture(
        name="a_reader_refusing_one_refused_path_and_allowing_another_is_only_partly_competent",
        robots_txt="""
User-agent: *
Disallow: /admin
Allow: /
Disallow: /apply
""",
        agent="integral-job-search/0.1",
        expected=PARTIALLY_COMPETENT,
        section="RFC 9309 §2.2.2",
        why=(
            "§2.2.2's most-octets rule refuses BOTH `/admin` and `/apply`: each "
            "disallow is six octets against `Allow: /`'s one. A first-match reader "
            "refuses `/admin`, whose rule it meets first, and ALLOWS `/apply`, whose "
            "first matching rule is `Allow: /`. A single per-file verdict would call "
            "this reader competent on the strength of `/admin` — and the path a row "
            "adjudicates could be `/apply`, where the same reader is fail-open. "
            "Competence is a property of a (file, target) pair before it is a "
            "property of a file, so this file's verdict is `partially_competent` and "
            "no `two_parsers_agreed` may rest on it."
        ),
    ),
)


@dataclass(frozen=True)
class RobotsAdjudication:
    """One recorded adjudication, read for the standing it claims."""

    site: str
    package: str
    checked: date | None
    agent: str
    standing: str
    second_reader: str
    source: str
    allowed: tuple[str, ...]
    second_reader_refused: tuple[str, ...]
    reason: str
    #: The robots.txt this row was read off, when the row commits one. Optional
    #: because most of these boards' files are not in the repository and egress
    #: is blocked here — but where it IS present, every claim the row makes
    #: becomes checkable against the text instead of taken from its prose.
    robots_txt: str

    @classmethod
    def from_mapping(cls, payload: Any) -> RobotsAdjudication:
        """Read one row, tolerating everything — the reading is the check."""
        if not isinstance(payload, dict):
            return cls("", "", None, "", "", "", "", (), (), "", "")

        def _paths(key: str) -> tuple[str, ...]:
            raw = payload.get(key) or []
            if not isinstance(raw, list):
                return ()
            return tuple(str(item).strip() for item in raw if str(item).strip())

        return cls(
            site=str(payload.get("site") or "").strip(),
            package=str(payload.get("package") or "").strip(),
            checked=_as_date(payload.get("checked")),
            agent=str(payload.get("agent") or "").strip(),
            standing=str(payload.get("standing") or "").strip(),
            second_reader=str(payload.get("second_reader") or "").strip(),
            source=str(payload.get("source") or "").strip(),
            allowed=_paths("allowed"),
            second_reader_refused=_paths("second_reader_refused"),
            reason=str(payload.get("reason") or "").strip(),
            robots_txt=str(payload.get("robots_txt") or ""),
        )

    def problems(self, repo_root: Path = _REPO_ROOT) -> list[str]:
        """Everything this row fails to establish. Empty is the goal."""
        where = self.site or "(a row naming no site)"
        found: list[str] = []
        if not self.site:
            found.append(
                "an adjudication naming no site cannot be argued with, retested "
                "or overturned"
            )
        if self.checked is None:
            found.append(f"{where}: no `checked` date — an undated standing reads as settled")
        if not self.agent:
            found.append(
                f"{where}: no agent — robots.txt is addressed to whoever the client "
                "says it is, so a verdict with no agent names no group (§2.2.1)"
            )
        else:
            # §2.2.1 selects the group by product token, so an agent string
            # from which no single token can be read names no group at all and
            # the row's verdict is about nothing. `robots._product_token` is
            # the module's own rule — asked, not re-implemented, so this cannot
            # drift back into the prefix matching T102 removed.
            try:
                robots._product_token(self.agent)
            except robots.RobotsError as exc:
                found.append(f"{where}: agent {self.agent!r} names no decidable group: {exc}")
        if self.second_reader and self.second_reader not in (NOT_RUN, *KNOWN_SECOND_READERS):
            found.append(
                f"{where}: `second_reader` is {self.second_reader!r}, which is neither "
                f"{NOT_RUN!r} nor one of {', '.join(KNOWN_SECOND_READERS)} — free text "
                "here makes 'a parser read it' and 'somebody looked' the same record"
            )
        both = [path for path in self.allowed if path in self.second_reader_refused]
        if both:
            found.append(
                f"{where}: {', '.join(both)} listed as both admitted and refused by the "
                "second reader — the row contradicts itself on the one path that would "
                "decide it"
            )
        if not self.source:
            found.append(f"{where}: no `source` — nothing says where this reading is written")
        elif not (repo_root / self.source).exists():
            found.append(f"{where}: `source` {self.source!r} is not a file in this repository")
        if self.standing not in STANDINGS:
            found.append(
                f"{where}: standing is {self.standing or 'unset'!r}; it must be one of "
                f"{', '.join(STANDINGS)}"
            )
            return found
        if self.standing == TWO_PARSERS_AGREED:
            if not self.second_reader_refused:
                found.append(
                    f"{where}: claims two parsers agreed and names no path the second "
                    "reader refused on the same file. An agreement with a reader that "
                    "cannot say no is one parser's verdict wearing two names — this is "
                    "the defect, and it is fail-open"
                )
            if not self.allowed:
                found.append(
                    f"{where}: claims an agreement and names no path it admitted — "
                    "there is nothing for the agreement to be about"
                )
            if not self.second_reader or self.second_reader == NOT_RUN:
                found.append(
                    f"{where}: claims two parsers agreed while `second_reader` is "
                    f"{self.second_reader or 'unset'!r}"
                )
        else:
            if self.standing == SINGLE_PARSER and not self.second_reader:
                # `single_parser` covers two different findings — the reader
                # ran and could not refuse anything on this file, or it was
                # never run — and `second_reader` is the only thing that says
                # which. An unset value collapses them back into one silence,
                # which is the distinction the third standing exists to make.
                found.append(
                    f"{where}: standing {SINGLE_PARSER!r} with `second_reader` unset — "
                    f"'ran and could not refuse' and 'never run' are different findings, "
                    f"and only this field distinguishes them ({NOT_RUN!r} says the second)"
                )
            if not self.reason:
                found.append(
                    f"{where}: standing {self.standing!r} with no reason — "
                    "'no control was possible' and 'no control was run' are different "
                    "findings and this row does not say which"
                )
            if self.second_reader_refused:
                found.append(
                    f"{where}: standing {self.standing!r} while naming paths the second "
                    "reader refused — a row that contradicts its own standing"
                )
        found += self._snapshot_problems(where)
        return found

    def _snapshot_problems(self, where: str) -> list[str]:
        """What the committed robots.txt says about the claims of this row.

        Everything above validates the row's **shape**: that a
        `two_parsers_agreed` names some path, that a standing is spelled from
        the vocabulary. None of it connects the row to a robots.txt, so a row
        claiming an agreement over invented paths passed every check, and
        `_classify` — the whole competence mechanism — was never run against a
        single real board. The record's only agreement was unverified prose.

        A row that commits `robots_txt` is checked against it three ways:

        * its standing must be one `_classify` permits for that file
          (`STANDINGS_FOR_CLASSIFICATION`) — under-claiming is always allowed,
          over-claiming never is;
        * every path in `second_reader_refused` must be refused by RFC 9309
          **and** by the second reader over that text — a claimed refusal that
          neither reader makes is the fail-open shape of this whole task;
        * every path in `allowed` must be RFC-allowed over that text, since
          the admission is what the row exists to justify.

        A row with no snapshot is not faulted for it: most of these files are
        not in this repository and egress is blocked here. What is faulted is a
        snapshot that contradicts the row beside it.
        """
        if not self.robots_txt.strip():
            return []
        try:
            found = _classify(self.robots_txt, self.agent)
        except robots.RobotsError as exc:
            return [f"{where}: `robots_txt` could not be classified for {self.agent!r}: {exc}"]
        problems: list[str] = []
        permitted = STANDINGS_FOR_CLASSIFICATION.get(found.verdict, ())
        if self.standing in STANDINGS and self.standing not in permitted:
            problems.append(
                f"{where}: standing {self.standing!r}, but its own `robots_txt` "
                f"classifies {found.verdict!r} — that standing needs one of "
                f"{', '.join(permitted) or '(none)'}"
            )
        for path in self.second_reader_refused:
            if robots.allows_text(self.robots_txt, self.agent, path):
                problems.append(
                    f"{where}: names {path!r} as a second-reader refusal, but RFC 9309 "
                    "ALLOWS it on this file — a refusal the RFC does not make is not a "
                    "negative control, it is the second reader being wrong"
                )
            elif second_reader_allows(self.robots_txt, self.agent, path):
                problems.append(
                    f"{where}: names {path!r} as a second-reader refusal, and the second "
                    "reader ALLOWS it on this file — the agreement this row rests on is "
                    "not there"
                )
        for path in self.allowed:
            if not robots.allows_text(self.robots_txt, self.agent, path):
                problems.append(
                    f"{where}: admits {path!r}, which RFC 9309 REFUSES on this file"
                )
        return problems


#: Rows malformed by construction, put through the same reader every run. Each
#: names a way this record could look complete while establishing nothing.
MALFORMED_ADJUDICATIONS: tuple[tuple[str, dict[str, Any]], ...] = (
    (
        "an agreement with no refused path — the defect itself",
        {
            "site": "a.test",
            "checked": "2026-09-04",
            "agent": "integral-job-search/0.1",
            "standing": TWO_PARSERS_AGREED,
            "second_reader": "urllib.robotparser",
            "source": "connectors/robots-adjudications.yaml",
            "allowed": ["/jobs"],
        },
    ),
    (
        "an agreement whose second reader was never run",
        {
            "site": "b.test",
            "checked": "2026-09-04",
            "agent": "integral-job-search/0.1",
            "standing": TWO_PARSERS_AGREED,
            "second_reader": "not_run",
            "source": "connectors/robots-adjudications.yaml",
            "allowed": ["/jobs"],
            "second_reader_refused": ["/admin/"],
        },
    ),
    (
        "an agreement naming nothing it admitted",
        {
            "site": "c.test",
            "checked": "2026-09-04",
            "agent": "integral-job-search/0.1",
            "standing": TWO_PARSERS_AGREED,
            "second_reader": "urllib.robotparser",
            "source": "connectors/robots-adjudications.yaml",
            "second_reader_refused": ["/admin/"],
        },
    ),
    (
        "no negative control possible, with no reason — indistinguishable from forgetting",
        {
            "site": "d.test",
            "checked": "2026-09-04",
            "agent": "integral-job-search/0.1",
            "standing": NO_NEGATIVE_CONTROL_POSSIBLE,
            "second_reader": "urllib.robotparser",
            "source": "connectors/robots-adjudications.yaml",
        },
    ),
    (
        "a single-parser row that also claims a refusal",
        {
            "site": "e.test",
            "checked": "2026-09-04",
            "agent": "integral-job-search/0.1",
            "standing": SINGLE_PARSER,
            "second_reader": "urllib.robotparser",
            "source": "connectors/robots-adjudications.yaml",
            "reason": "the file opens with `Allow: /`",
            "second_reader_refused": ["/admin/"],
        },
    ),
    (
        "a standing this vocabulary does not have",
        {
            "site": "f.test",
            "checked": "2026-09-04",
            "agent": "integral-job-search/0.1",
            "standing": "agreed",
            "second_reader": "urllib.robotparser",
            "source": "connectors/robots-adjudications.yaml",
        },
    ),
    (
        "a source that is not in this repository",
        {
            "site": "g.test",
            "checked": "2026-09-04",
            "agent": "integral-job-search/0.1",
            "standing": SINGLE_PARSER,
            "second_reader": "not_run",
            "source": "connectors/no-such-file.yaml",
            "reason": "one parser only",
        },
    ),
    (
        "an undated standing",
        {
            "site": "h.test",
            "agent": "integral-job-search/0.1",
            "standing": SINGLE_PARSER,
            "second_reader": "not_run",
            "source": "connectors/robots-adjudications.yaml",
            "reason": "one parser only",
        },
    ),
    (
        "a row naming no site",
        {
            "checked": "2026-09-04",
            "agent": "integral-job-search/0.1",
            "standing": SINGLE_PARSER,
            "second_reader": "not_run",
            "source": "connectors/robots-adjudications.yaml",
            "reason": "one parser only",
        },
    ),
    (
        "an agreement whose own robots.txt shows the second reader cannot refuse on it",
        {
            "site": "i.test",
            "checked": "2026-09-04",
            "agent": "integral-job-search/0.1",
            "standing": TWO_PARSERS_AGREED,
            "second_reader": "urllib.robotparser",
            "source": "connectors/robots-adjudications.yaml",
            "allowed": ["/jobs"],
            "second_reader_refused": ["/apply"],
            "robots_txt": "User-agent: *\nAllow: /\nDisallow: /apply\n",
        },
    ),
    (
        "no negative control possible, on a file that refuses one",
        {
            "site": "j.test",
            "checked": "2026-09-04",
            "agent": "integral-job-search/0.1",
            "standing": NO_NEGATIVE_CONTROL_POSSIBLE,
            "second_reader": "urllib.robotparser",
            "source": "connectors/robots-adjudications.yaml",
            "reason": "claimed to refuse nothing",
            "robots_txt": "User-agent: *\nDisallow: /a*\nAllow: /ax\n",
        },
    ),
    (
        "a row admitting a path its own robots.txt refuses",
        {
            "site": "k.test",
            "checked": "2026-09-04",
            "agent": "integral-job-search/0.1",
            "standing": TWO_PARSERS_AGREED,
            "second_reader": "urllib.robotparser",
            "source": "connectors/robots-adjudications.yaml",
            "allowed": ["/admin/x"],
            "second_reader_refused": ["/admin/"],
            "robots_txt": "User-agent: *\nDisallow: /admin/\n",
        },
    ),
    (
        "an agent naming no decidable product token",
        {
            "site": "l.test",
            "checked": "2026-09-04",
            "agent": "Mozilla/5.0 (compatible; integral-job-search/0.1)",
            "standing": SINGLE_PARSER,
            "second_reader": NOT_RUN,
            "source": "connectors/robots-adjudications.yaml",
            "reason": "one parser only",
        },
    ),
    (
        "a second reader that is prose rather than a parser",
        {
            "site": "m.test",
            "checked": "2026-09-04",
            "agent": "integral-job-search/0.1",
            "standing": SINGLE_PARSER,
            "second_reader": "read it myself",
            "source": "connectors/robots-adjudications.yaml",
            "reason": "one parser only",
        },
    ),
    (
        "one path listed as both admitted and refused",
        {
            "site": "n.test",
            "checked": "2026-09-04",
            "agent": "integral-job-search/0.1",
            "standing": TWO_PARSERS_AGREED,
            "second_reader": "urllib.robotparser",
            "source": "connectors/robots-adjudications.yaml",
            "allowed": ["/admin/"],
            "second_reader_refused": ["/admin/"],
        },
    ),
    (
        "a single-parser row that does not say whether the reader ever ran",
        {
            "site": "o.test",
            "checked": "2026-09-04",
            "agent": "integral-job-search/0.1",
            "standing": SINGLE_PARSER,
            "source": "connectors/robots-adjudications.yaml",
            "reason": "one parser only",
        },
    ),
)


def adjudications(path: Path = DEFAULT_ADJUDICATIONS_PATH) -> list[RobotsAdjudication]:
    """Every row in the adjudication record."""
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise AdjudicationLedgerError(f"{path}: could not be read: {exc}") from exc
    if not isinstance(payload, dict):
        raise AdjudicationLedgerError(f"{path}: is not a mapping")
    rows = payload.get("adjudications")
    if not isinstance(rows, list):
        raise AdjudicationLedgerError(f"{path}: `adjudications` is not a list")
    return [RobotsAdjudication.from_mapping(row) for row in rows]


def shipped_packages(packages_dir: Path = DEFAULT_PACKAGES_DIR) -> list[str]:
    """Every connector package directory, repo-relative — the coverage set."""
    if not packages_dir.is_dir():
        return []
    return sorted(
        f"{packages_dir.name}/{child.name}" for child in packages_dir.iterdir() if child.is_dir()
    )


def measure_second_readers(
    path: Path = DEFAULT_ADJUDICATIONS_PATH,
    *,
    packages_dir: Path = DEFAULT_PACKAGES_DIR,
    fixtures: tuple[_CompetenceFixture, ...] = COMPETENCE_FIXTURES,
    controls: tuple[tuple[str, dict[str, Any]], ...] = MALFORMED_ADJUDICATIONS,
    repo_root: Path = _REPO_ROOT,
) -> dict[str, Any]:
    """T116's gate: `robots_adjudications_misrepresenting_their_standing`.

    Four things go through one number, because all four are ways one record can
    say something the file underneath it does not support: a row whose claim it
    cannot establish (including one its own committed `robots_txt` contradicts),
    a malformed control accepted, a shipped package with no record at all — the
    record silently standing for a fetch it never adjudicated — and a
    constructed file the classifier itself gets wrong, which is the machine that
    assigns standings being broken.

    **`robots_adjudications_without_a_competent_second_reader` is measured here
    too, and it is not this gate.** It is the honest count of adjudications
    whose second reader is not competent, which is 19 of 20 today and which no
    amount of correct recording can reduce — see the module docstring.
    """
    live = adjudications(path)
    violations = [problem for row in live for problem in row.problems(repo_root)]
    unearned = sum(1 for row in live if row.problems(repo_root))

    accepted = [
        name
        for name, payload in controls
        if not RobotsAdjudication.from_mapping(payload).problems(repo_root)
    ]
    violations += [f"accepted a malformed adjudication: {name}" for name in accepted]

    recorded = {row.package for row in live if row.package}
    packages = shipped_packages(packages_dir)
    uncovered = [package for package in packages if package not in recorded]
    violations += [
        f"{package}: a shipped connector package with no adjudication record — a fetch "
        "admitted with no second reader at all"
        for package in uncovered
    ]

    misclassified = []
    for fixture in fixtures:
        found = _classify(fixture.robots_txt, fixture.agent)
        if found.verdict != fixture.expected:
            misclassified.append(
                {
                    "name": fixture.name,
                    "section": fixture.section,
                    "expected": fixture.expected,
                    "actual": found.verdict,
                    "controls_tried": list(found.controls_tried),
                    "rfc_refused": list(found.rfc_refused),
                    "second_reader_refused": list(found.second_reader_refused),
                }
            )
    violations += [
        f"competence fixture {case['name']}: {case['section']} requires "
        f"{case['expected']}, classifier says {case['actual']}"
        for case in misclassified
    ]

    checked = len(live) + len(controls) + len(fixtures)
    floored = checked >= ADJUDICATIONS_AT_LEAST and len(packages) >= PACKAGES_AT_LEAST
    standings = {
        standing: sum(1 for row in live if row.standing == standing) for standing in STANDINGS
    }
    # The two findings `single_parser` used to hold at once. `not_run` is the
    # discriminator, and until it was validated it was also unnamed: the record
    # said "one parser" for a reader that ran and could not refuse and for one
    # nobody ever invoked, which are different things to fix.
    ran = [row for row in live if row.standing == SINGLE_PARSER and row.second_reader != NOT_RUN]
    single_parser_cases = {
        "second_reader_ran_and_could_not_refuse": len(ran),
        "second_reader_never_run": standings[SINGLE_PARSER] - len(ran),
    }
    # The literal count the metric's name has always described: an adjudication
    # stands on a competent second reader only when it claims an agreement AND
    # establishes it. Everything else — every honest `single_parser`, the file
    # admitting no control, and any row that fails its own checks — does not.
    without_a_competent_second_reader = sum(
        1 for row in live if row.standing != TWO_PARSERS_AGREED or row.problems(repo_root)
    )
    return {
        "robots_adjudications_misrepresenting_their_standing": (
            unearned + len(accepted) + len(uncovered) + len(misclassified)
        ),
        "robots_adjudications_misrepresenting_their_standing_evaluated": checked,
        "robots_adjudications_without_a_competent_second_reader": (
            without_a_competent_second_reader
        ),
        "robots_adjudications_checked": checked,
        "live_adjudications": len(live),
        "shipped_packages": len(packages),
        "controls_checked": len(controls),
        "competence_fixtures_checked": len(fixtures),
        "packages_without_an_adjudication_record": len(uncovered),
        "standings": standings,
        "single_parser_cases": single_parser_cases,
        # `unmeasured` is the honest reading of a scan too small to mean
        # anything — not a pass, and not a fail.
        "gate_status": "measured" if floored else "unmeasured",
        "sites": sorted(row.site for row in live if row.site),
        "misclassified_fixtures": misclassified,
        "violations": violations,
    }


def record_second_readers(measured: dict[str, Any]) -> dict[str, Any]:
    """What is committed, out of what was measured.

    The denominators go out and the floors they were checked against go in:
    a count of the day makes every added connector an evidence drift, which is
    T100's finding one module over. The live numbers stay in what the tests
    assert — they are just not the thing a committed record has to hold still.
    """
    moving = (
        "robots_adjudications_misrepresenting_their_standing_evaluated",
        "robots_adjudications_checked",
        "live_adjudications",
        "shipped_packages",
    )
    committed = {key: value for key, value in measured.items() if key not in moving}
    committed["robots_adjudications_at_least"] = ADJUDICATIONS_AT_LEAST
    committed["shipped_packages_at_least"] = PACKAGES_AT_LEAST
    return committed


def write_second_reader_evidence(
    evidence: Path = DEFAULT_T116_EVIDENCE_PATH,
    path: Path = DEFAULT_ADJUDICATIONS_PATH,
) -> dict[str, Any]:
    """Measure and record `status/evidence/T116.json`."""
    measured = measure_second_readers(path)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(record_second_readers(measured), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return measured


_KNOWN_OPTIONS = frozenset({"--second-readers"})


def _run_second_readers(target: Path) -> int:
    try:
        measured = write_second_reader_evidence(target)
    except AdjudicationLedgerError as exc:
        print(f"connector_policy: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(record_second_readers(measured), ensure_ascii=False))
    for violation in measured["violations"]:
        print(violation, file=sys.stderr)
    if measured["robots_adjudications_misrepresenting_their_standing"]:
        return 1
    if measured["gate_status"] == "unmeasured":
        print(
            "robots_adjudications_misrepresenting_their_standing: UNMEASURED — the "
            "scan is under its floor. Not a pass and not a fail.",
            file=sys.stderr,
        )
        return 3
    return 0


def _run_owner_decisions(target: Path) -> int:
    try:
        measured = write_evidence(target)
    except PolicyLedgerError as exc:
        # Exit 3, not 1: nothing was read, so nothing passed and nothing failed.
        print(f"connector_policy: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(measured, ensure_ascii=False))
    for violation in measured["violations"]:
        print(violation, file=sys.stderr)
    if measured["policy_refusals_without_an_owner_decision"]:
        return 1
    if measured["gate_status"] == "unmeasured":
        print(
            "policy_refusals_without_an_owner_decision: UNMEASURED — no refusal was "
            "read. Not a pass and not a fail.",
            file=sys.stderr,
        )
        return 3
    return 0


def _main(argv: list[str]) -> int:
    """`python -m integral.connector_policy [--second-readers] [path]`.

    A bare invocation writes **both** evidence files, T99's and T116's — the
    same reason `robots.py` writes T70 and T71 on a bare run: `make evidence`
    runs each module once and has no way to know a module owns two gates.
    Naming `--second-readers` writes T116 alone, so that gate block's own
    invocation stays precise.
    """
    options = [arg for arg in argv[1:] if arg.startswith("--")]
    unknown = [arg for arg in options if arg not in _KNOWN_OPTIONS]
    if unknown:
        print(
            f"connector_policy: unknown option(s) {' '.join(unknown)} — "
            f"expected any of {' '.join(sorted(_KNOWN_OPTIONS))}",
            file=sys.stderr,
        )
        return 2

    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    if len(positional) > 1:
        print(
            f"connector_policy: expected at most one path, got {len(positional)}: "
            f"{' '.join(positional)}",
            file=sys.stderr,
        )
        return 2

    if "--second-readers" in options:
        return _run_second_readers(
            Path(positional[0]) if positional else DEFAULT_T116_EVIDENCE_PATH
        )
    if positional:
        return _run_owner_decisions(Path(positional[0]))
    # `worst`, never `max`: `max(1, 3) == 3`, and 3 is what `make evidence`
    # prints as `unmeasured (recorded)` before continuing — so a real T99
    # failure was swallowed whenever T116's scan happened to be under its
    # floor. Failure outranks unmeasured (`integral.gate_exit`).
    return worst(
        _run_owner_decisions(DEFAULT_EVIDENCE_PATH),
        _run_second_readers(DEFAULT_T116_EVIDENCE_PATH),
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
