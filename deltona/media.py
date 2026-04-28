"""Media-related utility functions."""

from __future__ import annotations

from datetime import datetime
from itertools import chain
from os import utime
from pathlib import Path
from shlex import quote
from shutil import copyfile
from typing import TYPE_CHECKING, Any, Literal, NamedTuple, cast
import contextlib
import getpass
import json
import logging
import operator
import re
import socket
import subprocess as sp
import tempfile

from async_lru import alru_cache
from niquests import AsyncSession

from .typing import ProbeDict, StrPath, assert_not_none

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

__all__ = ('CDDBQueryResult', 'add_info_json_to_media_file', 'archive_dashcam_footage',
           'cddb_query', 'create_static_text_video', 'ffprobe', 'get_info_json', 'group_pairs',
           'hlg_to_sdr', 'is_audio_input_format_supported', 'pair_redtiger_dashcam_files',
           'parse_timestamp', 'supported_audio_input_formats')

log = logging.getLogger(__name__)

_DEFAULT_FORMATS = ('f32be', 'f32le', 'f64be', 'f64le', 's8', 's16be', 's16le', 's24be', 's24le',
                    's32be', 's32le', 'u8', 'u16be', 'u16le', 'u24be', 'u24le', 'u32be', 'u32le')
_DEFAULT_RATES = (8000, 12000, 16000, 22050, 24000, 32000, 44100, 48000, 64000, 88200, 96000,
                  128000, 176400, 192000, 352800, 384000)


def supported_audio_input_formats(
        input_device: str,
        *,
        formats: Sequence[str] = _DEFAULT_FORMATS,
        rates: Sequence[int] = _DEFAULT_RATES) -> tuple[tuple[str, int], ...]:
    """
    Get supported input formats and sample rates by invoking ``ffmpeg``.

    For possible formats, invoke ``ffmpeg``: ``ffmpeg -formats | grep PCM | cut '-d ' -f3``.

    Parameters
    ----------
    input_device : str
        Device name (platform-specific). Examples: ``'hw:Audio'``, ``'hw:NVidia'``.

    formats : Sequence[str]
        Formats to check.

    rates : Sequence[int]
        Rates in Hz to check. The default set is taken from possible frequencies for DTS format.

    Returns
    -------
    tuple[tuple[str, int], ...]
        A tuple of ``(format, rate)`` tuples.

    Raises
    ------
    OSError
        If the device is not found or busy.
    """
    ret = []
    for format_ in formats:
        for rate in rates:
            log.debug('Checking pcm_%s @ %d.', format_, rate)
            p = sp.run(
                (  # noqa: S607
                    'ffmpeg', '-hide_banner', '-loglevel', 'info', '-f', 'alsa', '-acodec',
                    f'pcm_{format_}', '-ar', str(rate), '-i', input_device),
                text=True,
                capture_output=True,
                check=False)
            all_output = p.stdout.strip() + p.stderr.strip()
            if 'Device or resource busy' in all_output or 'No such device' in all_output:
                raise OSError
            log.debug('Output: %s', all_output)
            if 'cannot set sample format 0x' in all_output or f'{rate} Hz' not in all_output:
                continue
            ret.append((format_, rate))
    return tuple(ret)


def is_audio_input_format_supported(
        input_device: str,
        format: str,  # noqa: A002
        rate: int) -> bool:
    """
    Check if an audio format is supported by a device.

    Parameters
    ----------
    input_device : str
        Device name (platform-specific).
    format : str
        Audio format to check, such as ``'s16le'``.
    rate : int
        Sample rate in Hz.

    Returns
    -------
    bool
        ``True`` if the format and rate are supported.
    """
    return bool(supported_audio_input_formats(input_device, formats=(format,), rates=(rate,)))


