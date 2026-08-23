## 2026-05-26

SKILL.md is aligned with the guidelines.

(dismissed) SKILL.md:3 — R-MEM-7 — first walk flagged the description's
`~/.claude/projects/` and `~/.claude/proposed-skill-improvements/` mentions as
hard-coded home paths. Dismissed: R-MEM-7 is a purely mechanical regex rule
("outside fenced code blocks → fail"); the validator that owns it deliberately
scopes the scan to the SKILL.md body and references, not the description. The
description is a retrieval key, not loaded/executed context, so a path mention
there is descriptive, not a portability hazard. `make validate` confirms
session-end clean. No edit.

(dismissed) SKILL.md:3 — R-FM-3 — first walk estimated the description at
>1024 chars. Dismissed: actual length is 999 chars; validator confirms within
budget.

(dismissed) references/auto-fire-setup.md, references/retrospective-rubric.md —
R-MEM-7 — the `~/.claude/...` paths there sit inside inline-backtick spans;
`validate.py` strips inline code before applying the home-path regex, so they
are documentation, not hard-coded instructions. Clean.

(dismissed) references/auto-fire-setup.md — R-BODY-9 — second-person "you"
prose. Dismissed: §3 R-BODY-9 governs the SKILL.md body voice; the validator's
second-person scan does not extend to reference files, which carry their own
Q-PROSE expectations (not a MUST).

(should, not fixed) scripts/create_handoff.py — `--output` deviates from the
canonical `--output-dir` (arg-canon, should). Left for the PR #2 status/
rewrite, which revisits handoff routing.
