from __future__ import annotations

from base64 import b64encode
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any, get_args
import ctypes
import json
import sqlite3
import subprocess as sp
import sys
import types

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, aead, algorithms, modes
from cryptography.hazmat.primitives.kdf import pbkdf2
import pytest

from deltona.chrome import (
    CHANNEL_CACHE_DIRECTORIES,
    CHANNEL_DIRECTORIES,
    KEYRING_NAMES,
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
from deltona.chrome.typing import ChromeChannel
from deltona.commands.chrome import chrome_dump
from deltona.commands.chrome_common import echo_json, echo_mapping, echo_rows, echo_tree
from deltona.commands.chrome_core import dig

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Mapping, Sequence

    from click.testing import CliRunner
    from pytest_mock import MockerFixture

    from .conftest import FakeChromeUserData

DT_2020_01_01 = datetime(2020, 1, 1, tzinfo=timezone.utc)
UNIX_2020_01_01 = 1577836800
WEBKIT_2020_01_01 = 13222310400000000
WEBKIT_MILLISECONDS_2020_01_01 = 13222310400000
SQLITE_MAGIC = b'SQLite format 3\x00'
# The ciphertext of this plaintext under the v10 key is printable ASCII, so the blob survives a
# round trip through :py:class:`str`.
ASCII_PLAINTEXT = b'secret-4481144'


def derive_key(password: bytes, iterations: int = 1) -> bytes:
    return pbkdf2.PBKDF2HMAC(
        algorithm=hashes.SHA1(),  # noqa: S303
        iterations=iterations,
        length=16,
        salt=b'saltysalt').derive(password)


def encrypt_cbc(plaintext: bytes,
                key: bytes,
                *,
                hash_prefix: bool = False,
                version: bytes = b'v10') -> bytes:
    body = (sha256(b'example.com').digest() + plaintext) if hash_prefix else plaintext
    padding = 16 - (len(body) % 16)
    body += bytes([padding]) * padding
    encryptor = Cipher(algorithms.AES(key), modes.CBC(b' ' * 16)).encryptor()
    return version + encryptor.update(body) + encryptor.finalize()


def encrypt_gcm(plaintext: bytes, key: bytes) -> bytes:
    nonce = bytes(range(12))
    return b'v10' + nonce + aead.AESGCM(key).encrypt(nonce, plaintext, None)


def install_windows_crypt_api(mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch,
                              payload: bytes | None) -> None:
    wintypes = types.ModuleType('ctypes.wintypes')
    vars(wintypes)['DWORD'] = ctypes.c_uint32
    monkeypatch.setitem(sys.modules, 'ctypes.wintypes', wintypes)
    monkeypatch.setattr(ctypes, 'wintypes', wintypes, raising=False)
    buffers: list[Any] = []

    def unprotect(_source: Any, _description: Any, _entropy: Any, _reserved: Any, _prompt: Any,
                  _flags: int, target: Any) -> int:
        if payload is None:
            return 0
        buffer = ctypes.create_string_buffer(payload, len(payload))
        buffers.append(buffer)
        blob = target._obj  # noqa: SLF001
        blob.cbData = len(payload)
        blob.pbData = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))
        return 1

    windll = mocker.MagicMock()
    windll.crypt32.CryptUnprotectData.side_effect = unprotect
    monkeypatch.setattr(ctypes, 'windll', windll, raising=False)


def which_for(available: Collection[str]) -> Callable[[str], str | None]:
    return lambda name: f'/usr/bin/{name}' if name in available else None


def run_for(
    outputs: Mapping[str, Sequence[tuple[int, bytes] | BaseException]]
) -> Callable[..., sp.CompletedProcess[bytes]]:
    pending = {name: list(results) for name, results in outputs.items()}

    def run(args: Sequence[str], **_kwargs: Any) -> sp.CompletedProcess[bytes]:
        queue = pending[args[0]]
        result = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(result, BaseException):
            raise result
        return sp.CompletedProcess(args=list(args), returncode=result[0], stdout=result[1])

    return run


class FakeSecretItem:
    def __init__(self,
                 secret: bytes,
                 *,
                 application: str = 'chrome',
                 label: str = 'Chrome Safe Storage',
                 locked: bool = False) -> None:
        self.secret = secret
        self.application = application
        self.label = label
        self.locked = locked
        self.unlocked = False

    def get_attributes(self) -> dict[str, str]:
        return {'application': self.application} if self.application else {}

    def get_label(self) -> str:
        return self.label

    def is_locked(self) -> bool:
        return self.locked

    def unlock(self) -> None:
        self.unlocked = True
        self.locked = False

    def get_secret(self) -> bytes:
        return self.secret


def keyring_setup(mocker: MockerFixture,
                  available: Collection[str],
                  outputs: Mapping[str, Sequence[tuple[int, bytes] | BaseException]],
                  password: str | BaseException | None,
                  items: Sequence[FakeSecretItem] | BaseException | None = None) -> None:
    if isinstance(items, BaseException) or items is None:
        mocker.patch('secretstorage.dbus_init', side_effect=items or RuntimeError('no session bus'))
    else:
        mocker.patch('secretstorage.dbus_init', return_value=mocker.MagicMock())
        mocker.patch('secretstorage.search_items', side_effect=[items, [], []])
    mocker.patch('deltona.chrome.core.which', side_effect=which_for(available))
    mocker.patch('subprocess.run', side_effect=run_for(outputs))
    if isinstance(password, BaseException):
        mocker.patch('keyring.get_password', side_effect=password)
    else:
        mocker.patch('keyring.get_password', return_value=password)


