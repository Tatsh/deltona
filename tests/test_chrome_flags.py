# cspell:ignore reloc, shstrtab
from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any
import json
import lzma
import struct
import sys

import pytest

from deltona.chrome.flag_binary import (
    FEATURE_ENTRY_STRIDE,
    FlagBinaryUnreadable,
    extract_flag_table,
    find_browser_binary,
)
from deltona.chrome.flags import (
    FlagTableUnavailable,
    cache_path,
    flag_source_url,
    flag_states,
    flag_table,
    flag_table_for,
    installed_version,
    parse_experiment,
    parse_flag_sources,
)
from deltona.commands.chrome import chrome_dump

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from click.testing import CliRunner
    from pytest_mock import MockerFixture

    from deltona.chrome.typing import ChromeChannel

    from .conftest import FakeChromeUserData

VERSION = '152.0.7977.42'
ABOUT_FLAGS = """// Copyright, mentioning kFeatureEntries so the marker search must not stop here.
/*
 * A block comment spanning several lines, so that a parser that dropped it
 * without keeping the newlines would report the wrong line numbers.
 */
#include "chrome/browser/about_flags.h"

constexpr char kNamedFlagSymbol[] = "named-by-symbol";

const FeatureEntry::FeatureParam kExampleParams[] = {{"param", "1"}};

const FeatureEntry::FeatureVariation kExampleVariations[] = {
    {flag_descriptions::kVariationLabel, kExampleParams, 1, nullptr},
    {"Literal Variation", kExampleParams, 1, nullptr},
    {},
    kSharedVariation,
};

const FeatureEntry::Choice kExampleChoices[] = {
    {flags_ui::kGenericExperimentChoiceDefault, "", ""},
    {"see https://example.com", "switch", "value"},
    {flag_descriptions::kChoiceLabel, "switch", "other"},
    {kUndefinedChoiceLabel, "switch", "third"},
};

const FeatureEntry kFeatureEntries[] = {
    {"literal-flag", flag_descriptions::kLiteralFlagName,
     flag_descriptions::kLiteralFlagDescription, kOsAll,
     FEATURE_VALUE_TYPE(features::kLiteralFlag)},
    {kNamedFlagSymbol, flag_descriptions::kSymbolFlagName,
     flag_descriptions::kSymbolFlagDescription, kOsLinux | kOsMac,
     FEATURE_WITH_PARAMS_VALUE_TYPE(features::kSymbolFlag, kExampleVariations, "TrialName")},
    {kUnresolvedSymbol, flag_descriptions::kLiteralFlagName,
     flag_descriptions::kLiteralFlagDescription, kOsAll,
     FEATURE_VALUE_TYPE(features::kUnresolved)},
    {"choice-flag", flag_descriptions::kChoiceFlagName,
     flag_descriptions::kChoiceFlagDescription,
     kOsWin /* Windows only */  // for the moment
     ,
     MULTI_VALUE_TYPE(kExampleChoices)},
    {"missing-choices-flag", flag_descriptions::kLiteralFlagName,
     flag_descriptions::kLiteralFlagDescription, kOsAll,
     MULTI_VALUE_TYPE(kMissingChoices)},
    {"empty-multi-flag", flag_descriptions::kLiteralFlagName,
     flag_descriptions::kLiteralFlagDescription, kOsAll, MULTI_VALUE_TYPE()},
    {"lonely-params-flag", flag_descriptions::kLiteralFlagName,
     flag_descriptions::kLiteralFlagDescription, kOsAll,
     FEATURE_WITH_PARAMS_VALUE_TYPE(features::kLonely)},
    {"single-value-flag", flag_descriptions::kLiteralFlagName,
     flag_descriptions::kLiteralFlagDescription, kOsAll,
     SINGLE_VALUE_TYPE("--single")},
    {"unterminated-flag", flag_descriptions::kLiteralFlagName,
     flag_descriptions::kLiteralFlagDescription, kOsAll,
     MULTI_VALUE_TYPE(kUnterminatedChoices)},
};

const FeatureEntry::Choice kUnterminatedChoices[] = {
    {"unterminated
"""
FLAG_DESCRIPTIONS = """#ifndef CHROME_BROWSER_FLAG_DESCRIPTIONS_H_
inline constexpr char kLiteralFlagName[] = "Literal Flag";
inline constexpr char kLiteralFlagDescription[] =
    "A description that "
    "wraps across two lines.";
inline constexpr char kSymbolFlagName[] = "Symbol Flag";
inline constexpr char kSymbolFlagDescription[] = "Named by a symbol.";
inline constexpr char kChoiceFlagName[] = "Choice Flag";
inline constexpr char kChoiceFlagDescription[] = "Chooses between values.";
inline constexpr char kVariationLabel[] = "With Params";
inline constexpr char kChoiceLabel[] = "Choice Label";
#endif
"""
FLAG_METADATA = """// This file records who owns each flag and when it expires.
[
  {
    "name": "literal-flag",
    "owners": ["someone@chromium.org"],
    "expiry_milestone": 200
  },
  {"missing_name": true},
  "not-an-object"
]
"""
NEVER_EXPIRE_LIST = """// Flags that are exempt from expiry.
["choice-flag"]
"""
SOURCES = {
    'about_flags.cc': ABOUT_FLAGS,
    'flag-metadata.json': FLAG_METADATA,
    'flag-never-expire-list.json': NEVER_EXPIRE_LIST,
    'flag_descriptions.h': FLAG_DESCRIPTIONS
}
EXPERIMENTS = [
    'choice-flag@2', 'empty-multi-flag@1', 'literal-flag@2', 'named-by-symbol', 'unknown-flag@7'
]
BINARY_TABLE: dict[str, dict[str, Any]] = {
    'literal-flag': {
        'description': 'Read out of the binary.',
        'expiry_milestone': None,
        'line': 0,
        'name': 'Literal Flag',
        'never_expires': False,
        'options': ['Default', 'Enabled', 'Disabled'],
        'os': 'kOsLinux',
        'owners': [],
        'type': 'FEATURE_VALUE_TYPE'
    }
}


def patch_sources(mocker: MockerFixture,
                  tmp_path: Path,
                  sources: Mapping[str, str] = SOURCES) -> Any:
    flag_table.cache_clear()
    mocker.patch('platformdirs.user_cache_dir', return_value=str(tmp_path))
    mocker.patch('deltona.chrome.flags.find_browser_binary', return_value=None)

    def get(url: str, **_kwargs: Any) -> Any:
        response = mocker.MagicMock()
        response.text = next(text for path, text in sources.items() if url.endswith(path))
        return response

    return mocker.patch('niquests.get', side_effect=get)


