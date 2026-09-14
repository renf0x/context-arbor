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
        self.assertIn("compact NOW", out.getvalue())

    def test_gauge_uses_last_main_chain_usage(self):
        p = self.write_transcript([
            {"type": "assistant", "message": {"role": "assistant", "usage": {
                "cache_read_input_tokens": 130_000}}},
            {"isSidechain": True, "message": {"role": "assistant", "usage": {
                "cache_read_input_tokens": 100}}},
        ])
        self.assertEqual(ctx._last_context_tokens(p), 130_000)

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
