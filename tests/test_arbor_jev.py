import argparse
import contextlib
import http.client
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

import arbor as ctx


KEY = "sk-or-v1-" + "a1b2c3d4" * 8

DECISIONS = """# Decision Log

## DEC-20260901-001 Headless Godot never runs next to the editor

- Status: active
- Date: 2026-09-01
- Decision: Close the editor before headless runs.

## DEC-20260902-002 Quality presets

- Status: active
- Date: 2026-09-02
- Decision: Three presets.
"""


class JevBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "memory").mkdir()
        (self.root / "memory" / "decisions.md").write_text(DECISIONS, encoding="utf-8")
        self.secrets = self.root / "secrets"
        env = {"ARBOR_SECRETS_DIR": str(self.secrets)}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        os.environ.pop("OPENROUTER_API_KEY", None)
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)


@unittest.skipUnless(sys.platform == "win32", "DPAPI is Windows-only")
class DpapiStoreTest(JevBase):
    def test_key_round_trips_and_is_not_stored_in_plain_text(self):
        self.assertEqual(ctx.jev_key_store(KEY), "dpapi")
        blob = (self.secrets / "context-arbor" / "openrouter.dpapi").read_bytes()
        self.assertNotIn(KEY.encode(), blob)
        self.assertNotIn(KEY.encode("utf-16-le"), blob)
        self.assertEqual(ctx.jev_key_load(), KEY)
        ctx.jev_key_clear()
        self.assertEqual(ctx.jev_key_load(), "")


class KeySourceTest(JevBase):
    def test_environment_key_wins_and_no_backend_refuses_plain_storage(self):
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": KEY, "ARBOR_SECRETS_BACKEND": "none"}):
            self.assertEqual(ctx.jev_key_load(), KEY)
            with self.assertRaises(OSError):
                ctx.jev_key_store(KEY)
        self.assertFalse(self.secrets.exists())


class HookInstallTest(JevBase):
    def test_on_adds_hook_once_and_off_removes_only_it(self):
        settings = self.root / ".claude" / "settings.local.json"
        settings.parent.mkdir()
        other = {"type": "command", "command": "echo mine"}
        settings.write_text(json.dumps({"hooks": {"UserPromptSubmit": [{"hooks": [other]}]}}), encoding="utf-8")
        ctx.jev_enable(self.root, True)
        ctx.jev_enable(self.root, True)
        groups = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["UserPromptSubmit"]
        commands = [h["command"] for g in groups for h in g["hooks"]]
        self.assertEqual(commands.count(ctx._hook_command(ctx.JEV_HOOK_ARGS)), 1)
        self.assertTrue(ctx._jev_config(self.root)["enabled"])
        ctx.jev_enable(self.root, False)
        groups = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["UserPromptSubmit"]
        self.assertEqual([h["command"] for g in groups for h in g["hooks"]], ["echo mine"])
        self.assertFalse(ctx._jev_config(self.root)["enabled"])


class HookRunTest(JevBase):
    def run_hook(self, prompt="почему падает headless"):
        stdin = io.StringIO(json.dumps({"prompt": prompt}))
        out = io.StringIO()
        with mock.patch.object(ctx, "_read_hook_event", return_value=json.load(stdin)), \
                contextlib.redirect_stdout(out):
            code = ctx.cmd_jev(argparse.Namespace(jev_cmd="hook", path=str(self.root)))
        self.assertEqual(code, 0)
        return out.getvalue()

    def answers(self, *_args):
        return {"n0": {"noul": 0.6}, "n1": {"noul": 0.1}}, {"cost": 0.0004}

    def test_silent_when_off_or_without_key(self):
        with mock.patch.object(ctx, "_jev_request", side_effect=AssertionError("no call")):
            self.assertEqual(self.run_hook(), "")
            ctx.jev_enable(self.root, True)
            self.assertEqual(self.run_hook(), "")

    def test_injects_matched_note_and_logs_without_prompt_or_key(self):
        ctx.jev_enable(self.root, True)
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": KEY}), \
                mock.patch.object(ctx, "_jev_request", side_effect=self.answers):
            out = json.loads(self.run_hook("секретный запрос"))
        context = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Headless Godot never runs", context)
        self.assertNotIn("Quality presets", context)
        log = (self.root / ctx.JEV_LOG_PATH).read_text(encoding="utf-8")
        self.assertNotIn("секретный", log)
        self.assertNotIn(KEY, log)

    def test_daily_cap_stops_calls_and_errors_stay_silent(self):
        ctx.jev_enable(self.root, True)
        ctx._jev_log(self.root, {"t": ctx.datetime.datetime.now().isoformat(), "cost": 5.0})
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": KEY}), \
                mock.patch.object(ctx, "_jev_request", side_effect=AssertionError("no call")):
            self.assertEqual(self.run_hook(), "")
        (self.root / ctx.JEV_LOG_PATH).unlink()
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": KEY}), \
                mock.patch.object(ctx, "_jev_request", side_effect=TimeoutError("slow")):
            self.assertEqual(self.run_hook(), "")


