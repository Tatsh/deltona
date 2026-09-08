"""Read a profile's bookmarks, downloads, history, shortcuts, top sites, and spell-check data."""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any
import json
import os

from .core import open_database, query_database, webkit_timestamp_to_datetime

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from deltona.typing import StrPath

__all__ = ('DOWNLOAD_DANGER_TYPES', 'DOWNLOAD_INTERRUPT_REASONS', 'DOWNLOAD_STATES',
           'find_bookmark_folder', 'flatten_bookmarks', 'read_bookmarks', 'read_custom_dictionary',
           'read_downloads', 'read_history', 'read_history_urls', 'read_search_terms',
           'read_shortcuts', 'read_top_sites')

DOWNLOAD_STATES: dict[int, str] = {
    -1: 'INVALID',
    0: 'IN_PROGRESS',
    1: 'COMPLETE',
    2: 'CANCELLED',
    3: 'BUG_140687',
    4: 'INTERRUPTED'
}
"""
Names of ``downloads.state`` values in a profile's ``History`` database.

See Also
--------
`download_constants.h <https://source.chromium.org/chromium/chromium/src/+/main:components/history/core/browser/download_constants.h>`_

:meta hide-value:
"""
DOWNLOAD_DANGER_TYPES: dict[int, str] = {
    -1: 'INVALID',
    0: 'NOT_DANGEROUS',
    1: 'DANGEROUS_FILE',
    2: 'DANGEROUS_URL',
    3: 'DANGEROUS_CONTENT',
    4: 'MAYBE_DANGEROUS_CONTENT',
    5: 'UNCOMMON_CONTENT',
    6: 'USER_VALIDATED',
    7: 'DANGEROUS_HOST',
    8: 'POTENTIALLY_UNWANTED',
    9: 'ALLOWLISTED_BY_POLICY',
    10: 'ASYNC_SCANNING',
    11: 'BLOCKED_PASSWORD_PROTECTED',
    12: 'BLOCKED_TOO_LARGE',
    13: 'SENSITIVE_CONTENT_WARNING',
    14: 'SENSITIVE_CONTENT_BLOCK',
    15: 'DEEP_SCANNED_SAFE',
    16: 'DEEP_SCANNED_OPENED_DANGEROUS',
    17: 'PROMPT_FOR_SCANNING',
    18: 'BLOCKED_UNSUPPORTED_FILETYPE',
    19: 'DANGEROUS_ACCOUNT_COMPROMISE',
    20: 'DEEP_SCANNED_FAILED',
    21: 'PROMPT_FOR_LOCAL_PASSWORD_SCANNING',
    22: 'ASYNC_LOCAL_PASSWORD_SCANNING',
    23: 'BLOCKED_SCAN_FAILED',
    24: 'FORCED_SAVE_TO_GDRIVE',
    25: 'FORCED_SAVE_TO_ONEDRIVE'
}
"""
Names of ``downloads.danger_type`` values in a profile's ``History`` database.

See Also
--------
`download_constants.h <https://source.chromium.org/chromium/chromium/src/+/main:components/history/core/browser/download_constants.h>`_

:meta hide-value:
"""
DOWNLOAD_INTERRUPT_REASONS: dict[int, str] = {
    0: 'NONE',
    1: 'FILE_FAILED',
    2: 'FILE_ACCESS_DENIED',
    3: 'FILE_NO_SPACE',
    5: 'FILE_NAME_TOO_LONG',
    6: 'FILE_TOO_LARGE',
    7: 'FILE_VIRUS_INFECTED',
    10: 'FILE_TRANSIENT_ERROR',
    11: 'FILE_BLOCKED',
    12: 'FILE_SECURITY_CHECK_FAILED',
    13: 'FILE_TOO_SHORT',
    14: 'FILE_HASH_MISMATCH',
    15: 'FILE_SAME_AS_SOURCE',
    20: 'NETWORK_FAILED',
    21: 'NETWORK_TIMEOUT',
    22: 'NETWORK_DISCONNECTED',
    23: 'NETWORK_SERVER_DOWN',
    24: 'NETWORK_INVALID_REQUEST',
    30: 'SERVER_FAILED',
    31: 'SERVER_NO_RANGE',
    33: 'SERVER_BAD_CONTENT',
    34: 'SERVER_UNAUTHORIZED',
    35: 'SERVER_CERT_PROBLEM',
    36: 'SERVER_FORBIDDEN',
    37: 'SERVER_UNREACHABLE',
    38: 'SERVER_CONTENT_LENGTH_MISMATCH',
    39: 'SERVER_CROSS_ORIGIN_REDIRECT',
    40: 'USER_CANCELED',
    41: 'USER_SHUTDOWN',
    50: 'CRASH',
    51: 'LOCAL_DOWNLOAD_BLOCKED'
}
"""
Names of ``downloads.interrupt_reason`` values in a profile's ``History`` database.

See Also
--------
`download_interrupt_reason_values.h <https://source.chromium.org/chromium/chromium/src/+/main:components/download/public/common/download_interrupt_reason_values.h>`_

:meta hide-value:
"""
_TRANSITION_CORE_MASK = 0xFF
_TRANSITION_CORE_TYPES: dict[int, str] = {
    0: 'LINK',
    1: 'TYPED',
    2: 'AUTO_BOOKMARK',
    3: 'AUTO_SUBFRAME',
    4: 'MANUAL_SUBFRAME',
    5: 'GENERATED',
    6: 'AUTO_TOPLEVEL',
    7: 'FORM_SUBMIT',
    8: 'RELOAD',
    9: 'KEYWORD',
    10: 'KEYWORD_GENERATED'
}
_TRANSITION_QUALIFIERS: dict[int, str] = {
    0x00800000: 'BLOCKED',
    0x01000000: 'FORWARD_BACK',
    0x02000000: 'FROM_ADDRESS_BAR',
    0x04000000: 'HOME_PAGE',
    0x08000000: 'FROM_API',
    0x10000000: 'CHAIN_START',
    0x20000000: 'CHAIN_END',
    0x40000000: 'CLIENT_REDIRECT',
    0x80000000: 'SERVER_REDIRECT'
}


