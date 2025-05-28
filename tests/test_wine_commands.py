from __future__ import annotations

from typing import TYPE_CHECKING
import subprocess as sp

from deltona.commands.wine import (
    kill_wine_main,
    mkwineprefix_main,
    patch_ultraiso_font_main,
    set_wine_fonts_main,
    unix2wine_main,
    unregister_wine_file_associations_main,
    winegoginstall_main,
    wineshell_main,
)
import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from click.testing import CliRunner
    from pytest_mock import MockerFixture


@pytest.fixture
def fake_prefix(tmp_path: Path) -> Path:
    return tmp_path / 'test-prefix'


def test_mkwineprefix_main_success(mocker: MockerFixture, runner: CliRunner,
                                   fake_prefix: Path) -> None:
    create_wine_prefix = mocker.patch('deltona.commands.wine.create_wine_prefix',
                                      return_value=str(fake_prefix))
    result = runner.invoke(mkwineprefix_main, ['test-prefix', '--dpi', '120'])
    assert result.exit_code == 0
    create_wine_prefix.assert_called_once()


def test_mkwineprefix_main_file_exists(mocker: MockerFixture, runner: CliRunner) -> None:
    mocker.patch('deltona.commands.wine.create_wine_prefix', side_effect=FileExistsError)
    result = runner.invoke(mkwineprefix_main, ['test-prefix'])
    assert result.exit_code != 0


def test_mkwineprefix_main_subprocess_error(mocker: MockerFixture, runner: CliRunner) -> None:
    mocker.Mock(stderr='err', stdout='out')
    mocker.patch('deltona.commands.wine.create_wine_prefix',
                 side_effect=sp.CalledProcessError(1, 'cmd', stderr='err', output='out'))
    result = runner.invoke(mkwineprefix_main, ['test-prefix'])
    assert result.exit_code != 0


def test_unregister_wine_file_associations_main(mocker: MockerFixture, runner: CliRunner) -> None:
    unregister = mocker.patch('deltona.commands.wine.unregister_wine_file_associations')
    result = runner.invoke(unregister_wine_file_associations_main, [])
    assert result.exit_code == 0
    unregister.assert_called_once()


def test_wineshell_main_success(mocker: MockerFixture, runner: CliRunner, tmp_path: Path) -> None:
    shell = '/bin/bash'
    mock_spawn = mocker.patch('deltona.commands.wine.pexpect.spawn')
    mock_spawn.return_value = mocker.Mock(status=0)
    mocker.patch('deltona.commands.wine.os.environ', {'SHELL': shell})
    prefix = tmp_path / 'prefix'
    prefix.mkdir()
    result = runner.invoke(wineshell_main, [str(prefix)])
    assert result.exit_code == 0


def test_wineshell_main_fail(mocker: MockerFixture, runner: CliRunner, tmp_path: Path) -> None:
    shell = '/bin/bash'
    mock_spawn = mocker.patch('deltona.commands.wine.pexpect.spawn')
    mock_spawn.return_value = mocker.Mock(status=1)
    mocker.patch('deltona.commands.wine.os.environ', {'SHELL': shell})
    prefix = tmp_path / 'prefix'
    prefix.mkdir()
    result = runner.invoke(wineshell_main, [str(prefix)])
    assert result.exit_code != 0


def test_unix2wine_main(mocker: MockerFixture, runner: CliRunner) -> None:
    unix_path_to_wine = mocker.patch('deltona.commands.wine.unix_path_to_wine',
                                     return_value=r'C:\foo\bar')
    result = runner.invoke(unix2wine_main, ['/foo/bar'])
    assert result.exit_code == 0
    unix_path_to_wine.assert_called_once_with('/foo/bar')
    assert r'C:\foo\bar' in result.output


def test_winegoginstall_main_success(mocker: MockerFixture, runner: CliRunner,
                                     tmp_path: Path) -> None:
    file = tmp_path / 'setup.exe'
    file.write_text('dummy')
    sp_run = mocker.patch('deltona.commands.wine.sp.run')
    result = runner.invoke(winegoginstall_main, [str(file)])
    assert result.exit_code == 0
    sp_run.assert_called_once()


def test_winegoginstall_main_logs_warning_about_missing_env_vars(mocker: MockerFixture,
                                                                 runner: CliRunner,
                                                                 tmp_path: Path) -> None:
    mock_log_warning = mocker.patch('deltona.commands.wine.log.warning')
    mocker.patch('deltona.commands.wine.os.environ', {
        'HOME': str(tmp_path),
        'PATH': '',
    })
    file = tmp_path / 'setup.exe'
    file.write_text('dummy')
    sp_run = mocker.patch('deltona.commands.wine.sp.run')
    result = runner.invoke(winegoginstall_main, [str(file)])
    assert result.exit_code == 0
    sp_run.assert_called_once()
    mock_log_warning.assert_called_once_with(
        'Wine will likely fail to run since DISPLAY or XAUTHORITY are not in the environment.')


