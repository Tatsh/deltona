from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
import re

from deltona.actions import RetryCandidate, RetryRule
from deltona.commands.git import (
    git_checkout_default_branch_main,
    git_open_main,
    git_rebase_default_branch_main,
    merge_dependabot_prs_main,
    merge_pre_commit_ci_prs_main,
    retry_gh_jobs_main,
)
from deltona.git import DependabotMergeError, PreCommitCIMergeError
from deltona.gmail import GmailAuthorizationError, GmailConfigurationError
import click
import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from click.testing import CliRunner
    from pytest_mock import MockerFixture

GOOGLE_CREDENTIALS_JSON = ('{"client_id": "id", "client_secret": "secret", "refresh_token": '
                           '"refresh", "type": "authorized_user"}')
CANDIDATE = RetryCandidate(attempt=1,
                           job='coverage',
                           repo='tatsh/deltona',
                           rule=RetryRule(step=re.compile(r'coveralls', re.IGNORECASE),
                                          error=re.compile(r'internal server error', re.IGNORECASE),
                                          reason='Coveralls returned a server error.'),
                           run_id=7,
                           step='Coveralls',
                           url='https://github.com/tatsh/deltona/actions/runs/7',
                           workflow='Tests')


def test_git_checkout_default_branch_success(mocker: MockerFixture, runner: CliRunner) -> None:
    mock_repo = mocker.patch('deltona.commands.git._get_git_repo')
    mocker.patch('keyring.get_password', return_value='dummy_token')
    mock_get_gh_default_branch = mocker.patch('deltona.commands.git.get_github_default_branch',
                                              new_callable=mocker.AsyncMock)
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
    mocker.patch('keyring.get_password', return_value=None)
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
    mocker.patch('keyring.get_password', return_value='dummy_token')
    mock_get_gh_default_branch = mocker.patch('deltona.commands.git.get_github_default_branch',
                                              new_callable=mocker.AsyncMock)
    mock_get_gh_default_branch.return_value = 'main'

    result = runner.invoke(git_rebase_default_branch_main, ['--remote'])
    assert result.exit_code == 0
    mock_get_gh_default_branch.assert_called_once()
    mock_repo.return_value.git.rebase.assert_called_once_with('origin/main')


def test_git_rebase_default_branch_no_token(mocker: MockerFixture, runner: CliRunner) -> None:
    mocker.patch('keyring.get_password', return_value=None)
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
    failure = DependabotMergeError({'tatsh/alpha': 2, 'tatsh/beta': 1})
    mock_merge = mocker.patch('deltona.commands.git.merge_dependabot_pull_requests',
                              new_callable=mocker.AsyncMock,
                              side_effect=[failure, None])
    mock_sleep = mocker.patch('deltona.commands.git.sleep')
    mocker.patch('keyring.get_password', return_value='dummy_token')

    result = runner.invoke(merge_dependabot_prs_main)
    assert result.exit_code == 0
    assert mock_merge.call_count == 2
    assert mock_sleep.call_count == 1
    assert 'Repositories with remaining Dependabot pull requests:' in result.output
    assert 'tatsh/alpha: 2 pull requests' in result.output
    assert 'tatsh/beta: 1 pull request' in result.output
    assert result.output.index('tatsh/alpha') < result.output.index('tatsh/beta')
    first_kwargs = mock_merge.call_args_list[0].kwargs
    second_kwargs = mock_merge.call_args_list[1].kwargs
    assert first_kwargs['repos'] is None
    assert second_kwargs['repos'] == ('tatsh/alpha', 'tatsh/beta')


def test_merge_dependabot_prs_main_retries_only_remaining_repos(mocker: MockerFixture,
                                                                runner: CliRunner) -> None:
    failure = DependabotMergeError({'tatsh/beta': 1})
    mock_merge = mocker.patch('deltona.commands.git.merge_dependabot_pull_requests',
                              new_callable=mocker.AsyncMock,
                              side_effect=[failure, None])
    mocker.patch('deltona.commands.git.sleep')
    mocker.patch('keyring.get_password', return_value='dummy_token')

    result = runner.invoke(merge_dependabot_prs_main,
                           ['-r', 'tatsh/alpha', '-r', 'tatsh/beta', '-r', 'tatsh/gamma'])
    assert result.exit_code == 0
    assert mock_merge.call_count == 2
    assert mock_merge.call_args_list[0].kwargs['repos'] == ('tatsh/alpha', 'tatsh/beta',
                                                            'tatsh/gamma')
    assert mock_merge.call_args_list[1].kwargs['repos'] == ('tatsh/beta',)


