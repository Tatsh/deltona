"""Core access to a Chrome or Chromium user data directory."""

from __future__ import annotations

from contextlib import closing, contextmanager, suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import cached_property
from pathlib import Path
from shutil import copyfile, which
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any, ClassVar, cast
import json
import logging
import os
import sqlite3
import subprocess as sp
import sys

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence
    from types import ModuleType

    from deltona.typing import StrPath

    from .typing import ChromeChannel, LocalState, ProfileInfo

__all__ = ('CHANNEL_CACHE_DIRECTORIES', 'CHANNEL_DIRECTORIES', 'KEYRING_NAMES', 'ChromeProfile',
           'ChromeUserData', 'OSCrypt', 'ProfileNotFound', 'chrome_cache_directory',
           'chrome_config_directory', 'chrome_timestamp_to_datetime', 'classify_path',
           'database_summary', 'is_sqlite_database', 'linux_keyring_password', 'open_database',
           'profile_files', 'query_database', 'table_names', 'unix_timestamp_to_datetime',
           'webkit_timestamp_to_datetime')

log = logging.getLogger(__name__)

_WEBKIT_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)
_AES_BLOCK_SIZE = 16
_GCM_NONCE_SIZE = 12
_GCM_TAG_SIZE = 16
_SHA256_SIZE = 32
_DERIVED_KEY_SIZE = 16
_LIBSECRET_SCHEMA = 'chrome_libsecret_os_crypt_password_v2'
_UNIX_SECONDS_LIMIT = 10 ** 11
_WEBKIT_MILLISECONDS_LIMIT = 10 ** 15
CHANNEL_DIRECTORIES: dict[str, dict[ChromeChannel, str]] = {
    'darwin': {
        'beta': 'Google/Chrome Beta',
        'canary': 'Google/Chrome Canary',
        'chromium': 'Chromium',
        'dev': 'Google/Chrome Dev',
        'stable': 'Google/Chrome'
    },
    'linux': {
        'beta': 'google-chrome-beta',
        'canary': 'google-chrome-canary',
        'chromium': 'chromium',
        'dev': 'google-chrome-unstable',
        'stable': 'google-chrome'
    },
    'win32': {
        'beta': 'Google/Chrome Beta/User Data',
        'canary': 'Google/Chrome SxS/User Data',
        'chromium': 'Chromium/User Data',
        'dev': 'Google/Chrome Dev/User Data',
        'stable': 'Google/Chrome/User Data'
    }
}
"""
User data directory of each channel, relative to the platform's base directory.

:meta hide-value:
"""
CHANNEL_CACHE_DIRECTORIES: dict[str, dict[ChromeChannel, str]] = {
    'darwin': {
        'beta': 'Google/Chrome Beta',
        'canary': 'Google/Chrome Canary',
        'chromium': 'Chromium',
        'dev': 'Google/Chrome Dev',
        'stable': 'Google/Chrome'
    },
    'linux': {
        'beta': 'google-chrome-beta',
        'canary': 'google-chrome-canary',
        'chromium': 'chromium',
        'dev': 'google-chrome-unstable',
        'stable': 'google-chrome'
    }
}
"""
Cache directory of each channel, relative to the platform's base cache directory.

Windows is absent because it keeps the cache inside the profile directory.

:meta hide-value:
"""
KEYRING_NAMES: dict[ChromeChannel, str] = {
    'beta': 'Chrome',
    'canary': 'Chrome',
    'chromium': 'Chromium',
    'dev': 'Chrome',
    'stable': 'Chrome'
}
"""
Name the browser registers its encryption key under.

:meta hide-value:
"""


class ProfileNotFound(Exception):
    """Raised when no profile matches the requested name."""
    def __init__(self, name: str, available: Sequence[str] = ()) -> None:
        known = ', '.join(f'{x!r}' for x in available)
        super().__init__(f'No profile matching {name!r}.'
                         f' Available: {known}' if known else f'No profile matching {name!r}.')


def _is_windows() -> bool:
    return sys.platform in {'cygwin', 'win32'}


def _is_mac() -> bool:
    return sys.platform == 'darwin'


def _platform_key() -> str:
    if _is_windows():
        return 'win32'
    if _is_mac():
        return 'darwin'
    return 'linux'


