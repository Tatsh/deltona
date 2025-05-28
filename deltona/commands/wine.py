"""Windows/Wine-related commands."""
from __future__ import annotations

from pathlib import Path
from shlex import quote
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Any, get_args
import logging
import os
import shutil
import signal
import subprocess as sp
import sys

from deltona.constants import CONTEXT_SETTINGS
from deltona.string import unix_path_to_wine
from deltona.system import IS_WINDOWS, kill_wine
from deltona.ultraiso import patch_ultraiso_font
from deltona.utils import WineWindowsVersion, create_wine_prefix, unregister_wine_file_associations
from deltona.windows import DEFAULT_DPI, Field, make_font_entry
import click
import pexpect

if TYPE_CHECKING:
    from collections.abc import Sequence

log = logging.getLogger(__name__)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('prefix_name')
@click.option('-D', '--dpi', default=DEFAULT_DPI, type=int, help='DPI.')
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
@click.option('--disable-explorer',
              is_flag=True,
              help='Disable starting explorer.exe automatically.')
@click.option('--disable-services',
              is_flag=True,
              help=('Disable starting services.exe automatically (only useful for simple CLI '
                    'programs with --disable-explorer).'))
@click.option('-E', '--eax', is_flag=True, help='Enable EAX.')
@click.option('-g', '--gtk', is_flag=True, help='Enable Gtk+ theming.')
@click.option('-r', '--prefix-root', type=click.Path(path_type=Path), help='Prefix root.')
@click.option('-S', '--sandbox', is_flag=True, help='Sandbox the prefix.')
@click.option('--no-gecko', is_flag=True, help='Disable downloading Gecko automatically.')
@click.option('--no-mono', is_flag=True, help='Disable downloading Mono automatically.')
@click.option('--no-xdg', is_flag=True, help='Disable winemenubuilder.exe.')
@click.option('--no-assocs',
              is_flag=True,
              help=('Disable creating file associations, but still allow menu entries to be made'
                    ' (unless --no-xdg is also passed).'))
@click.option('-N', '--nvapi', help='Add dxvk-nvapi.', is_flag=True)
@click.option('-o', '--noto', is_flag=True, help='Use Noto Sans in place of most fonts.')
@click.option('-T', '--trick', 'tricks', help='Add an argument for winetricks.', multiple=True)
@click.option('-t', '--tmpfs', is_flag=True, help='Make Wine use tmpfs.')
@click.option('-V',
              '--windows-version',
              default='10',
              type=click.Choice(get_args(WineWindowsVersion)),
              help='Windows version.')
@click.option('--vd',
              metavar='SIZE',
              nargs=1,
              default='off',
              help='Virtual desktop size, e.g. 1024x768.')
