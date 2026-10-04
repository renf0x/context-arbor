"""The arbor.py side of the Claude Code mod: compaction window as JSON, Jev notes and log for a
model the mod runs, exact per-turn records and their KPI in the UI."""
import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import arbor as ctx


KEY = "sk-or-v1-" + "a1b2c3d4" * 8

DECISIONS = """# Decision Log

## DEC-20260901-001 Headless Godot never runs next to the editor

- Status: active
- Decision: Close the editor before headless runs. """ + "x" * 400 + """

## DEC-20260902-002 Quality presets

- Status: active
- Decision: Three presets.
"""


def run(argv, stdin=""):
    out = io.StringIO()
    with mock.patch("sys.stdin", io.StringIO(stdin)), contextlib.redirect_stdout(out):
        code = ctx.main(argv)
    return code, out.getvalue()


class ModBase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        (self.root / "memory").mkdir()
        (self.root / "memory" / "decisions.md").write_text(DECISIONS, encoding="utf-8")
        patcher = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.root / "cc")})
        patcher.start()
        self.addCleanup(patcher.stop)


class CompactionWindowTest(ModBase):
    def test_without_transcripts_the_hint_is_the_window(self):
        code, out = run(["session", "compaction", "--json", "--path", str(self.root)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"hint": 200_000, "suggested": None, "sessions": 0, "window": 200_000})

    def test_a_suggestion_from_the_replay_wins(self):
        with mock.patch.object(ctx, "_long_sessions", return_value=[("s1", [{}])]), \
                mock.patch.object(ctx, "_simulate_report", return_value={"sessions": [
                    {"windows": {str(w): {"cost": 1.0 if w == 250_000 else 2.0}
                                 for w in (150_000, 200_000, 250_000, 300_000, 400_000, 967_000)}}]}):
            (self.root / "cc" / "projects").mkdir(parents=True)
            ctx._claude_projects_dir(self.root).mkdir()
            window = ctx.compaction_window(self.root)
        self.assertEqual((window["suggested"], window["window"], window["sessions"]), (250_000, 250_000, 1))


class RecordTurnTest(ModBase):
    def test_only_numbers_and_ids_are_kept(self):
        raw = {"session": "abc-123/../x", "agent": 0, "model": "claude-opus-5-5[1m]; rm", "input": 10,
               "output": "7", "cache_read": -5, "cache_write": None, "ms": 1500.9, "context": 140_000,
               "usd_total": 1.25, "prompt": "секретный запрос", "answer": "ответ"}
        code, _ = run(["session", "record-turn", "--stdin", "--path", str(self.root)], json.dumps(raw))
        self.assertEqual(code, 0)
        line = (self.root / ctx.TURNS_PATH).read_text(encoding="utf-8")
        record = json.loads(line)
        self.assertEqual(record["session"], "abc-123x")
        self.assertEqual(record["model"], "claude-opus-5-5[1m]rm")
        self.assertEqual((record["input"], record["output"], record["cache_read"], record["cache_write"]), (10, 7, 0, 0))
        self.assertEqual((record["ms"], record["context"], record["usd_total"], record["agent"]), (1500, 140_000, 1.25, False))
        self.assertNotIn("секретный", line)
        self.assertNotIn("ответ", line)

    def test_bad_input_is_refused(self):
        self.assertEqual(run(["session", "record-turn", "--stdin", "--path", str(self.root)], "not json")[0], 2)
        self.assertEqual(run(["session", "record-turn", "--stdin", "--path", str(self.root)], "[1]")[0], 2)
        self.assertFalse((self.root / ctx.TURNS_PATH).exists())

    def test_measured_cost_adds_up_by_deltas_and_a_resume_starts_over(self):
        path = self.root / ctx.TURNS_PATH
        path.parent.mkdir()
        rows = [("2026-10-01T10:00:00", "a", 0.5), ("2026-10-01T10:05:00", "a", 1.5),
                ("2026-10-02T09:00:00", "a", 0.25),  # resumed: the counter restarted
                ("2026-10-02T09:01:00", "b", 2.0), ("2026-10-02T09:02:00", "b", None)]
        lines = [json.dumps({"t": t, "session": sid, "input": 1, "output": 2,
                             **({"usd_total": usd} if usd is not None else {})}) for t, sid, usd in rows]
        path.write_text("\n".join(lines + ["garbage"]) + "\n", encoding="utf-8")
        measured = ctx._ui_measured(self.root)
        self.assertEqual((measured["turns"], measured["sessions"]), (5, 2))
        self.assertAlmostEqual(measured["usd"], 3.75)
        self.assertEqual([(d["date"], round(d["usd"], 2)) for d in measured["days"]],
                         [("2026-10-01", 1.5), ("2026-10-02", 2.25)])
        self.assertEqual(measured["tokens"]["output"], 10)


class JevForModTest(ModBase):
    def test_entries_carry_ids_cut_bodies_and_the_spend_gate(self):
        code, out = run(["jev", "entries", "--json", "--chars", "120", "--path", str(self.root)])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual([e["id"] for e in payload["entries"]], ["n0", "n1"])
        self.assertTrue(payload["entries"][0]["body"].endswith(" ..."))
        self.assertLessEqual(len(payload["entries"][0]["body"]), 124)
        self.assertEqual(payload["config"]["daily_cap_usd"], 0.5)
        self.assertEqual(payload["config"]["spent_today"], 0)

    def test_log_keeps_the_ui_fields_and_never_a_prompt_or_key(self):
        raw = {"source": "Claude!", "kind": "memory", "entries": 2, "questions": 2, "cost": 0.0012,
               "latency_s": 1.234, "injected": ["DEC-20260901-001 Headless " + "y" * 100, 5],
               "top": [{"title": "DEC-20260901-001", "p": 0.91}, "bad"], "model": "haiku",
               "error": "boom " + KEY, "prompt": "секретный запрос"}
        code, _ = run(["jev", "log", "--path", str(self.root)], json.dumps(raw))
        self.assertEqual(code, 0)
        text = (self.root / ctx.JEV_LOG_PATH).read_text(encoding="utf-8")
        self.assertNotIn("секретный", text)
        self.assertNotIn(KEY, text)
        record = json.loads(text)
        self.assertEqual(record["source"], "mod-claude")
        self.assertEqual(len(record["injected"]), 1)
        self.assertEqual(len(record["injected"][0]), 70)
        self.assertEqual(record["top"], [{"title": "DEC-20260901-001", "p": 0.91}])
        log = ctx._ui_jev_log(self.root)
        self.assertEqual((log["calls"], round(log["cost"], 4)), (1, 0.0012))
        self.assertAlmostEqual(ctx._jev_spent_today(self.root), 0.0012)


if __name__ == "__main__":
    unittest.main()
