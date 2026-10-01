#!/usr/bin/env python3
"""Context Arbor: local project memory, Obsidian and session continuity.

Commands: init, memory, session. Python standard library only.
"""


from __future__ import annotations


__version__ = "0.5.0"


import argparse
import ast
import datetime
import hashlib
import html
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.parse
import webbrowser
from pathlib import Path


CHARS_PER_TOKEN = 3.5


MEMORY_REQUIRED = (
    "MEMORY.md",
    "NOW.md",
    "project-rules.md",
    "development.md",
    "links.md",
    "architecture.md",
    "decisions.md",
    "bugs.md",
    "investigations.md",
    "operations.md",
    "changelog.md",
    "archive/tasks",
    "archive/bugs",
    "archive/decisions",
    "archive/investigations",
    "templates/task.md",
    "templates/bug.md",
    "templates/decision.md",
    "templates/investigation.md",
    ".obsidian/app.json",
    ".obsidian/templates.json",
    ".gitignore",
    ".rules.sha256",
)


MEMORY_DIRECTORIES = {
    "archive/tasks",
    "archive/bugs",
    "archive/decisions",
    "archive/investigations",
}


MEMORY_LINE_LIMIT = 120


NOW_MAX_TOKENS = 1500


# Deliberately tight: architecture.md holds only the most important extract (stack,
# key libraries, structure boundaries), not prose or rationale -- that stays in
# decisions.md/investigations.md, which architecture.md can link to.
ARCHITECTURE_MAX_TOKENS = 400


JOURNAL_MAX_TOKENS = 8000


JOURNAL_TARGET_TOKENS = 5000


MEMORY_JOURNALS = {
    "bugs.md": "bugs",
    "decisions.md": "decisions",
    "investigations.md": "investigations",
    "ideas.md": "ideas",
    "knowledge.md": "knowledge",
}


WIKI_LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


# Entry types: prefix -> (note that `memory add` writes to, default status, field order).
# CHG entries go to monthly `history/YYYY-MM.md` files so retention is a file-level prune.
ENTRY_TYPES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "TASK": ("NOW.md", "next", ("Goal", "Success", "Constraints", "Assumptions / unknowns",
                                "Scope", "Next", "Verification")),
    "BUG": ("bugs.md", "open", ("Date", "Symptom", "Cause", "Resolution", "Regression test")),
    "DEC": ("decisions.md", "active", ("Date", "Decision", "Reason", "Consequences")),
    "INV": ("investigations.md", "open", ("Date", "Question", "Findings", "Conclusion")),
    "IDEA": ("ideas.md", "idea", ("Date", "Author", "Summary", "Motivation", "Proposal",
                                  "Source")),
    "KNW": ("knowledge.md", "active", ("Date", "Topic", "Fact", "Evidence", "Source")),
    "CHG": ("history/{month}.md", "recorded", ("Date", "Target", "Kind", "Author", "Summary",
                                               "Before", "After")),
}


TYPE_ALT = "|".join(ENTRY_TYPES)


NOTE_HEADERS = {
    "ideas.md": "# Ideas and Tasks\n\n> App improvement ideas and tasks (IDEA-*). Managed via "
                "`python arbor.py memory add --type IDEA`.\n",
    "knowledge.md": "# Agent Knowledge\n\n> Confirmed facts, verdicts and domain rules (KNW-*).\n",
}


ENTRY_RE = re.compile(rf"(?m)^##\s+((?:{TYPE_ALT})-[^\n]+)\n")


# A narrow, typed edge between two entries, e.g. `Relations: supersedes:DEC-20260914-001`.
# Direction is always "this entry -> target". Kept deliberately small: extend only when a
# real recurring question needs a new type, per the article's "earns its cost" criteria
# (see DEC-20260914-003 / INV-20260914-002) -- not a general-purpose knowledge graph.
RELATION_TYPES = ("supersedes", "caused-by", "blocks", "depends-on", "relates-to")


ID_PATTERN = rf"(?:{TYPE_ALT})-\d{{8}}-\d{{3}}"


ID_HEAD_RE = re.compile(rf"(?m)^##\s+({ID_PATTERN})\b")


RELATION_LINE_RE = re.compile(r"(?mi)^-\s*Relations:\s*(.+)$")


RELATION_ITEM_RE = re.compile(rf"([a-z][a-z-]*)\s*:\s*({ID_PATTERN})")


MEMORY_TEMPLATES = {
    "MEMORY.md": """# Context Arbor Memory

> Open this index only when project context is needed. Follow links on demand.

## Project

- Goal:
- Current state:
- Primary stack:

## Start Here

- Active task: [[NOW]]
- Permanent rules: [[project-rules]]
- Architecture: [[architecture]]
- Operations: [[operations]]

## On Demand

- Development method: [[development]]
- Search anchors and cross-links: [[links]]

## Warm Ring

- Decisions: [[decisions]]
- Bugs: [[bugs]]
- Investigations: [[investigations]]
- Changes: [[changelog]]

## Retrieval

- Relevant durable notes (local, no LLM): `python arbor.py memory query "<question>"`
- First bootstrap: `python arbor.py memory open --install-obsidian`
""",
    "NOW.md": """# Now

> Hot ring. Keep only the active task and facts needed for the next action.
> Move completed tasks to `archive/tasks/` with `python arbor.py memory rotate`.

## TASK-YYYYMMDD-NNN

- Status: next
- Goal:
- Success:
- Constraints:
- Assumptions / unknowns:
- Scope:
- Next:
- Verification:
- Relations:
- Links:
""",
    "project-rules.md": """# Permanent Project Rules

> Agents must not edit or delete these rules without explicit user instruction
> or confirmation. After an approved change, run
> `python arbor.py memory rules-approve --user-approved`.

## RULE-001

- Status: active
- Rule: Preserve existing behavior unless the task explicitly requires a change.

## RULE-002

- Status: active
- Rule: After memory initialization, run
  `python arbor.py memory open --install-obsidian` once for project bootstrap.
""",
    "architecture.md": (
        "# Architecture\n\n"
        "> English-only stack/structure facts, not prose -- replace an outdated line, "
        "don't append. Update or re-read only when the stack changes, or on request. "
        f"Cap ~{ARCHITECTURE_MAX_TOKENS} tokens (see [[development]]).\n"
    ),
    "development.md": """# Development Method

Use for non-trivial implementation work; this note is not loaded automatically.

- Make uncertain assumptions visible before they affect code.
- Choose the smallest implementation that satisfies the stated goal.
- Keep every changed line within the requested scope; preserve surrounding style.
- Define observable success and verify it before marking the task done.

Store the goal, success criteria, constraints and unresolved assumptions in [[NOW]].
Record only durable outcomes in the journals. Do not preserve routine narration,
temporary command output or abandoned implementation detail.

Inspired by `multica-ai/andrej-karpathy-skills` (MIT-labelled skill, reviewed at
commit `2c606141936f1eeef17fa3043a72095b4765b9c2`).
""",
    "links.md": """# Memory Links

> Sparse bilingual anchors for concepts that may be phrased differently.
> Keep one compact block per concept and link only to notes worth retrieving.

## ANCHOR-ID

- Aliases RU:
- Aliases EN:
- Links:
""",
    "decisions.md": "# Decision Log\n\n## DEC-000 Template\n\n- Status: example\n- Date: YYYY-MM-DD\n- Decision:\n- Reason:\n- Consequences:\n- Relations:\n- Links:\n",
    "bugs.md": "# Bug Log\n\n## BUG-000 Template\n\n- Status: example\n- Date: YYYY-MM-DD\n- Symptom:\n- Cause:\n- Resolution:\n- Regression test:\n- Relations:\n- Links:\n",
    "investigations.md": "# Investigation Log\n\n## INV-000 Template\n\n- Status: example\n- Date: YYYY-MM-DD\n- Question:\n- Findings:\n- Conclusion:\n- Relations:\n- Links:\n",
    "operations.md": "# Operations\n\nCommands, verification steps, and operational constraints.\n",
    "changelog.md": "# Memory Changelog\n\nRecord meaningful changes to the memory system.\n",
    "templates/task.md": """## TASK-YYYYMMDD-NNN

- Status: next
- Goal:
- Success:
- Constraints:
- Assumptions / unknowns:
- Scope:
- Next:
- Verification:
- Relations:
- Links:
""",
    "templates/bug.md": """## BUG-YYYYMMDD-NNN

- Status: open
- Date: YYYY-MM-DD
- Symptom:
- Cause:
- Resolution:
- Regression test:
- Relations:
- Links:
""",
    "templates/decision.md": """## DEC-YYYYMMDD-NNN

- Status: active
- Date: YYYY-MM-DD
- Decision:
- Reason:
- Consequences:
- Relations:
- Links:
""",
    "templates/investigation.md": """## INV-YYYYMMDD-NNN

- Status: open
- Date: YYYY-MM-DD
- Question:
- Findings:
- Conclusion:
- Relations:
- Links:
""",
    ".obsidian/app.json": json.dumps({
        "newFileLocation": "folder",
        "newFileFolderPath": "memory",
        "useMarkdownLinks": False,
        "alwaysUpdateLinks": True,
    }, indent=2) + "\n",
    ".obsidian/templates.json": json.dumps({
        "folder": "templates",
        "dateFormat": "YYYY-MM-DD",
        "timeFormat": "HH:mm",
    }, indent=2) + "\n",
    ".gitignore": "workspace.json\nworkspace-mobile.json\ncache\n",
}


ROOT_GITIGNORE_TEMPLATE = """.arbor/
.ctx/
.claude/settings.local.json
__pycache__/
node_modules/
dist/
build/
coverage/
.env
.env.*
"""


def est_tokens(text: str) -> int:
    return max(1, round(len(text) / CHARS_PER_TOKEN))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _project_root(path: str | os.PathLike[str]) -> Path:
    return Path(path).resolve()


def _memory_root(path: str | os.PathLike[str]) -> Path:
    return _project_root(path) / "memory"


def _hook_command(args: str) -> str:
    """Command line for a Claude Code hook. Claude Code runs hooks with bash (Git Bash on
    Windows) in the session's current directory, which an agent's `cd` moves; a bare
    `python arbor.py ...` then fails with exit code 2, and on PreToolUse/UserPromptSubmit
    that blocks every tool call or prompt for the rest of the session. So the hook goes to
    the project root first and does nothing at all when arbor.py is not there."""
    return f'cd "${{CLAUDE_PROJECT_DIR:-.}}" && [ -f arbor.py ] || exit 0; python arbor.py {args}'


# Hook commands written by earlier versions; `init` rewrites them in place.
_LEGACY_HOOK_ARGS = ("session gauge", "session snapshot", "session restore", "session guard",
                     "session compact-guard --trigger manual", "session compact-guard --trigger auto")
LEGACY_HOOK_COMMANDS = {f"python arbor.py {a}": _hook_command(a) for a in _LEGACY_HOOK_ARGS}


def _upgrade_hook_commands(hooks: dict) -> bool:
    """Rewrite hook commands of earlier versions to the current form; True if any changed."""
    changed = False
    for groups in hooks.values():
        for group in groups if isinstance(groups, list) else []:
            for hook in group.get("hooks", []) if isinstance(group, dict) else []:
                if isinstance(hook, dict) and hook.get("command") in LEGACY_HOOK_COMMANDS:
                    hook["command"] = LEGACY_HOOK_COMMANDS[hook["command"]]
                    changed = True
    return changed


def _rules_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_rules_digest(memory: Path) -> None:
    rules = memory / "project-rules.md"
    (memory / ".rules.sha256").write_text(_rules_digest(rules) + "\n", encoding="utf-8")


def cmd_memory_init(args: argparse.Namespace) -> int:
    root = _project_root(args.path)
    memory = root / "memory"
    created: list[str] = []
    memory.mkdir(parents=True, exist_ok=True)
    for rel in MEMORY_REQUIRED:
        target = memory / rel
        if rel in MEMORY_DIRECTORIES:
            if not target.exists():
                target.mkdir(parents=True)
                created.append(f"memory/{rel}/")
            continue
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if rel == ".rules.sha256":
            continue
        target.write_text(MEMORY_TEMPLATES[rel], encoding="utf-8")
        created.append(f"memory/{rel}")

    # Context Arbor v0.3 moves volatile work into the Obsidian vault. Preserve
    # an existing handoff verbatim when NOW.md has not already been created.
    handoff = root / "handoff.md"
    now = memory / "NOW.md"
    if handoff.is_file() and now.is_file() and read_text(now) == MEMORY_TEMPLATES["NOW.md"]:
        legacy = read_text(handoff).strip()
        if legacy:
            now.write_text(
                "# Now\n\n> Imported from the legacy `handoff.md`. Restructure this into "
                "the active task fields when next edited.\n\n" + legacy + "\n",
                encoding="utf-8",
            )
            handoff.unlink()
            created.append("memory/NOW.md (migrated handoff.md)")

    root_gitignore = root / ".gitignore"
    if not root_gitignore.exists():
        root_gitignore.write_text(ROOT_GITIGNORE_TEMPLATE, encoding="utf-8")
        created.append(".gitignore")

    checksum = memory / ".rules.sha256"
    if not checksum.exists():
        _write_rules_digest(memory)
        created.append("memory/.rules.sha256")

    print(f"# memory initialized at {memory}")
    print("# created: " + (", ".join(created) if created else "nothing (already initialized)"))
    return 0


def _resolve_wiki_link(source: Path, memory: Path, raw: str) -> Path | None:
    target = raw.split("|", 1)[0].split("#", 1)[0].strip()
    if not target or "://" in target:
        return None
    candidate = (source.parent / target)
    if not candidate.suffix:
        candidate = candidate.with_suffix(".md")
    if candidate.exists():
        return candidate
    # Obsidian also resolves note names anywhere in the vault.
    matches = list(memory.rglob(candidate.name))
    return matches[0] if len(matches) == 1 else candidate


def memory_check(root: Path) -> list[dict[str, str]]:
    memory = root / "memory"
    issues: list[dict[str, str]] = []
    for rel in MEMORY_REQUIRED:
        target = memory / rel
        if not target.exists():
            issues.append({"code": "missing", "path": f"memory/{rel}",
                           "message": "required path is missing"})

    index = memory / "MEMORY.md"
    if index.is_file():
        lines = read_text(index).count("\n") + 1
        if lines > MEMORY_LINE_LIMIT:
            issues.append({"code": "index-too-long", "path": "memory/MEMORY.md",
                           "message": f"{lines} lines; limit is {MEMORY_LINE_LIMIT}"})

    now = memory / "NOW.md"
    if now.is_file() and est_tokens(read_text(now)) > NOW_MAX_TOKENS:
        issues.append({"code": "hot-ring-too-large", "path": "memory/NOW.md",
                       "message": f"over {NOW_MAX_TOKENS} estimated tokens; run `python arbor.py "
                                  "memory rotate` (archives closed tasks, folds long open ones)"})

    architecture = memory / "architecture.md"
    if architecture.is_file() and est_tokens(read_text(architecture)) > ARCHITECTURE_MAX_TOKENS:
        issues.append({"code": "architecture-too-large", "path": "memory/architecture.md",
                       "message": f"over {ARCHITECTURE_MAX_TOKENS} estimated tokens; keep only "
                                  "the most important stack/structure facts, not prose"})

    for name in MEMORY_JOURNALS:
        journal = memory / name
        if journal.is_file() and est_tokens(read_text(journal)) > JOURNAL_MAX_TOKENS:
            issues.append({"code": "journal-too-large", "path": f"memory/{name}",
                           "message": f"over {JOURNAL_MAX_TOKENS} estimated tokens; rotate it"})

    for note in memory.rglob("*.md"):
        if "archive" in note.relative_to(memory).parts:
            continue
        for raw in WIKI_LINK_RE.findall(read_text(note)):
            resolved = _resolve_wiki_link(note, memory, raw)
            if resolved is not None and not resolved.exists():
                issues.append({"code": "broken-link",
                               "path": note.relative_to(root).as_posix(),
                               "message": f"[[{raw}]] does not resolve"})

    rules = memory / "project-rules.md"
    checksum = memory / ".rules.sha256"
    if rules.is_file() and checksum.is_file():
        expected = read_text(checksum).strip()
        actual = _rules_digest(rules)
        if expected != actual:
            issues.append({"code": "rules-changed", "path": "memory/project-rules.md",
                           "message": "rules changed without approved checksum update"})

    if memory.is_dir():
        _ids, _edges, relation_issues = _relations_graph(memory)
        issues.extend(relation_issues)
    return issues


def _entry_blocks(text: str) -> list[tuple[str, str]]:
    """Split a note into (entry_id, block) pairs at each `## ID` heading whose
    ID matches the strict `TYPE-YYYYMMDD-NNN` format (template placeholders
    like `DEC-YYYYMMDD-NNN` never match, so templates need no special-casing)."""
    matches = list(ID_HEAD_RE.finditer(text))
    blocks: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        blocks.append((m.group(1), text[m.start():end]))
    return blocks


def _relations_graph(
    memory: Path,
) -> tuple[dict[str, str], dict[str, list[tuple[str, str]]], list[dict[str, str]]]:
    """The local entry graph: which note defines each ID, the typed `Relations:`
    edges each entry declares, and any validation issues. Deterministic, no
    model, no network -- entries and edges come only from files already on disk.
    Archived notes are included so a rotated ID does not look dangling."""
    ids: dict[str, str] = {}
    raw_edges: list[tuple[str, str, str, str]] = []  # (entry_id, rtype, target, defining note)
    for note in sorted(memory.rglob("*.md")):
        rel_note = note.relative_to(memory).with_suffix("").as_posix()
        text = read_text(note)
        for entry_id, block in _entry_blocks(text):
            ids.setdefault(entry_id, rel_note)
            match = RELATION_LINE_RE.search(block)
            if not match:
                continue
            for rtype, target in RELATION_ITEM_RE.findall(match.group(1)):
                raw_edges.append((entry_id, rtype.lower(), target, rel_note))

    edges: dict[str, list[tuple[str, str]]] = {}
    issues: list[dict[str, str]] = []
    for entry_id, rtype, target, rel_note in raw_edges:
        if rtype not in RELATION_TYPES:
            issues.append({"code": "unknown-relation-type",
                           "path": f"memory/{rel_note}.md",
                           "message": f"{entry_id}: {rtype!r} is not a known relation type "
                                      f"({', '.join(RELATION_TYPES)})"})
            continue
        edges.setdefault(entry_id, []).append((rtype, target))
        if target not in ids:
            issues.append({"code": "dangling-relation",
                           "path": f"memory/{rel_note}.md",
                           "message": f"{entry_id} {rtype} {target}, which no entry defines"})
    return ids, edges, issues


def _invert_edges(edges: dict[str, list[tuple[str, str]]]) -> dict[str, list[tuple[str, str]]]:
    incoming: dict[str, list[tuple[str, str]]] = {}
    for source, rels in edges.items():
        for rtype, target in rels:
            incoming.setdefault(target, []).append((rtype, source))
    return incoming


def _trace_direction(start: str, adjacency: dict[str, list[tuple[str, str]]],
                     ids: dict[str, str], depth: int) -> list[dict[str, object]]:
    """Breadth-first walk of one edge direction up to `depth` hops. Deterministic:
    edges expand in declaration order and each ID is visited at most once, so a
    cycle (A blocks B, B blocks A) cannot loop. This is the whole traversal --
    no ranking, no model call, just following typed edges already on disk."""
    rows: list[dict[str, object]] = []
    seen = {start}
    frontier = [start]
    for level in range(1, depth + 1):
        next_frontier: list[str] = []
        for node in frontier:
            for rtype, other in adjacency.get(node, []):
                rows.append({"from": node, "relation": rtype, "to": other, "depth": level,
                            "resolved": other in ids, "note": ids.get(other)})
                if other not in seen:
                    seen.add(other)
                    next_frontier.append(other)
        frontier = next_frontier
        if not frontier:
            break
    return rows


def cmd_memory_trace(args: argparse.Namespace) -> int:
    """Follow typed `Relations:` edges from one entry ID: what it leads to
    (outgoing) and what points to it (incoming), up to --depth hops. Answers a
    connected, multi-hop question ("what led to DEC-017?") the way a small graph
    would, without a database or a model -- local traversal over the vault."""
    root = _project_root(args.path)
    memory = root / "memory"
    ids, edges, _issues = _relations_graph(memory)
    if args.id not in ids:
        sys.stderr.write(f"[arbor] unknown entry ID: {args.id}\n")
        return 2
    incoming = _invert_edges(edges)
    outgoing_rows = _trace_direction(args.id, edges, ids, args.depth)
    incoming_rows = _trace_direction(args.id, incoming, ids, args.depth)
    if args.json:
        print(json.dumps({"id": args.id, "note": ids[args.id], "depth": args.depth,
                          "outgoing": outgoing_rows, "incoming": incoming_rows},
                         ensure_ascii=False, indent=2))
        return 0

    def render(rows: list[dict[str, object]], label: str, reverse: bool) -> None:
        print(f"\n## {label}")
        if not rows:
            print("(none)")
            return
        for row in rows:
            indent = "  " * (row["depth"] - 1)
            left, right = (row["to"], row["from"]) if reverse else (row["from"], row["to"])
            where = f" [memory/{row['note']}.md]" if row["resolved"] else " [unresolved]"
            print(f"{indent}{left} --{row['relation']}--> {right}{where}")

    print(f"# trace: {args.id} (memory/{ids[args.id]}.md)")
    render(outgoing_rows, "Outgoing (what this leads to)", reverse=False)
    render(incoming_rows, "Incoming (what points to this)", reverse=True)
    return 0


def cmd_memory_check(args: argparse.Namespace) -> int:
    root = _project_root(args.path)
    issues = memory_check(root)
    if args.json:
        print(json.dumps({"ok": not issues, "issues": issues}, ensure_ascii=False, indent=2))
    elif issues:
        print("# memory check failed")
        for issue in issues:
            print(f"- [{issue['code']}] {issue['path']}: {issue['message']}")
    else:
        print("# memory check: OK")
    return 1 if issues else 0


_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text)]


def _split_blocks(text: str) -> list[tuple[str, str]]:
    """Split a note into (heading, block) chunks on markdown headers so a hit
    points the agent at a section, not a whole file."""
    blocks: list[tuple[str, str]] = []
    heading = ""
    buf: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^#{1,3}\s+(.*)", line)
        if m:
            if any(b.strip() for b in buf):
                blocks.append((heading, "\n".join(buf).strip()))
            heading = m.group(1).strip()
            buf = [line]
        else:
            buf.append(line)
    if any(b.strip() for b in buf):
        blocks.append((heading, "\n".join(buf).strip()))
    return blocks


def _iter_search_files(root: Path, memory_only: bool = True):
    base = root / "memory"
    for note in sorted(base.rglob("*.md")):
        parts = note.relative_to(base).parts
        if "archive" not in parts and "templates" not in parts:
            yield note


def _memory_ring_weight(rel: str) -> float:
    """Prefer the hot working set and sparse links without loading more text."""
    if rel == "memory/NOW.md":
        return 3.0
    if rel in {"memory/project-rules.md", "memory/links.md"}:
        return 2.0
    return 1.0


def _retrieve(root: Path, query: str, top: int,
              memory_only: bool) -> list[tuple[float, str, str, str]]:
    """Return the top-k (score, relpath, heading, block) matches for a query.

    Scoring is query-term frequency normalized by sqrt(block length): a short,
    on-topic block outranks a long one that mentions the term once. Deterministic
    and cheap -- no model, no network."""
    qterms = set(_tokenize(query))
    if not qterms:
        return []
    scored: list[tuple[float, str, str, str]] = []
    for path in _iter_search_files(root, memory_only):
        rel = path.relative_to(root).as_posix()
        try:
            text = read_text(path)
        except OSError:
            continue
        for heading, block in _split_blocks(text):
            words = _tokenize(block)
            hits = sum(1 for w in words if w in qterms)
            if not hits:
                continue
            # A query term in the section heading is a stronger relevance signal
            # than one buried in the body -- count heading hits twice.
            head_hits = sum(1 for w in _tokenize(heading) if w in qterms)
            score = ((hits + head_hits) / (len(words) ** 0.5)) * _memory_ring_weight(rel)
            scored.append((score, rel, heading, block))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return scored[:top]


def _render_hits(hits: list[tuple[float, str, str, str]]) -> str:
    out: list[str] = []
    for _score, rel, heading, block in hits:
        loc = rel + (f" # {heading}" if heading else "")
        snippet = block if len(block) <= 800 else block[:800].rstrip() + " ..."
        out.append(f"----- {loc} -----\n{snippet}")
    return "\n\n".join(out)


def _memory_context(root: Path, task: str) -> str:
    memory = root / "memory"
    parts = [f"# Task\n\n{task}"]
    core = (memory / "MEMORY.md", memory / "NOW.md", memory / "project-rules.md")
    for path in core:
        if path.is_file():
            parts.append(f"# {path.relative_to(root).as_posix()}\n\n{read_text(path)}")

    core_rel = {path.relative_to(root).as_posix() for path in core}
    hits = [hit for hit in _retrieve(root, task, top=8, memory_only=True)
            if hit[1] not in core_rel][:5]
    if hits:
        parts.append("# Relevant durable notes (top-k retrieval)\n\n" + _render_hits(hits))
    return "\n\n".join(parts).strip() + "\n"


def cmd_memory_context(args: argparse.Namespace) -> int:
    root = _project_root(args.path)
    text = _memory_context(root, args.task)
    print(text, end="")
    return 0


def cmd_memory_query(args: argparse.Namespace) -> int:
    """Search durable notes locally without a model or network."""
    root = _project_root(args.path)
    hits = _retrieve(root, args.question, top=args.top,
                     memory_only=True)
    if args.json:
        print(json.dumps({
            "query": args.question,
            "scope": "memory",
            "hits": [{"score": round(s, 4), "path": rel, "heading": h,
                      "snippet": b[:800]} for s, rel, h, b in hits],
        }, ensure_ascii=False, indent=2))
        return 0
    if not hits:
        print(f"# no matching notes "
              f"for: {args.question!r}")
        if re.search(r"[^\x00-\x7f]", args.question):
            # Local retrieval matches words, not meaning: a Russian question finds nothing in
            # English notes (measured: 0 of 9), and the agent then greps the vault instead.
            print("# retrieval matches words, not meaning: if the notes are written in another "
                  "language (usually English), retry with keywords in that language")
        return 0
    rendered = _render_hits(hits)
    print(rendered)
    print(f"\n# {len(hits)} block(s) "
          f"(local retrieval, no LLM)")
    return 0


def _entry_is_closed(entry: str) -> bool:
    match = re.search(r"(?mi)^-\s*Status:\s*([^\n]+)", entry)
    if not match:
        return False
    status = match.group(1).strip().lower()
    return status in {"closed", "done", "resolved", "superseded", "archived", "example"}


def _rotate_journal(memory: Path, name: str, category: str,
                    always_closed: bool = False) -> int:
    path = memory / name
    if not path.is_file():
        return 0
    text = read_text(path)
    if not always_closed and est_tokens(text) <= JOURNAL_MAX_TOKENS:
        return 0
    matches = list(ENTRY_RE.finditer(text))
    if not matches:
        return 0
    header = text[:matches[0].start()]
    entries = [
        text[m.start():(matches[i + 1].start() if i + 1 < len(matches) else len(text))]
        for i, m in enumerate(matches)
    ]
    moved: list[str] = []
    kept: list[str] = []
    current = est_tokens(text)
    for entry in entries:
        if (always_closed or current > JOURNAL_TARGET_TOKENS) and _entry_is_closed(entry):
            moved.append(entry.strip())
            current -= est_tokens(entry)
        else:
            kept.append(entry.strip())
    if not moved:
        return 0
    path.write_text(header.rstrip() + "\n\n" + "\n\n".join(kept).rstrip() + "\n",
                    encoding="utf-8")
    month = datetime.date.today().strftime("%Y-%m")
    archive = memory / "archive" / category / f"{month}.md"
    archive.parent.mkdir(parents=True, exist_ok=True)
    existing = read_text(archive).rstrip() if archive.exists() else f"# {category.title()} Archive {month}"
    archive.write_text(existing + "\n\n" + "\n\n".join(moved) + "\n", encoding="utf-8")
    return len(moved)


def cmd_memory_rotate(args: argparse.Namespace) -> int:
    memory = _memory_root(args.path)
    total = sum(_rotate_journal(memory, name, category)
                for name, category in MEMORY_JOURNALS.items())
    # NOW is deliberately tiny: an explicit rotation always removes completed
    # task blocks, even before the hot-ring size limit is reached.
    total += _rotate_journal(memory, "NOW.md", "tasks", always_closed=True)
    print(f"# memory rotation: moved {total} closed entr{'y' if total == 1 else 'ies'}")
    folded = _fold_now(memory)
    if folded:
        size = est_tokens(read_text(memory / "NOW.md"))
        print(f"# folded {len(folded)} long open entr{'y' if len(folded) == 1 else 'ies'} into "
              f"memory/tasks/ ({', '.join(folded)}); NOW.md is now ~{size} tokens")
    return 0


