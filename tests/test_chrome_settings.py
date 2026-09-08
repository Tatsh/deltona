"""Tests for the Chrome settings commands and library functions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
import json

import pytest

from deltona.chrome.core import webkit_timestamp_to_datetime
from deltona.chrome.settings import (
    read_content_settings,
    read_default_content_settings,
    read_extensions,
    read_search_engines,
    read_web_apps,
)
from deltona.commands.chrome import chrome_dump

if TYPE_CHECKING:
    from click.testing import CliRunner

    from .conftest import FakeChromeUserData

_TS_INT = 13390000000000000
_TS = str(_TS_INT)
_KEYWORDS_SCHEMA = ((
    'CREATE TABLE keywords (id INTEGER PRIMARY KEY, short_name TEXT, keyword TEXT, url TEXT, '
    'date_created INTEGER, last_modified INTEGER, last_visited INTEGER, alternate_urls TEXT, '
    'sync_guid TEXT, prepopulate_id INTEGER, is_active INTEGER)'),)


def _write_extension(chrome_user_data: FakeChromeUserData,
                     directory: str,
                     extension_id: str,
                     version: str,
                     manifest: dict[str, Any],
                     locales: dict[str, dict[str, str]] | None = None) -> None:
    chrome_user_data.write_json(directory, f'Extensions/{extension_id}/{version}/manifest.json',
                                manifest)
    for locale, messages in (locales or {}).items():
        chrome_user_data.write_json(
            directory, f'Extensions/{extension_id}/{version}/_locales/{locale}/messages.json', {
                key: {
                    'message': value
                }
                for key, value in messages.items()
            })


def _write_web_app_icons(chrome_user_data: FakeChromeUserData,
                         directory: str,
                         app_id: str,
                         sizes: tuple[int, ...],
                         icon_dir: str = 'Icons') -> None:
    for size in sizes:
        chrome_user_data.write_text(
            directory, f'Web Applications/Manifest Resources/{app_id}/{icon_dir}/{size}.png', '')


def _write_search_engines(chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.write_json(
        'Default', 'Preferences', {
            'default_search_provider_data': {
                'template_url_data': {
                    'synced_guid': 'guid-user'
                }
            },
            'site_search_settings': {
                'templates': [{
                    'keyword': 'site1',
                    'name': 'Site Search',
                    'url': 'https://site.example'
                }]
            }
        })
    chrome_user_data.write_database(
        'Default',
        'Web Data',
        _KEYWORDS_SCHEMA,
        rows={
            'keywords': [(1, 'My Engine', 'eng', 'https://example.com/?q=%s', 0, 0, 0, None,
                          'guid-user', 0, 1),
                         (2, 'Google', 'google.com', 'https://google.com/?q=%s', 0, 0, 0, None,
                          'guid-google', 1, 2)]
        })


def test_read_extensions_empty(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile()
    assert read_extensions(profile) == []


def test_read_extensions_populated(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile()
    manifest = {
        'name': 'Test Extension',
        'description': 'A test extension.',
        'version': '1.2.3',
        'manifest_version': 3,
        'permissions': ['storage', 'tabs'],
        'host_permissions': ['https://*.example.com/*'],
        'optional_permissions': ['bookmarks'],
        'background': {
            'service_worker': 'background.js'
        },
        'content_scripts': [{
            'matches': ['<all_urls>'],
            'js': ['content.js']
        }],
        'update_url': 'https://clients2.google.com/service/update2/crx',
        'default_locale': 'en'
    }
    _write_extension(chrome_user_data, 'Default', 'e1', '1.0', manifest)
    chrome_user_data.write_json(
        'Default', 'Preferences', {
            'extensions': {
                'settings': {
                    'e1': {
                        'state': 1,
                        'location': 1,
                        'disable_reasons': [],
                        'from_webstore': True,
                        'was_installed_by_default': False,
                        'first_install_time': _TS,
                        'granted_permissions': {
                            'api': ['storage']
                        }
                    }
                }
            }
        })
    records = read_extensions(profile)
    assert len(records) == 1
    record = records[0]
    assert record['id'] == 'e1'
    assert record['name'] == 'Test Extension'
    assert record['description'] == 'A test extension.'
    assert record['version'] == '1.2.3'
    assert record['manifest_version'] == 3
    assert record['permissions'] == ('storage', 'tabs')
    assert record['host_permissions'] == ('https://*.example.com/*',)
    assert record['optional_permissions'] == ('bookmarks',)
    assert record['permission_count'] == 3
    assert record['background'] == {'service_worker': 'background.js'}
    assert record['content_script_count'] == 1
    assert record['update_url'] == 'https://clients2.google.com/service/update2/crx'
    assert record['default_locale'] == 'en'
    assert record['state'] == 1
    assert record['state_display'] == 'enabled'
    assert record['enabled'] is True
    assert record['location'] == 1
    assert record['location_display'] == 'internal'
    assert record['from_webstore'] is True
    assert record['install_time'] == webkit_timestamp_to_datetime(_TS)
    assert record['disable_reasons'] == ()
    assert record['granted_permissions'] == {'api': ['storage']}
    assert record['was_installed_by_default'] is False
    assert record['path'] == profile / 'Extensions' / 'e1'


def test_read_extensions_message_resolution(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile()
    manifest = {'name': '__MSG_extname__', 'description': '__MSG_extdesc__', 'default_locale': 'en'}
    _write_extension(
        chrome_user_data,
        'Default',
        'e1',
        '1.0',
        manifest,
        locales={'en': {
            'extname': 'Resolved Name',
            'extdesc': 'Resolved description.'
        }})
    chrome_user_data.write_json('Default', 'Preferences', {'extensions': {'settings': {'e1': {}}}})
    record = read_extensions(profile)[0]
    assert record['name'] == 'Resolved Name'
    assert record['description'] == 'Resolved description.'


@pytest.mark.parametrize('fallback_locale', ['en', 'en_US'])
def test_read_extensions_message_fallback_locale(chrome_user_data: FakeChromeUserData,
                                                 fallback_locale: str) -> None:
    profile = chrome_user_data.add_profile()
    manifest = {'name': '__MSG_extname__', 'default_locale': 'de'}
    _write_extension(chrome_user_data,
                     'Default',
                     'e1',
                     '1.0',
                     manifest,
                     locales={fallback_locale: {
                         'extname': 'Fallback Name'
                     }})
    chrome_user_data.write_json('Default', 'Preferences', {'extensions': {'settings': {'e1': {}}}})
    assert read_extensions(profile)[0]['name'] == 'Fallback Name'


def test_read_extensions_message_unresolved(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile()
    manifest = {'name': '__MSG_missing__', 'default_locale': 'en'}
    _write_extension(chrome_user_data,
                     'Default',
                     'e1',
                     '1.0',
                     manifest,
                     locales={'en': {
                         'other': 'Unrelated'
                     }})
    chrome_user_data.write_json('Default', 'Preferences', {'extensions': {'settings': {'e1': {}}}})
    assert read_extensions(profile)[0]['name'] == '__MSG_missing__'


def test_read_extensions_locale_messages_invalid_json(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile()
    manifest = {'name': '__MSG_extname__', 'default_locale': 'en'}
    _write_extension(chrome_user_data, 'Default', 'e1', '1.0', manifest)
    chrome_user_data.write_text('Default', 'Extensions/e1/1.0/_locales/en/messages.json',
                                'not json')
    chrome_user_data.write_json('Default', 'Preferences', {'extensions': {'settings': {'e1': {}}}})
    assert read_extensions(profile)[0]['name'] == '__MSG_extname__'


def test_read_extensions_manifest_malformed_json(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile()
    chrome_user_data.write_text('Default', 'Extensions/e1/1.0/manifest.json', 'not json')
    chrome_user_data.write_json('Default', 'Preferences', {'extensions': {'settings': {'e1': {}}}})
    record = read_extensions(profile)[0]
    assert record['name'] is None
    assert record['version'] is None


def test_read_extensions_manifest_from_preferences_fallback(
        chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile()
    chrome_user_data.write_json(
        'Default', 'Preferences', {
            'extensions': {
                'settings': {
                    'e1': {
                        'manifest': {
                            'name': 'Component Extension',
                            'version': '9.0'
                        }
                    }
                }
            }
        })
    record = read_extensions(profile)[0]
    assert record['name'] == 'Component Extension'
    assert record['version'] == '9.0'
    assert record['path'] is None


def test_read_extensions_no_version_directory(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile()
    (profile / 'Extensions' / 'e1').mkdir(parents=True)
    chrome_user_data.write_json('Default', 'Preferences', {'extensions': {'settings': {'e1': {}}}})
    assert read_extensions(profile)[0]['name'] is None


def test_read_extensions_picks_latest_version_directory(
        chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile()
    _write_extension(chrome_user_data, 'Default', 'e1', '2.0', {'name': 'Old'})
    _write_extension(chrome_user_data, 'Default', 'e1', '10.0', {'name': 'New'})
    chrome_user_data.write_json('Default', 'Preferences', {'extensions': {'settings': {'e1': {}}}})
    assert read_extensions(profile)[0]['name'] == 'New'


@pytest.mark.parametrize(('state', 'disable_reasons', 'location', 'expected_state',
                          'expected_enabled', 'expected_location'),
                         [(1, (), 1, 'enabled', True, 'internal'),
                          (0, (), 2, 'disabled', False, 'external_pref'),
                          (3, (), None, 'enabled_component', True, None),
                          (42, (), 99, 'unknown (42)', False, None),
                          (None, (), None, 'enabled', True, None),
                          (None, (1,), None, 'disabled', False, None),
                          (None, 5, None, 'disabled', False, None)])
def test_read_extensions_state_location_matrix(chrome_user_data: FakeChromeUserData,
                                               state: int | None,
                                               disable_reasons: int | tuple[int, ...],
                                               location: int | None, expected_state: str, *,
                                               expected_enabled: bool,
                                               expected_location: str | None) -> None:
    profile = chrome_user_data.add_profile()
    chrome_user_data.write_json(
        'Default', 'Preferences', {
            'extensions': {
                'settings': {
                    'e1': {
                        'state': state,
                        'disable_reasons': disable_reasons,
                        'location': location
                    }
                }
            }
        })
    record = read_extensions(profile)[0]
    assert record['state_display'] == expected_state
    assert record['enabled'] is expected_enabled
    assert record['location_display'] == expected_location


def test_read_content_settings_populated(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile()
    chrome_user_data.write_json(
        'Default', 'Preferences', {
            'profile': {
                'content_settings': {
                    'exceptions': {
                        'cookies': {
                            'https://a.example.com,*': {
                                'setting': 1,
                                'last_modified': _TS,
                                'expiration': '0'
                            }
                        },
                        'geolocation': {
                            '[*.]example.com,*': {
                                'setting': 99
                            }
                        },
                        'notifications': {
                            'https://b.example.com': {
                                'setting': True
                            }
                        },
                        'popups': {
                            'https://c.example.com,*': {
                                'setting': {
                                    'nested': 'state'
                                }
                            }
                        },
                        'ignored_type': ['not', 'a', 'dict'],
                        'plugins': {
                            'https://d.example.com,*': 123
                        }
                    }
                }
            }
        })
    records = {r['type']: r for r in read_content_settings(profile)}
    assert set(records) == {'cookies', 'geolocation', 'notifications', 'popups'}
    assert records['cookies']['primary_pattern'] == 'https://a.example.com'
    assert records['cookies']['secondary_pattern'] == '*'
    assert records['cookies']['setting_display'] == 'allow'
    assert records['cookies']['last_modified'] == webkit_timestamp_to_datetime(_TS)
    assert records['cookies']['expiration'] is None
    assert records['geolocation']['secondary_pattern'] == '*'
    assert records['geolocation']['setting_display'] == 'unknown (99)'
    assert records['geolocation']['last_modified'] is None
    assert not records['notifications']['secondary_pattern']
    assert records['notifications']['setting_display'] is True
    assert records['popups']['setting_display'] == {'nested': 'state'}


def test_read_content_settings_empty(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile()
    assert read_content_settings(profile) == []


def test_read_default_content_settings_populated(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile()
    chrome_user_data.write_json('Default', 'Preferences', {
        'profile': {
            'default_content_setting_values': {
                'cookies': 1,
                'javascript': True,
                'popups': 99
            }
        }
    })
    records = {r['type']: r for r in read_default_content_settings(profile)}
    assert records['cookies']['setting_display'] == 'allow'
    assert records['javascript']['setting_display'] is True
    assert records['popups']['setting_display'] == 'unknown (99)'


def test_read_default_content_settings_empty(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile()
    assert read_default_content_settings(profile) == []


def test_read_search_engines_populated(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile()
    chrome_user_data.write_json(
        'Default', 'Preferences',
        {'default_search_provider_data': {
            'template_url_data': {
                'synced_guid': 'guid-user'
            }
        }})
    chrome_user_data.write_database(
        'Default',
        'Web Data',
        _KEYWORDS_SCHEMA,
        rows={
            'keywords': [(1, 'My Engine', 'eng', 'https://example.com/?q=%s', 0, _TS_INT, 0,
                          '["https://alt.example.com/?q=%s"]', 'guid-user', 0, 1),
                         (2, 'Google', 'google.com', 'https://google.com/?q=%s', 0, 0, 0, '',
                          'guid-google', 1, 2),
                         (3, 'Bing', 'bing.com', 'https://bing.com/?q=%s', 0, 0, 0, 'not-json',
                          'guid-bing', 1, 5),
                         (4, 'Legacy', 'legacy.com', 'https://legacy.com/?q=%s', 0, 0, 0, None,
                          'guid-legacy', 1, None)]
        })
    records = {r['short_name']: r for r in read_search_engines(profile)}
    assert records['My Engine']['is_active_display'] == 'true'
    assert records['My Engine']['alternate_urls'] == ['https://alt.example.com/?q=%s']
    assert records['My Engine']['is_default'] is True
    assert records['My Engine']['last_modified'] == webkit_timestamp_to_datetime(_TS_INT)
    assert records['My Engine']['source'] == 'keywords'
    assert records['Google']['is_active_display'] == 'false'
    assert records['Google']['alternate_urls'] is None
    assert records['Google']['is_default'] is False
    assert records['Bing']['is_active_display'] == 'unknown (5)'
    assert records['Bing']['alternate_urls'] is None
    assert records['Legacy']['is_active_display'] == 'unknown'
    assert records['Legacy']['alternate_urls'] is None


def test_read_search_engines_site_search_templates(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile()
    chrome_user_data.write_json(
        'Default', 'Preferences', {
            'site_search_settings': {
                'templates': [{
                    'keyword': 'site1',
                    'name': 'Site Search',
                    'url': 'https://site.example'
                }]
            }
        })
    chrome_user_data.write_database('Default', 'Web Data', _KEYWORDS_SCHEMA)
    assert read_search_engines(profile) == [{
        'keyword': 'site1',
        'name': 'Site Search',
        'url': 'https://site.example',
        'source': 'site_search'
    }]


@pytest.mark.parametrize(('preferences', 'expected_default'), [
    ({
        'default_search_provider_data': {
            'template_url_data': {
                'synced_guid': 'guid-a'
            }
        }
    }, True),
    ({
        'default_search_provider_data': {
            'mirrored_template_url_data': {
                'synced_guid': 'guid-a'
            }
        }
    }, True),
    ({
        'default_search_provider': {
            'guid': 'guid-a'
        }
    }, True),
    ({}, False),
])
def test_read_search_engines_default_guid(chrome_user_data: FakeChromeUserData,
                                          preferences: dict[str, Any], *,
                                          expected_default: bool) -> None:
    profile = chrome_user_data.add_profile()
    chrome_user_data.write_json('Default', 'Preferences', preferences)
    chrome_user_data.write_database(
        'Default',
        'Web Data',
        _KEYWORDS_SCHEMA,
        rows={
            'keywords': [(1, 'Engine', 'eng', 'https://example.com', 0, 0, 0, None, 'guid-a', 0, 1)]
        })
    assert read_search_engines(profile)[0]['is_default'] is expected_default


def test_read_search_engines_empty(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile()
    chrome_user_data.write_database('Default', 'Web Data', _KEYWORDS_SCHEMA)
    assert read_search_engines(profile) == []


def test_read_web_apps_populated(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile()
    chrome_user_data.write_json(
        'Default', 'Preferences', {
            'web_apps': {
                'web_app_ids': {
                    'app1': {
                        'name': 'App One',
                        'start_url': 'https://a.example',
                        'display_mode': 'standalone',
                        'is_locally_installed': True,
                        'first_install_time': _TS,
                        'latest_install_time': '0'
                    }
                }
            }
        })
    _write_web_app_icons(chrome_user_data, 'Default', 'app1', (48, 128))
    chrome_user_data.write_text('Default',
                                'Web Applications/Manifest Resources/app1/Icons/icon.png', '')
    (chrome_user_data.config_path / 'Default' / 'Web Applications' / 'Manifest Resources' / 'app1' /
     'Icons Maskable').mkdir(parents=True)
    records = read_web_apps(profile)
    assert len(records) == 1
    record = records[0]
    assert record['id'] == 'app1'
    assert record['name'] == 'App One'
    assert record['icon_sizes'] == {'Icons': [48, 128]}
    assert record['first_install_time'] == webkit_timestamp_to_datetime(_TS)
    assert record['latest_install_time'] is None


def test_read_web_apps_no_icons(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile()
    chrome_user_data.write_json('Default', 'Preferences',
                                {'web_apps': {
                                    'web_app_ids': {
                                        'app2': {
                                            'name': 'App Two'
                                        }
                                    }
                                }})
    assert read_web_apps(profile)[0]['icon_sizes'] == {}


def test_read_web_apps_fs_only(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile()
    _write_web_app_icons(chrome_user_data, 'Default', 'app3', (48,))
    record = read_web_apps(profile)[0]
    assert record['id'] == 'app3'
    assert record.get('name') is None
    assert record['icon_sizes'] == {'Icons': [48]}
    assert record['first_install_time'] is None


def test_read_web_apps_empty(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile()
    assert read_web_apps(profile) == []


def test_list_extensions_table(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile()
    _write_extension(chrome_user_data, 'Default', 'e1', '1.0', {'name': 'Ext One'})
    chrome_user_data.write_json('Default', 'Preferences',
                                {'extensions': {
                                    'settings': {
                                        'e1': {
                                            'state': 1
                                        }
                                    }
                                }})
    result = runner.invoke(chrome_dump,
                           [*chrome_user_data.argv, 'list-extensions', '-P', 'Default'])
    assert result.exit_code == 0
    assert 'Extensions in Default' in result.output


def test_list_extensions_json(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile()
    _write_extension(chrome_user_data, 'Default', 'e1', '1.0', {'name': 'Ext One'})
    chrome_user_data.write_json(
        'Default', 'Preferences', {
            'extensions': {
                'settings': {
                    'e1': {
                        'state': 1,
                        'location': 1,
                        'from_webstore': True,
                        'first_install_time': _TS
                    }
                }
            }
        })
    result = runner.invoke(chrome_dump,
                           [*chrome_user_data.argv, 'list-extensions', '-P', 'Default', '--json'])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 1
    assert data[0]['id'] == 'e1'
    assert data[0]['state_display'] == 'enabled'
    assert data[0]['location_display'] == 'internal'
    expected_install_time = webkit_timestamp_to_datetime(_TS)
    assert expected_install_time is not None
    assert data[0]['install_time'] == expected_install_time.isoformat()


def test_list_extensions_by_id(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile()
    _write_extension(chrome_user_data, 'Default', 'e1', '1.0', {'name': 'Ext One'})
    chrome_user_data.write_json('Default', 'Preferences',
                                {'extensions': {
                                    'settings': {
                                        'e1': {
                                            'state': 1
                                        }
                                    }
                                }})
    result = runner.invoke(
        chrome_dump,
        [*chrome_user_data.argv, 'list-extensions', '-P', 'Default', '-i', 'e1', '--json'])
    assert result.exit_code == 0
    assert json.loads(result.output)['name'] == 'Ext One'


def test_list_extensions_by_id_not_found(runner: CliRunner,
                                         chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile()
    result = runner.invoke(
        chrome_dump, [*chrome_user_data.argv, 'list-extensions', '-P', 'Default', '-i', 'missing'])
    assert result.exit_code != 0
    assert "No extension with ID 'missing'" in result.output


@pytest.mark.parametrize(('flag', 'expected_ids'), [('--enabled', ['e1']), ('--disabled', ['e2'])])
def test_list_extensions_enabled_disabled_filter(runner: CliRunner,
                                                 chrome_user_data: FakeChromeUserData, flag: str,
                                                 expected_ids: list[str]) -> None:
    chrome_user_data.add_profile()
    _write_extension(chrome_user_data, 'Default', 'e1', '1.0', {'name': 'One'})
    _write_extension(chrome_user_data, 'Default', 'e2', '1.0', {'name': 'Two'})
    chrome_user_data.write_json(
        'Default', 'Preferences',
        {'extensions': {
            'settings': {
                'e1': {
                    'state': 1
                },
                'e2': {
                    'state': 0
                }
            }
        }})
    result = runner.invoke(
        chrome_dump, [*chrome_user_data.argv, 'list-extensions', '-P', 'Default', flag, '--json'])
    assert result.exit_code == 0
    assert [r['id'] for r in json.loads(result.output)] == expected_ids


def test_list_permissions_table(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile()
    chrome_user_data.write_json(
        'Default', 'Preferences', {
            'profile': {
                'content_settings': {
                    'exceptions': {
                        'cookies': {
                            'https://a.example.com,*': {
                                'setting': 1
                            }
                        }
                    }
                }
            }
        })
    result = runner.invoke(chrome_dump,
                           [*chrome_user_data.argv, 'list-permissions', '-P', 'Default'])
    assert result.exit_code == 0
    assert 'Content setting exceptions in Default' in result.output


def test_list_permissions_json(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile()
    chrome_user_data.write_json(
        'Default', 'Preferences', {
            'profile': {
                'content_settings': {
                    'exceptions': {
                        'cookies': {
                            'https://a.example.com,*': {
                                'setting': 1
                            }
                        },
                        'geolocation': {
                            'https://b.example.com,*': {
                                'setting': 99
                            }
                        }
                    }
                }
            }
        })
    result = runner.invoke(chrome_dump,
                           [*chrome_user_data.argv, 'list-permissions', '-P', 'Default', '--json'])
    assert result.exit_code == 0
    data = {r['type']: r for r in json.loads(result.output)}
    assert data['cookies']['setting_display'] == 'allow'
    assert data['geolocation']['setting_display'] == 'unknown (99)'


def test_list_permissions_defaults(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile()
    chrome_user_data.write_json(
        'Default', 'Preferences',
        {'profile': {
            'default_content_setting_values': {
                'cookies': 1,
                'popups': 99
            }
        }})
    result = runner.invoke(
        chrome_dump, [*chrome_user_data.argv, 'list-permissions', '-P', 'Default', '--defaults'])
    assert result.exit_code == 0
    assert 'cookies' in result.output
    assert 'allow' in result.output


def test_list_permissions_type_filter(runner: CliRunner,
                                      chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile()
    chrome_user_data.write_json(
        'Default', 'Preferences', {
            'profile': {
                'content_settings': {
                    'exceptions': {
                        'cookies': {
                            'https://a.example.com,*': {
                                'setting': 1
                            }
                        },
                        'geolocation': {
                            'https://b.example.com,*': {
                                'setting': 2
                            }
                        }
                    }
                }
            }
        })
    result = runner.invoke(
        chrome_dump,
        [*chrome_user_data.argv, 'list-permissions', '-P', 'Default', '-t', 'cookies', '--json'])
    assert result.exit_code == 0
    assert [r['type'] for r in json.loads(result.output)] == ['cookies']


def test_list_permissions_no_settings(runner: CliRunner,
                                      chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile()
    result = runner.invoke(chrome_dump,
                           [*chrome_user_data.argv, 'list-permissions', '-P', 'Default'])
    assert result.exit_code == 0
    assert 'No content setting exceptions in default found.' in result.output


def test_list_search_engines_table(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile()
    _write_search_engines(chrome_user_data)
    result = runner.invoke(chrome_dump,
                           [*chrome_user_data.argv, 'list-search-engines', '-P', 'Default'])
    assert result.exit_code == 0
    assert 'Search engines in Default' in result.output


def test_list_search_engines_json(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile()
    _write_search_engines(chrome_user_data)
    result = runner.invoke(
        chrome_dump, [*chrome_user_data.argv, 'list-search-engines', '-P', 'Default', '--json'])
    assert result.exit_code == 0
    data = json.loads(result.output)
    names = {r.get('short_name') or r.get('name') for r in data}
    assert names == {'My Engine', 'Site Search'}
    default_record = next(r for r in data if r.get('short_name') == 'My Engine')
    assert default_record['is_default'] is True


def test_list_search_engines_all_flag(runner: CliRunner,
                                      chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile()
    _write_search_engines(chrome_user_data)
    result = runner.invoke(
        chrome_dump,
        [*chrome_user_data.argv, 'list-search-engines', '-P', 'Default', '--all', '--json'])
    assert result.exit_code == 0
    data = json.loads(result.output)
    names = {r.get('short_name') or r.get('name') for r in data}
    assert names == {'My Engine', 'Google', 'Site Search'}


def test_list_search_engines_missing_web_data(runner: CliRunner,
                                              chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile()
    result = runner.invoke(chrome_dump,
                           [*chrome_user_data.argv, 'list-search-engines', '-P', 'Default'])
    assert result.exit_code != 0
    assert 'Web Data' in result.output


def test_list_web_apps_table(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile()
    chrome_user_data.write_json('Default', 'Preferences', {
        'web_apps': {
            'web_app_ids': {
                'app1': {
                    'name': 'App One',
                    'start_url': 'https://a.example'
                }
            }
        }
    })
    _write_web_app_icons(chrome_user_data, 'Default', 'app1', (48,))
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-web-apps', '-P', 'Default'])
    assert result.exit_code == 0
    assert 'Web apps in Default' in result.output


def test_list_web_apps_json(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile()
    chrome_user_data.write_json(
        'Default', 'Preferences', {
            'web_apps': {
                'web_app_ids': {
                    'app1': {
                        'name': 'App One',
                        'start_url': 'https://a.example',
                        'first_install_time': _TS
                    }
                }
            }
        })
    _write_web_app_icons(chrome_user_data, 'Default', 'app1', (48, 128))
    result = runner.invoke(chrome_dump,
                           [*chrome_user_data.argv, 'list-web-apps', '-P', 'Default', '--json'])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 1
    assert data[0]['id'] == 'app1'
    assert data[0]['icon_sizes'] == {'Icons': [48, 128]}
    expected_install_time = webkit_timestamp_to_datetime(_TS)
    assert expected_install_time is not None
    assert data[0]['first_install_time'] == expected_install_time.isoformat()


def test_list_web_apps_by_id(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile()
    chrome_user_data.write_json('Default', 'Preferences',
                                {'web_apps': {
                                    'web_app_ids': {
                                        'app1': {
                                            'name': 'App One'
                                        }
                                    }
                                }})
    result = runner.invoke(
        chrome_dump,
        [*chrome_user_data.argv, 'list-web-apps', '-P', 'Default', '-i', 'app1', '--json'])
    assert result.exit_code == 0
    assert json.loads(result.output)['name'] == 'App One'


def test_list_web_apps_by_id_not_found(runner: CliRunner,
                                       chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile()
    result = runner.invoke(
        chrome_dump, [*chrome_user_data.argv, 'list-web-apps', '-P', 'Default', '-i', 'missing'])
    assert result.exit_code != 0
    assert "No web app with ID 'missing'" in result.output


def test_list_web_apps_no_web_apps_key(runner: CliRunner,
                                       chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile()
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-web-apps', '-P', 'Default'])
    assert result.exit_code == 0
    assert 'No web apps in default found.' in result.output


@pytest.mark.parametrize(
    'subcommand', ['list-extensions', 'list-permissions', 'list-search-engines', 'list-web-apps'])
def test_missing_preferences_file(runner: CliRunner, chrome_user_data: FakeChromeUserData,
                                  subcommand: str) -> None:
    chrome_user_data.add_profile()
    (chrome_user_data.config_path / 'Default' / 'Preferences').unlink()
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, subcommand, '-P', 'Default'])
    assert result.exit_code != 0
    assert 'No `Preferences` file' in result.output


def test_missing_preferences_file_defaults(runner: CliRunner,
                                           chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile()
    (chrome_user_data.config_path / 'Default' / 'Preferences').unlink()
    result = runner.invoke(
        chrome_dump, [*chrome_user_data.argv, 'list-permissions', '-P', 'Default', '--defaults'])
    assert result.exit_code != 0
    assert 'No `Preferences` file' in result.output
