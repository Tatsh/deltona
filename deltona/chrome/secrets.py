"""Passwords, cookies, payment methods, and autofill data from a Chrome profile."""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING, Any
import logging
import sqlite3

from .core import (
    OSCrypt,
    chrome_timestamp_to_datetime,
    query_database,
    unix_timestamp_to_datetime,
    webkit_timestamp_to_datetime,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from deltona.typing import StrPath

__all__ = (
    'COOKIE_DATABASES',
    'PAYMENT_SECRET_FIELDS',
    'PAYMENT_TABLES',
    'cookie_database_version',
    'decode_cookie_priority',
    'decode_cookie_samesite',
    'decode_cookie_source_scheme',
    'decode_insecurity_type',
    'decode_login_scheme',
    'iter_addresses',
    'iter_ai_entities',
    'iter_autocomplete',
    'iter_autofill',
    'iter_cookies',
    'iter_login_stats',
    'iter_logins',
    'iter_payment_table',
    'iter_plus_addresses',
    'iter_sign_in_tokens',
)

log = logging.getLogger(__name__)

_HASH_PREFIX_VERSION = 24
_LOGIN_SCHEMES: dict[int, str] = {
    0: 'HTML',
    1: 'BASIC',
    2: 'DIGEST',
    3: 'OTHER',
    4: 'USERNAME_ONLY'
}
_INSECURITY_TYPES: dict[int, str] = {0: 'LEAKED', 1: 'PHISHED', 2: 'WEAK', 3: 'REUSED'}
_COOKIE_SAMESITE: dict[int, str] = {
    -1: 'UNSPECIFIED',
    0: 'NO_RESTRICTION',
    1: 'LAX_MODE',
    2: 'STRICT_MODE'
}
_COOKIE_PRIORITY: dict[int, str] = {0: 'LOW', 1: 'MEDIUM', 2: 'HIGH'}
_COOKIE_SOURCE_SCHEME: dict[int, str] = {0: 'UNSET', 1: 'NON_SECURE', 2: 'SECURE'}
_PAYMENT_ENCRYPTED_COLUMNS: dict[str, str] = {
    'credit_cards': 'card_number_encrypted',
    'generic_payment_instruments': 'serialized_value_encrypted',
    'local_ibans': 'value_encrypted',
    'local_stored_cvc': 'value_encrypted',
    'payment_instrument_creation_options': 'serialized_value_encrypted',
    'server_stored_cvc': 'value_encrypted',
}
_PAYMENT_DATE_COLUMNS = frozenset({
    'date_created', 'date_modified', 'end_time', 'expire_date', 'expiry', 'last_updated_timestamp',
    'last_used', 'start_time', 'use_date'
})

COOKIE_DATABASES: dict[str, str] = {
    'cookies': 'Cookies',
    'extension': 'Extension Cookies',
    'safe-browsing': 'Safe Browsing Cookies'
}
"""
Map a ``--database`` choice to its file name within a profile directory.

:meta hide-value:
"""

PAYMENT_TABLES: tuple[str, ...] = (
    'credit_cards', 'masked_credit_cards', 'masked_credit_card_benefits',
    'benefit_merchant_domains', 'server_card_metadata', 'server_card_cloud_token_data',
    'local_stored_cvc', 'server_stored_cvc', 'local_ibans', 'masked_ibans', 'masked_ibans_metadata',
    'masked_bank_accounts', 'masked_bank_accounts_metadata', 'loyalty_cards',
    'loyalty_card_merchant_domain', 'valuables_metadata', 'payments_customer_data', 'offer_data',
    'offer_eligible_instrument', 'offer_merchant_domain', 'virtual_card_usage_data',
    'generic_payment_instruments', 'payment_instrument_creation_options', 'payment_method_manifest',
    'secure_payment_confirmation_instrument', 'secure_payment_confirmation_browser_bound_key',
    'web_app_manifest_section')
"""
Tables in ``Web Data``/``Account Web Data`` that make up the payments surface, in display order.

:meta hide-value:
"""

PAYMENT_SECRET_FIELDS: dict[str, str] = {
    'credit_cards': 'card_number',
    'generic_payment_instruments': 'serialized_value',
    'local_ibans': 'value',
    'local_stored_cvc': 'value',
    'payment_instrument_creation_options': 'serialized_value',
    'server_stored_cvc': 'value',
}
"""
Map a table in :py:data:`PAYMENT_TABLES` to the output field holding its decrypted secret.

Tables absent from this mapping have no encrypted column.

:meta hide-value:
"""


def _optional_rows(database_path: StrPath, sql: str) -> list[dict[str, Any]]:
    with suppress(sqlite3.OperationalError):
        return query_database(database_path, sql)
    log.debug('Skipping a table absent from this schema: %s', sql)
    return []


def decode_login_scheme(value: int) -> str:
    """
    Decode a ``logins.scheme`` value into its Chromium enum name.

    Parameters
    ----------
    value : int
        The stored value.

    Returns
    -------
    str
        The enum member name, or the raw value as a string if unrecognised.
    """
    return _LOGIN_SCHEMES.get(value, str(value))


def decode_insecurity_type(value: int) -> str:
    """
    Decode an ``insecure_credentials.insecurity_type`` value into its Chromium enum name.

    Parameters
    ----------
    value : int
        The stored value.

    Returns
    -------
    str
        The enum member name, or the raw value as a string if unrecognised.
    """
    return _INSECURITY_TYPES.get(value, str(value))


def decode_cookie_samesite(value: int) -> str:
    """
    Decode a ``cookies.samesite`` value into its Chromium enum name.

    Parameters
    ----------
    value : int
        The stored value.

    Returns
    -------
    str
        The enum member name, or the raw value as a string if unrecognised.
    """
    return _COOKIE_SAMESITE.get(value, str(value))


def decode_cookie_priority(value: int) -> str:
    """
    Decode a ``cookies.priority`` value into its Chromium enum name.

    Parameters
    ----------
    value : int
        The stored value.

    Returns
    -------
    str
        The enum member name, or the raw value as a string if unrecognised.
    """
    return _COOKIE_PRIORITY.get(value, str(value))


def decode_cookie_source_scheme(value: int) -> str:
    """
    Decode a ``cookies.source_scheme`` value into its Chromium enum name.

    Parameters
    ----------
    value : int
        The stored value.

    Returns
    -------
    str
        The enum member name, or the raw value as a string if unrecognised.
    """
    return _COOKIE_SOURCE_SCHEME.get(value, str(value))


def cookie_database_version(database_path: StrPath) -> int:
    """
    Read the schema version stored in a cookie database's ``meta`` table.

    Parameters
    ----------
    database_path : StrPath
        Path to a cookies database.

    Returns
    -------
    int
        The version, or ``0`` if it could not be read.
    """
    rows = query_database(database_path, "SELECT value FROM meta WHERE key = 'version'")
    return int(rows[0]['value']) if rows else 0


def iter_logins(database_path: StrPath, crypt: OSCrypt) -> Iterator[dict[str, Any]]:
    """
    Read every row of the ``logins`` table, decoding times, scheme, and decrypting the password.

    Parameters
    ----------
    database_path : StrPath
        Path to ``Login Data`` or ``Login Data For Account``.
    crypt : OSCrypt
        Decryptor used for ``password_value``.

    Yields
    ------
    dict[str, Any]
        One row per saved or blocklisted login. ``password`` holds the decrypted value or
        ``None``; blocklisted entries have no password to decrypt. ``insecurity_types`` lists the
        decoded issues recorded against the login in ``insecure_credentials``.
    """
    insecure_by_login: dict[int, list[str]] = {}
    for row in _optional_rows(database_path,
                              'SELECT parent_id, insecurity_type FROM insecure_credentials'):
        insecure_by_login.setdefault(row['parent_id'], []).append(
            decode_insecurity_type(row['insecurity_type']))
    notes_by_login: dict[int, dict[str, str | None]] = {}
    for row in _optional_rows(database_path, 'SELECT parent_id, key, value FROM password_notes'):
        notes_by_login.setdefault(row['parent_id'], {})[row['key']] = crypt.decrypt(row['value'])
    for row in query_database(database_path, 'SELECT * FROM logins ORDER BY id'):
        yield {
            'id': row['id'],
            'origin': row['origin_url'],
            'username': row['username_value'],
            'password': crypt.decrypt(row['password_value']),
            'signon_realm': row['signon_realm'],
            'scheme': decode_login_scheme(row['scheme']),
            'blocklisted': bool(row['blacklisted_by_user']),
            'times_used': row['times_used'],
            'date_created': webkit_timestamp_to_datetime(row['date_created']),
            'date_last_used': webkit_timestamp_to_datetime(row['date_last_used']),
            'date_password_modified': webkit_timestamp_to_datetime(row['date_password_modified']),
            'insecurity_types': insecure_by_login.get(row['id'], []),
            'notes': notes_by_login.get(row['id'], {}),
        }


def iter_login_stats(database_path: StrPath) -> Iterator[dict[str, Any]]:
    """
    Read the ``stats`` table, which records how often a save prompt was dismissed per site.

    Parameters
    ----------
    database_path : StrPath
        Path to ``Login Data`` or ``Login Data For Account``.

    Yields
    ------
    dict[str, Any]
        One row per origin and username pair.
    """
    for row in _optional_rows(database_path, 'SELECT * FROM stats ORDER BY origin_domain'):
        yield {**row, 'update_time': webkit_timestamp_to_datetime(row['update_time'])}


def iter_cookies(database_path: StrPath, crypt: OSCrypt) -> Iterator[dict[str, Any]]:
    """
    Read every row of the ``cookies`` table, decoding enums and decrypting the value.

    A cookie database at schema version 24 or later stores the decrypted plaintext with a 32-byte
    SHA-256 prefix, which is dropped automatically.

    Parameters
    ----------
    database_path : StrPath
        Path to a cookies database.
    crypt : OSCrypt
        Decryptor used for ``encrypted_value``.

    Yields
    ------
    dict[str, Any]
        One row per cookie, with ``value`` holding the plaintext (from the unencrypted ``value``
        column, or decrypted from ``encrypted_value``) or ``None``.
    """
    hash_prefix = cookie_database_version(database_path) >= _HASH_PREFIX_VERSION
    for row in query_database(database_path, 'SELECT * FROM cookies ORDER BY creation_utc'):
        yield {
            'host': row['host_key'],
            'name': row['name'],
            'value': row['value'] or crypt.decrypt(row['encrypted_value'], hash_prefix=hash_prefix),
            'path': row['path'],
            'is_secure': bool(row['is_secure']),
            'is_httponly': bool(row['is_httponly']),
            'samesite': decode_cookie_samesite(row['samesite']),
            'priority': decode_cookie_priority(row['priority']),
            'source_scheme': decode_cookie_source_scheme(row['source_scheme']),
            'source_port': row['source_port'],
            'has_expires': bool(row['has_expires']),
            'is_persistent': bool(row['is_persistent']),
            'creation': webkit_timestamp_to_datetime(row['creation_utc']),
            'last_access': webkit_timestamp_to_datetime(row['last_access_utc']),
            'expires': webkit_timestamp_to_datetime(row['expires_utc']),
        }


def iter_payment_table(database_path: StrPath, table: str,
                       crypt: OSCrypt) -> Iterator[dict[str, Any]]:
    """
    Read every row of one table in :py:data:`PAYMENT_TABLES`.

    Any ``*_encrypted`` column is decrypted and renamed without its suffix, and WebKit timestamp
    columns are converted to :py:class:`~datetime.datetime`.

    Parameters
    ----------
    database_path : StrPath
        Path to ``Web Data`` or ``Account Web Data``.
    table : str
        A table name from :py:data:`PAYMENT_TABLES`.
    crypt : OSCrypt
        Decryptor used for the table's encrypted column, if it has one.

    Yields
    ------
    dict[str, Any]
        One row per record.
    """
    encrypted_column = _PAYMENT_ENCRYPTED_COLUMNS.get(table)
    for row in query_database(database_path,
                              f'SELECT * FROM {table}'):  # ruff: ignore[hardcoded-sql-expression]
        decoded: dict[str, Any] = {}
        for key, value in row.items():
            if key == encrypted_column:
                decoded[PAYMENT_SECRET_FIELDS[table]] = crypt.decrypt(value)
            elif key in _PAYMENT_DATE_COLUMNS:
                decoded[key] = chrome_timestamp_to_datetime(value)
            else:
                decoded[key] = value
        yield decoded


def iter_autofill(database_path: StrPath) -> Iterator[dict[str, Any]]:
    """
    Read every row of the ``autofill`` table.

    Parameters
    ----------
    database_path : StrPath
        Path to ``Web Data``.

    Yields
    ------
    dict[str, Any]
        One row per remembered form field value.
    """
    for row in _optional_rows(database_path, 'SELECT * FROM autofill ORDER BY name'):
        yield {
            **row, 'date_created': unix_timestamp_to_datetime(row['date_created']),
            'date_last_used': unix_timestamp_to_datetime(row['date_last_used'])
        }


def iter_autocomplete(database_path: StrPath) -> Iterator[dict[str, Any]]:
    """
    Read every row of the ``autocomplete`` table.

    Parameters
    ----------
    database_path : StrPath
        Path to ``Web Data``.

    Yields
    ------
    dict[str, Any]
        One row per remembered form field value.
    """
    for row in _optional_rows(database_path, 'SELECT * FROM autocomplete ORDER BY name'):
        yield {
            **row, 'date_created': unix_timestamp_to_datetime(row['date_created']),
            'date_last_used': unix_timestamp_to_datetime(row['date_last_used'])
        }


def iter_addresses(database_path: StrPath) -> Iterator[dict[str, Any]]:
    """
    Read every row of the ``addresses`` table, joined with its ``address_type_tokens``.

    Parameters
    ----------
    database_path : StrPath
        Path to ``Web Data``.

    Yields
    ------
    dict[str, Any]
        Address metadata with ``tokens`` mapping each stored field type to its value.
    """
    tokens_by_guid: dict[str, dict[int, str]] = {}
    for row in _optional_rows(database_path, 'SELECT guid, type, value FROM address_type_tokens'):
        tokens_by_guid.setdefault(row['guid'], {})[row['type']] = row['value']
    for row in _optional_rows(database_path, 'SELECT * FROM addresses ORDER BY guid'):
        yield {
            'guid': row['guid'],
            'label': row['label'],
            'record_type': row['record_type'],
            'language_code': row['language_code'],
            'use_count': row['use_count'],
            'use_date': unix_timestamp_to_datetime(row['use_date']),
            'date_modified': unix_timestamp_to_datetime(row['date_modified']),
            'tokens': tokens_by_guid.get(row['guid'], {}),
        }


def iter_ai_entities(database_path: StrPath, crypt: OSCrypt) -> Iterator[dict[str, Any]]:
    """
    Read the Autofill AI entities, decrypting each of their attribute values.

    Parameters
    ----------
    database_path : StrPath
        Path to ``Web Data``.
    crypt : OSCrypt
        Decryptor used for ``autofill_ai_attributes.value_encrypted``.

    Yields
    ------
    dict[str, Any]
        One row per entity, with ``attributes`` mapping each attribute name to its decrypted value
        and ``use_count``, ``use_date``, and ``date_modified`` taken from the metadata table.
    """
    attributes_by_guid: dict[str, dict[str, str | None]] = {}
    for row in _optional_rows(
            database_path, 'SELECT entity_guid, attribute_type, value_encrypted'
            ' FROM autofill_ai_attributes'):
        attributes_by_guid.setdefault(
            row['entity_guid'], {})[row['attribute_type']] = crypt.decrypt(row['value_encrypted'])
    metadata_by_guid = {
        row['entity_guid']: row
        for row in _optional_rows(database_path, 'SELECT * FROM autofill_ai_entities_metadata')
    }
    for row in _optional_rows(database_path, 'SELECT * FROM autofill_ai_entities ORDER BY guid'):
        metadata = metadata_by_guid.get(row['guid'], {})
        yield {
            **row, 'attributes': attributes_by_guid.get(row['guid'], {}),
            'use_count': metadata.get('use_count'),
            'use_date': unix_timestamp_to_datetime(metadata.get('use_date')),
            'date_modified': unix_timestamp_to_datetime(metadata.get('date_modified'))
        }


def iter_sign_in_tokens(database_path: StrPath, crypt: OSCrypt) -> Iterator[dict[str, Any]]:
    """
    Read the ``token_service`` table, decrypting each stored sign-in token.

    Parameters
    ----------
    database_path : StrPath
        Path to ``Web Data``.
    crypt : OSCrypt
        Decryptor used for ``encrypted_token``.

    Yields
    ------
    dict[str, Any]
        One row per service, with ``token`` holding the decrypted value or ``None``.
    """
    for row in _optional_rows(database_path, 'SELECT * FROM token_service ORDER BY service'):
        yield {
            'service': row['service'],
            'token': crypt.decrypt(row['encrypted_token']),
            'is_bound': bool(row['binding_key']),
            'mtls_token_binding': row['mtls_token_binding']
        }


def iter_plus_addresses(database_path: StrPath) -> Iterator[dict[str, Any]]:
    """
    Read every row of the ``plus_addresses`` table.

    Parameters
    ----------
    database_path : StrPath
        Path to ``Web Data``.

    Yields
    ------
    dict[str, Any]
        One row per plus address.
    """
    yield from _optional_rows(database_path, 'SELECT * FROM plus_addresses ORDER BY facet')
