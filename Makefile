.PHONY: help update-skills

ARSENAL_REPO    ?= https://github.com/nuncaeslupus/claude-arsenal.git
ARSENAL_REF     ?= v0.23.1  # pin to a tag — upgrade deliberately
ARSENAL_PLUGINS ?= all      # comma list, or "all" to include skill-creator

# Immutable pin: the commit v0.23.1 resolved to when it was reviewed and
# vendored. A tag can be moved by anyone with push access upstream, and this
# target executes vendor-skills.sh straight out of the fetched checkout — so
# the tag alone is not enough to guarantee we run the code we reviewed.
# Re-vendoring aborts if the ref no longer resolves here. To upgrade: bump
# ARSENAL_REF, run once, read the reported SHA, review the diff, then set it.
ARSENAL_SHA     ?= f84b4eff13a87c29023931147877bc55085466f8

help:  ## list available targets
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

update-skills:  ## vendor claude-arsenal skills into .claude/skills (for CC web)
	@tmp=$$(mktemp -d); trap 'rm -rf $$tmp' EXIT; \
	git clone --depth 1 --branch $(ARSENAL_REF) $(ARSENAL_REPO) $$tmp >/dev/null 2>&1 \
		|| { echo "update-skills: clone of $(ARSENAL_REF) from $(ARSENAL_REPO) failed" >&2; exit 1; }; \
	got=$$(git -C $$tmp rev-parse HEAD); \
	if [ "$$got" != "$(ARSENAL_SHA)" ]; then \
		echo "update-skills: refusing to run vendor-skills.sh from an unverified checkout." >&2; \
		echo "  $(ARSENAL_REF) resolves to $$got" >&2; \
		echo "  ARSENAL_SHA expects   $(ARSENAL_SHA)" >&2; \
		echo "  The tag moved, or you are upgrading. Review the diff, then update ARSENAL_SHA." >&2; \
		exit 1; \
	fi; \
	bash $$tmp/scripts/vendor-skills.sh --src $$tmp --dest .claude/skills --plugins $(ARSENAL_PLUGINS)
