---
id: t-c2cd850d
title: "Match an uppercase .SVG logo in the profile kit"
label: "profile kit svg case"
priority: 10
status: merged
---

Review leftovers from #963 (profile kit), batched per policy G.

1. Fail-closed: `_place_logo` in `integral.profile_kit` matches raster suffixes case-insensitively, but builds the vector path as `f"{slug}.svg"`. So a logo dropped as `<slug>.SVG` is reported missing although it is there.
2. Optional: add a 4:4:4 JPEG case at the original 0.05 aspect tolerance, beside the 4:2:0 case that needed 0.15.

## Wanted

Find the vector the same way as the raster, case-insensitively. Add one test with an uppercase `.SVG`.

## Acceptance gate

```bash
uv run --extra dev pytest tests/test_profile_kit.py -q
```
