from __future__ import annotations

from typing import TYPE_CHECKING, Any
import json
import os
import struct

import pytest

from deltona.chrome.core import unix_timestamp_to_datetime, webkit_timestamp_to_datetime
from deltona.chrome.network import (
    CACHE_INITIAL_MAGIC,
    SNSS_MAGIC,
    cache_entries,
    dips_bounces,
    dips_popups,
    nel_policies,
    network_persistent_state,
    reporting_endpoint_groups,
    reporting_endpoints,
    session_files,
    transport_security,
)
from deltona.commands.chrome import chrome_dump

if TYPE_CHECKING:
    from pathlib import Path

    from click.testing import CliRunner

    from .conftest import FakeChromeUserData

WEBKIT_A = 13355053200000000
WEBKIT_B = 13354979400000000
WEBKIT_C = 13330080000000000
WEBKIT_D = 13312147500000000
UNIX_A = 1735689600
UNIX_B = 1700000000
_CACHE_ENTRY_HEADER = struct.Struct('<QIIII')
_SNSS_FILE_HEADER = struct.Struct('<4sI')
_SNSS_RECORD_PREFIX = struct.Struct('<H')
KEY_WHOLE_URL = b'https://example.com/one'
KEY_SPACE_TOKEN_URL = b'GET https://example.com/two'
KEY_PREFIX_URL = b'0/0/https://example.com/three'
KEY_NO_URL = b'no-url-key-here'
EXTRA_STREAM = b'x' * 500
_DIPS_SCHEMA = (
    ('CREATE TABLE bounces(site TEXT PRIMARY KEY, first_bounce_time INTEGER, '
     'first_user_activation_time INTEGER, first_web_authn_assertion_time INTEGER, '
     'last_bounce_time INTEGER, last_user_activation_time INTEGER, '
     'last_web_authn_assertion_time INTEGER)'),
    ('CREATE TABLE popups(opener_site TEXT, popup_site TEXT, last_popup_time INTEGER, '
     'is_authentication_interaction INTEGER, is_current_interaction INTEGER)'),
)
_DIPS_ROWS: dict[str, list[tuple[Any, ...]]] = {
    'bounces': [
        ('b.example', WEBKIT_A, WEBKIT_B, WEBKIT_B, WEBKIT_A, WEBKIT_B, WEBKIT_B),
        ('a.example', WEBKIT_C, 0, 0, WEBKIT_C, 0, 0),
    ],
    'popups': [
        ('opener-b.example', 'popup-b.example', WEBKIT_A, 0, None),
        ('opener-a.example', 'popup-a.example', WEBKIT_C, None, 1),
    ],
}
_NEL_SCHEMA = (
    ('CREATE TABLE nel_policies(origin_host TEXT PRIMARY KEY, is_include_subdomains INTEGER, '
     'expires_us_since_epoch INTEGER, last_access_us_since_epoch INTEGER)'),
    'CREATE TABLE reporting_endpoints(origin_host TEXT, group_name TEXT, url TEXT)',
    ('CREATE TABLE reporting_endpoint_groups(origin_host TEXT, group_name TEXT, '
     'is_include_subdomains INTEGER, expires_us_since_epoch INTEGER, '
     'last_access_us_since_epoch INTEGER)'),
)
_NEL_ROWS: dict[str, list[tuple[Any, ...]]] = {
    'nel_policies': [
        ('b.example.com', 1, WEBKIT_A, WEBKIT_B),
        ('a.example.com', 0, WEBKIT_A, WEBKIT_B),
    ],
    'reporting_endpoints': [
        ('b.example.com', 'default', 'https://b.example.com/reports'),
        ('a.example.com', 'default', 'https://a.example.com/reports'),
    ],
    'reporting_endpoint_groups': [
        ('b.example.com', 'default', 1, WEBKIT_A, WEBKIT_B),
        ('a.example.com', 'default', 0, WEBKIT_A, WEBKIT_B),
    ],
}


def _cache_header(key_length: int, *, magic: int = CACHE_INITIAL_MAGIC) -> bytes:
    return _CACHE_ENTRY_HEADER.pack(magic, 1, key_length, 0, 0)


def _write_cache_entry(directory: Path,
                       name: str,
                       key: bytes,
                       *,
                       extra_stream: bytes | None = None) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f'{name}_0').write_bytes(_cache_header(len(key)) + key)
    if extra_stream is not None:
        (directory / f'{name}_1').write_bytes(extra_stream)


