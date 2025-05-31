# ruff: noqa: FBT003, S108
from __future__ import annotations

from typing import TYPE_CHECKING, Any
import subprocess as sp

from deltona.media import CD_FRAMES
from deltona.utils import (
    DataAdapter,
    add_cdda_times,
    create_wine_prefix,
    kill_processes_by_name,
    secure_move_path,
    unregister_wine_file_associations,
)
import pytest
import requests

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch
    from pytest_mock import MockerFixture


def test_add_cdda_times_none_or_empty() -> None:
    assert add_cdda_times(None) is None
    assert add_cdda_times([]) is None


def test_add_cdda_times_invalid_format() -> None:
    # Not matching MM:SS:FF
    assert add_cdda_times(['12:34']) is None
    assert add_cdda_times(['99:99:99']) is None
    assert add_cdda_times(['abc:def:ghi']) is None
    assert add_cdda_times(['12:34:']) is None


def test_add_cdda_times_valid_single() -> None:
    # 01:02:03 should be valid
    result = add_cdda_times(['01:02:03'])
    assert isinstance(result, str)
    assert result.count(':') == 2


def test_add_cdda_times_valid_multiple() -> None:
    result = add_cdda_times(['00:01:00', '00:01:00'])
    assert result.startswith('00:02:')  # type: ignore[union-attr]


def test_add_cdda_times_overflow_minutes() -> None:
    # Minutes > 99 should return None
    # Use a time that will sum to > 99 minutes
    times = ['99:59:74', '00:01:01']
    assert add_cdda_times(times) is None


def test_add_cdda_times_overflow_seconds() -> None:
    # Seconds > 59 should return None
    times = ['00:60:00']
    assert add_cdda_times(times) is None


def test_add_cdda_times_overflow_frames() -> None:
    # Frames > CD_FRAMES should return None
    times = [f'00:00:{CD_FRAMES + 1:02d}']
    assert add_cdda_times(times) is None


def test_add_cdda_times_exact_maximum() -> None:
    # Exactly at the maximum allowed
    times = ['99:59:74']
    result = add_cdda_times(times)
    assert isinstance(result, str)
    assert result.startswith('99:59:')


def test_add_cdda_times_leading_zeros() -> None:
    # Should handle leading zeros
    result = add_cdda_times(['00:00:01', '00:00:01'])
    assert result.startswith('00:00:')  # type: ignore[union-attr]


def test_create_wine_prefix_basic(mocker: MockerFixture) -> None:
    # Patch all subprocess calls and environment
    sp_run = mocker.patch('deltona.utils.sp.run')
    mocker.patch('deltona.utils.which', return_value=None)
    mocker.patch('deltona.utils.requests.get')
    mocker.patch('deltona.utils.xz.open')
    mocker.patch('deltona.utils.tarfile.TarFile')
    mocker.patch('deltona.utils.copyfile')
    mocker.patch('deltona.utils.platformdirs.user_config_path')
    mocker.patch('deltona.utils.sqlite3.connect')
    mock_path = mocker.patch('deltona.utils.Path')
    mock_path.home.return_value.__truediv__.return_value.__truediv__.return_value.exists.return_value = False  # noqa: E501
    mocker.patch('deltona.utils.rmtree')
    mocker.patch('deltona.utils.tempfile.gettempdir', return_value='/tmp')
    mocker.patch('deltona.utils.requests.get')
    mocker.patch('deltona.utils.xz.open')
    mocker.patch('deltona.utils.tarfile.TarFile')
    mocker.patch('deltona.utils.copyfile')
    mocker.patch('deltona.utils.struct.pack', return_value=b'\x00' * 92)
    mocker.patch('deltona.utils.IS_WINDOWS', False)
    mocker.patch.dict('deltona.utils.environ', {
        'PATH': '/bin',
        'DISPLAY': ':0',
        'XAUTHORITY': '/tmp/.Xauthority'
    },
                      clear=True)
    result = create_wine_prefix('test-prefix')
    assert result is not None
    assert sp_run.call_count > 0


