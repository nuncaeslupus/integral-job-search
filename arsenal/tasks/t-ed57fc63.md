---
id: t-ed57fc63
title: "T316: T241 follow-ups: page-shell scan gaps left open by #729"
priority: 5
requires: [human:gate]
---

Imported from issue #732

Optional findings left open when #729 (T241, closes #642) merged. All fail-open; the CSP backstops the fetch cases.

- **R1** — an `.html` name in one function written from another (`_target()` returning `d/'board.html'`, called by `save()`) is not seen (mutant M13 survived). The blunt fix also flags 6 modules that read `.html` fixtures; needs a sharper rule.
- **R2** — CSS escape followed by CRLF (`\75\r\nrl(`) is not decoded the browser's way. Normalise `\r\n`, `\r`, `\f` → `\n` before decoding.
- **R3** — duplicate `http-equiv` (`<meta http-equiv=refresh http-equiv=x …>`): the check reads the last value, browsers the first. Not covered by CSP (navigation, not fetch).
- **O4** — `tools/blind_ranking_page.py` and `tools/labelling_page.py` write their own `<!doctype html>` pages outside `src/integral` and outside `page()`. `os.fdopen`, `writelines` and `print(file=)` are not recognised as writes.
- **O2** — SVG `href`/`xlink:href` outside `<a>`, `ping`, `background`, `srcdoc`, `image-set()`, entities in foreign `<style>`: left to the CSP (documented).
- **O6** — the print-path test shows the tokens are declared, not that the print CSS uses them.
- Exemption limit: a bypass inside an already-exempt scope is caught only if it changes that exemption's count or kind.

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
