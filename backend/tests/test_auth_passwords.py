import pytest

from app.auth.passwords import MAX_LEN, MIN_LEN, PasswordError, validate_password


class TestValidatePassword:
    def test_strong_password_passes(self):
        validate_password("StrongP@ss1")

    def test_too_short(self):
        with pytest.raises(PasswordError, match="between"):
            validate_password("Ab1!cde")  # 7 chars

    def test_too_long(self):
        with pytest.raises(PasswordError, match="between"):
            validate_password("Ab1!" + "x" * MAX_LEN)

    def test_missing_lower(self):
        with pytest.raises(PasswordError, match="lowercase"):
            validate_password("ABCD1234!")

    def test_missing_upper(self):
        with pytest.raises(PasswordError, match="uppercase"):
            validate_password("abcd1234!")

    def test_missing_digit(self):
        with pytest.raises(PasswordError, match="digit"):
            validate_password("AbcdEfg!")

    def test_missing_special(self):
        with pytest.raises(PasswordError, match="special"):
            validate_password("Abcd1234")

    def test_rejects_mmap(self):
        with pytest.raises(PasswordError, match="mmap"):
            validate_password("MmapPass1!")

    def test_rejects_multimodal(self):
        with pytest.raises(PasswordError, match="multimodal"):
            validate_password("Multimodal9!")

    def test_rejects_full_email(self):
        with pytest.raises(PasswordError, match="email"):
            validate_password("Hi-alice@x.io-1A!", email="alice@x.io")

    def test_rejects_email_local_part(self):
        with pytest.raises(PasswordError, match="email"):
            validate_password("AliceWonder1!", email="alicewonder@x.io")

    def test_short_local_part_does_not_block(self):
        # Two-letter local-parts like "al" are too common to block in passwords.
        validate_password("Wonder1Land!", email="al@x.io")

    def test_boundary_minimum_length_ok(self):
        assert MIN_LEN == 8
        validate_password("Ab1!cdEf")  # exactly 8
