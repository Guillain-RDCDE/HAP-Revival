"""Shared pytest setup: put `tools/` on the import path so the test modules can
`import hap_sync`, `import i18n`, etc. exactly as the tools import each other.

All tests here are pure / offline — no HAP device, no network beyond a local
loopback mock. They run on any OS (the CI runner is Linux)."""

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
