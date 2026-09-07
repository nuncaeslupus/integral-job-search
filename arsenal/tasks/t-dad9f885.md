---
id: t-dad9f885
title: "T145: Nothing captures what the candidate tells us unless a step happens to ask"
priority: 1
tags: [PROFILE]
workspace: PROFILE
issue: 390
---

## Acceptance gate

```gate
capture_misses == 0
evidence: status/evidence/T145.json
key: capture_misses
```

```bash
uv run --extra dev pytest tests/test_capture_sweep.py -q
uv run --extra dev python -m integral.capture_sweep
```

The candidate, at the end of the first complete run:

> "todo lo que dice el candidato es oro […] aquí he hecho el trabajo más yo que
> tú. Tú deberías buscar en el usuario este tipo de información: cómo trabajas,
> qué clase de proyectos haces, a qué dedicas el tiempo libre […] Cualquier
> aportación que haga, ya sea en conversación o modificando él mismo los
> ficheros, debe ser añadida a su perfil."

**Measured on that run.** When the CV and letter were finished and sent, the
profile held **62 evidence rows spanning one dimension**. A backfill of what
that same session had already said produced **34 more rows spanning 26
dimensions**, plus one retraction of a claim that had reached a letter and was
false. None of it was new information. All of it had been said out loud, or
written by the candidate himself into the CV, hours earlier.

Two distinct failures with one symptom.

**1. Capture is opt-in per step.** `profile_capture.capture` is reached only
through the step drivers — intake, constraints, history, traits, feedback. The
`application` step, the whole document-generation stretch where a candidate
talks most freely about how they work and why, has no writer attached at all.
The richest conversation in the run is the one nothing was listening to.
Capture has to be a property of the session, not of five steps.

**2. Nothing elicits.** Even where capture existed, nobody asked. The candidate
volunteered Honeycomb, the saxophone, scripts-inside-skills, and the leap of
faith about no longer reading his own PRs — every one of them a thing a
recruiter weighs, every one of them something this tool exists to ask for. The
questions he named as valid and never got:

> cómo trabajas, qué clase de proyectos haces, a qué dedicas el tiempo libre
> (tenga o no relación con tu trabajo), qué es importante para ti cuando estás
> trabajando, qué intentas siempre mejorar, cómo afrontas los retos que te
> encuentras y cuáles han sido esos retos, cómo reaccionas a ciertas normas

**What "always" has to mean.** The candidate asked for *"una norma, un hook o
algún tipo de técnica"*. A rule in prose is exactly what already existed —
`profile_capture`'s own docstring says the profile is built from what the
candidate says — and prose is what failed. So the contract is behavioural:
over a fixture of turns taken from a real transcript, each carrying a
contribution the profile should hold, the detector names it. `capture_misses`
counts the ones it does not.

**Announce, do not ask.** A capture is reported in one short line — *"Añado lo
de tus clases de pintura a tu perfil"* — and never put to the candidate as a
question. Asking permission per contribution turns a background property into
an interruption, and it is unnecessary: `integral.retraction` already makes
removal cheap and immediate, which is the guarantee that makes silent-by-
default capture fair rather than sly.

**The source matters.** A contribution the candidate makes by editing the CV or
the letter himself is evidence exactly as much as something he said.
`source: "cv_document"` has existed since T28 and carried **zero rows** before
the backfill — a channel declared and never wired.

The gate needs a deliberate break in the T45 style: disable one detector and
require `capture_misses` to rise **and name the turn it missed**. A silent
capture mechanism whose own failures are silent is the thing being built here,
so its check cannot be one that passes by doing nothing.
