"""Uncategorised commands."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
import ast
import asyncio
import json
import logging
import shutil
import subprocess as sp
import tokenize

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
from deltona.refactor import remove_trailing_commas
from deltona.typing import INCITS38Code, assert_not_none
import click
import pathspec

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

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
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files.extend(_walk_directory(p, use_gitignore=not no_gitignore, allow_dot=not no_dot))
        else:
            files.append(p)
    originals = asyncio.run(_process_files(files))
    if originals and not no_format:
        _run_post_format_steps()
    changed = sum(1 for f, original in originals.items() if _read_or_empty(f) != original)
    click.echo(f'Modified {changed} {"file" if changed == 1 else "files"}.')


def _rewrite_one(path: Path) -> tuple[Path, str] | None:
    log.debug('Processing `%s`.', path)
    try:
        src = path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as e:
        log.debug('Skipped `%s`: %s.', path, e)
        return None
    try:
        ast.parse(src)
    except (SyntaxError, ValueError) as e:
        log.debug('Skipped `%s`: not valid Python (%s).', path, e)
        return None
    try:
        new = ''.join(remove_trailing_commas(src))
    except (SyntaxError, tokenize.TokenError) as e:
        log.debug('Skipped `%s`: %s.', path, e)
        return None
    if new == src:
        return None
    path.write_text(new, encoding='utf-8')
    return path, src


async def _process_files(files: list[Path]) -> dict[Path, str]:
    results = await asyncio.gather(*(asyncio.to_thread(_rewrite_one, f) for f in files))
    return {path: original for entry in results if entry is not None for path, original in (entry,)}


def _read_or_empty(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return ''


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
    if 'format' in scripts:
        click.echo('Running `yarn format`.')
        sp.run((yarn, 'format'), check=True)
    else:
        log.info('No `format` script in `package.json`; skipping.')
    if 'ruff:fix' in scripts:
        click.echo('Running `yarn ruff:fix`.')
        result = sp.run((yarn, 'ruff:fix'), check=False)
        if result.returncode != 0:
            log.warning('`yarn ruff:fix` exited with code %d; some issues may remain.',
                        result.returncode)
    else:
        log.info('No `ruff:fix` script in `package.json`; skipping.')


def _git_repo_root(start: Path) -> Path | None:
    cur = start.resolve()
    for c in (cur, *cur.parents):
        if (c / '.git').exists():
            return c
    return None


def _build_gitignore_spec(start: Path, repo_root: Path) -> pathspec.PathSpec | None:
    chain = [repo_root]
    relative = start.resolve().relative_to(repo_root)
    for part in relative.parts:
        chain.append(chain[-1] / part)
    patterns: list[str] = ['.git']
    for level in chain:
        gi = level / '.gitignore'
        if gi.is_file():
            try:
                patterns.extend(gi.read_text().splitlines())
            except OSError as e:
                log.debug('Could not read `%s`: %s.', gi, e)
    return pathspec.PathSpec.from_lines('gitignore', patterns)


def _walk_directory(start: Path, *, use_gitignore: bool, allow_dot: bool) -> Iterator[Path]:
    repo_root = _git_repo_root(start) if use_gitignore else None
    spec = _build_gitignore_spec(start, repo_root) if repo_root is not None else None
    base = repo_root if repo_root is not None else start.resolve()
    for c in start.rglob('*'):
        if not c.is_file():
            continue
        try:
            rel = c.resolve().relative_to(base)
        except ValueError:
            yield c
            continue
        parts = rel.parts
        if not allow_dot and any(part.startswith('.') for part in parts):
            continue
        if spec is not None and spec.match_file(str(rel)):
            continue
        yield c
