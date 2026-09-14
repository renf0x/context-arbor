import argparse


import contextlib


import io


import json


import os


import tempfile


import unittest


from pathlib import Path


from unittest import mock


import arbor as ctx


class MemoryTests(unittest.TestCase):


    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)


    def tearDown(self):
        self.temp.cleanup()


    def init_memory(self):
        args = argparse.Namespace(path=str(self.root))
        self.assertEqual(ctx.cmd_memory_init(args), 0)


    def test_init_is_idempotent_and_preserves_content(self):
        self.init_memory()
        rules = self.root / "memory" / "project-rules.md"
        self.assertTrue((self.root / "memory" / ".gitignore").is_file())
        self.assertIn("node_modules/", (self.root / ".gitignore").read_text(encoding="utf-8"))
        rules.write_text("custom rules\n", encoding="utf-8")
        self.init_memory()
        self.assertEqual(rules.read_text(encoding="utf-8"), "custom rules\n")
        self.assertTrue((self.root / "memory" / "templates" / "bug.md").is_file())

    def test_init_migrates_legacy_handoff_into_hot_ring(self):
        handoff = self.root / "handoff.md"
        handoff.write_text("# Handoff\n\n## Now\n\ncontinue auth work\n", encoding="utf-8")
        self.init_memory()
        self.assertFalse(handoff.exists())
        self.assertIn("continue auth work",
                      (self.root / "memory" / "NOW.md").read_text(encoding="utf-8"))


    def test_check_detects_missing_broken_link_and_large_index(self):
        self.init_memory()
        (self.root / "memory" / "architecture.md").unlink()
        index = self.root / "memory" / "MEMORY.md"
        index.write_text("# Index\n\n[[missing-note]]\n" + "line\n" * 121, encoding="utf-8")
        issues = ctx.memory_check(self.root)
        codes = {issue["code"] for issue in issues}
        self.assertIn("missing", codes)
        self.assertIn("broken-link", codes)
        self.assertIn("index-too-long", codes)

    def test_check_limits_hot_ring(self):
        self.init_memory()
        (self.root / "memory" / "NOW.md").write_text("active " * 1000, encoding="utf-8")
        self.assertIn("hot-ring-too-large", {i["code"] for i in ctx.memory_check(self.root)})

    def test_default_architecture_template_is_under_its_own_cap(self):
        self.init_memory()
        text = (self.root / "memory" / "architecture.md").read_text(encoding="utf-8")
        self.assertLessEqual(ctx.est_tokens(text), ctx.ARCHITECTURE_MAX_TOKENS)
        self.assertNotIn("architecture-too-large",
                         {i["code"] for i in ctx.memory_check(self.root)})

    def test_check_limits_architecture_note(self):
        self.init_memory()
        (self.root / "memory" / "architecture.md").write_text("stack fact " * 400,
                                                               encoding="utf-8")
        self.assertIn("architecture-too-large",
                      {i["code"] for i in ctx.memory_check(self.root)})


    def test_rules_change_requires_approval(self):
        self.init_memory()
        rules = self.root / "memory" / "project-rules.md"
        rules.write_text(rules.read_text(encoding="utf-8") + "\nnew rule\n", encoding="utf-8")
        self.assertIn("rules-changed", {i["code"] for i in ctx.memory_check(self.root)})
        args = argparse.Namespace(path=str(self.root), user_approved=True)
        self.assertEqual(ctx.cmd_memory_rules_approve(args), 0)
        self.assertNotIn("rules-changed", {i["code"] for i in ctx.memory_check(self.root)})


    def test_rotate_moves_only_closed_entries(self):
        self.init_memory()
        journal = self.root / "memory" / "bugs.md"
        closed = "## BUG-20260615-001\n\n- Status: closed\n\n" + ("fixed\n" * 5000)
        opened = "## BUG-20260615-002\n\n- Status: open\n\nKeep this active.\n"
        journal.write_text("# Bug Log\n\n" + closed + "\n" + opened, encoding="utf-8")
        args = argparse.Namespace(path=str(self.root))
        self.assertEqual(ctx.cmd_memory_rotate(args), 0)
        active = journal.read_text(encoding="utf-8")
        self.assertNotIn("BUG-20260615-001", active)
        self.assertIn("BUG-20260615-002", active)
        archives = list((self.root / "memory" / "archive" / "bugs").glob("*.md"))
        self.assertEqual(len(archives), 1)
        self.assertIn("BUG-20260615-001", archives[0].read_text(encoding="utf-8"))


    def test_context_bundles_memory_and_topk_notes(self):
        self.init_memory()
        # a durable decision that should surface via local top-k retrieval
        (self.root / "memory" / "decisions.md").write_text(
            "# Decision Log\n\n## DEC-1 Caching boundary\n\n"
            "- Decision: keep the prompt prefix stable to preserve cache hits.\n",
            encoding="utf-8",
        )
        text = ctx._memory_context(self.root, "prompt cache prefix stable")
        self.assertIn("memory/MEMORY.md", text)
        self.assertIn("memory/NOW.md", text)
        self.assertIn("memory/project-rules.md", text)
        self.assertIn("Relevant durable notes", text)
        self.assertIn("prompt prefix stable", text)
        self.assertNotIn("secret archived payload", text)

    def test_hot_ring_and_links_rank_above_general_notes(self):
        self.init_memory()
        (self.root / "memory" / "NOW.md").write_text(
            "# Now\n\n## TASK-1 auth\n\n- Goal: исправить авторизацию входа\n",
            encoding="utf-8",
        )
        (self.root / "memory" / "investigations.md").write_text(
            "# Investigation\n\n## INV-1 auth\n\nавторизация входа\n",
            encoding="utf-8",
        )
        hits = ctx._retrieve(self.root, "авторизация входа", 5, True)
        self.assertEqual(hits[0][1], "memory/NOW.md")

    def test_templates_and_archive_do_not_participate_in_retrieval(self):
        self.init_memory()
        (self.root / "memory" / "templates" / "task.md").write_text(
            "uniquetemplatepayload", encoding="utf-8")
        archive = self.root / "memory" / "archive" / "tasks" / "old.md"
        archive.write_text("uniquearchivepayload", encoding="utf-8")
        self.assertEqual(ctx._retrieve(self.root, "uniquetemplatepayload", 5, True), [])
        self.assertEqual(ctx._retrieve(self.root, "uniquearchivepayload", 5, True), [])

    def test_rotate_archives_completed_hot_ring_task_even_when_small(self):
        self.init_memory()
        now = self.root / "memory" / "NOW.md"
        now.write_text(
            "# Now\n\n## TASK-1 done\n\n- Status: done\n- Goal: completed\n\n"
            "## TASK-2 active\n\n- Status: active\n- Goal: continue\n",
            encoding="utf-8",
        )
        args = argparse.Namespace(path=str(self.root))
        self.assertEqual(ctx.cmd_memory_rotate(args), 0)
        self.assertNotIn("TASK-1", now.read_text(encoding="utf-8"))
        self.assertIn("TASK-2", now.read_text(encoding="utf-8"))


    def test_query_returns_local_topk_without_llm(self):
        self.init_memory()
        (self.root / "memory" / "investigations.md").write_text(
            "# Investigations\n\n## INV-7 Token budget\n\n"
            "- Findings: digest large files before reading them verbatim.\n",
            encoding="utf-8",
        )
        args = argparse.Namespace(
            path=str(self.root), scope="memory",
            question="digest large files budget", top=5, json=False,
        )
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(ctx.cmd_memory_query(args), 0)
        text = out.getvalue()
        self.assertIn("investigations.md", text)
        self.assertIn("digest large files", text)
        self.assertIn("local retrieval, no LLM", text)


    def test_query_finds_russian_notes(self):
        # \w+ tokenizer must handle Cyrillic -- an ASCII-only regex made Russian
        # notes invisible to retrieval.
        self.init_memory()
        (self.root / "memory" / "decisions.md").write_text(
            "# Решения\n\n## DEC-9 Кэширование префикса\n\n"
            "- Решение: держать префикс стабильным ради кэша.\n",
            encoding="utf-8",
        )
        args = argparse.Namespace(
            path=str(self.root), scope="memory",
            question="кэширование префикса", top=3, json=False,
        )
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(ctx.cmd_memory_query(args), 0)
        self.assertIn("Кэширование префикса", out.getvalue())


    @mock.patch("arbor._find_obsidian", return_value=None)
    def test_open_does_not_install_without_explicit_flag(self, find_obsidian):
        self.init_memory()
        args = argparse.Namespace(path=str(self.root), install_obsidian=False)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(ctx.cmd_memory_open(args), 1)
        find_obsidian.assert_called_once()


    @mock.patch("arbor.subprocess.Popen")
    @mock.patch("arbor._restart_obsidian_if_running")
    @mock.patch("arbor._register_obsidian_vault",
                return_value=("0123456789abcdef", True))
    @mock.patch("arbor._find_obsidian", return_value="C:/Program Files/Obsidian/Obsidian.exe")
    def test_open_launches_existing_obsidian(
        self, find_obsidian, register, restart, popen
    ):
        self.init_memory()
        args = argparse.Namespace(path=str(self.root), install_obsidian=False)
        self.assertEqual(ctx.cmd_memory_open(args), 0)
        register.assert_called_once_with(self.root / "memory")
        restart.assert_called_once_with()
        command = popen.call_args.args[0]
        self.assertEqual(command[0], "C:/Program Files/Obsidian/Obsidian.exe")
        self.assertEqual(command[1], "obsidian://open?vault=memory")


    @mock.patch("arbor.subprocess.Popen")
    @mock.patch("arbor.subprocess.run")
    @mock.patch("arbor.shutil.which")
    @mock.patch("arbor._register_obsidian_vault",
                return_value=("0123456789abcdef", False))
    @mock.patch("arbor._find_obsidian")
    def test_open_installs_only_with_explicit_flag(
        self, find_obsidian, register, which, run, popen
    ):
        self.init_memory()
        find_obsidian.side_effect = [None, "C:/Obsidian.exe"]
        which.return_value = "C:/Windows/winget.exe"
        run.return_value = mock.Mock(returncode=0)
        args = argparse.Namespace(path=str(self.root), install_obsidian=True)
        self.assertEqual(ctx.cmd_memory_open(args), 0)
        run.assert_called_once()
        self.assertIn("Obsidian.Obsidian", run.call_args.args[0])
        popen.assert_called_once()


    @mock.patch("arbor.subprocess.Popen")
    @mock.patch("arbor._install_obsidian_from_official_release", return_value=0)
    @mock.patch("arbor.shutil.which", return_value=None)
    @mock.patch("arbor._register_obsidian_vault",
                return_value=("0123456789abcdef", False))
    @mock.patch("arbor._find_obsidian")
    def test_open_falls_back_to_official_release_without_winget(
        self, find_obsidian, register, which, install_release, popen
    ):
        self.init_memory()
        find_obsidian.side_effect = [None, "C:/Obsidian.exe"]
        args = argparse.Namespace(path=str(self.root), install_obsidian=True)
        self.assertEqual(ctx.cmd_memory_open(args), 0)
        install_release.assert_called_once_with()
        popen.assert_called_once()


    @mock.patch.dict(os.environ, {"APPDATA": ""}, clear=False)
    def test_adapter_blocks_tell_the_agent_when_to_touch_architecture_md(self):
        for block in (ctx.AGENT_CONTEXT_MD, ctx.ADAPTER_CLAUDE, ctx.ADAPTER_AGENTS):
            self.assertIn("memory/architecture.md", block)
            self.assertIn("only when the stack or structure changes", block)
            self.assertIn("read it again only then or when asked directly", block)

    def test_register_vault_preserves_existing_entries(self):
        appdata = self.root / "appdata"
        with mock.patch.dict(os.environ, {"APPDATA": str(appdata)}, clear=False):
            config = appdata / "obsidian" / "obsidian.json"
            config.parent.mkdir(parents=True)
            config.write_text(
                '{"vaults":{"existing":{"path":"C:/notes","ts":1}}}',
                encoding="utf-8",
            )
            memory = self.root / "memory"
            memory.mkdir()
            vault_id, created = ctx._register_obsidian_vault(memory)
            data = json.loads(config.read_text(encoding="utf-8"))
            self.assertIn("existing", data["vaults"])
            self.assertEqual(len(vault_id), 16)
            self.assertTrue(created)
            self.assertTrue(any(
                value["path"] == str(memory.resolve())
                for value in data["vaults"].values()
            ))
