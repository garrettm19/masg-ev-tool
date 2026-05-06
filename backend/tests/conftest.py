"""
Test-suite-wide fixtures.

The runtime maker config (``services.maker.config._runtime_maker_config``)
is mutable module-level state.  Without a reset hook, a test that calls
``set_maker_config`` could leak its setting into unrelated tests that rely
on the disabled default — flaky failures in the worst case, false greens in
the best.  This autouse fixture resets the runtime config to ``None``
around every test so each one starts from the pristine
``DEFAULT_MAKER_CONFIG`` (disabled, paper-only, Kalshi+H2H).
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_maker_runtime_config():
    from services.maker.config import reset_maker_config
    reset_maker_config()
    yield
    reset_maker_config()
