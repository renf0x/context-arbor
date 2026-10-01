"""Suite `co`: one real task from a real project (Contested Orbit, Godot/GDScript).

The other suites use a library nobody on this project wrote (`code`) or a made-up history
(`memory`). This one takes the user's own game, its real vault and a real open bug, and asks
for the fix the way the user would ask, in Russian, without naming a file. The vault is English.

The project is copied once into a frozen snapshot (heavy binary folders left out), so the
live project can keep changing while a run is in progress, and nothing here ever writes to it.
Scoring is static, from the diff the agent leaves: Godot is not installed, and the tests of the
project need it. The scorer's rubric was fixed before any run (see `score_bug016`).
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import suites

REPO = Path(__file__).resolve().parent.parent
SOURCE = Path(os.environ.get("CO_SOURCE", r"D:\Contested Orbit"))
FIXTURE = Path(os.environ.get("CO_FIXTURE", Path(tempfile.gettempdir()) / "arbor-bench" / "co-fixture"))

KEEP_DIRS = ("addons", "data", "docs", "localization", "memory", "scenes", "shaders", "src", "tests", "tools")
KEEP_FILES = ("game.md", "project.godot")
_IGNORE = shutil.ignore_patterns("__pycache__", "*.uid", "*.import")

# The user's words for the symptom, not the vault's: no file, no function, no bug number.
PROMPT = (
    "Автосейв в игре иногда срабатывает несколько раз подряд в один и тот же игровой момент: "
    "в логе событий идёт SAVED autosave_1, autosave_2, autosave_3, снова autosave_1 и так далее, "
    "и у всех одно и то же игровое время. Найди причину и исправь. "
    "Godot запускать не нужно, проверяй чтением кода."
)
FOOTER = ("\n\nWork efficiently. When you are done, end your reply with exactly one line of the form "
          '`ANSWER: {"file": "<path of the main file you changed>"}` and nothing after it.')

CONTROL_POINTER = ("# Contested Orbit\n\nProject notes live in `memory/` "
                   "(NOW.md, decisions.md, bugs.md, knowledge.md).\n")

# Where the fix belongs (the timer is in the menu) and what counts as collateral damage.
RIGHT_PLACE = ("src/ui/menu/game_menu.gd", "src/app/save_store.gd")
ALLOWED_SRC = RIGHT_PLACE + ("src/app/settings.gd",)
# The vault's own link for BUG-016 points here, and this file has no autosave code.
STALE_LEAD = "src/host/main.gd"
# Sim state hangs off `_host.world`; a fix that follows game time has to reach for it.
SIM_TIME_RE = re.compile(r"\bworld\b")
_NOISE = (".arbor/", ".claude/", "arbor.py", "claude.md", "agents.md", "memory/", "__pycache__", ".pyc")


def snapshot(refresh: bool = False) -> tuple[Path, str]:
    """(path, id) of the frozen copy of the project. The id changes when the copy does."""
    marker = FIXTURE / ".snapshot-id"
    if refresh and FIXTURE.exists():
        shutil.rmtree(FIXTURE)
    if not marker.exists():
        if not SOURCE.is_dir():
            raise SystemExit(f"Contested Orbit not found at {SOURCE} (set CO_SOURCE)")
        if FIXTURE.exists():
            shutil.rmtree(FIXTURE)
        FIXTURE.mkdir(parents=True)
        for name in KEEP_DIRS:
            if (SOURCE / name).is_dir():
                shutil.copytree(SOURCE / name, FIXTURE / name, ignore=_IGNORE)
        for name in KEEP_FILES:
            if (SOURCE / name).is_file():
                shutil.copy2(SOURCE / name, FIXTURE / name)
        digest = hashlib.sha1()
        for path in sorted(FIXTURE.rglob("*")):
            if path.is_file():
                digest.update(path.relative_to(FIXTURE).as_posix().encode())
                digest.update(path.read_bytes())
        marker.write_text(digest.hexdigest()[:12], encoding="utf-8")
    return FIXTURE, marker.read_text(encoding="utf-8").strip()


def tasks(_root: Path, _package: str) -> list[suites.Task]:
    _path, snap = snapshot()
    return [suites.Task(id="bug016-autosave", kind="real-bug", prompt=PROMPT + FOOTER, expected=RIGHT_PLACE,
                        scorer="bug016", meta={"target": f"co-{snap}"})]


def _run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, timeout=600)


def build(job, proj: Path, hook_command: str | None = None) -> None:
    """Fill `proj` for the job's arm: control (plain project plus a line pointing at memory/),
    nomem (control with Claude's Auto Memory off), arbor (Context Arbor installed the documented
    way), jev (arbor plus the experimental Jev hook)."""
    path, _snap = snapshot()
    shutil.copytree(path, proj, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".snapshot-id"))
    arm = job.arm
    if arm in ("control", "nomem"):
        (proj / "CLAUDE.md").write_text(CONTROL_POINTER, encoding="utf-8")
    if arm == "nomem":
        (proj / ".claude").mkdir(exist_ok=True)
        (proj / ".claude" / "settings.local.json").write_text('{"autoMemoryEnabled": false}\n', encoding="utf-8")
    if arm in ("arbor", "jev"):
        shutil.copy2(REPO / "arbor.py", proj / "arbor.py")
        _run([sys.executable, "arbor.py", "init", "--agents", "claude"], proj)
        _run([sys.executable, "arbor.py", "code", "index"], proj)
    if arm == "jev":
        import json
        settings = proj / ".claude" / "settings.local.json"
        data = json.loads(settings.read_text(encoding="utf-8")) if settings.exists() else {}
        command = hook_command or f'"{sys.executable}" "{(REPO / "bench" / "jev_hook.py").as_posix()}"'
        data.setdefault("hooks", {}).setdefault("UserPromptSubmit", []).append(
            {"hooks": [{"type": "command", "command": command, "timeout": 15}]})
        settings.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _git(proj: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=proj, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=120)
    return done.stdout


def changed_files(proj: Path) -> list[str]:
    """Paths the agent changed or created since the fixture commit, without Arbor's own files."""
    names = set(_git(proj, "diff", "HEAD", "--name-only").split())
    names |= set(_git(proj, "ls-files", "--others", "--exclude-standard").split())
    return sorted(n for n in names if not any(bit in n.lower() for bit in _NOISE))


