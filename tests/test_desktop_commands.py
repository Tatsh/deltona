from __future__ import annotations

from typing import TYPE_CHECKING, Any
import errno

from deltona.commands.desktop import (
    connect_g603_main,
    inhibit_notifications_main,
    kill_gamescope_main,
    mpv_sbs_main,
    umpv_main,
    upload_to_imgbb_main,
)
from requests import HTTPError

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from click.testing import CliRunner
    from pytest_mock import MockerFixture


def test_inhibit_notifications_main_success(mocker: MockerFixture, runner: CliRunner) -> None:
    mock_inhibit = mocker.patch('deltona.commands.desktop.inhibit_notifications')
    mock_inhibit.return_value = 0
    result = runner.invoke(inhibit_notifications_main, [])
    assert result.exit_code == 0
    mock_inhibit.assert_called_once()


def test_inhibit_notifications_main_failure(mocker: MockerFixture, runner: CliRunner) -> None:
    mock_sleep = mocker.patch('deltona.commands.desktop.sleep')
    mock_inhibit = mocker.patch('deltona.commands.desktop.inhibit_notifications')
    mock_inhibit.return_value = False
    runner.invoke(inhibit_notifications_main, [])
    mock_sleep.assert_not_called()


def test_inhibit_notifications_main_args(mocker: MockerFixture, runner: CliRunner) -> None:
    mock_sleep = mocker.patch('deltona.commands.desktop.sleep')
    mock_inhibit = mocker.patch('deltona.commands.desktop.inhibit_notifications')
    result = runner.invoke(inhibit_notifications_main, ['--sleep-time', '10'])
    assert result.exit_code == 0
    mock_inhibit.assert_called_once()
    mock_sleep.assert_called_once_with(10)


def test_umpv_main_success(mocker: MockerFixture, runner: CliRunner, tmp_path: Path) -> None:
    mocker.patch('deltona.commands.desktop.logging.basicConfig')
    mocker.patch('deltona.commands.desktop.user_state_path')
    mock_socket = mocker.patch('deltona.commands.desktop.socket.socket')
    mocker.patch('deltona.commands.desktop.sp.run')
    out_mp4 = tmp_path / 'file"1.mp4'
    out_mp4.write_bytes(b'')
    result = runner.invoke(umpv_main, [str(out_mp4)])
    assert result.exit_code == 0
    mock_socket.return_value.send.assert_called_once_with(
        f'raw loadfile "{tmp_path}/file\\"1.mp4"\n'.encode())


def test_umpv_main_socket_conn_refused(mocker: MockerFixture, runner: CliRunner,
                                       tmp_path: Path) -> None:
    mocker.patch('deltona.commands.desktop.logging.basicConfig')
    mocker.patch('deltona.commands.desktop.user_state_path', return_value=tmp_path)
    mock_socket = mocker.patch('deltona.commands.desktop.socket.socket')
    sock_exc = OSError(errno.ECONNREFUSED, 'Connection refused')
    mock_socket.return_value.connect.side_effect = sock_exc
    sp_run = mocker.patch('deltona.commands.desktop.sp.run')
    out_mp4 = tmp_path / 'file"1.mp4'
    out_mp4.write_bytes(b'')
    result = runner.invoke(umpv_main, [str(out_mp4)])
    assert result.exit_code == 0
    mock_socket.return_value.send.assert_not_called()
    sp_run.assert_called_once_with(
        ('mpv', '--no-terminal', '--force-window', f'--input-ipc-server={tmp_path}/umpv-socket',
         '--', str(out_mp4)),
        check=True)


