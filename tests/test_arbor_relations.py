import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import arbor as ctx


class RelationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        args = argparse.Namespace(path=str(self.root))
        self.assertEqual(ctx.cmd_memory_init(args), 0)
        self.memory = self.root / "memory"

    def tearDown(self):
        self.temp.cleanup()

    def write(self, rel, text):
        (self.memory / rel).write_text(text, encoding="utf-8")

    def test_templates_declare_the_field(self):
        for rel in ("templates/task.md", "templates/bug.md",
                    "templates/decision.md", "templates/investigation.md"):
            self.assertIn("- Relations:", (self.memory / rel).read_text(encoding="utf-8"))

    def test_parses_typed_edges_and_ignores_unrelated_entries(self):
        self.write("decisions.md",
                   "# Decisions\n\n"
                   "## DEC-20260910-001 Base\n\n- Status: active\n\n"
                   "## DEC-20260914-001 Follow-up\n\n"
                   "- Status: active\n"
                   "- Relations: supersedes:DEC-20260910-001, caused-by:BUG-20260909-002\n")
        self.write("bugs.md", "# Bugs\n\n## BUG-20260909-002 Regression\n\n- Status: closed\n")
        ids, edges, issues = ctx._relations_graph(self.memory)
        self.assertEqual(ids["DEC-20260910-001"], "decisions")
        self.assertEqual(ids["BUG-20260909-002"], "bugs")
        self.assertEqual(
            sorted(edges["DEC-20260914-001"]),
            [("caused-by", "BUG-20260909-002"), ("supersedes", "DEC-20260910-001")],
        )
        self.assertEqual(issues, [])

    def test_check_flags_dangling_target_and_unknown_type(self):
        self.write("decisions.md",
                   "# Decisions\n\n## DEC-20260914-002 Orphan\n\n"
                   "- Status: active\n"
                   "- Relations: supersedes:DEC-20990101-001, affects:DEC-20260914-002\n")
        codes = {i["code"] for i in ctx.memory_check(self.root)}
        self.assertIn("dangling-relation", codes)
        self.assertIn("unknown-relation-type", codes)

    def test_archived_targets_are_not_dangling(self):
        archive = self.memory / "archive" / "tasks" / "2026-01.md"
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_text("# Archive\n\n## TASK-20260101-001 Old\n\n- Status: done\n",
                           encoding="utf-8")
        self.write("decisions.md",
                   "# Decisions\n\n## DEC-20260914-003 Refers back\n\n"
                   "- Status: active\n"
                   "- Relations: relates-to:TASK-20260101-001\n")
        self.assertEqual(ctx.memory_check(self.root), [])

    def test_malformed_id_in_relations_is_silently_skipped_not_an_edge(self):
        self.write("decisions.md",
                   "# Decisions\n\n## DEC-20260914-004 Typo\n\n"
                   "- Status: active\n"
                   "- Relations: supersedes:DEC-not-an-id\n")
        _ids, edges, issues = ctx._relations_graph(self.memory)
        self.assertEqual(edges.get("DEC-20260914-004", []), [])
        self.assertEqual(issues, [])

    def _build_chain(self):
        # INV-1 caused BUG-1; DEC-1 fixes it and supersedes DEC-0; DEC-2 later
        # supersedes DEC-1. Deliberately spans three journals plus a second hop.
        self.write("investigations.md",
                   "# Investigations\n\n## INV-20260910-001 Root cause\n\n- Status: closed\n")
        self.write("bugs.md",
                   "# Bugs\n\n## BUG-20260911-001 Symptom\n\n"
                   "- Status: closed\n- Relations: caused-by:INV-20260910-001\n")
        self.write("decisions.md",
                   "# Decisions\n\n"
                   "## DEC-20260909-001 Original\n\n- Status: superseded\n\n"
                   "## DEC-20260912-001 Fix\n\n"
                   "- Status: active\n"
                   "- Relations: supersedes:DEC-20260909-001, caused-by:BUG-20260911-001\n\n"
                   "## DEC-20260913-001 Later revision\n\n"
                   "- Status: active\n- Relations: supersedes:DEC-20260912-001\n")

    def test_trace_walks_outgoing_and_incoming_with_depth(self):
        self._build_chain()
        args = argparse.Namespace(path=str(self.root), id="DEC-20260912-001",
                                  depth=2, json=True)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(ctx.cmd_memory_trace(args), 0)
        data = json.loads(out.getvalue())
        outgoing = {(r["relation"], r["to"], r["depth"]) for r in data["outgoing"]}
        self.assertEqual(outgoing, {
            ("supersedes", "DEC-20260909-001", 1),
            ("caused-by", "BUG-20260911-001", 1),
            ("caused-by", "INV-20260910-001", 2),
        })
        incoming = {(r["relation"], r["to"], r["depth"]) for r in data["incoming"]}
        self.assertEqual(incoming, {("supersedes", "DEC-20260913-001", 1)})

    def test_trace_depth_one_stops_before_second_hop(self):
        self._build_chain()
        args = argparse.Namespace(path=str(self.root), id="DEC-20260912-001",
                                  depth=1, json=True)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ctx.cmd_memory_trace(args)
        data = json.loads(out.getvalue())
        self.assertEqual(len(data["outgoing"]), 2)  # not the INV two hops away

    def test_trace_marks_unresolved_target_in_text_output(self):
        self.write("decisions.md",
                   "# Decisions\n\n## DEC-20260914-005 Dangling\n\n"
                   "- Status: active\n- Relations: blocks:TASK-20990101-001\n")
        args = argparse.Namespace(path=str(self.root), id="DEC-20260914-005",
                                  depth=2, json=False)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(ctx.cmd_memory_trace(args), 0)
        text = out.getvalue()
        self.assertIn("DEC-20260914-005 --blocks--> TASK-20990101-001 [unresolved]", text)
        self.assertIn("(none)", text)  # nothing points back at it

    def test_trace_rejects_unknown_id(self):
        args = argparse.Namespace(path=str(self.root), id="DEC-99999999-999",
                                  depth=1, json=False)
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(ctx.cmd_memory_trace(args), 2)
        self.assertIn("unknown entry ID", err.getvalue())

    def test_trace_never_loops_on_a_relation_cycle(self):
        self.write("decisions.md",
                   "# Decisions\n\n"
                   "## DEC-20260914-006 A\n\n- Status: active\n- Relations: blocks:DEC-20260914-007\n\n"
                   "## DEC-20260914-007 B\n\n- Status: active\n- Relations: blocks:DEC-20260914-006\n")
        args = argparse.Namespace(path=str(self.root), id="DEC-20260914-006",
                                  depth=5, json=True)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(ctx.cmd_memory_trace(args), 0)
        data = json.loads(out.getvalue())
        self.assertEqual(len(data["outgoing"]), 2)  # A->B, B->A, then stops (A already seen)


if __name__ == "__main__":
    unittest.main()
