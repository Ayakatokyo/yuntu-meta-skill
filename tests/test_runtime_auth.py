import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

import requests

from scripts import collector


class RuntimeAuthTests(unittest.TestCase):
    inherited = {
        "ENV_BACKEND_HOST": "https://wrong.example/api",
        "YUCE_AUTHORIZATION": "old-auth",
        "YCSESSIONID": "old-cookie",
        "YUCE_SESSION_ID": "old-session",
    }
    explicit = {
        "ENV_BACKEND_HOST": "https://requested.example/api",
        "YUCE_AUTHORIZATION": "new-auth",
        "YCSESSIONID": "new-cookie",
    }

    def run_cli(self, args, payload=None, response=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        session = mock.Mock()
        if response is None:
            response = requests.Response()
            response.status_code = 200
            response._content = b'{"success":true,"code":"200","data":[]}'
        session.post.return_value = response
        with mock.patch.dict(os.environ, self.inherited, clear=True), \
                mock.patch.object(collector.sys, "stdin", io.StringIO(json.dumps(payload) + "\n")), \
                mock.patch.object(collector, "_default_session", return_value=session), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                status = collector.main(args)
            except SystemExit as exc:
                status = exc.code
            self.assertEqual(dict(os.environ), self.inherited)
        return status, stdout.getvalue(), stderr.getvalue(), session

    def test_explicit_config_replaces_stale_environment_in_actual_request(self):
        status, out, err, session = self.run_cli(
            ["--runtime-config-stdin", "list-accounts"], self.explicit
        )
        self.assertEqual(status, 0, err)
        self.assertTrue(json.loads(out)["success"])
        self.assertEqual(session.post.call_args.args[0],
                         "https://requested.example/api/adg/v1/agent/rpa/authorizations/query")
        self.assertEqual(session.post.call_args.kwargs["json"]["authorization"], "new-auth")
        self.assertEqual(session.post.call_args.kwargs["cookies"], {"YCSESSIONID": "new-cookie"})
        self.assertIn("stdin", err)
        self.assertIn("https://requested.example/api", err)
        for secret in ("new-auth", "new-cookie", "old-session", "old-auth", "old-cookie"):
            self.assertNotIn(secret, out + err)

    def test_incomplete_explicit_config_never_borrows_old_credentials(self):
        status, out, err, session = self.run_cli(
            ["--runtime-config-stdin", "list-accounts"],
            {"ENV_BACKEND_HOST": "https://requested.example/api"},
        )
        self.assertEqual(status, 2)
        self.assertIn("YUCE_AUTHORIZATION", err)
        session.post.assert_not_called()

    def test_expected_gateway_mismatch_blocks_request(self):
        status, out, err, session = self.run_cli(
            ["--expected-gateway", "https://requested.example/api", "list-accounts"]
        )
        self.assertEqual(status, 2)
        self.assertIn("gateway mismatch", err)
        session.post.assert_not_called()

    def test_runtime_check_is_offline_and_shows_inherited_source(self):
        status, out, err, session = self.run_cli(["runtime-check"])
        self.assertEqual(status, 0, err)
        self.assertEqual(json.loads(out)["gateway"], "https://wrong.example/api")
        self.assertEqual(json.loads(out)["source"], "environment")
        session.post.assert_not_called()

    def test_cli_pipe_reads_config_and_keeps_credentials_out_of_output(self):
        result = subprocess.run(
            [sys.executable, str(Path(collector.__file__)), "--runtime-config-stdin", "runtime-check"],
            input=json.dumps(self.explicit) + "\n", capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["source"], "stdin")
        self.assertEqual(json.loads(result.stdout)["gateway"], "https://requested.example/api")
        self.assertNotIn("new-auth", result.stdout + result.stderr)
        self.assertNotIn("new-cookie", result.stdout + result.stderr)

    def test_invalid_runtime_payload_is_rejected_without_echo_or_network(self):
        for payload in [[], {**self.explicit, "secret-extra-key": "secret-extra-value"},
                        {**self.explicit, "YCSESSIONID": 123}]:
            with self.subTest(payload_type=type(payload).__name__):
                status, out, err, session = self.run_cli(["--runtime-config-stdin", "list-accounts"], payload)
                self.assertEqual(status, 2)
                self.assertNotIn("secret-extra", out + err)
                self.assertNotIn("new-auth", out + err)
                session.post.assert_not_called()

    def test_http_and_business_auth_failures_keep_evidence_without_claiming_yuntu_login(self):
        for http_status, body, category in [
            (200, {"success": False, "code": "500", "msg": "鉴权失败：用户未登录", "traceId": "trace-123"}, "authentication_failed"),
            (401, {"status": 401, "code": 11, "message": "token已过期", "data": None}, "credential_expired"),
        ]:
            with self.subTest(http_status=http_status):
                response = requests.Response()
                response.status_code = http_status
                response._content = json.dumps(body).encode()
                status, out, err, _ = self.run_cli(["list-accounts"], response=response)
                self.assertEqual(status, 2)
                self.assertIn(category, err)
                self.assertIn(str(http_status), err)
                self.assertIn(str(body["code"]), err)
                self.assertIn("https://wrong.example/api", err)
                if "traceId" in body:
                    self.assertIn("trace-123", err)
                self.assertNotIn("local runtime is not logged in", err)

    def test_batch_submission_and_poll_use_same_explicit_config(self):
        session = mock.Mock()
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"success":true,"data":{"task_group_id":"tg-1","status":"completed"}}'
        session.post.return_value = response
        with mock.patch.dict(os.environ, self.inherited, clear=True), \
                mock.patch.object(collector, "_default_session", return_value=session), \
                mock.patch.object(collector.time, "sleep"):
            invoker = collector._batch_invoker(environ=self.explicit)
            invoker.invoke_list("shop-1", {})
            task = invoker.submit_detail("shop-1", {"material_id": "101", "date_type": "LAST_7_DAYS"})
            invoker.wait_detail(task)
        self.assertEqual(len(session.post.call_args_list), 3)
        for call in session.post.call_args_list:
            self.assertTrue(call.args[0].startswith("https://requested.example/api/"))
            self.assertEqual(call.kwargs["cookies"], {"YCSESSIONID": "new-cookie"})
            self.assertEqual(call.kwargs["json"]["authorization"], "new-auth")
        self.assertEqual(session.post.call_args_list[1].kwargs["json"]["agent_session_id"], "new-cookie")


if __name__ == "__main__":
    unittest.main()
