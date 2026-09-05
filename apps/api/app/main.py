from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr, field_validator

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


class TodoCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: StrictStr

    @field_validator("title")
    @classmethod
    def canonical_title(cls, title: str) -> str:
        title = title.strip(ECMASCRIPT_TRIM_CHARS)
        if any(0xD800 <= ord(character) <= 0xDFFF for character in title):
            raise ValueError("title must not contain an unpaired surrogate")
        if not 1 <= len(title) <= 120:
            raise ValueError("title must contain 1 to 120 code points")
        return title


class TodoCompletedUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    completed: StrictBool


def create_app() -> FastAPI:
    todos: dict[UUID, Todo] = {}
    app = FastAPI(title="Expo FastAPI Todo API")

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
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Content-Type"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/todos", response_model=list[Todo])
    async def list_todos() -> list[Todo]:
        return list(todos.values())

    @app.post("/todos", response_model=Todo, status_code=201)
    async def create_todo(payload: TodoCreate) -> Todo:
        todo = Todo(id=uuid4(), title=payload.title, completed=False)
        todos[todo.id] = todo
        return todo

    @app.patch("/todos/{todo_id}", response_model=Todo)
    async def update_todo(
        todo_id: UUID,
        payload: TodoCompletedUpdate,
    ) -> Todo:
        todo = todos.get(todo_id)
        if todo is None:
            raise HTTPException(status_code=404, detail="Todo not found.")
        updated_todo = todo.model_copy(update={"completed": payload.completed})
        todos[todo_id] = updated_todo
        return updated_todo

    return app


app = create_app()
