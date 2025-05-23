# ruff: noqa: FBT003, S108
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
import subprocess as sp

from deltona.ultraiso import (
    ULTRAISO_FONT_REPLACEMENT_MAX_LENGTH,
    InsufficientArguments,
    InvalidExec,
    get_ultraiso_path,
    patch_ultraiso_font,
    run_ultraiso,
    unix_path_to_wine,
)
import pytest

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def test_patch_ultraiso_font_success(mocker: MockerFixture, tmp_path: Path) -> None:
    exe_path = tmp_path / 'UltraISO.exe'
    backup_path = tmp_path / 'UltraISO.exebak'
    original_data = b'headerMS Sans Serif\x00footer'
    exe_path.write_bytes(original_data)
    mocker.patch('deltona.ultraiso.copyfile',
                 side_effect=lambda src, dst: Path(dst).write_bytes(Path(src).read_bytes()))
    patch_ultraiso_font(exe_path, font_name='Noto Sans')
    assert backup_path.exists()
    patched = exe_path.read_bytes()
    assert b'Noto Sans\x00' in patched
    assert b'MS Sans Serif\x00' not in patched


def test_patch_ultraiso_font_backup_exists(mocker: MockerFixture, tmp_path: Path) -> None:
    exe_path = tmp_path / 'UltraISO.exe'
    backup_path = tmp_path / 'UltraISO.exebak'
    original_data = b'headerMS Sans Serif\x00footer'
    exe_path.write_bytes(b'should not be used')
    backup_path.write_bytes(original_data)
    mocker.patch('deltona.ultraiso.copyfile')
    patch_ultraiso_font(exe_path, font_name='Noto Sans')
    assert exe_path.read_bytes().startswith(b'headerNoto Sans\x00')


def test_patch_ultraiso_font_font_too_long(mocker: MockerFixture, tmp_path: Path) -> None:
    exe_path = tmp_path / 'UltraISO.exe'
    exe_path.write_bytes(b'MS Sans Serif\x00')
    with pytest.raises(ValueError, match=r'Font name too long.') as e:
        patch_ultraiso_font(exe_path, font_name='A' * (ULTRAISO_FONT_REPLACEMENT_MAX_LENGTH + 1))
    assert 'Font name too long' in str(e.value)


def test_patch_ultraiso_font_file_not_found(mocker: MockerFixture, tmp_path: Path) -> None:
    exe_path = tmp_path / 'UltraISO.exe'
    with pytest.raises(FileNotFoundError):
        patch_ultraiso_font(exe_path, font_name='Noto Sans')


def test_patch_ultraiso_font_is_directory(mocker: MockerFixture, tmp_path: Path) -> None:
    exe_dir = tmp_path / 'UltraISO_dir'
    exe_dir.mkdir()
    with pytest.raises(IsADirectoryError):
        patch_ultraiso_font(exe_dir, font_name='Noto Sans')


def test_patch_ultraiso_font_backup_is_directory(mocker: MockerFixture, tmp_path: Path) -> None:
    exe_path = tmp_path / 'UltraISO.exe'
    exe_path.write_bytes(b'MS Sans Serif\x00')
    backup_dir = tmp_path / 'UltraISO.exebak'
    backup_dir.mkdir()
    with pytest.raises(IsADirectoryError):
        patch_ultraiso_font(exe_path, font_name='Noto Sans')


def test_patch_ultraiso_font_invalid_exec(mocker: MockerFixture, tmp_path: Path) -> None:
    exe_path = tmp_path / 'UltraISO.exe'
    exe_path.write_bytes(b'no font here')
    with pytest.raises(InvalidExec):
        patch_ultraiso_font(exe_path, font_name='Noto Sans')


def test_unix_path_to_wine_windows(mocker: MockerFixture) -> None:
    mocker.patch('deltona.ultraiso.IS_WINDOWS', True)
    assert unix_path_to_wine(r'C:\foo\bar') == r'C:\foo\bar'
    assert unix_path_to_wine('/unix/path') == '/unix/path'


