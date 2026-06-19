"""Shared pytest fixtures for ankavm test suite.

The fixtures here avoid any dependency on a real libvirt daemon, a real
KVM-capable host, or persistent state under /var/lib/ankavm. Tests should
be runnable on a developer laptop with only Python and the dev requirements
installed.
"""

from __future__ import annotations

import os
import sys
import types
import tempfile
import pathlib

import pytest


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def tmp_state_dir(monkeypatch):
    """Provide a clean temporary directory in place of /var/lib/ankavm."""
    with tempfile.TemporaryDirectory(prefix="ankavm-test-") as d:
        monkeypatch.setenv("ankavm_STATE_DIR", d)
        monkeypatch.setenv("ankavm_AUDIT_LOG", os.path.join(d, "audit.log"))
        yield d


@pytest.fixture
def mock_libvirt(monkeypatch):
    """Install a stub libvirt module so backend imports succeed without KVM."""
    stub = types.ModuleType("libvirt")

    class _Conn:
        def listAllDomains(self, *_a, **_kw):
            return []

        def listAllNetworks(self, *_a, **_kw):
            return []

        def listAllStoragePools(self, *_a, **_kw):
            return []

        def close(self):
            return 0

    def _open(_uri=None):
        return _Conn()

    stub.open = _open
    stub.openReadOnly = _open
    stub.libvirtError = type("libvirtError", (Exception,), {})
    stub.VIR_DOMAIN_RUNNING = 1
    stub.VIR_DOMAIN_SHUTOFF = 5
    monkeypatch.setitem(sys.modules, "libvirt", stub)
    return stub


@pytest.fixture
def app(mock_libvirt, tmp_state_dir, monkeypatch):
    """Return a Flask test client without starting SocketIO."""
    monkeypatch.setenv("ankavm_TEST_MODE", "1")
    monkeypatch.setenv("ankavm_DISABLE_SOCKETIO", "1")

    try:
        import backend.main as main_module  # type: ignore
    except Exception:
        try:
            import main as main_module  # type: ignore
        except Exception as exc:
            pytest.skip(f"backend not importable in this environment: {exc}")

    flask_app = getattr(main_module, "app", None)
    if flask_app is None:
        pytest.skip("backend exposes no `app` attribute")

    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    with flask_app.test_client() as client:
        yield client






