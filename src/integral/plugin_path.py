#!/usr/bin/env python3
"""Resolve a file inside an installed claude-arsenal plugin.

T58 moved the arsenal skills out of `.claude/skills/` and into marketplace
plugins under `~/.claude/plugins/`. Two places in this repo execute a script
that lives inside one of them — `make reader` runs `specify`'s reader generator,
and the S10 cross-check runs `skill-workshop`'s library auditor — and both need
a path that is no longer in the working tree.

The path is read from `installed_plugins.json`, never globbed off the cache
directory. The cache holds every version ever fetched, including ones the loader
**refused** — v1.0.0's `core` sits there beside 0.1.0 because its manifest
carried a bare-string `author` — so a glob picking "the newest directory" would
happily return a plugin Claude Code will not load. The registry names the one
version that is actually installed, which is the only one worth resolving.

    python3 tools/plugin_path.py core skills/specify/scripts/create_reader.py

Exits 1 with a message naming what to install when the plugin is absent, rather
than printing an empty string that a Makefile would then treat as a filename.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

MARKETPLACE = "claude-arsenal"
REGISTRY = Path.home() / ".claude" / "plugins" / "installed_plugins.json"


class PluginNotInstalled(Exception):
    """The plugin is not registered, so nothing inside it can be resolved."""


def install_path(plugin: str, registry: Path = REGISTRY) -> Path:
    """Where the registered install of `plugin` lives."""
    try:
        entries = json.loads(registry.read_text(encoding="utf-8"))["plugins"]
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        raise PluginNotInstalled(f"cannot read {registry}: {exc}") from exc

    installs = entries.get(f"{plugin}@{MARKETPLACE}")
    if not installs:
        raise PluginNotInstalled(
            f"{plugin}@{MARKETPLACE} is not installed — run "
            f"`/plugin install {plugin}@{MARKETPLACE}` in a Claude Code session"
        )
    return Path(installs[-1]["installPath"])


def resolve(plugin: str, relative: str, registry: Path = REGISTRY) -> Path:
    """The absolute path of `relative` inside the registered install of `plugin`."""
    path = install_path(plugin, registry) / relative
    if not path.exists():
        raise PluginNotInstalled(
            f"{plugin}@{MARKETPLACE} is installed but carries no {relative} — "
            "the registered version predates it; run `/plugin marketplace update "
            f"{MARKETPLACE}` then `/plugin update {MARKETPLACE}`"
        )
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resolve a file inside an installed plugin.")
    parser.add_argument("plugin")
    parser.add_argument("relative")
    args = parser.parse_args(argv)
    try:
        print(resolve(args.plugin, args.relative))
    except PluginNotInstalled as exc:
        print(f"plugin_path: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
