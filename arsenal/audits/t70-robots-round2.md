# T70 robots.txt matching — round 2 adversarial audit

**Auditor note on process.** This audit followed the mandatory order: cases were
derived from RFC 9309 alone and committed (`21ad1af`) *before*
`src/integral/robots.py` was opened. One case (#7 below) turned out to model the
spec incorrectly — it ignored that an unanchored `Disallow` value is a *prefix*
rule — and was corrected in a separate commit (`4a97ed4`) that cites the section
the correction rests on, per the audit protocol; it was not "fixed" because the
implementation disagreed with it. Everything else below is the implementation's
behaviour as measured by actually running it, not by re-reading the code.

**Source-text caveat.** `https://www.rfc-editor.org/rfc/rfc9309.txt` and
`https://www.ietf.org/rfc/rfc9309.txt` both returned `403` through this
session's egress proxy (an organization policy denial — `recentRelayFailures`
in the proxy status recorded `connect_rejected` for `www.rfc-editor.org:443`;
the second host failed identically). Per the proxy runbook, a 403 is not
retried. Every citation below is therefore from trained knowledge of RFC 9309,
not a freshly-fetched copy of the text, and should be spot-checked against the
actual RFC by whoever reads this before treating the one confirmed-discrepancy
case (#22) as settled. **That spot-check was done — see the resolution note on
case 22: the recollection was wrong and the implementation was right.**

## Totals

| | count |
|---|---|
| Cases derived | 35 |
| Cases the implementation passes | 33 |
| Fail-OPEN discrepancies | 0 (case 22 was resolved by T102: no defect — the recollected citation was wrong) |
| Fail-CLOSED discrepancies | 0 |
| Neither (schema mismatch — implementation raises rather than returns a bool; see case 35) | 1 |

33 + 1 + 1 = 35. The one non-fail-open, non-fail-closed row (case 35) is not
folded into "passing" because the implementation's actual behavior (raising)
does not match what the case's `expected_allowed: bool` schema demanded, but it
is also not counted as a defect, for the reason given under case 35.

## Method recap

1. Read RFC 9309 §2.2.1 (User-agent line, product tokens), §2.2.2
   (Allow/Disallow, percent-encoding equivalence, empty values), §2.2.3 ('*'
   and '$'), §2.3 (access-method / status handling) and §5.1 (longest-match,
   Allow-wins tie-break) from memory (fetch blocked, see above).
2. Derived 35 cases into `t70-robots-round2-cases.py`, committed before
   opening the implementation.
3. Read `src/integral/robots.py`.
4. Ran every case through `Robots.allows()` via a throwaway runner
   (`/tmp/.../run_t70_round2.py`, not committed — scratch only) that injects a
   fake `fetch` callable so no network access is needed.
5. Corrected one case's own modeling error (case 7) in a separate, cited
   commit, then re-ran all 35.

## Per-case results

Legend: **MATCH** = implementation's verdict equals the spec-required verdict.
**DISCREPANCY (fail-open)** = spec requires block, implementation allows.
**DISCREPANCY (fail-closed)** = spec requires allow, implementation blocks.

### 1. `percent-encoded-unreserved-rule-vs-literal-request` — MATCH
- robots.txt: `User-agent: *` / `Disallow: /%7Euser`
- agent: `TestBot/1.0`, url: `https://example.com/~user`
- Required: **blocked**. RFC 9309 §2.2.2 + RFC 3986 §2.3 — `~` is unreserved,
  so `%7E` in the rule must normalize to the literal `~` in the request path.
- Actual: blocked. `_canon` decodes `%7E` to `~` (it's in `_UNRESERVED`), giving
  canonical form `/~user` on both sides.

### 2. `literal-rule-vs-percent-encoded-unreserved-request` — MATCH
- robots.txt: `Disallow: /~user`; url: `https://example.com/%7Euser`
- Required: **blocked** (same normalization, reversed direction).
- Actual: blocked, same reasoning as case 1 applied to the request path instead
  of the rule.

### 3. `percent-encoded-reserved-slash-exact-match` — MATCH
- robots.txt: `Disallow: /a%2Fb`; url: `https://example.com/a%2Fb`
- Required: **blocked**. `/` is reserved, not unreserved, so `%2F` is never
  decode-normalized — but an identically-encoded rule and request path are the
  same octet sequence regardless.
- Actual: blocked. `_canon` leaves `%2F` as an uppercase escape on both sides.

### 4. `percent-encoded-reserved-slash-must-not-equal-literal-slash` — MATCH
- robots.txt: `Disallow: /a%2Fb`; url: `https://example.com/a/b`
- Required: **allowed**. Because `/` is reserved, `%2F` must not be equated
  with an unencoded `/`; the rule and the request denote different resources.
- Actual: allowed. `_canon("/a/b")` stays `/a/b` (no escapes to decode), which
  does not start with the rule's canonical `/a%2Fb`.

### 5. `percent-encoding-hex-digit-case-insensitivity` — MATCH
- robots.txt: `Disallow: /caf%C3%A9`; url: `https://example.com/caf%c3%a9`
- Required: **blocked**. RFC 3986 §2.1 — hex digits in a percent-triplet are
  case-insensitive; `%C3%A9` and `%c3%a9` are the same two octets.
- Actual: blocked. `_canon` decodes via `int(hex, 16)` (case-insensitive) and
  re-emits any kept escape uppercased, so both sides canonicalize to
  `/caf%C3%A9`.

### 6. `percent-25-literal-percent-sign-exact-match` — MATCH
- robots.txt: `Disallow: /100%25`; url: `https://example.com/100%25`
- Required: **blocked**. `%` is not unreserved, so a literal `%` octet is
  spelled `%25`; identical spellings on both sides match.
- Actual: blocked.

### 7. `double-encoded-percent-sign-does-not-match-single-encoded` — MATCH (case corrected)
- robots.txt (corrected): `Disallow: /100%25$`; url: `https://example.com/100%2525`
- Required: **allowed**. `$` anchors the pattern to end exactly after the
  decoded `%` octet (9th... 7th character of the canonical rule, `/100%25`,
  length 7); `%2525` decodes one level to the literal string `%25` (3 further
  characters), so the request's canonical form (`/100%2525`, length 9) cannot
  end where the anchor requires.
- Actual: allowed.
- **Why this case was corrected.** The original version used an *unanchored*
  `Disallow: /100%25` and claimed the double-encoded request must not match it.
  That was wrong on the spec's own terms, independent of the implementation:
  an unanchored Disallow value is a *prefix* rule under RFC 9309 §2.2.2, and
  the literal octet string `/100%25` genuinely is a prefix of `/100%2525`, so
  the original expected answer (allowed) was actually correct for the wrong
  reason and would have passed either way without exercising what it meant to
  test. Anchoring with `$` is what actually isolates "does double-encoding
  collapse to single-encoding" from "is this a prefix". Fixed in a separate
  commit citing §2.2.2/§2.2.3, not because the code disagreed with the
  original.

### 8. `percent-encoded-unreserved-letters-spelling-a-word` — MATCH
- robots.txt: `Disallow: /%41dmin`; url: `https://example.com/Admin`
- Required: **blocked**. `A`-`Z`/`a`-`z` are unreserved; `%41` decodes to `A`.
- Actual: blocked.

### 9. `empty-disallow-value-permits-everything` — MATCH
- robots.txt: `User-agent: *` / `Disallow:` (empty); url: anything
- Required: **allowed**. RFC 9309 §2.2.2 — an empty Disallow value is a no-op,
  not a rule matching every path.
- Actual: allowed. The parser's `if value: rules.append(...)` guard drops
  empty-valued rules entirely; the code's own comment (lines 158–166) explains
  this was a deliberate fix for exactly this failure mode (`Disallow:` used to
  be stored as pattern `""`, which matched everything and blocked the whole
  site).

### 10. `empty-allow-value-does-not-suppress-real-disallow` — MATCH
- robots.txt: `Allow:` (empty) then `Disallow: /private`; url: `/private`
- Required: **blocked**. An empty Allow rule carries no specificity and must
  not suppress a real, matching Disallow.
- Actual: blocked (the empty Allow line never becomes a rule at all, so there
  is nothing to out-rank the Disallow).

### 11. `literal-question-mark-blocks-matching-query-string` — MATCH
- robots.txt: `Disallow: /path?`; url: `https://example.com/path?query=1`
- Required: **blocked**. `?` outside `*`/`$` is a literal octet; `/path?` is a
  prefix of `/path?query=1`.
- Actual: blocked. `_request_path` explicitly reconstructs `path?query` from
  `urlsplit`, with a comment (lines 292–297) noting that testing `parts.query`
  alone would have dropped a bare trailing `?` and let this exact case through.

### 12. `literal-question-mark-does-not-block-bare-path` — MATCH
- robots.txt: `Disallow: /path?`; url: `https://example.com/path`
- Required: **allowed**. `/path?` is not a prefix of `/path` (missing `?`).
- Actual: allowed.

### 13. `wildcard-then-literal-question-mark-blocks-any-query` — MATCH
- robots.txt: `Disallow: /*?`; url: `https://example.com/page?x=1`
- Required: **blocked**. `*` absorbs `page`, leaving the literal `?` to match.
- Actual: blocked.

### 14. `wildcard-then-literal-question-mark-does-not-block-no-query` — MATCH
- robots.txt: `Disallow: /*?`; url: `https://example.com/page`
- Required: **allowed** (no `?` anywhere in the path to satisfy the pattern).
- Actual: allowed.

### 15. `dollar-anchor-exact-match` — MATCH
- robots.txt: `Disallow: /path$`; url: `https://example.com/path`
- Required: **blocked**.
- Actual: blocked.

### 16. `dollar-anchor-rejects-longer-suffix` — MATCH
- robots.txt: `Disallow: /path$`; url: `https://example.com/pathxyz`
- Required: **allowed** (anchor forbids trailing characters).
- Actual: allowed.

### 17. `dollar-anchor-rejects-trailing-slash` — MATCH
- robots.txt: `Disallow: /path$`; url: `https://example.com/path/`
- Required: **allowed** (`/path/` has an extra `/` after `path`).
- Actual: allowed.

### 18. `wildcard-basic-suffix-match` — MATCH
- robots.txt: `Disallow: /*.php`; url: `https://example.com/index.php`
- Required: **blocked**.
- Actual: blocked.

### 19. `wildcard-dollar-anchor-excludes-query-suffix` — MATCH
- robots.txt: `Disallow: /*.php$`; url: `https://example.com/index.php?x=1`
- Required: **allowed** (string continues with `?x=1` after `.php`, so the
  anchor is not satisfied).
- Actual: allowed.

### 20. `consecutive-wildcards-collapse-to-one` — MATCH
- robots.txt: `Disallow: /a**b`; url: `https://example.com/axyzb`
- Required: **blocked** (two adjacent `*` behave as one).
- Actual: blocked. Splitting `/a**b` on `*` yields `["/a", "", "b"]`; the empty
  middle chunk is explicitly skipped (`if not chunk: continue`) rather than
  breaking the scan.

### 21. `trailing-wildcard-before-dollar-matches-zero-expansion` — MATCH
- robots.txt: `Disallow: /a*$`; url: `https://example.com/a`
- Required: **blocked** (`*` may expand to zero characters).
- Actual: blocked.

### 22. `agent-token-is-substring-of-longer-crawler-token` — **RESOLVED: no defect; the recollected citation was wrong**

> **Resolution (T102, issue #236).** Two sessions read RFC 9309 §2.2.1
> independently of each other and of the implementation, and both reached the
> same verdict: the section grants **one** relaxation — "Crawlers MUST use
> case-insensitive matching to find the group that matches the product token"
> — and the only substring relation the RFC states runs the other way, between
> a crawler's product token and the identification string it sends. There is no
> prefix rule and no specificity rule; the RFC says only to combine every group
> whose token matches, which is coherent only under equality. Its own figures
> agree from the other side: one describes "two groups that match the same
> product token exactly", and another declares `user-agent: BazBot` a non-match
> for the crawler `ExampleBot` — two tokens sharing the suffix `Bot`.
> `_select_rules` is correct and was **not** changed. The `googlebot` /
> `Googlebot-Image` illustration below is Google's crawler handing the matcher
> several of its own names, not a rule in the RFC.
>
> **The recommendation at the end of this file is retracted.** Acting on it
> would introduce the fail-open it was filed to prevent: an explicitly matched
> group is used *exclusively*, so a prefix match can displace the `*` group and
> unblock a path the site disallowed for every crawler. The fixture
> `a_prefix_file_token_does_not_displace_the_wildcard_group` is that document.
> Three fixtures now hold this case in both directions (`robots.py`), and the
> gate's denominator rose 56 → 59.

- robots.txt: `User-agent: Bot` / `Disallow: /private`
- agent: `Botly/2.0` (extracted product token: `Botly`)
- url: `https://example.com/private`
- Required (per recollected RFC 9309 §2.2.1): **blocked**. My recollection of
  the spec's User-agent matching rule is that a robots.txt product token
  matches a crawler if it is a case-insensitive **prefix/substring of the
  crawler's own product token** — the canonical illustration being that a
  single line `User-agent: googlebot` is meant to also govern
  `Googlebot-Image` and `Googlebot-News`, whose product tokens start with
  `googlebot` but are not equal to it. Under that reading, `Bot` (the rule's
  token) is a prefix of `Botly` (the crawler's token), so the `Bot` group's
  `Disallow: /private` should govern this crawler.
- Actual: **allowed**. `_select_rules` (robots.py:183–198) requires the
  group's token to be *exactly* equal (case-insensitively) to the crawler's
  extracted token (`a.lower() == agent_lower`) — never a prefix/substring
  relationship in this direction. Since `"bot" != "botly"` and there is no
  wildcard `*` group in this document, no group matches at all, `_select_rules`
  returns an empty rule list, and `_allowed([], path)` returns the implicit-allow
  default (`True`).
- **Why I am flagging this rather than asserting it as a confirmed bug.** I
  could not fetch the live RFC text (see caveat above) to re-check the exact
  wording of §2.2.1 before writing this citation. The module's own docstring
  (robots.py:52–99) discusses a *different* substring relationship at length —
  extracting one product token out of a multi-product identification string
  such as `Mozilla/5.0 (compatible; integral-job-search/0.1; ...)` — and is
  visibly deliberate and well-reasoned about that. It does not address the
  question this case raises (whether a *rule's* token should match as a prefix
  of a longer *crawler* token), and its own docstring for `_select_rules`
  states the exact-match design in absolute terms ("An explicit token equal to
  `agent` is used exclusively when one exists"), suggesting this was a
  conscious choice rather than an oversight — but a choice that, if my
  recollection of §2.2.1 is right, is a real fail-open: a site that writes one
  rule for `googlebot` intending to cover all of Google's specialized crawlers
  would have none of them actually governed by it under this implementation,
  and depending on what the wildcard group says (or its absence, as here),
  the specialized crawler could see strictly more of the site than the site
  intended. **Recommendation: the next reader with working RFC access should
  confirm the exact wording of §2.2.1 on this specific point before this is
  either fixed or dismissed.** Cases 23 and 24 below test adjacent
  specificity/direction behavior that does *not* depend on this ambiguity, and
  both pass — so this implementation's handling of *exact*-token groups is
  solid; the open question is narrowly about whether a *rule* token must also
  match as a prefix of a *longer* crawler token, which it currently never
  does.

### 23. `most-specific-agent-group-wins-over-shorter-token` — MATCH
- robots.txt: `User-agent: Bot` / `Disallow:` (empty), then `User-agent: Botly`
  / `Disallow: /private`
- agent: `Botly/2.0`; url: `/private`
- Required: **blocked** — the crawler's token `Botly` exactly matches the
  `Botly` group, which is used exclusively (the `Bot` group is not combined
  in, since RFC 9309 §2.2.1 says an exact match to one group must not also
  fall back to, or merge with, others).
- Actual: blocked. Note this case does not actually exercise "specificity
  between two candidate substring matches" — it exercises "exact-match takes
  priority and is used exclusively" — since `Botly` equals the second group's
  token exactly. It does not depend on the open question in case 22.

### 24. `agent-token-longer-than-crawler-token-does-not-match` — MATCH
- robots.txt: `User-agent: Botly` / `Disallow:` (empty), then `User-agent: *`
  / `Disallow: /private`
- agent: `Bot/1.0`; url: `/private`
- Required: **blocked** — `Botly` cannot match a shorter crawler token `Bot`
  under either the exact-match or the prefix-match reading (a longer string
  can never be a prefix of a shorter one), so the crawler falls through to the
  wildcard group's Disallow either way.
- Actual: blocked (via the `*` fallback, as `_select_rules` intends).

### 25. `agent-match-is-case-insensitive` — MATCH
- robots.txt: `User-agent: GoogleBot` / `Disallow: /private`
- agent: `googlebot/2.1`; url: `/private`
- Required: **blocked**. §2.2.1 — case-insensitive product-token matching.
- Actual: blocked (`_select_rules` lowercases both sides before comparing).

### 26. `path-match-is-case-sensitive` — MATCH
- robots.txt: `Disallow: /Secret`; url: `https://example.com/secret`
- Required: **allowed**. §2.2.2 — unlike agent matching, path comparison is
  case-sensitive.
- Actual: allowed (`_canon` never folds case; `str.startswith` is
  case-sensitive).

### 27. `shared-group-applies-to-every-listed-agent-token` — MATCH
- robots.txt: `User-agent: A` / `User-agent: B` / `Disallow: /secret`
- agent: `B/1.0`; url: `/secret`
- Required: **blocked** — consecutive User-agent lines with no rule between
  them form one group covering every listed token.
- Actual: blocked. `_parse_groups` only flushes a group on a new `User-agent`
  line if `started` (a directive has already been read); two agent lines in a
  row without an intervening rule are accumulated into the same group's
  `agents` tuple.

### 28. `group-with-no-rules-permits-everything` — MATCH
- robots.txt: `User-agent: *` (no rules at all); url: anything
- Required: **allowed**.
- Actual: allowed (`rules == ()`; `_allowed` defaults to `True` when no rule
  matches, "no matching rule at all is an implicit allow" per its own
  docstring).

### 29. `equal-length-tie-allow-wins-subpath` — MATCH
- robots.txt: `Allow: /page` and `Disallow: /page` (equal length)
- Required: **allowed** — RFC 9309 §5.1, Allow wins an equal-specificity tie.
- Actual: allowed. `_allowed`'s tie-break condition
  (`length == best_len and is_allow`) resolves to Allow regardless of which
  rule is processed first — verified both orderings by inspection of the
  comparison logic.

### 30. `equal-length-tie-allow-wins-root` — MATCH
- robots.txt: `Allow: /` and `Disallow: /`; url: `/`
- Required: **allowed** (same tie-break, at the root).
- Actual: allowed.

### 31. `specificity-must-be-computed-on-decoded-octets-not-raw-text` — MATCH
- robots.txt: `Allow: /%61/%62` (decodes to `/a/b`, 4 octets) and
  `Disallow: /a/bcdef` (8 octets); url: `/a/bcdef`
- Required: **blocked** — RFC 9309 §5.1 + §2.2.2: specificity must be computed
  on the decoded octet length, not on the raw rule-line character count
  (which happens to be 8 characters for *both* lines here — `/%61/%62` and
  `/a/bcdef` are each 8 raw characters — a naive raw-length comparison would
  see this as a tie and wrongly resolve to Allow, i.e. fail open).
- Actual: blocked. `_allowed` computes `length` from the already-decoded
  `chunks` (`sum(len(chunk) for chunk in chunks) + ...`), so `Allow` scores 4
  and `Disallow` scores 8; Disallow correctly wins as strictly more specific.
  **This is a real, deliberately-designed defense** — this exact case is what
  the audit was asked to target, and it passes cleanly.

### 32. `duplicate-agent-groups-combine-first-groups-rule-survives` — MATCH
- robots.txt: `User-agent: Bot` / `Disallow: /a`, then `User-agent: Bot` /
  `Disallow: /b`; agent `Bot/1.0`; url: `/a`
- Required: **blocked** — RFC 9309 §2.2.1, duplicate groups for the same token
  must have their rules combined, not have the first one discarded.
- Actual: blocked. `_select_rules`'s `explicit` list includes every group
  whose token matches, and concatenates all their rules.

### 33. `duplicate-agent-groups-combine-second-groups-rule-survives` — MATCH
- Same document as case 32; url: `/b`
- Required: **blocked** — the second group's rule must also survive, not be
  discarded in favor of "first group wins".
- Actual: blocked.

### 34. `http-404-treated-as-unavailable-full-allow` — MATCH
- Simulated fetch raising `HTTPError(..., 404, ...)`; url: anything
- Required: **allowed**. RFC 9309 §2.3 — a 4xx status means the robots.txt
  resource does not exist, so no restrictions apply.
- Actual: allowed. `_groups_for` (robots.py:344–350) catches `HTTPError` and,
  for code `404` specifically, treats the text as empty (`text = ""`), which
  parses to zero groups and therefore implicit-allows everything.

### 35. `http-500-treated-as-unreachable-full-disallow` — **NEITHER pass nor a fail-open/fail-closed defect (schema mismatch)**
- Simulated fetch raising `HTTPError(..., 500, ...)`; url: anything
- Required (per my recollection of §2.3): **blocked** — a 5xx / unreachable
  status must not be treated the same as a 404; absent a usable cached copy,
  the crawler must assume complete disallow.
- Actual: `Robots.allows()` does not return a boolean at all for this
  scenario — it **raises `RobotsError`** ("`https://example.com/robots.txt
  returned 500`"), propagated straight out of `_groups_for` for any
  `HTTPError` whose code is not `404` (robots.py:348–349), and also for any
  `OSError` (network failure) at line 351–352.
- **Why this isn't scored as a defect.** My case schema assumed a boolean
  return, which was itself a modeling gap on my part (I designed the schema
  before reading the code, per the mandated order, and the code models
  "unreachable" as an exception rather than a value). Behaviorally, an
  exception that is not caught and is allowed to propagate is at least as
  conservative as returning `False` — it stops the caller from fetching
  outright, and is arguably *safer* than a bare boolean, because it cannot be
  silently misread as a normal "allowed" `True`/`False` by code that forgets
  to check it. It only becomes a fail-open risk if some *caller* of
  `Robots.allows()` catches `RobotsError` and defaults to permitting the fetch
  on failure — that is outside `robots.py` itself and outside the scope of
  this audit; whoever calls `.allows()` in `tools/collect_ads.py` (or
  wherever) should be checked separately for that pattern.

## Recommendation summary

- ~~**One item to escalate to a human or a session with working RFC access:**
  case 22 (agent-token substring/prefix matching direction). If §2.2.1 does
  say a rule's product token must match as a prefix of a longer crawler token
  (not just equality), `_select_rules` has a genuine fail-open gap and should
  be extended to try a prefix match when no exact match exists, before falling
  back to `*`.~~ **RETRACTED — T102 read §2.2.1: it does not say that, matching
  is case-folded equality, `_select_rules` is correct, and extending it to try a
  prefix match would *create* a fail-open. See case 22 above.**
- **One item worth a follow-up audit, not a code change:** whichever code
  calls `Robots.allows()` should be checked for how it handles `RobotsError`
  on network/server failures (case 35) — if it catches and defaults to
  allowing, *that* call site is the fail-open, not this module.
- **Everything else (33 of 35 cases) passed as specified**, including the
  case this audit was specifically dispatched to probe (case 31, decoded-octet
  specificity crossing a percent-encoding boundary) and the duplicate-group
  merging and empty-value handling the module's own comments flag as past
  regressions (cases 9, 32, 33).
