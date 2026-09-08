"""Network-related storage subcommands of ``chrome-dump``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import click

from deltona.chrome.network import (
    cache_entries,
    dips_bounces,
    dips_popups,
    nel_policies,
    network_persistent_state,
    reporting_endpoint_groups,
    reporting_endpoints,
    session_files,
    transport_security,
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
    from pathlib import Path

    from deltona.chrome import ChromeUserData
    from deltona.chrome.network import CacheKind, SortField

__all__ = ('list_cache', 'list_dips', 'list_network_state', 'list_reporting', 'list_sessions')

_REPORTING_COLUMNS: dict[str, tuple[str, ...]] = {
    'endpoints': ('origin_host', 'origin_port', 'group_name', 'url', 'priority', 'weight'),
    'groups': ('origin_host', 'origin_port', 'group_name', 'is_include_subdomains',
               'expires_us_since_epoch'),
    'nel': ('origin_host', 'origin_port', 'group_name', 'success_fraction', 'failure_fraction',
            'is_include_subdomains', 'expires_us_since_epoch')
}


def _require_file(path: Path) -> None:
    if not path.is_file():
        click.echo(f"'{path}' does not exist.", err=True)
        raise click.Abort


def _matches_search(row: dict[str, Any], search: str | None) -> bool:
    if not search:
        return True
    host = row.get('host')
    return host is None or search.casefold() in str(host).casefold()


def _network_state_section_rows(state: dict[str, Any], hsts: list[dict[str, Any]],
                                section: str) -> list[dict[str, Any]]:
    if section == 'servers':
        rows = []
        for server in state['servers']:
            row = dict(server)
            row['host'] = urlparse(row.get('server', '')).hostname
            rows.append(row)
        return rows
    if section == 'broken':
        return [dict(row) for row in state['broken_alternative_services']]
    if section == 'quic':
        rows = [{
            'kind': 'supports_quic',
            **state['supports_quic']
        }] if state['supports_quic'] else []
        rows.extend({'kind': 'quic_server', **row} for row in state['quic_servers'])
        return rows
    if section == 'network-qualities':
        return [{
            'network_id': key,
            'quality': value
        } for key, value in state['network_qualities'].items()]
    return list(hsts)


@click.command()
@click.option('--cache',
              'cache_kind',
              default='http',
              help='Which cache to read.',
              show_default=True,
              type=click.Choice(('code', 'http', 'image')))
@click.option('-l',
              '--limit',
              default=100,
              help='Maximum entries to show. 0 means no limit.',
              show_default=True,
              type=int)
@click.option('-s', '--search', help='Substring filter on the raw cache key.')
@click.option('--sort',
              default='modified',
              help='Sort order.',
              show_default=True,
              type=click.Choice(('key', 'modified', 'size')))
@json_option
@profile_option
@pass_user_data
def list_cache(user_data: ChromeUserData,
               profile_name: str = 'Default',
               cache_kind: CacheKind = 'http',
               search: str | None = None,
               sort: SortField = 'modified',
               limit: int = 100,
               *,
               as_json: bool = False) -> None:
    """List entries of a profile's HTTP, code, or image cache."""  # ruff:ignore[docstring-missing-exception]
    profile = resolve_profile(user_data, profile_name)
    if not profile.cache_path.is_dir():
        click.echo(f"'{profile.cache_path}' does not exist.", err=True)
        raise click.Abort
    rows = cache_entries(profile.cache_path, kind=cache_kind, search=search, sort=sort)
    if not as_json:
        click.echo(f'{len(rows)} entries, {sum(row["size"] for row in rows)} bytes.', err=True)
    echo_rows(rows[:limit] if limit else rows,
              as_json=as_json,
              title=f'Cache in {profile.directory}',
              columns=('key/url', 'size', 'modified', 'file'))


@click.command()
@click.option('--popups', 'show_popups', is_flag=True, help='Show the popups table instead.')
@click.option('-s', '--search', help='Case-insensitive substring filter on the site.')
@json_option
@profile_option
@pass_user_data
def list_dips(user_data: ChromeUserData,
              profile_name: str = 'Default',
              search: str | None = None,
              *,
              as_json: bool = False,
              show_popups: bool = False) -> None:
    """List bounce tracking and popup interaction records from a profile's `DIPS` database."""
    profile = resolve_profile(user_data, profile_name)
    path = profile.path / 'DIPS'
    _require_file(path)
    rows = dips_popups(path, search=search) if show_popups else dips_bounces(path, search=search)
    echo_rows(rows,
              as_json=as_json,
              title=f'{"Popups" if show_popups else "Bounces"} in {profile.directory}')


