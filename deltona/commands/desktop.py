"""Desktop commands."""
from __future__ import annotations

from pathlib import Path
from shlex import quote, split
from shutil import which
from time import sleep
from typing import TYPE_CHECKING, Any, Literal, overload
import contextlib
import errno
import logging
import re
import socket
import subprocess as sp
import webbrowser

from deltona.constants import CONTEXT_SETTINGS
from deltona.media import ffprobe
from deltona.string import is_url
from deltona.system import (
    IS_LINUX,
    find_bluetooth_device_info_by_name,
    inhibit_notifications,
    kill_gamescope,
)
from deltona.www import upload_to_imgbb
from gi.repository import Gio
from platformdirs import user_state_path
from requests import HTTPError
import click
import pyperclip
import requests

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from types import ModuleType

    from deltona.typing import ProbeDict, StreamDispositionDict
    from gi.repository import GLib
    from pydbus.bus import Bus

log = logging.getLogger(__name__)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option('-d', '--debug', is_flag=True, help='Enable debug logging.')
@click.option('-t',
              '--sleep-time',
              default=0,
              type=int,
              help='Sleep time in seconds to inhibit notifications for.')
def inhibit_notifications_main(sleep_time: int = 60, *, debug: bool = False) -> None:
    """
    Disable notifications state for a time.

    On exit, notifications will be enabled. This command does nothing if notifications are already
    disabled.

    This is an alternative to ``kde-inhibit``. Unlike ``kde-inhibit``, this tool may only sleep.
    A sleep time of ``0`` effectively does nothing.
    """
    logging.basicConfig(level=logging.ERROR if not debug else logging.DEBUG)
    if inhibit_notifications():
        sleep(sleep_time)


@click.command(context_settings={**CONTEXT_SETTINGS, 'auto_envvar_prefix': 'UMPV'})
@click.option('-d', '--debug', is_flag=True)
@click.option('--mpv-command', default='mpv', help='mpv command including arguments.')
@click.argument('files', type=click.Path(path_type=Path), nargs=-1)
def umpv_main(files: Sequence[Path], mpv_command: str = 'mpv', *, debug: bool = False) -> None:
    """Run a single instance of mpv."""  # noqa: DOC501
    logging.basicConfig(level=logging.DEBUG if debug else logging.ERROR)
    fixed_files = ((p if is_url(p) else str(p.resolve(strict=True))) for p in files)
    socket_path = str(user_state_path() / 'umpv-socket')
    sock = None
    socket_connected = False
    try:
        sock = socket.socket(socket.AF_UNIX)
        sock.connect(socket_path)
        socket_connected = True
    except OSError as e:
        if e.errno == errno.ECONNREFUSED:
            log.debug('Socket refused connection')
            sock = None  # abandoned socket
        elif e.errno == errno.ENOENT:
            log.debug('Socket does not exist')
            sock = None  # does not exist
        else:
            log.exception('Socket errno: %d', e.errno)
            raise click.Abort from e
    if sock and socket_connected:
        # Unhandled race condition: what if mpv is terminating right now?
        for f in fixed_files:
            # escape: \ \n "
            g = str(f).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
            log.debug('Loading file "%s"', f)
            sock.send(f'raw loadfile "{g}"\n'.encode())
    else:
        log.debug('Starting new mpv instance')
        # Let mpv recreate socket if it does not already exist
        args = (*split(mpv_command), *(() if debug else ('--no-terminal',)), '--force-window',
                f'--input-ipc-server={socket_path}', '--', *fixed_files)
        log.debug('Command: %s', ' '.join(quote(x) for x in args))
        sp.run(args, check=True)


def _get_pydbus_system_bus_callable() -> Callable[[], Bus]:  # pragma: no cover
    from pydbus import SystemBus  # noqa: PLC0415
    return SystemBus


def _get_gi_repository_glib() -> ModuleType:  # pragma: no cover
    from gi.repository import GLib  # type: ignore[unused-ignore] # noqa: PLC0415
    return GLib


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option('-d', '--debug', is_flag=True)
@click.option('--device',
              'device_name',
              default='hci0',
              help='Bluetooth device (defaults to hci0).')