def _platformdirs() -> ModuleType:
    import platformdirs  # ruff:ignore[import-outside-top-level]

    return platformdirs


def chrome_config_directory(channel: ChromeChannel = 'stable') -> Path:
    """
    Get the default user data directory of a Chrome or Chromium channel.

    Parameters
    ----------
    channel : ChromeChannel
        Release channel. Default is ``'stable'``.

    Returns
    -------
    pathlib.Path
        Path to the user data directory. It is not guaranteed to exist.
    """
    platformdirs = _platformdirs()
    base = Path(
        platformdirs.user_data_dir(
            roaming=False) if _is_windows() or _is_mac() else platformdirs.user_config_dir())
    return base / CHANNEL_DIRECTORIES[_platform_key()][channel]


def chrome_cache_directory(channel: ChromeChannel = 'stable') -> Path:
    """
    Get the default cache directory of a Chrome or Chromium channel.

    Parameters
    ----------
    channel : ChromeChannel
        Release channel. Default is ``'stable'``.

    Returns
    -------
    pathlib.Path
        Path to the cache directory. On Windows this is the user data directory because the cache
        lives inside each profile. It is not guaranteed to exist.
    """
    if _is_windows():
        return chrome_config_directory(channel)
    return Path(
        _platformdirs().user_cache_dir()) / CHANNEL_CACHE_DIRECTORIES[_platform_key()][channel]


def webkit_timestamp_to_datetime(value: float | str | None) -> datetime | None:
    """
    Convert a WebKit timestamp to a datetime.

    WebKit timestamps count microseconds since 1601-01-01 UTC. Chrome uses them for almost every
    stored time.

    Parameters
    ----------
    value : float | str | None
        The timestamp. Strings are accepted because JSON files store the value as a string.

    Returns
    -------
    datetime.datetime | None
        The converted time, or ``None`` if ``value`` is empty or zero.
    """
    if not value:
        return None
    with suppress(ValueError, OverflowError):
        if not (number := int(value)):
            return None
        return _WEBKIT_EPOCH + timedelta(microseconds=number)
    return None


def unix_timestamp_to_datetime(value: float | str | None) -> datetime | None:
    """
    Convert a UNIX timestamp in seconds to a datetime.

    Parameters
    ----------
    value : float | str | None
        Seconds since the UNIX epoch.

    Returns
    -------
    datetime.datetime | None
        The converted time, or ``None`` if ``value`` is empty or zero.
    """
    if not value:
        return None
    with suppress(ValueError, OverflowError, OSError):
        if not (number := float(value)):
            return None
        return datetime.fromtimestamp(number, tz=timezone.utc)
    return None


def chrome_timestamp_to_datetime(value: float | str | None) -> datetime | None:
    """
    Convert a Chrome timestamp whose unit is not known in advance.

    Chrome mixes three encodings within a single database. Autofill and local payment tables store
    seconds since the UNIX epoch, offer expiry stores milliseconds since 1601, and server payment
    metadata stores microseconds since 1601. They are told apart by magnitude: below 1e11 is
    seconds, below 1e15 is milliseconds, and anything larger is microseconds. The ranges do not
    overlap for any time this century.

    Parameters
    ----------
    value : float | str | None
        The stored timestamp.

    Returns
    -------
    datetime.datetime | None
        The converted time, or ``None`` if ``value`` is empty or zero.
    """
    if not value:
        return None
    with suppress(ValueError, OverflowError):
        number = int(value)
        if abs(number) < _UNIX_SECONDS_LIMIT:
            return unix_timestamp_to_datetime(number)
        if abs(number) < _WEBKIT_MILLISECONDS_LIMIT:
            return webkit_timestamp_to_datetime(number * 1000)
        return webkit_timestamp_to_datetime(number)
    return None


def _decode_text(data: bytes) -> str | bytes:
    try:
        return data.decode()
    except UnicodeDecodeError:
        return data


