# RFC 9309 adversarial case table

An independent, **spec-derived** case table for a robots.txt matcher. It exists to break
the circularity CLAUDE.md names: a gate written by the implementer, from the
implementer's reading of the spec, is green when the reading is wrong.

## Provenance — read this before trusting any row

- **No implementation was read.** Nothing under `src/` or `tests/` was opened while this
  table was written. The `expected` column is not a description of what any code does.
- **No verdict was decided by running code.** Every `expected` value below is read off
  RFC 9309's text. Deciding correctness by execution is exactly the circularity this
  table exists to break.
- **Citations are `RECOLLECTED`.** Network egress is blocked here (rfc-editor.org answers
  403), so section numbers and quoted text are recalled, not fetched. The repo's
  convention is to mark that rather than pretend to a fetch. Where recall does not settle
  a case, `confidence` says `LOW` and the entry says what is unsettled instead of
  inventing a rule.
- **`why` paraphrases unless it is in quotes.** Quoted fragments are recalled verbatim as
  closely as memory allows; treat exact wording as approximate, the *rule* as asserted.

## Conventions used throughout

- **Default agent.** `integral-job-search/0.1`. Under §2.2.1 a product token may contain
  only `a-z`, `A-Z`, `_` and `-`, so the token this crawler matches on is
  `integral-job-search`; `/0.1` is a version suffix, not part of the token. Cases about
  token matching say so explicitly.
- **"Path" means path *and* query.** §2.2.2's own example table adjudicates
  `/foo/bar?baz=quz`, so the query string is part of the string a rule is matched
  against. Fragments are never sent to a server and are out of scope.
- **Specificity reading.** §2.2.2 says "The most specific match is the match that has the
  most octets." Two readings survive that sentence:
  - **(P) pattern-length** — count the octets of the rule's path pattern as written,
    with `*` and `$` counting as the one octet each occupies.
  - **(M) matched-length** — count the octets of the request path the rule actually
    consumed, so a `*` expansion inflates the score.
  **This table takes (P)**, because the RFC's wildcard-free examples cannot distinguish
  the two and (P) is the reading that makes a rule's specificity a property of the
  robots.txt file rather than of the request. Cases 23–25 are built so the two readings
  are *tested*: 23 makes them agree, 24 and 25 make them diverge and are marked `LOW`.
- **`direction`** is about the failure a weak matcher makes on this row:
  `FAIL_OPEN_RISK` — the RFC says DISALLOW and a weak matcher would ALLOW (a fetch the
  check exists to refuse goes out); `FAIL_CLOSED_RISK` — the RFC says ALLOW and a weak
  matcher would DISALLOW (one skipped fetch); `NEUTRAL` — baseline.

## Index

| # | id | expected | direction | conf | § |
|---|---|---|---|---|---|
| 1 | `allow_root_then_longer_disallow` | DISALLOW | FAIL_OPEN_RISK | HIGH | 2.2.2 |
| 2 | `allow_subtree_then_longer_disallow` | DISALLOW | FAIL_OPEN_RISK | HIGH | 2.2.2 |
| 3 | `disallow_then_longer_allow` | ALLOW | FAIL_CLOSED_RISK | HIGH | 2.2.2 |
| 4 | `tie_disallow_first_allow_wins` | ALLOW | FAIL_CLOSED_RISK | HIGH | 2.2.2 |
| 5 | `tie_allow_first_allow_wins` | ALLOW | FAIL_CLOSED_RISK | HIGH | 2.2.2 |
| 6 | `disallow_all_with_longer_allow` | ALLOW | FAIL_CLOSED_RISK | HIGH | 2.2.2 |
| 7 | `disallow_all_allow_does_not_reach` | DISALLOW | FAIL_OPEN_RISK | HIGH | 2.2.2 |
| 8 | `empty_disallow_value_allows_all` | ALLOW | FAIL_CLOSED_RISK | MEDIUM | 2.2 / 2.2.2 |
| 9 | `three_rules_middle_length_loses` | DISALLOW | FAIL_OPEN_RISK | HIGH | 2.2.2 |
| 10 | `prefix_match_crosses_segment_boundary` | DISALLOW | FAIL_OPEN_RISK | HIGH | 2.2.2 |
| 11 | `match_must_start_at_first_octet` | ALLOW | FAIL_CLOSED_RISK | HIGH | 2.2.2 |
| 12 | `leading_wildcard_reaches_interior` | DISALLOW | FAIL_OPEN_RISK | HIGH | 2.2.3 |
| 13 | `trailing_slash_is_significant` | ALLOW | FAIL_CLOSED_RISK | HIGH | 2.2.2 |
| 14 | `star_matches_empty_sequence` | DISALLOW | FAIL_OPEN_RISK | HIGH | 2.2.3 |
| 15 | `double_star_matches_empty` | DISALLOW | FAIL_OPEN_RISK | MEDIUM | 2.2.3 |
| 16 | `trailing_star_is_not_a_boundary` | DISALLOW | FAIL_OPEN_RISK | HIGH | 2.2.3 |
| 17 | `dollar_anchors_exact_path` | DISALLOW | FAIL_OPEN_RISK | HIGH | 2.2.3 |
| 18 | `dollar_rejects_longer_path` | ALLOW | NEUTRAL | HIGH | 2.2.3 |
| 19 | `dollar_allow_homepage_only` | ALLOW | FAIL_CLOSED_RISK | HIGH | 2.2.2 / 2.2.3 |
| 20 | `star_dot_gif_dollar` | DISALLOW | FAIL_OPEN_RISK | HIGH | 2.2.3 |
| 21 | `gif_dollar_defeated_by_query` | ALLOW | FAIL_CLOSED_RISK | MEDIUM | 2.2.2 / 2.2.3 |
| 22 | `dollar_in_middle_of_pattern` | DISALLOW | FAIL_OPEN_RISK | LOW | 2.2.3 |
| 23 | `wildcard_specificity_readings_agree` | DISALLOW | FAIL_OPEN_RISK | MEDIUM | 2.2.2 |
| 24 | `wildcard_specificity_readings_diverge` | DISALLOW | FAIL_OPEN_RISK | LOW | 2.2.2 |
| 25 | `dollar_specificity_readings_diverge` | DISALLOW | FAIL_OPEN_RISK | LOW | 2.2.2 |
| 26 | `pct_unreserved_encoded_in_rule` | DISALLOW | FAIL_OPEN_RISK | HIGH | 2.2.2 |
| 27 | `pct_unreserved_encoded_in_path_lowercase_hex` | DISALLOW | FAIL_OPEN_RISK | MEDIUM | 2.2.2 |
| 28 | `pct_triplets_decode_to_baz` | DISALLOW | FAIL_OPEN_RISK | HIGH | 2.2.2 |
| 29 | `pct_encoded_slash_is_not_a_separator` | ALLOW | FAIL_CLOSED_RISK | HIGH | 2.2.2 |
| 30 | `pct_encoded_slash_in_rule_matches` | DISALLOW | FAIL_OPEN_RISK | MEDIUM | 2.2.2 |
| 31 | `reserved_octets_stay_encoded_in_query` | DISALLOW | FAIL_OPEN_RISK | HIGH | 2.2.2 |
| 32 | `non_ascii_utf8_is_percent_encoded` | DISALLOW | FAIL_OPEN_RISK | HIGH | 2.2.2 |
| 33 | `bare_percent_is_not_an_escape` | DISALLOW | FAIL_OPEN_RISK | MEDIUM | 2.2.2 |
| 34 | `plus_is_not_a_space` | ALLOW | FAIL_CLOSED_RISK | LOW | 2.2.2 |
| 35 | `query_is_part_of_the_matched_string` | DISALLOW | FAIL_OPEN_RISK | HIGH | 2.2.2 |
| 36 | `wildcard_question_mark_bans_queries` | DISALLOW | FAIL_OPEN_RISK | MEDIUM | 2.2.3 |
| 37 | `path_matching_is_case_sensitive` | ALLOW | FAIL_CLOSED_RISK | MEDIUM | 2.2.2 |
| 38 | `product_token_matching_is_case_insensitive` | DISALLOW | FAIL_OPEN_RISK | HIGH | 2.2.1 |
| 39 | `product_token_has_no_prefix_rule` | ALLOW | FAIL_CLOSED_RISK | MEDIUM | 2.2.1 |
| 40 | `version_suffix_is_not_part_of_the_token` | DISALLOW | FAIL_OPEN_RISK | MEDIUM | 2.2.1 |
| 41 | `star_group_ignored_when_specific_group_matches` | ALLOW | FAIL_CLOSED_RISK | HIGH | 2.2.1 |
| 42 | `foreign_agent_group_is_not_ours` | ALLOW | FAIL_CLOSED_RISK | HIGH | 2.2.1 |
| 43 | `foreign_agent_allow_does_not_rescue` | DISALLOW | FAIL_OPEN_RISK | HIGH | 2.2.1 |
| 44 | `consecutive_ua_lines_share_the_rules` | DISALLOW | FAIL_OPEN_RISK | HIGH | 2.2 / 2.2.1 |
| 45 | `two_groups_same_token_are_combined` | DISALLOW | FAIL_OPEN_RISK | HIGH | 2.2.1 |
| 46 | `blank_line_before_any_rule_does_not_split` | DISALLOW | FAIL_OPEN_RISK | LOW | 2.2 |
| 47 | `group_with_no_rules_allows` | ALLOW | FAIL_CLOSED_RISK | MEDIUM | 2.2.2 |
| 48 | `rules_before_first_ua_line_are_ignored` | ALLOW | FAIL_CLOSED_RISK | MEDIUM | 2.2 |
| 49 | `comment_is_stripped_from_the_value` | DISALLOW | FAIL_OPEN_RISK | MEDIUM | 2.2.3 |
| 50 | `ampersand_as_query_data_is_encoded` | DISALLOW | FAIL_OPEN_RISK | HIGH | 2.2.2 |
| 51 | `equals_as_query_data_is_encoded` | DISALLOW | FAIL_OPEN_RISK | HIGH | 2.2.2 |
| 52 | `star_as_query_data_is_encoded` | DISALLOW | FAIL_OPEN_RISK | HIGH | 2.2.2 |
| 53 | `dollar_as_query_data_is_encoded` | DISALLOW | FAIL_OPEN_RISK | HIGH | 2.2.2 |