def add_info_json_to_media_file(path: StrPath,
                                info_json: StrPath | None = None,
                                *,
                                debug: bool = False) -> None:
    """
    Add yt-dlp ``info.json`` file to media file at ``path``.

    On successful completion, the ``info.json`` file will be deleted.

    This function remains until yt-dlp embeds ``info.json`` in all formats it supports where
    possible.

    This function requires the following:

    - For FLAC, MP3, and Opus: `ffmpeg <https://ffmpeg.org/>`_.
    - For MP4: `gpac <https://gpac.io/>`_.

    Parameters
    ----------
    path : StrPath
        Path to FLAC, MP3, MP4, or Opus media file.
    info_json : StrPath | None
        Path to ``info.json`` file. If not passed, ``path`` with suffix changed to ``info.json``
        is used.
    debug : bool
        If ``True``, show ffmpeg/mkvpropedit output.
    """
    path = Path(path)
    json_path = Path(info_json) if info_json else path.with_suffix('.info.json')

    def set_date() -> None:
        with json_path.open() as fp:
            data = json.load(fp)
        try:
            upload_date = data['upload_date'].strip()
        except KeyError:
            log.debug('Upload date key not found.')
            return
        if not upload_date:
            log.debug('No upload date to set.')
            return
        log.debug('Setting date to %s.', upload_date)
        seconds = datetime.strptime(upload_date, '%Y%m%d').timestamp()  # noqa: DTZ007
        utime(path, times=(seconds, seconds))

    def mkvpropedit_add_json() -> None:
        if any(
                re.match((r"^Attachment ID \d+: type 'application/json', size \d+ bytes, "
                          r"file name 'info.json'"), line) for line in sp.run(
                              ('mkvmerge', '--identify', str(path)),  # noqa: S607
                              capture_output=True,
                              check=True,
                              text=True).stdout.splitlines()):
            log.warning('Attachment named info.json already exists. Not modifying file.')
            return
        log.debug('Attaching info.json to MKV.')
        sp.run(
            (  # noqa: S607
                'mkvpropedit', str(path), '--attachment-name', 'info.json', '--add-attachment',
                str(json_path)),
            check=True,
            capture_output=not debug)
        set_date()

    def flac_mp3_add_json() -> None:
        log.debug('Attaching info.json.')
        with (tempfile.NamedTemporaryFile(suffix=path.suffix, delete=False, dir=path.parent) as tf,
              tempfile.NamedTemporaryFile(suffix='.ffmetadata',
                                          encoding='utf-8',
                                          dir=path.parent,
                                          mode='w+') as ffm):
            sp.run(
                (  # noqa: S607
                    'ffmpeg', '-hide_banner', '-loglevel', 'warning', '-y', '-i', f'file:{path}',
                    '-f', 'ffmetadata', f'{ffm.name}'),
                check=True,
                capture_output=True)
            lines = Path(ffm.name).read_text(encoding='utf-8').splitlines(keepends=True)
            escaped = re.sub(r'([=;#\\\n])', r'\\\1', json_path.read_text())
            is_mp3 = path.suffix == '.mp3'
            key = r'TXXX=info_json\=' if is_mp3 else 'info_json='
            lines.insert(1, f'{key}{escaped}\n')
            with tempfile.NamedTemporaryFile(suffix='.ffmetadata',
                                             encoding='utf-8',
                                             dir=path.parent,
                                             delete=False,
                                             mode='w+') as nfw:
                nfw.writelines(lines)
            sp.run(
                (  # noqa: S607
                    'ffmpeg', '-y', '-i', f'file:{path}', '-i', f'file:{nfw.name}', '-map_metadata',
                    '1', '-c', 'copy', *(('-write_id3v1', '1') if is_mp3 else
                                         ()), f'file:{tf.name}'),
                capture_output=not debug,
                check=True)
            Path(tf.name).rename(path)
            Path(nfw.name).unlink()
        set_date()

    def mp4box_add_json() -> None:
        with contextlib.suppress(sp.CalledProcessError):
            sp.run(
                ('MP4Box', '-rem-item', '1', str(path)),  # noqa: S607
                capture_output=not debug,
                check=True)
        sp.run(
            ('MP4Box', '-set-meta', 'mp21', str(path)),  # noqa: S607
            capture_output=not debug,
            check=True)
        info_json_path = Path('info.json')
        copyfile(json_path, info_json_path)
        log.debug('Attaching info.json to MP4.')
        sp.run(
            (  # noqa: S607
                'MP4Box', '-add-item',
                (f'{info_json_path}:replace:name=youtube-dl metadata:mime=application/json:'
                 'encoding=utf8'), str(path)),
            check=True,
            capture_output=not debug)
        info_json_path.unlink()
        set_date()

    if not json_path.exists():
        log.warning('JSON path not found.')
        return
    match path.suffix.lower()[1:]:
        case 'flac' | 'mp3' | 'opus':
            flac_mp3_add_json()
        case 'm4a' | 'm4b' | 'm4p' | 'm4r' | 'm4v' | 'mp4':
            mp4box_add_json()
        case 'mkv':
            mkvpropedit_add_json()
        case _:
            return
    json_path.unlink()


def ffprobe(path: StrPath) -> ProbeDict:
    """
    Run ``ffprobe`` and decode its JSON output.

    Parameters
    ----------
    path : StrPath
        Path to the media file.

    Returns
    -------
    ProbeDict
        Parsed JSON output from ``ffprobe``.
    """
    return cast(
        'ProbeDict',
        json.loads(
            sp.run(
                (  # noqa: S607
                    'ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format',
                    '-show_streams', str(path)),
                check=True,
                capture_output=True,
                text=True).stdout.strip()))


