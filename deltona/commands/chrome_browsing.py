"""Bookmark, download, history, shortcut, top site, and spell-check ``chrome-dump`` subcommands."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.tree import Tree
import click

from deltona.chrome.browsing import (
    DOWNLOAD_STATES,
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
from deltona.commands.chrome_common import (
    echo_json,
    echo_mapping,
    echo_rows,
    json_option,
    pass_user_data,
    profile_option,
    resolve_profile,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from deltona.chrome import ChromeUserData

__all__ = ('bookmarks', 'list_downloads', 'list_history', 'list_shortcuts', 'list_top_sites',
           'spell_check')

_HISTORY_COLUMNS = ('url', 'title', 'visit_time', 'transition_core', 'visit_count',
                    'visit_duration')
_SHORTCUT_COLUMNS = ('text', 'url', 'description', 'keyword', 'number_of_hits', 'last_access_time')
_URL_COLUMNS = ('url', 'title', 'visit_count', 'typed_count', 'last_visit_time')
_SEARCH_TERM_COLUMNS = ('term', 'url', 'title')


def _add_bookmark_node(parent: Tree, node: Mapping[str, Any]) -> None:
    label = node['name'] if node['type'] == 'folder' else f"{node['name']} ({node['url']})"
    branch = parent.add(label)
    for child in node.get('children', ()):
        _add_bookmark_node(branch, child)


@click.command()
@click.argument('folder', required=False)
@click.option('--tree/--flat', 'tree', default=False, help='Show a tree instead of a flat table.')
@json_option
@profile_option
@pass_user_data
def bookmarks(user_data: ChromeUserData,
              folder: str | None = None,
              profile_name: str = 'Default',
              *,
              as_json: bool = False,
              tree: bool = False) -> None:
    """
    Dump a profile's bookmarks.

    FOLDER optionally limits the output to one folder and everything under it. Give it as a
    slash-separated path such as `Bookmarks bar/Development`; the first segment may be a root name
    such as `other`. Matching ignores case.
    """  # ruff:ignore[docstring-missing-exception]
    profile = resolve_profile(user_data, profile_name)
    try:
        roots = read_bookmarks(profile.path)
    except FileNotFoundError as e:
        click.echo(f"No `Bookmarks` file for '{profile.directory}': {e}", err=True)
        raise click.Abort from e
    if folder:
        node = find_bookmark_folder(roots, folder)
        if node is None:
            click.echo(f"No bookmark folder matching '{folder}'.", err=True)
            raise click.Abort
        roots = {folder: node}
    if as_json:
        echo_json(flatten_bookmarks(roots))
        return
    if tree:
        rich_tree = Tree(profile.directory)
        for root in roots.values():
            _add_bookmark_node(rich_tree, root)
        Console().print(rich_tree)
        return
    echo_rows(flatten_bookmarks(roots), as_json=False, title=f'Bookmarks in {profile.directory}')


@click.command()
@click.option('-l', '--limit', default=0, help='Maximum rows to show. 0 means no limit.', type=int)
@click.option('--state',
              help='Restrict to downloads in this state.',
              type=click.Choice(sorted(DOWNLOAD_STATES.values()), case_sensitive=False))
@json_option
@profile_option
@pass_user_data
def list_downloads(user_data: ChromeUserData,
                   profile_name: str = 'Default',
                   limit: int = 0,
                   state: str | None = None,
                   *,
                   as_json: bool = False) -> None:
    """Dump every download recorded in a profile's `History` database."""  # ruff:ignore[docstring-missing-exception]
    profile = resolve_profile(user_data, profile_name)
    state_value = None
    if state:
        state_value = next(k for k, v in DOWNLOAD_STATES.items() if v == state.upper())
    try:
        downloads = read_downloads(profile.path, limit=limit, state=state_value)
    except FileNotFoundError as e:
        click.echo(f"No `History` database for '{profile.directory}': {e}", err=True)
        raise click.Abort from e
    if as_json:
        echo_json(downloads)
        return
    echo_rows(({
        'id': download['id'],
        'target_path': download['target_path'],
        'start_time': download['start_time'],
        'received_bytes': download['received_bytes'],
        'total_bytes': download['total_bytes'],
        'state': download['state_name'],
        'danger_type': download['danger_type_name'],
        'tab_url': download['tab_url']
    } for download in downloads),
              as_json=False,
              title=f'Downloads in {profile.directory}')


