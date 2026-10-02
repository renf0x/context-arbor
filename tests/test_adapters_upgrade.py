import hashlib
import tempfile
import unittest
from pathlib import Path

import arbor as ctx


# The adapter lines v0.5.0 shipped, verbatim; v0.4.0 had the same minus the code and /clear lines.
V050_CLEAR_LINE = ("Suggest `/clear`, not `/compact` (compaction is a model call); saved state comes "
                   "back on its own.")
V050_LINES = (
    "When prior project context is needed, read `memory/NOW.md` first and follow links on demand.",
    'Search durable notes with `python arbor.py memory query "question"`; do not scan the vault.',
    ctx._CODE_ADAPTER_LINE,
    "Keep only the active task in `memory/NOW.md`; store durable outcomes in linked notes.",
    ctx._ARCHITECTURE_ADAPTER_LINE,
    "Preserve user rules. Update their checksum only after explicit user approval.",
    'Before clearing context, save useful state with `python arbor.py session save --note "..."`.',
    V050_CLEAR_LINE,
    "Use `python arbor.py session restore` to recover it. Treat restored notes as potentially stale.",
    "Open the vault with `python arbor.py memory open`. Context Arbor invokes no model.",
)
V040_LINES = tuple(line for line in V050_LINES if line not in (ctx._CODE_ADAPTER_LINE, V050_CLEAR_LINE))


def block(lines) -> str:
    return (ctx.MANAGED_START + "\n# Context Arbor: memory and sessions\n\n" + "\n".join(lines)
            + "\n\n" + ctx.MANAGED_END + "\n")


def context(lines) -> str:
    return "# Context Arbor: memory and sessions\n\n" + "\n".join(lines) + "\n"


def v040_block() -> str:
    return block(V040_LINES)


def v040_context() -> str:
    return context(V040_LINES)


class AdapterUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_known_hashes_really_match_the_shipped_texts(self):
        for lines in (V040_LINES, V050_LINES):
            digest = hashlib.sha256(block(lines).strip().encode("utf-8")).hexdigest()
            self.assertIn(digest, ctx.PREVIOUS_MANAGED_BLOCK_SHA256)
            digest = hashlib.sha256(context(lines).encode("utf-8")).hexdigest()
            self.assertIn(digest, ctx.PREVIOUS_AGENT_CONTEXT_SHA256)

    def test_an_untouched_previous_block_is_upgraded_in_place(self):
        for lines in (V040_LINES, V050_LINES):
            path = self.dir / "CLAUDE.md"
            path.write_text("# Mine\n\n" + block(lines).strip() + "\n\n# Tail\n", encoding="utf-8")
            self.assertEqual(ctx._append_managed_block(path, ctx.ADAPTER_CLAUDE), "upgraded")
            text = path.read_text(encoding="utf-8")
            self.assertIn("code map", text)
            self.assertIn("/autocompact 200k", text)
            self.assertNotIn(V050_CLEAR_LINE, text)
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
