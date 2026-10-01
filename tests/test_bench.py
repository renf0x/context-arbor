"""The A/B benchmark's own machinery: scorers, statistics and stream parsing. No model is called."""
import json
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench"))

import analyze  # noqa: E402
import harness  # noqa: E402
import suites  # noqa: E402


def task(scorer, expected, **meta):
    return suites.Task("t", "k", "q", expected, scorer, {"package": "pkg", **meta})


class ScorerTests(unittest.TestCase):
    def test_answer_is_the_json_after_the_last_answer_line(self):
        text = 'thinking\nANSWER: 1\nmore\nANSWER: {"file": "a.py", "line": 3}\n'
        self.assertEqual(suites.parse_answer(text), {"file": "a.py", "line": 3})
        self.assertIsNone(suites.parse_answer("no answer here"))
        self.assertIsNone(suites.parse_answer("ANSWER: not json"))

    def test_class_line_gives_half_credit_for_the_right_file_only(self):
        t = task("def_line", {"file": "pkg/a.py", "line": 10})
        self.assertEqual(suites.score(t, {"file": "pkg/a.py", "line": 10}, package="pkg"), 1.0)
        self.assertEqual(suites.score(t, {"file": "a.py", "line": "10"}, package="pkg"), 1.0)
        self.assertEqual(suites.score(t, {"file": "pkg/a.py", "line": 11}, package="pkg"), 0.5)
        self.assertEqual(suites.score(t, {"file": "pkg/b.py", "line": 10}, package="pkg"), 0.0)
        self.assertEqual(suites.score(t, None, package="pkg"), 0.0)
        self.assertEqual(suites.score(t, [1], package="pkg"), 0.0)

    def test_defaults_compare_values_not_spelling(self):
        t = task("defaults", {"etm": "False", "iv_in": "None", "size": "65536", "enc": "'utf-8'"})
        good = {"etm": False, "iv_in": None, "size": "65536", "enc": "utf-8"}
        self.assertEqual(suites.score(t, good, package="pkg"), 1.0)
        self.assertEqual(suites.score(t, {**good, "size": 1}, package="pkg"), 0.75)
        self.assertEqual(suites.score(t, {"etm": "False"}, package="pkg"), 0.25)

    def test_caller_pairs_use_f1_and_ignore_qualification(self):
        t = task("pairs", [["pkg/a.py", "f"], ["pkg/b.py", "g"]])
        self.assertEqual(suites.score(t, ["pkg/a.py:f", "b.py:Cls.g"], package="pkg"), 1.0)
        self.assertAlmostEqual(suites.score(t, ["pkg/a.py:f"], package="pkg"), 2 / 3)
        self.assertAlmostEqual(suites.score(t, ["pkg/a.py:f", "pkg/b.py:g", "pkg/c.py:h"], package="pkg"), 0.8)
        self.assertEqual(suites.score(t, [], package="pkg"), 0.0)

    def test_name_sets_and_integers(self):
        self.assertEqual(suites.score(task("names", ["A", "B"]), ["`A`", "pkg.B"], package="pkg"), 1.0)
        self.assertAlmostEqual(suites.score(task("names", ["A", "B"]), ["A", "C"], package="pkg"), 0.5)
        self.assertEqual(suites.score(task("int", 20), "20", package="pkg"), 1.0)
        self.assertEqual(suites.score(task("int", 20), 21, package="pkg"), 0.0)


class RenameScorerTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        (self.dir / "pkg").mkdir()
        self.files = {"pkg/__init__.py": "from .a import _helper\n",
                      "pkg/a.py": "def _helper():\n    return 1\n\nx = _helper()\n",
                      "pkg/c.py": "y = 2\n"}
        for rel, text in self.files.items():
            (self.dir / rel).write_text(text, encoding="utf-8")
        import hashlib
        self.task = task("rename", {
            "old": "_helper", "new": "_helper2",
            "originals": {r: self.files[r] for r in ("pkg/__init__.py", "pkg/a.py")},
            "others": {"pkg/c.py": hashlib.sha1((self.dir / "pkg" / "c.py").read_bytes()).hexdigest()}})

    def rename(self, *rels):
        for rel in rels:
            path = self.dir / rel
            path.write_text(path.read_text(encoding="utf-8").replace("_helper", "_helper2"), encoding="utf-8")

    def test_full_rename_scores_one_partial_scores_the_fraction(self):
        self.assertEqual(suites.score_rename(self.task, self.dir), 0.0)
        self.rename("pkg/a.py")
        self.assertEqual(suites.score_rename(self.task, self.dir), 0.5)
        self.rename("pkg/__init__.py")
        self.assertEqual(suites.score_rename(self.task, self.dir), 1.0)

    def test_touching_another_file_caps_the_score(self):
        self.rename("pkg/a.py", "pkg/__init__.py")
        (self.dir / "pkg" / "c.py").write_text("y = 3\n", encoding="utf-8")
        self.assertEqual(suites.score_rename(self.task, self.dir), 0.5)

    def test_a_rename_that_breaks_the_import_scores_zero(self):
        self.rename("pkg/a.py", "pkg/__init__.py")
        (self.dir / "pkg" / "a.py").write_text(
            (self.dir / "pkg" / "a.py").read_text(encoding="utf-8") + "\nraise RuntimeError\n", encoding="utf-8")
        # the expectation no longer matches the file, so it is not a clean rename either way
        self.assertLess(suites.score_rename(self.task, self.dir), 1.0)


@unittest.skipUnless(suites.importlib.util.find_spec("paramiko"), "paramiko is not installed")
class GeneratedTasksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp())
        suites.copy_package("paramiko", cls.dir)
        cls.tasks = suites.code_tasks(cls.dir, "paramiko")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, True)

    def test_the_same_fixture_always_yields_the_same_tasks(self):
        again = suites.code_tasks(self.dir, "paramiko")
        self.assertEqual([(t.id, t.meta["target"]) for t in self.tasks],
                         [(t.id, t.meta["target"]) for t in again])

    def test_every_kind_has_the_planned_number_of_targets_and_unique_ids(self):
        ids = [t.id for t in self.tasks]
        self.assertEqual(len(ids), len(set(ids)))
        kinds = {}
        for t in self.tasks:
            kinds[t.kind] = kinds.get(t.kind, 0) + 1
        self.assertEqual(kinds["callers"], 3)
        self.assertTrue(all(n >= 2 for n in kinds.values()))
        self.assertEqual(len(kinds), 7)

    def test_the_true_answer_scores_one_and_a_shifted_one_does_not(self):
        for t in self.tasks:
            if t.scorer == "rename":
                continue
            answer = _true_answer(t)
            self.assertEqual(suites.score(t, answer, package="paramiko"), 1.0, t.id)
        line = next(t for t in self.tasks if t.scorer == "def_line")
        wrong = {"file": line.expected["file"], "line": line.expected["line"] + 1}
        self.assertLess(suites.score(line, wrong, package="paramiko"), 1.0)

    def test_ground_truth_never_contains_a_variable_or_a_bare_reraise(self):
        for t in self.tasks:
            if t.kind == "raises":
                self.assertTrue(all(name[:1].isupper() for name in t.expected), t.expected)
            if t.kind == "defaults":
                cls, method = t.meta["target"].split(".")
                ix = suites.Index(self.dir, "paramiko")
                func = next(f for _r, f, c in ix.functions[method] if c is not None and c.name == cls)
                self.assertFalse(func.args.posonlyargs)
                self.assertFalse(any(d is not None for d in func.args.kw_defaults))

    def test_tasks_do_not_mention_the_tool_under_test(self):
        for t in self.tasks:
            self.assertNotIn("arbor", t.prompt.lower())
            self.assertNotIn("index", t.prompt.lower())


