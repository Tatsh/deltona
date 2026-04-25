"""Uncategorised commands."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any
import asyncio
import json
import logging
import shutil
import subprocess as sp

from bascom import setup_logging
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
from deltona.refactor import remove_trailing_commas_in_paths
from deltona.typing import INCITS38Code, assert_not_none
import click
import tomlkit
import tomlkit.exceptions

if TYPE_CHECKING:
    from collections.abc import Sequence

log = logging.getLogger(__name__)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
@click.option('-H',
              '--hours',
              default=160,
              type=int,
              help='Hours worked in a month.',
              metavar='HOURS')
@click.option('-r',
              '--pay-rate',
              default=70.0,
              type=float,
              help='Dollars per hour.',
              metavar='DOLLARS')
@click.option(
    '-s',
    '--state',
    metavar='STATE',
    default='FL',
    type=click.Choice(INCITS38Code.__args__),  # type: ignore[attr-defined]
    help='US state abbreviation.')
def adp_main(hours: int = 160,
             pay_rate: float = 70.0,
             state: INCITS38Code = 'FL',
             *,
             debug: bool = False) -> None:
    """Calculate US salary."""
    setup_logging(debug=debug, loggers={'deltona': {}, 'urllib3': {}})
    click.echo(str(asyncio.run(calculate_salary(hours=hours, pay_rate=pay_rate, state=state))))


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
    setup_logging(debug=debug, loggers={'deltona': {}})
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
    setup_logging(debug=debug, loggers={'deltona': {}})
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
        if not sfv_file_expected.exists():
            msg = 'Expected SFV file is missing.'
            raise FileNotFoundError(msg)
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
        stdout = assert_not_none(u.stdout)
        stdout.close()
        cdrecord.wait()
        u.wait()
        if not (u.returncode == 0 and cdrecord.returncode == 0):
            click.echo('Write failed!', err=True)
            raise click.Abort


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('paths', nargs=-1, required=True, type=click.Path(exists=True, path_type=Path))
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
@click.option('--no-format',
              is_flag=True,
              help='Skip running `yarn format` and `yarn ruff:fix` after editing.')
@click.option('--no-gitignore',
              is_flag=True,
              help='Do not respect `.gitignore` files when walking directories.')
@click.option('--no-dot',
              is_flag=True,
              help='Skip files and directories whose names begin with `.`.')
def remove_trailing_commas_main(paths: Sequence[Path],
                                *,
                                debug: bool = False,
                                no_format: bool = False,
                                no_gitignore: bool = False,
                                no_dot: bool = False) -> None:
    """Remove non-required trailing commas from Python source files."""
    setup_logging(debug=debug, loggers={'deltona': {}})
    originals = asyncio.run(
        remove_trailing_commas_in_paths(
            paths,
            use_gitignore=not no_gitignore,
            allow_dot=not no_dot,
            extra_excludes=() if no_format else _gather_format_exclusions()))
    if originals and not no_format:
        _run_post_format_steps()
    changed = sum(1 for f, original in originals.items() if _read_or_empty(f) != original)
    click.echo(f'Modified {changed} {"file" if changed == 1 else "files"}.')


def _read_or_empty(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return ''


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        return dict(tomlkit.parse(path.read_text(encoding='utf-8')))
    except (OSError, tomlkit.exceptions.TOMLKitError) as e:
        log.debug('Could not parse `%s`: %s.', path, e)
        return {}


def _project_root() -> Path | None:
    cur = Path.cwd().resolve()
    for candidate in (cur, *cur.parents):
        for name in ('pyproject.toml', 'ruff.toml', '.ruff.toml'):
            if (candidate / name).is_file():
                return candidate
    return None


def _add_patterns(patterns: list[str], source: str, new: list[str]) -> None:
    if not new:
        return
    log.debug('Adding %d exclude pattern(s) from `%s`: %s.', len(new), source, new)
    patterns.extend(new)


def _gather_format_exclusions() -> list[str]:
    root = _project_root()
    if root is None:
        log.debug('No project root found; skipping format-tool exclusions.')
        return []
    log.debug('Gathering format-tool exclusions from `%s`.', root)
    patterns: list[str] = []
    pyproject = root / 'pyproject.toml'
    if pyproject.is_file():
        data = _load_toml(pyproject)
        tool = data.get('tool')
        if isinstance(tool, dict):
            yapfignore = tool.get('yapfignore')
            if isinstance(yapfignore, dict):
                _add_patterns(patterns, 'pyproject.toml:tool.yapfignore.ignore_patterns',
                              _string_list(yapfignore.get('ignore_patterns')))
            ruff = tool.get('ruff')
            if isinstance(ruff, dict):
                _add_patterns(patterns, 'pyproject.toml:tool.ruff.exclude',
                              _string_list(ruff.get('exclude')))
                _add_patterns(patterns, 'pyproject.toml:tool.ruff.extend-exclude',
                              _string_list(ruff.get('extend-exclude')))
                ruff_format = ruff.get('format')
                if isinstance(ruff_format, dict):
                    _add_patterns(patterns, 'pyproject.toml:tool.ruff.format.exclude',
                                  _string_list(ruff_format.get('exclude')))
    for name in ('ruff.toml', '.ruff.toml'):
        rf = root / name
        if rf.is_file():
            data = _load_toml(rf)
            _add_patterns(patterns, f'{name}:exclude', _string_list(data.get('exclude')))
            _add_patterns(patterns, f'{name}:extend-exclude',
                          _string_list(data.get('extend-exclude')))
            rf_format = data.get('format')
            if isinstance(rf_format, dict):
                _add_patterns(patterns, f'{name}:format.exclude',
                              _string_list(rf_format.get('exclude')))
    log.debug('Final format-tool exclusions (%d): %s.', len(patterns), patterns)
    return patterns


def _package_json_scripts() -> dict[str, str]:
    cur = Path.cwd().resolve()
    for candidate in (cur, *cur.parents):
        pj = candidate / 'package.json'
        if pj.is_file():
            try:
                data = json.loads(pj.read_text())
            except (OSError, json.JSONDecodeError):
                return {}
            scripts = data.get('scripts') if isinstance(data, dict) else None
            return scripts if isinstance(scripts, dict) else {}
    return {}


def _run_post_format_steps() -> None:
    yarn = shutil.which('yarn')
    if yarn is None:
        log.warning('`yarn` not found in PATH; skipping format and lint steps.')
        return
    scripts = _package_json_scripts()
    output = None if log.isEnabledFor(logging.DEBUG) else sp.DEVNULL
    if 'format' in scripts:
        click.echo('Running `yarn format`.')
        sp.run((yarn, 'format'), check=True, stdout=output, stderr=output)
    else:
        log.info('No `format` script in `package.json`; skipping.')
    if 'ruff:fix' in scripts:
        click.echo('Running `yarn ruff:fix`.')
        result = sp.run((yarn, 'ruff:fix'), check=False, stdout=output, stderr=output)
        if result.returncode != 0:
            log.warning('`yarn ruff:fix` exited with code %d; some issues may remain.',
                        result.returncode)
    else:
        log.info('No `ruff:fix` script in `package.json`; skipping.')
