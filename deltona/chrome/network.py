"""Network-related storage: the HTTP cache, DIPS, Reporting/NEL, network state, and sessions."""

from __future__ import annotations

from collections import Counter
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypeAlias
from urllib.parse import urlparse
import json
import os
import re
import struct

from deltona.chrome.core import (
    query_database,
    unix_timestamp_to_datetime,
    webkit_timestamp_to_datetime,
)

if TYPE_CHECKING:
    from deltona.typing import StrPath

__all__ = (
    'CACHE_FINAL_MAGIC',
    'CACHE_INITIAL_MAGIC',
    'SNSS_MAGIC',
    'CacheKind',
    'SortField',
    'cache_entries',
    'dips_bounces',
    'dips_popups',
    'nel_policies',
    'network_persistent_state',
    'reporting_endpoint_groups',
    'reporting_endpoints',
    'session_files',
    'transport_security',
)

CacheKind: TypeAlias = Literal['code', 'http', 'image']
"""Which on-disk Simple Cache backend to read."""
SortField: TypeAlias = Literal['key', 'modified', 'size']
"""Field to sort :py:func:`cache_entries` results by."""

CACHE_INITIAL_MAGIC = 0xfcfb6d1ba7725c30
"""Magic number at the start of a Simple Cache entry file (``kSimpleInitialMagicNumber``).

:meta hide-value:
"""
CACHE_FINAL_MAGIC = 0xf4fa6f45970d41d8
"""
Magic number of a Simple Cache entry's trailing end-of-file record (``kSimpleFinalMagicNumber``).

Not used by this module: locating this record requires walking the entry's stream layout forward
from the header, because stream 1's data precedes its own end-of-file record and there is no way
to find that record's position by reading backward from the end of the file alone.

:meta hide-value:
"""
SNSS_MAGIC = b'SNSS'
"""Magic bytes at the start of a session, tab, or app restore file.

:meta hide-value:
"""
_CACHE_HEADER = struct.Struct('<QIIII')
_CACHE_ENTRY_RE = re.compile(r'^([0-9a-f]{16})_([0-9s])$')
_CACHE_URL_PREFIX_RE = re.compile(r'^\d+/\d+/(.+)$')
_SNSS_HEADER = struct.Struct('<4sI')
_SNSS_RECORD_LENGTH = struct.Struct('<H')
_SNSS_FILE_RE = re.compile(r'^(Apps|Session|Tabs)_(\d+)$')
_SNSS_URL_RE = re.compile(rb'https?://[!-~]+')


def _cache_dirs(cache_path: Path, kind: CacheKind) -> tuple[Path, ...]:
    if kind == 'http':
        return (cache_path / 'Cache' / 'Cache_Data',)
    if kind == 'image':
        return (cache_path / 'image_cache',)
    base = cache_path / 'Code Cache'
    return tuple(base / name for name in ('js', 'wasm', 'pc') if (base / name).is_dir())


def _scan_cache_dir(directory: Path) -> dict[str, dict[str, os.DirEntry[str]]]:
    grouped: dict[str, dict[str, os.DirEntry[str]]] = {}
    with suppress(OSError):
        for entry in os.scandir(directory):
            if match := _CACHE_ENTRY_RE.match(entry.name):
                grouped.setdefault(match.group(1), {})[match.group(2)] = entry
    return grouped


def _extract_cache_url(key: str) -> str | None:
    candidate = key.rsplit(' ', 1)[-1]
    if urlparse(candidate).netloc:
        return candidate
    if match := _CACHE_URL_PREFIX_RE.match(key):
        candidate = match.group(1)
        if urlparse(candidate).netloc:
            return candidate
    return None


def _read_cache_header(path: Path) -> tuple[bytes, int] | None:
    try:
        with path.open('rb') as f:
            head = f.read(_CACHE_HEADER.size)
            if len(head) < _CACHE_HEADER.size:
                return None
            magic, _version, key_length, _key_hash, _padding = _CACHE_HEADER.unpack(head)
            return (f.read(key_length), key_length) if magic == CACHE_INITIAL_MAGIC else None
    except OSError:
        return None


def _read_cache_key(path: Path) -> str | None:
    if not (header := _read_cache_header(path)):
        return None
    key_bytes, key_length = header
    if len(key_bytes) < key_length:
        return None
    return key_bytes.decode('utf-8', errors='replace')


