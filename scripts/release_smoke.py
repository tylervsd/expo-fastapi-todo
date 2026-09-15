"""Phase 19 deployment smoke contract (stdlib only).

Checks, in order: GET /health returns 200 with {"status": "ok"}; a CORS
preflight from the deployed web app allows POST with content-type; an invalid
POST /auth/login returns exactly 401 (database reached, no test data needed).
"""

import json
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 10
ORIGIN = "https://expo-fastapi-todo.pages.dev"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _validate_base(base_url):
    parts = urllib.parse.urlsplit(base_url)
    if parts.username is not None or parts.password is not None:
        raise ValueError("URL must not contain userinfo")
    if parts.scheme == "https":
        if not parts.hostname:
            raise ValueError("invalid URL")
        return parts._replace(path="", query="", fragment="").geturl().rstrip("/")
    if parts.scheme == "http" and parts.hostname in (
        "localhost",
        "127.0.0.1",
        "::1",
    ):
        return parts._replace(path="", query="", fragment="").geturl().rstrip("/")
    raise ValueError("URL must be https or a loopback http URL")


def _header(headers, name):
    value = headers.get(name)
    if value is None:
        value = headers.get(name.lower())
    return value


def _send(req, endpoint):
    try:
        resp = _OPENER.open(req, timeout=TIMEOUT)
        return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.headers or {}, exc.read()
        finally:
            exc.close()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"{endpoint} request failed: {exc}") from exc


def _check_health(base):
    req = urllib.request.Request(base + "/health", method="GET")
    status, _headers, body = _send(req, "health")
    if status != 200:
        raise RuntimeError(f"health check failed: HTTP {status}")
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError("health check failed: invalid JSON") from exc
    if parsed != {"status": "ok"}:
        raise RuntimeError("health check failed: unexpected body")


def _check_cors(base):
    req = urllib.request.Request(
        base + "/auth/login",
        method="OPTIONS",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    status, headers, _body = _send(req, "CORS preflight")
    if status != 200:
        raise RuntimeError(f"CORS preflight failed: HTTP {status}")
    if _header(headers, "Access-Control-Allow-Origin") != ORIGIN:
        raise RuntimeError("CORS preflight failed: unexpected allow-origin")
    methods = (_header(headers, "Access-Control-Allow-Methods") or "").upper()
    if "POST" not in [m.strip() for m in methods.split(",")]:
        raise RuntimeError("CORS preflight failed: POST not allowed")
    allowed = (_header(headers, "Access-Control-Allow-Headers") or "").lower()
    if "content-type" not in [h.strip() for h in allowed.split(",")]:
        raise RuntimeError("CORS preflight failed: content-type not allowed")


def _check_login(base):
    username = "smoke-" + secrets.token_hex(6)
    password = secrets.token_hex(16)
    data = json.dumps({"username": username, "password": password}).encode("utf-8")
    req = urllib.request.Request(
        base + "/auth/login",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    status, _headers, _body = _send(req, "login")
    if status != 401:
        raise RuntimeError(f"login probe failed: HTTP {status}")


def check(base_url: str) -> None:
    """Run one full check set against base_url; raise on any failure."""
    base = _validate_base(base_url)
    _check_health(base)
    _check_cors(base)
    _check_login(base)


def smoke(base_url: str, *, attempts: int = 12, delay: float = 5) -> None:
    """Retry check() until one set passes or attempts are exhausted."""
    if not isinstance(attempts, int) or attempts < 1:
        raise ValueError("attempts must be a positive integer")
    if delay < 0:
        raise ValueError("delay must be non-negative")
    _validate_base(base_url)
    error = None
    for attempt in range(attempts):
        try:
            check(base_url)
            return
        except RuntimeError as exc:
            error = exc
            if attempt < attempts - 1 and delay:
                time.sleep(delay)
    raise error  # type: ignore[misc]


def main(argv):
    if len(argv) != 1:
        print("usage: release_smoke.py BASE_URL", file=sys.stderr)
        return 2
    try:
        smoke(argv[0])
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"smoke failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