@contextmanager
def open_database(path: StrPath) -> Iterator[sqlite3.Connection]:
    """
    Open a copy of a Chrome SQLite database for reading.

    The database is copied because the browser may hold an exclusive lock on it, and because a
    write-ahead log that is not copied alongside its database yields stale rows.

    Some encrypted columns are declared ``VARCHAR`` yet hold ciphertext, so values that are not
    valid UTF-8 are returned as :py:class:`bytes` rather than raising.

    Parameters
    ----------
    path : StrPath
        Path to the database.

    Yields
    ------
    sqlite3.Connection
        Connection with :py:attr:`sqlite3.Connection.row_factory` set to :py:class:`sqlite3.Row`.

    Raises
    ------
    FileNotFoundError
        If the database does not exist.
    """
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(os.strerror(2), str(source))
    with TemporaryDirectory(prefix='deltona-chrome-') as temp_dir:
        target = Path(temp_dir) / source.name
        copyfile(source, target)
        for suffix in ('-wal', '-shm', '-journal'):
            if (side_car := source.with_name(f'{source.name}{suffix}')).is_file():
                copyfile(side_car, target.with_name(f'{target.name}{suffix}'))
        connection = sqlite3.connect(target)
        connection.row_factory = sqlite3.Row
        connection.text_factory = _decode_text
        try:
            yield connection
        finally:
            connection.close()


def query_database(path: StrPath, sql: str, parameters: Sequence[Any] = ()) -> list[dict[str, Any]]:
    """
    Run a query against a Chrome SQLite database and return every row as a dictionary.

    Parameters
    ----------
    path : StrPath
        Path to the database.
    sql : str
        The statement to run.
    parameters : Sequence[Any]
        Values bound to the statement.

    Returns
    -------
    list[dict[str, Any]]
        Rows keyed by column name.
    """
    with open_database(path) as connection:
        return [dict(row) for row in connection.execute(sql, parameters)]


def table_names(path: StrPath) -> tuple[str, ...]:
    """
    List the tables of a Chrome SQLite database.

    Parameters
    ----------
    path : StrPath
        Path to the database.

    Returns
    -------
    tuple[str, ...]
        Table names, sorted.
    """
    return tuple(row['name'] for row in query_database(
        path, "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"))