# Lines of a folded entry that stay in the hot ring; the rest moves to memory/tasks/<ID>.md.
_FOLD_KEEP_RE = re.compile(r"(?mi)^-\s*\**(?:status|goal|next|relations)\**\s*:.*$")
_FOLDED_MARK = "- Details: [[tasks/"


def _fold_now(memory: Path) -> list[str]:
    """Bring NOW.md under NOW_MAX_TOKENS without dropping anything. NOW.md is read at the
    start of every session and after every /clear, so a hot ring of open tasks with long
    bodies is paid for again and again (one real project: ~8k tokens, read ~14 times over
    five sessions). The biggest open TASK/BUG entries move to memory/tasks/<ID>.md; NOW.md keeps
    the heading, the Status/Goal/Next/Relations lines and a link. Returns the folded ids."""
    now = memory / "NOW.md"
    if not now.is_file():
        return []
    text = read_text(now)
    if est_tokens(text) <= NOW_MAX_TOKENS:
        return []
    sections = re.split(r"(?m)^(?=## )", text)
    order = sorted(range(len(sections)), key=lambda i: -len(sections[i]))
    folded: list[str] = []
    total = est_tokens(text)
    for i in order:
        if total <= NOW_MAX_TOKENS:
            break
        block = sections[i]
        head = ID_HEAD_RE.match(block)
        if not head or not head.group(1).startswith(("TASK-", "BUG-")) or _FOLDED_MARK in block:
            continue
        entry_id = head.group(1)
        heading = block.splitlines()[0]
        kept = [line[:240] for line in _FOLD_KEEP_RE.findall(block)]
        stub = "\n".join([heading, "", *kept, f"{_FOLDED_MARK}{entry_id}]] (folded from NOW.md)"]) + "\n\n"
        if est_tokens(stub) >= 0.7 * est_tokens(block):
            continue  # not worth a separate note
        target = memory / "tasks" / f"{entry_id}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        body = re.sub(r"^##\s+", "# ", block).strip() + "\n"  # h1: the `## ID` entry stays in NOW.md
        if target.exists():
            body = read_text(target).rstrip() + f"\n\n## Folded again {datetime.date.today()}\n\n" \
                + block.split("\n", 1)[-1].strip() + "\n"
        target.write_text(body, encoding="utf-8")
        total -= est_tokens(block) - est_tokens(stub)
        sections[i] = stub
        folded.append(entry_id)
    if folded:
        now.write_text("".join(sections).rstrip() + "\n", encoding="utf-8")
    return folded


def cmd_memory_rules_approve(args: argparse.Namespace) -> int:
    if not args.user_approved:
        sys.stderr.write("[arbor] refusing to approve rules without --user-approved\n")
        return 2
    memory = _memory_root(args.path)
    rules = memory / "project-rules.md"
    if not rules.is_file():
        sys.stderr.write(f"[arbor] missing rules file: {rules}\n")
        return 2
    _write_rules_digest(memory)
    print("# permanent rules checksum updated after explicit user approval")
    return 0


# --- Entry CRUD -------------------------------------------------------------
# Entries are `## ID Title` blocks of `- Key: value` lines. Multi-line values are
# stored as continuation lines indented by two spaces. Writers take a vault lock
# and replace files atomically, because the app and coding agents share a vault.

FIELD_RE = re.compile(r"^-\s*([^:\n]+?):[ \t]?(.*)$")


class _VaultLock:
    def __init__(self, memory: Path, timeout: float = 10.0, stale: float = 30.0):
        self.path = memory / ".arbor.lock"
        self.timeout = timeout
        self.stale = stale

    def __enter__(self) -> "_VaultLock":
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > self.stale:
                        self.path.unlink()
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() > deadline:
                    raise TimeoutError(f"vault is locked: {self.path}")
                time.sleep(0.05)

    def __exit__(self, *exc: object) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def _parse_entry(entry_id: str, block: str) -> dict[str, object]:
    lines = block.rstrip("\n").splitlines()
    head = lines[0] if lines else ""
    title = head.split(entry_id, 1)[1].strip() if entry_id in head else ""
    fields: dict[str, str] = {}
    current: str | None = None
    for line in lines[1:]:
        m = FIELD_RE.match(line)
        if m:
            current = m.group(1).strip()
            fields[current] = m.group(2).rstrip()
        elif current is not None and line.startswith("  "):
            fields[current] += "\n" + line[2:]
        elif line.strip():
            current = None
    return {"id": entry_id, "type": entry_id.split("-", 1)[0], "title": title,
            "status": fields.get("Status", ""), "fields": fields}


def _render_entry(entry_id: str, title: str, fields: dict[str, str]) -> str:
    out = [f"## {entry_id}" + (f" {title}" if title else ""), ""]
    for key, value in fields.items():
        first, *rest = (value or "").split("\n")
        out.append(f"- {key}: {first}".rstrip())
        out.extend("  " + line for line in rest)
    return "\n".join(out) + "\n"


def _entry_notes(memory: Path, include_archive: bool = False):
    for note in sorted(memory.rglob("*.md")):
        parts = note.relative_to(memory).parts
        if "templates" in parts or (not include_archive and "archive" in parts):
            continue
        yield note


def _find_entry(memory: Path, entry_id: str) -> tuple[Path, str, str] | None:
    for note in _entry_notes(memory, include_archive=True):
        text = read_text(note)
        for eid, block in _entry_blocks(text):
            if eid == entry_id:
                return note, text, block
    return None


def _next_id(memory: Path, prefix: str, day: str) -> str:
    stem = f"{prefix}-{day}-"
    used = 0
    for note in _entry_notes(memory, include_archive=True):
        for eid, _block in _entry_blocks(read_text(note)):
            if eid.startswith(stem):
                used = max(used, int(eid[-3:]))
    if used >= 999:
        raise ValueError(f"no free {prefix} IDs left for {day}")
    return f"{stem}{used + 1:03d}"


def _entry_payload(args: argparse.Namespace) -> dict[str, object]:
    """Merge `--input-json` (stdin JSON: title/status/fields) with CLI flags."""
    data: dict[str, object] = {}
    if getattr(args, "input_json", False):
        # PowerShell pipes add a UTF-8 BOM; accept it.
        raw = sys.stdin.read().lstrip("﻿")
        data = json.loads(raw) if raw.strip() else {}
    fields = dict(data.get("fields") or {})
    for item in getattr(args, "field", None) or []:
        key, sep, value = item.partition("=")
        if not sep:
            raise ValueError(f"--field expects KEY=VALUE, got {item!r}")
        fields[key.strip()] = value
    data["fields"] = {str(k): "" if v is None else str(v) for k, v in fields.items()}
    if getattr(args, "title", None) is not None:
        data["title"] = args.title
    if getattr(args, "status", None) is not None:
        data["status"] = args.status
    return data


def _emit(args: argparse.Namespace, payload: object, text: str) -> None:
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(text)


def _fail(message: str, code: int = 2) -> int:
    sys.stderr.write(f"[arbor] {message}\n")
    return code


def cmd_memory_add(args: argparse.Namespace) -> int:
    memory = _memory_root(args.path)
    prefix = args.type.upper()
    if prefix not in ENTRY_TYPES:
        return _fail(f"unknown type {prefix}; known: {', '.join(ENTRY_TYPES)}")
    try:
        data = _entry_payload(args)
    except (ValueError, json.JSONDecodeError) as exc:
        return _fail(str(exc))
    note_tpl, default_status, order = ENTRY_TYPES[prefix]
    today = datetime.date.today()
    note = memory / note_tpl.format(month=today.strftime("%Y-%m"))
    given: dict[str, str] = data["fields"]  # type: ignore[assignment]
    fields = {"Status": str(data.get("status") or given.pop("Status", "") or default_status)}
    for key in order:
        fields[key] = given.pop(key, today.isoformat() if key == "Date" else "")
    fields.update(given)
    fields.setdefault("Relations", "")
    fields.setdefault("Links", "")
    with _VaultLock(memory):
        entry_id = _next_id(memory, prefix, today.strftime("%Y%m%d"))
        if note.exists():
            current = read_text(note)
        elif note.name in NOTE_HEADERS:
            current = NOTE_HEADERS[note.name]
        elif prefix == "CHG":
            current = f"# Change History {today.strftime('%Y-%m')}\n"
        else:
            current = f"# {note.stem}\n"
        block = _render_entry(entry_id, str(data.get("title") or ""), fields)
        _atomic_write(note, current.rstrip() + "\n\n" + block)
    entry = _parse_entry(entry_id, block)
    entry["note"] = note.relative_to(memory).as_posix()
    _emit(args, entry, f"# added {entry_id} -> memory/{entry['note']}")
    return 0


def cmd_memory_get(args: argparse.Namespace) -> int:
    memory = _memory_root(args.path)
    found = _find_entry(memory, args.id)
    if not found:
        return _fail(f"unknown entry ID: {args.id}")
    note, _text, block = found
    entry = _parse_entry(args.id, block)
    entry["note"] = note.relative_to(memory).as_posix()
    _emit(args, entry, block.rstrip())
    return 0


def cmd_memory_list(args: argparse.Namespace) -> int:
    memory = _memory_root(args.path)
    types = {t.strip().upper() for t in (args.type or "").split(",") if t.strip()}
    statuses = {s.strip().lower() for s in (args.status or "").split(",") if s.strip()}
    rows: list[dict[str, object]] = []
    for note in _entry_notes(memory, include_archive=args.include_archive):
        for eid, block in _entry_blocks(read_text(note)):
            entry = _parse_entry(eid, block)
            if types and entry["type"] not in types:
                continue
            if statuses and str(entry["status"]).lower() not in statuses:
                continue
            entry["note"] = note.relative_to(memory).as_posix()
            rows.append(entry)
    rows.sort(key=lambda e: str(e["id"]), reverse=True)
    if args.limit:
        rows = rows[:args.limit]
    text = "\n".join(f"{e['id']}  [{e['status']}]  {e['title']}" for e in rows) or "(none)"
    _emit(args, {"entries": rows}, text)
    return 0


def _rewrite_entry(memory: Path, entry_id: str, change) -> tuple[int, dict[str, object] | None]:
    with _VaultLock(memory):
        found = _find_entry(memory, entry_id)
        if not found:
            return _fail(f"unknown entry ID: {entry_id}"), None
        note, text, block = found
        new_block = change(_parse_entry(entry_id, block))
        start = text.index(block)
        replacement = new_block + "\n" if new_block else ""
        new_text = text[:start] + replacement + text[start + len(block):]
        new_text = re.sub(r"\n{3,}", "\n\n", new_text)
        _atomic_write(note, new_text.rstrip() + "\n")
    if not new_block:
        return 0, None
    entry = _parse_entry(entry_id, new_block)
    entry["note"] = note.relative_to(memory).as_posix()
    return 0, entry


def cmd_memory_update(args: argparse.Namespace) -> int:
    memory = _memory_root(args.path)
    try:
        data = _entry_payload(args)
    except (ValueError, json.JSONDecodeError) as exc:
        return _fail(str(exc))

    def change(entry: dict[str, object]) -> str:
        fields: dict[str, str] = dict(entry["fields"])  # type: ignore[arg-type]
        fields.update(data["fields"])  # type: ignore[arg-type]
        if data.get("status") is not None:
            fields["Status"] = str(data["status"])
        title = str(data["title"]) if data.get("title") is not None else str(entry["title"])
        return _render_entry(args.id, title, fields)

    code, entry = _rewrite_entry(memory, args.id, change)
    if code == 0:
        _emit(args, entry, f"# updated {args.id}")
    return code


def cmd_memory_close(args: argparse.Namespace) -> int:
    args.field, args.title, args.input_json = [], None, False
    args.status = args.status or "closed"
    return cmd_memory_update(args)


def cmd_memory_delete(args: argparse.Namespace) -> int:
    if not args.yes:
        return _fail("refusing to delete without --yes")
    memory = _memory_root(args.path)
    code, _entry = _rewrite_entry(memory, args.id, lambda _e: "")
    if code == 0:
        _emit(args, {"id": args.id, "deleted": True}, f"# deleted {args.id}")
    return code


def cmd_memory_prune(args: argparse.Namespace) -> int:
    """Retention: delete monthly history (and optionally archive) files older
    than N months. Month files are named YYYY-MM.md, so no parsing is needed."""
    memory = _memory_root(args.path)
    today = datetime.date.today()
    cutoff = today.year * 12 + today.month - 1 - args.older_than_months
    dirs = [memory / "history"]
    if args.include_archive:
        dirs += [d for d in (memory / "archive").glob("*") if d.is_dir()]
    removed: list[str] = []
    with _VaultLock(memory):
        for folder in dirs:
            for f in sorted(folder.glob("*.md")) if folder.is_dir() else []:
                m = re.fullmatch(r"(\d{4})-(\d{2})\.md", f.name)
                if m and int(m.group(1)) * 12 + int(m.group(2)) - 1 < cutoff:
                    if not args.dry_run:
                        f.unlink()
                    removed.append(f.relative_to(memory).as_posix())
    _emit(args, {"removed": removed, "dry_run": args.dry_run},
          f"# pruned {len(removed)} file(s)" + (" (dry run)" if args.dry_run else ""))
    return 0


def _find_obsidian() -> str | None:
    found = shutil.which("obsidian")
    if found:
        return found
    if os.name != "nt":
        return None
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    candidates = (
        local / "Obsidian" / "Obsidian.exe",
        local / "Programs" / "Obsidian" / "Obsidian.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Obsidian" / "Obsidian.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Obsidian" / "Obsidian.exe",
    )
    return str(next((path for path in candidates if path.is_file()), "")) or None


def _install_obsidian_from_official_release() -> int:
    if os.name != "nt":
        sys.stderr.write("[arbor] automatic fallback install is currently supported on Windows only\n")
        return 1
    import urllib.request  # only this rare fallback needs it; hooks must start fast

    api = "https://api.github.com/repos/obsidianmd/obsidian-releases/releases/latest"
    try:
        request = urllib.request.Request(
            api,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "context-arbor"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            release = json.load(response)
        assets = release.get("assets", [])
        asset = next(
            item for item in assets
            if re.fullmatch(r"Obsidian-\d+(?:\.\d+)+\.exe", item.get("name", ""))
        )
        url = asset["browser_download_url"]
        if not url.startswith(
            "https://github.com/obsidianmd/obsidian-releases/releases/download/"
        ):
            raise RuntimeError("release asset is not hosted by the official Obsidian repository")
        with tempfile.TemporaryDirectory(prefix="arbor-obsidian-") as temp:
            installer = Path(temp) / asset["name"]
            urllib.request.urlretrieve(url, installer)
            proc = subprocess.run([str(installer), "/S"])
            return proc.returncode
    except (OSError, KeyError, StopIteration, ValueError, RuntimeError) as exc:
        sys.stderr.write(f"[arbor] official Obsidian install failed: {exc}\n")
        return 1


def _register_obsidian_vault(memory: Path) -> tuple[str | None, bool]:
    if os.name != "nt":
        return None, False
    appdata = Path(os.environ.get("APPDATA", ""))
    if not appdata:
        return None, False
    config = appdata / "obsidian" / "obsidian.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {"vaults": {}}
    if config.is_file():
        try:
            loaded = json.loads(read_text(config))
            if isinstance(loaded, dict):
                data = loaded
        except json.JSONDecodeError:
            backup = config.with_suffix(".json.invalid")
            shutil.copy2(config, backup)
    vaults = data.setdefault("vaults", {})
    if not isinstance(vaults, dict):
        vaults = {}
        data["vaults"] = vaults
    normalized = str(memory.resolve())
    existing = next(
        (key for key, value in vaults.items()
         if isinstance(value, dict)
         and os.path.normcase(value.get("path", "")) == os.path.normcase(normalized)),
        None,
    )
    key = existing or hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    created = existing is None
    vaults[key] = {
        **(vaults.get(key, {}) if isinstance(vaults.get(key), dict) else {}),
        "path": normalized,
        "ts": round(datetime.datetime.now().timestamp() * 1000),
        "open": True,
    }
    config.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    return key, created


def _restart_obsidian_if_running() -> None:
    if os.name != "nt":
        return
    check = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq Obsidian.exe", "/NH"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if "Obsidian.exe" not in check.stdout:
        return
    subprocess.run(
        ["taskkill", "/IM", "Obsidian.exe", "/T"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    import time
    time.sleep(2)


def cmd_memory_open(args: argparse.Namespace) -> int:
    memory = _memory_root(args.path)
    if not memory.is_dir():
        sys.stderr.write(f"[arbor] memory vault not found: {memory}\n")
        return 2
    obsidian = _find_obsidian()
    if not obsidian and args.install_obsidian:
        winget = shutil.which("winget")
        if winget:
            proc = subprocess.run([
                winget, "install", "--id", "Obsidian.Obsidian", "-e",
                "--accept-package-agreements", "--accept-source-agreements",
            ], text=True)
            if proc.returncode != 0:
                return proc.returncode
        else:
            result = _install_obsidian_from_official_release()
            if result != 0:
                return result
        obsidian = _find_obsidian()
    if not obsidian:
        sys.stderr.write("[arbor] Obsidian not found. Re-run with --install-obsidian or open "
                         f"this folder manually: {memory}\n")
        return 1
    _, created = _register_obsidian_vault(memory)
    if created:
        _restart_obsidian_if_running()
    # Obsidian assigns the real vault ID internally. The stable public reference
    # after registering the path is the folder/vault name, not our config key.
    vault_uri = "obsidian://open?vault=" + urllib.parse.quote(memory.name, safe="")
    subprocess.Popen([obsidian, vault_uri])
    print(f"# opened Obsidian vault: {memory}")
    return 0


SESSION_STATE_PATH = Path(".arbor") / "session-state.md"
LEGACY_SESSION_STATE_PATH = Path(".ctx") / "session-state.md"


STATE_SECTIONS = ("Agent notes", "Auto snapshot")


STATE_HEADER = (
    "# Session state -- survives /compact, /clear and restarts.\n"
    "# Managed by `arbor session save` (agent) / `arbor session snapshot` (auto).\n"
)


def _read_hook_event() -> dict:
    """Parse the hook JSON Claude Code pipes on stdin; {} when run by hand.
    A hook's stdin is written-then-closed immediately, but a MANUAL run may
    inherit a pipe that never closes -- so the read happens on a daemon thread
    with a 1s deadline instead of blocking the shell forever. Never raises."""
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return {}
        import threading
        buf: list[str] = []
        reader = threading.Thread(target=lambda: buf.append(sys.stdin.read()),
                                  daemon=True)
        reader.start()
        reader.join(1.0)
        if not buf:
            return {}  # stdin open but silent: a by-hand run, not a hook
        obj = json.loads(buf[0] or "{}")
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _tail_text(path: Path, max_bytes: int) -> str:
    """Last max_bytes of a file, decoded leniently -- transcripts grow to tens
    of MB and the records that matter are at the end."""
    with path.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - max_bytes))
        return fh.read().decode("utf-8", errors="replace")


def _last_context_tokens(transcript: Path) -> int:
    """Live context size: total input of the LAST main-chain assistant turn
    (uncached + cache read + cache write) -- what every further turn re-sends."""
    latest = 0
    for line in _tail_text(transcript, 400_000).splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict) or obj.get("isSidechain"):
            continue
        msg = obj.get("message")
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        usage = msg.get("usage")
        if isinstance(usage, dict):
            tok = sum(int(usage.get(k, 0) or 0) for k in (
                "input_tokens", "cache_read_input_tokens",
                "cache_creation_input_tokens"))
            if tok:
                latest = tok
    return latest


def _state_sections_read() -> dict[str, str]:
    if not SESSION_STATE_PATH.is_file() and LEGACY_SESSION_STATE_PATH.is_file():
        SESSION_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(LEGACY_SESSION_STATE_PATH), str(SESSION_STATE_PATH))
    if not SESSION_STATE_PATH.is_file():
        return {}
    sections: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for ln in read_text(SESSION_STATE_PATH).splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", ln)
        if m and m.group(1) in STATE_SECTIONS:
            if current:
                sections[current] = "\n".join(buf).strip()
            current, buf = m.group(1), []
        elif current is not None:
            buf.append(ln)
    if current:
        sections[current] = "\n".join(buf).strip()
    return sections


def _state_write(agent: str | None, auto: str | None) -> None:
    """Update one section of the state file, preserving the other (None=keep)."""
    sections = _state_sections_read()
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    if agent is not None:
        sections["Agent notes"] = f"_Saved: {stamp}_\n\n{agent.strip()}"
    if auto is not None:
        sections["Auto snapshot"] = f"_Saved: {stamp}_\n\n{auto.strip()}"
    parts = [STATE_HEADER]
    for name in STATE_SECTIONS:
        if sections.get(name):
            parts.append(f"## {name}\n\n{sections[name]}\n")
    SESSION_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SESSION_STATE_PATH.write_text("\n".join(parts), encoding="utf-8")


_TRANSCRIPT_NOISE_RE = re.compile(
    r"<(?:local-command|command-name|command-message|command-args|system-reminder|task-notification)"
    r"|^\s*Caveat:|^\[Request interrupted"
    r"|^This session is being continued", re.IGNORECASE)


_EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


_SHELL_TOOLS = {"Bash", "PowerShell"}

# The state file is re-injected into contexts and sits on disk: keep credentials out.
_SECRET_RES = (
    re.compile(r"((?:\$env:|export\s+|set\s+)?[A-Za-z_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD)"
               r"[A-Za-z_]*\s*=\s*)(['\"]?)[^\s'\";]+\2", re.IGNORECASE),
    re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[abpr]-[A-Za-z0-9-]{10,}"
               r"|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,})"),
    re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE),
)


def _redact_secrets(text: str) -> str:
    assign, token, bearer = _SECRET_RES
    text = assign.sub(lambda m: f"{m.group(1)}{m.group(2)}<redacted>{m.group(2)}", text)
    text = token.sub("<redacted>", text)
    return bearer.sub(lambda m: f"{m.group(1)}<redacted>", text)


def _extract_session_facts(transcript: Path) -> tuple[list[str], list[str]]:
    """Deterministic facts from the transcript tail: the last real user asks
    (what the work is) and the files the agent edited (where it happened).
    No LLM. This bounded extract is partial and does not preserve the full session."""
    facts = _session_facts(transcript)
    return facts["asks"], facts["files"]


def _session_facts(transcript: Path) -> dict:
    """One pass over the transcript tail: user asks, edited files, the agent's last
    reply (where it stopped) and commands it left running in the background (work
    that outlives the context, e.g. a benchmark run)."""
    asks: list[str] = []
    files: dict[str, None] = {}
    background: dict[str, None] = {}
    last_reply = ""
    for line in _tail_text(transcript, 2_000_000).splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict) or obj.get("isSidechain"):
            continue
        msg = obj.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if msg.get("role") == "user":
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                text = " ".join(c.get("text", "") for c in content
                                if isinstance(c, dict) and c.get("type") == "text")
            else:
                text = ""
            text = text.strip()
            if not text or _TRANSCRIPT_NOISE_RE.search(text):
                continue
            text = _redact_secrets(text)
            asks.append(text[:280] + (" ..." if len(text) > 280 else ""))
        elif msg.get("role") == "assistant" and isinstance(content, list):
            for c in content:
                if not isinstance(c, dict):
                    continue
                if c.get("type") == "text" and str(c.get("text", "")).strip():
                    last_reply = str(c["text"]).strip()
                if c.get("type") != "tool_use":
                    continue
                inp = c.get("input") or {}
                if c.get("name") in _EDIT_TOOLS:
                    fp = inp.get("file_path") or inp.get("notebook_path")
                    if isinstance(fp, str):
                        files.pop(fp, None)  # re-insert: most-recent-last order
                        files[fp] = None
                elif c.get("name") in _SHELL_TOOLS and inp.get("run_in_background"):
                    cmd = _redact_secrets(" ".join(str(inp.get("command", "")).split()))
                    if cmd:
                        cmd = cmd[:240] + (" ..." if len(cmd) > 240 else "")
                        background.pop(cmd, None)
                        background[cmd] = None
    last_reply = _redact_secrets(last_reply)
    if len(last_reply) > 700:
        last_reply = last_reply[:700].rstrip() + " ..."
    return {"asks": asks[-6:], "files": list(files)[-15:],
            "background": list(background)[-5:], "last_reply": last_reply}


def cmd_session_save(args: argparse.Namespace) -> int:
    """Persist the agent's own distillate of the session (goal, decisions,
    open items, key paths) for recovery after /compact or /clear. The agent
    writes the content -- it knows the session; Arbor stores it deterministically
    and `restore` re-injects it after compaction at ~zero re-derivation cost."""
    note = sys.stdin.read() if args.stdin else (args.note or "")
    note = note.strip()
    if not note:
        sys.stderr.write('[arbor] session save: pass --note "..." or --stdin with content\n')
        return 2
    if len(note) > args.max_chars:
        note = note[: args.max_chars].rstrip() + "\n... [truncated by Arbor]"
    _state_write(agent=note, auto=None)
    print(f"# session state saved: {SESSION_STATE_PATH} (~{est_tokens(note):,} tok; "
          f"restore manually or via configured session hooks)")
    return 0


def _write_auto_snapshot(transcript: str | None) -> bool:
    """Deterministic transcript extract into the state file. True when written."""
    if not transcript or not Path(transcript).is_file():
        return False
    facts = _session_facts(Path(transcript))
    if not facts["asks"] and not facts["files"]:
        return False
    lines: list[str] = []
    if facts["asks"]:
        lines.append("Last user asks:")
        lines.extend(f"- {a}" for a in facts["asks"])
    if facts["files"]:
        lines.append("Files edited this session:")
        lines.extend(f"- {f}" for f in facts["files"])
    if facts["background"]:
        lines.append("Started in the background (may still be running; check before re-running):")
        lines.extend(f"- `{c}`" for c in facts["background"])
    if facts["last_reply"]:
        lines.append("Agent's last reply:")
        lines.append("> " + facts["last_reply"].replace("\n", "\n> "))
    _state_write(agent=None, auto="\n".join(lines))
    return True


HOOK_LOG_PATH = Path(".arbor") / "hook-log.jsonl"


def _log_hook_event(event: dict) -> None:
    """Keep the last 50 session-hook events (name, source/reason) so it is visible
    which events a client really sends -- the desktop app's clear arrives as a new
    session (`startup`), not as `clear`. Never raises."""
    if not event:
        return
    try:
        entry = {"t": datetime.datetime.now().isoformat(timespec="seconds"),
                 "event": event.get("hook_event_name"),
                 "source": event.get("source") or event.get("reason") or event.get("trigger")}
        old = read_text(HOOK_LOG_PATH).splitlines()[-49:] if HOOK_LOG_PATH.is_file() else []
        HOOK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        HOOK_LOG_PATH.write_text("\n".join(old + [json.dumps(entry)]) + "\n", encoding="utf-8")
    except Exception:
        pass


def _previous_transcript(current: str | None, max_age_hours: float) -> Path | None:
    """The newest other transcript of this project (Claude Code keeps one .jsonl per
    session in one directory), if it is fresh. A clear that starts a new session
    without a SessionEnd hook still leaves the old transcript there to snapshot."""
    if not current:
        return None
    cur = Path(current)
    try:
        others = [p for p in cur.parent.glob("*.jsonl") if p.name != cur.name]
        newest = max(others, key=lambda p: p.stat().st_mtime, default=None)
    except OSError:
        return None
    if newest is None or time.time() - newest.stat().st_mtime > max_age_hours * 3600:
        return None
    return newest


def cmd_session_snapshot(args: argparse.Namespace) -> int:
    """PreCompact / SessionEnd hook (also runnable by hand): deterministic
    transcript extract into the state file right before the context is dropped, so
    even a session the agent never distilled keeps its floor. Silent on error; never
    blocks."""
    try:
        event = _read_hook_event()
        _log_hook_event(event)
        if _write_auto_snapshot(event.get("transcript_path") or args.transcript):
            print(f"# auto snapshot written to {SESSION_STATE_PATH}")
    except Exception:  # a hook must never break the agent loop
        pass
    return 0


COMPACTION_MODES = ("off", "manual", "all")