def _populate_corrupt_cache_matrix(cache_data_dir: Path) -> None:
    cache_data_dir.mkdir(parents=True, exist_ok=True)
    base_mtime = 1_700_000_000.0
    _write_cache_entry(cache_data_dir, '0000000000000001', KEY_WHOLE_URL)
    os.utime(cache_data_dir / '0000000000000001_0', (base_mtime, base_mtime))
    _write_cache_entry(cache_data_dir,
                       '0000000000000002',
                       KEY_SPACE_TOKEN_URL,
                       extra_stream=EXTRA_STREAM)
    os.utime(cache_data_dir / '0000000000000002_0', (base_mtime + 300, base_mtime + 300))
    _write_cache_entry(cache_data_dir, '0000000000000003', KEY_PREFIX_URL)
    os.utime(cache_data_dir / '0000000000000003_0', (base_mtime + 100, base_mtime + 100))
    _write_cache_entry(cache_data_dir, '0000000000000004', KEY_NO_URL)
    os.utime(cache_data_dir / '0000000000000004_0', (base_mtime + 200, base_mtime + 200))
    (cache_data_dir / '0000000000000005_0'
     ).write_bytes(_cache_header(len(b'bad-magic-key'), magic=0xdeadbeef) + b'bad-magic-key')
    (cache_data_dir / '0000000000000006_0').write_bytes(b'\x00' * 10)
    (cache_data_dir / '0000000000000007_0').write_bytes(_cache_header(999) + b'short')
    (cache_data_dir / '0000000000000008_1').write_bytes(_cache_header(3) + b'abc')
    _write_cache_entry(cache_data_dir, '0000000000000009', b'entry-nine-key')
    (cache_data_dir / '0000000000000009_1').symlink_to(cache_data_dir / 'does-not-exist')


def _snss_record(record_id: int, payload: bytes = b'') -> bytes:
    body = bytes([record_id]) + payload
    return _SNSS_RECORD_PREFIX.pack(len(body)) + body


def _snss_file(records: bytes, *, magic: bytes = SNSS_MAGIC, version: int = 1) -> bytes:
    return _SNSS_FILE_HEADER.pack(magic, version) + records


def _network_state_data() -> dict[str, Any]:
    return {
        'net': {
            'http_server_properties': {
                'servers': [
                    {
                        'server': 'https://a.example.com',
                        'supports_spdy': True
                    },
                    {
                        'server': 'https://b.example.com',
                        'supports_spdy': False
                    },
                ],
                'broken_alternative_services': [{
                    'broken_until': 123,
                    'host_port_pair': 'c.example.com:443'
                }],
                'quic_servers': [{
                    'server_id': 'https://d.example.com',
                    'used_quic': True
                }],
                'supports_quic': {
                    'used_quic': True,
                    'address': '1.2.3.4'
                }
            },
            'network_qualities': {
                'network-id-1': {
                    'effective_connection_type': '4G'
                },
                'network-id-2': {
                    'effective_connection_type': '3G'
                }
            }
        }
    }


def _transport_security_data() -> dict[str, Any]:
    return {
        'sts': [
            {
                'host': 'hash-one==',
                'mode': 'force-https',
                'sts_include_subdomains': True,
                'sts_observed': UNIX_A,
                'expiry': UNIX_B
            },
            {
                'host': 'hash-two==',
                'mode': 'default',
                'sts_include_subdomains': False,
                'sts_observed': 0,
                'expiry': 0
            },
        ]
    }


def _write_dips_db(chrome_user_data: FakeChromeUserData, directory: str = 'Default') -> Path:
    return chrome_user_data.write_database(directory, 'DIPS', _DIPS_SCHEMA, _DIPS_ROWS)


def _write_nel_db(chrome_user_data: FakeChromeUserData, directory: str = 'Default') -> Path:
    return chrome_user_data.write_database(directory, 'Reporting and NEL', _NEL_SCHEMA, _NEL_ROWS)


def _write_network_state(chrome_user_data: FakeChromeUserData,
                         directory: str = 'Default',
                         *,
                         network_state: bool = True,
                         transport_security_file: bool = True) -> None:
    if network_state:
        chrome_user_data.write_json(directory, 'Network Persistent State', _network_state_data())
    if transport_security_file:
        chrome_user_data.write_json(directory, 'TransportSecurity', _transport_security_data())


# cache_entries