def test_unix_path_to_wine_non_windows(mocker: MockerFixture) -> None:
    mocker.patch('deltona.ultraiso.IS_WINDOWS', False)
    mock_base = mocker.patch('deltona.ultraiso.base_unix_path_to_wine',
                             return_value='Z:\\unix\\path')
    result = unix_path_to_wine('/unix/path')
    mock_base.assert_called_once_with('/unix/path')
    assert result == 'Z:\\unix\\path'


def test_unix_path_to_wine_non_windows_str_path(mocker: MockerFixture) -> None:
    mocker.patch('deltona.ultraiso.IS_WINDOWS', False)
    mock_base = mocker.patch('deltona.ultraiso.base_unix_path_to_wine',
                             return_value='Z:\\unix\\path')
    result = unix_path_to_wine(Path('/unix/path'))
    mock_base.assert_called_once_with('/unix/path')
    assert result == 'Z:\\unix\\path'


def test_run_ultraiso_cmd_arg(mocker: MockerFixture, tmp_path: Path) -> None:
    exe_path = tmp_path / 'UltraISO.exe'
    exe_path.write_text('dummy')
    mocker.patch('deltona.ultraiso.get_ultraiso_path', return_value=exe_path)
    mocker.patch('deltona.ultraiso.IS_WINDOWS', False)
    mock_run = mocker.patch('deltona.ultraiso.sp.run')
    mocker.patch('deltona.ultraiso.base_unix_path_to_wine', side_effect=lambda x: f'Z:\\{x}')
    run_ultraiso(cmd='/tmp/cmd.txt', prefix=tmp_path)
    args = mock_run.call_args[0][0]
    assert 'wine' in args
    assert str(exe_path) in args
    assert '-cmd' in args
    assert 'Z:\\/tmp/cmd.txt' in args


def test_run_ultraiso_minimum_args(mocker: MockerFixture, tmp_path: Path) -> None:
    exe_path = tmp_path / 'UltraISO.exe'
    exe_path.write_text('dummy')
    mocker.patch('deltona.ultraiso.get_ultraiso_path', return_value=exe_path)
    mocker.patch('deltona.ultraiso.IS_WINDOWS', False)
    mock_run = mocker.patch('deltona.ultraiso.sp.run')
    mocker.patch('deltona.ultraiso.base_unix_path_to_wine', side_effect=lambda x: f'Z:\\{x}')
    run_ultraiso(input='/tmp/in.iso', output='/tmp/out.iso', prefix=tmp_path)
    args = mock_run.call_args[0][0]
    assert '-in' in args
    assert '-out' in args


def test_run_ultraiso_insufficient_args(mocker: MockerFixture, tmp_path: Path) -> None:
    exe_path = tmp_path / 'UltraISO.exe'
    exe_path.write_text('dummy')
    mocker.patch('deltona.ultraiso.get_ultraiso_path', return_value=exe_path)
    mocker.patch('deltona.ultraiso.IS_WINDOWS', False)
    with pytest.raises(InsufficientArguments):
        run_ultraiso(prefix=tmp_path)


