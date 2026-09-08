"""Read a profile's extensions, content setting exceptions, search engines, and web apps."""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
import json
import os
import re

from .core import query_database, webkit_timestamp_to_datetime

if TYPE_CHECKING:
    from collections.abc import Mapping

    from deltona.typing import StrPath

__all__ = ('CONTENT_SETTING_VALUES', 'EXTENSION_LOCATIONS', 'EXTENSION_STATES',
           'SEARCH_ENGINE_ACTIVE_STATUSES', 'read_content_settings',
           'read_default_content_settings', 'read_extensions', 'read_search_engines',
           'read_web_apps')

_MSG_RE = re.compile(r'^__MSG_(?P<key>.+)__$')
_ICON_DIR_NAMES = ('Icons', 'Icons Maskable', 'Icons Monochrome')

EXTENSION_STATES: dict[int, str] = {
    0: 'disabled',
    1: 'enabled',
    2: 'external_extension_uninstalled',
    3: 'enabled_component'
}
"""
Names of the legacy ``extensions.settings.<id>.state`` value.

Current Chrome versions no longer write this field, deriving the enabled state from
``disable_reasons`` instead, but older profiles may still carry it.

See Also
--------
`extension.h at 120.0.6099.1 <https://chromium.googlesource.com/chromium/src/+/120.0.6099.1/
extensions/common/extension.h>`_

:meta hide-value:
"""
EXTENSION_LOCATIONS: dict[int, str] = {
    0: 'invalid',
    1: 'internal',
    2: 'external_pref',
    3: 'external_registry',
    4: 'unpacked',
    5: 'component',
    6: 'external_pref_download',
    7: 'external_policy_download',
    8: 'command_line',
    9: 'external_policy',
    10: 'external_component'
}
"""
Names of the ``extensions.settings.<id>.location`` value (``ManifestLocation``).

See Also
--------
`manifest.mojom <https://source.chromium.org/chromium/chromium/src/+/main:extensions/common/mojom/manifest.mojom>`_

:meta hide-value:
"""
CONTENT_SETTING_VALUES: dict[int, str] = {
    0: 'default',
    1: 'allow',
    2: 'block',
    3: 'ask',
    4: 'session_only'
}
"""
Names of a ``ContentSetting`` value.

See Also
--------
`content_settings.h <https://source.chromium.org/chromium/chromium/src/+/main:components/content_settings/core/common/content_settings.h>`_

:meta hide-value:
"""
SEARCH_ENGINE_ACTIVE_STATUSES: dict[int, str] = {0: 'unspecified', 1: 'true', 2: 'false'}
"""
Names of the ``keywords.is_active`` column (``TemplateURLData::ActiveStatus``).

See Also
--------
`template_url_data.h <https://source.chromium.org/chromium/chromium/src/+/main:components/search_engines/template_url_data.h>`_

:meta hide-value:
"""


def _load_json(path: Path) -> dict[str, Any]:
    return cast('dict[str, Any]', json.loads(path.read_text(encoding='utf-8')))


def _version_key(directory_name: str) -> tuple[int, ...]:
    version = directory_name.rsplit('_', 1)[0]
    return tuple(int(part) if part.isdigit() else 0 for part in version.split('.'))


def _latest_version_directory(extension_directory: Path) -> Path | None:
    candidates = [
        child for child in extension_directory.iterdir()
        if child.is_dir() and (child / 'manifest.json').is_file()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda child: _version_key(child.name))


def _read_manifest(version_directory: Path) -> dict[str, Any]:
    with suppress(OSError, ValueError):
        return cast('dict[str, Any]',
                    json.loads((version_directory / 'manifest.json').read_text(encoding='utf-8')))
    return {}


def _locale_messages(version_directory: Path, locale: str) -> dict[str, str]:
    path = version_directory / '_locales' / locale / 'messages.json'
    if not path.is_file():
        return {}
    with suppress(OSError, ValueError):
        data = json.loads(path.read_text(encoding='utf-8'))
        return {
            key.casefold(): value['message']
            for key, value in data.items() if isinstance(value, dict) and 'message' in value
        }
    return {}


