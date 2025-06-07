"""Media commands."""
from __future__ import annotations

from operator import itemgetter
from pathlib import Path
from shlex import quote
from typing import TYPE_CHECKING, Any, Literal, TypeVar, cast, override
import getpass
import json
import logging
import re
import subprocess as sp
import sys
import unicodedata

from deltona.constants import CONTEXT_SETTINGS
from deltona.io import make_sfv, unpack_ebook
from deltona.media import (
    add_info_json_to_media_file,
    archive_dashcam_footage,
    cddb_query,
    create_static_text_video,
    get_info_json,
    hlg_to_sdr,
    rip_cdda_to_flac,
    supported_audio_input_formats,
)
from deltona.string import underscorize
from deltona.system import IS_WINDOWS, wait_for_disc
from deltona.ultraiso import InsufficientArguments, run_ultraiso
from deltona.utils import TIMES_RE, add_cdda_times
from send2trash import send2trash
import click
import requests

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

log = logging.getLogger(__name__)
_T = TypeVar('_T', bound=str)


class _CDDATimeStringParamType(click.ParamType):
    name = 'cdda_time_string'

    @override
    def convert(self, value: _T, param: click.Parameter | None, ctx: click.Context | None) -> _T:
        if TIMES_RE.match(value):
            return value
        self.fail(f'{value!r} is not a valid CDDA time string.', param, ctx)
        return None  # type: ignore[unreachable] # pragma: no cover


@click.command(context_settings=CONTEXT_SETTINGS,
               epilog='Example invocation: add-cdda-times 01:02:73 02:05:09')
@click.argument('times', nargs=-1, type=_CDDATimeStringParamType())
def add_cdda_times_main(times: tuple[str, ...]) -> None:
    """Add CDDA timestamps together.

    A CDDA timestamp is 3 zero-prefixed integers MM:SS:FF, separated by colons. FF is the number of
    frames out of 75.
    """  # noqa: DOC501
    if (result := add_cdda_times(times)) is None:
        raise click.Abort
    click.echo(result)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('drive_path',
                type=click.Path(exists=True, dir_okay=False, writable=True, path_type=Path))
@click.option('-w',
              '--wait-time',
              type=float,
              default=1.0,
              help='Wait time in seconds.',
              metavar='TIME')