Fifty-three rows: 35 `FAIL_OPEN_RISK`, 17 `FAIL_CLOSED_RISK`, 1 `NEUTRAL` — weighted toward
fail-open, since a fail-closed bug costs one skipped fetch and a fail-open bug means the
check said yes to something it exists to refuse. Forty-nine of them were derived before
any implementation existed; **50–53 were derived later, by the session that reviewed
the reader those 49 were written for** — 50 and 51 in its first round, 52 and 53 in its
second, against the fix the first round produced — and section H says what the first
forty-nine missed. That is six over the 30–45 the brief asked for; four of the six are the paired
mirrors (5 against 4, 7 against 6, 18 against 17, 30 against 29), each of which exists
because its partner can be passed by accident — dropping either half of a pair would leave
a matcher able to score the row without implementing the rule.

---

## A. Precedence and longest match (§2.2.2)

### 1. `allow_root_then_longer_disallow`

```
User-agent: *
Allow: /
Disallow: /admin/
```

- **agent:** `integral-job-search/0.1`
- **path:** `/admin/users`
- **expected:** DISALLOW
- **section:** 2.2.2 — RECOLLECTED
- **why:** "The most specific match found MUST be used. The most specific match is the
  match that has the most octets." `Disallow: /admin/` matches 7 octets, `Allow: /`
  matches 1. File order is not part of the rule.
- **direction:** FAIL_OPEN_RISK
- **confidence:** HIGH

### 2. `allow_subtree_then_longer_disallow`

```
User-agent: *
Allow: /jobs/
Disallow: /jobs/internal/
```

- **agent:** `integral-job-search/0.1`
- **path:** `/jobs/internal/7`
- **expected:** DISALLOW
- **section:** 2.2.2 — RECOLLECTED
- **why:** 15 octets beats 6. A first-match-in-file-order matcher returns the `Allow` and
  fetches a page the operator fenced off.
- **direction:** FAIL_OPEN_RISK
- **confidence:** HIGH

### 3. `disallow_then_longer_allow`

```
User-agent: *
Disallow: /jobs/
Allow: /jobs/public/
```

- **agent:** `integral-job-search/0.1`
- **path:** `/jobs/public/1`
- **expected:** ALLOW
- **section:** 2.2.2 — RECOLLECTED
- **why:** `Allow: /jobs/public/` is 13 octets against the `Disallow`'s 6, so the allow is
  the most specific match. This is the mirror of case 1 and catches a matcher that
  "resolves conflicts by preferring Disallow".
- **direction:** FAIL_CLOSED_RISK
- **confidence:** HIGH

### 4. `tie_disallow_first_allow_wins`

```
User-agent: *
Disallow: /a/b/
Allow: /a/b/
```

- **agent:** `integral-job-search/0.1`
- **path:** `/a/b/c.html`
- **expected:** ALLOW
- **section:** 2.2.2 — RECOLLECTED
- **why:** "If an allow rule and a disallow rule are equivalent, then the allow rule
  SHOULD be used." Both patterns are 5 octets.
- **direction:** FAIL_CLOSED_RISK
- **confidence:** HIGH

### 5. `tie_allow_first_allow_wins`

```
User-agent: *
Allow: /a/b/
Disallow: /a/b/
```