def _decode_transition(value: int) -> tuple[str, list[str]]:
    unsigned = value & 0xFFFFFFFF
    core = _TRANSITION_CORE_TYPES.get(unsigned & _TRANSITION_CORE_MASK, 'UNKNOWN')
    qualifiers = [name for bit, name in _TRANSITION_QUALIFIERS.items() if unsigned & bit]
    return core, qualifiers


def _normalise_bookmark_node(node: Mapping[str, Any]) -> dict[str, Any]:
    normalised = {
        'date_added': webkit_timestamp_to_datetime(node.get('date_added')),
        'date_last_used': webkit_timestamp_to_datetime(node.get('date_last_used')),
        'date_modified': webkit_timestamp_to_datetime(node.get('date_modified')),
        'guid': node.get('guid'),
        'id': node.get('id'),
        'name': node.get('name'),
        'type': node.get('type'),
        'url': node.get('url')
    }
    if 'children' in node:
        normalised['children'] = [_normalise_bookmark_node(child) for child in node['children']]
    return normalised


def _walk_bookmarks(node: Mapping[str, Any], folder_path: tuple[str,
                                                                ...]) -> Iterator[dict[str, Any]]:
    if node.get('type') == 'folder':
        child_path = (*folder_path, node['name'])
        for child in node.get('children', ()):
            yield from _walk_bookmarks(child, child_path)
    else:
        yield {
            'folder': ' / '.join(folder_path),
            'name': node.get('name'),
            'url': node.get('url'),
            'date_added': node.get('date_added'),
            'date_last_used': node.get('date_last_used')
        }