def database_summary(path: StrPath) -> dict[str, Any]:
    """
    Summarise a Chrome SQLite database.

    Parameters
    ----------
    path : StrPath
        Path to the database.

    Returns
    -------
    dict[str, Any]
        The file name, size in bytes, schema version and last compatible version from the ``meta``
        table when it has one, and the list of tables.
    """
    database = Path(path)
    summary: dict[str, Any] = {
        'name': database.name,
        'size': database.stat().st_size,
        'version': None,
        'last_compatible_version': None,
        'tables': []
    }
    with suppress(sqlite3.Error):
        with open_database(database) as connection:
            summary['tables'] = sorted(row['name'] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"))
            if 'meta' in summary['tables']:
                meta = dict(connection.execute('SELECT key, value FROM meta').fetchall())
                summary['version'] = meta.get('version')
                summary['last_compatible_version'] = meta.get('last_compatible_version')
        return summary
    return summary


def classify_path(path: StrPath) -> str:
    """
    Describe what kind of storage a path in a profile directory holds.

    Parameters
    ----------
    path : StrPath
        Path to a file or directory.

    Returns
    -------
    str
        One of ``'sqlite'``, ``'json'``, ``'leveldb'``, ``'directory'``, ``'empty'``, ``'text'``,
        or ``'binary'``.
    """
    candidate = Path(path)
    if candidate.is_dir():
        return 'leveldb' if (candidate / 'CURRENT').is_file() else 'directory'
    if not candidate.is_file():
        return 'binary'
    if candidate.stat().st_size == 0:
        return 'empty'
    with candidate.open('rb') as f:
        head = f.read(16)
    if head == b'SQLite format 3\x00':
        return 'sqlite'
    if head[:1] in {b'{', b'['}:
        return 'json'
    try:
        candidate.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return 'binary'
    return 'text'


def profile_files(path: StrPath) -> Iterator[dict[str, Any]]:
    """
    Inventory the top level of a profile directory.

    Parameters
    ----------
    path : StrPath
        Path to the profile directory.

    Yields
    ------
    dict[str, Any]
        The entry name, kind as returned by :py:func:`classify_path`, size in bytes (recursive for
        directories), and modification time.
    """
    root = Path(path)
    if not root.is_dir():
        return
    for child in sorted(root.iterdir(), key=lambda p: p.name):
        size = (sum(f.stat().st_size for f in child.rglob('*')
                    if f.is_file()) if child.is_dir() else child.stat().st_size)
        yield {
            'name': child.name,
            'kind': classify_path(child),
            'size': size,
            'modified': datetime.fromtimestamp(child.stat().st_mtime, tz=timezone.utc)
        }


def is_sqlite_database(path: StrPath) -> bool:
    """
    Determine whether a file is a SQLite database by reading its magic header.

    Parameters
    ----------
    path : StrPath
        Path to the file.

    Returns
    -------
    bool
        ``True`` if the file starts with the SQLite 3 magic string.
    """
    candidate = Path(path)
    if not candidate.is_file():
        return False
    with candidate.open('rb') as f:
        return f.read(16) == b'SQLite format 3\x00'


@dataclass(frozen=True)
class ChromeProfile:
    """A single browser profile within a user data directory."""

    directory: str
    """Directory name, such as ``'Default'`` or ``'Profile 1'``."""
    path: Path
    """Absolute path to the profile directory."""
    cache_path: Path
    """Absolute path to the profile's cache directory."""
    info: ProfileInfo
    """The profile's ``Local State`` entry."""
    @property
    def active_time(self) -> datetime | None:
        """Time the profile was last active."""
        return unix_timestamp_to_datetime(self.info.get('active_time'))

    @property
    def email(self) -> str | None:
        """Email address of the signed-in Google account."""
        return self.info.get('user_name') or None

    @property
    def gaia_name(self) -> str | None:
        """Full name of the signed-in Google account."""
        return self.info.get('gaia_name') or None

    @property
    def name(self) -> str:
        """Display name of the profile, falling back to the directory name."""
        return self.info.get('name') or self.directory

    def aliases(self) -> tuple[str, ...]:
        """
        List every string the profile can be selected by.

        Returns
        -------
        tuple[str, ...]
            Directory name, display name, account name, given name, and email address.
        """
        return tuple(
            dict.fromkeys(
                x for x in (self.directory, self.info.get('name'), self.info.get('gaia_name'),
                            self.info.get('gaia_given_name'), self.info.get('user_name')) if x))


class ChromeUserData:
    """A Chrome or Chromium user data directory."""
    def __init__(self,
                 config_path: StrPath | None = None,
                 cache_path: StrPath | None = None,
                 channel: ChromeChannel = 'stable') -> None:
        self.channel = channel
        self.config_path = Path(config_path) if config_path else chrome_config_directory(channel)
        self.cache_path = (Path(cache_path) if cache_path else chrome_cache_directory(channel))

    @cached_property
    def local_state(self) -> LocalState:
        """
        Contents of the ``Local State`` file.

        Returns
        -------
        LocalState
            An empty mapping if the file is missing or unreadable.
        """
        path = self.config_path / 'Local State'
        if not path.is_file():
            log.debug('No `Local State` at `%s`.', path)
            return cast('LocalState', {})
        with suppress(OSError, ValueError):
            return cast('LocalState', json.loads(path.read_text(encoding='utf-8')))
        return cast('LocalState', {})

    @cached_property
    def keyring_name(self) -> str:
        """Name the browser stores its encryption key under."""
        return KEYRING_NAMES[self.channel]

    def profiles(self) -> tuple[ChromeProfile, ...]:
        """
        List every profile in the user data directory.

        Directories present on disk but missing from ``Local State`` are included so that a
        partially written state file does not hide data.

        Returns
        -------
        tuple[ChromeProfile, ...]
            Profiles sorted by directory name, with ``Default`` first.
        """
        info_cache = self.local_state.get('profile', {}).get('info_cache', {})
        directories = dict.fromkeys((*info_cache, *self._profile_directories_on_disk()))
        profiles = [
            ChromeProfile(directory=directory,
                          path=self.config_path / directory,
                          cache_path=self._cache_path_for(directory),
                          info=info_cache.get(directory, cast('ProfileInfo', {})))
            for directory in directories
        ]
        return tuple(sorted(profiles, key=lambda p: (p.directory != 'Default', p.directory)))

    def profile(self, name: str = 'Default') -> ChromeProfile:
        """
        Resolve a profile by directory name, display name, account name, or email address.

        Parameters
        ----------
        name : str
            The value to match. Matching is case-insensitive. Default is ``'Default'``.

        Returns
        -------
        ChromeProfile
            The matching profile.

        Raises
        ------
        ProfileNotFound
            If no profile matches ``name``.
        """
        profiles = self.profiles()
        wanted = name.casefold()
        for profile in profiles:
            if any(alias.casefold() == wanted for alias in profile.aliases()):
                return profile
        raise ProfileNotFound(name, [p.directory for p in profiles])

    def _cache_path_for(self, directory: str) -> Path:
        return (self.config_path / directory) if _is_windows() else (self.cache_path / directory)

    def _profile_directories_on_disk(self) -> Iterator[str]:
        if not self.config_path.is_dir():
            return
        for child in sorted(self.config_path.iterdir()):
            if child.is_dir() and (child / 'Preferences').is_file():
                yield child.name


class OSCrypt:
    """
    Decryptor for values Chrome protects with ``OSCrypt``.

    On Linux and macOS the key is derived with PBKDF2-HMAC-SHA1 from a password held by the
    keyring, using the salt ``saltysalt`` and a 128-bit key. On Windows the key is wrapped with
    DPAPI and stored in ``Local State``.

    See Also
    --------
    `components/os_crypt <https://source.chromium.org/chromium/chromium/src/+/main:components/os_crypt/>`_
    """
    def __init__(self,
                 keyring_name: str = 'Chrome',
                 local_state: Mapping[str, Any] | None = None) -> None:
        self.keyring_name = keyring_name
        self.local_state = local_state or {}

    @cached_property
    def _empty_key(self) -> bytes:
        return _derive_key(b'')

    @cached_property
    def _v10_key(self) -> bytes | None:
        if _is_windows():
            return _windows_master_key(self.local_state)
        if _is_mac():
            password = _macos_password(self.keyring_name)
            return _derive_key(password, iterations=1003) if password else None
        return _derive_key(b'peanuts')

    @cached_property
    def _v11_key(self) -> bytes | None:
        if _is_windows() or _is_mac():
            return None
        password = linux_keyring_password(self.keyring_name)
        return _derive_key(password) if password else None

    @property
    def available(self) -> bool:
        """Whether any key could be obtained."""
        return self._v10_key is not None or self._v11_key is not None

    @property
    def keyring_available(self) -> bool:
        """
        Whether the key the desktop keyring holds could be read.

        A Linux value written as ``v11`` needs this key. The fixed ``v10`` key is always derivable,
        so :py:attr:`available` says nothing about whether such a value can be read.
        """
        return self._v11_key is not None

    def decrypt(self, value: bytes | str | None, *, hash_prefix: bool = False) -> str | None:
        """
        Decrypt one encrypted value.

        Parameters
        ----------
        value : bytes | str | None
            The stored blob, including its version prefix. A string is accepted because SQLite
            reports some ciphertext columns as text.
        hash_prefix : bool
            If ``True``, drop the 32-byte SHA-256 prefix that cookie databases at meta version 24
            and later prepend to the plaintext.

        Returns
        -------
        str | None
            The plaintext, or ``None`` if the value could not be decrypted.
        """
        if not value:
            return None
        if isinstance(value, str):
            value = value.encode()
        version, ciphertext = value[:3], value[3:]
        if version == b'v10' and _is_windows():
            plaintext = _decrypt_aes_gcm(ciphertext, self._v10_key)
        elif version in {b'v10', b'v11'}:
            keys = (self._v10_key if version == b'v10' else self._v11_key, self._empty_key)
            plaintext = _decrypt_aes_cbc(ciphertext, [k for k in keys if k])
        elif _is_windows():
            plaintext = _windows_dpapi_decrypt(value)
        elif _is_mac():
            return value.decode(errors='replace')
        else:
            log.debug('Unknown encryption version %r.', version)
            return None
        if plaintext is None:
            return None
        if hash_prefix and len(plaintext) >= _SHA256_SIZE:
            plaintext = plaintext[_SHA256_SIZE:]
        return plaintext.decode(errors='replace')


def _derive_key(password: bytes, iterations: int = 1) -> bytes:
    from cryptography.hazmat.primitives import hashes  # ruff:ignore[import-outside-top-level]
    from cryptography.hazmat.primitives.kdf import pbkdf2  # ruff:ignore[import-outside-top-level]

    return pbkdf2.PBKDF2HMAC(
        algorithm=hashes.SHA1(),  # noqa: S303
        iterations=iterations,
        length=_DERIVED_KEY_SIZE,
        salt=b'saltysalt').derive(password)


def _decrypt_aes_cbc(ciphertext: bytes, keys: Sequence[bytes]) -> bytes | None:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes  # noqa: PLC0415

    if not keys or len(ciphertext) < _AES_BLOCK_SIZE:
        return None
    for key in keys:
        decryptor = Cipher(algorithms.AES(key), modes.CBC(b' ' * _AES_BLOCK_SIZE)).decryptor()
        plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        padding = plaintext[-1] if plaintext else 0
        if 0 < padding <= _AES_BLOCK_SIZE and plaintext.endswith(bytes([padding]) * padding):
            return plaintext[:-padding]
    log.debug('Failed to decrypt an AES-CBC value with any available key.')
    return None


def _decrypt_aes_gcm(ciphertext: bytes, key: bytes | None) -> bytes | None:
    from cryptography.hazmat.primitives.ciphers import aead  # ruff:ignore[import-outside-top-level]

    if not key or len(ciphertext) < _GCM_NONCE_SIZE + _GCM_TAG_SIZE:
        return None
    with suppress(Exception):
        return aead.AESGCM(key).decrypt(ciphertext[:_GCM_NONCE_SIZE], ciphertext[_GCM_NONCE_SIZE:],
                                        None)
    log.debug('Failed to decrypt an AES-GCM value.')
    return None


def _windows_master_key(local_state: Mapping[str, Any]) -> bytes | None:
    from base64 import b64decode  # ruff:ignore[import-outside-top-level]

    encoded = local_state.get('os_crypt', {}).get('encrypted_key')
    if not encoded:
        return None
    with suppress(ValueError):
        blob = b64decode(encoded)
        if blob.startswith(b'DPAPI'):
            return _windows_dpapi_decrypt(blob[5:])
    return None


def _windows_dpapi_decrypt(blob: bytes) -> bytes | None:  # pragma: no cover
    import ctypes  # ruff:ignore[import-outside-top-level]
    import ctypes.wintypes  # ruff:ignore[import-outside-top-level]

    class DataBlob(ctypes.Structure):
        if TYPE_CHECKING:
            cbData: int  # noqa: N815
            pbData: Any  # noqa: N815
        _fields_: ClassVar[list[tuple[str, Any]]] = [('cbData', ctypes.wintypes.DWORD),
                                                     ('pbData', ctypes.POINTER(ctypes.c_char))]

    buffer_in = DataBlob(len(blob), ctypes.create_string_buffer(blob, len(blob)))
    buffer_out = DataBlob()
    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined] # ty: ignore[unresolved-attribute]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined] # ty: ignore[unresolved-attribute]
    if not crypt32.CryptUnprotectData(ctypes.byref(buffer_in), None, None, None, None, 0,
                                      ctypes.byref(buffer_out)):
        log.debug('CryptUnprotectData failed.')
        return None
    try:
        return ctypes.string_at(buffer_out.pbData, buffer_out.cbData)
    finally:
        kernel32.LocalFree(buffer_out.pbData)