@click.option('-W', '--winrt-dark', is_flag=True, help='Enable dark mode for WinRT apps.')
@click.option('-x', '--dxva-vaapi', is_flag=True, help='Enable DXVA2 support with VA-API.')
@click.option('--32', '_32bit', help='Use 32-bit prefix.', is_flag=True)
def mkwineprefix_main(prefix_name: str,
                      prefix_root: Path,
                      tricks: tuple[str, ...],
                      vd: str = 'off',
                      windows_version: WineWindowsVersion = '10',
                      *,
                      _32bit: bool = False,
                      asio: bool = False,
                      debug: bool = False,
                      disable_explorer: bool = False,
                      disable_services: bool = False,
                      dpi: int = DEFAULT_DPI,
                      dxva_vaapi: bool = False,
                      eax: bool = False,
                      gtk: bool = False,
                      no_assocs: bool = False,
                      no_gecko: bool = False,
                      no_mono: bool = False,
                      no_xdg: bool = False,
                      noto: bool = False,
                      nvapi: bool = False,
                      sandbox: bool = False,
                      tmpfs: bool = False,
                      winrt_dark: bool = False) -> None:
    """
    Create a Wine prefix with custom settings.

    This should be used with eval: eval $(mkwineprefix ...)
    """  # noqa: DOC501
    logging.basicConfig(level=logging.DEBUG if debug else logging.ERROR)
    try:
        target = create_wine_prefix(prefix_name,
                                    _32bit=_32bit,
                                    asio=asio,
                                    disable_explorer=disable_explorer,
                                    disable_services=disable_services,
                                    dpi=dpi,
                                    dxva_vaapi=dxva_vaapi,
                                    dxvk_nvapi=nvapi,
                                    eax=eax,
                                    gtk=gtk,
                                    no_associations=no_assocs,
                                    no_gecko=no_gecko,
                                    no_mono=no_mono,
                                    no_xdg=no_xdg,
                                    noto_sans=noto,
                                    prefix_root=prefix_root,
                                    sandbox=sandbox,
                                    tmpfs=tmpfs,
                                    tricks=tricks,
                                    vd=vd,
                                    windows_version=windows_version,
                                    winrt_dark=winrt_dark)
    except FileExistsError as e:
        raise click.Abort from e
    except sp.CalledProcessError as e:
        click.echo(f'Exception: {e}', err=True)
        click.echo(f'STDERR: {e.stderr}', err=True)
        click.echo(f'STDOUT: {e.stdout}', err=True)
        raise click.Abort from e
    wineprefix_env = quote(f'WINEPREFIX={target}')
    click.echo(f"""Run `export WINEPREFIX={target}` before running wine or use env:

env {wineprefix_env} wine ...

If you ran this with eval, your shell is ready.""",
               file=sys.stderr)
    click.echo(f'export {wineprefix_env}')
    click.echo(f'export PS1="{prefix_name}🍷$PS1"')


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
def unregister_wine_file_associations_main(*, debug: bool = False) -> None:
    """Unregister Wine file associations. Terminates all Wine processes before starting."""
    logging.basicConfig(level=logging.DEBUG if debug else logging.ERROR)
    unregister_wine_file_associations(debug=debug)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('prefix_name')
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
def wineshell_main(prefix_name: str, *, debug: bool = False) -> None:
    """
    Start a new shell with WINEPREFIX set up.

    For Bash and similar shells only.
    """  # noqa: DOC501
    logging.basicConfig(level=logging.DEBUG if debug else logging.ERROR)
    target = (Path(prefix_name) if Path(prefix_name).exists() else
              Path('~/.local/share/wineprefixes').expanduser() / prefix_name)
    terminal = shutil.get_terminal_size()
    c = pexpect.spawn(os.environ.get('SHELL', '/bin/bash'), ['-i'],
                      dimensions=(terminal.lines, terminal.columns))
    c.sendline(f'export WINEPREFIX={quote(str(target))}; export PS1="{target.name}🍷$PS1"')

    def resize(sig: Any, data: Any) -> None:  # pragma: no cover
        terminal = shutil.get_terminal_size()
        c.setwinsize(terminal.lines, terminal.columns)

    signal.signal(signal.SIGWINCH, resize)
    c.interact(escape_character=None)
    c.close()
    if c.status is not None and c.status != 0:
        raise click.exceptions.Exit(c.status)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('filepath')
def unix2wine_main(filepath: str) -> None:
    """Convert a UNIX path to an absolute Wine path."""
    click.echo(unix_path_to_wine(filepath))


