.PHONY: help sync build lint format test gate evidence verify-gates verify-subtree ci arsenal-remote arsenal-upgrade reader reader-process reader-steps clean update-skills assemble-bundle

ARSENAL_REPO    ?= https://github.com/nuncaeslupus/claude-arsenal.git
ARSENAL_REF     ?= v0.30.0  # pin to a tag — upgrade deliberately
ARSENAL_PLUGINS ?= all      # comma list, or "all" to include skill-creator
ARSENAL_PREFIX  ?= vendor/claude-arsenal

# ARSENAL_SHA is gone, and its absence is the point of the subtree (S9).
# It existed because update-skills used to execute vendor-skills.sh straight
# out of a freshly fetched checkout: a tag can be moved by anyone with upstream
# push access, so the tag alone did not guarantee we ran the code we reviewed,
# and a second hand-copied hash had to guard it. A subtree records the exact
# commit in its own merge, in this repository's history, where review already
# looks — so the guarantee comes from git rather than from remembering to
# update a constant.

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

# The assembled bundle under claude-arsenal/ is a copy of the subtree's assets.
# A hand-edit there works perfectly until the next upgrade silently reverts it —
# the exact failure a vendored copy has and a subtree is meant to remove.
verify-subtree:  ## assert claude-arsenal/ still matches its subtree source
	uv run python tools/verify_arsenal_subtree.py

ci: lint test evidence verify-gates verify-subtree  ## everything CI runs, in CI's order

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
#
# check_update.sh needs BOTH paths, and they are different here: the subtree is
# vendored whole at vendor/claude-arsenal, while the assembled bundle holding
# .bundle-version is claude-arsenal/. Until v0.29.0 one variable had to serve
# both, so no setting worked and the check always failed (claude-arsenal#162).
# `--check-only` is not optional here. Without it this target pulls the subtree
# and COMMITS, as a side effect of a target whose name and help both say it only
# wires up a remote and compares versions. It did exactly that on 2026-08-20.
# And the pull it performs is not the whole upgrade: check_update.sh re-runs
# init.py, which assembles claude-arsenal/ out of .claude/skills/init/assets/ —
# refreshed only by `update-skills` — so the bundle is rebuilt from the OLD
# assets and stays a version behind the subtree. `arsenal-upgrade` is the target
# that does all four steps; this one reports.
arsenal-remote:  ## wire up the 'arsenal' remote so check_update.sh can compare versions
	@git remote get-url arsenal >/dev/null 2>&1 \
		|| git remote add arsenal $(ARSENAL_REPO)
	@git fetch --tags arsenal
	@ARSENAL_PREFIX=$(ARSENAL_PREFIX) ARSENAL_BUNDLE_DIR=claude-arsenal \
		bash claude-arsenal/bin/check_update.sh --check-only

update-skills:  ## assemble .claude/skills from the vendored subtree (for CC web)
	@test -d $(ARSENAL_PREFIX) \
		|| { echo "update-skills: no subtree at $(ARSENAL_PREFIX) — run 'make arsenal-upgrade REF=<tag>'" >&2; exit 1; }
	bash $(ARSENAL_PREFIX)/scripts/vendor-skills.sh \
		--src $(ARSENAL_PREFIX) --dest .claude/skills --plugins $(ARSENAL_PLUGINS)

# `update-skills` only rebuilds .claude/skills/ — that is what its name and its
# help text both say, and it is the only thing CC-web needs. It is deliberately
# NOT the step that touches claude-arsenal/: that name would then lie about
# what it does, and a target with two unrelated jobs is a target nobody can
# reason about from its name alone.
#
# claude-arsenal/ is a separate copy, assembled from the *bundle* half of the
# skill — .claude/skills/init/assets/ — which update-skills just refreshed
# from the subtree. Re-running init.py's own refresh logic is what actually
# reassembles it; this is the same invocation the session-start protocol
# already runs at the top of every session (see AGENTS.md step 0b), so
# `arsenal-upgrade` performs no fewer steps by hand than a live session would.
assemble-bundle:  ## reassemble claude-arsenal/ from the freshly-pulled subtree
	python3 .claude/skills/init/scripts/init.py --repo-path . --silent

# Upgrading is a subtree pull, a re-assembly of both halves the pull feeds
# (.claude/skills/ via update-skills, claude-arsenal/ via assemble-bundle),
# and only then the verifier — which proves the assembled bundle is a
# function of the subtree rather than something hand-edited since. Skipping
# assemble-bundle here was the bug: verify-subtree compares claude-arsenal/
# against the subtree, but nothing between the pull and the verify ever
# rebuilt claude-arsenal/ — so any upstream change to a bundle asset failed
# the verify step through no fault of the user.
#
# ⚠️ MERGE THE UPGRADE PR WITH A MERGE COMMIT, NEVER A SQUASH. The pull below
# is `--squash`, which records the release it landed on as a `git-subtree-split:`
# trailer on a commit of its own. A squash merge into main rewrites the branch
# into a single commit and that trailer goes with it, so the NEXT pull cannot
# find where the last one stopped and replays from the last split main still
# remembers — re-applying changes already in the tree as add/add conflicts.
#
# This has already happened here, and it is cheap to check. `origin/main`
# records exactly one split:
#
#     $ git log origin/main --format=%H | while read c; do \
#           git cat-file -p $c | grep git-subtree-split:; done
#     git-subtree-split: f84b4ef...        # the original `git subtree add` (S9)
#
# f84b4ef is v0.25.0. The v0.26.0 upgrade was squash-merged (#44), so its split
# never reached main — and the v0.27.0 pull therefore computed its base as
# `f84b4ef..085fa8c`, replaying v0.25→v0.27 onto a tree already at v0.26 and
# conflicting on twelve files that had no common ancestor to merge from. The
# resolution is always "take upstream's tree verbatim", because this prefix
# carries no local edits by construction — but the conflict should not happen
# at all, and it will not if the merge commit survives.
arsenal-upgrade:  ## pull a new claude-arsenal release into the subtree (REF=v0.x.y)
	@test -n "$(REF)" || { echo "usage: make arsenal-upgrade REF=v0.24.0" >&2; exit 1; }
	git subtree pull --prefix=$(ARSENAL_PREFIX) arsenal $(REF) --squash
	$(MAKE) --no-print-directory update-skills
	$(MAKE) --no-print-directory assemble-bundle
	$(MAKE) --no-print-directory verify-subtree
