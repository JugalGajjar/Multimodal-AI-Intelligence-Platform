import pytest

from app.documents.validation import (
    ALLOWED_MIME_TYPES,
    is_allowed_mime,
    sanitize_filename,
)


class TestIsAllowedMime:
    @pytest.mark.parametrize("mime", sorted(ALLOWED_MIME_TYPES))
    def test_allows_canonical_types(self, mime: str):
        assert is_allowed_mime(mime) is True

    def test_strips_parameters(self):
        assert is_allowed_mime("application/pdf; charset=utf-8") is True

    def test_case_insensitive(self):
        assert is_allowed_mime("Application/PDF") is True

    def test_rejects_unknown(self):
        assert is_allowed_mime("application/x-executable") is False

    def test_rejects_empty(self):
        assert is_allowed_mime("") is False
        assert is_allowed_mime(None) is False


class TestSanitizeFilename:
    def test_strips_path_traversal(self):
        # We deliberately keep only the final path component (more secure than
        # joining with underscores) — no parent path leaks through.
        assert sanitize_filename("../../etc/passwd") == "passwd"

    def test_strips_windows_path(self):
        assert sanitize_filename(r"C:\Users\admin\report.pdf") == "report.pdf"

    def test_keeps_safe_chars(self):
        assert sanitize_filename("my-doc_v2.final.pdf") == "my-doc_v2.final.pdf"

    def test_collapses_unsafe_chars(self):
        assert sanitize_filename("hello world!?.pdf") == "hello_world_.pdf"

    def test_collapses_dots(self):
        assert sanitize_filename("evil...exe") == "evil.exe"

    def test_returns_fallback_for_empty(self):
        assert sanitize_filename("") == "upload"
        assert sanitize_filename(None) == "upload"

    def test_returns_fallback_for_all_unsafe(self):
        assert sanitize_filename("///") == "upload"
