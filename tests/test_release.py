"""Tests for scripts/release_smoke.py — the Phase 19 HTTP smoke contract."""

import json
import os
import re
import sys
import tempfile
import unittest
from io import BytesIO
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import release_deploy
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


class _Cloud:
    """Scripted fake for release_deploy.cloud; records every command."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.commands = []

    def __call__(self, *args):
        self.commands.append(tuple(args))
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


REL = "r123-a1-abcdef12"
ENV = {
    "CLOUD_PROJECT": "demo-proj",
    "CLOUD_REGION": "us-central1",
    "CLOUD_SERVICE": "api",
    "CLOUD_MIGRATION_JOB": "migrate",
    "CLOUD_IMAGE": "us-central1-docker.pkg.dev/demo-proj/repo/api",
    "RELEASE_ID": REL,
    "GITHUB_SHA": "0123456789abcdef0123456789abcdef01234567",
}
IMAGE = ENV["CLOUD_IMAGE"] + "@sha256:" + "ab" * 32
OTHER_IMAGE = ENV["CLOUD_IMAGE"] + "@sha256:" + "cd" * 32
PREV = "api-00001"
CAND = "api-" + REL
STABLE_URL = "https://api-example.run.app"
CAND_URL = f"https://{REL}---api-example.run.app"


def _svc(traffic, image=None):
    svc = {"status": {"url": STABLE_URL, "traffic": traffic}}
    if image is not None:
        svc["spec"] = {"template": {"spec": {"containers": [{"image": image}]}}}
    return svc


def _prod(rev):
    return {"revisionName": rev, "percent": 100}


def _tagged(rev, tag, url):
    return {"revisionName": rev, "percent": 0, "tag": tag, "url": url}


def _exec_ok():
    return {
        "metadata": {"name": "migrate-xyz"},
        "status": {"conditions": [{"type": "Completed", "status": "True"}]},
        "spec": {"template": {"spec": {"containers": [{"image": IMAGE}]}}},
    }


def _rev(image=IMAGE, name=CAND):
    return {
        "metadata": {"name": name},
        "spec": {"containers": [{"image": image}]},
    }


class DeploySequenceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.summary = os.path.join(self._tmp.name, "summary.md")
        self._env = patch.dict(
            os.environ, {**ENV, "GITHUB_STEP_SUMMARY": self.summary}
        )
        self._env.start()
        self.addCleanup(self._env.stop)
        self.addCleanup(self._tmp.cleanup)

    def _deploy(self, fake, smoke_effect):
        with (
            patch.object(release_deploy, "cloud", fake),
            patch.object(release_deploy, "smoke", side_effect=smoke_effect),
        ):
            release_deploy.deploy(IMAGE, PREV)

    def _replies_to_candidate(self):
        return [
            _svc([_prod(PREV)]),
            {},
            _exec_ok(),
            {},
            _rev(),
            _svc([_prod(PREV), _tagged(CAND, REL, CAND_URL)], image=IMAGE),
        ]

    def _assert_safe(self, commands):
        for cmd in commands:
            self.assertEqual(cmd[0], "run")
            joined = " ".join(cmd)
            for bad in (
                "downgrade",
                "terraform",
                "set-env",
                "allow-unauthenticated",
            ):
                self.assertNotIn(bad, joined)

    def _assert_ordered(self, commands):
        order = ["update", "execute", "deploy", "traffic"]
        kinds = []
        for cmd in commands:
            if cmd[1:3] == ("jobs", "update"):
                kinds.append("update")
            elif cmd[1:3] == ("jobs", "execute"):
                kinds.append("execute")
            elif cmd[1] == "deploy":
                kinds.append("deploy")
            elif "update-traffic" in cmd and any(
                a.startswith("--to-revisions=") for a in cmd
            ):
                kinds.append("traffic")
        idx = {}
        for i, kind in enumerate(kinds):
            idx.setdefault(kind, i)
        for want in order:
            self.assertIn(want, idx)
        self.assertLess(idx["update"], idx["execute"])
        self.assertLess(idx["execute"], idx["deploy"])
        self.assertLess(idx["deploy"], idx["traffic"])

    def _traffic_moves(self, commands):
        return [c for c in commands if any(
            a.startswith("--to-revisions=") for a in c
        )]

    def test_stable_smoke_failure_restores_traffic(self):
        service = ENV["CLOUD_SERVICE"]
        replies = self._replies_to_candidate() + [
            {},
            _svc([_prod(CAND)], image=IMAGE),
            {},
            _svc([_prod(PREV)], image=IMAGE),
            {},
        ]
        fake = _Cloud(replies)
        with patch.object(release_deploy, "cloud", fake):  # noqa: SIM117 - brief mandates this exact form
            with patch.object(
                release_deploy,
                "smoke",
                side_effect=[None, RuntimeError("stable failed"), None],
            ):
                with self.assertRaises(RuntimeError):
                    release_deploy.deploy(IMAGE, PREV)
        self.assertIn(
            (
                "run",
                "services",
                "update-traffic",
                service,
                "--to-revisions=" + PREV + "=100",
            ),
            fake.commands,
        )
        self._assert_safe(fake.commands)

    def test_split_traffic_stops_before_mutation(self):
        fake = _Cloud([
            _svc([
                {"revisionName": PREV, "percent": 50},
                {"revisionName": "api-00002", "percent": 50},
            ])
        ])
        with (
            patch.object(release_deploy, "cloud", fake),
            patch.object(release_deploy, "smoke") as smoke,
            self.assertRaises(RuntimeError),
        ):
            release_deploy.deploy(IMAGE, PREV)
        smoke.assert_not_called()
        self.assertEqual(len(fake.commands), 1)

    def test_empty_traffic_stops_before_mutation(self):
        fake = _Cloud([_svc([])])
        with (
            patch.object(release_deploy, "cloud", fake),
            patch.object(release_deploy, "smoke") as smoke,
            self.assertRaises(RuntimeError),
        ):
            release_deploy.deploy(IMAGE, PREV)
        smoke.assert_not_called()
        self.assertEqual(len(fake.commands), 1)

    def test_tagged_zero_traffic_entries_are_not_a_split(self):
        replies = [
            _svc([_prod(PREV), _tagged("api-old", "rold", "https://old")]),
            {},
            _exec_ok(),
            {},
            _rev(),
            _svc([_prod(PREV), _tagged(CAND, REL, CAND_URL)], image=IMAGE),
            {},
            _svc([_prod(CAND)], image=IMAGE),
            {},
        ]
        fake = _Cloud(replies)
        self._deploy(fake, [None, None])
        self._assert_ordered(fake.commands)
        self._assert_safe(fake.commands)

    def test_migration_failure_stops_before_candidate(self):
        replies = [_svc([_prod(PREV)]), {}, RuntimeError("migration boom"), {}]
        fake = _Cloud(replies)
        with (
            patch.object(release_deploy, "cloud", fake),
            patch.object(release_deploy, "smoke") as smoke,
            self.assertRaisesRegex(RuntimeError, "migration"),
        ):
            release_deploy.deploy(IMAGE, PREV)
        smoke.assert_not_called()
        self.assertFalse(any("deploy" in c for c in fake.commands))
        self.assertEqual(self._traffic_moves(fake.commands), [])

    def test_missing_candidate_url_stops_before_promotion(self):
        no_url = _svc(
            [_prod(PREV), {"revisionName": CAND, "percent": 0, "tag": REL}],
            image=IMAGE,
        )
        replies = [_svc([_prod(PREV)]), {}, _exec_ok(), {}, _rev(), no_url, {}]
        fake = _Cloud(replies)
        with (
            patch.object(release_deploy, "cloud", fake),
            patch.object(release_deploy, "smoke") as smoke,
            self.assertRaisesRegex(RuntimeError, "tag"),
        ):
            release_deploy.deploy(IMAGE, PREV)
        smoke.assert_not_called()
        self.assertEqual(self._traffic_moves(fake.commands), [])

    def test_candidate_smoke_failure_leaves_traffic(self):
        replies = self._replies_to_candidate() + [{}]
        fake = _Cloud(replies)
        with (
            patch.object(release_deploy, "cloud", fake),
            patch.object(release_deploy, "smoke", side_effect=RuntimeError("bad")),
            self.assertRaisesRegex(RuntimeError, "candidate"),
        ):
            release_deploy.deploy(IMAGE, PREV)
        self.assertEqual(self._traffic_moves(fake.commands), [])
        self._assert_safe(fake.commands)

    def test_promotion_failure_attempts_restore(self):
        replies = self._replies_to_candidate() + [
            RuntimeError("promote boom"),
            {},
            _svc([_prod(PREV)], image=IMAGE),
            {},
        ]
        fake = _Cloud(replies)
        with (
            patch.object(release_deploy, "cloud", fake),
            patch.object(release_deploy, "smoke", side_effect=[None, None]),
            self.assertRaisesRegex(RuntimeError, "promote"),
        ):
            release_deploy.deploy(IMAGE, PREV)
        moves = self._traffic_moves(fake.commands)
        self.assertEqual(len(moves), 2)
        self.assertTrue(moves[1][-1].startswith("--to-revisions=" + PREV))

    def test_restore_failure_reports_both_errors(self):
        replies = self._replies_to_candidate() + [
            {},
            _svc([_prod(CAND)], image=IMAGE),
            RuntimeError("restore boom"),
            _svc([_prod(CAND)], image=IMAGE),
            {},
        ]
        fake = _Cloud(replies)
        with (
            patch.object(release_deploy, "cloud", fake),
            patch.object(
                release_deploy,
                "smoke",
                side_effect=[None, RuntimeError("stable failed")],
            ),
            self.assertRaisesRegex(RuntimeError, "stable"),
        ):
            try:
                release_deploy.deploy(IMAGE, PREV)
            except RuntimeError as exc:
                self.assertIn("restore", str(exc))
                raise

    def test_cleanup_failure_does_not_mask_original(self):
        replies = self._replies_to_candidate() + [RuntimeError("tag gone")]
        fake = _Cloud(replies)
        with (
            patch.object(release_deploy, "cloud", fake),
            patch.object(release_deploy, "smoke", side_effect=RuntimeError("bad")),
            self.assertRaisesRegex(RuntimeError, "candidate"),
        ):
            release_deploy.deploy(IMAGE, PREV)
        with open(self.summary) as handle:
            self.assertIn("cleanup", handle.read())

    def test_success_writes_summary_and_ordering(self):
        replies = self._replies_to_candidate() + [
            {},
            _svc([_prod(CAND)], image=IMAGE),
            {},
        ]
        fake = _Cloud(replies)
        self._deploy(fake, [None, None])
        self._assert_ordered(fake.commands)
        self._assert_safe(fake.commands)
        moves = self._traffic_moves(fake.commands)
        self.assertEqual(len(moves), 1)
        self.assertTrue(moves[0][-1].startswith("--to-revisions=" + CAND))
        with open(self.summary) as handle:
            body = handle.read()
        for want in (ENV["GITHUB_SHA"][:8], "migrate-xyz", PREV, CAND, "passed"):
            self.assertIn(want, body)
        self.assertIn("sha256:", body)

    def test_restore_traffic_mismatch_is_not_reported_recovered(self):
        still_candidate = _svc([_prod(CAND)], image=IMAGE)
        replies = self._replies_to_candidate() + [
            {},
            _svc([_prod(CAND)], image=IMAGE),
            {},
            still_candidate,
            still_candidate,
            {},
        ]
        fake = _Cloud(replies)
        with (
            patch.object(release_deploy, "cloud", fake),
            patch.object(
                release_deploy,
                "smoke",
                side_effect=[None, RuntimeError("stable failed")],
            ),
            self.assertRaisesRegex(RuntimeError, "restore") as ctx,
        ):
            release_deploy.deploy(IMAGE, PREV)
        self.assertIn(CAND, str(ctx.exception))

    def test_candidate_revision_image_mismatch_stops(self):
        replies = [
            _svc([_prod(PREV)]),
            {},
            _exec_ok(),
            {},
            _rev(image=OTHER_IMAGE),
            {},
        ]
        fake = _Cloud(replies)
        with (
            patch.object(release_deploy, "cloud", fake),
            patch.object(release_deploy, "smoke") as smoke,
            self.assertRaisesRegex(RuntimeError, "image mismatch"),
        ):
            release_deploy.deploy(IMAGE, PREV)
        smoke.assert_not_called()
        self.assertEqual(self._traffic_moves(fake.commands), [])

    def test_candidate_revision_identity_mismatch_stops(self):
        replies = [
            _svc([_prod(PREV)]),
            {},
            _exec_ok(),
            {},
            _rev(name="api-stale"),
            {},
        ]
        fake = _Cloud(replies)
        with (
            patch.object(release_deploy, "cloud", fake),
            patch.object(release_deploy, "smoke") as smoke,
            self.assertRaisesRegex(RuntimeError, "not found"),
        ):
            release_deploy.deploy(IMAGE, PREV)
        smoke.assert_not_called()
        self.assertEqual(self._traffic_moves(fake.commands), [])

    def test_migration_completed_false_stops_before_candidate(self):
        failed = {
            "metadata": {"name": "migrate-xyz"},
            "status": {"conditions": [{"type": "Completed", "status": "False"}]},
            "spec": {"template": {"spec": {"containers": [{"image": IMAGE}]}}},
        }
        fake = _Cloud([_svc([_prod(PREV)]), {}, failed])
        with (
            patch.object(release_deploy, "cloud", fake),
            patch.object(release_deploy, "smoke") as smoke,
            self.assertRaisesRegex(RuntimeError, "migration execution failed"),
        ):
            release_deploy.deploy(IMAGE, PREV)
        smoke.assert_not_called()
        self.assertFalse(any("deploy" in c for c in fake.commands))
        self.assertEqual(self._traffic_moves(fake.commands), [])

    def test_migration_wrong_digest_stops_before_candidate(self):
        wrong = {
            "metadata": {"name": "migrate-xyz"},
            "status": {"conditions": [{"type": "Completed", "status": "True"}]},
            "spec": {"template": {"spec": {"containers": [{"image": OTHER_IMAGE}]}}},
        }
        replies = [_svc([_prod(PREV)]), {}, wrong]
        fake = _Cloud(replies)
        with (
            patch.object(release_deploy, "cloud", fake),
            patch.object(release_deploy, "smoke") as smoke,
            self.assertRaisesRegex(RuntimeError, "did not run"),
        ):
            release_deploy.deploy(IMAGE, PREV)
        smoke.assert_not_called()
        self.assertFalse(any("deploy" in c for c in fake.commands))
        self.assertEqual(self._traffic_moves(fake.commands), [])

    def test_invalid_digest_writes_failure_summary(self):
        fake = _Cloud([])
        with (
            patch.object(release_deploy, "cloud", fake),
            self.assertRaisesRegex(RuntimeError, "digest"),
        ):
            release_deploy.deploy("not-an-image", PREV)
        self.assertEqual(fake.commands, [])
        with open(self.summary) as handle:
            body = handle.read()
        self.assertIn("failed", body)
        self.assertIn("not reached", body)

    def test_missing_env_writes_failure_summary(self):
        del os.environ["CLOUD_SERVICE"]
        fake = _Cloud([])
        with (
            patch.object(release_deploy, "cloud", fake),
            self.assertRaisesRegex(RuntimeError, "CLOUD_SERVICE"),
        ):
            release_deploy.deploy(IMAGE, PREV)
        self.assertEqual(fake.commands, [])
        with open(self.summary) as handle:
            self.assertIn("failed", handle.read())


if __name__ == "__main__":
    unittest.main()
