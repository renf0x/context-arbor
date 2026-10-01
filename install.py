#!/usr/bin/env python3
"""Install Context Arbor (arbor.py + memory + agent adapters) into a project."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MANAGED_START = "<!-- CONTEXT-ARBOR:START -->"
MANAGED_END = "<!-- CONTEXT-ARBOR:END -->"
LEGACY_MANAGED_START = "<!-- CTX-AGENT-CONTEXT-STACK:START -->"
LEGACY_MANAGED_END = "<!-- CTX-AGENT-CONTEXT-STACK:END -->"
TEMPLATES = ROOT / "templates"
LEGACY_AGENT_CONTEXT_SHA256 = "33fe20ecdedd8e6f6abf89e92a0f89e6cf6a3fbf2b477595bf3b16a0800010e7"


def copy_file(source: Path, target: Path, force: bool) -> str:
    if target.exists() and not force:
        return "kept"
    existed = target.exists()
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return "updated" if existed else "created"


def append_managed_block(target: Path, block: str) -> str:
    block = block.strip()
    current = target.read_text(encoding="utf-8") if target.exists() else ""
    if MANAGED_START in current:
        return "kept"
    if LEGACY_MANAGED_START in current and LEGACY_MANAGED_END in current:
        start = current.index(LEGACY_MANAGED_START)
        end = current.index(LEGACY_MANAGED_END, start) + len(LEGACY_MANAGED_END)
        prefix = current[:start].rstrip()
        suffix = current[end:].strip()
        target.write_text(
            prefix + ("\n\n" if prefix else "") + block
            + ("\n\n" + suffix if suffix else "") + "\n",
            encoding="utf-8",
        )
        return "migrated"
    target.parent.mkdir(parents=True, exist_ok=True)
    separator = "\n\n" if current.strip() else ""
    target.write_text(current.rstrip() + separator + block + "\n", encoding="utf-8")
    return "appended"


def read_template(relative: str) -> str:
    return (TEMPLATES / relative).read_text(encoding="utf-8")


def write_or_migrate_agent_context(target: Path, content: str) -> str:
    """Replace only the untouched legacy CACP context; preserve user-owned files."""
    if not target.exists():
        target.write_text(content, encoding="utf-8")
        return "created"
    current = target.read_text(encoding="utf-8").replace("\r\n", "\n")
    digest = hashlib.sha256(current.encode("utf-8")).hexdigest()
    if digest == LEGACY_AGENT_CONTEXT_SHA256:
        target.write_text(content, encoding="utf-8")
        return "migrated"
    return "kept"


def run(command: list[str], cwd: Path) -> int:
    print("+", subprocess.list2cmdline(command))
    return subprocess.run(command, cwd=cwd).returncode


def parse_agents(value: str) -> list[str]:
    if value == "all":
        return ["generic", "codex", "claude"]
    agents = [part.strip().lower() for part in value.split(",") if part.strip()]
    valid = {"generic", "codex", "claude"}
    invalid = sorted(set(agents) - valid)
    if invalid:
        raise argparse.ArgumentTypeError(f"unknown agents: {', '.join(invalid)}")
    return agents or ["generic"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Install Context Arbor (arbor.py, memory vault, agent adapters)."
    )
    parser.add_argument("project", nargs="?", default=".", help="target project root")
    parser.add_argument(
        "--agents",
        type=parse_agents,
        default=parse_agents("all"),
        help="all or comma-separated: generic,codex,claude (default: all)",
    )
    parser.add_argument(
        "--force-toolkit",
        action="store_true",
        help="replace an existing arbor.py",
    )
    parser.add_argument(
        "--open-obsidian",
        action="store_true",
        help="install Obsidian when needed and open the memory vault",
    )
    args = parser.parse_args(argv)

    project = Path(args.project).resolve()
    project.mkdir(parents=True, exist_ok=True)

    results = {
        "arbor.py": copy_file(ROOT / "arbor.py", project / "arbor.py", args.force_toolkit),
    }
    if "generic" in args.agents:
        context = project / "AGENT_CONTEXT.md"
        results["AGENT_CONTEXT.md"] = write_or_migrate_agent_context(
            context, read_template("AGENT_CONTEXT.md")
        )
    if "codex" in args.agents:
        results["AGENTS.md"] = append_managed_block(
            project / "AGENTS.md",
            read_template("adapters/AGENTS.md"),
        )
    if "claude" in args.agents:
        results["CLAUDE.md"] = append_managed_block(
            project / "CLAUDE.md",
            read_template("adapters/CLAUDE.md"),
        )

    python = sys.executable
    if run([python, "arbor.py", "init", "--agents", ",".join(args.agents)], project) != 0:
        return 1
    if args.open_obsidian:
        if run([python, "arbor.py", "memory", "open", "--install-obsidian"], project) != 0:
            return 1
    if run([python, "arbor.py", "memory", "check"], project) != 0:
        return 1

    print("\nInstalled:")
    for name, result in results.items():
        print(f"- {name}: {result}")
    print("\nNext:")
    print('  Search memory: python arbor.py memory query "question"')
    print("  Open Obsidian: python arbor.py memory open")
    print('  Save session: python arbor.py session save --note "current state"')
    print('  Find code: python arbor.py code map | code find "topic"')
    print("  Chronicle: python arbor.py ui --open")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
