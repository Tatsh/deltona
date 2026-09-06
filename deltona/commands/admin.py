"""System administration commands."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple, TextIO
import json
import logging
import os
import re
import shutil
import subprocess as sp
import sys

from bascom import setup_logging
from rich.console import Console
from rich.filesize import decimal
from rich.table import Table
from rich.text import Text
import click

from deltona.constants import CONTEXT_SETTINGS, SYSLOG_SOCKETS
from deltona.gentoo import (
    DEFAULT_ACTIVE_KERNEL_NAME,
    DEFAULT_KERNEL_LOCATION,
    DEFAULT_MODULES_PATH,
    clean_old_kernels_and_modules,
)
from deltona.rclone import (
    DEFAULT_CHANGES_LIMIT,
    DEFAULT_DEDUPE_MODE,
    DEFAULT_DEDUPE_SECONDS,
    DEFAULT_IDLE_SECONDS,
    DEFAULT_MAX_SYNCS_PER_MINUTE,
    DEFAULT_POLL_SECONDS,
    DEFAULT_REMOTE_NAME,
    DEFAULT_REMOTE_POLL_SECONDS,
    RCLONE_CONFIG_ENV,
    AlreadyRunning,
    InvalidCredentials,
    bisync,
    dedupe,
    default_remote,
    default_service_kind,
    default_service_name,
    generate_service,
    install_service,
    recent_changes,
    single_instance,
    sync_once,
    uninstall_service,
    watch_and_sync,
)
from deltona.system import (
    MultipleKeySlots,
    get_kconfig_dict,
    get_kwriteconfig_commands,
    patch_macos_bundle_info_plist,
    reset_tpm_enrollment,
    slug_rename,
)
from deltona.utils import secure_move_path
from deltona.www import generate_html_dir_tree

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping, Sequence

    from paramiko import SSHClient

    from deltona.rclone import DedupeMode, ServiceKind


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('uuids', nargs=-1)
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
@click.option('-a', '--all', 'all_', is_flag=True, help='Reset all enrolments.')
@click.option('-f', '--force', is_flag=True, help='Apply the changes.')
@click.option('--crypttab',
              type=click.Path(path_type=Path, dir_okay=False, exists=True),
              help='File to read from when passing --all.',
              default='/etc/crypttab')
def reset_tpm_enrollments_main(uuids: Sequence[str],
                               crypttab: Path,
                               *,
                               all_: bool = False,
                               debug: bool = False,
                               force: bool = False) -> None:
    """
    Reset TPM enrolments that were created by systemd-cryptenroll -tpm2-device=auto.

    Requires root privileges to work.

    Only crypttab files with UUID= entries are supported.
    """
    setup_logging(debug=debug, loggers={'deltona': {}})
    if all_:
        uuids = [
            x[1][5:]
            for x in (re.split(r'\s+', line, maxsplit=4)
                      for line in (li.strip()
                                   for li in crypttab.read_text(encoding='utf-8').splitlines())
                      if not line.startswith('#')) if 'tpm2-device=auto' in x[3] and 'UUID=' in x[1]
        ]
    for uuid in uuids:
        try:
            reset_tpm_enrollment(uuid, dry_run=not force)
        except MultipleKeySlots:  # ruff:ignore[try-except-in-loop]
            click.echo(f'Cannot reset TPM enrolment for {uuid}.')
            continue


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('path',
                type=click.Path(exists=True, dir_okay=True, file_okay=False, path_type=Path),
                default=DEFAULT_KERNEL_LOCATION)
@click.option('--active-kernel-name',
              help='Kernel name like "linux".',
              default=DEFAULT_ACTIVE_KERNEL_NAME)
@click.option('-m',
              '--modules-path',
              type=click.Path(exists=True, dir_okay=True, file_okay=False, path_type=Path),
              help='Location where modules get installed, such as "/lib/modules".',
              default=DEFAULT_MODULES_PATH)
@click.option('-d', '--debug', is_flag=True, help='Enable debug logging.')
def clean_old_kernels_and_modules_main(path: Path = DEFAULT_KERNEL_LOCATION,
                                       modules_path: Path = DEFAULT_MODULES_PATH,
                                       active_kernel_name: str = DEFAULT_ACTIVE_KERNEL_NAME,
                                       *,
                                       debug: bool = False) -> None:
    """
    Remove inactive kernels and modules.

    By default, removes old Linux sources from /usr/src.
    """
    setup_logging(debug=debug, loggers={'deltona': {}})
    for item in clean_old_kernels_and_modules(path, modules_path, active_kernel_name):
        click.echo(item)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('filenames', nargs=-1)
@click.option('--no-lower', is_flag=True, help='Disable lowercase.')
@click.option('-v', '--verbose', is_flag=True, help='Enable verbose output.')
def slug_rename_main(filenames: tuple[str, ...],
                     *,
                     no_lower: bool = False,
                     verbose: bool = False) -> None:
    """Rename a file to a slugified version."""
    for name in filenames:
        target = slug_rename(name, no_lower=no_lower)
        if verbose:
            click.echo(f'{name} -> {target}')


def _get_ssh_client_cls() -> type[SSHClient]:  # pragma: no cover
    from paramiko import SSHClient  # ruff:ignore[import-outside-top-level]

    return SSHClient


def _parse_target(target: str) -> tuple[str | None, str, str]:
    host_part, _, path = target.partition(':')
    if '@' in host_part:
        user, _, host = host_part.partition('@')
        return user, host, path
    return None, host_part, path


_SUPPORTED_SSH_OPTIONS = frozenset(
    {'compression', 'connecttimeout', 'hostname', 'identityfile', 'port', 'proxyjump', 'user'})


class _JumpHop(NamedTuple):
    """A single jump hop in an ssh chain."""

    host: str
    """Hostname or IP address."""
    port: int
    """TCP port."""
    user: str | None
    """Optional username override for this hop."""


def _parse_jump_spec(spec: str) -> list[_JumpHop]:
    hops: list[_JumpHop] = []
    for raw in spec.split(','):
        entry = raw.strip()
        if not entry:
            continue
        if '@' in entry:
            user, _, host_port = entry.partition('@')
        else:
            user, host_port = None, entry
        host, _, port_str = host_port.partition(':')
        try:
            port = int(port_str) if port_str else 22
        except ValueError as e:
            msg = f'invalid jump port in {entry!r}'
            raise click.BadParameter(msg, param_hint='-J') from e
        hops.append(_JumpHop(host=host, port=port, user=user))
    return hops


@contextmanager
def _connect_with_jumps(jumps: Sequence[_JumpHop], target_host: str, target_port: int,
                        target_user: str | None, *, compress: bool, key_filename: str | None,
                        timeout: float) -> Iterator[SSHClient]:
    ssh_client_cls = _get_ssh_client_cls()
    with ExitStack() as stack:
        prev_transport = None
        for hop in jumps:
            jump_client = stack.enter_context(ssh_client_cls())
            jump_client.load_system_host_keys()
            kwargs: dict[str, Any] = {
                'compress': compress,
                'key_filename': key_filename,
                'timeout': timeout
            }
            if prev_transport is not None:
                kwargs['sock'] = prev_transport.open_channel('direct-tcpip', (hop.host, hop.port),
                                                             ('', 0))
            jump_client.connect(hop.host, hop.port, hop.user, **kwargs)
            prev_transport = jump_client.get_transport()
        target = stack.enter_context(ssh_client_cls())
        target.load_system_host_keys()
        target_kwargs: dict[str, Any] = {
            'compress': compress,
            'key_filename': key_filename,
            'timeout': timeout
        }
        if prev_transport is not None:
            target_kwargs['sock'] = prev_transport.open_channel('direct-tcpip',
                                                                (target_host, target_port), ('', 0))
        target.connect(target_host, target_port, target_user, **target_kwargs)
        yield target


def _parse_ssh_options(entries: Sequence[str]) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for entry in entries:
        if '=' not in entry:
            msg = f'expected KEY=VALUE, got {entry!r}'
            raise click.BadParameter(msg, param_hint='-o')
        key, _, value = entry.partition('=')
        key = key.strip().lower()
        value = value.strip()
        if key not in _SUPPORTED_SSH_OPTIONS:
            supported = ', '.join(sorted(_SUPPORTED_SSH_OPTIONS))
            msg = f'unsupported ssh option {key!r}. Supported: {supported}'
            raise click.BadParameter(msg, param_hint='-o')
        overrides[key] = [value] if key == 'identityfile' else value
    return overrides


def _resolve_ssh_config(host: str, ssh_config: Path | None, *,
                        no_ssh_config: bool) -> dict[str, Any]:
    if no_ssh_config:
        return {}
    path = ssh_config
    if path is None:
        default = Path.home() / '.ssh' / 'config'
        if default.is_file():
            path = default
    if path is None:
        return {}
    from paramiko import SSHConfig  # ruff:ignore[import-outside-top-level]
    return dict(SSHConfig.from_path(str(path)).lookup(host))


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('filenames', type=click.Path(exists=True, path_type=Path), nargs=-1)
@click.argument('target')
@click.option('-C',
              'compress',
              is_flag=True,
              flag_value=True,
              default=None,
              help='Enable compression.')
@click.option('-F',
              '--ssh-config',
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help='Path to an alternative ssh_config file. Defaults to ~/.ssh/config if it '
              'exists.')
@click.option('-J',
              'jump_dest',
              metavar='DESTINATION',
              help='Connect to the target host by first making an SSH connection to one or '
              'more jump hosts. Multiple hops are comma-separated. Each entry is '
              '[user@]host[:port].')
@click.option('-l',
              'bandwidth_limit',
              type=int,
              default=None,
              metavar='KBIT_PER_SEC',
              help='Limit bandwidth used in Kbit/s. Applied per-file.')
@click.option('-P', '--port', type=int, default=None, help='Port.')
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
@click.option('-i',
              '--key',
              'key_filename',
              type=click.Path(exists=True, dir_okay=False, path_type=str),
              help='Private key file.')
@click.option('-t', '--timeout', type=float, default=None, help='Timeout in seconds.')
@click.option(
    '-p',
    'preserve',
    is_flag=True,
    help='Preserves modification times, access times, and file mode bits from the source file.')
@click.option('-y',
              '--dry-run',
              is_flag=True,
              help='Do not copy anything. Use with -d for testing.')
@click.option('-B',
              'batch_mode',
              is_flag=True,
              help='Batch mode. Accepted for compatibility; no runtime effect because the '
              'underlying SSH library is already non-interactive.')
@click.option('-o',
              'ssh_options',
              multiple=True,
              metavar='KEY=VALUE',
              help='Pass an ssh_config-style option. May be repeated. Supported keys: '
              'Compression, ConnectTimeout, HostName, IdentityFile, Port, User. Explicit '
              'flags override these; these override -F and ~/.ssh/config.')
@click.option('-q', '--quiet', is_flag=True, help='Suppress non-error log output.')
@click.option('-v', '--verbose', is_flag=True, help='Verbose output. Alias for --debug.')
@click.option('--no-ssh-config',
              is_flag=True,
              help='Do not read ~/.ssh/config or any other ssh_config file.')
def smv_main(filenames: Sequence[Path],
             target: str,
             key_filename: str | None,
             ssh_config: Path | None,
             ssh_options: tuple[str, ...],
             bandwidth_limit: int | None = None,
             jump_dest: str | None = None,
             port: int | None = None,
             timeout: float | None = None,
             *,
             batch_mode: bool = False,
             compress: bool | None = None,
             debug: bool = False,
             dry_run: bool = False,
             no_ssh_config: bool = False,
             preserve: bool = False,
             quiet: bool = False,
             verbose: bool = False) -> None:
    """
    Secure move.

    This is similar to scp but deletes the file or directory after successful copy.

    Always test with the --dry-run/-y option.
    """
    setup_logging(debug=debug or verbose, loggers={'deltona': {}, 'paramiko': {}})
    if quiet and not (debug or verbose):
        for name in ('deltona', 'paramiko'):
            logging.getLogger(name).setLevel(logging.WARNING)
    del batch_mode  # accepted for scp compatibility; paramiko is non-interactive by default.
    cli_user, cli_host, target_dir_or_filename = _parse_target(target)
    cfg = _resolve_ssh_config(cli_host, ssh_config, no_ssh_config=no_ssh_config)
    cfg.update(_parse_ssh_options(ssh_options))
    hostname = cfg.get('hostname', cli_host)
    username = cli_user or cfg.get('user')
    resolved_port = port if port is not None else int(cfg.get('port', 22))
    resolved_timeout = (timeout if timeout is not None else float(cfg.get('connecttimeout', 2.0)))
    resolved_compress = (compress
                         if compress is not None else cfg.get('compression', 'no').lower() == 'yes')
    resolved_key: str | None = key_filename
    if resolved_key is None:
        identityfiles = cfg.get('identityfile')
        if identityfiles:
            resolved_key = identityfiles[0]
    jump_spec = jump_dest if jump_dest is not None else cfg.get('proxyjump') or ''
    jumps = _parse_jump_spec(jump_spec) if jump_spec else []
    with _connect_with_jumps(jumps,
                             hostname,
                             resolved_port,
                             username,
                             compress=resolved_compress,
                             key_filename=resolved_key,
                             timeout=resolved_timeout) as client:
        for filename in filenames:
            secure_move_path(client,
                             filename,
                             target_dir_or_filename,
                             bandwidth_limit_kbits=bandwidth_limit,
                             dry_run=dry_run,
                             preserve_stats=preserve)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('bundle', type=click.Path(dir_okay=True, file_okay=False, path_type=Path))
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
@click.option('-E',
              '--env-var',
              'env_vars',
              help='Environment variable to set.',
              multiple=True,
              type=(str, str))
@click.option('-r', '--retina', is_flag=True, help='For macOS apps, force Retina support.')
def patch_bundle_main(bundle: Path,
                      env_vars: tuple[tuple[str, str], ...],
                      *,
                      debug: bool = False,
                      retina: bool = False) -> None:
    """Patch a macOS/iOS/etc bundle's Info.plist file."""
    setup_logging(debug=debug, loggers={'deltona': {}})
    data: dict[str, Any] = {}
    if env_vars:
        data['LSEnvironment'] = dict(env_vars)
    if retina:
        data['NSHighResolutionCapable'] = True
    patch_macos_bundle_info_plist(bundle, **data)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('files', type=click.Path(exists=True, dir_okay=False, path_type=Path), nargs=-1)
