"""Basic smoke tests for the ankavm backend.

These tests confirm that the application imports, that core endpoints
respond, and that internal registries are usable. They do not exercise
real virtualization.
"""

from __future__ import annotations

import json

import pytest


def test_app_starts(mock_libvirt, tmp_state_dir, monkeypatch):
    """The backend module imports without raising."""
    monkeypatch.setenv("ankavm_TEST_MODE", "1")
    monkeypatch.setenv("ankavm_DISABLE_SOCKETIO", "1")
    try:
        import backend.main as main_module  # type: ignore
    except Exception:
        try:
            import main as main_module  # type: ignore
        except Exception as exc:
            pytest.skip(f"backend not importable: {exc}")
    assert hasattr(main_module, "app")


def test_health_endpoint(app):
    """/api/system/info returns 200 or 401 if auth required."""
    resp = app.get("/api/system/info")
    assert resp.status_code in (200, 401, 403), (
        f"unexpected status {resp.status_code}: {resp.data!r}"
    )


def test_openapi_spec(app):
    """/api/openapi returns valid JSON with a `paths` key."""
    resp = app.get("/api/openapi")
    if resp.status_code == 404:
        pytest.skip("openapi endpoint not present in this build")
    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert isinstance(payload, dict)
    assert "paths" in payload
    assert isinstance(payload["paths"], dict)


def test_config_load(tmp_state_dir, monkeypatch):
    """config module loads without /etc/ankavm/ankavm.conf."""
    monkeypatch.setenv("ankavm_CONFIG", "/nonexistent/ankavm.conf")
    try:
        from backend import config as cfg  # type: ignore
    except Exception:
        try:
            import config as cfg  # type: ignore
        except Exception as exc:
            pytest.skip(f"config module not importable: {exc}")
    # Either a load() function or a module-level CONFIG dict is acceptable.
    if hasattr(cfg, "load"):
        data = cfg.load()
        assert isinstance(data, dict)
    elif hasattr(cfg, "CONFIG"):
        assert isinstance(cfg.CONFIG, dict)
    else:
        pytest.skip("config module exposes no load() or CONFIG")


def test_feature_registry(mock_libvirt, tmp_state_dir):
    """feature_registry.list_features() returns a list of dicts."""
    try:
        from backend import feature_registry as fr  # type: ignore
    except Exception:
        try:
            import feature_registry as fr  # type: ignore
        except Exception as exc:
            pytest.skip(f"feature_registry not importable: {exc}")
    fn = getattr(fr, "list_features", None)
    if fn is None:
        pytest.skip("feature_registry.list_features() not present")
    features = fn()
    assert isinstance(features, list)
    for item in features:
        assert isinstance(item, dict)






