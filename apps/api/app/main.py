import re
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.orm import Session, sessionmaker

from app.auth_repository import (
    UserRow,
    create_session,
    create_user,
    delete_expired_sessions,
    delete_session,
    find_user_by_id,
    find_user_by_username,
    find_valid_session,
    generate_token,
    hash_token,
)
from app.database import (
    create_database_engine,
    create_session_factory,
    get_database_url,
)
from app.passwords import DUMMY_PASSWORD_HASH, hash_password, verify_password
from app.title_validation import canonicalize_title
from app.todo_repository import TodoRow, delete_todo, set_completed, set_title
from app.todo_repository import create_todo as create_todo_row
from app.todo_repository import list_todos as list_todo_rows
from app.workflow_domain import (
    AnswerMultipleSteps,
    Cancel,
    Confirm,
    InvalidWorkflowAction,
    SubmitTasks,
    TerminalWorkflow,
    WorkflowCommand,
    WorkflowSnapshot,
    create_submit_tasks,
)
from app.workflow_presentation import WorkflowView, present_workflow
from app.workflow_service import advance_workflow, get_workflow, start_workflow

EXPO_WEB_ORIGIN = "http://localhost:8081"


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
        return canonicalize_title(title)


def validate_username(username: str) -> str:
    if "\x00" in username or re.fullmatch(r"[A-Za-z0-9_-]{3,32}", username) is None:
        raise ValueError("username must be 3-32 letters, digits, _ or -")
    return username


def validate_password(password: str) -> str:
    if (
        "\x00" in password
        or not 8 <= len(password) <= 128
        or any(0xD800 <= ord(character) <= 0xDFFF for character in password)
    ):
        raise ValueError("password must contain 8 to 128 code points")
    return password


class UserPublic(BaseModel):
    id: UUID
    username: str


class UserSignup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: StrictStr
    password: StrictStr

    @field_validator("username")
    @classmethod
    def check_username(cls, username: str) -> str:
        return validate_username(username)

    @field_validator("password")
    @classmethod
    def check_password(cls, password: str) -> str:
        return validate_password(password)


class UserLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: StrictStr
    password: StrictStr

    @field_validator("username")
    @classmethod
    def check_username(cls, username: str) -> str:
        return validate_username(username)

    @field_validator("password")
    @classmethod
    def check_password(cls, password: str) -> str:
        return validate_password(password)


class SessionResponse(BaseModel):
    token: str
    expires_at: datetime
    user: UserPublic


class TodoWorkflowStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: StrictStr

    @field_validator("title")
    @classmethod
    def canonical_title(cls, title: str) -> str:
        return canonicalize_title(title)


class AnswerMultipleStepsAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["answer_multiple_steps"]
    answer: StrictBool


class SubmitTasksAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["submit_tasks"]
    titles: list[StrictStr]

    @field_validator("titles")
    @classmethod
    def canonical_titles(cls, titles: list[str]) -> list[str]:
        return list(create_submit_tasks(titles).titles)


class ConfirmAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["confirm"]


class CancelAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["cancel"]


TodoWorkflowAction = Annotated[
    AnswerMultipleStepsAction | SubmitTasksAction | ConfirmAction | CancelAction,
    Field(discriminator="action"),
]


class TodoWorkflowContext(BaseModel):
    involves_multiple_steps: StrictBool | None
    proposed_todo_titles: list[str]


class TodoWorkflowResult(BaseModel):
    created_todos: list[Todo]


class TodoWorkflowResponse(BaseModel):
    workflow_id: UUID
    state: str
    title: str
    context: TodoWorkflowContext
    result: TodoWorkflowResult | None
    view: TodoWorkflowView


class WorkflowChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Literal["yes", "no"]
    label: StrictStr


class YesNoWorkflowView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["yes_no"]
    step_id: StrictStr
    title: StrictStr
    question: StrictStr
    actions: list[WorkflowChoice]


class TaskBreakdownWorkflowView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["task_breakdown"]
    step_id: StrictStr
    title: StrictStr
    min_titles: StrictInt
    max_titles: StrictInt


class ReviewWorkflowView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["review"]
    step_id: StrictStr
    title: StrictStr
    proposed_titles: list[StrictStr]


class CompletionWorkflowView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["completion"]
    step_id: StrictStr
    title: StrictStr
    outcome: Literal["completed", "cancelled"]
    created_todos: list[Todo]