class UiTest(JevBase):
    def test_static_page_shows_status_but_no_form(self):
        data = ctx._ui_collect(self.root, "demo", "ru")
        data["jev"] = ctx.jev_status(self.root)
        page = ctx.render_ui(data)
        self.assertIn('id="jev"', page)
        self.assertNotIn("<form", page)
        self.assertNotIn("form-action", page)

    def test_post_actions(self):
        with mock.patch.object(ctx, "jev_key_store") as store:
            self.assertEqual(ctx._ui_post(self.root, {"action": ["save_key"], "key": ["nope"]}), "bad_key")
            store.assert_not_called()
            self.assertEqual(ctx._ui_post(self.root, {"action": ["save_key"], "key": [f" {KEY} "]}), "saved")
            store.assert_called_once_with(KEY)
        self.assertEqual(ctx._ui_post(self.root, {"action": ["on"]}), "on")
        self.assertTrue(ctx._jev_config(self.root)["enabled"])


class ServerTest(JevBase):
    def setUp(self):
        super().setUp()
        self.served = {}
        import http.server

        class Capturing(http.server.ThreadingHTTPServer):
            def __init__(inner, *a, **kw):
                super().__init__(*a, **kw)
                self.served["server"] = inner

        self.patch = mock.patch("http.server.ThreadingHTTPServer", Capturing)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        args = argparse.Namespace(title="demo", lang="en", port=0, open=False)
        with contextlib.redirect_stdout(io.StringIO()):
            self.thread = threading.Thread(target=ctx._ui_serve, args=(self.root, args), daemon=True)
            self.thread.start()
            for _ in range(200):
                if "server" in self.served:
                    break
                threading.Event().wait(0.02)
        self.server = self.served["server"]
        self.port = self.server.server_address[1]
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, body=None, host=None, origin=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Host": host or f"127.0.0.1:{self.port}"}
        if origin:
            headers["Origin"] = origin
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        return resp.status, resp.read().decode("utf-8", "replace"), resp.getheader("Location")

    def token(self):
        status, page, _ = self.request("GET", "/")
        self.assertEqual(status, 200)
        start = page.index('name="token" value="') + len('name="token" value="')
        return page[start:page.index('"', start)]

    def test_guards_and_key_never_echoed(self):
        self.assertEqual(self.request("GET", "/", host="evil.example:80")[0], 403)
        token = self.token()
        form = urllib.parse.urlencode({"token": token, "action": "save_key", "key": KEY})
        self.assertEqual(self.request("POST", "/jev", form, origin="http://evil.example")[0], 403)
        bad = urllib.parse.urlencode({"token": "x", "action": "save_key", "key": KEY})
        self.assertEqual(self.request("POST", "/jev", bad)[0], 403)
        with mock.patch.object(ctx, "jev_key_store") as store, \
                mock.patch.object(ctx, "jev_key_load", return_value=KEY):
            status, _body, location = self.request("POST", "/jev", form, origin=f"http://127.0.0.1:{self.port}")
            self.assertEqual((status, location), (303, "/?m=saved#jev"))
            store.assert_called_once_with(KEY)
            _status, page, _ = self.request("GET", location.split("#")[0])
        self.assertNotIn(KEY, page)
        self.assertIn(KEY[-4:], page)
        self.assertIn("form-action 'self'", page)
        self.assertIn("Key stored encrypted.", page)


