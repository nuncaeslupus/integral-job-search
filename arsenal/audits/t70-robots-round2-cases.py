"""Spec-derived adversarial cases for T70 robots.txt matching, round 2.

Written BEFORE opening src/integral/robots.py or tests/test_robots.py. Expected
verdicts are derived from RFC 9309 text alone (or, where the live text was
unreachable through the session's egress proxy, from documented recollection of
it), never from running the implementation. See t70-robots-round2.md for the
execution results and any post-hoc corrections (recorded as separate commits).

NOTE ON SOURCE TEXT: https://www.rfc-editor.org/rfc/rfc9309.txt and
https://www.ietf.org/rfc/rfc9309.txt both returned a 403 from this session's
egress proxy (organization policy denial, not a transient failure -- see
/root/.ccr/README.md). Citations below are from training-data knowledge of
RFC 9309, not a freshly-fetched copy, and should be spot-checked against the
actual RFC text by the next reader before being trusted blindly.

Each case is a complete, independent scenario:
  name              -- short unique slug
  robots_txt        -- full robots.txt document text (None for §2.3 fetch-status
                        cases, which test status-code handling rather than
                        document parsing)
  agent             -- the crawler's own product token / user-agent string
  url               -- the full request URL being checked
  expected_allowed  -- bool: True if the spec requires the fetch to be permitted
  citation          -- RFC 9309 section + the reasoning that decides the verdict
  http_status       -- optional int, only set for §2.3 fetch-status cases
"""