TodoWorkflowView = Annotated[
    YesNoWorkflowView
    | TaskBreakdownWorkflowView
    | ReviewWorkflowView
    | CompletionWorkflowView,
    Field(discriminator="type"),
]


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
        fields = self.model_fields_set
        if len(fields) != 1 or getattr(self, next(iter(fields), ""), None) is None:
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

    def as_user(row: UserRow) -> UserPublic:
        return UserPublic(id=row.public_id, username=row.username)

    def unauthorized() -> HTTPException:
        return HTTPException(status_code=401, detail="Not authenticated.")

    bearer = HTTPBearer(auto_error=False)

    def get_current_user(
        credentials: Annotated[
            HTTPAuthorizationCredentials | None, Depends(bearer)
        ],
        session: Annotated[Session, Depends(get_session)],
    ) -> UserRow:
        if credentials is None:
            raise unauthorized()
        try:
            row = find_valid_session(session, hash_token(credentials.credentials))
            user = find_user_by_id(session, row.user_id) if row else None
        except (OperationalError, SQLAlchemyTimeoutError) as exc:
            raise HTTPException(
                status_code=503, detail="Database unavailable."
            ) from exc
        if user is None:
            raise unauthorized()
        # Close the read-only transaction: todo routes own their writes via
        # `session.begin()` on this same request session, which rejects an
        # already-begun transaction. expire_on_commit=False keeps `user` loaded.
        session.commit()
        return user

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
        allow_headers=["Content-Type", "Authorization"],
    )

    @app.post("/auth/signup", response_model=UserPublic, status_code=201)
    def signup(
        payload: UserSignup, session: Annotated[Session, Depends(get_session)]
    ) -> UserPublic:
        try:
            with session.begin():
                user = as_user(
                    create_user(
                        session,
                        uuid4(),
                        payload.username,
                        hash_password(payload.password),
                    )
                )
            return user
        except IntegrityError as exc:
            raise HTTPException(status_code=422, detail="Username is taken.") from exc
        except (OperationalError, SQLAlchemyTimeoutError) as exc:
            raise HTTPException(
                status_code=503, detail="Database unavailable."
            ) from exc

    @app.post("/auth/login", response_model=SessionResponse)
    def login(
        payload: UserLogin, session: Annotated[Session, Depends(get_session)]
    ) -> SessionResponse:
        try:
            with session.begin():
                user = find_user_by_username(session, payload.username)
                password_hash = (
                    user.password_hash if user is not None else DUMMY_PASSWORD_HASH
                )
                password_valid = verify_password(payload.password, password_hash)
                if user is None or not password_valid:
                    raise HTTPException(
                        status_code=401, detail="Invalid username or password."
                    )
                token = generate_token()
                expires_at = datetime.now(UTC) + timedelta(days=30)
                create_session(session, user.id, hash_token(token), expires_at)
                delete_expired_sessions(session, user.id)
                response = SessionResponse(
                    token=token, expires_at=expires_at, user=as_user(user)
                )
            return response
        except (OperationalError, SQLAlchemyTimeoutError) as exc:
            raise HTTPException(
                status_code=503, detail="Database unavailable."
            ) from exc

    @app.post("/auth/logout", status_code=204)
    def logout(
        credentials: Annotated[
            HTTPAuthorizationCredentials | None, Depends(bearer)
        ],
        session: Annotated[Session, Depends(get_session)],
    ) -> Response:
        try:
            with session.begin():
                if credentials is not None:
                    delete_session(session, hash_token(credentials.credentials))
            return Response(status_code=204)
        except (OperationalError, SQLAlchemyTimeoutError) as exc:
            raise HTTPException(
                status_code=503, detail="Database unavailable."
            ) from exc

    @app.get("/auth/me", response_model=UserPublic)
    def read_me(user: Annotated[UserRow, Depends(get_current_user)]) -> UserPublic:
        return as_user(user)

    def as_workflow_response(snapshot: WorkflowSnapshot) -> TodoWorkflowResponse:
        view: WorkflowView = present_workflow(snapshot)
        return TodoWorkflowResponse(
            workflow_id=snapshot.id,
            state=snapshot.state.value,
            title=snapshot.title,
            context=TodoWorkflowContext(
                involves_multiple_steps=snapshot.involves_multiple_steps,
                proposed_todo_titles=list(snapshot.proposed_todo_titles),
            ),
            result=(
                TodoWorkflowResult(
                    created_todos=[
                        Todo(
                            id=item.id,
                            title=item.title,
                            completed=item.completed,
                        )
                        for item in snapshot.created_todos
                    ]
                )
                if snapshot.created_todos is not None
                else None
            ),
            view=view,
        )

    def to_domain_command(
        payload: AnswerMultipleStepsAction
        | SubmitTasksAction
        | ConfirmAction
        | CancelAction,
    ) -> WorkflowCommand:
        if isinstance(payload, AnswerMultipleStepsAction):
            return AnswerMultipleSteps(answer=payload.answer)
        if isinstance(payload, SubmitTasksAction):
            return SubmitTasks(titles=tuple(payload.titles))
        if isinstance(payload, ConfirmAction):
            return Confirm()
        return Cancel()

    def workflow_not_found() -> HTTPException:
        return HTTPException(status_code=404, detail="Todo workflow not found.")

    @app.post(
        "/todo-workflows", response_model=TodoWorkflowResponse, status_code=201
    )
    def start_todo_workflow(
        payload: TodoWorkflowStart,
        user: Annotated[UserRow, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> TodoWorkflowResponse:
        try:
            return as_workflow_response(
                start_workflow(session, user.id, payload.title)
            )
        except (OperationalError, SQLAlchemyTimeoutError) as exc:
            raise HTTPException(
                status_code=503, detail="Database unavailable."
            ) from exc

    @app.get(
        "/todo-workflows/{workflow_id}", response_model=TodoWorkflowResponse
    )
    def get_todo_workflow(
        workflow_id: UUID,
        user: Annotated[UserRow, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> TodoWorkflowResponse:
        try:
            snapshot = get_workflow(session, user.id, workflow_id)
        except (OperationalError, SQLAlchemyTimeoutError) as exc:
            raise HTTPException(
                status_code=503, detail="Database unavailable."
            ) from exc
        if snapshot is None:
            raise workflow_not_found()
        return as_workflow_response(snapshot)

    @app.post(
        "/todo-workflows/{workflow_id}/actions", response_model=TodoWorkflowResponse
    )
    def advance_todo_workflow(
        workflow_id: UUID,
        payload: TodoWorkflowAction,
        user: Annotated[UserRow, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> TodoWorkflowResponse:
        try:
            snapshot = advance_workflow(
                session, user.id, workflow_id, to_domain_command(payload)
            )
        except TerminalWorkflow as exc:
            raise HTTPException(
                status_code=409, detail="Todo workflow is already terminal."
            ) from exc
        except InvalidWorkflowAction as exc:
            raise HTTPException(
                status_code=409,
                detail="Action is not valid for the current workflow state.",
            ) from exc
        except (OperationalError, SQLAlchemyTimeoutError) as exc:
            raise HTTPException(
                status_code=503, detail="Database unavailable."
            ) from exc
        if snapshot is None:
            raise workflow_not_found()
        return as_workflow_response(snapshot)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/todos", response_model=list[Todo])
    def list_todos(
        user: Annotated[UserRow, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> list[Todo]:
        try:
            return [as_todo(row) for row in list_todo_rows(session, user.id)]
        except (OperationalError, SQLAlchemyTimeoutError) as exc:
            raise HTTPException(
                status_code=503, detail="Database unavailable."
            ) from exc

    @app.post("/todos", response_model=Todo, status_code=201)
    def create_todo(
        payload: TodoCreate,
        user: Annotated[UserRow, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> Todo:
        try:
            with session.begin():
                todo = as_todo(
                    create_todo_row(session, uuid4(), payload.title, user.id)
                )
            return todo
        except (OperationalError, SQLAlchemyTimeoutError) as exc:
            raise HTTPException(
                status_code=503, detail="Database unavailable."
            ) from exc

    @app.patch("/todos/{todo_id}", response_model=Todo)
    def update_todo(
        todo_id: UUID,
        payload: TodoUpdate,
        user: Annotated[UserRow, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> Todo:
        try:
            with session.begin():
                if payload.title is not None:
                    todo = set_title(session, todo_id, payload.title, user.id)
                else:
                    assert payload.completed is not None
                    todo = set_completed(session, todo_id, payload.completed, user.id)
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
        user: Annotated[UserRow, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> Response:
        try:
            with session.begin():
                removed = delete_todo(session, todo_id, user.id)
                if not removed:
                    raise HTTPException(status_code=404, detail="Todo not found.")
            return Response(status_code=204)
        except (OperationalError, SQLAlchemyTimeoutError) as exc:
            raise HTTPException(
                status_code=503, detail="Database unavailable."
            ) from exc

    return app


app = create_app()