@click.option('-a', '--all', 'all_', is_flag=True, help='Find compatible files and process them.')
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
def kconfig_to_commands_main(files: Sequence[Path],
                             *,
                             all_: bool = False,
                             debug: bool = False) -> None:
    """Generate kwriteconfig6 commands to set (Plasma) settings from your current settings."""
    setup_logging(debug=debug, loggers={'deltona': {}})
    if all_:
        files = [*(Path.home() / '.config').glob('*rc'), Path.home() / '.config/kdeglobals']
    for file in sorted(files):
        for cmd in get_kwriteconfig_commands(file):
            click.echo(cmd)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('files', type=click.Path(exists=True, dir_okay=False, path_type=Path), nargs=-1)
@click.option('-a', '--all', 'all_', is_flag=True, help='Find compatible files and process them.')
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
def kconfig_to_json_main(files: Sequence[Path], *, all_: bool = False, debug: bool = False) -> None:
    """Convert Plasma and compatible settings (INI-style) to JSON."""
    setup_logging(debug=debug, loggers={'deltona': {}})
    if all_:
        files = [*(Path.home() / '.config').glob('*rc'), Path.home() / '.config/kdeglobals']
    for file in sorted(files):
        click.echo(
            json.dumps(get_kconfig_dict(file) | {'_file': str(file)}, indent=2, sort_keys=True))


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('path',
                type=click.Path(exists=True, dir_okay=True, file_okay=False, path_type=Path),
                default='.')
