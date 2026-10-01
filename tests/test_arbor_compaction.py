import argparse
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import arbor as ctx


ACTIVE_NOW = """# Now

## TASK-20260929-001 Ship the chronicle

- Status: next
- Goal: Render the project chronicle page.
- Success: The page opens offline.
"""


CLOSED_NOW = ACTIVE_NOW.replace("Status: next", "Status: done")


class CompactionTestCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.prev = os.getcwd()
        os.chdir(self.root)
        self._stdin = sys.stdin
        sys.stdin = io.StringIO("")

    def tearDown(self):
        sys.stdin = self._stdin
        os.chdir(self.prev)
        shutil.rmtree(self.root, ignore_errors=True)

    def transcript(self):
        path = Path("t.jsonl")
        records = [
            {"type": "user", "message": {"role": "user", "content": "add the chronicle page"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Edit", "input": {"file_path": "ui.py"}}]}},
        ]
        path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
        return path

    def hook(self, trigger, mode, with_event=True):
        ctx._config_write(Path("."), {"compaction": mode})
        sys.stdin = io.StringIO(json.dumps({"transcript_path": str(self.transcript())})
                                if with_event else "")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = ctx.cmd_session_compact_guard(argparse.Namespace(trigger=trigger))
        return code, err.getvalue()


class CompactGuardTests(CompactionTestCase):
    def test_off_is_the_default_and_never_blocks(self):
        code, err = self.hook("manual", "off")
        self.assertEqual((code, err), (0, ""))
        self.assertFalse(ctx.SESSION_STATE_PATH.exists())
        Path(".arbor/config.json").unlink()
        sys.stdin = io.StringIO("")
        self.assertEqual(ctx.cmd_session_compact_guard(argparse.Namespace(trigger="auto")), 0)

    def test_manual_mode_blocks_slash_compact_but_lets_auto_compaction_run(self):
        code, err = self.hook("manual", "manual")
        self.assertEqual(code, 2)
        self.assertIn("/clear", err)
        self.assertEqual(self.hook("auto", "manual")[0], 0)

    def test_all_mode_blocks_both_triggers(self):
        self.assertEqual(self.hook("manual", "all")[0], 2)
        self.assertEqual(self.hook("auto", "all")[0], 2)

    def test_a_blocked_compaction_still_saves_the_session_first(self):
        self.hook("manual", "all")
        state = ctx._state_sections_read()["Auto snapshot"]
        self.assertIn("add the chronicle page", state)
        self.assertIn("ui.py", state)

    def test_a_broken_config_or_missing_event_never_wedges_the_hook(self):
        Path(".arbor").mkdir()
        Path(".arbor/config.json").write_text("{broken", encoding="utf-8")
        self.assertEqual(ctx.cmd_session_compact_guard(argparse.Namespace(trigger="manual")), 0)
        code, err = self.hook("manual", "all", with_event=False)
        self.assertEqual(code, 2)  # still blocks; there was just nothing to snapshot

    def test_compaction_command_sets_reports_and_rejects_modes(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(ctx.main(["session", "compaction"]), 0)
            self.assertEqual(ctx.main(["session", "compaction", "--mode", "all"]), 0)
            self.assertEqual(ctx.main(["session", "compaction"]), 0)
        self.assertIn("guard: off", out.getvalue())
        self.assertIn("guard: all", out.getvalue())
        self.assertEqual(ctx._config_read(Path("."))["compaction"], "all")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            ctx.main(["session", "compaction", "--mode", "sometimes"])

    def test_compaction_setting_keeps_other_config(self):
        ctx._config_write(Path("."), {"prices": {"input": 1}})
        with contextlib.redirect_stdout(io.StringIO()):
            ctx.main(["session", "compaction", "--mode", "manual"])
        self.assertEqual(ctx._config_read(Path("."))["prices"], {"input": 1})


class HookRegistrationTests(CompactionTestCase):
    def test_init_registers_clear_snapshot_and_both_compaction_guards(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ctx.main(["init", ".", "--agents", "claude"]), 0)
        hooks = json.loads(Path(".claude/settings.local.json").read_text(encoding="utf-8"))["hooks"]
        end = hooks["SessionEnd"]
        self.assertNotIn("matcher", end[0])  # every way a session ends, not only /clear
        self.assertEqual(end[0]["hooks"][0]["command"], ctx._hook_command("session snapshot"))
        self.assertIn("startup", hooks["SessionStart"][0]["matcher"])  # the desktop app's clear
        pre = {g.get("matcher"): g["hooks"][0]["command"] for g in hooks["PreCompact"]}
        self.assertEqual(pre["manual"], ctx._hook_command("session compact-guard --trigger manual"))
        self.assertEqual(pre["auto"], ctx._hook_command("session compact-guard --trigger auto"))
        self.assertEqual(pre[None], ctx._hook_command("session snapshot"))

    def test_an_older_install_gains_the_new_hooks_and_keeps_user_hooks(self):
        path = Path(".claude/settings.local.json")
        path.parent.mkdir()
        path.write_text(json.dumps({"hooks": {
            "PreCompact": [{"hooks": [{"type": "command", "command": "python arbor.py session snapshot"}]},
                           {"hooks": [{"type": "command", "command": "python mine.py"}]}],
        }}), encoding="utf-8")
        self.assertEqual(ctx._merge_claude_local_settings(path), "updated")
        data = json.loads(path.read_text(encoding="utf-8"))["hooks"]
        commands = [h["command"] for g in data["PreCompact"] for h in g["hooks"]]
        self.assertIn("python mine.py", commands)
        self.assertNotIn("python arbor.py session snapshot", commands)  # rewritten in place
        self.assertEqual(commands.count(ctx._hook_command("session snapshot")), 1)
        self.assertIn("SessionEnd", data)
        before = path.read_bytes()
        self.assertEqual(ctx._merge_claude_local_settings(path), "kept")
        self.assertEqual(path.read_bytes(), before)

    def test_older_session_hook_matchers_are_upgraded_in_place(self):
        path = Path(".claude/settings.local.json")
        path.parent.mkdir()
        snap, rest = ctx._hook_command("session snapshot"), ctx._hook_command("session restore")
        path.write_text(json.dumps({"hooks": {
            "SessionEnd": [{"matcher": "clear", "hooks": [{"type": "command", "command": snap}]}],
            "SessionStart": [{"matcher": "compact|clear|resume",
                              "hooks": [{"type": "command", "command": rest}]},
                             {"matcher": "startup", "hooks": [{"type": "command", "command": "python mine.py"}]}],
        }}), encoding="utf-8")
        self.assertEqual(ctx._merge_claude_local_settings(path), "updated")
        hooks = json.loads(path.read_text(encoding="utf-8"))["hooks"]
        self.assertEqual(len(hooks["SessionEnd"]), 1)
        self.assertNotIn("matcher", hooks["SessionEnd"][0])
        self.assertEqual([g["matcher"] for g in hooks["SessionStart"]],
                         ["startup|clear|compact|resume", "startup"])  # the user's group is untouched
        self.assertEqual(ctx._merge_claude_local_settings(path), "kept")

    def test_an_older_guard_hook_is_rewritten_not_duplicated(self):
        path = Path(".claude/settings.local.json")
        path.parent.mkdir()
        path.write_text(json.dumps({"hooks": {"PreToolUse": [
            {"hooks": [{"type": "command", "command": "python arbor.py session guard"}]}]}}), encoding="utf-8")
        self.assertEqual(ctx._set_guard_hook(path, True), "already installed")
        groups = json.loads(path.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
        self.assertEqual([h["command"] for g in groups for h in g["hooks"]], [ctx.GUARD_HOOK_COMMAND])
        self.assertEqual(ctx._set_guard_hook(path, False), "removed")


@unittest.skipUnless(shutil.which("bash"), "Claude Code runs hooks with bash")
class HookCommandShellTests(CompactionTestCase):
    """The hook command line itself, run the way Claude Code runs it: bash, in whatever
    directory the session's shell is in, with CLAUDE_PROJECT_DIR set to the project."""

    def run_hook(self, args, cwd, project):
        import subprocess
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
        return subprocess.run([shutil.which("bash"), "-c", ctx._hook_command(args)], cwd=cwd, env=env,
                              input="{}", capture_output=True, text=True, timeout=60)

    def test_hook_runs_from_the_project_root_after_the_agent_changed_directory(self):
        project = self.root / "my project"
        (project / "sub" / "deeper").mkdir(parents=True)
        (project / "arbor.py").write_text(
            "import os, sys; open('ran.txt', 'w').write(os.getcwd() + ' ' + ' '.join(sys.argv[1:]))\n",
            encoding="utf-8")
        done = self.run_hook("session gauge", project / "sub" / "deeper", project)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue((project / "ran.txt").exists())
        self.assertFalse((project / "sub" / "deeper" / "ran.txt").exists())
        self.assertTrue((project / "ran.txt").read_text(encoding="utf-8").endswith("session gauge"))

    def test_hook_without_arbor_py_does_nothing_and_never_blocks(self):
        project = self.root / "gone"
        project.mkdir()
        done = self.run_hook("session guard", project, project)
        self.assertEqual((done.returncode, done.stdout), (0, ""))

    def test_hook_keeps_the_exit_code_of_arbor_py(self):
        project = self.root / "p"
        project.mkdir()
        (project / "arbor.py").write_text("raise SystemExit(2)\n", encoding="utf-8")  # e.g. compact-guard blocking
        self.assertEqual(self.run_hook("session compact-guard --trigger manual", project, project).returncode, 2)


class RestoreAfterClearTests(CompactionTestCase):
    def restore(self, source):
        args = argparse.Namespace(source=source, max_age_hours=72.0, max_chars=8000)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(ctx.cmd_session_restore(args), 0)
        return out.getvalue()

    def setup_memory(self, now_text):
        Path("memory").mkdir(exist_ok=True)
        Path("memory/NOW.md").write_text(now_text, encoding="utf-8")

    def test_clear_hands_back_the_saved_state_and_the_active_task(self):
        ctx._state_write(agent="resume the ui work", auto=None)
        self.setup_memory(ACTIVE_NOW)
        out = self.restore("clear")
        self.assertIn("resume the ui work", out)
        self.assertIn("## Active task (memory/NOW.md)", out)
        self.assertIn("Ship the chronicle", out)
        self.assertIn("code find", out)

    def test_the_state_files_own_header_is_not_injected(self):
        ctx._state_write(agent="resume the ui work", auto=None)
        out = self.restore("clear")
        self.assertIn("## Agent notes", out)
        self.assertNotIn("survives /compact", out)

    def test_the_task_arrives_even_when_no_state_was_saved(self):
        self.setup_memory(ACTIVE_NOW)
        self.assertIn("Render the project chronicle page", self.restore("clear"))

    def test_resume_keeps_its_context_so_the_task_is_not_repeated(self):
        ctx._state_write(agent="state", auto=None)
        self.setup_memory(ACTIVE_NOW)
        self.assertNotIn("Ship the chronicle", self.restore("resume"))
        self.assertIn("Ship the chronicle", self.restore("startup"))  # desktop clear = new session

    def test_startup_without_recent_state_stays_clean(self):
        self.setup_memory(ACTIVE_NOW)
        self.assertEqual(self.restore("startup"), "")

    def test_finished_tasks_and_the_empty_template_are_not_injected(self):
        ctx._state_write(agent="state", auto=None)
        self.setup_memory(CLOSED_NOW)
        self.assertNotIn("Ship the chronicle", self.restore("clear"))
        self.setup_memory(ctx.MEMORY_TEMPLATES["NOW.md"])
        self.assertNotIn("TASK-YYYYMMDD", self.restore("clear"))
        self.assertEqual(ctx._active_task_excerpt(), "")

    def test_nothing_to_restore_prints_nothing(self):
        self.assertEqual(self.restore("clear"), "")


class SessionEndSnapshotTests(CompactionTestCase):
    def test_snapshot_reads_the_transcript_from_the_hook_event(self):
        sys.stdin = io.StringIO(json.dumps({"transcript_path": str(self.transcript()),
                                            "hook_event_name": "SessionEnd", "reason": "clear"}))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(ctx.cmd_session_snapshot(argparse.Namespace(transcript=None)), 0)
        self.assertIn("auto snapshot written", out.getvalue())
        self.assertIn("add the chronicle page", ctx._state_sections_read()["Auto snapshot"])

    def test_snapshot_keeps_background_commands_and_the_last_reply(self):
        path = self.transcript()
        records = [
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Bash",
                 "input": {"command": "python bench/ab.py run --suite co-mem", "run_in_background": True}},
                {"type": "tool_use", "name": "Bash", "input": {"command": "git status"}}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": "Прогон идёт: 34/54, дальше отчёт."}]}},
        ]
        with path.open("a", encoding="utf-8") as fh:
            fh.write("\n" + "\n".join(json.dumps(r, ensure_ascii=False) for r in records))
        self.assertTrue(ctx._write_auto_snapshot(str(path)))
        auto = ctx._state_sections_read()["Auto snapshot"]
        self.assertIn("`python bench/ab.py run --suite co-mem`", auto)
        self.assertNotIn("git status", auto)  # foreground commands are finished, not state
        self.assertIn("> Прогон идёт: 34/54", auto)


    def test_snapshot_never_stores_credentials(self):
        key = "sk-or-v1-" + "e6fd28b81adefb89" * 4
        path = self.transcript()
        records = [
            {"type": "user", "message": {"role": "user", "content": f"вот ключ {key}"}},
            {"type": "user", "message": {"role": "user", "content":
                "<task-notification>\n<task-id>b1</task-id>\n</task-notification>"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "PowerShell", "input": {
                    "command": f"$env:OPENROUTER_API_KEY='{key}'; python bench/ab.py run",
                    "run_in_background": True}},
                {"type": "tool_use", "name": "Bash", "input": {
                    "command": "export GH_TOKEN=abc123def456; curl -H 'Authorization: Bearer "
                               "eyJhbGciOiJIUzI1NiJ9.payload' x", "run_in_background": True}},
                {"type": "text", "text": f"ключ {key} принят"}]}},
        ]
        with path.open("a", encoding="utf-8") as fh:
            fh.write("\n" + "\n".join(json.dumps(r, ensure_ascii=False) for r in records))
        self.assertTrue(ctx._write_auto_snapshot(str(path)))
        state = ctx.SESSION_STATE_PATH.read_text(encoding="utf-8")
        for secret in (key, "e6fd28b81adefb89", "abc123def456", "eyJhbGciOiJIUzI1NiJ9"):
            self.assertNotIn(secret, state)
        self.assertIn("$env:OPENROUTER_API_KEY='<redacted>'; python bench/ab.py run", state)
        self.assertIn("export GH_TOKEN=<redacted>", state)
        self.assertNotIn("task-notification", state)  # harness events are not user asks


class DesktopClearTests(CompactionTestCase):
    """The desktop app's clear opens a NEW session (SessionStart source=startup) and fires
    no SessionEnd: restore itself snapshots the previous transcript of the project."""

    def setUp(self):
        super().setUp()
        self.sessions = Path("sessions")
        self.sessions.mkdir()
        old = self.sessions / "old.jsonl"
        old.write_text(json.dumps({"type": "user", "message": {
            "role": "user", "content": "finish the co-mem benchmark"}}), encoding="utf-8")
        (self.sessions / "new.jsonl").write_text("", encoding="utf-8")

    def restore(self, source="startup", max_age_hours=12.0):
        sys.stdin = io.StringIO(json.dumps({"hook_event_name": "SessionStart", "source": source,
                                            "transcript_path": str(self.sessions / "new.jsonl")}))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ctx.cmd_session_restore(argparse.Namespace(source=None, max_age_hours=max_age_hours,
                                                       max_chars=8000))
        return out.getvalue()

    def test_new_session_restores_the_previous_one_from_its_transcript(self):
        out = self.restore()
        self.assertIn("source=startup", out)
        self.assertIn("finish the co-mem benchmark", out)
        log = ctx.HOOK_LOG_PATH.read_text(encoding="utf-8")
        self.assertIn('"source": "startup"', log)

    def test_a_stale_previous_session_is_left_alone(self):
        old = self.sessions / "old.jsonl"
        t = old.stat().st_mtime - 30 * 3600
        os.utime(old, (t, t))
        self.assertEqual(self.restore(), "")
        self.assertFalse(ctx.SESSION_STATE_PATH.exists())

    def test_an_existing_newer_snapshot_is_not_overwritten(self):
        ctx._state_write(agent=None, auto="written by SessionEnd")
        t = ctx.SESSION_STATE_PATH.stat().st_mtime + 60
        os.utime(ctx.SESSION_STATE_PATH, (t, t))
        out = self.restore("clear")
        self.assertIn("written by SessionEnd", out)
        self.assertNotIn("finish the co-mem benchmark", out)


if __name__ == "__main__":
    unittest.main()
