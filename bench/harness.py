"""Runs one benchmark job: build a fresh project, run `claude -p` in it, measure what happened.

Every job gets its own throw-away directory outside this repository and its own headless
session, so nothing from another run, from this repository or from the user's own Claude Code
setup can reach it (user settings, skills, MCP servers and the Agent tool are switched off
for both arms alike).
"""
from __future__ import annotations

import json
import re
import os
import shutil
import stat
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import comemsuite
import cosuite
import memsuite
import suites

REPO = Path(__file__).resolve().parent.parent

# Variables that tie a child to the interactive session that spawned it.
_STRIP_ENV = ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_HOST_SESSION_ID",
              "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_MESSAGING_SOCKET",
              "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_EMIT_TOOL_USE_SUMMARIES",
              "CLAUDE_CODE_ENABLE_ASK_USER_QUESTION_TOOL", "CLAUDE_CODE_TERMINAL_MCP_TOOLS",
              "CLAUDE_CODE_REPORT_FINDINGS", "CLAUDE_CODE_SESSION_ATTENDED", "CLAUDE_EFFORT")

TOOLS = "Bash,Read,Grep,Glob,Edit,Write"
ARMS = ("control", "nomem", "arbor", "jev")  # nomem = control + Auto Memory off; jev = arbor + Jev hook (suite co)


@dataclass
class Job:
    suite: str
    task: suites.Task
    arm: str
    rep: int
    model: str

    @property
    def id(self) -> str:
        return f"{self.suite}/{self.task.id}/{self.arm}/{self.rep}/{self.model}"

    @property
    def slug(self) -> str:
        return self.id.replace("/", "_")


def claude_bin() -> str:
    found = shutil.which("claude")
    if not found:
        raise SystemExit("`claude` is not on PATH")
    return found


def _run(cmd: list[str], cwd: Path, timeout: int = 300) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, timeout=timeout)


def _force_remove(path: Path) -> None:
    """rmtree that also removes the read-only files git leaves behind on Windows."""
    def onerror(func, target, _exc):
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            pass
    shutil.rmtree(path, onerror=onerror)


def build_project(job: Job, work: Path, package: str) -> Path:
    """A fresh copy of the fixture, committed to a fresh git repository. The `arbor` arm then
    gets Context Arbor installed the documented way: arbor.py copied in, `init --agents claude`
    run, and the code index built once (an installed project keeps it between sessions)."""
    proj = work / f"{job.slug}_{uuid.uuid4().hex[:6]}" / "proj"  # a new directory for every attempt
    proj.mkdir(parents=True)
    history = memsuite.history_for(job.suite) if job.suite in memsuite.SPECS else None
    if job.suite in ("co", "co-mem"):
        cosuite.build(job, proj)
    elif history is None:
        suites.copy_package(package, proj)
    else:
        memsuite.write_stub_code(proj)
        if job.arm != "arbor":  # the same notes, as plain files in the usual ADR layout
            memsuite.write_docs(proj, history)
    if job.suite in ("co", "co-mem"):
        pass  # cosuite.build made every arm
    elif job.arm == "nomem":
        # Arbor's installer switches Claude Code's built-in Auto Memory off. This arm makes only
        # that one change, so the effect of the switch can be told apart from Arbor's own.
        (proj / ".claude").mkdir()
        (proj / ".claude" / "settings.local.json").write_text('{"autoMemoryEnabled": false}\n', encoding="utf-8")
    if job.arm == "arbor" and job.suite not in ("co", "co-mem"):
        shutil.copy2(REPO / "arbor.py", proj / "arbor.py")
        _run([sys.executable, "arbor.py", "init", "--agents", "claude"], proj)
        if history is not None:
            problems = memsuite.write_vault(proj, history)
            if problems:
                raise OSError("vault did not pass `memory check`: " + "; ".join(problems[:3]))
        _run([sys.executable, "arbor.py", "code", "index"], proj)
    env = {**os.environ, "GIT_AUTHOR_NAME": "bench", "GIT_AUTHOR_EMAIL": "bench@example.com",
           "GIT_COMMITTER_NAME": "bench", "GIT_COMMITTER_EMAIL": "bench@example.com"}
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"], ["git", "commit", "-q", "-m", "fixture"]):
        subprocess.run(cmd, cwd=proj, check=True, capture_output=True, env=env, timeout=120)
    return proj


