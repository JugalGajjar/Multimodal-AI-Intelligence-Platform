import pytest
from pydantic import ValidationError

from app.auth.schemas import TokenResponse, UserLogin, UserRegister


def _reg(**overrides):
    """Build a valid UserRegister with overrides for one-field test cases."""
    defaults = {
        "email": "a@b.com",
        "password": "StrongP@ss1",
        "first_name": "Jane",
        "last_name": "Doe",
    }
    return UserRegister(**{**defaults, **overrides})


class TestUserRegister:
    def test_accepts_valid(self):
        u = _reg()

        assert u.email == "a@b.com"
        assert u.password == "StrongP@ss1"
        assert u.first_name == "Jane"
        assert u.last_name == "Doe"

    def test_rejects_invalid_email(self):
        with pytest.raises(ValidationError):
            _reg(email="not-an-email")

    def test_rejects_password_too_short(self):
        with pytest.raises(ValidationError):
            _reg(password="Ab1!")

    def test_rejects_password_too_long(self):
        with pytest.raises(ValidationError):
            _reg(password="Ab1!" + "x" * 200)

    def test_rejects_weak_password(self):
        with pytest.raises(ValidationError):
            _reg(password="abcdefgh1A")

    def test_rejects_blank_first_name(self):
        with pytest.raises(ValidationError):
            _reg(first_name="")

    def test_rejects_blank_last_name(self):
        with pytest.raises(ValidationError):
            _reg(last_name="")

    def test_rejects_first_name_too_long(self):
        with pytest.raises(ValidationError):
            _reg(first_name="x" * 101)


class TestUserLogin:
    def test_accepts_valid(self):
        u = UserLogin(email="a@b.com", password="x")

        assert u.email == "a@b.com"

    def test_rejects_invalid_email(self):
        with pytest.raises(ValidationError):
            UserLogin(email="bad", password="x")

    def test_empty_password_rejected(self):
        with pytest.raises(ValidationError):
            UserLogin(email="a@b.com", password="")


class TestTokenResponse:
    def test_defaults_to_bearer(self):
        t = TokenResponse(access_token="abc")

        assert t.token_type == "bearer"