@click.option('-d', '--depth', default=2, type=int, help='Maximum depth.', metavar='DEPTH')
@click.option('-f', '--follow-symlinks', is_flag=True, help='Follow symbolic links.')
@click.option('-o', '--output-file', type=click.File('w'), default=sys.stdout, help='Output file.')
def generate_html_dir_tree_main(path: Path,
                                *,
                                output_file: TextIO,
                                depth: int = 2,
                                follow_symlinks: bool = False) -> None:
    """Generate an HTML directory listing."""
    click.echo(generate_html_dir_tree(path, follow_symlinks=follow_symlinks, depth=depth),
               output_file)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('local',
                type=click.Path(exists=True, dir_okay=True, file_okay=False, path_type=Path))
@click.argument('remote', required=False)
@click.option('-a',
              '--rclone-arg',
              'rclone_args',
              multiple=True,
              help='Extra argument passed to rclone bisync. May be repeated.')
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
@click.option('-k',
              '--kind',
              type=click.Choice(('launchd', 'systemd-system', 'systemd-user')),
              help='Service manager to target. Defaults to the one native to this platform.')
@click.option('-n', '--dry-run', is_flag=True, help='Print the service definition and exit.')
@click.option('--dedupe-interval',
              default=DEFAULT_DEDUPE_SECONDS,
              type=float,
              help='Shortest wait between deduplications. 0 disables them.')
