import os

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DEFAULT_DATABASE_URL = "postgresql+psycopg://todo:todo@127.0.0.1:5432/todo"


class Base(DeclarativeBase):
    pass


def get_database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def create_database_engine(url: str) -> Engine:
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_timeout=3,
        connect_args={"connect_timeout": 3},
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
