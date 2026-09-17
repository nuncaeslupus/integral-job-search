---
id: t-b2734bcc
title: "T191: Promote the docgen/weasyprint HTML+PDF pipeline out of one candidate's one offer directory"
priority: 5
tags: [step-11-application]
---

Candidate note (2026-09-17, step `application`): "Los generadores de HTML y PDF
deberían servir para todos si son lo bastante genéricos" — the HTML/PDF generators
should serve every candidate if they're generic enough.

They already are. `cv/generated/<grafana offer id>/v13/docgen.py` renders a portable
JSON block schema (`header`/`summary`/`section`/`job`/`project`/`bullets`/`grid`/
`board`/`letter`/`to`/`text`/`sign`) to HTML — its own module docstring says "nothing
here is candidate-specific" — `style.css` in the same directory is parameterised via
`%%PAGESIZE%%`/`%%MARGIN_TB%%`/`%%MARGIN_LR%%`/`%%ACCENT%%`, and `build_docs.sh`
derives page size from country and drives both files plus `weasyprint` to produce
PDFs from `cv.json`/`letter.json`. None of the three references Grafana or any
candidate string. The problem is not genericity, it is location: this only lives
inside one candidate's one already-sent offer version directory, so nothing else
in the repo can reach it.

The gap this created, concretely: this same session hand-authored HTML for a
different candidate's different offer (Bolt.new, `cv.html`/`letter.html`, v1-v3)
token by token instead of filling the JSON schema and running the existing
renderer — the exact "spend tokens where a script would do" pattern CLAUDE.md's
own Automation section and a separate 2026-09-17 candidate note both name directly
("Lo de usar scripts para todo lo que se pueda automatizar en vez de usar tokens,
también es importante, eso lo intento en todos los proyectos y skills").

Ask: promote `docgen.py` and `style.css` into shared tooling reachable by any
candidate/offer (e.g. under `src/integral/docgen/` or
`.claude/skills/step-11-application/scripts/` — implementer's call, whichever
fits the existing module layout), and generalise `build_docs.sh` into a wrapper
that takes a candidate handle + offer id + version directory instead of assuming
the one hardcoded path it has today. **Do not move or edit anything inside the
already-sent Grafana v13 directory itself** — that package is immutable once
sent; copy the two generic files out, point step-11-application's own tooling at
the shared copy, and leave the original in place. First real exercise of the
promoted tool: render Bolt.new's existing `cv.json`/`letter.json` (or fill them
from its hand-written HTML if they don't yet exist) into a PDF the same way
Grafana's v13 was.

This task cannot be exercised against fabricated data: proving the promoted renderer
works means pointing it at a real candidate's `cv/master.json` + `profile/stories.jsonl`,
not placeholder content — and that data lives outside this repo, under
`~/.integral-job-search/profiles/<handle>/`. Reading it requires an identified session
with the profile's own owner present, e.g. a test-mode session where they point the
assistant at their own data with a `[[...]]` note (`.claude/skills/test-mode/SKILL.md`).
If this task is picked up with nobody present to supply that pointer, say so in the task
file and hold rather than fabricate or guess profile data — and never read a profile
without its own owner's go-ahead.

## Acceptance gate

<!-- Replace this with a fenced bash block. A gate that is only prose runs
     nothing, and a gate that runs nothing passes everything — `task_select.py`
     reports gate: false for a task with no block, so an unenforced gate is
     visible rather than quietly inert. -->

```bash
# arsenal:gate-placeholder — replace with the real check; it may land in this task's own PR
# e.g. bash tests/docgen_shared_smoke_test.sh
false
```
