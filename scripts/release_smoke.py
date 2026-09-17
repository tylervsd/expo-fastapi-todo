"""Phase 19 deployment smoke contract (stdlib only).

Checks, in order: GET /health returns 200 with {"status": "ok"}; a CORS
preflight from the deployed web app allows POST with content-type; an invalid
POST /auth/login returns exactly 401 (database reached, no test data needed).

Phase 20 adds an authenticated private worker smoke: GET /health and
GET /ready against verified worker URLs with a short-lived ID token minted
for the canonical root audience by the permitted invocation account. The
token is held in memory, masked in Actions before any other output, and
never appears in logs, summaries, exception messages, or command arguments.
"""

import json
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 10
WORKER_TOKEN_TIMEOUT = 60
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
        with _OPENER.open(req, timeout=TIMEOUT) as resp:
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


def _validate_worker_audience(audience: str) -> str:
    """Return the canonical root worker URL used as the ID-token audience.

    Tagged candidate URLs carry a `<tag>---` hostname prefix and must never
    be used as the audience; the token is always minted for the stable root.
    """
    parts = urllib.parse.urlsplit(audience)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("worker audience must be an https URL")
    if "---" in (parts.hostname or ""):
        raise ValueError("worker audience must be the canonical root URL")
    if parts.username is not None or parts.password is not None:
        raise ValueError("worker audience must not contain userinfo")
    return parts._replace(path="", query="", fragment="").geturl().rstrip("/")


def _acquire_worker_token(audience: str, invoker: str) -> str:
    """Mint a short-lived ID token via impersonation; hold it in memory.

    The token is masked in Actions before any other output and is never
    included in exception messages, logs, or command arguments.
    """
    if not invoker or "@" not in invoker:
        raise ValueError("invoker must be a service account email")
    audience = _validate_worker_audience(audience)
    cmd = [
        "gcloud",
        "auth",
        "print-identity-token",
        "--impersonate-service-account=" + invoker,
        "--audiences=" + audience,
        "--include-email",
        "--quiet",
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=WORKER_TOKEN_TIMEOUT, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "worker identity token acquisition timed out"
        ) from exc
    except OSError as exc:
        raise RuntimeError(
            "worker identity token acquisition failed"
        ) from exc
    if proc.returncode != 0:
        raise RuntimeError("worker identity token acquisition failed")
    token = proc.stdout.strip()
    if not token or any(char.isspace() for char in token):
        raise RuntimeError("worker identity token acquisition failed")
    print(f"::add-mask::{token}", flush=True)
    return token


def _validate_worker_url(url: str, audience: str) -> str:
    """Return the normalized worker base URL bound to the audience origin.

    Only the canonical audience origin itself or a Cloud Run tagged
    hostname (`<tag>---<canonical-host>`) derived from it is allowed, so
    an audience-scoped token is never sent to an unrelated host.
    """
    canonical = _validate_worker_audience(audience)
    aud = urllib.parse.urlsplit(canonical)
    base = _validate_base(url)
    parts = urllib.parse.urlsplit(base)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("worker URL must be an https URL")
    aud_host = (aud.hostname or "").lower()
    url_host = (parts.hostname or "").lower()
    if (parts.port or 443) != (aud.port or 443):
        raise ValueError("worker URL does not match worker audience")
    if url_host == aud_host:
        return base
    suffix = "---" + aud_host
    if url_host.endswith(suffix):
        prefix = url_host[: -len(suffix)]
        if prefix and "." not in prefix:
            return base
    raise ValueError("worker URL does not match worker audience")


def _worker_get(base: str, endpoint: str, token: str) -> None:
    req = urllib.request.Request(
        base + endpoint,
        method="GET",
        headers={"Authorization": "Bearer " + token},
    )
    status, _headers, body = _send(req, f"worker {endpoint}")
    if status != 200:
        raise RuntimeError(f"worker {endpoint} check failed: HTTP {status}")
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError(
            f"worker {endpoint} check failed: invalid JSON"
        ) from exc
    if parsed != {"status": "ok"}:
        raise RuntimeError(f"worker {endpoint} check failed: unexpected body")


def check_worker(url: str, audience: str, invoker: str) -> None:
    """Check private worker /health and /ready with an ID token.

    The URL and audience are verified before any token is minted, and the
    Authorization header is only ever sent to the verified worker URL.
    """
    base = _validate_worker_url(url, audience)
    token = _acquire_worker_token(audience, invoker)
    _worker_get(base, "/health", token)
    _worker_get(base, "/ready", token)


def smoke_worker(url: str, audience: str, invoker: str, *,
                 attempts: int = 12, delay: float = 5) -> None:
    """Retry check_worker() until one set passes or attempts run out."""
    if not isinstance(attempts, int) or attempts < 1:
        raise ValueError("attempts must be a positive integer")
    if delay < 0:
        raise ValueError("delay must be non-negative")
    _validate_worker_url(url, audience)
    error = None
    for attempt in range(attempts):
        try:
            check_worker(url, audience, invoker)
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