ASK_DECISION = """
## DEC-20260905-003 Retry limit of the label printer is 5

- Status: active
- Date: 2026-09-05
- Decision: Raise the retry limit to 5.
- Relations: caused-by:BUG-20260801-002
"""

ARCHIVED_BUG = """# Bugs 2026

## BUG-20260801-002 Label printer drops jobs under load

- Status: closed
- Date: 2026-08-01
- Cause: Retry limit 2 was too low.
"""

QUESTION = "почему поменяли лимит повторов принтера"


class FakeJev:
    """Stands in for `_jev_call`: probabilities from substrings of each instruction."""

    def __init__(self, scores, cost=0.0001):
        self.scores, self.cost, self.calls = scores, cost, []
        self.lock = threading.Lock()

    def __call__(self, request, instructions, criteria, key, config):
        with self.lock:
            self.calls.append((request, list(instructions), criteria))
        probs = [next((p for needle, p in self.scores if needle in text), 0.05) for text in instructions]
        return probs, self.cost


class AskBase(JevBase):
    def setUp(self):
        super().setUp()
        memory = self.root / "memory"
        with (memory / "decisions.md").open("a", encoding="utf-8") as fh:
            fh.write(ASK_DECISION)
        (memory / "archive").mkdir()
        (memory / "archive" / "bugs-2026.md").write_text(ARCHIVED_BUG, encoding="utf-8")
        (memory / "templates").mkdir()
        (memory / "templates" / "decision.md").write_text("## DEC-20260101-001 Never asked\n", encoding="utf-8")
        (memory / "MEMORY.md").write_text("# Index\n\n## Notes\n\n- decisions.md\n", encoding="utf-8")
        (memory / "NOW.md").write_text("# Now\n\n## TASK-YYYYMMDD-NNN Short title\n\n- Status: open\n",
                                       encoding="utf-8")
        ctx.jev_enable(self.root, True)
        patcher = mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": KEY})
        patcher.start()
        self.addCleanup(patcher.stop)

    def log(self):
        path = self.root / ctx.JEV_LOG_PATH
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.is_file() else []

    def cli(self, question, **flags):
        args = argparse.Namespace(jev_cmd="ask", path=str(self.root), question=question, code=False,
                                  show=False, top=5, dir=None, json=False)
        for name, value in flags.items():
            setattr(args, name, value)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = ctx.cmd_jev(args)
        return code, out.getvalue()


class DecideTest(AskBase):
    def test_questions_go_in_chunks_answers_keep_their_order_and_costs_add_up(self):
        sizes = []

        def call(request, instructions, criteria, key, config):
            sizes.append(len(instructions))
            return [int(text[1:]) / 1000 for text in instructions], 0.0001

        with mock.patch.object(ctx, "_jev_call", side_effect=call):
            probs, cost, requests = ctx._jev_decide("r", [f"q{i}" for i in range(130)], {}, KEY,
                                                    {"model": "m", "timeout": 1})
        self.assertEqual(requests, 3)
        self.assertEqual(sorted(sizes), [10, 60, 60])
        self.assertEqual(probs, [i / 1000 for i in range(130)])
        self.assertAlmostEqual(cost, 0.0003)


