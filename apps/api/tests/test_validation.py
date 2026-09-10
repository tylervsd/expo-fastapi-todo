from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.main import (
    TodoCreate,
    TodoWorkflowActionRequest,
    TodoWorkflowStart,
    TodoWorkflowSuggestionRequest,
    UserLogin,
    UserSignup,
)
from app.passwords import hash_password, verify_password
from app.title_validation import canonicalize_title


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("  Plan birthday party  ", "Plan birthday party"),
        ("😀" * 120, "😀" * 120),
    ],
)
def test_shared_title_validation(raw: str, canonical: str) -> None:
    assert canonicalize_title(raw) == canonical


@pytest.mark.parametrize(
    "raw",
    [
        "",
        " \t\u2003",
        "😀" * 121,
        "Contains\x00Nul",
        pytest.param("\ud800", id="high-surrogate"),
        pytest.param("\udc00", id="low-surrogate"),
    ],
)
def test_shared_title_validation_rejects(raw: str) -> None:
    with pytest.raises(ValueError):
        canonicalize_title(raw)


def test_todo_create_canonicalizes_ecmascript_whitespace() -> None:
    assert TodoCreate(title="\ufeff\u2003Buy milk\u2029").title == "Buy milk"


def test_todo_create_accepts_120_emoji_code_points() -> None:
    assert TodoCreate(title="😀" * 120).title == "😀" * 120


@pytest.mark.parametrize(
    "title",
    [
        "",
        " \t\u2003",
        "😀" * 121,
        pytest.param("\ud800", id="high-surrogate"),
        pytest.param("\udc00", id="low-surrogate"),
        "Contains\x00Nul",
    ],
)
def test_todo_create_rejects_invalid_string_titles(title: str) -> None:
    with pytest.raises(ValidationError):
        TodoCreate(title=title)


@pytest.mark.parametrize("title", [42, True, None])
def test_todo_create_rejects_non_string_titles(title: object) -> None:
    with pytest.raises(ValidationError):
        TodoCreate(title=title)


