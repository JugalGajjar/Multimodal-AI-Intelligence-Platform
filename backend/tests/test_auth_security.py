from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.auth.security import (
    create_access_token,
    decode_access_token,
    generate_code,
    hash_password,
    verify_password,
)
from app.core.config import settings


class TestPasswordHashing:
    def test_hash_is_not_plaintext(self):
        hashed = hash_password("secret123")

        assert hashed != "secret123"
        assert len(hashed) > 30

    def test_hash_is_salted(self):
        a = hash_password("secret123")
        b = hash_password("secret123")

        assert a != b

    def test_verify_returns_true_for_correct_password(self):
        hashed = hash_password("secret123")

        assert verify_password("secret123", hashed) is True

    def test_verify_returns_false_for_wrong_password(self):
        hashed = hash_password("secret123")

        assert verify_password("wrong", hashed) is False

    def test_verify_returns_false_for_malformed_hash(self):
        assert verify_password("secret123", "not-a-bcrypt-hash") is False


class TestJWT:
    def test_create_and_decode_round_trip(self):
        token = create_access_token("user-123")

        payload = decode_access_token(token)
        assert payload["sub"] == "user-123"
        assert "exp" in payload
        assert "iat" in payload

    def test_decode_rejects_tampered_token(self):
        token = create_access_token("user-123")
        tampered = token[:-4] + "AAAA"

        with pytest.raises(jwt.InvalidTokenError):
            decode_access_token(tampered)

    def test_decode_rejects_expired_token(self):
        token = jwt.encode(
            {
                "sub": "user-123",
                "iat": datetime.now(UTC) - timedelta(minutes=10),
                "exp": datetime.now(UTC) - timedelta(minutes=5),
            },
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )

        with pytest.raises(jwt.ExpiredSignatureError):
            decode_access_token(token)

    def test_decode_rejects_wrong_secret(self):
        token = jwt.encode(
            {"sub": "user-123", "exp": datetime.now(UTC) + timedelta(minutes=5)},
            "different-secret",
            algorithm=settings.jwt_algorithm,
        )

        with pytest.raises(jwt.InvalidSignatureError):
            decode_access_token(token)

    def test_create_respects_custom_expiry(self):
        token = create_access_token("user-123", expires_minutes=1)

        payload = decode_access_token(token)
        delta = payload["exp"] - payload["iat"]
        assert 55 <= delta <= 65


class TestGenerateCode:
    def test_default_length_8(self):
        assert len(generate_code()) == 8

    def test_custom_length(self):
        assert len(generate_code(12)) == 12

    def test_alphabet_excludes_ambiguous(self):
        # 0/O and 1/I/l are hard to tell apart in most fonts.
        for _ in range(50):
            code = generate_code(8)
            assert not any(ch in code for ch in "0O1Il")

    def test_codes_differ(self):
        seen = {generate_code() for _ in range(20)}
        assert len(seen) == 20
