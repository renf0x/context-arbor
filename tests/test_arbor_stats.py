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


def record(message_id, inp, cache_write, cache_read, out, side=False,
           stamp="2026-09-01T10:00:00Z"):
    return {"type": "assistant", "timestamp": stamp, "isSidechain": side, "uuid": message_id + "-u",
            "message": {"id": message_id, "role": "assistant", "usage": {
                "input_tokens": inp, "cache_creation_input_tokens": cache_write,
                "cache_read_input_tokens": cache_read, "output_tokens": out}}}


class StatsTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)

    def write(self, rel, records):
        path = self.dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")

    def test_lines_of_one_message_count_once_with_the_largest_output(self):
        self.write("s1.jsonl", [
            record("m1", 10, 100, 1000, 1),
            record("m1", 10, 100, 1000, 1),   # one line per content block repeats the usage
            record("m1", 10, 100, 1000, 50),
            record("m2", 5, 0, 2000, 20, stamp="2026-09-01T10:05:00Z"),
        ])
        usage = ctx.collect_usage(Path("."), self.dir)
        totals = usage["totals"]
        self.assertEqual((totals["input"], totals["cache_write"], totals["cache_read"], totals["output"]),
                         (15, 100, 3000, 70))
        self.assertEqual(totals["turns"], 2)
        self.assertEqual(totals["peak_context"], 2005)
        self.assertEqual(usage["sessions"][0]["first"], "2026-09-01T10:00:00Z")
        self.assertAlmostEqual(usage["cache_share"], 3000 / 3115)

    def test_subagent_transcripts_join_their_session_but_not_its_peak_context(self):
        self.write("s1.jsonl", [record("m1", 1, 0, 100, 5)])
        self.write("s1/subagents/agent-a.jsonl", [record("x1", 1, 0, 9000, 5)])
        self.write("s1.jsonl", [record("m1", 1, 0, 100, 5),
                                record("side", 1, 0, 700, 5, side=True)])
        usage = ctx.collect_usage(Path("."), self.dir)
        row = usage["sessions"][0]
        self.assertEqual((row["turns"], row["subagent_turns"]), (1, 2))
        self.assertEqual(row["cache_read"], 100 + 700 + 9000)
        self.assertEqual(row["peak_context"], 101)

    def test_records_without_usage_and_bad_lines_are_ignored(self):
        path = self.dir / "s1.jsonl"
        path.write_text("not json\n" + json.dumps({"type": "user", "message": {"role": "user"}})
                        + "\n" + json.dumps(record("m1", 1, 2, 3, 4)) + "\n[]\n", encoding="utf-8")
        usage = ctx.collect_usage(Path("."), self.dir)
        self.assertEqual(usage["totals"]["turns"], 1)

    def test_no_transcripts_means_none(self):
        self.assertIsNone(ctx.collect_usage(Path("."), self.dir / "missing"))
        self.assertIsNone(ctx.collect_usage(Path("."), self.dir))

    def test_projects_directory_uses_claude_codes_folder_naming(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.dir)}):
            folder = ctx._claude_projects_dir(Path(r"C:\Users\Renf\Desktop\Новая папка\cacp"))
        self.assertEqual(folder.name, "C--Users-Renf-Desktop-------------cacp")
        self.assertEqual(folder.parent, self.dir / "projects")

    def test_prices_parse_and_reject_typos_and_gaps(self):
        prices = ctx._parse_prices("input=10,cache_write=12.5,cache_read=1,output=50")
        self.assertEqual(prices["cache_write"], 12.5)
        with self.assertRaises(ValueError):
            ctx._parse_prices("input=1,cache_read=1,cache_write=1,outpt=1")
        with self.assertRaises(ValueError):
            ctx._parse_prices("input=1,output=1")

    def test_cost_is_per_million_tokens_and_summed(self):
        totals = {"input": 1_000_000, "cache_write": 0, "cache_read": 2_000_000, "output": 500_000}
        cost = ctx.usage_cost(totals, {"input": 10, "cache_write": 12, "cache_read": 1, "output": 50})
        self.assertEqual((cost["input"], cost["cache_read"], cost["output"]), (10.0, 2.0, 25.0))
        self.assertEqual(cost["total"], 37.0)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ctx.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_cli_reports_tokens_and_only_prices_what_it_is_told(self):
        self.write("abc12345.jsonl", [record("m1", 100, 1000, 900_000, 2000)])
        project = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, project, True)
        code, out, _ = self.run_cli("stats", "--path", project, "--transcripts", str(self.dir))
        self.assertEqual(code, 0)
        self.assertIn("cache read", out)
        self.assertIn("99.9% of all input", out)
        self.assertIn("abc12345", out)
        self.assertNotIn("$", out)
        self.assertIn("no prices set", out)
        code, out, _ = self.run_cli("stats", "--path", project, "--transcripts", str(self.dir),
                                    "--prices", "input=1,cache_write=1,cache_read=1,output=1", "--save")
        self.assertIn("total", out)
        self.assertIn("$", out)
        self.assertEqual(ctx._stored_prices(Path(project))["output"], 1.0)
        code, out, _ = self.run_cli("stats", "--path", project, "--transcripts", str(self.dir), "--json")
        self.assertIsNotNone(json.loads(out)["cost_usd"])

    def why_session(self, compactions=3, per_segment=10, start=65_000, after=100_000, written=60_000):
        """A session that grows 2k per turn and is compacted `compactions` times, as
        Claude Code logs it: a compact_boundary record, then a turn that rewrites the context."""
        records, n = [], 0

        def turn(context, cache_write=0, thinking=0):
            nonlocal n
            n += 1
            r = record(f"m{n}", 5, cache_write, context - 5 - cache_write, 100)
            r["message"]["usage"]["output_tokens_details"] = {"thinking_tokens": thinking}
            records.append(r)

        context = start
        turn(context, cache_write=25_000, thinking=60)
        for segment in range(compactions + 1):
            if segment:
                records.append({"type": "system", "subtype": "compact_boundary", "uuid": f"c{segment}",
                                "compactMetadata": {"trigger": "manual", "preTokens": context}})
                context = after
                turn(context, cache_write=written, thinking=60)
            for _ in range(per_segment):
                context += 2_000
                turn(context, thinking=60)
        return records

    def test_why_finds_compactions_their_size_and_suggests_a_fixed_window(self):
        self.write("s1.jsonl", self.why_session())
        report = ctx._why_report(self.dir, None)
        self.assertEqual(len(report), 1)
        row = report[0]
        self.assertEqual((row["turns"], row["compactions"], row["baseline"]), (44, 3, 65_000))
        self.assertEqual((row["compaction_before"], row["compaction_after"], row["compaction_written"]),
                         (120_000, 100_000, 60_000))   # segments end at 85k, 120k, 120k
        self.assertEqual(row["compactions_below_150k"], 3)
        self.assertEqual(row["growth_per_turn"], 2_000)
        self.assertGreater(row["compaction_share"], 0.10)
        self.assertEqual(row["compactions_manual"], 3)
        self.assertAlmostEqual(row["compaction_payback_turns"], 60.0)  # 60k written * 2.0 / (20k dropped * 0.1)
        self.assertTrue(any("/autocompact 200k" in tip and "3 of them manual /compact" in tip
                            and "to win back" in tip for tip in row["advice"]))
        self.assertTrue(any("thinking is 60%" in tip for tip in row["advice"]))

    def test_why_ignores_replayed_history_and_short_sessions(self):
        records = self.why_session()
        self.write("s1.jsonl", records + records)        # the file repeats the whole history
        self.write("short.jsonl", records[:5])
        report = ctx._why_report(self.dir, None)
        self.assertEqual([r["id"] for r in report], ["s1"])
        self.assertEqual((report[0]["turns"], report[0]["compactions"]), (44, 3))

    def test_why_without_compaction_or_runaway_says_nothing_dramatic(self):
        self.write("s1.jsonl", self.why_session(compactions=0, per_segment=25))
        row = ctx._why_report(self.dir, None)[0]
        self.assertEqual(row["compactions"], 0)
        self.assertFalse(any("compaction" in tip for tip in row["advice"]))

    def test_why_flags_a_run_far_above_its_start_and_uses_prices_when_given(self):
        self.write("s1.jsonl", self.why_session(compactions=0, per_segment=200))  # 65k -> 465k
        row = ctx._why_report(self.dir, None)[0]
        self.assertGreater(row["long_run_share"], 0.25)
        self.assertTrue(any("200k+ above" in tip and "/autocompact" in tip for tip in row["advice"]))
        prices = {"input": 3.0, "cache_write": 3.75, "cache_read": 0.3, "output": 15.0}
        self.assertAlmostEqual(ctx._why_report(self.dir, prices)[0]["long_run_share"],
                               row["long_run_share"], delta=0.15)

    def test_cli_why_prints_a_section_and_json_carries_it(self):
        self.write("s1.jsonl", self.why_session())
        project = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, project, True)
        code, out, _ = self.run_cli("stats", "--why", "--path", project, "--transcripts", str(self.dir))
        self.assertEqual(code, 0)
        self.assertIn("# why: where each session's cost goes", out)
        self.assertIn("compaction", out)
        code, out, _ = self.run_cli("stats", "--why", "--json", "--path", project,
                                    "--transcripts", str(self.dir))
        self.assertEqual(json.loads(out)["why"][0]["compactions"], 3)
        code, out, _ = self.run_cli("stats", "--json", "--path", project, "--transcripts", str(self.dir))
        self.assertNotIn("why", json.loads(out))

    def test_parse_window_takes_what_autocompact_takes(self):
        self.assertEqual([ctx._parse_window(t) for t in ("250k", "1M", "200", "300000", " 967K ")],
                         [250_000, 1_000_000, 200_000, 300_000, 967_000])
        for bad in ("50k", "2M", "abc", ""):
            with self.assertRaises(ValueError):
                ctx._parse_window(bad)

    def test_replay_above_the_peak_reproduces_the_recorded_cost(self):
        turns = ctx._diagnose_transcript(self.write_path("s1.jsonl", self.why_session(0, 25)))
        model = ctx._compaction_model([turns])
        recorded = ctx._replay(turns, None, model, None)
        replayed = ctx._replay(turns, 1_000_000, model, None)
        self.assertAlmostEqual(replayed["cost"], recorded["cost"])
        self.assertAlmostEqual(recorded["cost"], sum(sum(ctx._turn_cost(t, None)) for t in turns))
        self.assertEqual((recorded["compactions"], replayed["compactions"]), (0, 0))

    def test_replay_compacts_at_the_window_and_restarts_from_the_carry_over(self):
        turns = ctx._diagnose_transcript(self.write_path("s1.jsonl", self.why_session(0, 200)))
        model = {"carry": 20_000, "rewrite": 30_000, "summary": 3_000, "measured": 0}
        recorded = ctx._replay(turns, None, model, None)      # 65k -> 465k, never compacted
        replayed = ctx._replay(turns, 200_000, model, None)   # 65k -> 201k, then 85k -> 201k twice
        self.assertEqual(replayed["compactions"], 3)
        self.assertLess(replayed["avg_context"], recorded["avg_context"])
        self.assertLess(replayed["cost"], recorded["cost"])

    def test_compaction_model_measures_the_users_own_compactions(self):
        records = []
        for r in self.why_session():          # three compactions: 120k -> 100k, 60k rewritten
            records.append(r)
            if r.get("subtype") == "compact_boundary":
                records.append({"type": "user", "isCompactSummary": True, "uuid": r["uuid"] + "s",
                                "message": {"role": "user", "content": [{"type": "text", "text": "x" * 7_000}]}})
        turns = ctx._diagnose_transcript(self.write_path("s1.jsonl", records))
        model = ctx._compaction_model([turns])
        self.assertEqual((model["measured"], model["carry"], model["rewrite"]), (3, 35_000, 60_000))
        self.assertAlmostEqual(model["summary"], 7_000 / ctx.CHARS_PER_TOKEN)
        recorded = ctx._replay(turns, None, model, None)
        self.assertEqual(recorded["compactions"], 3)
        self.assertGreater(recorded["cost"], sum(sum(ctx._turn_cost(t, None)) for t in turns))

    def test_cli_simulate_compact_prints_a_table_and_json_carries_it(self):
        self.write("s1.jsonl", self.why_session(0, 200))
        project = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, project, True)
        code, out, _ = self.run_cli("stats", "--simulate-compact", "200k,1M", "--path", project,
                                    "--transcripts", str(self.dir))
        self.assertEqual(code, 0)
        self.assertIn("# simulate-compact", out)
        self.assertIn("suggested window: 200k", out)
        code, out, _ = self.run_cli("stats", "--simulate-compact", "--json", "--path", project,
                                    "--transcripts", str(self.dir))
        sim = json.loads(out)["simulate"]
        self.assertEqual(sim["windows"], [150_000, 200_000, 250_000, 300_000, 400_000, 967_000])
        self.assertEqual(sim["sessions"][0]["windows"]["967000"]["compactions"], 0)  # peak is 465k
        code, _, err = self.run_cli("stats", "--simulate-compact", "20k", "--path", project,
                                    "--transcripts", str(self.dir))
        self.assertEqual(code, 2)
        self.assertIn("--simulate-compact", err)

    def write_path(self, rel, records):
        self.write(rel, records)
        return self.dir / rel

    def test_cli_explains_a_missing_transcript_folder_and_bad_prices(self):
        project = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, project, True)
        code, _, err = self.run_cli("stats", "--path", project, "--transcripts", str(self.dir / "none"))
        self.assertEqual(code, 1)
        self.assertIn("no Claude Code transcripts", err)
        self.write("s.jsonl", [record("m1", 1, 1, 1, 1)])
        code, _, err = self.run_cli("stats", "--path", project, "--transcripts", str(self.dir),
                                    "--prices", "input=1")
        self.assertEqual(code, 2)
        self.assertIn("missing prices", err)


if __name__ == "__main__":
    unittest.main()