def get_info_json(path: StrPath, *, raw: bool = False) -> Any:
    """
    Get ``info.json`` content in ``path``.

    Parameters
    ----------
    path : StrPath
        Path to FLAC, MP3, MP4, or Opus media file.
    raw : bool
        If ``True``, do not decode.

    Returns
    -------
    Any
        The JSON data decoded. Currently not typed.

    Raises
    ------
    NotImplementedError
        If the file type is not supported.
    """
    path = Path(path)
    match path.suffix.lower()[1:]:
        case 'flac':
            out = ffprobe(path)['format']['tags']['info_json']
        case 'm4a' | 'm4b' | 'm4p' | 'm4r' | 'm4v' | 'mp4':
            out = sp.run(
                ('MP4Box', '-dump-item', '1:path=/dev/stdout', str(path)),  # noqa: S607
                check=True,
                capture_output=True,
                text=True).stdout.strip()
        case 'mkv':
            out = (
                sp.run(
                    ('mkvextract', str(path), 'attachments', '1:/dev/stdout'),  # noqa: S607
                    check=True,
                    capture_output=True,
                    text=True).stdout.strip().splitlines()[1])
        case 'mp3':
            out = ffprobe(path)['format']['tags']['TXXX'].replace('info_json=', '', 1)
        case 'opus':
            out = ffprobe(path)['streams'][0]['tags']['info_json']
        case _:
            raise NotImplementedError
    return out if raw else json.loads(out)


def create_static_text_video(audio_file: StrPath,
                             text: str,
                             font: str = 'Roboto',
                             font_size: int = 150,
                             output_file: StrPath | None = None,
                             *,
                             debug: bool = False,
                             nvenc: bool = False,
                             videotoolbox: bool = False) -> None:
    """
    Create a video with static text overlay from an audio file.

    Parameters
    ----------
    audio_file : StrPath
        Path to the audio file.
    text : str
        Text to overlay on the video.
    font : str
        Font name to use. Default is ``'Roboto'``.
    font_size : int
        Font size in points. Default is ``150``.
    output_file : StrPath | None
        Output file path. If ``None``, defaults to ``<audio_file>-video.mkv``.
    debug : bool
        If ``True``, show ffmpeg/ImageMagick output.
    nvenc : bool
        If ``True``, use NVENC hardware encoding.
    videotoolbox : bool
        If ``True``, use VideoToolbox hardware encoding.

    Raises
    ------
    ValueError
        If both ``nvenc`` and ``videotoolbox`` are set to ``True``.
    subprocess.CalledProcessError
        If ImageMagick or FFmpeg fails.
    """
    if nvenc and videotoolbox:
        msg = 'nvenc and videotoolbox parameters are exclusive. Only one can be set to True.'
        raise ValueError(msg)
    audio_file = Path(audio_file)
    out = (Path(output_file) if output_file else
           (Path(audio_file.parent) / f'{audio_file.stem}-video.mkv'))
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False, dir=Path.cwd()) as tf:
        try:
            sp.run(
                (  # noqa: S607
                    'magick', '-font',
                    font, '-size', '1920x1080', 'xc:black', '-fill', 'white', '-pointsize',
                    str(font_size), '-draw', f"gravity Center text 0,0 '{text}'", tf.name),
                capture_output=not debug,
                check=True)
        except sp.CalledProcessError:
            Path(tf.name).unlink()
            raise
    args_start: tuple[str,
                      ...] = ('ffmpeg', '-loglevel', 'warning', '-hide_banner', '-y', '-loop', '1',
                              '-i', tf.name, '-i', str(audio_file), '-shortest', '-acodec', 'copy')
    if nvenc:
        args_start += ('-vcodec', 'h264_nvenc', '-profile:v', 'high', '-level', '1', '-preset',
                       'llhq', '-coder:v', 'cabac', '-b:v', '1M')
    elif videotoolbox:
        args_start += ('-vcodec', 'hevc_videotoolbox', '-profile:v', 'main', '-level', '1', '-b:v',
                       '0.5M')
    else:
        args_start += ('-vcodec', 'libx265', '-crf', '20', '-level', '1', '-profile:v', 'main')
    log.debug('Output: %s', out)
    sp.run((*args_start, '-pix_fmt', 'yuv420p', '-b:v', '1M', '-maxrate:v', '1M', str(out)),
           capture_output=not debug,
           check=True)
    Path(tf.name).unlink()


class CDDBQueryResult(NamedTuple):
    """CDDB query result."""

    artist: str
    """Artist name."""
    album: str
    """Album title."""
    year: int
    """Release year."""
    genre: str
    """Genre string."""
    tracks: tuple[str, ...]
    """Track titles."""


def _parse_cddb_query_response(lines: Sequence[str], *,
                               accept_first_match: bool) -> tuple[str, str, str, str]:
    """
    Parse the first CDDB HTTP response (``cddb query``).

    Returns
    -------
    tuple[str, str, str, str]
        ``category``, ``disc_id``, ``artist``, and ``disc_title`` from the server.

    Raises
    ------
    ValueError
        If the server returns multiple matches and ``accept_first_match`` is ``False``, or if the
        response code is not ``'200'`` or ``'210'``.
    """
    first_line = lines[0].split(' ', 3)
    match (len(lines) == 1, first_line[0]):
        case (True, '200'):
            _, category, disc_id, artist_title = first_line
        case (_, '210'):
            if not accept_first_match:
                log.debug('Results:\n%s', '\n'.join(lines).strip())
                raise ValueError(len(lines[1:-1]))
            category, disc_id, artist_title = lines[1].split(' ', 2)
        case _:
            raise ValueError(first_line[0])
    artist, disc_title = artist_title.split(' / ', 1)
    return category, disc_id, artist, disc_title


