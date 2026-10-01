import hashlib
import tempfile
import unittest
from pathlib import Path

import arbor as ctx


def v040_block() -> str:
    """The managed block v0.4.0 shipped: today's block minus the two lines added in v0.5."""
    return (ctx.ADAPTER_CLAUDE.replace(ctx._CODE_ADAPTER_LINE + "\n", "")
            .replace(ctx._CLEAR_ADAPTER_LINE + "\n", ""))


def v040_context() -> str:
    return (ctx.AGENT_CONTEXT_MD.replace(ctx._CODE_ADAPTER_LINE + "\n", "")
            .replace(ctx._CLEAR_ADAPTER_LINE + "\n", ""))


class AdapterUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_known_hashes_really_match_the_shipped_texts(self):
        block = hashlib.sha256(v040_block().strip().encode("utf-8")).hexdigest()
        self.assertIn(block, ctx.PREVIOUS_MANAGED_BLOCK_SHA256)
        context = hashlib.sha256(v040_context().encode("utf-8")).hexdigest()
        self.assertIn(context, ctx.PREVIOUS_AGENT_CONTEXT_SHA256)

    def test_an_untouched_previous_block_is_upgraded_in_place(self):
        path = self.dir / "CLAUDE.md"
        path.write_text("# Mine\n\n" + v040_block().strip() + "\n\n# Tail\n", encoding="utf-8")
        self.assertEqual(ctx._append_managed_block(path, ctx.ADAPTER_CLAUDE), "upgraded")
        text = path.read_text(encoding="utf-8")
        self.assertIn("code map", text)
        self.assertIn("/clear", text)
        self.assertTrue(text.startswith("# Mine\n\n"))
        self.assertTrue(text.endswith("\n\n# Tail\n"))
        self.assertEqual(text.count(ctx.MANAGED_START), 1)
        self.assertEqual(ctx._append_managed_block(path, ctx.ADAPTER_CLAUDE), "kept")

    def test_a_block_the_user_edited_is_left_alone(self):
        path = self.dir / "CLAUDE.md"
        edited = v040_block().replace("Preserve user rules.", "Preserve user rules, always.")
        path.write_text(edited, encoding="utf-8")
        self.assertEqual(ctx._append_managed_block(path, ctx.ADAPTER_CLAUDE), "kept")
        self.assertEqual(path.read_text(encoding="utf-8"), edited)

    def test_crlf_files_are_still_recognised(self):
        path = self.dir / "AGENTS.md"
        path.write_bytes(v040_block().replace("\n", "\r\n").encode("utf-8"))
        self.assertEqual(ctx._append_managed_block(path, ctx.ADAPTER_AGENTS), "upgraded")

    def test_a_block_without_its_end_marker_is_never_touched(self):
        path = self.dir / "CLAUDE.md"
        broken = ctx.MANAGED_START + "\nhalf a block\n"
        path.write_text(broken, encoding="utf-8")
        self.assertEqual(ctx._append_managed_block(path, ctx.ADAPTER_CLAUDE), "kept")
        self.assertEqual(path.read_text(encoding="utf-8"), broken)

    def test_stock_generic_context_of_v040_is_migrated_but_a_custom_one_is_kept(self):
        path = self.dir / "AGENT_CONTEXT.md"
        path.write_text(v040_context(), encoding="utf-8")
        self.assertEqual(ctx._write_or_migrate_agent_context(path, ctx.AGENT_CONTEXT_MD), "migrated")
        self.assertEqual(path.read_text(encoding="utf-8"), ctx.AGENT_CONTEXT_MD)
        path.write_text(v040_context() + "\nMy own rule.\n", encoding="utf-8")
        self.assertEqual(ctx._write_or_migrate_agent_context(path, ctx.AGENT_CONTEXT_MD), "kept")

    def test_init_upgrades_a_project_installed_by_the_previous_release(self):
        (self.dir / "CLAUDE.md").write_text(v040_block().strip() + "\n", encoding="utf-8")
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ctx.main(["init", str(self.dir), "--agents", "claude"]), 0)
        self.assertIn("code map", (self.dir / "CLAUDE.md").read_text(encoding="utf-8"))

    def test_new_adapter_lines_stay_short(self):
        # This text is loaded on every session, so growth has a price. Keep it visible.
        self.assertLess(ctx.est_tokens(ctx._ADAPTER_BODY), 330)


if __name__ == "__main__":
    unittest.main()
