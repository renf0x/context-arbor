import ast
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipIf(sys.version_info < (3, 12), "older interpreters reject the file outright")
class SourceCompatibilityTests(unittest.TestCase):
    """The package declares Python >= 3.10. Since 3.12 an f-string may reuse its own quote
    character or contain a backslash inside `{...}`; 3.10 and 3.11 cannot even import such a
    file. Development happens on newer Pythons, so this is the only place the mistake shows."""

    def test_f_string_expressions_stay_valid_on_python_310(self):
        for name in ("arbor.py", "install.py"):
            source = (ROOT / name).read_text(encoding="utf-8")
            unsafe = []
            for node in ast.walk(ast.parse(source)):
                if not isinstance(node, ast.JoinedStr):
                    continue
                segment = ast.get_source_segment(source, node)
                if not segment or segment[0] not in "fF":
                    continue
                quote = segment[1:4] if segment[1:4] in ('"""', "'''") else segment[1]
                for part in node.values:
                    if isinstance(part, ast.FormattedValue):
                        expression = ast.get_source_segment(source, part.value) or ""
                        if quote in expression or chr(92) in expression:
                            unsafe.append(f"{name}:{node.lineno}: {expression[:60]}")
            self.assertEqual(unsafe, [])

    def test_no_syntax_newer_than_the_declared_minimum(self):
        for name in ("arbor.py", "install.py"):
            source = (ROOT / name).read_text(encoding="utf-8")
            ast.parse(source, feature_version=(3, 10))


if __name__ == "__main__":
    unittest.main()
