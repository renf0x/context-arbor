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


if __name__ == "__main__":
    unittest.main()
