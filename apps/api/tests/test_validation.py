import pytest
from pydantic import ValidationError

from app.main import TodoCreate


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
