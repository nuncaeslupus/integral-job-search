---
id: t-ddbc55ae
title: "review: PDF and CV-import paths are skipped in CI"
priority: 5
requires: [human:gate]
---

Imported from issue #933

**Severity:** medium · **Confidence:** medium · **Category:** tests

**Where:** `Makefile:47, pyproject.toml:21-37, .github/workflows/ci.yml:70-117`

### Finding
`make test` installs only the `dev` and `collect` extras, so the WeasyPrint PDF contracts (page budget, text layer) and the pypdf importer tests skip on CI; the PDF is the artefact actually sent to an employer. CI also runs a single OS and Python (ubuntu, 3.12) while README claims macOS/Windows state directories.

### Evidence
Makefile test recipe is `uv run --extra dev --extra collect pytest -n auto`; pyproject comments state the PDF contracts 'skip without it'; 67 skipif/platform references in tests/. Did not run the suite to count skips.

### Suggested direction
Add a CI job with `--extra pdf --extra cv` (apt install pango) and fail if the PDF tests are skipped there; add macOS/Windows smoke jobs or narrow the claim.

_From the full repo review of 2026-11-11 (finding #14). Not fixed yet; verify before acting._

## Acceptance gate

<!-- This task came from an issue, so its "gate" is prose. Write a real check
     below, then DELETE the `requires: [human:gate]` line in the front matter.
     Until that line is gone the selector will not offer this task, which is
     deliberate: a prose gate runs nothing, and a gate that runs nothing passes
     everything. -->

```bash
# arsenal:gate-placeholder — replace with the real check; it may land in this task's own PR
false
```
