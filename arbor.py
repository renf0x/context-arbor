#!/usr/bin/env python3
"""Context Arbor: local project memory, Obsidian and session continuity.

Commands: init, memory, session. Python standard library only.
"""


from __future__ import annotations


__version__ = "0.5.0"


import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
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
                       "message": f"over {NOW_MAX_TOKENS} estimated tokens; archive completed tasks"})

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
    return 0


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
    r"<(?:local-command|command-name|command-message|command-args|system-reminder)"
    r"|^\s*Caveat:|^\[Request interrupted"
    r"|^This session is being continued", re.IGNORECASE)


_EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def _extract_session_facts(transcript: Path) -> tuple[list[str], list[str]]:
    """Deterministic facts from the transcript tail: the last real user asks
    (what the work is) and the files the agent edited (where it happened).
    No LLM. This bounded extract is partial and does not preserve the full session."""
    asks: list[str] = []
    files: dict[str, None] = {}
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
            asks.append(text[:280] + (" ..." if len(text) > 280 else ""))
        elif msg.get("role") == "assistant" and isinstance(content, list):
            for c in content:
                if (isinstance(c, dict) and c.get("type") == "tool_use"
                        and c.get("name") in _EDIT_TOOLS):
                    inp = c.get("input") or {}
                    fp = inp.get("file_path") or inp.get("notebook_path")
                    if isinstance(fp, str):
                        files.pop(fp, None)  # re-insert: most-recent-last order
                        files[fp] = None
    return asks[-6:], list(files)[-15:]


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


def cmd_session_snapshot(args: argparse.Namespace) -> int:
    """PreCompact hook (also runnable by hand): deterministic transcript
    extract into the state file right before compaction, so even a session the
    agent never distilled keeps its floor. Silent on error; never blocks."""
    try:
        event = _read_hook_event()
        tp = event.get("transcript_path") or args.transcript
        if not tp or not Path(tp).is_file():
            return 0
        asks, files = _extract_session_facts(Path(tp))
        if not asks and not files:
            return 0
        lines: list[str] = []
        if asks:
            lines.append("Last user asks:")
            lines.extend(f"- {a}" for a in asks)
        if files:
            lines.append("Files edited this session:")
            lines.extend(f"- {f}" for f in files)
        _state_write(agent=None, auto="\n".join(lines))
        print(f"# auto snapshot written to {SESSION_STATE_PATH}")
    except Exception:  # a hook must never break the agent loop
        pass
    return 0


def cmd_session_restore(args: argparse.Namespace) -> int:
    """SessionStart hook (compact/clear/resume): print the saved state so the
    harness injects it into the fresh context. Small by construction -- the
    point is to spend ~1k tokens instead of re-reading files to re-derive
    where the work stood. Run by hand it doubles as `show`."""
    try:
        event = _read_hook_event()
        source = str(event.get("source") or args.source or "manual")
        if not SESSION_STATE_PATH.is_file():
            return 0
        age_h = (time.time() - SESSION_STATE_PATH.stat().st_mtime) / 3600.0
        if source == "startup" and age_h > args.max_age_hours:
            return 0  # stale state must not haunt a fresh, unrelated session
        text = read_text(SESSION_STATE_PATH).strip()
        if len(text) > args.max_chars:
            text = text[: args.max_chars].rstrip() + \
                "\n... [truncated; open .arbor/session-state.md]"
        print(f"[arbor session restore | source={source} | saved {age_h:.1f}h ago]")
        print(text)
        print("(This is a POINTER to where work stood, not ground truth: it can be "
              "stale or incomplete. Re-read a file before you change it; trust the "
              "code over this note on any conflict. Durable memory: memory/MEMORY.md; "
              "active task: memory/NOW.md.)")
    except Exception:  # a hook must never break the agent loop
        pass
    return 0