def test_merge_dependabot_prs_main_forwards_concurrency_options(mocker: MockerFixture,
                                                                runner: CliRunner) -> None:
    mock_merge = mocker.patch('deltona.commands.git.merge_dependabot_pull_requests',
                              new_callable=mocker.AsyncMock,
                              return_value=None)
    mocker.patch('keyring.get_password', return_value='dummy_token')

    result = runner.invoke(merge_dependabot_prs_main,
                           ['--concurrency', '7', '--max-concurrent-http-requests', '5'])
    assert result.exit_code == 0
    mock_merge.assert_called_once_with(archive_email=False,
                                       base_url=None,
                                       concurrency=7,
                                       email=None,
                                       mark_notifications_done=False,
                                       max_concurrent_http_requests=5,
                                       repos=None,
                                       token='dummy_token')


def test_merge_dependabot_prs_main_gmail_not_configured_aborts(mocker: MockerFixture,
                                                               runner: CliRunner) -> None:
    mocker.patch('deltona.commands.git.merge_dependabot_pull_requests',
                 new_callable=mocker.AsyncMock,
                 side_effect=GmailConfigurationError('No Google credentials are stored.'))
    mocker.patch('keyring.get_password', return_value='dummy_token')

    result = runner.invoke(merge_dependabot_prs_main, ['-A'])
    assert result.exit_code != 0
    assert 'No Google credentials are stored.' in result.output
    assert 'Google Cloud console' in result.output
    assert '--authorize-gmail' in result.output


def test_merge_dependabot_prs_main_lapsed_authorization_says_only_to_authorize_again(
        mocker: MockerFixture, runner: CliRunner) -> None:
    mocker.patch('deltona.commands.git.merge_dependabot_pull_requests',
                 new_callable=mocker.AsyncMock,
                 side_effect=GmailAuthorizationError('HTTP 400: Token has been expired.'))
    mocker.patch('keyring.get_password', return_value='dummy_token')

    result = runner.invoke(merge_dependabot_prs_main, ['-A', '-E', 'me@example.com'])
    assert result.exit_code != 0
    # The client is unchanged, so nothing in the Google Cloud console has to be touched and no
    # client secret has to be found again.
    assert 'Authorise again with' in result.output
    assert '--authorize-gmail --email me@example.com' in result.output
    assert '--client-secret' not in result.output
    assert 'Create an OAuth client ID' not in result.output


def test_merge_dependabot_prs_main_names_the_command_to_run(mocker: MockerFixture,
                                                            runner: CliRunner) -> None:
    mocker.patch('deltona.commands.git.merge_dependabot_pull_requests',
                 new_callable=mocker.AsyncMock,
                 side_effect=GmailAuthorizationError('HTTP 400.'))
    mocker.patch('keyring.get_password', return_value='dummy_token')

    result = runner.invoke(merge_dependabot_prs_main, ['-A', '-E', 'me@example.com'],
                           prog_name='merge-dependabot-prs')
    assert result.exit_code != 0
    # The whole command has to be shown, not just the options, since two commands share this help.
    assert 'merge-dependabot-prs --authorize-gmail --email me@example.com' in result.output


def test_merge_dependabot_prs_main_authorize_gmail(mocker: MockerFixture, runner: CliRunner,
                                                   tmp_path: Path) -> None:
    mock_authorize = mocker.patch('deltona.commands.git.authorize', return_value='{"stored": 1}')
    mock_set = mocker.patch('keyring.set_password')
    mock_merge = mocker.patch('deltona.commands.git.merge_dependabot_pull_requests',
                              new_callable=mocker.AsyncMock)
    client_secret = tmp_path / 'client_secret.json'
    client_secret.write_text('{"installed": {}}')

    result = runner.invoke(
        merge_dependabot_prs_main,
        ['--authorize-gmail', '--client-secret',
         str(client_secret), '-E', 'me@example.com'])
    assert result.exit_code == 0
    assert mock_authorize.call_args.args == ('{"installed": {}}',)
    # The URL is echoed rather than opened, so it is visible over SSH.
    assert mock_authorize.call_args.kwargs['notify'] is click.echo
    mock_set.assert_called_once_with('deltona:mpr:google', 'me@example.com', '{"stored": 1}')
    # The merge must not run when only authorising.
    mock_merge.assert_not_called()