def test_create_wine_prefix_raises_if_exists(mocker: MockerFixture) -> None:
    mock_path = mocker.patch('deltona.utils.Path')
    mock_path.home.return_value.__truediv__.return_value.__truediv__.return_value.exists.return_value = True  # noqa: E501
    with pytest.raises(FileExistsError):
        create_wine_prefix('already-exists')


def test_create_wine_prefix_with_tricks_and_winetricks(mocker: MockerFixture) -> None:
    sp_run = mocker.patch('deltona.utils.sp.run')
    mocker.patch('deltona.utils.which', return_value='/usr/bin/winetricks')
    mock_path = mocker.patch('deltona.utils.Path')
    mock_path.home.return_value.__truediv__.return_value.__truediv__.return_value.exists.return_value = False  # noqa: E501
    mocker.patch('deltona.utils.IS_WINDOWS', False)
    mocker.patch.dict('deltona.utils.environ', {
        'PATH': '/bin',
        'DISPLAY': ':0',
        'XAUTHORITY': '/tmp/.Xauthority'
    },
                      clear=True)
    create_wine_prefix('prefix2', tricks=['corefonts', 'win10'])
    assert any('/usr/bin/winetricks' in str(args[0]) for args in sp_run.call_args_list)


def test_create_wine_prefix_with_options(mocker: MockerFixture) -> None:
    sp_run = mocker.patch('deltona.utils.sp.run')
    mocker.patch('deltona.utils.which', return_value=None)
    mock_path = mocker.patch('deltona.utils.Path')
    mock_path.home.return_value.__truediv__.return_value.__truediv__.return_value.exists.return_value = False  # noqa: E501
    mocker.patch.dict('deltona.utils.environ', {
        'PATH': '/bin',
        'DISPLAY': ':0',
        'XAUTHORITY': '/tmp/.Xauthority'
    },
                      clear=True)
    create_wine_prefix('prefix3',
                       _32bit=True,
                       asio=True,
                       disable_explorer=True,
                       disable_services=True,
                       dpi=120,
                       dxva_vaapi=True,
                       dxvk_nvapi=False,
                       eax=True,
                       gtk=True,
                       no_associations=True,
                       no_gecko=True,
                       no_mono=True,
                       no_xdg=True,
                       noto_sans=True,
                       sandbox=True,
                       tmpfs=True,
                       tricks=['corefonts'],
                       vd='1024x768',
                       windows_version='7',
                       winrt_dark=True)
    assert sp_run.call_count > 5


def test_create_wine_prefix_handles_winetricks_failure(mocker: MockerFixture) -> None:
    sp_run = mocker.patch('deltona.utils.sp.run')
    mocker.patch('deltona.utils.which', return_value='/usr/bin/winetricks')
    mock_path = mocker.patch('deltona.utils.Path')
    mock_path.home.return_value.__truediv__.return_value.__truediv__.return_value.exists.return_value = False  # noqa: E501
    mocker.patch('deltona.utils.IS_WINDOWS', False)
    mocker.patch('deltona.utils.logging.getLogger', return_value=mocker.Mock())
    mocker.patch.dict('deltona.utils.environ', {
        'PATH': '/bin',
        'DISPLAY': ':0',
        'XAUTHORITY': '/tmp/.Xauthority'
    },
                      clear=True)

    def run_side_effect(*args: Any, **kwargs: Any) -> None:
        if args[0] == '/usr/bin/winetricks':
            raise sp.CalledProcessError(1, 'winetricks', '', '')

    sp_run.side_effect = run_side_effect
    create_wine_prefix('prefix4', tricks=['corefonts'])