def test_umpv_main_socket_enoent(mocker: MockerFixture, runner: CliRunner, tmp_path: Path) -> None:
    mocker.patch('deltona.commands.desktop.logging.basicConfig')
    mocker.patch('deltona.commands.desktop.user_state_path', return_value=tmp_path)
    mock_socket = mocker.patch('deltona.commands.desktop.socket.socket')
    sock_exc = OSError(errno.ENOENT, 'No such file or directory')
    mock_socket.return_value.connect.side_effect = sock_exc
    sp_run = mocker.patch('deltona.commands.desktop.sp.run')
    out_mp4 = tmp_path / 'file"1.mp4'
    out_mp4.write_bytes(b'')
    result = runner.invoke(umpv_main, [str(out_mp4)])
    assert result.exit_code == 0
    mock_socket.return_value.send.assert_not_called()
    sp_run.assert_called_once_with(
        ('mpv', '--no-terminal', '--force-window', f'--input-ipc-server={tmp_path}/umpv-socket',
         '--', str(out_mp4)),
        check=True)


def test_umpv_main_unhandled_socket_exception(mocker: MockerFixture, runner: CliRunner,
                                              tmp_path: Path) -> None:
    mocker.patch('deltona.commands.desktop.logging.basicConfig')
    mocker.patch('deltona.commands.desktop.user_state_path', return_value=tmp_path)
    mock_socket = mocker.patch('deltona.commands.desktop.socket.socket')
    sock_exc = OSError(errno.ENOTBLK, 'Block device required')
    mock_socket.return_value.connect.side_effect = sock_exc
    sp_run = mocker.patch('deltona.commands.desktop.sp.run')
    out_mp4 = tmp_path / 'file"1.mp4'
    out_mp4.write_bytes(b'')
    result = runner.invoke(umpv_main, [str(out_mp4)])
    assert result.exit_code != 0
    mock_socket.return_value.send.assert_not_called()
    sp_run.assert_not_called()


def test_connect_g603_import_error(mocker: MockerFixture, runner: CliRunner) -> None:
    mocker.patch('deltona.commands.desktop.logging.basicConfig')
    mocker.patch('deltona.commands.desktop._get_gi_repository_glib')
    mock_system_bus_callable = mocker.patch(
        'deltona.commands.desktop._get_pydbus_system_bus_callable')
    mock_system_bus_callable.side_effect = ImportError("No module named 'pydbus'")
    result = runner.invoke(connect_g603_main)
    assert result.exit_code != 0


def test_connect_g603_not_linux(mocker: MockerFixture, runner: CliRunner) -> None:
    mocker.patch('deltona.commands.desktop.IS_LINUX', False)  # noqa: FBT003
    mocker.patch('deltona.commands.desktop.logging.basicConfig')
    mocker.patch('deltona.commands.desktop._get_gi_repository_glib')
    mocker.patch('deltona.commands.desktop._get_pydbus_system_bus_callable')
    result = runner.invoke(connect_g603_main)
    assert result.exit_code != 0


