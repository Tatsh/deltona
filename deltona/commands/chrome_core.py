"""Profile, preference, and raw storage subcommands of ``chrome-dump``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
import json
import sqlite3

import click

from deltona.chrome import (
    ChromeUserData,
    database_summary,
    is_sqlite_database,
    profile_files,
    query_database as run_query,
)
from deltona.chrome.preferences import flatten_preferences, summarise_preferences
from deltona.commands.chrome_common import (
    echo_json,
    echo_rows,
    echo_tree,
    json_option,
    pass_user_data,
    profile_option,
    resolve_profile,
)

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ('list_databases', 'list_files', 'list_profiles', 'local_state', 'preferences', 'query')

_MAX_PREVIEW_TABLES = 8


def dig(data: Any, key: str) -> Any:
    """
    Follow a dotted path into nested mappings and sequences.

    Parameters
    ----------
    data : Any
        The value to walk.
    key : str
        Dotted path, such as ``'browser.enabled_labs_experiments'``. List indices are written as
        numbers.

    Returns
    -------
    Any
        The value at ``key``, or ``None`` if any component is missing.
    """
    current = data
    for part in key.split('.'):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    return current


def _read_json(path: Path) -> Any:
    if not path.is_file():
        click.echo(f"'{path}' does not exist.", err=True)
        raise click.Abort
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        click.echo(f"'{path}' could not be read: {e}", err=True)
        raise click.Abort from e


@click.command()
@json_option
@pass_user_data
def list_profiles(user_data: ChromeUserData, *, as_json: bool = False) -> None:
    """List every profile in the user data directory."""
    echo_rows(({
        'directory': profile.directory,
        'name': profile.name,
        'account': profile.gaia_name,
        'email': profile.email,
        'hosted_domain': profile.info.get('hosted_domain'),
        'ephemeral': bool(profile.info.get('is_ephemeral')),
        'active_time': profile.active_time,
        'path': profile.path
    } for profile in user_data.profiles()),
              as_json=as_json,
              title='Profiles')


@click.command()
@click.option('-k', '--key', help='Dotted path to a single value, such as `browser.hovercard`.')
@json_option
@pass_user_data
def local_state(user_data: ChromeUserData,
                key: str | None = None,
                *,
                as_json: bool = False) -> None:
    """Dump the browser-wide `Local State` file."""
    data: Any = _read_json(user_data.config_path / 'Local State')
    if key:
        data = dig(data, key)
    echo_tree(data, as_json=as_json, title=f'Local State{f" ({key})" if key else ""}')


@click.command()
@click.option('--changed', is_flag=True, help='Omit settings left at their default.')
@click.option('-k',
              '--key',
              help='Dotted path to a single value, such as `download.default_directory`.')
@click.option('-r', '--raw', is_flag=True, help='Dump the file as stored instead of summarising.')
@click.option('-s', '--secure', is_flag=True, help='Read `Secure Preferences` instead.')
@click.option('-S', '--section', help='Only show settings in this section of the summary.')
@click.option('-x', '--expand', is_flag=True, help='List every stored key rather than a summary.')
@json_option
@profile_option
@pass_user_data
def preferences(user_data: ChromeUserData,
                profile_name: str = 'Default',
                key: str | None = None,
                section: str | None = None,
                *,
                as_json: bool = False,
                changed: bool = False,
                expand: bool = False,
                raw: bool = False,
                secure: bool = False) -> None:
    """
    Show a profile's settings the way the browser's own settings page groups them.

    Chrome only writes a preference once it differs from its built-in default, so the summary also
    reports the defaults that are in force and marks where each value came from. It is lossy: use
    `--expand` for every stored key, `--raw` for the file as stored, or `--key` for one value.

    `--secure` reads `Secure Preferences`, which holds no settings the summary knows about, so it
    implies `--raw` unless `--expand` is given.
    """
    profile = resolve_profile(user_data, profile_name)
    name = 'Secure Preferences' if secure else 'Preferences'
    data: Any = _read_json(profile.path / name)
    if key:
        echo_tree(dig(data, key), as_json=as_json, title=f'{name} ({key})')
        return
    if raw or (secure and not expand):
        echo_tree(data, as_json=as_json, title=name)
        return
    if expand:
        echo_rows(flatten_preferences(data),
                  as_json=as_json,
                  title=f'{name} in {profile.directory}')
        return
    rows = summarise_preferences(data, changed_only=changed)
    if section:
        wanted = section.casefold()
        rows = [row for row in rows if wanted in str(row['section']).casefold()]
    echo_rows(rows,
              as_json=as_json,
              columns=('section', 'setting', 'value', 'source'),
              title=f'Settings in {profile.directory}')


@click.command()
@json_option
@profile_option
@pass_user_data
def list_databases(user_data: ChromeUserData,
                   profile_name: str = 'Default',
                   *,
                   as_json: bool = False) -> None:
    """List the SQLite databases of a profile with their schema versions and tables."""
    profile = resolve_profile(user_data, profile_name)
    summaries = [
        database_summary(path) for path in sorted(profile.path.iterdir())
        if is_sqlite_database(path)
    ]
    if as_json:
        echo_json(summaries)
        return
    echo_rows(({
        'name':
            summary['name'],
        'size':
            summary['size'],
        'version':
            summary['version'],
        'last_compatible_version':
            summary['last_compatible_version'],
        'tables':
            len(summary['tables']),
        'table_names':
            ', '.join(summary['tables'][:_MAX_PREVIEW_TABLES]) +
            ('…' if len(summary['tables']) > _MAX_PREVIEW_TABLES else '')
    } for summary in summaries),
              as_json=False,
              title=f'Databases in {profile.directory}')


@click.command()
@json_option
@profile_option
@pass_user_data
def list_files(user_data: ChromeUserData,
               profile_name: str = 'Default',
               *,
               as_json: bool = False) -> None:
    """Inventory everything stored at the top level of a profile directory."""
    profile = resolve_profile(user_data, profile_name)
    echo_rows(profile_files(profile.path), as_json=as_json, title=f'Files in {profile.directory}')


@click.command()
@click.argument('database')
@click.argument('sql')
@click.option('-l', '--limit', default=0, help='Maximum rows to show. 0 means no limit.', type=int)
@json_option
@profile_option
@pass_user_data
def query(user_data: ChromeUserData,
          database: str,
          sql: str,
          profile_name: str = 'Default',
          limit: int = 0,
          *,
          as_json: bool = False) -> None:
    """
    Run a read-only query against one of a profile's SQLite databases.

    DATABASE is a file name within the profile directory, such as `Web Data` or `History`. Use
    `list-databases` to see what is available.
    """  # ruff:ignore[docstring-missing-exception]
    profile = resolve_profile(user_data, profile_name)
    path = profile.path / database
    if not is_sqlite_database(path):
        click.echo(f"'{path}' is not a SQLite database.", err=True)
        raise click.Abort
    try:
        rows = run_query(path, sql)
    except sqlite3.Error as e:
        click.echo(f'Query failed: {e}', err=True)
        raise click.Abort from e
    echo_rows(rows[:limit] if limit > 0 else rows, as_json=as_json, title=database)
