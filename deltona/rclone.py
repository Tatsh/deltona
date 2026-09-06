"""rclone utilities."""

from __future__ import annotations

from collections import deque
from contextlib import contextmanager, suppress
from datetime import datetime, timedelta, timezone
from pathlib import Path
from shlex import quote
from typing import TYPE_CHECKING, Any, Literal, TypeAlias
import json
import logging
import os
import plistlib
import re
import subprocess as sp
import sys
import tempfile
import threading
import time

from typing_extensions import override
from watchdog.events import (
    EVENT_TYPE_CLOSED_NO_WRITE,
    EVENT_TYPE_MODIFIED,
    EVENT_TYPE_OPENED,
    FileSystemEventHandler,
)
from watchdog.observers import Observer
import niquests
import pathspec
import platformdirs

from .string import pluralize, slugify

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence
    from pathlib import PurePath

    from pathspec.patterns.gitignore.basic import GitIgnoreBasicPattern
    from watchdog.events import FileSystemEvent

    IgnoreSpec: TypeAlias = pathspec.PathSpec[GitIgnoreBasicPattern]

__all__ = ('DEFAULT_BISYNC_ARGS', 'DEFAULT_CHANGES_LIMIT', 'DEFAULT_CHANGES_SINCE_SECONDS',
           'DEFAULT_DEDUPE_MODE', 'DEFAULT_DEDUPE_SECONDS', 'DEFAULT_IDLE_SECONDS',
           'DEFAULT_MAX_SYNCS_PER_MINUTE', 'DEFAULT_POLL_SECONDS', 'DEFAULT_REMOTE_NAME',
           'DEFAULT_REMOTE_POLL_SECONDS', 'DEFAULT_TOKEN_MARGIN_SECONDS', 'GRIVEIGNORE_NAME',
           'LAUNCHD_LABEL_PREFIX', 'RCLONE_CONFIG_ENV', 'AlreadyRunning', 'DedupeMode',
           'DriveChanges', 'InvalidCredentials', 'ServiceKind', 'access_token', 'bisync',
           'check_credentials', 'dedupe', 'default_remote', 'default_service_kind',
           'default_service_name', 'disable_service', 'enable_service', 'generate_service',
           'griveignore_filters', 'griveignore_spec', 'install_service', 'is_drive_remote',
           'launchd_label', 'rclone_config_path', 'recent_changes', 'service_path',
           'single_instance', 'sync_once', 'uninstall_service', 'watch_and_sync')

DedupeMode: TypeAlias = Literal['first', 'largest', 'newest', 'oldest', 'rename', 'skip',
                                'smallest']