def test_channel_tables_cover_every_channel() -> None:
    channels = set(get_args(ChromeChannel))
    assert set(KEYRING_NAMES) == channels
    assert set(CHANNEL_CACHE_DIRECTORIES['linux']) == channels
    assert all(set(directories) == channels for directories in CHANNEL_DIRECTORIES.values())


@pytest.mark.parametrize(('platform', 'channel', 'expected'), [
    ('linux', 'stable', 'config/google-chrome'),
    ('linux', 'dev', 'config/google-chrome-unstable'),
    ('darwin', 'beta', 'data/Google/Chrome Beta'),
    ('win32', 'canary', 'data/Google/Chrome SxS/User Data'),
    ('cygwin', 'chromium', 'data/Chromium/User Data'),
])
def test_chrome_config_directory(mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch,
                                 tmp_path: Path, platform: str, channel: ChromeChannel,
                                 expected: str) -> None:
    monkeypatch.setattr(sys, 'platform', platform)
    mocker.patch('platformdirs.user_data_dir', return_value=str(tmp_path / 'data'))
    mocker.patch('platformdirs.user_config_dir', return_value=str(tmp_path / 'config'))
    assert chrome_config_directory(channel) == tmp_path / expected


@pytest.mark.parametrize(('platform', 'channel', 'expected'), [
    ('linux', 'stable', 'cache/google-chrome'),
    ('darwin', 'dev', 'cache/Google/Chrome Dev'),
    ('win32', 'stable', 'data/Google/Chrome/User Data'),
])
def test_chrome_cache_directory(mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch,
                                tmp_path: Path, platform: str, channel: ChromeChannel,
                                expected: str) -> None:
    monkeypatch.setattr(sys, 'platform', platform)
    mocker.patch('platformdirs.user_cache_dir', return_value=str(tmp_path / 'cache'))
    mocker.patch('platformdirs.user_data_dir', return_value=str(tmp_path / 'data'))
    assert chrome_cache_directory(channel) == tmp_path / expected


@pytest.mark.parametrize(('value', 'expected'), [
    (None, None),
    (0, None),
    ('', None),
    ('0', None),
    ('nonsense', None),
    (float('inf'), None),
    (WEBKIT_2020_01_01, DT_2020_01_01),
])
def test_webkit_timestamp_to_datetime(value: float | str | None, expected: datetime | None) -> None:
    assert webkit_timestamp_to_datetime(value) == expected


@pytest.mark.parametrize(('value', 'expected'), [
    (None, None),
    (0, None),
    ('0.0', None),
    ('nonsense', None),
    (1e300, None),
    (UNIX_2020_01_01, DT_2020_01_01),
])
def test_unix_timestamp_to_datetime(value: float | str | None, expected: datetime | None) -> None:
    assert unix_timestamp_to_datetime(value) == expected


@pytest.mark.parametrize(('value', 'expected'), [
    (None, None),
    (0, None),
    ('nonsense', None),
    (UNIX_2020_01_01, DT_2020_01_01),
    (WEBKIT_MILLISECONDS_2020_01_01, DT_2020_01_01),
    (WEBKIT_2020_01_01, DT_2020_01_01),
])
def test_chrome_timestamp_to_datetime(value: float | str | None, expected: datetime | None) -> None:
    assert chrome_timestamp_to_datetime(value) == expected


def test_open_database_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError), open_database(tmp_path / 'Nothing'):
        pass


def test_open_database_copies_write_ahead_log(chrome_user_data: FakeChromeUserData) -> None:
    path = chrome_user_data.write_database('Default', 'Journalled', ('CREATE TABLE t(a)',))
    connection = sqlite3.connect(path)
    try:
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute("INSERT INTO t VALUES ('written')")
        connection.commit()
        assert path.with_name('Journalled-wal').is_file()
        assert query_database(path, 'SELECT a FROM t') == [{'a': 'written'}]
    finally:
        connection.close()


def test_open_database_returns_bytes_for_invalid_utf8(chrome_user_data: FakeChromeUserData) -> None:
    path = chrome_user_data.write_database('Default', 'Mixed', ('CREATE TABLE t(a TEXT)',))
    connection = sqlite3.connect(path)
    try:
        connection.execute("INSERT INTO t VALUES (CAST(x'FFFE' AS TEXT))")
        connection.execute("INSERT INTO t VALUES ('readable')")
        connection.commit()
    finally:
        connection.close()
    assert query_database(path, 'SELECT a FROM t ORDER BY rowid') == [{
        'a': b'\xff\xfe'
    }, {
        'a': 'readable'
    }]


def test_table_names(chrome_user_data: FakeChromeUserData) -> None:
    path = chrome_user_data.write_database('Default', 'Two',
                                           ('CREATE TABLE b(x)', 'CREATE TABLE a(x)'))
    assert table_names(path) == ('a', 'b')


