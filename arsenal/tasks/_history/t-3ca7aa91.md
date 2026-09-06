---
id: t-3ca7aa91
title: "T129: the set of supported languages is declared eight times, and only one pair is checked"
priority: 5
deps: []
requires: []
tags: [BACKEND]
workspace: BACKEND
max-attempts: 3
status: merged
---

## Context

#358 asks for a fourth language. Before choosing one, this measures what
adding one actually touches — by adding `pt` to the obvious declaration and
reading what happened.

`Language = Literal["en", "es", "ca"]` is not the definition of the language
set. It is one of **eight** independent restatements of it:

| site | form |
|---|---|
| `corpus.py:19` | `LANGUAGES = ("es", "en", "ca")` |
| `salary_recovery.py:143` | `LANGUAGES = ("es", "ca", "en")` — a second tuple, different order |
| `dimensions.py:45` | `Language = Literal["en", "es", "ca"]` |
| `identity.py:78` | `Language = Literal["en", "es", "ca"]` — a second Literal |
| `dimensions.py:131-133` | `LocalisedText` fields `en` / `es` / `ca` |
| `corpus_scope.py:118` | `TARGET_MIX = {"es": 60, "en": 25, "ca": 15}` |
| `interview.py:535` | `for language in ("en", "es", "ca")` |
| `strings/catalogue.json:22` | `"languages": ["en", "es", "ca"]` |

**One pair is asserted equal** — `test_dimension_model.py:243` checks
`set(get_args(Language)) == set(LANGUAGES)`, covering rows 1 and 3. The other
six agree today by coincidence.

Two of them fail *silently* rather than loudly:

- `identity.Language` validates `Identity.language`, the field in every
  candidate's `identity.json`. `identity.py:490` separately checks membership in
  `corpus.LANGUAGES`. Widening the tuple leaves the model refusing what the
  function accepts — two rules, same file, nothing comparing them.
- `LocalisedText.get()` checks `language not in LANGUAGES` and then does
  `getattr(self, language)`. Measured: with `pt` in `LANGUAGES`, `make evidence`
  dies on `AttributeError: 'LocalisedText' object has no attribute 'pt'` — the
  guard reads one declaration and the lookup reads another.

This is the repo's recurring shape (T122, T123, T127): a check that passes for a
mechanism other than the one it names. Here it is a check that covers 2 of 8
sites while reading as though it covers the concept.

Widening the set is not this task. Making the eight sites checkable is.

## Acceptance gate
```bash
uv run python -m integral.language_set --check
```