def _config_read(root: Path) -> dict:
    try:
        loaded = json.loads(read_text(root / ".arbor" / "config.json"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _config_write(root: Path, data: dict) -> None:
    path = root / ".arbor" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cmd_session_compaction(args: argparse.Namespace) -> int:
    """Choose whether Claude Code may run its model-based compaction in this project.
    `/compact` and auto-compact are model calls that re-read the whole context and
    write a summary -- exactly the spend Arbor exists to avoid. `/clear` costs no model
    call, and the SessionEnd/SessionStart hooks carry the state across it."""
    root = _project_root(args.path)
    config = _config_read(root)
    if args.mode is None:
        print(f"# compaction guard: {config.get('compaction', 'off')} "
              f"(off = allow, manual = block /compact, all = also block auto-compact)")
        return 0
    config["compaction"] = args.mode
    _config_write(root, config)
    note = {
        "off": "model compaction is allowed again",
        "manual": "/compact is blocked; auto-compact still runs at the window limit",
        "all": "/compact and auto-compact are blocked; use /clear (state is restored)",
    }[args.mode]
    print(f"# compaction guard: {args.mode} -- {note}")
    if args.mode != "off":
        print("# needs the PreCompact hooks: run `python arbor.py init` once if this project "
              "predates v0.5")
    return 0


def cmd_session_compact_guard(args: argparse.Namespace) -> int:
    """PreCompact hook: snapshot the session, then refuse the compaction when the
    project opted in (exit 2 is Claude Code's documented way to block it, and stderr
    is shown to the user). Never raises -- a broken guard must not wedge the agent."""
    try:
        mode = _config_read(Path(".")).get("compaction", "off")
        blocked = mode == "all" or (mode == "manual" and args.trigger == "manual")
        if not blocked:
            return 0
        _write_auto_snapshot(_read_hook_event().get("transcript_path"))
        sys.stderr.write(
            "[arbor] compaction blocked: /compact and auto-compact are model calls that "
            "spend your limits. Run /clear instead -- the session is already saved and "
            "is restored, with the active task, in the fresh context. "
            "Allow compaction again: python arbor.py session compaction --mode off\n")
        return 2
    except Exception:
        return 0


def _active_task_excerpt(max_chars: int = 4000) -> str:
    """Open TASK entries of memory/NOW.md (the hot ring, capped at ~1500 tokens by
    design), or '' when nothing is active. Injecting them after a /clear saves the
    read-NOW.md round trip the agent would otherwise spend a turn on."""
    now = Path("memory") / "NOW.md"
    if not now.is_file():
        return ""
    blocks = [block.strip() for _id, block in _entry_blocks(read_text(now))
              if not _entry_is_closed(block)]
    text = "\n\n".join(blocks)
    return text if len(text) <= max_chars else text[:max_chars].rstrip() + "\n... [truncated]"


def cmd_session_restore(args: argparse.Namespace) -> int:
    """SessionStart hook (startup/clear/compact/resume): print the saved state so
    the harness injects it into the fresh context. Small by construction -- the
    point is to spend ~1k tokens instead of re-reading files to re-derive
    where the work stood. Run by hand it doubles as `show`."""
    try:
        event = _read_hook_event()
        _log_hook_event(event)
        source = str(event.get("source") or args.source or "manual")
        if source in {"startup", "clear"}:
            # The desktop app's clear opens a new session with no SessionEnd hook: snapshot
            # the session that just ended from its transcript, unless that already happened.
            prev = _previous_transcript(event.get("transcript_path"), args.max_age_hours)
            if prev is not None and (not SESSION_STATE_PATH.is_file()
                                     or prev.stat().st_mtime > SESSION_STATE_PATH.stat().st_mtime):
                _write_auto_snapshot(str(prev))
        has_state = SESSION_STATE_PATH.is_file()
        age_h = ((time.time() - SESSION_STATE_PATH.stat().st_mtime) / 3600.0
                 if has_state else 0.0)
        if source == "startup" and (not has_state or age_h > args.max_age_hours):
            return 0  # no recent work to continue: keep a fresh, unrelated session clean
        # The context is really gone (clear, compaction, a new session): hand back the task too.
        task = _active_task_excerpt() if source in {"clear", "compact", "startup"} else ""
        if not has_state and not task:
            return 0
        age = f" | saved {age_h:.1f}h ago" if has_state else ""
        print(f"[arbor session restore | source={source}{age}]")
        if has_state:
            # The file's own two-line header is for people opening it; it is noise in a context.
            text = read_text(SESSION_STATE_PATH).replace(STATE_HEADER, "", 1).strip()
            if len(text) > args.max_chars:
                text = text[: args.max_chars].rstrip() + \
                    "\n... [truncated; open .arbor/session-state.md]"
            print(text)
        if task:
            print("\n## Active task (memory/NOW.md)\n\n" + task)
        if _jev_config(Path("."))["enabled"]:
            print("\nJev is on: notes matched to each prompt arrive as `[jev]` context. Ask it "
                  "directly (works across languages): python arbor.py jev ask \"question\".")
        print("(This is a POINTER to where work stood, not ground truth: it can be "
              "stale or incomplete. Re-read a file before you change it; trust the "
              "code over this note on any conflict. Durable memory: memory/MEMORY.md; "
              "find code with `python arbor.py code find \"topic\"`.)")
    except Exception:  # a hook must never break the agent loop
        pass
    return 0


# Thresholds are GROWTH over the session's first turn, not absolute sizes: the first turn
# already carries the fixed prefix (system prompt, tools, CLAUDE.md, start-up injections;
# 60-70k on a real project), so an absolute 80k warns from the first minute. Growth per
# turn is roughly constant, a restart costs a fixed amount, and total cost is flat near
# its minimum at about +60-90k and doubles by +160k: warn at +60k, "now" at +120k.
CONTEXT_LIMIT_DEFAULTS = {"warn_growth": 60_000, "crit_growth": 120_000, "stop_growth": 0}


ASSUMED_PREFIX_TOKENS = 60_000


def _context_limits(args: argparse.Namespace, root: Path | None = None) -> dict[str, int]:
    """Built-in defaults, then `.arbor/config.json` ("context"), then command-line values."""
    limits = dict(CONTEXT_LIMIT_DEFAULTS)
    saved = _config_read(root or Path(".")).get("context")
    if isinstance(saved, dict):
        for key in limits:
            try:
                limits[key] = max(0, int(saved.get(key, limits[key])))
            except (TypeError, ValueError):
                pass
    for key in limits:
        value = getattr(args, key, None)
        if value is not None:
            limits[key] = max(0, int(value))
    return limits


def _first_context_tokens(transcript: Path) -> int:
    """Context of the first main-chain assistant turn: the fixed prefix. 0 when the head of
    the transcript has none (then callers assume a typical prefix)."""
    with transcript.open("rb") as fh:
        head = fh.read(400_000).decode("utf-8", errors="replace")
    for line in head.splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict) or obj.get("isSidechain"):
            continue
        msg = obj.get("message")
        usage = msg.get("usage") if isinstance(msg, dict) and msg.get("role") == "assistant" else None
        if isinstance(usage, dict):
            tok = sum(int(usage.get(k, 0) or 0) for k in (
                "input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
            if tok:
                return tok
    return 0


def _context_growth(transcript: Path) -> tuple[int, int]:
    """(live context, growth over the session's first turn)."""
    now = _last_context_tokens(transcript)
    base = _first_context_tokens(transcript) or min(now, ASSUMED_PREFIX_TOKENS)
    return now, max(0, now - base)


def cmd_session_gauge(args: argparse.Namespace) -> int:
    """UserPromptSubmit hook: inject ONE short line only when the live context
    has grown expensive. Reads the latest input usage from a Claude Code transcript as a
    context-size indicator, not a billing or quota measurement. Below the threshold it prints nothing and costs nothing."""
    try:
        event = _read_hook_event()
        tp = event.get("transcript_path") or args.transcript
        if not tp or not Path(tp).is_file():
            return 0
        ctx_tok, growth = _context_growth(Path(tp))
        limits = _context_limits(args)
        warn_abs, crit_abs = getattr(args, "warn_tokens", None), getattr(args, "crit_tokens", None)
        if warn_abs is not None or crit_abs is not None:  # explicit absolute thresholds win
            warn_at, crit_at, measured = (warn_abs or 0), (crit_abs or 10 ** 12), ctx_tok
        else:
            warn_at, crit_at, measured = limits["warn_growth"], limits["crit_growth"], growth
        if measured < warn_at:
            return 0
        if SESSION_STATE_PATH.is_file():
            age_h = (time.time() - SESSION_STATE_PATH.stat().st_mtime) / 3600.0
            state = f"state saved {age_h:.1f}h ago"
        else:
            state = "state NOT saved"
        push = "clear NOW" if measured >= crit_at else "clear soon"
        print(f"[arbor gauge] live context ~{ctx_tok / 1000:.0f}k tok (+{growth / 1000:.0f}k "
              f"since the session started) -- every turn re-sends it all; {state}. Batch "
              f"remaining work, save state (`python arbor.py session save --stdin`), then "
              f"ask the user to run /clear ({push}): it makes no model call and Arbor "
              f"restores the state. Do not suggest /compact -- that is a model call.")
    except Exception:  # a hook must never break the agent loop
        pass
    return 0


GUARD_STATE_REL = Path(".arbor") / "guard-state.json"


_GUARD_ALLOW_RE = re.compile(
    r"^\s*(?:cd\s+(?:\"[^\"]*\"|'[^']*'|\S+)\s*(?:&&|;)\s*)?(?:python3?|py)\s+(?:\./)?"
    r"arbor\.py\s+(?:session|memory)\b")


def _hook_json(event_name: str, **fields: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event_name, **fields}},
                     ensure_ascii=False))


def _guard_state_read() -> dict:
    try:
        loaded = json.loads(read_text(GUARD_STATE_REL))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _guard_state_write(state: dict) -> None:
    try:
        GUARD_STATE_REL.parent.mkdir(parents=True, exist_ok=True)
        GUARD_STATE_REL.write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        pass


def cmd_session_guard(args: argparse.Namespace) -> int:
    """PreToolUse hook: the per-tool-call twin of `gauge`. A long autonomous run never
    passes through UserPromptSubmit, so it can grow from 70k to 800k with nobody
    looking; this looks on every tool call but speaks only when a threshold is crossed
    (once per level per session). With `session limit --stop N` (opt-in) it goes further:
    past +N tokens it snapshots the session and refuses every tool call except
    `arbor.py session|memory ...`, so the agent stops and hands the user a /clear."""
    try:
        event = _read_hook_event()
        tp = event.get("transcript_path") or args.transcript
        if not tp or not Path(tp).is_file():
            return 0
        ctx_tok, growth = _context_growth(Path(tp))
        limits = _context_limits(args)
        stop = limits["stop_growth"]
        if stop and growth >= stop:
            command = (event.get("tool_input") or {}).get("command") or ""
            if event.get("tool_name") == "Bash" and _GUARD_ALLOW_RE.match(command):
                return 0
            _write_auto_snapshot(tp)
            _hook_json(
                "PreToolUse", permissionDecision="deny",
                permissionDecisionReason=(
                    f"[arbor guard] Context limit reached: ~{ctx_tok / 1000:.0f}k tokens "
                    f"(+{growth / 1000:.0f}k since the session started, limit +{stop / 1000:.0f}k). "
                    "Every further tool call re-sends all of it. The session state was saved "
                    "automatically. Stop here and tell the user to run /clear: Arbor restores "
                    "the task in the fresh context. (`python arbor.py session save` is still "
                    "allowed; lift the limit with `python arbor.py session limit --stop 0`.)"))
            return 0
        level = 2 if growth >= limits["crit_growth"] else 1 if growth >= limits["warn_growth"] else 0
        state = _guard_state_read()
        session = str(event.get("session_id") or "")
        seen = int(state.get("level", 0)) if state.get("session") == session else 0
        if level != seen:
            _guard_state_write({"session": session, "level": level})
        if level > seen:
            _hook_json(
                "PreToolUse",
                additionalContext=(
                    f"[arbor guard] live context ~{ctx_tok / 1000:.0f}k tok "
                    f"(+{growth / 1000:.0f}k since the session started); every tool call "
                    "re-sends all of it. Finish the current step, save state "
                    "(`python arbor.py session save --stdin`) and tell the user to run /clear"
                    f"{' NOW' if level == 2 else ' at the next break'} -- it makes no model call "
                    "and Arbor restores the state. Do not suggest /compact."))
    except Exception:  # a hook must never break the agent loop
        pass
    return 0


def cmd_session_limit(args: argparse.Namespace) -> int:
    """Show or set the context thresholds (tokens of growth over the session's first turn)."""
    root = _project_root(args.path)
    config = _config_read(root)
    saved = dict(config["context"]) if isinstance(config.get("context"), dict) else {}
    changed = False
    for key in CONTEXT_LIMIT_DEFAULTS:
        value = getattr(args, key, None)
        if value is not None:
            saved[key] = max(0, value)
            changed = True
    if changed:
        config["context"] = saved
        _config_write(root, config)
    limits = _context_limits(argparse.Namespace(), root)
    stop = f"+{limits['stop_growth'] // 1000}k" if limits["stop_growth"] else "off"
    print(f"# context limits (tokens above the session's first turn): "
          f"warn +{limits['warn_growth'] // 1000}k, clear-now +{limits['crit_growth'] // 1000}k, "
          f"hard stop {stop}")
    if getattr(args, "stop_growth", None) is not None:
        note = _set_guard_hook(root / ".claude" / "settings.local.json", args.stop_growth > 0)
        print(f"# per-tool-call guard hook: {note}"
              + (" (adds ~0.1 s to every tool call)" if args.stop_growth > 0 else ""))
    return 0


GUARD_HOOK_COMMAND = _hook_command("session guard")


def _set_guard_hook(path: Path, enabled: bool) -> str:
    """Install or remove the PreToolUse guard in a Claude settings file. Opt-in: the hook
    starts a Python process on every tool call (~0.1 s), so only a project that asked for
    a hard stop pays for it."""
    data: dict = {}
    if path.is_file():
        try:
            loaded = json.loads(read_text(path))
        except json.JSONDecodeError:
            return f"left alone ({path.name} is not valid JSON)"
        data = loaded if isinstance(loaded, dict) else {}
    upgraded = _upgrade_hook_commands(data.setdefault("hooks", {}))
    groups = data["hooks"].setdefault("PreToolUse", [])

    def is_guard(group: object) -> bool:
        return isinstance(group, dict) and any(
            isinstance(h, dict) and h.get("command") == GUARD_HOOK_COMMAND
            for h in group.get("hooks", []))

    present = any(is_guard(g) for g in groups)
    if enabled == present and not upgraded:
        return "already installed" if present else "not installed"
    if enabled and not present:
        groups.append({"hooks": [{"type": "command", "command": GUARD_HOOK_COMMAND}]})
    elif not enabled:
        groups[:] = [g for g in groups if not is_guard(g)]
    if not groups:
        del data["hooks"]["PreToolUse"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if enabled == present:
        return "already installed" if present else "not installed"
    return "installed" if enabled else "removed"


# ---------------------------------------------------------------------------
# Code index: find code without reading whole files. A file/symbol table built
# by static parsing (Python `ast`, line rules for the rest) -- no model, no
# network. Agents ask it short questions instead of paging through sources, so
# less text lands in the context that every later turn re-sends.
# ---------------------------------------------------------------------------


CODE_INDEX_REL = Path(".arbor") / "code-index.json"


CODE_INDEX_VERSION = 1


CODE_MAX_FILE_BYTES = 400_000


CODE_MAX_FILES = 20_000


CODE_MAX_SYMBOLS_PER_FILE = 500


CODE_SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn", ".arbor", ".ctx", ".obsidian", ".idea", ".vscode",
    ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache", "__pycache__",
    "node_modules", "dist", "build", ".next", "coverage",
})


CODE_SKIP_SUFFIXES = (".lock", "-lock.json", ".min.js", ".min.css", ".map")


CODE_SECRET_RE = re.compile(
    r"(?i)^(?:\.env(?:\..+)?|.+\.(?:pem|key|p12|pfx)|id_(?:rsa|dsa|ecdsa|ed25519))$")


CODE_LANGS = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".vue": "javascript", ".svelte": "javascript",
    ".go": "go", ".rs": "rust", ".java": "java", ".kt": "kotlin", ".cs": "csharp",
    ".rb": "ruby", ".php": "php", ".sh": "shell", ".bash": "shell", ".ps1": "powershell",
    ".md": "markdown", ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".hpp": "cpp",
    ".swift": "swift", ".sql": "sql", ".html": "html", ".css": "css", ".scss": "css",
    ".json": "json", ".toml": "toml", ".yaml": "yaml", ".yml": "yaml", ".ini": "ini",
    ".gd": "gdscript",
}


CODE_NAMED_FILES = {"dockerfile": "docker", "makefile": "make"}


# Symbol kinds that own members: a `def`/`fn` found inside one becomes `Owner.name`.
CODE_CONTAINER_KINDS = frozenset(
    {"class", "interface", "struct", "enum", "trait", "impl", "module", "object", "record"})


# Names a line rule can capture by mistake (`else if (x) {`, `return foo(a) {`).
_NOT_SYMBOLS = frozenset({
    "if", "for", "while", "switch", "catch", "return", "new", "throw", "else", "try", "do",
    "synchronized", "using", "lock", "foreach", "when", "elif", "with", "match", "await",
})


_JS_NAME = r"[A-Za-z_$][\w$]*"


_MODS = (r"(?:(?:public|private|protected|internal|static|final|abstract|sealed|open|data|"
         r"partial|override|virtual|async|suspend|synchronized|native|export)\s+)*")


# (pattern, kind, member_only). `kind=None` reads it from the pattern's `kind` group;
# `member_only` rules only count inside a container (methods), so `if (x) {` at
# statement level is never mistaken for a method.
_CODE_RULES: dict[str, tuple[tuple[re.Pattern[str], str | None, bool], ...]] = {}


def _rules(*specs: tuple[str, str | None, bool]) -> tuple[tuple[re.Pattern[str], str | None, bool], ...]:
    return tuple((re.compile(pattern), kind, member) for pattern, kind, member in specs)


_JS_RULES = _rules(
    (rf"\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*(?P<name>{_JS_NAME})",
     "function", False),
    (rf"\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+(?P<name>{_JS_NAME})",
     "class", False),
    (rf"\s*(?:export\s+)?interface\s+(?P<name>{_JS_NAME})", "interface", False),
    (rf"\s*(?:export\s+)?(?:declare\s+)?type\s+(?P<name>{_JS_NAME})\s*(?:<[^=]*>)?\s*=",
     "type", False),
    (rf"\s*(?:export\s+)?(?:declare\s+)?(?:const\s+)?enum\s+(?P<name>{_JS_NAME})",
     "enum", False),
    (rf"\s*(?:export\s+)?(?:const|let|var)\s+(?P<name>{_JS_NAME})\s*(?::[^=]+)?=\s*"
     rf"(?:async\s*)?(?:\([^)]*\)|{_JS_NAME})\s*(?::[^=]+?)?=>", "function", False),
    (rf"\s*(?:export\s+)?const\s+(?P<name>[A-Z][A-Z0-9_]+)\s*(?::[^=]+)?=", "const", False),
    (rf"\s+(?:(?:public|private|protected|static|async|override|readonly|abstract|get|set)\s+)*"
     rf"(?P<name>{_JS_NAME})\s*(?:<[^>]*>)?\s*\([^)]*\)\s*(?::\s*[^{{;=]+)?\{{", "method", True),
)


_CODE_RULES.update({
    "javascript": _JS_RULES,
    "typescript": _JS_RULES,
    "go": _rules(
        (r"func\s+\((?:\w+\s+)?\*?(?P<recv>\w+)(?:\[[^\]]*\])?\)\s*(?P<name>\w+)", "method", False),
        (r"func\s+(?P<name>\w+)", "function", False),
        (r"type\s+(?P<name>\w+)\s+struct\b", "struct", False),
        (r"type\s+(?P<name>\w+)\s+interface\b", "interface", False),
        (r"type\s+(?P<name>\w+)\s+\S", "type", False),
    ),
    "rust": _rules(
        (r"\s*(?:pub(?:\([^)]*\))?\s+)?(?:const\s+)?(?:async\s+)?(?:unsafe\s+)?"
         r"(?:extern\s+\"[^\"]*\"\s+)?fn\s+(?P<name>\w+)", "function", False),
        (r"\s*(?:pub(?:\([^)]*\))?\s+)?(?P<kind>struct|enum|trait|union)\s+(?P<name>\w+)",
         None, False),
        (r"\s*(?:pub(?:\([^)]*\))?\s+)?mod\s+(?P<name>\w+)\s*\{", "module", False),
        (r"\s*impl(?:<[^>]*>)?\s+(?:[\w:<>, ]+?\s+for\s+)?(?P<name>[\w:]+)", "impl", False),
    ),
    "java": _rules(
        (rf"\s*{_MODS}(?P<kind>class|interface|enum|record)\s+(?P<name>\w+)", None, False),
        (rf"\s+{_MODS}(?:[\w<>\[\],.?]+\s+)+(?P<name>\w+)\s*\([^;{{}}]*\)\s*"
         r"(?:throws\s+[\w., ]+)?\s*\{?\s*$", "method", True),
    ),
    "kotlin": _rules(
        (rf"\s*{_MODS}(?P<kind>class|interface|enum|object)(?:\s+class)?\s+(?P<name>\w+)",
         None, False),
        (rf"\s*{_MODS}fun\s+(?:<[^>]*>\s*)?(?:[\w.<>?]+\.)?(?P<name>\w+)\s*\(", "function", False),
    ),
    "csharp": _rules(
        (rf"\s*{_MODS}(?P<kind>class|interface|enum|record|struct)\s+(?P<name>\w+)", None, False),
        (rf"\s+{_MODS}(?:[\w<>\[\],.?]+\s+)+(?P<name>\w+)\s*\([^;{{}}]*\)\s*(?:=>|\{{)?\s*$",
         "method", True),
    ),
    "ruby": _rules(
        (r"\s*(?P<kind>class|module)\s+(?P<name>[A-Z][\w:]*)", None, False),
        (r"\s*def\s+(?:self\.)?(?P<name>[\w?!=]+)", "function", False),
    ),
    "php": _rules(
        (r"\s*(?:abstract\s+|final\s+)?(?P<kind>class|interface|trait|enum)\s+(?P<name>\w+)",
         None, False),
        (r"\s*(?:(?:public|private|protected|static|abstract|final)\s+)*function\s+&?(?P<name>\w+)",
         "function", False),
    ),
    "shell": _rules(
        (r"\s*function\s+(?P<name>[A-Za-z_][\w:-]*)", "function", False),
        (r"\s*(?P<name>[A-Za-z_][\w:-]*)\s*\(\)\s*\{?", "function", False),
    ),
    "powershell": _rules(
        (r"(?i)\s*function\s+(?P<name>[\w-]+)", "function", False),
    ),
    # A .gd file is one class: `class_name` names it, inner `class` blocks own members,
    # and the `@export` properties are its inspector interface. Plain `var` lines are
    # state, not landmarks, and `refs` finds them.
    "gdscript": _rules(
        (r"class_name\s+(?P<name>[A-Za-z_]\w*)", "class", False),
        (r"\s*class\s+(?P<name>[A-Za-z_]\w*)", "class", False),
        (r"\s*(?:static\s+)?func\s+(?P<name>[A-Za-z_]\w*)", "function", False),
        (r"\s*signal\s+(?P<name>[A-Za-z_]\w*)", "signal", False),
        (r"\s*enum\s+(?P<name>[A-Za-z_]\w*)", "enum", False),
        (r"\s*const\s+(?P<name>[A-Z]\w*)", "const", False),
        (r"\s*@export\w*(?:\([^)]*\))?\s+(?:static\s+)?var\s+(?P<name>[A-Za-z_]\w*)",
         "property", False),
    ),
})


_CLOSER_RE = re.compile(r"^(?:[\}\)\]]|(?:end|fi|esac|done)\b)")


def _first_line(text: str, limit: int = 110) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _block_end(lines: list[str], index: int, indent: int) -> int:
    """Heuristic 1-based end line of the block that starts at lines[index]: the last
    line before the next non-blank line indented at or below `indent`. A closer
    (`}`, `)`, `end`, ...) or a lone `{` at that indent belongs to the block. Exact for
    formatted code; Python uses `ast` instead and never gets here."""
    last = index
    for j in range(index + 1, len(lines)):
        line = lines[j]
        stripped = line.strip()
        if not stripped:
            continue
        level = len(line) - len(line.lstrip())
        if level <= indent:
            if level == indent and (_CLOSER_RE.match(stripped) or stripped == "{"):
                last = j
                if stripped == "{":
                    continue
            break
        last = j
    return last + 1


def _comment_text(line: str) -> str:
    text = re.sub(r"^(?:/\*+[*!]?|\*+/?|//+[/!]?|#+|--+)\s*", "", line.strip())
    return text.rstrip("*/ ").strip()


def _leading_comment(lines: list[str], index: int) -> str:
    """First text line of the comment block directly above lines[index]."""
    block: list[str] = []
    k = index - 1
    while k >= 0:
        stripped = lines[k].strip()
        if not stripped:
            break
        if stripped.startswith(("@", "#[")):
            k -= 1  # decorator / attribute between the comment and the symbol
            continue
        if stripped.startswith(("//", "#", "*", "/*", "--")) or stripped.endswith("*/"):
            block.append(stripped)
            k -= 1
            continue
        break
    for stripped in reversed(block):
        text = _comment_text(stripped)
        if text and not text.startswith(("!", "@", "eslint", "prettier")):
            return _first_line(text, 160)
    return ""


def _file_comment(lines: list[str]) -> str:
    """First text line of the file's header comment -- a stand-in for a module docstring.
    A comment counts only when a blank line follows it; otherwise it documents the first
    declaration (a Go `// Server ...` above `type Server`), not the file."""
    skip = ("#!", "<?php", "'use strict'", '"use strict"', "package ", "namespace ",
            "class_name ", "extends ", "@tool", "@icon(")
    head = lines[:40]
    i = 0
    while i < len(head) and (not head[i].strip() or head[i].strip().startswith(skip)):
        i += 1
    block: list[str] = []
    while i < len(head) and head[i].strip().startswith(("//", "#", "/*", "*", "--", "<!--")):
        block.append(head[i].strip())
        i += 1
    if not block or (i < len(head) and head[i].strip() and not block[0].startswith(("/*", "<!--"))):
        return ""
    for line in block:
        text = _comment_text(line.replace("<!--", "").replace("-->", ""))
        if text:
            return _first_line(text, 160)
    return ""


