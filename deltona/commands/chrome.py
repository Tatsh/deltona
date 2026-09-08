"""The ``chrome-dump`` command group."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bascom import setup_logging
from typing_extensions import override
import click

from deltona.chrome import ChromeUserData
from deltona.constants import CONTEXT_SETTINGS

if TYPE_CHECKING:
    from deltona.chrome.typing import ChromeChannel

__all__ = ('chrome_dump',)

_SUBCOMMANDS: dict[str, str] = {
    'bookmarks': 'deltona.commands.chrome_browsing:bookmarks',
    'list-accounts': 'deltona.commands.chrome_secrets:list_accounts',
    'list-autofill': 'deltona.commands.chrome_secrets:list_autofill',
    'list-cache': 'deltona.commands.chrome_network:list_cache',
    'list-cookies': 'deltona.commands.chrome_secrets:list_cookies',
    'list-databases': 'deltona.commands.chrome_core:list_databases',
    'list-dips': 'deltona.commands.chrome_network:list_dips',
    'list-downloads': 'deltona.commands.chrome_browsing:list_downloads',
    'list-extensions': 'deltona.commands.chrome_settings:list_extensions',
    'list-files': 'deltona.commands.chrome_core:list_files',
    'list-flags': 'deltona.commands.chrome_flags:list_flags',
    'list-history': 'deltona.commands.chrome_browsing:list_history',
    'list-network-state': 'deltona.commands.chrome_network:list_network_state',
    'list-passwords': 'deltona.commands.chrome_secrets:list_passwords',
    'list-payments': 'deltona.commands.chrome_secrets:list_payments',
    'list-permissions': 'deltona.commands.chrome_settings:list_permissions',
    'list-profiles': 'deltona.commands.chrome_core:list_profiles',
    'list-reporting': 'deltona.commands.chrome_network:list_reporting',
    'list-search-engines': 'deltona.commands.chrome_settings:list_search_engines',
    'list-sessions': 'deltona.commands.chrome_network:list_sessions',
    'list-shortcuts': 'deltona.commands.chrome_browsing:list_shortcuts',
    'list-top-sites': 'deltona.commands.chrome_browsing:list_top_sites',
    'list-web-apps': 'deltona.commands.chrome_settings:list_web_apps',
    'local-state': 'deltona.commands.chrome_core:local_state',
    'preferences': 'deltona.commands.chrome_core:preferences',
    'query': 'deltona.commands.chrome_core:query',
    'spell-check': 'deltona.commands.chrome_browsing:spell_check'
}


class _LazyGroup(click.Group):
    def __init__(self,
                 *args: Any,
                 lazy_subcommands: dict[str, str] | None = None,
                 **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._lazy_subcommands = lazy_subcommands or {}

    @override
    def list_commands(self, ctx: click.Context) -> list[str]:
        return sorted(self._lazy_subcommands)

    @override
    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        if cmd_name not in self._lazy_subcommands:
            return None
        module_path, attribute = self._lazy_subcommands[cmd_name].rsplit(':', 1)
        command: click.Command = getattr(import_module(module_path), attribute)
        command.name = cmd_name
        return command


@click.group(cls=_LazyGroup, lazy_subcommands=_SUBCOMMANDS, context_settings=CONTEXT_SETTINGS)
@click.option('-C',
              '--cache-path',
              help='Cache directory. Defaults to the location for the chosen channel.',
              type=click.Path(file_okay=False, path_type=Path))
@click.option('-c',
              '--config-path',
              help='User data directory. Defaults to the location for the chosen channel.',
              type=click.Path(file_okay=False, path_type=Path))
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
@click.option('--channel',
              default='stable',
              help='Browser release channel used to find the default directories.',
              show_default=True,
              type=click.Choice(('beta', 'canary', 'chromium', 'dev', 'stable')))
@click.pass_context
def chrome_dump(ctx: click.Context,
                cache_path: Path | None = None,
                config_path: Path | None = None,
                channel: ChromeChannel = 'stable',
                *,
                debug: bool = False) -> None:
    """Dump settings and cache information from Chrome and Chromium."""
    setup_logging(debug=debug, loggers={'deltona': {}})
    ctx.obj = ChromeUserData(config_path, cache_path, channel)