class AskMemoryTest(AskBase):
    def test_whole_vault_is_asked_and_relations_lead_into_the_archive(self):
        fake = FakeJev([("Retry limit of the label printer", 0.9)])
        with mock.patch.object(ctx, "_jev_call", side_effect=fake):
            res = ctx.jev_ask_memory(self.root, QUESTION, 5, show=False)
        asked = " ".join(text for _req, texts, _crit in fake.calls for text in texts)
        self.assertIn("Label printer drops jobs", asked)  # archived sections are asked too
        self.assertNotIn("Never asked", asked)            # templates are not
        self.assertNotIn('"Notes"', asked)                # nor the MEMORY.md index
        self.assertNotIn("YYYYMMDD", asked)               # nor placeholder sections
        self.assertTrue(res["jev"])
        first = res["notes"][0]
        self.assertEqual((first["source"], first["id"], first["p"]), ("jev", "DEC-20260905-003", 0.9))
        self.assertEqual(first["links"], [{"dir": "out", "type": "caused-by", "id": "BUG-20260801-002",
                                           "title": "BUG-20260801-002 Label printer drops jobs under load",
                                           "path": "memory/archive/bugs-2026.md"}])
        record = self.log()[-1]
        self.assertEqual((record["source"], record["kind"]), ("ask", "memory"))
        self.assertEqual(record["picked"], ["DEC-20260905-003 Retry limit of the label printer is 5"])
        self.assertNotIn("принтера", json.dumps(record, ensure_ascii=False))
        self.assertNotIn(KEY, json.dumps(record))

    def test_show_prints_the_pick_then_its_linked_entry_within_the_bounds(self):
        fake = FakeJev([("Retry limit of the label printer", 0.9)])
        with mock.patch.object(ctx, "_jev_call", side_effect=fake):
            res = ctx.jev_ask_memory(self.root, QUESTION, 5, show=True)
            self.assertEqual([b["heading"][:16] for b in res["bodies"]][:2],
                             ["DEC-20260905-003", "BUG-20260801-002"])
            self.assertIn("Retry limit 2 was too low", res["bodies"][1]["body"])
            with mock.patch.object(ctx, "JEV_SHOW_CHARS", 60):
                res = ctx.jev_ask_memory(self.root, QUESTION, 5, show=True)
        self.assertEqual(len(res["bodies"]), 1)
        self.assertTrue(res["bodies"][0]["body"].endswith(" ..."))
        self.assertLessEqual(len(res["bodies"][0]["body"]), 64)
        self.assertGreaterEqual(res["left_out"], 1)

    def test_text_and_json_output(self):
        fake = FakeJev([("Retry limit of the label printer", 0.9)])
        with mock.patch.object(ctx, "_jev_call", side_effect=fake):
            code, text = self.cli(QUESTION)
            self.assertEqual(code, 0)
            self.assertIn("1 of 4 sections matched (Jev", text)
            self.assertIn("[jev 0.90]", text)
            self.assertIn("-> caused-by BUG-20260801-002 Label printer drops jobs under load "
                          "(memory/archive/bugs-2026.md)", text)
            code, raw = self.cli(QUESTION, json=True)
        self.assertEqual(json.loads(raw)["notes"][0]["id"], "DEC-20260905-003")

    def test_off_no_key_cap_or_error_fall_back_to_words(self):
        never = mock.patch.object(ctx, "_jev_call", side_effect=AssertionError("no call"))
        ctx.jev_enable(self.root, False)
        with never:
            res = ctx.jev_ask_memory(self.root, "retry limit printer", 5, show=False)
            self.assertFalse(res["jev"])
            self.assertIn("off", res["reason"])
            self.assertEqual(res["notes"][0]["source"], "words")
            self.assertEqual(self.cli("ничего такого")[0], 1)  # nothing at all, Jev did not run
        ctx.jev_enable(self.root, True)
        with never, mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}), \
                mock.patch.object(ctx, "jev_key_load", return_value=""):
            self.assertIn("no key", ctx.jev_ask_memory(self.root, QUESTION, 5, False)["reason"])
        ctx._jev_log(self.root, {"t": ctx.datetime.datetime.now().isoformat(), "cost": 5.0})
        with never:
            self.assertEqual(ctx.jev_ask_memory(self.root, QUESTION, 5, False)["reason"], "daily cap reached")
        (self.root / ctx.JEV_LOG_PATH).unlink()
        with mock.patch.object(ctx, "_jev_call", side_effect=TimeoutError("slow")):
            res = ctx.jev_ask_memory(self.root, "retry limit printer", 5, show=False)
        self.assertTrue(res["failed"])
        self.assertTrue(res["notes"])
        self.assertIn("TimeoutError", self.log()[-1]["error"])


