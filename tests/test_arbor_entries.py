import json
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ARBOR = Path(__file__).resolve().parents[1] / "arbor.py"


def run(root: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ARBOR), *args, "--path", str(root)],
                          input=stdin, capture_output=True, text=True, encoding="utf-8")


class EntryCrudTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        subprocess.run([sys.executable, str(ARBOR), "memory", "init", str(self.root)],
                       check=True, capture_output=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def add(self, *args: str, stdin: str | None = None) -> dict:
        proc = run(self.root, "memory", "add", *args, "--json", stdin=stdin)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_add_get_update_close_delete(self) -> None:
        entry = self.add("--type", "IDEA", "--title", "Интеграция с Azure",
                         "--field", "Summary=Тянуть тест-планы", "--field", "Author=agent")
        eid = entry["id"]
        self.assertRegex(eid, r"^IDEA-\d{8}-001$")
        self.assertEqual(entry["status"], "idea")
        self.assertEqual(entry["note"], "ideas.md")

        got = json.loads(run(self.root, "memory", "get", eid, "--json").stdout)
        self.assertEqual(got["title"], "Интеграция с Azure")
        self.assertEqual(got["fields"]["Summary"], "Тянуть тест-планы")

        payload = json.dumps({"status": "in-progress", "fields": {"Proposal": "строка 1\nстрока 2"}})
        upd = run(self.root, "memory", "update", eid, "--input-json", "--json", stdin=payload)
        self.assertEqual(upd.returncode, 0, upd.stderr)
        got = json.loads(run(self.root, "memory", "get", eid, "--json").stdout)
        self.assertEqual(got["status"], "in-progress")
        self.assertEqual(got["fields"]["Proposal"], "строка 1\nстрока 2")

        self.assertEqual(run(self.root, "memory", "close", eid, "--status", "done").returncode, 0)
        listed = json.loads(run(self.root, "memory", "list", "--type", "IDEA",
                                "--status", "done", "--json").stdout)["entries"]
        self.assertEqual([e["id"] for e in listed], [eid])

        # `check` takes a positional path, so call it directly.
        check = subprocess.run([sys.executable, str(ARBOR), "memory", "check", str(self.root)],
                               capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stdout)

        self.assertNotEqual(run(self.root, "memory", "delete", eid).returncode, 0)
        self.assertEqual(run(self.root, "memory", "delete", eid, "--yes").returncode, 0)
        self.assertNotEqual(run(self.root, "memory", "get", eid).returncode, 0)

    def test_sequential_ids_and_relations(self) -> None:
        first = self.add("--type", "KNW", "--title", "a")
        second = self.add("--type", "KNW", "--title", "b",
                          "--field", f"Relations=supersedes:{first['id']}")
        self.assertTrue(second["id"].endswith("-002"))
        trace = run(self.root, "memory", "trace", second["id"], "--json")
        self.assertEqual(json.loads(trace.stdout)["outgoing"][0]["to"], first["id"])

    def test_parallel_adds_get_unique_ids(self) -> None:
        with ThreadPoolExecutor(max_workers=6) as pool:
            ids = list(pool.map(lambda i: self.add("--type", "CHG", "--title", f"c{i}")["id"],
                                range(12)))
        self.assertEqual(len(set(ids)), 12)
        listed = json.loads(run(self.root, "memory", "list", "--type", "CHG", "--json").stdout)
        self.assertEqual(len(listed["entries"]), 12)

    def test_prune_removes_old_history_months(self) -> None:
        history = self.root / "memory" / "history"
        history.mkdir(parents=True, exist_ok=True)
        (history / "2000-01.md").write_text("# old\n", encoding="utf-8")
        self.add("--type", "CHG", "--title", "fresh")
        out = json.loads(run(self.root, "memory", "prune", "--older-than-months", "6",
                             "--json").stdout)
        self.assertEqual(out["removed"], ["history/2000-01.md"])
        self.assertEqual(len(list(history.glob("*.md"))), 1)


if __name__ == "__main__":
    unittest.main()
