"""Uncategorised utilities."""

from __future__ import annotations

from http import HTTPStatus
from math import trunc
from pathlib import Path
from shlex import quote
from shutil import rmtree
from signal import SIGTERM
from typing import TYPE_CHECKING, Any, overload
import csv
import logging
import os
import re
import subprocess as sp
import time

from niquests.adapters import BaseAdapter
from typing_extensions import override
import niquests

from .media import CD_FRAMES
from .system import IS_WINDOWS, kill_wine

if TYPE_CHECKING:
    from collections.abc import Iterable

    from paramiko import SFTPClient, SSHClient

    from .typing import StrPath

__all__ = (
    'DataAdapter',
    'add_cdda_times',
    'kill_processes_by_name',
    'secure_move_path',
    'unregister_wine_file_associations',
)

ZERO_TO_99 = '|'.join(f'{x:02d}' for x in range(100))
ZERO_TO_59 = '|'.join(f'{x:02d}' for x in range(60))
ZERO_TO_74 = '|'.join(f'{x:02d}' for x in range(75))
TIMES_RE = re.compile(f'^({ZERO_TO_99}):({ZERO_TO_59}):({ZERO_TO_74})$')
MAX_MINUTES = 99
MAX_SECONDS = 60
log = logging.getLogger(__name__)


