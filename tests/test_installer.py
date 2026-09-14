import tempfile
import unittest
import hashlib
from pathlib import Path
from unittest import mock

import install


class InstallerTests(unittest.TestCase):
    def test_installs_all_adapters_without_overwriting_existing_rules(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "AGENTS.md").write_text("# Existing\n", encoding="utf-8")
            with mock.patch("install.run", return_value=0):
                result = install.main([str(project), "--agents", "all"])
            self.assertEqual(result, 0)
            self.assertTrue((project / "arbor.py").is_file())
            self.assertFalse((project / "rlm.py").exists())
            self.assertTrue((project / "AGENT_CONTEXT.md").is_file())
            self.assertEqual(
                (project / "AGENT_CONTEXT.md").read_text(encoding="utf-8"),
                install.read_template("AGENT_CONTEXT.md"),
            )
            agents = (project / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("# Existing", agents)
            self.assertIn(install.read_template("adapters/AGENTS.md").strip(), agents)
            self.assertEqual(agents.count(install.MANAGED_START), 1)
            self.assertTrue((project / "CLAUDE.md").is_file())
            self.assertEqual(
                (project / "CLAUDE.md").read_text(encoding="utf-8"),
                install.read_template("adapters/CLAUDE.md").rstrip() + "\n",
            )

    def test_repeated_install_does_not_duplicate_managed_blocks(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            with mock.patch("install.run", return_value=0):
                self.assertEqual(install.main([str(project)]), 0)
                self.assertEqual(install.main([str(project)]), 0)
            agents = (project / "AGENTS.md").read_text(encoding="utf-8")
            claude = (project / "CLAUDE.md").read_text(encoding="utf-8")
            self.assertEqual(agents.count(install.MANAGED_START), 1)
            self.assertEqual(claude.count(install.MANAGED_START), 1)

    def test_legacy_managed_block_is_replaced_without_touching_surrounding_text(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "AGENTS.md"
            target.write_text(
                "# User rule\n\n" + install.LEGACY_MANAGED_START
                + "\nold CACP text\n" + install.LEGACY_MANAGED_END + "\n\n# Tail\n",
                encoding="utf-8",
            )
            block = install.read_template("adapters/AGENTS.md").strip()
            self.assertEqual(install.append_managed_block(target, block), "migrated")
            text = target.read_text(encoding="utf-8")
            self.assertIn("# User rule", text)
            self.assertIn("# Tail", text)
            self.assertIn(install.MANAGED_START, text)
            self.assertNotIn("old CACP text", text)

    def test_untouched_legacy_generic_context_is_migrated(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            legacy = '# Legacy stock context\n'
            target = project / 'AGENT_CONTEXT.md'
            target.write_text(legacy, encoding='utf-8')
            digest = hashlib.sha256(legacy.encode('utf-8')).hexdigest()
            with mock.patch('install.LEGACY_AGENT_CONTEXT_SHA256', digest):
                self.assertEqual(
                    install.write_or_migrate_agent_context(
                        target, install.read_template('AGENT_CONTEXT.md')
                    ),
                    'migrated',
                )
            self.assertEqual(target.read_text(encoding='utf-8'),
                             install.read_template('AGENT_CONTEXT.md'))

    def test_custom_generic_context_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'AGENT_CONTEXT.md'
            target.write_text('# User-owned context\n', encoding='utf-8')
            self.assertEqual(
                install.write_or_migrate_agent_context(target, 'replacement\n'),
                'kept',
            )
            self.assertEqual(target.read_text(encoding='utf-8'), '# User-owned context\n')

    def test_real_install_creates_valid_generic_memory(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            result = install.main([
                str(project),
                "--agents",
                "generic",
            ])
            self.assertEqual(result, 0)
            self.assertTrue((project / "memory" / "MEMORY.md").is_file())
            self.assertNotIn(
                "COURSE_OVERVIEW",
                (project / "memory" / "MEMORY.md").read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
