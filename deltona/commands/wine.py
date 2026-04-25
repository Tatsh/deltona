"""Windows/Wine-related commands."""

from __future__ import annotations

from pathlib import Path
from shlex import quote
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING
import logging
import os
import shutil
import signal
import subprocess as sp

from bascom import setup_logging
from deltona.constants import CONTEXT_SETTINGS
from deltona.string import unix_path_to_wine
from deltona.system import IS_WINDOWS, kill_wine
from deltona.ultraiso import patch_ultraiso_font
from deltona.utils import unregister_wine_file_associations
from deltona.windows import DEFAULT_DPI, Field, make_font_entry
import click

if TYPE_CHECKING:
    from collections.abc import Sequence
    from types import FrameType

log = logging.getLogger(__name__)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
def unregister_wine_file_associations_main(*, debug: bool = False) -> None:
    """Unregister Wine file associations. Terminates all Wine processes before starting."""
    setup_logging(debug=debug, loggers={'deltona': {}})
    unregister_wine_file_associations(debug=debug)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('prefix_name')
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
def wineshell_main(prefix_name: str, *, debug: bool = False) -> None:
    """
    Start a new shell with WINEPREFIX set up.

    For Bash and similar shells only.
    """  # noqa: DOC501
    import pexpect  # noqa: PLC0415

    setup_logging(debug=debug, loggers={'deltona': {}, 'pexpect': {}})
    target = (Path(prefix_name) if Path(prefix_name).exists() else
              Path('~/.local/share/wineprefixes').expanduser() / prefix_name)
    terminal = shutil.get_terminal_size()
    c = pexpect.spawn(os.environ.get('SHELL', '/bin/bash'), ['-i'],
                      dimensions=(terminal.lines, terminal.columns))
    c.sendline(f'export WINEPREFIX={quote(str(target))}; export PS1="{target.name}🍷$PS1"')

    def resize(sig: int, frame: FrameType | None) -> None:  # pragma: no cover  # noqa: ARG001
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
    setup_logging(debug=debug, loggers={'deltona': {}})
    if 'DISPLAY' not in os.environ or 'XAUTHORITY' not in os.environ:  # pragma: no cover
        log.warning(
            'Wine will likely fail to run since DISPLAY or XAUTHORITY are not in the environment.')
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
    setup_logging(debug=debug, loggers={'deltona': {}})
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
    setup_logging(debug=debug, loggers={'deltona': {}})
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