CASES = [
    {
        "name": "percent-encoded-unreserved-rule-vs-literal-request",
        "robots_txt": "User-agent: *\nDisallow: /%7Euser\n",
        "agent": "TestBot/1.0",
        "url": "https://example.com/~user",
        "expected_allowed": False,
        "citation": (
            "RFC 9309 SS2.2.2, incorporating RFC 3986 SS2.3 -- percent-encoded octets "
            "for unreserved characters (which includes '~') must be normalized to the "
            "unencoded character before path comparison, so '%7E' in a rule matches a "
            "literal '~' in the request path."
        ),
    },
    {
        "name": "literal-rule-vs-percent-encoded-unreserved-request",
        "robots_txt": "User-agent: *\nDisallow: /~user\n",
        "agent": "TestBot/1.0",
        "url": "https://example.com/%7Euser",
        "expected_allowed": False,
        "citation": (
            "RFC 9309 SS2.2.2 / RFC 3986 SS2.3 -- normalization is symmetric: an "
            "unencoded '~' in the rule must still match a request path that spells "
            "the same character as '%7E'."
        ),
    },
    {
        "name": "percent-encoded-reserved-slash-exact-match",
        "robots_txt": "User-agent: *\nDisallow: /a%2Fb\n",
        "agent": "TestBot/1.0",
        "url": "https://example.com/a%2Fb",
        "expected_allowed": False,
        "citation": (
            "RFC 9309 SS2.2.2 / RFC 3986 SS2.3 -- '/' is a reserved character, not "
            "unreserved, so '%2F' is never decode-normalized. An identically-encoded "
            "rule and request path are the same octet sequence and must match."
        ),
    },
    {
        "name": "percent-encoded-reserved-slash-must-not-equal-literal-slash",
        "robots_txt": "User-agent: *\nDisallow: /a%2Fb\n",
        "agent": "TestBot/1.0",
        "url": "https://example.com/a/b",
        "expected_allowed": True,
        "citation": (
            "RFC 9309 SS2.2.2 / RFC 3986 SS2.3 -- because '/' is reserved, '%2F' must "
            "NOT be treated as equivalent to an unencoded '/'. 'Disallow: /a%2Fb' and "
            "the request path '/a/b' denote different octet sequences, so they do "
            "not match. A matcher that folds %2F into / here fails open in reverse "
            "(over-blocks) on the companion case above and under-blocks nothing here, "
            "but the two cases together catch either direction of that bug."
        ),
    },
    {
        "name": "percent-encoding-hex-digit-case-insensitivity",
        "robots_txt": "User-agent: *\nDisallow: /caf%C3%A9\n",
        "agent": "TestBot/1.0",
        "url": "https://example.com/caf%c3%a9",
        "expected_allowed": False,
        "citation": (
            "RFC 9309 SS2.2.2, incorporating RFC 3986 SS2.1 -- the hex digits of a "
            "percent-encoded triplet are case-insensitive; '%C3%A9' and '%c3%a9' "
            "denote the same two octets and must compare equal."
        ),
    },
    {
        "name": "percent-25-literal-percent-sign-exact-match",
        "robots_txt": "User-agent: *\nDisallow: /100%25\n",
        "agent": "TestBot/1.0",
        "url": "https://example.com/100%25",
        "expected_allowed": False,
        "citation": (
            "RFC 9309 SS2.2.2 -- '%' is not itself an unreserved character, so a "
            "literal '%' octet in a path is represented as '%25'. An identically "
            "written rule and request path match."
        ),
    },
    {
        "name": "double-encoded-percent-sign-does-not-match-single-encoded",
        "robots_txt": "User-agent: *\nDisallow: /100%25\n",
        "agent": "TestBot/1.0",
        "url": "https://example.com/100%2525",
        "expected_allowed": True,
        "citation": (
            "RFC 9309 SS2.2.2 -- percent-decoding is applied one level. '%2525' "
            "decodes to the literal string '%25' (a '%' followed by '2' and '5'), a "
            "different, longer octet sequence than the single encoded-percent octet "
            "the rule denotes; they are different resources and must not match."
        ),
    },
    {
        "name": "percent-encoded-unreserved-letters-spelling-a-word",
        "robots_txt": "User-agent: *\nDisallow: /%41dmin\n",
        "agent": "TestBot/1.0",
        "url": "https://example.com/Admin",
        "expected_allowed": False,
        "citation": (
            "RFC 9309 SS2.2.2 / RFC 3986 SS2.3 -- ALPHA characters are unreserved, so "
            "'%41' (encoding 'A') normalizes to 'A', making the rule equivalent to "
            "'Disallow: /Admin'."
        ),
    },
    {
        "name": "empty-disallow-value-permits-everything",
        "robots_txt": "User-agent: *\nDisallow:\n",
        "agent": "TestBot/1.0",
        "url": "https://example.com/anything/at/all",
        "expected_allowed": True,
        "citation": (
            "RFC 9309 SS2.2.2 -- an empty value on a Disallow line imposes no "
            "restriction at all; a group whose only rule is an empty Disallow "
            "permits every path."
        ),
    },
    {
        "name": "empty-allow-value-does-not-suppress-real-disallow",
        "robots_txt": "User-agent: *\nAllow:\nDisallow: /private\n",
        "agent": "TestBot/1.0",
        "url": "https://example.com/private",
        "expected_allowed": False,
        "citation": (
            "RFC 9309 SS2.2.2 -- an empty Allow value matches a zero-length path "
            "and therefore has no specificity; it must not out-rank or otherwise "
            "suppress a non-empty Disallow rule that actually matches the request "
            "path."
        ),
    },
    {
        "name": "literal-question-mark-blocks-matching-query-string",
        "robots_txt": "User-agent: *\nDisallow: /path?\n",
        "agent": "TestBot/1.0",
        "url": "https://example.com/path?query=1",
        "expected_allowed": False,
        "citation": (
            "RFC 9309 SS2.2.2 / SS2.2.3 -- outside of the '*' and '$' special "
            "characters, a rule's octets (including '?') are matched literally as a "
            "prefix of the path-plus-query string; '/path?' is a prefix of "
            "'/path?query=1'."
        ),
    },
    {
        "name": "literal-question-mark-does-not-block-bare-path",
        "robots_txt": "User-agent: *\nDisallow: /path?\n",
        "agent": "TestBot/1.0",
        "url": "https://example.com/path",
        "expected_allowed": True,
        "citation": (
            "RFC 9309 SS2.2.2 -- '/path?' is not a prefix of '/path' because the "
            "literal '?' octet the rule requires is absent from the request; the "
            "rule does not apply."
        ),
    },
    {
        "name": "wildcard-then-literal-question-mark-blocks-any-query",
        "robots_txt": "User-agent: *\nDisallow: /*?\n",
        "agent": "TestBot/1.0",
        "url": "https://example.com/page?x=1",
        "expected_allowed": False,
        "citation": (
            "RFC 9309 SS2.2.3 -- '*' matches zero or more of any character, so "
            "'/*?' matches any path that contains a literal '?' anywhere after the "
            "root, including '/page?x=1'."
        ),
    },
    {
        "name": "wildcard-then-literal-question-mark-does-not-block-no-query",
        "robots_txt": "User-agent: *\nDisallow: /*?\n",
        "agent": "TestBot/1.0",
        "url": "https://example.com/page",
        "expected_allowed": True,
        "citation": (
            "RFC 9309 SS2.2.3 -- '/*?' requires a literal '?' to occur somewhere in "
            "the path; a request with no '?' cannot satisfy the pattern no matter "
            "how '*' expands."
        ),
    },
    {
        "name": "dollar-anchor-exact-match",
        "robots_txt": "User-agent: *\nDisallow: /path$\n",
        "agent": "TestBot/1.0",
        "url": "https://example.com/path",
        "expected_allowed": False,
        "citation": (
            "RFC 9309 SS2.2.3 -- '$' designates the end of the match pattern; "
            "'/path$' matches only a request path that is exactly '/path'."
        ),
    },
    {
        "name": "dollar-anchor-rejects-longer-suffix",
        "robots_txt": "User-agent: *\nDisallow: /path$\n",
        "agent": "TestBot/1.0",
        "url": "https://example.com/pathxyz",
        "expected_allowed": True,
        "citation": (
            "RFC 9309 SS2.2.3 -- because '$' anchors the pattern to end exactly "
            "after 'path', a request path with trailing characters ('pathxyz') does "
            "not match."
        ),
    },
    {
        "name": "dollar-anchor-rejects-trailing-slash",
        "robots_txt": "User-agent: *\nDisallow: /path$\n",
        "agent": "TestBot/1.0",
        "url": "https://example.com/path/",
        "expected_allowed": True,
        "citation": (
            "RFC 9309 SS2.2.3 -- '$' requires the string to end exactly at that "
            "point; '/path/' has an extra '/' octet after 'path' and therefore does "
            "not satisfy '/path$'."
        ),
    },
    {
        "name": "wildcard-basic-suffix-match",
        "robots_txt": "User-agent: *\nDisallow: /*.php\n",
        "agent": "TestBot/1.0",
        "url": "https://example.com/index.php",
        "expected_allowed": False,
        "citation": (
            "RFC 9309 SS2.2.3 -- '*' matches any sequence of characters, including "
            "none; '/*.php' matches any path that ends in the literal suffix '.php' "
            "reached after zero or more characters, including '/index.php'."
        ),
    },
    {
        "name": "wildcard-dollar-anchor-excludes-query-suffix",
        "robots_txt": "User-agent: *\nDisallow: /*.php$\n",
        "agent": "TestBot/1.0",
        "url": "https://example.com/index.php?x=1",
        "expected_allowed": True,
        "citation": (
            "RFC 9309 SS2.2.3 -- '$' anchors the end of the pattern immediately "
            "after '.php'; the request continues with '?x=1' after '.php', so the "
            "string does not end where the pattern requires."
        ),
    },
    {
        "name": "consecutive-wildcards-collapse-to-one",
        "robots_txt": "User-agent: *\nDisallow: /a**b\n",
        "agent": "TestBot/1.0",
        "url": "https://example.com/axyzb",
        "expected_allowed": False,
        "citation": (
            "RFC 9309 SS2.2.3 -- '*' matches zero or more characters; two adjacent "
            "'*' tokens are semantically equivalent to one and together still match "
            "any run of characters between 'a' and 'b', including 'xyz'."
        ),
    },
    {
        "name": "trailing-wildcard-before-dollar-matches-zero-expansion",
        "robots_txt": "User-agent: *\nDisallow: /a*$\n",
        "agent": "TestBot/1.0",
        "url": "https://example.com/a",
        "expected_allowed": False,
        "citation": (
            "RFC 9309 SS2.2.3 -- '*' may expand to zero characters, so '/a*$' "
            "matches a path that is exactly '/a' as well as any longer path "
            "beginning with '/a'."
        ),
    },
    {
        "name": "agent-token-is-substring-of-longer-crawler-token",
        "robots_txt": "User-agent: Bot\nDisallow: /private\n",
        "agent": "Botly/2.0",
        "url": "https://example.com/private",
        "expected_allowed": False,
        "citation": (
            "RFC 9309 SS2.2.1 -- a crawler matches a User-agent line if the line's "
            "product token is a case-insensitive substring of the crawler's own "
            "product token; 'Bot' is a substring of 'Botly', so the group applies."
        ),
    },
    {
        "name": "most-specific-agent-group-wins-over-shorter-token",
        "robots_txt": (
            "User-agent: Bot\nDisallow:\n\nUser-agent: Botly\nDisallow: /private\n"
        ),
        "agent": "Botly/2.0",
        "url": "https://example.com/private",
        "expected_allowed": False,
        "citation": (
            "RFC 9309 SS2.2.1 -- when a crawler token matches more than one group's "
            "product token, the crawler MUST use the most specific (longest) "
            "matching token. 'Botly' is more specific than 'Bot' for the crawler "
            "token 'Botly/2.0', so the Botly group's Disallow applies even though "
            "the Bot group alone would permit everything."
        ),
    },
    {
        "name": "agent-token-longer-than-crawler-token-does-not-match",
        "robots_txt": (
            "User-agent: Botly\nDisallow:\n\nUser-agent: *\nDisallow: /private\n"
        ),
        "agent": "Bot/1.0",
        "url": "https://example.com/private",
        "expected_allowed": False,
        "citation": (
            "RFC 9309 SS2.2.1 -- the match direction is one-way: the rule's product "
            "token must be a substring of the crawler's token, not the reverse. "
            "'Botly' is not a substring of the crawler token 'Bot', so that group "
            "does not apply and the crawler falls back to the wildcard '*' group."
        ),
    },
    {
        "name": "agent-match-is-case-insensitive",
        "robots_txt": "User-agent: GoogleBot\nDisallow: /private\n",
        "agent": "googlebot/2.1",
        "url": "https://example.com/private",
        "expected_allowed": False,
        "citation": (
            "RFC 9309 SS2.2.1 -- matching of the User-agent product token against "
            "the crawler's own token MUST be case-insensitive; 'GoogleBot' matches "
            "the crawler's self-identification as 'googlebot'."
        ),
    },
    {
        "name": "path-match-is-case-sensitive",
        "robots_txt": "User-agent: *\nDisallow: /Secret\n",
        "agent": "TestBot/1.0",
        "url": "https://example.com/secret",
        "expected_allowed": True,
        "citation": (
            "RFC 9309 SS2.2.2 -- unlike the User-agent match, Allow/Disallow path "
            "values are compared octet-for-octet, case-sensitively; '/Secret' does "
            "not match the differently-cased path '/secret'."
        ),
    },
    {
        "name": "shared-group-applies-to-every-listed-agent-token",
        "robots_txt": "User-agent: A\nUser-agent: B\nDisallow: /secret\n",
        "agent": "B/1.0",
        "url": "https://example.com/secret",
        "expected_allowed": False,
        "citation": (
            "RFC 9309 SS2.2.1 -- consecutive User-agent lines with no intervening "
            "rule lines form a single group whose rules bind every listed token; a "
            "crawler matching the second-listed token 'B' is bound exactly as one "
            "matching 'A' would be."
        ),
    },
    {
        "name": "group-with-no-rules-permits-everything",
        "robots_txt": "User-agent: *\n",
        "agent": "TestBot/1.0",
        "url": "https://example.com/anything",
        "expected_allowed": True,
        "citation": (
            "RFC 9309 SS2.2.2 -- a group that declares no Allow or Disallow lines "
            "contains no restrictions, so every path is permitted for a crawler "
            "matching it."
        ),
    },
    {
        "name": "equal-length-tie-allow-wins-subpath",
        "robots_txt": "User-agent: *\nAllow: /page\nDisallow: /page\n",
        "agent": "TestBot/1.0",
        "url": "https://example.com/page",
        "expected_allowed": True,
        "citation": (
            "RFC 9309 SS5.1 -- when an Allow and a Disallow rule match a path with "
            "equal specificity (equal matched octet length), the Allow rule takes "
            "precedence."
        ),
    },
    {
        "name": "equal-length-tie-allow-wins-root",
        "robots_txt": "User-agent: *\nAllow: /\nDisallow: /\n",
        "agent": "TestBot/1.0",
        "url": "https://example.com/",
        "expected_allowed": True,
        "citation": (
            "RFC 9309 SS5.1 -- the Allow-wins tie-break applies regardless of path "
            "depth; equal-length root rules still resolve to Allow."
        ),
    },
    {
        "name": "specificity-must-be-computed-on-decoded-octets-not-raw-text",
        "robots_txt": "User-agent: *\nAllow: /%61/%62\nDisallow: /a/bcdef\n",
        "agent": "TestBot/1.0",
        "url": "https://example.com/a/bcdef",
        "expected_allowed": False,
        "citation": (
            "RFC 9309 SS5.1 combined with SS2.2.2 -- specificity is the length of the "
            "matched octet sequence AFTER percent-decoding unreserved characters, "
            "not the raw rule-line character count. Decoded, 'Allow: /%61/%62' is "
            "'/a/b' (4 octets) and 'Disallow: /a/bcdef' is 8 octets, so Disallow is "
            "strictly more specific and wins -- even though the two raw rule lines "
            "happen to be the same length (8 characters each), which would "
            "wrongly read as a tie (and therefore wrongly resolve to Allow, "
            "fail-open) under a matcher that compares raw text length instead of "
            "decoded octet length."
        ),
    },
    {
        "name": "duplicate-agent-groups-combine-first-groups-rule-survives",
        "robots_txt": "User-agent: Bot\nDisallow: /a\n\nUser-agent: Bot\nDisallow: /b\n",
        "agent": "Bot/1.0",
        "url": "https://example.com/a",
        "expected_allowed": False,
        "citation": (
            "RFC 9309 SS2.2.1 -- when the same product token reappears in more than "
            "one group, the crawler MUST combine the rules of all such groups; the "
            "first group's Disallow must still apply even though a later group for "
            "the same token exists."
        ),
    },
    {
        "name": "duplicate-agent-groups-combine-second-groups-rule-survives",
        "robots_txt": "User-agent: Bot\nDisallow: /a\n\nUser-agent: Bot\nDisallow: /b\n",
        "agent": "Bot/1.0",
        "url": "https://example.com/b",
        "expected_allowed": False,
        "citation": (
            "RFC 9309 SS2.2.1 -- combining duplicate groups means the second "
            "group's Disallow must also apply; a matcher that keeps only the first "
            "group it encounters for a token would incorrectly allow this path."
        ),
    },
    {
        "name": "http-404-treated-as-unavailable-full-allow",
        "robots_txt": None,
        "agent": "TestBot/1.0",
        "url": "https://example.com/anything",
        "expected_allowed": True,
        "citation": (
            "RFC 9309 SS2.3 -- a 4xx status when fetching robots.txt means the "
            "resource does not exist ('unavailable'); the crawler MUST proceed as "
            "if no robots.txt restrictions exist at all, i.e. full access is "
            "allowed."
        ),
        "http_status": 404,
    },
    {
        "name": "http-500-treated-as-unreachable-full-disallow",
        "robots_txt": None,
        "agent": "TestBot/1.0",
        "url": "https://example.com/anything",
        "expected_allowed": False,
        "citation": (
            "RFC 9309 SS2.3 -- a 5xx (server error) status, or any failure to reach "
            "the server at all, is 'unreachable'; absent a usable cached copy the "
            "crawler MUST assume complete disallow. A matcher that treats any fetch "
            "failure the same as a 404 (full allow) fails open here."
        ),
        "http_status": 500,
    },
]