def patch_binary(mocker: MockerFixture, found: Path | None,
                 result: Mapping[str, Mapping[str, Any]] | BaseException) -> Any:
    mocker.patch('deltona.chrome.flags.find_browser_binary', return_value=found)
    if isinstance(result, BaseException):
        return mocker.patch('deltona.chrome.flags.extract_flag_table', side_effect=result)
    return mocker.patch('deltona.chrome.flags.extract_flag_table',
                        side_effect=lambda _: {
                            name: dict(entry)
                            for name, entry in result.items()
                        })


def write_cache(path: Path, payload: Mapping[str, Any] | bytes) -> None:
    path.parent.mkdir(exist_ok=True, parents=True)
    path.write_bytes(
        payload if isinstance(payload, bytes) else lzma.compress(json.dumps(payload).encode()))


def build_table() -> dict[str, dict[str, Any]]:
    return parse_flag_sources(ABOUT_FLAGS, FLAG_DESCRIPTIONS, FLAG_METADATA, NEVER_EXPIRE_LIST)


def test_installed_version(chrome_user_data: FakeChromeUserData) -> None:
    assert installed_version(chrome_user_data.config_path) is None
    chrome_user_data.write_version(VERSION)
    assert installed_version(chrome_user_data.config_path) == VERSION
    chrome_user_data.write_version('   ')
    assert installed_version(chrome_user_data.config_path) is None