@unittest.skipUnless(suites.importlib.util.find_spec("paramiko"), "paramiko is not installed")
class SessionSuiteTests(unittest.TestCase):
    def test_a_session_bundles_six_questions_and_scores_their_mean(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        suites.copy_package("paramiko", d)
        tasks = suites.code_session_tasks(d, "paramiko")
        self.assertEqual(len(tasks), 4)
        t = tasks[0]
        self.assertEqual(len(t.expected), 6)
        self.assertEqual(len({s.kind for s in t.expected}), 6)
        self.assertIn('keys "1" to "6"', t.prompt)
        truth = {str(i): _true_answer(s) for i, s in enumerate(t.expected, 1)}
        self.assertEqual(suites.score(t, truth, package="paramiko"), 1.0)
        half = {k: v for k, v in truth.items() if int(k) <= 3}
        self.assertEqual(suites.score(t, half, package="paramiko"), 0.5)
        self.assertEqual(suites.score(t, [1, 2], package="paramiko"), 0.0)
        self.assertEqual([x.meta["target"] for x in tasks],
                         [x.meta["target"] for x in suites.code_session_tasks(d, "paramiko")])


def _true_answer(t):
    if t.scorer == "def_line":
        return t.expected
    if t.scorer == "defaults":
        return t.expected
    if t.scorer == "pairs":
        return [f"{f}:{n}" for f, n in t.expected]
    return t.expected


class MemoryScorerTests(unittest.TestCase):
    def test_id_and_value_answers(self):
        self.assertEqual(suites.score(task("id", "DEC-20240111-001"), {"id": " dec-20240111-001 "}), 1.0)
        self.assertEqual(suites.score(task("id", "DEC-20240111-001"), {"id": "DEC-20240111-002"}), 0.0)
        self.assertEqual(suites.score(task("value", "1792"), {"value": "1792 ms"}), 1.0)
        self.assertEqual(suites.score(task("value", "1792"), {"value": 1792}), 1.0)
        self.assertEqual(suites.score(task("value", "1792"), {"value": 3394}), 0.0)
        self.assertEqual(suites.score(task("value", "NATS"), {"value": "nats"}), 1.0)

    def test_an_unrecorded_question_is_answered_by_saying_so_and_guessing_scores_zero(self):
        t = task("absent", None)
        for good in ({"value": None}, {"value": "not recorded"}, {"value": "Unknown"}):
            self.assertEqual(suites.score(t, good, answered=True), 1.0, good)
        self.assertEqual(suites.score(t, None, answered=True), 1.0)   # `ANSWER: null`
        self.assertEqual(suites.score(t, None, answered=False), 0.0)  # no answer line at all
        self.assertEqual(suites.score(t, {"value": "30 days"}, answered=True), 0.0)


class MemorySuiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import memsuite
        cls.m = memsuite
        cls.hist = {name: memsuite.history_for(name) for name in memsuite.SPECS}

    def test_history_is_deterministic_and_internally_consistent(self):
        for name, hist in self.hist.items():
            again = self.m.history_for(name)
            self.assertEqual([self.m.entry_block(e) for e in hist.entries],
                             [self.m.entry_block(e) for e in again.entries])
            ids = [e.id for e in hist.entries]
            self.assertEqual(len(ids), len(set(ids)))
            by_id = {e.id: e for e in hist.entries}
            for e in hist.entries:
                for _type, target in e.relations:
                    self.assertIn(target, by_id)
                if any(t == "supersedes" for t, _ in e.relations):
                    old = by_id[next(i for t, i in e.relations if t == "supersedes")]
                    self.assertEqual(old.status, "superseded")
                    self.assertEqual(e.status, "active")

    def test_every_expected_answer_is_in_the_notes_and_nothing_answers_the_unrecorded(self):
        for name, hist in self.hist.items():
            corpus = "\n".join(self.m.entry_block(e) for e in hist.entries)
            for t in suites.SUITES[name](Path("."), name):
                if t.scorer in ("id", "value"):
                    self.assertIn(str(t.expected), corpus, t.id)
                if t.scorer == "absent":
                    component, param = t.meta["target"].split("/")
                    self.assertFalse(any(component in self.m.entry_block(e) and param in self.m.entry_block(e)
                                         for e in hist.entries), t.id)

    def test_count_questions_have_the_true_count(self):
        hist = self.hist["memory"]
        for t in suites.SUITES["memory"](Path("."), "memory"):
            if t.scorer == "int":
                component = t.meta["target"]
                self.assertEqual(t.expected, sum(1 for e in hist.entries if e.kind == "DEC" and e.topic[0] == component))

    def test_prompts_do_not_name_the_tool_or_the_answer_location(self):
        for t in suites.SUITES["memory"](Path("."), "memory"):
            self.assertNotIn("arbor", t.prompt.lower())
            self.assertNotIn("docs/", t.prompt)
            self.assertNotIn("memory/", t.prompt)

    def test_both_arms_get_the_same_facts_and_the_vault_passes_its_own_check(self):
        for name, hist in self.hist.items():
            docs = Path(tempfile.mkdtemp())
            vault = Path(tempfile.mkdtemp())
            self.addCleanup(shutil.rmtree, docs, True)
            self.addCleanup(shutil.rmtree, vault, True)
            self.m.write_docs(docs, hist)
            files = list((docs / "docs").rglob("*.md"))
            self.assertEqual(len(files), len(hist.entries))
            shutil.copy2(ROOT / "arbor.py", vault / "arbor.py")
            subprocess.run([sys.executable, "arbor.py", "init", "--agents", "claude"], cwd=vault,
                           check=True, capture_output=True, timeout=120)
            self.assertEqual(self.m.write_vault(vault, hist), [], name)
            text = "\n".join(p.read_text(encoding="utf-8") for p in (vault / "memory").rglob("*.md")
                             if "templates" not in p.parts)
            for e in hist.entries:
                self.assertIn(f"## {e.id} {e.title}", text, e.id)
            if name == "memory-large":  # the vault outgrew its journal cap, so rotation archived some
                self.assertTrue(any((vault / "memory" / "archive").rglob("*.md")))


class StreamParsingTests(unittest.TestCase):
    def test_tokens_turns_tools_and_arbor_calls_are_read_from_the_stream(self):
        def assistant(mid, usage, *blocks):
            return json.dumps({"type": "assistant", "message": {"id": mid, "usage": usage, "content": list(blocks)}})
        u1 = {"input_tokens": 3, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 0, "output_tokens": 10}
        u2 = {"input_tokens": 1, "cache_creation_input_tokens": 5, "cache_read_input_tokens": 100, "output_tokens": 20}
        lines = [
            assistant("m1", u1, {"type": "tool_use", "name": "Bash", "input": {"command": "python arbor.py code map"}}),
            assistant("m1", u1, {"type": "text", "text": "same message, second block"}),
            json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "content": "x" * 400}]}}),
            assistant("m2", u2, {"type": "tool_use", "name": "Read", "input": {}}),
            json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "ANSWER: 1",
                        "total_cost_usd": 0.5, "duration_ms": 4200,
                        "modelUsage": {"m": {"inputTokens": 4, "outputTokens": 30,
                                             "cacheReadInputTokens": 100, "cacheCreationInputTokens": 105}}}),
            "not json at all",
        ]
        s = harness.summarize(lines)
        self.assertEqual(s["turns"], 2)
        self.assertEqual(s["tokens"], {"input": 4, "cache_write": 105, "cache_read": 100, "output": 30})
        self.assertEqual(s["context_processed"], 209)
        self.assertEqual(s["first_context"], 103)
        self.assertEqual(s["tools"], {"Bash": 1, "Read": 1})
        self.assertEqual(s["arbor_calls"], 1)
        self.assertEqual(s["tool_result_tokens_est"], 100)
        self.assertEqual((s["cost_usd"], s["duration_s"], s["subtype"]), (0.5, 4.2, "success"))

    def test_a_missing_result_is_reported_not_hidden(self):
        s = harness.summarize([])
        self.assertEqual(s["subtype"], "missing")
        self.assertEqual(s["turns"], 0)