def test_run_ultraiso_file_not_found(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.ultraiso.get_ultraiso_path', return_value=None)
    with pytest.raises(FileNotFoundError):
        run_ultraiso(cmd='/tmp/cmd.txt', prefix=tmp_path)


def test_run_ultraiso_all_options(mocker: MockerFixture, tmp_path: Path) -> None:
    exe_path = tmp_path / 'UltraISO.exe'
    exe_path.write_text('dummy')
    mocker.patch('deltona.ultraiso.get_ultraiso_path', return_value=exe_path)
    mocker.patch('deltona.ultraiso.IS_WINDOWS', False)
    mock_run = mocker.patch('deltona.ultraiso.sp.run')
    mocker.patch('deltona.ultraiso.base_unix_path_to_wine', side_effect=lambda x: f'Z:\\{x}')
    run_ultraiso(
        input='/tmp/in.iso',
        output='/tmp/out.iso',
        add_dirs=['/tmp/dir1'],
        add_files=['/tmp/file1'],
        appid='appid',
        preparer='prep',
        publisher='pub',
        sysid='sys',
        volset=1,
        volume='vol',
        ilong=True,
        imax=True,
        lowercase=True,
        vernum=True,
        hfs=True,
        jlong=True,
        joliet=True,
        rockridge=True,
        udf=True,
        udfdvd=True,
        bootfile='/tmp/boot.img',
        bootinfotable=True,
        optimize=True,
        chdir='chdir',
        newdir='newdir',
        rmdir='rmdir',
        ahide='ahide',
        hide='hide',
        pn=2,
        bin2iso='/tmp/bin2iso',
        dmg2iso='/tmp/dmg2iso',
        bin2isz='/tmp/bin2isz',
        compress=3,
        encrypt=2,
        password='pw',
        split=1024,
        extract='/tmp/extract',
        get='get',
        list_='/tmp/list',
        prefix=tmp_path,
    )
    args = ' '.join(mock_run.call_args[0][0])
    assert '-in' in args
    assert '-out' in args
    assert '-file' in args
    assert '-directory' in args
    assert '-appid' in args
    assert '-preparer' in args
    assert '-publisher' in args
    assert '-sysid' in args
    assert '-volset' in args
    assert '-volume' in args
    assert '-ilong' in args
    assert '-imax' in args
    assert '-lowercase' in args
    assert '-vernum' in args
    assert '-hfs' in args
    assert '-jlong' in args
    assert '-joliet' in args
    assert '-rockridge' in args
    assert '-udf' in args
    assert '-udfdvd' in args
    assert '-bootfile' in args
    assert '-bootinfotable' in args
    assert '-optimize' in args
    assert '-chdir' in args
    assert '-newdir' in args
    assert '-rmdir' in args
    assert '-ahide' in args
    assert '-hide' in args
    assert '-pn' in args
    assert '-bin2iso' in args
    assert '-dmg2iso' in args
    assert '-bin2isz' in args
    assert '-compress' in args
    assert '-encrypt' in args
    assert '-password' in args
    assert '-split' in args
    assert '-extract' in args
    assert '-get' in args
    assert '-list' in args


def test_run_ultraiso_windows_env(mocker: MockerFixture, tmp_path: Path) -> None:
    exe_path = tmp_path / 'UltraISO.exe'
    exe_path.write_text('dummy')
    mocker.patch('deltona.ultraiso.get_ultraiso_path', return_value=exe_path)
    mocker.patch('deltona.ultraiso.IS_WINDOWS', True)
    mock_run = mocker.patch('deltona.ultraiso.sp.run')
    run_ultraiso(input='C:\\in.iso', output='C:\\out.iso', prefix=tmp_path)
    args = mock_run.call_args[0][0]
    assert 'wine' not in args
    assert str(exe_path) in args
    assert '-in' in args
    assert '-out' in args


def test_run_ultraiso_called_process_error_with_stderr(mocker: MockerFixture,
                                                       tmp_path: Path) -> None:
    exe_path = tmp_path / 'UltraISO.exe'
    exe_path.write_text('dummy')
    mocker.patch('deltona.ultraiso.get_ultraiso_path', return_value=exe_path)
    mocker.patch('deltona.ultraiso.IS_WINDOWS', False)
    mocker.patch('deltona.ultraiso.base_unix_path_to_wine', side_effect=lambda x: f'Z:\\{x}')
    error = sp.CalledProcessError(1, ['wine'],
                                  stderr=('some error\nfixme: ignored\nwinemenubuilder.exe'
                                          '\nwine: using fast synchronization.\nreal error'))
    mocker.patch('deltona.ultraiso.sp.run', side_effect=error)
    mock_log = mocker.patch('deltona.ultraiso.log')
    with pytest.raises(sp.CalledProcessError):
        run_ultraiso(input='/tmp/in.iso', output='/tmp/out.iso', prefix=tmp_path)
    logged_lines = [
        call.args[1] for call in mock_log.exception.call_args_list if len(call.args) > 1
    ]
    assert any('some error' in line for line in logged_lines)
    assert any('real error' in line for line in logged_lines)
    assert not any('fixme:' in line for line in logged_lines)
    assert not any('winemenubuilder.exe' in line for line in logged_lines)
    assert not any('wine: using fast synchronization.' in line for line in logged_lines)


def test_run_ultraiso_called_process_error_with_empty_stderr(mocker: MockerFixture,
                                                             tmp_path: Path) -> None:
    exe_path = tmp_path / 'UltraISO.exe'
    exe_path.write_text('dummy')
    mocker.patch('deltona.ultraiso.get_ultraiso_path', return_value=exe_path)
    mocker.patch('deltona.ultraiso.IS_WINDOWS', False)
    mocker.patch('deltona.ultraiso.base_unix_path_to_wine', side_effect=lambda x: f'Z:\\{x}')
    error = sp.CalledProcessError(1, ['wine'], stderr=b'')
    mocker.patch('deltona.ultraiso.sp.run', side_effect=error)
    mock_log = mocker.patch('deltona.ultraiso.log')
    with pytest.raises(sp.CalledProcessError):
        run_ultraiso(input='/tmp/in.iso', output='/tmp/out.iso', prefix=tmp_path)
    assert not mock_log.exception.called


def test_run_ultraiso_warns_missing_display_xauthority(mocker: MockerFixture,
                                                       tmp_path: Path) -> None:
    exe_path = tmp_path / 'UltraISO.exe'
    exe_path.write_text('dummy')
    mocker.patch('deltona.ultraiso.get_ultraiso_path', return_value=exe_path)
    mocker.patch('deltona.ultraiso.IS_WINDOWS', False)
    mock_run = mocker.patch('deltona.ultraiso.sp.run')
    mocker.patch('deltona.ultraiso.base_unix_path_to_wine', side_effect=lambda x: f'Z:\\{x}')
    mock_environ: dict[str, str] = {'HOME': str(tmp_path)}
    mocker.patch('deltona.ultraiso.os.environ', mock_environ)
    mock_log = mocker.patch('deltona.ultraiso.log')
    run_ultraiso(input='/tmp/in.iso', output='/tmp/out.iso', prefix=tmp_path)
    assert mock_log.warning.called
    warning_msg = mock_log.warning.call_args[0][0]
    assert 'DISPLAY or XAUTHORITY' in warning_msg
    assert mock_run.called


def test_get_ultraiso_path_windows_found(mocker: MockerFixture) -> None:
    mocker.patch('deltona.ultraiso.IS_WINDOWS', True)
    mock_exists = mocker.patch('pathlib.Path.exists', side_effect=[True, False])
    result = get_ultraiso_path('C:/')
    assert result is not None
    assert 'UltraISO.exe' in str(result)
    assert mock_exists.call_count == 1


def test_get_ultraiso_path_windows_not_found(mocker: MockerFixture) -> None:
    mocker.patch('deltona.ultraiso.IS_WINDOWS', True)
    mocker.patch('pathlib.Path.exists', return_value=False)
    result = get_ultraiso_path('C:/')
    assert result is None


def test_get_ultraiso_path_non_windows_found(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.ultraiso.IS_WINDOWS', False)
    # Create fake UltraISO.exe in Program Files
    pf = tmp_path / 'drive_c' / 'Program Files'
    pf.mkdir(parents=True)
    exe = pf / 'UltraISO' / 'UltraISO.exe'
    exe.parent.mkdir(parents=True)
    exe.write_text('dummy')

    def exists_side_effect(self: Path) -> bool:
        return str(self) == str(exe)

    mocker.patch('pathlib.Path.exists', new=exists_side_effect)
    result = get_ultraiso_path(tmp_path)
    assert result == exe


def test_get_ultraiso_path_non_windows_not_found(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.ultraiso.IS_WINDOWS', False)
    mocker.patch('pathlib.Path.exists', return_value=False)
    result = get_ultraiso_path(tmp_path)
    assert result is None


def test_get_ultraiso_path_checks_both_program_files(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.ultraiso.IS_WINDOWS', False)
    pf86 = tmp_path / 'drive_c' / 'Program Files (x86)' / 'UltraISO'
    pf86.mkdir(parents=True)
    exe = pf86 / 'UltraISO.exe'
    exe.write_text('dummy')

    def exists_side_effect(self: Path) -> bool:
        return str(self) == str(exe)

    mocker.patch('pathlib.Path.exists', new=exists_side_effect)
    result = get_ultraiso_path(tmp_path)
    assert result == exe