def test_connect_g603(mocker: MockerFixture, runner: CliRunner) -> None:
    mocker.patch('deltona.commands.desktop.logging.basicConfig')
    mock_get_gi_repository_glib = mocker.patch('deltona.commands.desktop._get_gi_repository_glib')
    mock_get_pydbus_callable = mocker.patch(
        'deltona.commands.desktop._get_pydbus_system_bus_callable')
    mock_bus = mock_get_pydbus_callable.return_value.return_value
    mock_device = mocker.MagicMock()
    mock_device.Name = 'G603'
    mock_device1 = mocker.MagicMock()
    mock_device.__getitem__.return_value = mock_device1
    mock_bus.get.return_value = mock_device
    mock_signal_subscribe = mock_bus.con.signal_subscribe

    def do_on_properties_changed(sender: str | None, interface_name: str | None, member: str | None,
                                 object_path: str | None, arg0: str | None, flags: int,
                                 callback: Callable[..., object], *user_data: Any) -> int:
        props = mocker.MagicMock()
        props.unpack.side_effect = [
            [
                'org.bluez.Adapter1',
                {
                    'Discovering': True
                },
            ],
            [
                'org.bluez.Device1',
                {
                    'Address': '00:11:22:33:44:55',
                    'ServicesResolved': True,
                    'Connected': True,
                    'RSSI': -50
                },
            ],
        ]
        callback(None, None, '/org/bluez/hci0/dev_00_11_22_33_44_55', None, None, props)
        callback(None, None, '/org/bluez/hci0/dev_00_11_22_33_44_55', None, None, props)
        return 0

    mock_signal_subscribe.side_effect = do_on_properties_changed
    mocker.patch('deltona.commands.desktop.find_bluetooth_device_info_by_name',
                 side_effect=[('path', {
                     'Address': '00:11:22:33:44:55'
                 }), KeyError])
    mock_remove_device = mock_bus.get.return_value.RemoveDevice
    mock_start_discovery = mock_bus.get.return_value.StartDiscovery
    mock_get_gi_repository_glib.return_value.MainLoop.return_value.run.side_effect = KeyboardInterrupt  # noqa: E501
    result = runner.invoke(connect_g603_main)
    assert result.exit_code == 0
    mock_remove_device.assert_called_once_with('path')
    mock_start_discovery.assert_called_once()
    mock_get_gi_repository_glib.return_value.MainLoop.return_value.run.assert_called_once()
    mock_get_gi_repository_glib.return_value.MainLoop.return_value.quit.assert_called_once()
    mock_device1.Pair.assert_called_once()
    assert 'Pairing with 00:11:22:33:44:55' in result.output


def test_connect_g603_unhandled_property_change(mocker: MockerFixture, runner: CliRunner) -> None:
    mocker.patch('deltona.commands.desktop.logging.basicConfig')
    mock_log_debug = mocker.patch('deltona.commands.desktop.log.debug')
    mock_get_gi_repository_glib = mocker.patch('deltona.commands.desktop._get_gi_repository_glib')
    mock_get_pydbus_callable = mocker.patch(
        'deltona.commands.desktop._get_pydbus_system_bus_callable')
    mock_bus = mock_get_pydbus_callable.return_value.return_value
    mock_device = mocker.MagicMock()
    mock_device.Name = 'G603'
    mock_device1 = mocker.MagicMock()
    mock_device.__getitem__.return_value = mock_device1
    mock_bus.get.return_value = mock_device
    mock_signal_subscribe = mock_bus.con.signal_subscribe

    def do_on_properties_changed(sender: str | None, interface_name: str | None, member: str | None,
                                 object_path: str | None, arg0: str | None, flags: int,
                                 callback: Callable[..., object], *user_data: Any) -> int:
        props = mocker.MagicMock()
        props.unpack.return_value = ['org.bluez.Device1', {}]
        callback(None, None, '/org/bluez/hci0/dev_00_11_22_33_44_55', None, None, props)
        return 0

    mock_signal_subscribe.side_effect = do_on_properties_changed
    mocker.patch('deltona.commands.desktop.find_bluetooth_device_info_by_name',
                 side_effect=[('path', {
                     'Address': '00:11:22:33:44:55'
                 }), KeyError])
    mock_remove_device = mock_bus.get.return_value.RemoveDevice
    mock_start_discovery = mock_bus.get.return_value.StartDiscovery
    mock_get_gi_repository_glib.return_value.MainLoop.return_value.run.side_effect = KeyboardInterrupt  # noqa: E501
    result = runner.invoke(connect_g603_main)
    assert result.exit_code == 0
    mock_remove_device.assert_called_once_with('path')
    mock_start_discovery.assert_called_once()
    mock_get_gi_repository_glib.return_value.MainLoop.return_value.run.assert_called_once()
    mock_get_gi_repository_glib.return_value.MainLoop.return_value.quit.assert_called_once()
    mock_log_debug.assert_has_calls([
        mocker.call('Unhandled property changes: interface=%s, values=%s, mac=%s',
                    'org.bluez.Device1', {}, '00:11:22:33:44:55')
    ])


