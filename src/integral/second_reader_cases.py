"""RFC 9309's verdicts for 51 constructed cases, derived by second sessions.

**Nothing in this file was written by the session that wrote
`integral.second_reader`, and nothing in it was decided by running code.**
That is the whole point, and it is CLAUDE.md's rule for exactly this family of
work: a gate a worker writes alongside its own implementation judges that
implementation by the author's own reading of the spec, so when the reading is
wrong the code and the fixtures are wrong together and the gate is green. T70
took ten defects across five review rounds learning it, eight of them
introduced by the session fixing the previous one.

So these cases were produced by a separate session, under three instructions:
read RFC 9309 first and derive every case from its text; never settle a verdict
by running code; and weight the table toward **fail-open** — a path the rules
forbid that a weak matcher would allow. A fail-closed bug costs one skipped
fetch; a fail-open bug means the check said yes to something it exists to
refuse. That session returned 31 `FAIL_OPEN_RISK` cases, 17 `FAIL_CLOSED_RISK`
and one neutral, each citing the section its verdict was read off.

Cases 50 and 51 arrived the same way and later: the session that reviewed the
reader's pull request derived two more from §2.2.2's text, both `FAIL_OPEN_RISK`,
and both ALLOW at the time against a table of 49 that was already green. The
comment above them says what the first 49 missed. The rule the file is built on
is unchanged — the session that writes a case is never the session whose code it
judges — and it has now been applied three times. Cases 54-59 came from the third
round, and they are the inverse of what 52 and 53 closed: those two found §2.2.3's
metacharacter hold-out wrongly applied to a request **target**, and this round found
it wrongly applied to the **position** — every `$` in a pattern exempted, when
§2.2.3 names one position and case 22 had already ruled the others ordinary octets.
Five shapes, all fail-open. Three rounds have now each closed one side of the same
equivalence, which is the argument for the discipline rather than against it: each
round's fixtures were derived from the RFC by a session that had not written the
fix, and each found what the previous round's author could not see.

The prose it wrote — its provenance statement, its reading of the two
specificity interpretations, and the full derivation of every row — is kept
verbatim at `docs/rfc9309-second-reader-cases.md`. This module is a mechanical
transcription of that document, not a retyping of it.

**Citations are RECOLLECTED.** Egress is blocked in this repository and
`https://www.rfc-editor.org/rfc/rfc9309.txt` answers 403, so section numbers and
quoted fragments are recalled rather than fetched — the same convention every
other RFC citation here carries. `confidence` records how sure that session was
that the RFC settles the case at all; a `LOW` row is a case where two readings
survive the text, and the document says which reading it took and why.

Two conventions worth stating here because the verdicts depend on them:

* **"Path" means path and query.** §2.2.2's own example table adjudicates
  `/foo/bar?baz=quz`, so the query string is part of what a rule matches.
* **Specificity is counted on the pattern as written**, `*` and `$` included —
  not on the span of the request a wildcard expansion consumed. The RFC's
  wildcard-free examples cannot distinguish the two readings; cases 23-25 are
  built so the choice is tested rather than assumed, and are marked accordingly.
"""

from __future__ import annotations

from dataclasses import dataclass

ALLOW_VERDICT = "ALLOW"
DISALLOW_VERDICT = "DISALLOW"
VERDICTS = (ALLOW_VERDICT, DISALLOW_VERDICT)

#: The failure a weak matcher would make on a case. `FAIL_OPEN_RISK` is the one
#: that matters: the RFC refuses the path and a weak matcher allows it, so a
#: fetch the check exists to refuse goes out.
FAIL_OPEN_RISK = "FAIL_OPEN_RISK"
FAIL_CLOSED_RISK = "FAIL_CLOSED_RISK"
NEUTRAL = "NEUTRAL"
DIRECTIONS = (FAIL_OPEN_RISK, FAIL_CLOSED_RISK, NEUTRAL)

#: How sure the deriving session was that RFC 9309's text settles the case.
CONFIDENCES = ("HIGH", "MEDIUM", "LOW")


@dataclass(frozen=True)
class Case:
    """One robots.txt, one request path, and the verdict the RFC requires.

    `expected` is a statement about the **spec**, not about any parser. It was
    written down before this repository's reader existed, and a case that fails
    is a defect in the reader until the derivation in `why` is shown to be
    wrong — never the other way round.
    """

    id: str
    robots_txt: str
    agent: str
    path: str
    expected: str
    #: The section the verdict was read off, so a later reader can check the
    #: derivation rather than the code.
    section: str
    why: str
    direction: str
    confidence: str = "HIGH"
    #: What the deriving session said about a case the RFC does not settle in
    #: one sentence: which readings survive its text, and why it took the one it
    #: took. Kept because a `LOW` with no argument behind it is not a case, it
    #: is a guess wearing a label.
    confidence_note: str = ""


