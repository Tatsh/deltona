from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
import json

import pytest

from deltona.chrome.browsing import (
    find_bookmark_folder,
    flatten_bookmarks,
    read_bookmarks,
    read_custom_dictionary,
    read_downloads,
    read_history,
    read_history_urls,
    read_search_terms,
    read_shortcuts,
    read_top_sites,
)
from deltona.commands.chrome import chrome_dump

if TYPE_CHECKING:
    from click.testing import CliRunner

    from .conftest import FakeChromeUserData

CUSTOM_DICTIONARY_TEXT = 'word1\n\nword2\nchecksum_v1 = abc123\n'
DT_2020_01_01 = datetime(2020, 1, 1, tzinfo=timezone.utc)
DT_2022_11_05 = datetime(2022, 11, 5, 18, 45, tzinfo=timezone.utc)
DT_2023_06_01 = datetime(2023, 6, 1, 8, tzinfo=timezone.utc)
DT_2024_03_15 = datetime(2024, 3, 15, 12, 30, tzinfo=timezone.utc)
DT_2024_03_16 = datetime(2024, 3, 16, 9, tzinfo=timezone.utc)
WEBKIT_2020_01_01 = 13222310400000000
WEBKIT_2022_11_05 = 13312147500000000
WEBKIT_2023_06_01 = 13330080000000000
WEBKIT_2024_03_15 = 13354979400000000
WEBKIT_2024_03_16 = 13355053200000000
TRANSITION_TYPED_QUALIFIED = 1 | 0x02000000 | 0x10000000
TRANSITION_UNKNOWN = 99
_HISTORY_SCHEMA = (
    ('CREATE TABLE downloads(id INTEGER PRIMARY KEY, target_path TEXT, start_time INTEGER, '
     'end_time INTEGER, last_access_time INTEGER, received_bytes INTEGER, total_bytes INTEGER, '
     'state INTEGER, danger_type INTEGER, interrupt_reason INTEGER, tab_url TEXT)'),
    'CREATE TABLE downloads_url_chains(id INTEGER, chain_index INTEGER, url TEXT)',
    ('CREATE TABLE downloads_slices(download_id INTEGER, offset INTEGER, received_bytes INTEGER, '
     'finished INTEGER)'),
    ('CREATE TABLE urls(id INTEGER PRIMARY KEY, url TEXT, title TEXT, visit_count INTEGER, '
     'typed_count INTEGER, hidden INTEGER, last_visit_time INTEGER)'),
    ('CREATE TABLE visits(id INTEGER PRIMARY KEY, url INTEGER, visit_time INTEGER, '
     'from_visit INTEGER, transition INTEGER, segment_id INTEGER, visit_duration INTEGER, '
     'opener_visit INTEGER, external_referrer_url TEXT, app_id TEXT)'),
    ('CREATE TABLE keyword_search_terms(keyword_id INTEGER, term TEXT, normalized_term TEXT, '
     'url_id INTEGER)'),
)
_HISTORY_ROWS: dict[str, list[tuple[Any, ...]]] = {
    'downloads': [
        (1, '/home/user/Downloads/a.zip', WEBKIT_2024_03_15, WEBKIT_2023_06_01, WEBKIT_2023_06_01,
         100, 200, 1, 0, 0, 'https://a.example'),
        (2, '/home/user/Downloads/b.zip', WEBKIT_2020_01_01, 0, 0, 50, 50, 99, 99, 99,
         'https://b.example'),
    ],
    'downloads_url_chains': [
        (1, 0, 'https://a.example/redirect'),
        (1, 1, 'https://a.example/final'),
        (2, 0, 'https://b.example'),
    ],
    'downloads_slices': [(1, 0, 100, 1), (2, 0, 50, 0)],
    'urls': [
        (1, 'https://example.com', 'Example', 5, 2, 0, WEBKIT_2024_03_15),
        (2, 'https://other.com', 'Other Site', 1, 0, 0, WEBKIT_2020_01_01),
    ],
    'visits': [
        (1, 1, WEBKIT_2024_03_15, 0, TRANSITION_TYPED_QUALIFIED, 10, 500, 0, '', ''),
        (2, 2, WEBKIT_2020_01_01, 0, TRANSITION_UNKNOWN, 0, 0, 0, '', ''),
    ],
    'keyword_search_terms': [
        (1, 'example query', 'example query', 1),
        (2, 'other', 'other', 2),
    ],
}
_SHORTCUTS_SCHEMA = (('CREATE TABLE omni_box_shortcuts(text TEXT, url TEXT, contents TEXT, '
                      'transition INTEGER, last_access_time INTEGER)'),)