def _resolve_message(value: str | None, version_directory: Path,
                     default_locale: str | None) -> str | None:
    if not value or not (match := _MSG_RE.match(value)):
        return value
    key = match['key'].casefold()
    for locale in filter(None, (default_locale, 'en', 'en_US')):
        messages = _locale_messages(version_directory, locale)
        if key in messages:
            return messages[key]
    return value


def _bitmask_to_flags(value: int) -> tuple[int, ...]:
    return tuple(bit for i in range(value.bit_length()) if value & (bit := 1 << i))


def _extension_record(extension_id: str, extension_directory: Path | None,
                      preferences_entry: Mapping[str, Any]) -> dict[str, Any]:
    manifest: dict[str, Any] = {}
    version_directory = (_latest_version_directory(extension_directory)
                         if extension_directory else None)
    if version_directory is not None:
        manifest = _read_manifest(version_directory)
    if not manifest:
        manifest = cast('dict[str, Any]', preferences_entry.get('manifest', {}))
    default_locale = manifest.get('default_locale')
    name = manifest.get('name')
    description = manifest.get('description')
    if version_directory is not None:
        name = _resolve_message(name, version_directory, default_locale)
        description = _resolve_message(description, version_directory, default_locale)
    state = preferences_entry.get('state')
    raw_disable_reasons = preferences_entry.get('disable_reasons', ())
    disable_reasons = (_bitmask_to_flags(raw_disable_reasons) if isinstance(
        raw_disable_reasons, int) else tuple(raw_disable_reasons))
    enabled = state in {1, 3} if state is not None else not disable_reasons
    location = preferences_entry.get('location')
    permissions = tuple(manifest.get('permissions', ()))
    host_permissions = tuple(manifest.get('host_permissions', ()))
    return {
        'id':
            extension_id,
        'name':
            name,
        'version':
            manifest.get('version'),
        'description':
            description,
        'manifest_version':
            manifest.get('manifest_version'),
        'permissions':
            permissions,
        'host_permissions':
            host_permissions,
        'optional_permissions':
            tuple(manifest.get('optional_permissions', ())),
        'permission_count':
            len(permissions) + len(host_permissions),
        'background':
            manifest.get('background'),
        'content_script_count':
            len(manifest.get('content_scripts', ())),
        'update_url':
            manifest.get('update_url'),
        'default_locale':
            default_locale,
        'state':
            state,
        'state_display':
            EXTENSION_STATES.get(state, f'unknown ({state})') if state is not None else
            ('enabled' if enabled else 'disabled'),
        'enabled':
            enabled,
        'location':
            location,
        'location_display':
            EXTENSION_LOCATIONS.get(location) if location is not None else None,
        'from_webstore':
            bool(preferences_entry.get('from_webstore')),
        'install_time':
            webkit_timestamp_to_datetime(
                preferences_entry.get('first_install_time')
                or preferences_entry.get('install_time')),
        'disable_reasons':
            disable_reasons,
        'granted_permissions':
            preferences_entry.get('granted_permissions'),
        'was_installed_by_default':
            bool(preferences_entry.get('was_installed_by_default')),
        'path':
            extension_directory
    }


def read_extensions(path: StrPath) -> list[dict[str, Any]]:
    """
    Read every extension installed in a profile.

    Extensions are read from both the ``Extensions`` directory, which holds the manifest, and
    ``extensions.settings`` in ``Preferences``, which holds installation metadata. Either source
    alone may be incomplete: component and externally managed extensions can be absent from disk,
    and a partially written ``Preferences`` can be missing an entry that is still installed.

    Parameters
    ----------
    path : StrPath
        Path to the profile directory.

    Returns
    -------
    list[dict[str, Any]]
        One record per extension ID, ordered by ID. ``name`` and ``description`` are resolved from
        the extension's own locale messages when the manifest uses a ``__MSG_*__`` placeholder.

    Raises
    ------
    FileNotFoundError
        If the profile has no ``Preferences`` file.
    """
    profile = Path(path)
    preferences_path = profile / 'Preferences'
    if not preferences_path.is_file():
        raise FileNotFoundError(os.strerror(2), str(preferences_path))
    settings = cast('dict[str, Any]',
                    _load_json(preferences_path).get('extensions', {}).get('settings', {}))
    extensions_directory = profile / 'Extensions'
    on_disk = ({child.name
                for child in extensions_directory.iterdir()
                if child.is_dir()} if extensions_directory.is_dir() else set())
    return [
        _extension_record(extension_id,
                          extensions_directory / extension_id if extension_id in on_disk else None,
                          settings.get(extension_id, {}))
        for extension_id in sorted(on_disk | settings.keys())
    ]