def test_cache_entries_populated_url_extraction_and_key_sort(tmp_path: Path) -> None:
    _populate_corrupt_cache_matrix(tmp_path / 'Cache' / 'Cache_Data')
    rows = cache_entries(tmp_path, sort='key')
    assert [row['key'] for row in rows] == [
        KEY_PREFIX_URL.decode(),
        KEY_SPACE_TOKEN_URL.decode(),
        KEY_WHOLE_URL.decode(),
        KEY_NO_URL.decode()
    ]
    by_key = {row['key']: row for row in rows}
    assert by_key[KEY_WHOLE_URL.decode()]['url'] == 'https://example.com/one'
    assert by_key[KEY_WHOLE_URL.decode()]['key/url'] == 'https://example.com/one'
    assert by_key[KEY_SPACE_TOKEN_URL.decode()]['url'] == 'https://example.com/two'
    assert by_key[KEY_PREFIX_URL.decode()]['url'] == 'https://example.com/three'
    assert by_key[KEY_NO_URL.decode()]['url'] is None
    assert by_key[KEY_NO_URL.decode()]['key/url'] == KEY_NO_URL.decode()


def test_cache_entries_sorted_by_modified_descending(tmp_path: Path) -> None:
    _populate_corrupt_cache_matrix(tmp_path / 'Cache' / 'Cache_Data')
    rows = cache_entries(tmp_path, sort='modified')
    assert [row['key'] for row in rows] == [
        KEY_SPACE_TOKEN_URL.decode(),
        KEY_NO_URL.decode(),
        KEY_PREFIX_URL.decode(),
        KEY_WHOLE_URL.decode()
    ]


def test_cache_entries_sorted_by_size_descending(tmp_path: Path) -> None:
    _populate_corrupt_cache_matrix(tmp_path / 'Cache' / 'Cache_Data')
    rows = cache_entries(tmp_path, sort='size')
    assert [row['key'] for row in rows] == [
        KEY_SPACE_TOKEN_URL.decode(),
        KEY_PREFIX_URL.decode(),
        KEY_WHOLE_URL.decode(),
        KEY_NO_URL.decode()
    ]
    assert rows[0]['size'] == _CACHE_ENTRY_HEADER.size + len(KEY_SPACE_TOKEN_URL) + len(
        EXTRA_STREAM)


def test_cache_entries_search_filter(tmp_path: Path) -> None:
    _populate_corrupt_cache_matrix(tmp_path / 'Cache' / 'Cache_Data')
    rows = cache_entries(tmp_path, search='two')
    assert [row['key'] for row in rows] == [KEY_SPACE_TOKEN_URL.decode()]


def test_cache_entries_skips_corrupt_and_edge_cases(tmp_path: Path) -> None:
    _populate_corrupt_cache_matrix(tmp_path / 'Cache' / 'Cache_Data')
    rows = cache_entries(tmp_path)
    assert len(rows) == 4
    keys = {row['key'] for row in rows}
    assert keys == {
        KEY_WHOLE_URL.decode(),
        KEY_SPACE_TOKEN_URL.decode(),
        KEY_PREFIX_URL.decode(),
        KEY_NO_URL.decode(),
    }


def test_cache_entries_code_kind_merges_existing_subdirectories(tmp_path: Path) -> None:
    _write_cache_entry(tmp_path / 'Code Cache' / 'js', '0000000000000010', b'https://js.example')
    _write_cache_entry(tmp_path / 'Code Cache' / 'wasm', '0000000000000011',
                       b'https://wasm.example')
    rows = cache_entries(tmp_path, kind='code')
    assert {row['key'] for row in rows} == {'https://js.example', 'https://wasm.example'}


def test_cache_entries_code_kind_no_subdirectories(tmp_path: Path) -> None:
    assert cache_entries(tmp_path, kind='code') == []


def test_cache_entries_image_kind_missing_directory(tmp_path: Path) -> None:
    assert cache_entries(tmp_path, kind='image') == []


def test_cache_entries_image_kind_populated(tmp_path: Path) -> None:
    _write_cache_entry(tmp_path / 'image_cache', '0000000000000012', b'https://image.example')
    rows = cache_entries(tmp_path, kind='image')
    assert [row['key'] for row in rows] == ['https://image.example']


def test_cache_entries_ignores_non_entry_filenames(tmp_path: Path) -> None:
    cache_data_dir = tmp_path / 'Cache' / 'Cache_Data'
    cache_data_dir.mkdir(parents=True)
    (cache_data_dir / 'index').write_bytes(b'not-an-entry-file')
    _write_cache_entry(cache_data_dir, '0000000000000013', KEY_WHOLE_URL)
    rows = cache_entries(tmp_path)
    assert [row['key'] for row in rows] == [KEY_WHOLE_URL.decode()]


def test_cache_entries_prefix_match_without_netloc_has_no_url(tmp_path: Path) -> None:
    cache_data_dir = tmp_path / 'Cache' / 'Cache_Data'
    _write_cache_entry(cache_data_dir, '0000000000000014', b'1/2/not-a-real-url')
    rows = cache_entries(tmp_path)
    assert rows[0]['url'] is None
    assert rows[0]['key/url'] == '1/2/not-a-real-url'


