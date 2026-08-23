## 2026-05-26

SKILL.md is not aligned with the guidelines:
  must   line 55   Reference `references/template.md` cited as "Output format: see ..." without a "load when ..." trigger descriptor  (R-LAZYLOAD-1)
  must   line 55   Same citation lacks the required one-line "load this when…" inline descriptor  (R-SR-5)
  should line 8    SKILL.md body contains no fenced code block — mechanical proxy for "concrete examples" fails  (R-XPOLL-6)

references/template.md is not aligned with the guidelines (dismissed):
  must   line 1    Output template skeleton flagged as belonging in `assets/`  (R-SR-3)
                   dismissed: R-SR-3 targets script-consumed output assets (fonts, schemas);
                   workflow templates that Claude loads into context to mirror a structure are
                   correctly in `references/`. The other four workflow skills' templates were
                   not flagged for the same shape — agent over-interpretation.

(other files in this skill are aligned)