@click.option('--dedupe-mode',
              default=DEFAULT_DEDUPE_MODE,
              type=click.Choice(
                  ('first', 'largest', 'newest', 'oldest', 'rename', 'skip', 'smallest')),
              help='What deduplication keeps out of the files that share a name.')
@click.option('--idle',
              default=DEFAULT_IDLE_SECONDS,
              type=float,
              help='Seconds of quiet before a burst of writes is synchronised.')
@click.option('--max-syncs-per-minute',
              default=DEFAULT_MAX_SYNCS_PER_MINUTE,
              type=int,
              help='Synchronisations allowed in a minute. 0 allows any rate.')
@click.option('--name', help='Service name. Defaults to a name based on LOCAL.')
@click.option('--no-enable', is_flag=True, help='Do not enable and start the service.')
@click.option('--poll',
              default=DEFAULT_POLL_SECONDS,
              type=float,
              help='Longest wait between synchronisations.')
@click.option('-r',
              '--remote-name',
              default=DEFAULT_REMOTE_NAME,
              help='rclone remote to use when REMOTE is not given.')
@click.option('--rclone-config',
              type=click.Path(dir_okay=False, path_type=Path),
              help='Configuration file rclone reads. Defaults to the one rclone reports.')
@click.option('--remote-poll',
              default=DEFAULT_REMOTE_POLL_SECONDS,
              type=float,
              help='Wait between reads of the Google Drive changes feed. 0 disables them.')