def read_bookmarks(path: StrPath) -> dict[str, Any]:
    """
    Read a profile's bookmarks.

    ``Bookmarks.bak`` is read when ``Bookmarks`` is missing, since Chrome keeps only the backup
    for a short time after startup.

    Parameters
    ----------
    path : StrPath
        Path to the profile directory.

    Returns
    -------
    dict[str, Any]
        The ``bookmark_bar``, ``other``, and ``synced`` roots, each a node with ``name``, ``type``,
        ``url``, the parsed dates, and, for folders, a ``children`` list of the same shape.

    Raises
    ------
    FileNotFoundError
        If neither ``Bookmarks`` nor ``Bookmarks.bak`` exists.
    """
    profile = Path(path)
    candidate = profile / 'Bookmarks'
    if not candidate.is_file():
        candidate = profile / 'Bookmarks.bak'
    if not candidate.is_file():
        raise FileNotFoundError(os.strerror(2), str(profile / 'Bookmarks'))
    data = json.loads(candidate.read_text(encoding='utf-8'))
    return {name: _normalise_bookmark_node(node) for name, node in data.get('roots', {}).items()}


def find_bookmark_folder(roots: Mapping[str, Any], folder: str) -> dict[str, Any] | None:
    """
    Resolve a slash-separated folder path within a bookmark tree.

    The first segment may be a root key such as ``'other'`` or a root's display name such as
    ``'Bookmarks bar'``. Matching is case-insensitive and surrounding whitespace is ignored, so the
    ``folder`` column of :py:func:`flatten_bookmarks` can be pasted back in verbatim.

    Parameters
    ----------
    roots : Mapping[str, Any]
        The value returned by :py:func:`read_bookmarks`.
    folder : str
        The path, such as ``'Bookmarks bar/Development'``.

    Returns
    -------
    dict[str, Any] | None
        The folder node, or ``None`` if any segment does not match.
    """
    segments = [segment.strip() for segment in folder.split('/') if segment.strip()]
    if not segments:
        return None
    wanted = segments[0].casefold()
    node = next(
        (candidate for key, candidate in roots.items()
         if key.casefold() == wanted or str(candidate.get('name', '')).casefold() == wanted), None)
    for segment in segments[1:]:
        if node is None:
            return None
        node = next((child for child in node.get('children', ()) if child.get('type') == 'folder'
                     and str(child.get('name', '')).casefold() == segment.casefold()), None)
    return node


def flatten_bookmarks(roots: Mapping[str, Any]) -> list[dict[str, Any]]:
    """
    Flatten a bookmark tree returned by :py:func:`read_bookmarks` into one row per URL.

    Parameters
    ----------
    roots : Mapping[str, Any]
        The value returned by :py:func:`read_bookmarks`.

    Returns
    -------
    list[dict[str, Any]]
        One entry per bookmarked URL, with its folder path, name, URL, and dates.
    """
    return [entry for root in roots.values() for entry in _walk_bookmarks(root, ())]


def read_downloads(path: StrPath,
                   *,
                   limit: int = 0,
                   state: int | None = None) -> list[dict[str, Any]]:
    """
    Read every download recorded in a profile's ``History`` database.

    Parameters
    ----------
    path : StrPath
        Path to the profile directory.
    limit : int
        Maximum rows to return, most recent first. ``0`` means no limit.
    state : int | None
        Restrict to downloads whose ``state`` column equals this value.

    Returns
    -------
    list[dict[str, Any]]
        Every column of the ``downloads`` table, with timestamps converted; ``state_name``,
        ``danger_type_name``, and ``interrupt_reason_name`` added from :py:data:`DOWNLOAD_STATES`,
        :py:data:`DOWNLOAD_DANGER_TYPES`, and :py:data:`DOWNLOAD_INTERRUPT_REASONS`; and the
        download's URL chain and byte-range slices attached as ``url_chain`` and ``slices``.
    """
    sql = 'SELECT * FROM downloads'
    parameters: list[Any] = []
    if state is not None:
        sql += ' WHERE state = ?'
        parameters.append(state)
    sql += ' ORDER BY start_time DESC'
    if limit > 0:
        sql += ' LIMIT ?'
        parameters.append(limit)
    with open_database(Path(path) / 'History') as connection:
        downloads = [dict(row) for row in connection.execute(sql, parameters)]
        url_chains: dict[int, list[str]] = {}
        for chain_row in connection.execute(
                'SELECT id, url FROM downloads_url_chains ORDER BY id, chain_index'):
            url_chains.setdefault(chain_row['id'], []).append(chain_row['url'])
        slices: dict[int, list[dict[str, Any]]] = {}
        for slice_row in connection.execute('SELECT download_id, offset, received_bytes, '
                                            'finished FROM downloads_slices '
                                            'ORDER BY download_id, offset'):
            slices.setdefault(slice_row['download_id'], []).append({
                'offset': slice_row['offset'],
                'received_bytes': slice_row['received_bytes'],
                'finished': bool(slice_row['finished'])
            })
    return [{
        **download, 'start_time':
            webkit_timestamp_to_datetime(download['start_time']),
        'end_time':
            webkit_timestamp_to_datetime(download['end_time']),
        'last_access_time':
            webkit_timestamp_to_datetime(download['last_access_time']),
        'state_name':
            DOWNLOAD_STATES.get(download['state'], 'UNKNOWN'),
        'danger_type_name':
            DOWNLOAD_DANGER_TYPES.get(download['danger_type'], 'UNKNOWN'),
        'interrupt_reason_name':
            DOWNLOAD_INTERRUPT_REASONS.get(download['interrupt_reason'], 'UNKNOWN'),
        'url_chain':
            url_chains.get(download['id'], []),
        'slices':
            slices.get(download['id'], [])
    } for download in downloads]


