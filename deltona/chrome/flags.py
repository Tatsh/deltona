"""
Read the state of ``chrome://flags`` entries.

Chrome stores only the flags a user changed, as ``browser.enabled_labs_experiments`` in
``Local State``. Neither flag titles nor their descriptions live anywhere in the profile: they are
compiled into the browser from ``chrome/browser/about_flags.cc`` and
``chrome/browser/flag_descriptions.h``.

Those two files are therefore fetched from the Chromium mirror at the tag matching the browser's
own ``Last Version``, parsed, and cached. Pinning to the installed version keeps titles,
descriptions, and source line numbers correct for the browser actually on the machine rather than
for whatever ``main`` happens to hold.

The same table is also compiled into the browser itself, where :py:mod:`deltona.chrome.flag_binary`
can read it without a network at all, and where it describes the entries this build compiled rather
than the union over every platform. :py:func:`flag_table_for` prefers that. Only owners and expiry
milestones are missing from a binary, because they live in ``flag-metadata.json``.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
import json
import logging
import lzma
import re

from deltona.typing import assert_not_none

from .flag_binary import FlagBinaryUnreadable, extract_flag_table, find_browser_binary

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, MutableMapping, Sequence

    from deltona.typing import StrPath

    from .typing import ChromeChannel

__all__ = (
    'CHROMIUM_RAW_URL',
    'SOURCE_URL_TEMPLATE',
    'FlagTableUnavailable',
    'flag_source_url',
    'flag_states',
    'flag_table',
    'flag_table_for',
    'installed_version',
    'parse_experiment',
)

log = logging.getLogger(__name__)

CHROMIUM_RAW_URL = 'https://raw.githubusercontent.com/chromium/chromium/{version}/{path}'
"""
Template for one file of the Chromium source at a release tag.

:meta hide-value:
"""
SOURCE_URL_TEMPLATE = ('https://source.chromium.org/chromium/chromium/src/+/refs/tags/{version}:'
                       'chrome/browser/about_flags.cc;l={line}')
"""
Template for a permalink to a flag's declaration at a release tag.