"""
What ``rclone dedupe`` keeps when it finds files that share a name.

:meta hide-value:
"""
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
DEFAULT_CHANGES_LIMIT = 100
"""
Number of files a listing of recent changes reports when no limit is given.

:meta hide-value:
"""
DEFAULT_CHANGES_SINCE_SECONDS = 86400.0
"""
How far back a listing of recent changes reaches when no start is given.

:meta hide-value:
"""
DEFAULT_DEDUPE_MODE: DedupeMode = 'newest'
"""
What ``rclone dedupe`` keeps by default, matching ``--conflict-resolve newer``.

``rclone dedupe`` otherwise defaults to asking, which would hang an unattended daemon.

:meta hide-value:
"""
DEFAULT_DEDUPE_SECONDS = 3600.0
"""
Shortest wait between deduplications.

Google Drive lets two files in a directory share a name, which a local directory cannot represent.
Deduplicating costs a full recursive listing of the remote, so it is not worth doing after every
synchronisation.

:meta hide-value:
"""
DEFAULT_IDLE_SECONDS = 10.0
"""
Seconds of quiet required before a burst of writes is synchronised.

:meta hide-value:
"""
DEFAULT_MAX_SYNCS_PER_MINUTE = 5
"""
Most synchronisations started in a minute before the next one is held back.

bisync writing into the watched directory sets off the watcher that started it, which settles after
one further run that finds nothing to do. Anything that never settles would otherwise run as often
as ``idle`` allows, so the rate is capped and the cap is logged.

:meta hide-value:
"""
DEFAULT_POLL_SECONDS = 300.0
"""
Longest wait between synchronisations, regardless of whether anything is known to have changed.

:meta hide-value:
"""
DEFAULT_REMOTE_NAME = 'gdrive'
"""
Name of the rclone remote used when only a local directory is given.

:meta hide-value:
"""
DEFAULT_REMOTE_POLL_SECONDS = 15.0
"""
Wait between checks of the Google Drive changes feed.

Google Drive delivers change notifications only to a public HTTPS endpoint, so the feed is read
instead. One read is a single API request that returns nothing when the drive is idle, which is
cheap enough to repeat at this interval.

:meta hide-value:
"""
DEFAULT_TOKEN_MARGIN_SECONDS = 60.0
"""
How long before a stored access token expires it is treated as already expired.

An hour is all one lasts, and a read that starts just inside the margin can still be answered
after it, so refreshing early costs nothing and a refused request costs a round trip.

:meta hide-value:
"""
GRIVEIGNORE_NAME = '.griveignore'
"""
Name of the ignore file read from the top of a local directory.

It holds ``.gitignore`` patterns. Only the one at the top is read, not any in subdirectories.

:meta hide-value:
"""
LAUNCHD_LABEL_PREFIX = 'sh.tat.deltona.'
"""
Reverse-DNS prefix given to launchd labels.

:meta hide-value:
"""
RCLONE_CONFIG_ENV = 'RCLONE_CONFIG'
"""
Environment variable naming the rclone configuration file to use.

rclone reads it too, so setting it points this and every rclone it starts at the same file.

:meta hide-value:
"""
_GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'  # noqa: S105
# Go writes RFC 3339 with nanoseconds, which datetime only reads to microseconds, and only reads
# the trailing Z at all from 3.11.
_EXPIRY_RE = re.compile(r'^(?P<stamp>.+?T[^.+Z-]+)(?:\.(?P<fraction>\d+))?(?P<zone>Z|[+-].+)?$')
_QUIET_EVENTS = frozenset({EVENT_TYPE_CLOSED_NO_WRITE, EVENT_TYPE_OPENED})
_SYNC_WINDOW_SECONDS = 60.0
_DRIVE_CHANGES_FIELDS = ('changes/file(id,mimeType,name,parents),newStartPageToken,nextPageToken')
_DRIVE_CHANGES_URL = 'https://www.googleapis.com/drive/v3/changes'
_DRIVE_FILE_PARAMS = {'supportsAllDrives': 'true'}
_DRIVE_FILES_URL = 'https://www.googleapis.com/drive/v3/files'
_DRIVE_FOLDER_MIME = 'application/vnd.google-apps.folder'
_DRIVE_LIST_FIELDS = ('files(createdTime,explicitlyTrashed,id,'
                      'lastModifyingUser(displayName,emailAddress),mimeType,modifiedTime,name,'
                      'parents,size,trashed,webViewLink),nextPageToken')
_DRIVE_MAX_DEPTH = 64
_DRIVE_PAGE_SIZE = 1000
_SYSTEMD_SYSTEM_PATH = Path('/etc/systemd/system')
log = logging.getLogger(__name__)


class AlreadyRunning(RuntimeError):
    """Raised when another instance already holds the lock."""


class InvalidCredentials(RuntimeError):
    """Raised when the credentials rclone holds for a remote are absent or are refused."""


_DRIVE_ERRORS = (KeyError, OSError, ValueError, InvalidCredentials, niquests.RequestException,
                 sp.SubprocessError)


def default_remote(local: Path, name: str = DEFAULT_REMOTE_NAME) -> str:
    """
    Get the remote directory that corresponds to a local directory.

    Parameters
    ----------
    local : Path
        Local directory.
    name : str
        Name of the rclone remote to place the directory under.

    Returns
    -------
    str
        Remote in ``name:directory`` form.
    """
    return f'{name}:{local.resolve().name}'


def _griveignore_lines(local: Path) -> tuple[str, ...]:
    path = local / GRIVEIGNORE_NAME
    if not path.is_file():
        return ()
    return tuple(path.read_text(encoding='utf-8').splitlines())


def griveignore_spec(local: Path) -> pathspec.PathSpec[GitIgnoreBasicPattern] | None:
    """
    Read the ignore file at the top of a local directory.

    Parameters
    ----------
    local : Path
        Local directory holding the :py:data:`GRIVEIGNORE_NAME` file.

    Returns
    -------
    pathspec.PathSpec | None
        Matcher for paths relative to ``local``, or ``None`` if there is no ignore file.
    """
    if not (lines := _griveignore_lines(local)):
        return None
    return pathspec.PathSpec.from_lines('gitignore', lines)


def griveignore_filters(local: Path) -> tuple[str, ...]:
    """
    Translate the ignore file at the top of a local directory into rclone filter rules.

    rclone matches files rather than directories, so a pattern that is not restricted to
    directories becomes both itself and everything under it. A pattern holding a separator anywhere
    but at its end is anchored to ``local``, and one without a separator matches at any depth.

    Parameters
    ----------
    local : Path
        Local directory holding the :py:data:`GRIVEIGNORE_NAME` file.

    Returns
    -------
    tuple[str, ...]
        Rules for ``rclone --filter-from``. Empty if there is no ignore file.
    """
    rules: list[str] = []
    for line in _griveignore_lines(local):
        if not (pattern := line.strip()) or pattern.startswith('#'):
            continue
        sign = '-'
        if pattern.startswith('!'):
            sign, pattern = '+', pattern[1:]
        if not pattern:
            continue
        core = pattern.rstrip('/')
        base = f'/{core.lstrip("/")}' if '/' in core else f'/**/{core}'
        if not pattern.endswith('/'):
            rules.append(f'{sign} {base}')
        rules.append(f'{sign} {base}/**')
    # rclone stops at the first rule that matches whereas gitignore takes the last one, so the
    # order is reversed to keep a later negation winning.
    return tuple(reversed(rules))


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


