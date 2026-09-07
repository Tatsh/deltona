"""Service manager utilities."""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from shlex import quote
from typing import TYPE_CHECKING, Literal, TypeAlias
import logging
import os
import plistlib
import subprocess as sp
import sys

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ('LAUNCHD_LABEL_PREFIX', 'ServiceKind', 'default_service_kind', 'disable_service',
           'enable_service', 'generate_service', 'install_service', 'launchd_label', 'service_path',
           'uninstall_service')

ServiceKind: TypeAlias = Literal['launchd', 'systemd-system', 'systemd-user']
"""
Kind of service manager a service definition targets.

:meta hide-value:
"""
LAUNCHD_LABEL_PREFIX = 'sh.tat.deltona.'
"""
Reverse-DNS prefix given to launchd labels.

:meta hide-value:
"""
_SYSTEMD_SYSTEM_PATH = Path('/etc/systemd/system')
log = logging.getLogger(__name__)


def default_service_kind() -> ServiceKind:
    """
    Get the service manager native to this platform.

    Returns
    -------
    ServiceKind
        ``launchd`` on macOS, otherwise ``systemd-user``.
    """
    return 'launchd' if sys.platform == 'darwin' else 'systemd-user'


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
                     description: str = 'Managed by deltona.',
                     extra_service_lines: Sequence[str] = (),
                     user: str | None = None) -> str:
    """
    Generate a definition for a service that runs continuously.

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
    extra_service_lines : Sequence[str]
        Lines appended to the systemd ``[Service]`` section. Ignored by launchd.
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
                # launchd starts jobs with a minimal PATH, which would keep a daemon from finding
                # what it runs in a package manager's prefix.
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
        '[Unit]', f'Description={description}', '', '[Service]', 'Type=simple',
        f'ExecStart={" ".join(quote(part) for part in command)}', 'Restart=on-failure',
        'RestartSec=30', *extra_service_lines
    ]
    if kind == 'systemd-system' and user:
        lines.append(f'User={user}')
    target = 'multi-user.target' if kind == 'systemd-system' else 'default.target'
    lines += ['', '[Install]', f'WantedBy={target}', '']
    return '\n'.join(lines)


def enable_service(kind: ServiceKind, name: str) -> None:
    """
    Enable an installed service and start it, replacing it if it is already running.

    A rewritten definition does not reach the process running the old one, so the service is
    restarted rather than started.

    Parameters
    ----------
    kind : ServiceKind
        Kind of service manager.
    name : str
        Service name.
    """
    match kind:
        case 'launchd':
            # launchctl will not bootstrap a label that is already loaded, and booting out one that
            # was never loaded exits non-zero, which is the wanted state rather than a failure.
            with suppress(sp.CalledProcessError):
                sp.run(('launchctl', 'bootout', f'gui/{os.getuid()}/{launchd_label(name)}'),
                       check=True)
            sp.run(('launchctl', 'bootstrap', f'gui/{os.getuid()}', str(service_path(kind, name))),
                   check=True)
        case 'systemd-system':
            sp.run(('systemctl', 'daemon-reload'), check=True)
            sp.run(('systemctl', 'enable', name), check=True)
            sp.run(('systemctl', 'restart', name), check=True)
        case 'systemd-user':
            sp.run(('systemctl', '--user', 'daemon-reload'), check=True)
            sp.run(('systemctl', '--user', 'enable', name), check=True)
            sp.run(('systemctl', '--user', 'restart', name), check=True)


def install_service(kind: ServiceKind,
                    name: str,
                    command: Sequence[str],
                    *,
                    description: str = 'Managed by deltona.',
                    enable: bool = True,
                    extra_service_lines: Sequence[str] = (),
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
        Enable and start the service once it is written, restarting it if it is already running.
    extra_service_lines : Sequence[str]
        Lines appended to the systemd ``[Service]`` section. Ignored by launchd.
    user : str | None
        Account the service runs as. Only used by ``systemd-system``.

    Returns
    -------
    Path
        Path the service definition was written to.
    """
    path = service_path(kind, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(generate_service(kind,
                                     name,
                                     command,
                                     description=description,
                                     extra_service_lines=extra_service_lines,
                                     user=user),
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
