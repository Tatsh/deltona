"""Tests for :py:mod:`deltona.chrome.secrets` and :py:mod:`deltona.commands.chrome_secrets`."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import TYPE_CHECKING, Any
import json

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf import pbkdf2
import pytest

from deltona.chrome import OSCrypt
from deltona.chrome.secrets import (
    cookie_database_version,
    decode_cookie_priority,
    decode_cookie_samesite,
    decode_cookie_source_scheme,
    decode_insecurity_type,
    decode_login_scheme,
    iter_addresses,
    iter_ai_entities,
    iter_autocomplete,
    iter_autofill,
    iter_cookies,
    iter_login_stats,
    iter_logins,
    iter_payment_table,
    iter_plus_addresses,
    iter_sign_in_tokens,
)
from deltona.commands.chrome import chrome_dump

if TYPE_CHECKING:
    from pathlib import Path

    from click.testing import CliRunner
    from pytest_mock import MockerFixture

    from .conftest import FakeChromeUserData

UTC = timezone.utc
_WEBKIT_EPOCH = datetime(1601, 1, 1, tzinfo=UTC)
_V99_BLOB = b'v99'
_V11_BLOB = b'v11' + bytes(range(16))
_LOGINS_SCHEMA = (
    ('CREATE TABLE logins (id INTEGER PRIMARY KEY, origin_url VARCHAR NOT NULL, '
     'username_value VARCHAR, password_value BLOB, signon_realm VARCHAR NOT NULL, '
     'scheme INTEGER NOT NULL, blacklisted_by_user INTEGER NOT NULL, times_used INTEGER NOT NULL, '
     'date_created INTEGER NOT NULL, date_last_used INTEGER NOT NULL, '
     'date_password_modified INTEGER NOT NULL)'),
    ('CREATE TABLE insecure_credentials (parent_id INTEGER NOT NULL, '
     'insecurity_type INTEGER NOT NULL)'),
    'CREATE TABLE password_notes (parent_id INTEGER NOT NULL, key VARCHAR NOT NULL, value BLOB)',
    ('CREATE TABLE stats (origin_domain VARCHAR, username_value VARCHAR, '
     'dismissal_count INTEGER, update_time INTEGER)'),
)
_COOKIES_SCHEMA = (('CREATE TABLE cookies (creation_utc INTEGER NOT NULL, host_key TEXT NOT NULL, '
                    'name TEXT NOT NULL, value TEXT NOT NULL, encrypted_value BLOB NOT NULL, '
                    'path TEXT NOT NULL, expires_utc INTEGER NOT NULL, is_secure INTEGER NOT NULL, '
                    'is_httponly INTEGER NOT NULL, last_access_utc INTEGER NOT NULL, '
                    'has_expires INTEGER NOT NULL, is_persistent INTEGER NOT NULL, '
                    'priority INTEGER NOT NULL, samesite INTEGER NOT NULL, '
                    'source_scheme INTEGER NOT NULL, source_port INTEGER NOT NULL)'),)
_CREDIT_CARDS_SCHEMA = (('CREATE TABLE credit_cards (guid VARCHAR PRIMARY KEY, '
                         'name_on_card VARCHAR, card_number_encrypted BLOB, '
                         'date_modified INTEGER)'),)
_MASKED_CREDIT_CARDS_SCHEMA = (('CREATE TABLE masked_credit_cards (id VARCHAR PRIMARY KEY, '
                                'network VARCHAR, last_four VARCHAR)'),)
_LOCAL_IBANS_SCHEMA = (('CREATE TABLE local_ibans (guid VARCHAR PRIMARY KEY, '
                        'value_encrypted BLOB, use_date INTEGER)'),)
_SERVER_CARD_METADATA_SCHEMA = (('CREATE TABLE server_card_metadata (id VARCHAR PRIMARY KEY, '
                                 'use_date INTEGER)'),)
_LOCAL_STORED_CVC_SCHEMA = (('CREATE TABLE local_stored_cvc (guid VARCHAR PRIMARY KEY, '
                             'value_encrypted BLOB, last_updated_timestamp INTEGER)'),)
_SERVER_STORED_CVC_SCHEMA = (('CREATE TABLE server_stored_cvc (guid VARCHAR PRIMARY KEY, '
                              'value_encrypted BLOB)'),)
_AUTOFILL_SCHEMA = (('CREATE TABLE autofill (name VARCHAR, value VARCHAR, '
                     'date_created INTEGER, date_last_used INTEGER)'),)
_AUTOCOMPLETE_SCHEMA = (('CREATE TABLE autocomplete (name VARCHAR, value VARCHAR, '
                         'date_created INTEGER, date_last_used INTEGER)'),)
_ADDRESSES_SCHEMA = (
    'CREATE TABLE address_type_tokens (guid VARCHAR, type INTEGER, value VARCHAR)',
    ('CREATE TABLE addresses (guid VARCHAR PRIMARY KEY, label VARCHAR, record_type INTEGER, '
     'language_code VARCHAR, use_count INTEGER, use_date INTEGER, date_modified INTEGER)'),
)
_PLUS_ADDRESSES_SCHEMA = ('CREATE TABLE plus_addresses (facet VARCHAR, plus_address VARCHAR)',)
_AI_ENTITIES_SCHEMA = (
    ('CREATE TABLE autofill_ai_attributes (entity_guid VARCHAR, attribute_type VARCHAR, '
     'value_encrypted BLOB)'),
    ('CREATE TABLE autofill_ai_entities_metadata (entity_guid VARCHAR PRIMARY KEY, '
     'use_count INTEGER, use_date INTEGER, date_modified INTEGER)'),
    'CREATE TABLE autofill_ai_entities (guid VARCHAR PRIMARY KEY, entity_name VARCHAR)',
)
_TOKEN_SERVICE_SCHEMA = (('CREATE TABLE token_service (service VARCHAR PRIMARY KEY, '
                          'encrypted_token BLOB, binding_key BLOB, mtls_token_binding BLOB)'),)


def _webkit(when: datetime) -> int:
    return int((when - _WEBKIT_EPOCH).total_seconds() * 1_000_000)


def _unix(when: datetime) -> int:
    return int(when.timestamp())


def _encrypt_v10(plaintext: bytes, *, hash_prefix: bool = False) -> bytes:
    key = pbkdf2.PBKDF2HMAC(
        algorithm=hashes.SHA1(),  # noqa: S303
        iterations=1,
        length=16,
        salt=b'saltysalt').derive(b'peanuts')
    body = (sha256(b'example.com').digest() + plaintext) if hash_prefix else plaintext
    padding = 16 - (len(body) % 16)
    body += bytes([padding]) * padding
    encryptor = Cipher(algorithms.AES(key), modes.CBC(b' ' * 16)).encryptor()
    return b'v10' + encryptor.update(body) + encryptor.finalize()


def _write_login_data(chrome_user_data: FakeChromeUserData, directory: str, name: str) -> Path:
    created = _webkit(datetime(2023, 1, 1, tzinfo=UTC))
    last_used = _webkit(datetime(2023, 6, 1, tzinfo=UTC))
    update_time = _webkit(datetime(2023, 5, 1, tzinfo=UTC))
    rows = [
        (1, 'https://example.com/login', 'alice', _encrypt_v10(b'Sup3rSecretPass!'),
         'https://example.com/', 0, 0, 5, created, last_used, last_used),
        (2, 'https://blocked.example.com/login', None, b'', 'https://blocked.example.com/', 99, 1,
         0, created, 0, created),
    ]
    insecure = [(1, 0), (1, 3)]
    notes = [(1, 'security_question', _encrypt_v10(b'Some note text'))]
    stats = [('example.com', 'alice', 2, update_time)]
    return chrome_user_data.write_database(directory, name, _LOGINS_SCHEMA, {
        'logins': rows,
        'insecure_credentials': insecure,
        'password_notes': notes,
        'stats': stats,
    })


def _write_cookies_db(chrome_user_data: FakeChromeUserData, directory: str, name: str) -> Path:
    t1 = _webkit(datetime(2023, 1, 1, tzinfo=UTC))
    t2 = _webkit(datetime(2023, 2, 1, tzinfo=UTC))
    t3 = _webkit(datetime(2023, 3, 1, tzinfo=UTC))
    t4 = _webkit(datetime(2023, 4, 1, tzinfo=UTC))
    expires = _webkit(datetime(2024, 1, 1, tzinfo=UTC))
    rows = [
        (t1, '.example.com', 'session', '', _encrypt_v10(
            b'abc123token', hash_prefix=True), '/', expires, 1, 1, t1, 1, 1, 1, 1, 2, 443),
        (t2, '.sub.example.com', 'pref', 'plainvalue', b'x', '/', expires, 0, 0, t2, 0, 0, 2, 99, 0,
         80),
        (t3, '.other.com', 'v99blob', '', _V99_BLOB, '/', expires, 0, 0, t3, 0, 0, 0, 0, 1, 80),
        (t4, '.other.com', 'v11blob', '', _V11_BLOB, '/', expires, 0, 0, t4, 0, 0, 0, 0, 1, 80),
    ]
    return chrome_user_data.write_database(directory,
                                           name,
                                           _COOKIES_SCHEMA, {'cookies': rows},
                                           meta={'version': '24'})


def _write_web_data_payments(chrome_user_data: FakeChromeUserData, directory: str) -> Path:
    modified = _unix(datetime(2022, 5, 4, tzinfo=UTC))
    use_date = _webkit(datetime(2024, 3, 1, tzinfo=UTC))
    schema = (*_CREDIT_CARDS_SCHEMA, *_MASKED_CREDIT_CARDS_SCHEMA, *_LOCAL_IBANS_SCHEMA,
              *_SERVER_CARD_METADATA_SCHEMA)
    rows: dict[str, list[tuple[Any, ...]]] = {
        'credit_cards': [('card-1', 'Alice Doe', _encrypt_v10(b'4111111111111111'), modified)],
        'masked_credit_cards': [('mc-1', 'visa', '1111')],
        'server_card_metadata': [('meta-1', use_date)],
    }
    return chrome_user_data.write_database(directory, 'Web Data', schema, rows)


def _write_account_web_data_payments(chrome_user_data: FakeChromeUserData, directory: str) -> Path:
    schema = (*_LOCAL_STORED_CVC_SCHEMA, *_SERVER_STORED_CVC_SCHEMA)
    rows: dict[str, list[tuple[Any, ...]]] = {
        'local_stored_cvc': [('cvc-1', _encrypt_v10(b'123'), _unix(datetime(2023, 1, 1,
                                                                            tzinfo=UTC)))],
        'server_stored_cvc': [('cvc-2', _encrypt_v10(b'456'))],
    }
    return chrome_user_data.write_database(directory, 'Account Web Data', schema, rows)


def _write_autofill_web_data(chrome_user_data: FakeChromeUserData, directory: str) -> Path:
    schema = (*_AUTOFILL_SCHEMA, *_AUTOCOMPLETE_SCHEMA, *_ADDRESSES_SCHEMA, *_PLUS_ADDRESSES_SCHEMA,
              *_AI_ENTITIES_SCHEMA, *_TOKEN_SERVICE_SCHEMA)
    autofill_rows = [
        ('alice_pref', 'xyz123', _unix(datetime(
            2019, 1, 1, tzinfo=UTC)), _unix(datetime(2019, 2, 1, tzinfo=UTC))),
        ('search_query', 'weather today', _unix(datetime(2021, 1, 1, tzinfo=UTC)), 0),
        ('username', 'alice_autofill', _unix(datetime(
            2022, 1, 1, tzinfo=UTC)), _unix(datetime(2022, 6, 1, tzinfo=UTC))),
    ]
    autocomplete_rows = [('email', 'alice@example.com', _unix(datetime(
        2020, 1, 1, tzinfo=UTC)), _unix(datetime(2020, 2, 1, tzinfo=UTC)))]
    address_tokens = [('addr-1', 3, '123 Main St'), ('addr-1', 10, 'Springfield')]
    addresses = [('addr-1', 'Home', 0, 'en-US', 2, _unix(datetime(
        2022, 3, 1, tzinfo=UTC)), _unix(datetime(2022, 4, 1, tzinfo=UTC)))]
    plus_addresses = [('facet1', 'plus1@example.com'), ('facet2', 'plus2@example.com')]
    ai_attributes = [('ai-1', 'name', _encrypt_v10(b'John Doe'))]
    ai_metadata = [('ai-1', 3, _unix(datetime(
        2022, 1, 1, tzinfo=UTC)), _unix(datetime(2022, 2, 1, tzinfo=UTC)))]
    ai_entities = [('ai-1', 'Contact'), ('ai-2', 'Empty Entity')]
    token_service = [
        ('service-1', _encrypt_v10(b'token-abc'), b'somebindingkey', None),
        ('service-2', _encrypt_v10(b'token-xyz'), None, None),
    ]
    rows: dict[str, list[tuple[Any, ...]]] = {
        'autofill': autofill_rows,
        'autocomplete': autocomplete_rows,
        'address_type_tokens': address_tokens,
        'addresses': addresses,
        'plus_addresses': plus_addresses,
        'autofill_ai_attributes': ai_attributes,
        'autofill_ai_entities_metadata': ai_metadata,
        'autofill_ai_entities': ai_entities,
        'token_service': token_service,
    }
    return chrome_user_data.write_database(directory, 'Web Data', schema, rows)


@pytest.mark.parametrize(('value', 'expected'), [(0, 'HTML'), (1, 'BASIC'), (2, 'DIGEST'),
                                                 (3, 'OTHER'), (4, 'USERNAME_ONLY'), (99, '99')])
def test_decode_login_scheme(value: int, expected: str) -> None:
    assert decode_login_scheme(value) == expected


@pytest.mark.parametrize(('value', 'expected'), [(0, 'LEAKED'), (1, 'PHISHED'), (2, 'WEAK'),
                                                 (3, 'REUSED'), (99, '99')])
def test_decode_insecurity_type(value: int, expected: str) -> None:
    assert decode_insecurity_type(value) == expected


@pytest.mark.parametrize(('value', 'expected'), [(-1, 'UNSPECIFIED'), (0, 'NO_RESTRICTION'),
                                                 (1, 'LAX_MODE'), (2, 'STRICT_MODE'), (99, '99')])
def test_decode_cookie_samesite(value: int, expected: str) -> None:
    assert decode_cookie_samesite(value) == expected


@pytest.mark.parametrize(('value', 'expected'), [(0, 'LOW'), (1, 'MEDIUM'), (2, 'HIGH'),
                                                 (99, '99')])
def test_decode_cookie_priority(value: int, expected: str) -> None:
    assert decode_cookie_priority(value) == expected


@pytest.mark.parametrize(('value', 'expected'), [(0, 'UNSET'), (1, 'NON_SECURE'), (2, 'SECURE'),
                                                 (99, '99')])
def test_decode_cookie_source_scheme(value: int, expected: str) -> None:
    assert decode_cookie_source_scheme(value) == expected


def test_cookie_database_version_reads_meta(chrome_user_data: FakeChromeUserData) -> None:
    path = chrome_user_data.write_database('Default',
                                           'Cookies',
                                           _COOKIES_SCHEMA,
                                           meta={'version': '24'})
    assert cookie_database_version(path) == 24


def test_cookie_database_version_defaults_to_zero(chrome_user_data: FakeChromeUserData) -> None:
    path = chrome_user_data.write_database('Default',
                                           'Cookies',
                                           _COOKIES_SCHEMA,
                                           meta={'last_compatible_version': '1'})
    assert cookie_database_version(path) == 0


def test_iter_logins_decodes_and_decrypts(chrome_user_data: FakeChromeUserData) -> None:
    path = _write_login_data(chrome_user_data, 'Default', 'Login Data')
    first, second = list(iter_logins(path, OSCrypt()))
    assert first['password'] == 'Sup3rSecretPass!'
    assert first['scheme'] == 'HTML'
    assert first['insecurity_types'] == ['LEAKED', 'REUSED']
    assert first['blocklisted'] is False
    assert first['date_last_used'] is not None
    assert first['date_last_used'].year == 2023
    assert first['notes'] == {'security_question': 'Some note text'}
    assert second['password'] is None
    assert second['scheme'] == '99'
    assert second['blocklisted'] is True
    assert second['insecurity_types'] == []
    assert second['date_last_used'] is None
    assert second['notes'] == {}


def test_iter_logins_empty(chrome_user_data: FakeChromeUserData) -> None:
    path = chrome_user_data.write_database('Default', 'Login Data', _LOGINS_SCHEMA)
    assert list(iter_logins(path, OSCrypt())) == []


def test_iter_login_stats_converts_update_time(chrome_user_data: FakeChromeUserData) -> None:
    path = _write_login_data(chrome_user_data, 'Default', 'Login Data')
    [row] = list(iter_login_stats(path))
    assert row['origin_domain'] == 'example.com'
    assert row['update_time'] is not None
    assert row['update_time'].year == 2023


def test_iter_login_stats_empty(chrome_user_data: FakeChromeUserData) -> None:
    path = chrome_user_data.write_database('Default', 'Login Data', _LOGINS_SCHEMA)
    assert list(iter_login_stats(path)) == []


def test_iter_cookies_strips_hash_prefix_at_version_24(
        chrome_user_data: FakeChromeUserData) -> None:
    creation = _webkit(datetime(2023, 1, 1, tzinfo=UTC))
    rows = [(creation, '.example.com', 'session', '', _encrypt_v10(
        b'abc123token', hash_prefix=True), '/', creation, 1, 1, creation, 1, 1, 1, 1, 2, 443)]
    path = chrome_user_data.write_database('Default',
                                           'Cookies',
                                           _COOKIES_SCHEMA, {'cookies': rows},
                                           meta={'version': '24'})
    [cookie] = list(iter_cookies(path, OSCrypt()))
    assert cookie['value'] == 'abc123token'


def test_iter_cookies_no_hash_prefix_before_version_24(
        chrome_user_data: FakeChromeUserData) -> None:
    creation = _webkit(datetime(2022, 1, 1, tzinfo=UTC))
    rows = [(creation, '.example.com', 'legacy', '', _encrypt_v10(b'legacyvalue'), '/', creation, 0,
             0, creation, 0, 0, 0, 0, 0, 80)]
    path = chrome_user_data.write_database('Default',
                                           'Cookies',
                                           _COOKIES_SCHEMA, {'cookies': rows},
                                           meta={'version': '23'})
    [cookie] = list(iter_cookies(path, OSCrypt()))
    assert cookie['value'] == 'legacyvalue'


def test_iter_cookies_empty(chrome_user_data: FakeChromeUserData) -> None:
    path = chrome_user_data.write_database('Default',
                                           'Cookies',
                                           _COOKIES_SCHEMA,
                                           meta={'version': '24'})
    assert list(iter_cookies(path, OSCrypt())) == []


def test_iter_payment_table_decrypts_and_converts_dates(
        chrome_user_data: FakeChromeUserData) -> None:
    modified = _unix(datetime(2022, 5, 4, tzinfo=UTC))
    rows = [('card-1', 'Alice Doe', _encrypt_v10(b'4111111111111111'), modified)]
    path = chrome_user_data.write_database('Default', 'Web Data', _CREDIT_CARDS_SCHEMA,
                                           {'credit_cards': rows})
    [card] = list(iter_payment_table(path, 'credit_cards', OSCrypt()))
    assert card['card_number'] == '4111111111111111'
    assert 'card_number_encrypted' not in card
    assert card['name_on_card'] == 'Alice Doe'
    assert card['date_modified'] is not None
    assert card['date_modified'].year == 2022


def test_iter_payment_table_without_encrypted_column(chrome_user_data: FakeChromeUserData) -> None:
    rows = [('card-1', 'visa', '1111')]
    path = chrome_user_data.write_database('Default', 'Web Data', _MASKED_CREDIT_CARDS_SCHEMA,
                                           {'masked_credit_cards': rows})
    [card] = list(iter_payment_table(path, 'masked_credit_cards', OSCrypt()))
    assert card == {'id': 'card-1', 'network': 'visa', 'last_four': '1111'}


def test_iter_payment_table_microseconds_since_1601(chrome_user_data: FakeChromeUserData) -> None:
    use_date = _webkit(datetime(2024, 3, 1, tzinfo=UTC))
    rows = [('meta-1', use_date)]
    path = chrome_user_data.write_database('Default', 'Web Data', _SERVER_CARD_METADATA_SCHEMA,
                                           {'server_card_metadata': rows})
    [row] = list(iter_payment_table(path, 'server_card_metadata', OSCrypt()))
    assert row['use_date'].year == 2024


def test_iter_payment_table_empty(chrome_user_data: FakeChromeUserData) -> None:
    path = chrome_user_data.write_database('Default', 'Web Data', _CREDIT_CARDS_SCHEMA)
    assert list(iter_payment_table(path, 'credit_cards', OSCrypt())) == []


def test_iter_autofill_converts_timestamps(chrome_user_data: FakeChromeUserData) -> None:
    created = _unix(datetime(2022, 1, 1, tzinfo=UTC))
    rows = [('username', 'alice', created, created)]
    path = chrome_user_data.write_database('Default', 'Web Data', _AUTOFILL_SCHEMA,
                                           {'autofill': rows})
    [row] = list(iter_autofill(path))
    assert row['name'] == 'username'
    assert row['date_created'].year == 2022


def test_iter_autofill_empty(chrome_user_data: FakeChromeUserData) -> None:
    path = chrome_user_data.write_database('Default', 'Web Data', _AUTOFILL_SCHEMA)
    assert list(iter_autofill(path)) == []


def test_iter_autofill_returns_empty_when_table_is_missing(
        chrome_user_data: FakeChromeUserData) -> None:
    path = chrome_user_data.write_database('Default', 'Web Data', ())
    assert list(iter_autofill(path)) == []


def test_iter_autocomplete_converts_timestamps(chrome_user_data: FakeChromeUserData) -> None:
    created = _unix(datetime(2021, 1, 1, tzinfo=UTC))
    rows = [('email', 'alice@example.com', created, created)]
    path = chrome_user_data.write_database('Default', 'Web Data', _AUTOCOMPLETE_SCHEMA,
                                           {'autocomplete': rows})
    [row] = list(iter_autocomplete(path))
    assert row['value'] == 'alice@example.com'
    assert row['date_created'].year == 2021


def test_iter_autocomplete_empty(chrome_user_data: FakeChromeUserData) -> None:
    path = chrome_user_data.write_database('Default', 'Web Data', _AUTOCOMPLETE_SCHEMA)
    assert list(iter_autocomplete(path)) == []


def test_iter_addresses_joins_tokens(chrome_user_data: FakeChromeUserData) -> None:
    use_date = _unix(datetime(2022, 3, 1, tzinfo=UTC))
    modified = _unix(datetime(2022, 4, 1, tzinfo=UTC))
    tokens = [('addr-1', 3, '123 Main St'), ('addr-1', 10, 'Springfield')]
    addresses = [
        ('addr-1', 'Home', 0, 'en-US', 2, use_date, modified),
        ('addr-2', 'Work', 1, 'en-GB', 0, use_date, modified),
    ]
    path = chrome_user_data.write_database('Default', 'Web Data', _ADDRESSES_SCHEMA, {
        'address_type_tokens': tokens,
        'addresses': addresses
    })
    [first, second] = list(iter_addresses(path))
    assert first['tokens'] == {3: '123 Main St', 10: 'Springfield'}
    assert first['use_date'] is not None
    assert first['use_date'].year == 2022
    assert second['tokens'] == {}


def test_iter_addresses_empty(chrome_user_data: FakeChromeUserData) -> None:
    path = chrome_user_data.write_database('Default', 'Web Data', _ADDRESSES_SCHEMA)
    assert list(iter_addresses(path)) == []


def test_iter_plus_addresses_lists_rows(chrome_user_data: FakeChromeUserData) -> None:
    rows = [('facet1', 'plus1@example.com')]
    path = chrome_user_data.write_database('Default', 'Web Data', _PLUS_ADDRESSES_SCHEMA,
                                           {'plus_addresses': rows})
    assert list(iter_plus_addresses(path)) == [{
        'facet': 'facet1',
        'plus_address': 'plus1@example.com'
    }]


def test_iter_plus_addresses_empty(chrome_user_data: FakeChromeUserData) -> None:
    path = chrome_user_data.write_database('Default', 'Web Data', _PLUS_ADDRESSES_SCHEMA)
    assert list(iter_plus_addresses(path)) == []


def test_iter_ai_entities_decrypts_attributes_and_joins_metadata(
        chrome_user_data: FakeChromeUserData) -> None:
    attributes = [('ai-1', 'name', _encrypt_v10(b'John Doe'))]
    metadata = [('ai-1', 3, _unix(datetime(2022, 1, 1,
                                           tzinfo=UTC)), _unix(datetime(2022, 2, 1, tzinfo=UTC)))]
    entities = [('ai-1', 'Contact'), ('ai-2', 'Empty Entity')]
    path = chrome_user_data.write_database(
        'Default', 'Web Data', _AI_ENTITIES_SCHEMA, {
            'autofill_ai_attributes': attributes,
            'autofill_ai_entities_metadata': metadata,
            'autofill_ai_entities': entities,
        })
    [first, second] = list(iter_ai_entities(path, OSCrypt()))
    assert first['attributes'] == {'name': 'John Doe'}
    assert first['use_count'] == 3
    assert first['use_date'] is not None
    assert first['use_date'].year == 2022
    assert second['attributes'] == {}
    assert second['use_count'] is None
    assert second['use_date'] is None
    assert second['date_modified'] is None


def test_iter_ai_entities_empty(chrome_user_data: FakeChromeUserData) -> None:
    path = chrome_user_data.write_database('Default', 'Web Data', _AI_ENTITIES_SCHEMA)
    assert list(iter_ai_entities(path, OSCrypt())) == []


def test_iter_sign_in_tokens_decrypts_and_reports_binding(
        chrome_user_data: FakeChromeUserData) -> None:
    rows = [
        ('service-1', _encrypt_v10(b'token-abc'), b'somebindingkey', None),
        ('service-2', _encrypt_v10(b'token-xyz'), None, None),
    ]
    path = chrome_user_data.write_database('Default', 'Web Data', _TOKEN_SERVICE_SCHEMA,
                                           {'token_service': rows})
    first, second = list(iter_sign_in_tokens(path, OSCrypt()))
    assert first['token'] == 'token-abc'
    assert first['is_bound'] is True
    assert second['token'] == 'token-xyz'
    assert second['is_bound'] is False


def test_iter_sign_in_tokens_empty(chrome_user_data: FakeChromeUserData) -> None:
    path = chrome_user_data.write_database('Default', 'Web Data', _TOKEN_SERVICE_SCHEMA)
    assert list(iter_sign_in_tokens(path, OSCrypt())) == []


def test_list_passwords_masks_by_default(runner: CliRunner,
                                         chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_login_data(chrome_user_data, 'Default', 'Login Data')
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-passwords', '-P', 'Default'])
    assert result.exit_code == 0, result.output
    assert 'Sup3rSecretPass!' not in result.output
    assert 'Some note text' not in result.output
    assert 'alice' in result.output
    rows = json.loads(
        runner.invoke(chrome_dump,
                      [*chrome_user_data.argv, 'list-passwords', '-P', 'Default', '-j']).output)
    assert all(set(row['password']) == {'*'} or row['password'] == '(encrypted)' for row in rows)
    assert any(set(row['password']) == {'*'} for row in rows)


def test_list_passwords_show_passwords_reveals_plaintext(
        runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_login_data(chrome_user_data, 'Default', 'Login Data')
    result = runner.invoke(
        chrome_dump,
        [*chrome_user_data.argv, 'list-passwords', '-P', 'Default', '--show-passwords', '--json'])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    by_username = {row['username']: row for row in rows}
    assert by_username['alice']['password'] == 'Sup3rSecretPass!'
    assert by_username['alice']['scheme'] == 'HTML'
    assert by_username['alice']['insecurity_types'] == 'LEAKED, REUSED'
    assert by_username['alice']['notes'] == {'security_question': 'Some note text'}
    assert by_username[None]['scheme'] == '99'
    assert not by_username[None]['insecurity_types']
    assert by_username[None]['blocklisted'] is True
    assert by_username[None]['notes'] == {}


def test_list_passwords_stats_option(runner: CliRunner,
                                     chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_login_data(chrome_user_data, 'Default', 'Login Data')
    result = runner.invoke(
        chrome_dump,
        [*chrome_user_data.argv, 'list-passwords', '-P', 'Default', '--stats', '--json'])
    assert result.exit_code == 0, result.output
    [row] = json.loads(result.output)
    assert row['origin_domain'] == 'example.com'
    assert datetime.fromisoformat(row['update_time']).year == 2023


def test_list_passwords_account_flag_reads_account_database(
        runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    created = _webkit(datetime(2023, 1, 1, tzinfo=UTC))
    rows = [(1, 'https://work.example.com/login', 'bob', _encrypt_v10(b'WorkPass123'),
             'https://work.example.com/', 1, 0, 1, created, created, created)]
    chrome_user_data.write_database('Default', 'Login Data For Account', _LOGINS_SCHEMA,
                                    {'logins': rows})
    result = runner.invoke(
        chrome_dump, [*chrome_user_data.argv, 'list-passwords', '-P', 'Default', '-a', '--json'])
    assert result.exit_code == 0, result.output
    [row] = json.loads(result.output)
    assert row['username'] == 'bob'
    assert row['scheme'] == 'BASIC'


def test_list_passwords_missing_database(runner: CliRunner,
                                         chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-passwords', '-P', 'Default'])
    assert result.exit_code != 0
    assert 'does not exist' in result.output


def test_list_passwords_warns_when_no_decryption_key(runner: CliRunner,
                                                     chrome_user_data: FakeChromeUserData,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    chrome_user_data.add_profile('Default')
    _write_login_data(chrome_user_data, 'Default', 'Login Data')
    monkeypatch.setattr(OSCrypt, 'available', property(lambda _: False))
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-passwords', '-P', 'Default'])
    assert result.exit_code == 0, result.output
    assert 'No decryption key is available.' in result.output
    assert 'alice' in result.output


def test_list_cookies_masks_values_by_default(runner: CliRunner,
                                              chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_cookies_db(chrome_user_data, 'Default', 'Cookies')
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-cookies', '-P', 'Default'])
    assert result.exit_code == 0, result.output
    assert 'abc123token' not in result.output
    assert 'plainvalue' not in result.output
    rows = json.loads(
        runner.invoke(chrome_dump,
                      [*chrome_user_data.argv, 'list-cookies', '-P', 'Default', '-j']).output)
    assert all(set(row['value']) == {'*'} or row['value'] == '(encrypted)' for row in rows)
    assert any(set(row['value']) == {'*'} for row in rows)


def test_list_cookies_show_values_reveals_plaintext(runner: CliRunner,
                                                    chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_cookies_db(chrome_user_data, 'Default', 'Cookies')
    result = runner.invoke(
        chrome_dump,
        [*chrome_user_data.argv, 'list-cookies', '-P', 'Default', '--show-values', '-j'])
    assert result.exit_code == 0, result.output
    assert {'abc123token', 'plainvalue'} <= {row['value'] for row in json.loads(result.output)}


def test_list_cookies_json_decodes_enums_and_dates(runner: CliRunner,
                                                   chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_cookies_db(chrome_user_data, 'Default', 'Cookies')
    result = runner.invoke(chrome_dump,
                           [*chrome_user_data.argv, 'list-cookies', '-P', 'Default', '--json'])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    by_name = {row['name']: row for row in rows}
    assert by_name['session']['samesite'] == 'LAX_MODE'
    assert by_name['session']['priority'] == 'MEDIUM'
    assert by_name['session']['source_scheme'] == 'SECURE'
    assert by_name['pref']['samesite'] == '99'
    assert by_name['pref']['priority'] == 'HIGH'
    assert by_name['pref']['source_scheme'] == 'UNSET'
    assert datetime.fromisoformat(by_name['session']['creation']).year == 2023
    assert datetime.fromisoformat(by_name['session']['expires']).year == 2024


def test_list_cookies_host_filter(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_cookies_db(chrome_user_data, 'Default', 'Cookies')
    result = runner.invoke(
        chrome_dump,
        [*chrome_user_data.argv, 'list-cookies', '-P', 'Default', '--json', '-H', 'sub'])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    assert [row['host'] for row in rows] == ['.sub.example.com']


@pytest.mark.parametrize(('limit', 'expected_names'), [
    ('1', ['session']),
    ('0', ['session', 'pref', 'v99blob', 'v11blob']),
])
def test_list_cookies_limit(runner: CliRunner, chrome_user_data: FakeChromeUserData, limit: str,
                            expected_names: list[str]) -> None:
    chrome_user_data.add_profile('Default')
    _write_cookies_db(chrome_user_data, 'Default', 'Cookies')
    result = runner.invoke(
        chrome_dump,
        [*chrome_user_data.argv, 'list-cookies', '-P', 'Default', '--json', '-l', limit])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    assert [row['name'] for row in rows] == expected_names


@pytest.mark.parametrize(('database', 'directory_name'),
                         [('extension', 'Extension Cookies'),
                          ('safe-browsing', 'Safe Browsing Cookies')])
def test_list_cookies_database_choice(runner: CliRunner, chrome_user_data: FakeChromeUserData,
                                      database: str, directory_name: str) -> None:
    chrome_user_data.add_profile('Default')
    _write_cookies_db(chrome_user_data, 'Default', directory_name)
    result = runner.invoke(
        chrome_dump,
        [*chrome_user_data.argv, 'list-cookies', '-P', 'Default', '--json', '--database', database])
    assert result.exit_code == 0, result.output
    assert len(json.loads(result.output)) == 4


def test_list_cookies_missing_database(runner: CliRunner,
                                       chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-cookies', '-P', 'Default'])
    assert result.exit_code != 0
    assert 'does not exist' in result.output


def test_list_payments_masks_numbers_by_default(runner: CliRunner,
                                                chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_web_data_payments(chrome_user_data, 'Default')
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-payments', '-P', 'Default'])
    assert result.exit_code == 0, result.output
    assert '4111111111111111' not in result.output
    assert 'Credit Cards' in result.output
    assert 'Masked Credit Cards' in result.output


def test_list_payments_show_numbers_reveals_plaintext(runner: CliRunner,
                                                      chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_web_data_payments(chrome_user_data, 'Default')
    result = runner.invoke(
        chrome_dump,
        [*chrome_user_data.argv, 'list-payments', '-P', 'Default', '--show-numbers', '--json'])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data['credit_cards'][0]['card_number'] == '4111111111111111'
    assert datetime.fromisoformat(data['credit_cards'][0]['date_modified']).year == 2022
    assert datetime.fromisoformat(data['server_card_metadata'][0]['use_date']).year == 2024
    assert 'local_ibans' not in data


def test_list_payments_table_option_selects_one_table(runner: CliRunner,
                                                      chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_web_data_payments(chrome_user_data, 'Default')
    result = runner.invoke(chrome_dump, [
        *chrome_user_data.argv, 'list-payments', '-P', 'Default', '--json', '-t',
        'masked_credit_cards'
    ])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == [{'id': 'mc-1', 'network': 'visa', 'last_four': '1111'}]


def test_list_payments_table_option_includes_empty_table(
        runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_web_data_payments(chrome_user_data, 'Default')
    result = runner.invoke(
        chrome_dump,
        [*chrome_user_data.argv, 'list-payments', '-P', 'Default', '--json', '-t', 'local_ibans'])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == []


def test_list_payments_table_option_missing_from_schema(
        runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_web_data_payments(chrome_user_data, 'Default')
    result = runner.invoke(
        chrome_dump,
        [*chrome_user_data.argv, 'list-payments', '-P', 'Default', '-t', 'loyalty_cards'])
    assert result.exit_code != 0
    assert 'does not exist' in result.output


def test_list_payments_account_flag_reads_account_database(
        runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_account_web_data_payments(chrome_user_data, 'Default')
    result = runner.invoke(chrome_dump, [
        *chrome_user_data.argv, 'list-payments', '-P', 'Default', '-a', '--show-numbers', '--json'
    ])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data['local_stored_cvc'][0]['value'] == '123'
    assert data['server_stored_cvc'][0]['value'] == '456'


def test_list_payments_missing_database(runner: CliRunner,
                                        chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-payments', '-P', 'Default'])
    assert result.exit_code != 0
    assert 'does not exist' in result.output


def test_list_payments_reports_no_data(runner: CliRunner,
                                       chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    chrome_user_data.write_database('Default', 'Web Data', ('CREATE TABLE keywords (id INTEGER)',))
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-payments', '-P', 'Default'])
    assert result.exit_code == 0, result.output
    assert 'No payment data found.' in result.output


def test_list_autofill_default_combines_autofill_and_autocomplete(
        runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_autofill_web_data(chrome_user_data, 'Default')
    result = runner.invoke(chrome_dump,
                           [*chrome_user_data.argv, 'list-autofill', '-P', 'Default', '--json'])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    assert {row['name'] for row in rows} == {'alice_pref', 'search_query', 'username', 'email'}


def test_list_autofill_addresses(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_autofill_web_data(chrome_user_data, 'Default')
    result = runner.invoke(
        chrome_dump,
        [*chrome_user_data.argv, 'list-autofill', '-P', 'Default', '--json', '--addresses'])
    assert result.exit_code == 0, result.output
    [address] = json.loads(result.output)
    assert address['tokens'] == {'3': '123 Main St', '10': 'Springfield'}
    assert datetime.fromisoformat(address['use_date']).year == 2022


def test_list_autofill_plus_addresses(runner: CliRunner,
                                      chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_autofill_web_data(chrome_user_data, 'Default')
    result = runner.invoke(
        chrome_dump,
        [*chrome_user_data.argv, 'list-autofill', '-P', 'Default', '--json', '--plus-addresses'])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    assert {row['facet'] for row in rows} == {'facet1', 'facet2'}


def test_list_autofill_search_matches_name_or_value(runner: CliRunner,
                                                    chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_autofill_web_data(chrome_user_data, 'Default')
    result = runner.invoke(
        chrome_dump,
        [*chrome_user_data.argv, 'list-autofill', '-P', 'Default', '--json', '-s', 'alice'])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    assert {row['name'] for row in rows} == {'alice_pref', 'username', 'email'}


@pytest.mark.parametrize(('limit', 'expected_count'), [('1', 1), ('0', 4)])
def test_list_autofill_limit(runner: CliRunner, chrome_user_data: FakeChromeUserData, limit: str,
                             expected_count: int) -> None:
    chrome_user_data.add_profile('Default')
    _write_autofill_web_data(chrome_user_data, 'Default')
    result = runner.invoke(
        chrome_dump,
        [*chrome_user_data.argv, 'list-autofill', '-P', 'Default', '--json', '-l', limit])
    assert result.exit_code == 0, result.output
    assert len(json.loads(result.output)) == expected_count


def test_list_autofill_missing_database(runner: CliRunner,
                                        chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-autofill', '-P', 'Default'])
    assert result.exit_code != 0
    assert 'does not exist' in result.output


def test_list_autofill_ai_entities_masks_by_default(runner: CliRunner,
                                                    chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_autofill_web_data(chrome_user_data, 'Default')
    result = runner.invoke(
        chrome_dump, [*chrome_user_data.argv, 'list-autofill', '-P', 'Default', '--ai-entities'])
    assert result.exit_code == 0, result.output
    assert 'John Doe' not in result.output


def test_list_autofill_ai_entities_show_values_reveals_plaintext(
        runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_autofill_web_data(chrome_user_data, 'Default')
    result = runner.invoke(chrome_dump, [
        *chrome_user_data.argv, 'list-autofill', '-P', 'Default', '--ai-entities', '--show-values',
        '--json'
    ])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    by_guid = {row['guid']: row for row in rows}
    assert by_guid['ai-1']['attributes']['name'] == 'John Doe'
    assert by_guid['ai-1']['use_count'] == 3
    assert datetime.fromisoformat(by_guid['ai-1']['use_date']).year == 2022
    assert by_guid['ai-2']['attributes'] == {}
    assert by_guid['ai-2']['use_count'] is None
    assert by_guid['ai-2']['use_date'] is None


def _write_accounts_preferences(chrome_user_data: FakeChromeUserData, directory: str) -> None:
    chrome_user_data.write_json(
        directory, 'Preferences', {
            'account_info': [{
                'account_id': 'gaia-1',
                'email': 'alice@example.com',
                'full_name': 'Alice Example',
                'gaia': 'gaia-1',
                'hosted_domain': '',
                'is_supervised_child': False,
                'is_under_advanced_protection': False,
                'locale': 'en-US',
                'picture_url': 'https://example.com/alice.png',
            }, 'not-a-dict-entry']
        })


def test_list_accounts_masks_tokens_by_default(runner: CliRunner,
                                               chrome_user_data: FakeChromeUserData) -> None:
    _write_accounts_preferences(chrome_user_data, 'Default')
    chrome_user_data.add_profile('Default')
    _write_autofill_web_data(chrome_user_data, 'Default')
    result = runner.invoke(chrome_dump,
                           [*chrome_user_data.argv, 'list-accounts', '-P', 'Default', '-j'])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload['accounts'][0]['email'] == 'alice@example.com'
    assert 'token-abc' not in result.output


def test_list_accounts_json_and_show_tokens(runner: CliRunner,
                                            chrome_user_data: FakeChromeUserData) -> None:
    _write_accounts_preferences(chrome_user_data, 'Default')
    chrome_user_data.add_profile('Default')
    _write_autofill_web_data(chrome_user_data, 'Default')
    result = runner.invoke(
        chrome_dump,
        [*chrome_user_data.argv, 'list-accounts', '-P', 'Default', '--show-tokens', '--json'])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert len(data['accounts']) == 1
    assert data['accounts'][0]['email'] == 'alice@example.com'
    tokens_by_service = {row['service']: row for row in data['tokens']}
    assert tokens_by_service['service-1']['token'] == 'token-abc'
    assert tokens_by_service['service-1']['is_bound'] is True
    assert tokens_by_service['service-2']['is_bound'] is False


def test_list_accounts_without_preferences_or_web_data(
        runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.local_state['profile']['info_cache']['Default'] = {}
    chrome_user_data.write_local_state()
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-accounts', '-P', 'Default'])
    assert result.exit_code == 0, result.output
    assert 'No accounts in default found.' in result.output
    assert 'No sign-in tokens found.' in result.output


def test_list_accounts_ignores_invalid_preferences_json(
        runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    chrome_user_data.write_text('Default', 'Preferences', '{not valid json')
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-accounts', '-P', 'Default'])
    assert result.exit_code == 0, result.output
    assert 'No accounts in default found.' in result.output


def test_list_accounts_ignores_non_dict_preferences_json(
        runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    chrome_user_data.write_text('Default', 'Preferences', '[]')
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-accounts', '-P', 'Default'])
    assert result.exit_code == 0, result.output
    assert 'No accounts in default found.' in result.output


def test_list_passwords_tolerates_an_older_schema(runner: CliRunner,
                                                  chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    chrome_user_data.write_database(
        'Default', 'Login Data', _LOGINS_SCHEMA[:1], {
            'logins': [(1, 'https://example.com/login', 'alice', _encrypt_v10(b'pw'),
                        'https://example.com/', 0, 0, 5, 0, 0, 0)]
        })
    result = runner.invoke(chrome_dump,
                           [*chrome_user_data.argv, 'list-passwords', '-P', 'Default', '-j'])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    assert not rows[0]['insecurity_types']
    assert rows[0]['notes'] == {}


def test_list_passwords_stats_tolerates_an_older_schema(
        runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    chrome_user_data.write_database('Default', 'Login Data', _LOGINS_SCHEMA[:1])
    result = runner.invoke(
        chrome_dump, [*chrome_user_data.argv, 'list-passwords', '-P', 'Default', '--stats', '-j'])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == []


def test_list_passwords_suggests_the_account_database(runner: CliRunner,
                                                      chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    chrome_user_data.write_database('Default', 'Login Data', _LOGINS_SCHEMA)
    _write_login_data(chrome_user_data, 'Default', 'Login Data For Account')
    result = runner.invoke(chrome_dump,
                           [*chrome_user_data.argv, 'list-passwords', '-P', 'Default', '-j'])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == []
    assert 'pass --account' in result.stderr


def test_list_payments_suggests_the_account_database(runner: CliRunner,
                                                     chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    chrome_user_data.write_database('Default', 'Web Data', ('CREATE TABLE keywords (id INTEGER)',))
    chrome_user_data.write_database('Default', 'Account Web Data',
                                    ('CREATE TABLE keywords (id INTEGER)',))
    result = runner.invoke(chrome_dump,
                           [*chrome_user_data.argv, 'list-payments', '-P', 'Default', '-j'])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {}
    assert 'pass --account' in result.stderr


def test_list_passwords_reports_values_it_could_not_decrypt(runner: CliRunner,
                                                            chrome_user_data: FakeChromeUserData,
                                                            mocker: MockerFixture) -> None:
    chrome_user_data.add_profile('Default')
    _write_login_data(chrome_user_data, 'Default', 'Login Data')
    mocker.patch('deltona.chrome.core.linux_keyring_password', return_value=None)
    mocker.patch('deltona.chrome.core.OSCrypt.decrypt', return_value=None)
    result = runner.invoke(chrome_dump,
                           [*chrome_user_data.argv, 'list-passwords', '-P', 'Default', '-j'])
    assert result.exit_code == 0, result.output
    assert 'could not be decrypted' in result.stderr
    assert 'desktop keyring' in result.stderr


def test_list_passwords_omits_the_keyring_hint_when_the_key_was_found(
        runner: CliRunner, chrome_user_data: FakeChromeUserData, mocker: MockerFixture) -> None:
    chrome_user_data.add_profile('Default')
    _write_login_data(chrome_user_data, 'Default', 'Login Data')
    mocker.patch('deltona.chrome.core.OSCrypt.decrypt', return_value=None)
    mocker.patch('deltona.chrome.core.OSCrypt.keyring_available',
                 new_callable=mocker.PropertyMock,
                 return_value=True)
    result = runner.invoke(chrome_dump,
                           [*chrome_user_data.argv, 'list-passwords', '-P', 'Default', '-j'])
    assert result.exit_code == 0, result.output
    assert 'could not be decrypted' in result.stderr
    assert 'desktop keyring' not in result.stderr