def _py_symbols(text: str) -> tuple[str, list[dict]] | None:
    """(module summary, symbols) from `ast`; None when the file does not parse."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return None
    symbols: list[dict] = []

    def visit(body: list[ast.stmt], owner: str) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                kind = "class"
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = "method" if owner else "function"
            elif (not owner and isinstance(node, ast.Assign) and len(node.targets) == 1
                  and isinstance(node.targets[0], ast.Name) and node.targets[0].id.isupper()):
                symbols.append({"n": node.targets[0].id, "k": "const", "l": node.lineno,
                                "e": node.end_lineno or node.lineno, "d": ""})
                continue
            else:
                continue
            name = f"{owner}.{node.name}" if owner else node.name
            first = min([node.lineno] + [d.lineno for d in node.decorator_list])
            doc = (ast.get_docstring(node) or "").strip().split("\n\n")[0]
            symbols.append({"n": name, "k": kind, "l": first,
                            "e": node.end_lineno or node.lineno, "d": _first_line(doc, 160)})
            if isinstance(node, ast.ClassDef):
                visit(node.body, name)

    visit(tree.body, "")
    summary = _first_line((ast.get_docstring(tree) or "").strip().split("\n\n")[0])
    return summary, symbols


def _md_symbols(lines: list[str]) -> tuple[str, list[dict]]:
    heads: list[tuple[int, str, int]] = []
    fenced = False
    for number, line in enumerate(lines, 1):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced:
            continue
        match = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if match:
            heads.append((len(match.group(1)), match.group(2), number))
    symbols = []
    for i, (level, title, number) in enumerate(heads):
        end = next((n - 1 for lv, _t, n in heads[i + 1:] if lv <= level), len(lines))
        symbols.append({"n": title, "k": "section", "l": number, "e": end, "d": ""})
    return (_first_line(heads[0][1]) if heads else ""), symbols


def _nest_symbols(found: list[dict]) -> list[dict]:
    """Attach members to their owners by line range and drop statement-level noise:
    a member-only match with no container, or anything declared inside a function body."""
    kept: list[dict] = []
    stack: list[dict] = []
    for sym in found:
        while stack and stack[-1]["e"] < sym["l"]:
            stack.pop()
        owner = stack[-1] if stack else None
        if owner is None:
            if sym["_member"]:
                continue
        elif owner["k"] in CODE_CONTAINER_KINDS:
            sym["n"] = f"{owner['n']}.{sym['n']}"
            if sym["k"] == "function":
                sym["k"] = "method"
        else:
            continue
        kept.append(sym)
        stack.append(sym)
    for sym in kept:
        sym.pop("_member", None)
    return kept


def _regex_symbols(lang: str, lines: list[str]) -> list[dict]:
    rules = _CODE_RULES.get(lang, ())
    found: list[dict] = []
    for i, line in enumerate(lines):
        if not line.strip() or len(line) > 400:
            continue
        for pattern, kind, member_only in rules:
            match = pattern.match(line)
            if not match or (member_only and match.group("name") in _NOT_SYMBOLS):
                continue
            parts = match.groupdict()
            name = f"{parts['recv']}.{parts['name']}" if parts.get("recv") else parts["name"]
            indent = len(line) - len(line.lstrip())
            found.append({"n": name, "k": kind or parts["kind"], "l": i + 1,
                          "e": _block_end(lines, i, indent),
                          "d": _leading_comment(lines, i), "_member": member_only})
            break
    return _nest_symbols(found)


def _index_file(path: Path, info: os.stat_result) -> dict | None:
    lang = (CODE_LANGS.get(path.suffix.lower())
            or CODE_NAMED_FILES.get(path.name.lower()))
    if lang is None:
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:4096]:
        return None
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    summary, symbols = "", []
    if lang == "python":
        parsed = _py_symbols(text)
        if parsed:
            summary, symbols = parsed
    elif lang == "markdown":
        summary, symbols = _md_symbols(lines)
    elif lang in _CODE_RULES:
        symbols = _regex_symbols(lang, lines)
    if not summary and lang != "markdown":
        summary = _file_comment(lines)
    return {"lang": lang, "size": info.st_size, "mtime": info.st_mtime_ns,
            "lines": len(lines), "summary": summary,
            "symbols": symbols[:CODE_MAX_SYMBOLS_PER_FILE]}


def _code_candidates(root: Path) -> list[str]:
    """Project-relative POSIX paths worth indexing: tracked and untracked-but-not-ignored
    files when git is available (so .gitignore is honoured exactly), a filtered walk
    otherwise. The memory vault is skipped -- `memory query` already covers it."""
    rels: list[str] = []
    if (root / ".git").exists() and shutil.which("git"):
        try:
            out = subprocess.run(
                ["git", "-C", str(root), "ls-files", "-co", "--exclude-standard", "-z"],
                capture_output=True, timeout=30, check=True).stdout
            rels = [p for p in out.decode("utf-8", errors="replace").split("\0") if p]
        except (OSError, subprocess.SubprocessError):
            rels = []
    if not rels:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in CODE_SKIP_DIRS]
            base = Path(dirpath).relative_to(root)
            rels.extend((base / name).as_posix() for name in filenames)
    vault = (root / "memory" / "MEMORY.md").is_file()
    kept = []
    for rel in rels:
        parts = rel.split("/")
        name = parts[-1]
        if any(part in CODE_SKIP_DIRS for part in parts[:-1]):
            continue
        if vault and parts[0] == "memory":
            continue
        if CODE_SECRET_RE.match(name) or name.lower().endswith(CODE_SKIP_SUFFIXES):
            continue
        kept.append(rel)
    return kept


def _code_index(root: Path, refresh: bool = True) -> tuple[dict, int]:
    """Load the index, re-parsing only files whose size or mtime changed. Returns
    (index, files_updated). A stat pass over the tree is all a warm refresh costs, so
    every `code` command refreshes first and the agent never has to think about it."""
    path = root / CODE_INDEX_REL
    stored: dict = {}
    if path.is_file():
        try:
            loaded = json.loads(read_text(path))
            if (isinstance(loaded, dict) and loaded.get("version") == CODE_INDEX_VERSION
                    and isinstance(loaded.get("files"), dict)):
                stored = loaded["files"]
        except json.JSONDecodeError:
            pass
    if not refresh:
        return {"version": CODE_INDEX_VERSION, "files": stored}, 0
    files: dict[str, dict] = {}
    updated = 0
    for rel in _code_candidates(root)[:CODE_MAX_FILES]:
        full = root / rel
        try:
            info = full.stat()
        except OSError:
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_size > CODE_MAX_FILE_BYTES:
            continue
        record = stored.get(rel)
        if record and record.get("mtime") == info.st_mtime_ns and record.get("size") == info.st_size:
            files[rel] = record
            continue
        record = _index_file(full, info)
        if record is not None:
            files[rel] = record
            updated += 1
    index = {"version": CODE_INDEX_VERSION, "files": files}
    if updated or set(files) != set(stored) or not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({**index, "built": datetime.datetime.now().isoformat(
            timespec="seconds")}, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8")
    return index, updated


_TEST_PATH_RE = re.compile(r"(?i)(?:^|/)(?:tests?|__tests__|spec)/|(?:^|/)test_[^/]*$|[._]tests?\.[^/]*$|\.spec\.[^/]*$")


_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _name_terms(text: str) -> list[str]:
    """Lowercase words of an identifier or phrase: `parseHTTPRequest` -> parse http request."""
    spaced = _CAMEL_RE.sub(" ", re.sub(r"[_\-./\\:]+", " ", text))
    return [word.lower() for word in _WORD_RE.findall(spaced)]


def _code_find(index: dict, query: str, top: int,
               kind: str | None = None) -> list[tuple[float, str, dict | None]]:
    """Rank symbols and files for a query: exact name > name words > doc line > path.
    Deterministic lexical scoring (same spirit as `_retrieve`), no model."""
    qterms = list(dict.fromkeys(_name_terms(query)))
    if not qterms:
        return []
    flat = re.sub(r"\W+", "", query).lower()
    hits: list[tuple[float, str, dict | None]] = []
    for rel, record in index["files"].items():
        path_terms = set(_name_terms(rel))
        path_hits = sum(1 for t in qterms if t in path_terms)
        weight = 0.8 if _TEST_PATH_RE.search(rel) else 1.0  # definitions before their tests
        for sym in record["symbols"]:
            if kind and sym["k"] != kind:
                continue
            # A member's own name is the strong signal; its owner class only a weak one,
            # otherwise every method of `RelationsTests` would match "relations" in full.
            owner, _dot, own = sym["n"].rpartition(".")
            words = _name_terms(own)
            owner_words = set(_name_terms(owner))
            doc_words = set(_name_terms(sym["d"])) if sym["d"] else set()
            score, matched = 0.0, 0
            for term in qterms:
                if term in words:
                    score += 3.0
                elif len(term) >= 3 and any(w.startswith(term) for w in words):
                    score += 2.0
                elif term in owner_words or term in doc_words:
                    score += 1.0
                elif term in path_terms:
                    score += 0.5
                else:
                    continue
                matched += 1
            if re.sub(r"\W+", "", sym["n"]).lower() == flat:
                score += 12.0
            elif re.sub(r"\W+", "", sym["n"].rsplit(".", 1)[-1]).lower() == flat:
                score += 10.0
            if not score:
                continue
            if matched == len(qterms):
                score += 4.0
            hits.append(((score + 0.25 * path_hits) * weight, rel, sym))
        if not kind:
            summary_terms = set(_name_terms(record.get("summary", "")))
            file_score = 2.0 * path_hits + 1.5 * sum(1 for t in qterms if t in summary_terms)
            if file_score:
                if all(t in path_terms or t in summary_terms for t in qterms):
                    file_score += 4.0
                hits.append((file_score * weight, rel, None))
    hits.sort(key=lambda h: (-h[0], h[1], h[2]["l"] if h[2] else 0))
    return hits[:top]


def _resolve_indexed_path(index: dict, target: str) -> tuple[str | None, list[str]]:
    """Map a user-typed path to an indexed key: exact, or a unique trailing-path match."""
    norm = target.replace("\\", "/")
    while norm.startswith("./"):
        norm = norm[2:]
    if norm in index["files"]:
        return norm, []
    matches = sorted(rel for rel in index["files"] if rel.endswith("/" + norm))
    if len(matches) == 1:
        return matches[0], []
    return None, matches


def _sym_line(rel: str, sym: dict, width: int = 90) -> str:
    doc = f" - {_first_line(sym['d'], width)}" if sym["d"] else ""
    return f"{rel}:{sym['l']}  {sym['k']}  {sym['n']}{doc}"


def cmd_code_index(args: argparse.Namespace) -> int:
    root = _project_root(args.path)
    index, updated = _code_index(root)
    files = index["files"]
    symbols = sum(len(r["symbols"]) for r in files.values())
    print(f"# code index: {len(files)} files ({updated} updated, {len(files) - updated} reused), "
          f"{symbols} symbols -> {CODE_INDEX_REL.as_posix()}")
    return 0


def _map_entry(rel: str, record: dict, level: int) -> list[str]:
    name = rel.rpartition("/")[2]
    summary = f" {record['summary']}" if record["summary"] else ""
    lines = [f"  {name} [{record['lang']}, {record['lines']}L]{summary}"]
    if level >= 2:
        tops = [s for s in record["symbols"] if "." not in s["n"] or s["k"] == "section"]
        # Definitions first: a map that opens with a page of constants hides the API.
        tops = [s["n"] for s in sorted(tops, key=lambda s: s["k"] == "const")]
        limit = 8 if level >= 3 else 3
        if tops:
            extra = f" +{len(tops) - limit}" if len(tops) > limit else ""
            lines.append("    " + ", ".join(tops[:limit]) + extra)
    return lines


def _render_dir_overview(files: dict[str, dict], depth: int | None) -> list[str]:
    """One line per directory; with `depth`, directories deeper than that are folded into
    their ancestor, so a big tree still gets an overview instead of a wall of paths."""
    groups: dict[str, list[dict]] = {}
    deeper: set[str] = set()
    for rel, record in files.items():
        parts = rel.split("/")[:-1]
        key = "/".join(parts[:depth]) if depth else "/".join(parts)
        groups.setdefault(key or ".", []).append(record)
        if depth and len(parts) > depth:
            deeper.add(key or ".")
    out: list[str] = []
    for directory in sorted(groups):
        records = groups[directory]
        counts: dict[str, int] = {}
        for r in records:
            counts[r["lang"]] = counts.get(r["lang"], 0) + 1
        langs = sorted(counts, key=lambda lang: (-counts[lang], lang))
        more = ", incl. subfolders" if directory in deeper else ""
        out.append(f"{directory}/  {len(records)} files ({', '.join(langs[:3])}{more})")
    return out


CODE_MAP_DIR_LINES = 40


def _fold_overview(files: dict[str, dict], max_lines: int) -> list[str]:
    """The directory overview, folded to the deepest level that fits `max_lines`: past that a
    wall of paths tells an agent less than a short tree it can drill into with --dir."""
    out = _render_dir_overview(files, None)
    depth = max(rel.count("/") for rel in files)
    while len(out) > max_lines and depth > 1:
        depth -= 1
        out = _render_dir_overview(files, depth)
    return out


def _render_code_map(files: dict[str, dict], level: int) -> list[str]:
    out: list[str] = []
    if level == 0:
        return _fold_overview(files, CODE_MAP_DIR_LINES)
    current: str | None = None
    for rel in sorted(files, key=lambda p: (p.rpartition("/")[0], p)):
        directory = rel.rpartition("/")[0] or "."
        if directory != current:
            out.append(f"{directory}/")
            current = directory
        out.extend(_map_entry(rel, files[rel], level))
    return out


def cmd_code_map(args: argparse.Namespace) -> int:
    """A bounded overview of the project: the most detailed level that fits --budget
    tokens (symbols > summaries > directories). The orientation an agent would
    otherwise assemble from a dozen listings and file reads."""
    root = _project_root(args.path)
    index, _ = _code_index(root)
    prefix = args.dir.replace("\\", "/").strip("/") if args.dir else ""
    files = {rel: rec for rel, rec in index["files"].items()
             if not prefix or rel == prefix or rel.startswith(prefix + "/")}
    if not files:
        print(f"# no indexed files{' under ' + prefix if prefix else ''}")
        return 0
    lines: list[str] = []
    for level in (3, 2, 1, 0):
        lines = _render_code_map(files, level)
        if est_tokens("\n".join(lines)) <= args.budget:
            break
    else:
        while lines and est_tokens("\n".join(lines)) > args.budget:
            lines.pop()
        lines.append("... truncated; narrow it with --dir <directory>")
    symbols = sum(len(r["symbols"]) for r in files.values())
    print(f"# code map: {len(files)} files, {symbols} symbols (local index, no LLM)")
    print("\n".join(lines))
    print('# next: code find "topic" | code outline FILE | code show FILE:SYMBOL')
    return 0


def cmd_code_find(args: argparse.Namespace) -> int:
    root = _project_root(args.path)
    index, _ = _code_index(root)
    hits = _code_find(index, args.query, args.top, args.kind)
    if args.json:
        print(json.dumps({"query": args.query, "hits": [
            {"score": round(score, 2), "path": rel,
             **({"line": sym["l"], "end": sym["e"], "kind": sym["k"], "symbol": sym["n"],
                 "doc": sym["d"]} if sym else {"kind": "file"})}
            for score, rel, sym in hits]}, ensure_ascii=False, indent=2))
        return 0
    if not hits:
        print(f"# no matching code for: {args.query!r}")
        return 0
    for _score, rel, sym in hits:
        if sym:
            print(_sym_line(rel, sym))
        else:
            summary = index["files"][rel]["summary"]
            print(f"{rel}  file  {_first_line(summary, 90)}" if summary else f"{rel}  file")
    print(f"# {len(hits)} hit(s) (local index, no LLM) | show: code show FILE:SYMBOL")
    return 0


def _print_outline(index: dict, rel: str, limit: int) -> None:
    record = index["files"][rel]
    head = f"# {rel} [{record['lang']}, {record['lines']} lines]"
    print(head + (f" {record['summary']}" if record["summary"] else ""))
    symbols = record["symbols"]
    for sym in symbols[:limit]:
        section = sym["k"] == "section"
        depth = 0 if section else sym["n"].count(".")
        label = sym["n"] if section else sym["n"].rsplit(".", 1)[-1]
        doc = f" - {_first_line(sym['d'], 80)}" if sym["d"] else ""
        print(f"{'  ' * depth}{sym['l']}-{sym['e']} {sym['k']} {label}{doc}")
    if len(symbols) > limit:
        print(f"... {len(symbols) - limit} more symbols (raise --limit)")
    if not symbols:
        print("(no symbols; use `code show FILE:START-END` to read a range)")


def cmd_code_outline(args: argparse.Namespace) -> int:
    root = _project_root(args.path)
    index, _ = _code_index(root)
    rel, others = _resolve_indexed_path(index, args.file)
    if rel is None:
        hint = f" Did you mean: {', '.join(others[:5])}?" if others else ""
        sys.stderr.write(f"[arbor] not in the code index: {args.file}.{hint}\n")
        return 2
    _print_outline(index, rel, args.limit)
    return 0


def _numbered(lines: list[str], start: int) -> str:
    return "\n".join(f"{start + i}|{line}" for i, line in enumerate(lines))


def cmd_code_show(args: argparse.Namespace) -> int:
    """Print one symbol, a line range or a small file with line numbers -- the slice an
    agent needs instead of the whole file. Big files without a target fall back to their
    outline so a blind whole-file read is never the cheapest option."""
    root = _project_root(args.path)
    index, _ = _code_index(root)
    target, spec = args.target, ""
    rel, others = _resolve_indexed_path(index, target)
    if rel is None and ":" in target:
        head, _sep, spec = target.rpartition(":")
        rel, others = _resolve_indexed_path(index, head)
    if rel is None:
        hint = f" Did you mean: {', '.join(others[:5])}?" if others else ""
        sys.stderr.write(f"[arbor] not in the code index: {target}.{hint}\n")
        return 2
    full = (root / rel).resolve()
    if root not in full.parents or CODE_SECRET_RE.match(full.name):
        sys.stderr.write(f"[arbor] refusing to read {rel}\n")
        return 2
    lines = read_text(full).splitlines()
    record = index["files"][rel]
    start, end, label = 1, len(lines), ""
    range_match = re.fullmatch(r"(\d+)(?:-(\d+))?", spec)
    if range_match:
        start = max(1, int(range_match.group(1)))
        end = min(len(lines), int(range_match.group(2) or start))
    elif spec:
        wanted = spec.lower()
        matches = [s for s in record["symbols"] if s["n"].lower() == wanted]
        matches = matches or [s for s in record["symbols"]
                              if s["n"].lower().rsplit(".", 1)[-1] == wanted]
        if not matches:
            sys.stderr.write(f"[arbor] no symbol {spec!r} in {rel}; try `code outline {rel}`\n")
            return 2
        start, end, label = matches[0]["l"], matches[0]["e"], f"{matches[0]['k']} {matches[0]['n']}"
        if len(matches) > 1:
            label += " (also: " + ", ".join(f"{m['n']}@{m['l']}" for m in matches[1:4]) + ")"
    elif len(lines) > args.max_lines:
        print(f"# {rel} has {len(lines)} lines; showing its outline instead. "
              f"Pick a symbol or range: code show {rel}:SYMBOL | {rel}:START-END")
        _print_outline(index, rel, 200)
        return 0
    if start > len(lines) or start > end:
        sys.stderr.write(f"[arbor] range is outside {rel} ({len(lines)} lines)\n")
        return 2
    chunk = lines[start - 1:end]
    shown = chunk[:args.max_lines]
    print(f"# {rel}:{start}-{start + len(shown) - 1}" + (f" ({label})" if label else ""))
    print(_numbered(shown, start))
    if len(chunk) > len(shown):
        print(f"... {len(chunk) - len(shown)} more lines; continue with "
              f"code show {rel}:{start + len(shown)}-{end}")
    return 0


def cmd_code_refs(args: argparse.Namespace) -> int:
    """Whole-word occurrences of a name across indexed files, one short line each --
    a bounded stand-in for a repo-wide grep whose output would sit in context forever."""
    root = _project_root(args.path)
    index, _ = _code_index(root)
    pattern = re.compile(r"(?<!\w)" + re.escape(args.name) + r"(?!\w)")
    total, shown, in_files = 0, 0, set()
    for rel in sorted(index["files"]):
        try:
            text = read_text(root / rel)
        except OSError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if not pattern.search(line):
                continue
            total += 1
            in_files.add(rel)
            if shown < args.top:
                print(f"{rel}:{number}: {_first_line(line, 130)}")
                shown += 1
    if not total:
        print(f"# no references to {args.name!r}")
        return 0
    more = f"; {total - shown} more (raise --top)" if total > shown else ""
    print(f"# {total} reference(s) in {len(in_files)} file(s){more}")
    return 0


# ---------------------------------------------------------------------------
# Token stats: what the local Claude Code transcripts say a project has spent.
# Read-only, offline. It reports measurements -- it does not estimate savings.
# ---------------------------------------------------------------------------


PRICE_KEYS = ("input", "cache_write", "cache_read", "output")


def _claude_projects_dir(root: Path) -> Path:
    """Where Claude Code keeps this project's transcripts: the project path with every
    non-alphanumeric character replaced by `-`, under the config directory."""
    base = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))
    return base / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(root))


def _transcript_usage(path: Path, sidechain_file: bool) -> tuple[dict[str, dict], list[str]]:
    """message id -> token usage for one transcript, plus its timestamps. A message is
    written on several lines (one per content block) that repeat the same usage, so
    lines are deduplicated by message id, keeping the largest count per field."""
    messages: dict[str, dict] = {}
    stamps: list[str] = []
    try:
        handle = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return messages, stamps
    with handle:
        for line in handle:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            if isinstance(obj.get("timestamp"), str):
                stamps.append(obj["timestamp"])
            msg = obj.get("message")
            if not isinstance(msg, dict) or msg.get("role") != "assistant":
                continue
            usage = msg.get("usage")
            if not isinstance(usage, dict):
                continue
            counts = {
                "input": int(usage.get("input_tokens") or 0),
                "cache_write": int(usage.get("cache_creation_input_tokens") or 0),
                "cache_read": int(usage.get("cache_read_input_tokens") or 0),
                "output": int(usage.get("output_tokens") or 0),
            }
            if not any(counts.values()):
                continue
            key = str(msg.get("id") or obj.get("uuid") or f"{path.name}:{len(messages)}")
            current = messages.setdefault(key, {**{k: 0 for k in counts}, "side": False})
            for name, value in counts.items():
                current[name] = max(current[name], value)
            current["side"] = current["side"] or bool(obj.get("isSidechain")) or sidechain_file
    return messages, stamps


def collect_usage(root: Path, transcripts: Path | None = None) -> dict | None:
    """Per-session and total token usage for a project, or None when it has no
    transcripts. Subagent transcripts (`<session>/subagents/*.jsonl`) join their session."""
    directory = transcripts or _claude_projects_dir(root)
    if not directory.is_dir():
        return None
    sessions: list[dict] = []
    for main in sorted(directory.glob("*.jsonl")):
        messages, stamps = _transcript_usage(main, sidechain_file=False)
        for sub in sorted((directory / main.stem / "subagents").glob("*.jsonl")):
            sub_messages, sub_stamps = _transcript_usage(sub, sidechain_file=True)
            for key, value in sub_messages.items():
                messages[f"{sub.name}:{key}"] = value
            stamps.extend(sub_stamps)
        if not messages:
            continue
        row = {"id": main.stem, "turns": 0, "subagent_turns": 0, "peak_context": 0,
               **{name: 0 for name in PRICE_KEYS}}
        for value in messages.values():
            if value["side"]:
                row["subagent_turns"] += 1
            else:
                row["turns"] += 1
                row["peak_context"] = max(row["peak_context"], value["input"]
                                          + value["cache_write"] + value["cache_read"])
            for name in PRICE_KEYS:
                row[name] += value[name]
        stamps.sort()
        row["first"], row["last"] = (stamps[0], stamps[-1]) if stamps else ("", "")
        sessions.append(row)
    if not sessions:
        return None
    sessions.sort(key=lambda r: r["first"])
    totals = {name: sum(r[name] for r in sessions) for name in (*PRICE_KEYS, "turns", "subagent_turns")}
    totals["peak_context"] = max(r["peak_context"] for r in sessions)
    read_side = totals["input"] + totals["cache_write"] + totals["cache_read"]
    return {"dir": str(directory), "sessions": sessions, "totals": totals,
            "cache_share": (totals["cache_read"] / read_side) if read_side else 0.0}


def _parse_prices(spec: str) -> dict[str, float]:
    """`input=10,cache_write=12.5,cache_read=1,output=50` -> USD per million tokens."""
    prices: dict[str, float] = {}
    for part in spec.split(","):
        key, _sep, value = part.partition("=")
        key = key.strip()
        if key not in PRICE_KEYS:
            raise ValueError(f"unknown price key {key!r}; use {', '.join(PRICE_KEYS)}")
        prices[key] = float(value)
    missing = [k for k in PRICE_KEYS if k not in prices]
    if missing:
        raise ValueError(f"missing prices: {', '.join(missing)}")
    return prices


def _stored_prices(root: Path) -> dict[str, float] | None:
    raw = _config_read(root).get("prices")
    try:
        return {k: float(raw[k]) for k in PRICE_KEYS} if isinstance(raw, dict) else None
    except (KeyError, TypeError, ValueError):
        return None


def usage_cost(totals: dict, prices: dict[str, float]) -> dict[str, float]:
    """USD per token class plus the total, from public per-million prices you supply.
    Arbor ships no price table: prices differ by model and change, so a built-in
    number would quietly go stale."""
    parts = {name: totals[name] * prices[name] / 1_000_000 for name in PRICE_KEYS}
    parts["total"] = sum(parts.values())
    return parts


def _human(n: float) -> str:
    for limit, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if n >= limit:
            return f"{n / limit:.2f}".rstrip("0").rstrip(".") + suffix
    return str(int(n))


# `stats --why`: where a session's tokens actually go. Relative weights (one uncached input
# token = 1) when no prices are given; the cache-write weight assumes the 1-hour cache that
# the logs record. All of it is read from the transcripts, nothing is sent anywhere.
RELATIVE_WEIGHTS = {"input": 1.0, "cache_write_5m": 1.25, "cache_write_1h": 2.0,
                    "cache_read": 0.1, "output": 5.0}


WHY_MIN_TURNS = 20


def _diagnose_transcript(path: Path) -> list[dict]:
    """One row per main-chain turn. Claude Code rewrites the whole history into the file
    after each compaction or resume, so records are deduplicated by uuid as well as by
    message id (a 2 GB file is mostly repeats)."""
    turns: list[dict] = []
    by_msg: dict[str, dict] = {}
    seen: set[str] = set()
    after_compact = ""
    try:
        handle = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return turns
    with handle:
        for line in handle:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            uid = obj.get("uuid")
            if isinstance(uid, str):
                if uid in seen:
                    continue
                seen.add(uid)
            if obj.get("type") == "system" and obj.get("subtype") == "compact_boundary":
                meta = obj.get("compactMetadata")
                after_compact = str(meta.get("trigger") or "?") if isinstance(meta, dict) else "?"
                continue
            msg = obj.get("message")
            if obj.get("isSidechain") or not isinstance(msg, dict) or msg.get("role") != "assistant":
                continue
            usage = msg.get("usage")
            if not isinstance(usage, dict):
                continue
            details = usage.get("output_tokens_details")
            created = usage.get("cache_creation")
            counts = {
                "in": int(usage.get("input_tokens") or 0),
                "cw": int(usage.get("cache_creation_input_tokens") or 0),
                "cr": int(usage.get("cache_read_input_tokens") or 0),
                "out": int(usage.get("output_tokens") or 0),
                "think": int(details.get("thinking_tokens") or 0) if isinstance(details, dict) else 0,
                "cw1h": int(created.get("ephemeral_1h_input_tokens") or 0) if isinstance(created, dict) else 0,
            }
            key = str(msg.get("id") or uid or len(turns))
            known = by_msg.get(key)
            if known is not None:  # another content block of the same message
                known["out"] = max(known["out"], counts["out"])
                known["think"] = max(known["think"], counts["think"])
                continue
            if not (counts["in"] or counts["cw"] or counts["cr"] or counts["out"]):
                continue
            counts["cw1h"] = min(counts["cw1h"], counts["cw"])
            counts["ctx"] = counts["in"] + counts["cw"] + counts["cr"]
            counts["after_compact"] = bool(after_compact)
            counts["trigger"] = after_compact or ""
            after_compact = ""
            by_msg[key] = counts
            turns.append(counts)
    return turns


def _turn_cost(turn: dict, prices: dict[str, float] | None) -> tuple[float, float]:
    """(input-side cost, output cost) of one turn: USD with `prices`, else relative units."""
    if prices:
        return ((turn["in"] * prices["input"] + turn["cw"] * prices["cache_write"]
                 + turn["cr"] * prices["cache_read"]) / 1e6, turn["out"] * prices["output"] / 1e6)
    w = RELATIVE_WEIGHTS
    write = turn["cw1h"] * w["cache_write_1h"] + (turn["cw"] - turn["cw1h"]) * w["cache_write_5m"]
    return turn["in"] * w["input"] + write + turn["cr"] * w["cache_read"], turn["out"] * w["output"]


def _diagnose(turns: list[dict], prices: dict[str, float] | None = None) -> dict:
    """Split one session's cost into what a project can act on: compaction (the write of
    the rebuilt context plus the carried-over summary/skills re-read every later turn),
    time spent far above the starting context, and the fixed prefix."""
    read_w = prices["cache_read"] / 1e6 if prices else RELATIVE_WEIGHTS["cache_read"]
    base = turns[0]["ctx"]
    total = compaction = long_run = 0.0
    buckets = {"<100k": 0.0, "100-200k": 0.0, "200-400k": 0.0, ">=400k": 0.0}
    events: list[dict] = []
    deltas: list[int] = []
    carry = 0
    for i, turn in enumerate(turns):
        cost_in, cost_out = _turn_cost(turn, prices)
        cost = cost_in + cost_out
        total += cost
        ctx = turn["ctx"]
        buckets["<100k" if ctx < 100_000 else "100-200k" if ctx < 200_000
                else "200-400k" if ctx < 400_000 else ">=400k"] += cost
        if ctx - base >= 200_000:
            long_run += cost
        if turn["after_compact"] and i:
            carry = max(ctx - base, 0)
            compaction += cost_in - ctx * read_w
            events.append({"before": turns[i - 1]["ctx"], "after": ctx, "written": turn["cw"],
                           "trigger": turn["trigger"]})
        elif i:
            deltas.append(ctx - turns[i - 1]["ctx"])
        compaction += carry * read_w
    total = total or 1.0

    def med(values) -> float:
        ordered = sorted(values)
        mid = len(ordered) // 2
        return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2

    write_w = prices["cache_write"] / 1e6 if prices else RELATIVE_WEIGHTS["cache_write_1h"]
    written = med(e["written"] for e in events) if events else 0
    drop = (med(e["before"] for e in events) - med(e["after"] for e in events)) if events else 0
    # Turns until the smaller context has paid back the rewrite alone (the summary call is extra).
    payback = written * write_w / (drop * read_w) if drop > 0 else None
    return {
        "turns": len(turns), "baseline": base,
        "avg_context": sum(t["ctx"] for t in turns) / len(turns),
        "prefix_share": base * len(turns) * read_w / total if not prices else None,
        "compactions": len(events), "compaction_share": compaction / total,
        "compactions_manual": sum(1 for e in events if e["trigger"] == "manual"),
        "compaction_payback_turns": payback,
        "compaction_before": med(e["before"] for e in events) if events else 0,
        "compaction_after": med(e["after"] for e in events) if events else 0,
        "compaction_written": med(e["written"] for e in events) if events else 0,
        "compactions_below_150k": sum(1 for e in events if e["before"] < 150_000),
        "growth_per_turn": med(deltas) if deltas else 0,
        "long_run_share": long_run / total,
        "buckets": {k: v / total for k, v in buckets.items()},
        "output_tokens": sum(t["out"] for t in turns),
        "thinking_tokens": sum(t["think"] for t in turns),
    }


def _why_advice(d: dict) -> list[str]:
    tips: list[str] = []
    if d["compactions"] >= 3 and d["compaction_share"] >= 0.10:
        interval = d["turns"] / d["compactions"]
        payback = d["compaction_payback_turns"]
        verdict = (f"; the rewrite alone takes ~{payback:.0f} turns to win back and the next compaction "
                   f"came after ~{interval:.0f}" if payback and payback > interval else "")
        kind = f", {d['compactions_manual']} of them manual /compact" if d["compactions_manual"] else ""
        tips.append(
            f"compaction is ~{d['compaction_share']:.0%} of the cost: {d['compactions']} of them "
            f"(one per {interval:.0f} turns{kind}), each takes the context only "
            f"{_human(d['compaction_before'])} -> {_human(d['compaction_after'])} and rewrites "
            f"{_human(d['compaction_written'])} tokens ({d['compactions_below_150k']} started below "
            f"150k){verdict}. Use /clear instead: `python arbor.py session compaction --mode manual`.")
    if d["long_run_share"] >= 0.25:
        tips.append(
            f"{d['long_run_share']:.0%} of the cost was spent while the context stood 200k+ above "
            "its start (long uninterrupted growth). A hard stop hands the user a /clear "
            "instead: `python arbor.py session limit --stop 250000`.")
    if d["prefix_share"] is not None and d["prefix_share"] >= 0.30:
        tips.append(
            f"the fixed prefix ({_human(d['baseline'])} tokens: system prompt, tools, CLAUDE.md, "
            f"skills, MCP) is ~{d['prefix_share']:.0%} of the input cost. Trim what loads at start.")
    if d["output_tokens"] and d["thinking_tokens"] / d["output_tokens"] >= 0.30:
        tips.append(
            f"thinking is {d['thinking_tokens'] / d['output_tokens']:.0%} of the output tokens and "
            "stays in the context, so it is re-read every turn: a lower effort level for routine "
            "work cuts both.")
    return tips


def _why_report(directory: Path, prices: dict[str, float] | None) -> list[dict]:
    report = []
    for main in sorted(directory.glob("*.jsonl")):
        turns = _diagnose_transcript(main)
        if len(turns) >= WHY_MIN_TURNS:
            row = _diagnose(turns, prices)
            row["id"] = main.stem
            row["advice"] = _why_advice(row)
            report.append(row)
    return report


def _print_why(report: list[dict], prices: dict[str, float] | None) -> None:
    unit = "USD" if prices else "relative units"
    print(f"# why: where each session's cost goes ({unit}; sessions with >= {WHY_MIN_TURNS} turns)")
    if not report:
        print("(no session that long yet)")
    for row in report:
        b = row["buckets"]
        print(f"{row['id'][:8]}  {row['turns']} turns, starts at {_human(row['baseline'])}, avg "
              f"{_human(row['avg_context'])}, +{_human(row['growth_per_turn'])}/turn")
        print(f"          compaction {row['compaction_share']:.0%} ({row['compactions']}x) | "
              f"cost by context size: " + ", ".join(f"{k} {v:.0%}" for k, v in b.items()))
        for tip in row["advice"]:
            print(f"          -> {tip}")
    if report and not any(row["advice"] for row in report):
        print("no dominant waste found: the cost is the context growing as the work goes on")


def cmd_stats(args: argparse.Namespace) -> int:
    root = _project_root(args.path)
    usage = collect_usage(root, Path(args.transcripts) if args.transcripts else None)
    if usage is None:
        sys.stderr.write(f"[arbor] no Claude Code transcripts for {root} "
                         f"(looked in {args.transcripts or _claude_projects_dir(root)})\n")
        return 1
    prices = None
    if args.prices:
        try:
            prices = _parse_prices(args.prices)
        except ValueError as exc:
            sys.stderr.write(f"[arbor] --prices: {exc}\n")
            return 2
        if args.save:
            _config_write(root, {**_config_read(root), "prices": prices})
    else:
        prices = _stored_prices(root)
    totals = usage["totals"]
    cost = usage_cost(totals, prices) if prices else None
    why = _why_report(Path(usage["dir"]), prices) if getattr(args, "why", False) else None
    if args.json:
        print(json.dumps({**usage, "cost_usd": cost, **({"why": why} if why is not None else {})},
                         ensure_ascii=False, indent=2))
        return 0
    print(f"# token usage from local Claude Code transcripts ({len(usage['sessions'])} sessions)")
    print("# approximate: parsed from usage records, not a bill")
    print(f"turns: {totals['turns']} (+{totals['subagent_turns']} subagent)   "
          f"peak context: {_human(totals['peak_context'])}")
    rows = (("input, uncached", "input"), ("cache write", "cache_write"),
            ("cache read", "cache_read"), ("output", "output"))
    for label, key in rows:
        money = f"   ${cost[key]:,.2f}" if cost else ""
        print(f"{label:<16}{_human(totals[key]):>9}{money}")
    if cost:
        print(f"{'total':<16}{'':>9}   ${cost['total']:,.2f}   (with the prices you set)")
    print(f"cache read is {usage['cache_share'] * 100:.1f}% of all input: the context re-sent "
          f"on every turn, so it grows with turns x context size.")
    print("top sessions by cache read:")
    for row in sorted(usage["sessions"], key=lambda r: -r["cache_read"])[:args.top]:
        avg = (row["input"] + row["cache_write"] + row["cache_read"]) / max(1, row["turns"])
        print(f"  {row['id'][:8]}  turns {row['turns']:>4}  peak {_human(row['peak_context']):>7}"
              f"  avg ctx {_human(avg):>7}  cache read {_human(row['cache_read']):>8}")
    if why is not None:
        _print_why(why, prices)
    if not cost:
        print("(no prices set: add --prices input=..,cache_write=..,cache_read=..,output=.. "
              "in USD per million tokens, and --save to keep them)")
    return 0


# ---------------------------------------------------------------------------
# Jev (opt-in, off by default): the one place Arbor calls a model. On each prompt a
# UserPromptSubmit hook asks Jev (OpenRouter's Decisions API: typed answers with
# probabilities, no generated text) which vault notes bear on the request and injects
# them. Measured on bench suite co-mem: memory reads 2290 -> 60 tokens per run, context
# -54% against control, accuracy unchanged. Sent to OpenRouter: the prompt text and the
# vault's section titles; note bodies stay local. The key is stored encrypted per user
# (Windows DPAPI, macOS Keychain, Linux Secret Service), never in the project.
# ---------------------------------------------------------------------------


JEV_ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
JEV_DEFAULTS = {"enabled": False, "model": "~typesafe/jev-latest", "threshold": 0.2, "top": 2,
                "daily_cap_usd": 0.5, "timeout": 10.0, "body_chars": 1800}
JEV_FILES = ("NOW.md", "bugs.md", "decisions.md", "knowledge.md", "investigations.md")
JEV_LOG_PATH = Path(".arbor") / "jev-log.jsonl"
JEV_KEY_RE = re.compile(r"^sk-or-[A-Za-z0-9_\-]{16,200}$")
_KEYRING_SERVICE, _KEYRING_ACCOUNT = "context-arbor", "openrouter"
_DPAPI_ENTROPY = b"context-arbor/openrouter"


def _jev_config(root: Path) -> dict:
    config = dict(JEV_DEFAULTS)
    saved = _config_read(root).get("jev")
    if isinstance(saved, dict):
        config.update({k: saved[k] for k in JEV_DEFAULTS if k in saved})
    return config


def _secret_dir() -> Path:
    base = os.environ.get("ARBOR_SECRETS_DIR") or os.environ.get("APPDATA") or Path.home() / ".config"
    return Path(base) / "context-arbor"


def _dpapi(data: bytes, protect: bool) -> bytes:
    """Windows DPAPI: only this Windows user on this machine can decrypt the blob."""
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(raw: bytes) -> Blob:
        buf = ctypes.create_string_buffer(raw, len(raw))
        return Blob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32  # type: ignore[attr-defined]
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_wchar_p, ctypes.POINTER(Blob), ctypes.c_void_p,
                   ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    source, entropy, out = blob(data), blob(_DPAPI_ENTROPY), Blob()
    ui_forbidden = 0x1
    if not fn(ctypes.byref(source), "context-arbor" if protect else None, ctypes.byref(entropy),
              None, None, ui_forbidden, ctypes.byref(out)):
        raise OSError(f"DPAPI failed (error {ctypes.GetLastError()})")  # type: ignore[attr-defined]
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def _secret_backend() -> str:
    if os.environ.get("ARBOR_SECRETS_BACKEND"):
        return os.environ["ARBOR_SECRETS_BACKEND"]
    if sys.platform == "win32":
        return "dpapi"
    if sys.platform == "darwin" and shutil.which("security"):
        return "keychain"
    if shutil.which("secret-tool"):
        return "secret-service"
    return ""


def jev_key_store(key: str) -> str:
    """Encrypt and keep the OpenRouter key for this OS user; returns the backend used."""
    backend = _secret_backend()
    if backend == "dpapi":
        path = _secret_dir() / "openrouter.dpapi"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_dpapi(key.encode("utf-8"), protect=True))
    elif backend == "keychain":
        # `security` takes the secret only as an argument; it is visible to this user's
        # processes for the moment the command runs.
        subprocess.run(["security", "add-generic-password", "-U", "-s", _KEYRING_SERVICE,
                        "-a", _KEYRING_ACCOUNT, "-w", key], check=True, capture_output=True)
    elif backend == "secret-service":
        subprocess.run(["secret-tool", "store", "--label=Context Arbor OpenRouter key",
                        "service", _KEYRING_SERVICE, "account", _KEYRING_ACCOUNT],
                       input=key.encode("utf-8"), check=True, capture_output=True)
    else:
        raise OSError("no encrypted key store on this system (needs Windows, macOS Keychain or "
                      "secret-tool); set OPENROUTER_API_KEY in the environment instead")
    return backend


def jev_key_load() -> str:
    """OPENROUTER_API_KEY wins; otherwise the stored key, or '' when there is none."""
    if os.environ.get("OPENROUTER_API_KEY"):
        return os.environ["OPENROUTER_API_KEY"].strip()
    backend = _secret_backend()
    try:
        if backend == "dpapi":
            path = _secret_dir() / "openrouter.dpapi"
            return _dpapi(path.read_bytes(), protect=False).decode("utf-8") if path.is_file() else ""
        if backend == "keychain":
            done = subprocess.run(["security", "find-generic-password", "-s", _KEYRING_SERVICE,
                                   "-a", _KEYRING_ACCOUNT, "-w"], capture_output=True, text=True)
            return done.stdout.strip() if done.returncode == 0 else ""
        if backend == "secret-service":
            done = subprocess.run(["secret-tool", "lookup", "service", _KEYRING_SERVICE,
                                   "account", _KEYRING_ACCOUNT], capture_output=True, text=True)
            return done.stdout.strip() if done.returncode == 0 else ""
    except OSError:
        return ""
    return ""


def jev_key_clear() -> None:
    backend = _secret_backend()
    if backend == "dpapi":
        (_secret_dir() / "openrouter.dpapi").unlink(missing_ok=True)
    elif backend == "keychain":
        subprocess.run(["security", "delete-generic-password", "-s", _KEYRING_SERVICE,
                        "-a", _KEYRING_ACCOUNT], capture_output=True)
    elif backend == "secret-service":
        subprocess.run(["secret-tool", "clear", "service", _KEYRING_SERVICE,
                        "account", _KEYRING_ACCOUNT], capture_output=True)


def _key_hint(key: str) -> str:
    return f"sk-or-...{key[-4:]}" if key else ""


def _jev_entries(memory: Path) -> list[dict]:
    """Every `## ` section of the vault's journals: {file, title, body}."""
    entries = []
    for name in JEV_FILES:
        path = memory / name
        if not path.is_file():
            continue
        text = read_text(path)
        marks = list(re.finditer(r"(?m)^## (.+?)\s*$", text))
        for i, mark in enumerate(marks):
            if "template" in mark.group(1).lower():
                continue
            end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
            entries.append({"file": name, "title": mark.group(1), "body": text[mark.start():end].strip()})
    return entries


