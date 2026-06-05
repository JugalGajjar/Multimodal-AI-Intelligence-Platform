"""Every API response should ship with the defensive header set."""

EXPECTED = {
    "Strict-Transport-Security": "max-age=63072000",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=()",
    "Content-Security-Policy": "default-src 'none'",
}


class TestSecurityHeaders:
    def test_health_response_has_all_headers(self, client):
        r = client.get("/api/v1/health")

        assert r.status_code == 200
        for key, contains in EXPECTED.items():
            assert key in r.headers, f"missing header: {key}"
            assert contains in r.headers[key], (
                f"{key}: expected '{contains}', got '{r.headers[key]}'"
            )

    def test_404_response_also_has_headers(self, client):
        # Even error paths must carry the headers — a bare 404 is the most
        # common page an attacker probes for misconfiguration.
        r = client.get("/api/v1/does-not-exist")

        assert r.status_code == 404
        for key in EXPECTED:
            assert key in r.headers, f"missing header on 404: {key}"
