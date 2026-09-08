"""Tests for :py:mod:`deltona.chrome.preferences`."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from deltona.chrome.preferences import (
    SETTINGS,
    SettingSpec,
    flatten_preferences,
    summarise_preferences,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


def _row(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    return next(row for row in rows if row['key'] == key)


def test_settings_have_unique_keys() -> None:
    keys = [spec.key for spec in SETTINGS]
    assert len(keys) == len(set(keys))


def test_summarise_reports_stored_value() -> None:
    rows = summarise_preferences({'enable_do_not_track': True})
    assert _row(rows, 'enable_do_not_track') == {
        'key': 'enable_do_not_track',
        'section': 'Privacy and security',
        'setting': 'Send a Do Not Track request',
        'source': 'profile',
        'value': 'On'
    }


def test_summarise_reports_default_when_absent() -> None:
    row = _row(summarise_preferences({}), 'safebrowsing.enabled')
    assert row['source'] == 'default'
    assert row['value'] == 'On'


def test_summarise_omits_settings_with_no_default() -> None:
    assert not [row for row in summarise_preferences({}) if row['key'] == 'homepage']


def test_summarise_changed_only_drops_defaults() -> None:
    rows = summarise_preferences({'enable_do_not_track': True}, changed_only=True)
    assert [row['key'] for row in rows] == ['enable_do_not_track']


def test_summarise_walks_into_a_list() -> None:
    rows = summarise_preferences({'account_info': [{'email': 'a@example.com'}]})
    assert _row(rows, 'account_info.0.email')['value'] == 'a@example.com'


@pytest.mark.parametrize(('preferences', 'expected'), [
    ({
        'account_info': []
    }, 0),
    ({
        'account_info': [{}]
    }, 0),
    ({
        'account_info': 'not a list'
    }, 0),
])
def test_summarise_ignores_unwalkable_paths(preferences: Mapping[str, Any], expected: int) -> None:
    assert len([
        row for row in summarise_preferences(preferences) if row['key'] == 'account_info.0.email'
    ]) == expected


def test_summarise_joins_list_values() -> None:
    rows = summarise_preferences({'spellcheck': {'dictionaries': ['en-GB', 'en-US']}})
    assert _row(rows, 'spellcheck.dictionaries')['value'] == 'en-GB, en-US'


def test_summarise_passes_through_unmapped_value() -> None:
    rows = summarise_preferences({'session': {'restore_on_startup': 99}})
    assert _row(rows, 'session.restore_on_startup')['value'] == 99


def test_summarise_accepts_custom_specs() -> None:
    specs = (SettingSpec('a.b', 'Section', 'Label', values={1: 'One'}),)
    assert summarise_preferences({'a': {
        'b': 1
    }}, specs) == [{
        'key': 'a.b',
        'section': 'Section',
        'setting': 'Label',
        'source': 'profile',
        'value': 'One'
    }]


def test_flatten_walks_nested_mappings() -> None:
    flattened = list(flatten_preferences({'a': {'b': 1, 'c': {}}, 'd': [1, 2]}))
    assert flattened == [{
        'key': 'a.b',
        'type': 'int',
        'value': 1
    }, {
        'key': 'a.c',
        'type': 'dict',
        'value': {}
    }, {
        'key': 'd',
        'type': 'list',
        'value': [1, 2]
    }]