def _cddb_result_from_read_response(read_text: str, artist: str,
                                    disc_title: str) -> CDDBQueryResult:
    """
    Build a :class:`CDDBQueryResult` from the ``cddb read`` response body.

    Returns
    -------
    CDDBQueryResult
        Parsed metadata and track titles.
    """
    tracks: dict[str, str] = {}
    disc_genre: str | None = None
    disc_year: int | None = None
    log.debug('Artist: %s', artist)
    log.debug('Album: %s', disc_title)
    for line in (x.strip() for x in read_text.splitlines()[1:]
                 if x.strip() and x[0] not in {'.', '#'}):
        field_name, value = line.split('=', 1)
        match field_name:
            case 'DTITLE':
                artist, disc_title = value.split(' / ', 1)
            case 'DYEAR':
                disc_year = int(value)
            case 'DGENRE':
                disc_genre = value
            case key:
                if key.startswith('TTITLE'):
                    tracks[assert_not_none(re.match(r'^TTITLE([^=]+).*', key)).group(1)] = value
    return CDDBQueryResult(artist, disc_title, assert_not_none(disc_year),
                           assert_not_none(disc_genre),
                           tuple(x[1] for x in sorted(tracks.items(), key=operator.itemgetter(0))))


@alru_cache
async def cddb_query(disc_id: str,
                     *,
                     accept_first_match: bool = False,
                     app: str = 'deltona cddb_query',
                     host: str | None = None,
                     timeout: float = 5,
                     username: str | None = None,
                     version: str = '0.0.1') -> CDDBQueryResult:
    """
    Run a query against a CDDB host.

    Defaults to the host in the keyring under the ``gnudb`` key and the current user name.

    It is advised to ``except`` typical
    `niquests exceptions <https://niquests.readthedocs.io/en/latest/>`_ when calling this.

    Parameters
    ----------
    disc_id : str
        Disc ID string in CDDB query format.
    accept_first_match : bool
        If ``True``, accept the first match when multiple results are returned.
    app : str
        App name.
    host : str | None
        Hostname to query.
    timeout : float
        HTTP timeout.
    username : str | None
        Username for keyring and for the ``hello`` parameter to the CDDB server.
    version : str
        Application version.

    Returns
    -------
    CDDBQueryResult
        Tuple with artist, album, year, genre, and tracks.

    Raises
    ------
    ValueError
        If the username or host is empty, if the server returns multiple matches and
        ``accept_first_match`` is ``False``, or if the server response code is not ``'200'`` or
        ``'210'`` (these are CDDB codes **not** HTTP status codes).
    """
    username = username or getpass.getuser()
    if not username:
        raise ValueError(username)
    import keyring  # noqa: PLC0415

    host = host or keyring.get_password('gnudb', username)
    if not host:
        raise ValueError(host)
    this_host = socket.gethostname()
    hello = {'hello': f'{username} {this_host} {app} {version}', 'proto': '6'}
    server = f'http://{host}/~cddb/cddb.cgi'
    async with AsyncSession() as session:
        r = await session.get(server,
                              params={
                                  'cmd': f'cddb query {disc_id}',
                                  **hello
                              },
                              timeout=timeout,
                              headers={'user-agent': hello['hello']})
        r.raise_for_status()
        text = assert_not_none(r.text)
        log.debug('Response:\n%s', text.strip())
        lines = text.splitlines()
        category, disc_id, artist, disc_title = _parse_cddb_query_response(
            lines, accept_first_match=accept_first_match)
        r = await session.get(server,
                              params={
                                  'cmd': f'cddb read {category} {disc_id.split(" ")[0]}',
                                  **hello
                              },
                              timeout=timeout)
    r.raise_for_status()
    read_text = assert_not_none(r.text)
    log.debug('Response: %s', read_text)
    return _cddb_result_from_read_response(read_text, artist, disc_title)


def group_files(items: Iterable[str],
                clip_length: int = 3,
                match_re: re.Pattern[str] | str = r'^(\d+)_.*',
                time_format: str = '%Y%m%d%H%M%S') -> list[list[Path]]:
    items_sorted = sorted(items)
    groups: list[list[Path]] = []
    group: list[Path] = [Path(items_sorted[0]).resolve(strict=True)]
    groups.append(group)
    for item in items_sorted[1:]:
        p = Path(item).resolve(strict=True)
        this_dt = datetime.strptime(  # noqa: DTZ007
            assert_not_none(re.match(match_re,
                                     Path(item).name)).group(1), time_format)
        last_dt = datetime.strptime(  # noqa: DTZ007
            assert_not_none(re.match(match_re,
                                     Path(group[-1]).name)).group(1), time_format)
        diff = (this_dt - last_dt).total_seconds() // 60
        log.debug('Difference for current file %s vs last file %s: %d minutes', p, group[-1], diff)
        if diff > clip_length:
            log.debug('New group started with %s.', p)
            group = [p]
            groups.append(group)
        else:
            group.append(p)
    return groups