def _jev_spent_today(root: Path) -> float:
    path = root / JEV_LOG_PATH
    today, total = datetime.date.today().isoformat(), 0.0
    if path.is_file():
        for line in read_text(path).splitlines():
            try:
                record = json.loads(line)
                if str(record.get("t", "")).startswith(today):
                    total += float(record.get("cost") or 0)
            except (ValueError, TypeError, AttributeError):
                pass
    return total


def _jev_log(root: Path, record: dict) -> None:
    path = root / JEV_LOG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _jev_request(prompt: str, entries: list[dict], key: str, config: dict) -> tuple[dict, dict]:
    import urllib.request
    questions = {f"n{i}": {
        "type": "noul",
        "instructions": ("A developer is given the request. Is the recorded note titled "
                         f"\"{e['title']}\" needed to carry it out correctly?"),
        "criteria": {"true": "the note records a bug, decision or rule that bears directly on the request",
                     "false": "the note is about something else"}} for i, e in enumerate(entries)}
    body = {"model": config["model"], "state": {"request": prompt}, "questions": questions}
    req = urllib.request.Request(JEV_ENDPOINT, data=json.dumps(body).encode("utf-8"), headers={
        "Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=float(config["timeout"])) as resp:
        data = json.load(resp)
    return data.get("answers") or {}, data.get("usage") or {}


def _jev_probability(answer: object) -> float:
    if isinstance(answer, dict):
        for field in ("noul", "probability", "value"):
            if isinstance(answer.get(field), (int, float)):
                return float(answer[field])
    return 0.0


def jev_match(root: Path, prompt: str, source: str = "hook") -> tuple[list[tuple[float, dict]], str]:
    """Ask Jev which notes bear on `prompt`: (chosen [(p, entry)], reason when nothing was
    asked). Logs cost and titles to .arbor/jev-log.jsonl, never the prompt or the key."""
    config = _jev_config(root)
    key = jev_key_load()
    if not key:
        return [], "no key"
    if _jev_spent_today(root) >= float(config["daily_cap_usd"]):
        return [], "daily cap reached"
    entries = _jev_entries(root / "memory")
    if not entries:
        return [], "no notes"
    started = time.time()
    record: dict = {"t": datetime.datetime.now().isoformat(timespec="seconds"), "source": source,
                    "entries": len(entries), "cost": 0.0}
    try:
        answers, usage = _jev_request(prompt, entries, key, config)
    except Exception as exc:  # noqa: BLE001 - the caller must never break
        reason = type(exc).__name__ + ": " + str(exc)[:160]
        record.update({"error": reason, "latency_s": round(time.time() - started, 2)})
        _jev_log(root, record)
        return [], reason
    scored = sorted(((_jev_probability(answers.get(f"n{i}")), e) for i, e in enumerate(entries)),
                    key=lambda pair: -pair[0])
    chosen = [(p, e) for p, e in scored if p >= float(config["threshold"])][: int(config["top"])]
    record.update({"cost": float(usage.get("cost") or 0), "latency_s": round(time.time() - started, 2),
                   "top": [{"title": e["title"][:70], "p": round(p, 3)} for p, e in scored[:4]],
                   "injected": [e["title"][:70] for _p, e in chosen]})
    _jev_log(root, record)
    return chosen, ""


def _jev_inject_text(chosen: list[tuple[float, dict]], body_chars: int) -> str:
    parts = ["[jev] Notes from memory/ that a model matched to this request. They may be out of "
             "date or wrong: check them against the code before relying on them."]
    for _p, e in chosen:
        body = e["body"] if len(e["body"]) <= body_chars else e["body"][:body_chars].rstrip() + " ..."
        parts.append(f"### {e['file']}: {e['title']}\n{body}")
    return "\n\n".join(parts)


JEV_HOOK_ARGS = "jev hook"


def _jev_set_hook(settings: Path, on: bool) -> bool:
    """Add or remove the Jev UserPromptSubmit hook in Claude's local settings."""
    data: dict = {}
    if settings.is_file():
        loaded = json.loads(read_text(settings))
        data = loaded if isinstance(loaded, dict) else {}
    hooks = data.setdefault("hooks", {})
    groups = hooks.setdefault("UserPromptSubmit", [])
    command = _hook_command(JEV_HOOK_ARGS)
    present = any(isinstance(h, dict) and h.get("command") == command
                  for g in groups if isinstance(g, dict) for h in g.get("hooks", []))
    if on == present:
        return False
    if on:
        groups.append({"hooks": [{"type": "command", "command": command}]})
    else:
        hooks["UserPromptSubmit"] = [
            {**g, "hooks": [h for h in g.get("hooks", []) if not (isinstance(h, dict) and h.get("command") == command)]}
            for g in groups if isinstance(g, dict)]
        hooks["UserPromptSubmit"] = [g for g in hooks["UserPromptSubmit"] if g["hooks"]]
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def jev_enable(root: Path, on: bool) -> None:
    config = _config_read(root)
    jev = config.get("jev") if isinstance(config.get("jev"), dict) else {}
    jev["enabled"] = on
    config["jev"] = jev
    _config_write(root, config)
    _jev_set_hook(root / ".claude" / "settings.local.json", on)


def jev_status(root: Path) -> dict:
    config = _jev_config(root)
    key = jev_key_load()
    source = "env" if os.environ.get("OPENROUTER_API_KEY") else (_secret_backend() if key else "")
    return {"enabled": bool(config["enabled"]), "key": bool(key), "key_hint": _key_hint(key),
            "key_source": source, "backend": _secret_backend(),
            "spent_today": round(_jev_spent_today(root), 4), "daily_cap_usd": config["daily_cap_usd"],
            "threshold": config["threshold"], "top": config["top"]}


def cmd_jev(args: argparse.Namespace) -> int:
    root = _project_root(args.path)
    action = args.jev_cmd
    if action == "key":
        if args.clear:
            jev_key_clear()
            print("# Jev key removed from the encrypted store")
            return 0
        import getpass
        key = (sys.stdin.readline() if args.stdin else getpass.getpass("OpenRouter key: ")).strip()
        if not JEV_KEY_RE.match(key):
            sys.stderr.write("[arbor] that does not look like an OpenRouter key (sk-or-...)\n")
            return 2
        backend = jev_key_store(key)
        print(f"# Jev key {_key_hint(key)} stored encrypted ({backend}); it is never written to the project")
        return 0
    if action in ("on", "off"):
        jev_enable(root, action == "on")
        status = jev_status(root)
        print(f"# Jev {action}" + ("" if action == "off" or status["key"] else
                                   " -- no key yet: python arbor.py jev key (or arbor ui --serve)"))
        return 0
    if action == "status":
        status = jev_status(root)
        if args.json:
            print(json.dumps(status, ensure_ascii=False, indent=2))
            return 0
        print(f"# Jev: {'on' if status['enabled'] else 'off'} | key: "
              f"{status['key_hint'] + ' (' + status['key_source'] + ')' if status['key'] else 'none'} | "
              f"spent today ${status['spent_today']:.4f} of ${status['daily_cap_usd']} | "
              f"threshold {status['threshold']}, top {status['top']}")
        return 0
    if action == "ask":
        chosen, reason = jev_match(root, args.question, source="ask")
        if not chosen:
            print(f"# jev: no matching notes{' (' + reason + ')' if reason else ''}")
            return 0 if not reason else 1
        for p, e in chosen:
            print(f"- p={p:.2f} memory/{e['file']}: {e['title']}")
        return 0
    # hook: UserPromptSubmit. Silent unless on, keyed and matched; never blocks the prompt.
    try:
        if not _jev_config(root)["enabled"]:
            return 0
        prompt = str(_read_hook_event().get("prompt") or "").strip()
        if not prompt:
            return 0
        chosen, _reason = jev_match(root, prompt)
        if chosen:
            sys.stdout.write(json.dumps({"hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": _jev_inject_text(chosen, int(_jev_config(root)["body_chars"]))}}))
    except Exception:  # noqa: BLE001 - a hook must never break the agent loop
        pass
    return 0


# ---------------------------------------------------------------------------
# Web UI: one self-contained HTML page -- the project's chronicle -- built from the
# vault, the git history and (when present) local session transcripts. Every number is
# read from a file already on disk; no model, no network, no server, no script fetched.
# ---------------------------------------------------------------------------


UI_MAX_CHAPTERS = 60


# Order of kinds inside a day, and the vault entry types that map onto them.
UI_KINDS = ("CHANGE", "DEC", "INV", "BUG", "TASK", "COMMIT")


UI_DEFAULT_OUT = Path(".arbor") / "ui" / "index.html"


_ENTRY_FIELD_RE = re.compile(r"^-\s*([A-Za-z][\w /-]*?):[ \t]*(.*)$")


def _md_plain(text: str, limit: int = 240) -> str:
    """Drop light markdown and wiki-link syntax so a note reads as plain text on the page."""
    text = re.sub(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]",
                  lambda m: m.group(2) or m.group(1), text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    return _first_line(text, limit)


def _entry_fields(block: str) -> dict[str, str]:
    """`- Key: value` bullets of an entry block; indented lines continue the last value."""
    fields: dict[str, str] = {}
    key: str | None = None
    for line in block.splitlines()[1:]:
        match = _ENTRY_FIELD_RE.match(line)
        if match:
            key = match.group(1).strip().lower()
            fields[key] = match.group(2).strip()
        elif key and line.startswith((" ", "\t")) and line.strip():
            fields[key] = (fields[key] + " " + line.strip()).strip()
        else:
            key = None
    return fields


def _valid_date(text: str) -> str:
    try:
        return datetime.date.fromisoformat(text).isoformat()
    except ValueError:
        return ""


def _ui_entries(memory: Path) -> list[dict]:
    """Every TASK/BUG/DEC/INV entry in the vault (archive included) with its date, ring
    and relations. Templates are skipped: their placeholder IDs never match anyway."""
    entries: dict[str, dict] = {}
    for note in sorted(memory.rglob("*.md")):
        rel = note.relative_to(memory)
        if "templates" in rel.parts or rel.parts[0].startswith("."):
            continue
        ring = "cold" if "archive" in rel.parts else "hot" if rel.as_posix() == "NOW.md" else "warm"
        for entry_id, block in _entry_blocks(read_text(note)):
            if entry_id in entries:
                continue
            fields = _entry_fields(block)
            stamp = entry_id.split("-")[1]
            date = _valid_date(f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}") or _valid_date(
                fields.get("date", "")[:10])
            found = RELATION_LINE_RE.search(block)
            entries[entry_id] = {
                "id": entry_id, "type": entry_id.split("-")[0], "date": date,
                "title": _md_plain(re.sub(rf"^##\s+{re.escape(entry_id)}\s*", "",
                                          block.splitlines()[0]), 140),
                "status": fields.get("status", "").lower(), "fields": fields, "ring": ring,
                "note": rel.with_suffix("").as_posix(),
                "relations": [(t.lower(), target) for t, target in
                              RELATION_ITEM_RE.findall(found.group(1))] if found else [],
            }
    return list(entries.values())


def _ui_changelog(memory: Path) -> list[dict]:
    """`## YYYY-MM-DD -- title` sections of memory/changelog.md, with their bullets."""
    path = memory / "changelog.md"
    if not path.is_file():
        return []
    sections = []
    for part in re.split(r"(?m)^##\s+", read_text(path))[1:]:
        head, _sep, body = part.partition("\n")
        match = re.match(r"(\d{4}-\d{2}-\d{2})\s*[—–-]+\s*(.+)$", head.strip())
        if not match or not _valid_date(match.group(1)):
            continue
        bullets = [_md_plain(" ".join(b.split()), 220)
                   for b in re.findall(r"(?m)^-\s+(.*(?:\n  .*)*)", body)]
        sections.append({"date": match.group(1), "title": _md_plain(match.group(2), 120),
                         "summary": bullets[0] if bullets else "", "points": bullets[:4]})
    return sections