@click.command(context_settings=CONTEXT_SETTINGS | {'ignore_unknown_options': True})
@click.argument('args', nargs=-1, type=click.UNPROCESSED)
@click.argument('filename', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option('-S',
              '--very-silent',
              help='Pass /VERYSILENT (no windows will be displayed).',
              is_flag=True)
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
@click.option('-p', '--prefix', help='Wine prefix path or name.')
def winegoginstall_main(args: Sequence[str],
                        filename: Path,
                        prefix: str,
                        *,
                        debug: bool = False,
                        very_silent: bool = False) -> None:
    """
    Silent installer for GOG InnoSetup-based releases.

    This calls the installer with the following arguments:

    .. code-block:: text

       /CLOSEAPPLICATIONS /FORCECLOSEAPPLICATIONS /NOCANCEL /NORESTART /SILENT
    """  # noqa: DOC501
    logging.basicConfig(level=logging.DEBUG if debug else logging.ERROR)
    if 'DISPLAY' not in os.environ or 'XAUTHORITY' not in os.environ:
        log.warning('Wine will likely fail to run since DISPLAY or XAUTHORITY are not in the '
                    'environment.')
    env = {
        'DISPLAY': os.environ.get('DISPLAY', ''),
        'XAUTHORITY': os.environ.get('XAUTHORITY', ''),
        'WINEDEBUG': 'fixme-all'
    }
    very_silent_args = ('/SP-', '/SUPPRESSMSGBOXES', '/VERYSILENT') if very_silent else ('/SILENT',)
    if prefix:
        env['WINEPREFIX'] = (prefix if Path(prefix).exists() else str(
            (Path('~/.local/share/wineprefixes') / prefix).expanduser()))
    cmd = ('wine', str(filename), '/CLOSEAPPLICATIONS', '/FORCECLOSEAPPLICATIONS', '/NOCANCEL',
           '/NORESTART', *very_silent_args, *args)
    log.debug('Running: %s', ' '.join(quote(x) for x in cmd))
    click.echo('Be very patient especially if this release is large.', err=True)
    try:
        sp.run(cmd, check=True, env=env)
    except sp.CalledProcessError as e:
        click.echo(f'STDERR: {e.stderr}', err=True)
        click.echo(f'STDOUT: {e.stdout}', err=True)
        raise click.exceptions.Exit(e.returncode) from e


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option('--dpi',
              default=DEFAULT_DPI,
              type=int,
              help='DPI. This should generally be left as 96.')
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
@click.option('-f', '--font', default='Noto Sans', help='Font to use.')
@click.option('-s', '--font-size', default=9, type=int, help='Font size in points.')
def set_wine_fonts_main(dpi: int = DEFAULT_DPI,
                        font: str = 'Noto Sans',
                        font_size: int = 9,
                        *,
                        debug: bool = False) -> None:
    """
    Set all Wine fonts to be the one passed in.

    This will run on Windows but it is not recommended to try on newer than Windows 7.
    """
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)
    with NamedTemporaryFile(mode='w+',
                            suffix='.reg',
                            prefix='set-wine-fonts',
                            delete=False,
                            encoding='utf-8') as f:
        f.write('Windows Registry Editor Version 5.00\n\n')
        f.write(r'[HKEY_CURRENT_USER\Control Panel\Desktop\WindowMetrics]')
        f.write('\n')
        f.write(''.join(
            make_font_entry(item, font, dpi=dpi, font_size_pt=font_size) for item in Field))
        f.write('\n')
    cmd = ('wine', 'regedit', '/S', f.name) if not IS_WINDOWS else ('regedit', '/S', f.name)
    log.debug('Registry file content:\n%s', Path(f.name).read_text(encoding='utf-8').strip())
    log.debug('Running: %s', ' '.join(quote(x) for x in cmd))
    env = {'HOME': os.environ['HOME']}
    if 'DISPLAY' not in os.environ or 'XAUTHORITY' not in os.environ:
        log.warning(
            'UltraISO.exe will likely fail to run since DISPLAY or XAUTHORITY are not in the '
            'environment.')
    if 'WINEPREFIX' in os.environ:
        env['WINEPREFIX'] = os.environ['WINEPREFIX']
    env['DISPLAY'] = os.environ.get('DISPLAY', '')
    env['XAUTHORITY'] = os.environ.get('XAUTHORITY', '')
    env['WINEDEBUG'] = 'fixme-all'
    env['PATH'] = os.environ.get('PATH', '')
    sp.run(cmd, check=True, env=env)
    Path(f.name).unlink()
    click.echo('Fonts set. Restart Wine applications for changes to take effect.')


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
@click.option('-e',
              '--exe',
              help='EXE to patch.',
              type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option('-f', '--font', default='Noto Sans Regular', help='Font to use.')
def patch_ultraiso_font_main(exe: Path | None = None,
                             font: str = 'Noto Sans',
                             *,
                             debug: bool = False) -> None:
    """Patch UltraISO's hard-coded font."""
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)
    if not exe:
        if not IS_WINDOWS:
            exe = (Path(os.environ.get('WINEPREFIX', str(Path.home() / '.wine'))) / 'drive_c' /
                   'Program Files (x86)' / 'UltraISO' / 'UltraISO.exe')
        else:
            exe = (Path(os.environ.get('PROGRAMFILES(X86)', os.environ.get('PROGRAMFILES', ''))) /
                   'UltraISO' / 'UltraISO.exe')
    patch_ultraiso_font(exe, font)


@click.command(context_settings=CONTEXT_SETTINGS)
def kill_wine_main() -> None:
    """Terminate all Wine processes."""
    kill_wine()
