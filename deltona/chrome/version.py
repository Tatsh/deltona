"""Browser version lookup and user agent generation."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from async_lru import alru_cache
from niquests import AsyncSession
import anyio

from .core import chrome_config_directory

if TYPE_CHECKING:
    from .typing import ChromeChannel

__all__ = ('LATEST_VERSION_URL', 'VERSION_CHANNEL_ORDER', 'generate_chrome_user_agent',
           'get_last_chrome_major_version', 'get_latest_chrome_major_version')

LATEST_VERSION_URL = ('https://versionhistory.googleapis.com/v1/chrome/platforms/win/channels/'
                      'stable/versions')
"""
Where the newest released version is published.

:meta hide-value:
"""
VERSION_CHANNEL_ORDER: tuple[ChromeChannel, ...] = ('beta', 'stable', 'dev', 'canary', 'chromium')
"""
Channels searched for a ``Last Version`` file, in order of preference.

:meta hide-value:
"""


@alru_cache
async def get_last_chrome_major_version() -> str:
    """
    Get the major version of the browser that last ran on this machine.

    Each channel's user data directory is checked in the order of
    :py:data:`VERSION_CHANNEL_ORDER`, using the location
    :py:func:`~deltona.chrome.core.chrome_config_directory` reports for the current platform.

    Returns
    -------
    str
        The major version, or an empty string if no ``Last Version`` file was found.
    """
    for channel in VERSION_CHANNEL_ORDER:
        path = anyio.Path(chrome_config_directory(channel)) / 'Last Version'
        if await path.exists():
            return (await path.read_text()).split('.', 1)[0]
    return ''


@alru_cache
async def get_latest_chrome_major_version() -> str:
    """
    Get the latest released Chrome major version.

    Returns
    -------
    str
        The latest major version number as a string.
    """
    async with AsyncSession() as session:
        r = await session.get(LATEST_VERSION_URL, timeout=5)
    return cast('str', r.json()['versions'][0]['version'].split('.')[0])


@alru_cache
async def generate_chrome_user_agent(os: str = 'Windows NT 10.0; Win64; x64') -> str:
    """
    Get a Chrome user agent.

    The installed browser's version is preferred, since a user agent claiming a version far from
    the one in use is the kind of mismatch a server can notice. The latest released version is used
    when no browser is installed.

    Parameters
    ----------
    os : str
        The operating system. Default is ``'Windows NT 10.0; Win64; x64'``.

    Returns
    -------
    str
        A Chrome user agent string.
    """
    last_major = await get_last_chrome_major_version() or await get_latest_chrome_major_version()
    return (f'Mozilla/5.0 ({os}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{last_major}.0.0.0'
            ' Safari/537.36')