CASES: tuple[Case, ...] = (
    # ---- 1. allow_root_then_longer_disallow -----------------------------
    Case(
        id="allow_root_then_longer_disallow",
        robots_txt="""User-agent: *
Allow: /
Disallow: /admin/
""",
        agent="integral-job-search/0.1",
        path="/admin/users",
        expected=DISALLOW_VERDICT,
        section="2.2.2 — RECOLLECTED",
        why=(
            '"The most specific match found MUST be used. The most specific match is the match '
            'that has the most octets." `Disallow: /admin/` matches 7 octets, `Allow: /` '
            "matches 1. File order is not part of the rule."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="HIGH",
    ),
    # ---- 2. allow_subtree_then_longer_disallow --------------------------
    Case(
        id="allow_subtree_then_longer_disallow",
        robots_txt="""User-agent: *
Allow: /jobs/
Disallow: /jobs/internal/
""",
        agent="integral-job-search/0.1",
        path="/jobs/internal/7",
        expected=DISALLOW_VERDICT,
        section="2.2.2 — RECOLLECTED",
        why=(
            "15 octets beats 6. A first-match-in-file-order matcher returns the `Allow` and "
            "fetches a page the operator fenced off."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="HIGH",
    ),
    # ---- 3. disallow_then_longer_allow ----------------------------------
    Case(
        id="disallow_then_longer_allow",
        robots_txt="""User-agent: *
Disallow: /jobs/
Allow: /jobs/public/
""",
        agent="integral-job-search/0.1",
        path="/jobs/public/1",
        expected=ALLOW_VERDICT,
        section="2.2.2 — RECOLLECTED",
        why=(
            "`Allow: /jobs/public/` is 13 octets against the `Disallow`'s 6, so the allow is "
            "the most specific match. This is the mirror of case 1 and catches a matcher that "
            '"resolves conflicts by preferring Disallow".'
        ),
        direction=FAIL_CLOSED_RISK,
        confidence="HIGH",
    ),
    # ---- 4. tie_disallow_first_allow_wins -------------------------------
    Case(
        id="tie_disallow_first_allow_wins",
        robots_txt="""User-agent: *
Disallow: /a/b/
Allow: /a/b/
""",
        agent="integral-job-search/0.1",
        path="/a/b/c.html",
        expected=ALLOW_VERDICT,
        section="2.2.2 — RECOLLECTED",
        why=(
            '"If an allow rule and a disallow rule are equivalent, then the allow rule SHOULD '
            'be used." Both patterns are 5 octets.'
        ),
        direction=FAIL_CLOSED_RISK,
        confidence="HIGH",
    ),
    # ---- 5. tie_allow_first_allow_wins ----------------------------------
    Case(
        id="tie_allow_first_allow_wins",
        robots_txt="""User-agent: *
Allow: /a/b/
Disallow: /a/b/
""",
        agent="integral-job-search/0.1",
        path="/a/b/c.html",
        expected=ALLOW_VERDICT,
        section="2.2.2 — RECOLLECTED",
        why=(
            "Same tie, opposite file order — the verdict must not move, because the tiebreak is "
            '"allow wins", not "last wins" or "first wins". Cases 4 and 5 together pin that: a '
            "matcher that passes one by accident of ordering fails the other."
        ),
        direction=FAIL_CLOSED_RISK,
        confidence="HIGH",
    ),
    # ---- 6. disallow_all_with_longer_allow ------------------------------
    Case(
        id="disallow_all_with_longer_allow",
        robots_txt="""User-agent: *
Disallow: /
Allow: /jobs/
""",
        agent="integral-job-search/0.1",
        path="/jobs/1234",
        expected=ALLOW_VERDICT,
        section="2.2.2 — RECOLLECTED",
        why=(
            '6 octets beats 1. The "closed by default, one door open" idiom; a matcher that '
            "short-circuits on `Disallow: /` reads it as a whole-site ban."
        ),
        direction=FAIL_CLOSED_RISK,
        confidence="HIGH",
    ),
    # ---- 7. disallow_all_allow_does_not_reach ---------------------------
    Case(
        id="disallow_all_allow_does_not_reach",
        robots_txt="""User-agent: *
Disallow: /
Allow: /jobs/
""",
        agent="integral-job-search/0.1",
        path="/about",
        expected=DISALLOW_VERDICT,
        section="2.2.2 — RECOLLECTED",
        why=(
            "Same file as case 6, a path the `Allow` does not match at all, so the only "
            'matching rule is `Disallow: /`. Paired with 6 it catches a matcher that "opens the '
            'site" once any `Allow` is present.'
        ),
        direction=FAIL_OPEN_RISK,
        confidence="HIGH",
    ),
    # ---- 8. empty_disallow_value_allows_all -----------------------------
    Case(
        id="empty_disallow_value_allows_all",
        robots_txt="""User-agent: *
Disallow:
""",
        agent="integral-job-search/0.1",
        path="/anything/at/all",
        expected=ALLOW_VERDICT,
        section="2.2 (ABNF `empty-pattern = *WS`) and 2.2.2 — RECOLLECTED",
        why=(
            'The ABNF admits `rule = *WS ("allow" / "disallow") *WS ":" *WS (path-pattern / '
            "empty-pattern) EOL`, so an empty value is a well-formed line and not a parse "
            "error. It states no path, so no path matches it, and §2.2.2's fallback applies: "
            '"If no match is found amongst the rules in a group for a matching user agent, or '
            'there are no rules in the group, the URI is allowed." This is also the historical '
            "meaning of a bare `Disallow:` — the 1994 convention's way of spelling \"everything "
            'is open".'
        ),
        direction=FAIL_CLOSED_RISK,
        confidence="MEDIUM",
        confidence_note=(
            "the RFC admits the syntax but (as recalled) does not spell out the semantics of "
            'the empty pattern in one sentence. The competing reading, "an empty pattern '
            'matches every path with 0 octets", would make this DISALLOW and would invert every '
            "legacy robots.txt on the web; it is rejected here for that reason, not on a quoted "
            "line."
        ),
    ),
    # ---- 9. three_rules_middle_length_loses -----------------------------
    Case(
        id="three_rules_middle_length_loses",
        robots_txt="""User-agent: *
Allow: /jobs/internal/preview/
Disallow: /jobs/internal/
Allow: /jobs/
""",
        agent="integral-job-search/0.1",
        path="/jobs/internal/x",
        expected=DISALLOW_VERDICT,
        section="2.2.2 — RECOLLECTED",
        why=(
            "Only two of the three rules match this path: `Disallow: /jobs/internal/` (15) and "
            "`Allow: /jobs/` (6). The longest *matching* rule wins; the longer `Allow` at the "
            "top of the file matches nothing here and must not be counted. This separates "
            '"longest rule in the file" from "longest rule that matches".'
        ),
        direction=FAIL_OPEN_RISK,
        confidence="HIGH",
    ),
    # ---- 10. prefix_match_crosses_segment_boundary -----------------------
    Case(
        id="prefix_match_crosses_segment_boundary",
        robots_txt="""User-agent: *
Disallow: /admin
""",
        agent="integral-job-search/0.1",
        path="/administrator/login",
        expected=DISALLOW_VERDICT,
        section="2.2.2 — RECOLLECTED",
        why=(
            'A rule is a *prefix* pattern — "The matching MUST start with the first octet of '
            'the path" and nothing terminates it. There is no implicit path-segment boundary, '
            "so `/admin` covers `/administrator`."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="HIGH",
    ),
    # ---- 11. match_must_start_at_first_octet -----------------------------
    Case(
        id="match_must_start_at_first_octet",
        robots_txt="""User-agent: *
Disallow: /secret
""",
        agent="integral-job-search/0.1",
        path="/en/secret/page",
        expected=ALLOW_VERDICT,
        section="2.2.2 — RECOLLECTED",
        why=(
            '"The matching MUST start with the first octet of the path." `/secret` is present '
            "in the request path but not at its start, so the rule does not match and no rule "
            "does. A substring matcher wrongly refuses."
        ),
        direction=FAIL_CLOSED_RISK,
        confidence="HIGH",
    ),
    # ---- 12. leading_wildcard_reaches_interior ---------------------------
    Case(
        id="leading_wildcard_reaches_interior",
        robots_txt="""User-agent: *
Disallow: /*secret
""",
        agent="integral-job-search/0.1",
        path="/en/secret/page",
        expected=DISALLOW_VERDICT,
        section="2.2.3 — RECOLLECTED",
        why=(
            '`*` "designates 0 or more instances of any character", so `/*secret` anchors at '
            "the first octet and then skips `en/`. This is how an operator writes the interior "
            "match case 11 denies to a bare pattern — a matcher treating `*` as a literal "
            "asterisk finds no match and fetches."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="HIGH",
    ),
    # ---- 13. trailing_slash_is_significant -------------------------------
    Case(
        id="trailing_slash_is_significant",
        robots_txt="""User-agent: *
Disallow: /jobs/
""",
        agent="integral-job-search/0.1",
        path="/jobs",
        expected=ALLOW_VERDICT,
        section="2.2.2 — RECOLLECTED",
        why=(
            "Matching is octet-by-octet from the first octet; the pattern's 6th octet is `/` "
            "and the request path has no 6th octet. The rule does not match. A matcher that "
            '"normalises" a trailing slash away refuses a page the operator left open — and, '
            "worse, the same normalisation in the other direction would open `/jobs/x` under "
            "`Disallow: /jobs` cases."
        ),
        direction=FAIL_CLOSED_RISK,
        confidence="HIGH",
    ),
    # ---- 14. star_matches_empty_sequence ---------------------------------
    Case(
        id="star_matches_empty_sequence",
        robots_txt="""User-agent: *
Disallow: /jobs*/apply
""",
        agent="integral-job-search/0.1",
        path="/jobs/apply",
        expected=DISALLOW_VERDICT,
        section="2.2.3 — RECOLLECTED",
        why=(
            "`*` designates **0** or more instances of any character, so it matches the empty "
            "sequence between `/jobs` and `/apply`. A matcher requiring at least one character "
            "allows the exact page the rule names."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="HIGH",
    ),
    # ---- 15. double_star_matches_empty -----------------------------------
    Case(
        id="double_star_matches_empty",
        robots_txt="""User-agent: *
Disallow: /a**b
""",
        agent="integral-job-search/0.1",
        path="/ab",
        expected=DISALLOW_VERDICT,
        section="2.2.3 — RECOLLECTED",
        why=(
            "Two wildcards, each matching zero characters. `**` is not a distinct operator in "
            "RFC 9309 — it is just `*` twice, and it collapses."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="MEDIUM",
        confidence_note=(
            "the collapse follows from the definition of `*` rather than from any sentence "
            "about repeated wildcards. A naive backtracker can also blow up here rather than "
            'answer, which is its own fail-open if the error path defaults to "allow".'
        ),
    ),
    # ---- 16. trailing_star_is_not_a_boundary -----------------------------
    Case(
        id="trailing_star_is_not_a_boundary",
        robots_txt="""User-agent: *
Disallow: /admin*
""",
        agent="integral-job-search/0.1",
        path="/admin",
        expected=DISALLOW_VERDICT,
        section="2.2.3 — RECOLLECTED",
        why=(
            "The trailing `*` matches the empty sequence, so the pattern is satisfied by the "
            "bare `/admin` with nothing after it. A matcher that requires the wildcard to "
            "consume something allows the directory root while refusing everything under it."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="HIGH",
    ),
    # ---- 17. dollar_anchors_exact_path -----------------------------------
    Case(
        id="dollar_anchors_exact_path",
        robots_txt="""User-agent: *
Disallow: /page$
""",
        agent="integral-job-search/0.1",
        path="/page",
        expected=DISALLOW_VERDICT,
        section="2.2.3 — RECOLLECTED",
        why=(
            '`$` "designates the end of the match pattern": the pattern matches `/page` and '
            "requires the path to end there, which it does. A matcher treating `$` as a literal "
            "octet compares `/page$` against `/page`, finds no match, and fetches."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="HIGH",
    ),
    # ---- 18. dollar_rejects_longer_path ----------------------------------
    Case(
        id="dollar_rejects_longer_path",
        robots_txt="""User-agent: *
Disallow: /page$
""",
        agent="integral-job-search/0.1",
        path="/page/1",
        expected=ALLOW_VERDICT,
        section="2.2.3 — RECOLLECTED",
        why=(
            "The anchor requires the path to end at `/page`; `/page/1` continues, so nothing "
            "matches. Paired with 17 this is the pin: a literal-`$` matcher gets 18 right by "
            "accident while getting 17 wrong, so 18 alone proves nothing."
        ),
        direction=NEUTRAL,
        confidence="HIGH",
    ),
    # ---- 19. dollar_allow_homepage_only ----------------------------------
    Case(
        id="dollar_allow_homepage_only",
        robots_txt="""User-agent: *
Disallow: /
Allow: /$
""",
        agent="integral-job-search/0.1",
        path="/",
        expected=ALLOW_VERDICT,
        section="2.2.2 and 2.2.3 — RECOLLECTED",
        why=(
            'The standard "only the homepage" idiom. Both rules match `/`; under reading (P) '
            "`Allow: /$` is 2 octets against 1 and wins outright, and under reading (M) both "
            "match one octet and the allow wins the tie by §2.2.2's \"if an allow rule and a "
            'disallow rule are equivalent, then the allow rule SHOULD be used". Both readings '
            "agree, which is why this row is not in section D."
        ),
        direction=FAIL_CLOSED_RISK,
        confidence="HIGH",
    ),
    # ---- 20. star_dot_gif_dollar -----------------------------------------
    Case(
        id="star_dot_gif_dollar",
        robots_txt="""User-agent: *
Disallow: /*.gif$
""",
        agent="integral-job-search/0.1",
        path="/assets/img/photo.gif",
        expected=DISALLOW_VERDICT,
        section="2.2.3 — RECOLLECTED",
        why=(
            "The RFC's own worked example of the two special characters together: `*` spans "
            "`assets/img/photo`, `.gif` matches literally, `$` requires the path to end there."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="HIGH",
    ),
    # ---- 21. gif_dollar_defeated_by_query --------------------------------
    Case(
        id="gif_dollar_defeated_by_query",
        robots_txt="""User-agent: *
Disallow: /*.gif$
""",
        agent="integral-job-search/0.1",
        path="/assets/photo.gif?v=2",
        expected=ALLOW_VERDICT,
        section="2.2.2 and 2.2.3 — RECOLLECTED",
        why=(
            "§2.2.2's example table adjudicates `/foo/bar?baz=quz`, i.e. the string matched "
            "against includes the query, so this path ends at `2` and not at `.gif`; the `$` "
            'anchor therefore fails. The two rules that produce this — "query is included" and '
            '"`$` means end of the *whole* matched string" — are the same two that produce case '
            "35's DISALLOW, so a matcher cannot satisfy both by leaning one way."
        ),
        direction=FAIL_CLOSED_RISK,
        confidence="MEDIUM",
        confidence_note=(
            "rests on the query being part of the matched string, which the example table shows "
            "rather than states in prose."
        ),
    ),
    # ---- 22. dollar_in_middle_of_pattern ---------------------------------
    Case(
        id="dollar_in_middle_of_pattern",
        robots_txt="""User-agent: *
Disallow: /a$b
""",
        agent="integral-job-search/0.1",
        path="/a$b",
        expected=DISALLOW_VERDICT,
        section="2.2.3 — RECOLLECTED",
        why=(
            '§2.2.3 defines `$` as "the end of the match pattern", which describes a character '
            "at the end of a pattern and says nothing about one in the middle. Two readings "
            "survive: (a) `$` is special only in final position, so here it is an ordinary "
            "octet and the pattern matches the literal path `/a$b`; (b) `$` always anchors, so "
            "the pattern is `/a` anchored, nothing after it is reachable, and the rule matches "
            "only `/a` — making this ALLOW. **This table takes (a)**, because it is the reading "
            "under which the operator gets what they wrote, and because it is fail-closed "
            "relative to (b)."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="LOW",
        confidence_note=(
            "the RFC does not settle mid-pattern `$`: reading (a) and reading (b) both survive "
            "§2.2.3's sentence, and this table takes (a) because it is the fail-closed one. "
            "That much is unchanged. **The second wrinkle this note used to carry is now "
            "settled and is recorded here rather than deleted.** It read: `$` is a sub-delim "
            "under RFC 3986, so a request URI carrying it may arrive as `/a%24b`, and whether "
            "a rule's literal `$` should be encoded before comparison is 'also unsettled'. It "
            "is not independent of reading (a) — it is a consequence of it. Once a non-final "
            "`$` is an ordinary octet (which is what (a) says, and what makes THIS row "
            "DISALLOW), it is an ordinary octet in RFC 3986's reserved range, and §2.2.2 says "
            "such octets 'MUST be percent-encoded ... prior to comparison' with no exception "
            "for rules. So taking (a) and then exempting the `$` from §2.2.2 is not a second "
            "open question, it is a contradiction: the same character called data by one "
            "section's reading and a metacharacter by the other's. Cases 54-58 are where that "
            "was measured — five shapes returning ALLOW under the exemption where §2.2.2 "
            "requires DISALLOW — and case 59 pins the half of §2.2.3 that survives it, the "
            "trailing `$`. What stays unsettled is only reading (a) versus (b); a matcher "
            "disagreeing on THAT is a finding to discuss, not a defect to fix blind."
        ),
    ),
    # ---- 23. wildcard_specificity_readings_agree -------------------------
    Case(
        id="wildcard_specificity_readings_agree",
        robots_txt="""User-agent: *
Allow: /a/b/
Disallow: /a/*/secret
""",
        agent="integral-job-search/0.1",
        path="/a/b/secret",
        expected=DISALLOW_VERDICT,
        section="2.2.2 — RECOLLECTED",
        why=(
            "The disallow scores 11 under (P) (`/a/*/secret` as written) and 11 under (M) (the "
            "whole path consumed); the allow scores 5 either way. Both readings disallow, so a "
            "matcher failing this one is not failing on the ambiguity — it is failing on "
            "wildcards or on longest-match."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="MEDIUM",
    ),
    # ---- 24. wildcard_specificity_readings_diverge -----------------------
    Case(
        id="wildcard_specificity_readings_diverge",
        robots_txt="""User-agent: *
Allow: /a*
Disallow: /abc
""",
        agent="integral-job-search/0.1",
        path="/abcd",
        expected=DISALLOW_VERDICT,
        section="2.2.2 — RECOLLECTED",
        why=(
            "Under **(P)** the allow pattern `/a*` is 3 octets and the disallow `/abc` is 4, so "
            "the disallow is more specific. Under **(M)** the allow's `*` consumes `bcd` and "
            "the allow's match is 5 octets against the disallow's 3, so the allow wins and the "
            "verdict flips to ALLOW. This table takes (P), so: DISALLOW."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="LOW",
        confidence_note=(
            "the divergence is the point. A matcher answering ALLOW here has taken reading (M) "
            "and is not necessarily wrong; report it as a reading disagreement and make the "
            "repo pick one deliberately, in writing."
        ),
    ),
    # ---- 25. dollar_specificity_readings_diverge -------------------------
    Case(
        id="dollar_specificity_readings_diverge",
        robots_txt="""User-agent: *
Disallow: /a/b$
Allow: /a/b
""",
        agent="integral-job-search/0.1",
        path="/a/b",
        expected=DISALLOW_VERDICT,
        section="2.2.2 — RECOLLECTED",
        why=(
            "Under **(P)** `Disallow: /a/b$` counts the `$` and scores 5 against the allow's 4, "
            "so the disallow wins. Under **(M)** both consume exactly `/a/b` (4 octets), the "
            "rules are equivalent, and the allow wins the §2.2.2 tiebreak — ALLOW. This table "
            "takes (P): DISALLOW. Note this is the same shape as case 19 with the roles "
            "swapped, and there the two readings happened to agree; here they do not."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="LOW",
        confidence_note=(
            'whether an anchor character contributes to "the match that has the most octets" is '
            "exactly what the RFC leaves open, and it stays open — this row is still "
            "contested. What has been **narrowed** is which `$` the question is about, and the "
            "narrowing is worth recording because a `$`'s contribution to a pattern's length "
            "decides which rule wins. A **non-final** `$` is settled at three octets, and not "
            "by a new judgement: §2.2.2 requires reserved octets percent-encoded 'prior to "
            "comparison', the comparison and therefore the count run over the canonicalised "
            "pattern, and a literal `$` canonicalises to `%24` exactly as a literal `=` "
            "canonicalises to `%3D` and has always counted three. `$` and `=` are both "
            "sub-delims; no reading of §2.2.2 encodes one and exempts the other. So the "
            "shift from one octet to three is this table's existing rule applied "
            "consistently, not a change of reading. A **final** `$` is the anchor: §2.2.3 "
            "consumes it rather than comparing it, so §2.2.2 never reaches it, it stays one "
            "octet — and whether that one octet counts toward specificity is the question "
            "this row asks and does not answer. This row's own pattern, `/a/b$`, carries only "
            "the final kind, so nothing above moves its verdict; it is (P) versus (M) as "
            "written."
        ),
    ),
    # ---- 26. pct_unreserved_encoded_in_rule ------------------------------
    Case(
        id="pct_unreserved_encoded_in_rule",
        robots_txt="""User-agent: *
Disallow: /%7Euser/
""",
        agent="integral-job-search/0.1",
        path="/~user/cv.html",
        expected=DISALLOW_VERDICT,
        section="2.2.2 — RECOLLECTED",
        why=(
            "`~` is unreserved in RFC 3986, so `%7E` decodes to `~` before comparison and the "
            "rule is `/~user/`. A byte-comparing matcher sees `%7E` against `~`, finds no "
            "match, and fetches."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="HIGH",
    ),
    # ---- 27. pct_unreserved_encoded_in_path_lowercase_hex ----------------
    Case(
        id="pct_unreserved_encoded_in_path_lowercase_hex",
        robots_txt="""User-agent: *
Disallow: /~user/
""",
        agent="integral-job-search/0.1",
        path="/%7euser/cv.html",
        expected=DISALLOW_VERDICT,
        section="2.2.2 — RECOLLECTED",
        why=(
            "The same equivalence in the other direction, plus RFC 3986's rule that the hex "
            "digits of a percent-encoding are case-insensitive: `%7e` and `%7E` both decode to "
            "`~`. Case 26 and this one together stop a matcher that canonicalises only one "
            "side."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="MEDIUM",
        confidence_note=(
            "the direction is symmetric by construction; the hex-case half is RFC 3986's, cited "
            "through §2.2.2's reference to it."
        ),
    ),
    # ---- 28. pct_triplets_decode_to_baz ----------------------------------
    Case(
        id="pct_triplets_decode_to_baz",
        robots_txt="""User-agent: *
Disallow: /foo/bar/baz
""",
        agent="integral-job-search/0.1",
        path="/foo/bar/%62%61%7A",
        expected=DISALLOW_VERDICT,
        section="2.2.2 — RECOLLECTED",
        why=(
            "This is verbatim the last row of §2.2.2's example table: the path "
            '`/foo/bar/%62%61%7A` has "path to match" `/foo/bar/baz`. `b`, `a`, `z` are '
            "unreserved, so the triplets are gratuitous encodings and must be decoded before "
            "comparison. It is also the obvious evasion: encode every letter of a banned path."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="HIGH",
    ),
    # ---- 29. pct_encoded_slash_is_not_a_separator ------------------------
    Case(
        id="pct_encoded_slash_is_not_a_separator",
        robots_txt="""User-agent: *
Disallow: /a/b
""",
        agent="integral-job-search/0.1",
        path="/a%2Fb",
        expected=ALLOW_VERDICT,
        section="2.2.2 — RECOLLECTED",
        why=(
            "`/` is a gen-delim, i.e. reserved, and reserved octets stay percent-encoded "
            "through comparison — decoding `%2F` would change the URI's meaning, since an "
            "encoded slash is data inside one segment, not a path separator. So the canonical "
            "forms are `/a/b` and `/a%2Fb` and they differ. A matcher that blanket-unquotes the "
            "path refuses a distinct resource."
        ),
        direction=FAIL_CLOSED_RISK,
        confidence="HIGH",
    ),
    # ---- 30. pct_encoded_slash_in_rule_matches ---------------------------
    Case(
        id="pct_encoded_slash_in_rule_matches",
        robots_txt="""User-agent: *
Disallow: /a%2Fb
""",
        agent="integral-job-search/0.1",
        path="/a%2Fb",
        expected=DISALLOW_VERDICT,
        section="2.2.2 — RECOLLECTED",
        why=(
            "The other half of case 29 and the fail-open one: an operator who wrote `%2F` meant "
            "the encoded-slash resource, and it is what was requested. A matcher that "
            "canonicalises the rule by decoding everything turns it into `/a/b`, which does not "
            "match `/a%2Fb`, and fetches. 29 and 30 must both hold; passing one by choosing a "
            "global decode policy fails the other."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="MEDIUM",
    ),
    # ---- 31. reserved_octets_stay_encoded_in_query -----------------------
    Case(
        id="reserved_octets_stay_encoded_in_query",
        robots_txt="""User-agent: *
Disallow: /foo/bar?baz=https%3A%2F%2Ffoo.bar
""",
        agent="integral-job-search/0.1",
        path="/foo/bar?baz=https://foo.bar",
        expected=DISALLOW_VERDICT,
        section="2.2.2 — RECOLLECTED",
        why=(
            "Row two of §2.2.2's example table: the path `/foo/bar?baz=https://foo.bar` has "
            '"path to match" `/foo/bar?baz=https%3A%2F%2Ffoo.bar`, because `:` and `/` '
            "appearing as *data* inside a query value are reserved octets and get encoded "
            "before comparison. Note the tension with the same table's first row, where `?` and "
            "`=` acting as delimiters stay literal: the encoding applies to reserved octets "
            "used as data, not to the URI's own structural delimiters."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="HIGH",
    ),
    # ---- 32. non_ascii_utf8_is_percent_encoded ---------------------------
    Case(
        id="non_ascii_utf8_is_percent_encoded",
        robots_txt="""User-agent: *
Disallow: /jobs/ツ
""",
        agent="integral-job-search/0.1",
        path="/jobs/%E3%83%84",
        expected=DISALLOW_VERDICT,
        section="2.2.2 — RECOLLECTED",
        why=(
            "Rows three and four of the §2.2.2 example table: both `/foo/bar/U+E38384` and "
            '`/foo/bar/%E3%83%84` have "path to match" `/foo/bar/%E3%83%84`. Octets outside '
            "US-ASCII are percent-encoded before comparison, so a literal UTF-8 rule and a "
            "percent-encoded request path are the same string."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="HIGH",
    ),
    # ---- 33. bare_percent_is_not_an_escape -------------------------------
    Case(
        id="bare_percent_is_not_an_escape",
        robots_txt="""User-agent: *
Disallow: /sale/100%discount
""",
        agent="integral-job-search/0.1",
        path="/sale/100%discount",
        expected=DISALLOW_VERDICT,
        section="2.2.2 — RECOLLECTED",
        why=(
            "`%di` is not a valid percent-encoding triplet, so there is nothing to decode on "
            "either side and the two strings are octet-identical. The verdict is easy; the risk "
            "is the *implementation* — a decoder that raises on an invalid escape, or that "
            'silently drops the `%`, will disagree, and if the error path defaults to "allow" '
            "the failure is fail-open on a rule the operator wrote in plain sight."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="MEDIUM",
    ),
    # ---- 34. plus_is_not_a_space -----------------------------------------
    Case(
        id="plus_is_not_a_space",
        robots_txt="""User-agent: *
Disallow: /search/a+b
""",
        agent="integral-job-search/0.1",
        path="/search/a%20b",
        expected=ALLOW_VERDICT,
        section="2.2.2 — RECOLLECTED",
        why=(
            "In a URI path `+` is a literal plus (a sub-delim); `+` means space only under the "
            "`application/x-www-form-urlencoded` serialisation, which is not what §2.2.2's "
            "canonicalisation invokes. So the canonical forms are `/search/a+b` and "
            "`/search/a%20b`, which differ. A matcher that runs a form-decoder over paths "
            "refuses a page the operator did not name."
        ),
        direction=FAIL_CLOSED_RISK,
        confidence="LOW",
        confidence_note=(
            "RFC 9309 says nothing about `+` at all; this is read off RFC 3986 via §2.2.2's "
            "reference to it. In a *query* string the same case is genuinely murkier and is "
            "deliberately not asserted here."
        ),
    ),
    # ---- 35. query_is_part_of_the_matched_string -------------------------
    Case(
        id="query_is_part_of_the_matched_string",
        robots_txt="""User-agent: *
Disallow: /search
""",
        agent="integral-job-search/0.1",
        path="/search?q=developer&page=2",
        expected=DISALLOW_VERDICT,
        section="2.2.2 — RECOLLECTED",
        why=(
            "§2.2.2's example table adjudicates `/foo/bar?baz=quz` as a single string, so the "
            "query is matched, and a prefix rule of `/search` covers it. A matcher that splits "
            "the query off before matching still disallows here — but see case 36, which it "
            "fails."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="HIGH",
    ),
    # ---- 36. wildcard_question_mark_bans_queries -------------------------
    Case(
        id="wildcard_question_mark_bans_queries",
        robots_txt="""User-agent: *
Disallow: /*?
""",
        agent="integral-job-search/0.1",
        path="/jobs?page=2",
        expected=DISALLOW_VERDICT,
        section="2.2.3 (with 2.2.2 on what is matched) — RECOLLECTED",
        why=(
            'The common "no crawling of parameterised URLs" idiom: `*` spans `jobs` and the '
            "literal `?` must then be found in the matched string, which it is only because the "
            "query is part of that string. `?` is not a special character in a robots pattern. "
            "A matcher that strips the query finds no `?` and fetches every faceted URL on the "
            "site — which is precisely the load the operator wrote this rule to avoid."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="MEDIUM",
    ),
    # ---- 37. path_matching_is_case_sensitive -----------------------------
    Case(
        id="path_matching_is_case_sensitive",
        robots_txt="""User-agent: *
Disallow: /Private/
""",
        agent="integral-job-search/0.1",
        path="/private/notes",
        expected=ALLOW_VERDICT,
        section="2.2.2 — RECOLLECTED",
        why=(
            '"The matching SHOULD be case sensitive." `/Private/` and `/private/` are different '
            "paths, so no rule matches. This is the row that pairs against case 38: the *path* "
            "is case-sensitive while the *product token* is not, and a matcher with one global "
            "case policy gets exactly one of the two right."
        ),
        direction=FAIL_CLOSED_RISK,
        confidence="MEDIUM",
        confidence_note=(
            "it is a SHOULD, not a MUST, so a case-insensitive matcher is not strictly "
            "non-conformant; it is however fail-closed here and would be fail-open on the "
            "mirrored file."
        ),
    ),
    # ---- 38. product_token_matching_is_case_insensitive ------------------
    Case(
        id="product_token_matching_is_case_insensitive",
        robots_txt="""USER-AGENT: Integral-Job-Search
Disallow: /jobs/
""",
        agent="integral-job-search/0.1",
        path="/jobs/1",
        expected=DISALLOW_VERDICT,
        section="2.2.1 — RECOLLECTED",
        why=(
            '"The crawler MUST use case-insensitive matching to find the group that matches the '
            "product token\" — the RFC's own example is a crawler `foobot` matching a group "
            "`FOOBOT`. The directive keyword `USER-AGENT` is likewise case-insensitive (ABNF "
            "string literals are). A case-sensitive matcher finds no group, finds no `*` group "
            "either, and concludes the whole site is open."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="HIGH",
    ),
    # ---- 39. product_token_has_no_prefix_rule ----------------------------
    Case(
        id="product_token_has_no_prefix_rule",
        robots_txt="""User-agent: integral
Disallow: /

User-agent: *
Allow: /jobs/
""",
        agent="integral-job-search/0.1",
        path="/jobs/1",
        expected=ALLOW_VERDICT,
        section="2.2.1 — RECOLLECTED",
        why=(
            "§2.2.1 defines matching a group by the product token, case-insensitively, and "
            'defines no prefix rule and no "most specific token" rule. `integral` is not '
            "`integral-job-search`, so that group is not ours; with no specific group matching, "
            '"If no matching group exists, crawlers MUST obey the group with a user-agent line '
            'with the `*` value, if present", which allows `/jobs/`.'
        ),
        direction=FAIL_CLOSED_RISK,
        confidence="MEDIUM",
        confidence_note=(
            "asserted as the absence of a rule rather than the presence of one. A matcher doing "
            "substring or longest-prefix token matching lands on the `Disallow: /` group; that "
            "is the widespread-in-practice behaviour, but it is not what the RFC describes."
        ),
    ),
    # ---- 40. version_suffix_is_not_part_of_the_token ---------------------
    Case(
        id="version_suffix_is_not_part_of_the_token",
        robots_txt="""User-agent: integral-job-search
Disallow: /jobs/

User-agent: *
Allow: /
""",
        agent="integral-job-search/0.1",
        path="/jobs/1",
        expected=DISALLOW_VERDICT,
        section="2.2.1 — RECOLLECTED",
        why=(
            '"The product token MUST contain only uppercase and lowercase letters ("a-z" and '
            '"A-Z"), underscores ("_"), and hyphens ("-")" — so `/0.1` cannot be part of a '
            "token, and the token this crawler matches on is `integral-job-search`. The "
            "specific group matches; the `*` group is therefore never consulted. A matcher "
            "comparing the full User-Agent string finds no group, falls through to `*`, and "
            "fetches a directory named for it."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="MEDIUM",
        confidence_note=(
            "the token-charset sentence is recalled with confidence; that a crawler must strip "
            "its own version suffix before matching is the natural consequence rather than a "
            "separate quoted rule."
        ),
    ),
    # ---- 41. star_group_ignored_when_specific_group_matches --------------
    Case(
        id="star_group_ignored_when_specific_group_matches",
        robots_txt="""User-agent: *
Disallow: /

User-agent: integral-job-search
Allow: /jobs/
""",
        agent="integral-job-search/0.1",
        path="/about",
        expected=ALLOW_VERDICT,
        section="2.2.1 with 2.2.2 — RECOLLECTED",
        why=(
            'The `*` group is a fallback used only "if no matching group exists". A specific '
            "group exists, so its rules — and only its rules — apply; its single `Allow: "
            "/jobs/` does not match `/about`, and §2.2.2 says a URI with no matching rule in "
            "the group is allowed. A matcher that unions all groups inherits `Disallow: /` and "
            "refuses the whole site."
        ),
        direction=FAIL_CLOSED_RISK,
        confidence="HIGH",
    ),
    # ---- 42. foreign_agent_group_is_not_ours -----------------------------
    Case(
        id="foreign_agent_group_is_not_ours",
        robots_txt="""User-agent: ClaudeBot
Disallow: /

User-agent: GPTBot
Disallow: /

User-agent: *
Allow: /jobs/
""",
        agent="integral-job-search/0.1",
        path="/jobs/1",
        expected=ALLOW_VERDICT,
        section="2.2.1 — RECOLLECTED",
        why=(
            "A crawler matches the group for its own product token and falls back to `*`. "
            "Neither `ClaudeBot` nor `GPTBot` is `integral-job-search`, so neither group binds "
            "this crawler; the `*` group does, and it allows. (This is the case CLAUDE.md says "
            "has been re-litigated twice — it is here as a *spec* row, not as a policy row: "
            "what an operator's ban on a training crawler means for a different product token "
            "is settled by §2.2.1 alone.)"
        ),
        direction=FAIL_CLOSED_RISK,
        confidence="HIGH",
    ),
    # ---- 43. foreign_agent_allow_does_not_rescue -------------------------
    Case(
        id="foreign_agent_allow_does_not_rescue",
        robots_txt="""User-agent: *
Disallow: /jobs/

User-agent: GPTBot
Allow: /jobs/apply
""",
        agent="integral-job-search/0.1",
        path="/jobs/apply",
        expected=DISALLOW_VERDICT,
        section="2.2.1 with 2.2.2 — RECOLLECTED",
        why=(
            "The mirror of case 42 and the fail-open half of it. Only the `*` group applies to "
            "us; the longer `Allow` lives in a group naming a different token and must not "
            "enter the longest-match comparison at all. A matcher that flattens the file into "
            "one rule list finds a 15-octet allow beating a 6-octet disallow and fetches."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="HIGH",
    ),
    # ---- 44. consecutive_ua_lines_share_the_rules ------------------------
    Case(
        id="consecutive_ua_lines_share_the_rules",
        robots_txt="""User-agent: foobot
User-agent: integral-job-search
Disallow: /admin/
""",
        agent="integral-job-search/0.1",
        path="/admin/x",
        expected=DISALLOW_VERDICT,
        section="2.2 and 2.2.1 — RECOLLECTED",
        why=(
            "The ABNF's `group = startgroupline *(startgroupline / emptyline) *(rule / "
            "emptyline)`: consecutive user-agent lines start **one** group covering the rules "
            "that follow. A matcher that keeps only the first or only the last user-agent line "
            "of a run loses one of the two tokens, and for that token the file reads as empty."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="HIGH",
    ),
    # ---- 45. two_groups_same_token_are_combined --------------------------
    Case(
        id="two_groups_same_token_are_combined",
        robots_txt="""User-agent: integral-job-search
Allow: /jobs/

User-agent: integral-job-search
Disallow: /jobs/internal/
""",
        agent="integral-job-search/0.1",
        path="/jobs/internal/7",
        expected=DISALLOW_VERDICT,
        section="2.2.1 with 2.2.2 — RECOLLECTED",
        why=(
            "\"If there is more than one group matching the user agent, the matching groups' "
            'rules MUST be combined into one group" — so this is case 2 spread across two '
            "groups: 15 octets beats 6. A matcher that stops at the first matching group sees "
            "only the `Allow`."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="HIGH",
    ),
    # ---- 46. blank_line_before_any_rule_does_not_split -------------------
    Case(
        id="blank_line_before_any_rule_does_not_split",
        robots_txt="""User-agent: integral-job-search

User-agent: *
Disallow: /
""",
        agent="integral-job-search/0.1",
        path="/jobs/1",
        expected=DISALLOW_VERDICT,
        section="2.2 — RECOLLECTED",
        why=(
            "Under the ABNF a group is `startgroupline *(startgroupline / emptyline) *(rule / "
            "emptyline)`, and an `emptyline` is admitted *between* start-group lines — so the "
            "blank line does not end a group that has not yet had a rule, and both user-agent "
            'lines head one group whose only rule is `Disallow: /`. The competing reading, "a '
            'blank line terminates a group", makes the first group rule-less and ALLOWs '
            "everything for this crawler while the `*` group is never reached (case 41's "
            "logic). **This table takes the ABNF reading**: DISALLOW."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="LOW",
        confidence_note=(
            "this is the sharpest place two *correct* readers diverge, because the "
            'widely-deployed convention ("blank line ends a group") and the published grammar '
            "do not obviously agree. The safe implementation choice is the one taken here, "
            "since the alternative opens a whole site on the strength of a blank line. Flag "
            "disagreement for discussion rather than treating it as a defect."
        ),
    ),
    # ---- 47. group_with_no_rules_allows ----------------------------------
    Case(
        id="group_with_no_rules_allows",
        robots_txt="""User-agent: *
Disallow: /admin/

User-agent: integral-job-search
""",
        agent="integral-job-search/0.1",
        path="/admin/x",
        expected=ALLOW_VERDICT,
        section="2.2.2 with 2.2.1 — RECOLLECTED",
        why=(
            "A specific group matches, so the `*` group is not consulted; the specific group is "
            'at end-of-file and contains no rules, and §2.2.2 says "If no match is found '
            "amongst the rules in a group for a matching user agent, **or there are no rules in "
            'the group**, the URI is allowed." A rule-less group is a real and deliberate way '
            "to exempt a crawler."
        ),
        direction=FAIL_CLOSED_RISK,
        confidence="MEDIUM",
        confidence_note=(
            'the "no rules in the group" clause is recalled with confidence; what is slightly '
            "less certain is that a trailing rule-less start line constitutes a group at all "
            "rather than being discarded. Both routes reach ALLOW here, by different arguments."
        ),
    ),
    # ---- 48. rules_before_first_ua_line_are_ignored ----------------------
    Case(
        id="rules_before_first_ua_line_are_ignored",
        robots_txt="""Disallow: /secret/

User-agent: *
Allow: /
""",
        agent="integral-job-search/0.1",
        path="/secret/x",
        expected=ALLOW_VERDICT,
        section="2.2 — RECOLLECTED",
        why=(
            "`robotstxt = *(group / emptyline)` and every group begins with a start-group line, "
            "so a rule preceding any `User-agent:` belongs to no group and there is no crawler "
            "it applies to. It is not a syntax error that voids the file — the rest parses "
            "normally, and here the `*` group allows."
        ),
        direction=FAIL_CLOSED_RISK,
        confidence="MEDIUM",
        confidence_note=(
            'read off the grammar rather than off a prose sentence saying "ignore them". Note '
            "this row is fail-*closed*, so a matcher that wrongly honours the orphan rule is "
            "being conservative; it is included because the same bug in a file whose orphan "
            "line is an `Allow:` is fail-open."
        ),
    ),
    # ---- 49. comment_is_stripped_from_the_value --------------------------
    Case(
        id="comment_is_stripped_from_the_value",
        robots_txt="""User-agent: *
Disallow: /admin/    # staff only, humans welcome
""",
        agent="integral-job-search/0.1",
        path="/admin/users",
        expected=DISALLOW_VERDICT,
        section="2.2.3 (with 2.2's `*WS`) — RECOLLECTED",
        why=(
            '`#` "designates an end-of-line comment", so everything from `#` is dropped and the '
            "surrounding whitespace with it, leaving the pattern `/admin/`. A matcher that "
            "takes the rest of the line literally holds a pattern containing spaces and a `#`, "
            "which no request path can match — the rule silently becomes inert, which is the "
            "worst kind of fail-open because the file *looks* like it forbids the path."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="MEDIUM",
        confidence_note=(
            "the comment rule is recalled with confidence; that trailing whitespace before the "
            "`#` is trimmed rather than kept as part of the pattern is the natural reading of "
            "the ABNF's `*WS`, not a separate quoted sentence."
        ),
    ),
    # -- The independent read of PR #410 -----------------------------------
    #
    # Cases 50 and 51 were derived by the session that reviewed the reader,
    # not by the one that wrote it — the same split as the 49 above, made a
    # second time. Both were ALLOW when they were written down, in a reader
    # whose 49-row table was already green: the table exercised §2.2.2's
    # percent-encoding requirement only through the two octets the section's
    # example table happens to print, so an encode set of `":/"` passed it
    # while every other reserved octet used as query data escaped the
    # equivalence. That is the shape CLAUDE.md's T70 paragraph describes — a
    # green gate that is necessary and not sufficient — and the reason these
    # are committed as rows rather than answered in a comment.
    #
    # ---- 50. ampersand_as_query_data_is_encoded --------------------------
    Case(
        id="ampersand_as_query_data_is_encoded",
        robots_txt="""User-agent: *
Disallow: /s?q=a%26b
""",
        agent="integral-job-search/0.1",
        path="/s?q=a&b",
        expected=DISALLOW_VERDICT,
        section="2.2.2 — RECOLLECTED",
        why=(
            "§2.2.2 states its canonicalisation over a **set**, not over an example: octets "
            '"outside the range of the US-ASCII coded character set, and those in the reserved '
            'range defined by RFC3986, MUST be percent-encoded ... prior to comparison". `&` is '
            "a sub-delim, so it is in RFC 3986's reserved range, so it is encoded before "
            "comparison exactly as the `:` and the two `/` of the example table's second row "
            "are. Here it is data inside the value of `q`, the same position `https://foo.bar` "
            "occupies inside the value of `baz` in that row. So rule and request are two "
            "spellings of one URI and the rule refuses the request. The example table is an "
            "illustration of the requirement and never its extent — a matcher that encodes "
            "only the octets the table prints allows every other reserved octet through, and "
            "the operator's rule covers nothing."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="HIGH",
    ),
    # ---- 51. equals_as_query_data_is_encoded -----------------------------
    Case(
        id="equals_as_query_data_is_encoded",
        robots_txt="""User-agent: *
Disallow: /s?q=a%3Db
""",
        agent="integral-job-search/0.1",
        path="/s?q=a=b",
        expected=DISALLOW_VERDICT,
        section="2.2.2 — RECOLLECTED",
        why=(
            "Case 50's argument with `=` in place of `&`: `=` is a sub-delim and therefore "
            "reserved, so `%3D` and `=` are one octet in two spellings and the rule refuses "
            "the request. This row is deliberately built so the *sub-reading* does not change "
            "the verdict. Read strictly — only reserved octets appearing as **data** are "
            "encoded, and the `=` separating `q` from its value is structure — the second `=` "
            "in `q=a=b` is still data, so both sides canonicalise alike. Read broadly — every "
            "reserved octet after the query delimiter is encoded — both `=` are encoded on "
            "both sides, and they still canonicalise alike. The verdict is DISALLOW under "
            "either, which is why the case can be asserted at HIGH confidence while the "
            "structural/data line itself is not settled by the RFC's text."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="HIGH",
    ),
    # Cases 52 and 53 come from the SECOND round of the independent review, and
    # they are the same finding as 50 and 51 one level up: the round-1 fix
    # derived the encode set from RFC 3986's reserved production and then held
    # `*` and `$` out of it, on the ground that §2.2.3 gives them pattern
    # meaning. That ground holds for a **pattern**. It does not reach a request
    # target, which has no pattern semantics for either octet to carry, so
    # holding them out of the target's canonicalisation left the two rows below
    # answering ALLOW. The code's own comment predicted it — "or the exemption
    # list becomes the new `\":/\"`".
    #
    # ---- 52. star_as_query_data_is_encoded -------------------------------
    Case(
        id="star_as_query_data_is_encoded",
        robots_txt="""User-agent: *
Disallow: /s?q=a%2Ab
""",
        agent="integral-job-search/0.1",
        path="/s?q=a*b",
        expected=DISALLOW_VERDICT,
        section="2.2.2 — RECOLLECTED",
        why=(
            "§2.2.2 requires octets 'in the reserved range defined by RFC3986' to be "
            "percent-encoded prior to comparison, and `*` is a sub-delim, so it is in that "
            "range. The rule writes it encoded and the request writes it literally: two "
            "spellings of one URI, so the rule refuses the request. §2.2.3 is not a "
            "counter-argument here, and the direction matters. §2.2.3 defines `*` as a "
            "special character 'in the value' of an `Allow` or `Disallow` field — it "
            "designates 0 or more instances of any character *in a pattern*. A request "
            "target is not a pattern: there is nothing in `/s?q=a*b` for a `*` to designate "
            "0 or more of. So a matcher may hold `*` out of the encode pass on the rule "
            "side, where deleting it would destroy the rule's own wildcard, and must not "
            "hold it out on the target side, where doing so leaves the rule's `%2A` with "
            "nothing to compare equal to and the operator's rule covering nothing."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="HIGH",
    ),
    # ---- 53. dollar_as_query_data_is_encoded -----------------------------
    Case(
        id="dollar_as_query_data_is_encoded",
        robots_txt="""User-agent: *
Disallow: /s?q=a%24b
""",
        agent="integral-job-search/0.1",
        path="/s?q=a$b",
        expected=DISALLOW_VERDICT,
        section="2.2.2 — RECOLLECTED",
        why=(
            "Case 52's argument with `$` in place of `*`, and it needs its own row for the "
            "reason case 51 needs one after case 50: a fix that reaches one octet of a "
            "two-octet hold-out leaves the other exactly as it was. `$` is a sub-delim and "
            "therefore in RFC 3986's reserved range, so §2.2.2 encodes it before comparison; "
            "§2.2.3 designates it 'the end of the match pattern', which is a property a "
            "**pattern** has and a request target does not. Note this row does not disturb "
            "case 22's open question — whether a literal `$` written inside a *rule* should "
            "be encoded is still unsettled, and this row takes no position on it. It asks "
            "only about the target, where there is no anchor for `$` to be."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="HIGH",
    ),
    # ---- 54. dollar_as_pattern_data_is_encoded ---------------------------
    #
    # Cases 54-58 are case 53's **inverse twin**, and they are here because that
    # row said in as many words that it was not asking the other half: "whether
    # a literal `$` written inside a *rule* should be encoded is still
    # unsettled, and this row takes no position on it. It asks only about the
    # target." Five shapes then reproduced the fail-open on the side it left
    # alone, which is the third time in this file that a fix reaching one side
    # of a two-sided equivalence left the other exactly as it was (cases 50/51,
    # then 52/53). The general rule the three of them share: §2.2.2's
    # canonicalisation is a property of the **comparison**, so it runs over both
    # operands and over both kinds of rule; §2.2.3's metacharacters are a
    # property of a **pattern**, and — case 54's own subject — of the position
    # §2.2.3 names and no other.
    Case(
        id="dollar_as_pattern_data_is_encoded",
        robots_txt="""User-agent: *
Disallow: /s?q=a$b
""",
        agent="integral-job-search/0.1",
        path="/s?q=a%24b",
        expected=DISALLOW_VERDICT,
        section="2.2.2 — RECOLLECTED",
        why=(
            "`$` is a sub-delim, so it is in RFC 3986's reserved range, and §2.2.2 requires "
            "octets in that range to be percent-encoded 'prior to comparison' — in 'the URI "
            "**and robots.txt paths**', so the rule's `$` and the target's `%24` are both "
            "canonicalised to `%24` and compare equal. The only thing that could exempt this "
            "`$` is §2.2.3's 'designates the end of the match pattern', and this `$` is not at "
            "the end of the pattern: there is a `b` after it. §2.2.3's sentence describes one "
            "position, and the matcher has already ruled on the others — a non-trailing `$` is "
            "an ordinary octet held in the literal run around it, which is what makes "
            "`Disallow: /a$b` cover the literal path `/a$b` in case 22. An ordinary octet in "
            "the reserved range is exactly what §2.2.2 encodes. A matcher that exempts every "
            "`$` in a pattern leaves the rule's `$` literal while the target's `%24` stays "
            "encoded, so the two can never compare equal and a rule the operator wrote in "
            "plain sight covers nothing."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="HIGH",
    ),
    # ---- 55. dollar_in_both_roles_in_one_pattern -------------------------
    Case(
        id="dollar_in_both_roles_in_one_pattern",
        robots_txt="""User-agent: *
Disallow: /s?a=$b$
""",
        agent="integral-job-search/0.1",
        path="/s?a=%24b",
        expected=DISALLOW_VERDICT,
        section="2.2.2 — RECOLLECTED",
        why=(
            "One pattern carrying `$` in **both** of its roles, which is the row that stops "
            "either role's rule being stated as a fact about the octet. The first `$` has a "
            "`b` after it, so §2.2.3's 'the end of the match pattern' does not describe it: it "
            "is data, in RFC 3986's reserved range, and §2.2.2 encodes it to `%24` on both "
            "sides. The second `$` is final, so §2.2.3 does describe it: it is the anchor, it "
            "is consumed by the matcher rather than compared, and encoding it would delete the "
            "anchoring the operator asked for. Canonicalised, the rule is `/s?a%3D%24b` "
            "anchored, and the target canonicalises to exactly that — DISALLOW. A matcher "
            "exempting every `$` cannot reach the target's `%24`; a matcher encoding every `$` "
            "destroys the anchor. Only reading the position gets both, and this is the row "
            "where a matcher must get both at once rather than one per file. The earlier "
            "draft of this row paired `$` with `&` instead of with a second `$`; that made it "
            "fail for `integral.robots` on the `&`, which case 51 already counts, so the row "
            "would have re-counted a known defect under a new id instead of measuring this one."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="HIGH",
    ),
    # ---- 56. dollar_as_pattern_data_opening_a_value ----------------------
    Case(
        id="dollar_as_pattern_data_opening_a_value",
        robots_txt="""User-agent: *
Disallow: /s?price=$5
""",
        agent="integral-job-search/0.1",
        path="/s?price=%245",
        expected=DISALLOW_VERDICT,
        section="2.2.2 — RECOLLECTED",
        why=(
            "The realistic spelling of case 54: a currency sign opening a query value, which "
            "is how a literal `$` actually reaches a robots.txt. Same derivation — `$` is a "
            "sub-delim in RFC 3986's reserved range, it is not in the pattern's final "
            "position, so §2.2.2 encodes it and §2.2.3 exempts nothing. The row is here "
            "because a hold-out keyed on 'looks like an anchor' would have to decide what a "
            "`$` immediately after `=` is, and the answer is not positional guesswork: it is "
            "the one position §2.2.3 names, and this is not it."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="HIGH",
    ),
    # ---- 57. dollar_as_pattern_data_reached_through_a_wildcard -----------
    Case(
        id="dollar_as_pattern_data_reached_through_a_wildcard",
        robots_txt="""User-agent: *
Disallow: /*?q=a$b
""",
        agent="integral-job-search/0.1",
        path="/x?q=a%24b",
        expected=DISALLOW_VERDICT,
        section="2.2.2 — RECOLLECTED",
        why=(
            "Case 54 with the path reached through §2.2.3's `*`, so the rule carries both a "
            "metacharacter and a literal `$` and a matcher must tell them apart within one "
            "pattern. §2.2.3 gives `*` '0 or more instances of any character' with no position "
            "attached, so it is held out wherever it stands; it gives `$` 'the end of the "
            "match pattern', which is a claim about one position, and this `$` is not in it. "
            "Encoding both, or exempting both, both fail: the first deletes the wildcard and "
            "the rule stops matching `/x`, the second leaves the `$` unable to meet `%24`."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="HIGH",
    ),
    # ---- 58. dollar_as_pattern_data_behind_a_path_wildcard ---------------
    Case(
        id="dollar_as_pattern_data_behind_a_path_wildcard",
        robots_txt="""User-agent: *
Disallow: /*a$b
""",
        agent="integral-job-search/0.1",
        path="/x?q=a%24b",
        expected=DISALLOW_VERDICT,
        section="2.2.2 — RECOLLECTED",
        why=(
            "The same fault one function further on, and the row that stops the fix being a "
            "pattern-side-only patch. This rule has no literal `?`, so 'which octets are in "
            "the query' is undecidable from the pattern and its `$` is canonicalised as a "
            "path octet — left literal, correctly, since §2.2.2's example table encodes "
            "reserved octets that appear as data **inside a query**. The equivalence must "
            "therefore be met from the target side, by offering the target's query with its "
            "reserved-as-data escapes resolved — which is what case 50 established for `:` "
            "and `/` under a wildcard. A matcher that resolves every reserved octet there "
            "*except* `$` and `*` refuses this row: the target's `%24` stays encoded and the "
            "rule's `$` stays literal. Nothing justifies that exception. The decode pass reads "
            "a **request target**, and a target has no pattern for `*` to designate 0 or more "
            "of and no end of a pattern for `$` to designate — case 52 and case 53's whole "
            "argument, applied where it had not been applied."
        ),
        direction=FAIL_OPEN_RISK,
        confidence="HIGH",
    ),
    # ---- 59. a_data_dollar_does_not_defeat_the_anchor_beside_it ----------
    Case(
        id="a_data_dollar_does_not_defeat_the_anchor_beside_it",
        robots_txt="""User-agent: *
Disallow: /s?a=$b$
""",
        agent="integral-job-search/0.1",
        path="/s?a=%24bc",
        expected=ALLOW_VERDICT,
        section="2.2.3 — RECOLLECTED",
        why=(
            "Case 55's mirror, on the same pattern, and the reason the pair is here rather "
            "than case 55 alone: 55 asks that the rule still REFUSE `/s?a=%24b`, and a "
            "matcher can pass that by dropping §2.2.3's anchoring altogether and matching "
            "the pattern as a plain prefix. This row is the path that separates the two. "
            "§2.2.3's final `$` 'designates the end of the match pattern', so the rule "
            "covers `/s?a=%24b` and nothing longer; `/s?a=%24bc` is longer, and a path no "
            "rule matches is allowed. The first `$` is data — §2.2.2 encodes it to `%24` on "
            "both sides, which is what lets the rule reach this target's spelling at all — "
            "and encoding it must not consume the anchor after it, nor may anchoring on the "
            "wrong `$` make the rule end at the first one. Fail-**closed** on its own, which "
            "is exactly why it is pinned: no sweep for fail-opens would find a matcher that "
            "refuses this path, and 55 and 59 together admit only the reading that tells the "
            "two `$` apart by position."
        ),
        direction=FAIL_CLOSED_RISK,
        confidence="HIGH",
    ),
)