def test_create_wine_prefix_dxvk_nvapi_true_no_q4wine_db(mocker: MockerFixture) -> None:
    sp_run = mocker.patch('deltona.utils.sp.run')
    mocker.patch('deltona.utils.which',
                 side_effect=lambda x: '/usr/bin/winetricks' if x == 'winetricks' else None)
    mock_get = mocker.patch('deltona.utils.requests.get')
    mocker.patch('deltona.utils.xz.open')
    mocker.patch('deltona.utils.tarfile.TarFile')
    mocker.patch('deltona.utils.copyfile')
    mocker.patch('deltona.utils.struct.pack', return_value=b'\x00' * 92)
    mocker.patch('deltona.utils.IS_WINDOWS', False)
    mocker.patch.dict('deltona.utils.environ', {
        'PATH': '/bin',
        'XAUTHORITY': '/tmp/.Xauthority'
    },
                      clear=True)
    mock_user_config_path = mocker.patch('deltona.utils.platformdirs.user_config_path')
    mock_db_path = mocker.Mock()
    mock_db_path.exists.return_value = False
    mock_user_config_path.return_value.__truediv__.return_value = mock_db_path
    mock_path = mocker.patch('deltona.utils.Path')
    prefix_root = mock_path.home.return_value.__truediv__.return_value.__truediv__.return_value
    prefix_root.exists.return_value = False
    mocker.patch('deltona.utils.rmtree')
    mocker.patch('deltona.utils.tempfile.gettempdir', return_value='/tmp')
    mock_get.return_value.content = b''
    mocker.patch('deltona.utils.xz.open')
    result = create_wine_prefix('dxvk-prefix', dxvk_nvapi=True)
    assert result is not None
    assert any('setup_vkd3d_proton.sh' in str(args[0]) for args in sp_run.call_args_list)


def test_create_wine_prefix_dxvk_nvapi_true_32bit(mocker: MockerFixture) -> None:
    sp_run = mocker.patch('deltona.utils.sp.run')
    mocker.patch('deltona.utils.which',
                 side_effect=lambda x: '/usr/bin/winetricks' if x == 'winetricks' else None)
    mock_get = mocker.patch('deltona.utils.requests.get')
    mocker.patch('deltona.utils.xz.open')
    mocker.patch('deltona.utils.tarfile.TarFile')
    mocker.patch('deltona.utils.copyfile')
    mocker.patch('deltona.utils.struct.pack', return_value=b'\x00' * 92)
    mocker.patch('deltona.utils.IS_WINDOWS', False)
    mocker.patch.dict('deltona.utils.environ', {
        'PATH': '/bin',
        'DISPLAY': ':0',
        'XAUTHORITY': '/tmp/.Xauthority'
    },
                      clear=True)
    mock_user_config_path = mocker.patch('deltona.utils.platformdirs.user_config_path')
    mock_db_path = mocker.Mock()
    mock_db_path.exists.return_value = False
    mock_user_config_path.return_value.__truediv__.return_value = mock_db_path
    mock_path = mocker.patch('deltona.utils.Path')
    prefix_root = mock_path.home.return_value.__truediv__.return_value.__truediv__.return_value
    prefix_root.exists.return_value = False
    mocker.patch('deltona.utils.rmtree')
    mocker.patch('deltona.utils.tempfile.gettempdir', return_value='/tmp')
    mock_get.return_value.content = b''
    mocker.patch('deltona.utils.xz.open')
    result = create_wine_prefix('dxvk-prefix-32', dxvk_nvapi=True, _32bit=True)
    assert result is not None
    assert any('setup_vkd3d_proton.sh' in str(args[0]) for args in sp_run.call_args_list)
    assert not any(
        isinstance(args[0], tuple) and args[0][0] == 'wine64' and 'NGXCore' in args[0]
        for args in sp_run.call_args_list)


