"""Typing helpers for :py:mod:`deltona.chrome`."""

from __future__ import annotations

from typing import Literal, TypeAlias

from typing_extensions import NotRequired, TypedDict

__all__ = ('ChromeChannel', 'LocalState', 'LocalStateBrowser', 'LocalStateProfile', 'ProfileInfo')

ChromeChannel: TypeAlias = Literal['beta', 'canary', 'chromium', 'dev', 'stable']
"""
Release channel of a Chrome or Chromium installation.

:meta hide-value:
"""


class ProfileInfo(TypedDict):
    """One entry of ``profile.info_cache`` in ``Local State``."""

    active_time: NotRequired[float]
    """Time the profile was last active, in seconds since the UNIX epoch."""
    avatar_icon: NotRequired[str]
    """URL of the avatar icon."""
    gaia_given_name: NotRequired[str]
    """Given name of the signed-in Google account."""
    gaia_id: NotRequired[str]
    """Identifier of the signed-in Google account."""
    gaia_name: NotRequired[str]
    """Full name of the signed-in Google account."""
    hosted_domain: NotRequired[str]
    """Hosted domain of the signed-in Google account."""
    is_ephemeral: NotRequired[bool]
    """If ``True``, the profile is discarded when the browser exits."""
    metrics_bucket_index: NotRequired[int]
    """Index used to bucket metrics for this profile."""
    name: NotRequired[str]
    """Display name of the profile."""
    user_name: NotRequired[str]
    """Email address of the signed-in Google account."""


class LocalStateProfile(TypedDict):
    """The ``profile`` section of ``Local State``."""

    info_cache: NotRequired[dict[str, ProfileInfo]]
    """Profile information keyed by profile directory name."""
    last_used: NotRequired[str]
    """Directory name of the profile that was last used."""
    profiles_order: NotRequired[list[str]]
    """Directory names in the order they are displayed."""


class LocalStateBrowser(TypedDict):
    """The ``browser`` section of ``Local State``."""

    enabled_labs_experiments: NotRequired[list[str]]
    """Flags the user changed, each written as ``name`` or ``name@index``."""


class LocalState(TypedDict):
    """Selected parts of the ``Local State`` file."""

    browser: NotRequired[LocalStateBrowser]
    """Browser-wide settings, including changed ``chrome://flags`` entries."""
    os_crypt: NotRequired[dict[str, str]]
    """Encryption settings, including the DPAPI-wrapped key on Windows."""
    profile: NotRequired[LocalStateProfile]
    """Profile information."""