def test_connect_g603_disconnected(mocker: MockerFixture, runner: CliRunner) -> None:
    mocker.patch('deltona.commands.desktop.logging.basicConfig')
    mock_log_debug = mocker.patch('deltona.commands.desktop.log.debug')
    mock_get_gi_repository_glib = mocker.patch('deltona.commands.desktop._get_gi_repository_glib')
    mock_get_pydbus_callable = mocker.patch(
        'deltona.commands.desktop._get_pydbus_system_bus_callable')
    mock_bus = mock_get_pydbus_callable.return_value.return_value
    mock_device = mocker.MagicMock()
    mock_device.Name = 'G603'
    mock_device1 = mocker.MagicMock()
    mock_device.__getitem__.return_value = mock_device1
    mock_bus.get.return_value = mock_device
    mock_signal_subscribe = mock_bus.con.signal_subscribe

    def do_on_properties_changed(sender: str | None, interface_name: str | None, member: str | None,
                                 object_path: str | None, arg0: str | None, flags: int,
                                 callback: Callable[..., object], *user_data: Any) -> int:
        props = mocker.MagicMock()
        props.unpack.side_effect = [['org.bluez.Device1', {
            'ServicesResolved': False
        }], ['other_interface', {}]]
        callback(None, None, '/org/bluez/hci0/dev_00_11_22_33_44_55', None, None, props)
        callback(None, None, '/org/bluez/hci0/dev_00_11_22_33_44_55', None, None, props)
        return 0

    mock_signal_subscribe.side_effect = do_on_properties_changed
    mocker.patch('deltona.commands.desktop.find_bluetooth_device_info_by_name',
                 side_effect=[('path', {
                     'Address': '00:11:22:33:44:55'
                 }), KeyError])
    mock_remove_device = mock_bus.get.return_value.RemoveDevice
    mock_start_discovery = mock_bus.get.return_value.StartDiscovery
    mock_get_gi_repository_glib.return_value.MainLoop.return_value.run.side_effect = KeyboardInterrupt  # noqa: E501
    result = runner.invoke(connect_g603_main)
    assert result.exit_code == 0
    mock_remove_device.assert_called_once_with('path')
    mock_start_discovery.assert_called_once()
    mock_get_gi_repository_glib.return_value.MainLoop.return_value.run.assert_called_once()
    mock_get_gi_repository_glib.return_value.MainLoop.return_value.quit.assert_called_once()
    mock_log_debug.assert_has_calls(
        [mocker.call('Device %s was disconnected.', '00:11:22:33:44:55')])


def test_connect_g603_ignores_non_g603_devices(mocker: MockerFixture, runner: CliRunner) -> None:
    mocker.patch('deltona.commands.desktop.logging.basicConfig')
    mock_log_debug = mocker.patch('deltona.commands.desktop.log.debug')
    mock_get_gi_repository_glib = mocker.patch('deltona.commands.desktop._get_gi_repository_glib')
    mock_get_pydbus_callable = mocker.patch(
        'deltona.commands.desktop._get_pydbus_system_bus_callable')
    mock_bus = mock_get_pydbus_callable.return_value.return_value
    mock_device = mocker.MagicMock()
    mock_device.Name = 'G604'
    mock_device1 = mocker.MagicMock()
    mock_device.__getitem__.return_value = mock_device1
    mock_bus.get.return_value = mock_device
    mock_signal_subscribe = mock_bus.con.signal_subscribe

    def do_on_properties_changed(sender: str | None, interface_name: str | None, member: str | None,
                                 object_path: str | None, arg0: str | None, flags: int,
                                 callback: Callable[..., object], *user_data: Any) -> int:
        props = mocker.MagicMock()
        props.unpack.return_value = ['org.bluez.Device1', {}]
        callback(None, None, '/org/bluez/hci0/dev_00_11_22_33_44_55', None, None, props)
        return 0

    mock_signal_subscribe.side_effect = do_on_properties_changed
    mocker.patch('deltona.commands.desktop.find_bluetooth_device_info_by_name',
                 side_effect=[('path', {
                     'Address': '00:11:22:33:44:55'
                 }), KeyError])
    mock_remove_device = mock_bus.get.return_value.RemoveDevice
    mock_start_discovery = mock_bus.get.return_value.StartDiscovery
    mock_get_gi_repository_glib.return_value.MainLoop.return_value.run.side_effect = KeyboardInterrupt  # noqa: E501
    result = runner.invoke(connect_g603_main)
    assert result.exit_code == 0
    mock_remove_device.assert_called_once_with('path')
    mock_start_discovery.assert_called_once()
    mock_get_gi_repository_glib.return_value.MainLoop.return_value.run.assert_called_once()
    mock_get_gi_repository_glib.return_value.MainLoop.return_value.quit.assert_called_once()
    mock_log_debug.assert_has_calls(
        [mocker.call('Ignoring device %s (MAC: %s).', 'G604', '00:11:22:33:44:55')])


