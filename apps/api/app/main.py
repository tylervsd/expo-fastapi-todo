from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import (
    BaseModel,
    ConfigDict,
    StrictBool,
    StrictStr,
    field_validator,
    model_validator,
)
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.orm import Session, sessionmaker

from app.database import (
    create_database_engine,
    create_session_factory,
    get_database_url,
)
from app.todo_repository import TodoRow, delete_todo, set_completed, set_title
from app.todo_repository import create_todo as create_todo_row
from app.todo_repository import list_todos as list_todo_rows

EXPO_WEB_ORIGIN = "http://localhost:8081"
ECMASCRIPT_TRIM_CHARS = (
    "\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680"
    "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000\ufeff"
)


class Todo(BaseModel):
    id: UUID
    title: str
    completed: bool


def canonicalize_title(title: str) -> str:
    title = title.strip(ECMASCRIPT_TRIM_CHARS)
    if "\x00" in title:
        raise ValueError("title must not contain NUL")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in title):
        raise ValueError("title must not contain an unpaired surrogate")
    if not 1 <= len(title) <= 120:
        raise ValueError("title must contain 1 to 120 code points")
    return title


class TodoCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: StrictStr

    @field_validator("title")
    @classmethod
    def canonical_title(cls, title: str) -> str:
        return canonicalize_title(title)


class TodoUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: StrictStr | None = None
    completed: StrictBool | None = None

    @field_validator("title")
    @classmethod
    def canonical_title(cls, title: StrictStr | None) -> StrictStr | None:
        if title is None:
            return None
        return canonicalize_title(title)

    @model_validator(mode="after")
    def require_exactly_one_field(self) -> TodoUpdate:
        if (self.title is None) == (self.completed is None):
            raise ValueError("exactly one of title or completed is required")
        return self


def create_app(session_factory: sessionmaker[Session] | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine: Engine | None = None
        factory = session_factory
        if factory is None:
            engine = create_database_engine(get_database_url())
            factory = create_session_factory(engine)
        app.state.session_factory = factory
        try:
            yield
        finally:
            if engine is not None:
                engine.dispose()

    app = FastAPI(title="Expo FastAPI Todo API", lifespan=lifespan)

    def get_session() -> Iterator[Session]:
        with app.state.session_factory() as session:
            yield session

    def as_todo(row: TodoRow) -> Todo:
        return Todo(id=row.public_id, title=row.title, completed=row.completed)

    def escape_surrogates(value: Any) -> Any:
        if isinstance(value, str):
            return value.encode("utf-8", "backslashreplace").decode("utf-8")
        if isinstance(value, list):
            return [escape_surrogates(item) for item in value]
        if isinstance(value, dict):
            return {
                escape_surrogates(key): escape_surrogates(item)
                for key, item in value.items()
            }
        return value

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        del request
        detail = escape_surrogates(jsonable_encoder(exc.errors()))
        return JSONResponse(status_code=422, content={"detail": detail})

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[EXPO_WEB_ORIGIN],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/todos", response_model=list[Todo])
    def list_todos(session: Annotated[Session, Depends(get_session)]) -> list[Todo]:
        try:
            return [as_todo(row) for row in list_todo_rows(session)]
        except (OperationalError, SQLAlchemyTimeoutError) as exc:
            raise HTTPException(
                status_code=503, detail="Database unavailable."
            ) from exc

    @app.post("/todos", response_model=Todo, status_code=201)
    def create_todo(
        payload: TodoCreate,
        session: Annotated[Session, Depends(get_session)],
    ) -> Todo:
        try:
            with session.begin():
                todo = as_todo(create_todo_row(session, uuid4(), payload.title))
            return todo
        except (OperationalError, SQLAlchemyTimeoutError) as exc:
            raise HTTPException(
                status_code=503, detail="Database unavailable."
            ) from exc

    @app.patch("/todos/{todo_id}", response_model=Todo)
    def update_todo(
        todo_id: UUID,
        payload: TodoUpdate,
        session: Annotated[Session, Depends(get_session)],
    ) -> Todo:
        try:
            with session.begin():
                if payload.title is not None:
                    todo = set_title(session, todo_id, payload.title)
                else:
                    assert payload.completed is not None
                    todo = set_completed(session, todo_id, payload.completed)
                if todo is None:
                    raise HTTPException(status_code=404, detail="Todo not found.")
                updated_todo = as_todo(todo)
            return updated_todo
        except (OperationalError, SQLAlchemyTimeoutError) as exc:
            raise HTTPException(
                status_code=503, detail="Database unavailable."
            ) from exc

    @app.delete("/todos/{todo_id}", status_code=204)
    def remove_todo(
        todo_id: UUID,
        session: Annotated[Session, Depends(get_session)],
    ) -> Response:
        try:
            with session.begin():
                removed = delete_todo(session, todo_id)
                if not removed:
                    raise HTTPException(status_code=404, detail="Todo not found.")
            return Response(status_code=204)
        except (OperationalError, SQLAlchemyTimeoutError) as exc:
            raise HTTPException(
                status_code=503, detail="Database unavailable."
            ) from exc

    return app


app = create_app()