def wait_for_disc_main(drive_path: Path, wait_time: float = 1.0) -> None:
    """Wait for a disc in a drive to be ready."""  # noqa: DOC501
    if not wait_for_disc(str(drive_path), sleep_time=wait_time):
        raise click.Abort


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option('--appid', metavar='STRING', help='Application ID')
@click.option('--preparer', metavar='STRING', help='Preparer')
@click.option('--publisher', metavar='STRING', help='Publisher')
@click.option('--sysid', metavar='STRING', help='System ID')
@click.option('--volset', metavar='STRING', help='Volume Set ID', type=int)
@click.option('--volume', metavar='STRING', help='Volume label')
@click.option('--bootfile',
              metavar='FILENAME',
              help='Set boot file',
              type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option('--bootinfotable', is_flag=True, help='Generate boot information table in boot file')
@click.option('--optimize',
              is_flag=True,
              help='Optimise file systems by coding same files only once')
@click.option(
    '-f',
    '--file',
    'files',
    metavar='FILENAME',
    help='Add one file or folder (include folder name and all files and folders under it)',
    multiple=True,
    type=click.Path(exists=True, path_type=Path))
@click.option(
    '--dir',
    'dirs',
    metavar='DIRNAME',
    multiple=True,
    help='Add all files and folders under given directory (not include directory name itself)',
    type=click.Path(exists=True, path_type=Path))
@click.option('--newdir', metavar='DIRNAME', help='Create a new directory')
@click.option('-c', '--chdir', metavar='DIRNAME', help='Change current directory in ISO image')
@click.option('-r',
              '--rmdir',
              metavar='FILENAME',
              help='Remove a file or folder from ISO image (full path should be specified)')
@click.option('--hide',
              metavar='FILENAME',
              help='Set hidden attribute of a file or folder (full path should be specified)')
@click.option(
    '--ahide',
    metavar='FILENAME',
    help='Set advanced hidden attribute of a file or folder (full path should be specified)')
@click.option('-i',
              '--input',
              'input_',
              metavar='FILENAME',
              help='Input ISO image',
              type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option('-o', '--output', metavar='FILENAME', help='Output ISO image')
@click.option('--bin2iso',
              metavar='FILENAME',
              help='Convert input CD/DVD image to ISO format',
              type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option('--dmg2iso',
              metavar='FILENAME',
              help='Convert input DMG image to ISO format',
              type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option('--bin2isz',
              metavar='FILENAME',
              help='Compress input CD/DVD image to ISZ format',
              type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option('--compress', help='Set compression level', type=click.IntRange(1, 16))
@click.option('--encrypt', help='Set encryption method', type=click.IntRange(1, 3))
@click.option('--password',
              metavar='PASSWORD',
              help='Set ISZ password',
              prompt_required=True,
              hide_input=True)
@click.option('--split', metavar='SIZE', help='Set segment size in bytes', type=int)
@click.option('--list',
              'list_',
              metavar='FILENAME',
              help='Create a list of files and folders in an ISO image',
              type=click.Path(dir_okay=False, path_type=Path))
@click.option('--get',
              metavar='FILENAME',
              help='Set a file or folder(full path should be specified) to be extracted')
@click.option('--extract', metavar='DIRNAME', help='Extract ISO image to specified directory')
@click.option('--cmd',
              metavar='FILENAME',
              help='Read arguments from a text file',
              type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option('-l',
              '--ilong',
              is_flag=True,
              help='Long filename for ISO 9660 volume, up to 31 chars')
@click.option('--imax', is_flag=True, help='Max filename for ISO 9660 volume, up to 207 chars')
@click.option('--vernum', is_flag=True, help='Include file version number')
@click.option('--lowercase', is_flag=True, help='Allow lowercase letter')
@click.option('--joliet', is_flag=True, help='Create Joliet volume')
@click.option('--jlong', is_flag=True, help='Long filename for joliet volume, up to 103 chars')
@click.option('--rockridge', is_flag=True, help='Create RockRidge volume')
@click.option('--udf', is_flag=True, help='Create UDF volume')
@click.option('--hfs', is_flag=True, help='Create Apple HFS volume')
@click.option('--udfdvd',
              is_flag=True,
              help='Create UDF DVD image (this option will overwrite all other volume settings)')
@click.option('-d', '--debug', is_flag=True, help='Enable debug logging.')
def ultraiso_main(ahide: str | None = None,
                  appid: str | None = None,
                  bin2iso: Path | None = None,
                  bin2isz: Path | None = None,
                  bootfile: Path | None = None,
                  chdir: str | None = None,
                  cmd: str | None = None,
                  compress: int | None = None,
                  dirs: Sequence[Path] | None = None,
                  dmg2iso: Path | None = None,
                  encrypt: int | None = None,
                  extract: str | None = None,
                  files: Sequence[Path] | None = None,
                  get: str | None = None,
                  hide: str | None = None,
                  input_: Path | None = None,
                  list_: Path | None = None,
                  newdir: str | None = None,
                  output: str | None = None,
                  password: str | None = None,
                  pn: int | None = None,
                  prefix: str | None = None,
                  preparer: str | None = None,
                  publisher: str | None = None,
                  rmdir: str | None = None,
                  split: int | None = None,
                  sysid: str | None = None,
                  volset: int | None = None,
                  volume: str | None = None,
                  *,
                  bootinfotable: bool = False,
                  hfs: bool = False,
                  ilong: bool = False,
                  imax: bool = False,
                  jlong: bool = False,
                  joliet: bool = False,
                  lowercase: bool = False,
                  optimize: bool = False,
                  rockridge: bool = False,
                  udf: bool = False,
                  udfdvd: bool = False,
                  vernum: bool = False,
                  debug: bool = False) -> None:
    """
    CLI interface to UltraISO.

    On non-Windows, runs UltraISO via Wine.
    """  # noqa: DOC501
    kwargs = {'prefix': prefix} if prefix and not IS_WINDOWS else {}
    logging.basicConfig(level=logging.ERROR if not debug else logging.DEBUG)
    try:
        run_ultraiso(add_dirs=dirs or [],
                     add_files=files or [],
                     bin2iso=bin2iso,
                     dmg2iso=dmg2iso,
                     bootfile=bootfile,
                     bootinfotable=bootinfotable,
                     optimize=optimize,
                     cmd=cmd,
                     chdir=chdir,
                     newdir=newdir,
                     rmdir=rmdir,
                     hfs=hfs,
                     jlong=jlong,
                     joliet=joliet,
                     rockridge=rockridge,
                     udf=udf,
                     udfdvd=udfdvd,
                     ahide=ahide,
                     hide=hide,
                     pn=cast('Any', pn),
                     appid=appid,
                     preparer=preparer,
                     publisher=publisher,
                     sysid=sysid,
                     volset=volset,
                     volume=volume,
                     input=input_,
                     bin2isz=bin2isz,
                     compress=cast('Any', compress),
                     encrypt=cast('Any', encrypt),
                     password=password,
                     split=split,
                     output=output,
                     extract=extract,
                     get=get,
                     list_=list_,
                     ilong=ilong,
                     imax=imax,
                     lowercase=lowercase,
                     vernum=vernum,
                     **kwargs)
    except (InsufficientArguments, sp.CalledProcessError) as e:
        raise click.Abort from e
    except FileNotFoundError as e:
        click.echo('Is UltraISO installed?')
        raise click.Abort from e


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
@click.argument('device')
def supported_audio_input_formats_main(device: str, *, debug: bool = False) -> None:
    """Get supported input formats and sample rates by invoking ffmpeg."""  # noqa: DOC501
    logging.basicConfig(level=logging.DEBUG if debug else logging.ERROR)
    try:
        for format_, rate in supported_audio_input_formats(device):
            click.echo(f'{format_} @ {rate}')
    except OSError as e:
        click.echo('Likely invalid device name.', err=True)
        raise click.Abort from e


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
@click.argument('filename', type=click.Path(exists=True, dir_okay=False, path_type=Path), nargs=-1)
def add_info_json_main(filename: Sequence[Path], *, debug: bool = False) -> None:
    """Embed info.json in a media file."""
    logging.basicConfig(level=logging.DEBUG if debug else logging.ERROR)
    for f in filename:
        add_info_json_to_media_file(f, debug=debug)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
@click.argument('filename', type=click.Path(exists=True, dir_okay=False, path_type=Path))
def display_info_json_main(filename: Path, *, debug: bool = False) -> None:
    """Display embedded info.json in a media file."""  # noqa: DOC501
    logging.basicConfig(level=logging.DEBUG if debug else logging.ERROR)
    try:
        click.echo(get_info_json(filename, raw=True))
    except NotImplementedError as e:
        raise click.Abort from e
    except sp.CalledProcessError as e:
        click.echo(e.stdout)
        click.echo(e.stderr)
        raise click.Abort from e


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option('-V', '--videotoolbox', is_flag=True, help='Use VideoToolbox.')
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
@click.option('-f', '--font', default='Roboto', help='Font to use.')
@click.option('-n', '--nvenc', is_flag=True, help='Use NVENC.')
@click.option('-o',
              '--output',
              'output_file',
              type=click.Path(dir_okay=False, path_type=Path),
              help='Output file.')
@click.option('-s', '--font-size', type=int, default=150, help='Font size in pt.')
@click.argument('audio_filename', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument('text', nargs=-1)
def audio2vid_main(audio_filename: Path,
                   text: str,
                   font: str = 'Roboto',
                   font_size: int = 150,
                   output_file: Path | None = None,
                   *,
                   debug: bool = False,
                   nvenc: bool = False,
                   videotoolbox: bool = False) -> None:
    """Create a video with static text and audio."""
    logging.basicConfig(level=logging.DEBUG if debug else logging.ERROR)
    create_static_text_video(audio_filename,
                             ' '.join(text),
                             font,
                             font_size,
                             output_file,
                             debug=debug,
                             nvenc=nvenc,
                             videotoolbox=videotoolbox)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('filenames', nargs=-1)
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
def mvid_rename_main(filenames: tuple[str, ...], *, debug: bool = False) -> None:
    """Rename music video files."""
    logging.basicConfig(level=logging.DEBUG if debug else logging.ERROR)
    for filename in filenames:
        path = Path(filename).resolve(strict=True)
        if not path.is_dir():
            log.debug('Ignored: %s', path)
            continue
        try:
            src = path / f'{path.name.lower()}.mkv'
            target = (path / f'../{path.name}.mkv').resolve()
            log.debug('%s -> %s', src, target)
            src.rename(target)
            send2trash(path)
        except Exception:
            log.exception('Exception with file %s.', path)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('args', nargs=-1)
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
@click.option('-H', '--host', help='CDDB hostname.', metavar='HOST')
def cddb_query_main(args: tuple[str, ...], host: str | None = None, *, debug: bool = False) -> None:
    """
    Display a CDDB result in a simple JSON format.

    Does not handle if result is not an exact match.
    """
    logging.basicConfig(level=logging.DEBUG if debug else logging.ERROR)
    click.echo(json.dumps(cddb_query(' '.join(args), host=host)._asdict(), indent=2,
                          sort_keys=True))


DEFAULT_DRIVE_SR0 = Path('/dev/sr0')


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option('-D',
              '--drive',
              default='/dev/sr0',
              help='Optical drive path.',
              type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option('-M',
              '--accept-first-cddb-match',
              is_flag=True,
              help='Accept the first CDDB match in case of multiple matches.')
@click.option('--album-artist', help='Album artist override.')
@click.option('--album-dir', help='Album directory name. Defaults to artist-album-year format.')
@click.option('--cddb-host', help='CDDB host.', default='gnudb.gnudb.org')
@click.option('--never-skip',
              help="Passed to cdparanoia's --never-skip=... option.",
              type=int,
              default=5)
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
@click.option('-o',
              '--output-dir',
              help='Parent directory for album_dir. Defaults to current directory.')
@click.option('-u', '--username', default=getpass.getuser(), help='Username for CDDB.')
def ripcd_main(drive: Path = DEFAULT_DRIVE_SR0,
               album_artist: str | None = None,
               album_dir: str | None = None,
               cddb_host: str | None = None,
               never_skip: int = 5,
               output_dir: str | None = None,
               username: str | None = None,
               *,
               accept_first_cddb_match: bool = True,
               debug: bool = False) -> None:
    """
    Rip an audio disc to FLAC files.

    Requires cdparanoia and flac to be in PATH.

    For Linux only.
    """  # noqa: DOC501
    logging.basicConfig(level=logging.DEBUG if debug else logging.ERROR)
    try:
        rip_cdda_to_flac(drive,
                         accept_first_cddb_match=accept_first_cddb_match,
                         album_artist=album_artist,
                         album_dir=album_dir,
                         cddb_host=cddb_host,
                         never_skip=never_skip,
                         output_dir=output_dir,
                         username=username)
    except (sp.CalledProcessError, requests.RequestException, ValueError) as e:
        click.echo(str(e), err=True)
        raise click.Abort from e


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('files', nargs=-1, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option('-A', '--album', help='Album.')
@click.option('-D',
              '--delete-all-before',
              is_flag=True,
              help='Delete all existing tags before processing.')
@click.option('-T', '--track', type=int, help='Track number.')
@click.option('-a', '--artist', help='Track artist.')
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
@click.option('-g', '--genre', help='Genre.')
@click.option('-p', '--picture', help='Cover artwork to attach.')
@click.option('-t', '--title', help='Track title.')
@click.option('-y', '--year', type=int, help='Year.')
def flacted_main(files: tuple[Path, ...],
                 album: str | None = None,
                 artist: str | None = None,
                 genre: str | None = None,
                 picture: str | None = None,
                 title: str | None = None,
                 track: int | None = None,
                 year: int | None = None,
                 *,
                 debug: bool = False,
                 delete_all_before: bool = False) -> None:
    """Front-end to metaflac to set common tags."""  # noqa: DOC501
    logging.basicConfig(level=logging.DEBUG if debug else logging.ERROR)

    def metaflac(*args: Any, **kwargs: Any) -> sp.CompletedProcess[str]:
        return sp.run(('metaflac', *cast('tuple[str, ...]', args)),
                      capture_output=not debug,
                      **kwargs,
                      check=True,
                      text=True)

    invoked_as = Path(sys.argv[0]).name
    if invoked_as != 'flacted' and len(files) > 0:
        tag_requested = invoked_as.split('-')[1].lower()
        possible: tuple[str, ...] = (tag_requested.title(), tag_requested.upper(), tag_requested)
        if tag_requested == 'year':
            possible += ('Date', 'DATE', 'date')
        show_filename = len(files) > 1
        for filename in files:
            for tag in possible:
                val = metaflac(f'--show-tag={tag}', filename).stdout.strip()
                try:
                    val = val[len(tag) + 1:].splitlines()[0].strip()
                except IndexError:
                    val = ''
                if val:
                    if tag_requested == 'track':
                        try:
                            val_int: int | None = int(val)
                        except (TypeError, ValueError):
                            val = ''
                            val_int = None
                        if val_int:
                            val = f'{val_int:02d}'
                    if show_filename:
                        click.echo(f'{filename}: {val}')
                    else:
                        click.echo(f'{val}')
                    break
        return
    min_args = 3
    metaflac_args = ['--preserve-modtime', '--no-utf8-convert']
    clean_up_args = metaflac_args.copy()
    destroy = delete_all_before
    clean_up_args.append('--remove-all-tags')
    clean_up_args += (str(x) for x in files)
    for key, value in {
            'album': album,
            'artist': artist,
            'genre': genre,
            'title': title,
            'track': track,
            'year': year
    }.items():
        if not value:
            continue
        value_ = value.strip() if isinstance(value, str) else value
        match key:
            case 'year':
                flac_tag = 'Date'
            case 'track':
                flac_tag = 'Tracknumber'
            case _:
                flac_tag = f'{key[0].upper()}{key[1:]}'
        metaflac_args.append(f'--set-tag={flac_tag}={value_}')
    if picture:
        metaflac_args.append(f'--import-picture-from={picture}')
    if len(metaflac_args) < min_args:
        click.echo('Not doing anything', err=True)
        raise click.Abort
    if destroy:
        metaflac(*clean_up_args)
    metaflac_args += (str(x) for x in files)
    metaflac(*metaflac_args)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('paths', type=click.Path(exists=True, file_okay=False, path_type=Path), nargs=-1)
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
@click.option('-D', '--delete-paths', help='Delete paths after extraction.', is_flag=True)
def ke_ebook_ex_main(paths: Sequence[Path],
                     *,
                     debug: bool = False,
                     delete_paths: bool = False) -> None:
    """Extract ebooks from RARs within Zip files."""
    logging.basicConfig(level=logging.DEBUG if debug else logging.ERROR)
    for path in paths:
        unpack_ebook(path)
    if delete_paths:
        for path in paths:
            send2trash(path)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('front_dir', type=click.Path(exists=True, dir_okay=True, path_type=Path))
@click.argument('rear_dir', type=click.Path(exists=True, dir_okay=True, path_type=Path))
@click.argument('output_dir', type=click.Path(dir_okay=True, path_type=Path), default=Path())
@click.option('--clip-length', help='Clip length in minutes.', type=int, default=3)
@click.option('--crf', type=int, default=26, help='Constant rate factor.')
@click.option('--hwaccel', help='-hwaccel string for ffmpeg.', default='auto')
@click.option('--level', help='Level (HEVC).', default='auto')
@click.option('--no-fix-groups', help='Disable group discrepancy resolution.', is_flag=True)
@click.option('--no-hwaccel', help='Disable hardware decoding.', is_flag=True)
@click.option('--no-rear-crop', is_flag=True, help='Disable rear video cropping.')
@click.option('--no-setpts', is_flag=True, help='Disable use of setpts.')
@click.option('--preset', help='Output preset (various codecs).', default='slow')
@click.option('--rear-crop', default='1920:1020:0:0', help='Crop string for the rear camera view.')
@click.option('--rear-view-scale-divisor',
              default=2.5,
              type=float,
              help='Scaling divisor for rear view.')
@click.option('--setpts',
              help='setpts= string. Defaults to speeding video by 4x.',
              default='0.25*PTS')
@click.option('--tier', help='Tier (HEVC).', default='high')
@click.option('--time-format',
              metavar='FORMAT',
              help='Time format to parse from video files.',
              default='%Y%m%d%H%M%S')
@click.option('--video-bitrate', default='0k', help='Video bitrate.', metavar='BITRATE')
@click.option('--video-decoder',
              default='hevc_cuvid',
              help='Video decoder (for hardware decoding only).',
              metavar='DECODER')
@click.option('--video-encoder', default='hevc_nvenc', help='Video encoder.', metavar='ENCODER')
@click.option('--video-max-bitrate',
              default='15M',
              help='Maximum video bitrate.',
              metavar='BITRATE')
@click.option('-D', '--no-delete', is_flag=True, help='Do not delete original files.')
@click.option('-M',
              '--match-regexp',
              help='Regular expression to find the date string.',
              default=r'^(\d+)_.*',
              metavar='RE')
@click.option('-O', '--overwrite', is_flag=True, help='Overwrite existing files.')
@click.option('-T', '--temp-dir', help='Temporary directory for processing.')
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
def encode_dashcam_main(front_dir: Path,
                        rear_dir: Path,
                        output_dir: Path,
                        clip_length: int = 3,
                        crf: int = 26,
                        hwaccel: str = 'auto',
                        level: str = 'auto',
                        match_regexp: str = r'^(\d+)_.*',
                        preset: str = 'p7',
                        rear_crop: str = '1920:1020:0:0',
                        rear_view_scale_divisor: float = 2.5,
                        setpts: str = '0.25*PTS',
                        temp_dir: str | None = None,
                        tier: str = 'high',
                        time_format: str = '%Y%m%d%H%M%S',
                        video_bitrate: str = '0k',
                        video_decoder: str = 'hevc_cuvid',
                        video_encoder: str = 'hevc_nvenc',
                        video_max_bitrate: str = '15M',
                        *,
                        debug: bool = False,
                        no_delete: bool = False,
                        no_fix_groups: bool = False,
                        no_hwaccel: bool = False,
                        no_rear_crop: bool = False,
                        no_setpts: bool = False,
                        overwrite: bool = False) -> None:
    """
    Batch encode dashcam footage, merging rear and front camera footage.

    This command's defaults are intended for use with Red Tiger dashcam output and file structure.

    The rear camera view will be placed in the bottom right of the video scaled by dividing the
    width and height by the --rear-view-scale-divisor value specified. It will also be cropped using
    the --rear-crop value unless --no-rear-crop is passed.

    Files are automatically grouped using the regular expression passed with -M/--match-regexp. This
    RE must contain at least one group and only the first group will be considered. Make dubious use
    of non-capturing groups if necessary. The captured group string is expected to be usable with
    the time format specified with --time-format (see strptime documentation at
    https://docs.python.org/3/library/datetime.html#datetime.datetime.strptime).

    In many cases, the camera leaves behind stray rear camera files (usually no more than one per
    group and always a video without a matching front video file the end). These are automatically
    ignored if possible. This behaviour can be disabled by passing --no-fix-groups.

    Original files' whose content is successfully converted are sent to the wastebin.

    Example use:

        encode-dashcam Movie_F/ Movie_R/ ~/output_dir
    """  # noqa: DOC501
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)
    if Path(front_dir).resolve(strict=True) == Path(rear_dir).resolve(strict=True):
        click.echo('Front and rear directories are the same.', err=True)
        raise click.Abort
    archive_dashcam_footage(front_dir,
                            rear_dir,
                            output_dir,
                            allow_group_discrepancy_resolution=not no_fix_groups,
                            clip_length=clip_length,
                            crf=crf,
                            hwaccel=None if no_hwaccel else hwaccel,
                            level=level,
                            match_re=match_regexp,
                            no_delete=no_delete,
                            overwrite=overwrite,
                            preset=preset,
                            rear_crop=None if no_rear_crop else rear_crop,
                            rear_view_scale_divisor=rear_view_scale_divisor,
                            setpts=None if no_setpts else setpts,
                            temp_dir=temp_dir,
                            tier=tier,
                            time_format=time_format,
                            video_bitrate=video_bitrate,
                            video_decoder=video_decoder,
                            video_encoder=video_encoder,
                            video_max_bitrate=video_max_bitrate)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('filename', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument('output', type=click.Path(dir_okay=False, path_type=Path), required=False)
@click.option('--codec',
              help='Video codec.',
              type=click.Choice(('libx264', 'libx265')),
              default='libx265')
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
@click.option('--crf', help='CRF value.', type=int, default=20)
@click.option('--delete-after', help='Send processed file to wastebin.', is_flag=True)
@click.option('-f', '--fast', help='Use less filters (lower quality).', is_flag=True)
def hlg2sdr_main(filename: Path,
                 output: Path | None,
                 crf: int = 20,
                 codec: Literal['libx264', 'libx265'] = 'libx265',
                 *,
                 debug: bool = False,
                 delete_after: bool = False,
                 fast: bool = False) -> None:
    """Convert a HLG video to SDR."""
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)
    hlg_to_sdr(filename, crf, codec, output, fast=fast, delete_after=delete_after)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('filename', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
@click.option('--input-json',
              help='Input JSON file.',
              type=click.Path(exists=True, dir_okay=False, path_type=Path))
def tbc2srt_main(filename: Path, input_json: Path | None = None, *, debug: bool = False) -> None:
    """
    Convert VBI data in a ld-decode/vhs-decode TBC file to SubRip format.

    Requires the following: ld-process-vbi, ld-export-metadata, scc2raw.pl, ccextractor.
    """
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)
    p_filename = Path(filename)
    scc_file = p_filename.parent / f'{p_filename.stem}.scc'
    bin_file = p_filename.parent / f'{p_filename.stem}.bin'
    output_json_file = p_filename.parent / f'{p_filename.stem}.json'
    input_json = input_json or p_filename.parent / 'input.json'
    cmd: tuple[str, ...] = ('ld-process-vbi', '--input-json', str(input_json), '--output-json',
                            str(output_json_file), str(filename))
    log.debug('Running: %s', ' '.join(quote(x) for x in cmd))
    sp.run(cmd, check=True)
    cmd = ('ld-export-metadata', '--closed-captions', str(scc_file), str(output_json_file))
    log.debug('Running: %s', ' '.join(quote(x) for x in cmd))
    sp.run(cmd, check=True)
    cmd = ('scc2raw.pl', str(scc_file))
    log.debug('Running: %s', ' '.join(quote(x) for x in cmd))
    sp.run(cmd, check=True)
    cmd = ('ccextractor', '-in=raw', str(bin_file))
    log.debug('Running: %s', ' '.join(quote(x) for x in cmd))
    sp.run(cmd, check=True)
    send2trash([scc_file, bin_file, output_json_file, input_json])


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('directory', type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
def flac_dir_finalize_main(directory: Path, *, debug: bool = False) -> None:
    """Finalise a FLAC album directory."""
    def get_flac_tags(flac_path: Path) -> Iterator[tuple[str, str]]:
        def _split_eq(x: str) -> tuple[str, str] | None:
            y = x.split('=', 1)
            if len(y) == 2:  # noqa: PLR2004
                return y[0].lower(), y[1]
            return None

        return (y for y in (_split_eq(x)
                            for x in sp.run(('metaflac', '--export-tags-to=-', str(flac_path)),
                                            stdout=sp.PIPE,
                                            text=True,
                                            check=False).stdout.splitlines()) if y is not None)

    def remove_accents(s: str) -> str:
        return ''.join(c for c in unicodedata.normalize('NFD', re.sub(r'[Øø]', 'o', s))
                       if unicodedata.category(c) != 'Mn')

    def sanitize_for_filename(s: str) -> str:
        return underscorize(
            re.sub(
                r'[!&"\'$;`^,#\?%=\.,°±¡¯¬«ª²³¨§¦¥¤£¢¿¾½¼»þ÷¹¸·¶µ´]',  # noqa: RUF001
                '',
                re.sub(
                    r'[/\|:\\\*\+@~]', '-',
                    re.sub(
                        r'[<{\(\[]', '(',
                        re.sub(r'[>}\)\]]', ')',
                               re.sub(r'\s&\s', ' and ', remove_accents(s),
                                      flags=re.IGNORECASE))))))

    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)
    path = Path(directory).resolve(strict=True)
    flac_files = ((path / x) for x in Path(directory).iterdir() if x.name.endswith('.flac'))
    new_flac_files: list[Path] = []
    imgs = ((path / x) for x in Path(directory).iterdir()
            if re.search(r'\.(?:jpe?g|png|gif|webp)', str(x)) is not None)
    misc_files_prefix = f'00-{path.name.lower()}'
    img_prefix = '-'.join(misc_files_prefix.split('-')[:-1])
    out_m3u = path / f'{misc_files_prefix}.m3u'
    out_sfv = path / f'{misc_files_prefix}.sfv'
    for flac in flac_files:
        tracknumber, artist, title = itemgetter('tracknumber', 'artist', 'title')(dict(
            get_flac_tags(flac)))
        new_fn = path / re.sub(r'-+', '-',
                               (f'{int(tracknumber):02d}-{sanitize_for_filename(artist)}-'
                                f'{sanitize_for_filename(title)}.flac'.lower()))
        new_flac_files.append(new_fn)
        flac.rename(new_fn)
    for i, img in enumerate(sorted(imgs), start=1):
        ext = img.suffix[1:].replace('jpg', 'jpeg')
        new_fn = path / f'{img_prefix}-{i:>02}.{ext}'
        img.rename(new_fn)
    with out_m3u.open('w+', encoding='utf-8') as f:
        for flac in sorted(new_flac_files):
            f.write(f'{flac.name}\r\n')
    make_sfv(out_sfv, new_flac_files)
