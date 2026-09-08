"""
Present a profile's ``Preferences`` file the way ``chrome://settings`` does.

Chrome only writes a preference once it differs from the compiled-in default, so a raw dump shows
what changed rather than what is in effect. :py:func:`summarise_preferences` therefore walks a
curated list of the settings the browser exposes in its own user interface and reports the value
in force, marking whether it came from the file or from the default.

The summary is deliberately lossy. :py:func:`flatten_preferences` gives every stored key when the
whole file is wanted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

__all__ = ('SETTINGS', 'SettingSpec', 'flatten_preferences', 'summarise_preferences')

_RESTORE_ON_STARTUP = {
    1: 'Continue where you left off',
    4: 'Open specific pages',
    5: 'Open the New Tab page'
}
_NETWORK_PREDICTION = {0: 'Standard preloading', 1: 'Extended preloading', 2: 'No preloading'}
_COOKIE_CONTROLS = {
    0: 'Allow all cookies',
    1: 'Block third-party cookies in Incognito',
    2: 'Block third-party cookies'
}
_CONTENT_SETTING = {0: 'Default', 1: 'Allow', 2: 'Block', 3: 'Ask', 4: 'Session only'}
_ANSWER = {True: 'On', False: 'Off'}


class SettingSpec(NamedTuple):
    """One row of the settings summary."""

    key: str
    """Dotted path into the ``Preferences`` file."""
    section: str
    """Heading the setting appears under."""
    label: str
    """Human-readable name of the setting."""
    values: Mapping[Any, str] | None = None
    """Maps a stored value to its display text, for settings that are not free-form."""
    default: Any = None
    """Value in force when the key is absent, which is how Chrome stores an unchanged setting."""


SETTINGS = (
    SettingSpec('session.restore_on_startup',
                'Startup',
                'On startup',
                values=_RESTORE_ON_STARTUP,
                default=5),
    SettingSpec('session.startup_urls', 'Startup', 'Startup pages'),
    SettingSpec('homepage', 'Appearance', 'Home button URL'),
    SettingSpec('homepage_is_newtabpage',
                'Appearance',
                'Home button opens the New Tab page',
                values=_ANSWER,
                default=True),
    SettingSpec('browser.show_home_button',
                'Appearance',
                'Show home button',
                values=_ANSWER,
                default=False),
    SettingSpec('bookmark_bar.show_on_all_tabs',
                'Appearance',
                'Always show the bookmarks bar',
                values=_ANSWER,
                default=False),
    SettingSpec('extensions.theme.id', 'Appearance', 'Theme extension'),
    SettingSpec('webkit.webprefs.default_font_size', 'Appearance', 'Font size', default=16),
    SettingSpec('webkit.webprefs.default_fixed_font_size',
                'Appearance',
                'Fixed font size',
                default=13),
    SettingSpec('webkit.webprefs.minimum_font_size', 'Appearance', 'Minimum font size', default=0),
    SettingSpec('default_search_provider_data.template_url_data.short_name', 'Search',
                'Search engine'),
    SettingSpec('default_search_provider_data.template_url_data.keyword', 'Search',
                'Search engine keyword'),
    SettingSpec('search.suggest_enabled',
                'Search',
                'Autocomplete searches and URLs',
                values=_ANSWER,
                default=True),
    SettingSpec('savefile.default_directory', 'Downloads', 'Download location'),
    SettingSpec('download.default_directory', 'Downloads', 'Configured download location'),
    SettingSpec('download.prompt_for_download',
                'Downloads',
                'Ask where to save each file',
                values=_ANSWER,
                default=False),
    SettingSpec('download.open_pdf_in_system_reader',
                'Downloads',
                'Open PDFs externally',
                values=_ANSWER,
                default=False),
    SettingSpec('credentials_enable_service',
                'Autofill',
                'Offer to save passwords',
                values=_ANSWER,
                default=True),
    SettingSpec('credentials_enable_autosignin',
                'Autofill',
                'Auto sign-in',
                values=_ANSWER,
                default=True),
    SettingSpec('profile.password_manager_leak_detection',
                'Autofill',
                'Warn about compromised passwords',
                values=_ANSWER,
                default=True),
    SettingSpec('autofill.profile_enabled',
                'Autofill',
                'Save and fill addresses',
                values=_ANSWER,
                default=True),
    SettingSpec('autofill.credit_card_enabled',
                'Autofill',
                'Save and fill payment methods',
                values=_ANSWER,
                default=True),
    SettingSpec('payments.can_make_payment_enabled',
                'Autofill',
                'Allow sites to check for saved payment methods',
                values=_ANSWER,
                default=True),
    SettingSpec('safebrowsing.enabled',
                'Privacy and security',
                'Safe Browsing',
                values=_ANSWER,
                default=True),
    SettingSpec('safebrowsing.enhanced',
                'Privacy and security',
                'Enhanced Safe Browsing',
                values=_ANSWER,
                default=False),
    SettingSpec('enable_do_not_track',
                'Privacy and security',
                'Send a Do Not Track request',
                values=_ANSWER,
                default=False),
    SettingSpec('https_only_mode_enabled',
                'Privacy and security',
                'Always use secure connections',
                values=_ANSWER,
                default=False),
    SettingSpec('profile.cookie_controls_mode',
                'Privacy and security',
                'Third-party cookies',
                values=_COOKIE_CONTROLS,
                default=1),
    SettingSpec('privacy_sandbox.m1.topics_enabled',
                'Privacy and security',
                'Ad topics',
                values=_ANSWER,
                default=True),
    SettingSpec('privacy_sandbox.m1.fledge_enabled',
                'Privacy and security',
                'Site-suggested ads',
                values=_ANSWER,
                default=True),
    SettingSpec('privacy_sandbox.m1.ad_measurement_enabled',
                'Privacy and security',
                'Ad measurement',
                values=_ANSWER,
                default=True),
    SettingSpec('net.network_prediction_options',
                'Privacy and security',
                'Preload pages',
                values=_NETWORK_PREDICTION,
                default=1),
    SettingSpec('dns_over_https.mode', 'Privacy and security', 'Secure DNS mode'),
    SettingSpec('dns_over_https.templates', 'Privacy and security', 'Secure DNS provider'),
    SettingSpec('url_keyed_anonymized_data_collection.enabled',
                'Privacy and security',
                'Make searches and browsing better',
                values=_ANSWER,
                default=False),
    SettingSpec('profile.default_content_setting_values.notifications',
                'Site settings',
                'Notifications',
                values=_CONTENT_SETTING,
                default=3),
    SettingSpec('profile.default_content_setting_values.geolocation',
                'Site settings',
                'Location',
                values=_CONTENT_SETTING,
                default=3),
    SettingSpec('profile.default_content_setting_values.media_stream_camera',
                'Site settings',
                'Camera',
                values=_CONTENT_SETTING,
                default=3),
    SettingSpec('profile.default_content_setting_values.media_stream_mic',
                'Site settings',
                'Microphone',
                values=_CONTENT_SETTING,
                default=3),
    SettingSpec('profile.default_content_setting_values.javascript',
                'Site settings',
                'JavaScript',
                values=_CONTENT_SETTING,
                default=1),
    SettingSpec('profile.default_content_setting_values.images',
                'Site settings',
                'Images',
                values=_CONTENT_SETTING,
                default=1),
    SettingSpec('profile.default_content_setting_values.popups',
                'Site settings',
                'Pop-ups and redirects',
                values=_CONTENT_SETTING,
                default=2),
    SettingSpec('profile.default_content_setting_values.sound',
                'Site settings',
                'Sound',
                values=_CONTENT_SETTING,
                default=1),
    SettingSpec('intl.accept_languages', 'Languages', 'Accept languages'),
    SettingSpec('intl.selected_languages', 'Languages', 'Preferred languages'),
    SettingSpec('translate.enabled',
                'Languages',
                'Offer to translate pages',
                values=_ANSWER,
                default=True),
    SettingSpec('translate_blocked_languages', 'Languages', 'Never translate'),
    SettingSpec('spellcheck.dictionaries', 'Languages', 'Spell-check dictionaries'),
    SettingSpec('spellcheck.use_spelling_service',
                'Languages',
                'Use the enhanced spell checker',
                values=_ANSWER,
                default=False),
    SettingSpec('performance_tuning.high_efficiency_mode.state', 'Performance', 'Memory Saver'),
    SettingSpec('performance_tuning.battery_saver_mode.state', 'Performance', 'Energy Saver'),
    SettingSpec('settings.a11y.caretbrowsing.enabled',
                'Accessibility',
                'Caret browsing',
                values=_ANSWER,
                default=False),
    SettingSpec('account_info.0.email', 'Account', 'Signed-in account'),
    SettingSpec('account_info.0.full_name', 'Account', 'Account name'),
    SettingSpec('signin.allowed', 'Account', 'Sign-in allowed', values=_ANSWER, default=True),
    SettingSpec('sync.requested', 'Account', 'Sync requested', values=_ANSWER, default=False),
)
"""
Settings surfaced by the browser's own interface, in display order.