def _ui_git(root: Path, limit: int = 600) -> list[dict]:
    """Recent non-merge commits (newest first) with size, or [] outside a git repository."""
    if not (root / ".git").exists() or not shutil.which("git"):
        return []
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "log", "--no-merges", f"-n{limit}", "--date=short",
             "--numstat", "--pretty=format:%x1e%h%x1f%ad%x1f%s"],
            capture_output=True, timeout=30, check=True).stdout.decode("utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return []
    commits = []
    for record in out.split("\x1e"):
        if not record.strip():
            continue
        head, _sep, numstat = record.partition("\n")
        sha, date, subject = (head.split("\x1f") + ["", "", ""])[:3]
        files = added = removed = 0
        for line in numstat.splitlines():
            cols = line.split("\t")
            if len(cols) == 3:
                files += 1
                added += int(cols[0]) if cols[0].isdigit() else 0
                removed += int(cols[1]) if cols[1].isdigit() else 0
        if _valid_date(date):
            commits.append({"hash": sha, "date": date, "subject": subject.strip(),
                            "files": files, "add": added, "del": removed})
    return commits


def _entry_lede(entry: dict) -> str:
    keys = {"DEC": ("decision",), "INV": ("conclusion", "question"), "BUG": ("symptom",),
            "TASK": ("goal",)}[entry["type"]]
    return next((_md_plain(entry["fields"][k], 260) for k in keys if entry["fields"].get(k)), "")


def _ui_chapters(entries: list[dict], changes: list[dict], commits: list[dict]) -> list[dict]:
    """One chapter per calendar day that has any event, oldest first. The day's headline
    is its changelog title, else its first decision/investigation/bug/task, else its
    biggest commit -- picked by rule, not written by a model."""
    days: dict[str, dict] = {}

    def day(date: str) -> dict:
        return days.setdefault(date, {"date": date, "changes": [], "entries": [], "commits": []})

    for change in changes:
        day(change["date"])["changes"].append(change)
    for entry in entries:
        if entry["date"]:
            day(entry["date"])["entries"].append(entry)
    for commit in commits:
        day(commit["date"])["commits"].append(commit)
    order = {"DEC": 0, "INV": 1, "BUG": 2, "TASK": 3}
    chapters = []
    for date in sorted(days):
        d = days[date]
        d["entries"].sort(key=lambda e: (order[e["type"]], e["id"]))
        d["commits"].sort(key=lambda c: -(c["add"] + c["del"]))
        if d["changes"]:
            headline, lede = d["changes"][0]["title"], d["changes"][0]["summary"]
        elif d["entries"]:
            headline, lede = d["entries"][0]["title"] or d["entries"][0]["id"], _entry_lede(d["entries"][0])
        else:
            headline, lede = d["commits"][0]["subject"], ""
        d["headline"], d["lede"] = headline, lede
        d["weight"] = len(d["changes"]) + len(d["entries"]) + len(d["commits"])
        d["added"] = sum(c["add"] for c in d["commits"])
        d["removed"] = sum(c["del"] for c in d["commits"])
        d["id"] = f"ch-{date}"
        chapters.append(d)
    return chapters


def _ui_rings(memory: Path) -> dict:
    """Token weight of the three memory rings against the caps `memory check` enforces."""
    def tokens(path: Path) -> int:
        return est_tokens(read_text(path)) if path.is_file() else 0

    warm = [p for p in sorted(memory.rglob("*.md"))
            if not {"archive", "templates"} & set(p.relative_to(memory).parts)
            and p.relative_to(memory).parts[0][0] != "." and p.name != "NOW.md"]
    cold = sorted((memory / "archive").rglob("*.md")) if (memory / "archive").is_dir() else []
    caps = {"NOW.md": NOW_MAX_TOKENS, "architecture.md": ARCHITECTURE_MAX_TOKENS,
            **{name: JOURNAL_MAX_TOKENS for name in MEMORY_JOURNALS}}
    return {
        "hot": {"tokens": tokens(memory / "NOW.md"), "cap": NOW_MAX_TOKENS, "files": 1},
        "warm": {"tokens": sum(tokens(p) for p in warm), "files": len(warm),
                 "rows": [{"name": name, "tokens": tokens(memory / name), "cap": cap}
                          for name, cap in caps.items() if name != "NOW.md"
                          and (memory / name).is_file()]},
        "cold": {"tokens": sum(tokens(p) for p in cold), "files": len(cold)},
    }


def _ui_collect(root: Path, title: str, lang: str) -> dict:
    memory = root / "memory"
    entries = _ui_entries(memory) if memory.is_dir() else []
    changes = _ui_changelog(memory) if memory.is_dir() else []
    commits = _ui_git(root)
    chapters = _ui_chapters(entries, changes, commits)
    goal = ""
    index_note = memory / "MEMORY.md"
    if index_note.is_file():
        found = re.search(r"(?m)^-\s*Goal:[ \t]*(\S.*)$", read_text(index_note))
        goal = _md_plain(found.group(1), 200) if found else ""
    active = next((e for e in entries if e["type"] == "TASK" and e["ring"] == "hot"
                   and e["status"] not in {"closed", "done", "resolved", "archived"}), None)
    try:
        code_index, _updated = _code_index(root)
    except OSError:
        code_index = {"files": {}}
    languages: dict[str, int] = {}
    for record in code_index["files"].values():
        languages[record["lang"]] = languages.get(record["lang"], 0) + 1
    by_type = {kind: sum(1 for e in entries if e["type"] == kind) for kind in ("DEC", "INV", "BUG", "TASK")}
    prices = _stored_prices(root)
    usage = collect_usage(root)
    return {
        "title": title, "lang": lang, "goal": goal, "generated": datetime.date.today().isoformat(),
        "entries": entries, "chapters": chapters, "commits": commits,
        "by_type": by_type, "active": active, "rings": _ui_rings(memory) if memory.is_dir() else None,
        "health": memory_check(root) if memory.is_dir() else [],
        "code": {"files": len(code_index["files"]),
                 "symbols": sum(len(r["symbols"]) for r in code_index["files"].values()),
                 "languages": sorted(languages.items(), key=lambda kv: (-kv[1], kv[0]))},
        "usage": usage, "cost": usage_cost(usage["totals"], prices) if usage and prices else None,
        "version": __version__,
    }



UI_TEXT = {
    "ru": {
        "nav": {"chronicle": "Хроника", "rings": "Кольца", "links": "Связи",
                "tokens": "Токены", "code": "Код", "jev": "Jev"},
        "eyebrow": "Память проекта · без нейросети",
        "tagline": "Как проект вырос.",
        "sub_default": "Хроника собрана из заметок памяти и истории git. "
                       "Ни одного вызова модели.",
        "cta": "Открыть хронику",
        "tag_left": "Память → хроника",
        "tag_right": "Собрано {date}",
        "figure": "Один столбец — один день. Высота — число событий: коммиты, решения, записи. "
                  "Нажмите на столбец, чтобы открыть этот день.",
        "chart_h": "Активность по дням", "chart_unit": "событий в день",
        "chart_older": "Ещё {n} раньше — в разделе «Раньше».",
        "share_h": "Из чего состоят токены",
        "stat_days": "дней разработки", "stat_commits": "коммитов",
        "stat_entries": "записей памяти", "stat_tokens": "токенов сессий",
        "stat_files": "файлов в карте кода",
        "prologue": "Пролог", "prologue_h": ("Что проект ", "помнит."),
        "memory_has": "В памяти {parts}.",
        "active_now": "Сейчас в работе: «{title}».", "active_none": "Активной задачи нет.",
        "prologue_2": "Это обычные Markdown-заметки в папке memory/. Хроника ниже собрана "
                      "из них и из истории git — правилами, а не моделью.",
        "chron": "Ход разработки", "chron_h": ("Хроника ", "по дням."),
        "earlier": "Раньше", "earlier_h": "Всё, что было до этих дней",
        "earlier_lede": "{days} — {commits}, {entries}.",
        "result": "Итог дня", "written": "Что записано", "commits_h": "Коммиты",
        "more": "и ещё {n}", "lines": "строк",
        "empty": "Хроника пуста. Она появится, когда в memory/ будут записи с датами "
                 "(DEC, INV, BUG, TASK) или в git — коммиты.",
        "rings": "Кольца памяти", "rings_h": ("Чем ближе к сердцевине, ", "тем чаще читается."),
        "hot": "Горячее", "hot_d": "NOW.md — только активная задача. Агент открывает его первым.",
        "warm": "Тёплое", "warm_d": "Правила, архитектура, журналы решений, багов и "
                                   "исследований. Достаётся поиском, а не целиком.",
        "cold": "Холодное", "cold_d": "Архив закрытых записей. В обычный поиск не попадает.",
        "tok": "ток.", "cap": "лимит {n}", "files": "файлов",
        "check_ok": "memory check: замечаний нет", "check_bad": "memory check: замечаний — {n}",
        "links": "Связи", "links_h": ("Что из чего ", "выросло."),
        "links_lead": "Типизированные связи между записями: кто кого заменил, что стало "
                      "причиной чего и что от чего зависит.",
        "tokens": "Ресурсы", "tokens_h": ("Куда уходят ", "токены."),
        "tokens_lead": "Токены сессий Claude Code этого проекта по локальным журналам. "
                       "Это оценка по записям об использовании, а не счёт.",
        "t_input": "Вход без кэша", "t_read": "Чтение кэша", "t_write": "Запись в кэш",
        "t_output": "Выход модели",
        "cache_note": "{p}% входных токенов — чтение кэша: контекст, который пересылается "
                      "на каждом ходу. Оно растёт как число ходов × размер контекста, поэтому "
                      "держите контекст коротким: /clear вместо /compact и "
                      "arbor code find вместо чтения файлов целиком.",
        "cost": "Оценка стоимости", "cost_note": "По ценам, которые вы задали "
                                                 "(arbor stats --prices).",
        "sessions_h": "Самые тяжёлые сессии", "turns": "ходов", "peak": "пик контекста",
        "avg": "средний контекст", "read": "чтение кэша",
        "code": "Карта кода", "code_h": ("Найти, ", "а не перечитывать."),
        "code_lead": "{files} и {symbols} в локальном индексе. Агент задаёт короткий вопрос "
                     "— arbor code find — и получает файл и строку, а не всю страницу.",
        "jev": "Jev · по желанию", "jev_h": ("Память, которая ", "находит сама."),
        "jev_lead": "Перед каждым вашим сообщением Jev (модель на OpenRouter) выбирает из "
                    "memory/ заметки по теме и кладёт их агенту. В тесте co-mem это сократило "
                    "чтение памяти с 2 290 до 60 токенов за запуск. Каждый вызов платный.",
        "jev_state": "Состояние", "jev_on": "включён", "jev_off": "выключен",
        "jev_key": "Ключ OpenRouter", "jev_key_set": "{hint} · {src}", "jev_key_none": "не задан",
        "jev_spent": "Потрачено сегодня / лимит",
        "jev_paste": "Вставьте ключ OpenRouter. Он шифруется для вашей учётной записи ОС и "
                     "в папку проекта не попадает.",
        "jev_save": "Сохранить ключ", "jev_turn_on": "Включить Jev", "jev_turn_off": "Выключить Jev",
        "jev_forget": "Удалить ключ",
        "jev_static": "Чтобы вставить ключ здесь, откройте страницу через сервер: "
                      "python arbor.py ui --serve --open. Или в терминале: python arbor.py jev key.",
        "jev_privacy": "На OpenRouter уходят текст сообщения и заголовки заметок; тексты "
                       "заметок остаются на компьютере. Ключ и текст сообщений не пишутся в журналы.",
        "jev_msg": {"saved": "Ключ сохранён в зашифрованном виде.", "cleared": "Ключ удалён.",
                    "on": "Jev включён для этого проекта.", "off": "Jev выключен.",
                    "bad_key": "Это не похоже на ключ OpenRouter (sk-or-...).",
                    "no_store": "На этой системе нет зашифрованного хранилища: задайте "
                                "переменную OPENROUTER_API_KEY."},
        "footer": "Собрано arbor ui из memory/, git и локальных журналов сессий. "
                  "Ни одного вызова модели.",
        "rel": {"supersedes": "заменяет", "caused-by": "вызвано", "blocks": "блокирует",
                "depends-on": "зависит от", "relates-to": "связано с"},
        "kinds": {"CHANGE": ("изменение", "изменения", "изменений"),
                  "DEC": ("решение", "решения", "решений"),
                  "INV": ("исследование", "исследования", "исследований"),
                  "BUG": ("баг", "бага", "багов"),
                  "TASK": ("задача", "задачи", "задач"),
                  "COMMIT": ("коммит", "коммита", "коммитов")},
        "plural": {"day": ("день", "дня", "дней"), "entry": ("запись", "записи", "записей"),
                   "file": ("файл", "файла", "файлов"), "symbol": ("символ", "символа", "символов")},
        "months": ("янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт",
                   "ноя", "дек"),
    },
    "en": {
        "nav": {"chronicle": "Chronicle", "rings": "Rings", "links": "Links",
                "tokens": "Tokens", "code": "Code", "jev": "Jev"},
        "eyebrow": "Project memory · no neural network",
        "tagline": "How the project grew.",
        "sub_default": "A chronicle assembled from memory notes and git history. "
                       "Not a single model call.",
        "cta": "Open the chronicle",
        "tag_left": "Memory → chronicle",
        "tag_right": "Built {date}",
        "figure": "One column is one day. Height is the number of events: commits, decisions, "
                  "notes. Click a column to open that day.",
        "chart_h": "Activity by day", "chart_unit": "events per day",
        "chart_older": "{n} earlier — see “Earlier”.",
        "share_h": "What the tokens are made of",
        "stat_days": "days of work", "stat_commits": "commits",
        "stat_entries": "memory entries", "stat_tokens": "session tokens",
        "stat_files": "files in the code map",
        "prologue": "Prologue", "prologue_h": ("What the project ", "remembers."),
        "memory_has": "The memory holds {parts}.",
        "active_now": "In progress: “{title}”.", "active_none": "No active task.",
        "prologue_2": "These are plain Markdown notes in memory/. The chronicle below is "
                      "built from them and from git history — by rules, not by a model.",
        "chron": "Course of work", "chron_h": ("A chronicle ", "day by day."),
        "earlier": "Earlier", "earlier_h": "Everything before these days",
        "earlier_lede": "{days} — {commits}, {entries}.",
        "result": "Day total", "written": "What was recorded", "commits_h": "Commits",
        "more": "and {n} more", "lines": "lines",
        "empty": "The chronicle is empty. It appears once memory/ has dated entries "
                 "(DEC, INV, BUG, TASK) or git has commits.",
        "rings": "Memory rings", "rings_h": ("The closer to the pith, ", "the more it is read."),
        "hot": "Hot", "hot_d": "NOW.md — the active task only. The agent opens it first.",
        "warm": "Warm", "warm_d": "Rules, architecture, and the decision, bug and "
                                  "investigation journals. Reached by search, never whole.",
        "cold": "Cold", "cold_d": "Archive of closed entries. Left out of normal search.",
        "tok": "tok.", "cap": "cap {n}", "files": "files",
        "check_ok": "memory check: no issues", "check_bad": "memory check: {n} issue(s)",
        "links": "Links", "links_h": ("What grew ", "from what."),
        "links_lead": "Typed links between entries: what replaced what, what caused what, "
                      "and what depends on what.",
        "tokens": "Resources", "tokens_h": ("Where the ", "tokens go."),
        "tokens_lead": "Claude Code session tokens for this project, from local logs. "
                       "An estimate from usage records, not a bill.",
        "t_input": "Uncached input", "t_read": "Cache read", "t_write": "Cache write",
        "t_output": "Model output",
        "cache_note": "{p}% of input tokens are cache reads: the context re-sent on every "
                      "turn. It grows as turns × context size, so keep the context short: "
                      "/clear instead of /compact, and arbor code find instead of reading "
                      "whole files.",
        "cost": "Estimated cost", "cost_note": "At the prices you set (arbor stats --prices).",
        "sessions_h": "Heaviest sessions", "turns": "turns", "peak": "peak context",
        "avg": "avg context", "read": "cache read",
        "code": "Code map", "code_h": ("Find it, ", "don't reread it."),
        "code_lead": "{files} and {symbols} in the local index. The agent asks a short "
                     "question — arbor code find — and gets a file and a line, not the page.",
        "jev": "Jev · optional", "jev_h": ("Memory that ", "finds itself."),
        "jev_lead": "Before each of your messages Jev (a model on OpenRouter) picks the notes "
                    "in memory/ that bear on it and hands them to the agent. On bench co-mem it "
                    "cut memory reads from 2,290 to 60 tokens per run. Every call is paid.",
        "jev_state": "State", "jev_on": "on", "jev_off": "off",
        "jev_key": "OpenRouter key", "jev_key_set": "{hint} · {src}", "jev_key_none": "not set",
        "jev_spent": "Spent today / cap",
        "jev_paste": "Paste your OpenRouter key. It is encrypted for your OS account and never "
                     "lands in the project folder.",
        "jev_save": "Save key", "jev_turn_on": "Turn Jev on", "jev_turn_off": "Turn Jev off",
        "jev_forget": "Remove key",
        "jev_static": "To paste the key here, open the page through the server: "
                      "python arbor.py ui --serve --open. Or in a terminal: python arbor.py jev key.",
        "jev_privacy": "Sent to OpenRouter: the message text and the note titles; note bodies "
                       "stay on this computer. Neither the key nor the messages are logged.",
        "jev_msg": {"saved": "Key stored encrypted.", "cleared": "Key removed.",
                    "on": "Jev is on for this project.", "off": "Jev is off.",
                    "bad_key": "That does not look like an OpenRouter key (sk-or-...).",
                    "no_store": "No encrypted store on this system: set OPENROUTER_API_KEY."},
        "footer": "Built by arbor ui from memory/, git and local session logs. "
                  "Not a single model call.",
        "rel": {"supersedes": "supersedes", "caused-by": "caused by", "blocks": "blocks",
                "depends-on": "depends on", "relates-to": "relates to"},
        "kinds": {"CHANGE": ("change", "changes"), "DEC": ("decision", "decisions"),
                  "INV": ("investigation", "investigations"), "BUG": ("bug", "bugs"),
                  "TASK": ("task", "tasks"), "COMMIT": ("commit", "commits")},
        "plural": {"day": ("day", "days"), "entry": ("entry", "entries"),
                   "file": ("file", "files"), "symbol": ("symbol", "symbols")},
        "months": ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct",
                   "Nov", "Dec"),
    },
}


def _plural(n: int, forms: tuple[str, ...], lang: str) -> str:
    if lang == "ru":
        last, last2 = n % 10, n % 100
        if last == 1 and last2 != 11:
            return forms[0]
        return forms[1] if 2 <= last <= 4 and not 12 <= last2 <= 14 else forms[2]
    return forms[0] if n == 1 else forms[-1]


def _count(n: int, forms: tuple[str, ...], lang: str) -> str:
    return f"{_num(n, lang)} {_plural(n, forms, lang)}"


def _num(n: float, lang: str) -> str:
    return f"{int(n):,}".replace(",", " " if lang == "ru" else ",")


def _tokens_text(n: float, lang: str) -> str:
    """620 040 000 -> '620,04 млн' (ru) / '620.04M' (en)."""
    if n >= 1e6:
        text = f"{n / 1e6:.2f}"
        return (text.replace(".", ",") + " млн") if lang == "ru" else text + "M"
    if n >= 1e3:
        text = f"{n / 1e3:.1f}".rstrip("0").rstrip(".")
        return (text.replace(".", ",") + " тыс") if lang == "ru" else text + "k"
    return str(int(n))


def _date_parts(iso: str, lang: str) -> tuple[str, str]:
    year, month, day = iso.split("-")
    months = UI_TEXT[lang]["months"]
    return str(int(day)), f"{months[int(month) - 1]} {year}"


def _short_date(iso: str, lang: str) -> str:
    day, month = _date_parts(iso, lang)
    return f"{day} {month.split()[0]}"


def _e(text: object) -> str:
    return html.escape(str(text), quote=True)


UI_CHART_DAYS = 45