def test_merge_dependabot_prs_main_authorize_gmail_requires_an_email(mocker: MockerFixture,
                                                                     runner: CliRunner) -> None:
    mock_authorize = mocker.patch('deltona.commands.git.authorize')

    result = runner.invoke(merge_dependabot_prs_main, ['--authorize-gmail'])
    assert result.exit_code != 0
    assert '--email' in result.output
    mock_authorize.assert_not_called()


def test_merge_dependabot_prs_main_authorize_gmail_reuses_the_stored_client(
        mocker: MockerFixture, runner: CliRunner) -> None:
    mock_authorize = mocker.patch('deltona.commands.git.authorize', return_value='{"new": 1}')
    mocker.patch('keyring.get_password', return_value=GOOGLE_CREDENTIALS_JSON)
    mock_set = mocker.patch('keyring.set_password')

    result = runner.invoke(merge_dependabot_prs_main, ['--authorize-gmail', '-E', 'me@example.com'])
    assert result.exit_code == 0
    # No --client-secret was passed, so the client stored beside the refresh token is reused and
    # nothing has to be downloaded from the Google Cloud console again.
    assert mock_authorize.call_args.args == (GOOGLE_CREDENTIALS_JSON,)
    mock_set.assert_called_once_with('deltona:mpr:google', 'me@example.com', '{"new": 1}')


def test_merge_dependabot_prs_main_authorize_gmail_without_a_stored_client(
        mocker: MockerFixture, runner: CliRunner) -> None:
    mock_authorize = mocker.patch('deltona.commands.git.authorize')
    mocker.patch('keyring.get_password', return_value=None)

    result = runner.invoke(merge_dependabot_prs_main, ['--authorize-gmail', '-E', 'me@example.com'])
    assert result.exit_code != 0
    assert '--client-secret is required' in result.output
    assert 'Google Cloud console' in result.output
    mock_authorize.assert_not_called()


def test_merge_dependabot_prs_main_authorize_gmail_reports_failure(mocker: MockerFixture,
                                                                   runner: CliRunner,
                                                                   tmp_path: Path) -> None:
    mocker.patch('deltona.commands.git.authorize',
                 side_effect=GmailConfigurationError('Google returned no refresh token.'))
    client_secret = tmp_path / 'client_secret.json'
    client_secret.write_text('{}')

    result = runner.invoke(
        merge_dependabot_prs_main,
        ['--authorize-gmail', '--client-secret',
         str(client_secret), '-E', 'me@example.com'])
    assert result.exit_code != 0
    assert 'Google returned no refresh token.' in result.output


@pytest.mark.parametrize('flag', ['-A', '--archive-email'])
def test_merge_dependabot_prs_main_forwards_archive_email(flag: str, mocker: MockerFixture,
                                                          runner: CliRunner) -> None:
    mock_merge = mocker.patch('deltona.commands.git.merge_dependabot_pull_requests',
                              new_callable=mocker.AsyncMock,
                              return_value=None)
    mocker.patch('keyring.get_password', return_value='dummy_token')

    result = runner.invoke(merge_dependabot_prs_main, [flag, '-E', 'me@example.com'])
    assert result.exit_code == 0
    assert mock_merge.call_args.kwargs['archive_email'] is True
    assert mock_merge.call_args.kwargs['email'] == 'me@example.com'