:meta hide-value:
"""

_ABSENT = object()


def _lookup(preferences: Mapping[str, Any], key: str) -> Any:
    current: Any = preferences
    for part in key.split('.'):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, (list, tuple)) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return _ABSENT
    return current


def _render(value: Any, values: Mapping[Any, str] | None) -> Any:
    if values is not None:
        key = bool(value) if isinstance(value, bool) else value
        if key in values:
            return values[key]
    if isinstance(value, (list, tuple)):
        return ', '.join(str(item) for item in value)
    return value


def summarise_preferences(preferences: Mapping[str, Any],
                          specs: Sequence[SettingSpec] = SETTINGS,
                          *,
                          changed_only: bool = False) -> list[dict[str, Any]]:
    """
    Describe the settings a profile has in force.

    Parameters
    ----------
    preferences : Mapping[str, Any]
        The parsed ``Preferences`` file.
    specs : Sequence[SettingSpec]
        Settings to report. Defaults to :py:data:`SETTINGS`.
    changed_only : bool
        If ``True``, omit settings the profile has left at their default.

    Returns
    -------
    list[dict[str, Any]]
        One row per setting, with its section, label, rendered value, whether the value came from
        the file or from the default, and the key it was read from.
    """
    rows: list[dict[str, Any]] = []
    for spec in specs:
        stored = _lookup(preferences, spec.key)
        is_set = stored is not _ABSENT
        value = stored if is_set else spec.default
        if not is_set and (changed_only or value is None):
            continue
        rows.append({
            'section': spec.section,
            'setting': spec.label,
            'value': _render(value, spec.values),
            'source': 'profile' if is_set else 'default',
            'key': spec.key
        })
    return rows


def flatten_preferences(preferences: Mapping[str, Any],
                        prefix: str = '') -> Iterator[dict[str, Any]]:
    """
    Flatten a ``Preferences`` mapping into one row per leaf value.

    Parameters
    ----------
    preferences : Mapping[str, Any]
        The parsed file, or any nested mapping within it.
    prefix : str
        Dotted path already walked, used when recursing.

    Yields
    ------
    dict[str, Any]
        The dotted ``key``, the ``value``, and its ``type`` name.
    """
    for name, value in sorted(preferences.items()):
        key = f'{prefix}.{name}' if prefix else name
        if isinstance(value, dict) and value:
            yield from flatten_preferences(value, key)
        else:
            yield {'key': key, 'value': value, 'type': type(value).__name__}