@click.option('--user', help='Account the service runs as. Only used with systemd-system.')
def make_rclone_bisync_service_main(local: Path,
                                    remote: str | None = None,
                                    rclone_args: Sequence[str] = (),
                                    kind: ServiceKind | None = None,
                                    name: str | None = None,
                                    rclone_config: Path | None = None,
                                    remote_name: str = DEFAULT_REMOTE_NAME,
                                    user: str | None = None,
                                    dedupe_interval: float = DEFAULT_DEDUPE_SECONDS,
                                    dedupe_mode: DedupeMode = DEFAULT_DEDUPE_MODE,
                                    idle: float = DEFAULT_IDLE_SECONDS,
                                    max_syncs_per_minute: int = DEFAULT_MAX_SYNCS_PER_MINUTE,
                                    poll: float = DEFAULT_POLL_SECONDS,
                                    remote_poll: float = DEFAULT_REMOTE_POLL_SECONDS,
                                    *,
                                    debug: bool = False,
                                    dry_run: bool = False,
                                    no_enable: bool = False) -> None:
    """
    Install a service that keeps LOCAL in bidirectional sync with REMOTE.

    REMOTE defaults to a directory of the same name as LOCAL under the remote named by
    --remote-name. Installing a systemd-system service requires root privileges.
    """  # noqa: DOC501
    setup_logging(debug=debug, loggers={'deltona': {}})
    if rclone_config:
        os.environ[RCLONE_CONFIG_ENV] = str(rclone_config.resolve())
    kind = kind or default_service_kind()
    name = name or default_service_name(local)
    remote = remote or default_remote(local, remote_name)
    command = [
        shutil.which('rclone-bisyncd') or 'rclone-bisyncd',
        str(local.resolve()), remote, '--dedupe-interval',
        str(dedupe_interval), '--dedupe-mode', dedupe_mode, '--idle',
        str(idle), '--max-syncs-per-minute',
        str(max_syncs_per_minute), '--poll',
        str(poll), '--remote-poll',
        str(remote_poll)
    ]
    if rclone_config:
        command += ['--rclone-config', str(rclone_config.resolve())]
    for arg in rclone_args:
        command += ['--rclone-arg', arg]
    description = f'Bidirectional rclone sync of {local} with {remote}.'
    if dry_run:
        click.echo(generate_service(kind, name, command, description=description, user=user))
        return
    try:
        path = install_service(kind,
                               name,
                               command,
                               description=description,
                               enable=not no_enable,
                               user=user)
    except sp.CalledProcessError as e:
        click.echo(f'Failed to enable {name}.', err=True)
        raise click.Abort from e
    except FileNotFoundError as e:
        click.echo(f'{e.filename} is not installed.', err=True)
        raise click.Abort from e
    click.echo(f'Installed {path}.')


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('local', type=click.Path(dir_okay=True, file_okay=False, path_type=Path))
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
@click.option('-k',
              '--kind',
              type=click.Choice(('launchd', 'systemd-system', 'systemd-user')),
              help='Service manager to target. Defaults to the one native to this platform.')