_SHORTCUTS_ROWS: dict[str, list[tuple[Any, ...]]] = {
    'omni_box_shortcuts': [
        ('ex', 'https://example.com', 'Example', TRANSITION_TYPED_QUALIFIED, WEBKIT_2024_03_15),
        ('zz', 'https://zzz.com', 'ZZZ', TRANSITION_UNKNOWN, WEBKIT_2020_01_01),
    ],
}
_TOP_SITES_SCHEMA = ('CREATE TABLE top_sites(url TEXT, url_rank INTEGER, title TEXT)',)
_TOP_SITES_ROWS: dict[str, list[tuple[Any, ...]]] = {
    'top_sites': [('https://b.com', 1, 'B Site'), ('https://a.com', 0, 'A Site')],
}


def _bookmarks_data() -> dict[str, Any]:
    return {
        'roots': {
            'bookmark_bar': {
                'type':
                    'folder',
                'name':
                    'Bookmark Bar',
                'date_added':
                    str(WEBKIT_2024_03_15),
                'children': [
                    {
                        'type':
                            'folder',
                        'name':
                            'Sub',
                        'date_added':
                            str(WEBKIT_2024_03_16),
                        'children': [{
                            'type': 'url',
                            'name': 'Example',
                            'url': 'https://example.com',
                            'date_added': str(WEBKIT_2023_06_01),
                            'guid': 'guid-example',
                            'id': '1'
                        }]
                    },
                    {
                        'type': 'url',
                        'name': 'Top',
                        'url': 'https://top.example',
                        'date_added': str(WEBKIT_2022_11_05),
                        'guid': 'guid-top',
                        'id': '2'
                    },
                ]
            },
            'other': {
                'type': 'folder',
                'name': 'Other Bookmarks',
                'children': []
            },
            'synced': {
                'type': 'folder',
                'name': 'Synced Bookmarks'
            }
        }
    }


def _write_bookmarks(chrome_user_data: FakeChromeUserData, directory: str = 'Default') -> None:
    chrome_user_data.write_json(directory, 'Bookmarks', _bookmarks_data())


def _write_history_db(chrome_user_data: FakeChromeUserData,
                      directory: str = 'Default',
                      *,
                      populate: bool = True) -> None:
    chrome_user_data.write_database(directory, 'History', _HISTORY_SCHEMA,
                                    _HISTORY_ROWS if populate else None)


def _write_shortcuts_db(chrome_user_data: FakeChromeUserData,
                        directory: str = 'Default',
                        *,
                        populate: bool = True) -> None:
    chrome_user_data.write_database(directory, 'Shortcuts', _SHORTCUTS_SCHEMA,
                                    _SHORTCUTS_ROWS if populate else None)


def _write_top_sites_db(chrome_user_data: FakeChromeUserData,
                        directory: str = 'Default',
                        *,
                        populate: bool = True) -> None:
    chrome_user_data.write_database(directory, 'Top Sites', _TOP_SITES_SCHEMA,
                                    _TOP_SITES_ROWS if populate else None)