def test_create_wine_prefix_asio_true_register_found(mocker: MockerFixture) -> None:
    sp_run = mocker.patch('deltona.utils.sp.run')
    mocker.patch('deltona.utils.which',
                 side_effect=lambda x: '/usr/bin/wineasio-register'
                 if x == 'wineasio-register' else None)
    mock_path = mocker.patch('deltona.utils.Path')
    prefix = mock_path.home.return_value.__truediv__.return_value.__truediv__.return_value
    prefix.exists.return_value = False
    mocker.patch.dict('deltona.utils.environ', {
        'PATH': '/bin',
        'DISPLAY': ':0',
        'XAUTHORITY': '/tmp/.Xauthority'
    },
                      clear=True)
    mocker.patch('deltona.utils.requests.get')
    mocker.patch('deltona.utils.xz.open')
    mocker.patch('deltona.utils.tarfile.TarFile')
    mocker.patch('deltona.utils.copyfile')
    mocker.patch('deltona.utils.platformdirs.user_config_path')
    mocker.patch('deltona.utils.sqlite3.connect')
    mocker.patch('deltona.utils.rmtree')
    mocker.patch('deltona.utils.tempfile.gettempdir', return_value='/tmp')
    mocker.patch('deltona.utils.struct.pack', return_value=b'\x00' * 92)
    result = create_wine_prefix('asio-prefix', asio=True)
    assert result is not None
    assert any(
        isinstance(args.args[0], tuple) and args.args[0][0] == '/usr/bin/wineasio-register'
        for args in sp_run.call_args_list)


def test_unregister_wine_file_associations_basic(mocker: MockerFixture) -> None:
    kill_wine_mock = mocker.patch('deltona.utils.kill_wine')
    mock_file1 = mocker.Mock()
    mock_file2 = mocker.Mock()
    mock_file3 = mocker.Mock()
    mock_file4 = mocker.Mock()
    mock_file5 = mocker.Mock()
    mock_file6 = mocker.Mock()
    mock_file7 = mocker.Mock()
    mock_file8 = mocker.Mock()
    mimeinfo_mock = mocker.Mock()
    mock_path = mocker.patch('deltona.utils.Path')
    mock_path.home.return_value.__truediv__.return_value = mimeinfo_mock
    mock_path.home.return_value.__truediv__.return_value.glob.side_effect = [
        [mock_file1, mock_file2],  # wine-extension-*.desktop
        [mock_file3, mock_file4],  # x-wine*
        [mock_file5, mock_file6],  # x-wine-extension*
    ]
    # application-x-wine-extension*
    mock_path.home.return_value.__truediv__.return_value.rglob.return_value = [
        mock_file7, mock_file8
    ]
    sp_run = mocker.patch('deltona.utils.sp.run')
    unregister_wine_file_associations()
    kill_wine_mock.assert_called_once()
    for _i, f in enumerate([
            mock_file1, mock_file2, mock_file3, mock_file4, mock_file5, mock_file6, mock_file7,
            mock_file8
    ],
                           start=1):
        f.unlink.assert_called()
    mimeinfo_mock.unlink.assert_called()
    assert sp_run.call_count >= 2


def test_unregister_wine_file_associations_debug_true(mocker: MockerFixture) -> None:
    kill_wine_mock = mocker.patch('deltona.utils.kill_wine')
    mocker.patch('deltona.utils.Path.glob', return_value=[])
    mocker.patch('deltona.utils.Path.rglob', return_value=[])
    mimeinfo_mock = mocker.Mock()
    mocker.patch('deltona.utils.Path', return_value=mimeinfo_mock)
    mimeinfo_mock.unlink = mocker.Mock()
    sp_run = mocker.patch('deltona.utils.sp.run')
    unregister_wine_file_associations(debug=True)
    called_args = [call[0][0] for call in sp_run.call_args_list]
    assert any('update-desktop-database' in str(args) for args in called_args)
    assert any('update-mime-database' in str(args) for args in called_args)
    kill_wine_mock.assert_called_once()


def test_secure_move_path_file_basic(mocker: MockerFixture) -> None:
    client = mocker.MagicMock()
    sftp = mocker.MagicMock()
    client.open_sftp.return_value.__enter__.return_value = sftp
    path_mock = mocker.patch('deltona.utils.Path')
    path_instance = path_mock.return_value
    path_instance.is_file.return_value = True
    path_instance.name = 'file.txt'
    path_instance.stat.return_value = mocker.Mock(st_atime=1.0, st_mtime=2.0)
    mocker.patch('deltona.utils.os.walk')
    client.exec_command.return_value = (None, mocker.Mock(read=lambda: b'/home/remote'), None)
    path_instance.unlink = mocker.Mock()
    secure_move_path(client, 'file.txt', '~/target')
    assert sftp.put.called
    assert path_instance.unlink.called


