"""Uncategorised commands."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
import logging
import subprocess as sp

from deltona.adp import calculate_salary
from deltona.constants import CONTEXT_SETTINGS
from deltona.io import (
    SFVVerificationError,
    UnRAR,
    UnRARExtractionTestFailed,
    extract_gog,
    unpack_0day,
    verify_sfv,
)
from deltona.typing import INCITS38Code
import click

if TYPE_CHECKING:
    from collections.abc import Sequence

log = logging.getLogger(__name__)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option('-H', '--hours', default=160, help='Hours worked in a month.', metavar='HOURS')
@click.option('-r', '--pay-rate', default=70.0, help='Dollars per hour.', metavar='DOLLARS')
@click.option(
    '-s',
    '--state',
    metavar='STATE',
    default='FL',
    type=click.Choice(INCITS38Code.__args__),  # type: ignore[attr-defined]
    help='US state abbreviation.')
def adp_main(hours: int = 160, pay_rate: float = 70.0, state: INCITS38Code = 'FL') -> None:
    """Calculate US salary."""
    click.echo(str(calculate_salary(hours=hours, pay_rate=pay_rate, state=state)))


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('dirs',
                nargs=-1,
                metavar='DIR',
                type=click.Path(exists=True, dir_okay=True, file_okay=False, path_type=Path))
def unpack_0day_main(dirs: Sequence[Path]) -> None:
    """Unpack RAR files from 0day zip file sets."""
    for path in dirs:
        unpack_0day(path)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('filename', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
@click.option('-o',
              '--output-dir',
              default='.',
              type=click.Path(exists=True, file_okay=False, path_type=Path),
              help='Output directory.')
def gogextract_main(filename: Path, output_dir: Path, *, debug: bool = False) -> None:
    """Extract a Linux gog.com archive."""
    logging.basicConfig(level=logging.DEBUG if debug else logging.ERROR)
    extract_gog(filename, output_dir)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('rar_filename', type=click.Path(dir_okay=False, exists=True, path_type=Path))
@click.option('--no-crc-check', is_flag=True, help='Disable CRC check.')
@click.option('--test-extraction', help='Enable extraction test.', is_flag=True)
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
@click.option('-D',
              '--device-name',
              help='Device name.',
              type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option('-s', '--speed', type=int, help='Disc write speed.', default=8)
@click.option('--sfv',
              help='SFV file.',
              type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option('--cdrecord-path', help='Path to cdrecord.', default='cdrecord')
@click.option('--unrar-path', help='Path to unrar.', default='unrar')
def burnrariso_main(rar_filename: Path,
                    unrar_path: str = 'unrar',
                    cdrecord_path: str = 'cdrecord',
                    device_name: Path | None = None,
                    sfv: Path | None = None,
                    speed: int = 8,
                    *,
                    debug: bool = False,
                    no_crc_check: bool = False,
                    test_extraction: bool = False) -> None:
    """Burns an ISO found in a RAR file via piping."""  # noqa: DOC501
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)
    rar_path = Path(rar_filename)
    unrar = UnRAR(unrar_path)
    isos = [x for x in unrar.list_files(rar_path) if x.name.lower().endswith('.iso')]
    if len(isos) != 1:
        raise click.Abort
    iso = isos[0]
    if not iso.size:
        raise click.Abort
    if not no_crc_check:
        sfv_file_expected = (Path(sfv) if sfv else rar_path.parent /
                             f'{rar_path.name.split(".", 1)}.sfv')
        assert sfv_file_expected.exists()
        try:
            verify_sfv(sfv_file_expected)
        except SFVVerificationError as e:
            click.echo('SFV verification failed.', err=True)
            raise click.Abort from e
    if test_extraction:
        click.echo('Testing extraction.')
        try:
            unrar.test_extraction(rar_path, iso.name)
        except UnRARExtractionTestFailed as e:
            click.echo('RAR extraction test failed.', err=True)
            raise click.Abort from e
    with (unrar.pipe(rar_filename, iso.name) as u,
          sp.Popen(
              (cdrecord_path, *((f'dev={device_name}',) if device_name else
                                ()), f'speed={speed}', 'driveropts=burnfree', f'tsize={iso.size}'),
              stdin=u.stdout,
              close_fds=True) as cdrecord):
        assert u.stdout is not None
        u.stdout.close()
        cdrecord.wait()
        u.wait()
        if not (u.returncode == 0 and cdrecord.returncode == 0):
            click.echo('Write failed!', err=True)
            raise click.Abort