def test_read_bookmarks_populated(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    _write_bookmarks(chrome_user_data)
    roots = read_bookmarks(profile)
    bookmark_bar = roots['bookmark_bar']
    assert bookmark_bar['name'] == 'Bookmark Bar'
    assert bookmark_bar['type'] == 'folder'
    assert bookmark_bar['date_added'] == DT_2024_03_15
    sub, top = bookmark_bar['children']
    assert sub['name'] == 'Sub'
    assert sub['date_added'] == DT_2024_03_16
    example = sub['children'][0]
    assert example['name'] == 'Example'
    assert example['url'] == 'https://example.com'
    assert example['date_added'] == DT_2023_06_01
    assert example['date_last_used'] is None
    assert top['name'] == 'Top'
    assert top['url'] == 'https://top.example'
    assert top['date_added'] == DT_2022_11_05
    assert roots['other']['children'] == []
    assert 'children' not in roots['synced']


def test_read_bookmarks_uses_backup_when_missing(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    chrome_user_data.write_json('Default', 'Bookmarks.bak', _bookmarks_data())
    roots = read_bookmarks(profile)
    assert roots['bookmark_bar']['name'] == 'Bookmark Bar'


def test_read_bookmarks_missing_raises(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    with pytest.raises(FileNotFoundError):
        read_bookmarks(profile)


def test_flatten_bookmarks_populated(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    _write_bookmarks(chrome_user_data)
    flattened = flatten_bookmarks(read_bookmarks(profile))
    assert [entry['name'] for entry in flattened] == ['Example', 'Top']
    example, top = flattened
    assert example['folder'] == 'Bookmark Bar / Sub'
    assert example['url'] == 'https://example.com'
    assert example['date_last_used'] is None
    assert top['folder'] == 'Bookmark Bar'
    assert top['date_added'] == DT_2022_11_05


def test_flatten_bookmarks_empty() -> None:
    assert flatten_bookmarks({}) == []


def test_find_bookmark_folder_root_by_key(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    _write_bookmarks(chrome_user_data)
    roots = read_bookmarks(profile)
    node = find_bookmark_folder(roots, 'other')
    assert node is not None
    assert node['name'] == 'Other Bookmarks'


def test_find_bookmark_folder_root_by_name(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    _write_bookmarks(chrome_user_data)
    roots = read_bookmarks(profile)
    node = find_bookmark_folder(roots, 'bookmark bar')
    assert node is not None
    assert node['name'] == 'Bookmark Bar'


def test_find_bookmark_folder_nested(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    _write_bookmarks(chrome_user_data)
    roots = read_bookmarks(profile)
    node = find_bookmark_folder(roots, '  Bookmark Bar  /  sub  ')
    assert node is not None
    assert node['name'] == 'Sub'


def test_find_bookmark_folder_leaf_is_not_a_folder(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    _write_bookmarks(chrome_user_data)
    roots = read_bookmarks(profile)
    assert find_bookmark_folder(roots, 'Bookmark Bar/Top') is None


def test_find_bookmark_folder_missing_root(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    _write_bookmarks(chrome_user_data)
    roots = read_bookmarks(profile)
    assert find_bookmark_folder(roots, 'Nonexistent') is None


def test_find_bookmark_folder_missing_nested_segment(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    _write_bookmarks(chrome_user_data)
    roots = read_bookmarks(profile)
    assert find_bookmark_folder(roots, 'Bookmark Bar/Nonexistent/Deeper') is None


def test_find_bookmark_folder_blank() -> None:
    assert find_bookmark_folder({}, '   ///   ') is None


def test_read_downloads_populated(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    _write_history_db(chrome_user_data)
    downloads = read_downloads(profile)
    assert [download['id'] for download in downloads] == [1, 2]
    first, second = downloads
    assert first['start_time'] == DT_2024_03_15
    assert first['state_name'] == 'COMPLETE'
    assert first['danger_type_name'] == 'NOT_DANGEROUS'
    assert first['interrupt_reason_name'] == 'NONE'
    assert first['url_chain'] == ['https://a.example/redirect', 'https://a.example/final']
    assert first['slices'] == [{'offset': 0, 'received_bytes': 100, 'finished': True}]
    assert second['state_name'] == 'UNKNOWN'
    assert second['danger_type_name'] == 'UNKNOWN'
    assert second['interrupt_reason_name'] == 'UNKNOWN'
    assert second['url_chain'] == ['https://b.example']
    assert second['slices'] == [{'offset': 0, 'received_bytes': 50, 'finished': False}]


def test_read_downloads_empty(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    _write_history_db(chrome_user_data, populate=False)
    assert read_downloads(profile) == []


def test_read_downloads_limit(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    _write_history_db(chrome_user_data)
    downloads = read_downloads(profile, limit=1)
    assert [download['id'] for download in downloads] == [1]


def test_read_downloads_state_filter(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    _write_history_db(chrome_user_data)
    downloads = read_downloads(profile, state=1)
    assert [download['id'] for download in downloads] == [1]


def test_read_history_populated(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    _write_history_db(chrome_user_data)
    rows = read_history(profile)
    assert [row['url_id'] for row in rows] == [1, 2]
    first, second = rows
    assert first['visit_time'] == DT_2024_03_15
    assert first['transition_core'] == 'TYPED'
    assert first['transition_qualifiers'] == ['FROM_ADDRESS_BAR', 'CHAIN_START']
    assert second['transition_core'] == 'UNKNOWN'
    assert second['transition_qualifiers'] == []


def test_read_history_empty(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    _write_history_db(chrome_user_data, populate=False)
    assert read_history(profile) == []


def test_read_history_no_limit(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    _write_history_db(chrome_user_data)
    assert len(read_history(profile, limit=0)) == 2


def test_read_history_search(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    _write_history_db(chrome_user_data)
    rows = read_history(profile, search='other')
    assert [row['url_id'] for row in rows] == [2]


def test_read_history_urls_populated(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    _write_history_db(chrome_user_data)
    rows = read_history_urls(profile)
    assert [row['id'] for row in rows] == [1, 2]
    assert rows[0]['last_visit_time'] == DT_2024_03_15
    assert rows[1]['last_visit_time'] == DT_2020_01_01


def test_read_history_urls_empty(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    _write_history_db(chrome_user_data, populate=False)
    assert read_history_urls(profile) == []


def test_read_history_urls_no_limit(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    _write_history_db(chrome_user_data)
    assert len(read_history_urls(profile, limit=0)) == 2


def test_read_history_urls_search(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    _write_history_db(chrome_user_data)
    rows = read_history_urls(profile, search='other.com')
    assert [row['id'] for row in rows] == [2]


def test_read_search_terms_populated(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    _write_history_db(chrome_user_data)
    rows = read_search_terms(profile)
    assert [row['keyword_id'] for row in rows] == [1, 2]
    assert rows[0]['last_visit_time'] == DT_2024_03_15


def test_read_search_terms_empty(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    _write_history_db(chrome_user_data, populate=False)
    assert read_search_terms(profile) == []


def test_read_search_terms_no_limit(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    _write_history_db(chrome_user_data)
    assert len(read_search_terms(profile, limit=0)) == 2


def test_read_search_terms_search(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    _write_history_db(chrome_user_data)
    rows = read_search_terms(profile, search='query')
    assert [row['keyword_id'] for row in rows] == [1]


def test_read_shortcuts_populated(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    _write_shortcuts_db(chrome_user_data)
    rows = read_shortcuts(profile)
    assert [row['text'] for row in rows] == ['ex', 'zz']
    assert rows[0]['transition_core'] == 'TYPED'
    assert rows[0]['transition_qualifiers'] == ['FROM_ADDRESS_BAR', 'CHAIN_START']
    assert rows[0]['last_access_time'] == DT_2024_03_15
    assert rows[1]['transition_core'] == 'UNKNOWN'
    assert rows[1]['transition_qualifiers'] == []


def test_read_shortcuts_empty(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    _write_shortcuts_db(chrome_user_data, populate=False)
    assert read_shortcuts(profile) == []


def test_read_top_sites_populated(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    _write_top_sites_db(chrome_user_data)
    rows = read_top_sites(profile)
    assert [row['url'] for row in rows] == ['https://a.com', 'https://b.com']


def test_read_top_sites_empty(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    _write_top_sites_db(chrome_user_data, populate=False)
    assert read_top_sites(profile) == []


def test_read_custom_dictionary_populated(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    chrome_user_data.write_text('Default', 'Custom Dictionary.txt', CUSTOM_DICTIONARY_TEXT)
    chrome_user_data.write_json('Default', 'Preferences', {'spellcheck': {'dictionary': 'en-US'}})
    data = read_custom_dictionary(profile)
    assert data['words'] == ['word1', 'word2']
    assert data['checksum'] == 'abc123'
    assert data['preferences'] == {'dictionary': 'en-US'}


def test_read_custom_dictionary_no_preferences_file(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    chrome_user_data.write_text('Default', 'Custom Dictionary.txt', CUSTOM_DICTIONARY_TEXT)
    (chrome_user_data.config_path / 'Default' / 'Preferences').unlink()
    data = read_custom_dictionary(profile)
    assert data['preferences'] is None


def test_read_custom_dictionary_malformed_preferences(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    chrome_user_data.write_text('Default', 'Custom Dictionary.txt', CUSTOM_DICTIONARY_TEXT)
    chrome_user_data.write_text('Default', 'Preferences', '{not valid json')
    data = read_custom_dictionary(profile)
    assert data['preferences'] is None


def test_read_custom_dictionary_missing_raises(chrome_user_data: FakeChromeUserData) -> None:
    profile = chrome_user_data.add_profile('Default')
    with pytest.raises(FileNotFoundError):
        read_custom_dictionary(profile)


def test_bookmarks_flat_table(runner: CliRunner, chrome_user_data: FakeChromeUserData,
                              monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('COLUMNS', '1000')
    chrome_user_data.add_profile('Default')
    _write_bookmarks(chrome_user_data)
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'bookmarks'])
    assert result.exit_code == 0, result.output
    assert 'Bookmarks in Default' in result.output
    assert 'Bookmark Bar / Sub' in result.output
    assert 'Example' in result.output
    assert '2023-06-01 08:00:00' in result.output


def test_bookmarks_json(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_bookmarks(chrome_user_data)
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'bookmarks', '--json'])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert [entry['name'] for entry in data] == ['Example', 'Top']
    assert data[0]['date_added'] == '2023-06-01T08:00:00+00:00'
    assert data[0]['date_last_used'] is None


def test_bookmarks_tree(runner: CliRunner, chrome_user_data: FakeChromeUserData,
                        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('COLUMNS', '1000')
    chrome_user_data.add_profile('Default')
    _write_bookmarks(chrome_user_data)
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'bookmarks', '--tree'])
    assert result.exit_code == 0, result.output
    assert 'Default' in result.output
    assert 'Bookmark Bar' in result.output
    assert 'Example (https://example.com)' in result.output


def test_bookmarks_folder_filter(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_bookmarks(chrome_user_data)
    result = runner.invoke(chrome_dump,
                           [*chrome_user_data.argv, 'bookmarks', 'Bookmark Bar/Sub', '--json'])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert [entry['name'] for entry in data] == ['Example']
    assert data[0]['folder'] == 'Sub'


def test_bookmarks_folder_not_found(runner: CliRunner,
                                    chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_bookmarks(chrome_user_data)
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'bookmarks', 'Nonexistent'])
    assert result.exit_code == 1
    assert "No bookmark folder matching 'Nonexistent'." in result.stderr


def test_list_downloads_table(runner: CliRunner, chrome_user_data: FakeChromeUserData,
                              monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('COLUMNS', '1000')
    chrome_user_data.add_profile('Default')
    _write_history_db(chrome_user_data)
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-downloads'])
    assert result.exit_code == 0, result.output
    assert 'Downloads in Default' in result.output
    assert '/home/user/Downloads/a.zip' in result.output
    assert 'COMPLETE' in result.output
    assert 'UNKNOWN' in result.output


def test_list_downloads_json(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_history_db(chrome_user_data)
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-downloads', '--json'])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert [download['id'] for download in data] == [1, 2]
    assert data[0]['state_name'] == 'COMPLETE'
    assert data[1]['danger_type_name'] == 'UNKNOWN'


def test_list_downloads_limit(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_history_db(chrome_user_data)
    result = runner.invoke(chrome_dump,
                           [*chrome_user_data.argv, 'list-downloads', '--limit', '1', '--json'])
    assert result.exit_code == 0, result.output
    assert [download['id'] for download in json.loads(result.output)] == [1]


def test_list_downloads_state_filter(runner: CliRunner,
                                     chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_history_db(chrome_user_data)
    result = runner.invoke(
        chrome_dump, [*chrome_user_data.argv, 'list-downloads', '--state', 'complete', '--json'])
    assert result.exit_code == 0, result.output
    assert [download['id'] for download in json.loads(result.output)] == [1]


def test_list_history_default_table(runner: CliRunner, chrome_user_data: FakeChromeUserData,
                                    monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('COLUMNS', '1000')
    chrome_user_data.add_profile('Default')
    _write_history_db(chrome_user_data)
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-history'])
    assert result.exit_code == 0, result.output
    assert 'History in Default' in result.output
    assert 'example.com' in result.output


def test_list_history_json(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_history_db(chrome_user_data)
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-history', '--json'])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert [row['url_id'] for row in data] == [1, 2]
    assert data[0]['transition_core'] == 'TYPED'
    assert data[0]['transition_qualifiers'] == ['FROM_ADDRESS_BAR', 'CHAIN_START']


def test_list_history_search(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_history_db(chrome_user_data)
    result = runner.invoke(chrome_dump,
                           [*chrome_user_data.argv, 'list-history', '--search', 'other', '--json'])
    assert result.exit_code == 0, result.output
    assert [row['url_id'] for row in json.loads(result.output)] == [2]


def test_list_history_search_terms(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_history_db(chrome_user_data)
    result = runner.invoke(chrome_dump,
                           [*chrome_user_data.argv, 'list-history', '--search-terms', '--json'])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert [row['keyword_id'] for row in data] == [1, 2]


def test_list_history_urls_only(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_history_db(chrome_user_data)
    result = runner.invoke(chrome_dump,
                           [*chrome_user_data.argv, 'list-history', '--urls-only', '--json'])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert [row['id'] for row in data] == [1, 2]


def test_list_shortcuts_table(runner: CliRunner, chrome_user_data: FakeChromeUserData,
                              monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('COLUMNS', '1000')
    chrome_user_data.add_profile('Default')
    _write_shortcuts_db(chrome_user_data)
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-shortcuts'])
    assert result.exit_code == 0, result.output
    assert 'Shortcuts in Default' in result.output
    assert 'example.com' in result.output


def test_list_shortcuts_json(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_shortcuts_db(chrome_user_data)
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-shortcuts', '--json'])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert [row['text'] for row in data] == ['ex', 'zz']
    assert data[0]['transition_core'] == 'TYPED'


def test_list_top_sites_table(runner: CliRunner, chrome_user_data: FakeChromeUserData,
                              monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('COLUMNS', '1000')
    chrome_user_data.add_profile('Default')
    _write_top_sites_db(chrome_user_data)
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-top-sites'])
    assert result.exit_code == 0, result.output
    assert 'Top sites in Default' in result.output
    assert 'a.com' in result.output


def test_list_top_sites_json(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    _write_top_sites_db(chrome_user_data)
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-top-sites', '--json'])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert [row['url'] for row in data] == ['https://a.com', 'https://b.com']


def test_spell_check_table_with_preferences(runner: CliRunner, chrome_user_data: FakeChromeUserData,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('COLUMNS', '1000')
    chrome_user_data.add_profile('Default')
    chrome_user_data.write_text('Default', 'Custom Dictionary.txt', CUSTOM_DICTIONARY_TEXT)
    chrome_user_data.write_json('Default', 'Preferences', {'spellcheck': {'dictionary': 'en-US'}})
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'spell-check'])
    assert result.exit_code == 0, result.output
    assert 'checksum' in result.output
    assert 'abc123' in result.output
    assert 'word1' in result.output
    assert 'Spell-check' in result.output
    assert 'preferences' in result.output
    assert 'en-US' in result.output


def test_spell_check_table_without_preferences(runner: CliRunner,
                                               chrome_user_data: FakeChromeUserData,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('COLUMNS', '1000')
    chrome_user_data.add_profile('Default')
    chrome_user_data.write_text('Default', 'Custom Dictionary.txt', CUSTOM_DICTIONARY_TEXT)
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'spell-check'])
    assert result.exit_code == 0, result.output
    assert 'Spell-check preferences' not in result.output


def test_spell_check_json(runner: CliRunner, chrome_user_data: FakeChromeUserData) -> None:
    chrome_user_data.add_profile('Default')
    chrome_user_data.write_text('Default', 'Custom Dictionary.txt', CUSTOM_DICTIONARY_TEXT)
    chrome_user_data.write_json('Default', 'Preferences', {'spellcheck': {'dictionary': 'en-US'}})
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'spell-check', '--json'])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        'checksum': 'abc123',
        'preferences': {
            'dictionary': 'en-US'
        },
        'words': ['word1', 'word2']
    }


@pytest.mark.parametrize(('args', 'message'), [
    (['bookmarks'], "No `Bookmarks` file for 'Default'"),
    (['list-downloads'], "No `History` database for 'Default'"),
    (['list-history'], "No `History` database for 'Default'"),
    (['list-shortcuts'], "No `Shortcuts` database for 'Default'"),
    (['list-top-sites'], "No `Top Sites` database for 'Default'"),
    (['spell-check'], "No `Custom Dictionary.txt` for 'Default'"),
])
def test_missing_file_aborts(runner: CliRunner, chrome_user_data: FakeChromeUserData,
                             args: list[str], message: str) -> None:
    chrome_user_data.add_profile('Default')
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, *args])
    assert result.exit_code == 1
    assert message in result.stderr