@pytest.mark.parametrize('flag', ['-A', '--archive-email'])
def test_merge_pre_commit_prs_main_forwards_archive_email(flag: str, mocker: MockerFixture,
                                                          runner: CliRunner) -> None:
    mock_merge = mocker.patch('deltona.commands.git.merge_pre_commit_ci_pull_requests',
                              new_callable=mocker.AsyncMock,
                              return_value=None)
    mocker.patch('keyring.get_password', return_value='dummy_token')

    result = runner.invoke(merge_pre_commit_ci_prs_main, [flag, '--email', 'me@example.com'])
    assert result.exit_code == 0
    assert mock_merge.call_args.kwargs['archive_email'] is True
    assert mock_merge.call_args.kwargs['email'] == 'me@example.com'


@pytest.mark.parametrize('flag', ['-N', '--mark-notifications-done'])
def test_merge_dependabot_prs_main_forwards_mark_notifications_done(flag: str,
                                                                    mocker: MockerFixture,
                                                                    runner: CliRunner) -> None:
    mock_merge = mocker.patch('deltona.commands.git.merge_dependabot_pull_requests',
                              new_callable=mocker.AsyncMock,
                              return_value=None)
    mocker.patch('keyring.get_password', return_value='dummy_token')

    result = runner.invoke(merge_dependabot_prs_main, [flag])
    assert result.exit_code == 0
    assert mock_merge.call_args.kwargs['mark_notifications_done'] is True


@pytest.mark.parametrize('flag', ['-N', '--mark-notifications-done'])
def test_merge_pre_commit_prs_main_forwards_mark_notifications_done(flag: str,
                                                                    mocker: MockerFixture,
                                                                    runner: CliRunner) -> None:
    mock_merge = mocker.patch('deltona.commands.git.merge_pre_commit_ci_pull_requests',
                              new_callable=mocker.AsyncMock,
                              return_value=None)
    mocker.patch('keyring.get_password', return_value='dummy_token')

    result = runner.invoke(merge_pre_commit_ci_prs_main, [flag])
    assert result.exit_code == 0
    assert mock_merge.call_args.kwargs['mark_notifications_done'] is True


def test_merge_dependabot_prs_main_forwards_repos(mocker: MockerFixture, runner: CliRunner) -> None:
    mock_merge = mocker.patch('deltona.commands.git.merge_dependabot_pull_requests',
                              new_callable=mocker.AsyncMock,
                              return_value=None)
    mocker.patch('keyring.get_password', return_value='dummy_token')

    result = runner.invoke(merge_dependabot_prs_main, ['--repo', 'mine', '-r', 'tatsh/other'])
    assert result.exit_code == 0
    _, kwargs = mock_merge.call_args
    assert kwargs['repos'] == ('mine', 'tatsh/other')


def test_merge_dependabot_prs_main_no_token(mocker: MockerFixture, runner: CliRunner) -> None:
    mocker.patch('keyring.get_password', return_value=None)
    mock_get_gh_default_branch = mocker.patch('deltona.commands.git.get_github_default_branch')

    result = runner.invoke(merge_dependabot_prs_main)
    assert result.exit_code != 0
    mock_get_gh_default_branch.assert_not_called()


def test_merge_pre_commit_ci_prs_main(mocker: MockerFixture, runner: CliRunner) -> None:
    failure = PreCommitCIMergeError({'tatsh/alpha': 2, 'tatsh/beta': 1})
    mock_merge = mocker.patch('deltona.commands.git.merge_pre_commit_ci_pull_requests',
                              new_callable=mocker.AsyncMock,
                              side_effect=[failure, None])
    mock_sleep = mocker.patch('deltona.commands.git.sleep')
    mocker.patch('keyring.get_password', return_value='dummy_token')

    result = runner.invoke(merge_pre_commit_ci_prs_main)
    assert result.exit_code == 0
    assert mock_merge.call_count == 2
    assert mock_sleep.call_count == 1
    assert 'Repositories with remaining pre-commit.ci pull requests:' in result.output
    assert 'tatsh/alpha: 2 pull requests' in result.output
    assert 'tatsh/beta: 1 pull request' in result.output
    assert mock_merge.call_args_list[0].kwargs['repos'] is None
    assert mock_merge.call_args_list[1].kwargs['repos'] == ('tatsh/alpha', 'tatsh/beta')


