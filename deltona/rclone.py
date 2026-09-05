"""rclone utilities."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from shlex import quote
from typing import TYPE_CHECKING, Literal, TypeAlias
import logging
import os
import plistlib
import subprocess as sp
import sys
import tempfile
import threading

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .string import slugify

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from watchdog.events import FileSystemEvent

__all__ = ('DEFAULT_BISYNC_ARGS', 'DEFAULT_IDLE_SECONDS', 'DEFAULT_POLL_SECONDS', 'AlreadyRunning',
           'ServiceKind', 'bisync', 'default_remote', 'default_service_kind',
           'default_service_name', 'enable_service', 'generate_service', 'install_service',
           'service_path', 'single_instance', 'sync_once', 'watch_and_sync')

ServiceKind: TypeAlias = Literal['launchd', 'systemd-system', 'systemd-user']
"""
Kind of service manager a service definition targets.

:meta hide-value:
"""
DEFAULT_BISYNC_ARGS = ('--conflict-resolve', 'newer', '--drive-skip-gdocs', '--max-lock', '2m',
                       '--recover', '--resilient')
"""
Arguments always passed to ``rclone bisync``.

``--resilient`` and ``--recover`` keep a transient failure from locking out later runs, and
``--max-lock`` lets an abandoned lock expire. ``--drive-skip-gdocs`` omits Google Docs, which
report a size of ``-1`` and carry no checksum.

:meta hide-value:
"""
DEFAULT_IDLE_SECONDS = 10.0
"""
Seconds of quiet required before a burst of writes is synchronised.

:meta hide-value:
"""
DEFAULT_POLL_SECONDS = 300.0
"""
Longest wait between synchronisations, which is what notices changes made on the remote.