def test_connect_g603_key_error(mocker: MockerFixture, runner: CliRunner) -> None:
    mocker.patch('deltona.commands.desktop.logging.basicConfig')
    mock_log_debug = mocker.patch('deltona.commands.desktop.log.debug')
    mock_get_gi_repository_glib = mocker.patch('deltona.commands.desktop._get_gi_repository_glib')
    mock_get_pydbus_callable = mocker.patch(
        'deltona.commands.desktop._get_pydbus_system_bus_callable')
    mock_bus = mock_get_pydbus_callable.return_value.return_value
    mock_device = mocker.MagicMock()
    mock_device.Name = 'G603'
    mock_device1 = mocker.MagicMock()
    mock_device.__getitem__.return_value = mock_device1
    mock_bus.get.side_effect = [mock_device, KeyError]
    mock_signal_subscribe = mock_bus.con.signal_subscribe

    def do_on_properties_changed(sender: str | None, interface_name: str | None, member: str | None,
                                 object_path: str | None, arg0: str | None, flags: int,
                                 callback: Callable[..., object], *user_data: Any) -> int:
        props = mocker.MagicMock()
        props.unpack.return_value = ['org.bluez.Device1', {}]
        callback(None, None, '/org/bluez/hci0/dev_00_11_22_33_44_55', None, None, props)
        return 0

    mock_signal_subscribe.side_effect = do_on_properties_changed
    mocker.patch('deltona.commands.desktop.find_bluetooth_device_info_by_name',
                 side_effect=[('path', {
                     'Address': '00:11:22:33:44:55'
                 }), KeyError])
    mock_get_gi_repository_glib.return_value.MainLoop.return_value.run.side_effect = KeyboardInterrupt  # noqa: E501
    result = runner.invoke(connect_g603_main)
    assert result.exit_code == 0
    mock_get_gi_repository_glib.return_value.MainLoop.return_value.run.assert_called_once()
    mock_get_gi_repository_glib.return_value.MainLoop.return_value.quit.assert_called_once()
    mock_log_debug.assert_has_calls(
        [mocker.call('Caught error with device %s: %s', '00:11:22:33:44:55', '')])