@click.command()
@click.option('--section',
              help='Section to show. Defaults to a summary of every section.',
              type=click.Choice(('broken', 'hsts', 'network-qualities', 'quic', 'servers')))
@click.option('-l',
              '--limit',
              default=100,
              help='Maximum rows to show. 0 means no limit.',
              type=int)
@click.option('-s', '--search', help='Case-insensitive substring filter on the host, where shown.')
@json_option
@profile_option
@pass_user_data
def list_network_state(user_data: ChromeUserData,
                       profile_name: str = 'Default',
                       section: str | None = None,
                       search: str | None = None,
                       limit: int = 100,
                       *,
                       as_json: bool = False) -> None:
    """List HTTP server properties, QUIC support, and HSTS state of a profile."""
    profile = resolve_profile(user_data, profile_name)
    network_state_path = profile.path / 'Network Persistent State'
    transport_security_path = profile.path / 'TransportSecurity'
    _require_file(network_state_path)
    _require_file(transport_security_path)
    state = network_persistent_state(network_state_path)
    hsts = transport_security(transport_security_path)
    if section is None:
        if as_json:
            echo_json({**state, 'hsts': hsts})
            return
        echo_mapping(
            {
                'servers': len(state['servers']),
                'broken_alternative_services': len(state['broken_alternative_services']),
                'quic_servers': (1 if state['supports_quic'] else 0) + len(state['quic_servers']),
                'network_qualities': len(state['network_qualities']),
                'hsts': len(hsts)
            },
            as_json=False,
            title='Network State Summary')
        return
    rows = [
        row for row in _network_state_section_rows(state, hsts, section)
        if _matches_search(row, search)
    ]
    echo_rows(rows[:limit] if limit else rows, as_json=as_json, title=f'Network State ({section})')


@click.command()
@click.option('--table',
              'table_name',
              default='nel',
              help='Table to show.',
              show_default=True,
              type=click.Choice(('endpoints', 'groups', 'nel')))
@click.option('-s', '--search', help='Case-insensitive substring filter on the origin host.')
@json_option
@profile_option
@pass_user_data
def list_reporting(user_data: ChromeUserData,
                   profile_name: str = 'Default',
                   table_name: str = 'nel',
                   search: str | None = None,
                   *,
                   as_json: bool = False) -> None:
    """List Network Error Logging policies and Reporting API endpoints of a profile."""
    profile = resolve_profile(user_data, profile_name)
    path = profile.path / 'Reporting and NEL'
    _require_file(path)
    if table_name == 'endpoints':
        rows = reporting_endpoints(path, search=search)
    elif table_name == 'groups':
        rows = reporting_endpoint_groups(path, search=search)
    else:
        rows = nel_policies(path, search=search)
    echo_rows(rows,
              as_json=as_json,
              columns=_REPORTING_COLUMNS[table_name],
              title=f'{table_name.title()} in {profile.directory}')


@click.command()
@click.option('--urls', 'show_urls', is_flag=True, help='Show extracted URLs instead.')
@json_option
@profile_option
@pass_user_data
def list_sessions(user_data: ChromeUserData,
                  profile_name: str = 'Default',
                  *,
                  as_json: bool = False,
                  show_urls: bool = False) -> None:
    """
    List a profile's session, tab, and app restore files.

    Only the SNSS record framing is decoded; individual command payloads are not, and URLs are
    recovered on a best-effort basis by scanning payload bytes for `http://` or `https://` runs.
    """  # ruff:ignore[docstring-missing-exception]
    profile = resolve_profile(user_data, profile_name)
    sessions_path = profile.path / 'Sessions'
    if not sessions_path.is_dir():
        click.echo(f"'{sessions_path}' does not exist.", err=True)
        raise click.Abort
    rows = session_files(sessions_path)
    if show_urls:
        echo_rows(({
            'file': row['name'],
            'kind': row['kind'],
            'url': url
        } for row in rows for url in row['urls']),
                  as_json=as_json,
                  title=f'Session URLs in {profile.directory}')
        return
    echo_rows(
        rows,
        as_json=as_json,
        columns=('name', 'kind', 'timestamp', 'size', 'version', 'record_count', 'record_ids'),
        title=f'Sessions in {profile.directory}')