def connect_g603_main(device_name: str = 'hci0', *, debug: bool = False) -> None:
    """
    Connect a G603 Bluetooth mouse, disconnecting/removing first if necessary.

    For Linux only.

    This is useful for connecting the mouse back when it randomly decides not to re-pair, and you
    have no other mouse but you can get to your terminal.
    """  # noqa: DOC501
    if not IS_LINUX:
        click.echo('Only Linux is supported.', err=True)
        raise click.Abort
    try:
        g_lib = _get_gi_repository_glib()
        system_bus = _get_pydbus_system_bus_callable()
    except (ImportError, ModuleNotFoundError) as e:
        click.echo('Imports are missing.', err=True)
        raise click.Abort from e
    loop = g_lib.MainLoop()
    logging.basicConfig(level=logging.DEBUG if debug else logging.ERROR)
    bus = system_bus()
    adapter = bus.get('org.bluez', f'/org/bluez/{device_name}')

    def on_properties_changed(_: Any, __: Any, object_path: str, ___: Any, ____: Any,
                              props: GLib.Variant) -> None:
        unpacked = props.unpack()
        dev_iface = unpacked[0]
        values = unpacked[1]
        if dev_iface == 'org.bluez.Adapter1' and values.get('Discovering'):
            log.debug('Scan on.')
        elif (dev_iface == 'org.bluez.Device1'
              and (m := re.match(fr'/org/bluez/{device_name}/dev_(.*)', object_path))):
            mac = m.group(1).replace('_', ':')
            for k in ('ServicesResolved', 'Connected'):
                if k in values and not values[k]:
                    log.debug('Device %s was disconnected.', mac)
                    return
            try:
                device = bus.get('org.bluez', object_path)
                if device.Name != 'G603':
                    log.debug('Ignoring device %s (MAC: %s).', device.Name, mac)
                    return
            except (KeyError, RuntimeError) as e:
                log.debug('Caught error with device %s: %s', mac, str(e))
                return
            if values.get('Paired'):
                log.debug('Quitting.')
                loop.quit()
                return
            if 'RSSI' in values:
                click.echo(f'Pairing with {mac}.')
                device['org.bluez.Device1'].Pair()
            else:
                log.debug('Unhandled property changes: interface=%s, values=%s, mac=%s', dev_iface,
                          values, mac)

    # PropertiesChanged.connect()/.PropertiesChanged = ... will not catch the device node events
    bus.con.signal_subscribe(None, 'org.freedesktop.DBus.Properties', 'PropertiesChanged', None,
                             None, Gio.DBusSignalFlags.NONE, on_properties_changed)
    log.debug('Looking for existing devices.')
    with contextlib.suppress(KeyError):
        while res := find_bluetooth_device_info_by_name('G603'):
            object_path, info = res
            log.debug('Removing device with MAC address %s.',
                      info['Address'])  # type: ignore[typeddict-item]
            adapter.RemoveDevice(object_path)
    click.echo('Put the mouse in pairing mode and be very patient.')
    log.debug('Starting scan.')
    adapter.StartDiscovery()
    try:
        loop.run()
    except KeyboardInterrupt:
        loop.quit()


@click.command(context_settings=CONTEXT_SETTINGS)
def kill_gamescope_main() -> None:
    """Terminate gamescope and gamescopereaper."""
    kill_gamescope()


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('filenames', type=click.Path(exists=True, dir_okay=False, path_type=Path), nargs=-1)
@click.option('--api-key', help='API key.', metavar='KEY')
@click.option('--keyring-username', help='Keyring username override.', metavar='USERNAME')
@click.option('--no-browser', is_flag=True, help='Do not open browser.')
@click.option('--no-clipboard', is_flag=True, help='Do not copy URL to clipboard.')
@click.option('--no-gui', is_flag=True, help='Disable GUI interactions.')
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
@click.option('-t',
              '--timeout',
              type=float,
              default=5,
              help='Timeout in seconds.',
              metavar='TIMEOUT')
@click.option('--xdg-install',
              default=None,
              metavar='PATH',
              help=('Install .desktop file. Argument is the installation prefix such as /usr. Use '
                    '- to install to user XDG directory.'))
