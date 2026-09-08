"""Read a Chrome or Chromium user data directory."""

from __future__ import annotations

from .core import (
    CHANNEL_CACHE_DIRECTORIES,
    CHANNEL_DIRECTORIES,
    KEYRING_NAMES,
    ChromeProfile,
    ChromeUserData,
    OSCrypt,
    ProfileNotFound,
    chrome_cache_directory,
    chrome_config_directory,
    chrome_timestamp_to_datetime,
    classify_path,
    database_summary,
    is_sqlite_database,
    linux_keyring_passwords,
    open_database,
    profile_files,
    query_database,
    table_names,
    unix_timestamp_to_datetime,
    webkit_timestamp_to_datetime,
)
from .pwa import fix_chromium_pwa_icon
from .version import (
    generate_chrome_user_agent,
    get_last_chrome_major_version,
    get_latest_chrome_major_version,
)

__all__ = ('CHANNEL_CACHE_DIRECTORIES', 'CHANNEL_DIRECTORIES', 'KEYRING_NAMES', 'ChromeProfile',
           'ChromeUserData', 'OSCrypt', 'ProfileNotFound', 'chrome_cache_directory',
           'chrome_config_directory', 'chrome_timestamp_to_datetime', 'classify_path',
           'database_summary', 'fix_chromium_pwa_icon', 'generate_chrome_user_agent',
           'get_last_chrome_major_version', 'get_latest_chrome_major_version', 'is_sqlite_database',
           'linux_keyring_passwords', 'open_database', 'profile_files', 'query_database',
           'table_names', 'unix_timestamp_to_datetime', 'webkit_timestamp_to_datetime')
