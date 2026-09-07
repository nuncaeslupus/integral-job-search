---
id: t-2d2ae9fc
title: "T148: A document edit is verified by the edit succeeding, not by the document"
priority: 5
deps: [t-e417aee2]
tags: [docs]
workspace: CANDIDATE
issue: 393
---

## Acceptance gate

```gate
document_edit_defects == 0
evidence: status/evidence/T148.json
key: document_edit_defects
```

```bash
uv run --extra dev pytest tests/test_document_edit.py -q
uv run --extra dev python -m integral.document_edit
```

Two silent corruptions in one letter, in one session, neither of which failed
anything.

**1. Paragraphs edited by index.** An earlier edit had removed a paragraph, so
`text[4]` and `text[8]` no longer meant what the caller believed. The edit
overwrote the leap-of-faith paragraph and the honest-gaps paragraph with
duplicates of two others. The write succeeded. The render succeeded. The PDF
came out with the right number of paragraphs and two of them were wrong.

**2. A filter that dropped a block.** `if b.get("text") is not None` silently
removed the letter's `to` block — the addressee and the link to the job. The
letter was addressed to nobody.

Both were found by running `pdftotext` and reading, which is not a check.
`integral.ats.check_document` passed both times, correctly: the text layer was
intact and parseable. It was simply the wrong text. An ATS contract asserts the
document can be read; it says nothing about whether it says what it should.

**The contract.** An edit names the blocks it changes, and **every block it does
not name comes out byte-identical in the rendered text layer**. Block count is
preserved unless the edit says it changes. That is the document-level analogue
of what `tools/verified_gate.sh` enforces for code, and for the same reason: the
thing that matters is the artefact that ships, not that the operation returned
success. A working tree is not what a reviewer merges, and an edited JSON is not
what an employer reads.

Depends on T142, which is where the block vocabulary lives.

The measurement replays both defects against the generator and requires each to
be refused, plus one legitimate edit that must be allowed — a gate that refuses
every edit would score zero defects and be useless.
