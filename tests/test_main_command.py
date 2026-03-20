from __future__ import annotations

from typing import TYPE_CHECKING

from deltona.commands.main import main

if TYPE_CHECKING:
    from click.testing import CliRunner


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