def test_connect_g603_paired(mocker: MockerFixture, runner: CliRunner) -> None:
    mocker.patch('deltona.commands.desktop.logging.basicConfig')
    mock_log_debug = mocker.patch('deltona.commands.desktop.log.debug')
    mock_get_gi_repository_glib = mocker.patch('deltona.commands.desktop._get_gi_repository_glib')
    mock_get_pydbus_callable = mocker.patch(
        'deltona.commands.desktop._get_pydbus_system_bus_callable')
    mock_bus = mock_get_pydbus_callable.return_value.return_value
    mock_device = mocker.MagicMock()
    mock_device.Name = 'G603'
    mock_device1 = mocker.MagicMock()
    mock_device.__getitem__.return_value = mock_device1
    mock_bus.get.return_value = mock_device
    mock_signal_subscribe = mock_bus.con.signal_subscribe

    def do_on_properties_changed(sender: str | None, interface_name: str | None, member: str | None,
                                 object_path: str | None, arg0: str | None, flags: int,
                                 callback: Callable[..., object], *user_data: Any) -> int:
        props = mocker.MagicMock()
        props.unpack.return_value = ['org.bluez.Device1', {'Paired': True}]
        callback(None, None, '/org/bluez/hci0/dev_00_11_22_33_44_55', None, None, props)
        return 0

    mock_signal_subscribe.side_effect = do_on_properties_changed
    mocker.patch('deltona.commands.desktop.find_bluetooth_device_info_by_name',
                 side_effect=[('path', {
                     'Address': '00:11:22:33:44:55'
                 }), KeyError])
    mock_get_gi_repository_glib.return_value.MainLoop.return_value.run.side_effect = KeyboardInterrupt  # noqa: E501
    result = runner.invoke(connect_g603_main)
    assert result.exit_code == 0
    mock_get_gi_repository_glib.return_value.MainLoop.return_value.run.assert_called_once()
    assert mock_get_gi_repository_glib.return_value.MainLoop.return_value.quit.call_count == 2
    mock_log_debug.assert_has_calls([mocker.call('Quitting.')])


def test_kill_gamescope_main(mocker: MockerFixture, runner: CliRunner) -> None:
    mock_kill_gamescope = mocker.patch('deltona.commands.desktop.kill_gamescope')
    result = runner.invoke(kill_gamescope_main)
    assert result.exit_code == 0
    mock_kill_gamescope.assert_called_once()


def test_upload_to_imgbb_xdg_install(mocker: MockerFixture, runner: CliRunner,
                                     tmp_path: Path) -> None:
    mocker.patch('deltona.commands.desktop.logging.basicConfig')
    mock_requests_get = mocker.patch('deltona.commands.desktop.requests.get')
    mock_requests_get.return_value.content = b'some image data'
    mock_sp_run = mocker.patch('deltona.commands.desktop.sp.run')
    result = runner.invoke(upload_to_imgbb_main, ['--xdg-install', str(tmp_path)])
    assert result.exit_code == 0
    mock_sp_run.assert_called_once_with(
        ('update-desktop-database', '-v', str(tmp_path / 'share/applications')),
        check=True,
        capture_output=True)
    assert (tmp_path / 'share/applications').exists()
    assert (tmp_path / 'share/applications/upload-to-imgbb.desktop').exists()
    assert 'TryExec=upload-to-imgbb' in (tmp_path /
                                         'share/applications/upload-to-imgbb.desktop').read_text()
    assert (tmp_path / 'share/icons/hicolor/300x300/apps/imgbb.png').exists()


def test_upload_to_imgbb_no_gui(mocker: MockerFixture, runner: CliRunner, tmp_path: Path) -> None:
    mocker.patch('deltona.commands.desktop.which', return_value=None)
    mocker.patch('deltona.commands.desktop.pyperclip.copy')
    mock_open = mocker.patch('deltona.commands.desktop.webbrowser.open')
    mocker.patch('deltona.commands.desktop.logging.basicConfig')
    mocker.patch('deltona.commands.desktop.upload_to_imgbb',
                 return_value=mocker.MagicMock(json=mocker.MagicMock(
                     return_value={'data': {
                         'url': 'https://example.com/image.png'
                     }})))
    a_png = tmp_path / 'a.png'
    a_png.write_bytes(b'some image data')
    result = runner.invoke(upload_to_imgbb_main,
                           [str(a_png), '--no-gui', '--no-browser', '--no-clipboard'])
    assert result.exit_code == 0
    mock_open.assert_not_called()
    assert 'https://example.com/image.png' in result.output


