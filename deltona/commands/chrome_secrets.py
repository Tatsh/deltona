"""Password, cookie, payment, and autofill subcommands of ``chrome-dump``."""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING, Any
import json

import click

from deltona.chrome import ChromeUserData, OSCrypt, is_sqlite_database, table_names
from deltona.chrome.secrets import (
    COOKIE_DATABASES,
    PAYMENT_SECRET_FIELDS,
    PAYMENT_TABLES,
    iter_addresses,
    iter_ai_entities,
    iter_autocomplete,
    iter_autofill,
    iter_cookies,
    iter_login_stats,
    iter_logins,
    iter_payment_table,
    iter_plus_addresses,
    iter_sign_in_tokens,
)
from deltona.commands.chrome_common import (
    echo_json,
    echo_rows,
    json_option,
    pass_user_data,
    profile_option,
    resolve_profile,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from deltona.chrome import ChromeProfile

__all__ = ('list_accounts', 'list_autofill', 'list_cookies', 'list_passwords', 'list_payments')

_MASK_LENGTH = 12
_COOKIE_COLUMNS = ('host', 'name', 'value', 'path', 'is_secure', 'samesite', 'expires')
_PASSWORD_COLUMNS = ('origin', 'username', 'password', 'scheme', 'times_used', 'date_last_used',
                     'insecurity_types')


def _resolve_database(profile: ChromeProfile, name: str) -> Path:
    path = profile.path / name
    if not is_sqlite_database(path):
        reason = 'is not a SQLite database' if path.exists() else 'does not exist'
        click.echo(f"'{path}' {reason}.", err=True)
        raise click.Abort
    return path


def _read_preferences(profile: ChromeProfile) -> dict[str, Any]:
    path = profile.path / 'Preferences'
    if not path.is_file():
        return {}
    with suppress(OSError, ValueError):
        loaded = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(loaded, dict):
            return loaded
    return {}


def _make_crypt(user_data: ChromeUserData) -> OSCrypt:
    return OSCrypt(user_data.keyring_name, dict(user_data.local_state))


def _warn_if_undecryptable(crypt: OSCrypt) -> None:
    if not crypt.available:
        click.echo('No decryption key is available. Secrets will show as `(encrypted)`.', err=True)


def _warn_undecrypted(values: Sequence[str | None], crypt: OSCrypt) -> None:
    if not (failed := sum(value is None for value in values)):
        return
    click.echo(f'{failed} of {len(values)} values could not be decrypted.', err=True)
    if not crypt.keyring_available:
        click.echo(
            'The desktop keyring did not return the browser key, which every value written as'
            ' `v11` needs. Run with --debug to see which backends were tried. The keyring daemon'
            ' must be running and unlocked in this session.',
            err=True)


def _suggest_account(profile: ChromeProfile, name: str, *, account: bool) -> None:
    if not account and is_sqlite_database(profile.path / name):
        click.echo(f"'{name}' also exists; pass --account to read it.", err=True)


def _secret(value: str | None, *, reveal: bool) -> str:
    if value is None:
        return '(encrypted)'
    return value if reveal else '*' * min(len(value), _MASK_LENGTH)


@click.command()
@click.option('-a',
              '--account',
              is_flag=True,
              help='Read `Login Data For Account` instead of `Login Data`.')
@click.option('--show-passwords',
              is_flag=True,
              help='Show decrypted passwords and notes instead of a masked placeholder.')
@click.option('--stats',
              'show_stats',
              is_flag=True,
              help='Show dismissal statistics from the `stats` table instead of logins.')
@json_option
@profile_option
@pass_user_data
def list_passwords(user_data: ChromeUserData,
                   profile_name: str = 'Default',
                   *,
                   account: bool = False,
                   as_json: bool = False,
                   show_passwords: bool = False,
                   show_stats: bool = False) -> None:
    """List saved and blocklisted logins."""
    profile = resolve_profile(user_data, profile_name)
    path = _resolve_database(profile, 'Login Data For Account' if account else 'Login Data')
    if show_stats:
        echo_rows(iter_login_stats(path),
                  as_json=as_json,
                  title=f'Password statistics in {profile.directory}')
        return
    crypt = _make_crypt(user_data)
    _warn_if_undecryptable(crypt)
    logins = list(iter_logins(path, crypt))
    _warn_undecrypted([row['password'] for row in logins if not row['blocklisted']], crypt)
    rows = [{
        **row, 'password': _secret(row['password'], reveal=show_passwords),
        'insecurity_types': ', '.join(row['insecurity_types']),
        'notes': {
            key: _secret(value, reveal=show_passwords)
            for key, value in row['notes'].items()
        }
    } for row in logins]
    if not rows:
        _suggest_account(profile, 'Login Data For Account', account=account)
    echo_rows(rows,
              as_json=as_json,
              columns=_PASSWORD_COLUMNS,
              title=f'Passwords in {profile.directory}')


@click.command()
@click.option('--database',
              default='cookies',
              help='Which cookie database to read.',
              show_default=True,
              type=click.Choice(sorted(COOKIE_DATABASES)))
@click.option('-H', '--host', help='Only show cookies whose host contains this substring.')
@click.option('-l',
              '--limit',
              default=100,
              help='Maximum rows to show. 0 means no limit.',
              type=int)
@click.option('--show-values',
              is_flag=True,
              help='Show decrypted values instead of a masked placeholder.')
@json_option
@profile_option
@pass_user_data
def list_cookies(user_data: ChromeUserData,
                 profile_name: str = 'Default',
                 database: str = 'cookies',
                 host: str | None = None,
                 limit: int = 100,
                 *,
                 as_json: bool = False,
                 show_values: bool = False) -> None:
    """List stored cookies."""
    profile = resolve_profile(user_data, profile_name)
    path = _resolve_database(profile, COOKIE_DATABASES[database])
    crypt = _make_crypt(user_data)
    _warn_if_undecryptable(crypt)
    rows = (row for row in iter_cookies(path, crypt) if not host or host in row['host'])
    if limit > 0:
        rows = (row for _, row in zip(range(limit), rows, strict=False))
    result = [{**row, 'value': _secret(row['value'], reveal=show_values)} for row in rows]
    echo_rows(result,
              as_json=as_json,
              columns=_COOKIE_COLUMNS,
              title=f'Cookies in {profile.directory}')


@click.command()
@click.option('-a',
              '--account',
              is_flag=True,
              help='Read `Account Web Data` instead of `Web Data`.')
@click.option('-t',
              '--table',
              help='Only show this table. Defaults to every non-empty table.',
              type=click.Choice(sorted(PAYMENT_TABLES)))
@click.option('--show-numbers',
              is_flag=True,
              help='Show decrypted card, IBAN, and CVC numbers instead of a masked placeholder.')
@json_option
@profile_option
@pass_user_data
def list_payments(user_data: ChromeUserData,
                  profile_name: str = 'Default',
                  table: str | None = None,
                  *,
                  account: bool = False,
                  as_json: bool = False,
                  show_numbers: bool = False) -> None:
    """List saved payment methods: cards, IBANs, bank accounts, loyalty cards, and offers."""  # ruff:ignore[docstring-missing-exception]
    profile = resolve_profile(user_data, profile_name)
    path = _resolve_database(profile, 'Account Web Data' if account else 'Web Data')
    crypt = _make_crypt(user_data)
    _warn_if_undecryptable(crypt)
    available = set(table_names(path))
    if table and table not in available:
        click.echo(f"'{table}' does not exist in '{path}'.", err=True)
        raise click.Abort
    tables = (table,) if table else tuple(t for t in PAYMENT_TABLES if t in available)
    results: dict[str, list[dict[str, Any]]] = {}
    for name in tables:
        secret_field = PAYMENT_SECRET_FIELDS.get(name)
        rows = [{
            **row, secret_field: _secret(row[secret_field], reveal=show_numbers)
        } if secret_field else dict(row) for row in iter_payment_table(path, name, crypt)]
        if table or rows:
            results[name] = rows
    if not results:
        _suggest_account(profile, 'Account Web Data', account=account)
    if as_json:
        echo_json(results if table is None else results.get(table, []))
        return
    if not results:
        click.echo('No payment data found.', err=True)
        return
    for name, rows in results.items():
        echo_rows(rows, as_json=False, title=name.replace('_', ' ').title())


@click.command()
@click.option('--show-tokens',
              is_flag=True,
              help='Show decrypted sign-in tokens instead of a masked placeholder.')
@json_option
@profile_option
@pass_user_data
def list_accounts(user_data: ChromeUserData,
                  profile_name: str = 'Default',
                  *,
                  as_json: bool = False,
                  show_tokens: bool = False) -> None:
    """List the Google accounts signed in to a profile and their stored sign-in tokens."""
    profile = resolve_profile(user_data, profile_name)
    preferences = _read_preferences(profile)
    accounts = [{
        'account_id': entry.get('account_id'),
        'email': entry.get('email'),
        'full_name': entry.get('full_name'),
        'gaia': entry.get('gaia'),
        'hosted_domain': entry.get('hosted_domain'),
        'is_supervised_child': entry.get('is_supervised_child'),
        'is_under_advanced_protection': entry.get('is_under_advanced_protection'),
        'locale': entry.get('locale'),
        'picture_url': entry.get('picture_url')
    } for entry in preferences.get('account_info', []) if isinstance(entry, dict)]
    path = profile.path / 'Web Data'
    tokens: list[dict[str, Any]] = []
    if is_sqlite_database(path):
        crypt = _make_crypt(user_data)
        _warn_if_undecryptable(crypt)
        tokens = [{
            **row, 'token': _secret(row['token'], reveal=show_tokens)
        } for row in iter_sign_in_tokens(path, crypt)]
    if as_json:
        echo_json({'accounts': accounts, 'profile': dict(profile.info), 'tokens': tokens})
        return
    echo_rows(accounts,
              as_json=False,
              columns=('email', 'full_name', 'gaia', 'hosted_domain'),
              title=f'Accounts in {profile.directory}')
    echo_rows(tokens, as_json=False, title='Sign-in tokens')


@click.command()
@click.option('--addresses', is_flag=True, help='Show addresses instead of autofill entries.')
@click.option('--ai-entities',
              is_flag=True,
              help='Show Autofill AI entities instead of autofill entries.')
@click.option('--show-values',
              is_flag=True,
              help='Show decrypted Autofill AI attribute values instead of a masked placeholder.')
@click.option('--plus-addresses',
              is_flag=True,
              help='Show plus addresses instead of autofill entries.')
@click.option('-l',
              '--limit',
              default=100,
              help='Maximum rows to show. 0 means no limit.',
              type=int)
@click.option('-s',
              '--search',
              help='Only show entries whose name or value contains this substring.')
@json_option
@profile_option
@pass_user_data
def list_autofill(user_data: ChromeUserData,
                  profile_name: str = 'Default',
                  limit: int = 100,
                  search: str | None = None,
                  *,
                  addresses: bool = False,
                  ai_entities: bool = False,
                  as_json: bool = False,
                  plus_addresses: bool = False,
                  show_values: bool = False) -> None:
    """List remembered form data: autofill entries, addresses, plus addresses, or AI entities."""
    profile = resolve_profile(user_data, profile_name)
    path = _resolve_database(profile, 'Web Data')
    if ai_entities:
        crypt = _make_crypt(user_data)
        _warn_if_undecryptable(crypt)
        rows: Any = [{
            **row, 'attributes': {
                key: _secret(value, reveal=show_values)
                for key, value in row['attributes'].items()
            }
        } for row in iter_ai_entities(path, crypt)]
        title = 'Autofill AI Entities'
    elif addresses:
        rows = iter_addresses(path)
        title = 'Addresses'
    elif plus_addresses:
        rows = iter_plus_addresses(path)
        title = 'Plus Addresses'
    else:
        rows = (*iter_autofill(path), *iter_autocomplete(path))
        title = 'Autofill'
    if search:
        rows = (row for row in rows
                if search in str(row.get('name', '')) or search in str(row.get('value', '')))
    if limit > 0:
        rows = (row for _, row in zip(range(limit), rows, strict=False))
    echo_rows(rows, as_json=as_json, title=f'{title} in {profile.directory}')
