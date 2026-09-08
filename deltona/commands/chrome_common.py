"""Shared options and output helpers for the ``chrome-dump`` subcommands."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
import json

from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table
import click

from deltona.chrome import ChromeProfile, ChromeUserData, ProfileNotFound

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

__all__ = ('echo_json', 'echo_mapping', 'echo_rows', 'json_option', 'pass_user_data',
           'profile_option', 'resolve_profile')

pass_user_data = click.make_pass_decorator(ChromeUserData)
"""
Pass the :py:class:`~deltona.chrome.ChromeUserData` built by the group to a subcommand.

:meta hide-value:
"""


def json_option(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Add the ``-j``/``--json`` flag to a subcommand.

    Parameters
    ----------
    func : Callable[..., Any]
        The command callback.

    Returns
    -------
    Callable[..., Any]
        The decorated callback.
    """
    return click.option('-j', '--json', 'as_json', is_flag=True, help='Output JSON.')(func)


def profile_option(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Add the ``-P``/``--profile`` option to a subcommand.

    The value may be a profile directory name, display name, Google account name, or email
    address.

    Parameters
    ----------
    func : Callable[..., Any]
        The command callback.

    Returns
    -------
    Callable[..., Any]
        The decorated callback.
    """
    return click.option('-P',
                        '--profile',
                        'profile_name',
                        default='Default',
                        help='Profile directory name, display name, account name, or email.',
                        show_default=True)(func)


def resolve_profile(user_data: ChromeUserData, name: str) -> ChromeProfile:
    """
    Resolve a profile, aborting with a helpful message when it does not exist.

    Parameters
    ----------
    user_data : ChromeUserData
        The user data directory.
    name : str
        Value passed to ``--profile``.

    Returns
    -------
    ChromeProfile
        The matching profile.

    Raises
    ------
    click.Abort
        If no profile matches.
    """
    try:
        return user_data.profile(name)
    except ProfileNotFound as e:
        click.echo(str(e), err=True)
        raise click.Abort from e


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).hex()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, set):
        return sorted(value)
    return str(value)


def echo_json(data: Any) -> None:
    """
    Write a value as JSON.

    Parameters
    ----------
    data : Any
        Any JSON-serialisable value. Datetimes, byte strings, and paths are converted. Non-ASCII
        characters are written as UTF-8 rather than escaped.
    """
    click.echo(
        json.dumps(data,
                   allow_nan=False,
                   default=_json_default,
                   ensure_ascii=False,
                   indent=2,
                   sort_keys=True))


def _display(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'yes' if value else 'no'
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).hex()
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, default=_json_default, ensure_ascii=False, sort_keys=True)
    return str(value)


def _console() -> Console:
    return Console()


def echo_rows(rows: Iterable[Mapping[str, Any]],
              *,
              as_json: bool,
              title: str,
              columns: Sequence[str] | None = None) -> None:
    """
    Write a sequence of records either as JSON or as a table.

    Parameters
    ----------
    rows : Iterable[Mapping[str, Any]]
        The records. Every record is expected to have the same keys.
    as_json : bool
        If ``True``, write JSON instead of a table.
    title : str
        Table title. Ignored when writing JSON.
    columns : Sequence[str] | None
        Columns to show, in order. Defaults to the keys of the first record.
    """
    materialised = [dict(row) for row in rows]
    if as_json:
        echo_json(materialised)
        return
    if not materialised:
        click.echo(f'No {title.lower()} found.', err=True)
        return
    headers = list(columns) if columns else list(materialised[0])
    table = Table(title=title, header_style='bold', title_justify='left')
    for header in headers:
        table.add_column(header.replace('_', ' ').title(), overflow='fold')
    for row in materialised:
        table.add_row(*(_display(row.get(header)) for header in headers))
    _console().print(table)


def echo_mapping(data: Mapping[str, Any], *, as_json: bool, title: str) -> None:
    """
    Write a mapping either as JSON or as a two-column table.

    Parameters
    ----------
    data : Mapping[str, Any]
        The mapping.
    as_json : bool
        If ``True``, write JSON instead of a table.
    title : str
        Table title. Ignored when writing JSON.
    """
    if as_json:
        echo_json(dict(data))
        return
    echo_rows(({
        'key': key,
        'value': value
    } for key, value in sorted(data.items())),
              as_json=False,
              title=title)


def echo_tree(data: Any, *, as_json: bool, title: str) -> None:
    """
    Write arbitrary nested data either as JSON or as a syntax-highlighted view.

    Parameters
    ----------
    data : Any
        The value to write.
    as_json : bool
        If ``True``, write plain JSON instead of the highlighted view.
    title : str
        Heading printed above the highlighted view. Ignored when writing JSON.
    """
    if as_json:
        echo_json(data)
        return
    text = json.dumps(data, default=_json_default, ensure_ascii=False, indent=2, sort_keys=True)
    console = _console()
    console.print(f'[bold]{title}[/bold]')
    console.print(Syntax(text, 'json', word_wrap=True))