- **agent:** `integral-job-search/0.1`
- **path:** `/a/b/c.html`
- **expected:** ALLOW
- **section:** 2.2.2 — RECOLLECTED
- **why:** Same tie, opposite file order — the verdict must not move, because the tiebreak
  is "allow wins", not "last wins" or "first wins". Cases 4 and 5 together pin that: a
  matcher that passes one by accident of ordering fails the other.
- **direction:** FAIL_CLOSED_RISK
- **confidence:** HIGH

### 6. `disallow_all_with_longer_allow`

```
User-agent: *
Disallow: /
Allow: /jobs/
```

- **agent:** `integral-job-search/0.1`
- **path:** `/jobs/1234`
- **expected:** ALLOW
- **section:** 2.2.2 — RECOLLECTED
- **why:** 6 octets beats 1. The "closed by default, one door open" idiom; a matcher that
  short-circuits on `Disallow: /` reads it as a whole-site ban.
- **direction:** FAIL_CLOSED_RISK
- **confidence:** HIGH

### 7. `disallow_all_allow_does_not_reach`

```
User-agent: *
Disallow: /
Allow: /jobs/
```

- **agent:** `integral-job-search/0.1`
- **path:** `/about`
- **expected:** DISALLOW
- **section:** 2.2.2 — RECOLLECTED
- **why:** Same file as case 6, a path the `Allow` does not match at all, so the only
  matching rule is `Disallow: /`. Paired with 6 it catches a matcher that "opens the site"
  once any `Allow` is present.
- **direction:** FAIL_OPEN_RISK
- **confidence:** HIGH

### 8. `empty_disallow_value_allows_all`

```
User-agent: *
Disallow:
```

- **agent:** `integral-job-search/0.1`
- **path:** `/anything/at/all`
- **expected:** ALLOW
- **section:** 2.2 (ABNF `empty-pattern = *WS`) and 2.2.2 — RECOLLECTED
- **why:** The ABNF admits `rule = *WS ("allow" / "disallow") *WS ":" *WS (path-pattern /
  empty-pattern) EOL`, so an empty value is a well-formed line and not a parse error. It
  states no path, so no path matches it, and §2.2.2's fallback applies: "If no match is
  found amongst the rules in a group for a matching user agent, or there are no rules in
  the group, the URI is allowed." This is also the historical meaning of a bare
  `Disallow:` — the 1994 convention's way of spelling "everything is open".
- **direction:** FAIL_CLOSED_RISK
- **confidence:** MEDIUM — the RFC admits the syntax but (as recalled) does not spell out
  the semantics of the empty pattern in one sentence. The competing reading, "an empty
  pattern matches every path with 0 octets", would make this DISALLOW and would invert
  every legacy robots.txt on the web; it is rejected here for that reason, not on a quoted
  line.

### 9. `three_rules_middle_length_loses`

```
User-agent: *
Allow: /jobs/internal/preview/
Disallow: /jobs/internal/
Allow: /jobs/
```

- **agent:** `integral-job-search/0.1`
- **path:** `/jobs/internal/x`
- **expected:** DISALLOW
- **section:** 2.2.2 — RECOLLECTED
- **why:** Only two of the three rules match this path: `Disallow: /jobs/internal/` (15)
  and `Allow: /jobs/` (6). The longest *matching* rule wins; the longer `Allow` at the top
  of the file matches nothing here and must not be counted. This separates "longest rule
  in the file" from "longest rule that matches".
- **direction:** FAIL_OPEN_RISK
- **confidence:** HIGH

---

## B. Anchoring (§2.2.2)

### 10. `prefix_match_crosses_segment_boundary`

```
User-agent: *
Disallow: /admin
```

- **agent:** `integral-job-search/0.1`
- **path:** `/administrator/login`
- **expected:** DISALLOW
- **section:** 2.2.2 — RECOLLECTED
- **why:** A rule is a *prefix* pattern — "The matching MUST start with the first octet of
  the path" and nothing terminates it. There is no implicit path-segment boundary, so
  `/admin` covers `/administrator`.
- **direction:** FAIL_OPEN_RISK
- **confidence:** HIGH

### 11. `match_must_start_at_first_octet`

```
User-agent: *
Disallow: /secret
```

- **agent:** `integral-job-search/0.1`
- **path:** `/en/secret/page`
- **expected:** ALLOW
- **section:** 2.2.2 — RECOLLECTED
- **why:** "The matching MUST start with the first octet of the path." `/secret` is present
  in the request path but not at its start, so the rule does not match and no rule does.
  A substring matcher wrongly refuses.
- **direction:** FAIL_CLOSED_RISK
- **confidence:** HIGH

### 12. `leading_wildcard_reaches_interior`

```
User-agent: *
Disallow: /*secret
```

- **agent:** `integral-job-search/0.1`
- **path:** `/en/secret/page`
- **expected:** DISALLOW
- **section:** 2.2.3 — RECOLLECTED
- **why:** `*` "designates 0 or more instances of any character", so `/*secret` anchors at
  the first octet and then skips `en/`. This is how an operator writes the interior match
  case 11 denies to a bare pattern — a matcher treating `*` as a literal asterisk finds no
  match and fetches.
- **direction:** FAIL_OPEN_RISK
- **confidence:** HIGH

### 13. `trailing_slash_is_significant`

```
User-agent: *
Disallow: /jobs/
```

- **agent:** `integral-job-search/0.1`
- **path:** `/jobs`
- **expected:** ALLOW
- **section:** 2.2.2 — RECOLLECTED
- **why:** Matching is octet-by-octet from the first octet; the pattern's 6th octet is `/`
  and the request path has no 6th octet. The rule does not match. A matcher that
  "normalises" a trailing slash away refuses a page the operator left open — and, worse,
  the same normalisation in the other direction would open `/jobs/x` under `Disallow:
  /jobs` cases.
- **direction:** FAIL_CLOSED_RISK
- **confidence:** HIGH

---

## C. `*` and `$` (§2.2.3)

### 14. `star_matches_empty_sequence`

```
User-agent: *
Disallow: /jobs*/apply
```

- **agent:** `integral-job-search/0.1`
- **path:** `/jobs/apply`
- **expected:** DISALLOW
- **section:** 2.2.3 — RECOLLECTED
- **why:** `*` designates **0** or more instances of any character, so it matches the empty
  sequence between `/jobs` and `/apply`. A matcher requiring at least one character allows
  the exact page the rule names.
- **direction:** FAIL_OPEN_RISK
- **confidence:** HIGH

### 15. `double_star_matches_empty`

```
User-agent: *
Disallow: /a**b
```

- **agent:** `integral-job-search/0.1`
- **path:** `/ab`
- **expected:** DISALLOW
- **section:** 2.2.3 — RECOLLECTED
- **why:** Two wildcards, each matching zero characters. `**` is not a distinct operator in
  RFC 9309 — it is just `*` twice, and it collapses.
