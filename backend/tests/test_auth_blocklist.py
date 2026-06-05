from app.auth.blocklist import DISPOSABLE_DOMAINS, is_disposable


class TestIsDisposable:
    def test_mailinator_is_blocked(self):
        assert is_disposable("foo@mailinator.com") is True

    def test_gmail_is_allowed(self):
        assert is_disposable("foo@gmail.com") is False

    def test_custom_domain_is_allowed(self):
        assert is_disposable("alice@mycompany.io") is False

    def test_case_insensitive(self):
        assert is_disposable("FOO@MAILINATOR.COM") is True

    def test_real_providers_not_in_blocklist(self):
        # Sanity: these were nearly-included false positives during the audit.
        for ok in ("gmail.com", "outlook.com", "naver.com", "tutanota.com"):
            assert ok not in DISPOSABLE_DOMAINS, f"{ok} should not be blocked"

    def test_only_takes_domain_part(self):
        # The local-part doesn't matter for disposable matching.
        assert is_disposable("mailinator.com@gmail.com") is False
