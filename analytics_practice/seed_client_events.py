"""Phase 30a: deterministic synthetic client events, sent through RudderStack.

Reproduces the Phase 28b outbox seed's users and suggestion times (same md5
rule), then adds the client side: auth screen views, signup submits, a
sign-in after every signup (the app requires it), an identify per user, a tap
before each suggestion outcome, retaps, ~8% of users with no client events
(ad blockers / opt-outs), and 600 visitors who never sign up -- some of whom
stay on sign-in and come back as returning (anonymous) sign-ins. Invented
data only; remove with unseed_client.sql.

  python analytics_practice/seed_client_events.py --dry-run
  RUDDERSTACK_WRITE_KEY=... RUDDERSTACK_DATA_PLANE_URL=https://... \\
    python analytics_practice/seed_client_events.py --probe   # one event
  ... --send                                                  # everything
"""

import argparse
import base64
import hashlib
import json
import math
import os
import urllib.request
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta

USER_PREFIX = "00000000-0000-4000-8000-"
ANON_PREFIX = "00000000-0000-4000-9000-"
START = datetime(2026, 7, 27, tzinfo=UTC)
CUTOFF = datetime(2026, 9, 25, tzinfo=UTC)
USERS = 400
VISITORS = 600
BATCH = 200


def u(seed: str) -> float:
    """pg_temp.u from seed_outbox.sql: 28 bits of md5, scaled to [0, 1)."""
    return int(hashlib.md5(seed.encode()).hexdigest()[:7], 16) / 268435456.0


def md5_uuid(seed: str) -> str:
    return str(uuid.UUID(hashlib.md5(seed.encode()).hexdigest()))


def _offset(fraction: float, days: int) -> timedelta:
    return timedelta(seconds=math.floor(fraction * days * 86400))


def server_timeline() -> list[dict]:
    """The 28b seed's users, workflows and suggestion outcome times, exactly."""
    users = []
    for n in range(1, USERS + 1):
        signed_up_at = START + _offset(u(f"signup-{n}"), 60)
        suggestions = []
        if u(f"starts-{n}") < 0.7:
            started_at = signed_up_at + _offset(u(f"start-delay-{n}"), 10)
            for k in range(1, math.floor(u(f"sugg-count-{n}") * 9) + 1):
                suggestions.append(started_at + _offset(u(f"sugg-at-{n}-{k}"), 5))
        users.append({
            "n": n,
            "user_key": f"{USER_PREFIX}{n:012d}",
            "workflow_key": md5_uuid(f"hex-seed-workflow-{n}"),
            "signed_up_at": signed_up_at,
            "suggestions": suggestions,
        })
    return users


def _iso(at: datetime) -> str:
    return at.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _message(key: str, at: datetime, anonymous_id: str, *, user_id: str | None = None,
             event: str | None = None, properties: dict | None = None) -> dict:
    message = {
        "type": "track" if event else "identify",
        "messageId": md5_uuid(f"client-seed-{key}"),
        "anonymousId": anonymous_id,
        "timestamp": _iso(at),
        "originalTimestamp": _iso(at),
        "context": {"library": {"name": "phase30a-seed"}},
    }
    if user_id:
        message["userId"] = user_id
    if event:
        message["event"] = event
        message["properties"] = properties or {}
    return message


def build_events() -> list[dict]:
    events: list[dict] = []
    for user in server_timeline():
        n, signed = user["n"], user["signed_up_at"]
        if u(f"client-blocked-{n}") < 0.08 or signed >= CUTOFF:
            continue
        anon, key, workflow = f"{ANON_PREFIX}{n:012d}", user["user_key"], user["workflow_key"]
        viewed = signed - timedelta(seconds=60 + math.floor(u(f"view-lead-{n}") * 1800))
        events += [
            _message(f"view-signin-{n}", viewed, anon, event="auth_screen_viewed", properties={"mode": "signin"}),
            _message(f"view-signup-{n}", viewed + timedelta(seconds=10), anon,
                     event="auth_screen_viewed", properties={"mode": "signup"}),
            _message(f"submit-{n}", signed - timedelta(seconds=2), anon, event="signup_submitted"),
            _message(f"identify-{n}", signed + timedelta(seconds=1), anon, user_id=key),
            _message(f"signin-{n}", signed + timedelta(seconds=20), anon, user_id=key, event="signin_submitted"),
        ]
        for k, finished_at in enumerate(user["suggestions"], start=1):
            if finished_at >= CUTOFF:
                continue
            tapped = finished_at - timedelta(seconds=5 + math.floor(u(f"tap-lead-{n}-{k}") * 55))
            tap = {"workflow_key": workflow}
            if u(f"retap-{n}-{k}") < 0.10:
                events.append(_message(f"retap-{n}-{k}", tapped - timedelta(seconds=30), anon,
                                       user_id=key, event="suggestion_requested", properties=tap))
            events.append(_message(f"tap-{n}-{k}", tapped, anon, user_id=key,
                                   event="suggestion_requested", properties=tap))
    for v in range(1, VISITORS + 1):
        anon = f"{ANON_PREFIX}{100000 + v:012d}"
        viewed = START + _offset(u(f"visitor-{v}"), 60)
        events.append(_message(f"visitor-view-{v}", viewed, anon, event="auth_screen_viewed",
                               properties={"mode": "signin"}))
        if u(f"visitor-signup-{v}") < 0.5:
            events.append(_message(f"visitor-signup-{v}", viewed + timedelta(seconds=10), anon,
                                   event="auth_screen_viewed", properties={"mode": "signup"}))
            if u(f"visitor-submit-{v}") < 0.3:
                events.append(_message(f"visitor-submit-{v}", viewed + timedelta(seconds=40), anon,
                                       event="signup_submitted"))
        elif u(f"visitor-signin-{v}") < 0.4:
            # Stayed on sign-in and came back: a returning (anonymous) user.
            events.append(_message(f"visitor-signin-{v}", viewed + timedelta(seconds=30), anon,
                                   event="signin_submitted"))
    return sorted(events, key=lambda e: (e["timestamp"], e["messageId"]))


def send(events: list[dict], write_key: str, data_plane_url: str) -> None:
    # HTTP API basic auth: the write key is the username, the password is empty.
    token = base64.b64encode(f"{write_key}:".encode()).decode()
    for start in range(0, len(events), BATCH):
        request = urllib.request.Request(
            f"{data_plane_url.rstrip('/')}/v1/batch",
            data=json.dumps({"batch": events[start:start + BATCH]}).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Basic {token}"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30):
            pass  # non-2xx raises HTTPError with the status


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Phase 30a synthetic client events.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="print a summary; send nothing")
    mode.add_argument("--probe", action="store_true", help="send the first event only")
    mode.add_argument("--send", action="store_true", help="send every event")
    args = parser.parse_args(argv)
    events = build_events()
    if args.dry_run:
        names = Counter(e.get("event", e["type"]) for e in events)
        print(json.dumps({"events": len(events), "by_name": dict(sorted(names.items())),
                          "first": events[0]}, indent=2))
        return
    batch = events[:1] if args.probe else events
    send(batch, os.environ["RUDDERSTACK_WRITE_KEY"], os.environ["RUDDERSTACK_DATA_PLANE_URL"])
    print(f"sent {len(batch)} events")


if __name__ == "__main__":
    main()
