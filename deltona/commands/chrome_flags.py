"""The ``list-flags`` subcommand of ``chrome-dump``."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

import click

from deltona.chrome.flags import (
    FlagTableUnavailable,
    flag_states,
    flag_table_for,
    installed_version,
)
from deltona.commands.chrome_common import echo_rows, json_option, pass_user_data

if TYPE_CHECKING:
    from deltona.chrome import ChromeUserData

__all__ = ('list_flags',)

_STATE_FILTERS = {
    'changed': lambda state: state != 'Default',
    'default': lambda state: state == 'Default',
    'disabled': lambda state: state == 'Disabled',
    'enabled': lambda state: state == 'Enabled'
}


@click.command()
@click.option('-a', '--all', 'show_all', is_flag=True, help='Include flags left at their default.')
@click.option('-s', '--search', help='Only show flags whose name, title, or description matches.')
@click.option('--binary',
              help='Browser binary to read the flag table out of.',
              type=click.Path(dir_okay=False, exists=True, path_type=Path))
@click.option('--offline', is_flag=True, help='Never fetch; use only the cache and the binary.')
@click.option('--refresh', is_flag=True, help='Read the flag definitions again.')
@click.option('--source',
              default='auto',
              help='Where to read the flag definitions from.',
              type=click.Choice(('auto', 'binary', 'network')))
@click.option('--state',
              help='Only show flags in this state.',
              type=click.Choice(('changed', 'default', 'disabled', 'enabled')))
@click.option('--version',
              'version_override',
              help='Browser version to describe. Defaults to the value in `Last Version`.')
@json_option
@pass_user_data
def list_flags(user_data: ChromeUserData,
               binary: Path | None = None,
               search: str | None = None,
               source: str = 'auto',
               state: str | None = None,
               version_override: str | None = None,
               *,
               as_json: bool = False,
               offline: bool = False,
               refresh: bool = False,
               show_all: bool = False) -> None:
    """
    List the state of every `chrome://flags` entry the browser has been told about.

    Flag titles and descriptions are not stored in the profile. They are read out of the installed
    browser binary when one can be found, and otherwise fetched from the Chromium source at the tag
    matching the installed browser version. Either way the result is cached. Flags the profile
    still records but the browser no longer defines are shown with an empty description.

    A binary supplies no owners or expiry milestones, so those are filled in from
    `flag-metadata.json` unless `--offline` was given.
    """  # ruff:ignore[docstring-missing-exception]
    version = version_override or installed_version(user_data.config_path)
    if not version:
        click.echo(f"No 'Last Version' in '{user_data.config_path}'. Pass --version.", err=True)
        raise click.Abort
    try:
        table, used = flag_table_for(version,
                                     binary=binary,
                                     channel=user_data.channel,
                                     offline=offline,
                                     refresh=refresh,
                                     source=cast('Literal["auto", "binary", "network"]', source))
    except FlagTableUnavailable as e:
        click.echo(str(e), err=True)
        raise click.Abort from e
    if not as_json:
        click.echo(f'Flag definitions from {used}.', err=True)
    experiments = user_data.local_state.get('browser', {}).get('enabled_labs_experiments', [])
    rows = flag_states(version, list(experiments), table, include_unchanged=show_all)
    if state:
        rows = (row for row in rows if _STATE_FILTERS[state](row['state']))
    if search:
        wanted = search.casefold()
        rows = (row for row in rows if wanted in row['name'].casefold()
                or wanted in row['title'].casefold() or wanted in row['description'].casefold())
    echo_rows(rows,
              as_json=as_json,
              columns=('name', 'title', 'state', 'description', 'os', 'expiry_milestone', 'source'),
              title=f'Flags ({version})')