:meta hide-value:
"""
_ABOUT_FLAGS = 'chrome/browser/about_flags.cc'
_FLAG_DESCRIPTIONS = 'chrome/browser/flag_descriptions.h'
_FLAG_METADATA = 'chrome/browser/flag-metadata.json'
_NEVER_EXPIRE_LIST = 'chrome/browser/flag-never-expire-list.json'
_DESCRIPTION_RE = re.compile(
    r'^inline constexpr char\s+(k\w+)\[\]\s*=\s*((?:"(?:[^"\\]|\\.)*"\s*)+);', re.MULTILINE)
_ENTRY_RE = re.compile(
    r'\{\s*(?P<name>(?:"(?:[^"\\]|\\.)*"\s*)+|[A-Za-z_][\w:]*)\s*,'
    r'\s*flag_descriptions::(?P<title>k\w+)\s*,'
    r'\s*flag_descriptions::(?P<description>k\w+)\s*,'
    r'\s*(?P<os>[^,]+?),\s*(?P<type>\w+)\s*\(', re.DOTALL)
_STRING_LITERAL_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
_SYMBOL_RE = re.compile(r'constexpr char\s+(\w+)\[\]\s*=\s*((?:"(?:[^"\\]|\\.)*"\s*)+);')
_COMMENT_RE = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|//[^\n]*|/\*.*?\*/', re.DOTALL)
_ARRAY_RE = r'(?:FeatureVariation|Choice)\s+{name}\[\]\s*=\s*\{{'
_ENTRIES_MARKER = 'const FeatureEntry kFeatureEntries[] = {'
_CACHE_FORMAT = 2
_ENABLED = 'Enabled'
_GENERIC_OPTIONS = ('Default', _ENABLED, 'Disabled')
_GENERIC_OPTION_TYPES = frozenset({
    'ENABLE_DISABLE_VALUE_TYPE', 'ENABLE_DISABLE_VALUE_TYPE_AND_VALUE', 'FEATURE_VALUE_TYPE',
    'PLATFORM_FEATURE_NAME_TYPE'
})
_VARIATION_OPTION_TYPES = frozenset(
    {'FEATURE_WITH_PARAMS_VALUE_TYPE', 'PLATFORM_FEATURE_NAME_WITH_PARAMS_VALUE_TYPE'})
_GENERIC_LABELS = {
    'kGenericExperimentChoiceDefault': 'Default',
    'kGenericExperimentChoiceDisabled': 'Disabled',
    'kGenericExperimentChoiceEnabled': _ENABLED,
    'kGenericExperimentChoiceAutomatic': 'Automatic'
}


class FlagTableUnavailable(Exception):
    """Raised when flag descriptions can be neither read from the cache nor fetched."""


def installed_version(config_path: StrPath) -> str | None:
    """
    Read the browser version that last wrote to a user data directory.

    Parameters
    ----------
    config_path : StrPath
        Path to the user data directory.

    Returns
    -------
    str | None
        The full version, such as ``'152.0.7977.42'``, or ``None`` if ``Last Version`` is missing.
    """
    path = Path(config_path) / 'Last Version'
    if not path.is_file():
        return None
    return path.read_text(encoding='utf-8').strip() or None


def cache_path(version: str) -> Path:
    """
    Get where the parsed flag table for a browser version is cached.

    Parameters
    ----------
    version : str
        Full browser version.

    Returns
    -------
    pathlib.Path
        Path to the compressed cache file. Its parent may not exist yet.
    """
    import platformdirs  # ruff:ignore[import-outside-top-level]

    return Path(platformdirs.user_cache_dir('deltona')) / 'chrome-flags' / f'{version}.json.xz'


def _read_cache(path: Path) -> tuple[str, dict[str, dict[str, Any]]] | None:
    if not path.is_file():
        return None
    try:
        with lzma.open(path) as f:
            cached = json.loads(f.read())
    except (OSError, ValueError, lzma.LZMAError):
        log.debug('Discarding an unreadable flag cache at `%s`.', path)
        return None
    if cached.get('format') != _CACHE_FORMAT:
        log.debug('Discarding a flag cache written in an older format.')
        return None
    return str(cached.get('source', 'network')), dict(cached['flags'])


def _write_cache(path: Path, table: Mapping[str, Mapping[str, Any]], source: str) -> None:
    path.parent.mkdir(exist_ok=True, parents=True)
    payload = json.dumps({
        'flags': table,
        'format': _CACHE_FORMAT,
        'source': source
    },
                         separators=(',', ':'))
    path.write_bytes(lzma.compress(payload.encode(), preset=6))


def _unquote(text: str) -> str:
    return ''.join(
        part.encode().decode('unicode_escape') for part in _STRING_LITERAL_RE.findall(text))


def _load_json5(text: str) -> Any:
    return json.loads('\n'.join(
        line for line in text.splitlines() if not line.lstrip().startswith('//')))


def _strip_comments(source: str) -> str:
    def replace(match: re.Match[str]) -> str:
        token = match[0]
        return token if token[0] in {'"', "'"} else '\n' * token.count('\n')

    return _COMMENT_RE.sub(replace, source)


def _skip_string(source: str, index: int) -> int:
    literal = _STRING_LITERAL_RE.match(source, index)
    return literal.end() if literal else index + 1


def _balanced(source: str, start: int, opening: str, closing: str) -> str:
    depth = 0
    index = start
    while index < len(source):
        char = source[index]
        if char == '"':
            index = _skip_string(source, index)
            continue
        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return source[start + 1:index]
        index += 1
    return ''


def _split_top_level(source: str) -> list[str]:
    parts: list[str] = []
    depth = last = index = 0
    while index < len(source):
        char = source[index]
        if char == '"':
            index = _skip_string(source, index)
            continue
        if char in '([{':
            depth += 1
        elif char in ')]}':
            depth -= 1
        elif char == ',' and depth == 0:
            parts.append(source[last:index])
            last = index + 1
        index += 1
    parts.append(source[last:])
    return [part.strip() for part in parts if part.strip()]


def _array_first_fields(source: str, name: str) -> list[str]:
    if not (match := re.search(_ARRAY_RE.format(name=re.escape(name)), source)):
        return []
    fields: list[str] = []
    for element in _split_top_level(_balanced(source, match.end() - 1, '{', '}')):
        if not element.startswith('{'):
            continue
        if parts := _split_top_level(_balanced(element, 0, '{', '}')):
            fields.append(parts[0])
    return fields


def _label(field: str, descriptions: Mapping[str, str]) -> str:
    if field.startswith('"'):
        return _unquote(field)
    symbol = field.rsplit('::', 1)[-1]
    return _GENERIC_LABELS.get(symbol) or descriptions.get(symbol, symbol)


def _entry_options(entry_type: str, arguments: Sequence[str], source: str,
                   descriptions: Mapping[str, str]) -> list[str]:
    if entry_type in _GENERIC_OPTION_TYPES:
        return list(_GENERIC_OPTIONS)
    if entry_type in _VARIATION_OPTION_TYPES and len(arguments) > 1:
        variations = _array_first_fields(source, arguments[1])
        return [
            'Default', _ENABLED,
            *(f'{_ENABLED} {_label(field, descriptions)}' for field in variations), 'Disabled'
        ]
    if entry_type == 'MULTI_VALUE_TYPE' and arguments:
        return [_label(field, descriptions) for field in _array_first_fields(source, arguments[0])]
    return []


def _fetch(version: str, path: str) -> str:
    import niquests  # ruff:ignore[import-outside-top-level]

    url = CHROMIUM_RAW_URL.format(path=path, version=version)
    log.debug('Fetching `%s`.', url)
    response = niquests.get(url, timeout=30)
    response.raise_for_status()
    return assert_not_none(response.text)


def parse_flag_sources(about_flags: str,
                       flag_descriptions: str,
                       flag_metadata: str = '[]',
                       never_expire_list: str = '[]') -> dict[str, dict[str, Any]]:
    """
    Parse Chromium's flag sources into a table.

    Parameters
    ----------
    about_flags : str
        Contents of ``chrome/browser/about_flags.cc``.
    flag_descriptions : str
        Contents of ``chrome/browser/flag_descriptions.h``.
    flag_metadata : str
        Contents of ``chrome/browser/flag-metadata.json``. Supplies owners and expiry milestones.
    never_expire_list : str
        Contents of ``chrome/browser/flag-never-expire-list.json``.

    Returns
    -------
    dict[str, dict[str, Any]]
        Every flag keyed by internal name, with ``description``, ``expiry_milestone``, ``line``,
        ``name``, ``never_expires``, ``options``, ``os``, ``owners``, and ``type``. ``options`` are
        the choice labels ``chrome://flags`` shows, in the order the stored choice index selects
        them.

    Raises
    ------
    ValueError
        If the feature entry table cannot be found in ``about_flags``.
    """
    about_flags = _strip_comments(about_flags)
    if (start := about_flags.find(_ENTRIES_MARKER)) < 0:
        msg = 'Could not find the feature entry table in about_flags.cc.'
        raise ValueError(msg)
    descriptions = {
        match[1]: _unquote(match[2])
        for match in _DESCRIPTION_RE.finditer(flag_descriptions)
    }
    metadata = {
        item['name']: item
        for item in _load_json5(flag_metadata) if isinstance(item, dict) and 'name' in item
    }
    never_expire = set(_load_json5(never_expire_list))
    symbols = {name: _unquote(value) for name, value in _SYMBOL_RE.findall(about_flags)}
    table: dict[str, dict[str, Any]] = {}
    for match in _ENTRY_RE.finditer(about_flags, start):
        raw = match['name'].strip()
        if raw.startswith('"'):
            internal = _unquote(raw)
        elif (resolved := symbols.get(raw.rsplit('::', 1)[-1])) is not None:
            internal = resolved
        else:
            log.debug('Skipping flag entry named by the unresolved symbol `%s`.', raw)
            continue
        entry = metadata.get(internal, {})
        arguments = _split_top_level(_balanced(about_flags, match.end() - 1, '(', ')'))
        table[internal] = {
            'description': descriptions.get(match['description'], ''),
            'expiry_milestone': entry.get('expiry_milestone'),
            'line': about_flags.count('\n', 0, match.start()) + 1,
            'name': descriptions.get(match['title'], ''),
            'never_expires': internal in never_expire,
            'options': _entry_options(match['type'], arguments, about_flags, descriptions),
            'os': ' '.join(match['os'].split()),
            'owners': entry.get('owners', []),
            'type': match['type']
        }
    return table


@cache
def flag_table(version: str,
               *,
               offline: bool = False,
               refresh: bool = False) -> dict[str, dict[str, Any]]:
    """
    Get the flag table for a browser version, fetching and caching it when needed.

    Parameters
    ----------
    version : str
        Full browser version, as returned by :py:func:`installed_version`.
    offline : bool
        If ``True``, never reach the network. Only a cached table is used.
    refresh : bool
        If ``True``, ignore any cached table and fetch again.

    Returns
    -------
    dict[str, dict[str, Any]]
        Every flag keyed by internal name.

    Raises
    ------
    FlagTableUnavailable
        If the table is neither cached nor fetchable.
    """
    path = cache_path(version)
    if not refresh and (cached := _read_cache(path)) is not None and cached[0] == 'network':
        return cached[1]
    if offline:
        msg = f'No cached flag descriptions for {version} and fetching is disabled.'
        raise FlagTableUnavailable(msg)
    try:
        table = parse_flag_sources(_fetch(version, _ABOUT_FLAGS), _fetch(
            version, _FLAG_DESCRIPTIONS), _fetch(version, _FLAG_METADATA),
                                   _fetch(version, _NEVER_EXPIRE_LIST))
    except Exception as e:
        msg = f'Could not fetch flag descriptions for {version}: {e}'
        raise FlagTableUnavailable(msg) from e
    _write_cache(path, table, 'network')
    return table


def _enrich_from_metadata(version: str, table: MutableMapping[str, dict[str, Any]]) -> None:
    try:
        metadata = _load_json5(_fetch(version, _FLAG_METADATA))
    except Exception as e:  # ruff: ignore[blind-except]
        log.debug('Could not fetch flag metadata for %s: %s', version, e)
        return
    for item in metadata:
        if isinstance(item, dict) and (entry := table.get(item.get('name', ''))) is not None:
            entry['expiry_milestone'] = item.get('expiry_milestone')
            entry['owners'] = list(item.get('owners') or ())


def _binary_table(version: str, binary: StrPath | None, channel: ChromeChannel, *,
                  offline: bool) -> dict[str, dict[str, Any]] | None:
    found = Path(binary) if binary else find_browser_binary(channel)
    if found is None:
        log.debug('No installed browser binary found for the `%s` channel.', channel)
        return None
    table = extract_flag_table(found)
    if not offline:
        _enrich_from_metadata(version, table)
    _write_cache(cache_path(version), table, 'binary')
    return table


def flag_table_for(
        version: str,
        *,
        binary: StrPath | None = None,
        channel: ChromeChannel = 'stable',
        offline: bool = False,
        refresh: bool = False,
        source: Literal['auto', 'binary',
                        'network'] = 'auto') -> tuple[dict[str, dict[str, Any]], str]:
    """
    Get the flag table for a browser version from whichever source can supply it.

    ``'auto'`` prefers the on-disk cache, then the installed binary, then the network. The binary
    comes first because it needs no network and describes the entries the installed build actually
    compiled, rather than the union over every platform that the source files describe. Its table
    is cached the same way and is enriched with owners and expiry milestones from
    ``flag-metadata.json`` when the network is available, since those are not compiled in.

    Parameters
    ----------
    version : str
        Full browser version, as returned by :py:func:`installed_version`. It is the cache key, and
        the tag both the network path and the metadata enrichment fetch from.
    binary : StrPath | None
        Path to the browser binary to read. If ``None``, the install locations of ``channel`` are
        probed.
    channel : ChromeChannel
        Release channel to look for a binary of. Ignored when ``binary`` is given.
    offline : bool
        If ``True``, never reach the network. The binary path still works, without owners or expiry
        milestones.
    refresh : bool
        If ``True``, ignore any cached table and read the source again.
    source : Literal['auto', 'binary', 'network']
        Which source to allow. Default is ``'auto'``.

    Returns
    -------
    tuple[dict[str, dict[str, Any]], str]
        Every flag keyed by internal name, and the source it came from: ``'binary'``,
        ``'network'``, or ``'cache (binary)'`` or ``'cache (network)'`` for a table read back from
        the cache.

    Raises
    ------
    FlagTableUnavailable
        If no allowed source could supply the table.
    """
    path = cache_path(version)
    if (not refresh and (cached := _read_cache(path)) is not None
            and source in {'auto', cached[0]}):
        return cached[1], f'cache ({cached[0]})'
    if source != 'network':
        try:
            if (table := _binary_table(version, binary, channel, offline=offline)) is not None:
                return table, 'binary'
        except FlagBinaryUnreadable as e:
            if source == 'binary':
                raise FlagTableUnavailable(str(e)) from e
            log.debug('Falling back to the network: %s', e)
        if source == 'binary':
            msg = f'No browser binary to read the flag table of for the {channel} channel.'
            raise FlagTableUnavailable(msg)
    return flag_table(version, offline=offline, refresh=refresh), 'network'


def flag_source_url(version: str, entry: Mapping[str, Any] | None) -> str | None:
    """
    Build a permalink to a flag's declaration in ``about_flags.cc``.

    Parameters
    ----------
    version : str
        Full browser version, used as the tag in the link.
    entry : Mapping[str, Any] | None
        A value from :py:func:`flag_table`.

    Returns
    -------
    str | None
        The URL, or ``None`` when the flag is unknown.
    """
    if not entry or not entry.get('line'):
        return None
    return SOURCE_URL_TEMPLATE.format(line=entry['line'], version=version)


def parse_experiment(experiment: str) -> tuple[str, int | None]:
    """
    Split one ``enabled_labs_experiments`` entry into its flag name and choice index.

    Chrome joins the two with ``@``. An entry without a separator selects the flag's single
    non-default value.

    Parameters
    ----------
    experiment : str
        The stored entry, such as ``'data-sharing@1'``.

    Returns
    -------
    tuple[str, int | None]
        The internal flag name and the choice index, or ``None`` when there is no index.
    """
    name, separator, index = experiment.partition('@')
    if not separator or not index.isdigit():
        return experiment, None
    return name, int(index)


def _state_name(entry: Mapping[str, Any] | None, index: int | None) -> str:
    if index is None:
        return _ENABLED
    options: Sequence[str] = (entry or {}).get('options') or ()
    if 0 <= index < len(options):
        return options[index]
    return _GENERIC_OPTIONS[index] if index < len(_GENERIC_OPTIONS) else f'Choice {index}'


def _describe(version: str, name: str, entry: Mapping[str, Any] | None, state: str,
              index: int | None) -> dict[str, Any]:
    known = entry or {}
    return {
        'name': name,
        'title': known.get('name') or '',
        'state': state,
        'choice': index,
        'description': known.get('description') or '',
        'os': known.get('os') or '',
        'type': known.get('type') or '',
        'expiry_milestone': known.get('expiry_milestone'),
        'never_expires': bool(known.get('never_expires')),
        'owners': list(known.get('owners') or ()),
        'known': bool(known),
        'source': flag_source_url(version, known)
    }


def flag_states(version: str,
                experiments: Sequence[str],
                table: Mapping[str, Mapping[str, Any]],
                *,
                include_unchanged: bool = False) -> Iterator[dict[str, Any]]:
    """
    Describe the flags a browser has changed, and optionally every other flag it knows.

    Parameters
    ----------
    version : str
        Full browser version, used to build source links.
    experiments : Sequence[str]
        Contents of ``browser.enabled_labs_experiments`` from ``Local State``.
    table : Mapping[str, Mapping[str, Any]]
        The flag table, as returned by :py:func:`flag_table`.
    include_unchanged : bool
        If ``True``, also yield every flag left at its default.

    Yields
    ------
    dict[str, Any]
        The internal name, title, description, state, choice index, supported operating systems,
        entry type, expiry milestone, owners, whether the flag is known to the table, and a link to
        its declaration.
    """
    changed = dict(parse_experiment(experiment) for experiment in experiments)
    for name, index in sorted(changed.items()):
        yield _describe(version, name, table.get(name), _state_name(table.get(name), index), index)
    if include_unchanged:
        for name in sorted(set(table) - set(changed)):
            yield _describe(version, name, table[name], 'Default', None)
