import json
import re
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, Protocol
from uuid import UUID, uuid4

from ag_ui.core import RunAgentInput
from ag_ui.encoder import EventEncoder
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.orm import Session, sessionmaker

from app.agent import (
    MAX_AGENT_BODY_BYTES,
    AgentValidationError,
    ChoiceCallable,
    agent_sse_body,
    choose_clarification,
    validate_run_input,
)
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
from app.suggestion_provider import (
    InvalidSuggestionOutput,
    OpenRouterConfig,
    ProviderUnavailable,
    SuggestionsNotConfigured,
    SuggestionTimeout,
    get_openrouter_config,
    request_todo_suggestions,
)
from app.suggestion_service import (
    Clarification,
    ClarificationField,
    InvalidStoredSuggestion,
    InvalidSuggestionState,
    StaleSuggestion,
    SuggestionErrorCode,
    SuggestionInProgress,
    SuggestionSnapshot,
    SuggestionStatus,
    finish_suggestion,
    get_current_suggestion,
    normalize_clarification,
    reserve_suggestion,
)
from app.title_validation import canonicalize_title
from app.todo_repository import TodoRow, delete_todo, set_completed, set_title
from app.todo_repository import create_todo as create_todo_row
from app.todo_repository import list_todos as list_todo_rows
from app.workflow_domain import (
    MAX_WORKFLOW_REVISION,
    AnswerMultipleSteps,
    Cancel,
    Confirm,
    InvalidWorkflowAction,
    SubmitTasks,
    TerminalWorkflow,
    UnsupportedWorkflowDefinition,
    WorkflowCommand,
    WorkflowSnapshot,
    create_submit_tasks,
)
from app.workflow_presentation import WorkflowView, present_workflow
from app.workflow_repository import InvalidStoredSnapshot
from app.workflow_service import (
    RequestIdReused,
    RevisionExhausted,
    StaleWorkflowStep,
    advance_workflow,
    get_workflow,
    list_active_workflows,
    start_workflow,
)

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


class SuggestionClarification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: ClarificationField
    value: StrictStr

    @model_validator(mode="after")
    def canonical_clarification(self) -> SuggestionClarification:
        try:
            canonical = normalize_clarification(
                Clarification(self.field, self.value)
            )
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        self.value = canonical.value
        return self


class TodoWorkflowSuggestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    expected_revision: StrictInt = Field(ge=0, le=MAX_WORKFLOW_REVISION)
    step_id: StrictStr
    clarification: SuggestionClarification | None = None


class TodoWorkflowSuggestionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal[1]
    workflow_id: UUID
    request_id: UUID
    base_revision: StrictInt
    step_id: StrictStr
    status: SuggestionStatus
    proposed_titles: list[StrictStr]
    error_code: SuggestionErrorCode | None


class TodoWorkflowStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
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


class TodoWorkflowActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    expected_revision: StrictInt = Field(ge=0, le=MAX_WORKFLOW_REVISION)
    step_id: StrictStr
    action: TodoWorkflowAction


class TodoWorkflowContext(BaseModel):
    involves_multiple_steps: StrictBool | None
    proposed_todo_titles: list[str]


class TodoWorkflowResult(BaseModel):
    created_todos: list[Todo]


class TodoWorkflowResponse(BaseModel):
    workflow_id: UUID
    revision: StrictInt
    definition_version: StrictInt
    view_contract_version: Literal[1]
    state: str
    title: str
    context: TodoWorkflowContext
    result: TodoWorkflowResult | None
    view: TodoWorkflowView


class TodoWorkflowList(BaseModel):
    items: list[TodoWorkflowResponse]


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


class SuggestionCallable(Protocol):
    async def __call__(
        self,
        goal: str,
        config: OpenRouterConfig,
        *,
        clarification: Clarification | None = None,
    ) -> tuple[str, ...]: ...


