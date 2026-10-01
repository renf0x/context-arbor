#!/usr/bin/env python3
"""EXPERIMENT, not part of Context Arbor (Arbor invokes no model; this file is a bench tool).

A Claude Code `UserPromptSubmit` hook that lets Jev (`~typesafe/jev-latest`, OpenRouter's
Decisions API: typed answers and probabilities, no generated text) decide which recorded notes
bear on the user's request, and puts those notes into the agent's context before its first turn.
Needed because the user writes in Russian and the vault is in English, so a local keyword search
finds nothing (measured earlier: 0 of 9).

Sent to the third party: the request text and the vault's section titles. Bodies stay local.
The key comes from OPENROUTER_API_KEY only and is never written anywhere. No key, cap reached,
timeout or any error means no output, so the session runs exactly as without the hook.

  JEV_LOG        file the decisions are appended to (one JSON line each; also holds the spend)
  JEV_CAP_USD    stop calling once the logged spend reaches this (default 0.03)
  JEV_THRESHOLD  least probability for a note to be injected (default 0.5)
  JEV_TOP        most notes injected (default 3)
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
MODEL = os.environ.get("JEV_MODEL", "~typesafe/jev-latest")
THRESHOLD = float(os.environ.get("JEV_THRESHOLD", "0.5"))
TOP = int(os.environ.get("JEV_TOP", "3"))
BODY_CHARS = int(os.environ.get("JEV_BODY_CHARS", "1800"))
TIMEOUT = float(os.environ.get("JEV_TIMEOUT", "10"))
CAP = float(os.environ.get("JEV_CAP_USD", "0.03"))
LOG = os.environ.get("JEV_LOG", "")
FILES = ("NOW.md", "bugs.md", "decisions.md", "knowledge.md", "investigations.md")
HEADING = re.compile(r"^## (.+?)\s*$", re.M)


def parse_entries(memory: Path) -> list[dict]:
    """Every `## ` section of the vault's main files: {file, title, body}."""
    entries = []
    for name in FILES:
        path = memory / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        marks = list(HEADING.finditer(text))
        for i, mark in enumerate(marks):
            title = mark.group(1)
            if "template" in title.lower():
                continue
            end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
            entries.append({"file": name, "title": title, "body": text[mark.start():end].strip()})
    return entries


def questions_for(entries: list[dict]) -> dict:
    return {f"n{i}": {
        "type": "noul",
        "instructions": ("A developer is given the request. Is the recorded note titled "
                         f"\"{e['title']}\" needed to carry it out correctly?"),
        "criteria": {"true": "the note records a bug, decision or rule that bears directly on the request",
                     "false": "the note is about something else"}} for i, e in enumerate(entries)}


def decide(prompt: str, entries: list[dict], key: str) -> tuple[dict, dict]:
    body = {"model": MODEL, "state": {"request": prompt}, "questions": questions_for(entries)}
    req = urllib.request.Request(ENDPOINT, data=json.dumps(body).encode("utf-8"), headers={
        "Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        data = json.load(resp)
    return data.get("answers") or {}, data.get("usage") or {}


def probability(answer: object) -> float:
    if isinstance(answer, dict):
        for field in ("noul", "probability", "value"):
            if isinstance(answer.get(field), (int, float)):
                return float(answer[field])
    return 0.0


def spent() -> float:
    total = 0.0
    if LOG and Path(LOG).is_file():
        for line in Path(LOG).read_text(encoding="utf-8").splitlines():
            try:
                total += float(json.loads(line).get("cost") or 0)
            except (ValueError, TypeError):
                pass
    return total


def log(record: dict) -> None:
    if LOG:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def inject_text(chosen: list[dict]) -> str:
    parts = ["[jev] Notes from memory/ that a model matched to this request. They may be out of "
             "date or wrong: check them against the code before relying on them."]
    for e in chosen:
        body = e["body"] if len(e["body"]) <= BODY_CHARS else e["body"][:BODY_CHARS].rstrip() + " ..."
        parts.append(f"### {e['file']}: {e['title']}\n{body}")
    return "\n\n".join(parts)


def run(event: dict) -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "")
    prompt = str(event.get("prompt") or "").strip()
    if not key or not prompt:
        return ""
    if spent() >= CAP:
        log({"t": time.strftime("%H:%M:%S"), "skipped": "cap", "cost": 0})
        return ""
    entries = parse_entries(Path(event.get("cwd") or os.getcwd()) / "memory")
    if not entries:
        return ""
    started = time.time()
    record = {"t": time.strftime("%H:%M:%S"), "entries": len(entries), "cost": 0.0}
    try:
        answers, usage = decide(prompt, entries, key)
    except Exception as exc:  # noqa: BLE001 - a hook must never break the session
        record.update({"error": type(exc).__name__ + ": " + str(exc)[:160], "latency_s": round(time.time() - started, 2)})
        log(record)
        return ""
    scored = sorted(((probability(answers.get(f"n{i}")), e) for i, e in enumerate(entries)),
                    key=lambda pair: -pair[0])
    chosen = [e for p, e in scored if p >= THRESHOLD][:TOP]
    text = inject_text(chosen) if chosen else ""
    record.update({"cost": float(usage.get("cost") or 0), "in_tokens": usage.get("input_tokens"),
                   "latency_s": round(time.time() - started, 2),
                   "top": [{"title": e["title"][:70], "p": round(p, 3)} for p, e in scored[:6]],
                   "injected": [e["title"][:70] for e in chosen], "injected_chars": len(text)})
    log(record)
    return text


def main() -> int:
    try:
        event = json.load(sys.stdin)
        text = run(event if isinstance(event, dict) else {})
    except Exception:  # noqa: BLE001
        text = ""
    if text:
        sys.stdout.write(json.dumps({"hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit", "additionalContext": text}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