- **direction:** FAIL_OPEN_RISK
- **confidence:** MEDIUM — the collapse follows from the definition of `*` rather than from
  any sentence about repeated wildcards. A naive backtracker can also blow up here rather
  than answer, which is its own fail-open if the error path defaults to "allow".

### 16. `trailing_star_is_not_a_boundary`

```
User-agent: *
Disallow: /admin*
```

- **agent:** `integral-job-search/0.1`
- **path:** `/admin`
- **expected:** DISALLOW
- **section:** 2.2.3 — RECOLLECTED
- **why:** The trailing `*` matches the empty sequence, so the pattern is satisfied by the
  bare `/admin` with nothing after it. A matcher that requires the wildcard to consume
  something allows the directory root while refusing everything under it.
- **direction:** FAIL_OPEN_RISK
- **confidence:** HIGH

### 17. `dollar_anchors_exact_path`

```
User-agent: *
Disallow: /page$
```

- **agent:** `integral-job-search/0.1`
- **path:** `/page`
- **expected:** DISALLOW
- **section:** 2.2.3 — RECOLLECTED
- **why:** `$` "designates the end of the match pattern": the pattern matches `/page` and
  requires the path to end there, which it does. A matcher treating `$` as a literal octet
  compares `/page$` against `/page`, finds no match, and fetches.
- **direction:** FAIL_OPEN_RISK
- **confidence:** HIGH

### 18. `dollar_rejects_longer_path`

```
User-agent: *
Disallow: /page$
```

- **agent:** `integral-job-search/0.1`
- **path:** `/page/1`
- **expected:** ALLOW
- **section:** 2.2.3 — RECOLLECTED
- **why:** The anchor requires the path to end at `/page`; `/page/1` continues, so nothing
  matches. Paired with 17 this is the pin: a literal-`$` matcher gets 18 right by accident
  while getting 17 wrong, so 18 alone proves nothing.
- **direction:** NEUTRAL
- **confidence:** HIGH

### 19. `dollar_allow_homepage_only`

```
User-agent: *
Disallow: /
Allow: /$
```

- **agent:** `integral-job-search/0.1`
- **path:** `/`
- **expected:** ALLOW
- **section:** 2.2.2 and 2.2.3 — RECOLLECTED
- **why:** The standard "only the homepage" idiom. Both rules match `/`; under reading (P)
  `Allow: /$` is 2 octets against 1 and wins outright, and under reading (M) both match one
  octet and the allow wins the tie by §2.2.2's "if an allow rule and a disallow rule are
  equivalent, then the allow rule SHOULD be used". Both readings agree, which is why this
  row is not in section D.
- **direction:** FAIL_CLOSED_RISK
- **confidence:** HIGH

### 20. `star_dot_gif_dollar`

```
User-agent: *
Disallow: /*.gif$
```

- **agent:** `integral-job-search/0.1`
- **path:** `/assets/img/photo.gif`
- **expected:** DISALLOW
- **section:** 2.2.3 — RECOLLECTED
- **why:** The RFC's own worked example of the two special characters together: `*` spans
  `assets/img/photo`, `.gif` matches literally, `$` requires the path to end there.
- **direction:** FAIL_OPEN_RISK
- **confidence:** HIGH

### 21. `gif_dollar_defeated_by_query`

```
User-agent: *
Disallow: /*.gif$
```

- **agent:** `integral-job-search/0.1`
- **path:** `/assets/photo.gif?v=2`
- **expected:** ALLOW
- **section:** 2.2.2 and 2.2.3 — RECOLLECTED
- **why:** §2.2.2's example table adjudicates `/foo/bar?baz=quz`, i.e. the string matched
  against includes the query, so this path ends at `2` and not at `.gif`; the `$` anchor
  therefore fails. The two rules that produce this — "query is included" and "`$` means
  end of the *whole* matched string" — are the same two that produce case 35's DISALLOW,
  so a matcher cannot satisfy both by leaning one way.
- **direction:** FAIL_CLOSED_RISK
- **confidence:** MEDIUM — rests on the query being part of the matched string, which the
  example table shows rather than states in prose.

### 22. `dollar_in_middle_of_pattern`

```
User-agent: *
Disallow: /a$b
```

- **agent:** `integral-job-search/0.1`
- **path:** `/a$b`
- **expected:** DISALLOW
- **section:** 2.2.3 — RECOLLECTED
- **why:** §2.2.3 defines `$` as "the end of the match pattern", which describes a
  character at the end of a pattern and says nothing about one in the middle. Two readings
  survive: (a) `$` is special only in final position, so here it is an ordinary octet and
  the pattern matches the literal path `/a$b`; (b) `$` always anchors, so the pattern is
  `/a` anchored, nothing after it is reachable, and the rule matches only `/a` — making
  this ALLOW. **This table takes (a)**, because it is the reading under which the operator
  gets what they wrote, and because it is fail-closed relative to (b).
- **direction:** FAIL_OPEN_RISK
- **confidence:** LOW — the RFC does not settle mid-pattern `$`. There is a second
  wrinkle: `$` is a sub-delim under RFC 3986, so a request URI carrying it may arrive as
  `/a%24b`, in which case whether a rule's literal `$` should be encoded before comparison
  is also unsettled. Treat a matcher disagreeing here as a finding to discuss, not a defect
  to fix blind.

---

## D. Where the specificity metric is ambiguous (§2.2.2)

Every row here exists to make the (P)/(M) choice from the conventions section *visible*.

### 23. `wildcard_specificity_readings_agree`

```
User-agent: *
Allow: /a/b/
Disallow: /a/*/secret
```

- **agent:** `integral-job-search/0.1`
- **path:** `/a/b/secret`
- **expected:** DISALLOW
- **section:** 2.2.2 — RECOLLECTED
- **why:** The disallow scores 11 under (P) (`/a/*/secret` as written) and 11 under (M)
  (the whole path consumed); the allow scores 5 either way. Both readings disallow, so a
  matcher failing this one is not failing on the ambiguity — it is failing on wildcards or
  on longest-match.
- **direction:** FAIL_OPEN_RISK
- **confidence:** MEDIUM

### 24. `wildcard_specificity_readings_diverge`

```
User-agent: *
Allow: /a*
Disallow: /abc
```

- **agent:** `integral-job-search/0.1`
- **path:** `/abcd`
- **expected:** DISALLOW
- **section:** 2.2.2 — RECOLLECTED
- **why:** Under **(P)** the allow pattern `/a*` is 3 octets and the disallow `/abc` is 4,
  so the disallow is more specific. Under **(M)** the allow's `*` consumes `bcd` and the
  allow's match is 5 octets against the disallow's 3, so the allow wins and the verdict
  flips to ALLOW. This table takes (P), so: DISALLOW.
- **direction:** FAIL_OPEN_RISK
- **confidence:** LOW — the divergence is the point. A matcher answering ALLOW here has
  taken reading (M) and is not necessarily wrong; report it as a reading disagreement and
  make the repo pick one deliberately, in writing.