@click.option('--name', help='Service name. Defaults to a name based on LOCAL.')
def remove_rclone_bisync_service_main(local: Path,
                                      kind: ServiceKind | None = None,
                                      name: str | None = None,
                                      *,
                                      debug: bool = False) -> None:
    """
    Uninstall the service that keeps LOCAL in bidirectional sync.

    LOCAL does not have to exist. Removing a systemd-system service requires root privileges.
    """  # noqa: DOC501
    setup_logging(debug=debug, loggers={'deltona': {}})
    kind = kind or default_service_kind()
    name = name or default_service_name(local)
    try:
        path = uninstall_service(kind, name)
    except sp.CalledProcessError as e:
        click.echo(f'Failed to remove {name}.', err=True)
        raise click.Abort from e
    except FileNotFoundError as e:
        click.echo(f'{e.filename} is not installed.', err=True)
        raise click.Abort from e
    if path is None:
        click.echo(f'No {kind} service named {name}.', err=True)
        raise click.exceptions.Exit(1)
    click.echo(f'Removed {path}.')


def _syslog_handler() -> dict[str, Any]:
    # The daemon runs unattended and launchd sends its output nowhere by default, so warnings have
    # to reach the system log to be seen at all. There is no socket in a container, where the
    # console is all there is.
    return next(({
        'syslog': {
            'address': path,
            'class': 'logging.handlers.SysLogHandler',
            'formatter': 'syslog',
            'level': 'WARNING'
        }
    } for path in SYSLOG_SOCKETS if Path(path).exists()), {})


def _run_bisyncd(local: Path, remote: str, rclone_args: Sequence[str], *, dedupe_interval: float,
                 dedupe_mode: DedupeMode, idle: float, max_syncs_per_minute: int, once: bool,
                 poll: float, remote_poll: float, resync: bool) -> None:
    if resync:
        bisync(local, remote, rclone_args, resync=True)
    elif once:
        sync_once(local, remote, rclone_args)
        if dedupe_interval > 0:
            dedupe(remote, dedupe_mode)
    else:
        watch_and_sync(local,
                       remote,
                       rclone_args,
                       dedupe_interval=dedupe_interval,
                       dedupe_mode=dedupe_mode,
                       idle=idle,
                       max_syncs_per_minute=max_syncs_per_minute,
                       poll=poll,
                       remote_poll=remote_poll)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('local',
                type=click.Path(exists=True, dir_okay=True, file_okay=False, path_type=Path))
@click.argument('remote', required=False)
@click.option('-a',
              '--rclone-arg',
              'rclone_args',
              multiple=True,
              help='Extra argument passed to rclone bisync. May be repeated.')
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
@click.option('--dedupe-interval',
              default=DEFAULT_DEDUPE_SECONDS,
              type=float,
              help='Shortest wait between deduplications. 0 disables them.')
@click.option('--dedupe-mode',
              default=DEFAULT_DEDUPE_MODE,
              type=click.Choice(
                  ('first', 'largest', 'newest', 'oldest', 'rename', 'skip', 'smallest')),
              help='What deduplication keeps out of the files that share a name.')
@click.option('--idle',
              default=DEFAULT_IDLE_SECONDS,
              type=float,
              help='Seconds of quiet before a burst of writes is synchronised.')
@click.option('--max-syncs-per-minute',
              default=DEFAULT_MAX_SYNCS_PER_MINUTE,
              type=int,
              help='Synchronisations allowed in a minute. 0 allows any rate.')