def test_database_summary_with_meta(chrome_user_data: FakeChromeUserData) -> None:
    path = chrome_user_data.write_database('Default',
                                           'Web Data', ('CREATE TABLE autofill(x)',),
                                           meta={
                                               'last_compatible_version': '83',
                                               'version': '117'
                                           })
    summary = database_summary(path)
    assert summary['name'] == 'Web Data'
    assert summary['size'] > 0
    assert summary['version'] == '117'
    assert summary['last_compatible_version'] == '83'
    assert summary['tables'] == ['autofill', 'meta']


def test_database_summary_without_meta(chrome_user_data: FakeChromeUserData) -> None:
    path = chrome_user_data.write_database('Default', 'Plain', ('CREATE TABLE only(x)',))
    summary = database_summary(path)
    assert summary['version'] is None
    assert summary['last_compatible_version'] is None
    assert summary['tables'] == ['only']


def test_database_summary_unreadable(chrome_user_data: FakeChromeUserData) -> None:
    path = chrome_user_data.write_text('Default', 'NotADatabase', 'plain text')
    summary = database_summary(path)
    assert summary['tables'] == []
    assert summary['version'] is None


@pytest.mark.parametrize(('content', 'expected'), [
    (SQLITE_MAGIC + b'\x00' * 16, 'sqlite'),
    (b'{"a": 1}', 'json'),
    (b'[1, 2]', 'json'),
    (b'plain text', 'text'),
    (b'\xff\xfe\x00\x01binary data here', 'binary'),
    (b'', 'empty'),
])
def test_classify_path_files(tmp_path: Path, content: bytes, expected: str) -> None:
    path = tmp_path / 'candidate'
    path.write_bytes(content)
    assert classify_path(path) == expected


def test_classify_path_leveldb(tmp_path: Path) -> None:
    (tmp_path / 'Local Storage').mkdir()
    (tmp_path / 'Local Storage' / 'CURRENT').write_text('MANIFEST-000001\n', encoding='utf-8')
    assert classify_path(tmp_path / 'Local Storage') == 'leveldb'


def test_classify_path_directory(tmp_path: Path) -> None:
    (tmp_path / 'Extensions').mkdir()
    assert classify_path(tmp_path / 'Extensions') == 'directory'


def test_classify_path_missing(tmp_path: Path) -> None:
    assert classify_path(tmp_path / 'gone') == 'binary'


def test_profile_files_not_a_directory(tmp_path: Path) -> None:
    assert list(profile_files(tmp_path / 'gone')) == []


def test_profile_files(chrome_user_data: FakeChromeUserData) -> None:
    path = chrome_user_data.add_profile()
    chrome_user_data.write_text('Default', 'Note', 'hello')
    (path / 'Sub').mkdir()
    (path / 'Sub' / 'inner').write_bytes(b'12345')
    entries = {entry['name']: entry for entry in profile_files(path)}
    assert entries['Note']['kind'] == 'text'
    assert entries['Note']['size'] == 5
    assert entries['Sub']['kind'] == 'directory'
    assert entries['Sub']['size'] == 5
    assert isinstance(entries['Note']['modified'], datetime)


def test_is_sqlite_database(chrome_user_data: FakeChromeUserData) -> None:
    database = chrome_user_data.write_database('Default', 'Real', ('CREATE TABLE t(x)',))
    text = chrome_user_data.write_text('Default', 'Fake', 'not a database')
    assert is_sqlite_database(database)
    assert not is_sqlite_database(text)
    assert not is_sqlite_database(chrome_user_data.config_path / 'Default' / 'gone')


def test_chrome_profile_properties(chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Profile 1',
                                 active_time=UNIX_2020_01_01,
                                 gaia_given_name='Ann',
                                 gaia_name='Ann Example',
                                 name='Work',
                                 user_name='ann@example.com')
    chrome_user_data.add_profile('Profile 2')
    user_data = ChromeUserData(chrome_user_data.config_path, chrome_user_data.cache_path)
    first, second = user_data.profiles()
    assert first.directory == 'Profile 1'
    assert first.name == 'Work'
    assert first.email == 'ann@example.com'
    assert first.gaia_name == 'Ann Example'
    assert first.active_time == DT_2020_01_01
    assert first.aliases() == ('Profile 1', 'Work', 'Ann Example', 'Ann', 'ann@example.com')
    assert first.cache_path == chrome_user_data.cache_path / 'Profile 1'
    assert second.name == 'Profile 2'
    assert second.email is None
    assert second.gaia_name is None
    assert second.active_time is None


def test_chrome_user_data_defaults() -> None:
    user_data = ChromeUserData()
    assert user_data.channel == 'stable'
    assert user_data.config_path == chrome_config_directory('stable')
    assert user_data.cache_path == chrome_cache_directory('stable')
    assert user_data.keyring_name == 'Chrome'


def test_chrome_user_data_local_state_missing(tmp_path: Path) -> None:
    assert ChromeUserData(tmp_path / 'gone').local_state == {}


def test_chrome_user_data_local_state_unreadable(chrome_user_data: FakeChromeUserData) -> None:
    (chrome_user_data.config_path / 'Local State').write_text('{ not json', encoding='utf-8')
    assert ChromeUserData(chrome_user_data.config_path).local_state == {}