class StatisticsTests(unittest.TestCase):
    def paired(self, ratios_by_task, key="context_processed"):
        out = {}
        for task_name, ratios in ratios_by_task.items():
            out[task_name] = {rep: ({key: 1000.0, "score": 1.0}, {key: 1000.0 * r, "score": 1.0})
                              for rep, r in enumerate(ratios, 1)}
        return out

    def test_a_uniform_saving_is_reported_with_a_tight_interval_below_one(self):
        m = analyze.ratio_effect(self.paired({f"t{i}": [0.5, 0.5, 0.5] for i in range(6)}), "context_processed")
        self.assertAlmostEqual(m["ratio"], 0.5)
        self.assertLess(m["hi"], 1.0)
        self.assertEqual(analyze.verdict(m["lo"], m["hi"]), "less")
        self.assertEqual(m["below"], 6)

    def test_noise_around_one_is_not_called_a_saving(self):
        rng = random.Random(3)
        data = {f"t{i}": [rng.choice([0.7, 1.3]) for _ in range(3)] for i in range(8)}
        m = analyze.ratio_effect(self.paired(data), "context_processed")
        self.assertLess(m["lo"], 1.0)
        self.assertGreater(m["hi"], 1.0)
        self.assertEqual(analyze.verdict(m["lo"], m["hi"]), "no significant difference")

    def test_a_uniform_increase_is_flagged_as_more(self):
        m = analyze.ratio_effect(self.paired({f"t{i}": [1.4, 1.4] for i in range(5)}), "context_processed")
        self.assertEqual(analyze.verdict(m["lo"], m["hi"]), "more")

    def test_sign_test_is_exact(self):
        self.assertAlmostEqual(analyze.sign_test(8, 8), 2 / 256)
        self.assertAlmostEqual(analyze.sign_test(4, 8), 1.0)
        self.assertAlmostEqual(analyze.sign_test(0, 5), 2 / 32)

    def test_pairs_need_both_arms_valid_and_a_rerun_replaces_the_old_record(self):
        def row(arm, valid=True, job="j", **extra):
            return {"job": f"{job}/{arm}", "task": "t", "rep": 1, "arm": arm, "valid": valid,
                    "context_processed": 100, "score": 1.0, **extra}
        rows = [row("control"), row("arbor", valid=False)]
        self.assertEqual(analyze.pair_up(rows), {})
        self.assertEqual(len(analyze.summarize_all(rows)["invalid"]), 1)
        rows = [row("control"), row("nomem"), row("arbor")]
        self.assertEqual(len(analyze.pair_up(rows, "nomem", "arbor")["t"]), 1)

    def test_accuracy_difference_has_its_own_interval(self):
        paired = {f"t{i}": {1: ({"score": 1.0}, {"score": 0.5}), 2: ({"score": 1.0}, {"score": 0.5})}
                  for i in range(5)}
        s = analyze.score_effect(paired)
        self.assertAlmostEqual(s["diff"], -0.5)
        self.assertEqual(analyze.verdict(s["lo"], s["hi"], False, 0.0), "worse")

    def test_reports_render_without_data_for_a_metric(self):
        summary = analyze.summarize_all([
            {"job": "a", "task": "t", "rep": 1, "arm": "control", "valid": True, "context_processed": 10,
             "cost_usd": 1, "turns": 2, "tool_result_tokens_est": 5, "duration_s": 3, "tokens": {"output": 4}, "score": 1},
            {"job": "b", "task": "t", "rep": 1, "arm": "arbor", "valid": True, "context_processed": 8,
             "cost_usd": 1, "turns": 2, "tool_result_tokens_est": 5, "duration_s": 3, "tokens": {"output": 4}, "score": 1}])
        self.assertIn("arbor / control", analyze.render_markdown(summary, "T"))
        page = analyze.render_html([summary], "T")
        self.assertTrue(page.startswith("<!doctype html>"))
        self.assertNotIn("http://", page)


if __name__ == "__main__":
    unittest.main()