def launchd_label(name: str) -> str:
    """
    Get the launchd label that corresponds to a service name.

    Parameters
    ----------
    name : str
        Service name.

    Returns
    -------
    str
        The name under :py:data:`LAUNCHD_LABEL_PREFIX`, unchanged if it is already there.
    """
    return name if name.startswith(LAUNCHD_LABEL_PREFIX) else f'{LAUNCHD_LABEL_PREFIX}{name}'


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
            return Path.home() / 'Library' / 'LaunchAgents' / f'{launchd_label(name)}.plist'
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
                'Label': launchd_label(name),
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


def disable_service(kind: ServiceKind, name: str) -> None:
    """
    Stop a service and keep it from starting again.

    Succeeds whether or not the service is loaded.

    Parameters
    ----------
    kind : ServiceKind
        Kind of service manager.
    name : str
        Service name.
    """
    command: tuple[str, ...]
    match kind:
        case 'launchd':
            command = ('launchctl', 'bootout', f'gui/{os.getuid()}/{launchd_label(name)}')
        case 'systemd-system':
            command = ('systemctl', 'disable', '--now', name)
        case 'systemd-user':
            command = ('systemctl', '--user', 'disable', '--now', name)
    # A service that was never loaded makes the manager exit non-zero, which is the wanted state
    # rather than a failure.
    with suppress(sp.CalledProcessError):
        sp.run(command, check=True)


def uninstall_service(kind: ServiceKind, name: str) -> Path | None:
    """
    Stop a service and delete its definition.

    Parameters
    ----------
    kind : ServiceKind
        Kind of service manager.
    name : str
        Service name.

    Returns
    -------
    Path | None
        Path the definition was deleted from, or ``None`` if there was nothing there.
    """
    path = service_path(kind, name)
    # Disabling before deleting lets systemd remove the symlinks it made, which needs the unit.
    disable_service(kind, name)
    if not path.exists():
        log.info('No service definition at `%s`.', path)
        return None
    path.unlink()
    log.info('Removed `%s`.', path)
    if kind != 'launchd':
        sp.run(('systemctl', 'daemon-reload') if kind == 'systemd-system' else
               ('systemctl', '--user', 'daemon-reload'),
               check=True)
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


def _run(command: Sequence[str]) -> float:
    log.debug('Running: %s', ' '.join(quote(part) for part in command))
    start = time.monotonic()
    sp.run(command, check=True)
    return time.monotonic() - start


@contextmanager
def _filter_file(local: Path) -> Iterator[Path | None]:
    if not (rules := griveignore_filters(local)):
        yield None
        return
    log.debug('Filtering with %d rule(s) from `%s`.', len(rules), local / GRIVEIGNORE_NAME)
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', prefix='deltona-filter-',
                                     suffix='.txt') as file:
        file.write('\n'.join(rules) + '\n')
        file.flush()
        yield Path(file.name)


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
    with _filter_file(local) as filters:
        command = ('rclone', 'bisync', str(local), remote, *DEFAULT_BISYNC_ARGS,
                   *(() if filters is None else
                     ('--filter-from', str(filters))), *rclone_args, *(('--resync',) if resync else
                                                                       ()))
        elapsed = _run(command)
        log.info('Synchronised `%s` with `%s` in %.1f seconds.', local, remote, elapsed)


def dedupe(remote: str, mode: DedupeMode = DEFAULT_DEDUPE_MODE) -> None:
    """
    Run ``rclone dedupe`` over a remote.

    Parameters
    ----------
    remote : str
        rclone remote, such as ``gdrive:Documents``.
    mode : DedupeMode
        What to keep out of the files that share a name.
    """
    elapsed = _run(('rclone', 'dedupe', '--dedupe-mode', mode, remote))
    log.info('Deduplicated `%s` in %.1f seconds.', remote, elapsed)


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


def _remote_name(remote: str) -> str:
    return remote.split(':', 1)[0]


def _remote_config(remote: str) -> dict[str, Any]:
    dump = sp.run(('rclone', 'config', 'dump'), capture_output=True, check=True, text=True).stdout
    config: dict[str, Any] = json.loads(dump).get(_remote_name(remote), {})
    return config


