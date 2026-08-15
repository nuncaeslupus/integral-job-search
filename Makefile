.PHONY: help sync build lint format test gate clean update-skills

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

sync:  ## install the project and its dev dependencies
	uv sync --extra dev

build:  ## build the wheel and sdist
	uv build

# `--extra dev` on every target that needs a dev tool, not just `sync`.
# Without it `uv run ruff` finds no ruff in the project environment and falls
# through to whatever is on PATH — which silently works on a machine that has
# one installed globally and fails on a clean one. The flag makes each target
# self-contained from a fresh clone.
lint:  ## ruff check + strict mypy
	uv run --extra dev ruff check .
	uv run --extra dev mypy .

format:  ## ruff format + autofix
	uv run --extra dev ruff format .
	uv run --extra dev ruff check --fix .

test:  ## run the test suite
	uv run --extra dev pytest

gate:  ## record lint_typecheck_exit_code into status/evidence/T1.json
	@mkdir -p status/evidence
	@if $(MAKE) --no-print-directory lint; then rc=0; else rc=$$?; fi; \
	printf '{\n  "lint_typecheck_exit_code": %s\n}\n' "$$rc" > status/evidence/T1.json; \
	echo "lint_typecheck_exit_code = $$rc  -> status/evidence/T1.json"; \
	exit $$rc

clean:  ## remove build and tool caches
	rm -rf dist build .pytest_cache .mypy_cache .ruff_cache *.egg-info
	find . -type d -name __pycache__ -not -path './.git/*' -exec rm -rf {} +

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
