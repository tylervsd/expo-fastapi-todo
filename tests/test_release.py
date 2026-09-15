"""Tests for scripts/release_smoke.py — the Phase 19 HTTP smoke contract."""

import json
import os
import re
import sys
import unittest
from io import BytesIO
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import release_smoke

BASE = "https://example.run.app"
ORIGIN = "https://expo-fastapi-todo.pages.dev"


class _Resp:
    """Minimal urlopen success response: status, headers, body."""

    def __init__(self, status, headers, body):
        self.status = status
        self.headers = dict(headers)
        self._body = body
        self.closed = False

    def read(self):
        return self._body

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _login_401():
    import urllib.error

    return urllib.error.HTTPError(
        BASE + "/auth/login", 401, "Unauthorized", {}, BytesIO(b"detail")
    )


class _FakeOpener:
    """Fake opener: pops scripted actions, records outgoing Requests."""

    def __init__(self, actions):
        self._actions = list(actions)
        self.requests = []
        self.timeouts = []
        self.responses = []

    def open(self, req, timeout=None):
        self.requests.append(req)
        self.timeouts.append(timeout)
        action = self._actions.pop(0)
        if action[0] == "raise":
            raise action[1]
        kind, status, headers, body = action
        assert kind == "respond"
        resp = _Resp(status, headers, body)
        self.responses.append(resp)
        return resp


def _run_check(actions, base_url=BASE):
    opener = _FakeOpener(actions)
    with patch.object(release_smoke, "_OPENER", opener):
        release_smoke.check(base_url)
    return opener


def _expect_check_failure(case, actions, pattern, base_url=BASE):
    opener = _FakeOpener(actions)
    try:
        with (
            patch.object(release_smoke, "_OPENER", opener),
            case.assertRaisesRegex(RuntimeError, pattern),
        ):
            release_smoke.check(base_url)
    finally:
        for action in opener._actions:
            if action[0] == "raise" and hasattr(action[1], "close"):
                action[1].close()


def _passing_actions():
    return [
        ("respond", 200, {}, b'{"status": "ok"}'),
        (
            "respond",
            200,
            {
                "Access-Control-Allow-Origin": ORIGIN,
                "Access-Control-Allow-Methods": "GET, POST, PATCH, DELETE",
                "Access-Control-Allow-Headers": "Content-Type, Authorization",
            },
            b"",
        ),
        ("raise", _login_401()),
    ]


def _set_login(actions, action):
    old = actions[2]
    actions[2] = action
    if old[0] == "raise":
        old[1].close()


def _headers_of(req):
    return {k.lower(): v for k, v in req.header_items()}