def rclone_config_path() -> Path:
    """
    Get the configuration file rclone reads.

    Returns
    -------
    Path
        The file named by :py:data:`RCLONE_CONFIG_ENV`, else the one rclone reports, else the
        platform's own configuration directory. Only a machine without a working rclone reaches
        that last one, where rclone's macOS location differs from the platform default.
    """
    if from_environment := os.environ.get(RCLONE_CONFIG_ENV):
        return Path(from_environment)
    with suppress(OSError, sp.SubprocessError):
        # rclone prints a sentence and then the path, so the path is the last line.
        reported = sp.run(('rclone', 'config', 'file'), capture_output=True, check=True,
                          text=True).stdout.splitlines()
        if reported:
            return Path(reported[-1].strip())
    return platformdirs.user_config_path('rclone') / 'rclone.conf'


def _expiry(token: Mapping[str, Any]) -> datetime | None:
    if not (raw := token.get('expiry')) or not (parts := _EXPIRY_RE.match(str(raw))):
        return None
    fraction = (parts['fraction'] or '')[:6].ljust(6, '0')
    zone = '+00:00' if parts['zone'] in {'Z', None} else parts['zone']
    with suppress(ValueError):
        return datetime.fromisoformat(f'{parts["stamp"]}.{fraction}{zone}')
    return None


def _stored_token(config: Mapping[str, Any], remote: str) -> dict[str, Any]:
    if not (token := config.get('token')):
        msg = (f'rclone has no stored credentials for `{_remote_name(remote)}`. Run `rclone config`'
               ' to authorise it.')
        raise InvalidCredentials(msg)
    # rclone keeps the token as JSON inside a string field.
    parsed: dict[str, Any] = json.loads(token) if isinstance(token, str) else dict(token)
    return parsed


def _store_token(path: Path, section: str, token: Mapping[str, Any]) -> None:
    # Only the one line is replaced. Rewriting the file from a parsed form would drop comments and
    # reorder what rclone wrote, and rclone may be part way through its own run against another
    # remote in it.
    try:
        lines = path.read_text(encoding='utf-8').splitlines(keepends=True)
    except OSError as e:
        log.warning('Could not read `%s` to store the refreshed token: %s', path, e)
        return
    current = ''
    for index, line in enumerate(lines):
        if (stripped := line.strip()).startswith('[') and stripped.endswith(']'):
            current = stripped[1:-1]
        elif current == section and re.match(r'token\s*=', stripped):
            lines[index] = f'token = {json.dumps(token)}\n'
            break
    else:
        log.warning('No token to replace for `%s` in `%s`.', section, path)
        return
    with tempfile.NamedTemporaryFile('w',
                                     delete=False,
                                     dir=path.parent,
                                     encoding='utf-8',
                                     prefix='.rclone.conf-') as file:
        file.write(''.join(lines))
        replacement = Path(file.name)
    replacement.chmod(path.stat().st_mode & 0o777)
    replacement.replace(path)
    log.debug('Stored a refreshed token for `%s`.', section)


def _refreshed(remote: str, config: Mapping[str, Any], token: Mapping[str, Any]) -> dict[str, Any]:
    name = _remote_name(remote)
    client_id, secret = config.get('client_id'), config.get('client_secret')
    if not (client_id and secret and (refresh_token := token.get('refresh_token'))):
        # rclone compiles its own client credentials in rather than storing them, so the exchange
        # cannot be made here. Reaching the remote through rclone makes rclone refresh and store.
        log.debug('Leaving the refresh of `%s` to rclone.', name)
        check_credentials(remote)
        return _stored_token(_remote_config(remote), remote)
    log.debug('Refreshing the access token of `%s`.', name)
    with niquests.Session() as session:
        response = session.post(_GOOGLE_TOKEN_URL,
                                data={
                                    'client_id': client_id,
                                    'client_secret': secret,
                                    'grant_type': 'refresh_token',
                                    'refresh_token': refresh_token
                                })
    if not response.ok:
        msg = (f'Refreshing the access token of `{name}` was refused. Run `rclone config reconnect'
               f' {name}:` to authorise it again.')
        raise InvalidCredentials(msg)
    granted = response.json()
    expiry = datetime.now(timezone.utc) + timedelta(seconds=float(granted.get('expires_in', 3600)))
    # The refresh token is kept: a refresh does not return one unless it has been rotated.
    updated = dict(token) | {
        'access_token': granted['access_token'],
        'expiry': expiry.isoformat().replace('+00:00', 'Z')
    }
    if refreshed := granted.get('refresh_token'):
        updated['refresh_token'] = refreshed
    _store_token(rclone_config_path(), name, updated)
    return updated


