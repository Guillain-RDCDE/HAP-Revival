"""Shared pytest setup: put `tools/` on the import path so the test modules can
`import hap_sync`, `import i18n`, etc. exactly as the tools import each other.

All tests here are pure / offline — no HAP device, no network beyond a local
loopback mock. They run on any OS (the CI runner is Linux)."""

import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))


@pytest.fixture(autouse=True)
def _isolated_user_cache(tmp_path, monkeypatch):
    """Keep every test away from the real ~/.hap-revival.

    A harvest or a share index written there by a test would be picked up by
    the next test — and by the owner's own tools.
    """
    import hap_fixit
    import hap_library

    cache = tmp_path / "user-cache"
    monkeypatch.setattr(hap_library, "CACHE_DIR", cache)
    monkeypatch.setattr(hap_fixit, "USER_CACHE_DIR", cache)
