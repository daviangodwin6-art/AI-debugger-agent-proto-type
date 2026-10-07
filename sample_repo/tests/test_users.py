import pytest

from auth.users import clear, get_user, register


@pytest.fixture(autouse=True)
def empty_store():
    clear()
    yield
    clear()


def test_register_stores_user():
    register("alice@example.com", "s3cret")
    user = get_user("alice@example.com")
    assert user["email"] == "alice@example.com"
    assert user["password_hash"] != "s3cret"


def test_register_duplicate_raises():
    register("alice@example.com", "s3cret")
    with pytest.raises(ValueError):
        register("alice@example.com", "other")


def test_register_invalid_email_raises():
    with pytest.raises(ValueError):
        register("not-an-email", "s3cret")