def access_token(remote: str, margin: float = DEFAULT_TOKEN_MARGIN_SECONDS) -> str:
    """
    Get an access token for a remote, refreshing the stored one when it is about to expire.

    A token rclone stored lasts an hour and is only renewed when rclone itself reaches the remote,
    so one read straight out of the configuration is not necessarily still good. A refresh is
    written back so that rclone sees it too.

    Parameters
    ----------
    remote : str
        rclone remote, such as ``gdrive:Documents``.
    margin : float
        Seconds before expiry at which the token counts as expired.

    Returns
    -------
    str
        A token that is current as far as its recorded expiry says.

    Raises
    ------
    InvalidCredentials
        If rclone holds no token for the remote, or refreshing it is refused.
    """  # noqa: DOC502
    config = _remote_config(remote)
    token = _stored_token(config, remote)
    expiry = _expiry(token)
    if expiry is not None and expiry - timedelta(seconds=margin) <= datetime.now(timezone.utc):
        token = _refreshed(remote, config, token)
    return str(token['access_token'])


def is_drive_remote(remote: str) -> bool:
    """
    Determine whether a remote is backed by Google Drive.

    Parameters
    ----------
    remote : str
        rclone remote, such as ``gdrive:Documents``.

    Returns
    -------
    bool
        ``True`` if rclone has the remote configured with type ``drive``.
    """
    return _remote_config(remote).get('type') == 'drive'


def check_credentials(remote: str) -> None:
    """
    Verify that rclone can authorise against a remote, and refresh its stored access token.

    Reaching the remote is what makes rclone notice an expired access token and store a fresh one,
    so calling this before reading the changes feed keeps a token that went stale while the daemon
    was down from being mistaken for a bad one.

    Parameters
    ----------
    remote : str
        rclone remote, such as ``gdrive:Documents``.

    Raises
    ------
    InvalidCredentials
        If rclone cannot reach the remote with the credentials it holds.
    """
    name = _remote_name(remote)
    try:
        sp.run(('rclone', 'about', f'{name}:'), capture_output=True, check=True, text=True)
    except sp.CalledProcessError as e:
        msg = f'rclone cannot authorise `{name}`: {(e.stderr or "").strip()}'
        raise InvalidCredentials(msg) from e


def _refused_message(remote: str) -> str:
    name = _remote_name(remote)
    return (f'Google Drive refused the credentials rclone holds for `{name}`. Run `rclone config'
            f' reconnect {name}:` to authorise it again.')


def _drive_get(session: niquests.Session, headers: Mapping[str, str], url: str,
               params: Mapping[str, str], refused: str) -> Any:
    response = session.get(url, headers=dict(headers), params=dict(params))
    if response.status_code in {401, 403}:
        raise InvalidCredentials(refused)
    response.raise_for_status()
    return response.json()


def _rfc3339(when: datetime) -> str:
    return when.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def recent_changes(remote: str = DEFAULT_REMOTE_NAME,
                   since: datetime | None = None,
                   until: datetime | None = None,
                   limit: int = DEFAULT_CHANGES_LIMIT,
                   token: str | None = None) -> Iterator[dict[str, Any]]:
    """
    List the files most recently changed on the Google Drive account behind a remote.

    The whole account is listed, not the directory the remote points at, and the newest change comes
    first. Deletions do not appear. Google serves those only through the changes feed
    :py:class:`DriveChanges` reads, which begins at the moment it is opened and cannot be asked
    about a time already past.

    Parameters
    ----------
    remote : str
        rclone remote, such as ``gdrive:Documents``. Any path on it is ignored.
    since : datetime | None
        Report only files modified after this. Defaults to
        :py:data:`DEFAULT_CHANGES_SINCE_SECONDS` seconds ago.
    until : datetime | None
        Report only files modified before this.
    limit : int
        Maximum number of files to report.
    token : str | None
        Access token to send instead of the one rclone holds.

    Yields
    ------
    dict[str, Any]
        A Drive file resource as Google sends it.

    Raises
    ------
    InvalidCredentials
        If rclone holds no token for the remote, or Google Drive refuses the one it is sent.
    """  # noqa: DOC502
    since = since or (datetime.now(timezone.utc) - timedelta(seconds=DEFAULT_CHANGES_SINCE_SECONDS))
    query = [f"modifiedTime > '{_rfc3339(since)}'"]
    if until is not None:
        query.append(f"modifiedTime < '{_rfc3339(until)}'")
    params = {
        'fields': _DRIVE_LIST_FIELDS,
        'orderBy': 'modifiedTime desc',
        'pageSize': str(min(max(limit, 1), _DRIVE_PAGE_SIZE)),
        'q': ' and '.join(query),
        'supportsAllDrives': 'true'
    }
    if drive_id := _remote_config(remote).get('team_drive'):
        params |= {'driveId': str(drive_id), 'includeItemsFromAllDrives': 'true'}
    headers = {'Authorization': f'Bearer {token or access_token(remote)}'}
    refused = ('Google Drive refused the access token given on the command line.'
               if token else _refused_message(remote))
    reported = 0
    page: str | None = None
    with niquests.Session() as session:
        while True:
            data = _drive_get(session, headers, _DRIVE_FILES_URL,
                              params | {'pageToken': page} if page else params, refused)
            for file in data.get('files') or ():
                yield dict(file)
                reported += 1
                if reported >= limit:
                    return
            if not (page := data.get('nextPageToken')):
                return


