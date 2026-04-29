"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _isolate_settings() -> Iterator[None]:
    """Clear the cached Settings before and after each test.

    Settings is an lru_cached singleton; without this fixture, env-var changes from
    earlier tests bleed into later tests via the cache.
    """
    from tongue_doctor.settings import reset_settings_cache

    reset_settings_cache()
    yield
    reset_settings_cache()