def test_secure_move_path_file_basic_preserve_stats(mocker: MockerFixture) -> None:
    client = mocker.MagicMock()
    sftp = mocker.MagicMock()
    client.open_sftp.return_value.__enter__.return_value = sftp
    path_mock = mocker.patch('deltona.utils.Path')
    path_instance = path_mock.return_value
    path_instance.is_file.return_value = True
    path_instance.name = 'file.txt'
    path_instance.stat.return_value = mocker.Mock(st_atime=1.0, st_mtime=2.0)
    mocker.patch('deltona.utils.os.walk')
    client.exec_command.return_value = (None, mocker.Mock(read=lambda: b'/home/remote'), None)
    path_instance.unlink = mocker.Mock()
    secure_move_path(client, 'file.txt', '~/target', preserve_stats=True)
    assert sftp.put.called
    assert sftp.utime.called
    assert path_instance.unlink.called


def test_secure_move_path_file_dry_run(mocker: MockerFixture) -> None:
    client = mocker.MagicMock()
    sftp = mocker.MagicMock()
    client.open_sftp.return_value.__enter__.return_value = sftp
    path_mock = mocker.patch('deltona.utils.Path')
    path_instance = path_mock.return_value
    path_instance.is_file.return_value = True
    path_instance.name = 'file.txt'
    path_instance.stat.return_value = mocker.Mock(st_atime=1.0, st_mtime=2.0)
    client.exec_command.return_value = (None, mocker.Mock(read=lambda: b'/home/remote'), None)
    path_instance.unlink = mocker.Mock()
    secure_move_path(client, 'file.txt', '~/target', dry_run=True)
    assert not sftp.put.called
    assert not path_instance.unlink.called


def test_secure_move_path_directory_basic(mocker: MockerFixture) -> None:
    client = mocker.MagicMock()
    sftp = mocker.MagicMock()
    client.open_sftp.return_value.__enter__.return_value = sftp
    path_mock = mocker.patch('deltona.utils.Path')
    path_instance = path_mock.return_value
    path_instance.is_file.return_value = False
    path_instance.name = 'dir'
    path_instance.stat.return_value = mocker.Mock(st_atime=1.0, st_mtime=2.0)
    client.exec_command.return_value = (None, mocker.Mock(read=lambda: b'/home/remote'), None)
    mocker.patch('deltona.utils.os.walk',
                 side_effect=[[('/src', ['subdir'], ['file1', 'file2'])],
                              [('/src', ['subdir'], [])]])
    sftp.stat.side_effect = FileNotFoundError
    sftp.mkdir = mocker.Mock()
    sftp.put = mocker.Mock()
    sftp.utime = mocker.Mock()
    sftp.remove = mocker.Mock()
    sftp.rmdir = mocker.Mock()
    mocker.patch('deltona.utils.Path', return_value=path_instance)
    secure_move_path(client, '/src', '~/target', preserve_stats=True)
    assert sftp.mkdir.called
    assert sftp.put.called
    assert sftp.utime.called


def test_secure_move_path_preserve_stats(mocker: MockerFixture) -> None:
    client = mocker.MagicMock()
    sftp = mocker.MagicMock()
    client.open_sftp.return_value.__enter__.return_value = sftp
    path_mock = mocker.patch('deltona.utils.Path')
    path_instance = path_mock.return_value
    path_instance.is_file.return_value = True
    path_instance.name = 'file.txt'
    path_instance.stat.return_value = mocker.Mock(st_atime=1.0, st_mtime=2.0)
    client.exec_command.return_value = (None, mocker.Mock(read=lambda: b'/home/remote'), None)
    sftp.utime = mocker.Mock()
    secure_move_path(client, 'file.txt', '~/target', preserve_stats=True)
    assert sftp.utime.called


