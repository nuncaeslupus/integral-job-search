---
id: t-6effce46
title: "T343: cv/generated/ has no index, so finding a delivery means reading hash directories"
priority: 5
status: merged
---

Promoted from the candidate sessions of 2026-09-06..2026-10-16: a practice the assistant ran by hand (scratch scripts or profile conventions) that any candidate needs.

Offer directories are `sha256:<hash>/v<N>/`. The employer symlink (#805) names the latest delivery, but the map of employer, role, versions and send path was a hand-kept `INDEX.md`.

Regenerate `cv/generated/INDEX.md` from the manifests whenever a version is written or an employer link is made, never by hand.

Suggested gate: `generated_versions_missing_from_the_index == 0`.

## Acceptance gate

```bash
uv run pytest tests/test_generated_index.py && uv run python -m integral.generated_index
```