def parse_timestamp(name: str, match_re: re.Pattern[str] | str, time_format: str) -> datetime:
    """
    Extract and parse a timestamp from a filename.

    Parameters
    ----------
    name : str
        Filename to extract the timestamp from.
    match_re : re.Pattern[str] | str
        Regular expression with at least one group capturing the timestamp portion.
    time_format : str
        Format string for :py:func:`~datetime.datetime.strptime`.

    Returns
    -------
    datetime
        Parsed datetime object.
    """
    return datetime.strptime(  # noqa: DTZ007
        assert_not_none(re.match(match_re, name)).group(1), time_format)


def pair_redtiger_dashcam_files(front_dir: StrPath,
                                rear_dir: StrPath,
                                match_re: re.Pattern[str] | str = r'^(\d+)_.*',
                                time_format: str = '%Y%m%d%H%M%S',
                                max_offset: int = 1) -> list[tuple[Path, Path]]:
    """
    Pair front and rear dashcam files by timestamp proximity.

    For each front file, finds the closest rear file whose timestamp is within ``max_offset``
    seconds. Files without a match are logged and skipped.

    Parameters
    ----------
    front_dir : StrPath
        Directory containing front footage.
    rear_dir : StrPath
        Directory containing rear footage.
    match_re : re.Pattern[str] | str
        Regular expression to extract the timestamp from filenames.
    time_format : str
        Format string for parsing the extracted timestamp.
    max_offset : int
        Maximum seconds between front and rear timestamps for pairing.

    Returns
    -------
    list[tuple[Path, Path]]
        Pairs of ``(rear_file, front_file)`` sorted by front file timestamp.
    """
    front_files = sorted(((f.resolve(strict=True), parse_timestamp(f.name, match_re, time_format))
                          for f in Path(front_dir).iterdir() if not f.name.startswith('.')),
                         key=operator.itemgetter(1))
    rear_files = sorted(((f.resolve(strict=True), parse_timestamp(f.name, match_re, time_format))
                         for f in Path(rear_dir).iterdir() if not f.name.startswith('.')),
                        key=operator.itemgetter(1))
    pairs: list[tuple[Path, Path]] = []
    used_rear: set[Path] = set()
    for front_file, front_dt in front_files:
        best_match: Path | None = None
        best_diff = float('inf')
        for rear_file, rear_dt in rear_files:
            if rear_file in used_rear:
                continue
            diff = abs((front_dt - rear_dt).total_seconds())
            if diff <= max_offset and diff < best_diff:
                best_match = rear_file
                best_diff = diff
        if best_match is not None:
            pairs.append((best_match, front_file))
            used_rear.add(best_match)
        else:
            log.info('No matching rear video for %s, skipping.', front_file.name)
    for rear_file, _ in rear_files:
        if rear_file not in used_rear:
            log.info('No matching front video for %s, skipping.', rear_file.name)
    return pairs


def group_pairs(pairs: Sequence[tuple[Path, Path]],
                clip_length: int = 3,
                match_re: re.Pattern[str] | str = r'^(\d+)_.*',
                time_format: str = '%Y%m%d%H%M%S') -> list[list[tuple[Path, Path]]]:
    """
    Group paired dashcam files into recording sessions by timestamp proximity.

    Consecutive pairs whose front file timestamps are within ``clip_length`` minutes of each other
    are placed in the same group. A gap exceeding ``clip_length`` starts a new group.

    Parameters
    ----------
    pairs : Sequence[tuple[Path, Path]]
        Pairs of ``(rear_file, front_file)`` sorted by front file timestamp.
    clip_length : int
        Maximum gap in minutes between consecutive pairs in a group.
    match_re : re.Pattern[str] | str
        Regular expression to extract the timestamp from filenames.
    time_format : str
        Format string for parsing the extracted timestamp.

    Returns
    -------
    list[list[tuple[Path, Path]]]
        Groups of pairs, each group representing a recording session.
    """
    if not pairs:
        return []
    groups: list[list[tuple[Path, Path]]] = []
    group: list[tuple[Path, Path]] = [pairs[0]]
    groups.append(group)
    for pair in pairs[1:]:
        _, front_file = pair
        _, last_front = group[-1]
        this_dt = parse_timestamp(front_file.name, match_re, time_format)
        last_dt = parse_timestamp(last_front.name, match_re, time_format)
        diff = (this_dt - last_dt).total_seconds() // 60
        log.debug('Pair gap: %s vs %s: %d minutes', front_file.name, last_front.name, diff)
        if diff > clip_length:
            log.debug('New group started with %s.', front_file.name)
            group = [pair]
            groups.append(group)
        else:
            group.append(pair)
    return groups


