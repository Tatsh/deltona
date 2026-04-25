from __future__ import annotations

from typing import TYPE_CHECKING

from deltona.commands.main import main

if TYPE_CHECKING:
    from click.testing import CliRunner
    from pytest_mock import MockerFixture

_LINUX_ONLY_COMMANDS = ('clean-old-kernels-modules', 'connect-g603', 'inhibit-notifications',
                        'kill-gamescope', 'systemd-reset-tpm-cryptenroll', 'wait-for-disc')
_WINE_COMMANDS = ('kill-wine', 'set-wine-fonts', 'unregister-wine-assocs', 'winegoginstall',
                  'wineshell')


def test_main_help(runner: CliRunner) -> None:
    result = runner.invoke(main, ['--help'])
    assert result.exit_code == 0
    assert 'Deltona' in result.output


def test_main_list_commands(runner: CliRunner) -> None:
    result = runner.invoke(main, ['--help'])
    assert result.exit_code == 0
    for cmd_name in ('add-cdda-times', 'adp', 'slugify', 'urldecode'):
        assert cmd_name in result.output


def test_main_subcommand_help(runner: CliRunner) -> None:
    result = runner.invoke(main, ['add-cdda-times', '--help'])
    assert result.exit_code == 0
    assert 'CDDA' in result.output


def test_main_unknown_subcommand(runner: CliRunner) -> None:
    result = runner.invoke(main, ['no-such-command'])
    assert result.exit_code != 0


def test_main_subcommand_execution(runner: CliRunner) -> None:
    result = runner.invoke(main, ['add-cdda-times', '01:02:73', '02:05:09'])
    assert result.exit_code == 0
    assert '03:08:07' in result.output


def test_main_shows_all_commands_on_linux(runner: CliRunner, mocker: MockerFixture) -> None:
    mocker.patch('deltona.commands.main.sys.platform', 'linux')
    result = runner.invoke(main, ['--help'])
    assert result.exit_code == 0
    for cmd in (*_LINUX_ONLY_COMMANDS, *_WINE_COMMANDS):
        assert cmd in result.output


def test_main_hides_linux_only_on_darwin(runner: CliRunner, mocker: MockerFixture) -> None:
    mocker.patch('deltona.commands.main.sys.platform', 'darwin')
    result = runner.invoke(main, ['--help'])
    assert result.exit_code == 0
    for cmd in _LINUX_ONLY_COMMANDS:
        assert cmd not in result.output
    for cmd in _WINE_COMMANDS:
        assert cmd in result.output
    assert 'add-cdda-times' in result.output


def test_main_hides_not_windows_on_win32(runner: CliRunner, mocker: MockerFixture) -> None:
    mocker.patch('deltona.commands.main.sys.platform', 'win32')
    result = runner.invoke(main, ['--help'])
    assert result.exit_code == 0
    for cmd in (*_LINUX_ONLY_COMMANDS, *_WINE_COMMANDS):
        assert cmd not in result.output
    assert 'add-cdda-times' in result.output