def add_cdda_times(times: Iterable[str] | None) -> str | None:
    """
    Add CDDA time strings and get a total runtime in CDDA format.

    CDDA format is ``MM:SS:FF`` where ``MM`` is minutes, ``SS`` is seconds, and ``FF`` is frames.

    Parameters
    ----------
    times : Iterable[str] | None
        CDDA time strings to add together.

    Returns
    -------
    str | None
        The total runtime in CDDA format, or ``None`` if the input is empty or invalid.
    """
    if not times:
        return None
    total_ms = 0
    for time_ in times:
        if not (res := re.match(TIMES_RE, time_)):
            return None
        minutes, seconds, frames = [int(x) for x in res.groups()]
        total_ms += ((minutes * MAX_SECONDS * 1000) + (seconds * 1000) +
                     ((frames * 1000) // CD_FRAMES))
    minutes = total_ms // (MAX_SECONDS * 1000)
    remainder_ms = total_ms % (MAX_SECONDS * 1000)
    seconds = remainder_ms // 1000
    remainder_ms %= 1000
    frames = round((remainder_ms * 1000 * CD_FRAMES) / 1000000)
    if minutes > MAX_MINUTES or seconds > (MAX_SECONDS - 1) or frames > (CD_FRAMES - 1):
        return None
    return f'{trunc(minutes):02d}:{trunc(seconds):02d}:{trunc(frames):02d}'


def unregister_wine_file_associations(*, debug: bool = False) -> None:
    """
    Remove Wine file associations, icons, and MIME types from the user's desktop environment.

    Kills running Wine processes before removing files.

    Parameters
    ----------
    debug : bool
        If ``True``, pass verbose flags to ``update-desktop-database`` and ``update-mime-database``.
    """
    kill_wine()
    for item in (Path.home() / '.local/share/applications').glob('wine-extension-*.desktop'):
        log.debug('Removing file association "%s".', item)
        item.unlink()
    for item in (Path.home() / '.local/share/icons/hicolor').rglob('application-x-wine-extension*'):
        log.debug('Removing icon "%s".', item)
        item.unlink()
    (Path.home() / '.local/share/applications/mimeinfo.cache').unlink(missing_ok=True)
    for item in (Path.home() / '.local/share/mime/packages').glob('x-wine*'):
        log.debug('Removing MIME file "%s".', item)
        item.unlink()
    for item in (Path.home() / '.local/share/application').glob('x-wine-extension*'):
        log.debug('Removing MIME file "%s".', item)
        item.unlink()
    cmd: tuple[str, ...] = (
        'update-desktop-database',
        *(('-v',) if debug else ()),
        str(Path.home() / '.local/share/applications'),
    )
    log.debug('Running: %s', ' '.join(quote(x) for x in cmd))
    sp.run(cmd, check=True)
    cmd = (
        'update-mime-database',
        *(('-v',) if debug else ()),
        str(Path.home() / '.local/share/mime'),
    )
    log.debug('Running: %s', ' '.join(quote(x) for x in cmd))
    sp.run(cmd, check=True)


def secure_move_path(
    client: SSHClient,
    filename: StrPath,
    remote_target: str,
    *,
    dry_run: bool = False,
    preserve_stats: bool = False,
    write_into: bool = False,
) -> None:
    """
    Move a file or directory to a remote host over SSH.

    Like ``scp`` but deletes the local file after a successful copy.

    Parameters
    ----------
    client : paramiko.SSHClient
        Connected SSH client.
    filename : StrPath
        Local file or directory to move.
    remote_target : str
        Remote destination path. ``~`` is expanded to the remote home directory.
    dry_run : bool
        If ``True``, do not perform any file operations.
    preserve_stats : bool
        If ``True``, preserve modification and access times.
    write_into : bool
        If ``True``, write into the target directory rather than creating a new one.
    """
    log.debug('Source: "%s", remote target: "%s"', filename, remote_target)

    def mkdir_ignore_existing(sftp: SFTPClient, td: str, times: tuple[float, float]) -> None:
        if not write_into:
            log.debug('MKDIR "%s"', td)
            if not dry_run:
                sftp.mkdir(td)
                if preserve_stats:
                    sftp.utime(td, times)
            return
        try:
            sftp.stat(td)
        except FileNotFoundError:
            log.debug('MKDIR "%s"', td)
            if not dry_run:
                sftp.mkdir(td)
                if preserve_stats:
                    sftp.utime(td, times)

    path = Path(filename)
    _, stdout, __ = client.exec_command('echo "${HOME}"')
    remote_target = remote_target.replace('~', stdout.read().decode().strip())
    with client.open_sftp() as sftp:
        if path.is_file():
            if not dry_run:
                sftp.put(filename, remote_target)
                if preserve_stats:
                    local_s = Path(filename).stat()
                    sftp.utime(remote_target, (local_s.st_atime, local_s.st_mtime))
            log.debug('Deleting local file "%s".', path)
            if not dry_run:
                path.unlink()
        else:
            pf = Path(filename)
            pf_stat = pf.stat()
            bn_filename = pf.name
            dn_prefix = str(pf).replace(bn_filename, '')
            mkdir_ignore_existing(sftp, remote_target, (pf_stat.st_atime, pf_stat.st_mtime))
            for root, dirs, files in os.walk(filename, followlinks=True):
                p_root = Path(root)
                remote_target_dir = f'{remote_target}/{bn_filename}'
                p_root_stat = p_root.stat()
                mkdir_ignore_existing(sftp, remote_target_dir,
                                      (p_root_stat.st_atime, p_root_stat.st_mtime))
                for name in sorted(dirs):
                    p_root_stat = (p_root / name).stat()
                    dp = str(p_root / name).replace(dn_prefix, '')
                    remote_target_dir = f'{remote_target}/{dp}'
                    mkdir_ignore_existing(sftp, remote_target_dir,
                                          (p_root_stat.st_atime, p_root_stat.st_mtime))
                for name in sorted(files):
                    src = p_root / name
                    dp = str(p_root / name).replace(dn_prefix, '')
                    log.debug('PUT "%s" "%s/%s"', src, remote_target, dp)
                    if not dry_run:
                        sftp.put(src, f'{remote_target}/{dp}')
                        if preserve_stats:
                            local_s = Path(src).stat()
                            sftp.utime(f'{remote_target}/{dp}',
                                       (local_s.st_atime, local_s.st_mtime))
            if not dry_run:
                rmtree(filename, ignore_errors=True)
            else:
                log.debug('Would delete local directory "%s".', filename)


@overload
def kill_processes_by_name(name: str) -> None:  # pragma: no cover
    pass


@overload
def kill_processes_by_name(name: str,
                           wait_timeout: float,
                           signal: int = SIGTERM,
                           *,
                           force: bool = False) -> list[int]:  # pragma: no cover
    pass


def kill_processes_by_name(name: str,
                           wait_timeout: float | None = None,
                           signal: int = SIGTERM,
                           *,
                           force: bool = False) -> list[int] | None:
    """
    Kill processes matching a name.

    On Windows, uses ``taskkill.exe``. On other platforms, uses ``killall``.

    Parameters
    ----------
    name : str
        Process name to kill.
    wait_timeout : float | None
        Seconds to wait after sending the signal. If ``None``, do not wait or collect PIDs.
    signal : int
        Signal number to send.
    force : bool
        If ``True``, forcefully kill remaining processes after the timeout.

    Returns
    -------
    list[int] | None
        List of PIDs that were found after the initial signal, or ``None`` if ``wait_timeout``
        is ``None``.
    """
    name = f'{name}{Path(name).suffix or ".exe"}' if IS_WINDOWS else name
    pids: list[int] = []
    if IS_WINDOWS:
        sp.run(('taskkill.exe', '/im', name), check=False, capture_output=True)  # noqa: S607
    else:
        sp.run(('killall', f'-{signal}', name), check=False, capture_output=True)  # noqa: S607
    if wait_timeout:
        lines = sp.run(
            ('tasklist.exe', '/fo', 'csv', '/fi', f'IMAGENAME eq {name}') if IS_WINDOWS else
            ('ps', 'ax'),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        if (pids := [int(x[1]) for x in list(csv.reader(lines))[1:]] if IS_WINDOWS else
            [int(y[0]) for y in (x.split() for x in lines) if Path(y[0]).name == name]):
            time.sleep(wait_timeout)
            if force:
                sp.run(
                    (
                        'taskkill.exe',
                        *(t for sl in (('/pid', str(pid)) for pid in pids) for t in sl),
                        '/f',
                    ) if IS_WINDOWS else ('kill', '-9', *(str(x) for x in pids)),
                    check=False,
                    capture_output=True,
                )
    return pids if wait_timeout else None


class DataAdapter(BaseAdapter):
    """Requests adapter that returns the URL content (after ``data:``) as the response body."""
    @override
    def send(  # type: ignore[override]
            self, request: niquests.PreparedRequest, **kwargs: Any) -> niquests.Response:
        """
        Send a request and return the URL content as the response body.

        Parameters
        ----------
        request : niquests.PreparedRequest
            The prepared request.
        **kwargs : Any
            Additional keyword arguments (unused, accepted for compatibility).

        Returns
        -------
        niquests.Response
            A response with the URL content (after ``data:``) as the body.
        """
        r = niquests.Response()
        assert request.url is not None
        r._content = request.url[5:].encode()  # noqa: SLF001
        r.status_code = HTTPStatus.OK
        return r

    @override
    def close(self) -> None:
        """Clean up adapter resources."""
