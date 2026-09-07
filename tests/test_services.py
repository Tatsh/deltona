from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
import plistlib
import subprocess as sp

import pytest

from deltona.services import (
    default_service_kind,
    disable_service,
    enable_service,
    generate_service,
    install_service,
    launchd_label,
    service_path,
    uninstall_service,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.mark.parametrize(('platform', 'expected'), [('darwin', 'launchd'),
                                                    ('linux', 'systemd-user')])
def test_default_service_kind(mocker: MockerFixture, platform: str, expected: str) -> None:
    mocker.patch('deltona.services.sys.platform', platform)
    assert default_service_kind() == expected


@pytest.mark.parametrize(('name', 'expected'), [('x', 'sh.tat.deltona.x'),
                                                ('sh.tat.deltona.x', 'sh.tat.deltona.x')])
def test_launchd_label(name: str, expected: str) -> None:
    assert launchd_label(name) == expected


def test_service_path(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.services.Path.home', return_value=tmp_path)
    assert service_path('launchd', 'x') == tmp_path / 'Library/LaunchAgents/sh.tat.deltona.x.plist'
    assert service_path('systemd-user', 'x') == tmp_path / '.config/systemd/user/x.service'
    assert service_path('systemd-system', 'x') == Path('/etc/systemd/system/x.service')


def test_service_path_unknown_kind() -> None:
    assert service_path(cast('Any', 'nonsense'), 'x') is None


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


def test_generate_service_extra_lines() -> None:
    text = generate_service('systemd-user',
                            'x', ('/bin/thing',),
                            extra_service_lines=('KillSignal=SIGINT',))
    assert 'KillSignal=SIGINT' in text
    # Extra lines belong to the service rather than to how it is installed.
    assert text.index('KillSignal=SIGINT') < text.index('[Install]')


def test_generate_service_launchd() -> None:
    parsed: dict[str, Any] = plistlib.loads(
        generate_service('launchd', 'x', ('/bin/thing', '--flag'),
                         extra_service_lines=('ignored',)).encode())
    assert parsed['Label'] == 'sh.tat.deltona.x'
    assert parsed['ProgramArguments'] == ['/bin/thing', '--flag']
    assert parsed['KeepAlive'] is True
    assert parsed['RunAtLoad'] is True
    assert 'PATH' in parsed['EnvironmentVariables']


@pytest.mark.parametrize(('kind', 'expected'), [
    ('launchd', ('launchctl', 'bootstrap')),
    ('systemd-system', ('systemctl', 'restart', 'x')),
    ('systemd-user', ('systemctl', '--user', 'restart', 'x')),
])
def test_enable_service(mocker: MockerFixture, tmp_path: Path, kind: str,
                        expected: tuple[str, ...]) -> None:
    mocker.patch('deltona.services.Path.home', return_value=tmp_path)
    mock_run = mocker.patch('deltona.services.sp.run')
    enable_service(kind, 'x')  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    # A rewritten definition does not reach the process running the old one.
    assert mock_run.call_args.args[0][:len(expected)] == expected


def test_enable_service_launchd_replaces_loaded_job(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.services.Path.home', return_value=tmp_path)
    mock_run = mocker.patch('deltona.services.sp.run',
                            side_effect=[sp.CalledProcessError(1, 'launchctl'),
                                         mocker.MagicMock()])
    enable_service('launchd', 'x')
    # Nothing was loaded, so booting out failed, which is the wanted state rather than a failure.
    assert mock_run.call_args_list[0].args[0][1] == 'bootout'
    assert mock_run.call_args_list[-1].args[0][1] == 'bootstrap'


def test_enable_service_unknown_kind(mocker: MockerFixture) -> None:
    mock_run = mocker.patch('deltona.services.sp.run')
    enable_service(cast('Any', 'nonsense'), 'x')
    mock_run.assert_not_called()


def test_install_service(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.services.Path.home', return_value=tmp_path)
    mock_enable = mocker.patch('deltona.services.enable_service')
    path = install_service('systemd-user', 'x', ('/bin/thing',))
    assert path.read_text(encoding='utf-8').startswith('[Unit]')
    mock_enable.assert_called_once_with('systemd-user', 'x')


def test_install_service_overwrites_and_restarts(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.services.Path.home', return_value=tmp_path)
    mock_run = mocker.patch('deltona.services.sp.run')
    install_service('systemd-user', 'x', ('/bin/old',), enable=False)

    path = install_service('systemd-user', 'x', ('/bin/new',))
    text = path.read_text(encoding='utf-8')
    assert '/bin/new' in text
    # The definition is replaced rather than added to, and the running process is replaced with it.
    assert '/bin/old' not in text
    assert mock_run.call_args.args[0] == ('systemctl', '--user', 'restart', 'x')


def test_install_service_no_enable(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.services.Path.home', return_value=tmp_path)
    mock_enable = mocker.patch('deltona.services.enable_service')
    install_service('systemd-user', 'x', ('/bin/thing',), enable=False)
    mock_enable.assert_not_called()


@pytest.mark.parametrize(('kind', 'expected'), [
    ('launchd', ('launchctl', 'bootout')),
    ('systemd-system', ('systemctl', 'disable', '--now', 'x')),
    ('systemd-user', ('systemctl', '--user', 'disable', '--now', 'x')),
])
def test_disable_service(mocker: MockerFixture, kind: str, expected: tuple[str, ...]) -> None:
    mock_run = mocker.patch('deltona.services.sp.run')
    disable_service(kind, 'x')  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    assert mock_run.call_args.args[0][:len(expected)] == expected


def test_disable_service_not_loaded(mocker: MockerFixture) -> None:
    mocker.patch('deltona.services.sp.run', side_effect=sp.CalledProcessError(1, 'systemctl'))
    disable_service('systemd-user', 'x')


def test_disable_service_unknown_kind(mocker: MockerFixture) -> None:
    mocker.patch('deltona.services.sp.run')
    with pytest.raises(UnboundLocalError):
        disable_service(cast('Any', 'nonsense'), 'x')


def test_uninstall_service(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.services.Path.home', return_value=tmp_path)
    mocker.patch('deltona.services.enable_service')
    mock_run = mocker.patch('deltona.services.sp.run')
    path = install_service('systemd-user', 'x', ('/bin/thing',), enable=False)
    assert uninstall_service('systemd-user', 'x') == path
    assert not path.exists()
    assert mock_run.call_args.args[0] == ('systemctl', '--user', 'daemon-reload')


def test_uninstall_service_system(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.services._SYSTEMD_SYSTEM_PATH', tmp_path)
    mock_run = mocker.patch('deltona.services.sp.run')
    path = install_service('systemd-system', 'x', ('/bin/thing',), enable=False)
    assert uninstall_service('systemd-system', 'x') == path
    assert mock_run.call_args.args[0] == ('systemctl', 'daemon-reload')


def test_uninstall_service_missing(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.services.Path.home', return_value=tmp_path)
    mocker.patch('deltona.services.sp.run')
    assert uninstall_service('systemd-user', 'x') is None


def test_uninstall_service_launchd(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.services.Path.home', return_value=tmp_path)
    mock_run = mocker.patch('deltona.services.sp.run')
    path = service_path('launchd', 'x')
    path.parent.mkdir(parents=True)
    path.touch()
    assert uninstall_service('launchd', 'x') == path
    assert not path.exists()
    assert mock_run.call_count == 1