def test_cache_entries_skips_entry_whose_stream_is_a_directory(tmp_path: Path) -> None:
    cache_data_dir = tmp_path / 'Cache' / 'Cache_Data'
    (cache_data_dir / '0000000000000015_0').mkdir(parents=True)
    assert cache_entries(tmp_path) == []


# dips_bounces / dips_popups


def test_dips_bounces_populated_sorted_and_converted(chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    path = _write_dips_db(chrome_user_data)
    rows = dips_bounces(path)
    assert [row['site'] for row in rows] == ['a.example', 'b.example']
    a_row, b_row = rows
    assert a_row['first_bounce_time'] == webkit_timestamp_to_datetime(WEBKIT_C)
    assert a_row['last_web_authn_assertion_time'] is None
    assert b_row['first_bounce_time'] == webkit_timestamp_to_datetime(WEBKIT_A)
    assert b_row['last_web_authn_assertion_time'] == webkit_timestamp_to_datetime(WEBKIT_B)


def test_dips_bounces_search(chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    path = _write_dips_db(chrome_user_data)
    rows = dips_bounces(path, search='a.example')
    assert [row['site'] for row in rows] == ['a.example']


def test_dips_bounces_empty(chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    path = chrome_user_data.write_database('Default', 'DIPS', _DIPS_SCHEMA, None)
    assert dips_bounces(path) == []


def test_dips_popups_populated_sorted_and_converted(chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    path = _write_dips_db(chrome_user_data)
    rows = dips_popups(path)
    assert [row['opener_site'] for row in rows] == ['opener-a.example', 'opener-b.example']
    a_row, b_row = rows
    assert a_row['last_popup_time'] == webkit_timestamp_to_datetime(WEBKIT_C)
    assert a_row['is_authentication_interaction'] is None
    assert a_row['is_current_interaction'] is True
    assert b_row['is_authentication_interaction'] is False
    assert b_row['is_current_interaction'] is None


def test_dips_popups_search(chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    path = _write_dips_db(chrome_user_data)
    rows = dips_popups(path, search='popup-a')
    assert [row['opener_site'] for row in rows] == ['opener-a.example']


def test_dips_popups_empty(chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    path = chrome_user_data.write_database('Default', 'DIPS', _DIPS_SCHEMA, None)
    assert dips_popups(path) == []


# nel_policies / reporting_endpoints / reporting_endpoint_groups


def test_nel_policies_populated_sorted_and_converted(chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    path = _write_nel_db(chrome_user_data)
    rows = nel_policies(path)
    assert [row['origin_host'] for row in rows] == ['a.example.com', 'b.example.com']
    assert rows[0]['is_include_subdomains'] is False
    assert rows[1]['is_include_subdomains'] is True
    assert rows[0]['expires_us_since_epoch'] == webkit_timestamp_to_datetime(WEBKIT_A)
    assert rows[0]['last_access_us_since_epoch'] == webkit_timestamp_to_datetime(WEBKIT_B)


def test_nel_policies_search(chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    path = _write_nel_db(chrome_user_data)
    rows = nel_policies(path, search='b.example')
    assert [row['origin_host'] for row in rows] == ['b.example.com']


def test_nel_policies_empty(chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    path = chrome_user_data.write_database('Default', 'Reporting and NEL', _NEL_SCHEMA, None)
    assert nel_policies(path) == []


def test_reporting_endpoints_populated_sorted(chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    path = _write_nel_db(chrome_user_data)
    rows = reporting_endpoints(path)
    assert [row['origin_host'] for row in rows] == ['a.example.com', 'b.example.com']
    assert rows[0]['url'] == 'https://a.example.com/reports'


def test_reporting_endpoints_search(chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    path = _write_nel_db(chrome_user_data)
    rows = reporting_endpoints(path, search='b.example')
    assert [row['origin_host'] for row in rows] == ['b.example.com']


def test_reporting_endpoints_empty(chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    path = chrome_user_data.write_database('Default', 'Reporting and NEL', _NEL_SCHEMA, None)
    assert reporting_endpoints(path) == []


def test_reporting_endpoint_groups_populated_sorted_and_converted(
        chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    path = _write_nel_db(chrome_user_data)
    rows = reporting_endpoint_groups(path)
    assert [row['origin_host'] for row in rows] == ['a.example.com', 'b.example.com']
    assert rows[0]['is_include_subdomains'] is False
    assert rows[1]['is_include_subdomains'] is True
    assert rows[1]['expires_us_since_epoch'] == webkit_timestamp_to_datetime(WEBKIT_A)


def test_reporting_endpoint_groups_search(chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    path = _write_nel_db(chrome_user_data)
    rows = reporting_endpoint_groups(path, search='a.example')
    assert [row['origin_host'] for row in rows] == ['a.example.com']


def test_reporting_endpoint_groups_empty(chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    path = chrome_user_data.write_database('Default', 'Reporting and NEL', _NEL_SCHEMA, None)
    assert reporting_endpoint_groups(path) == []


# network_persistent_state / transport_security


def test_network_persistent_state_populated(tmp_path: Path) -> None:
    path = tmp_path / 'Network Persistent State'
    path.write_text(json.dumps(_network_state_data()), encoding='utf-8')
    state = network_persistent_state(path)
    assert [server['server']
            for server in state['servers']] == ['https://a.example.com', 'https://b.example.com']
    assert state['broken_alternative_services'][0]['host_port_pair'] == 'c.example.com:443'
    assert state['quic_servers'][0]['server_id'] == 'https://d.example.com'
    assert state['supports_quic'] == {'used_quic': True, 'address': '1.2.3.4'}
    assert state['network_qualities']['network-id-1']['effective_connection_type'] == '4G'


def test_network_persistent_state_missing(tmp_path: Path) -> None:
    state = network_persistent_state(tmp_path / 'missing')
    assert state == {
        'servers': [],
        'broken_alternative_services': [],
        'quic_servers': [],
        'supports_quic': None,
        'network_qualities': {}
    }


def test_network_persistent_state_malformed(tmp_path: Path) -> None:
    path = tmp_path / 'Network Persistent State'
    path.write_text('{not valid json', encoding='utf-8')
    assert network_persistent_state(path)['servers'] == []


def test_transport_security_populated(tmp_path: Path) -> None:
    path = tmp_path / 'TransportSecurity'
    path.write_text(json.dumps(_transport_security_data()), encoding='utf-8')
    hsts = transport_security(path)
    assert [entry['host'] for entry in hsts] == ['hash-one==', 'hash-two==']
    assert hsts[0]['include_subdomains'] is True
    assert hsts[0]['observed'] == unix_timestamp_to_datetime(UNIX_A)
    assert hsts[0]['expiry'] == unix_timestamp_to_datetime(UNIX_B)
    assert hsts[1]['include_subdomains'] is False
    assert hsts[1]['observed'] is None
    assert hsts[1]['expiry'] is None


def test_transport_security_missing(tmp_path: Path) -> None:
    assert transport_security(tmp_path / 'missing') == []


# session_files


def test_session_files_missing_directory(tmp_path: Path) -> None:
    assert session_files(tmp_path / 'missing') == []


def test_session_files_populated_valid_truncated_and_corrupt(tmp_path: Path) -> None:
    sessions_path = tmp_path / 'Sessions'
    sessions_path.mkdir()
    valid_records = (_snss_record(1, b'hello') +
                     _snss_record(2, b'noise https://example.com/a more noise') +
                     _snss_record(1, b'world https://example.com/b'))
    (sessions_path / f'Session_{WEBKIT_A}').write_bytes(_snss_file(valid_records))
    truncated = _snss_record(1, b'ok') + _SNSS_RECORD_PREFIX.pack(50) + bytes([2]) + b'short'
    (sessions_path / f'Tabs_{WEBKIT_B}').write_bytes(_snss_file(truncated))
    (sessions_path / f'Apps_{WEBKIT_C}').write_bytes(
        _snss_file(_snss_record(1, b'x'), magic=b'XXXX'))
    (sessions_path / f'Session_{WEBKIT_D}').write_bytes(b'SN')
    (sessions_path / 'notes.txt').write_text('not a session file', encoding='utf-8')
    (sessions_path / 'Tabs_13300000000000000').mkdir()
    rows = session_files(sessions_path)
    assert [row['name'] for row in rows] == [f'Session_{WEBKIT_A}', f'Tabs_{WEBKIT_B}']
    valid_row, truncated_row = rows
    assert valid_row['kind'] == 'Session'
    assert valid_row['timestamp'] == webkit_timestamp_to_datetime(WEBKIT_A)
    assert valid_row['version'] == 1
    assert valid_row['record_count'] == 3
    assert valid_row['record_ids'] == {1: 2, 2: 1}
    assert valid_row['urls'] == ('https://example.com/a', 'https://example.com/b')
    assert truncated_row['kind'] == 'Tabs'
    assert truncated_row['record_count'] == 1
    assert truncated_row['record_ids'] == {1: 1}
    assert truncated_row['urls'] == ()


# list-cache


def test_list_cache_table_default(runner: CliRunner, chrome_user_data: FakeChromeUserData,
                                  monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('COLUMNS', '200')
    chrome_user_data.add_profile('Default')
    _write_cache_entry(chrome_user_data.cache_path / 'Default' / 'Cache' / 'Cache_Data',
                       '0000000000000001', KEY_WHOLE_URL)
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-cache'])
    assert result.exit_code == 0, result.output
    assert '1 entries,' in result.stderr
    assert 'Cache in Default' in result.output
    assert 'https://example.com/one' in result.output


def test_list_cache_json(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    cache_dir = chrome_user_data.cache_path / 'Default' / 'Cache' / 'Cache_Data'
    _write_cache_entry(cache_dir, '0000000000000001', KEY_WHOLE_URL)
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-cache', '--json'])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert len(data) == 1
    assert data[0]['key'] == KEY_WHOLE_URL.decode()
    assert data[0]['url'] == 'https://example.com/one'
    assert data[0]['size'] == _CACHE_ENTRY_HEADER.size + len(KEY_WHOLE_URL)
    assert data[0]['file'] == str(cache_dir / '0000000000000001_0')


def test_list_cache_search_and_sort(runner: CliRunner,
                                    chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    cache_dir = chrome_user_data.cache_path / 'Default' / 'Cache' / 'Cache_Data'
    _write_cache_entry(cache_dir, '0000000000000001', KEY_WHOLE_URL)
    _write_cache_entry(cache_dir, '0000000000000002', KEY_SPACE_TOKEN_URL)
    result = runner.invoke(
        chrome_dump,
        [*chrome_user_data.argv, 'list-cache', '--search', 'two', '--sort', 'key', '--json'])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert [row['key'] for row in data] == [KEY_SPACE_TOKEN_URL.decode()]


def test_list_cache_limit(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    cache_dir = chrome_user_data.cache_path / 'Default' / 'Cache' / 'Cache_Data'
    _write_cache_entry(cache_dir, '0000000000000001', KEY_WHOLE_URL)
    _write_cache_entry(cache_dir, '0000000000000002', KEY_SPACE_TOKEN_URL)
    result = runner.invoke(
        chrome_dump,
        [*chrome_user_data.argv, 'list-cache', '--limit', '1', '--sort', 'key', '--json'])
    assert result.exit_code == 0, result.output
    assert len(json.loads(result.output)) == 1
    result = runner.invoke(chrome_dump,
                           [*chrome_user_data.argv, 'list-cache', '--limit', '0', '--json'])
    assert result.exit_code == 0, result.output
    assert len(json.loads(result.output)) == 2


@pytest.mark.parametrize(('cache_kind', 'relative_dir', 'key'), [
    ('image', 'image_cache', b'https://image.example'),
    ('code', 'Code Cache/js', b'https://js.example'),
])
def test_list_cache_cache_kind_option(runner: CliRunner, chrome_user_data: FakeChromeUserData,
                                      cache_kind: str, relative_dir: str, key: bytes) -> None:
    chrome_user_data.add_profile('Default')
    directory = chrome_user_data.cache_path / 'Default'
    for part in relative_dir.split('/'):
        directory /= part
    _write_cache_entry(directory, '00000000000000ff', key)
    result = runner.invoke(chrome_dump,
                           [*chrome_user_data.argv, 'list-cache', '--cache', cache_kind, '--json'])
    assert result.exit_code == 0, result.output
    assert [row['key'] for row in json.loads(result.output)] == [key.decode()]


def test_list_cache_missing_cache_dir(runner: CliRunner,
                                      chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    (chrome_user_data.cache_path / 'Default').rmdir()
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-cache'])
    assert result.exit_code != 0
    assert 'does not exist.' in result.stderr


# list-dips


def test_list_dips_bounces_table(runner: CliRunner, chrome_user_data: FakeChromeUserData,
                                 monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('COLUMNS', '200')
    chrome_user_data.add_profile('Default')
    _write_dips_db(chrome_user_data)
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-dips'])
    assert result.exit_code == 0, result.output
    assert 'Bounces in Default' in result.output
    assert 'a.example' in result.output


def test_list_dips_bounces_json(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_dips_db(chrome_user_data)
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-dips', '--json'])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert [row['site'] for row in data] == ['a.example', 'b.example']


def test_list_dips_popups_table(runner: CliRunner, chrome_user_data: FakeChromeUserData,
                                monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('COLUMNS', '200')
    chrome_user_data.add_profile('Default')
    _write_dips_db(chrome_user_data)
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-dips', '--popups'])
    assert result.exit_code == 0, result.output
    assert 'Popups in Default' in result.output
    assert 'opener-a.example' in result.output


def test_list_dips_popups_json(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_dips_db(chrome_user_data)
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-dips', '--popups', '--json'])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert [row['opener_site'] for row in data] == ['opener-a.example', 'opener-b.example']


def test_list_dips_search(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_dips_db(chrome_user_data)
    result = runner.invoke(chrome_dump,
                           [*chrome_user_data.argv, 'list-dips', '--search', 'a.example', '--json'])
    assert result.exit_code == 0, result.output
    assert [row['site'] for row in json.loads(result.output)] == ['a.example']


def test_list_dips_empty_table(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    chrome_user_data.write_database('Default', 'DIPS', _DIPS_SCHEMA, None)
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-dips'])
    assert result.exit_code == 0, result.output
    assert 'No bounces in default found.' in result.stderr


# list-network-state


def test_list_network_state_summary_json(runner: CliRunner,
                                         chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_network_state(chrome_user_data)
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-network-state', '--json'])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert len(data['servers']) == 2
    assert data['broken_alternative_services'][0]['host_port_pair'] == 'c.example.com:443'
    assert data['quic_servers'][0]['server_id'] == 'https://d.example.com'
    assert data['supports_quic']['used_quic'] is True
    assert data['network_qualities']['network-id-1']['effective_connection_type'] == '4G'
    assert [entry['host'] for entry in data['hsts']] == ['hash-one==', 'hash-two==']


def test_list_network_state_summary_table(runner: CliRunner, chrome_user_data: FakeChromeUserData,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('COLUMNS', '200')
    chrome_user_data.add_profile('Default')
    _write_network_state(chrome_user_data)
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-network-state'])
    assert result.exit_code == 0, result.output
    assert 'Network State Summary' in result.output
    assert 'servers' in result.output
    assert 'hsts' in result.output


def test_list_network_state_section_servers(runner: CliRunner,
                                            chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_network_state(chrome_user_data)
    result = runner.invoke(
        chrome_dump,
        [*chrome_user_data.argv, 'list-network-state', '--section', 'servers', '--json'])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert {row['host'] for row in data} == {'a.example.com', 'b.example.com'}
    result = runner.invoke(chrome_dump, [
        *chrome_user_data.argv, 'list-network-state', '--section', 'servers', '--search',
        'b.example', '--json'
    ])
    assert result.exit_code == 0, result.output
    assert [row['host'] for row in json.loads(result.output)] == ['b.example.com']


def test_list_network_state_section_broken_ignores_search(
        runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_network_state(chrome_user_data)
    result = runner.invoke(chrome_dump, [
        *chrome_user_data.argv, 'list-network-state', '--section', 'broken', '--search',
        'irrelevant', '--json'
    ])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data[0]['host_port_pair'] == 'c.example.com:443'


def test_list_network_state_section_quic_with_data(runner: CliRunner,
                                                   chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_network_state(chrome_user_data)
    result = runner.invoke(
        chrome_dump, [*chrome_user_data.argv, 'list-network-state', '--section', 'quic', '--json'])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data[0] == {'kind': 'supports_quic', 'used_quic': True, 'address': '1.2.3.4'}
    assert data[1]['kind'] == 'quic_server'
    assert data[1]['server_id'] == 'https://d.example.com'


def test_list_network_state_section_quic_empty(runner: CliRunner,
                                               chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    empty_state = _network_state_data()
    empty_state['net']['http_server_properties']['supports_quic'] = None
    empty_state['net']['http_server_properties']['quic_servers'] = []
    chrome_user_data.write_json('Default', 'Network Persistent State', empty_state)
    chrome_user_data.write_json('Default', 'TransportSecurity', _transport_security_data())
    result = runner.invoke(chrome_dump,
                           [*chrome_user_data.argv, 'list-network-state', '--section', 'quic'])
    assert result.exit_code == 0, result.output
    assert 'No network state (quic) found.' in result.stderr


def test_list_network_state_section_network_qualities_and_limit(
        runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_network_state(chrome_user_data)
    result = runner.invoke(
        chrome_dump,
        [*chrome_user_data.argv, 'list-network-state', '--section', 'network-qualities', '--json'])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert {row['network_id'] for row in data} == {'network-id-1', 'network-id-2'}
    result = runner.invoke(chrome_dump, [
        *chrome_user_data.argv, 'list-network-state', '--section', 'network-qualities', '--limit',
        '1', '--json'
    ])
    assert result.exit_code == 0, result.output
    assert len(json.loads(result.output)) == 1


def test_list_network_state_section_hsts_search(runner: CliRunner,
                                                chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_network_state(chrome_user_data)
    result = runner.invoke(chrome_dump, [
        *chrome_user_data.argv, 'list-network-state', '--section', 'hsts', '--search', 'hash-one',
        '--json'
    ])
    assert result.exit_code == 0, result.output
    assert [row['host'] for row in json.loads(result.output)] == ['hash-one==']


def test_list_network_state_missing_network_state_file(
        runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-network-state'])
    assert result.exit_code != 0
    assert 'Network Persistent State' in result.stderr


def test_list_network_state_missing_transport_security_file(
        runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_network_state(chrome_user_data, transport_security_file=False)
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-network-state'])
    assert result.exit_code != 0
    assert 'TransportSecurity' in result.stderr


# list-reporting


def test_list_reporting_nel_table(runner: CliRunner, chrome_user_data: FakeChromeUserData,
                                  monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('COLUMNS', '200')
    chrome_user_data.add_profile('Default')
    _write_nel_db(chrome_user_data)
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-reporting'])
    assert result.exit_code == 0, result.output
    assert 'Nel in Default' in result.output
    assert 'a.example.com' in result.output


def test_list_reporting_nel_json(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_nel_db(chrome_user_data)
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-reporting', '--json'])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert [row['origin_host'] for row in data] == ['a.example.com', 'b.example.com']


def test_list_reporting_endpoints_json(runner: CliRunner,
                                       chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_nel_db(chrome_user_data)
    result = runner.invoke(
        chrome_dump, [*chrome_user_data.argv, 'list-reporting', '--table', 'endpoints', '--json'])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert [row['url']
            for row in data] == ['https://a.example.com/reports', 'https://b.example.com/reports']


def test_list_reporting_groups_json(runner: CliRunner,
                                    chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_nel_db(chrome_user_data)
    result = runner.invoke(
        chrome_dump, [*chrome_user_data.argv, 'list-reporting', '--table', 'groups', '--json'])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert [row['origin_host'] for row in data] == ['a.example.com', 'b.example.com']
    assert data[0]['is_include_subdomains'] is False


def test_list_reporting_search(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_nel_db(chrome_user_data)
    result = runner.invoke(
        chrome_dump,
        [*chrome_user_data.argv, 'list-reporting', '--search', 'b.example.com', '--json'])
    assert result.exit_code == 0, result.output
    assert [row['origin_host'] for row in json.loads(result.output)] == ['b.example.com']


# list-sessions


def test_list_sessions_table(runner: CliRunner, chrome_user_data: FakeChromeUserData,
                             monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('COLUMNS', '200')
    profile = chrome_user_data.add_profile('Default')
    sessions_path = profile / 'Sessions'
    sessions_path.mkdir()
    valid_records = _snss_record(1, b'hello https://example.com/a')
    (sessions_path / f'Session_{WEBKIT_A}').write_bytes(_snss_file(valid_records))
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-sessions'])
    assert result.exit_code == 0, result.output
    assert 'Sessions in Default' in result.output
    assert f'Session_{WEBKIT_A}' in result.output


def test_list_sessions_json(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    sessions_path = profile / 'Sessions'
    sessions_path.mkdir()
    valid_records = _snss_record(1, b'hello https://example.com/a')
    (sessions_path / f'Session_{WEBKIT_A}').write_bytes(_snss_file(valid_records))
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-sessions', '--json'])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data[0]['name'] == f'Session_{WEBKIT_A}'
    assert data[0]['urls'] == ['https://example.com/a']


def test_list_sessions_urls_flag_table(runner: CliRunner, chrome_user_data: FakeChromeUserData,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('COLUMNS', '200')
    profile = chrome_user_data.add_profile('Default')
    sessions_path = profile / 'Sessions'
    sessions_path.mkdir()
    valid_records = _snss_record(1, b'hello https://example.com/a')
    (sessions_path / f'Session_{WEBKIT_A}').write_bytes(_snss_file(valid_records))
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-sessions', '--urls'])
    assert result.exit_code == 0, result.output
    assert 'https://example.com/a' in result.output


# Missing-path aborts shared by the remaining commands.


@pytest.mark.parametrize(('args', 'message'), [
    (['list-dips'], 'DIPS'),
    (['list-reporting'], 'Reporting and NEL'),
    (['list-sessions'], 'Sessions'),
])
def test_missing_path_aborts(runner: CliRunner, chrome_user_data: FakeChromeUserData,
                             args: list[str], message: str) -> None:
    chrome_user_data.add_profile('Default')
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, *args])
    assert result.exit_code != 0
    assert message in result.stderr
    assert 'does not exist.' in result.stderr