class _Ignore:
    """
    The ignore file of a local directory.

    Consulting the patterns re-reads the file if it has changed since the last look, so an edit
    takes effect without restarting anything.
    """
    def __init__(self, local: Path) -> None:
        self._local = local
        self._lock = threading.Lock()
        self._spec: IgnoreSpec | None = None
        self._stamp: tuple[float, int] | None = None
        self._loaded = False
        self.refresh()

    @property
    def spec(self) -> IgnoreSpec | None:
        """Patterns as they stand on disk."""
        self.refresh()
        return self._spec

    def match(self, path: str | PurePath) -> bool:
        """
        Determine whether a path relative to the local directory is ignored.

        Parameters
        ----------
        path : str | PurePath
            Path relative to the local directory.

        Returns
        -------
        bool
            Whether the patterns exclude it.
        """
        self.refresh()
        spec = self._spec
        return spec is not None and spec.match_file(path)

    def refresh(self) -> None:
        """Re-read the ignore file if it has changed since it was last read."""
        path = self._local / GRIVEIGNORE_NAME
        try:
            status = path.stat()
        except OSError:
            stamp = None
        else:
            stamp = (status.st_mtime, status.st_size)
        with self._lock:
            if self._loaded and stamp == self._stamp:
                return
            if self._loaded:
                log.info('Reloading `%s`.', path)
            self._loaded = True
            self._stamp = stamp
            self._spec = griveignore_spec(self._local)


class DriveChanges:
    """
    Reader for the Google Drive changes feed of one remote.

    Google Drive reports a change as a name and a parent rather than as a path, so the reader keeps
    the identifier of the directory the remote points at along with the name and parent of every
    directory it has had to look up. A change is then matched by its path relative to the remote,
    and one that turns out to sit outside the remote is not a change at all.
    """
    def __init__(self, remote: str, margin: float = DEFAULT_TOKEN_MARGIN_SECONDS) -> None:
        self._directories: dict[str, tuple[str, str | None]] = {}
        self._headers: dict[str, str] = {}
        self._margin = margin
        self._page_token: str | None = None
        self._remote = remote
        self._root: str | None = None
        self._shared: dict[str, str] = {}

    def poll(self, ignore: IgnoreSpec | None = None) -> bool:
        """
        Read everything that has changed since the previous call.

        The first call reports nothing and only records where the feed has reached.

        Parameters
        ----------
        ignore : pathspec.PathSpec | None
            Patterns, relative to the remote, whose matches do not count as a change.

        Returns
        -------
        bool
            Whether anything that is not ignored changed.

        Raises
        ------
        InvalidCredentials
            If rclone holds no token for the remote, or Google Drive refuses the one it holds.
        """  # noqa: DOC502
        self._authorise()
        with niquests.Session() as session:
            if self._page_token is None:
                self._page_token = str(
                    self._get(session, f'{_DRIVE_CHANGES_URL}/startPageToken',
                              self._feed_params())['startPageToken'])
                return False
            if self._root is None:
                self._root = self._resolve_root(session)
            wanted = False
            while True:
                data = self._get(
                    session, _DRIVE_CHANGES_URL,
                    self._feed_params() | {
                        'fields': _DRIVE_CHANGES_FIELDS,
                        'pageSize': '1000',
                        'pageToken': self._page_token
                    })
                wanted = wanted or self._wanted(session, data.get('changes') or (), ignore)
                if not (following := data.get('nextPageToken')):
                    self._page_token = str(data['newStartPageToken'])
                    return wanted
                self._page_token = str(following)

    @property
    def remote(self) -> str:
        """The rclone remote the feed is read for."""
        return self._remote

    def _authorise(self) -> None:
        self._headers = {'Authorization': f'Bearer {access_token(self._remote, self._margin)}'}
        self._shared = {'supportsAllDrives': 'true'}
        if drive_id := _remote_config(self._remote).get('team_drive'):
            self._shared['driveId'] = str(drive_id)

    def _feed_params(self) -> dict[str, str]:
        # Only the feed accepts these two; a lookup of a single file rejects them.
        if 'driveId' not in self._shared:
            return dict(self._shared)
        return self._shared | {'includeItemsFromAllDrives': 'true'}

    def _get(self, session: niquests.Session, url: str, params: Mapping[str, str]) -> Any:
        return _drive_get(session, self._headers, url, params, _refused_message(self._remote))

    def _path(self, session: niquests.Session, file: Mapping[str, Any]) -> str | None:
        parts = [str(file['name'])]
        parent = next(iter(file.get('parents') or ()), None)
        for _ in range(_DRIVE_MAX_DEPTH):
            if parent is None:
                return None
            if parent == self._root:
                return '/'.join(reversed(parts))
            if parent not in self._directories:
                found = self._get(session, f'{_DRIVE_FILES_URL}/{parent}',
                                  {'fields': 'name,parents'} | _DRIVE_FILE_PARAMS)
                self._directories[parent] = (str(found.get(
                    'name', '')), next(iter(found.get('parents') or ()), None))
            name, parent = self._directories[parent]
            parts.append(name)
        return None

    def _resolve_root(self, session: niquests.Session) -> str:
        current = self._shared.get('driveId') or str(
            self._get(session, f'{_DRIVE_FILES_URL}/root',
                      {'fields': 'id'} | _DRIVE_FILE_PARAMS)['id'])
        for part in self._remote.split(':', 1)[1].strip('/').split('/'):
            if not part:
                continue
            quoted = part.replace('\\', '\\\\').replace("'", "\\'")
            found = self._get(
                session, _DRIVE_FILES_URL, {
                    'fields':
                        'files/id',
                    'q': (f"'{current}' in parents and name = '{quoted}' and mimeType = "
                          f"'{_DRIVE_FOLDER_MIME}' and trashed = false")
                } | _DRIVE_FILE_PARAMS)
            if not (files := found.get('files')):
                log.warning('`%s` does not exist on the remote yet.', self._remote)
                return current
            current = str(files[0]['id'])
        return current

    def _wanted(self, session: niquests.Session, changes: Sequence[Mapping[str, Any]],
                ignore: IgnoreSpec | None) -> bool:
        for change in changes:
            file = change.get('file') or {}
            # Renaming or moving a directory invalidates every path built through it.
            if file.get('mimeType') == _DRIVE_FOLDER_MIME:
                self._directories.pop(str(file.get('id', '')), None)
            if not file.get('name'):
                # A removal carries no file, so where it was cannot be looked up any more.
                return True
            if (path := self._path(session, file)) is None:
                continue
            if ignore is None or not ignore.match_file(path):
                return True
        return False


