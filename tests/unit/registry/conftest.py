"""Shared fixtures for tests/unit/registry/.

All tests in this directory exercise registry functionality and therefore
require the 'registry' experimental flag to be enabled.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _enable_registry_flag(monkeypatch):
    """Enable the 'registry' experimental flag for every test in this directory.

    Uses direct config-cache injection so there is no disk I/O.
    """
    import apm_cli.config as _conf
    from apm_cli.config import _invalidate_config_cache

    _invalidate_config_cache()
    monkeypatch.setattr(_conf, "_config_cache", {"experimental": {"registry": True}})
    yield
    _invalidate_config_cache()