def collect_diff(proj: Path, limit: int = 8000) -> str:
    """The agent's change as text, for a human to read afterwards (arm label not included)."""
    files = changed_files(proj)
    if not files:
        return ""
    return _git(proj, "diff", "HEAD", "-U2", "--", *[f for f in files if (proj / f).exists()])[:limit]


def _added_code(proj: Path, files: list[str]) -> list[str]:
    lines = []
    for raw in _git(proj, "diff", "HEAD", "-U0", "--", *files).splitlines():
        if raw.startswith("+") and not raw.startswith("+++"):
            text = raw[1:].strip()
            if text and not text.startswith("#"):
                lines.append(text)
    return lines


def score_bug016(proj: Path | None) -> float:
    """0, 0.5 or 1. Rubric, fixed before any run:
    +0.5 a change in the menu or the save store, where the autosave timer lives (a change only in
         the file the vault points at earns nothing);
    +0.5 that change adds code that reads the simulation's state (`world`), i.e. follows game
         time instead of the wall clock (the timer counted real seconds while game time stood still);
    capped at 0.5 when files other than those allowed under src/ were changed too.
    A human reads every diff afterwards; this is the coarse filter, not the verdict."""
    if proj is None:
        return 0.0
    files = changed_files(proj)
    src = [f for f in files if f.startswith("src/")]
    place = [f for f in src if f in RIGHT_PLACE]
    if not place:
        return 0.0
    added = _added_code(proj, place)
    points = 0.5 + (0.5 if any(SIM_TIME_RE.search(line) for line in added) else 0.0)
    if any(f not in ALLOWED_SRC for f in src):
        points = min(points, 0.5)
    return points


suites.SUITES["co"] = tasks