def upload_to_imgbb_main(filenames: Sequence[Path],
                         api_key: str | None = None,
                         keyring_username: str | None = None,
                         timeout: float = 5,
                         xdg_install: str | None = None,
                         *,
                         debug: bool = False,
                         no_browser: bool = False,
                         no_clipboard: bool = False,
                         no_gui: bool = False) -> None:
    """
    Upload image to ImgBB.

    Get an API key at https://api.imgbb.com/ and set it with `keyring set imgbb "${USER}"`.
    """  # noqa: DOC501
    logging.basicConfig(level=logging.DEBUG if debug else logging.ERROR)
    r: requests.Response | None = None
    if xdg_install:
        prefix = str(Path('~/.local').expanduser()) if xdg_install == '-' else xdg_install
        apps = Path(f'{prefix}/share/applications')
        apps.mkdir(parents=True, exist_ok=True)
        (apps / 'upload-to-imgbb.desktop').write_text("""[Desktop Entry]
Categories=Graphics;2DGraphics;RasterGraphics;
Exec=upload-to-imgbb %U
Icon=imgbb
Keywords=graphic;design;
MimeType=image/avif;image/gif;image/jpeg;image/png;image/webp
Name=Upload to ImgBB
StartupNotify=false
Terminal=false
TryExec=upload-to-imgbb
Type=Application
Version=1.0
    """)
        r = requests.get('https://simgbb.com/images/favicon.png', timeout=5)
        icons_dir = Path(f'{prefix}/share/icons/hicolor/300x300/apps')
        icons_dir.mkdir(parents=True, exist_ok=True)
        (icons_dir / 'imgbb.png').write_bytes(r.content)
        sp.run(('update-desktop-database', '-v', str(apps)), check=True, capture_output=not debug)
        return
    kdialog = which('kdialog')
    show_gui = not no_gui and len(filenames) == 1 and kdialog
    try:
        for name in filenames:
            r = upload_to_imgbb(name,
                                api_key=api_key,
                                keyring_username=keyring_username,
                                timeout=timeout)
            if not show_gui:
                click.echo(r.json()['data']['url'])
    except HTTPError as e:
        if show_gui:
            assert kdialog is not None
            sp.run((kdialog, '--sorry', 'Failed to upload!'), check=False)
        click.echo('Failed to upload. Check API key!', err=True)
        raise click.Abort from e
    if r:
        url: str = r.json()['data']['url']
        if not no_clipboard:
            pyperclip.copy(url)
        if show_gui:
            click.echo(url)
            assert kdialog is not None
            sp.run((kdialog, '--title', 'Successfully uploaded', '--msgbox', url), check=False)
        elif not no_browser:
            webbrowser.open(url)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('filenames', type=click.Path(exists=True, dir_okay=False, path_type=Path), nargs=2)
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
def mpv_sbs_main(filenames: tuple[Path, Path],
                 max_width: int = 3840,
                 min_height: int = 31,
                 min_width: int = 31,
                 *,
                 debug: bool = False) -> None:
    """Display two videos side by side in mpv."""
    @overload
    def get_prop(prop: Literal['codec_type'],
                 info: ProbeDict) -> Literal['audio', 'video']:  # pragma: no cover
        ...

    @overload
    def get_prop(prop: Literal['disposition'],
                 info: ProbeDict) -> StreamDispositionDict:  # pragma: no cover
        ...

    @overload
    def get_prop(prop: Literal['height', 'width'], info: ProbeDict) -> int:  # pragma: no cover
        ...

    def get_prop(prop: Literal['codec_type', 'disposition', 'height', 'width'],
                 info: ProbeDict) -> Literal['audio', 'video'] | StreamDispositionDict | int:
        return max((x for x in info['streams'] if x['codec_type'] == 'video'),
                   key=lambda x: x['disposition'].get('default', 0))[prop]

    def get_default_video_index(info: ProbeDict) -> int:
        return next(
            (i
             for i, x in enumerate(info['streams']) if x.get('disposition', {}).get('default', 0)),
            next((i for i, x in enumerate(info['streams']) if x['codec_type'] == 'video'), 0))

    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)
    filename1, filename2 = filenames
    info1, info2 = ffprobe(filename1), ffprobe(filename2)
    width1, width2 = (int(get_prop('width', info1)), int(get_prop('width', info2)))
    height1, height2 = (int(get_prop('height', info1)), int(get_prop('height', info2)))
    assert height1 > min_height, 'Invalid height in video 1'
    assert height2 > min_height, 'Invalid height in video 2'
    assert width1 <= max_width, 'Video 1 is too wide'
    assert width1 > min_width, 'Invalid width in video 1'
    assert width2 <= max_width, 'Video 2 is too wide'
    assert width2 > min_width, 'Invalid width in video 2'
    scale_w = max(width1, width2)
    scale_h = int(get_prop('height', info1)) if scale_w == width1 else int(get_prop(
        'height', info2))
    scale = '' if width1 == width2 and height1 == height2 else f'scale={scale_w}x{scale_h}'
    scale1, scale2 = scale if scale_h != height1 else '', scale if scale_h == height1 else ''
    second_stream_index = (len([x for x in info1['streams'] if x['codec_type'] == 'video']) +
                           get_default_video_index(info2)) + 1
    if not scale1 and not scale2:
        filter_chain = '[vid1][vid2] hstack [vo]'
    else:
        filter_chain = ';'.join(
            (f'[vid1] {scale} [vid1_scale]',
             f'[vid{second_stream_index}] {scale} [vid{second_stream_index}_crop]',
             f'[vid1_scale][vid{second_stream_index}_crop] hstack [vo]'))
    cmd = ('mpv', '--hwdec=no', '--config=no', str(filename1), f'--external-file={filename2}',
           f'--lavfi-complex={filter_chain}')
    log.debug('Running: %s', ' '.join(quote(str(x)) for x in cmd))
    sp.run(cmd, check=True)