def _macos_password(keyring_name: str) -> bytes | None:
    import keyring  # ruff:ignore[import-outside-top-level]

    with suppress(Exception):
        if password := keyring.get_password(f'{keyring_name} Safe Storage', keyring_name):
            return password.encode()
    return None


def linux_keyring_password(keyring_name: str = 'Chrome') -> bytes | None:
    """
    Read the browser's ``Safe Storage`` password from the desktop keyring.

    ``secret-tool`` is tried first because the browser writes its libsecret entry with an
    ``application`` attribute rather than the ``service``/``username`` pair the :py:mod:`keyring`
    package looks for. KWallet and :py:mod:`keyring` are tried after it.

    Parameters
    ----------
    keyring_name : str
        Name the browser registers under, such as ``'Chrome'`` or ``'Chromium'``.

    Returns
    -------
    bytes | None
        The password, or ``None`` if no keyring yielded one.
    """
    for reader in (_secret_service_password, _secret_tool_password, _kwallet_password,
                   _keyring_module_password):
        if password := reader(keyring_name):
            log.debug('%s returned a %d byte password for `%s`.', reader.__name__, len(password),
                      keyring_name)
            return password
        log.debug('%s returned nothing for `%s`.', reader.__name__, keyring_name)
    log.debug('No keyring returned a password for `%s`.', keyring_name)
    return None


