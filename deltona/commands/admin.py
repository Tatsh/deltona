"""System administration commands."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO
import logging
import re
import sys

from deltona.constants import CONTEXT_SETTINGS
from deltona.gentoo import (
    DEFAULT_ACTIVE_KERNEL_NAME,
    DEFAULT_KERNEL_LOCATION,
    DEFAULT_MODULES_PATH,
    clean_old_kernels_and_modules,
)
from deltona.system import (
    MultipleKeySlots,
    get_kwriteconfig_commands,
    patch_macos_bundle_info_plist,
    reset_tpm_enrollment,
    slug_rename,
)
from deltona.utils import secure_move_path
from deltona.www import generate_html_dir_tree
import click

if TYPE_CHECKING:
    from collections.abc import Sequence

    from paramiko import SSHClient


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
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)
    if all_:
        uuids = [
            x[1][5:] for x in (re.split(r'\s+', line, maxsplit=4)
                               for line in (li.strip() for li in crypttab.read_text().splitlines())
                               if not line.startswith('#'))
            if 'tpm2-device=auto' in x[3] and 'UUID=' in x[1]
        ]
    for uuid in uuids:
        try:
            reset_tpm_enrollment(uuid, dry_run=not force)
        except MultipleKeySlots:
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
    logging.basicConfig(level=logging.INFO if not debug else logging.DEBUG)
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


def get_ssh_client_cls() -> type[SSHClient]:  # pragma: no cover
    """Return the SSH client class."""
    from paramiko import SSHClient  # noqa: PLC0415
    return SSHClient


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('filenames', type=click.Path(exists=True, path_type=Path), nargs=-1)
@click.argument('target')
@click.option('-C', 'compress', is_flag=True, help='Enable compression.')
@click.option('-P', '--port', type=int, default=22, help='Port.')
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
@click.option('-i', '--key', 'key_filename', type=click.File('r'), help='Private key.')
@click.option('-t', '--timeout', type=float, default=2, help='Timeout in seconds.')
@click.option(
    '-p',
    'preserve',
    is_flag=True,
    help='Preserves modification times, access times, and file mode bits from the source file.')
@click.option('-y',
              '--dry-run',
              is_flag=True,
              help='Do not copy anything. Use with -d for testing.')
def smv_main(filenames: Sequence[Path],
             target: str,
             key_filename: str,
             port: int = 22,
             timeout: float = 2,
             *,
             compress: bool = False,
             debug: bool = False,
             dry_run: bool = False,
             preserve: bool = False) -> None:
    """
    Secure move.

    This is similar to scp but deletes the file or directory after successful copy.

    Always test with the --dry-run/-y option.
    """
    logging.basicConfig(level=logging.DEBUG if debug else logging.ERROR)
    username = target.split('@', maxsplit=1)[0] if '@' in target else None
    hostname = target.split(':', maxsplit=1)[0]
    target_dir_or_filename = target.split(':')[1]
    ssh_client_cls = get_ssh_client_cls()
    with ssh_client_cls() as client:
        client.load_system_host_keys()
        client.connect(hostname,
                       port,
                       username,
                       compress=compress,
                       key_filename=key_filename,
                       timeout=timeout)
        for filename in filenames:
            secure_move_path(client,
                             filename,
                             target_dir_or_filename,
                             dry_run=dry_run,
                             preserve_stats=preserve)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('bundle', type=click.Path(dir_okay=True, file_okay=False, path_type=Path))
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
                      retina: bool = False) -> None:
    """Patch a macOS/iOS/etc bundle's Info.plist file."""
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
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)
    if all_:
        files = [*(Path.home() / '.config').glob('*rc'), Path.home() / '.config/kdeglobals']
    for file in sorted(files):
        for cmd in get_kwriteconfig_commands(file):
            click.echo(cmd)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('path',
                type=click.Path(exists=True, dir_okay=True, file_okay=False, path_type=Path),
                default='.')
@click.option('-d', '--depth', default=2, help='Maximum depth.', metavar='DEPTH')
@click.option('-f', '--follow-symlinks', is_flag=True, help='Follow symbolic links.')
@click.option('-o', '--output-file', type=click.File('w'), default=sys.stdout, help='Output file.')
def generate_html_dir_tree_main(path: Path,
                                *,
                                output_file: TextIO,
                                depth: int = 2,
                                follow_symlinks: bool = False) -> None:
    """Generate a HTML directory listing."""
    click.echo(generate_html_dir_tree(path, follow_symlinks=follow_symlinks, depth=depth),
               output_file)
