"""Tests for :py:mod:`deltona.chrome.typing`."""

from __future__ import annotations

from typing import get_args, get_type_hints

from deltona.chrome.typing import (
    LocalState,
    LocalStateBrowser,
    LocalStateProfile,
    ProfileInfo,
    __all__ as exported,
)


def test_every_export_is_defined() -> None:
    import deltona.chrome.typing as module

    assert all(hasattr(module, name) for name in exported)


def test_local_state_shape() -> None:
    assert set(get_type_hints(LocalState)) == {'browser', 'os_crypt', 'profile'}
    assert set(get_type_hints(LocalStateBrowser)) == {'enabled_labs_experiments'}
    assert set(get_type_hints(LocalStateProfile)) == {'info_cache', 'last_used', 'profiles_order'}


def test_profile_info_carries_the_account_fields() -> None:
    assert {'gaia_id', 'gaia_name', 'name', 'user_name'} <= set(get_type_hints(ProfileInfo))


def test_channels_cover_every_release_track() -> None:
    from deltona.chrome.typing import ChromeChannel

    assert set(get_args(ChromeChannel)) == {'beta', 'canary', 'chromium', 'dev', 'stable'}