def test_merge_pre_commit_ci_prs_main_forwards_repos(mocker: MockerFixture,
                                                     runner: CliRunner) -> None:
    mock_merge = mocker.patch('deltona.commands.git.merge_pre_commit_ci_pull_requests',
                              new_callable=mocker.AsyncMock,
                              return_value=None)
    mocker.patch('keyring.get_password', return_value='dummy_token')

    result = runner.invoke(merge_pre_commit_ci_prs_main, ['--repo', 'mine', '-r', 'tatsh/other'])
    assert result.exit_code == 0
    _, kwargs = mock_merge.call_args
    assert kwargs['repos'] == ('mine', 'tatsh/other')


def test_merge_pre_commit_ci_prs_main_no_token(mocker: MockerFixture, runner: CliRunner) -> None:
    mocker.patch('keyring.get_password', return_value=None)
    result = runner.invoke(merge_pre_commit_ci_prs_main)
    assert result.exit_code != 0


def test_merge_pre_commit_ci_prs_main_gmail_not_configured_aborts(mocker: MockerFixture,
                                                                  runner: CliRunner) -> None:
    mocker.patch('deltona.commands.git.merge_pre_commit_ci_pull_requests',
                 new_callable=mocker.AsyncMock,
                 side_effect=GmailConfigurationError('No Google credentials are stored.'))
    mocker.patch('keyring.get_password', return_value='dummy_token')

    result = runner.invoke(merge_pre_commit_ci_prs_main, ['-A'])
    assert result.exit_code != 0
    assert 'No Google credentials are stored.' in result.output
    assert 'Google Cloud console' in result.output
    assert '--authorize-gmail' in result.output


def test_merge_pre_commit_ci_prs_main_lapsed_authorization_says_only_to_authorize_again(
        mocker: MockerFixture, runner: CliRunner) -> None:
    mocker.patch('deltona.commands.git.merge_pre_commit_ci_pull_requests',
                 new_callable=mocker.AsyncMock,
                 side_effect=GmailAuthorizationError('HTTP 400: Token has been expired.'))
    mocker.patch('keyring.get_password', return_value='dummy_token')

    result = runner.invoke(merge_pre_commit_ci_prs_main, ['-A', '-E', 'me@example.com'])
    assert result.exit_code != 0
    # The client is unchanged, so nothing in the Google Cloud console has to be touched and no
    # client secret has to be found again.
    assert 'Authorise again with' in result.output
    assert '--authorize-gmail --email me@example.com' in result.output
    assert '--client-secret' not in result.output
    assert 'Create an OAuth client ID' not in result.output


def test_merge_pre_commit_ci_prs_main_names_the_command_to_run(mocker: MockerFixture,
                                                               runner: CliRunner) -> None:
    mocker.patch('deltona.commands.git.merge_pre_commit_ci_pull_requests',
                 new_callable=mocker.AsyncMock,
                 side_effect=GmailAuthorizationError('HTTP 400.'))
    mocker.patch('keyring.get_password', return_value='dummy_token')

    result = runner.invoke(merge_pre_commit_ci_prs_main, ['-A', '-E', 'me@example.com'],
                           prog_name='merge-pre-commit-ci-prs')
    assert result.exit_code != 0
    # The whole command has to be shown, not just the options, since two commands share this help.
    assert 'merge-pre-commit-ci-prs --authorize-gmail --email me@example.com' in result.output


def test_merge_pre_commit_ci_prs_main_no_email_uses_a_placeholder_address(
        mocker: MockerFixture, runner: CliRunner) -> None:
    mocker.patch('deltona.commands.git.merge_pre_commit_ci_pull_requests',
                 new_callable=mocker.AsyncMock,
                 side_effect=GmailAuthorizationError('HTTP 401.'))
    mocker.patch('keyring.get_password', return_value='dummy_token')

    result = runner.invoke(merge_pre_commit_ci_prs_main, ['-A'],
                           prog_name='merge-pre-commit-ci-prs')
    assert result.exit_code != 0
    assert 'merge-pre-commit-ci-prs --authorize-gmail --email ADDRESS' in result.output


