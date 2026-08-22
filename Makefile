.PHONY: help sync build lint format test gate evidence verify-gates host-gate ci reader reader-process reader-steps clean

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
	@for m in $$(grep -l '^def _main' src/integral/*.py | xargs -n1 basename | sed 's/\.py$$//'); do \
		printf '  %-18s ' "$$m"; \
		uv run python -m integral.$$m >/dev/null || { echo "GATE FAILED"; exit 1; }; \
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

# The repo gate: the four `CLAUDE.md` says must pass before a merge, as one
# command. The name is the one `claude-arsenal`'s `host-gate` key points at, so
# a worker that gains the hook has something real to call — `gate` was already
# taken by T1's lint-exit-code recorder, and reusing it would have made "the
# payload gate ran" indistinguishable from "the repo gate ran", which is the
# confusion D-22 is about.
#
# The list lives here once. `ci` depends on it rather than repeating it: two
# lists of the same four drift, and the one that drifts is the one nobody runs.
host-gate: lint test evidence verify-gates  ## the four CLAUDE.md requires before a merge

ci: host-gate  ## everything CI runs — the same four, by one name

# The readers are generated but committed, so a spec edit without a regenerate
# leaves a reviewer annotating text that has changed underneath them — and
# nothing fails. `test_regenerating_the_reader_produces_no_diff` catches it;
# this is the one-line fix it tells you to run.
# The generator lives in the installed `core` plugin, not in the working tree —
# T58 moved the arsenal skills to the marketplace. integral.plugin_path reads the
# registered install rather than globbing the cache, which holds every version
# ever fetched including ones the loader refused, and fails with a message
# naming what to install rather than an empty string make would treat as a path.
READER_NAME ?= Job Search — Specification v2

# Regenerating both on every edit stamps a fresh date into the one you did not
# touch, which turns a one-document change into a two-document diff nobody can
# trace. `make reader` still does both for a release; `reader-steps` and
# `reader-process` do one, and one is what a normal edit needs.
reader: reader-process reader-steps  ## regenerate both annotatable spec readers

reader-process:  ## regenerate the process-spec reader only
	uv run --with markdown python3 $$(uv run python -m integral.plugin_path core skills/specify/scripts/create_reader.py) \
		--input status/spec-v2-process.md --output-dir docs/spec-v2 --name "$(READER_NAME)"

reader-steps:  ## regenerate the step-spec reader only
	uv run --with markdown python3 $$(uv run python -m integral.plugin_path core skills/specify/scripts/create_reader.py) \
		--input status/spec-v2-steps.md --output-dir docs/spec-v2-steps --name "$(READER_NAME)"

clean:  ## remove build and tool caches
	rm -rf dist build .pytest_cache .mypy_cache .ruff_cache *.egg-info
	find . -type d -name __pycache__ -not -path './.git/*' -exec rm -rf {} +

# Upstream is a Claude Code **marketplace**, not a vendored tree. The two
# plugins are installed once per machine, into ~/.claude/plugins/cache/, and
# updated there:
#
#     /plugin marketplace add github:nuncaeslupus/claude-arsenal
#     /plugin install skill-workshop@claude-arsenal
#     /plugin install core@claude-arsenal
#     /plugin update claude-arsenal
#
# So there is nothing here to pull, re-vendor or verify. The assembled bundle
# under claude-arsenal/ is still repo-side — every protocol step calls into it —
# and `init.py` out of the installed `core` plugin refreshes it, which the
# session-start protocol already does on turn one of every session.
#
# What this replaces: a subtree pull whose squash merge dropped the
# `git-subtree-split:` trailer, so the next pull replayed from a stale base and
# conflicted on files carrying no local edits by construction. The standing
# resolution was "take upstream's tree verbatim" — a ceremony to reconcile a
# copy nobody edits. T58 removed the class rather than the symptom.