def test_upload_to_imgbb_gui(mocker: MockerFixture, runner: CliRunner, tmp_path: Path) -> None:
    mocker.patch('deltona.commands.desktop.which', return_value='fake')
    mock_copy = mocker.patch('deltona.commands.desktop.pyperclip.copy')
    mock_open = mocker.patch('deltona.commands.desktop.webbrowser.open')
    mock_sp_run = mocker.patch('deltona.commands.desktop.sp.run')
    mocker.patch('deltona.commands.desktop.logging.basicConfig')
    mocker.patch('deltona.commands.desktop.upload_to_imgbb',
                 return_value=mocker.MagicMock(json=mocker.MagicMock(
                     return_value={'data': {
                         'url': 'https://example.com/image.png'
                     }})))
    a_png = tmp_path / 'a.png'
    a_png.write_bytes(b'some image data')
    result = runner.invoke(upload_to_imgbb_main, [str(a_png)])
    assert result.exit_code == 0
    mock_open.assert_not_called()
    assert 'https://example.com/image.png' in result.output
    mock_sp_run.assert_called_once_with(
        ('fake', '--title', 'Successfully uploaded', '--msgbox', 'https://example.com/image.png'),
        check=False)
    mock_copy.assert_called_once_with('https://example.com/image.png')


def test_upload_to_imgbb_http_error_gui(mocker: MockerFixture, runner: CliRunner,
                                        tmp_path: Path) -> None:
    mocker.patch('deltona.commands.desktop.which', return_value='fake')
    mock_copy = mocker.patch('deltona.commands.desktop.pyperclip.copy')
    mock_open = mocker.patch('deltona.commands.desktop.webbrowser.open')
    mock_sp_run = mocker.patch('deltona.commands.desktop.sp.run')
    mocker.patch('deltona.commands.desktop.logging.basicConfig')
    mocker.patch('deltona.commands.desktop.upload_to_imgbb', side_effect=HTTPError)
    a_png = tmp_path / 'a.png'
    a_png.write_bytes(b'some image data')
    result = runner.invoke(upload_to_imgbb_main, [str(a_png)])
    assert result.exit_code != 0
    assert 'Failed to upload. Check API key!' in result.output
    mock_open.assert_not_called()
    mock_sp_run.assert_called_once_with(('fake', '--sorry', 'Failed to upload!'), check=False)
    mock_copy.assert_not_called()


def test_upload_to_imgbb_http_error(mocker: MockerFixture, runner: CliRunner,
                                    tmp_path: Path) -> None:
    mocker.patch('deltona.commands.desktop.which', return_value='fake')
    mock_copy = mocker.patch('deltona.commands.desktop.pyperclip.copy')
    mock_open = mocker.patch('deltona.commands.desktop.webbrowser.open')
    mock_sp_run = mocker.patch('deltona.commands.desktop.sp.run')
    mocker.patch('deltona.commands.desktop.logging.basicConfig')
    mocker.patch('deltona.commands.desktop.upload_to_imgbb', side_effect=HTTPError)
    a_png = tmp_path / 'a.png'
    a_png.write_bytes(b'some image data')
    result = runner.invoke(upload_to_imgbb_main, [str(a_png), '--no-gui'])
    assert result.exit_code != 0
    assert 'Failed to upload. Check API key!' in result.output
    mock_open.assert_not_called()
    mock_sp_run.assert_not_called()
    mock_copy.assert_not_called()


def test_upload_to_imgbb_no_files(mocker: MockerFixture, runner: CliRunner, tmp_path: Path) -> None:
    mocker.patch('deltona.commands.desktop.which', return_value=None)
    mocker.patch('deltona.commands.desktop.pyperclip.copy')
    mocker.patch('deltona.commands.desktop.webbrowser.open')
    mocker.patch('deltona.commands.desktop.logging.basicConfig')
    mocker.patch('deltona.commands.desktop.upload_to_imgbb',
                 return_value=mocker.MagicMock(json=mocker.MagicMock(
                     return_value={'data': {
                         'url': 'https://example.com/image.png'
                     }})))
    result = runner.invoke(upload_to_imgbb_main)
    assert result.exit_code == 0