def command(model: str, cap: float, effort: str) -> list[str]:
    return [claude_bin(), "-p", "--output-format", "stream-json", "--verbose",
            "--model", model, "--effort", effort, "--no-session-persistence",
            "--setting-sources", "project,local", "--disable-slash-commands", "--strict-mcp-config",
            "--permission-mode", "acceptEdits", "--max-budget-usd", str(cap),
            "--tools", TOOLS, "--allowedTools", TOOLS, "--include-hook-events"]


def scrub(text: str) -> str:
    """Raw transcripts are kept on disk: drop the OpenRouter key if the agent's environment leaked it."""
    key = os.environ.get("OPENROUTER_API_KEY", "")
    return text.replace(key, "<OPENROUTER_API_KEY>") if len(key) > 12 else text


_MEMORY_WORD = re.compile(r"""(?:^|[\s"'=/])memory(?:[/\s"']|$)""")


def _touches_memory(tool_input: object) -> bool:
    """A tool call that reads the vault: a path under memory/, or a shell command naming it
    (`arbor.py memory ...`, `grep ... memory/`). A Bash description does not count."""
    if not isinstance(tool_input, dict):
        return False
    for field in ("file_path", "path", "pattern", "command"):
        text = str(tool_input.get(field) or "").replace("\\", "/").lower()
        if field == "command":
            if "arbor.py memory" in text or _MEMORY_WORD.search(text):
                return True
        elif "memory/" in text or text.rstrip("/").endswith("memory"):
            return True
    return False


def _text_of(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return ""


def steady_cost(per_turn: list[dict]) -> float:
    """Cost in input-token equivalents, in the steady state a returning user sits in: the first
    turn's context (system prompt, tools, CLAUDE.md, the prompt) is a cache read, every later
    turn pays the usual multipliers (cache write 1.25x, cache read 0.1x, output 5x). It does not
    depend on whether this particular run happened to find its prefix already cached -- which
    depends on run order and on paths, not on the tool under test."""
    total = 0.0
    for i, t in enumerate(per_turn):
        if i == 0:
            total += 0.1 * (t["input"] + t["cache_write"] + t["cache_read"])
        else:
            total += t["input"] + 1.25 * t["cache_write"] + 0.1 * t["cache_read"]
        total += 5 * t["output"]
    return total


def summarize(lines: list[str]) -> dict:
    """Measurements from one stream-json transcript. Token counts come from the final result
    (every model call, sub-agents included); the per-turn context sizes and the tool activity
    from the assistant/user messages."""
    messages: dict[str, dict] = {}
    tools: dict[str, int] = {}
    commands: list[str] = []
    result: dict = {}
    result_chars = 0
    hooks = 0
    memory_ids: set[str] = set()
    memory_chars = 0
    for line in lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = obj.get("type")
        if kind == "result":
            result = obj
        elif kind == "system" and str(obj.get("subtype", "")).startswith("hook"):
            hooks += 1
        elif kind == "assistant":
            msg = obj.get("message") or {}
            usage = msg.get("usage") or {}
            key = str(msg.get("id") or obj.get("uuid") or len(messages))
            entry = messages.setdefault(key, {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0})
            for name, field in (("input", "input_tokens"), ("cache_write", "cache_creation_input_tokens"),
                                ("cache_read", "cache_read_input_tokens"), ("output", "output_tokens")):
                entry[name] = max(entry[name], int(usage.get(field) or 0))
            for block in msg.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tools[block.get("name", "?")] = tools.get(block.get("name", "?"), 0) + 1
                    if _touches_memory(block.get("input")):
                        memory_ids.add(str(block.get("id")))
                    if block.get("name") == "Bash":
                        commands.append(str((block.get("input") or {}).get("command", ""))[:160])
        elif kind == "user":
            content = (obj.get("message") or {}).get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        result_chars += len(_text_of(block.get("content")))
                        if str(block.get("tool_use_id")) in memory_ids:
                            memory_chars += len(_text_of(block.get("content")))
    per_turn = list(messages.values())
    usage = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}
    for model_usage in (result.get("modelUsage") or {}).values():
        usage["input"] += int(model_usage.get("inputTokens") or 0)
        usage["cache_write"] += int(model_usage.get("cacheCreationInputTokens") or 0)
        usage["cache_read"] += int(model_usage.get("cacheReadInputTokens") or 0)
        usage["output"] += int(model_usage.get("outputTokens") or 0)
    if not any(usage.values()):  # no modelUsage: fall back to the per-message sums
        for turn in per_turn:
            for name in usage:
                usage[name] += turn[name]
    first = per_turn[0] if per_turn else {"input": 0, "cache_write": 0, "cache_read": 0}
    arbor_calls = sum(1 for c in commands if "arbor.py" in c)
    return {
        "turns": len(per_turn),
        "tokens": usage,
        "context_processed": usage["input"] + usage["cache_write"] + usage["cache_read"],
        "first_context": first["input"] + first["cache_write"] + first["cache_read"],
        "peak_context": max((t["input"] + t["cache_write"] + t["cache_read"] for t in per_turn), default=0),
        "cost_usd": float(result.get("total_cost_usd") or 0.0),
        "cost_steady": round(steady_cost(per_turn), 1),
        "duration_s": round(float(result.get("duration_ms") or 0) / 1000, 1),
        "tools": tools, "arbor_calls": arbor_calls, "bash": commands[:40],
        "tool_result_tokens_est": result_chars // 4,
        "memory_calls": len(memory_ids), "memory_tokens_est": memory_chars // 4,
        "hook_events": hooks,
        "is_error": bool(result.get("is_error")), "subtype": result.get("subtype", "missing"),
        "final_text": str(result.get("result") or "")[-2000:],
    }