def test_secure_move_path_write_into(mocker: MockerFixture) -> None:
    client = mocker.MagicMock()
    sftp = mocker.MagicMock()
    client.open_sftp.return_value.__enter__.return_value = sftp
    path_mock = mocker.patch('deltona.utils.Path')
    path_instance = path_mock.return_value
    path_instance.is_file.return_value = False
    path_instance.name = 'dir'
    path_instance.stat.return_value = mocker.Mock(st_atime=1.0, st_mtime=2.0)
    client.exec_command.return_value = (None, mocker.Mock(read=lambda: b'/home/remote'), None)
    mocker.patch('deltona.utils.os.walk', return_value=[('/src', [], ['file1'])])
    sftp.stat = mocker.Mock()
    secure_move_path(client, '/src', '~/target', write_into=True)
    assert sftp.stat.called


def test_secure_move_path_handles_file_not_found_on_stat(mocker: MockerFixture) -> None:
    client = mocker.MagicMock()
    sftp = mocker.MagicMock()
    client.open_sftp.return_value.__enter__.return_value = sftp
    path_mock = mocker.patch('deltona.utils.Path')
    path_instance = path_mock.return_value
    path_instance.is_file.return_value = False
    path_instance.name = 'dir'
    path_instance.stat.return_value = mocker.Mock(st_atime=1.0, st_mtime=2.0)
    client.exec_command.return_value = (None, mocker.Mock(read=lambda: b'/home/remote'), None)
    mocker.patch('deltona.utils.os.walk', return_value=[('/src', [], [])])
    sftp.stat.side_effect = FileNotFoundError
    sftp.mkdir = mocker.Mock()
    secure_move_path(client, '/src', '~/target')
    assert sftp.mkdir.called


def test_secure_move_path_file_dry_run_preserve_stats(mocker: MockerFixture) -> None:
    client = mocker.MagicMock()
    sftp = mocker.MagicMock()
    client.open_sftp.return_value.__enter__.return_value = sftp
    path_mock = mocker.patch('deltona.utils.Path')
    path_instance = path_mock.return_value
    path_instance.is_file.return_value = True
    path_instance.name = 'file.txt'
    path_instance.stat.return_value = mocker.Mock(st_atime=1.0, st_mtime=2.0)
    client.exec_command.return_value = (None, mocker.Mock(read=lambda: b'/home/remote'), None)
    path_instance.unlink = mocker.Mock()
    sftp.utime = mocker.Mock()
    secure_move_path(client, 'file.txt', '~/target', dry_run=True, preserve_stats=True)
    assert not sftp.put.called
    assert not path_instance.unlink.called
    assert not sftp.utime.called


def test_secure_move_path_dir_dry_run_preserve_stats(mocker: MockerFixture) -> None:
    client = mocker.MagicMock()
    sftp = mocker.MagicMock()
    client.open_sftp.return_value.__enter__.return_value = sftp
    path_mock = mocker.patch('deltona.utils.Path')
    path_instance = path_mock.return_value
    path_instance.is_file.return_value = False
    path_instance.name = 'dir'
    path_instance.stat.return_value = mocker.Mock(st_atime=1.0, st_mtime=2.0)
    client.exec_command.return_value = (None, mocker.Mock(read=lambda: b'/home/remote'), None)
    mocker.patch('deltona.utils.os.walk',
                 side_effect=[[('/src', ['subdir'], ['file1', 'file2'])],
                              [('/src', ['subdir'], [])]])
    sftp.stat.side_effect = FileNotFoundError
    sftp.mkdir = mocker.Mock()
    sftp.put = mocker.Mock()
    sftp.utime = mocker.Mock()
    sftp.remove = mocker.Mock()
    sftp.rmdir = mocker.Mock()
    mocker.patch('deltona.utils.Path', return_value=path_instance)
    secure_move_path(client, '/src', '~/target', dry_run=True, preserve_stats=True)
    assert not sftp.put.called
    assert not sftp.utime.called
    assert not sftp.remove.called
    assert not sftp.rmdir.called


