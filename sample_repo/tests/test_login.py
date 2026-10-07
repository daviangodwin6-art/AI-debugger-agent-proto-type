import pytest

from auth.login import login
from auth.users import clear, register


@pytest.fixture(autouse=True)
def empty_store():
    clear()
    yield
    clear()


def test_login_succeeds_with_correct_password():
    register("alice@example.com", "s3cret")
    assert login("alice@example.com", "s3cret") is True


def test_login_fails_with_wrong_password():
    register("alice@example.com", "s3cret")
    assert login("alice@example.com", "wrong") is False


def test_login_fails_for_unknown_user():
    assert login("bob@example.com", "s3cret") is False
