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
  path RFC 9309 also refuses. Refusing a path the RFC *allows* is not
  competence — it is the same parser being wrong in the other direction — and
  one fixture exists for exactly that.
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

An honest `single_parser` is **not** counted. The task's own scope says so —
"where it cannot, the adjudication is single-parser and must be recorded as
such rather than counted as agreement" — and a metric that counted it could
only reach zero by re-running every board with a parser that does not exist
yet, which would make the gate unpassable and therefore unread. What is
forbidden is *calling it an agreement*.
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
INCOMPETENT = "incompetent"
NO_CONTROL_POSSIBLE = "no_control_possible"

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
    """
    tried: list[str] = []
    rfc_refused: list[str] = []
    agreed: list[str] = []
    false_refusals: list[str] = []
    for pattern in robots.disallow_patterns(text, agent):
        target = robots.sample_path(pattern)
        if target is None or target in tried:
            continue
        tried.append(target)
        rfc_allows = robots.allows_text(text, agent, target)
        second_allows = second_reader_allows(text, agent, target)
        if not rfc_allows:
            rfc_refused.append(target)
            if not second_allows:
                agreed.append(target)
        elif not second_allows:
            false_refusals.append(target)
    if not rfc_refused:
        verdict = NO_CONTROL_POSSIBLE
    elif agreed:
        verdict = COMPETENT
    else:
        verdict = INCOMPETENT
    return Competence(
        verdict=verdict,
        controls_tried=tuple(tried),
        rfc_refused=tuple(rfc_refused),
        second_reader_refused=tuple(agreed),
        second_reader_false_refusals=tuple(false_refusals),
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

    @classmethod
    def from_mapping(cls, payload: Any) -> RobotsAdjudication:
        """Read one row, tolerating everything — the reading is the check."""
        if not isinstance(payload, dict):
            return cls("", "", None, "", "", "", "", (), (), "")

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
            if not self.second_reader or self.second_reader == "not_run":
                found.append(
                    f"{where}: claims two parsers agreed while `second_reader` is "
                    f"{self.second_reader or 'unset'!r}"
                )
        else:
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
        return found


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
    """T116's gate: `robots_adjudications_without_a_competent_second_reader`.

    Three things go through one number, because all three are ways the same
    claim can be empty: a recorded agreement that cannot show a refusal, a
    shipped package with no record at all, and a constructed file the
    classifier gets wrong.
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
    return {
        "robots_adjudications_without_a_competent_second_reader": (
            unearned + len(accepted) + len(uncovered) + len(misclassified)
        ),
        "robots_adjudications_without_a_competent_second_reader_evaluated": checked,
        "robots_adjudications_checked": checked,
        "live_adjudications": len(live),
        "shipped_packages": len(packages),
        "controls_checked": len(controls),
        "competence_fixtures_checked": len(fixtures),
        "packages_without_an_adjudication_record": len(uncovered),
        "standings": standings,
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
        "robots_adjudications_without_a_competent_second_reader_evaluated",
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
    if measured["robots_adjudications_without_a_competent_second_reader"]:
        return 1
    if measured["gate_status"] == "unmeasured":
        print(
            "robots_adjudications_without_a_competent_second_reader: UNMEASURED — the "
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
    return max(
        _run_owner_decisions(DEFAULT_EVIDENCE_PATH),
        _run_second_readers(DEFAULT_T116_EVIDENCE_PATH),
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
