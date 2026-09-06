---
id: t-9ee3b4b1
title: "T136: connecting a board is a procedure nobody had written down, so each one rediscovers the same four questions"
priority: 5
status: merged
---

Four boards were connected or ruled out on 2026-09-06, and the same sequence was rediscovered by hand each time: adjudicate robots with a negative control, find out whether the advert is in the served bytes, find the request behind a page that renders after load, map the fields, capture a fixture and a **different** probe.

The owner's point, and the reason this is a task rather than a note: *"crear conectores debería ser relativamente rápido, ya que cualquier usuario puede necesitarlo."* A board a candidate names is worth a connector, and it cannot cost an afternoon of rediscovery.

The pieces already existed and were never joined: the `har` skill finds the request, `integral.robots` adjudicates, `connector_health` checks rot, `ruled-out.yaml`'s header holds the two tests. What did not exist is the order to run them in, or a script that answers the first question in one command.

`query_board.py` reproduces both of today's real findings unaided: it tells landing.jobs from foorilla.com by content size across client profiles, and it reports that foorilla's second reader **ran and could not refuse** — which is the difference between `single_parser` and a `two_parsers_agreed` row that would have been false.


## Acceptance gate

```gate
connector_probe_misclassifications == 0
evidence: status/evidence/T136.json
key: connector_probe_misclassifications
```

Not `skill-workshop`'s validator, though it was run and the first draft failed
it twice — second-person voice, and a hardcoded self-path where
`${CLAUDE_SKILL_DIR}` belongs. That validator lives in a plugin cache a cloud
session never sees, so a gate depending on it would be green here and
unrunnable there.

What is gated instead is the one judgement in `query_board.py` that a person
cannot make by eye: whether CPython's `robotparser`, used as the second reader,
was **competent on this particular file**. On a robots.txt opening with
`Allow: /` it answers True to everything and cannot disagree, so an agreement
with it is worthless — `foorilla.com` is that file and `landing.jobs` is not,
and nothing short of running the parser on each tells them apart.

**The script is checked by running it, not by reading it.** `T121` is the
standing lesson here: three rounds of grepping a script's text were defeated by
comments and by an unused string holding every pattern the checker looked for.
So the judgement is **run**, over the robots.txt snapshots the connector
library already commits — real files, checked in, and argued with in review. A
verdict function returning one fixed answer fails on whichever of the two it
gets wrong.

It runs in the **package**, and the skill's script imports it, rather than the
other way round. The first draft had the module load
`.claude/skills/connector-new/scripts/query_board.py` by path, and
`test_nothing_in_the_codebase_executes_a_contributed_parse_module` refused it:
`spec_from_file_location` plus `exec_module` is exactly the machinery that
would let a contributed connector ship code, and a gate is not a reason to
introduce it. Inverting the dependency costs nothing and means the script and
the gate cannot drift.