@click.option('--once', is_flag=True, help='Synchronise once and exit.')
@click.option('--poll',
              default=DEFAULT_POLL_SECONDS,
              type=float,
              help='Longest wait between synchronisations.')
@click.option('-r',
              '--remote-name',
              default=DEFAULT_REMOTE_NAME,
              help='rclone remote to use when REMOTE is not given.')
@click.option('--rclone-config',
              type=click.Path(dir_okay=False, path_type=Path),
              help='Configuration file rclone reads. Defaults to the one rclone reports.')
@click.option('--remote-poll',
              default=DEFAULT_REMOTE_POLL_SECONDS,
              type=float,
              help='Wait between reads of the Google Drive changes feed. 0 disables them.')
@click.option('--resync', is_flag=True, help='Rebuild the baseline listings and exit.')
def rclone_bisyncd_main(local: Path,
                        remote: str | None = None,
                        rclone_args: Sequence[str] = (),
                        rclone_config: Path | None = None,
                        remote_name: str = DEFAULT_REMOTE_NAME,
                        dedupe_interval: float = DEFAULT_DEDUPE_SECONDS,
                        dedupe_mode: DedupeMode = DEFAULT_DEDUPE_MODE,
                        idle: float = DEFAULT_IDLE_SECONDS,
                        max_syncs_per_minute: int = DEFAULT_MAX_SYNCS_PER_MINUTE,
                        poll: float = DEFAULT_POLL_SECONDS,
                        remote_poll: float = DEFAULT_REMOTE_POLL_SECONDS,
                        *,
                        debug: bool = False,
                        once: bool = False,
                        resync: bool = False) -> None:
    """
    Keep LOCAL in bidirectional sync with REMOTE, synchronising whenever either side changes.

    REMOTE defaults to a directory of the same name as LOCAL under the remote named by
    --remote-name. Changes made on a Google Drive remote are noticed by reading its changes feed.
    Warnings and worse always go to the system log. Only one instance per directory runs at a time.
    """  # noqa: DOC501
    syslog = _syslog_handler()
    setup_logging(debug=debug,
                  formatters={'syslog': {
                      'format': '%(name)s: %(levelname)s: %(message)s'
                  }},
                  handlers=syslog,
                  loggers={'deltona': {}},
                  root={'handlers': ('console', *syslog)})
    # rclone reads this too, so every rclone the daemon starts uses the same file.
    if rclone_config:
        os.environ[RCLONE_CONFIG_ENV] = str(rclone_config.resolve())
    remote = remote or default_remote(local, remote_name)
    try:
        with single_instance(local):
            _run_bisyncd(local,
                         remote,
                         rclone_args,
                         dedupe_interval=dedupe_interval,
                         dedupe_mode=dedupe_mode,
                         idle=idle,
                         max_syncs_per_minute=max_syncs_per_minute,
                         once=once,
                         poll=poll,
                         remote_poll=remote_poll,
                         resync=resync)
    except (AlreadyRunning, InvalidCredentials) as e:
        click.echo(str(e), err=True)
        raise click.Abort from e
    except sp.CalledProcessError as e:
        click.echo(f'rclone exited with status {e.returncode}.', err=True)
        raise click.Abort from e
    except FileNotFoundError as e:
        click.echo(f'{e.filename} is not installed.', err=True)
        raise click.Abort from e


_ACTION_STYLES = {'created': 'green', 'modified': 'yellow', 'trashed': 'red'}
_DEFAULT_SINCE = '1d'
_DURATION_RE = re.compile(r'^(?P<count>\d+(?:\.\d+)?)(?P<unit>d|h|m|s|w)$')
_DURATION_SECONDS = {'d': 86400.0, 'h': 3600.0, 'm': 60.0, 's': 1.0, 'w': 604800.0}


def _iso(value: str) -> datetime:
    # Python 3.10 does not accept the trailing Z that Google sends.
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def _when(value: str) -> datetime:
    if parts := _DURATION_RE.match(value.strip()):
        seconds = float(parts['count']) * _DURATION_SECONDS[parts['unit']]
        return datetime.now(timezone.utc) - timedelta(seconds=seconds)
    parsed = _iso(value.strip())
    return parsed if parsed.tzinfo else parsed.astimezone()


