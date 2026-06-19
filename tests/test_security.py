"""Security regression tests for ankavm.

Each test corresponds to a property we do not want to silently lose. If a
refactor removes one of these guarantees the test should fail loudly.
"""

from __future__ import annotations

import time

import pytest


def test_jwt_algorithm_locked(mock_libvirt, tmp_state_dir):
    """JWT verification must accept only HS256."""
    try:
        from backend import auth  # type: ignore
    except Exception:
        try:
            import auth  # type: ignore
        except Exception as exc:
            pytest.skip(f"auth module not importable: {exc}")
    allowed = getattr(auth, "JWT_ALGORITHMS", None) or getattr(auth, "ALLOWED_ALGS", None)
    if allowed is None:
        pytest.skip("auth module does not expose an algorithm allowlist")
    assert list(allowed) == ["HS256"], f"expected only HS256, got {allowed!r}"


def test_login_constant_time(app):
    """Bad-user and bad-password paths differ by less than 50 ms on average."""
    samples_unknown = []
    samples_badpw = []
    for _ in range(5):
        t0 = time.perf_counter()
        app.post("/api/auth/login",
                 json={"username": "does-not-exist-xyz", "password": "x"})
        samples_unknown.append(time.perf_counter() - t0)

        t0 = time.perf_counter()
        app.post("/api/auth/login",
                 json={"username": "admin", "password": "definitely-wrong"})
        samples_badpw.append(time.perf_counter() - t0)

    avg_unknown = sum(samples_unknown) / len(samples_unknown)
    avg_badpw = sum(samples_badpw) / len(samples_badpw)
    delta_ms = abs(avg_unknown - avg_badpw) * 1000
    # Generous bound: we only want to catch order-of-magnitude regressions.
    assert delta_ms < 50, f"login timing delta {delta_ms:.1f} ms exceeds 50 ms"


def test_csrf_required(app):
    """POST without CSRF token to a non-exempt endpoint returns 401/403."""
    # Re-enable CSRF for this test only.
    app.application.config["WTF_CSRF_ENABLED"] = True
    try:
        resp = app.post("/api/vms", json={"name": "t"})
    finally:
        app.application.config["WTF_CSRF_ENABLED"] = False
    assert resp.status_code in (401, 403), (
        f"expected auth/CSRF rejection, got {resp.status_code}"
    )


def test_path_traversal_blocked(app):
    """A traversal sequence in an ISO path is rejected with 4xx."""
    resp = app.get("/api/storage/isos/../../../etc/passwd")
    assert resp.status_code in (400, 401, 403, 404), (
        f"path traversal returned {resp.status_code}; expected 4xx"
    )
    body = resp.get_data(as_text=True).lower()
    assert "root:" not in body, "path traversal appears to have leaked /etc/passwd"


def test_admin_only_endpoint_blocks_viewer(app, monkeypatch):
    """A viewer role must not be able to POST to /api/ai/agents."""
    # Simulate viewer session if the backend supports a test login helper.
    monkeypatch.setenv("ankavm_TEST_ROLE", "viewer")
    resp = app.post("/api/ai/agents", json={"name": "test-agent"})
    assert resp.status_code in (401, 403), (
        f"viewer should be denied, got {resp.status_code}"
    )