def test_secure_move_path_dir_preserve_stats_alt(mocker: MockerFixture) -> None:
    client = mocker.MagicMock()
    sftp = mocker.MagicMock()
    client.open_sftp.return_value.__enter__.return_value = sftp
    path_mock = mocker.patch('deltona.utils.Path')
    path_instance = path_mock.return_value
    path_instance.is_file.return_value = False
    path_instance.name = 'dir'
    path_instance.stat.return_value = mocker.Mock(st_atime=1.0, st_mtime=2.0)
    client.exec_command.return_value = (None, mocker.Mock(read=lambda: b'/home/remote'), None)
    mocker.patch('deltona.utils.os.walk',
                 side_effect=[[('/src', ['subdir'], ['file1', 'file2'])],
                              [('/src', ['subdir'], [])]])
    sftp.stat.side_effect = FileNotFoundError
    sftp.mkdir = mocker.Mock()
    sftp.put = mocker.Mock()
    sftp.utime = mocker.Mock()
    sftp.remove = mocker.Mock()
    sftp.rmdir = mocker.Mock()
    mocker.patch('deltona.utils.Path', return_value=path_instance)
    secure_move_path(client, '/src', '~/target', preserve_stats=True, write_into=True)
    assert sftp.put.called
    assert sftp.utime.called
    assert not sftp.remove.called
    assert not sftp.rmdir.called


def test_secure_move_path_dir_preserve_stats_alt_dry_run(mocker: MockerFixture) -> None:
    client = mocker.MagicMock()
    sftp = mocker.MagicMock()
    client.open_sftp.return_value.__enter__.return_value = sftp
    path_mock = mocker.patch('deltona.utils.Path')
    path_instance = path_mock.return_value
    path_instance.is_file.return_value = False
    path_instance.name = 'dir'
    path_instance.stat.return_value = mocker.Mock(st_atime=1.0, st_mtime=2.0)
    client.exec_command.return_value = (None, mocker.Mock(read=lambda: b'/home/remote'), None)
    mocker.patch('deltona.utils.os.walk',
                 side_effect=[[('/src', ['subdir'], ['file1', 'file2'])],
                              [('/src', ['subdir'], [])]])
    sftp.stat.side_effect = FileNotFoundError
    sftp.mkdir = mocker.Mock()
    sftp.put = mocker.Mock()
    sftp.utime = mocker.Mock()
    sftp.remove = mocker.Mock()
    sftp.rmdir = mocker.Mock()
    mocker.patch('deltona.utils.Path', return_value=path_instance)
    secure_move_path(client, '/src', '~/target', preserve_stats=True, write_into=True, dry_run=True)
    assert not sftp.put.called
    assert not sftp.utime.called
    assert not sftp.remove.called
    assert not sftp.rmdir.called


def test_secure_move_path_dir_write_into_no_preserve_stats(mocker: MockerFixture) -> None:
    client = mocker.MagicMock()
    sftp = mocker.MagicMock()
    client.open_sftp.return_value.__enter__.return_value = sftp
    path_mock = mocker.patch('deltona.utils.Path')
    path_instance = path_mock.return_value
    path_instance.is_file.return_value = False
    path_instance.name = 'dir'
    path_instance.stat.return_value = mocker.Mock(st_atime=1.0, st_mtime=2.0)
    client.exec_command.return_value = (None, mocker.Mock(read=lambda: b'/home/remote'), None)
    mocker.patch('deltona.utils.os.walk',
                 side_effect=[[('/src', ['subdir'], ['file1', 'file2'])],
                              [('/src', ['subdir'], [])]])
    sftp.stat.side_effect = FileNotFoundError
    sftp.mkdir = mocker.Mock()
    sftp.put = mocker.Mock()
    sftp.utime = mocker.Mock()
    sftp.remove = mocker.Mock()
    sftp.rmdir = mocker.Mock()
    mocker.patch('deltona.utils.Path', return_value=path_instance)
    secure_move_path(client, '/src', '~/target', write_into=True)
    assert sftp.put.called
    assert not sftp.utime.called
    assert not sftp.remove.called
    assert not sftp.rmdir.called


def test_kill_processes_by_name_windows_basic(mocker: MockerFixture) -> None:
    mocker.patch('deltona.utils.IS_WINDOWS', True)
    run_mock = mocker.patch('deltona.utils.sp.run')
    result = kill_processes_by_name('notepad')
    run_mock.assert_any_call(('taskkill.exe', '/im', 'notepad.exe'),
                             check=False,
                             capture_output=True)
    assert result is None


