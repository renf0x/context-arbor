#!/usr/bin/env python3
"""Context Arbor: local project memory, Obsidian and session continuity.

Commands: init, memory, session. Python standard library only.
"""


from __future__ import annotations


__version__ = "0.3.0"


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


JOURNAL_MAX_TOKENS = 8000


JOURNAL_TARGET_TOKENS = 5000


MEMORY_JOURNALS = {
    "bugs.md": "bugs",
    "decisions.md": "decisions",
    "investigations.md": "investigations",
}


WIKI_LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


ENTRY_RE = re.compile(r"(?m)^##\s+((?:TASK|BUG|DEC|INV)-[^\n]+)\n")


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
    "architecture.md": "# Architecture\n\nProject architecture and stable component boundaries.\n",
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
    "decisions.md": "# Decision Log\n\n## DEC-000 Template\n\n- Status: example\n- Date: YYYY-MM-DD\n- Decision:\n- Reason:\n- Consequences:\n- Links:\n",
    "bugs.md": "# Bug Log\n\n## BUG-000 Template\n\n- Status: example\n- Date: YYYY-MM-DD\n- Symptom:\n- Cause:\n- Resolution:\n- Regression test:\n- Links:\n",
    "investigations.md": "# Investigation Log\n\n## INV-000 Template\n\n- Status: example\n- Date: YYYY-MM-DD\n- Question:\n- Findings:\n- Conclusion:\n- Links:\n",
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
- Links:
""",
    "templates/bug.md": """## BUG-YYYYMMDD-NNN

- Status: open
- Date: YYYY-MM-DD
- Symptom:
- Cause:
- Resolution:
- Regression test:
- Links:
""",
    "templates/decision.md": """## DEC-YYYYMMDD-NNN

- Status: active
- Date: YYYY-MM-DD
- Decision:
- Reason:
- Consequences:
- Links:
""",
    "templates/investigation.md": """## INV-YYYYMMDD-NNN

- Status: open
- Date: YYYY-MM-DD
- Question:
- Findings:
- Conclusion:
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
    return issues


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


AGENT_CONTEXT_MD = '# Context Arbor: memory and sessions\n\nWhen prior project context is needed, read `memory/NOW.md` first and follow links on demand.\nSearch durable notes with `python arbor.py memory query "question"`; do not scan the vault.\nKeep only the active task in `memory/NOW.md`; store durable outcomes in linked notes.\nPreserve user rules. Update their checksum only after explicit user approval.\nBefore clearing context, save useful state with `python arbor.py session save --note "..."`.\nUse `python arbor.py session restore` to recover it. Treat restored notes as potentially stale.\nOpen the vault with `python arbor.py memory open`. Context Arbor invokes no model.\n'
ADAPTER_AGENTS = ADAPTER_CLAUDE = '<!-- CONTEXT-ARBOR:START -->\n# Context Arbor: memory and sessions\n\nWhen prior project context is needed, read `memory/NOW.md` first and follow links on demand.\nSearch durable notes with `python arbor.py memory query "question"`; do not scan the vault.\nKeep only the active task in `memory/NOW.md`; store durable outcomes in linked notes.\nPreserve user rules. Update their checksum only after explicit user approval.\nBefore clearing context, save useful state with `python arbor.py session save --note "..."`.\nUse `python arbor.py session restore` to recover it. Treat restored notes as potentially stale.\nOpen the vault with `python arbor.py memory open`. Context Arbor invokes no model.\n\n<!-- CONTEXT-ARBOR:END -->\n'

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