def read_history(path: StrPath,
                 *,
                 limit: int = 100,
                 search: str | None = None) -> list[dict[str, Any]]:
    """
    Read a profile's browsing history as visits joined to their URLs.

    Parameters
    ----------
    path : StrPath
        Path to the profile directory.
    limit : int
        Maximum rows to return, most recent first. ``0`` means no limit.
    search : str | None
        Restrict to rows whose URL or title contains this substring.

    Returns
    -------
    list[dict[str, Any]]
        Rows ordered by visit time descending, with ``visit_time`` converted and
        ``transition_core`` and ``transition_qualifiers`` decoded from the ``transition`` column.
    """
    sql = ('SELECT u.id AS url_id, u.url, u.title, u.visit_count, u.typed_count, u.hidden, '
           'v.id AS visit_id, v.visit_time, v.from_visit, v.transition, v.segment_id, '
           'v.visit_duration, v.opener_visit, v.external_referrer_url, v.app_id '
           'FROM visits v JOIN urls u ON v.url = u.id')
    parameters: list[Any] = []
    if search:
        sql += ' WHERE u.url LIKE ? OR u.title LIKE ?'
        parameters.extend((f'%{search}%', f'%{search}%'))
    sql += ' ORDER BY v.visit_time DESC'
    if limit > 0:
        sql += ' LIMIT ?'
        parameters.append(limit)
    result = []
    for row in query_database(Path(path) / 'History', sql, parameters):
        core, qualifiers = _decode_transition(row['transition'])
        result.append({
            **row, 'visit_time': webkit_timestamp_to_datetime(row['visit_time']),
            'transition_core': core,
            'transition_qualifiers': qualifiers
        })
    return result


def read_history_urls(path: StrPath,
                      *,
                      limit: int = 100,
                      search: str | None = None) -> list[dict[str, Any]]:
    """
    Read a profile's ``urls`` table without joining it to ``visits``.

    Parameters
    ----------
    path : StrPath
        Path to the profile directory.
    limit : int
        Maximum rows to return, most recently visited first. ``0`` means no limit.
    search : str | None
        Restrict to rows whose URL or title contains this substring.

    Returns
    -------
    list[dict[str, Any]]
        Every column of ``urls``, with ``last_visit_time`` converted.
    """
    sql = 'SELECT * FROM urls'
    parameters: list[Any] = []
    if search:
        sql += ' WHERE url LIKE ? OR title LIKE ?'
        parameters.extend((f'%{search}%', f'%{search}%'))
    sql += ' ORDER BY last_visit_time DESC'
    if limit > 0:
        sql += ' LIMIT ?'
        parameters.append(limit)
    return [{
        **row, 'last_visit_time': webkit_timestamp_to_datetime(row['last_visit_time'])
    } for row in query_database(Path(path) / 'History', sql, parameters)]