@click.command()
@click.option('-l',
              '--limit',
              default=100,
              help='Maximum rows to show. 0 means no limit.',
              type=int)
@click.option('-s', '--search', help='Filter by a substring of the URL or title.')
@click.option('--search-terms', is_flag=True, help='Show `keyword_search_terms` instead.')
@click.option('--urls-only', is_flag=True, help='Show `urls` without joining `visits`.')
@json_option
@profile_option
@pass_user_data
def list_history(user_data: ChromeUserData,
                 profile_name: str = 'Default',
                 limit: int = 100,
                 search: str | None = None,
                 *,
                 as_json: bool = False,
                 search_terms: bool = False,
                 urls_only: bool = False) -> None:
    """Dump a profile's browsing history."""  # ruff:ignore[docstring-missing-exception]
    profile = resolve_profile(user_data, profile_name)
    columns: tuple[str, ...]
    if search_terms:
        reader, columns = read_search_terms, _SEARCH_TERM_COLUMNS
        title = f'Search terms in {profile.directory}'
    elif urls_only:
        reader, columns = read_history_urls, _URL_COLUMNS
        title = f'URLs in {profile.directory}'
    else:
        reader, columns = read_history, _HISTORY_COLUMNS
        title = f'History in {profile.directory}'
    try:
        rows = reader(profile.path, limit=limit, search=search)
    except FileNotFoundError as e:
        click.echo(f"No `History` database for '{profile.directory}': {e}", err=True)
        raise click.Abort from e
    echo_rows(rows, as_json=as_json, columns=columns, title=title)


@click.command()
@json_option
@profile_option
@pass_user_data
def list_shortcuts(user_data: ChromeUserData,
                   profile_name: str = 'Default',
                   *,
                   as_json: bool = False) -> None:
    """Dump a profile's omnibox shortcuts."""  # ruff:ignore[docstring-missing-exception]
    profile = resolve_profile(user_data, profile_name)
    try:
        rows = read_shortcuts(profile.path)
    except FileNotFoundError as e:
        click.echo(f"No `Shortcuts` database for '{profile.directory}': {e}", err=True)
        raise click.Abort from e
    echo_rows(rows,
              as_json=as_json,
              columns=_SHORTCUT_COLUMNS,
              title=f'Shortcuts in {profile.directory}')


@click.command()
@json_option
@profile_option
@pass_user_data
def list_top_sites(user_data: ChromeUserData,
                   profile_name: str = 'Default',
                   *,
                   as_json: bool = False) -> None:
    """Dump a profile's top sites."""  # ruff:ignore[docstring-missing-exception]
    profile = resolve_profile(user_data, profile_name)
    try:
        rows = read_top_sites(profile.path)
    except FileNotFoundError as e:
        click.echo(f"No `Top Sites` database for '{profile.directory}': {e}", err=True)
        raise click.Abort from e
    echo_rows(rows, as_json=as_json, title=f'Top sites in {profile.directory}')


@click.command()
@json_option
@profile_option
@pass_user_data
def spell_check(user_data: ChromeUserData,
                profile_name: str = 'Default',
                *,
                as_json: bool = False) -> None:
    """Dump a profile's custom spell-check dictionary."""  # ruff:ignore[docstring-missing-exception]
    profile = resolve_profile(user_data, profile_name)
    try:
        data = read_custom_dictionary(profile.path)
    except FileNotFoundError as e:
        click.echo(f"No `Custom Dictionary.txt` for '{profile.directory}': {e}", err=True)
        raise click.Abort from e
    if as_json:
        echo_json(data)
        return
    echo_rows(({
        'word': word
    } for word in data['words']),
              as_json=False,
              title=f"Custom dictionary in {profile.directory} (checksum: {data['checksum']})")
    if data['preferences']:
        echo_mapping(data['preferences'], as_json=False, title='Spell-check preferences')
