from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.database import (
    create_database_engine,
    create_session_factory,
    get_database_url,
)

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+psycopg://todo_test:todo_test@127.0.0.1:5433/todo_test"
)
REVISION = "2026090601"


def get_test_database_url() -> URL:
    url = make_url(os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL))
    development_url = make_url(get_database_url())
    if (
        url.query
        or url.drivername != "postgresql+psycopg"
        or url.database != "todo_test"
        or url == development_url
    ):
        raise RuntimeError("TEST_DATABASE_URL must target the isolated todo_test database")
    return url


@pytest.fixture(scope="session")
def database_engine() -> Iterator[Engine]:
    url = get_test_database_url()
    engine = create_database_engine(url.render_as_string(hide_password=False))
    config = Config(Path(__file__).parents[1] / "alembic.ini")
    try:
        with engine.begin() as connection:
            assert connection.execute(text("SELECT current_database()")).scalar_one() == "todo_test"
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def session_factory(database_engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(database_engine)


@pytest.fixture
def database_session(
    database_engine: Engine, session_factory: sessionmaker[Session]
) -> Iterator[Session]:
    with database_engine.begin() as connection:
        connection.execute(text("TRUNCATE todos RESTART IDENTITY"))
    with session_factory() as session:
        yield session
        session.rollback()