def create_app(
    session_factory: sessionmaker[Session] | None = None,
    suggestion_callable: SuggestionCallable | None = None,
    agent_choice: ChoiceCallable | None = None,
) -> FastAPI:
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
    suggestion_runner: SuggestionCallable = (
        suggestion_callable or request_todo_suggestions
    )
    agent_chooser: ChoiceCallable = agent_choice or choose_clarification

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
            revision=snapshot.revision,
            definition_version=snapshot.definition_version,
            view_contract_version=1,
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

    def workflow_conflict(code: str, message: str) -> HTTPException:
        return HTTPException(status_code=409, detail={"code": code, "message": message})

    def database_unavailable() -> HTTPException:
        return HTTPException(status_code=503, detail="Database unavailable.")

    def as_suggestion_response(
        snapshot: SuggestionSnapshot,
    ) -> TodoWorkflowSuggestionResponse:
        return TodoWorkflowSuggestionResponse(
            contract_version=1,
            workflow_id=snapshot.workflow_id,
            request_id=snapshot.request_id,
            base_revision=snapshot.base_revision,
            step_id=snapshot.step_id,
            status=snapshot.status,
            proposed_titles=list(snapshot.proposed_titles),
            error_code=snapshot.error_code,
        )

    def suggestion_failure(error_code: SuggestionErrorCode) -> HTTPException:
        if error_code is SuggestionErrorCode.NOT_CONFIGURED:
            status_code = 503
            message = "Todo suggestions are not configured."
        elif error_code is SuggestionErrorCode.TIMEOUT:
            status_code = 504
            message = "Todo suggestions timed out."
        elif error_code is SuggestionErrorCode.INVALID_OUTPUT:
            status_code = 502
            message = "Todo suggestions returned invalid output."
        else:
            status_code = 502
            message = "Todo suggestion provider is unavailable."
        return HTTPException(
            status_code=status_code,
            detail={"code": error_code.value, "message": message},
        )

    def suggestion_conflict(code: str, message: str) -> HTTPException:
        return workflow_conflict(code, message)

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
                start_workflow(session, user.id, payload.title, payload.request_id)
            )
        except RequestIdReused as exc:
            raise workflow_conflict(
                "request_id_reused",
                "This request ID was already used with different details.",
            ) from exc
        except InvalidStoredSnapshot as exc:
            raise database_unavailable() from exc
        except (OperationalError, SQLAlchemyTimeoutError) as exc:
            raise HTTPException(
                status_code=503, detail="Database unavailable."
            ) from exc

    @app.get("/todo-workflows", response_model=TodoWorkflowList)
    def list_todo_workflows(
        user: Annotated[UserRow, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
        status: Literal["active"] = "active",
    ) -> TodoWorkflowList:
        del status
        try:
            return TodoWorkflowList(
                items=[
                    as_workflow_response(snapshot)
                    for snapshot in list_active_workflows(session, user.id)
                ]
            )
        except UnsupportedWorkflowDefinition as exc:
            raise workflow_conflict(
                "unsupported_workflow_definition",
                "This plan uses an unsupported workflow definition.",
            ) from exc
        except InvalidStoredSnapshot as exc:
            raise database_unavailable() from exc
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
        except UnsupportedWorkflowDefinition as exc:
            raise workflow_conflict(
                "unsupported_workflow_definition",
                "This plan uses an unsupported workflow definition.",
            ) from exc
        except (OperationalError, SQLAlchemyTimeoutError) as exc:
            raise HTTPException(
                status_code=503, detail="Database unavailable."
            ) from exc
        if snapshot is None:
            raise workflow_not_found()
        return as_workflow_response(snapshot)

    @app.post(
        "/todo-workflows/{workflow_id}/suggestions",
        response_model=TodoWorkflowSuggestionResponse,
        status_code=201,
    )
    async def suggest_todo_workflow(
        workflow_id: UUID,
        payload: TodoWorkflowSuggestionRequest,
        user: Annotated[UserRow, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> TodoWorkflowSuggestionResponse | JSONResponse:
        try:
            clarification = (
                Clarification(
                    payload.clarification.field, payload.clarification.value
                )
                if payload.clarification is not None
                else None
            )
            reservation = reserve_suggestion(
                session,
                user.id,
                workflow_id,
                payload.request_id,
                payload.expected_revision,
                payload.step_id,
                clarification=clarification,
            )
        except RequestIdReused as exc:
            raise suggestion_conflict(
                "request_id_reused",
                "This request ID was already used with different details.",
            ) from exc
        except SuggestionInProgress as exc:
            raise suggestion_conflict(
                "suggestion_in_progress",
                "A suggestion request is already in progress.",
            ) from exc
        except StaleSuggestion as exc:
            raise suggestion_conflict(
                "stale_suggestion",
                "This suggestion request is no longer current.",
            ) from exc
        except StaleWorkflowStep as exc:
            raise suggestion_conflict(
                "stale_step",
                "This plan changed. Reload it and try again.",
            ) from exc
        except InvalidSuggestionState as exc:
            raise suggestion_conflict(
                "invalid_state",
                "Suggestions are only available while collecting todo titles.",
            ) from exc
        except UnsupportedWorkflowDefinition as exc:
            raise suggestion_conflict(
                "unsupported_workflow_definition",
                "This plan uses an unsupported workflow definition.",
            ) from exc
        except InvalidStoredSuggestion as exc:
            raise database_unavailable() from exc
        except (OperationalError, SQLAlchemyTimeoutError) as exc:
            raise database_unavailable() from exc

        if reservation is None:
            raise workflow_not_found()
        if isinstance(reservation, SuggestionSnapshot):
            if reservation.status is SuggestionStatus.FAILED:
                assert reservation.error_code is not None
                raise suggestion_failure(reservation.error_code)
            response = as_suggestion_response(reservation)
            return JSONResponse(
                status_code=200, content=jsonable_encoder(response.model_dump())
            )

        # The injected callable is a credential-free test seam. The real
        # provider resolves configuration only after reservation, so a replay
        # above never consults environment configuration or calls OpenRouter.
        try:
            config = (
                get_openrouter_config()
                if suggestion_callable is None
                else OpenRouterConfig(api_key="", model="")
            )
        except SuggestionsNotConfigured:
            error_code = SuggestionErrorCode.NOT_CONFIGURED
            titles: tuple[str, ...] | None = None
        else:
            # Without clarification the legacy two-argument seam is retained so
            # Phase 10 callables keep working; the keyword is only used when
            # a clarification was supplied.
            try:
                if reservation.clarification is None:
                    titles = await suggestion_runner(reservation.goal, config)
                else:
                    titles = await suggestion_runner(
                        reservation.goal,
                        config,
                        clarification=reservation.clarification,
                    )
                error_code = None
            except SuggestionTimeout:
                titles = None
                error_code = SuggestionErrorCode.TIMEOUT
            except ProviderUnavailable:
                titles = None
                error_code = SuggestionErrorCode.PROVIDER_UNAVAILABLE
            except InvalidSuggestionOutput:
                titles = None
                error_code = SuggestionErrorCode.INVALID_OUTPUT
            except SuggestionsNotConfigured:
                titles = None
                error_code = SuggestionErrorCode.NOT_CONFIGURED
            except Exception:  # noqa: BLE001 - isolate provider failures
                # Do not expose provider details or leave an unknown failure
                # as a permanently pending request.
                titles = None
                error_code = SuggestionErrorCode.PROVIDER_UNAVAILABLE

        # Keep reservation, provider work, and finalization in distinct
        # transactions. This also closes any read transaction opened by a
        # dependency before the second short transaction begins.
        session.rollback()
        try:
            if error_code is not None:
                finished = finish_suggestion(
                    session,
                    user.id,
                    workflow_id,
                    payload.request_id,
                    titles=None,
                    error_code=error_code,
                )
            else:
                assert titles is not None
                try:
                    finished = finish_suggestion(
                        session,
                        user.id,
                        workflow_id,
                        payload.request_id,
                        titles=tuple(titles),
                        error_code=None,
                    )
                except StaleSuggestion:
                    raise
                except (TypeError, ValueError):
                    finished = finish_suggestion(
                        session,
                        user.id,
                        workflow_id,
                        payload.request_id,
                        titles=None,
                        error_code=SuggestionErrorCode.INVALID_OUTPUT,
                    )
                    error_code = SuggestionErrorCode.INVALID_OUTPUT
        except StaleSuggestion as exc:
            raise suggestion_conflict(
                "stale_suggestion",
                "This suggestion request is no longer current.",
            ) from exc
        except InvalidStoredSuggestion as exc:
            raise database_unavailable() from exc
        except (OperationalError, SQLAlchemyTimeoutError) as exc:
            raise database_unavailable() from exc

        if finished is None:
            raise workflow_not_found()
        if error_code is not None:
            raise suggestion_failure(error_code)
        return as_suggestion_response(finished)

    @app.get(
        "/todo-workflows/{workflow_id}/suggestions",
        response_model=TodoWorkflowSuggestionResponse,
    )
    def get_todo_workflow_suggestion(
        workflow_id: UUID,
        user: Annotated[UserRow, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> TodoWorkflowSuggestionResponse:
        try:
            snapshot = get_current_suggestion(session, user.id, workflow_id)
        except UnsupportedWorkflowDefinition as exc:
            raise suggestion_conflict(
                "unsupported_workflow_definition",
                "This plan uses an unsupported workflow definition.",
            ) from exc
        except InvalidStoredSuggestion as exc:
            raise database_unavailable() from exc
        except (OperationalError, SQLAlchemyTimeoutError) as exc:
            raise database_unavailable() from exc
        if snapshot is None:
            raise workflow_not_found()
        return as_suggestion_response(snapshot)

    @app.post("/agent")
    async def run_agent(
        request: Request,
        user: Annotated[UserRow, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> StreamingResponse:
        raw_body = await request.body()
        if len(raw_body) > MAX_AGENT_BODY_BYTES:
            raise HTTPException(
                status_code=413, detail="Agent request body is too large."
            )
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise HTTPException(
                status_code=422, detail="Agent request body must be JSON."
            ) from None
        try:
            run_input = RunAgentInput.model_validate(payload)
        except ValidationError as exc:
            raise HTTPException(
                status_code=422, detail="Agent request is malformed."
            ) from exc
        try:
            validate_run_input(run_input)
        except AgentValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        encoder = EventEncoder()

        async def stream() -> AsyncIterator[str]:
            async for chunk in agent_sse_body(
                run_input,
                user.id,
                session,
                choose=agent_chooser,
                is_disconnected=request.is_disconnected,
            ):
                yield chunk

        return StreamingResponse(stream(), media_type=encoder.get_content_type())

    @app.post(
        "/todo-workflows/{workflow_id}/actions", response_model=TodoWorkflowResponse
    )
    def advance_todo_workflow(
        workflow_id: UUID,
        payload: TodoWorkflowActionRequest,
        user: Annotated[UserRow, Depends(get_current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> TodoWorkflowResponse:
        try:
            snapshot = advance_workflow(
                session,
                user.id,
                workflow_id,
                to_domain_command(payload.action),
                request_id=payload.request_id,
                expected_revision=payload.expected_revision,
                step_id=payload.step_id,
            )
        except RequestIdReused as exc:
            raise workflow_conflict(
                "request_id_reused",
                "This request ID was already used with different details.",
            ) from exc
        except StaleWorkflowStep as exc:
            raise workflow_conflict(
                "stale_step",
                "This plan changed. Reload it and try again.",
            ) from exc
        except TerminalWorkflow as exc:
            raise workflow_conflict(
                "terminal_workflow", "Todo workflow is already terminal."
            ) from exc
        except InvalidWorkflowAction as exc:
            raise workflow_conflict(
                "invalid_action",
                "Action is not valid for the current workflow state.",
            ) from exc
        except UnsupportedWorkflowDefinition as exc:
            raise workflow_conflict(
                "unsupported_workflow_definition",
                "This plan uses an unsupported workflow definition.",
            ) from exc
        except RevisionExhausted as exc:
            raise workflow_conflict(
                "revision_exhausted", "This plan has reached its revision limit."
            ) from exc
        except InvalidStoredSnapshot as exc:
            raise database_unavailable() from exc
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
