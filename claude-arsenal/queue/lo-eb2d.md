# T31: Detect note-key rebinding, and a stale spec reader

## Acceptance gate

```gate
reader_note_rebindings == 0
evidence: status/evidence/T31.json
key: reader_note_rebindings
```

```bash
uv run python -m jobsearch.reader_notes
```

## What this is

Two failure modes in the review loop, both silent, both hit in one revision.

**1. Renumbering re-binds notes to the wrong sections.** `create_reader.py` keys
a reviewer's note by section number (`s-spec-10`). Inserting a section renumbers
every section after it, so the seed file re-attaches those notes to whatever now
holds the old number. In PR #16 a new §8 pushed "Open, and deliberately so" from
§10 to §11, and the owner's closing note re-attached to "What S2 inherits" — a
section they had never commented on. One note moved this time. A section
inserted higher up moves many, and nothing detects it: the reader simply shows a
reviewer someone else's words under a heading they did not write them for.

The fix is to make the rebinding visible: record the section *title* alongside
the key in `notes.json`, and report every note whose key now resolves to a
different title than the one it was written against. Re-anchoring stays a human
decision — the note follows the section it was written on, which is not always
the section that now answers it — but it can no longer happen silently.

**2. ~~The committed reader can be stale.~~** **Done in S2** (#17): `make reader`
regenerates both readers, and `test_regenerating_the_reader_produces_no_diff`
fails when a Markdown edit has not been regenerated. Verified by editing the
source and watching it fail. Left here for the record; nothing remains to do.

## Why it matters more than it looks

Both defects damage the same thing: the artefact the owner reviews. A stale
reader means review comments land on text that has changed; a rebound note means
their words are attributed to a section they never read. Neither shows up in any
existing gate, and both were found by a reviewer rather than a check.

## Tests

`test_a_note_whose_section_title_changed_is_reported`;
`test_a_note_on_an_unchanged_section_is_not_reported` — a warning on every note
is the same as no warning.

## Location

Service: **ONTOLOGY** · Size: S · Depends: — (scope reduced after S2 landed the staleness half)

Source: PR #16 review thread · `docs/spec-v2/notes.json` ·
`.claude/skills/specify/scripts/create_reader.py`
