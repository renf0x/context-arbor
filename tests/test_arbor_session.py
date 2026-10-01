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


class SessionTests(unittest.TestCase):
    def setUp(self):
        # Not TemporaryDirectory(): on Windows its strict cleanup raises
        # WinError 32 when the dir was ever the CWD. We rmtree(ignore_errors).
        self.root = Path(tempfile.mkdtemp())
        self.prev = os.getcwd()
        os.chdir(self.root)
        # The commands probe stdin for hook JSON; give them a closed, empty one
        # so the suite never depends on (or blocks on) the runner's real stdin.
        self._stdin = sys.stdin
        sys.stdin = io.StringIO("")

    def tearDown(self):
        sys.stdin = self._stdin
        os.chdir(self.prev)
        shutil.rmtree(self.root, ignore_errors=True)

    def write_transcript(self, records, name="t.jsonl"):
        p = Path(name)
        p.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
        return p

    def test_state_write_preserves_other_section(self):
        ctx._state_write(agent="goal: ship calculator", auto=None)
        ctx._state_write(agent=None, auto="- edited a.tsx")
        sections = ctx._state_sections_read()
        self.assertIn("goal: ship calculator", sections["Agent notes"])
        self.assertIn("edited a.tsx", sections["Auto snapshot"])
        ctx._state_write(agent="new goal", auto=None)
        sections = ctx._state_sections_read()
        self.assertIn("new goal", sections["Agent notes"])
        self.assertNotIn("ship calculator", sections["Agent notes"])
        self.assertIn("edited a.tsx", sections["Auto snapshot"])

    def test_legacy_state_moves_to_arbor_directory(self):
        legacy = Path(".ctx/session-state.md")
        legacy.parent.mkdir(parents=True)
        legacy.write_text("## Agent notes\n\nlegacy state\n", encoding="utf-8")
        self.assertIn("legacy state", ctx._state_sections_read()["Agent notes"])
        self.assertTrue(ctx.SESSION_STATE_PATH.is_file())
        self.assertFalse(legacy.exists())

    def test_extract_facts_skips_noise_and_sidechains(self):
        p = self.write_transcript([
            {"type": "user", "message": {"role": "user", "content": "сделай кнопку"}},
            {"type": "user", "message": {
                "role": "user",
                "content": "<command-name>/compact</command-name>"}},
            {"isSidechain": True,
             "message": {"role": "user", "content": "subagent ask"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Edit",
                 "input": {"file_path": "a.tsx"}}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "content": "big output"}]}},
        ])
        asks, files = ctx._extract_session_facts(p)
        self.assertEqual(asks, ["сделай кнопку"])
        self.assertEqual(files, ["a.tsx"])

    def test_edited_files_keep_most_recent_order(self):
        p = self.write_transcript([
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Write",
                 "input": {"file_path": "a.tsx"}},
                {"type": "tool_use", "name": "Edit",
                 "input": {"file_path": "b.css"}},
                {"type": "tool_use", "name": "Edit",
                 "input": {"file_path": "a.tsx"}}]}},
        ])
        _asks, files = ctx._extract_session_facts(p)
        self.assertEqual(files, ["b.css", "a.tsx"])

    def gauge_args(self, transcript):
        return argparse.Namespace(transcript=str(transcript),
                                  warn_tokens=80_000, crit_tokens=120_000)

    def test_gauge_quiet_below_threshold(self):
        p = self.write_transcript([
            {"type": "assistant", "message": {"role": "assistant", "usage": {
                "input_tokens": 10, "cache_read_input_tokens": 100,
                "cache_creation_input_tokens": 5}}}])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(ctx.cmd_session_gauge(self.gauge_args(p)), 0)
        self.assertEqual(out.getvalue(), "")

    def test_gauge_warns_above_threshold(self):
        p = self.write_transcript([
            {"type": "assistant", "message": {"role": "assistant", "usage": {
                "input_tokens": 1000, "cache_read_input_tokens": 130_000,
                "cache_creation_input_tokens": 2000}}}])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(ctx.cmd_session_gauge(self.gauge_args(p)), 0)
        self.assertIn("[arbor gauge]", out.getvalue())
        self.assertIn("clear NOW", out.getvalue())
        self.assertIn("/clear", out.getvalue())
        self.assertNotIn("recommend /compact", out.getvalue())

    def test_gauge_uses_last_main_chain_usage(self):
        p = self.write_transcript([
            {"type": "assistant", "message": {"role": "assistant", "usage": {
                "cache_read_input_tokens": 130_000}}},
            {"isSidechain": True, "message": {"role": "assistant", "usage": {
                "cache_read_input_tokens": 100}}},
        ])
        self.assertEqual(ctx._last_context_tokens(p), 130_000)

    def turns(self, *sizes, name="t.jsonl"):
        """A transcript whose main-chain assistant turns have these total context sizes."""
        return self.write_transcript([
            {"type": "assistant", "message": {"role": "assistant", "usage": {
                "input_tokens": 10, "cache_read_input_tokens": size - 10}}}
            for size in sizes], name=name)

    def run_hook(self, fn, transcript, **event):
        sys.stdin = io.StringIO(json.dumps({"transcript_path": str(transcript), **event}))
        out = io.StringIO()
        args = argparse.Namespace(transcript=None, warn_tokens=None, crit_tokens=None,
                                  warn_growth=None, crit_growth=None, stop_growth=None)
        with contextlib.redirect_stdout(out):
            self.assertEqual(fn(args), 0)
        return out.getvalue()

    def test_gauge_thresholds_are_growth_over_the_first_turn(self):
        quiet = self.turns(65_000, 90_000)          # +25k: a big prefix alone is not a reason
        self.assertEqual(self.run_hook(ctx.cmd_session_gauge, quiet), "")
        soon = self.turns(65_000, 130_000, name="soon.jsonl")   # +65k
        text = self.run_hook(ctx.cmd_session_gauge, soon)
        self.assertIn("clear soon", text)
        self.assertIn("+65k since the session started", text)
        now = self.turns(65_000, 200_000, name="now.jsonl")     # +135k
        self.assertIn("clear NOW", self.run_hook(ctx.cmd_session_gauge, now))

    def test_guard_speaks_once_per_level_and_stays_silent_before_a_threshold(self):
        p = self.turns(65_000, 70_000)
        self.assertEqual(self.run_hook(ctx.cmd_session_guard, p, session_id="s1"), "")
        p = self.turns(65_000, 140_000, name="warn.jsonl")      # +75k -> level 1
        first = json.loads(self.run_hook(ctx.cmd_session_guard, p, session_id="s1"))
        note = first["hookSpecificOutput"]
        self.assertEqual(note["hookEventName"], "PreToolUse")
        self.assertIn("at the next break", note["additionalContext"])
        self.assertNotIn("permissionDecision", note)
        self.assertEqual(self.run_hook(ctx.cmd_session_guard, p, session_id="s1"), "")  # same level
        p = self.turns(65_000, 200_000, name="crit.jsonl")      # +135k -> level 2
        second = json.loads(self.run_hook(ctx.cmd_session_guard, p, session_id="s1"))
        self.assertIn("/clear NOW", second["hookSpecificOutput"]["additionalContext"])
        again = self.run_hook(ctx.cmd_session_guard, self.turns(65_000, 70_000, name="reset.jsonl"),
                              session_id="s1")               # after a /clear the level resets
        self.assertEqual(again, "")
        self.assertIn("at the next break", self.run_hook(
            ctx.cmd_session_guard, p.with_name("warn.jsonl"), session_id="s1"))

    def test_guard_hard_stop_is_opt_in_and_still_allows_arbor_session_commands(self):
        p = self.turns(65_000, 300_000)
        self.assertNotIn("permissionDecision",
                         self.run_hook(ctx.cmd_session_guard, p, session_id="a", tool_name="Bash",
                                       tool_input={"command": "ls"}))       # default: never blocks
        args = argparse.Namespace(path=".", warn_growth=None, crit_growth=None, stop_growth=150_000)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ctx.cmd_session_limit(args), 0)
        denied = json.loads(self.run_hook(ctx.cmd_session_guard, p, session_id="a", tool_name="Read",
                                          tool_input={"file_path": "x.py"}))["hookSpecificOutput"]
        self.assertEqual(denied["permissionDecision"], "deny")
        self.assertIn("/clear", denied["permissionDecisionReason"])
        self.assertIn("+235k", denied["permissionDecisionReason"])
        for command in ("python arbor.py session save --note x", "cd \"/d/My Proj\" && python3 arbor.py memory query q"):
            self.assertEqual(self.run_hook(ctx.cmd_session_guard, p, session_id="a", tool_name="Bash",
                                           tool_input={"command": command}), "")
        blocked = self.run_hook(ctx.cmd_session_guard, p, session_id="a", tool_name="Bash",
                                tool_input={"command": "python arbor.py code find x && rm -rf ."})
        self.assertIn("deny", blocked)      # only session|memory commands pass, and only as a prefix
        below = self.turns(65_000, 120_000, name="below.jsonl")
        self.assertNotIn("deny", self.run_hook(ctx.cmd_session_guard, below, session_id="b",
                                               tool_name="Read", tool_input={}))

    def test_guard_never_breaks_on_a_missing_or_broken_transcript(self):
        args = argparse.Namespace(transcript=None, warn_tokens=None, crit_tokens=None,
                                  warn_growth=None, crit_growth=None, stop_growth=None)
        for event in ({}, {"transcript_path": "no-such-file.jsonl"}):
            sys.stdin = io.StringIO(json.dumps(event))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(ctx.cmd_session_guard(args), 0)
            self.assertEqual(out.getvalue(), "")
        Path("junk.jsonl").write_text("not json\n{]\n", encoding="utf-8")
        self.assertEqual(self.run_hook(ctx.cmd_session_guard, Path("junk.jsonl")), "")

    def test_limit_command_shows_and_persists_thresholds(self):
        def limit(**values):
            args = argparse.Namespace(path=".", warn_growth=None, crit_growth=None, stop_growth=None)
            vars(args).update(values)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(ctx.cmd_session_limit(args), 0)
            return out.getvalue()
        self.assertIn("warn +60k, clear-now +120k, hard stop off", limit())
        self.assertIn("warn +40k", limit(warn_growth=40_000))
        self.assertIn("warn +40k, clear-now +120k, hard stop +200k", limit(stop_growth=200_000))
        self.assertEqual(json.loads(Path(".arbor/config.json").read_text(encoding="utf-8"))["context"],
                         {"warn_growth": 40_000, "stop_growth": 200_000})

    def test_guard_hook_is_installed_only_by_a_hard_stop_and_removed_with_it(self):
        settings = Path(".claude/settings.local.json")
        ctx._merge_claude_local_settings(settings)      # what `init` does
        self.assertNotIn("PreToolUse", json.loads(settings.read_text(encoding="utf-8"))["hooks"])

        def limit(stop):
            out = io.StringIO()
            args = argparse.Namespace(path=".", warn_growth=None, crit_growth=None, stop_growth=stop)
            with contextlib.redirect_stdout(out):
                self.assertEqual(ctx.cmd_session_limit(args), 0)
            return out.getvalue()

        self.assertIn("hook: installed", limit(200_000))
        self.assertIn("hook: already installed", limit(250_000))
        hooks = json.loads(settings.read_text(encoding="utf-8"))["hooks"]
        self.assertEqual([h["command"] for g in hooks["PreToolUse"] for h in g["hooks"]],
                         [ctx.GUARD_HOOK_COMMAND])
        self.assertIn("UserPromptSubmit", hooks)         # the other hooks are untouched
        self.assertIn("hook: removed", limit(0))
        hooks = json.loads(settings.read_text(encoding="utf-8"))["hooks"]
        self.assertNotIn("PreToolUse", hooks)
        self.assertIn("SessionStart", hooks)
        self.assertNotIn("PreToolUse", json.loads(settings.read_text(encoding="utf-8"))["hooks"])

    def test_restore_prints_state_and_skips_stale_startup(self):
        ctx._state_write(agent="resume here", auto=None)
        args = argparse.Namespace(source="compact", max_age_hours=72.0,
                                  max_chars=8000)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(ctx.cmd_session_restore(args), 0)
        self.assertIn("resume here", out.getvalue())
        old = ctx.SESSION_STATE_PATH.stat().st_mtime - 100 * 3600
        os.utime(ctx.SESSION_STATE_PATH, (old, old))
        args = argparse.Namespace(source="startup", max_age_hours=72.0,
                                  max_chars=8000)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(ctx.cmd_session_restore(args), 0)
        self.assertEqual(out.getvalue(), "")

    def test_save_roundtrip_via_cmd(self):
        args = argparse.Namespace(note="открытые задачи: анимации", stdin=False,
                                  max_chars=6000)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(ctx.cmd_session_save(args), 0)
        self.assertIn("session state saved", out.getvalue())
        self.assertIn("анимации",
                      ctx._state_sections_read()["Agent notes"])


if __name__ == "__main__":
    unittest.main()