def read_content_settings(path: StrPath) -> list[dict[str, Any]]:
    """
    Read a profile's per-site content setting exceptions.

    Parameters
    ----------
    path : StrPath
        Path to the profile directory.

    Returns
    -------
    list[dict[str, Any]]
        One record per exception, with ``type``, the primary and secondary patterns split from the
        stored ``"primary,secondary"`` key, the raw ``setting``, a decoded ``setting_display``, and
        the parsed ``last_modified``/``expiration`` timestamps. Types whose value is not a plain
        ``ContentSetting`` integer (a few store nested state instead) keep ``setting_display`` equal
        to the raw value.

    Raises
    ------
    FileNotFoundError
        If the profile has no ``Preferences`` file.
    """
    profile = Path(path)
    preferences_path = profile / 'Preferences'
    if not preferences_path.is_file():
        raise FileNotFoundError(os.strerror(2), str(preferences_path))
    preferences = _load_json(preferences_path)
    exceptions = preferences.get('profile', {}).get('content_settings', {}).get('exceptions', {})
    records = []
    for setting_type, patterns in sorted(exceptions.items()):
        if not isinstance(patterns, dict):
            continue
        for pattern_key, value in patterns.items():
            if not isinstance(value, dict):
                continue
            primary, _, secondary = pattern_key.partition(',')
            setting = value.get('setting')
            records.append({
                'type': setting_type,
                'primary_pattern': primary,
                'secondary_pattern': secondary,
                'setting': setting,
                'setting_display': _decode_setting(setting),
                'last_modified': webkit_timestamp_to_datetime(value.get('last_modified')),
                'expiration': webkit_timestamp_to_datetime(value.get('expiration'))
            })
    return records


def read_default_content_settings(path: StrPath) -> list[dict[str, Any]]:
    """
    Read a profile's default content setting values.

    Parameters
    ----------
    path : StrPath
        Path to the profile directory.

    Returns
    -------
    list[dict[str, Any]]
        One record per configured type, with the raw ``setting`` and a decoded
        ``setting_display``.

    Raises
    ------
    FileNotFoundError
        If the profile has no ``Preferences`` file.
    """
    profile = Path(path)
    preferences_path = profile / 'Preferences'
    if not preferences_path.is_file():
        raise FileNotFoundError(os.strerror(2), str(preferences_path))
    preferences = _load_json(preferences_path)
    defaults = preferences.get('profile', {}).get('default_content_setting_values', {})
    return [{
        'type': setting_type,
        'setting': setting,
        'setting_display': _decode_setting(setting)
    } for setting_type, setting in sorted(defaults.items())]


def _default_search_engine_guid(preferences: Mapping[str, Any]) -> str | None:
    data = preferences.get('default_search_provider_data', {})
    for key in ('template_url_data', 'mirrored_template_url_data'):
        if guid := data.get(key, {}).get('synced_guid'):
            return cast('str', guid)
    return preferences.get('default_search_provider', {}).get('guid') or None


def _decode_setting(setting: Any) -> Any:
    if isinstance(setting, bool) or not isinstance(setting, int):
        return setting
    return CONTENT_SETTING_VALUES.get(setting, f'unknown ({setting})')


def _parse_json_field(value: str | None) -> Any:
    if not value:
        return None
    with suppress(ValueError):
        return json.loads(value)
    return None