def test_merge_pre_commit_ci_prs_main_authorize_gmail(mocker: MockerFixture, runner: CliRunner,
                                                      tmp_path: Path) -> None:
    mock_authorize = mocker.patch('deltona.commands.git.authorize', return_value='{"stored": 1}')
    mock_set = mocker.patch('keyring.set_password')
    mock_merge = mocker.patch('deltona.commands.git.merge_pre_commit_ci_pull_requests',
                              new_callable=mocker.AsyncMock)
    client_secret = tmp_path / 'client_secret.json'
    client_secret.write_text('{"installed": {}}')

    result = runner.invoke(
        merge_pre_commit_ci_prs_main,
        ['--authorize-gmail', '--client-secret',
         str(client_secret), '-E', 'me@example.com'])
    assert result.exit_code == 0
    assert mock_authorize.call_args.args == ('{"installed": {}}',)
    # The URL is echoed rather than opened, so it is visible over SSH.
    assert mock_authorize.call_args.kwargs['notify'] is click.echo
    mock_set.assert_called_once_with('deltona:mpr:google', 'me@example.com', '{"stored": 1}')
    # The merge must not run when only authorising.
    mock_merge.assert_not_called()


def test_merge_pre_commit_ci_prs_main_authorize_gmail_requires_an_email(
        mocker: MockerFixture, runner: CliRunner) -> None:
    mock_authorize = mocker.patch('deltona.commands.git.authorize')

    result = runner.invoke(merge_pre_commit_ci_prs_main, ['--authorize-gmail'])
    assert result.exit_code != 0
    assert '--email' in result.output
    mock_authorize.assert_not_called()


def test_merge_pre_commit_ci_prs_main_authorize_gmail_reuses_the_stored_client(
        mocker: MockerFixture, runner: CliRunner) -> None:
    mock_authorize = mocker.patch('deltona.commands.git.authorize', return_value='{"new": 1}')
    mocker.patch('keyring.get_password', return_value=GOOGLE_CREDENTIALS_JSON)
    mock_set = mocker.patch('keyring.set_password')

    result = runner.invoke(merge_pre_commit_ci_prs_main,
                           ['--authorize-gmail', '-E', 'me@example.com'])
    assert result.exit_code == 0
    # No --client-secret was passed, so the client stored beside the refresh token is reused and
    # nothing has to be downloaded from the Google Cloud console again.
    assert mock_authorize.call_args.args == (GOOGLE_CREDENTIALS_JSON,)
    mock_set.assert_called_once_with('deltona:mpr:google', 'me@example.com', '{"new": 1}')


def test_merge_pre_commit_ci_prs_main_authorize_gmail_without_a_stored_client(
        mocker: MockerFixture, runner: CliRunner) -> None:
    mock_authorize = mocker.patch('deltona.commands.git.authorize')
    mocker.patch('keyring.get_password', return_value=None)

    result = runner.invoke(merge_pre_commit_ci_prs_main,
                           ['--authorize-gmail', '-E', 'me@example.com'])
    assert result.exit_code != 0
    assert '--client-secret is required' in result.output
    assert 'Google Cloud console' in result.output
    mock_authorize.assert_not_called()


def test_merge_pre_commit_ci_prs_main_authorize_gmail_reports_failure(mocker: MockerFixture,
                                                                      runner: CliRunner,
                                                                      tmp_path: Path) -> None:
    mocker.patch('deltona.commands.git.authorize',
                 side_effect=GmailConfigurationError('Google returned no refresh token.'))
    client_secret = tmp_path / 'client_secret.json'
    client_secret.write_text('{}')

    result = runner.invoke(
        merge_pre_commit_ci_prs_main,
        ['--authorize-gmail', '--client-secret',
         str(client_secret), '-E', 'me@example.com'])
    assert result.exit_code != 0
    assert 'Google returned no refresh token.' in result.output


def test_retry_gh_jobs_main_no_token(mocker: MockerFixture, runner: CliRunner) -> None:
    mocker.patch('keyring.get_password', return_value=None)

    result = runner.invoke(retry_gh_jobs_main, [])
    assert result.exit_code != 0
    assert 'No token.' in result.output


