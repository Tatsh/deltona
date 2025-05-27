from __future__ import annotations

from typing import TYPE_CHECKING

from deltona.commands.git import (
    git_checkout_default_branch_main,
    git_open_main,
    git_rebase_default_branch_main,
    merge_dependabot_prs_main,
)

if TYPE_CHECKING:
    from click.testing import CliRunner
    from pytest_mock import MockerFixture


def test_git_checkout_default_branch_success(mocker: MockerFixture, runner: CliRunner) -> None:
    mock_repo = mocker.patch('deltona.commands.git._get_git_repo')
    mocker.patch('deltona.commands.git.keyring.get_password', return_value='dummy_token')
    mock_get_gh_default_branch = mocker.patch('deltona.commands.git.get_github_default_branch')
    mock_get_gh_default_branch.return_value = 'main'
    mock_checkout = mocker.Mock()
    mock_head = mocker.Mock(checkout=mock_checkout)
    mock_head.name = 'main'
    mock_repo.return_value.heads = [mock_head]

    result = runner.invoke(git_checkout_default_branch_main)
    assert result.exit_code == 0
    mock_get_gh_default_branch.assert_called_once()
    mock_checkout.assert_called_once()


def test_git_checkout_default_branch_no_token(mocker: MockerFixture, runner: CliRunner) -> None:
    mock_repo = mocker.patch('deltona.commands.git._get_git_repo')
    mocker.patch('deltona.commands.git.keyring.get_password', return_value=None)
    mock_get_gh_default_branch = mocker.patch('deltona.commands.git.get_github_default_branch')
    mock_checkout = mocker.Mock()
    mock_head = mocker.Mock(checkout=mock_checkout)
    mock_head.name = 'main'
    mock_repo.return_value.heads = [mock_head]

    result = runner.invoke(git_checkout_default_branch_main)
    assert result.exit_code != 0
    mock_get_gh_default_branch.assert_not_called()
    mock_checkout.assert_not_called()


def test_git_rebase_default_branch_success(mocker: MockerFixture, runner: CliRunner) -> None:
    mock_repo = mocker.patch('deltona.commands.git._get_git_repo')
    mocker.patch('deltona.commands.git.keyring.get_password', return_value='dummy_token')
    mock_get_gh_default_branch = mocker.patch('deltona.commands.git.get_github_default_branch')
    mock_get_gh_default_branch.return_value = 'main'

    result = runner.invoke(git_rebase_default_branch_main, ['--remote'])
    assert result.exit_code == 0
    mock_get_gh_default_branch.assert_called_once()
    mock_repo.return_value.git.rebase.assert_called_once_with('origin/main')


def test_git_rebase_default_branch_no_token(mocker: MockerFixture, runner: CliRunner) -> None:
    mocker.patch('deltona.commands.git.keyring.get_password', return_value=None)
    mock_get_gh_default_branch = mocker.patch('deltona.commands.git.get_github_default_branch')

    result = runner.invoke(git_rebase_default_branch_main)
    assert result.exit_code != 0
    mock_get_gh_default_branch.assert_not_called()


def test_git_open_main(mocker: MockerFixture, runner: CliRunner) -> None:
    mock_open = mocker.patch('deltona.commands.git.webbrowser.open')
    mock_repo = mocker.patch('deltona.commands.git._get_git_repo')
    mock_repo.return_value.remote.return_value.url = 'https://something'

    result = runner.invoke(git_open_main)
    assert result.exit_code == 0
    mock_open.assert_called_once_with('https://something')


def test_git_open_main_convert_ssh(mocker: MockerFixture, runner: CliRunner) -> None:
    mock_open = mocker.patch('deltona.commands.git.webbrowser.open')
    mock_repo = mocker.patch('deltona.commands.git._get_git_repo')
    mock_repo.return_value.remote.return_value.url = 'git@git.whatever.com:something.git'
    result = runner.invoke(git_open_main)
    assert result.exit_code == 0
    mock_open.assert_called_once_with('https://git.whatever.com/something')


def test_merge_dependabot_prs_main(mocker: MockerFixture, runner: CliRunner) -> None:
    mock_merge = mocker.patch('deltona.commands.git.merge_dependabot_pull_requests',
                              side_effect=[RuntimeError, None])
    mock_sleep = mocker.patch('deltona.commands.git.sleep')
    mocker.patch('deltona.commands.git.keyring.get_password', return_value='dummy_token')

    result = runner.invoke(merge_dependabot_prs_main)
    assert result.exit_code == 0
    assert mock_merge.call_count == 2
    assert mock_sleep.call_count == 1


def test_merge_dependabot_prs_main_no_token(mocker: MockerFixture, runner: CliRunner) -> None:
    mocker.patch('deltona.commands.git.keyring.get_password', return_value=None)
    mock_get_gh_default_branch = mocker.patch('deltona.commands.git.get_github_default_branch')

    result = runner.invoke(merge_dependabot_prs_main)
    assert result.exit_code != 0
    mock_get_gh_default_branch.assert_not_called()