@pytest.mark.parametrize("payload", [{}, {"title": "Known", "extra": "rejected"}])
def test_todo_create_rejects_missing_or_extra_fields(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        TodoCreate.model_validate(payload)


from app.main import TodoUpdate


def test_todo_update_accepts_title_only() -> None:
    assert TodoUpdate(title="Renamed").title == "Renamed"
    assert TodoUpdate(title="  Renamed  ").title == "Renamed"


def test_todo_update_accepts_completed_only() -> None:
    assert TodoUpdate(completed=True).completed is True


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"title": "Both", "completed": True},
        {"title": None},
        {"completed": None},
        {"title": None, "completed": None},
        {"title": "Known", "completed": None},
        {"title": None, "completed": True},
        {"title": 42},
        {"title": "Known", "extra": "rejected"},
        {"completed": True, "extra": False},
        {"completed": "true"},
        {"title": ""},
        {"title": "Contains\x00Nul"},
    ],
)
def test_todo_update_rejects_non_exact_single_field(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        TodoUpdate.model_validate(payload)


def test_password_hash_verifies_and_differs_per_user() -> None:
    first = hash_password("correct horse battery staple")
    second = hash_password("correct horse battery staple")

    assert first != second
    assert verify_password("correct horse battery staple", first) is True
    assert verify_password("correct horse battery staple", second) is True


def test_password_verify_rejects_wrong_password() -> None:
    assert verify_password("wrong", hash_password("right")) is False


@pytest.mark.parametrize(
    "username",
    ["ab", "x" * 33, "has space", "semi;colon", "unicodé", ""],
)
def test_user_signup_rejects_bad_usernames(username: str) -> None:
    with pytest.raises(ValidationError):
        UserSignup(username=username, password="long-enough-password")


@pytest.mark.parametrize("username", ["abc", "alice_1", "BOB-2", "x" * 32])
def test_user_signup_accepts_good_usernames(username: str) -> None:
    assert (
        UserSignup(username=username, password="long-enough-password").username
        == username
    )


@pytest.mark.parametrize(
    "password",
    [
        "short",
        "x" * 129,
        "contains\x00nul",
        pytest.param("valid\ud800-password", id="high-surrogate"),
        pytest.param("valid\udc00-password", id="low-surrogate"),
    ],
)
def test_user_signup_rejects_bad_passwords(password: str) -> None:
    with pytest.raises(ValidationError):
        UserSignup(username="alice", password=password)


@pytest.mark.parametrize(
    "password", ["valid" + chr(0xD800) + "-password", "valid" + chr(0xDC00) + "-password"]
)
def test_user_login_rejects_unpaired_surrogate_passwords(password: str) -> None:
    with pytest.raises(ValidationError):
        UserLogin(username="alice", password=password)


def test_user_signup_does_not_trim_password() -> None:
    assert (
        UserSignup(username="alice", password="  padded-password  ").password
        == "  padded-password  "
    )


def test_workflow_start_envelope_requires_request_id_and_title() -> None:
    request_id = uuid4()
    assert TodoWorkflowStart(
        request_id=request_id, title="  Plan birthday party  "
    ).title == "Plan birthday party"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"title": "Plan birthday party"},
        {"request_id": "not-a-uuid", "title": "Plan birthday party"},
        {"request_id": str(uuid4()), "title": ""},
        {"request_id": str(uuid4()), "title": "Known", "extra": 1},
    ],
)
def test_workflow_start_envelope_rejects_malformed(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        TodoWorkflowStart.model_validate(payload)


def test_workflow_suggestion_envelope_accepts_exact_shape() -> None:
    request_id = uuid4()
    envelope = TodoWorkflowSuggestionRequest.model_validate(
        {
            "request_id": str(request_id),
            "expected_revision": 2,
            "step_id": f"{uuid4()}:COLLECT_TASKS",
        }
    )
    assert envelope.request_id == request_id
    assert envelope.expected_revision == 2


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"request_id": str(uuid4()), "expected_revision": 0},
        {
            "request_id": "not-a-uuid",
            "expected_revision": 0,
            "step_id": "step",
        },
        {
            "request_id": str(uuid4()),
            "expected_revision": True,
            "step_id": "step",
        },
        {
            "request_id": str(uuid4()),
            "expected_revision": 1.5,
            "step_id": "step",
        },
        {
            "request_id": str(uuid4()),
            "expected_revision": "0",
            "step_id": "step",
        },
        {
            "request_id": str(uuid4()),
            "expected_revision": -1,
            "step_id": "step",
        },
        {
            "request_id": str(uuid4()),
            "expected_revision": 2147483648,
            "step_id": "step",
        },
        {
            "request_id": str(uuid4()),
            "expected_revision": 0,
            "step_id": "step",
            "extra": True,
        },
    ],
)
def test_workflow_suggestion_envelope_rejects_strict_shape_violations(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        TodoWorkflowSuggestionRequest.model_validate(payload)


def test_workflow_action_envelope_accepts_exact_shape() -> None:
    envelope = TodoWorkflowActionRequest.model_validate(
        {
            "request_id": str(uuid4()),
            "expected_revision": 2,
            "step_id": f"{uuid4()}:COLLECT_TASKS",
            "action": {"action": "confirm"},
        }
    )
    assert envelope.expected_revision == 2


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"expected_revision": 0, "step_id": "s", "action": {"action": "cancel"}},
        {"request_id": "not-a-uuid", "expected_revision": 0, "step_id": "s", "action": {"action": "cancel"}},
        {"request_id": "00000000-0000-0000-0000-000000000000", "expected_revision": True, "step_id": "s", "action": {"action": "cancel"}},
        {"request_id": "00000000-0000-0000-0000-000000000000", "expected_revision": 1.5, "step_id": "s", "action": {"action": "cancel"}},
        {"request_id": "00000000-0000-0000-0000-000000000000", "expected_revision": "0", "step_id": "s", "action": {"action": "cancel"}},
        {"request_id": "00000000-0000-0000-0000-000000000000", "expected_revision": -1, "step_id": "s", "action": {"action": "cancel"}},
        {"request_id": "00000000-0000-0000-0000-000000000000", "expected_revision": 2147483648, "step_id": "s", "action": {"action": "cancel"}},
        {"request_id": "00000000-0000-0000-0000-000000000000", "expected_revision": 0, "step_id": "s", "action": {"action": "cancel"}, "extra": 1},
    ],
)
def test_workflow_action_envelope_rejects_strict_shape_violations(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        TodoWorkflowActionRequest.model_validate(payload)


@pytest.mark.parametrize("model", [UserSignup, UserLogin])
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"username": "alice"},
        {"password": "x" * 12},
        {"username": "alice", "password": "x" * 12, "extra": 1},
        {"username": 1, "password": "x" * 12},
    ],
)
def test_auth_models_reject_malformed_bodies(
    model: object, payload: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)