def test_upload_to_imgbb(mocker: MockerFixture, runner: CliRunner, tmp_path: Path) -> None:
    mocker.patch('deltona.commands.desktop.which', return_value=None)
    mocker.patch('deltona.commands.desktop.pyperclip.copy')
    mock_open = mocker.patch('deltona.commands.desktop.webbrowser.open')
    mocker.patch('deltona.commands.desktop.logging.basicConfig')
    mocker.patch('deltona.commands.desktop.upload_to_imgbb',
                 return_value=mocker.MagicMock(json=mocker.MagicMock(
                     return_value={'data': {
                         'url': 'https://example.com/image.png'
                     }})))
    a_png = tmp_path / 'a.png'
    a_png.write_bytes(b'some image data')
    result = runner.invoke(upload_to_imgbb_main, [str(a_png)])
    assert result.exit_code == 0
    mock_open.assert_called_once_with('https://example.com/image.png')


def test_mpv_sbs_main(mocker: MockerFixture, runner: CliRunner, tmp_path: Path) -> None:
    mocker.patch('deltona.commands.desktop.logging.basicConfig')
    mocker.patch('deltona.commands.desktop.ffprobe',
                 return_value={
                     'streams': [{
                         'codec_type': 'other',
                         'disposition': {
                             'default': 0
                         }
                     }, {
                         'codec_type': 'other'
                     }, {
                         'codec_type': 'video',
                         'width': 1920,
                         'height': 1080,
                         'disposition': {
                             'default': 1
                         },
                     }]
                 })
    mock_sp_run = mocker.patch('deltona.commands.desktop.sp.run')
    out_mp4 = tmp_path / 'file1.mp4'
    out_mp4.write_bytes(b'file1')
    out_mp4_right = tmp_path / 'file1_right.mp4'
    out_mp4_right.write_bytes(b'file1_right')
    result = runner.invoke(mpv_sbs_main, [str(out_mp4), str(out_mp4_right)])
    assert result.exit_code == 0
    mock_sp_run.assert_called_once_with(
        ('mpv', '--hwdec=no', '--config=no', str(out_mp4), f'--external-file={out_mp4_right}',
         '--lavfi-complex=[vid1][vid2] hstack [vo]'),
        check=True)


def test_mpv_sbs_main_non_matching_height(mocker: MockerFixture, runner: CliRunner,
                                          tmp_path: Path) -> None:
    mocker.patch('deltona.commands.desktop.logging.basicConfig')
    mocker.patch('deltona.commands.desktop.ffprobe',
                 side_effect=[{
                     'streams': [{
                         'codec_type': 'other',
                         'disposition': {
                             'default': 0
                         }
                     }, {
                         'codec_type': 'other'
                     }, {
                         'codec_type': 'video',
                         'width': 1920,
                         'height': 1080,
                         'disposition': {
                             'default': 1
                         },
                     }]
                 }, {
                     'streams': [{
                         'codec_type': 'video',
                         'width': 640,
                         'height': 480,
                         'disposition': {
                             'default': 1
                         }
                     }]
                 }])
    mock_sp_run = mocker.patch('deltona.commands.desktop.sp.run')
    out_mp4 = tmp_path / 'file1.mp4'
    out_mp4.write_bytes(b'file1')
    out_mp4_right = tmp_path / 'file1_right.mp4'
    out_mp4_right.write_bytes(b'file1_right')
    result = runner.invoke(mpv_sbs_main, [str(out_mp4), str(out_mp4_right)])
    assert result.exit_code == 0
    mock_sp_run.assert_called_once_with(
        ('mpv', '--hwdec=no', '--config=no', str(out_mp4), f'--external-file={out_mp4_right}',
         ('--lavfi-complex=[vid1] scale=1920x1080 [vid1_scale];[vid2] scale=1920x1080 [vid2_crop];'
          '[vid1_scale][vid2_crop] hstack [vo]')),
        check=True)