def test_kill_processes_by_name_unix_basic(mocker: MockerFixture) -> None:
    mocker.patch('deltona.utils.IS_WINDOWS', False)
    run_mock = mocker.patch('deltona.utils.sp.run')
    result = kill_processes_by_name('bash')
    run_mock.assert_any_call(('killall', '-15', 'bash'), check=False, capture_output=True)
    assert result is None


def test_kill_processes_by_name_windows_with_wait_timeout(mocker: MockerFixture) -> None:
    mocker.patch('deltona.utils.IS_WINDOWS', True)
    run_mock = mocker.patch('deltona.utils.sp.run')
    run_mock.side_effect = [
        mocker.Mock(),  # taskkill
        mocker.Mock(
            stdout='"Image Name","PID"\n"notepad.exe","1234"\n"notepad.exe","5678"\n')  # tasklist
    ]
    sleep_mock = mocker.patch('deltona.utils.time.sleep')
    result = kill_processes_by_name('notepad', wait_timeout=0.1)
    assert result == [1234, 5678]
    sleep_mock.assert_called_once_with(0.1)


def test_kill_processes_by_name_unix_with_wait_timeout_and_force(mocker: MockerFixture) -> None:
    mocker.patch('deltona.utils.IS_WINDOWS', False)
    run_mock = mocker.patch('deltona.utils.sp.run')
    run_mock.side_effect = [
        mocker.Mock(),  # killall
        mocker.Mock(stdout='1234 bash\n5678 bash\n9999 other\n'),  # ps
        mocker.Mock(stdout='')  # kill -9
    ]
    sleep_mock = mocker.patch('deltona.utils.time.sleep')
    mocker.patch('deltona.utils.Path.name', new_callable=mocker.PropertyMock, return_value='bash')
    result = kill_processes_by_name('bash', wait_timeout=0.2, force=True)
    assert result == [1234, 5678, 9999]
    sleep_mock.assert_called_once_with(0.2)


def test_kill_processes_by_name_no_processes_left(mocker: MockerFixture,
                                                  monkeypatch: MonkeyPatch) -> None:
    mocker.patch('deltona.utils.IS_WINDOWS', True)
    run_mock = mocker.patch('deltona.utils.sp.run')
    run_mock.side_effect = [
        mocker.Mock(),  # taskkill
        mocker.Mock(stdout='"Image Name","PID"\n')  # tasklist
    ]
    sleep_mock = mocker.patch('deltona.utils.time.sleep')
    result = kill_processes_by_name('notepad', wait_timeout=0.1)
    assert result == []
    sleep_mock.assert_not_called()


def test_data_adapter_send_basic(mocker: MockerFixture) -> None:
    adapter = DataAdapter()
    session = requests.Session()
    session.mount('data:', adapter)
    req = requests.Request('GET', 'data:,HelloWorld').prepare()
    response = adapter.send(req)
    assert response.status_code == 200
    assert response.content == b',HelloWorld'


def test_data_adapter_send_with_stream_and_timeout(mocker: MockerFixture) -> None:
    adapter = DataAdapter()
    req = requests.Request('GET', 'data:,TestData').prepare()
    response = adapter.send(req, stream=True, timeout=5)
    assert response.status_code == 200
    assert response.content == b',TestData'


def test_data_adapter_send_with_cert_and_proxies(mocker: MockerFixture) -> None:
    adapter = DataAdapter()
    req = requests.Request('GET', 'data:,CertTest').prepare()
    response = adapter.send(req, cert='dummy', proxies={'http': 'proxy'})
    assert response.status_code == 200
    assert response.content == b',CertTest'


def test_data_adapter_send_assert_url_none(mocker: MockerFixture) -> None:
    adapter = DataAdapter()
    req = mocker.Mock()
    req.url = None
    with pytest.raises(AssertionError):
        adapter.send(req)


def test_data_adapter_close_noop(mocker: MockerFixture) -> None:
    adapter = DataAdapter()
    adapter.close()
