# Watching the exhaustion signal — how to reach it on purpose

Written 2026-08-25, from the owner's observation that a live sitting may never reach
exhaustion because *the conversation itself widens the scope*. That is correct, and it
is a property of the design rather than a flaw in it: T64 exists to make the tool
offer a way out, so a cooperative sitting takes one and the repeats never accumulate.

T69 (`t-192eaa52`) carries `requires: [surface:human]` because its prerequisite is the
signal **having been watched and trusted**, not merely built. This is how to watch it.

---

## The owner's plan works, and here is why

**A test session in which the candidate accepts nothing** reaches exhaustion by the
shortest path:

1. Scope stays where step 2 left it, because a scope change needs a recorded
   acceptance (T65) and there is none.
2. The same search runs again, so `offers_already_seen / offers_returned` climbs.
3. At `EXHAUSTION_REPEAT_SHARE = 0.8` the cycle is `exhausted` and carries its reason
   (T62), step 7 becomes offerable again on the new trigger kind (T63), and a
   symmetric proposal accompanies the re-entry (T64).
4. The refusals are recorded as evidence, and §5.5's re-ask rule means the tool does
   **not** ask again on the next cycle with the same trigger — so the scope stays put
   and the repeats keep climbing rather than being steered away.

So refusing everything is not merely a way to reach the signal; it is the case the
mechanism was designed around. It exercises T62, T63, T64, T65 and T69 in one sitting.

## The one thing it will not show you

**It cannot reach the empty market (T66).** `market_is_empty` requires exhaustion that
survived steering in **both** directions, and steering means an *accepted* decision —
verified:

```text
Cycle(..., steered_by=<a refusal>)
  -> refusal cannot steer: a refused decision steered nothing — §5.5, a refusal licenses none
```

A refuse-everything session therefore keeps `market_is_empty` false forever, and the
tool keeps proposing rather than declaring the market empty. **That is the correct
behaviour**, and it is worth seeing: the empty market is terminal, so it should only be
reachable by having tried the remedy and watched it fail.

To watch T66 instead, the candidate must **accept a widening and a narrowing**, and
both must fail to improve the rejection rate. That is a second, different sitting.

## Fiction is fine here — unlike T20

T20 refuses a simulated candidate outright: `measure_spearman` returns `unmeasured`
for a `fiction: true` profile, because T20 asks whether the system agrees with *this
person* and a persona answers a question nobody asked.

**T69 is not that kind of gate.** `unrequested_profile_reentries == 0` is a claim about
the tool's behaviour — that it offers a profile re-entry and never imposes one — and a
simulated candidate can exercise that as well as a real one. So the refuse-everything
sitting can be run in test mode with an invented profile, and notes captured in
`[[double brackets]]` alongside it.

Keep the two apart: **T20 must be the owner, as themselves. T69 need not be.**

## Watch for these while it runs

The point of watching is to judge whether the signal is *right*, so the things that
would make it wrong:

- **Exhaustion fires while the search is still producing new work.** The share is
  computed against every offer in the candidate's tree including purged tombstones,
  so a purge that misbehaves would inflate it.
- **A cycle returning nothing reads as exhausted for the wrong reason.** T62 sets
  `repeat_share = 0.0` on an empty return and carries a different reason; the reason
  must name the empty return, not repetition.
- **The proposal accompanying re-entry offers only narrowing.** Typed against, but this
  is the anchoring risk (IS-1) and the surface where it would be felt.
- **The tool re-asks a refused question in different words on the next cycle.** The
  rule forbids it; this is the sitting that would reveal it.

If the signal behaves, a person says so and takes T69. **Do not remove `requires` to
unblock the queue** — a missed chance to ask costs one cycle; an unwanted
interrogation costs the candidate's willingness to keep using the tool.