def cmd_session_gauge(args: argparse.Namespace) -> int:
    """UserPromptSubmit hook: inject ONE short line only when the live context
    is expensive. Reads the latest input usage from a Claude Code transcript as a
    context-size indicator, not a billing or quota measurement. Below the threshold it prints nothing and costs nothing."""
    try:
        event = _read_hook_event()
        tp = event.get("transcript_path") or args.transcript
        if not tp or not Path(tp).is_file():
            return 0
        ctx_tok = _last_context_tokens(Path(tp))
        if ctx_tok < args.warn_tokens:
            return 0
        if SESSION_STATE_PATH.is_file():
            age_h = (time.time() - SESSION_STATE_PATH.stat().st_mtime) / 3600.0
            state = f"state saved {age_h:.1f}h ago"
        else:
            state = "state NOT saved"
        push = "compact NOW" if ctx_tok >= args.crit_tokens else "compact soon"
        print(f"[arbor gauge] live context ~{ctx_tok / 1000:.0f}k tok -- every turn "
              f"re-sends it all; {state}. Batch remaining work, save state "
              f"(`python arbor.py session save --stdin`), recommend /compact to "
              f"the user ({push}).")
    except Exception:  # a hook must never break the agent loop
        pass
    return 0


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


def _write_or_migrate_agent_context(path: Path, content: str) -> str:
    """Replace only the untouched legacy CACP context; preserve user-owned files."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return "created"
    current = read_text(path).replace("\r\n", "\n")
    digest = hashlib.sha256(current.encode("utf-8")).hexdigest()
    if digest == LEGACY_AGENT_CONTEXT_SHA256:
        path.write_text(content, encoding="utf-8")
        return "migrated"
    return "kept"


def _append_managed_block(path: Path, block: str) -> str:
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    if MANAGED_START in current:
        return "kept"
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
AGENT_CONTEXT_MD = (
    '# Context Arbor: memory and sessions\n\nWhen prior project context is needed, read `memory/NOW.md` first and follow links on demand.\nSearch durable notes with `python arbor.py memory query "question"`; do not scan the vault.\nKeep only the active task in `memory/NOW.md`; store durable outcomes in linked notes.\n'
    + _ARCHITECTURE_ADAPTER_LINE +
    '\nPreserve user rules. Update their checksum only after explicit user approval.\nBefore clearing context, save useful state with `python arbor.py session save --note "..."`.\nUse `python arbor.py session restore` to recover it. Treat restored notes as potentially stale.\nOpen the vault with `python arbor.py memory open`. Context Arbor invokes no model.\n'
)
ADAPTER_AGENTS = ADAPTER_CLAUDE = (
    '<!-- CONTEXT-ARBOR:START -->\n# Context Arbor: memory and sessions\n\nWhen prior project context is needed, read `memory/NOW.md` first and follow links on demand.\nSearch durable notes with `python arbor.py memory query "question"`; do not scan the vault.\nKeep only the active task in `memory/NOW.md`; store durable outcomes in linked notes.\n'
    + _ARCHITECTURE_ADAPTER_LINE +
    '\nPreserve user rules. Update their checksum only after explicit user approval.\nBefore clearing context, save useful state with `python arbor.py session save --note "..."`.\nUse `python arbor.py session restore` to recover it. Treat restored notes as potentially stale.\nOpen the vault with `python arbor.py memory open`. Context Arbor invokes no model.\n\n<!-- CONTEXT-ARBOR:END -->\n'
)

CLAUDE_SETTINGS_JSON = json.dumps({
    "autoMemoryEnabled": False,
    "hooks": {
        "UserPromptSubmit": [
            {"hooks": [{"type": "command",
                        "command": "python arbor.py session gauge"}]},
        ],
        "PreCompact": [
            {"hooks": [{"type": "command",
                        "command": "python arbor.py session snapshot"}]},
        ],
        "SessionStart": [
            {"matcher": "compact|clear|resume",
             "hooks": [{"type": "command",
                        "command": "python arbor.py session restore"}]},
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
    s_rest.add_argument("--max-age-hours", type=float, default=72.0,
                        help="on startup, skip state older than this (default 72)")
    s_rest.add_argument("--max-chars", type=int, default=8000)
    s_rest.set_defaults(fn=cmd_session_restore)

    s_gau = ses_sub.add_parser(
        "gauge",
        help="UserPromptSubmit hook: one-line warning when live context is expensive")
    s_gau.add_argument("--transcript",
                       help="transcript .jsonl (hook JSON on stdin supplies it)")
    s_gau.add_argument("--warn-tokens", type=int, default=80_000,
                       help="warn when the live context exceeds this (default 80000)")
    s_gau.add_argument("--crit-tokens", type=int, default=120_000,
                       help="urge immediate compaction above this (default 120000)")
    s_gau.set_defaults(fn=cmd_session_gauge)

    args = ap.parse_args(argv)
    if getattr(args, "command", None) and args.command and args.command[0] == "--":
        args.command = args.command[1:]
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