def test_chrome_user_data_profiles_default_first(chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Profile 3')
    chrome_user_data.add_profile('Default')
    unregistered = chrome_user_data.config_path / 'Profile 9'
    unregistered.mkdir()
    (unregistered / 'Preferences').write_text('{}', encoding='utf-8')
    (chrome_user_data.config_path / 'System Profile').mkdir()
    user_data = ChromeUserData(chrome_user_data.config_path, chrome_user_data.cache_path)
    assert [p.directory for p in user_data.profiles()] == ['Default', 'Profile 3', 'Profile 9']


def test_chrome_user_data_profile_matches_alias(chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Profile 1', name='Work', user_name='ann@example.com')
    user_data = ChromeUserData(chrome_user_data.config_path, chrome_user_data.cache_path)
    assert user_data.profile('ANN@example.com').directory == 'Profile 1'


def test_chrome_user_data_profile_not_found(chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    user_data = ChromeUserData(chrome_user_data.config_path, chrome_user_data.cache_path)
    with pytest.raises(ProfileNotFound) as excinfo:
        user_data.profile('missing')
    assert str(excinfo.value) == "No profile matching 'missing'. Available: 'Default'"


def test_chrome_user_data_profile_not_found_without_profiles(tmp_path: Path) -> None:
    with pytest.raises(ProfileNotFound) as excinfo:
        ChromeUserData(tmp_path / 'gone').profile('missing')
    assert str(excinfo.value) == "No profile matching 'missing'."


def test_chrome_user_data_cache_path_on_windows(chrome_user_data: FakeChromeUserData,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    chrome_user_data.add_profile('Default')
    monkeypatch.setattr(sys, 'platform', 'win32')
    user_data = ChromeUserData(chrome_user_data.config_path, chrome_user_data.cache_path)
    assert user_data.profile().cache_path == chrome_user_data.config_path / 'Default'


@pytest.mark.parametrize('value', [None, b''])
def test_oscrypt_decrypt_empty(monkeypatch: pytest.MonkeyPatch, value: bytes | None) -> None:
    monkeypatch.setattr(sys, 'platform', 'linux')
    assert OSCrypt().decrypt(value) is None


def test_oscrypt_decrypt_v10(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, 'platform', 'linux')
    crypt = OSCrypt()
    assert crypt.available
    assert crypt.decrypt(encrypt_cbc(b'secret', derive_key(b'peanuts'))) == 'secret'


def test_oscrypt_decrypt_str_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, 'platform', 'linux')
    blob = encrypt_cbc(ASCII_PLAINTEXT, derive_key(b'peanuts'))
    assert OSCrypt().decrypt(blob.decode()) == ASCII_PLAINTEXT.decode()


def test_oscrypt_decrypt_empty_password_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, 'platform', 'linux')
    assert OSCrypt().decrypt(encrypt_cbc(b'secret', derive_key(b''))) == 'secret'


def test_oscrypt_decrypt_hash_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, 'platform', 'linux')
    blob = encrypt_cbc(b'secret', derive_key(b'peanuts'), hash_prefix=True)
    crypt = OSCrypt()
    assert crypt.decrypt(blob, hash_prefix=True) == 'secret'
    kept = crypt.decrypt(blob)
    assert kept is not None
    assert kept.endswith('secret')
    assert len(kept) > len('secret')


def test_oscrypt_decrypt_hash_prefix_shorter_than_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, 'platform', 'linux')
    blob = encrypt_cbc(b'tiny', derive_key(b'peanuts'))
    assert OSCrypt().decrypt(blob, hash_prefix=True) == 'tiny'


def test_oscrypt_decrypt_wrong_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, 'platform', 'linux')
    assert OSCrypt().decrypt(encrypt_cbc(b'secret', derive_key(b'wrong'))) is None


def test_oscrypt_decrypt_short_ciphertext(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, 'platform', 'linux')
    assert OSCrypt().decrypt(b'v10short') is None


def test_oscrypt_decrypt_unknown_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, 'platform', 'linux')
    assert OSCrypt().decrypt(b'v99' + b'\x00' * 16) is None


def test_oscrypt_decrypt_v11(mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, 'platform', 'linux')
    keyring_setup(mocker, {'secret-tool'}, {'secret-tool': [(0, b'wallet-password\n')]}, None)
    blob = encrypt_cbc(b'secret', derive_key(b'wallet-password'), version=b'v11')
    assert OSCrypt('Chrome').decrypt(blob) == 'secret'


def test_oscrypt_decrypt_v11_without_keyring(mocker: MockerFixture,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, 'platform', 'linux')
    keyring_setup(mocker, set(), {}, None)
    blob = encrypt_cbc(b'secret', derive_key(b'wallet-password'), version=b'v11')
    assert OSCrypt('Chrome').decrypt(blob) is None


def test_oscrypt_macos(mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, 'platform', 'darwin')
    mocker.patch('keyring.get_password', return_value='mac-password')
    crypt = OSCrypt('Chrome')
    assert crypt.available
    blob = encrypt_cbc(b'secret', derive_key(b'mac-password', 1003))
    assert crypt.decrypt(blob) == 'secret'


def test_oscrypt_macos_without_password(mocker: MockerFixture,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, 'platform', 'darwin')
    mocker.patch('keyring.get_password', return_value=None)
    crypt = OSCrypt('Chrome')
    assert not crypt.available
    assert crypt.decrypt(encrypt_cbc(b'secret', derive_key(b'mac-password', 1003))) is None