def run_job(job: Job, work: Path, raw_dir: Path, package: str, cap: float, effort: str,
            keep: bool = False, timeout: int = 900) -> dict:
    started = time.time()
    record = {"job": job.id, "suite": job.suite, "task": job.task.id, "kind": job.task.kind,
              "arm": job.arm, "rep": job.rep, "model": job.model, "effort": effort,
              "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
    proj = None
    try:
        proj = build_project(job, work, package)
        env = {k: v for k, v in os.environ.items() if k not in _STRIP_ENV}
        if job.arm == "jev" and job.suite == "co-mem":
            raw_dir.mkdir(parents=True, exist_ok=True)
            env.update(comemsuite.JEV_ENV, JEV_LOG=str(raw_dir / f"{job.slug}.jev.jsonl"))
        proc = subprocess.run(command(job.model, cap, effort), input=job.task.prompt, cwd=proj,
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, env=env)
        raw_dir.mkdir(parents=True, exist_ok=True)
        stdout = scrub(proc.stdout)
        (raw_dir / f"{job.slug}.jsonl").write_text(stdout, encoding="utf-8")
        summary = summarize(stdout.splitlines())
        answer = suites.parse_answer(summary["final_text"])
        summary["answer"] = answer
        answered = suites.ANSWER_RE.search(summary["final_text"]) is not None
        if job.suite == "co-mem":
            summary["score"] = comemsuite.score(job.task, answer)
        elif job.suite == "co":
            summary["score"] = cosuite.score_bug016(proj)
            summary["changed"] = cosuite.changed_files(proj)
            summary["diff"] = cosuite.collect_diff(proj)
        else:
            summary["score"] = suites.score(job.task, answer, proj, package, answered)
        summary["valid"] = summary["subtype"] == "success" and not summary["is_error"]
        record.update(summary)
        if proc.returncode != 0 and not record["valid"]:
            record["stderr"] = proc.stderr[-500:]
    except subprocess.TimeoutExpired:
        record.update({"valid": False, "subtype": "timeout", "score": 0.0})
    except (subprocess.SubprocessError, OSError) as exc:
        record.update({"valid": False, "subtype": "harness_error", "error": str(exc)[:300], "score": 0.0})
    finally:
        if proj is not None and not keep:
            _force_remove(proj.parent)
    record["wall_s"] = round(time.time() - started, 1)
    return record