def _watch_remote(reader: DriveChanges, flag: threading.Event, stop: threading.Event,
                  interval: float, ignore: _Ignore) -> None:
    while not stop.is_set():
        try:
            changed = reader.poll(ignore.spec)
        except _DRIVE_ERRORS as e:
            log.warning('Could not read the changes feed: %s', e)
            # An access token lives an hour, so the stored one goes stale between reads. Reaching
            # the remote makes rclone store a fresh one for the next read to pick up.
            with suppress(*_DRIVE_ERRORS):
                check_credentials(reader.remote)
        else:
            if changed:
                log.debug('Remote `%s` changed.', reader.remote)
                flag.set()
        stop.wait(interval)


class _WriteFlag(FileSystemEventHandler):
    """Set an event whenever anything under the watched tree changes."""
    def __init__(self, flag: threading.Event, root: Path, ignore: _Ignore) -> None:
        self._flag = flag
        self._ignore = ignore
        self._root = root

    @override
    def on_any_event(self, event: FileSystemEvent) -> None:
        """Record that the tree changed."""
        # Opening a file for reading reports both of these and nothing else. rclone reads every
        # file it compares, and the filters are read from the tree as well, so treating a read as a
        # change means every run arms the watcher that starts the next one.
        if event.event_type in _QUIET_EVENTS:
            return
        # Writing to a file marks the directory holding it as modified. Whatever happened to the
        # child is reported separately, so this carries nothing new and would otherwise leak a
        # change to an ignored file, whose own event is dropped just below.
        if event.is_directory and event.event_type == EVENT_TYPE_MODIFIED:
            return
        # A move reports where it came from and where it went, and only counts as ignored when
        # neither end is wanted.
        paths = (event.src_path, getattr(event, 'dest_path', ''))
        if all(not path or self._ignored(str(path)) for path in paths):
            return
        log.debug('Change detected at `%s` (%s).', event.src_path, event.event_type)
        self._flag.set()

    def _ignored(self, path: str) -> bool:
        try:
            relative = Path(path).relative_to(self._root)
        except ValueError:
            return False
        return self._ignore.match(relative)


def _wait_for_writes(flag: threading.Event, idle: float, poll: float) -> bool:
    if woken := flag.wait(timeout=poll):
        while flag.wait(timeout=idle):
            flag.clear()
    # Cleared before synchronising rather than after, so that a write arriving mid-run is kept.
    # rclone's own writes cost one extra run that finds nothing to do.
    flag.clear()
    return woken