### 25. `dollar_specificity_readings_diverge`

```
User-agent: *
Disallow: /a/b$
Allow: /a/b
```

- **agent:** `integral-job-search/0.1`
- **path:** `/a/b`
- **expected:** DISALLOW
- **section:** 2.2.2 — RECOLLECTED
- **why:** Under **(P)** `Disallow: /a/b$` counts the `$` and scores 5 against the allow's
  4, so the disallow wins. Under **(M)** both consume exactly `/a/b` (4 octets), the rules
  are equivalent, and the allow wins the §2.2.2 tiebreak — ALLOW. This table takes (P):
  DISALLOW. Note this is the same shape as case 19 with the roles swapped, and there the
  two readings happened to agree; here they do not.
- **direction:** FAIL_OPEN_RISK
- **confidence:** LOW — whether an anchor character contributes to "the match that has the
  most octets" is exactly what the RFC leaves open.

---

## E. Percent-encoding equivalence (§2.2.2)

The governing text, recalled: octets in the URI and in robots.txt paths that are outside
the US-ASCII range, or in RFC 3986's reserved range, MUST be percent-encoded before
comparison — and the §2.2.2 example table shows the converse in its last row,
`/foo/bar/%62%61%7A` being compared as `/foo/bar/baz`, i.e. percent-encoded **unreserved**
octets are decoded before comparison. Rule and path are compared after that
canonicalisation on both sides.

### 26. `pct_unreserved_encoded_in_rule`

```
User-agent: *
Disallow: /%7Euser/
```

- **agent:** `integral-job-search/0.1`
- **path:** `/~user/cv.html`
- **expected:** DISALLOW
- **section:** 2.2.2 — RECOLLECTED
- **why:** `~` is unreserved in RFC 3986, so `%7E` decodes to `~` before comparison and the
  rule is `/~user/`. A byte-comparing matcher sees `%7E` against `~`, finds no match, and
  fetches.
- **direction:** FAIL_OPEN_RISK
- **confidence:** HIGH

### 27. `pct_unreserved_encoded_in_path_lowercase_hex`

```
User-agent: *
Disallow: /~user/
```

- **agent:** `integral-job-search/0.1`
- **path:** `/%7euser/cv.html`
- **expected:** DISALLOW
- **section:** 2.2.2 — RECOLLECTED
- **why:** The same equivalence in the other direction, plus RFC 3986's rule that the hex
  digits of a percent-encoding are case-insensitive: `%7e` and `%7E` both decode to `~`.
  Case 26 and this one together stop a matcher that canonicalises only one side.
- **direction:** FAIL_OPEN_RISK
- **confidence:** MEDIUM — the direction is symmetric by construction; the hex-case half is
  RFC 3986's, cited through §2.2.2's reference to it.

### 28. `pct_triplets_decode_to_baz`

```
User-agent: *
Disallow: /foo/bar/baz
```

- **agent:** `integral-job-search/0.1`
- **path:** `/foo/bar/%62%61%7A`
- **expected:** DISALLOW
- **section:** 2.2.2 — RECOLLECTED
- **why:** This is verbatim the last row of §2.2.2's example table: the path
  `/foo/bar/%62%61%7A` has "path to match" `/foo/bar/baz`. `b`, `a`, `z` are unreserved, so
  the triplets are gratuitous encodings and must be decoded before comparison. It is also
  the obvious evasion: encode every letter of a banned path.
- **direction:** FAIL_OPEN_RISK
- **confidence:** HIGH

### 29. `pct_encoded_slash_is_not_a_separator`

```
User-agent: *
Disallow: /a/b
```

- **agent:** `integral-job-search/0.1`
- **path:** `/a%2Fb`
- **expected:** ALLOW
- **section:** 2.2.2 — RECOLLECTED
- **why:** `/` is a gen-delim, i.e. reserved, and reserved octets stay percent-encoded
  through comparison — decoding `%2F` would change the URI's meaning, since an encoded
  slash is data inside one segment, not a path separator. So the canonical forms are
  `/a/b` and `/a%2Fb` and they differ. A matcher that blanket-unquotes the path refuses a
  distinct resource.
- **direction:** FAIL_CLOSED_RISK
- **confidence:** HIGH

### 30. `pct_encoded_slash_in_rule_matches`

```
User-agent: *
Disallow: /a%2Fb
```

- **agent:** `integral-job-search/0.1`
- **path:** `/a%2Fb`
- **expected:** DISALLOW
- **section:** 2.2.2 — RECOLLECTED
- **why:** The other half of case 29 and the fail-open one: an operator who wrote `%2F`
  meant the encoded-slash resource, and it is what was requested. A matcher that
  canonicalises the rule by decoding everything turns it into `/a/b`, which does not match
  `/a%2Fb`, and fetches. 29 and 30 must both hold; passing one by choosing a global decode
  policy fails the other.
- **direction:** FAIL_OPEN_RISK
- **confidence:** MEDIUM

### 31. `reserved_octets_stay_encoded_in_query`

```
User-agent: *
Disallow: /foo/bar?baz=https%3A%2F%2Ffoo.bar
```

- **agent:** `integral-job-search/0.1`
- **path:** `/foo/bar?baz=https://foo.bar`
- **expected:** DISALLOW
- **section:** 2.2.2 — RECOLLECTED
- **why:** Row two of §2.2.2's example table: the path `/foo/bar?baz=https://foo.bar` has
  "path to match" `/foo/bar?baz=https%3A%2F%2Ffoo.bar`, because `:` and `/` appearing as
  *data* inside a query value are reserved octets and get encoded before comparison. Note
  the tension with the same table's first row, where `?` and `=` acting as delimiters stay
  literal: the encoding applies to reserved octets used as data, not to the URI's own
  structural delimiters.
- **direction:** FAIL_OPEN_RISK
- **confidence:** HIGH

### 32. `non_ascii_utf8_is_percent_encoded`

```
User-agent: *
Disallow: /jobs/ツ
```

- **agent:** `integral-job-search/0.1`
- **path:** `/jobs/%E3%83%84`
- **expected:** DISALLOW
- **section:** 2.2.2 — RECOLLECTED
- **why:** Rows three and four of the §2.2.2 example table: both `/foo/bar/U+E38384` and
  `/foo/bar/%E3%83%84` have "path to match" `/foo/bar/%E3%83%84`. Octets outside US-ASCII
  are percent-encoded before comparison, so a literal UTF-8 rule and a percent-encoded
  request path are the same string.
- **direction:** FAIL_OPEN_RISK
- **confidence:** HIGH

### 33. `bare_percent_is_not_an_escape`

```
User-agent: *
Disallow: /sale/100%discount
```