def _run_for_output(args: Sequence[str]) -> bytes | None:
    if not which(args[0]):
        log.debug('`%s` is not installed.', args[0])
        return None
    with suppress(OSError, sp.SubprocessError):
        result = sp.run(args, capture_output=True, check=False)
        if result.returncode == 0:
            return result.stdout
        log.debug('`%s` exited %d: %s', args[0], result.returncode,
                  (result.stderr or b'').decode(errors='replace').strip())
    return None


def _secret_service_password(keyring_name: str) -> bytes | None:
    # The browser stores its key with an `application` attribute rather than the service and
    # username pair the keyring package searches by, so the collection is searched directly. This
    # needs no `secret-tool` binary, which is packaged separately from the keyring daemon itself.
    import secretstorage  # ruff:ignore[import-outside-top-level]

    application = 'chromium' if keyring_name == 'Chromium' else 'chrome'
    try:
        with closing(secretstorage.dbus_init()) as connection:
            return _search_secret_service(connection, application)
    except Exception as e:  # noqa: BLE001
        log.debug('Secret Service lookup failed: %s: %s', type(e).__name__, e)
    return None


def _search_secret_service(connection: Any, application: str) -> bytes | None:
    import secretstorage  # ruff:ignore[import-outside-top-level]

    for attributes in ({
            'application': application,
            'xdg:schema': _LIBSECRET_SCHEMA
    }, {
            'application': application
    }, {}):
        found = 0
        for item in secretstorage.search_items(connection, attributes):
            found += 1
            if not _matches_browser(item, application):
                continue
            if item.is_locked():
                item.unlock()
            if secret := item.get_secret():
                return bytes(secret)
        log.debug('Secret Service search %r matched %d items, none usable.', attributes, found)
    return None


