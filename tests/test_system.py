from __future__ import annotations

from typing import TYPE_CHECKING, Any, Never
from unittest import mock
import os

from deltona.system import (
    POSITION_RE,
    STATE_RE,
    MultipleKeySlots,
    find_bluetooth_device_info_by_name,
    get_inhibitor,
    get_kwriteconfig_commands,
    inhibit_notifications,
    kill_gamescope,
    kill_wine,
    pan_connect,
    pan_disconnect,
    patch_macos_bundle_info_plist,
    reset_tpm_enrollment,
    slug_rename,
    uninhibit_notifications,
    wait_for_disc,
)
from deltona.typing import CDStatus
import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture

INHIBIT_SUCCESS_CODE = 1234


def make_fake_system_bus() -> tuple[Any, mock.Mock]:
    manager = mock.Mock()

    class FakeSystemBus:
        def get(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {'org.freedesktop.login1.Manager': manager}

    return FakeSystemBus, manager


def make_fake_session_bus() -> tuple[Any, mock.Mock]:
    notifications = mock.Mock()

    class FakeSessionBus:
        def get(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return notifications

    return FakeSessionBus, notifications


def test_get_inhibitor_success(monkeypatch: pytest.MonkeyPatch) -> None:
    fsb, manager = make_fake_system_bus()
    manager.Inhibit.return_value = INHIBIT_SUCCESS_CODE
    monkeypatch.setattr('pydbus.SystemBus', fsb)
    result = get_inhibitor('sleep', 'test_user', 'testing', 'block')
    assert result == INHIBIT_SUCCESS_CODE
    manager.Inhibit.assert_called_once_with('sleep', 'test_user', 'testing', 'block')


def test_inhibit_notifications_success(monkeypatch: pytest.MonkeyPatch) -> None:
    fsb, mock_notifications = make_fake_session_bus()
    monkeypatch.setattr('pydbus.SessionBus', fsb)
    mock_notifications.Inhibited = False
    mock_notifications.Inhibit.return_value = 1234
    result = inhibit_notifications('test_app', 'testing')
    assert result is True
    mock_notifications.Inhibit.assert_called_once_with('test_app', 'testing', {})


def test_inhibit_notifications_already_inhibited(monkeypatch: pytest.MonkeyPatch) -> None:
    fsb, mock_notifications = make_fake_session_bus()
    monkeypatch.setattr('pydbus.SessionBus', fsb)
    mock_notifications.Inhibited = True
    result = inhibit_notifications('test_app', 'testing')
    assert result is False


def test_uninhibit_notifications_success(monkeypatch: pytest.MonkeyPatch) -> None:
    fsb, mock_notifications = make_fake_session_bus()
    monkeypatch.setattr('pydbus.SessionBus', fsb)
    mock_notifications.Inhibited = True
    mock_notifications.UnInhibit.return_value = None
    monkeypatch.setattr('deltona.system._key', 1234)
    uninhibit_notifications()
    mock_notifications.UnInhibit.assert_called_once_with(1234)


def test_uninhibit_notifications_not_inhibited(monkeypatch: pytest.MonkeyPatch) -> None:
    fsb, mock_notifications = make_fake_session_bus()
    monkeypatch.setattr('pydbus.SessionBus', fsb)
    mock_notifications.Inhibited = False
    uninhibit_notifications()
    mock_notifications.UnInhibit.assert_not_called()


def test_uninhibit_notifications_session_bus_get_returns_none(mocker: MockerFixture) -> None:
    mock_session_bus = mocker.patch('pydbus.SessionBus')
    mock_session_bus.return_value.get.return_value = None
    with pytest.raises(ConnectionError):
        uninhibit_notifications()


def test_uninhibit_notifications_key_is_none(mocker: MockerFixture) -> None:
    fsb, mock_notifications = make_fake_session_bus()
    mocker.patch('pydbus.SessionBus', fsb)
    mock_notifications.Inhibited = True
    mocker.patch('deltona.system._key', None)
    uninhibit_notifications()
    mock_notifications.UnInhibit.assert_not_called()


def test_wait_for_disc_success(mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    def mock_ioctl(*args: Any) -> CDStatus:
        return CDStatus.DISC_OK

    monkeypatch.setattr('fcntl.ioctl', mock_ioctl)
    mock_context_os_open = mocker.patch('deltona.system.context_os_open')
    result = wait_for_disc()
    assert result is True
    mock_context_os_open.assert_called_once_with('dev/sr0', os.O_RDONLY | os.O_NONBLOCK)


def test_wait_for_disc_keyboard_interrupt(mocker: MockerFixture,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    def mock_ioctl(*args: Any) -> Never:
        raise KeyboardInterrupt

    monkeypatch.setattr('fcntl.ioctl', mock_ioctl)
    mock_context_os_open = mocker.patch('deltona.system.context_os_open')
    assert wait_for_disc() is False
    mock_context_os_open.assert_called_once_with('dev/sr0', os.O_RDONLY | os.O_NONBLOCK)


def test_wait_for_disc_waiting_for_ok(mocker: MockerFixture,
                                      monkeypatch: pytest.MonkeyPatch) -> None:
    call_count = 0

    def mock_ioctl(*args: Any) -> CDStatus:
        nonlocal call_count
        if call_count == 0:
            call_count += 1
            return CDStatus.DRIVE_NOT_READY
        return CDStatus.DISC_OK

    monkeypatch.setattr('fcntl.ioctl', mock_ioctl)
    mocker.patch('deltona.system.context_os_open')
    mock_sleep = mocker.patch('deltona.system.sleep')
    result = wait_for_disc()
    assert result
    assert mock_sleep.call_count == 1


def make_fake_bluez_system_bus() -> tuple[Any, mock.Mock]:
    manager = mock.Mock()

    class FakeSystemBus:
        def get(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {'org.freedesktop.DBus.ObjectManager': manager}

    return FakeSystemBus, manager


def test_find_bluetooth_device_info_by_name_success(monkeypatch: pytest.MonkeyPatch) -> None:
    fsb, mock_bluez = make_fake_bluez_system_bus()
    mock_bluez.GetManagedObjects.return_value = {
        '/org/bluez/hci0/dev_00_11_22_33_44_55': {
            'org.bluez.Device1': {
                'Name': 'TestDevice'
            }
        }
    }
    monkeypatch.setattr('pydbus.SystemBus', fsb)
    result = find_bluetooth_device_info_by_name('TestDevice')
    assert result == (  # type: ignore[comparison-overlap]
        '/org/bluez/hci0/dev_00_11_22_33_44_55', {
            'Name': 'TestDevice'
        })
    mock_bluez.GetManagedObjects.assert_called_once()


def test_find_bluetooth_device_info_by_name_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    fsb, mock_bluez = make_fake_bluez_system_bus()
    mock_bluez.GetManagedObjects.return_value = {}
    monkeypatch.setattr('pydbus.SystemBus', fsb)
    with pytest.raises(KeyError):
        find_bluetooth_device_info_by_name('TestDevice')


def test_find_bluetooth_device_info_by_name_not_linux(mocker: MockerFixture) -> None:
    mocker.patch('deltona.system.IS_LINUX', False)  # noqa: FBT003
    with pytest.raises(NotImplementedError):
        find_bluetooth_device_info_by_name('TestDevice')


def test_find_bluetooth_device_info_by_name_no_device1(mocker: MockerFixture) -> None:
    mocker.patch('deltona.system.IS_LINUX', True)  # noqa: FBT003
    fsb, mock_bluez = make_fake_bluez_system_bus()
    mock_bluez.GetManagedObjects.return_value = {
        '/org/bluez/hci0/dev_00_11_22_33_44_55': {
            'org.bluez.NotDevice1': {
                'Name': 'TestDevice'
            }
        }
    }
    mocker.patch('pydbus.SystemBus', fsb)
    with pytest.raises(KeyError):
        find_bluetooth_device_info_by_name('TestDevice')
    mock_bluez.GetManagedObjects.assert_called_once()


def test_slug_rename_success(mocker: MockerFixture) -> None:
    mock_path = mocker.patch('deltona.system.Path')
    mock_slugify = mocker.patch('deltona.system.slugify')
    mock_path.return_value.resolve.return_value = mock_path
    mock_path.parent = mock_path
    mock_slugify.return_value = 'slugified_name'
    result = slug_rename('test_path')
    assert result == mock_path.rename.return_value
    mock_path.return_value.resolve.assert_called_once_with(strict=True)
    mock_slugify.assert_called_once_with(mock_path.name, no_lower=False)
    mock_path.rename.assert_called_once_with(mock_path / 'slugified_name')


def test_patch_macos_bundle_info_plist_success(mocker: MockerFixture) -> None:
    mock_path = mocker.patch('deltona.system.Path')
    mock_plistlib = mocker.patch('deltona.system.plistlib')
    mock_info_plist = mock_path.return_value.resolve.return_value.__truediv__.return_value.__truediv__.return_value  # noqa: E501
    mock_info_plist.open.return_value.__enter__.return_value = mock.Mock()
    patch_macos_bundle_info_plist('test_bundle', key='value')
    mock_info_plist.open.assert_any_call('rb')
    mock_info_plist.open.assert_any_call('wb')
    mock_plistlib.load.assert_called_once()
    mock_plistlib.dump.assert_called_once()
    mock_info_plist.touch.assert_called_once()


def test_kill_gamescope_success(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_proc_gs = mock.Mock()
    mock_proc_gs.info = {'name': 'gamescope'}
    mock_proc_gsr = mock.Mock()
    mock_proc_gsr.info = {'name': 'gamescopereaper'}
    mock_proc_not_gs = mock.Mock()
    mock_proc_not_gs.info = {'name': 'not_gamescope'}

    def mock_process_iter(*args: Any) -> Any:
        nonlocal mock_proc_gs, mock_proc_gsr, mock_proc_not_gs
        return [mock_proc_gs, mock_proc_gsr, mock_proc_not_gs]

    monkeypatch.setattr('psutil.process_iter', mock_process_iter)
    kill_gamescope()
    mock_proc_gs.kill.assert_called_once()
    mock_proc_gsr.kill.assert_called_once()
    mock_proc_not_gs.kill.assert_not_called()


def test_pan_connect_success(mocker: MockerFixture) -> None:
    mock_system_bus = mocker.patch('pydbus.SystemBus')
    mock_device = mocker.Mock()
    mock_system_bus.return_value.get.return_value = mock_device
    mocker.patch('deltona.system.IS_LINUX', True)  # noqa: FBT003
    pan_connect('00:11:22:33:44:55', hci='hci1')
    mock_system_bus.return_value.get.assert_called_once_with(
        'org.bluez', '/org/bluez/hci1/dev_00_11_22_33_44_55')
    mock_device.Connect.assert_called_once_with('nap')


def test_pan_connect_not_linux(mocker: MockerFixture) -> None:
    mocker.patch('deltona.system.IS_LINUX', False)  # noqa: FBT003
    with pytest.raises(NotImplementedError):
        pan_connect('00:11:22:33:44:55')


def test_pan_disconnect_success(mocker: MockerFixture) -> None:
    mock_system_bus = mocker.patch('pydbus.SystemBus')
    mock_device = mocker.Mock()
    mock_system_bus.return_value.get.return_value = mock_device
    mocker.patch('deltona.system.IS_LINUX', True)  # noqa: FBT003
    pan_disconnect('00:11:22:33:44:55', hci='hci2')
    mock_system_bus.return_value.get.assert_called_once_with(
        'org.bluez', '/org/bluez/hci2/dev_00_11_22_33_44_55')
    mock_device.Disconnect.assert_called_once_with()


def test_pan_disconnect_not_linux(mocker: MockerFixture) -> None:
    mocker.patch('deltona.system.IS_LINUX', False)  # noqa: FBT003
    with pytest.raises(NotImplementedError):
        pan_disconnect('00:11:22:33:44:55')


def test_kill_wine_kills_wine_processes(mocker: MockerFixture) -> None:
    mock_proc_wineserver = mocker.Mock()
    mock_proc_wineserver.info = {'name': 'wineserver'}
    mock_proc_wine_preloader = mocker.Mock()
    mock_proc_wine_preloader.info = {'name': 'wine-preloader'}
    mock_proc_wine64_preloader = mocker.Mock()
    mock_proc_wine64_preloader.info = {'name': 'wine64-preloader'}
    mock_proc_exe = mocker.Mock()
    mock_proc_exe.info = {'name': 'SOME.EXE'}
    mock_proc_other = mocker.Mock()
    mock_proc_other.info = {'name': 'not_wine'}

    def mock_process_iter(*args: Any, **kwargs: Any) -> list[Any]:
        return [
            mock_proc_wineserver,
            mock_proc_wine_preloader,
            mock_proc_wine64_preloader,
            mock_proc_exe,
            mock_proc_other,
        ]

    mocker.patch('psutil.process_iter', mock_process_iter)
    kill_wine()
    mock_proc_wineserver.kill.assert_called_once()
    mock_proc_wine_preloader.kill.assert_called_once()
    mock_proc_wine64_preloader.kill.assert_called_once()
    mock_proc_exe.kill.assert_called_once()
    mock_proc_other.kill.assert_not_called()


def test_kill_wine_handles_no_matching_processes(mocker: MockerFixture) -> None:
    mock_proc_other1 = mocker.Mock()
    mock_proc_other1.info = {'name': 'foo'}
    mock_proc_other2 = mocker.Mock()
    mock_proc_other2.info = {'name': 'bar'}

    def mock_process_iter(*args: Any, **kwargs: Any) -> list[Any]:
        return [mock_proc_other1, mock_proc_other2]

    mocker.patch('psutil.process_iter', mock_process_iter)
    kill_wine()
    mock_proc_other1.kill.assert_not_called()
    mock_proc_other2.kill.assert_not_called()


def test_kill_wine_handles_case_insensitive_exe(mocker: MockerFixture) -> None:
    mock_proc_exe = mocker.Mock()
    mock_proc_exe.info = {'name': 'program.ExE'}

    def mock_process_iter(*args: Any, **kwargs: Any) -> list[Any]:
        return [mock_proc_exe]

    mocker.patch('psutil.process_iter', mock_process_iter)
    kill_wine()
    mock_proc_exe.kill.assert_called_once()


def test_reset_tpm_enrollment_dry_run_logs(mocker: MockerFixture) -> None:
    mock_log = mocker.patch('deltona.system.log')
    mock_sp_run = mocker.patch('deltona.system.sp.run')
    mock_json_loads = mocker.patch('deltona.system.json.loads')
    mock_json_loads.return_value = {'tokens': {'1': {'type': 'systemd-tpm2', 'keyslots': ['0']}}}
    uuid = 'deadbeef'
    reset_tpm_enrollment(uuid, dry_run=True)
    assert mock_log.info.call_count == 3
    assert mock_sp_run.call_count == 1
    mock_sp_run.assert_called_with(
        ('cryptsetup', 'luksDump', '--dump-json-metadata', f'/dev/disk/by-uuid/{uuid}'),
        check=True,
        capture_output=True)


def test_reset_tpm_enrollment_no_tokens(mocker: MockerFixture) -> None:
    mock_log = mocker.patch('deltona.system.log')
    mock_sp_run = mocker.patch('deltona.system.sp.run')
    mock_json_loads = mocker.patch('deltona.system.json.loads')
    mock_json_loads.return_value = {'tokens': {}}
    uuid = 'deadbeef'
    reset_tpm_enrollment(uuid, dry_run=True)
    mock_log.debug.assert_any_call('No tokens found for device %s.', f'/dev/disk/by-uuid/{uuid}')
    mock_sp_run.assert_called_once()


def test_reset_tpm_enrollment_multiple_keyslots(mocker: MockerFixture) -> None:
    mock_sp_run = mocker.patch('deltona.system.sp.run')
    mock_json_loads = mocker.patch('deltona.system.json.loads')
    mock_json_loads.return_value = {
        'tokens': {
            '1': {
                'type': 'systemd-tpm2',
                'keyslots': ['0', '1']
            }
        }
    }
    uuid = 'deadbeef'
    with pytest.raises(MultipleKeySlots):
        reset_tpm_enrollment(uuid, dry_run=True)
    mock_sp_run.assert_called_once()


def test_reset_tpm_enrollment_real_run(mocker: MockerFixture) -> None:
    mock_log = mocker.patch('deltona.system.log')
    mock_sp_run = mocker.patch('deltona.system.sp.run')
    mock_json_loads = mocker.patch('deltona.system.json.loads')
    mock_json_loads.return_value = {'tokens': {'1': {'type': 'systemd-tpm2', 'keyslots': ['0']}}}
    uuid = 'deadbeef'
    reset_tpm_enrollment(uuid, dry_run=False)
    assert mock_sp_run.call_count == 4
    mock_log.info.assert_called_with('Reset TPM enrolment for %s.', uuid)


def test_get_kwriteconfig_commands_basic(mocker: MockerFixture) -> None:
    mock_default_file = mocker.MagicMock()
    mock_path = mocker.patch('deltona.system.Path')
    mock_path.return_value.resolve.return_value = mock_default_file
    mocker.patch('deltona.system.DEFAULT_FILE', mock_default_file)
    mock_home = mock_path.home.return_value
    mock_home.__str__.return_value = '/home/user'
    mock_path.return_value.exists.return_value = False
    mock_path.return_value.__str__.return_value = '/home/user/.config/kdeglobals'
    mock_config = mocker.patch('deltona.system.configparser.ConfigParser')
    config_instance = mock_config.return_value
    config_instance.sections.return_value = ['General']
    config_instance.__getitem__.return_value.items.return_value = [('Key', 'Value')]
    mocker.patch('deltona.system.is_binary_string', return_value=False)
    mocker.patch('deltona.system.re.match', side_effect=lambda _, __: None)
    mocker.patch('deltona.system.re.search', side_effect=lambda _, __: None)
    commands = list(get_kwriteconfig_commands())
    assert commands
    assert commands[0].startswith('kwriteconfig6')
    assert '--group' in commands[0]
    assert '--key' in commands[0]
    assert 'General' in commands[0]
    assert 'Key' in commands[0]
    assert 'Value' in commands[0]


def test_get_kwriteconfig_commands_not_default_file(mocker: MockerFixture) -> None:
    mock_path = mocker.patch('deltona.system.Path')
    mock_home = mock_path.home
    mock_home.return_value = mock_path
    mock_path.__truediv__.return_value = mock_path
    mock_path.resolve.return_value = mock_path
    mock_path.__str__.return_value = '/home/user/.config/otherfilerc'  # type: ignore[attr-defined]
    mock_config = mocker.patch('deltona.system.configparser.ConfigParser')
    config_instance = mock_config.return_value
    config_instance.sections.return_value = ['General']
    config_instance.__getitem__.return_value.items.return_value = [('Key', 'Value')]
    mocker.patch('deltona.system.is_binary_string', return_value=False)
    mocker.patch('deltona.system.Path.exists', return_value=False)
    mocker.patch('deltona.system.re.match', side_effect=lambda _, __: None)
    mocker.patch('deltona.system.re.search', side_effect=lambda _, __: None)
    commands = list(get_kwriteconfig_commands('/home/user/.config/otherfilerc'))
    assert commands
    assert commands[0].startswith('kwriteconfig6')
    assert '--group' in commands[0]
    assert '--key' in commands[0]
    assert 'General' in commands[0]
    assert 'Key' in commands[0]
    assert 'Value' in commands[0]


def test_get_kwriteconfig_commands_ignores_binary(mocker: MockerFixture) -> None:
    mock_path = mocker.patch('deltona.system.Path')
    mock_home = mocker.patch('deltona.system.Path.home')
    mock_home.return_value = mock_path
    mock_path.__truediv__.return_value = mock_path
    mock_path.resolve.return_value = mock_path
    mock_path.__str__.return_value = '/home/user/.config/kdeglobals'  # type: ignore[attr-defined]
    mock_config = mocker.patch('deltona.system.configparser.ConfigParser')
    config_instance = mock_config.return_value
    config_instance.sections.return_value = ['General']
    config_instance.__getitem__.return_value.items.return_value = [('Key', 'Value')]
    mocker.patch('deltona.system.is_binary_string', return_value=True)
    mocker.patch('deltona.system.Path.exists', return_value=False)
    mocker.patch('deltona.system.re.match', side_effect=lambda _, __: None)
    mocker.patch('deltona.system.re.search', side_effect=lambda _, __: None)
    commands = list(get_kwriteconfig_commands('/home/user/.config/kdeglobals'))
    assert commands == []


def test_get_kwriteconfig_commands_ignores_ignored_groups(mocker: MockerFixture) -> None:
    mock_path = mocker.patch('deltona.system.Path')
    mock_home = mocker.patch('deltona.system.Path.home')
    mock_home.return_value = mock_path
    mock_path.__truediv__.return_value = mock_path
    mock_path.resolve.return_value = mock_path
    mock_path.__str__.return_value = '/home/user/.config/kdeglobals'  # type: ignore[attr-defined]

    mock_config = mocker.patch('deltona.system.configparser.ConfigParser')
    config_instance = mock_config.return_value
    # Use an ignored group
    config_instance.sections.return_value = ['KFileDialog Settings']
    config_instance.__getitem__.return_value.items.return_value = [('Key', 'Value')]

    mocker.patch('deltona.system.is_binary_string', return_value=False)
    mocker.patch('deltona.system.Path.exists', return_value=False)
    mocker.patch('deltona.system.re.match', side_effect=lambda _, __: None)
    mocker.patch('deltona.system.re.search', side_effect=lambda _, __: None)

    commands = list(get_kwriteconfig_commands('/home/user/.config/kdeglobals'))
    assert commands == []


def test_get_kwriteconfig_commands_skips_metrics_and_state(mocker: MockerFixture) -> None:
    mock_path = mocker.patch('deltona.system.Path')
    mock_home = mocker.patch('deltona.system.Path.home')
    mock_home.return_value = mock_path
    mock_path.__truediv__.return_value = mock_path
    mock_path.resolve.return_value = mock_path
    mock_path.__str__.return_value = '/home/user/.config/kdeglobals'  # type: ignore[attr-defined]
    mock_config = mocker.patch('deltona.system.configparser.ConfigParser')
    config_instance = mock_config.return_value
    config_instance.sections.return_value = ['General']
    config_instance.__getitem__.return_value.items.return_value = [('Height', '100'),
                                                                   ('State', 'AAAA/'),
                                                                   ('Special[$e]', 'foo'),
                                                                   ('NormalKey', 'bar')]

    mocker.patch('deltona.system.is_binary_string', return_value=False)
    mocker.patch('deltona.system.Path.exists', return_value=False)

    def fake_search(pattern: str, value: str) -> bool | None:
        if pattern == POSITION_RE and value == 'Height':
            return True
        if pattern == STATE_RE and value == 'AAAA/':
            return True
        return None

    mocker.patch('deltona.system.re.match', side_effect=lambda _, __: None)
    mocker.patch('deltona.system.re.search', side_effect=fake_search)

    commands = list(get_kwriteconfig_commands('/home/user/.config/kdeglobals'))
    # Only 'NormalKey' should be yielded
    assert len(commands) == 1
    assert 'NormalKey' in commands[0]


def test_get_kwriteconfig_commands_type_detection(mocker: MockerFixture) -> None:
    mock_path = mocker.patch('deltona.system.Path')
    mock_home = mocker.patch('deltona.system.Path.home')
    mock_home.return_value = mock_path
    mock_path.__truediv__.return_value = mock_path
    mock_path.resolve.return_value = mock_path
    mock_path.__str__.return_value = '/home/user/.config/kdeglobals'  # type: ignore[attr-defined]
    mock_config = mocker.patch('deltona.system.configparser.ConfigParser')
    config_instance = mock_config.return_value
    config_instance.sections.return_value = ['General']
    config_instance.__getitem__.return_value.items.return_value = [('BoolKey', 'true'),
                                                                   ('IntKey', '42'),
                                                                   ('PathKey', '/some/file'),
                                                                   ('StringKey', 'hello')]
    mocker.patch('deltona.system.is_binary_string', return_value=False)

    def fake_exists(path: Path) -> bool:
        return str(path) == '/some/file'

    mocker.patch('deltona.system.Path.exists', side_effect=fake_exists)

    def fake_match(pattern: str, value: str) -> bool | None:
        if pattern == r'^(?:1|true|false|on|yes)$' and value == 'true':
            return True
        if pattern == r'^-?[0-9]+$' and value == '42':
            return True
        return None

    mocker.patch('deltona.system.re.match', side_effect=fake_match)
    mocker.patch('deltona.system.re.search', return_value=None)
    commands = list(get_kwriteconfig_commands('/home/user/.config/kdeglobals'))
    assert any('--type' in cmd and 'bool' in cmd for cmd in commands)
    assert any('--type' in cmd and 'int' in cmd for cmd in commands)
    assert any('--type' in cmd and 'path' in cmd for cmd in commands)
    assert any('--type' not in cmd for cmd in commands)  # StringKey has no type


def test_get_kwriteconfig_commands_type_detection_path_not_file(mocker: MockerFixture) -> None:
    mock_path = mocker.patch('deltona.system.Path')
    mock_path.return_value.exists.side_effect = OSError
    mock_home = mock_path.home
    mock_home.return_value = mock_path
    mock_path.__truediv__.return_value = mock_path
    mock_path.resolve.return_value = mock_path
    mock_path.__str__.return_value = '/home/user/.config/kdeglobals'  # type: ignore[attr-defined]
    mock_config = mocker.patch('deltona.system.configparser.ConfigParser')
    config_instance = mock_config.return_value
    config_instance.sections.return_value = ['General']
    config_instance.__getitem__.return_value.items.return_value = [('BoolKey', 'true'),
                                                                   ('IntKey', '42'),
                                                                   ('PathKey', '/some/file'),
                                                                   ('StringKey', 'hello')]
    mocker.patch('deltona.system.is_binary_string', return_value=False)

    def fake_match(pattern: str, value: str) -> bool | None:
        if pattern == r'^(?:1|true|false|on|yes)$' and value == 'true':
            return True
        if pattern == r'^-?[0-9]+$' and value == '42':
            return True
        return None

    mocker.patch('deltona.system.re.match', side_effect=fake_match)
    mocker.patch('deltona.system.re.search', return_value=None)
    commands = list(get_kwriteconfig_commands('/home/user/.config/kdeglobals'))
    assert any('--type' in cmd and 'bool' in cmd for cmd in commands)
    assert any('--type' in cmd and 'int' in cmd for cmd in commands)
    assert any('--type' in cmd and 'path' not in cmd for cmd in commands)
    assert any('--type' not in cmd for cmd in commands)  # StringKey has no type


def test_get_kwriteconfig_commands_returns_from_unicode_decode_error(mocker: MockerFixture) -> None:
    mock_path = mocker.patch('deltona.system.Path')
    mock_path.home.return_value = mock_path
    mock_path.__truediv__.return_value = mock_path
    mock_path.resolve.return_value = mock_path
    mock_path.__str__.return_value = '/home/user/.config/kdeglobals'  # type: ignore[attr-defined]
    mock_config = mocker.patch('deltona.system.configparser.ConfigParser')
    config_instance = mock_config.return_value
    config_instance.read.side_effect = UnicodeDecodeError('utf-8', b'\x80', 0, 1,
                                                          'invalid start byte')
    try:
        list(get_kwriteconfig_commands('/home/user/.config/kdeglobals'))
    except UnicodeDecodeError:
        pytest.fail('Unexpected UnicodeDecodeError raised.')


def test_get_kwriteconfig_commands_skips_sections_with_brackets(mocker: MockerFixture) -> None:
    mock_path = mocker.patch('deltona.system.Path')
    mock_home = mocker.patch('deltona.system.Path.home')
    mock_home.return_value = mock_path
    mock_path.__truediv__.return_value = mock_path
    mock_path.resolve.return_value = mock_path
    mock_path.__str__.return_value = '/home/user/.config/kdeglobals'  # type: ignore[attr-defined]
    mock_config = mocker.patch('deltona.system.configparser.ConfigParser')
    config_instance = mock_config.return_value
    # Section with '][' in the name should be skipped
    config_instance.sections.return_value = ['General][Extra']
    config_instance.__getitem__.return_value.items.return_value = [('Key', 'Value')]
    mocker.patch('deltona.system.is_binary_string', return_value=False)
    mocker.patch('deltona.system.Path.exists', return_value=False)
    mocker.patch('deltona.system.re.match', side_effect=lambda _, __: None)
    mocker.patch('deltona.system.re.search', side_effect=lambda _, __: None)
    commands = list(get_kwriteconfig_commands('/home/user/.config/kdeglobals'))
    assert commands == []