- **agent:** `integral-job-search/0.1`
- **path:** `/sale/100%discount`
- **expected:** DISALLOW
- **section:** 2.2.2 — RECOLLECTED
- **why:** `%di` is not a valid percent-encoding triplet, so there is nothing to decode on
  either side and the two strings are octet-identical. The verdict is easy; the risk is
  the *implementation* — a decoder that raises on an invalid escape, or that silently
  drops the `%`, will disagree, and if the error path defaults to "allow" the failure is
  fail-open on a rule the operator wrote in plain sight.
- **direction:** FAIL_OPEN_RISK
- **confidence:** MEDIUM

### 34. `plus_is_not_a_space`

```
User-agent: *
Disallow: /search/a+b
```

- **agent:** `integral-job-search/0.1`
- **path:** `/search/a%20b`
- **expected:** ALLOW
- **section:** 2.2.2 — RECOLLECTED
- **why:** In a URI path `+` is a literal plus (a sub-delim); `+` means space only under
  the `application/x-www-form-urlencoded` serialisation, which is not what §2.2.2's
  canonicalisation invokes. So the canonical forms are `/search/a+b` and `/search/a%20b`,
  which differ. A matcher that runs a form-decoder over paths refuses a page the operator
  did not name.
- **direction:** FAIL_CLOSED_RISK
- **confidence:** LOW — RFC 9309 says nothing about `+` at all; this is read off RFC 3986
  via §2.2.2's reference to it. In a *query* string the same case is genuinely murkier and
  is deliberately not asserted here.

---

## F. Query strings and case (§2.2.1, §2.2.2)

### 35. `query_is_part_of_the_matched_string`

```
User-agent: *
Disallow: /search
```

- **agent:** `integral-job-search/0.1`
- **path:** `/search?q=developer&page=2`
- **expected:** DISALLOW
- **section:** 2.2.2 — RECOLLECTED
- **why:** §2.2.2's example table adjudicates `/foo/bar?baz=quz` as a single string, so the
  query is matched, and a prefix rule of `/search` covers it. A matcher that splits the
  query off before matching still disallows here — but see case 36, which it fails.
- **direction:** FAIL_OPEN_RISK
- **confidence:** HIGH

### 36. `wildcard_question_mark_bans_queries`

```
User-agent: *
Disallow: /*?
```

- **agent:** `integral-job-search/0.1`
- **path:** `/jobs?page=2`
- **expected:** DISALLOW
- **section:** 2.2.3 (with 2.2.2 on what is matched) — RECOLLECTED
- **why:** The common "no crawling of parameterised URLs" idiom: `*` spans `jobs` and the
  literal `?` must then be found in the matched string, which it is only because the query
  is part of that string. `?` is not a special character in a robots pattern. A matcher
  that strips the query finds no `?` and fetches every faceted URL on the site — which is
  precisely the load the operator wrote this rule to avoid.
- **direction:** FAIL_OPEN_RISK
- **confidence:** MEDIUM

### 37. `path_matching_is_case_sensitive`

```
User-agent: *
Disallow: /Private/
```

- **agent:** `integral-job-search/0.1`
- **path:** `/private/notes`
- **expected:** ALLOW
- **section:** 2.2.2 — RECOLLECTED
- **why:** "The matching SHOULD be case sensitive." `/Private/` and `/private/` are
  different paths, so no rule matches. This is the row that pairs against case 38: the
  *path* is case-sensitive while the *product token* is not, and a matcher with one global
  case policy gets exactly one of the two right.
- **direction:** FAIL_CLOSED_RISK
- **confidence:** MEDIUM — it is a SHOULD, not a MUST, so a case-insensitive matcher is not
  strictly non-conformant; it is however fail-closed here and would be fail-open on the
  mirrored file.

---

## G. Groups and user-agent matching (§2.2, §2.2.1)

### 38. `product_token_matching_is_case_insensitive`

```
USER-AGENT: Integral-Job-Search
Disallow: /jobs/
```

- **agent:** `integral-job-search/0.1`
- **path:** `/jobs/1`
- **expected:** DISALLOW
- **section:** 2.2.1 — RECOLLECTED
- **why:** "The crawler MUST use case-insensitive matching to find the group that matches
  the product token" — the RFC's own example is a crawler `foobot` matching a group
  `FOOBOT`. The directive keyword `USER-AGENT` is likewise case-insensitive (ABNF string
  literals are). A case-sensitive matcher finds no group, finds no `*` group either, and
  concludes the whole site is open.
- **direction:** FAIL_OPEN_RISK
- **confidence:** HIGH

### 39. `product_token_has_no_prefix_rule`

```
User-agent: integral
Disallow: /

User-agent: *
Allow: /jobs/
```

- **agent:** `integral-job-search/0.1`
- **path:** `/jobs/1`
- **expected:** ALLOW
- **section:** 2.2.1 — RECOLLECTED
- **why:** §2.2.1 defines matching a group by the product token, case-insensitively, and
  defines no prefix rule and no "most specific token" rule. `integral` is not
  `integral-job-search`, so that group is not ours; with no specific group matching, "If no
  matching group exists, crawlers MUST obey the group with a user-agent line with the `*`
  value, if present", which allows `/jobs/`.
- **direction:** FAIL_CLOSED_RISK
- **confidence:** MEDIUM — asserted as the absence of a rule rather than the presence of
  one. A matcher doing substring or longest-prefix token matching lands on the `Disallow:
  /` group; that is the widespread-in-practice behaviour, but it is not what the RFC
  describes.

### 40. `version_suffix_is_not_part_of_the_token`

```
User-agent: integral-job-search
Disallow: /jobs/

User-agent: *
Allow: /
```

- **agent:** `integral-job-search/0.1`
- **path:** `/jobs/1`
- **expected:** DISALLOW
- **section:** 2.2.1 — RECOLLECTED
- **why:** "The product token MUST contain only uppercase and lowercase letters ("a-z" and
  "A-Z"), underscores ("_"), and hyphens ("-")" — so `/0.1` cannot be part of a token, and
  the token this crawler matches on is `integral-job-search`. The specific group matches;
  the `*` group is therefore never consulted. A matcher comparing the full User-Agent
  string finds no group, falls through to `*`, and fetches a directory named for it.
- **direction:** FAIL_OPEN_RISK
- **confidence:** MEDIUM — the token-charset sentence is recalled with confidence; that a
  crawler must strip its own version suffix before matching is the natural consequence
  rather than a separate quoted rule.

### 41. `star_group_ignored_when_specific_group_matches`

```
User-agent: *
Disallow: /

User-agent: integral-job-search
Allow: /jobs/
```

- **agent:** `integral-job-search/0.1`
- **path:** `/about`
- **expected:** ALLOW
- **section:** 2.2.1 with 2.2.2 — RECOLLECTED
- **why:** The `*` group is a fallback used only "if no matching group exists". A specific
  group exists, so its rules — and only its rules — apply; its single `Allow: /jobs/` does
  not match `/about`, and §2.2.2 says a URI with no matching rule in the group is allowed.
  A matcher that unions all groups inherits `Disallow: /` and refuses the whole site.
