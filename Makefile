.PHONY: help sync build lint format test gate evidence verify-gates ci arsenal-remote reader reader-process reader-steps clean update-skills

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

# Every module that owns a gate writes its own evidence file. Regenerating them
# all and refusing any diff is what keeps a committed number honest: evidence
# is measured once, at release, and nothing afterwards notices when a later
# commit changes what the measurement would now say. The module list is
# derived, never listed here — a hardcoded list silently stops covering the
# next module somebody adds, which is the failure this target exists to catch.
evidence:  ## regenerate every module's gate evidence and fail on any drift
	@for m in $$(grep -l '^def _main' src/jobsearch/*.py | xargs -n1 basename | sed 's/\.py$$//'); do \
		printf '  %-18s ' "$$m"; \
		uv run python -m jobsearch.$$m >/dev/null || { echo "GATE FAILED"; exit 1; }; \
		echo ok; \
	done
	@git diff --exit-code --stat status/evidence/ \
		|| { echo "evidence: committed evidence does not match what the code measures now" >&2; exit 1; }
	@echo "evidence: no drift"

# The release path runs a task's gate once, the minute it is released. This
# asserts every task the ledger calls done or merged can still show the
# measurement its status claims — the same hole, reopened by time.
verify-gates:  ## assert every done/merged task's declared gate still holds
	uv run python tools/verify_gates.py

ci: lint test evidence verify-gates  ## everything CI runs, in CI's order

# The readers are generated but committed, so a spec edit without a regenerate
# leaves a reviewer annotating text that has changed underneath them — and
# nothing fails. `test_regenerating_the_reader_produces_no_diff` catches it;
# this is the one-line fix it tells you to run.
READER_NAME ?= Job Search — Specification v2

# Regenerating both on every edit stamps a fresh date into the one you did not
# touch, which turns a one-document change into a two-document diff nobody can
# trace. `make reader` still does both for a release; `reader-steps` and
# `reader-process` do one, and one is what a normal edit needs.
reader: reader-process reader-steps  ## regenerate both annotatable spec readers

reader-process:  ## regenerate the process-spec reader only
	uv run --with markdown python3 .claude/skills/specify/scripts/create_reader.py \
		--input status/spec-v2-process.md --output-dir docs/spec-v2 --name "$(READER_NAME)"

reader-steps:  ## regenerate the step-spec reader only
	uv run --with markdown python3 .claude/skills/specify/scripts/create_reader.py \
		--input status/spec-v2-steps.md --output-dir docs/spec-v2-steps --name "$(READER_NAME)"

clean:  ## remove build and tool caches
	rm -rf dist build .pytest_cache .mypy_cache .ruff_cache *.egg-info
	find . -type d -name __pycache__ -not -path './.git/*' -exec rm -rf {} +

# A git remote is local config, not repository content, so a fresh clone has no
# 'arsenal' remote and claude-arsenal/bin/check_update.sh reports itself INERT
# — it has nothing to compare the installed bundle against. This is the one
# line that wires it up; run it once per clone.
#
# Note this is NOT the subtree the bundle would ideally be. `git subtree` maps
# a prefix onto the upstream repository *root*, and the bundle upstream lives
# at plugins/core/skills/init/assets/ — so a subtree at claude-arsenal/ would
# import the whole marketplace repo, not the bundle layout the session protocol
# calls (claude-arsenal/bin/*.sh). See the queue task for the conversion plan.
arsenal-remote:  ## wire up the 'arsenal' remote so check_update.sh can compare versions
	@git remote get-url arsenal >/dev/null 2>&1 \
		|| git remote add arsenal $(ARSENAL_REPO)
	@git fetch --tags arsenal
	@bash claude-arsenal/bin/check_update.sh

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