def _next_chain(chain: int, poll: float, *, woken: bool) -> int:
    # A chain of runs set off by a change is only known to be over once nothing has woken the loop
    # for a whole poll, so that is the earliest it can be reported.
    if woken:
        return chain + 1
    if chain:
        log.info('Settled after %d %s, with no change for %.0f seconds.', chain,
                 pluralize(chain, 'synchronisation'), poll)
    return 0


def _throttle(stamps: deque[float], limit: int) -> None:
    if limit <= 0:
        return
    stamps.append(time.monotonic())
    # The deque holds the last `limit` start times, so its span is how long they took.
    if len(stamps) < limit or (wait := _SYNC_WINDOW_SECONDS - (stamps[-1] - stamps[0])) <= 0:
        return
    log.warning(
        'Synchronised %d times in under a minute, which means something is not settling. Waiting'
        ' %.0f seconds.', len(stamps), wait)
    time.sleep(wait)


def _dedupe_if_due(remote: str, mode: DedupeMode, interval: float,
                   last: float | None) -> float | None:
    if interval <= 0 or (last is not None and time.monotonic() - last < interval):
        return last
    dedupe(remote, mode)
    return time.monotonic()


def watch_and_sync(local: Path,
                   remote: str,
                   rclone_args: Sequence[str] = (),
                   *,
                   dedupe_interval: float = DEFAULT_DEDUPE_SECONDS,
                   dedupe_mode: DedupeMode = DEFAULT_DEDUPE_MODE,
                   idle: float = DEFAULT_IDLE_SECONDS,
                   max_syncs_per_minute: int = DEFAULT_MAX_SYNCS_PER_MINUTE,
                   poll: float = DEFAULT_POLL_SECONDS,
                   remote_poll: float = DEFAULT_REMOTE_POLL_SECONDS) -> None:
    """
    Synchronise a local directory whenever either side changes, and periodically regardless.

    Changes are collected until both sides have been quiet for ``idle`` seconds, so that a burst
    produces one synchronisation rather than one per file. Paths matching the
    :py:data:`GRIVEIGNORE_NAME` file at the top of ``local`` are neither watched nor synchronised.
    Returns when interrupted.

    Parameters
    ----------
    local : Path
        Local directory to watch, recursively.
    remote : str
        rclone remote, such as ``gdrive:Documents``.
    rclone_args : Sequence[str]
        Extra arguments appended after :py:data:`DEFAULT_BISYNC_ARGS`.
    dedupe_interval : float
        Shortest wait between deduplications, which run after a synchronisation. Zero disables them.
    dedupe_mode : DedupeMode
        What deduplication keeps out of the files that share a name.
    idle : float
        Seconds of quiet required before a burst of changes is synchronised.
    max_syncs_per_minute : int
        Synchronisations allowed in a minute before the next one is held back and the rate is
        logged as a warning. Zero allows any rate.
    poll : float
        Longest wait between synchronisations.
    remote_poll : float
        Wait between reads of the Google Drive changes feed. Zero disables them, leaving ``poll``
        to notice remote changes. Ignored unless ``remote`` is a Google Drive remote, in which case
        the credentials rclone holds for it are checked before watching starts and
        :py:class:`InvalidCredentials` is raised if they are absent or refused.
    """
    flag = threading.Event()
    stop = threading.Event()
    ignore = _Ignore(local)
    watcher = None
    if remote_poll > 0 and is_drive_remote(remote):
        # Check the credentials before anything is started, so that a remote that cannot be reached
        # is reported once at startup instead of every remote_poll seconds forever. This also
        # refreshes a token that expired while the daemon was down, which would otherwise look like
        # a bad one to the changes feed.
        check_credentials(remote)
        reader = DriveChanges(remote)
        reader.poll()
        watcher = threading.Thread(target=_watch_remote,
                                   args=(reader, flag, stop, remote_poll, ignore),
                                   daemon=True)
    observer = Observer()
    observer.schedule(_WriteFlag(flag, local.resolve(), ignore), str(local), recursive=True)
    observer.start()
    if watcher:
        watcher.start()
    log.info('Watching `%s`.', local)
    last_dedupe: float | None = None
    stamps: deque[float] = deque(maxlen=max(max_syncs_per_minute, 1))
    chain = 0
    try:
        while True:
            chain = _next_chain(chain, poll, woken=_wait_for_writes(flag, idle, poll))
            sync_once(local, remote, rclone_args)
            last_dedupe = _dedupe_if_due(remote, dedupe_mode, dedupe_interval, last_dedupe)
            _throttle(stamps, max_syncs_per_minute)
    except KeyboardInterrupt:
        log.info('Interrupted.')
    finally:
        stop.set()
        observer.stop()
        observer.join()
        if watcher:
            watcher.join()