- **direction:** FAIL_CLOSED_RISK
- **confidence:** HIGH

### 42. `foreign_agent_group_is_not_ours`

```
User-agent: ClaudeBot
Disallow: /

User-agent: GPTBot
Disallow: /

User-agent: *
Allow: /jobs/
```

- **agent:** `integral-job-search/0.1`
- **path:** `/jobs/1`
- **expected:** ALLOW
- **section:** 2.2.1 — RECOLLECTED
- **why:** A crawler matches the group for its own product token and falls back to `*`.
  Neither `ClaudeBot` nor `GPTBot` is `integral-job-search`, so neither group binds this
  crawler; the `*` group does, and it allows. (This is the case CLAUDE.md says has been
  re-litigated twice — it is here as a *spec* row, not as a policy row: what an operator's
  ban on a training crawler means for a different product token is settled by §2.2.1
  alone.)
- **direction:** FAIL_CLOSED_RISK
- **confidence:** HIGH

### 43. `foreign_agent_allow_does_not_rescue`

```
User-agent: *
Disallow: /jobs/

User-agent: GPTBot
Allow: /jobs/apply
```

- **agent:** `integral-job-search/0.1`
- **path:** `/jobs/apply`
- **expected:** DISALLOW
- **section:** 2.2.1 with 2.2.2 — RECOLLECTED
- **why:** The mirror of case 42 and the fail-open half of it. Only the `*` group applies
  to us; the longer `Allow` lives in a group naming a different token and must not enter
  the longest-match comparison at all. A matcher that flattens the file into one rule list
  finds a 15-octet allow beating a 6-octet disallow and fetches.
- **direction:** FAIL_OPEN_RISK
- **confidence:** HIGH

### 44. `consecutive_ua_lines_share_the_rules`

```
User-agent: foobot
User-agent: integral-job-search
Disallow: /admin/
```

- **agent:** `integral-job-search/0.1`
- **path:** `/admin/x`
- **expected:** DISALLOW
- **section:** 2.2 and 2.2.1 — RECOLLECTED
- **why:** The ABNF's `group = startgroupline *(startgroupline / emptyline) *(rule /
  emptyline)`: consecutive user-agent lines start **one** group covering the rules that
  follow. A matcher that keeps only the first or only the last user-agent line of a run
  loses one of the two tokens, and for that token the file reads as empty.
- **direction:** FAIL_OPEN_RISK
- **confidence:** HIGH

### 45. `two_groups_same_token_are_combined`

```
User-agent: integral-job-search
Allow: /jobs/

User-agent: integral-job-search
Disallow: /jobs/internal/
```

- **agent:** `integral-job-search/0.1`
- **path:** `/jobs/internal/7`
- **expected:** DISALLOW
- **section:** 2.2.1 with 2.2.2 — RECOLLECTED
- **why:** "If there is more than one group matching the user agent, the matching groups'
  rules MUST be combined into one group" — so this is case 2 spread across two groups: 15
  octets beats 6. A matcher that stops at the first matching group sees only the `Allow`.
- **direction:** FAIL_OPEN_RISK
- **confidence:** HIGH

### 46. `blank_line_before_any_rule_does_not_split`

```
User-agent: integral-job-search

User-agent: *
Disallow: /
```

- **agent:** `integral-job-search/0.1`
- **path:** `/jobs/1`
- **expected:** DISALLOW
- **section:** 2.2 — RECOLLECTED
- **why:** Under the ABNF a group is `startgroupline *(startgroupline / emptyline) *(rule /
  emptyline)`, and an `emptyline` is admitted *between* start-group lines — so the blank
  line does not end a group that has not yet had a rule, and both user-agent lines head one
  group whose only rule is `Disallow: /`. The competing reading, "a blank line terminates a
  group", makes the first group rule-less and ALLOWs everything for this crawler while the
  `*` group is never reached (case 41's logic). **This table takes the ABNF reading**:
  DISALLOW.
- **direction:** FAIL_OPEN_RISK
- **confidence:** LOW — this is the sharpest place two *correct* readers diverge, because
  the widely-deployed convention ("blank line ends a group") and the published grammar do
  not obviously agree. The safe implementation choice is the one taken here, since the
  alternative opens a whole site on the strength of a blank line. Flag disagreement for
  discussion rather than treating it as a defect.

### 47. `group_with_no_rules_allows`

```
User-agent: *
Disallow: /admin/

User-agent: integral-job-search
```

- **agent:** `integral-job-search/0.1`
- **path:** `/admin/x`
- **expected:** ALLOW
- **section:** 2.2.2 with 2.2.1 — RECOLLECTED
- **why:** A specific group matches, so the `*` group is not consulted; the specific group
  is at end-of-file and contains no rules, and §2.2.2 says "If no match is found amongst
  the rules in a group for a matching user agent, **or there are no rules in the group**,
  the URI is allowed." A rule-less group is a real and deliberate way to exempt a crawler.
- **direction:** FAIL_CLOSED_RISK
- **confidence:** MEDIUM — the "no rules in the group" clause is recalled with confidence;
  what is slightly less certain is that a trailing rule-less start line constitutes a group
  at all rather than being discarded. Both routes reach ALLOW here, by different arguments.

### 48. `rules_before_first_ua_line_are_ignored`

```
Disallow: /secret/

User-agent: *
Allow: /
```

- **agent:** `integral-job-search/0.1`
- **path:** `/secret/x`
- **expected:** ALLOW
- **section:** 2.2 — RECOLLECTED
- **why:** `robotstxt = *(group / emptyline)` and every group begins with a start-group
  line, so a rule preceding any `User-agent:` belongs to no group and there is no crawler
  it applies to. It is not a syntax error that voids the file — the rest parses normally,
  and here the `*` group allows.
- **direction:** FAIL_CLOSED_RISK
- **confidence:** MEDIUM — read off the grammar rather than off a prose sentence saying
  "ignore them". Note this row is fail-*closed*, so a matcher that wrongly honours the
  orphan rule is being conservative; it is included because the same bug in a file whose
  orphan line is an `Allow:` is fail-open.

### 49. `comment_is_stripped_from_the_value`

```
User-agent: *
Disallow: /admin/    # staff only, humans welcome
```

- **agent:** `integral-job-search/0.1`
- **path:** `/admin/users`
- **expected:** DISALLOW
- **section:** 2.2.3 (with 2.2's `*WS`) — RECOLLECTED
- **why:** `#` "designates an end-of-line comment", so everything from `#` is dropped and
  the surrounding whitespace with it, leaving the pattern `/admin/`. A matcher that takes
  the rest of the line literally holds a pattern containing spaces and a `#`, which no
  request path can match — the rule silently becomes inert, which is the worst kind of
  fail-open because the file *looks* like it forbids the path.
