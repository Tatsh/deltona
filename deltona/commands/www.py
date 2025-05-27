"""Chromium-related commands."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING
import json
import logging

from deltona.chromium import fix_chromium_pwa_icon
from deltona.constants import CONTEXT_SETTINGS
from deltona.system import CHROME_DEFAULT_CONFIG_PATH, CHROME_DEFAULT_LOCAL_STATE_PATH, IS_WINDOWS
from deltona.utils import kill_processes_by_name
from deltona.www import check_bookmarks_html_urls, where_from
import click

if TYPE_CHECKING:
    from collections.abc import Sequence

    from deltona.typing import ChromeLocalState


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('files',
                metavar='FILE',
                nargs=-1,
                type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path))
@click.option('-w', '--webpage', is_flag=True, help='Print the webpage URL (macOS only).')
def where_from_main(files: Sequence[Path], *, webpage: bool = False) -> None:
    """Display URL where a file was downloaded from."""
    has_multiple = len(files) > 1
    for arg in files:
        if has_multiple:
            click.echo(f'{arg}: ', nl=False)
        click.echo(where_from(arg, webpage=webpage))


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('local_state_path',
                type=click.Path(dir_okay=False, exists=True, path_type=Path),
                metavar='LOCAL_STATE_PATH',
                default=CHROME_DEFAULT_LOCAL_STATE_PATH)
@click.option('-s',
              '--subprocess-name',
              default='chrome' if not IS_WINDOWS else 'chrome.exe',
              help='Chromium-based browser subprocess name such as "chrome"')
@click.option('--sleep-time',
              default=0.5,
              type=float,
              help='Time to sleep after attempting to kill the browser processes in seconds.')
def chrome_bisect_flags_main(local_state_path: Path,
                             subprocess_name: str = 'chrome',
                             sleep_time: float = 0.5) -> None:
    """
    Determine which flag is causing an issue in Chrome or any Chromium-based browser.

    Only supports removing flags (setting back to default) and not setting them to 'safe' values.
    """  # noqa: DOC501
    flags_min_len = 2

    def start_test(flags: Sequence[str], local_state: ChromeLocalState) -> tuple[bool, str | None]:
        """
        Test apparatus.

        Returns ``True`` if:
        - there are no more flags (problem flag not found)
        - if there is only one flag left (problem flag possibly found)
        - if the problematic flag exists within the passed in flags
        """
        len_flags = len(flags)
        click.echo('Testing flags:')
        for flag in flags:
            click.echo(f'- {flag}')
        local_state['browser']['enabled_labs_experiments'] = flags
        with local_state_path.open('w+', encoding='utf-8') as f:
            json.dump(local_state, f, allow_nan=False)
        click.confirm('Start browser and test for the issue, then press enter', show_default=False)
        kill_processes_by_name(subprocess_name, sleep_time, force=True)
        at_fault = click.confirm('Did the problem occur?')
        return at_fault, flags[0] if at_fault and len_flags == 1 else None

    def do_test(flags: Sequence[str], local_state: ChromeLocalState) -> str | None:
        len_flags = len(flags)
        if len_flags < flags_min_len:
            return flags[0] if len_flags == 1 else None
        done, bad_flag = start_test(flags[:len_flags // 2], deepcopy(local_state))
        if done:
            return bad_flag or do_test(flags[:len_flags // 2], local_state)
        done, bad_flag = start_test(flags[len_flags // 2:], deepcopy(local_state))
        if done:
            return bad_flag or do_test(flags[len_flags // 2:], local_state)
        return None

    p_ls = local_state_path.resolve(strict=True)
    click.echo(f'Using "{local_state_path}".')
    with p_ls.open(encoding='utf-8') as f:
        local_state_data = json.load(f)
        flags = local_state_data['browser']['enabled_labs_experiments']
        len_flags = len(flags)
        if len_flags == 0:
            click.echo('Nothing to test.', err=True)
            raise click.Abort
    bad_flag = None
    try:
        click.confirm('Exit the browser and press enter', show_default=False)
        bad_flag = do_test(flags, local_state_data)
    except KeyboardInterrupt as e:  # pragma: no cover
        raise click.Abort from e
    finally:
        if bad_flag:
            local_state_data['browser']['enabled_labs_experiments'] = [
                x for x in local_state_data['browser']['enabled_labs_experiments'] if x != bad_flag
            ]
        with p_ls.open('w+', encoding='utf-8') as f:
            json.dump(local_state_data, f, sort_keys=True, indent=2, allow_nan=False)
        if not bad_flag:
            click.echo('Restored original "Local State".')
        else:
            click.echo(f'Saved "Local State" with "{bad_flag}" removed.')


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('app_id')
@click.argument('icon_src_uri')
@click.option('-M', '--monochrome', help='Copy icons to monochrome directory.', is_flag=True)
@click.option('-c',
              '--config-path',
              help='Chromium browser configuration path. Defaults to Google Chrome.',
              default=CHROME_DEFAULT_CONFIG_PATH,
              type=click.Path(exists=True, path_type=Path))
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
@click.option('-m', '--masked', help='Copy icons to masked directory.', is_flag=True)
@click.option('-p', '--profile', help='Profile name.', default='Default')
def fix_chromium_pwa_icon_main(config_path: Path,
                               app_id: str,
                               icon_src_uri: str,
                               profile: str = 'Default',
                               *,
                               debug: bool = False,
                               masked: bool = False,
                               monochrome: bool = False) -> None:
    """
    Fix a Chromium PWA icon that failed to sync.

    For more information see https://issues.chromium.org/issues/40595456.
    """
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)
    fix_chromium_pwa_icon(config_path,
                          app_id,
                          icon_src_uri,
                          profile,
                          masked=masked,
                          monochrome=monochrome)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('filename', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
def check_bookmarks_html_main(filename: Path, *, debug: bool = False) -> None:
    """Check for URLs that are not valid any more (status 404) and redirections."""
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)
    _, changed, not_found = check_bookmarks_html_urls(Path(filename).read_text(encoding='utf-8'))
    click.echo(f'{len(changed)} URLs changed.')
    click.echo(f'{len(not_found)} URLs resulted in 404 response.')