class SmokeContractTest(unittest.TestCase):
    def test_retry_exhausts_attempts(self):
        with patch.object(  # noqa: SIM117 - brief mandates this exact form
            release_smoke, "check", side_effect=RuntimeError("DB 503")
        ) as check:
            with self.assertRaises(RuntimeError):
                release_smoke.smoke(
                    "https://example.run.app", attempts=2, delay=0
                )
        self.assertEqual(check.call_count, 2)

    def test_retry_succeeds_on_second_attempt(self):
        with patch.object(
            release_smoke, "check", side_effect=[RuntimeError("flaky"), None]
        ) as check:
            release_smoke.smoke(BASE, attempts=3, delay=0)
        self.assertEqual(check.call_count, 2)

    def test_success_checks_exact_contract(self):
        opener = _run_check(_passing_actions())
        requests = opener.requests
        self.assertEqual(len(requests), 3)
        methods = [r.get_method() for r in requests]
        self.assertEqual(methods, ["GET", "OPTIONS", "POST"])
        urls = [r.full_url for r in requests]
        self.assertTrue(urls[0].endswith("/health"))
        self.assertTrue(urls[1].endswith("/auth/login"))
        self.assertTrue(urls[2].endswith("/auth/login"))
        self.assertEqual(opener.timeouts, [release_smoke.TIMEOUT] * 3)
        for resp in opener.responses:
            self.assertTrue(resp.closed)

    def test_outgoing_requests_make_no_writes(self):
        requests = _run_check(_passing_actions()).requests
        for req in requests:
            self.assertNotIn("signup", req.full_url)
            self.assertNotIn("authorization", _headers_of(req))
        login = requests[2]
        payload = json.loads(login.data.decode("utf-8"))
        self.assertEqual(set(payload), {"username", "password"})
        self.assertNotIn("email", json.dumps(payload).lower())
        self.assertIsNotNone(
            re.fullmatch(r"[A-Za-z0-9_-]{3,32}", payload["username"])
        )
        self.assertTrue(8 <= len(payload["password"]) <= 128)
        preflight = _headers_of(requests[1])
        self.assertEqual(preflight.get("origin"), ORIGIN)

    def test_wrong_health_body_fails(self):
        _expect_check_failure(
            self, [("respond", 200, {}, b'{"status": "broken"}')], "health"
        )

    def test_health_non_200_fails(self):
        import urllib.error

        err = urllib.error.HTTPError(
            BASE + "/health", 500, "Server Error", {}, BytesIO(b"oops")
        )
        _expect_check_failure(self, [("raise", err)], "health")

    def test_health_redirect_fails(self):
        actions = [("respond", 301, {"Location": "https://other.example/"}, b"")]
        _expect_check_failure(self, actions, "health")

    def test_wrong_cors_origin_fails(self):
        actions = _passing_actions()
        actions[1] = (
            "respond",
            200,
            {
                "Access-Control-Allow-Origin": "https://evil.example/",
                "Access-Control-Allow-Methods": "POST",
                "Access-Control-Allow-Headers": "content-type",
            },
            b"",
        )
        _expect_check_failure(self, actions, "[Cc][Oo][Rr][Ss]")

    def test_cors_missing_post_method_fails(self):
        actions = _passing_actions()
        actions[1] = (
            "respond",
            200,
            {
                "Access-Control-Allow-Origin": ORIGIN,
                "Access-Control-Allow-Methods": "GET",
                "Access-Control-Allow-Headers": "content-type",
            },
            b"",
        )
        _expect_check_failure(self, actions, "[Cc][Oo][Rr][Ss]")

    def test_login_401_passes(self):
        _run_check(_passing_actions())  # raises if 401 is not accepted

    def test_login_200_fails(self):
        actions = _passing_actions()
        _set_login(actions, ("respond", 200, {}, b'{"token": "x"}'))
        _expect_check_failure(self, actions, "login")

    def test_login_422_fails(self):
        import urllib.error

        actions = _passing_actions()
        _set_login(
            actions,
            (
                "raise",
                urllib.error.HTTPError(
                    BASE + "/auth/login", 422, "Unprocessable", {}, BytesIO(b"bad")
                ),
            ),
        )
        _expect_check_failure(self, actions, "login")

    def test_login_503_fails(self):
        import urllib.error

        actions = _passing_actions()
        _set_login(
            actions,
            (
                "raise",
                urllib.error.HTTPError(
                    BASE + "/auth/login", 503, "Unavailable", {}, BytesIO(b"down")
                ),
            ),
        )
        _expect_check_failure(self, actions, "login")

    def test_timeout_fails(self):
        _expect_check_failure(self, [("raise", TimeoutError("timed out"))], "health")

    def test_invalid_url_rejected(self):
        with self.assertRaises(ValueError):
            release_smoke.check("not-a-url")
        with self.assertRaises(ValueError):
            release_smoke.check("https://user:pass@example.run.app/health")

    def test_smoke_rejects_invalid_url_without_retry(self):
        with (
            patch.object(release_smoke, "check") as check,
            self.assertRaises(ValueError),
        ):
            release_smoke.smoke("not-a-url", attempts=3, delay=0)
        check.assert_not_called()

    def test_main_exit_codes(self):
        with patch.object(release_smoke, "smoke", return_value=None):
            self.assertEqual(release_smoke.main([BASE]), 0)
        with patch.object(
            release_smoke, "smoke", side_effect=RuntimeError("stable failed")
        ):
            self.assertEqual(release_smoke.main([BASE]), 1)
        self.assertEqual(release_smoke.main([]), 2)
        self.assertEqual(release_smoke.main(["not-a-url"]), 2)


if __name__ == "__main__":
    unittest.main()