def archive_dashcam_footage(  # noqa: PLR0913, PLR0914
        front_dir: StrPath,
        rear_dir: StrPath | None,
        output_dir: StrPath,
        *,
        chapters: bool = True,
        clip_length: int = 3,
        container: str = 'matroska',
        crf: int | None = 28,
        extension: str = 'mkv',
        hwaccel: str | None = 'auto',
        keep_audio: bool = False,
        level: int | str | None = 'auto',
        group_fn: Callable[[Sequence[tuple[Path, Path]], int, re.Pattern[str] | str, str],
                           list[list[tuple[Path, Path]]]] = group_pairs,
        max_offset: int = 1,
        no_delete: bool = False,
        overwrite: bool = False,
        match_re: re.Pattern[str] | str = r'^(\d+)_.*',
        pair_fn: Callable[[StrPath, StrPath, re.Pattern[str] | str, str, int], list[tuple[Path,
                                                                                          Path]]]
    | None = pair_redtiger_dashcam_files,
        preset: str | None = 'slow',
        rear_crop: str | None = '1920:1020:0:0',
        rear_view_scale_divisor: float | None = 2.5,
        setpts: str | None = '0.25*PTS',
        temp_dir: StrPath | None = None,
        tier: str | None = 'high',
        time_format: str = '%Y%m%d%H%M%S',
        video_bitrate: str | None = '0k',
        video_decoder: str | None = 'hevc_cuvid',
        video_encoder: str = 'libx265',
        video_max_bitrate: str | None = '30M') -> None:
    """
    Batch encode dashcam footage, merging rear and front camera footage.

    This function's defaults are intended for use with Red Tiger dashcam output and file structure.

    The rear camera view will be placed in the bottom right of the video scaled by dividing the
    width and height by the ``rear_view_scale_divisor`` value specified. It will also be cropped
    using the ``rear_crop`` value unless it is ``None``.

    Files are automatically grouped using the regular expression passed with ``match_re``. The RE
    must contain at least one group, and only the first group will be considered. Make dubious use
    of non-capturing groups if necessary. The captured group string is expected to be usable with
    the time format specified with ``time_format`` (see ``strptime`` documentation at
    https://docs.python.org/3/library/datetime.html#datetime.datetime.strptime).

    Front and rear files are paired by timestamp proximity (within ``max_offset`` seconds). Files
    without a corresponding partner are logged and skipped without deletion.

    Original files whose content is successfully converted are sent to the wastebin.

    Default parameters are set to use libx265 software encoding with CUVID hardware decoding.

    Example:

    .. code::python

        archive_dashcam_footage('Movie_F', 'Movie_R', Path.home() / 'output')

    Parameters
    ----------
    front_dir : StrPath
        Directory containing front footage.
    rear_dir : StrPath | None
        Directory containing rear footage. If ``None``, single-camera mode is used.
    output_dir : StrPath
        Will be created if it does not exist, including parents.
    chapters : bool
        Embed chapter markers in the output file. Each clip pair becomes a chapter named after the
        front file stem without the trailing letter suffix (e.g. ``20260318101701_025194``).
    clip_length : int
        Clip length in minutes.
    container : str
        Container to use. Must match the extension. Passed to ffmpeg's ``-f`` option.
    crf : int | None
        Constant rate factor.
    extension : str
        Output file extension. Defaults to ``mkv``.
    hwaccel : str | None
        String passed to ffmpeg's ``-hwaccel`` option. If ``None``, do not use hardware acceleration
        for decoding.
    keep_audio : bool
        Keep audio in the output video. Defaults to ``False``.
    level : int | str | None
        Level (HEVC).
    group_fn : Callable[[Sequence[tuple[Path, Path]], int, re.Pattern[str] | str, str],
                        list[list[tuple[Path, Path]]]]
        Function to group pairs into recording sessions. Defaults to :py:func:`group_pairs`.
    max_offset : int
        Maximum seconds between front and rear timestamps for pairing.
    no_delete : bool
        Do not delete original files after successful conversion.
    overwrite : bool
        Overwrite existing files.
    match_re : re.Pattern[str] | str
        Regular expression used for finding the timestamp in a filename. Must contain at least one
        group and only the first group is considered.
    pair_fn : Callable[[StrPath, StrPath, re.Pattern[str] | str, str, int],
                       list[tuple[Path, Path]]] | None
        Function to pair front and rear files. Defaults to
        :py:func:`pair_redtiger_dashcam_files`. If ``None``, single-camera mode is used.
    preset : str | None
        Preset (various codecs).
    rear_crop : str | None
        Crop string for the rear video. See `ffmpeg crop filter`_ for more information.
    rear_view_scale_divisor : float | None
        Scaling divisor for rear view.
    setpts : str | None
        Change the PTS. See `ffmpeg setpts filter`_ for more information. The default speeds the
        video up by 4x.
    temp_dir : StrPath | None
        Temporary directory root.
    tier : str | None
        Tier (HEVC).
    time_format : str
        Time format string. See `strptime() Format Codes`_ for more information.
    video_bitrate : str | None
        Video bitrate string.
    video_decoder : str | None
        Video decoder.
    video_encoder : str
        Video encoder.
    video_max_bitrate : str | None
        Maximum video bitrate.

    Raises
    ------
    subprocess.CalledProcessError
        If an FFmpeg invocation fails.
    """  # noqa: DOC502
    from send2trash import send2trash  # noqa: PLC0415

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    # Do not sort the dicts.
    input_options: list[str] = list(
        chain(*((k, *((str(v),) if not isinstance(v, bool) and v is not None else ()))
                for k, v in ({
                    '-y': overwrite,
                    '-hwaccel': hwaccel
                }
                             | ({
                                 '-c:v': video_decoder
                             } if hwaccel else {})).items() if v)))
    crop_str = f'crop={rear_crop},' if rear_crop else ''
    setpts_str = f'setpts={setpts}' if setpts else ''
    hevc_nvenc_options = ({
        '-b_ref_mode': 'middle',
        '-cq': '25',
        '-level': level,
        '-rc': 'vbr',
        '-rc-lookahead': '32',
        '-spatial_aq': '1',
        '-temporal_aq': '1',
        '-tier': tier,
        '-tune': 'uhq'
    } if video_encoder == 'hevc_nvenc' else {})
    main_options = {'-an': not keep_audio, '-vcodec': video_encoder, '-f': container}
    libx264_options = {'-crf': str(crf)} if crf and video_encoder == 'libx264' else {}
    libx265_options = {'-crf': str(crf)} if crf and video_encoder == 'libx265' else {}
    video_bitrate_option = {'-b:v': video_bitrate} if video_bitrate else {}
    video_max_bitrate_option = {'-maxrate:v': video_max_bitrate} if video_max_bitrate else {}
    scale_filter = ((f'[0]{crop_str}'
                     f'scale=iw/{rear_view_scale_divisor}:ih/{rear_view_scale_divisor} [pip]; '
                     f'[1][pip]overlay=main_w-overlay_w:main_h-overlay_h')
                    if crop_str and rear_view_scale_divisor else '')
    filter_complex_option = ({
        '-filter_complex': f'{scale_filter},{setpts_str}'  # Trailing comma is acceptable.
    } if scale_filter or setpts_str else {})
    single_vf_option = {'-vf': setpts_str} if setpts_str else {}
    preset_option = {'-preset': preset} if preset else {}
    codec_options = (video_bitrate_option
                     | video_max_bitrate_option
                     | hevc_nvenc_options
                     | libx265_options
                     | libx264_options)
    dual_output_options = list(
        chain(*((k, *((str(v),) if not isinstance(v, bool) and v is not None else ()))
                for k, v in (main_options | preset_option | filter_complex_option
                             | codec_options).items() if v)))
    single_output_options = list(
        chain(*((k, *((str(v),) if not isinstance(v, bool) and v is not None else ()))
                for k, v in (main_options | preset_option | single_vf_option
                             | codec_options).items() if v)))
    pair_groups: list[list[tuple[Path | None, Path]]]
    if pair_fn is not None and rear_dir is not None:
        pairs = pair_fn(front_dir, rear_dir, match_re, time_format, max_offset)
        pair_groups = cast('list[list[tuple[Path | None, Path]]]',
                           group_fn(pairs, clip_length, match_re, time_format))
    else:
        file_groups = group_files(
            (str(x) for x in Path(front_dir).iterdir() if not x.name.startswith('.')), clip_length,
            match_re, time_format)
        pair_groups = [[(None, f) for f in grp] for grp in file_groups]
    log.debug('Pair group count: %d', len(pair_groups))
    for pair_group in pair_groups:
        with tempfile.NamedTemporaryFile('w',
                                         dir=temp_dir,
                                         encoding='utf-8',
                                         prefix='concat-',
                                         suffix='.txt') as temp_concat:
            log.debug('Group size: %d pairs', len(pair_group))
            to_be_merged: list[Path] = []
            send_to_waste: list[Path] = []
            metadata_path: str | None = None
            try:
                for i, (back_file, front_file) in enumerate(pair_group):
                    log.debug('Back file: %s, front file: %s', back_file, front_file)
                    if back_file is not None:
                        cmd = ('ffmpeg', '-hide_banner', *input_options, '-i', str(back_file), '-i',
                               str(front_file), *dual_output_options, '-')
                        send_to_waste += [front_file, back_file]
                    else:
                        cmd = ('ffmpeg', '-hide_banner', *input_options, '-i', str(front_file),
                               *single_output_options, '-')
                        send_to_waste.append(front_file)
                    log.debug('Running: %s', ' '.join(quote(x) for x in cmd))
                    with tempfile.NamedTemporaryFile(delete=False,
                                                     dir=temp_dir,
                                                     prefix=f'{i:04d}-',
                                                     suffix=f'.{extension}') as tf:
                        sp.run(cmd, stdout=tf, check=True, stderr=sp.PIPE)
                        tf_fixed = Path(tf.name).resolve(strict=True)
                        to_be_merged.append(tf_fixed)
                        temp_concat.write(f"file '{tf_fixed}'\n")
                temp_concat.flush()
                first_front = pair_group[0][1]
                full_output_path = output_dir / first_front.with_suffix(f'.{extension}').name
                if not overwrite:
                    suffix = 1
                    while full_output_path.exists():
                        offset = 5 if suffix > 1 else 0
                        full_output_path = (full_output_path.parent /
                                            f'{full_output_path.stem[:-offset]}-{suffix:04d}'
                                            f'{full_output_path.suffix}')
                        suffix += 1
                metadata_args: tuple[str, ...] = ()
                if chapters and len(to_be_merged) > 0:
                    with tempfile.NamedTemporaryFile('w',
                                                     dir=temp_dir,
                                                     encoding='utf-8',
                                                     prefix='metadata-',
                                                     suffix='.txt',
                                                     delete=False) as metadata_file:
                        metadata_file.write(';FFMETADATA1\n')
                        chapter_start = 0
                        for _merged_file, (_, front_file) in zip(to_be_merged,
                                                                 pair_group,
                                                                 strict=True):
                            source_duration = float(
                                ffprobe(front_file)['format'].get('duration')
                                or ffprobe(front_file)['streams'][0].get('duration', '0'))
                            pts_match = re.match(r'^([\d.]+)\*PTS$', setpts) if setpts else None
                            duration_s = (source_duration * float(pts_match.group(1))
                                          if pts_match else source_duration)
                            duration_ms = int(duration_s * 1000)
                            chapter_title = front_file.stem[:-1]
                            metadata_file.write(f'\n[CHAPTER]\nTIMEBASE=1/1000\n'
                                                f'START={chapter_start}\n'
                                                f'END={chapter_start + duration_ms}\n'
                                                f'title={chapter_title}\n')
                            chapter_start += duration_ms
                        metadata_path = metadata_file.name
                    metadata_args = ('-i', metadata_path, '-map_metadata', '1')
                    log.debug('Chapter metadata file: %s', metadata_path)
                cmd = ('ffmpeg', '-hide_banner', '-y', '-f', 'concat', '-safe', '0', '-i',
                       temp_concat.name, *metadata_args, '-c', 'copy', str(full_output_path))
                log.debug('Concatenating with: %s', ' '.join(quote(x) for x in cmd))
                sp.run(cmd, check=True, capture_output=True)
                if not no_delete:
                    for path in send_to_waste:
                        send2trash(path)
                        log.debug('Sent to wastebin: %s', path)
            finally:
                for path in to_be_merged:
                    path.unlink(missing_ok=True)
                if metadata_path is not None:
                    Path(metadata_path).unlink(missing_ok=True)