def _axis_ticks(peak: int) -> list[int]:
    """0 plus at most four whole-number gridlines that reach `peak`."""
    peak = max(1, peak)
    step = next(s * m for m in (1, 10, 100, 1000, 10000) for s in (1, 2, 5)
                if -(-peak // (s * m)) <= 4)
    return list(range(0, -(-peak // step) * step + 1, step))


def _day_counts(chapter: dict) -> dict[str, int]:
    counts = {"CHANGE": len(chapter["changes"]), "COMMIT": len(chapter["commits"])}
    for kind in ("DEC", "INV", "BUG", "TASK"):
        counts[kind] = sum(1 for e in chapter["entries"] if e["type"] == kind)
    return counts


def _activity_chart(chapters: list[dict], t: dict, lang: str) -> str:
    """Plain stacked bar chart: one column per calendar day (the last UI_CHART_DAYS up to the
    newest day with events), height = events that day, colour = kind of event. Each column
    with events links to its chapter. Plain HTML and CSS, so the text stays real text."""
    if not chapters:
        return ""
    by_date = {c["date"]: c for c in chapters}
    last = datetime.date.fromisoformat(chapters[-1]["date"])
    first = max(datetime.date.fromisoformat(chapters[0]["date"]),
                last - datetime.timedelta(days=UI_CHART_DAYS - 1))
    days = [(first + datetime.timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]
    counts = [_day_counts(by_date[d]) if d in by_date else None for d in days]
    ticks = _axis_ticks(max(sum(c.values()) for c in counts if c))
    top = ticks[-1]
    columns = []
    for iso, day in zip(days, counts):
        if not day:
            columns.append('<span class="col"></span>')
            continue
        label = f'{_short_date(iso, lang)}: ' + ", ".join(
            _count(day[k], t["kinds"][k], lang) for k in UI_KINDS if day[k])
        segments = "".join(f'<i class="k-{k.lower()}" style="height:{day[k] / top * 100:.2f}%"></i>'
                           for k in UI_KINDS if day[k])
        columns.append(f'<a class="col" href="#ch-{iso}" title="{_e(label)}" '
                       f'aria-label="{_e(label)}">{segments}</a>')
    grid = "".join(f'<i class="gl" style="bottom:{tick / top * 100:.2f}%"></i>' for tick in ticks[1:])
    yaxis = "".join(f'<span style="bottom:{tick / top * 100:.2f}%">{tick}</span>' for tick in ticks)
    n = len(days)
    step = max(1, -(-n // 6))
    xaxis = "".join(f'<span style="left:{(i + 0.5) / n * 100:.2f}%">{_e(_short_date(days[i], lang))}</span>'
                    for i in range(n) if (n - 1 - i) % step == 0)
    legend = "".join(
        f'<li><i class="sw k-{k.lower()}"></i>{_e(_count(sum(c[k] for c in counts if c), t["kinds"][k], lang))}</li>'
        for k in UI_KINDS if any(c and c[k] for c in counts))
    older = sum(1 for c in chapters if c["date"] < days[0])
    note = (f'<p class="fine">{_e(t["chart_older"].format(n=_count(older, t["plural"]["day"], lang)))}</p>'
            if older else "")
    return (f'<div class="chart" role="group" aria-label="{_e(t["chart_h"])}">'
            f'<p class="chart-head"><b>{_e(t["chart_h"])}</b><span>{_e(t["chart_unit"])}</span></p>'
            f'<div class="plot"><div class="yaxis">{yaxis}</div><div class="field">'
            f'<div class="grid">{grid}</div><div class="bars" style="--n:{n}">{"".join(columns)}</div></div></div>'
            f'<div class="xaxis">{xaxis}</div><ul class="legend">{legend}</ul>{note}</div>')


def _chip(kind: str, label: str) -> str:
    return f'<span class="chip k-{kind.lower()}">{_e(label)}</span>'


def _kinds_row(chapter: dict, t: dict, lang: str) -> str:
    counts = _day_counts(chapter)
    return "".join(_chip(k, _count(counts[k], t["kinds"][k], lang))
                   for k in UI_KINDS if counts[k])


def _entry_html(entry: dict, t: dict) -> str:
    fields = entry["fields"]
    picks = {"DEC": ("decision", "reason"), "INV": ("question", "conclusion"),
             "BUG": ("symptom", "resolution"), "TASK": ("goal", "success")}[entry["type"]]
    rows = "".join(f'<dt>{_e(k)}</dt><dd>{_e(_md_plain(fields[k], 320))}</dd>'
                   for k in picks if fields.get(k))
    status = f' <span class="status">{_e(entry["status"])}</span>' if entry["status"] else ""
    return (f'<li><div class="ent-head"><code>{_e(entry["id"])}</code>{status}'
            f'<b>{_e(entry["title"])}</b></div>{f"<dl>{rows}</dl>" if rows else ""}</li>')


def _chapter_html(chapter: dict, t: dict, lang: str) -> str:
    day, month = _date_parts(chapter["date"], lang)
    entries = chapter["entries"]
    picks = [("CHANGE", "LOG", c["title"]) for c in chapter["changes"][:4]]
    picks += [(e["type"], e["type"], e["title"] or e["id"]) for e in entries]
    picks = [pick for pick in picks if pick[2] != chapter["headline"]]  # already the heading
    top = "".join(f'<li>{_chip(kind, label)}<span>{_e(text)}</span></li>'
                  for kind, label, text in picks[:6])
    commit_rows = "".join(
        f'<li><code>{_e(c["hash"])}</code><span>{_e(c["subject"])}</span></li>'
        for c in chapter["commits"][:12])
    extra = len(chapter["commits"]) - 12
    if extra > 0:
        commit_rows += f'<li class="more">{_e(t["more"].format(n=extra))}</li>'
    detail = ""
    if chapter["changes"] or entries or chapter["commits"]:
        change_list = ""
        if chapter["changes"]:
            change_list = "<ul class=changes>" + "".join(
                "<li><b>" + _e(c["title"]) + "</b>"
                + ("<ul>" + "".join("<li>" + _e(pt) + "</li>" for pt in c["points"]) + "</ul>"
                   if c["points"] else "") + "</li>" for c in chapter["changes"]) + "</ul>"
        ent_list = ""
        if entries:
            ent_list = "<ul class=ent>" + "".join(_entry_html(e, t) for e in entries) + "</ul>"
        commit_list = ""
        if chapter["commits"]:
            commit_list = ("<h4>" + _e(t["commits_h"]) + "</h4><ul class=commits>"
                           + commit_rows + "</ul>")
        detail = (f'<details><summary>{_e(t["written"])}</summary>'
                  f'{change_list}{ent_list}{commit_list}</details>')
    bits = [_count(len(chapter["commits"]), t["kinds"]["COMMIT"], lang)] if chapter["commits"] else []
    if chapter["changes"]:
        bits.append(_count(len(chapter["changes"]), t["kinds"]["CHANGE"], lang))
    if entries:
        bits.append(_count(len(entries), t["plural"]["entry"], lang))
    if chapter["added"] or chapter["removed"]:
        bits.append(f'+{_num(chapter["added"], lang)} / −{_num(chapter["removed"], lang)} {t["lines"]}')
    result = (f'<p class="result"><span>{_e(t["result"])}</span>{_e(" · ".join(bits))}</p>'
              if bits else "")
    lede = f'<p class="lede">{_e(chapter["lede"])}</p>' if chapter["lede"] else ""
    top_list = f'<ul class="picks">{top}</ul>' if top else ""
    return (f'<article class="chapter reveal" id="{_e(chapter["id"])}">'
            f'<div class="stamp"><b>{_e(day)}</b><span>{_e(month)}</span></div>'
            f'<div class="body"><p class="kinds">{_kinds_row(chapter, t, lang)}</p>'
            f'<h3>{_e(chapter["headline"])}</h3>{lede}{top_list}{detail}{result}</div></article>')


def _earlier_html(older: list[dict], t: dict, lang: str) -> str:
    first, last = _date_parts(older[0]["date"], lang), _date_parts(older[-1]["date"], lang)
    commits = sum(len(c["commits"]) for c in older)
    entries = sum(len(c["entries"]) for c in older)
    lede = t["earlier_lede"].format(
        days=_count(len(older), t["plural"]["day"], lang),
        commits=_count(commits, t["kinds"]["COMMIT"], lang),
        entries=_count(entries, t["plural"]["entry"], lang))
    return (f'<article class="chapter reveal" id="ch-earlier">'
            f'<div class="stamp"><b>…</b><span>{_e(first[1])}</span></div>'
            f'<div class="body"><p class="kinds">{_chip("COMMIT", t["earlier"])}</p>'
            f'<h3>{_e(t["earlier_h"])}</h3><p class="lede">{_e(lede)}'
            f' ({_e(" ".join(first))} — {_e(" ".join(last))})</p></div></article>')


def _title_html(title: str) -> str:
    head, sep, tail = title.rpartition(" ")
    return f'{_e(head)}{sep}<em>{_e(tail)}</em>' if head else f'<em>{_e(title)}</em>'


def _section_head(eyebrow: str, heading: tuple[str, str], lead: str = "") -> str:
    return (f'<header class="sec-head reveal"><p class="eyebrow">{_e(eyebrow)}</p>'
            f'<h2>{_e(heading[0])}<em>{_e(heading[1])}</em></h2>'
            f'{f"<p class=lead>{_e(lead)}</p>" if lead else ""}</header>')


def _svg_arcs(entries: list[dict], t: dict) -> str:
    """Typed relations as arcs over a dated axis: nodes are entries, arcs are edges."""
    linked = {e["id"] for e in entries if e["relations"]}
    for e in entries:
        linked.update(target for _r, target in e["relations"])
    nodes = sorted((e for e in entries if e["id"] in linked), key=lambda e: (e["date"], e["id"]))[:28]
    if len(nodes) < 2:
        return ""
    pos = {n["id"]: 60 + i * (880 / (len(nodes) - 1)) for i, n in enumerate(nodes)}
    colors = {"supersedes": "var(--sap)", "caused-by": "var(--ember)", "blocks": "var(--ember)",
              "depends-on": "var(--slate)", "relates-to": "var(--lichen)"}
    arcs = []
    for e in nodes:
        for rtype, target in e["relations"]:
            if target not in pos:
                continue
            x1, x2 = pos[e["id"]], pos[target]
            radius = abs(x2 - x1) / 2
            sweep = 1 if x2 > x1 else 0
            arcs.append(f'<path d="M{x1:.1f} 230 A{radius:.1f} {min(radius, 190):.1f} 0 0 {sweep} '
                        f'{x2:.1f} 230" fill="none" stroke="{colors[rtype]}" stroke-width="1.6" '
                        f'stroke-opacity=".85"><title>{_e(e["id"])} {_e(t["rel"][rtype])} '
                        f'{_e(target)}</title></path>')
    dots = "".join(
        f'<circle cx="{pos[n["id"]]:.1f}" cy="230" r="6" fill="var(--kind-{n["type"].lower()})">'
        f'<title>{_e(n["id"])} {_e(n["title"])}</title></circle>'
        f'<text x="{pos[n["id"]]:.1f}" y="256" text-anchor="middle">{_e(n["id"][:3])}·{_e(n["id"][-3:])}</text>'
        for n in nodes)
    legend = "".join(f'<li><i style="background:{colors[r]}"></i>{_e(t["rel"][r])}</li>' for r in colors)
    return (f'<figure class="arcs"><svg viewBox="0 0 1000 280" role="img" aria-label="relations">'
            f'{"".join(arcs)}<line x1="40" y1="230" x2="960" y2="230" stroke="var(--line-2)"/>{dots}</svg>'
            f'<ul class="legend">{legend}</ul></figure>')


def _ring_card(name: str, desc: str, ring: dict, t: dict, lang: str, rows: list[dict] | None = None) -> str:
    cap = ring.get("cap")
    bar = ""
    if cap:
        ratio = min(1.0, ring["tokens"] / cap)
        bar = (f'<div class="meter" role="meter" aria-valuemin="0" aria-valuemax="{cap}" '
               f'aria-valuenow="{ring["tokens"]}"><i style="width:{ratio * 100:.1f}%"></i></div>'
               f'<p class="cap">{_e(t["cap"].format(n=_num(cap, lang)))} {_e(t["tok"])}</p>')
    listing = ""
    if rows:
        listing = "<ul class=rows>" + "".join(
            f'<li><span>{_e(r["name"])}</span><b>{_num(r["tokens"], lang)}</b>'
            f'<i style="width:{min(1.0, r["tokens"] / r["cap"]) * 100:.0f}%"></i></li>'
            for r in rows) + "</ul>"
    return (f'<article class="ring-card reveal"><p class="eyebrow">{_e(name)}</p>'
            f'<p class="big">≈ {_num(ring["tokens"], lang)} <small>{_e(t["tok"])}</small></p>'
            f'{bar}<p class="desc">{_e(desc)}</p>{listing}'
            f'<p class="fine">{_e(_count(ring["files"], t["plural"]["file"], lang))}</p></article>')


TOKEN_COLORS = {"input": "var(--slate)", "cache_read": "var(--sap)", "cache_write": "var(--lichen)",
                "output": "var(--ember)"}


def _tokens_section(data: dict, t: dict, lang: str) -> str:
    usage, cost = data["usage"], data["cost"]
    totals = usage["totals"]
    cols = (("t_input", "input"), ("t_read", "cache_read"), ("t_write", "cache_write"),
            ("t_output", "output"))
    whole = sum(totals[key] for _label, key in cols) or 1

    def percent(key: str) -> str:
        text = f"{totals[key] / whole * 100:.1f}"
        return (text.replace(".", ",") if lang == "ru" else text) + "%"

    stat_cols = "".join(
        f'<div><p class="label"><i class="sw" style="--c:{TOKEN_COLORS[key]}"></i>{_e(t[label])}</p>'
        f'<p class="num">{_e(_tokens_text(totals[key], lang))}</p>'
        f'<p class="pct">{percent(key)}</p>'
        f'{f"<p class=usd>${cost[key]:,.2f}</p>" if cost else ""}</div>' for label, key in cols)
    share = "".join(
        f'<i style="flex:{totals[key]};background:{TOKEN_COLORS[key]}" '
        f'title="{_e(t[label])}: {percent(key)}"></i>' for label, key in cols if totals[key])
    headline = (f'<div class="cost-box"><p class="label">{_e(t["cost"])}</p>'
                f'<p class="cost">${cost["total"]:,.2f}</p><p class="fine">{_e(t["cost_note"])}</p></div>'
                if cost else
                f'<div class="cost-box"><p class="label">{_e(t["stat_tokens"])}</p>'
                f'<p class="cost">{_e(_tokens_text(totals["input"] + totals["cache_write"] + totals["cache_read"] + totals["output"], lang))}</p></div>')
    heavy = sorted(usage["sessions"], key=lambda r: -r["cache_read"])[:6]
    peak = max((r["cache_read"] for r in heavy), default=1) or 1
    rows = "".join(
        f'<li><code>{_e(r["id"][:8])}</code><span class="bar"><i style="width:{r["cache_read"] / peak * 100:.1f}%"></i></span>'
        f'<span>{_e(_tokens_text(r["cache_read"], lang))}</span>'
        f'<span class="fine">{r["turns"]} {_e(t["turns"])} · {_e(t["peak"])} {_e(_tokens_text(r["peak_context"], lang))}</span></li>'
        for r in heavy)
    note = t["cache_note"].format(p=f'{usage["cache_share"] * 100:.1f}'.replace(".", ",") if lang == "ru"
                                  else f'{usage["cache_share"] * 100:.1f}')
    return (f'<section class="block" id="tokens">{_section_head(t["tokens"], t["tokens_h"], t["tokens_lead"])}'
            f'<div class="token-top reveal">{headline}<div class="token-cols">{stat_cols}</div></div>'
            f'<div class="share reveal" role="img" aria-label="{_e(t["share_h"])}">'
            f'<p class="label">{_e(t["share_h"])}</p><div class="stack">{share}</div></div>'
            f'<p class="callout reveal">{_e(note)}</p>'
            f'<div class="sessions reveal"><h4>{_e(t["sessions_h"])}</h4><ul>{rows}</ul></div></section>')


def _code_section(data: dict, t: dict, lang: str) -> str:
    code = data["code"]
    peak = code["languages"][0][1] if code["languages"] else 1
    rows = "".join(
        f'<li><span>{_e(name)}</span><span class="bar"><i style="width:{count / peak * 100:.1f}%"></i></span>'
        f'<b>{_num(count, lang)}</b></li>' for name, count in code["languages"][:8])
    lead = t["code_lead"].format(files=_count(code["files"], t["plural"]["file"], lang),
                                 symbols=_count(code["symbols"], t["plural"]["symbol"], lang))
    return (f'<section class="block" id="code">{_section_head(t["code"], t["code_h"], lead)}'
            f'<ul class="langs reveal">{rows}</ul></section>')


def _jev_section(data: dict, t: dict) -> str:
    """Jev status; with `serve` (a per-run token) also the form that takes the key."""
    jev, token = data.get("jev") or {}, data.get("serve")
    key_text = (t["jev_key_set"].format(hint=jev["key_hint"], src=jev["key_source"]) if jev.get("key")
                else t["jev_key_none"])
    rows = (f'<li><span>{_e(t["jev_state"])}</span><b>{_e(t["jev_on"] if jev.get("enabled") else t["jev_off"])}</b></li>'
            f'<li><span>{_e(t["jev_key"])}</span><b>{_e(key_text)}</b></li>'
            f'<li><span>{_e(t["jev_spent"])}</span><b>${jev.get("spent_today", 0):.4f} / '
            f'${float(jev.get("daily_cap_usd", 0)):.2f}</b></li>')
    flash = t["jev_msg"].get(data.get("flash") or "", "")
    if token:
        hidden = f'<input type="hidden" name="token" value="{_e(token)}">'
        toggle = "off" if jev.get("enabled") else "on"
        controls = (
            f'<form class="jev-form" method="post" action="/jev">{hidden}'
            f'<label for="jev-key">{_e(t["jev_paste"])}</label>'
            f'<input id="jev-key" name="key" type="password" autocomplete="off" spellcheck="false" '
            f'placeholder="sk-or-v1-..." required>'
            f'<button name="action" value="save_key">{_e(t["jev_save"])}</button></form>'
            f'<form class="jev-form row" method="post" action="/jev">{hidden}'
            f'<button name="action" value="{toggle}">{_e(t["jev_turn_" + toggle])}</button>'
            + (f'<button class="quiet" name="action" value="clear_key">{_e(t["jev_forget"])}</button>'
               if jev.get("key") else "") + '</form>')
    else:
        controls = f'<p class="callout">{_e(t["jev_static"])}</p>'
    return (f'<section class="block" id="jev">{_section_head(t["jev"], t["jev_h"], t["jev_lead"])}'
            f'<div class="jev reveal"><ul class="jev-rows">{rows}</ul>'
            f'{f"<p class=jev-flash>{_e(flash)}</p>" if flash else ""}{controls}'
            f'<p class="fine">{_e(t["jev_privacy"])}</p></div></section>')


def render_ui(data: dict) -> str:
    lang = data["lang"]
    t = UI_TEXT[lang]
    chapters = data["chapters"]
    by_type = data["by_type"]
    total_entries = sum(by_type.values())
    usage = data["usage"]

    nav = [("chronicle", "#chronicle")]
    if data["rings"]:
        nav.append(("rings", "#rings"))
    has_links = _svg_arcs(data["entries"], t)
    if has_links:
        nav.append(("links", "#links"))
    if usage:
        nav.append(("tokens", "#tokens"))
    if data["code"]["files"]:
        nav.append(("code", "#code"))
    if data.get("jev") is not None:
        nav.append(("jev", "#jev"))
    nav_html = "".join(f'<a href="{href}">{_e(t["nav"][key])}</a>' for key, href in nav)

    stats = [(_num(len(chapters), lang), _plural(len(chapters), t["plural"]["day"], lang)),
             (_num(len(data["commits"]), lang), _plural(len(data["commits"]), t["kinds"]["COMMIT"], lang)),
             (_num(total_entries, lang), t["stat_entries"])]
    if usage:
        totals = usage["totals"]
        stats.append((_tokens_text(totals["input"] + totals["cache_write"] + totals["cache_read"]
                                   + totals["output"], lang), t["stat_tokens"]))
    else:
        stats.append((_num(data["code"]["files"], lang), t["stat_files"]))
    stats_html = "".join(f'<div><p class="num">{_e(n)}</p><p class="label">{_e(label)}</p></div>'
                         for n, label in stats)

    kinds = [("DEC", by_type["DEC"]), ("INV", by_type["INV"]), ("BUG", by_type["BUG"]),
             ("TASK", by_type["TASK"])]
    parts = [_count(n, t["kinds"][k], lang) for k, n in kinds if n]
    memory_line = t["memory_has"].format(parts=", ".join(parts)) if parts else ""
    active = data["active"]
    active_line = (t["active_now"].format(title=active["title"] or active["id"]) if active
                   else t["active_none"])

    older = chapters[:-UI_MAX_CHAPTERS]
    shown = chapters[-UI_MAX_CHAPTERS:]
    articles = ""
    if older:
        articles += _earlier_html(older, t, lang)
    articles += "".join(_chapter_html(c, t, lang) for c in shown)
    chronicle_body = (f'<div class="chapters">{articles}</div>' if chapters
                      else f'<p class="empty reveal">{_e(t["empty"])}</p>')

    rings_html = ""
    if data["rings"]:
        r = data["rings"]
        health = data["health"]
        badge = (f'<p class="health ok">{_e(t["check_ok"])}</p>' if not health else
                 f'<p class="health bad">{_e(t["check_bad"].format(n=len(health)))}</p>')
        rings_html = (
            f'<section class="block" id="rings">{_section_head(t["rings"], t["rings_h"])}'
            f'<div class="ring-cards">{_ring_card(t["hot"], t["hot_d"], r["hot"], t, lang)}'
            f'{_ring_card(t["warm"], t["warm_d"], r["warm"], t, lang, r["warm"]["rows"])}'
            f'{_ring_card(t["cold"], t["cold_d"], r["cold"], t, lang)}</div>{badge}</section>')
    links_html = (f'<section class="block" id="links">{_section_head(t["links"], t["links_h"], t["links_lead"])}'
                  f'<div class="reveal">{has_links}</div></section>') if has_links else ""
    tokens_html = _tokens_section(data, t, lang) if usage else ""
    code_html = _code_section(data, t, lang) if data["code"]["files"] else ""
    code_html += _jev_section(data, t) if data.get("jev") is not None else ""
    form_csp = " form-action 'self';" if data.get("serve") else ""

    title = data["title"]
    sub = data["goal"] or t["sub_default"]
    generated = " ".join(_date_parts(data["generated"], lang))
    mark = ('<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><g fill="none" '
            'stroke="currentColor" stroke-width="1.4"><circle cx="12" cy="12" r="10"/>'
            '<circle cx="12" cy="12" r="6.4"/></g><circle cx="12" cy="12" r="2.4" fill="var(--lichen)"/></svg>')
    return (
        f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        f'style-src \'unsafe-inline\'; script-src \'unsafe-inline\'; img-src data:;{form_csp}">'
        f'<meta name="color-scheme" content="dark"><title>{_e(title)} — {_e(t["tagline"])}</title>'
        f'<script>document.documentElement.classList.add("js")</script>'
        f'<style>{UI_CSS}</style></head><body id="top">'
        f'<header class="masthead"><a class="brand" href="#top">{mark}<span>Arbor</span></a>'
        f'<nav>{nav_html}</nav><span class="proj">{_e(title)}</span></header>'
        f'<main><section class="hero"><div class="hero-copy">'
        f'<p class="eyebrow">{_e(t["eyebrow"])}</p><h1>{_title_html(title)}</h1>'
        f'<p class="tagline">{_e(t["tagline"])}</p><p class="sub">{_e(sub)}</p>'
        f'<a class="cta" href="#chronicle">{_e(t["cta"])} <span aria-hidden="true">↓</span></a></div>'
        f'<figure class="hero-art">{_activity_chart(chapters, t, lang)}'
        f'<figcaption>{_e(t["figure"])}</figcaption></figure>'
        f'<p class="hero-tag l">{_e(t["tag_left"])}</p>'
        f'<p class="hero-tag r">{_e(t["tag_right"].format(date=generated))}</p></section>'
        f'<section class="stats reveal">{stats_html}</section>'
        f'<section class="block prologue"><div class="reveal"><p class="eyebrow">{_e(t["prologue"])}</p>'
        f'<h2>{_e(t["prologue_h"][0])}<em>{_e(t["prologue_h"][1])}</em></h2></div>'
        f'<div class="prose reveal"><p>{_e(" ".join(x for x in (memory_line, active_line) if x))}</p>'
        f'<p>{_e(t["prologue_2"])}</p></div></section>'
        f'<section class="block" id="chronicle">{_section_head(t["chron"], t["chron_h"])}'
        f'{chronicle_body}</section>{rings_html}{links_html}{tokens_html}{code_html}</main>'
        f'<footer><div class="foot"><p>{_e(t["footer"])}</p>'
        f'<p class="fine">Context Arbor {_e(data["version"])}</p></div></footer>'
        f'<script>{UI_JS}</script></body></html>'
    )


def cmd_ui(args: argparse.Namespace) -> int:
    """Write the chronicle page (default .arbor/ui/index.html) and optionally open it."""
    root = _project_root(args.path)
    if not (root / "memory").is_dir() and not (root / ".git").exists():
        sys.stderr.write(f"[arbor] nothing to show in {root}: no memory/ vault and no git history. "
                         f"Run `python arbor.py init` first.\n")
        return 2
    if getattr(args, "serve", False):
        return _ui_serve(root, args)
    data = _ui_collect(root, args.title or root.name, args.lang)
    data["jev"] = jev_status(root)
    out = Path(args.out) if args.out else root / UI_DEFAULT_OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_ui(data), encoding="utf-8")
    print(f"# chronicle written: {out} ({len(data['chapters'])} days, "
          f"{len(data['commits'])} commits, {len(data['entries'])} entries; no LLM)")
    if args.open:
        webbrowser.open(out.resolve().as_uri())
    return 0


def _ui_post(root: Path, form: dict[str, list[str]]) -> str:
    """Apply one Jev form action; returns the flash-message code."""
    action = (form.get("action") or [""])[0]
    if action == "save_key":
        key = (form.get("key") or [""])[0].strip()
        if not JEV_KEY_RE.match(key):
            return "bad_key"
        try:
            jev_key_store(key)
        except (OSError, subprocess.CalledProcessError):
            return "no_store"
        return "saved"
    if action == "clear_key":
        jev_key_clear()
        return "cleared"
    if action in ("on", "off"):
        jev_enable(root, action == "on")
        return action
    return ""


def _ui_serve(root: Path, args: argparse.Namespace) -> int:
    """Serve the chronicle on 127.0.0.1 with the Jev form. Only this machine can reach it;
    a per-run token, a Host check (DNS rebinding) and an Origin check (other sites
    posting here) guard the form. The key is never sent back to the page."""
    import http.server
    import secrets

    token = secrets.token_urlsafe(24)
    hosts: set[str] = set()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:  # keep form bodies out of the console
            pass

        def _refuse(self, code: int) -> None:
            self.send_error(code)

        def do_GET(self) -> None:  # noqa: N802
            if self.headers.get("Host", "") not in hosts:
                return self._refuse(403)
            path, _, query = self.path.partition("?")
            if path != "/":
                return self._refuse(404)
            data = _ui_collect(root, args.title or root.name, args.lang)
            data.update(jev=jev_status(root), serve=token,
                        flash=(urllib.parse.parse_qs(query).get("m") or [""])[0])
            body = render_ui(data).encode("utf-8")
            self.send_response(200)
            for name, value in (("Content-Type", "text/html; charset=utf-8"), ("Cache-Control", "no-store"),
                                ("X-Frame-Options", "DENY"), ("Referrer-Policy", "no-referrer"),
                                ("Content-Length", str(len(body)))):
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            origin = self.headers.get("Origin")
            if (self.headers.get("Host", "") not in hosts or self.path != "/jev"
                    or (origin and origin not in {f"http://{h}" for h in hosts})):
                return self._refuse(403)
            length = int(self.headers.get("Content-Length") or 0)
            if length > 4096:
                return self._refuse(413)
            form = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
            if not secrets.compare_digest((form.get("token") or [""])[0], token):
                return self._refuse(403)
            message = _ui_post(root, form)
            self.send_response(303)
            self.send_header("Location", f"/?m={message}#jev")
            self.end_headers()

    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    port = server.server_address[1]
    hosts.update({f"127.0.0.1:{port}", f"localhost:{port}"})
    url = f"http://127.0.0.1:{port}/"
    print(f"# Arbor UI: {url} (only this computer; Ctrl+C stops it)")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0



UI_CSS = r"""
:root{
  --peat:#12100d; --loam:#1a1712; --loam-2:#25201a;
  --line:rgba(236,226,204,.11); --line-2:rgba(236,226,204,.22);
  --heart:#ece2cc; --muted:#b3a992; --faint:#8b826e;
  --lichen:#9bbf7f; --sap:#d9a441; --ember:#d9694a; --slate:#86b1c4;
  --early:#b69a6c; --late:#70502f; --bark:#251a11;
  --kind-dec:var(--sap); --kind-inv:var(--lichen); --kind-bug:var(--ember);
  --kind-task:var(--slate); --kind-change:var(--heart); --kind-commit:var(--faint);
  --serif:"Iowan Old Style","Palatino Linotype",Constantia,"Book Antiqua",Palatino,Georgia,serif;
  --sans:"Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,"Helvetica Neue",Arial,sans-serif;
  --mono:ui-monospace,"Cascadia Mono","SF Mono",Consolas,"Liberation Mono",monospace;
  color-scheme:dark;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:84px;background:var(--peat)}
body{margin:0;background:var(--peat);color:var(--heart);font:16px/1.6 var(--sans);
  -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
a{color:inherit}
code{font:500 12px var(--mono)}
.jev{max-width:720px;display:grid;gap:18px}
.jev-rows{list-style:none;margin:0;padding:0;border-top:1px solid var(--line)}
.jev-rows li{display:flex;justify-content:space-between;gap:16px;padding:10px 0;border-bottom:1px solid var(--line)}
.jev-rows span{color:var(--muted)}
.jev-rows b{font:500 13px var(--mono);overflow-wrap:anywhere;text-align:right}
.jev-form{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.jev-form label{flex-basis:100%;color:var(--muted);font-size:14px}
.jev-form input{flex:1 1 260px;min-width:0;padding:10px 12px;border-radius:8px;border:1px solid var(--line-2);
  background:var(--loam);color:var(--heart);font:500 13px var(--mono)}
.jev-form button{padding:10px 16px;border-radius:8px;border:1px solid var(--lichen);background:var(--lichen);
  color:var(--peat);font:600 13px var(--sans);cursor:pointer}
.jev-form button.quiet{background:transparent;color:var(--muted);border-color:var(--line-2)}
.jev-form input:focus-visible,.jev-form button:focus-visible{outline:2px solid var(--lichen);outline-offset:2px}
.jev-flash{margin:0;padding:10px 14px;border-left:2px solid var(--sap);background:var(--loam);color:var(--heart)}
a:focus-visible,summary:focus-visible{outline:2px solid var(--lichen);outline-offset:3px;border-radius:4px}
:root{--wrap:1240px;--pad:clamp(20px,4vw,56px)}
main{max-width:var(--wrap);margin:0 auto;padding:0 var(--pad)}

.masthead{position:sticky;top:0;z-index:20;display:flex;align-items:center;gap:32px;
  padding:14px clamp(20px,4vw,56px);background:rgba(18,16,13,.86);
  -webkit-backdrop-filter:blur(12px);backdrop-filter:blur(12px);border-bottom:1px solid var(--line)}
.brand{display:inline-flex;align-items:center;gap:10px;text-decoration:none;
  font:600 12px var(--sans);letter-spacing:.24em;text-transform:uppercase}
.masthead nav{display:flex;gap:26px;font-size:13px;color:var(--muted)}
.masthead nav a{text-decoration:none;padding:4px 0;border-bottom:1px solid transparent}
.masthead nav a:hover{color:var(--heart);border-color:var(--lichen)}
.proj{margin-left:auto;font:500 11px var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--faint)}

.eyebrow{margin:0 0 18px;font:600 11px/1 var(--sans);letter-spacing:.18em;text-transform:uppercase;color:var(--lichen)}
.eyebrow::before{content:"";display:inline-block;width:28px;height:1px;background:currentColor;
  vertical-align:middle;margin-right:12px}
h1,h2,h3,h4{font-weight:500}
h1{margin:0;font:500 clamp(64px,10.5vw,152px)/.88 var(--serif);letter-spacing:-.03em;overflow-wrap:anywhere}
h1 em,h2 em{font-style:italic;font-weight:400;color:var(--lichen)}
h2{margin:0;font:500 clamp(34px,4.6vw,60px)/1.05 var(--serif);letter-spacing:-.015em}
.tagline{margin:22px 0 0;font:italic 400 clamp(26px,3.2vw,42px)/1.15 var(--serif)}
.sub{max-width:46ch;margin:18px 0 0;color:var(--muted);font-size:17px}
.cta{display:inline-flex;align-items:center;gap:12px;margin-top:36px;padding-bottom:10px;
  border-bottom:1px solid var(--line-2);color:var(--lichen);text-decoration:none;font-size:14px;letter-spacing:.02em;
  transition:border-color .2s,gap .2s}
.cta:hover{border-color:var(--lichen);gap:16px}

.hero{position:relative;display:grid;grid-template-columns:minmax(0,.9fr) minmax(0,1.1fr);
  gap:clamp(24px,5vw,72px);align-items:center;min-height:min(90vh,880px);padding:72px 0 104px}
.hero-art{margin:0}
.hero-art figcaption{max-width:52ch;margin:14px 0 0;color:var(--faint);font-size:13px}
.hero-tag{position:absolute;bottom:32px;margin:0;font:600 11px var(--sans);letter-spacing:.16em;
  text-transform:uppercase;color:var(--faint)}
.hero-tag.l{left:0}.hero-tag.r{right:0}

.chart{padding:22px 24px 20px;background:var(--loam);border:1px solid var(--line);border-radius:14px}
.chart-head{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;gap:4px 16px;margin:0 0 22px}
.chart-head b{font:600 14px var(--sans)}
.chart-head span{font-size:12px;color:var(--faint)}
.plot{display:grid;grid-template-columns:30px minmax(0,1fr);height:240px}
.yaxis{position:relative}
.yaxis span{position:absolute;right:10px;transform:translateY(50%);font:500 11px var(--mono);color:var(--faint)}
.field{position:relative;border-bottom:1px solid var(--line-2)}
.gl{position:absolute;left:0;right:0;height:0;border-top:1px solid var(--line)}
.bars{position:absolute;inset:0;display:grid;grid-template-columns:repeat(var(--n),minmax(0,1fr));gap:3px}
.col{position:relative;justify-self:center;width:min(100%,38px);height:100%;display:flex;
  flex-direction:column-reverse;text-decoration:none}
a.col i{display:block;flex:none;background:var(--c);border-top:1px solid var(--loam)}
a.col i:last-child{border-radius:3px 3px 0 0}
a.col:hover i,a.col:focus-visible i{filter:brightness(1.25)}
a.col:hover::after{content:"";position:absolute;inset:0;background:rgba(236,226,204,.06)}
.xaxis{position:relative;height:22px;margin:8px 0 0 30px}
.xaxis span{position:absolute;transform:translateX(-50%);white-space:nowrap;font:500 11px var(--mono);color:var(--faint)}
.chart .legend{margin-top:14px}
.chart .fine{margin:10px 0 0}
.sw{display:inline-block;width:9px;height:9px;margin-right:8px;border-radius:2px;background:var(--c)}
.chart .legend .sw{width:9px;height:9px}

.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));border-block:1px solid var(--line)}
.stats>div{padding:30px 26px;border-left:1px solid var(--line)}
.stats>div:first-child{border-left:0;padding-left:0}
.num{margin:0;font:400 clamp(34px,4vw,54px)/1 var(--serif);font-variant-numeric:lining-nums}
.label{margin:10px 0 0;font-size:12px;color:var(--muted);letter-spacing:.04em}

.block{padding-top:clamp(72px,10vw,132px)}
.sec-head{margin-bottom:52px}
.lead{max-width:58ch;margin:18px 0 0;color:var(--muted)}
.prologue{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:clamp(24px,6vw,88px);align-items:start}
.prose p{margin:0 0 18px;max-width:54ch;color:var(--muted);font-size:17px}
.prose p:first-child{color:var(--heart);font:400 21px/1.5 var(--serif)}

.chapter{display:grid;grid-template-columns:96px minmax(0,1fr);gap:28px;padding:40px 0 64px;
  border-top:1px solid var(--line)}
.stamp b{display:block;font:400 64px/.9 var(--serif);font-variant-numeric:oldstyle-nums;color:var(--early);
  transition:color .3s}
.stamp span{display:block;margin-top:10px;font:600 11px var(--sans);letter-spacing:.14em;
  text-transform:uppercase;color:var(--faint)}
.kinds{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 16px}
.chip{display:inline-flex;align-items:center;gap:7px;padding:5px 11px 5px 9px;border:1px solid var(--line-2);
  border-radius:999px;font:600 11px/1 var(--sans);letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.chip::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--c,var(--faint))}
.k-dec{--c:var(--kind-dec)}.k-inv{--c:var(--kind-inv)}.k-bug{--c:var(--kind-bug)}
.k-task{--c:var(--kind-task)}.k-change{--c:var(--kind-change)}.k-commit{--c:var(--kind-commit)}
.chapter h3{margin:0 0 12px;font:500 clamp(26px,3vw,38px)/1.15 var(--serif);letter-spacing:-.01em}
.lede{max-width:64ch;margin:0 0 20px;color:var(--muted)}
ul.picks{list-style:none;margin:0 0 22px;padding:0;display:grid;gap:9px}
ul.picks li{display:flex;gap:12px;align-items:baseline;font-size:15px}
ul.picks .chip{flex:none;padding:3px 9px 3px 8px;font-size:10px}
details{border-top:1px solid var(--line);padding-top:14px}
summary{display:flex;justify-content:space-between;align-items:center;cursor:pointer;list-style:none;font-size:14px}
summary::-webkit-details-marker{display:none}
summary::after{content:"+";color:var(--lichen);font-size:20px;line-height:1}
details[open]>summary::after{content:"\2212"}
ul.ent{list-style:none;margin:16px 0 0;padding:0;display:grid;gap:20px}
.ent-head{display:flex;flex-wrap:wrap;gap:6px 12px;align-items:baseline}
.ent-head code{color:var(--sap)}
.ent-head b{font-weight:600}
.status{font:600 10px var(--sans);letter-spacing:.1em;text-transform:uppercase;color:var(--faint)}
dl{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:4px 16px;margin:8px 0 0;font-size:14px}
dt{color:var(--faint);text-transform:capitalize}
dd{margin:0;color:var(--muted)}
h4{margin:22px 0 8px;font:600 11px var(--sans);letter-spacing:.14em;text-transform:uppercase;color:var(--faint)}
ul.changes{list-style:none;margin:16px 0 0;padding:0;display:grid;gap:16px}
ul.changes>li>b{font-weight:600}
ul.changes ul{margin:6px 0 0;padding-left:18px;color:var(--muted);font-size:14px}
ul.changes ul li{margin:3px 0}
ul.commits{list-style:none;margin:0;padding:0;display:grid;gap:6px;font-size:14px}
ul.commits li{display:flex;gap:12px}
ul.commits code{flex:none;color:var(--faint)}
ul.commits .more{color:var(--faint)}
.result{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:baseline;margin:24px 0 0;font-size:13px;color:var(--muted)}
.result span{font:600 11px var(--sans);letter-spacing:.14em;text-transform:uppercase;color:var(--lichen)}
.empty{color:var(--muted);max-width:56ch}

.ring-cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px}
.ring-card{padding:28px;background:var(--loam);border:1px solid var(--line);border-radius:14px;border-top-width:2px}
.ring-card:nth-child(1){border-top-color:var(--lichen)}
.ring-card:nth-child(2){border-top-color:var(--sap)}
.ring-card:nth-child(3){border-top-color:var(--slate)}
.ring-card .eyebrow{margin-bottom:14px}
.ring-card .eyebrow::before{display:none}
.big{margin:0 0 16px;font:400 44px/1 var(--serif);font-variant-numeric:lining-nums}
.big small{font:400 14px var(--sans);color:var(--muted)}
.meter{height:6px;border-radius:99px;background:var(--loam-2);overflow:hidden}
.meter i{display:block;height:100%;border-radius:inherit;background:var(--lichen)}
.cap{margin:8px 0 0;font-size:12px;color:var(--faint)}
.desc{margin:16px 0 0;color:var(--muted);font-size:14px}
.fine{margin:14px 0 0;font-size:12px;color:var(--faint)}
ul.rows{list-style:none;margin:18px 0 0;padding:0}
ul.rows li{display:grid;grid-template-columns:1fr auto;gap:5px 12px;padding:9px 0;border-top:1px solid var(--line);font-size:13px}
ul.rows b{font-weight:500;font-variant-numeric:tabular-nums}
ul.rows i{grid-column:1/-1;display:block;height:3px;border-radius:2px;background:var(--sap);opacity:.75}
.health{display:flex;align-items:center;gap:10px;margin:26px 0 0;font-size:13px;color:var(--muted)}
.health::before{content:"";width:8px;height:8px;border-radius:50%;background:var(--lichen)}
.health.bad::before{background:var(--ember)}

.arcs{margin:0}
.arcs svg{display:block;width:100%;height:auto;background:var(--loam);border:1px solid var(--line);border-radius:14px}
.arcs text{font:500 10px var(--mono);fill:var(--faint)}
.legend{display:flex;flex-wrap:wrap;gap:8px 20px;margin:16px 0 0;padding:0;list-style:none;font-size:13px;color:var(--muted)}
.legend i{display:inline-block;width:18px;height:3px;margin-right:8px;border-radius:2px;vertical-align:middle}
.legend i.sw{width:9px;height:9px;margin-right:8px;border-radius:2px;background:var(--c)}

.token-top{display:grid;grid-template-columns:minmax(0,.9fr) minmax(0,1.5fr);gap:32px;padding:34px;
  background:var(--loam);border:1px solid var(--line);border-radius:14px}
.cost{margin:8px 0 12px;font:400 clamp(48px,7vw,92px)/1 var(--serif);font-variant-numeric:lining-nums;color:var(--sap)}
.token-cols{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:26px 24px;align-content:center}
.token-cols .num{font-size:clamp(28px,3vw,38px)}
.usd{margin:6px 0 0;color:var(--sap);font-size:14px}
.token-cols .label{display:flex;align-items:center}
.pct{margin:6px 0 0;font-size:13px;color:var(--faint);font-variant-numeric:tabular-nums}
.share{margin-top:20px}
.share .label{margin:0 0 10px}
.stack{display:flex;gap:2px;height:14px;border-radius:99px;overflow:hidden;background:var(--loam-2)}
.stack i{display:block;min-width:3px}
.callout{max-width:72ch;margin:34px 0;padding:2px 0 2px 22px;border-left:2px solid var(--lichen);color:var(--muted)}
.sessions ul{list-style:none;margin:14px 0 0;padding:0;display:grid;gap:12px}
.sessions li{display:grid;grid-template-columns:76px minmax(90px,1fr) 84px minmax(0,auto);gap:14px;align-items:center;font-size:14px}
.sessions .fine{margin:0}
.bar{display:block;height:8px;border-radius:99px;background:var(--loam-2);overflow:hidden}
.bar i{display:block;height:100%;border-radius:inherit;background:var(--early)}
.langs{list-style:none;margin:0;padding:0;display:grid;gap:12px;max-width:560px}
.langs li{display:grid;grid-template-columns:110px minmax(0,1fr) 56px;gap:16px;align-items:center;font-size:14px}
.langs b{font-weight:500;text-align:right;font-variant-numeric:tabular-nums}

footer{max-width:var(--wrap);margin:128px auto 0;padding:0 var(--pad)}
.foot{display:flex;flex-wrap:wrap;justify-content:space-between;gap:12px 24px;padding:32px 0 60px;
  border-top:1px solid var(--line);color:var(--faint);font-size:13px}
footer p{margin:0}footer .fine{margin:0}

.js .reveal{opacity:0;transform:translateY(14px);transition:opacity .6s ease,transform .6s ease}
.js .reveal.in{opacity:1;transform:none}
@media (prefers-reduced-motion:reduce){
  html{scroll-behavior:auto}
  .js .reveal{opacity:1;transform:none;transition:none}
}
@media (max-width:960px){
  .hero{grid-template-columns:minmax(0,1fr);min-height:0;padding:44px 0 96px}
  .prologue,.token-top{grid-template-columns:minmax(0,1fr)}
  .ring-cards{grid-template-columns:minmax(0,1fr)}
  .stats{grid-template-columns:repeat(2,minmax(0,1fr))}
  .stats>div:nth-child(3){border-left:0;padding-left:0}
  .stats>div:nth-child(n+3){border-top:1px solid var(--line)}
  .chapter{grid-template-columns:minmax(0,1fr);gap:14px}
  .stamp{display:flex;align-items:baseline;gap:12px}
  .stamp b{font-size:48px}.stamp span{margin:0}
  .masthead{gap:16px}.masthead nav{gap:16px;overflow-x:auto}.proj{display:none}
  .sessions li{grid-template-columns:70px minmax(60px,1fr) 70px}.sessions li .fine{grid-column:1/-1}
}
"""


UI_JS = r"""
(function () {
  var doc = document;
  var items = [].slice.call(doc.querySelectorAll('.reveal'));
  if ('IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
      });
    }, { rootMargin: '0px 0px -6% 0px', threshold: 0.04 });
    items.forEach(function (el) { io.observe(el); });
  } else {
    items.forEach(function (el) { el.classList.add('in'); });
  }
})();
"""


MANAGED_START = "<!-- CONTEXT-ARBOR:START -->"


MANAGED_END = "<!-- CONTEXT-ARBOR:END -->"


LEGACY_MANAGED_START = "<!-- CTX-AGENT-CONTEXT-STACK:START -->"


LEGACY_MANAGED_END = "<!-- CTX-AGENT-CONTEXT-STACK:END -->"


VALID_AGENTS = ("generic", "codex", "claude")


def _parse_agents(value: str) -> list[str]:
    if value == "all":
        return list(VALID_AGENTS)
    agents = [p.strip().lower() for p in value.split(",") if p.strip()]
    bad = sorted(set(agents) - set(VALID_AGENTS))
    if bad:
        raise argparse.ArgumentTypeError(f"unknown agents: {', '.join(bad)}")
    return agents or ["generic"]


def _write_if_absent(path: Path, content: str) -> str:
    if path.exists():
        return "kept"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return "created"


LEGACY_AGENT_CONTEXT_SHA256 = "33fe20ecdedd8e6f6abf89e92a0f89e6cf6a3fbf2b477595bf3b16a0800010e7"


# Stock AGENT_CONTEXT.md files shipped by earlier Context Arbor releases (v0.3.0, v0.4.0).
PREVIOUS_AGENT_CONTEXT_SHA256 = frozenset({
    "eaaab40c91a6ccd8cfd1885fc99500d430954d67be1ed80cfd8e2ebc80a506a1",
    "5691e37b24c6e65b9869e68b9163de8eec570fccecdb405e0d1a433ca8fe19d4",
})


# Stock managed blocks (START..END, stripped) shipped by earlier releases (v0.3.0, v0.4.0).
PREVIOUS_MANAGED_BLOCK_SHA256 = frozenset({
    "7611e48692c2d0e308d7ddae2dcd0c1c680116082037b3a7b384d25d629fbfc0",
    "89f0971e5bdd6133aec8b10d9958ab966b1a0637ff0a2189daa34a0119547628",
})


def _write_or_migrate_agent_context(path: Path, content: str) -> str:
    """Replace only the untouched legacy CACP context; preserve user-owned files."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return "created"
    current = read_text(path).replace("\r\n", "\n")
    digest = hashlib.sha256(current.encode("utf-8")).hexdigest()
    if digest == LEGACY_AGENT_CONTEXT_SHA256 or digest in PREVIOUS_AGENT_CONTEXT_SHA256:
        path.write_text(content, encoding="utf-8")
        return "migrated"
    return "kept"


def _upgrade_managed_block(path: Path, current: str, block: str) -> str:
    """Refresh a managed block only when it is byte-for-byte a stock block of an earlier
    release. A block the user edited, or one already current, is left exactly as it is."""
    start = current.index(MANAGED_START)
    end = current.find(MANAGED_END, start)
    if end == -1:
        return "kept"
    end += len(MANAGED_END)
    existing = current[start:end].replace("\r\n", "\n").strip()
    if existing == block.strip():
        return "kept"
    if hashlib.sha256(existing.encode("utf-8")).hexdigest() not in PREVIOUS_MANAGED_BLOCK_SHA256:
        return "kept"
    path.write_text(current[:start] + block.strip() + current[end:], encoding="utf-8")
    return "upgraded"


def _append_managed_block(path: Path, block: str) -> str:
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    if MANAGED_START in current:
        return _upgrade_managed_block(path, current, block)
    if LEGACY_MANAGED_START in current and LEGACY_MANAGED_END in current:
        start = current.index(LEGACY_MANAGED_START)
        end = current.index(LEGACY_MANAGED_END, start) + len(LEGACY_MANAGED_END)
        prefix = current[:start].rstrip()
        suffix = current[end:].strip()
        merged = (prefix + ("\n\n" if prefix else "") + block.strip()
                  + ("\n\n" + suffix if suffix else "") + "\n")
        path.write_text(merged, encoding="utf-8")
        return "migrated"
    path.parent.mkdir(parents=True, exist_ok=True)
    sep = "\n\n" if current.strip() else ""
    path.write_text(current.rstrip() + sep + block.strip() + "\n", encoding="utf-8")
    return "appended"


_ARCHITECTURE_ADAPTER_LINE = (
    f"Update `memory/architecture.md` only when the stack or structure changes "
    f"(short English facts, ~{ARCHITECTURE_MAX_TOKENS} tokens); otherwise leave it, "
    f"and read it again only then or when asked directly."
)
_CODE_ADAPTER_LINE = (
    'Find code without opening whole files: `python arbor.py code map` (overview), '
    '`code find "topic"`, `code outline FILE`, `code show FILE:SYMBOL` (or `FILE:START-END`).'
)
_CLEAR_ADAPTER_LINE = (
    "Suggest `/clear`, not `/compact` (compaction is a model call); saved state comes back on its own."
)
_ADAPTER_BODY = "\n".join((
    "When prior project context is needed, read `memory/NOW.md` first and follow links on demand.",
    'Search durable notes with `python arbor.py memory query "question"`; do not scan the vault.',
    _CODE_ADAPTER_LINE,
    "Keep only the active task in `memory/NOW.md`; store durable outcomes in linked notes.",
    _ARCHITECTURE_ADAPTER_LINE,
    "Preserve user rules. Update their checksum only after explicit user approval.",
    'Before clearing context, save useful state with `python arbor.py session save --note "..."`.',
    _CLEAR_ADAPTER_LINE,
    "Use `python arbor.py session restore` to recover it. Treat restored notes as potentially stale.",
    "Open the vault with `python arbor.py memory open`. Context Arbor invokes no model.",
))
AGENT_CONTEXT_MD = "# Context Arbor: memory and sessions\n\n" + _ADAPTER_BODY + "\n"
ADAPTER_AGENTS = ADAPTER_CLAUDE = (
    MANAGED_START + "\n# Context Arbor: memory and sessions\n\n" + _ADAPTER_BODY
    + "\n\n" + MANAGED_END + "\n"
)

CLAUDE_SETTINGS_JSON = json.dumps({
    "autoMemoryEnabled": False,
    "hooks": {
        "UserPromptSubmit": [
            {"hooks": [{"type": "command",
                        "command": _hook_command("session gauge")}]},
        ],
        "PreCompact": [
            {"hooks": [{"type": "command",
                        "command": _hook_command("session snapshot")}]},
            {"matcher": "manual",
             "hooks": [{"type": "command",
                        "command": _hook_command("session compact-guard --trigger manual")}]},
            {"matcher": "auto",
             "hooks": [{"type": "command",
                        "command": _hook_command("session compact-guard --trigger auto")}]},
        ],
        "SessionEnd": [
            {"hooks": [{"type": "command",
                        "command": _hook_command("session snapshot")}]},
        ],
        "SessionStart": [
            {"matcher": "startup|clear|compact|resume",
             "hooks": [{"type": "command",
                        "command": _hook_command("session restore")}]},
        ],
    },
}, indent=2) + "\n"


def _merge_claude_local_settings(path: Path) -> str:
    """Disable Claude auto memory and add Arbor session hooks without replacing user settings."""
    existed = path.is_file()
    data: dict = {}
    if existed:
        loaded = json.loads(read_text(path))
        if not isinstance(loaded, dict):
            raise ValueError(f"Claude settings must contain a JSON object: {path}")
        data = loaded
    changed = data.get("autoMemoryEnabled") is not False
    data["autoMemoryEnabled"] = False
    hooks = data.setdefault("hooks", {})
    changed = _upgrade_hook_commands(hooks) or changed
    canonical = json.loads(CLAUDE_SETTINGS_JSON)["hooks"]
    for event, groups in canonical.items():
        current = hooks.setdefault(event, [])
        existing_commands = {
            hook.get("command")
            for group in current if isinstance(group, dict)
            for hook in group.get("hooks", []) if isinstance(hook, dict)
        }
        for group in groups:
            commands = {hook.get("command") for hook in group.get("hooks", [])}
            if not commands.issubset(existing_commands):
                current.append(group)
                existing_commands.update(commands)
                changed = True
                continue
            for mine in current:  # an older install of this group: bring its matcher up to date
                if (isinstance(mine, dict) and mine.get("matcher") != group.get("matcher")
                        and {h.get("command") for h in mine.get("hooks", [])
                             if isinstance(h, dict)} == commands):
                    if "matcher" in group:
                        mine["matcher"] = group["matcher"]
                    else:
                        mine.pop("matcher", None)
                    changed = True
    if changed or not existed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    return "updated" if existed and changed else "created" if not existed else "kept"


def cleanup_legacy_hooks(root: Path) -> None:
    """Remove exact pre-Arbor hook commands; preserve all other settings."""
    for name in ("settings.json", "settings.local.json"):
        path = root / ".claude" / name
        if not path.is_file():
            continue
        data = json.loads(read_text(path))
        hooks = data.get("hooks", {})
        changed = False
        for event, groups in list(hooks.items()):
            if not isinstance(groups, list):
                continue
            kept = []
            for group in groups:
                if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                    kept.append(group)
                    continue
                remaining = []
                for hook in group["hooks"]:
                    if not isinstance(hook, dict) or hook.get("type") != "command":
                        remaining.append(hook)
                        continue
                    command = hook.get("command", "").strip()
                    if command in {"python ctx.py guard", "python ctx.py hook",
                                   "python3 ctx.py guard", "python3 ctx.py hook"}:
                        changed = True
                        continue
                    old_session_commands = {
                        "python ctx.py session gauge", "python ctx.py session snapshot",
                        "python ctx.py session restore", "python3 ctx.py session gauge",
                        "python3 ctx.py session snapshot", "python3 ctx.py session restore",
                    }
                    if command in old_session_commands:
                        changed = True
                    else:
                        remaining.append(hook)
                if remaining:
                    kept.append({**group, "hooks": remaining})
                elif group["hooks"]:
                    changed = True
            if kept:
                hooks[event] = kept
            elif groups:
                hooks.pop(event, None)
        if changed:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize memory, adapters and session hooks without replacing user files."""
    root = _project_root(args.path)
    agents = args.agents if isinstance(args.agents, list) else _parse_agents(args.agents)
    results: dict[str, str] = {}

    # 1. memory vault + active hot ring + gitignore (reuses the tested initializer).
    cmd_memory_init(argparse.Namespace(path=str(root)))

    # 2. agent-facing instruction files.
    if "generic" in agents:
        results["AGENT_CONTEXT.md"] = _write_or_migrate_agent_context(
            root / "AGENT_CONTEXT.md", AGENT_CONTEXT_MD)
    if "codex" in agents:
        results["AGENTS.md"] = _append_managed_block(root / "AGENTS.md", ADAPTER_AGENTS)
    if "claude" in agents:
        results["CLAUDE.md"] = _append_managed_block(root / "CLAUDE.md", ADAPTER_CLAUDE)
        results[".claude/settings.local.json"] = _merge_claude_local_settings(
            root / ".claude" / "settings.local.json")

    cleanup_legacy_hooks(root)
    print(f"# Context Arbor memory and sessions initialized in {root}")
    for name, result in results.items():
        print(f"- {name}: {result}")
    if "claude" in agents:
        print("# optional: block model compaction so /clear is the only way to shrink context: "
              "python arbor.py session compaction --mode all")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Legacy Windows consoles default to cp1251/cp866, which cannot encode
    # characters that routinely appear in answers (arrows, em dashes, etc.).
    # Force UTF-8 so output never crashes with UnicodeEncodeError; stdin too, so
    # a piped `session save --stdin` with non-ASCII text is not mojibaked by the
    # console's default decoder.
    for _stream in (sys.stdout, sys.stderr, sys.stdin):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(prog="arbor.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    ini = sub.add_parser(
        "init",
        help="scaffold Context Arbor into a project (memory + agent adapters + session hooks)")
    ini.add_argument("path", nargs="?", default=".")
    ini.add_argument("--agents", type=_parse_agents, default=_parse_agents("all"),
                     help="all or comma list: generic,codex,claude (default: all)")
    ini.set_defaults(fn=cmd_init)

    mem = sub.add_parser("memory", help="manage the project memory vault")
    mem_sub = mem.add_subparsers(dest="memory_cmd", required=True)

    mem_init = mem_sub.add_parser("init", help="create missing memory vault files")
    mem_init.add_argument("path", nargs="?", default=".")
    mem_init.set_defaults(fn=cmd_memory_init)

    mem_check = mem_sub.add_parser("check", help="validate memory structure and rules")
    mem_check.add_argument("path", nargs="?", default=".")
    mem_check.add_argument("--json", action="store_true")
    mem_check.set_defaults(fn=cmd_memory_check)

    mem_context = mem_sub.add_parser("context", help="build a small task context")
    mem_context.add_argument("task")
    mem_context.add_argument("--path", default=".")
    mem_context.set_defaults(fn=cmd_memory_context)

    mem_query = mem_sub.add_parser(
        "query", help="local top-k retrieval over durable notes (no LLM, no keys)")
    mem_query.add_argument("question")
    mem_query.add_argument("--path", default=".")
    mem_query.add_argument("--top", type=int, default=5, help="number of blocks to return")
    mem_query.add_argument("--json", action="store_true")
    mem_query.set_defaults(fn=cmd_memory_query)

    mem_rotate = mem_sub.add_parser("rotate", help="archive closed journal entries")
    mem_rotate.add_argument("path", nargs="?", default=".")
    mem_rotate.set_defaults(fn=cmd_memory_rotate)

    mem_rules = mem_sub.add_parser("rules-approve",
                                   help="approve the current permanent-rules checksum")
    mem_rules.add_argument("path", nargs="?", default=".")
    mem_rules.add_argument("--user-approved", action="store_true", required=True)
    mem_rules.set_defaults(fn=cmd_memory_rules_approve)

    mem_open = mem_sub.add_parser("open", help="open the memory folder in Obsidian")
    mem_open.add_argument("path", nargs="?", default=".")
    mem_open.add_argument("--install-obsidian", action="store_true")
    mem_open.set_defaults(fn=cmd_memory_open)

    mem_trace = mem_sub.add_parser(
        "trace",
        help="follow typed Relations edges from an entry ID (local graph, no LLM)")
    mem_trace.add_argument("id", help="entry ID, e.g. DEC-20260914-003")
    mem_trace.add_argument("--path", default=".")
    mem_trace.add_argument("--depth", type=int, default=2, help="max hops per direction")
    mem_trace.add_argument("--json", action="store_true")
    mem_trace.set_defaults(fn=cmd_memory_trace)

    def entry_writer(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--title")
        parser.add_argument("--status")
        parser.add_argument("--field", action="append", metavar="KEY=VALUE")
        parser.add_argument("--input-json", action="store_true",
                            help="read {title, status, fields} JSON from stdin")

    mem_add = mem_sub.add_parser("add", help="append a new typed entry, print its ID")
    mem_add.add_argument("--type", required=True, help=", ".join(ENTRY_TYPES))
    entry_writer(mem_add)
    mem_get = mem_sub.add_parser("get", help="show one entry by ID")
    mem_get.add_argument("id")
    mem_list = mem_sub.add_parser("list", help="list entries (filter by type/status)")
    mem_list.add_argument("--type", help="comma list, e.g. IDEA,KNW")
    mem_list.add_argument("--status", help="comma list, e.g. idea,in-progress")
    mem_list.add_argument("--include-archive", action="store_true")
    mem_list.add_argument("--limit", type=int, default=0)
    mem_update = mem_sub.add_parser("update", help="change fields/title/status of an entry")
    mem_update.add_argument("id")
    entry_writer(mem_update)
    mem_close = mem_sub.add_parser("close", help="set an entry status to closed (or --status)")
    mem_close.add_argument("id")
    mem_close.add_argument("--status")
    mem_delete = mem_sub.add_parser("delete", help="remove an entry block")
    mem_delete.add_argument("id")
    mem_delete.add_argument("--yes", action="store_true")
    mem_prune = mem_sub.add_parser("prune", help="delete monthly history files older than N months")
    mem_prune.add_argument("--older-than-months", type=int, required=True)
    mem_prune.add_argument("--include-archive", action="store_true")
    mem_prune.add_argument("--dry-run", action="store_true")
    for parser, fn in ((mem_add, cmd_memory_add), (mem_get, cmd_memory_get),
                       (mem_list, cmd_memory_list), (mem_update, cmd_memory_update),
                       (mem_close, cmd_memory_close), (mem_delete, cmd_memory_delete),
                       (mem_prune, cmd_memory_prune)):
        parser.add_argument("--path", default=".")
        parser.add_argument("--json", action="store_true")
        parser.set_defaults(fn=fn)

    code = sub.add_parser(
        "code",
        help="local code index: find code without reading whole files (no LLM)")
    code_sub = code.add_subparsers(dest="code_cmd", required=True)

    c_index = code_sub.add_parser("index", help="build or refresh the code index")
    c_index.add_argument("--path", default=".")
    c_index.set_defaults(fn=cmd_code_index)

    c_map = code_sub.add_parser(
        "map", help="bounded project overview: files, summaries, top-level symbols")
    c_map.add_argument("--path", default=".")
    c_map.add_argument("--dir", help="limit the map to one directory")
    c_map.add_argument("--budget", type=int, default=1500,
                       help="max estimated tokens of output (default 1500)")
    c_map.set_defaults(fn=cmd_code_map)

    c_find = code_sub.add_parser("find", help="rank symbols and files for a query")
    c_find.add_argument("query")
    c_find.add_argument("--path", default=".")
    c_find.add_argument("--top", type=int, default=8)
    c_find.add_argument("--kind", help="only this symbol kind (class, function, method, ...)")
    c_find.add_argument("--json", action="store_true")
    c_find.set_defaults(fn=cmd_code_find)

    c_outline = code_sub.add_parser("outline", help="symbols of one file with line ranges")
    c_outline.add_argument("file")
    c_outline.add_argument("--path", default=".")
    c_outline.add_argument("--limit", type=int, default=120)
    c_outline.set_defaults(fn=cmd_code_outline)

    c_show = code_sub.add_parser(
        "show", help="print FILE:SYMBOL, FILE:START-END or a small FILE with line numbers")
    c_show.add_argument("target")
    c_show.add_argument("--path", default=".")
    c_show.add_argument("--max-lines", type=int, default=150)
    c_show.set_defaults(fn=cmd_code_show)

    c_refs = code_sub.add_parser("refs", help="whole-word occurrences of a name")
    c_refs.add_argument("name")
    c_refs.add_argument("--path", default=".")
    c_refs.add_argument("--top", type=int, default=25)
    c_refs.set_defaults(fn=cmd_code_refs)

    stats = sub.add_parser(
        "stats",
        help="token usage from local Claude Code transcripts (read-only, offline)")
    stats.add_argument("--path", default=".")
    stats.add_argument("--transcripts", help="transcript directory (default: Claude Code's "
                       "folder for this project)")
    stats.add_argument("--prices", help="USD per million tokens: "
                       "input=..,cache_write=..,cache_read=..,output=..")
    stats.add_argument("--save", action="store_true", help="keep --prices in .arbor/config.json")
    stats.add_argument("--top", type=int, default=5)
    stats.add_argument("--why", action="store_true",
                       help="explain where each long session's cost goes (compaction, runaway "
                       "context, fixed prefix, thinking) and what to change")
    stats.add_argument("--json", action="store_true")
    stats.set_defaults(fn=cmd_stats)

    ui = sub.add_parser(
        "ui",
        help="write the project chronicle as one static HTML page (no LLM, no server)")
    ui.add_argument("--path", default=".")
    ui.add_argument("--out", help=f"output file (default {UI_DEFAULT_OUT.as_posix()})")
    ui.add_argument("--title", help="project title (default: the folder name)")
    ui.add_argument("--lang", choices=sorted(UI_TEXT), default="ru")
    ui.add_argument("--open", action="store_true", help="open the page in the browser")
    ui.add_argument("--serve", action="store_true",
                    help="serve the page on 127.0.0.1 with Jev settings (paste the OpenRouter key)")
    ui.add_argument("--port", type=int, default=8765, help="port for --serve (default 8765)")
    ui.set_defaults(fn=cmd_ui)

    jev = sub.add_parser(
        "jev",
        help="opt-in: a model (Jev via OpenRouter) picks the vault notes for each prompt")
    jev_sub = jev.add_subparsers(dest="jev_cmd", required=True)
    j_key = jev_sub.add_parser("key", help="store the OpenRouter key encrypted (per OS user)")
    j_key.add_argument("--stdin", action="store_true", help="read the key from stdin")
    j_key.add_argument("--clear", action="store_true", help="remove the stored key")
    jev_sub.add_parser("on", help="enable Jev for this project (adds its prompt hook)")
    jev_sub.add_parser("off", help="disable Jev for this project (removes its prompt hook)")
    j_status = jev_sub.add_parser("status", help="on/off, key present, today's spend")
    j_status.add_argument("--json", action="store_true")
    j_ask = jev_sub.add_parser("ask", help="print the notes Jev matches to a question")
    j_ask.add_argument("question")
    jev_sub.add_parser("hook", help="UserPromptSubmit hook (installed by `jev on`)")
    for j_parser in jev_sub.choices.values():
        j_parser.add_argument("--path", default=".")
    jev.set_defaults(fn=cmd_jev)

    ses = sub.add_parser(
        "session",
        help="session-length cost control: distill/restore state, context gauge")
    ses_sub = ses.add_subparsers(dest="session_cmd", required=True)

    s_save = ses_sub.add_parser(
        "save",
        help="store the agent-written session distillate (survives /compact, /clear)")
    s_save.add_argument("--note", help="distillate text inline")
    s_save.add_argument("--stdin", action="store_true",
                        help="read distillate text from stdin")
    s_save.add_argument("--max-chars", type=int, default=6000)
    s_save.set_defaults(fn=cmd_session_save)

    s_snap = ses_sub.add_parser(
        "snapshot",
        help="PreCompact hook: deterministic transcript extract into the state file")
    s_snap.add_argument("--transcript",
                        help="transcript .jsonl (hook JSON on stdin supplies it)")
    s_snap.set_defaults(fn=cmd_session_snapshot)

    s_rest = ses_sub.add_parser(
        "restore",
        help="SessionStart hook: print saved state for injection (by hand: show)")
    s_rest.add_argument("--source",
                        help="override hook source (startup/resume/clear/compact)")
    s_rest.add_argument("--max-age-hours", type=float, default=12.0,
                        help="on startup, skip state older than this (default 12)")
    s_rest.add_argument("--max-chars", type=int, default=8000)
    s_rest.set_defaults(fn=cmd_session_restore)

    s_comp = ses_sub.add_parser(
        "compaction",
        help="allow or block Claude Code's model-based /compact and auto-compact")
    s_comp.add_argument("--mode", choices=COMPACTION_MODES,
                        help="off (allow), manual (block /compact), all (also block auto)")
    s_comp.add_argument("--path", default=".")
    s_comp.set_defaults(fn=cmd_session_compaction)

    s_guard = ses_sub.add_parser(
        "compact-guard",
        help="PreCompact hook: snapshot, then block the compaction when the project opted in")
    s_guard.add_argument("--trigger", choices=("manual", "auto"), default="manual")
    s_guard.set_defaults(fn=cmd_session_compact_guard)

    s_gau = ses_sub.add_parser(
        "gauge",
        help="UserPromptSubmit hook: one-line warning when live context is expensive")
    s_gau.add_argument("--transcript",
                       help="transcript .jsonl (hook JSON on stdin supplies it)")
    s_gau.add_argument("--warn-tokens", type=int, default=None,
                       help="absolute warning size; default: growth thresholds from `session limit`")
    s_gau.add_argument("--crit-tokens", type=int, default=None,
                       help="absolute size to urge an immediate /clear")
    s_gau.add_argument("--warn-growth", dest="warn_growth", type=int, default=None)
    s_gau.add_argument("--crit-growth", dest="crit_growth", type=int, default=None)
    s_gau.set_defaults(fn=cmd_session_gauge)

    s_grd = ses_sub.add_parser(
        "guard",
        help="PreToolUse hook: warn once per threshold, optionally stop a runaway session")
    s_grd.add_argument("--transcript",
                       help="transcript .jsonl (hook JSON on stdin supplies it)")
    s_grd.set_defaults(fn=cmd_session_guard)

    s_lim = ses_sub.add_parser(
        "limit",
        help="show or set the context growth thresholds (warn / clear-now / hard stop)")
    s_lim.add_argument("--warn", dest="warn_growth", type=int, metavar="TOKENS",
                       help=f"advise a /clear after this growth (default {CONTEXT_LIMIT_DEFAULTS['warn_growth']})")
    s_lim.add_argument("--crit", dest="crit_growth", type=int, metavar="TOKENS",
                       help=f"urge it after this growth (default {CONTEXT_LIMIT_DEFAULTS['crit_growth']})")
    s_lim.add_argument("--stop", dest="stop_growth", type=int, metavar="TOKENS",
                       help="refuse further tool calls after this growth; 0 = never (default)")
    s_lim.add_argument("--path", default=".")
    s_lim.set_defaults(fn=cmd_session_limit)

    args = ap.parse_args(argv)
    if getattr(args, "command", None) and args.command and args.command[0] == "--":
        args.command = args.command[1:]
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