def _bound(value: str, hint: str) -> datetime:
    try:
        return _when(value)
    except ValueError as e:
        msg = f'{value!r} is not a duration or a timestamp'
        raise click.BadParameter(msg, param_hint=hint) from e


def _modified(file: Mapping[str, Any]) -> str:
    if not (raw := file.get('modifiedTime')):
        return ''
    return _iso(str(raw)).astimezone().strftime('%Y-%m-%d %H:%M')


def _action(file: Mapping[str, Any]) -> str:
    # Google reports the state a file is in, not what was done to it, so the action is inferred
    # from the creation and modification times and the trashed flag. A rename or a move is reported
    # as an edit, since either only moves modifiedTime along.
    if file.get('trashed'):
        return 'trashed'
    if file.get('createdTime') == file.get('modifiedTime'):
        return 'created'
    return 'modified'


def _changes_table(files: Iterable[Mapping[str, Any]]) -> Table:
    table = Table()
    table.add_column('Modified')
    table.add_column('Action')
    table.add_column('Who')
    table.add_column('Size', justify='right')
    table.add_column('Name', overflow='fold')
    for file in files:
        action = _action(file)
        table.add_row(_modified(file), Text(action, style=_ACTION_STYLES[action]),
                      (file.get('lastModifyingUser') or {}).get('displayName') or '',
                      decimal(int(file['size'])) if file.get('size') is not None else '',
                      Text(str(file.get('name', ''))))
    return table


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('remote', required=False)
@click.option('--access-token', help='Access token to send instead of the one rclone holds.')
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
@click.option('-j',
              '--json',
              'as_json',
              is_flag=True,
              help='Print the file resources as Google sends them.')
@click.option('-n',
              '--limit',
              default=DEFAULT_CHANGES_LIMIT,
              type=int,
              help='Maximum number of files to report.')
@click.option('--rclone-config',
              type=click.Path(dir_okay=False, path_type=Path),
              help='Configuration file rclone reads. Defaults to the one rclone reports.')
@click.option('-s',
              '--since',
              default=_DEFAULT_SINCE,
              help='Report only what changed after this. A duration (30m, 2h, 7d) or a timestamp'
              ' (2026-09-01T08:00).')
@click.option('-u', '--until', help='Report only what changed before this. Same forms as --since.')
def rclone_drive_changes_main(remote: str | None = None,
                              access_token: str | None = None,
                              limit: int = DEFAULT_CHANGES_LIMIT,
                              rclone_config: Path | None = None,
                              since: str = _DEFAULT_SINCE,
                              until: str | None = None,
                              *,
                              as_json: bool = False,
                              debug: bool = False) -> None:
    """
    List files recently changed on the Google Drive account behind REMOTE.

    REMOTE defaults to gdrive. Any path on it is ignored, since the whole account is listed.

    The action is inferred from what Google reports about the file rather than stated by Google:
    one whose creation and modification times match was created, one in the bin was trashed, and
    anything else was edited. A rename or a move therefore reads as an edit, since either only
    moves the modification time along.

    Deletions are not reported. Google serves those only through the feed rclone-bisyncd watches,
    which starts at the moment it is opened and cannot be asked about a time already past.
    """  # noqa: DOC501
    setup_logging(debug=debug, loggers={'deltona': {}})
    if rclone_config:
        os.environ[RCLONE_CONFIG_ENV] = str(rclone_config.resolve())
    start = _bound(since, '--since')
    end = _bound(until, '--until') if until else None
    try:
        changes = list(
            recent_changes(remote or DEFAULT_REMOTE_NAME, start, end, limit, access_token))
    except InvalidCredentials as e:
        click.echo(str(e), err=True)
        raise click.Abort from e
    except sp.CalledProcessError as e:
        click.echo(f'rclone exited with status {e.returncode}.', err=True)
        raise click.Abort from e
    except FileNotFoundError as e:
        click.echo(f'{e.filename} is not installed.', err=True)
        raise click.Abort from e
    except OSError as e:
        click.echo(f'Google Drive could not be reached: {e}', err=True)
        raise click.Abort from e
    if as_json:
        click.echo(json.dumps(changes, indent=2, sort_keys=True))
        return
    if not changes:
        click.echo('Nothing changed.')
        return
    Console().print(_changes_table(changes))
