"""Guarded database helpers, deterministic provider fixtures, and host CLI.

Only the explicitly configured ``E2E_DATABASE_URL`` target is accepted:
``postgresql+psycopg`` with database/user ``todo_e2e`` on a loopback host
and no query parameters. Passwords are only rendered into connection
arguments, never logs.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import string
import sys
from pathlib import Path
from typing import Any

import httpx
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url

from alembic import command
from app.database import create_database_engine
from app.suggestion_service import Clarification, ClarificationField

E2E_DATABASE = "todo_e2e"
E2E_USER = "todo_e2e"
E2E_DRIVER = "postgresql+psycopg"
ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
DEFAULT_API_URL = "http://127.0.0.1:8001"

FIXTURE_TITLES = ("Gather supplies", "Prepare workspace", "Complete the task")
EXPECTED_FIELD: ClarificationField = "constraints"
EXPECTED_VALUE = "Use supplies already available"


def validated_database_url(value: str) -> str:
    """Return *value* unchanged if it targets the isolated E2E database."""
    if not value or not value.strip():
        raise ValueError("E2E_DATABASE_URL must be explicitly supplied")
    try:
        url = make_url(value)
    except Exception as exc:
        raise ValueError("E2E_DATABASE_URL is not a valid database URL") from exc
    if url.drivername != E2E_DRIVER:
        raise ValueError("E2E target must use postgresql+psycopg")
    if url.database != E2E_DATABASE or url.username != E2E_USER:
        raise ValueError("E2E target must use database/user todo_e2e")
    if (url.host or "") not in ALLOWED_HOSTS:
        raise ValueError("E2E target must use a loopback host")
    if url.query:
        raise ValueError("E2E target must not carry query parameters")
    return value


def prepare_database(value: str) -> None:
    """Validate the target, verify it, then apply Alembic ``head``."""
    validated = validated_database_url(value)
    engine = create_database_engine(validated)
    try:
        with engine.begin() as connection:
            current = connection.execute(text("SELECT current_database()")).scalar_one()
            if current != E2E_DATABASE:
                raise ValueError("connected database is not the E2E target")
            config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    finally:
        engine.dispose()


async def suggestions(
    goal: str,
    config: Any,
    *,
    clarification: Clarification | None = None,
) -> tuple[str, ...]:
    """Deterministic suggestion fixture; fails visibly on bad input."""
    del goal, config
    if clarification is not None:
        if clarification.field != EXPECTED_FIELD:
            raise ValueError("E2E fixture received an unexpected clarification field")
        if clarification.value.strip() != EXPECTED_VALUE:
            raise ValueError("E2E fixture received an unexpected clarification value")
    return FIXTURE_TITLES


async def choice(
    goal: str,
    config: Any,
    *,
    transport: Any = None,
) -> ClarificationField:
    """Deterministic agent-choice fixture; always picks ``constraints``."""
    del goal, config, transport
    return EXPECTED_FIELD


def _api_url() -> str:
    return os.environ.get("E2E_API_URL", DEFAULT_API_URL)


def _sanitize_prefix(prefix: str) -> str:
    cleaned = "".join(
        ch for ch in prefix if ch.isascii() and (ch.isalnum() or ch in "_-")
    )
    return cleaned[:16] or "e2e"


def _make_credentials(prefix: str) -> tuple[str, str]:
    clean = _sanitize_prefix(prefix)
    suffix = secrets.token_hex(4)
    username = f"{clean}-{suffix}"[:32]
    alphabet = string.ascii_letters + string.digits + "_-"
    password = "".join(secrets.choice(alphabet) for _ in range(20))
    return username, password


def cmd_prepare(_args: argparse.Namespace) -> int:
    try:
        prepare_database(os.environ.get("E2E_DATABASE_URL", ""))
    except Exception as exc:  # noqa: BLE001 - CLI reports any prepare failure nonzero
        print(f"e2e.support: prepare failed: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    try:
        validated_database_url(os.environ.get("E2E_DATABASE_URL", ""))
    except ValueError as exc:
        print(f"e2e.support: seed refused: {exc}", file=sys.stderr)
        return 1
    username, password = _make_credentials(args.prefix)
    try:
        with httpx.Client(base_url=_api_url(), timeout=10.0) as client:
            response = client.post(
                "/auth/signup",
                json={"username": username, "password": password},
            )
    except httpx.HTTPError as exc:
        print(
            f"e2e.support: seed request failed: {type(exc).__name__}", file=sys.stderr
        )
        return 1
    if response.status_code != 201:
        print(
            f"e2e.support: seed signup failed with status {response.status_code}",
            file=sys.stderr,
        )
        return 1
    # codeql[py/clear-text-logging-sensitive-data]: synthetic disposable E2E
    # credentials by design (spec: fresh account per case, never real
    # credentials); this exact JSON line is the CLI contract consumed via
    # pipe by scripts/e2e-ios and the web spec, never written to logs.
    print(json.dumps({"username": username, "password": password}))
    return 0


def cmd_assert_todos(args: argparse.Namespace) -> int:
    try:
        expected_raw = json.loads(args.expected)
    except json.JSONDecodeError as exc:
        print(f"e2e.support: invalid --expected JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(expected_raw, list):
        print("e2e.support: --expected must be a JSON list", file=sys.stderr)
        return 1
    try:
        expected = sorted(
            (str(item["title"]), bool(item["completed"]))
            for item in expected_raw
            if isinstance(item, dict) and "title" in item and "completed" in item
        )
    except (KeyError, TypeError, ValueError) as exc:
        print(f"e2e.support: invalid --expected entries: {exc}", file=sys.stderr)
        return 1
    if len(expected) != len(expected_raw):
        print(
            "e2e.support: --expected entries need title and completed", file=sys.stderr
        )
        return 1
    username = os.environ.get("E2E_USERNAME", "")
    password = os.environ.get("E2E_PASSWORD", "")
    if not username or not password:
        print("e2e.support: E2E_USERNAME/E2E_PASSWORD are required", file=sys.stderr)
        return 1
    try:
        with httpx.Client(base_url=_api_url(), timeout=10.0) as client:
            login = client.post(
                "/auth/login", json={"username": username, "password": password}
            )
            if login.status_code != 200:
                print(
                    f"e2e.support: login failed with status {login.status_code}",
                    file=sys.stderr,
                )
                return 1
            token = login.json().get("token", "")
            todos = client.get("/todos", headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as exc:
        print(
            f"e2e.support: assertion request failed: {type(exc).__name__}",
            file=sys.stderr,
        )
        return 1
    if todos.status_code != 200:
        print(
            f"e2e.support: /todos returned status {todos.status_code}",
            file=sys.stderr,
        )
        return 1
    actual = sorted(
        (str(item["title"]), bool(item["completed"])) for item in todos.json()
    )
    if actual != expected:
        print(
            f"e2e.support: todo mismatch: expected {len(expected)} rows, "
            f"found {len(actual)} rows",
            file=sys.stderr,
        )
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m e2e.support")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare", help="validate the E2E target and apply migrations")
    seed = sub.add_parser("seed", help="create a fresh account and print credentials")
    seed.add_argument("--prefix", required=True)
    assertion = sub.add_parser("assert-todos", help="compare persisted todos")
    assertion.add_argument("--expected", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "prepare":
        return cmd_prepare(args)
    if args.command == "seed":
        return cmd_seed(args)
    if args.command == "assert-todos":
        return cmd_assert_todos(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
