from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any
import plistlib

from deltona.rclone import (
    AlreadyRunning,
    bisync,
    default_remote,
    default_service_kind,
    default_service_name,
    enable_service,
    generate_service,
    install_service,
    service_path,
    single_instance,
    sync_once,
    watch_and_sync,
)
import pytest

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def test_default_remote(tmp_path: Path) -> None:
    assert default_remote(tmp_path / 'Documents') == 'gdrive:Documents'


def test_default_service_name(tmp_path: Path) -> None:
    assert default_service_name(tmp_path / 'My Docs') == 'rclone-bisync-my-docs'


@pytest.mark.parametrize(('platform', 'expected'), [('darwin', 'launchd'),
                                                    ('linux', 'systemd-user')])
def test_default_service_kind(mocker: MockerFixture, platform: str, expected: str) -> None:
    mocker.patch('deltona.rclone.sys.platform', platform)
    assert default_service_kind() == expected


def test_service_path(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.rclone.Path.home', return_value=tmp_path)
    assert service_path('launchd', 'x') == tmp_path / 'Library/LaunchAgents/x.plist'
    assert service_path('systemd-user', 'x') == tmp_path / '.config/systemd/user/x.service'
    assert service_path('systemd-system', 'x') == Path('/etc/systemd/system/x.service')


def test_generate_service_systemd_user() -> None:
    text = generate_service('systemd-user', 'x', ('/bin/thing', 'a b'), description='Sync.')
    assert 'Description=Sync.' in text
    assert "ExecStart=/bin/thing 'a b'" in text
    assert 'WantedBy=default.target' in text
    assert 'User=' not in text


def test_generate_service_systemd_system_user() -> None:
    text = generate_service('systemd-system', 'x', ('/bin/thing',), user='tatsh')
    assert 'User=tatsh' in text
    assert 'WantedBy=multi-user.target' in text


def test_generate_service_launchd() -> None:
    parsed: dict[str, Any] = plistlib.loads(
        generate_service('launchd', 'sh.tat.x', ('/bin/thing', '--flag')).encode())
    assert parsed['Label'] == 'sh.tat.x'
    assert parsed['ProgramArguments'] == ['/bin/thing', '--flag']
    assert parsed['RunAtLoad'] is True
    assert 'PATH' in parsed['EnvironmentVariables']


@pytest.mark.parametrize(('kind', 'expected'), [
    ('launchd', 'launchctl'),
    ('systemd-system', 'systemctl'),
    ('systemd-user', 'systemctl'),
])
def test_enable_service(mocker: MockerFixture, tmp_path: Path, kind: str, expected: str) -> None:
    mocker.patch('deltona.rclone.Path.home', return_value=tmp_path)
    mock_run = mocker.patch('deltona.rclone.sp.run')
    enable_service(kind, 'x')  # type: ignore[arg-type]
    assert mock_run.call_args_list[-1].args[0][0] == expected


def test_install_service(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.rclone.Path.home', return_value=tmp_path)
    mock_enable = mocker.patch('deltona.rclone.enable_service')
    path = install_service('systemd-user', 'x', ('/bin/thing',))
    assert path.read_text(encoding='utf-8').startswith('[Unit]')
    mock_enable.assert_called_once_with('systemd-user', 'x')


def test_install_service_no_enable(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.rclone.Path.home', return_value=tmp_path)
    mock_enable = mocker.patch('deltona.rclone.enable_service')
    install_service('systemd-user', 'x', ('/bin/thing',), enable=False)
    mock_enable.assert_not_called()


def test_bisync(mocker: MockerFixture, tmp_path: Path) -> None:
    mock_run = mocker.patch('deltona.rclone.sp.run')
    bisync(tmp_path, 'gdrive:D', ('--extra',))
    command = mock_run.call_args.args[0]
    assert command[:4] == ('rclone', 'bisync', str(tmp_path), 'gdrive:D')
    assert '--drive-skip-gdocs' in command
    assert command[-1] == '--extra'
    assert '--resync' not in command
    assert mock_run.call_args.kwargs['check'] is True


def test_bisync_resync(mocker: MockerFixture, tmp_path: Path) -> None:
    mock_run = mocker.patch('deltona.rclone.sp.run')
    bisync(tmp_path, 'gdrive:D', resync=True)
    assert mock_run.call_args.args[0][-1] == '--resync'


def test_sync_once_first_run_resyncs(mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch,
                                     tmp_path: Path) -> None:
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'cache'))
    mock_bisync = mocker.patch('deltona.rclone.bisync')
    sync_once(tmp_path, 'gdrive:D')
    assert mock_bisync.call_args.kwargs['resync'] is True
    sync_once(tmp_path, 'gdrive:D')
    assert mock_bisync.call_args.kwargs == {}


def test_single_instance_rejects_second(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('XDG_RUNTIME_DIR', str(tmp_path))
    with single_instance(tmp_path), pytest.raises(AlreadyRunning), single_instance(tmp_path):
        pass


def test_single_instance_releases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('XDG_RUNTIME_DIR', str(tmp_path))
    with single_instance(tmp_path):
        pass
    with single_instance(tmp_path):
        pass


def test_watch_and_sync_polls(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.rclone.Observer')
    mock_sync = mocker.patch('deltona.rclone.sync_once', side_effect=[None, KeyboardInterrupt])
    watch_and_sync(tmp_path, 'gdrive:D', idle=0.01, poll=0.01)
    assert mock_sync.call_count == 2


def test_watch_and_sync_debounces(mocker: MockerFixture, tmp_path: Path) -> None:
    observer = mocker.patch('deltona.rclone.Observer').return_value

    def schedule(handler: Any, path: str, *, recursive: bool = False) -> None:
        observer.start.side_effect = lambda: handler.on_any_event(mocker.MagicMock())

    observer.schedule.side_effect = schedule
    mock_sync = mocker.patch('deltona.rclone.sync_once', side_effect=KeyboardInterrupt)
    watch_and_sync(tmp_path, 'gdrive:D', idle=0.01, poll=30)
    mock_sync.assert_called_once_with(tmp_path, 'gdrive:D', ())
    observer.stop.assert_called_once()