- **direction:** FAIL_OPEN_RISK
- **confidence:** MEDIUM — the comment rule is recalled with confidence; that trailing
  whitespace before the `#` is trimmed rather than kept as part of the pattern is the
  natural reading of the ABNF's `*WS`, not a separate quoted sentence.

---

## H. Percent-encoding equivalence, again — what section E missed (§2.2.2)

**Provenance differs here and it is the point of the section.** Rows 1–49 were derived
before any implementation existed. Rows 50–53 were derived afterwards, from the same
text, by the session that **reviewed** the reader those rows were written to judge — and
they were derived because section E's rows were all green against a reader that was still
fail-open. Rows 52 and 53 come from that review's **second** round, and they are the
strongest form of the section's own claim: they were green against the fix rows 50 and 51
produced, and the reader was still fail-open where §2.2.2 and §2.2.3 meet.

Section E adjudicates percent-encoding equivalence through the two octets §2.2.2's example
table happens to print, `:` and `/` (rows 26–31). A reader can satisfy every one of those
rows with the literal set `":/"`, and that is exactly what the reader under review carried:
`_QUERY_DATA_OCTETS = ":/"`. Every *other* reserved octet used as query data then escaped
the equivalence, in the fail-open direction — `Disallow: /s?q=a%26b` matched nothing.

The generalisation the rows below assert is read off §2.2.2's own sentence rather than off
its table: octets "outside the range of the US-ASCII coded character set, and those in the
reserved range defined by RFC3986, MUST be percent-encoded ... prior to comparison"
(RECOLLECTED). The requirement is stated over RFC 3986's **reserved** production —
gen-delims `:/?#[]@` and sub-delims `!$&'()*+,;=` — and the table illustrates it with two
of those eleven-plus octets. **A table is an illustration of a rule and never its extent**,
and a case table built only from a spec's examples inherits whatever the examples do not
reach. That is the lesson of these two rows, and it applies to section E as much as to any
implementation.

### 50. `ampersand_as_query_data_is_encoded`

```
User-agent: *
Disallow: /s?q=a%26b
```

- **agent:** `integral-job-search/0.1`
- **path:** `/s?q=a&b`
- **expected:** DISALLOW
- **section:** 2.2.2 — RECOLLECTED
- **why:** `&` is a sub-delim, so it is in RFC 3986's reserved range, so §2.2.2's sentence
  requires it percent-encoded before comparison — exactly as the `:` and the two `/` of the
  example table's second row are. Here it sits as data inside the value of `q`, the same
  position `https://foo.bar` occupies inside the value of `baz` in row 31. Rule and request
  are therefore two spellings of one URI, and the rule refuses the request.
- **direction:** FAIL_OPEN_RISK
- **confidence:** HIGH — the octet's membership in `sub-delims` is not in doubt, and the
  sentence quantifies over the whole reserved range rather than over the table's examples.
  The one thing the RFC leaves open — where the line between "data" and "structure" falls
  inside a query — does not reach this row: `&` here separates nothing, it is the second
  octet of the value `a&b`.

### 51. `equals_as_query_data_is_encoded`

```
User-agent: *
Disallow: /s?q=a%3Db
```

- **agent:** `integral-job-search/0.1`
- **path:** `/s?q=a=b`
- **expected:** DISALLOW
- **section:** 2.2.2 — RECOLLECTED
- **why:** Row 50's argument with `=` in place of `&`; `=` is likewise a sub-delim. This
  row is built so the sub-reading cannot change the verdict, which is why it can be `HIGH`
  while the data/structure line stays unsettled. Read **strictly** — only reserved octets
  appearing as data are encoded, and the `=` separating `q` from its value is structure —
  the *second* `=` in `q=a=b` is still data, so `%3D` and `=` meet and the rule matches.
  Read **broadly** — every reserved octet after the query delimiter is encoded — both `=`
  are encoded on both sides, and the rule matches again. DISALLOW under either.
- **direction:** FAIL_OPEN_RISK
- **confidence:** HIGH — for the reason just given: the row is constructed to be invariant
  under the one ambiguity that could otherwise lower it.

---

### 52. `star_as_query_data_is_encoded`

```
User-agent: *
Disallow: /s?q=a%2Ab
```

- **agent:** `integral-job-search/0.1`
- **path:** `/s?q=a*b`
- **expected:** DISALLOW
- **section:** 2.2.2 — RECOLLECTED
- **why:** `*` is an RFC 3986 sub-delim, so §2.2.2 percent-encodes it before comparison
  like any other reserved octet, and rule and request are two spellings of one URI.
  §2.2.3 is not a counter-argument, and the **direction** is the whole of it: §2.2.3
  defines `*` as a special character *in the value* of an `Allow` or `Disallow` field —
  it designates 0 or more instances of any character **in a pattern**. A request target is
  not a pattern. There is nothing in `/s?q=a*b` for a `*` to designate 0 or more of. So a
  matcher may hold `*` out of the encode pass on the **rule** side, where encoding it would
  delete the rule's own wildcard, and must not hold it out on the **target** side, where
  doing so leaves the rule's `%2A` nothing to compare equal to.
- **direction:** FAIL_OPEN_RISK
- **confidence:** HIGH — the encoding requirement is stated over a set that contains `*`,
  and the exemption argument is about patterns, which a target is not.

---

### 53. `dollar_as_query_data_is_encoded`

```
User-agent: *
Disallow: /s?q=a%24b
```

- **agent:** `integral-job-search/0.1`
- **path:** `/s?q=a$b`
- **expected:** DISALLOW
- **section:** 2.2.2 — RECOLLECTED
- **why:** Row 52's argument with `$` in place of `*`, and it needs its own row for the
  reason 51 needs one after 50: a fix reaching one octet of a two-octet hold-out leaves the
  other exactly as it was. `$` is a sub-delim and therefore reserved; §2.2.3 designates it
  "the end of the match pattern", which is a property a **pattern** has and a request target
  does not. This row takes **no** position on row 22's open question — whether a literal
  `$` written inside a *rule* should be encoded is still unsettled. It asks only about the
  target, where there is no match pattern for `$` to end.
- **direction:** FAIL_OPEN_RISK
- **confidence:** HIGH — for row 52's reason; row 22's ambiguity is on the other side of
  the comparison and is untouched.

---

## Using this table

Each row is a fixture, not a comment. Per CLAUDE.md, an accepted case is only accepted once
it is **committed into the gate's own fixtures before the PR merges** — a report that is
read and waved through leaves the code exactly as unprotected as it was, and the measured
denominator must rise by the number of cases accepted.

Where a row is `LOW`, the finding is a *reading disagreement* to settle in writing (cases
22, 24, 25, 34, 46 — the five `second_reader.CONTESTED_CASES` publishes), not
automatically a defect. Where a row is `HIGH` and `FAIL_OPEN_RISK`, a
disagreeing matcher is fetching something the operator refused.