def test_winegoginstall_main_with_prefix(mocker: MockerFixture, runner: CliRunner,
                                         tmp_path: Path) -> None:
    file = tmp_path / 'setup.exe'
    file.write_text('dummy')
    prefix = tmp_path / 'a-prefix'
    prefix.mkdir()
    sp_run = mocker.patch('deltona.commands.wine.sp.run')
    result = runner.invoke(winegoginstall_main, ['-p', str(prefix), str(file)])
    assert result.exit_code == 0
    sp_run.assert_called_once()
    assert sp_run.call_args_list[0].kwargs['env']['WINEPREFIX'] == str(prefix)


def test_winegoginstall_main_subprocess_error(mocker: MockerFixture, runner: CliRunner,
                                              tmp_path: Path) -> None:
    file = tmp_path / 'setup.exe'
    file.write_text('dummy')
    mocker.patch('deltona.commands.wine.sp.run',
                 side_effect=sp.CalledProcessError(1, 'cmd', stderr='err', output='out'))
    result = runner.invoke(winegoginstall_main, [str(file)])
    assert result.exit_code != 0


def test_set_wine_fonts_main(mocker: MockerFixture, runner: CliRunner, tmp_path: Path) -> None:
    sp_run = mocker.patch('deltona.commands.wine.sp.run')
    mocker.patch('deltona.commands.wine.make_font_entry', return_value='FontEntry')
    mocker.patch('deltona.commands.wine.Field', ['foo'])
    mocker.patch('deltona.commands.wine.os.environ', {
        'HOME': str(tmp_path),
        'DISPLAY': 'x',
        'XAUTHORITY': 'y',
        'PATH': '',
        'WINEPREFIX': 'a-prefix'
    })
    result = runner.invoke(set_wine_fonts_main,
                           ['--dpi', '120', '--font', 'Arial', '--font-size', '10'])
    assert result.exit_code == 0
    sp_run.assert_called_once()


def test_set_wine_fonts_main_logs_warning_about_missing_env_vars(mocker: MockerFixture,
                                                                 runner: CliRunner,
                                                                 tmp_path: Path) -> None:
    sp_run = mocker.patch('deltona.commands.wine.sp.run')
    mock_log_warning = mocker.patch('deltona.commands.wine.log.warning')
    mocker.patch('deltona.commands.wine.make_font_entry', return_value='FontEntry')
    mocker.patch('deltona.commands.wine.Field', ['foo'])
    mocker.patch('deltona.commands.wine.os.environ', {
        'HOME': str(tmp_path),
        'PATH': '',
    })
    result = runner.invoke(set_wine_fonts_main,
                           ['--dpi', '120', '--font', 'Arial', '--font-size', '10'])
    assert result.exit_code == 0
    sp_run.assert_called_once()
    mock_log_warning.assert_called_once_with(
        'UltraISO.exe will likely fail to run since DISPLAY or XAUTHORITY are not in the '
        'environment.')


def test_patch_ultraiso_font_main_with_exe(mocker: MockerFixture, runner: CliRunner,
                                           tmp_path: Path) -> None:
    mocker.patch('deltona.commands.wine.IS_WINDOWS', False)  # noqa: FBT003
    exe = tmp_path / 'UltraISO.exe'
    exe.write_text('dummy')
    patch_ultraiso_font = mocker.patch('deltona.commands.wine.patch_ultraiso_font')
    result = runner.invoke(patch_ultraiso_font_main, ['--exe', str(exe), '--font', 'Arial'])
    assert result.exit_code == 0
    patch_ultraiso_font.assert_called_once_with(exe, 'Arial')


def test_patch_ultraiso_font_main_windows_no_exe(mocker: MockerFixture, runner: CliRunner,
                                                 tmp_path: Path) -> None:
    mocker.patch('deltona.commands.wine.IS_WINDOWS', True)  # noqa: FBT003
    patch_ultraiso_font = mocker.patch('deltona.commands.wine.patch_ultraiso_font')
    result = runner.invoke(patch_ultraiso_font_main, ['--font', 'Arial'])
    assert result.exit_code == 0
    patch_ultraiso_font.assert_called_once_with(mocker.ANY, 'Arial')


def test_patch_ultraiso_font_main_without_exe(mocker: MockerFixture, runner: CliRunner,
                                              tmp_path: Path) -> None:
    patch_ultraiso_font = mocker.patch('deltona.commands.wine.patch_ultraiso_font')
    mocker.patch('deltona.commands.wine.IS_WINDOWS', False)  # noqa: FBT003
    mocker.patch('os.environ', {'WINEPREFIX': str(tmp_path)})
    result = runner.invoke(patch_ultraiso_font_main, ['--font', 'Arial'])
    assert result.exit_code == 0
    assert patch_ultraiso_font.called


def test_kill_wine_main(mocker: MockerFixture, runner: CliRunner) -> None:
    kill_wine = mocker.patch('deltona.commands.wine.kill_wine')
    result = runner.invoke(kill_wine_main, [])
    assert result.exit_code == 0
    kill_wine.assert_called_once()
