import contextlib
import io
import json
import tempfile
import unittest
import hashlib
from pathlib import Path
from unittest import mock

import arbor as ctx


class ScopeTests(unittest.TestCase):
    def test_embedded_adapters_match_install_templates(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(
            ctx.AGENT_CONTEXT_MD,
            (root / 'templates/AGENT_CONTEXT.md').read_text(encoding='utf-8'),
        )
        self.assertEqual(
            ctx.ADAPTER_AGENTS,
            (root / 'templates/adapters/AGENTS.md').read_text(encoding='utf-8'),
        )
        self.assertEqual(
            ctx.ADAPTER_CLAUDE,
            (root / 'templates/adapters/CLAUDE.md').read_text(encoding='utf-8'),
        )

    def test_removed_commands_are_rejected(self):
        for name in ('pack', 'map', 'digest', 'guard', 'hook', 'measure',
                     'report', 'run', 'read', 'count', 'rawcount'):
            with self.subTest(command=name), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    ctx.main([name])
                self.assertEqual(error.exception.code, 2)

    def test_init_only_installs_session_hooks_and_no_packet(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(temp)
            self.assertEqual(ctx.main(['init', temp]), 0)
            settings = json.loads((root / '.claude/settings.local.json').read_text())
            self.assertIs(settings['autoMemoryEnabled'], False)
            self.assertEqual(set(settings['hooks']),
                             {'UserPromptSubmit', 'PreCompact', 'SessionStart', 'SessionEnd'})
            self.assertFalse((root / '.arbor').exists())

    def test_init_migrates_untouched_legacy_generic_context(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(temp)
            legacy = '# Legacy stock context\n'
            (root / 'AGENT_CONTEXT.md').write_text(legacy, encoding='utf-8')
            digest = hashlib.sha256(legacy.encode('utf-8')).hexdigest()
            with mock.patch.object(ctx, 'LEGACY_AGENT_CONTEXT_SHA256', digest):
                self.assertEqual(ctx.main(['init', temp, '--agents', 'generic']), 0)
            self.assertEqual((root / 'AGENT_CONTEXT.md').read_text(encoding='utf-8'),
                             ctx.AGENT_CONTEXT_MD)
            self.assertEqual(ctx.main(['memory', 'context', 'test', '--path', temp]), 0)
            self.assertFalse((root / '.arbor').exists())

    def test_cleanup_preserves_custom_hooks_and_migrates_session_hooks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / '.claude/settings.json'
            path.parent.mkdir()
            commands = ['python ctx.py guard', 'python ctx.py hook',
                        'python ctx.py session snapshot', 'python custom.py']
            path.write_text(json.dumps({'permissions': {'allow': ['Read']}, 'hooks': {
                'PreToolUse': [{'hooks': [{'type': 'command', 'command': c} for c in commands]}]
            }}))
            ctx.cleanup_legacy_hooks(root)
            result = json.loads(path.read_text())
            self.assertEqual(result['permissions'], {'allow': ['Read']})
            remaining = result['hooks']['PreToolUse'][0]['hooks']
            self.assertEqual([h['command'] for h in remaining], ['python custom.py'])
            before = path.read_bytes()
            ctx.cleanup_legacy_hooks(root)
            self.assertEqual(path.read_bytes(), before)

    def test_claude_local_settings_disable_auto_memory_and_preserve_user_data(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'settings.local.json'
            path.write_text(json.dumps({
                'autoMemoryEnabled': True,
                'permissions': {'allow': ['Read']},
            }), encoding='utf-8')
            self.assertEqual(ctx._merge_claude_local_settings(path), 'updated')
            data = json.loads(path.read_text(encoding='utf-8'))
            self.assertIs(data['autoMemoryEnabled'], False)
            self.assertEqual(data['permissions'], {'allow': ['Read']})
            self.assertEqual(set(data['hooks']),
                             {'UserPromptSubmit', 'PreCompact', 'SessionStart', 'SessionEnd'})

    def test_memory_query_does_not_fall_back_to_project_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'project.md').write_text('uniquesecret')
            self.assertEqual(ctx._retrieve(root, 'uniquesecret', 5, True), [])