def _matches_browser(item: Any, application: str) -> bool:
    with suppress(Exception):
        attributes = item.get_attributes()
        if attributes.get('application') == application:
            return True
        if attributes:
            return False
    with suppress(Exception):
        return 'safe storage' in item.get_label().casefold()
    return False


def _secret_tool_password(keyring_name: str) -> bytes | None:
    application = 'chromium' if keyring_name == 'Chromium' else 'chrome'
    output = _run_for_output(('secret-tool', 'lookup', 'application', application))
    return output.rstrip(b'\n') if output else None


def _kwallet_network_wallet() -> str:
    for service, path in (('org.kde.kwalletd6', '/modules/kwalletd6'), ('org.kde.kwalletd5',
                                                                        '/modules/kwalletd5')):
        output = _run_for_output(('dbus-send', '--session', '--print-reply=literal',
                                  f'--dest={service}', path, 'org.kde.KWallet.networkWallet'))
        if output and (name := output.decode(errors='replace').strip()):
            return name
    return 'kdewallet'


def _kwallet_password(keyring_name: str) -> bytes | None:
    output = _run_for_output(('kwallet-query', '--read-password', f'{keyring_name} Safe Storage',
                              '--folder', f'{keyring_name} Keys', _kwallet_network_wallet()))
    if not output or output.lower().startswith(b'failed to read'):
        return None
    return output.rstrip(b'\n') or None


def _keyring_module_password(keyring_name: str) -> bytes | None:
    import keyring  # ruff:ignore[import-outside-top-level]

    with suppress(Exception):
        if password := keyring.get_password(f'{keyring_name} Safe Storage', keyring_name):
            return password.encode()
    return None