def hlg_to_sdr(input_file: StrPath,
               crf: int = 20,
               output_codec: Literal['libx265', 'libx264'] = 'libx265',
               output_file: StrPath | None = None,
               input_args: Sequence[str] | None = None,
               output_args: Sequence[str] | None = None,
               *,
               delete_after: bool = False,
               fast: bool = False) -> None:
    """
    Convert an HLG HDR video to SDR using tone mapping.

    Parameters
    ----------
    input_file : StrPath
        Path to the input HLG video file.
    crf : int
        Constant rate factor. Default is ``20``.
    output_codec : Literal['libx265', 'libx264']
        Output video codec. Default is ``'libx265'``.
    output_file : StrPath | None
        Output file path. If ``None``, defaults to ``<input_file>-sdr.<ext>``.
    input_args : Sequence[str] | None
        Additional input arguments for FFmpeg.
    output_args : Sequence[str] | None
        Additional output arguments for FFmpeg.
    delete_after : bool
        If ``True``, send the input file to the wastebin after conversion.
    fast : bool
        If ``True``, use fewer filters for faster but lower quality conversion.
    """
    from send2trash import send2trash  # noqa: PLC0415

    input_file = Path(input_file)
    vf = ((
        'zscale=t=linear:npl=100,'
        'format=gbrpf32le,'
        'zscale=p=bt709,'
        'tonemap=tonemap=hable:desat=0,'
        'zscale=t=bt709:m=bt709:r=tv,'
        'format=yuv420p'
    ) if fast else (
        'zscale=tin=arib-std-b67:min=bt2020nc:pin=bt2020:rin=tv:t=arib-std-b67:m=bt2020nc:p=bt2020:'
        'r=tv,'
        'zscale=t=linear:npl=100,'
        'format=gbrpf32le,'
        'zscale=p=bt709,'
        'tonemap=tonemap=hable:desat=0,'
        'zscale=t=bt709:m=bt709:r=tv,'
        'format=yuv420p'))
    output_file = (str(output_file) if output_file else str(
        input_file.parent / f'{input_file.stem}-sdr{input_file.suffix}'))
    cmd = ('ffmpeg', '-hide_banner', '-y', *(input_args or []), '-i', str(input_file),
           *(output_args or []), '-c:v', output_codec,
           '-crf', str(crf), '-vf', vf, '-acodec', 'copy', '-movflags', '+faststart',
           str(output_file) if output_file else f'{input_file.stem}-sdr{input_file.suffix}')
    log.debug('Running: %s', ' '.join(quote(x) for x in cmd))
    sp.run(cmd, check=True, capture_output=True)
    if delete_after:
        send2trash(input_file)
        log.debug('Sent to wastebin: %s', input_file)