class AskCodeTest(AskBase):
    def setUp(self):
        super().setUp()
        files = {
            "pkg/net.py": '"""Network helpers."""\n\n\ndef open_socket(host):\n    """Open a TCP socket."""\n'
                          '    return host\n\n\ndef close_socket(sock):\n    """Close it."""\n    return sock\n',
            "pkg/store.py": '"""Storage."""\n\n\nclass Store:\n    """Key-value store."""\n\n'
                            '    def put(self, key, value):\n        """Save a value."""\n        return key\n',
            "conf/app.json": '{"port": 8080}\n',
            "tests/test_net.py": "def test_open():\n    pass\n",
        }
        for rel, text in files.items():
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text(text, encoding="utf-8")

    def test_files_first_then_symbols_of_the_top_three(self):
        fake = FakeJev([("file `pkg/net.py`", 0.9), ("file `conf/app.json`", 0.6),
                        ("file `pkg/store.py`", 0.5), ("`open_socket` in", 0.95)])
        with mock.patch.object(ctx, "_jev_call", side_effect=fake):
            res = ctx.jev_ask_code(self.root, "где открывается сокет", 5, show=True)
        hop1, hop2 = fake.calls[0][1], fake.calls[1][1]
        self.assertIn("`tests/test_net.py`", hop1[-1])  # tests are asked last
        self.assertEqual(fake.calls[0][2], ctx.JEV_CODE_CRITERIA)
        self.assertEqual(len(hop2), 4)  # open_socket, close_socket, Store, Store.put
        self.assertEqual([f["path"] for f in res["top_files"]], ["pkg/net.py", "conf/app.json", "pkg/store.py"])
        first = res["hits"][0]
        self.assertEqual((first["source"], first["path"], first["symbol"], first["p"]),
                         ("jev", "pkg/net.py", "open_socket", 0.95))
        self.assertIn({"source": "jev", "path": "conf/app.json", "kind": "file", "summary": "", "p": 0.6},
                      res["hits"])  # a top file without symbols is a hit by itself
        self.assertIn("4|def open_socket(host):", res["bodies"][0]["body"])
        record = self.log()[-1]
        self.assertEqual((record["source"], record["kind"], record["requests"]), ("ask-code", "code", 2))
        files = len(ctx._code_index(self.root, refresh=False)[0]["files"])
        self.assertEqual(record["questions"], files + 4)
        self.assertNotIn("сокет", json.dumps(record, ensure_ascii=False))

    def test_text_output_points_at_code_show(self):
        fake = FakeJev([("file `pkg/net.py`", 0.9), ("`open_socket` in", 0.95)])
        with mock.patch.object(ctx, "_jev_call", side_effect=fake):
            code, text = self.cli("где открывается сокет", code=True)
        self.assertEqual(code, 0)
        self.assertIn("- [jev 0.95] pkg/net.py:4  function  open_socket - Open a TCP socket.", text)
        self.assertIn("# read one: python arbor.py code show pkg/net.py:open_socket", text)

    def test_without_jev_the_lexical_index_answers_and_dir_narrows(self):
        ctx.jev_enable(self.root, False)
        with mock.patch.object(ctx, "_jev_call", side_effect=AssertionError("no call")):
            res = ctx.jev_ask_code(self.root, "open socket", 5, show=False)
            self.assertEqual((res["hits"][0]["source"], res["hits"][0]["symbol"]), ("words", "open_socket"))
            self.assertEqual(ctx.jev_ask_code(self.root, "open socket", 5, False, prefix="pkg/store")["hits"], [])
            code, text = self.cli("сокет", code=True)
        self.assertEqual(code, 1)
        self.assertIn("Jev did not run", text)


if __name__ == "__main__":
    unittest.main()