def cache_entries(cache_path: StrPath,
                  *,
                  kind: CacheKind = 'http',
                  search: str | None = None,
                  sort: SortField = 'modified') -> list[dict[str, Any]]:
    """
    List entries of a Simple Cache backend.

    Only each entry's header and key are read; entry bodies are never opened.

    Parameters
    ----------
    cache_path : StrPath
        A profile's cache directory, such as :py:attr:`~deltona.chrome.ChromeProfile.cache_path`.
    kind : CacheKind
        ``'http'`` reads ``Cache/Cache_Data``, ``'code'`` reads whichever of ``Code Cache/js``,
        ``Code Cache/wasm``, and ``Code Cache/pc`` exist, and ``'image'`` reads ``image_cache``.
    search : str | None
        Case-sensitive substring to match against the raw cache key.
    sort : SortField
        Sort order. ``'size'`` and ``'modified'`` sort descending, ``'key'`` sorts ascending.

    Returns
    -------
    list[dict[str, Any]]
        One entry per cache record with the fields ``key``, ``url``, ``key/url``, ``size``,
        ``modified``, and ``file``. ``size`` is the total on-disk size of every stream file
        belonging to the entry rather than the decoded payload size (see
        :py:data:`CACHE_FINAL_MAGIC`). ``url`` is a best-effort extraction from the key: the last
        space-separated token if it parses as a URL, otherwise the remainder of the key after a
        leading ``<digit>/<digit>/`` prefix. It is ``None`` if neither matches. ``key/url`` is
        ``url`` when available, otherwise the raw key.
    """
    root = Path(cache_path)
    grouped: dict[str, dict[str, os.DirEntry[str]]] = {}
    for directory in _cache_dirs(root, kind):
        grouped.update(_scan_cache_dir(directory))
    rows: list[dict[str, Any]] = []
    for files in grouped.values():
        if (zero := files.get('0')) is None:
            continue
        if (key := _read_cache_key(Path(zero.path))) is None:
            continue
        if search and search not in key:
            continue
        with suppress(OSError):
            url = _extract_cache_url(key)
            rows.append({
                'key': key,
                'url': url,
                'key/url': url or key,
                'size': sum(f.stat().st_size for f in files.values()),
                'modified': datetime.fromtimestamp(zero.stat().st_mtime, tz=timezone.utc),
                'file': Path(zero.path)
            })
    rows.sort(key=lambda row: row['key'] if sort == 'key' else row[sort], reverse=sort != 'key')
    return rows


def dips_bounces(path: StrPath, *, search: str | None = None) -> list[dict[str, Any]]:
    """
    List the ``bounces`` table of a profile's ``DIPS`` database.

    Parameters
    ----------
    path : StrPath
        Path to the ``DIPS`` database.
    search : str | None
        Case-insensitive substring to match against ``site``.

    Returns
    -------
    list[dict[str, Any]]
        Rows sorted by site, with every ``*_time`` column converted to a datetime.
    """
    sql = 'SELECT * FROM bounces'
    parameters: tuple[Any, ...] = ()
    if search:
        sql += ' WHERE LOWER(site) LIKE LOWER(?)'
        parameters = (f'%{search}%',)
    rows = query_database(path, f'{sql} ORDER BY site', parameters)
    for row in rows:
        for column in ('first_bounce_time', 'first_user_activation_time',
                       'first_web_authn_assertion_time', 'last_bounce_time',
                       'last_user_activation_time', 'last_web_authn_assertion_time'):
            row[column] = webkit_timestamp_to_datetime(row[column])
    return rows


def dips_popups(path: StrPath, *, search: str | None = None) -> list[dict[str, Any]]:
    """
    List the ``popups`` table of a profile's ``DIPS`` database.

    Parameters
    ----------
    path : StrPath
        Path to the ``DIPS`` database.
    search : str | None
        Case-insensitive substring to match against ``opener_site`` or ``popup_site``.

    Returns
    -------
    list[dict[str, Any]]
        Rows sorted by opener site, with ``last_popup_time`` converted to a datetime and the two
        interaction columns converted to booleans.
    """
    sql = 'SELECT * FROM popups'
    parameters: tuple[Any, ...] = ()
    if search:
        sql += ' WHERE LOWER(opener_site) LIKE LOWER(?) OR LOWER(popup_site) LIKE LOWER(?)'
        parameters = (f'%{search}%', f'%{search}%')
    rows = query_database(path, f'{sql} ORDER BY opener_site', parameters)
    for row in rows:
        row['last_popup_time'] = webkit_timestamp_to_datetime(row['last_popup_time'])
        for column in ('is_authentication_interaction', 'is_current_interaction'):
            row[column] = None if row[column] is None else bool(row[column])
    return rows


