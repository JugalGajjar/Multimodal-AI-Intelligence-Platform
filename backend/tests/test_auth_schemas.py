import pytest
from pydantic import ValidationError

from app.auth.schemas import TokenResponse, UserLogin, UserRegister


class TestUserRegister:
    def test_accepts_valid(self):
        u = UserRegister(email="a@b.com", password="StrongP@ss1")

        assert u.email == "a@b.com"
        assert u.password == "StrongP@ss1"

    def test_rejects_invalid_email(self):
        with pytest.raises(ValidationError):
            UserRegister(email="not-an-email", password="StrongP@ss1")

    def test_rejects_password_too_short(self):
        with pytest.raises(ValidationError):
            UserRegister(email="a@b.com", password="Ab1!")

    def test_rejects_password_too_long(self):
        with pytest.raises(ValidationError):
            UserRegister(email="a@b.com", password="Ab1!" + "x" * 200)

    def test_rejects_weak_password(self):
        # Missing special char — the validator's PasswordError surfaces here.
        with pytest.raises(ValidationError):
            UserRegister(email="a@b.com", password="abcdefgh1A")


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
