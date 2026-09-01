---
id: t-afa28a4a
title: "T102: Does a robots product token match as a prefix of a longer crawler token?"
priority: 5
tags: [ROBOTS]
workspace: BACKEND
---

Imported from issue #236 — case 22 of the round-2 independent T70 audit, the one
case of 33 deliberately **not** committed as a fixture.

```
User-agent: Bot
Disallow: /private
```

Crawler product token `Botly`, request `https://example.com/private`.
`_select_rules` compares product tokens by case-insensitive **equality**, so
`"bot" != "botly"`, no group matches, no rule applies, and the fetch is
**permitted**.

If RFC 9309 requires matching in that direction, this is fail-open — a site writing
one `googlebot` rule intending to govern `Googlebot-Image` and `Googlebot-News`
would govern none of them.

**The answer may not be obtained by running the code.** That is the circularity
`CLAUDE.md` describes: recording the implementation's own verdict as the expected
one is what let T70 take ten defects across five review rounds, eight of them
introduced while fixing the previous one. Read RFC 9309 §2.2.1 and derive the
verdict from its text, before opening `robots.py`.

Whichever way it resolves, **the case becomes a fixture**. An audit case answered in
a comment and waved through leaves the code exactly as unprotected as it was, and
the next regression reopens the same hole with nothing to catch it.

Note which direction is being asked. The token in the *file* is the short one and
the crawler's is the long one; the reverse — file says `Botly`, crawler is `Bot` —
is a different question and gets its own fixture with its own citation.

## Acceptance gate

```bash
uv run --extra dev pytest tests/test_robots.py -q -k "product_token"
uv run --extra dev python -m integral.robots
```

- `test_a_file_token_shorter_than_the_crawler_token_matches_per_rfc_9309`
  (or `..._does_not_match_...` — the name records the verdict the spec gave)
- `test_the_reverse_direction_is_asserted_separately`
- `test_the_case_22_fixture_cites_the_section_it_was_derived_from`