def nel_policies(path: StrPath, *, search: str | None = None) -> list[dict[str, Any]]:
    """
    List the ``nel_policies`` table of a profile's ``Reporting and NEL`` database.

    Parameters
    ----------
    path : StrPath
        Path to the ``Reporting and NEL`` database.
    search : str | None
        Case-insensitive substring to match against ``origin_host``.

    Returns
    -------
    list[dict[str, Any]]
        Rows sorted by origin host, with both ``*_us_since_epoch`` columns converted to datetimes
        and ``is_include_subdomains`` converted to a boolean.
    """
    sql = 'SELECT * FROM nel_policies'
    parameters: tuple[Any, ...] = ()
    if search:
        sql += ' WHERE LOWER(origin_host) LIKE LOWER(?)'
        parameters = (f'%{search}%',)
    rows = query_database(path, f'{sql} ORDER BY origin_host', parameters)
    for row in rows:
        row['is_include_subdomains'] = bool(row['is_include_subdomains'])
        for column in ('expires_us_since_epoch', 'last_access_us_since_epoch'):
            row[column] = webkit_timestamp_to_datetime(row[column])
    return rows


def reporting_endpoints(path: StrPath, *, search: str | None = None) -> list[dict[str, Any]]:
    """
    List the ``reporting_endpoints`` table of a profile's ``Reporting and NEL`` database.

    Parameters
    ----------
    path : StrPath
        Path to the ``Reporting and NEL`` database.
    search : str | None
        Case-insensitive substring to match against ``origin_host``.

    Returns
    -------
    list[dict[str, Any]]
        Rows sorted by origin host.
    """
    sql = 'SELECT * FROM reporting_endpoints'
    parameters: tuple[Any, ...] = ()
    if search:
        sql += ' WHERE LOWER(origin_host) LIKE LOWER(?)'
        parameters = (f'%{search}%',)
    return query_database(path, f'{sql} ORDER BY origin_host', parameters)


def reporting_endpoint_groups(path: StrPath, *, search: str | None = None) -> list[dict[str, Any]]:
    """
    List the ``reporting_endpoint_groups`` table of a profile's ``Reporting and NEL`` database.

    Parameters
    ----------
    path : StrPath
        Path to the ``Reporting and NEL`` database.
    search : str | None
        Case-insensitive substring to match against ``origin_host``.

    Returns
    -------
    list[dict[str, Any]]
        Rows sorted by origin host, with both ``*_us_since_epoch`` columns converted to datetimes
        and ``is_include_subdomains`` converted to a boolean.
    """
    sql = 'SELECT * FROM reporting_endpoint_groups'
    parameters: tuple[Any, ...] = ()
    if search:
        sql += ' WHERE LOWER(origin_host) LIKE LOWER(?)'
        parameters = (f'%{search}%',)
    rows = query_database(path, f'{sql} ORDER BY origin_host', parameters)
    for row in rows:
        row['is_include_subdomains'] = bool(row['is_include_subdomains'])
        for column in ('expires_us_since_epoch', 'last_access_us_since_epoch'):
            row[column] = webkit_timestamp_to_datetime(row[column])
    return rows


def _load_json(path: Path) -> Any:
    if not path.is_file():
        return None
    with suppress(OSError, ValueError):
        return json.loads(path.read_text(encoding='utf-8'))
    return None