def test_cache_path(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('platformdirs.user_cache_dir', return_value=str(tmp_path))
    assert cache_path(VERSION) == tmp_path / 'chrome-flags' / f'{VERSION}.json.xz'


def test_parse_flag_sources_names() -> None:
    assert sorted(build_table()) == [
        'choice-flag', 'empty-multi-flag', 'literal-flag', 'lonely-params-flag',
        'missing-choices-flag', 'named-by-symbol', 'single-value-flag', 'unterminated-flag'
    ]


def test_parse_flag_sources_descriptions() -> None:
    entry = build_table()['literal-flag']
    assert entry['name'] == 'Literal Flag'
    assert entry['description'] == 'A description that wraps across two lines.'
    assert entry['type'] == 'FEATURE_VALUE_TYPE'
    assert entry['owners'] == ['someone@chromium.org']
    assert entry['expiry_milestone'] == 200
    assert entry['never_expires'] is False


def test_parse_flag_sources_line_number() -> None:
    expected = ABOUT_FLAGS.count('\n', 0, ABOUT_FLAGS.index('"literal-flag"')) + 1
    assert build_table()['literal-flag']['line'] == expected


@pytest.mark.parametrize(('name', 'expected'), [('literal-flag', 'kOsAll'),
                                                ('named-by-symbol', 'kOsLinux | kOsMac'),
                                                ('choice-flag', 'kOsWin')])
def test_parse_flag_sources_os_ignores_comments(name: str, expected: str) -> None:
    assert build_table()[name]['os'] == expected


@pytest.mark.parametrize(('name', 'expected'), [
    ('literal-flag', ['Default', 'Enabled', 'Disabled']),
    ('named-by-symbol',
     ['Default', 'Enabled', 'Enabled With Params', 'Enabled Literal Variation', 'Disabled']),
    ('choice-flag', ['Default', 'see https://example.com', 'Choice Label', 'kUndefinedChoiceLabel'
                     ]),
    ('missing-choices-flag', []),
    ('empty-multi-flag', []),
    ('lonely-params-flag', []),
    ('single-value-flag', []),
    ('unterminated-flag', []),
])
def test_parse_flag_sources_options(name: str, expected: list[str]) -> None:
    assert build_table()[name]['options'] == expected


def test_parse_flag_sources_never_expires() -> None:
    assert build_table()['choice-flag']['never_expires'] is True


def test_parse_flag_sources_without_metadata() -> None:
    entry = parse_flag_sources(ABOUT_FLAGS, FLAG_DESCRIPTIONS)['literal-flag']
    assert entry['owners'] == []
    assert entry['expiry_milestone'] is None
    assert entry['never_expires'] is False


def test_parse_flag_sources_without_entry_table() -> None:
    with pytest.raises(ValueError, match='Could not find the feature entry table'):
        parse_flag_sources('int main() { return 0; }', FLAG_DESCRIPTIONS)


@pytest.mark.parametrize(('experiment', 'expected'), [('data-sharing@1', ('data-sharing', 1)),
                                                      ('data-sharing', ('data-sharing', None)),
                                                      ('data-sharing@x', ('data-sharing@x', None))])
def test_parse_experiment(experiment: str, expected: tuple[str, int | None]) -> None:
    assert parse_experiment(experiment) == expected


def test_flag_source_url() -> None:
    assert flag_source_url(VERSION, None) is None
    assert flag_source_url(VERSION, {'line': 0}) is None
    url = flag_source_url(VERSION, {'line': 42})
    assert url is not None
    assert url.endswith(f'refs/tags/{VERSION}:chrome/browser/about_flags.cc;l=42')


def test_flag_table_fetches_and_caches(mocker: MockerFixture, tmp_path: Path) -> None:
    get = patch_sources(mocker, tmp_path)
    assert 'literal-flag' in flag_table(VERSION)
    assert get.call_count == 4
    assert cache_path(VERSION).is_file()


def test_flag_table_reads_cache(mocker: MockerFixture, tmp_path: Path) -> None:
    patch_sources(mocker, tmp_path)
    flag_table(VERSION)
    get = patch_sources(mocker, tmp_path)
    assert 'literal-flag' in flag_table(VERSION)
    assert get.call_count == 0


def test_flag_table_reads_cache_without_source(mocker: MockerFixture, tmp_path: Path) -> None:
    get = patch_sources(mocker, tmp_path)
    write_cache(cache_path(VERSION), {'flags': {'cached-flag': {}}, 'format': 2})
    assert set(flag_table(VERSION)) == {'cached-flag'}
    assert get.call_count == 0


def test_flag_table_refresh(mocker: MockerFixture, tmp_path: Path) -> None:
    patch_sources(mocker, tmp_path)
    flag_table(VERSION)
    get = patch_sources(mocker, tmp_path)
    assert 'literal-flag' in flag_table(VERSION, refresh=True)
    assert get.call_count == 4


@pytest.mark.parametrize('payload', [
    {
        'flags': {},
        'format': 0
    },
    {
        'flags': {},
        'format': 2,
        'source': 'binary'
    },
    b'not compressed at all',
])
def test_flag_table_discards_unusable_cache(mocker: MockerFixture, tmp_path: Path,
                                            payload: Mapping[str, Any] | bytes) -> None:
    get = patch_sources(mocker, tmp_path)
    write_cache(cache_path(VERSION), payload)
    assert 'literal-flag' in flag_table(VERSION)
    assert get.call_count == 4


def test_flag_table_offline_without_cache(mocker: MockerFixture, tmp_path: Path) -> None:
    patch_sources(mocker, tmp_path)
    with pytest.raises(FlagTableUnavailable, match='fetching is disabled'):
        flag_table(VERSION, offline=True)


def test_flag_table_fetch_failure(mocker: MockerFixture, tmp_path: Path) -> None:
    flag_table.cache_clear()
    mocker.patch('platformdirs.user_cache_dir', return_value=str(tmp_path))
    mocker.patch('niquests.get', side_effect=RuntimeError('network down'))
    with pytest.raises(FlagTableUnavailable, match='network down'):
        flag_table(VERSION)


def test_flag_table_for_cache(mocker: MockerFixture, tmp_path: Path) -> None:
    patch_sources(mocker, tmp_path)
    flag_table(VERSION)
    get = patch_sources(mocker, tmp_path)
    table, used = flag_table_for(VERSION)
    assert 'literal-flag' in table
    assert used == 'cache (network)'
    assert get.call_count == 0


def test_flag_table_for_skips_cache_of_another_source(mocker: MockerFixture,
                                                      tmp_path: Path) -> None:
    patch_sources(mocker, tmp_path)
    flag_table(VERSION)
    patch_binary(mocker, tmp_path / 'chrome', BINARY_TABLE)
    table, used = flag_table_for(VERSION, offline=True, source='binary')
    assert table['literal-flag']['description'] == 'Read out of the binary.'
    assert used == 'binary'


def test_flag_table_for_binary_enriches_from_metadata(mocker: MockerFixture,
                                                      tmp_path: Path) -> None:
    patch_sources(mocker, tmp_path)
    patch_binary(mocker, tmp_path / 'chrome', BINARY_TABLE)
    table, used = flag_table_for(VERSION)
    assert used == 'binary'
    assert table['literal-flag']['owners'] == ['someone@chromium.org']
    assert table['literal-flag']['expiry_milestone'] == 200
    assert cache_path(VERSION).is_file()


def test_flag_table_for_binary_offline_skips_metadata(mocker: MockerFixture,
                                                      tmp_path: Path) -> None:
    get = patch_sources(mocker, tmp_path)
    patch_binary(mocker, tmp_path / 'chrome', BINARY_TABLE)
    table, _ = flag_table_for(VERSION, offline=True)
    assert table['literal-flag']['owners'] == []
    assert get.call_count == 0


def test_flag_table_for_binary_metadata_failure(mocker: MockerFixture, tmp_path: Path) -> None:
    flag_table.cache_clear()
    mocker.patch('platformdirs.user_cache_dir', return_value=str(tmp_path))
    mocker.patch('niquests.get', side_effect=RuntimeError('network down'))
    patch_binary(mocker, tmp_path / 'chrome', BINARY_TABLE)
    table, _ = flag_table_for(VERSION)
    assert table['literal-flag']['owners'] == []


def test_flag_table_for_explicit_binary(mocker: MockerFixture, tmp_path: Path) -> None:
    patch_sources(mocker, tmp_path)
    find = mocker.patch('deltona.chrome.flags.find_browser_binary', return_value=None)
    extract = mocker.patch('deltona.chrome.flags.extract_flag_table', return_value=BINARY_TABLE)
    table, used = flag_table_for(VERSION, binary=tmp_path / 'chrome', offline=True)
    assert used == 'binary'
    assert 'literal-flag' in table
    assert find.call_count == 0
    assert extract.call_args[0][0] == tmp_path / 'chrome'


def test_flag_table_for_unreadable_binary_falls_back(mocker: MockerFixture, tmp_path: Path) -> None:
    get = patch_sources(mocker, tmp_path)
    patch_binary(mocker, tmp_path / 'chrome', FlagBinaryUnreadable('not an image'))
    table, used = flag_table_for(VERSION)
    assert used == 'network'
    assert 'choice-flag' in table
    assert get.call_count == 4


def test_flag_table_for_unreadable_binary_when_required(mocker: MockerFixture,
                                                        tmp_path: Path) -> None:
    patch_sources(mocker, tmp_path)
    patch_binary(mocker, tmp_path / 'chrome', FlagBinaryUnreadable('not an image'))
    with pytest.raises(FlagTableUnavailable, match='not an image'):
        flag_table_for(VERSION, source='binary')


def test_flag_table_for_without_binary_when_required(mocker: MockerFixture, tmp_path: Path) -> None:
    patch_sources(mocker, tmp_path)
    with pytest.raises(FlagTableUnavailable, match='No browser binary'):
        flag_table_for(VERSION, channel='chromium', source='binary')


def test_flag_table_for_network_source_skips_binary(mocker: MockerFixture, tmp_path: Path) -> None:
    patch_sources(mocker, tmp_path)
    extract = mocker.patch('deltona.chrome.flags.extract_flag_table')
    table, used = flag_table_for(VERSION, source='network')
    assert used == 'network'
    assert 'literal-flag' in table
    assert extract.call_count == 0


def test_flag_states() -> None:
    table = build_table()
    states = {row['name']: row for row in flag_states(VERSION, EXPERIMENTS, table)}
    assert states['literal-flag']['state'] == 'Disabled'
    assert states['choice-flag']['state'] == 'Choice Label'
    assert states['named-by-symbol']['state'] == 'Enabled'
    assert states['named-by-symbol']['choice'] is None
    assert states['empty-multi-flag']['state'] == 'Enabled'
    assert states['unknown-flag']['state'] == 'Choice 7'
    assert states['unknown-flag']['known'] is False
    assert states['unknown-flag']['source'] is None
    assert states['literal-flag']['known'] is True
    assert states['literal-flag']['title'] == 'Literal Flag'
    assert states['choice-flag']['never_expires'] is True
    assert states['literal-flag']['owners'] == ['someone@chromium.org']


def test_flag_states_include_unchanged() -> None:
    table = build_table()
    states = {row['name']: row for row in flag_states(VERSION, ['literal-flag@2'], table)}
    assert set(states) == {'literal-flag'}
    everything = {
        row['name']: row
        for row in flag_states(VERSION, ['literal-flag@2'], table, include_unchanged=True)
    }
    assert set(everything) == set(table)
    assert everything['choice-flag']['state'] == 'Default'
    assert everything['choice-flag']['choice'] is None


def test_list_flags_without_version(runner: CliRunner,
                                    chrome_user_data: FakeChromeUserData) -> None:
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-flags'])
    assert result.exit_code == 1
    assert "No 'Last Version'" in result.stderr


def test_list_flags_offline_without_cache(runner: CliRunner, mocker: MockerFixture,
                                          chrome_user_data: FakeChromeUserData,
                                          tmp_path: Path) -> None:
    patch_sources(mocker, tmp_path)
    chrome_user_data.write_version(VERSION)
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-flags', '--offline'])
    assert result.exit_code == 1
    assert 'fetching is disabled' in result.stderr


def test_list_flags_json(runner: CliRunner, mocker: MockerFixture,
                         chrome_user_data: FakeChromeUserData, tmp_path: Path) -> None:
    patch_sources(mocker, tmp_path)
    chrome_user_data.write_version(VERSION)
    chrome_user_data.local_state['browser']['enabled_labs_experiments'] = EXPERIMENTS
    chrome_user_data.write_local_state()
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-flags', '-j'])
    assert result.exit_code == 0
    rows = {row['name']: row for row in json.loads(result.output)}
    assert set(rows) == {
        'choice-flag', 'empty-multi-flag', 'literal-flag', 'named-by-symbol', 'unknown-flag'
    }
    assert rows['literal-flag']['state'] == 'Disabled'


def test_list_flags_table(runner: CliRunner, mocker: MockerFixture,
                          chrome_user_data: FakeChromeUserData, tmp_path: Path,
                          monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('COLUMNS', '400')
    patch_sources(mocker, tmp_path)
    chrome_user_data.write_version(VERSION)
    chrome_user_data.local_state['browser']['enabled_labs_experiments'] = ['literal-flag@2']
    chrome_user_data.write_local_state()
    result = runner.invoke(chrome_dump, [*chrome_user_data.argv, 'list-flags'])
    assert result.exit_code == 0
    assert 'literal-flag' in result.output
    assert VERSION in result.output
    assert 'Flag definitions from network.' in result.stderr


def test_list_flags_binary_option(runner: CliRunner, mocker: MockerFixture,
                                  chrome_user_data: FakeChromeUserData, tmp_path: Path) -> None:
    patch_sources(mocker, tmp_path)
    extract = mocker.patch('deltona.chrome.flags.extract_flag_table', return_value=BINARY_TABLE)
    binary = tmp_path / 'chrome'
    binary.write_bytes(b'\x7fELF')
    chrome_user_data.write_version(VERSION)
    result = runner.invoke(chrome_dump, [
        *chrome_user_data.argv, 'list-flags', '--binary',
        str(binary), '--source', 'binary', '--offline', '--all', '-j'
    ])
    assert result.exit_code == 0
    assert [row['name'] for row in json.loads(result.output)] == ['literal-flag']
    assert extract.call_args[0][0] == binary


def test_list_flags_version_override(runner: CliRunner, mocker: MockerFixture,
                                     chrome_user_data: FakeChromeUserData, tmp_path: Path) -> None:
    patch_sources(mocker, tmp_path)
    result = runner.invoke(chrome_dump,
                           [*chrome_user_data.argv, 'list-flags', '--version', '1.2.3.4', '-j'])
    assert result.exit_code == 0
    assert json.loads(result.output) == []
    assert cache_path('1.2.3.4').is_file()


def test_list_flags_refresh_and_all(runner: CliRunner, mocker: MockerFixture,
                                    chrome_user_data: FakeChromeUserData, tmp_path: Path) -> None:
    patch_sources(mocker, tmp_path)
    chrome_user_data.write_version(VERSION)
    result = runner.invoke(chrome_dump,
                           [*chrome_user_data.argv, 'list-flags', '--refresh', '--all', '-j'])
    assert result.exit_code == 0
    assert len(json.loads(result.output)) == len(build_table())


@pytest.mark.parametrize(('state', 'expected'), [
    ('changed', {'choice-flag', 'literal-flag'}),
    ('default', {
        'empty-multi-flag', 'lonely-params-flag', 'missing-choices-flag', 'named-by-symbol',
        'single-value-flag', 'unterminated-flag'
    }),
    ('disabled', {'literal-flag'}),
    ('enabled', set()),
])
def test_list_flags_state_filter(runner: CliRunner, mocker: MockerFixture,
                                 chrome_user_data: FakeChromeUserData, tmp_path: Path, state: str,
                                 expected: set[str]) -> None:
    patch_sources(mocker, tmp_path)
    chrome_user_data.write_version(VERSION)
    chrome_user_data.local_state['browser']['enabled_labs_experiments'] = [
        'choice-flag@2', 'literal-flag@2'
    ]
    chrome_user_data.write_local_state()
    result = runner.invoke(chrome_dump,
                           [*chrome_user_data.argv, 'list-flags', '--all', '--state', state, '-j'])
    assert result.exit_code == 0
    assert {row['name'] for row in json.loads(result.output)} == expected


@pytest.mark.parametrize(('search', 'expected'), [('LITERAL-FLAG', {'literal-flag'}),
                                                  ('choice flag', {'choice-flag'}),
                                                  ('named by a symbol', {'named-by-symbol'})])
def test_list_flags_search(runner: CliRunner, mocker: MockerFixture,
                           chrome_user_data: FakeChromeUserData, tmp_path: Path, search: str,
                           expected: set[str]) -> None:
    patch_sources(mocker, tmp_path)
    chrome_user_data.write_version(VERSION)
    result = runner.invoke(chrome_dump,
                           [*chrome_user_data.argv, 'list-flags', '--all', '-s', search, '-j'])
    assert result.exit_code == 0
    assert {row['name'] for row in json.loads(result.output)} == expected


ENTRY_COUNT = 61
ENTRY_NAMES = ('browsing-history-M3', *(f'test-flag-{index:03d}'
                                        for index in range(1, 60)), 'trailing-window-M4')
ENTRY_TITLE = 'Visible name'
ENTRY_DESCRIPTION = 'A flag description that is long enough.'
# The two names carrying an uppercase milestone suffix fail the seed regular expression, so the run
# detector only finds them by extending the run it seeded from the plain names between them.
BINARY_STRINGS: tuple[bytes, ...] = (*(name.encode() for name in ENTRY_NAMES), ENTRY_TITLE.encode(),
                                     ENTRY_DESCRIPTION.encode(), b'', b'has space here', b'x',
                                     b'short', b'\x01control', b'\xff\xfe invalid', b'a' * 130,
                                     b'T' * 320, b'decoy-name', b'run-a-flag-one',
                                     b'run-a-flag-two', b'run-c-flag-one', b'run-c-flag-two')
TITLE_STRING = ENTRY_COUNT
DESCRIPTION_STRING = ENTRY_COUNT + 1
EMPTY_STRING = ENTRY_COUNT + 2
UNMAPPED_STRING = -1
DECOYS = ((ENTRY_COUNT + 3, TITLE_STRING, DESCRIPTION_STRING), (ENTRY_COUNT + 4, TITLE_STRING,
                                                                DESCRIPTION_STRING),
          (ENTRY_COUNT + 8, TITLE_STRING, DESCRIPTION_STRING), (EMPTY_STRING, TITLE_STRING,
                                                                DESCRIPTION_STRING),
          (ENTRY_COUNT + 6, TITLE_STRING, DESCRIPTION_STRING), (ENTRY_COUNT + 7, TITLE_STRING,
                                                                DESCRIPTION_STRING),
          (UNMAPPED_STRING, TITLE_STRING, DESCRIPTION_STRING), (ENTRY_COUNT + 10, EMPTY_STRING,
                                                                DESCRIPTION_STRING),
          (ENTRY_COUNT + 10, ENTRY_COUNT + 9, DESCRIPTION_STRING), (ENTRY_COUNT + 10, TITLE_STRING,
                                                                    ENTRY_COUNT + 5))
RUN_A_STRING = ENTRY_COUNT + 11
RUN_C_STRING = ENTRY_COUNT + 13
DEFAULT_ENTRY_WORD = 0x0004001F
ENTRY_WORDS = {1: 0x0000000F, 2: 0x00000003, 3: 0x0063001F, ENTRY_COUNT - 1: 0}
DATA_SIZE = 0x6000
RUN_A_OFFSET = 0x0000
MAIN_OFFSET = 0x1000
RUN_C_OFFSET = 0x3000
DECOY_OFFSET = 0x4000
DECOY_STRIDE = 256
UNALIGNED_OFFSET = 0x4A04
ZERO_SLOT_OFFSET = 0x4A80
BIND_OFFSET = 0x5000
STRING_VA = 0x1000
DATA_VA = 0x200000
UNMAPPED_VA = 0x900000
# The last entry's platform word deliberately falls past the declared end of the section holding
# it, so that the word reader has to report the address as unmapped.
ELF_DECLARED_DATA_SIZE = MAIN_OFFSET + (ENTRY_COUNT - 1) * FEATURE_ENTRY_STRIDE + 24
ELF_SECTION_SIZE = 64
R_X86_64_RELATIVE = 8
R_X86_64_GLOB_DAT = 6
SHT_PROGBITS = 1
SHT_RELA = 4
SHT_STRING_TABLE = 3
PE_IMAGE_BASE = 0x140000000
PE_HEADER_OFFSET = 0x80
PE_OPTIONAL_SIZE = 240
PE_RDATA_RVA = 0x1000
PE_DATA_RVA = 0x10000
PE_RELOCATION_RVA = 0x20000
PE_DIR64_ENTRY = 0xA000
MACHO_STRINGS_OFFSET = 0x1000
CHAINED_PAGE_SIZE = 0x1000
CHAINED_BIND_PAGE = 5


def nul_terminated(values: Sequence[bytes]) -> tuple[bytes, tuple[int, ...]]:
    blob = bytearray()
    offsets = []
    for value in values:
        offsets.append(len(blob))
        blob.extend(value)
        blob.append(0)
    return bytes(blob), tuple(offsets)


STRING_BLOB, STRING_OFFSETS = nul_terminated(BINARY_STRINGS)


def slot_plan() -> dict[int, int]:
    plan: dict[int, int] = {}
    for index in range(ENTRY_COUNT):
        base = MAIN_OFFSET + index * FEATURE_ENTRY_STRIDE
        plan[base] = index
        plan[base + 8] = TITLE_STRING
        plan[base + 16] = DESCRIPTION_STRING
    for offset, first in ((RUN_A_OFFSET, RUN_A_STRING), (RUN_C_OFFSET, RUN_C_STRING)):
        for position in range(2):
            base = offset + position * FEATURE_ENTRY_STRIDE
            plan[base] = first + position
            plan[base + 8] = TITLE_STRING
            plan[base + 16] = DESCRIPTION_STRING
    for index, (name, title, description) in enumerate(DECOYS):
        base = DECOY_OFFSET + index * DECOY_STRIDE
        plan[base] = name
        plan[base + 8] = title
        plan[base + 16] = description
    return plan


def slot_targets(string_base: int, unmapped: int) -> dict[int, int]:
    return {
        offset: (unmapped if index == UNMAPPED_STRING else string_base + STRING_OFFSETS[index])
        for offset, index in slot_plan().items()
    }


def data_blob(pointers: Mapping[int, int] | None = None, bind: int | None = None) -> bytes:
    blob = bytearray(DATA_SIZE)
    for index in range(ENTRY_COUNT):
        struct.pack_into('<I', blob, MAIN_OFFSET + index * FEATURE_ENTRY_STRIDE + 24,
                         ENTRY_WORDS.get(index, DEFAULT_ENTRY_WORD))
    for offset, value in (pointers or {}).items():
        struct.pack_into('<Q', blob, offset, value)
    if bind is not None:
        struct.pack_into('<Q', blob, BIND_OFFSET, bind)
    return bytes(blob)


def elf_header(sections_offset: int, count: int, name_index: int) -> bytearray:
    header = bytearray(ELF_SECTION_SIZE)
    header[:16] = b'\x7fELF\x02\x01\x01' + bytes(9)
    struct.pack_into('<HHI', header, 16, 3, 62, 1)
    struct.pack_into('<Q', header, 0x28, sections_offset)
    struct.pack_into('<HHH', header, 0x3A, ELF_SECTION_SIZE, count, name_index)
    return header


def build_elf(*, relocations: bool = True) -> bytes:
    blob = data_blob()
    targets = slot_targets(STRING_VA, UNMAPPED_VA)
    strings_offset = 0x1000
    data_offset = strings_offset + len(STRING_BLOB)
    data_offset += -data_offset % 8
    relocation_offset = data_offset + len(blob)
    relocation_blob = bytearray()
    if relocations:
        for offset, target in sorted(targets.items()):
            relocation_blob += struct.pack('<QQq', DATA_VA + offset, R_X86_64_RELATIVE, target)
        decoy = STRING_VA + STRING_OFFSETS[ENTRY_COUNT + 10]
        relocation_blob += struct.pack('<QQq', DATA_VA + UNALIGNED_OFFSET, R_X86_64_RELATIVE, decoy)
        relocation_blob += struct.pack('<QQq', DATA_VA + ZERO_SLOT_OFFSET, R_X86_64_GLOB_DAT, decoy)
    names_offset = relocation_offset + len(relocation_blob)
    name_blob, name_offsets = nul_terminated(
        (b'', b'.rodata', b'.data.rel.ro', b'.rela.dyn', b'.shstrtab'))
    sections_offset = names_offset + len(name_blob)
    sections = ((name_offsets[0], 0, 0, 0, 0), (name_offsets[1], SHT_PROGBITS, STRING_VA,
                                                strings_offset, len(STRING_BLOB)),
                (name_offsets[2], SHT_PROGBITS, DATA_VA, data_offset, ELF_DECLARED_DATA_SIZE),
                *(((name_offsets[3], SHT_RELA, 0, relocation_offset,
                    len(relocation_blob)),) if relocations else
                  ()), (name_offsets[4], SHT_STRING_TABLE, 0, names_offset, len(name_blob)))
    image = bytearray(sections_offset + len(sections) * ELF_SECTION_SIZE)
    image[:ELF_SECTION_SIZE] = elf_header(sections_offset, len(sections), len(sections) - 1)
    image[strings_offset:strings_offset + len(STRING_BLOB)] = STRING_BLOB
    image[data_offset:data_offset + len(blob)] = blob
    image[relocation_offset:relocation_offset + len(relocation_blob)] = relocation_blob
    image[names_offset:names_offset + len(name_blob)] = name_blob
    for index, (name, kind, address, offset, size) in enumerate(sections):
        struct.pack_into('<IIQQQQ', image, sections_offset + index * ELF_SECTION_SIZE, name, kind,
                         0, address, offset, size)
    return bytes(image)


def build_elf_without_name_terminator() -> bytes:
    sections_offset = ELF_SECTION_SIZE
    names_offset = sections_offset + 2 * ELF_SECTION_SIZE
    image = bytearray(names_offset)
    image[:ELF_SECTION_SIZE] = elf_header(sections_offset, 2, 1)
    struct.pack_into('<IIQQQQ', image, sections_offset + ELF_SECTION_SIZE, 1, SHT_STRING_TABLE, 0,
                     0, names_offset, 4)
    return bytes(image) + b'\0xyz'


def relocation_blocks(addresses: Sequence[int]) -> bytes:
    blocks = bytearray()
    for page in sorted({rva & ~0xFFF for rva in addresses}):
        entries = [PE_DIR64_ENTRY | (rva & 0xFFF) for rva in addresses if rva & ~0xFFF == page]
        entries.append(0)
        blocks += struct.pack('<II', page, 8 + 2 * len(entries))
        blocks += struct.pack(f'<{len(entries)}H', *entries)
    blocks += struct.pack('<IIH', UNMAPPED_VA, 10, PE_DIR64_ENTRY)
    blocks += struct.pack('<II', 0, 0)
    return bytes(blocks)


def build_pe(*, magic: int = 0x20B, relocation_rva: int = PE_RELOCATION_RVA) -> bytes:
    targets = slot_targets(PE_IMAGE_BASE + PE_RDATA_RVA, PE_IMAGE_BASE + UNMAPPED_VA)
    blob = data_blob(targets)
    blocks = relocation_blocks([PE_DATA_RVA + offset
                                for offset in sorted(targets)] + [PE_DATA_RVA + ZERO_SLOT_OFFSET])
    strings_offset = 0x1000
    strings_size = len(STRING_BLOB) + -len(STRING_BLOB) % 0x200
    data_offset = strings_offset + strings_size
    blocks_offset = data_offset + DATA_SIZE
    sections = ((b'.rdata', 0, PE_RDATA_RVA, strings_size,
                 strings_offset), (b'.data', DATA_SIZE, PE_DATA_RVA, DATA_SIZE, data_offset),
                (b'.reloc', len(blocks), PE_RELOCATION_RVA, len(blocks), blocks_offset))
    image = bytearray(blocks_offset + len(blocks))
    image[:2] = b'MZ'
    struct.pack_into('<I', image, 0x3C, PE_HEADER_OFFSET)
    image[PE_HEADER_OFFSET:PE_HEADER_OFFSET + 4] = b'PE\0\0'
    struct.pack_into('<HH', image, PE_HEADER_OFFSET + 4, 0x8664, len(sections))
    struct.pack_into('<H', image, PE_HEADER_OFFSET + 20, PE_OPTIONAL_SIZE)
    optional = PE_HEADER_OFFSET + 24
    struct.pack_into('<H', image, optional, magic)
    struct.pack_into('<Q', image, optional + 24, PE_IMAGE_BASE)
    struct.pack_into('<II', image, optional + 152, relocation_rva, len(blocks))
    for index, (name, virtual_size, rva, raw_size, raw_offset) in enumerate(sections):
        start = optional + PE_OPTIONAL_SIZE + index * 40
        image[start:start + len(name)] = name
        struct.pack_into('<IIII', image, start + 8, virtual_size, rva, raw_size, raw_offset)
    image[strings_offset:strings_offset + len(STRING_BLOB)] = STRING_BLOB
    image[data_offset:data_offset + len(blob)] = blob
    image[blocks_offset:blocks_offset + len(blocks)] = blocks
    return bytes(image)


def encode_link(pointer_format: int, target: int | None, step: int) -> int:
    if pointer_format in {2, 6}:
        raw = (step // 4) << 51
        return raw | (1 << 63) if target is None else raw | target
    raw = (step // 8) << 51
    return raw | (1 << 62) if target is None else raw | target


def chain_words(pointer_format: int, targets: Mapping[int, int]) -> tuple[dict[int, int], int]:
    offsets = sorted(targets)
    words = {
        offset:
            encode_link(pointer_format, targets[offset],
                        offsets[position + 1] - offset if position + 1 < len(offsets) else 0)
        for position, offset in enumerate(offsets)
    }
    return words, encode_link(pointer_format, None, 16380 if pointer_format in {2, 6} else 16376)


def build_fixups(pointer_format: int, segment_size: int) -> bytes:
    pages = -(-segment_size // CHAINED_PAGE_SIZE)
    starts = [0xFFFF] * pages
    starts[0] = 0
    starts[CHAINED_BIND_PAGE] = 0
    main = struct.pack('<IHHQIH', 22 + 2 * pages, CHAINED_PAGE_SIZE, pointer_format, DATA_VA, 0,
                       pages) + struct.pack(f'<{pages}H', *starts)
    unknown_segment = struct.pack('<IHHQIH', 22, CHAINED_PAGE_SIZE, pointer_format, 0xDEAD000, 0, 0)
    no_page_size = struct.pack('<IHHQIH', 22, 0, pointer_format, DATA_VA, 0, 0)
    offsets = (0, 24, 24 + len(main), 24 + len(main) + len(unknown_segment), 0)
    body = struct.pack('<I', len(offsets)) + struct.pack(f'<{len(offsets)}I', *offsets)
    return (struct.pack('<7I', 0, 32, 0, 0, 0, 0, 0) + bytes(4) + body + main + unknown_segment +
            no_page_size)


def segment_command(name: bytes, virtual_address: int, file_offset: int, size: int,
                    section: tuple[bytes, int, int, int]) -> bytes:
    command = bytearray(72 + 80)
    struct.pack_into('<II', command, 0, 0x19, len(command))
    command[8:8 + len(name)] = name
    struct.pack_into('<QQQQ', command, 24, virtual_address, size, file_offset, size)
    struct.pack_into('<I', command, 64, 1)
    section_name, address, offset, section_size = section
    command[72:72 + len(section_name)] = section_name
    command[88:88 + len(name)] = name
    struct.pack_into('<QQ', command, 104, address, section_size)
    struct.pack_into('<I', command, 120, offset)
    return bytes(command)


def build_macho(pointer_format: int | None,
                *,
                text: bool = True,
                bad_command: bool = False) -> bytes:
    targets = slot_targets(STRING_VA, UNMAPPED_VA)
    data_offset = MACHO_STRINGS_OFFSET + len(STRING_BLOB)
    data_offset += -data_offset % 16
    fixups_offset = data_offset + DATA_SIZE
    if pointer_format is None:
        blob = data_blob(targets)
        fixups = b''
    else:
        words, bind = chain_words(pointer_format, targets)
        blob = data_blob(words, bind)
        fixups = build_fixups(pointer_format, DATA_SIZE)
    commands = bytearray()
    count = 1
    if bad_command:
        commands += struct.pack('<II', 0, 4)
        count += 1
    if text:
        commands += segment_command(
            b'__TEXT', 0, 0, MACHO_STRINGS_OFFSET + len(STRING_BLOB),
            (b'__cstring', STRING_VA, MACHO_STRINGS_OFFSET, len(STRING_BLOB)))
        count += 1
    commands += segment_command(b'__DATA', DATA_VA, data_offset, DATA_SIZE,
                                (b'__data', DATA_VA, data_offset, DATA_SIZE))
    commands += struct.pack('<II', 0x1B, 24) + bytes(16)
    count += 1
    if fixups:
        commands += struct.pack('<IIII', 0x80000034, 16, fixups_offset, len(fixups))
        count += 1
    image = bytearray(fixups_offset + len(fixups))
    struct.pack_into('<7I', image, 0, 0xFEEDFACF, 0x1000007, 3, 6, count, len(commands), 0)
    image[32:32 + len(commands)] = commands
    image[MACHO_STRINGS_OFFSET:MACHO_STRINGS_OFFSET + len(STRING_BLOB)] = STRING_BLOB
    image[data_offset:data_offset + len(blob)] = blob
    image[fixups_offset:fixups_offset + len(fixups)] = fixups
    return bytes(image)


def build_fat(slices: Sequence[bytes], *, wide: bool = False) -> bytes:
    layout, stride = ('>IIQQQ', 32) if wide else ('>IIIII', 20)
    magic = b'\xca\xfe\xba\xbf' if wide else b'\xca\xfe\xba\xbe'
    header = bytearray(magic + struct.pack('>I', len(slices)))
    header += bytes(len(slices) * stride)
    image = bytearray(header)
    for index, payload in enumerate(slices):
        image += bytes(-len(image) % 0x4000)
        struct.pack_into(layout, image, 8 + index * stride, 0x1000007, 3, len(image), len(payload),
                         14)
        image += payload
    return bytes(image)


IMAGE_BUILDERS: dict[str, Callable[[], bytes]] = {
    'elf': build_elf,
    'macho-absolute': partial(build_macho, 2),
    'macho-arm64e': partial(build_macho, 9),
    'macho-offset': partial(build_macho, 6),
    'macho-plain': partial(build_macho, None),
    'pe': build_pe
}
BROKEN_IMAGE_BUILDERS: dict[str, Callable[[], bytes]] = {
    'elf-truncated-header': lambda: b'\x7fELF' + bytes(12),
    'elf-truncated-names': build_elf_without_name_terminator,
    'elf-without-relocations': partial(build_elf, relocations=False),
    'macho-bad-command': partial(build_macho, 6, bad_command=True),
    'macho-unknown-format': partial(build_macho, 3),
    'macho-without-text': partial(build_macho, 6, text=False),
    'pe-not-32-plus': partial(build_pe, magic=0x10B),
    'pe-without-relocations': partial(build_pe, relocation_rva=0)
}


def write_binary(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


@pytest.mark.parametrize('kind', sorted(IMAGE_BUILDERS))
def test_extract_flag_table(kind: str, tmp_path: Path) -> None:
    table = extract_flag_table(write_binary(tmp_path, kind, IMAGE_BUILDERS[kind]()))
    assert set(table) == set(ENTRY_NAMES)
    assert table['test-flag-001']['name'] == ENTRY_TITLE
    assert table['test-flag-001']['description'] == ENTRY_DESCRIPTION
    assert table['test-flag-001']['options'] == []
    assert table['test-flag-001']['owners'] == []
    assert table['test-flag-001']['line'] is None
    assert table['test-flag-001']['expiry_milestone'] is None
    assert table['test-flag-001']['never_expires'] is False


@pytest.mark.parametrize(('name', 'os_field', 'entry_type'),
                         [('browsing-history-M3', 'kOsAll', 'FEATURE_VALUE_TYPE'),
                          ('test-flag-001', 'kOsDesktop', 'SINGLE_VALUE_TYPE'),
                          ('test-flag-002', 'kOsMac | kOsWin', 'SINGLE_VALUE_TYPE'),
                          ('test-flag-003', 'kOsAll', '99'),
                          ('trailing-window-M4', '', 'SINGLE_VALUE_TYPE')])
@pytest.mark.parametrize('kind', sorted(IMAGE_BUILDERS))
def test_extract_flag_table_fields(kind: str, name: str, os_field: str, entry_type: str,
                                   tmp_path: Path) -> None:
    entry = extract_flag_table(write_binary(tmp_path, kind, IMAGE_BUILDERS[kind]()))[name]
    assert entry['os'] == os_field
    assert entry['type'] == entry_type


@pytest.mark.parametrize('wide', [False, True])
def test_extract_flag_table_universal(tmp_path: Path, *, wide: bool) -> None:
    image = build_fat((b'\xce\xfa\xed\xfe' + bytes(0xFC), build_macho(6)), wide=wide)
    assert set(extract_flag_table(write_binary(tmp_path, 'framework', image))) == set(ENTRY_NAMES)


@pytest.mark.parametrize('kind', sorted(BROKEN_IMAGE_BUILDERS))
def test_extract_flag_table_without_a_table(kind: str, tmp_path: Path) -> None:
    path = write_binary(tmp_path, kind, BROKEN_IMAGE_BUILDERS[kind]())
    with pytest.raises(FlagBinaryUnreadable, match='No flag table found'):
        extract_flag_table(path)


def test_extract_flag_table_unknown_container(tmp_path: Path) -> None:
    path = write_binary(tmp_path, 'notes.txt', b'just some text, at length.')
    with pytest.raises(FlagBinaryUnreadable, match='not an ELF, Mach-O, or PE image'):
        extract_flag_table(path)


@pytest.mark.parametrize('data', [None, b''])
def test_extract_flag_table_unreadable(tmp_path: Path, data: bytes | None) -> None:
    path = tmp_path / 'chrome'
    if data is not None:
        path.write_bytes(data)
    with pytest.raises(FlagBinaryUnreadable, match='Could not read'):
        extract_flag_table(path)


@pytest.mark.parametrize('channel', ['beta', 'chromium', 'stable'])
@pytest.mark.parametrize('platform', ['darwin', 'linux'])
def test_find_browser_binary_without_candidates(platform: str, channel: ChromeChannel,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, 'platform', platform)
    monkeypatch.setattr(Path, 'is_file', lambda _: False)
    assert find_browser_binary(channel) is None


def test_find_browser_binary_on_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.delenv('PROGRAMFILES', raising=False)
    monkeypatch.delenv('LOCALAPPDATA', raising=False)
    monkeypatch.setenv('PROGRAMFILES(X86)', str(tmp_path))
    application = tmp_path / 'Google' / 'Chrome' / 'Application'
    (application / '1.2.3.4').mkdir(parents=True)
    (application / '10.0.0.0').mkdir()
    (application / 'not-a-version').touch()
    write_binary(application / '1.2.3.4', 'chrome.dll', b'not an image at all')
    newest = write_binary(application / '10.0.0.0', 'chrome.dll', b'MZ' + bytes(60))
    assert find_browser_binary() == newest


def test_find_browser_binary_with_an_unreadable_candidate(tmp_path: Path,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, 'platform', 'cygwin')
    monkeypatch.delenv('PROGRAMFILES(X86)', raising=False)
    monkeypatch.delenv('LOCALAPPDATA', raising=False)
    monkeypatch.setenv('PROGRAMFILES', str(tmp_path))
    application = tmp_path / 'Google' / 'Chrome' / 'Application'
    (application / '1.0.0.0').mkdir(parents=True)
    write_binary(application / '1.0.0.0', 'chrome.dll', b'MZ' + bytes(60))
    monkeypatch.setattr(Path, 'open', _refuse_to_open)
    assert find_browser_binary() is None


def _refuse_to_open(*_args: Any, **_kwargs: Any) -> Any:
    msg = 'Permission denied.'
    raise OSError(msg)


def test_list_flags_reads_a_real_binary(runner: CliRunner, mocker: MockerFixture,
                                        chrome_user_data: FakeChromeUserData,
                                        tmp_path: Path) -> None:
    flag_table.cache_clear()
    mocker.patch('platformdirs.user_cache_dir', return_value=str(tmp_path))
    binary = write_binary(tmp_path, 'chrome', build_elf())
    chrome_user_data.write_version(VERSION)
    chrome_user_data.local_state['browser']['enabled_labs_experiments'] = ['test-flag-002@1']
    chrome_user_data.write_local_state()
    result = runner.invoke(chrome_dump, [
        *chrome_user_data.argv, 'list-flags', '--binary',
        str(binary), '--source', 'binary', '--offline', '-j'
    ])
    assert result.exit_code == 0
    rows = json.loads(result.output)
    assert [row['name'] for row in rows] == ['test-flag-002']
    assert rows[0]['title'] == ENTRY_TITLE
    assert rows[0]['os'] == 'kOsMac | kOsWin'
    assert rows[0]['state'] == 'Enabled'


def test_list_flags_with_a_binary_that_is_not_a_browser(runner: CliRunner, mocker: MockerFixture,
                                                        chrome_user_data: FakeChromeUserData,
                                                        tmp_path: Path) -> None:
    flag_table.cache_clear()
    mocker.patch('platformdirs.user_cache_dir', return_value=str(tmp_path))
    binary = write_binary(tmp_path, 'chrome', b'just some text, at length.')
    chrome_user_data.write_version(VERSION)
    result = runner.invoke(chrome_dump, [
        *chrome_user_data.argv, 'list-flags', '--binary',
        str(binary), '--source', 'binary', '--offline'
    ])
    assert result.exit_code == 1
    assert 'not an ELF, Mach-O, or PE image' in result.stderr