:meta hide-value:
"""
_SYSTEMD_SYSTEM_PATH = Path('/etc/systemd/system')
log = logging.getLogger(__name__)


class AlreadyRunning(RuntimeError):
    """Raised when another instance already holds the lock."""


def default_remote(local: Path) -> str:
    """
    Get the Google Drive remote that corresponds to a local directory.

    Parameters
    ----------
    local : Path
        Local directory.

    Returns
    -------
    str
        Remote in ``gdrive:name`` form.
    """
    return f'gdrive:{local.resolve().name}'


def default_service_kind() -> ServiceKind:
    """
    Get the service manager native to this platform.

    Returns
    -------
    ServiceKind
        ``launchd`` on macOS, otherwise ``systemd-user``.
    """
    return 'launchd' if sys.platform == 'darwin' else 'systemd-user'


def default_service_name(local: Path) -> str:
    """
    Get the service name that corresponds to a local directory.

    Parameters
    ----------
    local : Path
        Local directory.

    Returns
    -------
    str
        Service name.
    """
    return f'rclone-bisync-{slugify(local.resolve().name)}'


def service_path(kind: ServiceKind, name: str) -> Path:
    """
    Get where a service definition of this kind belongs.

    Parameters
    ----------
    kind : ServiceKind
        Kind of service manager.
    name : str
        Service name.

    Returns
    -------
    Path
        Path to the service definition.
    """
    match kind:
        case 'launchd':
            return Path.home() / 'Library' / 'LaunchAgents' / f'{name}.plist'
        case 'systemd-system':
            return _SYSTEMD_SYSTEM_PATH / f'{name}.service'
        case 'systemd-user':
            return Path.home() / '.config' / 'systemd' / 'user' / f'{name}.service'


def generate_service(kind: ServiceKind,
                     name: str,
                     command: Sequence[str],
                     *,
                     description: str = 'Bidirectional rclone sync.',
                     user: str | None = None) -> str:
    """
    Generate a service definition.

    Parameters
    ----------
    kind : ServiceKind
        Kind of service manager.
    name : str
        Service name.
    command : Sequence[str]
        Command the service runs.
    description : str
        Human-readable description.
    user : str | None
        Account the service runs as. Only used by ``systemd-system``.

    Returns
    -------
    str
        The service definition.
    """
    if kind == 'launchd':
        return plistlib.dumps(
            {
                # launchd starts jobs with a minimal PATH, which would keep the daemon from finding
                # rclone in a package manager's prefix.
                'EnvironmentVariables': {
                    'PATH': os.environ.get('PATH', '/usr/bin:/bin')
                },
                'KeepAlive': True,
                'Label': name,
                'ProgramArguments': list(command),
                'RunAtLoad': True
            },
            sort_keys=True).decode()
    lines = [
        '[Unit]',
        f'Description={description}',
        '',
        '[Service]',
        'Type=simple',
        f'ExecStart={" ".join(quote(part) for part in command)}',
        'Restart=on-failure',
        'RestartSec=30',
        # bisync releases its lock file cleanly when interrupted, and takes up to a minute to do
        # so. The default kill mode reaches rclone as well as the daemon.
        'KillSignal=SIGINT',
        'TimeoutStopSec=90'
    ]
    if kind == 'systemd-system' and user:
        lines.append(f'User={user}')
    target = 'multi-user.target' if kind == 'systemd-system' else 'default.target'
    lines += ['', '[Install]', f'WantedBy={target}', '']
    return '\n'.join(lines)


def enable_service(kind: ServiceKind, name: str) -> None:
    """
    Enable and start an installed service.

    Parameters
    ----------
    kind : ServiceKind
        Kind of service manager.
    name : str
        Service name.
    """
    match kind:
        case 'launchd':
            sp.run(('launchctl', 'bootstrap', f'gui/{os.getuid()}', str(service_path(kind, name))),
                   check=True)
        case 'systemd-system':
            sp.run(('systemctl', 'daemon-reload'), check=True)
            sp.run(('systemctl', 'enable', '--now', name), check=True)
        case 'systemd-user':
            sp.run(('systemctl', '--user', 'daemon-reload'), check=True)
            sp.run(('systemctl', '--user', 'enable', '--now', name), check=True)


def install_service(kind: ServiceKind,
                    name: str,
                    command: Sequence[str],
                    *,
                    description: str = 'Bidirectional rclone sync.',
                    enable: bool = True,
                    user: str | None = None) -> Path:
    """
    Write a service definition and optionally enable it.

    Parameters
    ----------
    kind : ServiceKind
        Kind of service manager.
    name : str
        Service name.
    command : Sequence[str]
        Command the service runs.
    description : str
        Human-readable description.
    enable : bool
        Enable and start the service once it is written.
    user : str | None
        Account the service runs as. Only used by ``systemd-system``.

    Returns
    -------
    Path
        Path the service definition was written to.
    """
    path = service_path(kind, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(generate_service(kind, name, command, description=description, user=user),
                    encoding='utf-8')
    log.info('Wrote `%s`.', path)
    if enable:
        enable_service(kind, name)
    return path


def _state_key(local: Path) -> str:
    # Path separators become part of the name so that two directories never share a key.
    return slugify(str(local.resolve()).replace('/', '-'))


@contextmanager
def single_instance(local: Path) -> Iterator[None]:
    """
    Hold an exclusive lock for a local directory.

    The lock is advisory and is released when the process exits, so an instance killed without
    warning does not leave the directory locked.

    Parameters
    ----------
    local : Path
        Local directory.

    Yields
    ------
    None
        With the lock held.

    Raises
    ------
    AlreadyRunning
        If another instance holds the lock.
    """
    import fcntl  # ruff:ignore[import-outside-top-level]
    runtime_dir = Path(os.environ.get('XDG_RUNTIME_DIR') or tempfile.gettempdir())
    with (runtime_dir / f'rclone-bisyncd{_state_key(local)}.lock').open('w',
                                                                        encoding='utf-8') as file:
        try:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            msg = f'Another instance is already syncing `{local}`.'
            raise AlreadyRunning(msg) from e
        yield


def bisync(local: Path,
           remote: str,
           rclone_args: Sequence[str] = (),
           *,
           resync: bool = False) -> None:
    """
    Run ``rclone bisync`` once.

    Parameters
    ----------
    local : Path
        Local directory.
    remote : str
        rclone remote, such as ``gdrive:Documents``.
    rclone_args : Sequence[str]
        Extra arguments appended after :py:data:`DEFAULT_BISYNC_ARGS`.
    resync : bool
        Rebuild the baseline listings. Required on the first run.
    """
    command = ('rclone', 'bisync', str(local), remote, *DEFAULT_BISYNC_ARGS, *rclone_args,
               *(('--resync',) if resync else ()))
    log.debug('Running: %s', ' '.join(quote(part) for part in command))
    sp.run(command, check=True)


def sync_once(local: Path, remote: str, rclone_args: Sequence[str] = ()) -> None:
    """
    Run ``rclone bisync``, building the baseline listings first if they do not exist yet.

    Parameters
    ----------
    local : Path
        Local directory.
    remote : str
        rclone remote, such as ``gdrive:Documents``.
    rclone_args : Sequence[str]
        Extra arguments appended after :py:data:`DEFAULT_BISYNC_ARGS`.
    """
    cache_dir = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache')
    stamp = cache_dir / 'rclone' / 'bisync' / f'.deltona-initialized{_state_key(local)}'
    if stamp.exists():
        bisync(local, remote, rclone_args)
        return
    log.info('No baseline for `%s`. Running with --resync.', local)
    bisync(local, remote, rclone_args, resync=True)
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.touch()


class _WriteFlag(FileSystemEventHandler):
    """Set an event whenever anything under the watched tree changes."""
    def __init__(self, flag: threading.Event) -> None:
        self._flag = flag

    def on_any_event(self, event: FileSystemEvent) -> None:
        """Record that the tree changed."""
        log.debug('Change detected at `%s`.', event.src_path)
        self._flag.set()


def _wait_for_writes(flag: threading.Event, idle: float, poll: float) -> None:
    if flag.wait(timeout=poll):
        while flag.wait(timeout=idle):
            flag.clear()
    # Cleared before synchronising rather than after, so that a write arriving mid-run is kept.
    # rclone's own writes cost one extra run that finds nothing to do.
    flag.clear()


def watch_and_sync(local: Path,
                   remote: str,
                   rclone_args: Sequence[str] = (),
                   *,
                   idle: float = DEFAULT_IDLE_SECONDS,
                   poll: float = DEFAULT_POLL_SECONDS) -> None:
    """
    Synchronise a local directory whenever it is written to, and periodically regardless.

    Writes are collected until the tree has been quiet for ``idle`` seconds, so that a burst
    produces one synchronisation rather than one per file. Returns when interrupted.

    Parameters
    ----------
    local : Path
        Local directory to watch, recursively.
    remote : str
        rclone remote, such as ``gdrive:Documents``.
    rclone_args : Sequence[str]
        Extra arguments appended after :py:data:`DEFAULT_BISYNC_ARGS`.
    idle : float
        Seconds of quiet required before a burst of writes is synchronised.
    poll : float
        Longest wait between synchronisations, which is what notices remote changes.
    """
    flag = threading.Event()
    observer = Observer()
    observer.schedule(_WriteFlag(flag), str(local), recursive=True)
    observer.start()
    log.info('Watching `%s`.', local)
    try:
        while True:
            _wait_for_writes(flag, idle, poll)
            sync_once(local, remote, rclone_args)
    except KeyboardInterrupt:
        log.info('Interrupted.')
    finally:
        observer.stop()
        observer.join()
