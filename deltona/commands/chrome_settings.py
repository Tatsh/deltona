"""Extension, content setting, search engine, and web app subcommands of ``chrome-dump``."""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from deltona.chrome.settings import (
    read_content_settings,
    read_default_content_settings,
    read_extensions,
    read_search_engines,
    read_web_apps,
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
    from deltona.chrome import ChromeUserData

__all__ = ('list_extensions', 'list_permissions', 'list_search_engines', 'list_web_apps')


@click.command()
@click.option('-i', '--id', 'extension_id', help='Show one extension by ID in full detail.')
@click.option('--enabled/--disabled',
              'enabled_filter',
              default=None,
              help='Restrict to enabled or disabled extensions.')
@json_option
@profile_option
@pass_user_data
def list_extensions(user_data: ChromeUserData,
                    profile_name: str = 'Default',
                    extension_id: str | None = None,
                    *,
                    as_json: bool = False,
                    enabled_filter: bool | None = None) -> None:
    """Dump every extension installed in a profile."""  # ruff:ignore[docstring-missing-exception]
    profile = resolve_profile(user_data, profile_name)
    try:
        records = read_extensions(profile.path)
    except FileNotFoundError as e:
        click.echo(f"No `Preferences` file for '{profile.directory}': {e}", err=True)
        raise click.Abort from e
    if extension_id:
        record = next((r for r in records if r['id'] == extension_id), None)
        if record is None:
            click.echo(f"No extension with ID '{extension_id}' in '{profile.directory}'.", err=True)
            raise click.Abort
        echo_mapping(record, as_json=as_json, title=f'Extension {extension_id}')
        return
    if enabled_filter is not None:
        records = [r for r in records if r['enabled'] == enabled_filter]
    if as_json:
        echo_json(records)
        return
    echo_rows(({
        'id': r['id'],
        'name': r['name'],
        'version': r['version'],
        'state': r['state_display'],
        'location': r['location_display'],
        'from_webstore': r['from_webstore'],
        'install_time': r['install_time'],
        'permissions': r['permission_count']
    } for r in records),
              as_json=False,
              title=f'Extensions in {profile.directory}')


@click.command()
@click.option('-t', '--type', 'type_', help='Restrict to one content setting type.')
@click.option('--defaults', is_flag=True, help="Show only the profile's default values.")
@json_option
@profile_option
@pass_user_data
def list_permissions(user_data: ChromeUserData,
                     profile_name: str = 'Default',
                     type_: str | None = None,
                     *,
                     as_json: bool = False,
                     defaults: bool = False) -> None:
    """Dump a profile's per-site content setting exceptions."""  # ruff:ignore[docstring-missing-exception]
    profile = resolve_profile(user_data, profile_name)
    try:
        records = (read_default_content_settings(profile.path)
                   if defaults else read_content_settings(profile.path))
    except FileNotFoundError as e:
        click.echo(f"No `Preferences` file for '{profile.directory}': {e}", err=True)
        raise click.Abort from e
    if type_:
        records = [r for r in records if r['type'] == type_]
    if as_json:
        echo_json(records)
        return
    if defaults:
        echo_rows(({
            'type': r['type'],
            'setting': r['setting_display']
        } for r in records),
                  as_json=False,
                  title=f'Default content settings in {profile.directory}')
        return
    echo_rows(({
        'type': r['type'],
        'primary_pattern': r['primary_pattern'],
        'secondary_pattern': r['secondary_pattern'],
        'setting': r['setting_display'],
        'last_modified': r['last_modified'],
        'expiration': r['expiration']
    } for r in records),
              as_json=False,
              title=f'Content setting exceptions in {profile.directory}')


@click.command()
@click.option('--all',
              'all_',
              is_flag=True,
              help='Include prepopulated engines that are not active. By default only engines '
              'with `prepopulate_id = 0` (user-created) or an active status are shown.')
@json_option
@profile_option
@pass_user_data
def list_search_engines(user_data: ChromeUserData,
                        profile_name: str = 'Default',
                        *,
                        all_: bool = False,
                        as_json: bool = False) -> None:
    """Dump a profile's search engines."""  # ruff:ignore[docstring-missing-exception]
    profile = resolve_profile(user_data, profile_name)
    try:
        records = read_search_engines(profile.path)
    except FileNotFoundError as e:
        click.echo(f"No `Preferences` file for '{profile.directory}': {e}", err=True)
        raise click.Abort from e
    if not all_:
        records = [
            r for r in records
            if r['source'] != 'keywords' or r.get('prepopulate_id') == 0 or r.get('is_active') == 1
        ]
    if as_json:
        echo_json(records)
        return
    echo_rows(({
        'short_name': r.get('short_name'),
        'keyword': r.get('keyword'),
        'url': r.get('url'),
        'is_active': r.get('is_active_display'),
        'is_default': r.get('is_default'),
        'prepopulate_id': r.get('prepopulate_id'),
        'source': r['source']
    } for r in records),
              as_json=False,
              title=f'Search engines in {profile.directory}')


@click.command()
@click.option('-i', '--id', 'app_id', help='Show one web app by ID in full detail.')
@json_option
@profile_option
@pass_user_data
def list_web_apps(user_data: ChromeUserData,
                  profile_name: str = 'Default',
                  app_id: str | None = None,
                  *,
                  as_json: bool = False) -> None:
    """Dump a profile's installed web apps."""  # ruff:ignore[docstring-missing-exception]
    profile = resolve_profile(user_data, profile_name)
    try:
        records = read_web_apps(profile.path)
    except FileNotFoundError as e:
        click.echo(f"No `Preferences` file for '{profile.directory}': {e}", err=True)
        raise click.Abort from e
    if app_id:
        record = next((r for r in records if r['id'] == app_id), None)
        if record is None:
            click.echo(f"No web app with ID '{app_id}' in '{profile.directory}'.", err=True)
            raise click.Abort
        echo_mapping(record, as_json=as_json, title=f'Web app {app_id}')
        return
    if as_json:
        echo_json(records)
        return
    echo_rows(({
        'id': r['id'],
        'name': r.get('name'),
        'start_url': r.get('start_url'),
        'display_mode': r.get('display_mode'),
        'is_locally_installed': r.get('is_locally_installed'),
        'install_time': r.get('first_install_time'),
        'icon_sizes': r.get('icon_sizes')
    } for r in records),
              as_json=False,
              title=f'Web apps in {profile.directory}')