def test_oscrypt_macos_keyring_raises(mocker: MockerFixture,
                                      monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, 'platform', 'darwin')
    mocker.patch('keyring.get_password', side_effect=RuntimeError('no keyring'))
    assert not OSCrypt('Chrome').available


def test_oscrypt_macos_unknown_version(mocker: MockerFixture,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, 'platform', 'darwin')
    mocker.patch('keyring.get_password', return_value='mac-password')
    assert OSCrypt('Chrome').decrypt('plain text') == 'plain text'


def test_oscrypt_windows_gcm(mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    key = bytes(range(32))
    install_windows_crypt_api(mocker, monkeypatch, key)
    monkeypatch.setattr(sys, 'platform', 'win32')
    local_state = {'os_crypt': {'encrypted_key': b64encode(b'DPAPIwrapped').decode()}}
    crypt = OSCrypt('Chrome', local_state)
    assert crypt.available
    assert crypt.decrypt(encrypt_gcm(b'secret', key)) == 'secret'


def test_oscrypt_windows_gcm_bad_tag(mocker: MockerFixture,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
    key = bytes(range(32))
    install_windows_crypt_api(mocker, monkeypatch, key)
    monkeypatch.setattr(sys, 'platform', 'win32')
    local_state = {'os_crypt': {'encrypted_key': b64encode(b'DPAPIwrapped').decode()}}
    blob = bytearray(encrypt_gcm(b'secret', key))
    blob[-1] ^= 0xFF
    assert OSCrypt('Chrome', local_state).decrypt(bytes(blob)) is None


def test_oscrypt_windows_gcm_too_short(mocker: MockerFixture,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    install_windows_crypt_api(mocker, monkeypatch, bytes(range(32)))
    monkeypatch.setattr(sys, 'platform', 'win32')
    local_state = {'os_crypt': {'encrypted_key': b64encode(b'DPAPIwrapped').decode()}}
    assert OSCrypt('Chrome', local_state).decrypt(b'v10' + b'\x00' * 8) is None


def test_oscrypt_windows_dpapi_value(mocker: MockerFixture,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
    install_windows_crypt_api(mocker, monkeypatch, b'legacy secret')
    monkeypatch.setattr(sys, 'platform', 'win32')
    assert OSCrypt('Chrome').decrypt(b'\x01\x00\x00\x00wrapped') == 'legacy secret'


def test_oscrypt_windows_dpapi_failure(mocker: MockerFixture,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    install_windows_crypt_api(mocker, monkeypatch, None)
    monkeypatch.setattr(sys, 'platform', 'win32')
    local_state = {'os_crypt': {'encrypted_key': b64encode(b'DPAPIwrapped').decode()}}
    crypt = OSCrypt('Chrome', local_state)
    assert not crypt.available
    assert crypt.decrypt(b'v10' + b'\x00' * 28) is None


@pytest.mark.parametrize('encrypted_key', ['', b64encode(b'OTHERwrapped').decode(), '!!!not b64'])
def test_oscrypt_windows_master_key_unusable(mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch,
                                             encrypted_key: str) -> None:
    install_windows_crypt_api(mocker, monkeypatch, b'unused')
    monkeypatch.setattr(sys, 'platform', 'win32')
    assert not OSCrypt('Chrome', {'os_crypt': {'encrypted_key': encrypted_key}}).available


@pytest.mark.parametrize(('keyring_name', 'application'), [('Chrome', 'chrome'),
                                                           ('Chromium', 'chromium')])
def test_linux_keyring_password_secret_tool(mocker: MockerFixture, keyring_name: str,
                                            application: str) -> None:
    run = mocker.patch('subprocess.run',
                       side_effect=run_for({'secret-tool': [(0, b'from-secret-tool\n')]}))
    mocker.patch('deltona.chrome.core.which', side_effect=which_for({'secret-tool'}))
    assert b'from-secret-tool' in linux_keyring_passwords(keyring_name)
    assert run.call_args[0][0] == ('secret-tool', 'lookup', 'application', application)


def test_linux_keyring_password_kwallet(mocker: MockerFixture) -> None:
    run = mocker.patch('subprocess.run',
                       side_effect=run_for({
                           'dbus-send': [(0, b'  \n'), (0, b'wallet6\n')],
                           'kwallet-query': [(0, b'from-kwallet\n')]
                       }))
    mocker.patch('deltona.chrome.core.which', side_effect=which_for({'dbus-send', 'kwallet-query'}))
    assert b'from-kwallet' in linux_keyring_passwords('Chrome')
    assert run.call_args[0][0][-1] == 'wallet6'


def test_linux_keyring_password_kwallet_default_wallet(mocker: MockerFixture) -> None:
    run = mocker.patch('subprocess.run',
                       side_effect=run_for({'kwallet-query': [(0, b'from-kwallet\n')]}))
    mocker.patch('deltona.chrome.core.which', side_effect=which_for({'kwallet-query'}))
    assert b'from-kwallet' in linux_keyring_passwords('Chrome')
    assert run.call_args[0][0][-1] == 'kdewallet'


@pytest.mark.parametrize('output', [b'Failed to read password\n', b'\n'])
def test_linux_keyring_password_kwallet_unusable(mocker: MockerFixture, output: bytes) -> None:
    keyring_setup(mocker, {'kwallet-query'}, {'kwallet-query': [(0, output)]}, 'from-keyring')
    assert b'from-keyring' in linux_keyring_passwords('Chrome')


@pytest.mark.parametrize(
    'result',
    [(1, b'ignored'), OSError('no such command'),
     sp.SubprocessError('broken')])
def test_linux_keyring_password_process_failures(mocker: MockerFixture,
                                                 result: tuple[int, bytes] | BaseException) -> None:
    keyring_setup(mocker, {'secret-tool'}, {'secret-tool': [result]}, 'from-keyring')
    assert b'from-keyring' in linux_keyring_passwords('Chrome')


def test_linux_keyring_password_none(mocker: MockerFixture) -> None:
    keyring_setup(mocker, set(), {}, None)
    assert linux_keyring_passwords('Chrome') == ()


def test_linux_keyring_password_keyring_raises(mocker: MockerFixture) -> None:
    keyring_setup(mocker, set(), {}, RuntimeError('locked'))
    assert linux_keyring_passwords('Chrome') == ()


@pytest.mark.parametrize(('key', 'expected'), [
    ('a.b', 'value'),
    ('a.list.1', 'second'),
    ('a.missing', None),
    ('a.list.9', None),
    ('a.list.x', None),
])
def test_dig(key: str, expected: Any) -> None:
    data = {'a': {'b': 'value', 'list': ['first', 'second']}}
    assert dig(data, key) == expected


def test_echo_json_conversions(capsys: pytest.CaptureFixture[str]) -> None:
    echo_json({
        'binary': b'\x01\x02',
        'buffer': bytearray(b'\x03'),
        'path': Path('/var/data/example'),
        'tags': {'b', 'a'},
        'text': 'café ☕',
        'unsupported': ProfileNotFound('x'),
        'when': DT_2020_01_01
    })
    output = capsys.readouterr().out
    assert '\\u' not in output
    assert 'café ☕' in output
    assert json.loads(output) == {
        'binary': '0102',
        'buffer': '03',
        'path': '/var/data/example',
        'tags': ['a', 'b'],
        'text': 'café ☕',
        'unsupported': "No profile matching 'x'.",
        'when': '2020-01-01T00:00:00+00:00'
    }


def test_echo_rows_json(capsys: pytest.CaptureFixture[str]) -> None:
    echo_rows([{'a': 1}], as_json=True, title='Things')
    assert json.loads(capsys.readouterr().out) == [{'a': 1}]


def test_echo_rows_empty(capsys: pytest.CaptureFixture[str]) -> None:
    echo_rows([], as_json=False, title='Things')
    assert capsys.readouterr().err == 'No things found.\n'


def test_echo_rows_table(capsys: pytest.CaptureFixture[str],
                         monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('COLUMNS', '200')
    echo_rows([{
        'active_time': DT_2020_01_01,
        'blob': b'\xff',
        'listed': [1, 2],
        'nothing': None,
        'number': 7,
        'pair': ('x', 'y'),
        'settings': {
            'k': 'v'
        },
        'wanted': True,
        'unwanted': False
    }],
              as_json=False,
              title='Values')
    output = capsys.readouterr().out
    assert 'Active Time' in output
    assert '2020-01-01 00:00:00' in output
    assert 'ff' in output
    assert '[1, 2]' in output
    assert '["x", "y"]' in output
    assert '{"k": "v"}' in output
    assert 'yes' in output
    assert 'no' in output


def test_echo_rows_explicit_columns(capsys: pytest.CaptureFixture[str],
                                    monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('COLUMNS', '200')
    echo_rows([{'a': 'shown', 'b': 'hidden'}], as_json=False, columns=('a',), title='Values')
    output = capsys.readouterr().out
    assert 'shown' in output
    assert 'hidden' not in output


def test_echo_mapping(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('COLUMNS', '200')
    echo_mapping({'b': 2, 'a': 1}, as_json=False, title='Settings')
    output = capsys.readouterr().out
    assert output.index('a') < output.index('b')


def test_echo_mapping_json(capsys: pytest.CaptureFixture[str]) -> None:
    echo_mapping({'a': 1}, as_json=True, title='Settings')
    assert json.loads(capsys.readouterr().out) == {'a': 1}


def test_echo_tree(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('COLUMNS', '200')
    echo_tree({'a': [1, 2]}, as_json=False, title='Tree')
    output = capsys.readouterr().out
    assert 'Tree' in output
    assert '"a"' in output


def test_echo_tree_json(capsys: pytest.CaptureFixture[str]) -> None:
    echo_tree({'a': [1, 2]}, as_json=True, title='Tree')
    assert json.loads(capsys.readouterr().out) == {'a': [1, 2]}


def test_chrome_dump_lists_commands(runner: CliRunner) -> None:
    result = runner.invoke(chrome_dump, ['--help'])
    assert result.exit_code == 0
    assert 'list-profiles' in result.output
    assert 'list-flags' in result.output


def test_chrome_dump_unknown_command(runner: CliRunner,
                                     chrome_user_data: FakeChromeUserData) -> None:
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'not-a-command'])
    assert result.exit_code == 2
    assert 'No such command' in result.stderr


def test_chrome_dump_channel_and_debug(runner: CliRunner, chrome_user_data: FakeChromeUserData,
                                       mocker: MockerFixture) -> None:
    setup_logging = mocker.patch('deltona.commands.chrome.setup_logging')
    result = runner.invoke(
        chrome_dump, [*chrome_user_data.argv, '--channel', 'chromium', '-d', 'list-profiles', '-j'])
    assert result.exit_code == 0
    assert setup_logging.call_args.kwargs['debug'] is True


def test_list_profiles_json(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default',
                                 hosted_domain='example.com',
                                 is_ephemeral=True,
                                 name='Personal')
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-profiles', '-j'])
    assert result.exit_code == 0
    rows = json.loads(result.output)
    assert rows[0]['directory'] == 'Default'
    assert rows[0]['name'] == 'Personal'
    assert rows[0]['hosted_domain'] == 'example.com'
    assert rows[0]['ephemeral'] is True


def test_list_profiles_table(runner: CliRunner, chrome_user_data: FakeChromeUserData,
                             monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('COLUMNS', '200')
    chrome_user_data.add_profile('Default', name='Personal')
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-profiles'])
    assert result.exit_code == 0
    assert 'Personal' in result.output


def test_local_state(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.local_state['browser']['enabled_labs_experiments'] = ['a@1']
    chrome_user_data.write_local_state()
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'local-state', '-j'])
    assert result.exit_code == 0
    assert json.loads(result.output)['browser']['enabled_labs_experiments'] == ['a@1']


def test_local_state_key(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.local_state['browser']['enabled_labs_experiments'] = ['a@1']
    chrome_user_data.write_local_state()
    result = runner.invoke(
        chrome_dump,
        [*chrome_user_data.argv, 'local-state', '-k', 'browser.enabled_labs_experiments', '-j'])
    assert result.exit_code == 0
    assert json.loads(result.output) == ['a@1']


def test_local_state_missing(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(chrome_dump, ['-c', str(tmp_path / 'empty'), 'local-state'])
    assert result.exit_code == 1
    assert 'does not exist' in result.stderr


def test_local_state_unreadable(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    (chrome_user_data.config_path / 'Local State').write_text('{ not json', encoding='utf-8')
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'local-state'])
    assert result.exit_code == 1
    assert 'could not be read' in result.stderr


def test_preferences_raw(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    chrome_user_data.write_json('Default', 'Preferences', {'download': {'prompt': True}})
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'preferences', '--raw', '-j'])
    assert result.exit_code == 0
    assert json.loads(result.output) == {'download': {'prompt': True}}


def test_preferences_summary(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    chrome_user_data.write_json('Default', 'Preferences', {'enable_do_not_track': True})
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'preferences', '-j'])
    assert result.exit_code == 0
    rows = {row['key']: row for row in json.loads(result.output)}
    assert rows['enable_do_not_track']['value'] == 'On'
    assert rows['enable_do_not_track']['source'] == 'profile'
    assert rows['safebrowsing.enabled']['source'] == 'default'


def test_preferences_summary_changed_and_section(runner: CliRunner,
                                                 chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    chrome_user_data.write_json('Default', 'Preferences', {
        'enable_do_not_track': True,
        'homepage': 'https://example.com/'
    })
    result = runner.invoke(
        chrome_dump, [*chrome_user_data.argv, 'preferences', '--changed', '-S', 'privacy', '-j'])
    assert result.exit_code == 0
    assert [row['key'] for row in json.loads(result.output)] == ['enable_do_not_track']


def test_preferences_expand(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    chrome_user_data.write_json('Default', 'Preferences', {'download': {'prompt': True}})
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'preferences', '-x', '-j'])
    assert result.exit_code == 0
    assert json.loads(result.output) == [{'key': 'download.prompt', 'type': 'bool', 'value': True}]


def test_preferences_key_and_secure(runner: CliRunner,
                                    chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    chrome_user_data.write_json('Default', 'Secure Preferences', {'protection': {'macs': {}}})
    result = runner.invoke(
        chrome_dump, [*chrome_user_data.argv, 'preferences', '-s', '-k', 'protection.macs', '-j'])
    assert result.exit_code == 0
    assert json.loads(result.output) == {}


def test_preferences_unknown_profile(runner: CliRunner,
                                     chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'preferences', '-P', 'missing'])
    assert result.exit_code == 1
    assert 'No profile matching' in result.stderr


def test_list_databases_json(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    chrome_user_data.write_database('Default',
                                    'History', ('CREATE TABLE urls(x)',),
                                    meta={'version': '60'})
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-databases', '-j'])
    assert result.exit_code == 0
    summaries = json.loads(result.output)
    assert [summary['name'] for summary in summaries] == ['History']
    assert summaries[0]['version'] == '60'


def test_list_databases_table(runner: CliRunner, chrome_user_data: FakeChromeUserData,
                              monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('COLUMNS', '200')
    chrome_user_data.add_profile('Default')
    chrome_user_data.write_database('Default', 'Small', ('CREATE TABLE only(x)',))
    chrome_user_data.write_database('Default', 'Large',
                                    tuple(f'CREATE TABLE t{index}(x)' for index in range(9)))
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-databases'])
    assert result.exit_code == 0
    assert '…' in result.output
    assert 'only' in result.output


def test_list_files(runner: CliRunner, chrome_user_data: FakeChromeUserData,
                    monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('COLUMNS', '200')
    chrome_user_data.add_profile('Default')
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-files'])
    assert result.exit_code == 0
    assert 'Preferences' in result.output


def test_query(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    chrome_user_data.write_database('Default', 'Web Data', ('CREATE TABLE autofill(name)',),
                                    {'autofill': [('first',), ('second',)]})
    result = runner.invoke(
        chrome_dump,
        [*chrome_user_data.argv, 'query', 'Web Data', 'SELECT name FROM autofill', '-l', '1', '-j'])
    assert result.exit_code == 0
    assert json.loads(result.output) == [{'name': 'first'}]


def test_query_without_limit(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    chrome_user_data.write_database('Default', 'Web Data', ('CREATE TABLE autofill(name)',),
                                    {'autofill': [('first',), ('second',)]})
    result = runner.invoke(
        chrome_dump,
        [*chrome_user_data.argv, 'query', 'Web Data', 'SELECT name FROM autofill', '-j'])
    assert result.exit_code == 0
    assert len(json.loads(result.output)) == 2


def test_query_not_a_database(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    result = runner.invoke(chrome_dump,
                           [*chrome_user_data.argv, 'query', 'Preferences', 'SELECT 1'])
    assert result.exit_code == 1
    assert 'is not a SQLite database' in result.stderr


def test_query_bad_sql(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    chrome_user_data.write_database('Default', 'Web Data', ('CREATE TABLE autofill(name)',))
    result = runner.invoke(chrome_dump,
                           [*chrome_user_data.argv, 'query', 'Web Data', 'SELECT * FROM missing'])
    assert result.exit_code == 1
    assert 'Query failed' in result.stderr


def test_linux_keyring_password_reads_the_secret_service(mocker: MockerFixture) -> None:
    keyring_setup(mocker, set(), {}, None, [FakeSecretItem(b'from-secret-service')])
    assert b'from-secret-service' in linux_keyring_passwords('Chrome')


def test_linux_keyring_password_unlocks_a_locked_item(mocker: MockerFixture) -> None:
    item = FakeSecretItem(b'from-secret-service', application='chromium', locked=True)
    keyring_setup(mocker, set(), {}, None, [item])
    assert b'from-secret-service' in linux_keyring_passwords('Chromium')
    assert item.unlocked


def test_linux_keyring_password_skips_an_empty_secret(mocker: MockerFixture) -> None:
    keyring_setup(mocker, set(), {}, 'from-keyring', [FakeSecretItem(b'')])
    assert b'from-keyring' in linux_keyring_passwords('Chrome')


def test_keyring_available_reports_the_v11_key(mocker: MockerFixture) -> None:
    keyring_setup(mocker, set(), {}, None)
    assert not OSCrypt('Chrome').keyring_available
    keyring_setup(mocker, set(), {}, None, [FakeSecretItem(b'password')])
    assert OSCrypt('Chrome').keyring_available


def test_linux_keyring_password_skips_another_applications_item(mocker: MockerFixture) -> None:
    keyring_setup(mocker, set(), {}, 'from-keyring',
                  [FakeSecretItem(b'someone-elses', application='signal')])
    assert b'from-keyring' in linux_keyring_passwords('Chrome')


def test_linux_keyring_password_falls_back_to_the_item_label(mocker: MockerFixture) -> None:
    keyring_setup(mocker, set(), {}, None,
                  [FakeSecretItem(b'from-label', application='', label='Chrome Safe Storage')])
    assert b'from-label' in linux_keyring_passwords('Chrome')


def test_linux_keyring_password_ignores_an_item_it_cannot_inspect(mocker: MockerFixture) -> None:
    item = FakeSecretItem(b'unreadable')
    mocker.patch.object(FakeSecretItem, 'get_attributes', side_effect=RuntimeError('no access'))
    mocker.patch.object(FakeSecretItem, 'get_label', side_effect=RuntimeError('no access'))
    keyring_setup(mocker, set(), {}, 'from-keyring', [item])
    assert b'from-keyring' in linux_keyring_passwords('Chrome')


def test_linux_keyring_passwords_collects_every_distinct_candidate(mocker: MockerFixture) -> None:
    keyring_setup(mocker, {'secret-tool'}, {'secret-tool': [(0, b'from-secret-tool\n')]},
                  'from-keyring',
                  [FakeSecretItem(b'stale'), FakeSecretItem(b'current')])
    assert linux_keyring_passwords('Chrome') == (b'stale', b'current', b'from-secret-tool',
                                                 b'from-keyring')


def test_oscrypt_tries_every_candidate_key(mocker: MockerFixture) -> None:
    keyring_setup(
        mocker, set(), {}, None,
        [FakeSecretItem(b'wrong-key'), FakeSecretItem(b'right-key')])
    sha1 = hashes.SHA1()  # noqa: S303
    key = pbkdf2.PBKDF2HMAC(algorithm=sha1, iterations=1, length=16,
                            salt=b'saltysalt').derive(b'right-key')
    assert OSCrypt('Chrome').decrypt(encrypt_cbc(b'hunter2', key, version=b'v11')) == 'hunter2'
