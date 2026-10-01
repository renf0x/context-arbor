"""Suite `co-mem`: questions only the real vault answers well (Contested Orbit, same snapshot as `co`).

Suite `co` showed that a bug-fix task barely touches memory/, so it cannot show whether a
memory lookup saves anything. Here every question asks for a recorded reason, number or rule,
in Russian, the way the user would ask; the vault is English. Expected answers were copied from
the snapshot's memory/ (decisions.md) before any run and are checked per field by regex, so
the wording of the answer does not matter. The Jev threshold is fixed here, not tuned on these
questions: top 2 notes with p >= 0.2.

    python bench/comemsuite.py   # memory-read table from bench/results/co-mem-co-mem.jsonl
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import cosuite
import suites

JEV_ENV = {"JEV_THRESHOLD": "0.2", "JEV_TOP": "2"}

FOOTER = ("\n\nWork efficiently. When you are done, end your reply with exactly one line of the form "
          "`ANSWER: {json}` with the keys {keys} and nothing after it.")

# (id, question, {key: expected}). An expected number is matched by value; a string is a regex
# (case-insensitive) that the field must match. Source entries in decisions.md are noted.
QUESTIONS = [
    ("headless",  # "Headless Godot never runs next to the open editor (2026-09-24)"
     "Раньше после прогона тестов пропадали записи class_name (MeshMergeRules и другие). "
     "Из-за чего это было и как теперь правильно добавлять новую деталь, если редактор Godot открыт?",
     {"cause": r"import", "how": r"execute_gdscript"}),
    ("collisions",  # "2026-09-27 Collisions are arcade, not a simulator (user)"
     "Как у нас проверяются столкновения юнитов, камней и станций: с каким шагом по игровому времени "
     "проверяются контакты и почему не взяли Area3D?",
     {"substep_s": 60, "area3d_rejected_because": r"tunnel|туннел|проскак|пролет|пролёт|warp|варп|"
                                                   r"кадр|frame|float|сцен|scene"}),
    ("quality",  # "DEC-20260923-025 Graphics quality presets"
     "Пресеты качества графики (low/medium/high/ultra): какой выбран сейчас и почему в них "
     "множители, а не абсолютные значения?",
     {"current": r"medium", "why_multipliers": r"belt|пояс"}),
    ("planes",  # "2026-09-27 Orbits above the air, safe manoeuvres"
     "Юнит атакует цель в другой орбитальной плоскости. При каких предельных затратах он "
     "разворачивается в плоскость цели, а не ждёт пересечения орбит?",
     {"max_dv_kms": 0.6, "max_dv_percent": 30}),
    ("dish",  # "Gold dish tracks the planet (2026-09-24)"
     "Почему для поворота золотой антенны-детектора не стали переиспользовать TurretRig, "
     "и какой максимальный наклон тарелки от нормали крепления?",
     {"tilt_max_deg": 35, "why_not_turretrig": r"-z|zenith|зенит|weapon|оруж|horizon|горизонт|"
                                               r"coupl|связ|смеш|барел|barrel|ствол"}),
    ("blender",  # "DEC-20260923-002 LLM-Blender-Agent used as method only, not installed"
     "Почему LLM-Blender-Agent не установлен в проект и через что тогда управляется Blender?",
     {"why_not_installed": r"9876|gradio|порт|port|ключ|key",
      "blender_driver": r"blender[-_ ]?mcp"}),
]


def tasks(_root: Path, _package: str) -> list[suites.Task]:
    _path, snap = cosuite.snapshot()
    out = []
    for qid, question, expected in QUESTIONS:
        keys = ", ".join(f'"{k}"' for k in expected)
        out.append(suites.Task(id=f"mem-{qid}", kind="memory", prompt=question + FOOTER.replace("{keys}", keys),
                               expected=expected, scorer="fields", meta={"target": f"co-{snap}"}))
    return out


def _number(value: object) -> float | None:
    found = re.search(r"-?\d+(?:[.,]\d+)?", str(value))
    return float(found.group(0).replace(",", ".")) if found else None


def score(task: suites.Task, answer: object) -> float:
    """Share of fields right: a number within 1%, a string matching its regex."""
    if not isinstance(answer, dict):
        return 0.0
    got = {str(k).lower(): v for k, v in answer.items()}
    hits = 0
    for key, want in task.expected.items():
        value = got.get(key.lower())
        if value is None:
            continue
        if isinstance(want, (int, float)):
            num = _number(value)
            hits += num is not None and abs(num - want) <= abs(want) * 0.01
        else:
            hits += re.search(want, str(value), re.I) is not None
    return hits / len(task.expected)


def memory_table(path: Path) -> str:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    rows = [r for r in rows if r.get("valid")]
    lines = ["| arm | n | score | memory calls | memory tokens (est.) | ctx k | steady k | $ |",
             "|---|---|---|---|---|---|---|---|"]
    for arm in ("control", "arbor", "jev"):
        rs = [r for r in rows if r["arm"] == arm]
        if not rs:
            continue
        n = len(rs)
        avg = lambda key: sum(float(r.get(key) or 0) for r in rs) / n  # noqa: E731
        lines.append(f"| {arm} | {n} | {avg('score'):.2f} | {avg('memory_calls'):.1f} | "
                     f"{avg('memory_tokens_est'):.0f} | {avg('context_processed') / 1000:.0f} | "
                     f"{avg('cost_steady') / 1000:.0f} | {sum(r.get('cost_usd', 0) for r in rs):.2f} |")
    lines += ["", "| task | control | arbor | jev |", "|---|---|---|---|"]
    for qid, *_ in QUESTIONS:
        cells = []
        for arm in ("control", "arbor", "jev"):
            rs = [r for r in rows if r["arm"] == arm and r["task"] == f"mem-{qid}"]
            cells.append(" ".join(f"{r['score']:.1f}/{r.get('memory_tokens_est', 0) / 1000:.1f}k" for r in rs) or "-")
        lines.append(f"| {qid} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


suites.SUITES["co-mem"] = tasks

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(memory_table(Path(__file__).resolve().parent / "results" / "co-mem-co-mem.jsonl"))