def network_persistent_state(path: StrPath) -> dict[str, Any]:
    """
    Parse a profile's ``Network Persistent State`` file.

    Parameters
    ----------
    path : StrPath
        Path to the ``Network Persistent State`` file.

    Returns
    -------
    dict[str, Any]
        The keys ``servers``, ``broken_alternative_services``, ``quic_servers``,
        ``supports_quic``, and ``network_qualities``, each defaulting to an empty list, an empty
        list, an empty list, ``None``, and an empty dictionary respectively when absent or when the
        file is missing or unreadable.
    """
    data = _load_json(Path(path)) or {}
    properties = data.get('net', {}).get('http_server_properties', {})
    return {
        'servers': properties.get('servers', []),
        'broken_alternative_services': properties.get('broken_alternative_services', []),
        'quic_servers': properties.get('quic_servers', []),
        'supports_quic': properties.get('supports_quic'),
        'network_qualities': data.get('net', {}).get('network_qualities', {})
    }


def transport_security(path: StrPath) -> list[dict[str, Any]]:
    """
    Parse a profile's ``TransportSecurity`` file.

    Hosts are stored as base64-encoded SHA-256 hashes and cannot be reversed to the original
    hostname.

    Parameters
    ----------
    path : StrPath
        Path to the ``TransportSecurity`` file.

    Returns
    -------
    list[dict[str, Any]]
        One entry per HSTS record, with the fields ``host`` (the hash), ``mode``,
        ``include_subdomains``, ``observed``, and ``expiry``. Empty if the file is missing or
        unreadable.
    """
    data = _load_json(Path(path)) or {}
    return [{
        'host': entry.get('host'),
        'mode': entry.get('mode'),
        'include_subdomains': bool(entry.get('sts_include_subdomains')),
        'observed': unix_timestamp_to_datetime(entry.get('sts_observed')),
        'expiry': unix_timestamp_to_datetime(entry.get('expiry'))
    } for entry in data.get('sts', [])]


def _parse_snss_records(data: bytes) -> tuple[int, Counter[int], set[str]] | None:
    if len(data) < _SNSS_HEADER.size:
        return None
    magic, version = _SNSS_HEADER.unpack_from(data, 0)
    if magic != SNSS_MAGIC:
        return None
    record_ids: Counter[int] = Counter()
    urls: set[str] = set()
    pos = _SNSS_HEADER.size
    while pos + _SNSS_RECORD_LENGTH.size <= len(data):
        (length,) = _SNSS_RECORD_LENGTH.unpack_from(data, pos)
        start = pos + _SNSS_RECORD_LENGTH.size
        if length == 0 or start + length > len(data):
            break
        record = data[start:start + length]
        record_ids[record[0]] += 1
        urls.update(match.decode('ascii') for match in _SNSS_URL_RE.findall(record[1:]))
        pos = start + length
    return version, record_ids, urls


def session_files(sessions_path: StrPath) -> list[dict[str, Any]]:
    """
    List and summarise the SNSS session, tab, and app restore files of a profile.

    This performs only a partial decode: the SNSS record framing (length and command id) is parsed
    for every file, but individual command payloads are not decoded. URLs are recovered on a
    best-effort basis by scanning payload bytes for ``http://`` or ``https://`` runs, which misses
    URLs that are not stored as contiguous ASCII text.

    Parameters
    ----------
    sessions_path : StrPath
        Path to a profile's ``Sessions`` directory.

    Returns
    -------
    list[dict[str, Any]]
        One entry per file, sorted by name, with the fields ``name``, ``kind`` (``'Apps'``,
        ``'Session'``, or ``'Tabs'``), ``timestamp`` (decoded from the file name), ``size``,
        ``version`` (the SNSS format version), ``record_count``, ``record_ids`` (a mapping of
        command id to occurrence count), and ``urls`` (the distinct URLs found). Files that are not
        valid SNSS files are skipped.
    """
    root = Path(sessions_path)
    if not root.is_dir():
        return []
    rows = []
    for entry in sorted(root.iterdir()):
        if not (match := _SNSS_FILE_RE.match(entry.name)):
            continue
        try:
            data = entry.read_bytes()
        except OSError:
            continue
        if (parsed := _parse_snss_records(data)) is None:
            continue
        version, record_ids, urls = parsed
        rows.append({
            'name': entry.name,
            'kind': match.group(1),
            'timestamp': webkit_timestamp_to_datetime(match.group(2)),
            'size': len(data),
            'version': version,
            'record_count': sum(record_ids.values()),
            'record_ids': dict(record_ids),
            'urls': tuple(sorted(urls))
        })
    return rows