def read_search_engines(path: StrPath) -> list[dict[str, Any]]:
    """
    Read a profile's search engines.

    Parameters
    ----------
    path : StrPath
        Path to the profile directory.

    Returns
    -------
    list[dict[str, Any]]
        Every column of ``keywords`` in ``Web Data``, plus every site search template from
        ``site_search_settings.templates`` in ``Preferences``. Timestamps are converted,
        ``alternate_urls`` is parsed from its stored JSON string, ``is_active_display`` is decoded,
        ``is_default`` marks the profile's default engine, and ``source`` is either
        ``'keywords'`` or ``'site_search'``.

    Raises
    ------
    FileNotFoundError
        If the profile has no ``Preferences`` file.
    """
    profile = Path(path)
    preferences_path = profile / 'Preferences'
    if not preferences_path.is_file():
        raise FileNotFoundError(os.strerror(2), str(preferences_path))
    preferences = _load_json(preferences_path)
    default_guid = _default_search_engine_guid(preferences)
    records = []
    for row in query_database(profile / 'Web Data', 'SELECT * FROM keywords ORDER BY short_name'):
        is_active = row.get('is_active')
        records.append({
            **row, 'date_created':
                webkit_timestamp_to_datetime(row.get('date_created')),
            'last_modified':
                webkit_timestamp_to_datetime(row.get('last_modified')),
            'last_visited':
                webkit_timestamp_to_datetime(row.get('last_visited')),
            'alternate_urls':
                _parse_json_field(row.get('alternate_urls')),
            'is_active_display':
                SEARCH_ENGINE_ACTIVE_STATUSES.get(is_active, f'unknown ({is_active})')
                if isinstance(is_active, int) else 'unknown',
            'is_default':
                bool(default_guid) and row.get('sync_guid') == default_guid,
            'source':
                'keywords'
        })
    templates = preferences.get('site_search_settings', {}).get('templates', [])
    records.extend({**template, 'source': 'site_search'} for template in templates)
    return records


def _icon_sizes(app_directory: Path) -> dict[str, list[int]]:
    sizes: dict[str, list[int]] = {}
    for directory_name in _ICON_DIR_NAMES:
        icon_directory = app_directory / directory_name
        if not icon_directory.is_dir():
            continue
        found = sorted(
            int(icon.stem) for icon in icon_directory.glob('*.png') if icon.stem.isdigit())
        if found:
            sizes[directory_name] = found
    return sizes


def read_web_apps(path: StrPath) -> list[dict[str, Any]]:
    """
    Read a profile's installed web apps.

    Parameters
    ----------
    path : StrPath
        Path to the profile directory.

    Returns
    -------
    list[dict[str, Any]]
        One record per app ID, merging whatever keys are present under
        ``web_apps.web_app_ids.<id>`` and ``web_app_install_metrics.<id>`` in ``Preferences`` with
        the icon sizes found on disk under ``Web Applications/Manifest Resources/<id>``. Install
        times are converted when present.

    Raises
    ------
    FileNotFoundError
        If the profile has no ``Preferences`` file.

    Notes
    -----
    Chrome keeps the app registry proper, including each app's name, start URL, and display mode,
    in a protocol buffer store rather than in ``Preferences``, so those fields are absent here.
    """
    profile = Path(path)
    preferences_path = profile / 'Preferences'
    if not preferences_path.is_file():
        raise FileNotFoundError(os.strerror(2), str(preferences_path))
    preferences = _load_json(preferences_path)
    web_app_ids = cast('dict[str, Any]', preferences.get('web_apps', {}).get('web_app_ids', {}))
    install_metrics = cast('dict[str, Any]', preferences.get('web_app_install_metrics', {}))
    manifest_resources = profile / 'Web Applications' / 'Manifest Resources'
    on_disk = ({child.name
                for child in manifest_resources.iterdir()
                if child.is_dir()} if manifest_resources.is_dir() else set())
    records = []
    for app_id in sorted(on_disk | web_app_ids.keys() | install_metrics.keys()):
        record: dict[str, Any] = {**web_app_ids.get(app_id, {}), **install_metrics.get(app_id, {})}
        record['id'] = app_id
        record['install_timestamp'] = webkit_timestamp_to_datetime(record.get('install_timestamp'))
        record['icon_sizes'] = (_icon_sizes(manifest_resources /
                                            app_id) if app_id in on_disk else {})
        record['first_install_time'] = webkit_timestamp_to_datetime(
            record.get('first_install_time'))
        record['latest_install_time'] = webkit_timestamp_to_datetime(
            record.get('latest_install_time'))
        records.append(record)
    return records