def read_search_terms(path: StrPath,
                      *,
                      limit: int = 100,
                      search: str | None = None) -> list[dict[str, Any]]:
    """
    Read a profile's ``keyword_search_terms`` table joined to its URL.

    Parameters
    ----------
    path : StrPath
        Path to the profile directory.
    limit : int
        Maximum rows to return, most recently visited first. ``0`` means no limit.
    search : str | None
        Restrict to rows whose search term or URL contains this substring.

    Returns
    -------
    list[dict[str, Any]]
        Each search term with the URL it was performed on, with ``last_visit_time`` converted.
    """
    sql = ('SELECT k.keyword_id, k.term, k.normalized_term, u.url, u.title, u.visit_count, '
           'u.last_visit_time FROM keyword_search_terms k JOIN urls u ON k.url_id = u.id')
    parameters: list[Any] = []
    if search:
        sql += ' WHERE k.term LIKE ? OR u.url LIKE ?'
        parameters.extend((f'%{search}%', f'%{search}%'))
    sql += ' ORDER BY u.last_visit_time DESC'
    if limit > 0:
        sql += ' LIMIT ?'
        parameters.append(limit)
    return [{
        **row, 'last_visit_time': webkit_timestamp_to_datetime(row['last_visit_time'])
    } for row in query_database(Path(path) / 'History', sql, parameters)]


def read_shortcuts(path: StrPath) -> list[dict[str, Any]]:
    """
    Read a profile's omnibox shortcuts.

    Parameters
    ----------
    path : StrPath
        Path to the profile directory.

    Returns
    -------
    list[dict[str, Any]]
        Every column of ``omni_box_shortcuts``, ordered by ``text``, with ``last_access_time``
        converted and ``transition_core``/``transition_qualifiers`` decoded from ``transition``.
    """
    result = []
    for row in query_database(
            Path(path) / 'Shortcuts', 'SELECT * FROM omni_box_shortcuts ORDER BY text'):
        core, qualifiers = _decode_transition(row['transition'])
        result.append({
            **row, 'last_access_time': webkit_timestamp_to_datetime(row['last_access_time']),
            'transition_core': core,
            'transition_qualifiers': qualifiers
        })
    return result


def read_top_sites(path: StrPath) -> list[dict[str, Any]]:
    """
    Read a profile's top sites.

    Parameters
    ----------
    path : StrPath
        Path to the profile directory.

    Returns
    -------
    list[dict[str, Any]]
        Every column of ``top_sites``, ordered by ``url_rank``.
    """
    return query_database(Path(path) / 'Top Sites', 'SELECT * FROM top_sites ORDER BY url_rank')


def read_custom_dictionary(path: StrPath) -> dict[str, Any]:
    """
    Read a profile's custom spell-check dictionary and preferences.

    Parameters
    ----------
    path : StrPath
        Path to the profile directory.

    Returns
    -------
    dict[str, Any]
        ``words`` (the dictionary entries), ``checksum`` (the trailing ``checksum_v1`` value), and
        ``preferences`` (the ``spellcheck`` key of ``Preferences``, or ``None`` if absent).

    Raises
    ------
    FileNotFoundError
        If the profile has no ``Custom Dictionary.txt``.
    """
    profile = Path(path)
    dictionary_path = profile / 'Custom Dictionary.txt'
    if not dictionary_path.is_file():
        raise FileNotFoundError(os.strerror(2), str(dictionary_path))
    words = []
    checksum = None
    for line in dictionary_path.read_text(encoding='utf-8').splitlines():
        if line.startswith('checksum_v1 = '):
            checksum = line.removeprefix('checksum_v1 = ')
        elif line:
            words.append(line)
    preferences: dict[str, Any] | None = None
    preferences_path = profile / 'Preferences'
    if preferences_path.is_file():
        with suppress(OSError, ValueError):
            preferences = json.loads(preferences_path.read_text(encoding='utf-8')).get('spellcheck')
    return {'words': words, 'checksum': checksum, 'preferences': preferences}
