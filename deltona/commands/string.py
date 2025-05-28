"""String commands."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, TextIO
from urllib.parse import unquote_plus, urlparse
import io
import json
import plistlib
import sys

from binaryornot.helpers import is_binary_string
from deltona import naming
from deltona.constants import CONTEXT_SETTINGS
from deltona.string import fullwidth_to_narrow, is_ascii, sanitize, slugify, underscorize
from deltona.typing import DecodeErrorsOption
import click
import yaml

if TYPE_CHECKING:
    from io import BytesIO


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('file', type=click.File('r'), default=sys.stdin)
def is_ascii_main(file: TextIO) -> None:
    """Check if a file is ASCII."""  # noqa: DOC501
    if not is_ascii(file.read()):
        raise click.exceptions.Exit(1)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option('-e', '--encoding', default='utf-8', help='Text encoding.')
@click.option(
    '-r',
    '--errors',
    default='strict',
    type=click.Choice(DecodeErrorsOption.__args__),  # type: ignore[attr-defined]
    help='Error handling mode.')
@click.argument('file', type=click.File('r'), default=sys.stdin)
def urldecode_main(file: TextIO,
                   encoding: str = 'utf-8',
                   errors: DecodeErrorsOption = 'strict') -> None:
    """Decode a URL-encoded string."""
    is_netloc = Path(sys.argv[0]).stem == 'netloc'
    for line in file:
        val = unquote_plus(line, encoding, errors)
        if is_netloc:
            val = urlparse(val).netloc.strip()
        click.echo(val.strip())


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('file', type=click.File('r'), default=sys.stdin)
def underscorize_main(file: TextIO) -> None:
    """Convert a string to an underscorised form."""
    for line in file:
        click.echo(underscorize(line.strip()))


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('file', type=click.File('r'), default=sys.stdin)
@click.option('-d', '--default-flow-style', is_flag=True, help='Enable compact flow style.')
@click.option('-i', '--indent', default=2, type=click.IntRange(2, 9), help='Indent width (spaces).')
def json2yaml_main(file: TextIO, indent: int = 2, *, default_flow_style: bool = False) -> None:
    """Convert JSON to YAML."""
    click.echo(yaml.dump(json.load(file), indent=indent, default_flow_style=default_flow_style))


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('file', type=click.File('r'), default=sys.stdin)
@click.option('-R', '--no-restricted', is_flag=True, help='Do not use restricted character set.')
def sanitize_main(file: TextIO, *, no_restricted: bool = False) -> None:
    """
    Transform a string to a 'sanitised' form.

    By default, a restricted character set safe for Windows filenames is used. Disable with -R.
    """
    click.echo(sanitize(file.read(), restricted=not no_restricted))


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('file', type=click.File('r'), default=sys.stdin)
def trim_main(file: TextIO) -> None:
    """Trim lines in file."""
    for line in file:
        click.echo(line.strip())


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('file', type=click.File('r'), default=sys.stdin)
def ucwords_main(file: TextIO) -> None:
    """
    Run Python ``str.title()`` for lines in file.

    Named after PHP's function.
    """
    for line in file:
        click.echo(line.title(), nl=False)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('file', type=click.File('rb'), default=sys.stdin)
def pl2json_main(file: BytesIO) -> None:
    """
    Convert a Property List file to JSON.

    This command does not do any type conversions. This means files containing <data> objects will
    not work.
    """  # noqa: DOC501
    try:
        click.echo(json.dumps(plistlib.load(file), sort_keys=True, allow_nan=False, indent=2))
    except TypeError as e:
        click.echo('A non-JSON serialisable item is present in the file.', err=True)
        raise click.Abort from e


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('file', type=click.File('rb'), default=sys.stdin)
def is_bin_main(file: BytesIO) -> None:
    """
    Check if a file has binary contents.

    For this utility, 0 byte files do not count as binary.

    Exit code 0 means the file probably contains binary content.
    """  # noqa: DOC501
    file.seek(0, io.SEEK_END)
    if file.tell() == 0:
        click.echo('File is empty. Not counting as binary.', err=True)
        raise click.Abort
    file.seek(0)
    if is_binary_string(file.read(1024)):
        return
    raise click.exceptions.Exit(1)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('file', type=click.File('r'), default=sys.stdin)
def fullwidth2ascii_main(file: TextIO) -> None:
    """Convert fullwidth characters to ASCII."""
    click.echo(fullwidth_to_narrow(file.read()), nl=False)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('file', type=click.File('r'), default=sys.stdin)
@click.option('--no-lower', is_flag=True, help='Disable lowercase.')
def slugify_main(file: TextIO, *, no_lower: bool = False) -> None:
    """Slugify a string."""
    click.echo(slugify(file.read(), no_lower=no_lower))


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('titles', type=click.File('r'), default=sys.stdin)
@click.option('--no-names', help='Disable name checking.', is_flag=True)
@click.option('-E', '--no-english', help='Disable English mode.', is_flag=True)
@click.option('-a', '--arabic', help='Enable Arabic mode.', is_flag=True)
@click.option('-c', '--chinese', help='Enable Chinese mode.', is_flag=True)
@click.option('-j', '--japanese', help='Enable Japanese mode.', is_flag=True)
@click.option('-s', '--ampersands', help='Replace " and " with " & ".', is_flag=True)
def title_fixer_main(titles: tuple[str, ...],
                     *,
                     no_english: bool = False,
                     chinese: bool = False,
                     japanese: bool = False,
                     arabic: bool = False,
                     no_names: bool = False,
                     ampersands: bool = False) -> None:
    """Fix titles."""  # noqa: DOC501
    modes = (
        *((naming.Mode.Arabic,) if arabic else ()),
        *((naming.Mode.Chinese,) if chinese else ()),
        *((naming.Mode.English,) if not no_english else ()),
        *((naming.Mode.Japanese,) if japanese else ()),
    )
    if not modes:
        click.echo('No modes specified.', err=True)
        raise click.Abort
    for title in titles:
        click.echo(naming.adjust_title(title, modes, disable_names=no_names, ampersands=ampersands))