def test_retry_gh_jobs_main_nothing_to_do(mocker: MockerFixture, runner: CliRunner) -> None:
    mocker.patch('keyring.get_password', return_value='dummy_token')
    mocker.patch('deltona.commands.git.find_retryable_runs', return_value=[])
    mock_rerun = mocker.patch('deltona.commands.git.rerun_failed_jobs')

    result = runner.invoke(retry_gh_jobs_main, [])
    assert result.exit_code == 0
    assert 'No failed runs worth starting again.' in result.output
    mock_rerun.assert_not_called()


@pytest.mark.parametrize('args', [[], ['--yes'], ['-y']])
def test_retry_gh_jobs_main_starts_runs_by_default(mocker: MockerFixture, runner: CliRunner,
                                                   args: list[str]) -> None:
    mocker.patch('keyring.get_password', return_value='dummy_token')
    mocker.patch('deltona.commands.git.find_retryable_runs', return_value=[CANDIDATE])
    mock_rerun = mocker.patch('deltona.commands.git.rerun_failed_jobs', return_value=1)

    result = runner.invoke(retry_gh_jobs_main, args)
    assert result.exit_code == 0
    assert 'tatsh/deltona run 7' in result.output
    assert "step 'Coveralls'" in result.output
    assert 'Coveralls returned a server error.' in result.output
    assert 'Started 1 of 1 run again.' in result.output
    mock_rerun.assert_called_once()


@pytest.mark.parametrize('flag', ['--dry-run', '-n'])
def test_retry_gh_jobs_main_reports_without_acting_on_dry_run(mocker: MockerFixture,
                                                              runner: CliRunner, flag: str) -> None:
    mocker.patch('keyring.get_password', return_value='dummy_token')
    mocker.patch('deltona.commands.git.find_retryable_runs', return_value=[CANDIDATE])
    mock_rerun = mocker.patch('deltona.commands.git.rerun_failed_jobs')

    result = runner.invoke(retry_gh_jobs_main, [flag])
    assert result.exit_code == 0
    assert 'tatsh/deltona run 7' in result.output
    assert '1 run would be started again' in result.output
    assert '--dry-run' in result.output
    mock_rerun.assert_not_called()


def test_retry_gh_jobs_main_dry_run_wins_over_yes(mocker: MockerFixture, runner: CliRunner) -> None:
    mocker.patch('keyring.get_password', return_value='dummy_token')
    mocker.patch('deltona.commands.git.find_retryable_runs', return_value=[CANDIDATE])
    mock_rerun = mocker.patch('deltona.commands.git.rerun_failed_jobs')

    result = runner.invoke(retry_gh_jobs_main, ['--dry-run', '--yes'])
    assert result.exit_code == 0
    mock_rerun.assert_not_called()


def test_retry_gh_jobs_main_exits_non_zero_when_a_run_is_refused(mocker: MockerFixture,
                                                                 runner: CliRunner) -> None:
    mocker.patch('keyring.get_password', return_value='dummy_token')
    mocker.patch('deltona.commands.git.find_retryable_runs',
                 return_value=[CANDIDATE, CANDIDATE._replace(run_id=8)])
    mocker.patch('deltona.commands.git.rerun_failed_jobs', return_value=1)

    result = runner.invoke(retry_gh_jobs_main, [])
    assert result.exit_code == 1
    assert 'Started 1 of 2 runs again.' in result.output


def test_retry_gh_jobs_main_defaults_since_to_a_day_ago(mocker: MockerFixture,
                                                        runner: CliRunner) -> None:
    mocker.patch('keyring.get_password', return_value='dummy_token')
    mock_find = mocker.patch('deltona.commands.git.find_retryable_runs', return_value=[])

    assert runner.invoke(retry_gh_jobs_main, []).exit_code == 0
    since = mock_find.call_args.kwargs['since']
    assert since == (datetime.now(tz=UTC) - timedelta(days=1)).strftime('%Y-%m-%d')


def test_retry_gh_jobs_main_passes_since_through(mocker: MockerFixture, runner: CliRunner) -> None:
    mocker.patch('keyring.get_password', return_value='dummy_token')
    mock_find = mocker.patch('deltona.commands.git.find_retryable_runs', return_value=[])

    assert runner.invoke(retry_gh_jobs_main, ['--since', '2026-01-02']).exit_code == 0
    assert mock_find.call_args.kwargs['since'] == '2026-01-02'
