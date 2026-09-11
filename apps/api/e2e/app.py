"""Test-only FastAPI entry point for Phase 12 E2E.

Builds the real application through :func:`app.main.create_app` with both
credential-free provider seams injected, so neither path can fall back to
OpenRouter. Normal ``app.main:app`` is unchanged. Requires an explicitly
supplied ``E2E_DATABASE_URL``; never reads ``DATABASE_URL``/``TEST_DATABASE_URL``
or application ``.env`` files.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from app.database import create_database_engine, create_session_factory
from app.main import create_app
from e2e.support import choice, suggestions, validated_database_url

try:
    _database_url = validated_database_url(os.environ.get("E2E_DATABASE_URL", ""))
except ValueError as exc:
    raise RuntimeError(
        "E2E_DATABASE_URL must target the isolated todo_e2e database"
    ) from exc

_engine = create_database_engine(_database_url)
_session_factory = create_session_factory(_engine)

app = create_app(
    _session_factory,
    suggestion_callable=suggestions,
    agent_choice=choice,
)


_e2e_lifespan = app.router.lifespan_context


@asynccontextmanager
async def _lifespan_with_e2e_engine(app_):
    try:
        async with _e2e_lifespan(app_):
            yield
    finally:
        _engine.dispose()


app.router.lifespan_context = _lifespan_with_e2e_engine
