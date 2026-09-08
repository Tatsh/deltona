from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
import json
import logging

import keyring.errors
import pytest

from deltona.git import (
    DEPENDABOT_LOGIN,
    DependabotMergeError,
    PreCommitCIMergeError,
    convert_git_ssh_url_to_https,
    get_github_default_branch,
    github_token,
    merge_dependabot_pull_requests,
    merge_pre_commit_ci_pull_requests,
    store_token,
    stored_token,
    token_path,
    watch_and_merge,
)
from deltona.gmail import GmailConfigurationError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Any

    from pytest_mock import MockerFixture

    from tests.conftest import FakeGitHub


class _StopWatching(Exception):
    """Ends the watch loop from inside a patched sleep."""


CREDENTIALS_JSON = ('{"client_id": "id", "client_secret": "secret", "refresh_token": "refresh", '
                    '"type": "authorized_user"}')


def test_convert_git_ssh_url_to_https() -> None:
    assert (convert_git_ssh_url_to_https('git@github.com:user/repo.git') ==
            'https://github.com/user/repo')
    assert (convert_git_ssh_url_to_https('ssh://git@github.com:user/repo.git') ==
            'https://github.com/user/repo')
    assert (convert_git_ssh_url_to_https('https://github.com/user/repo.git') ==
            'https://github.com/user/repo')


@pytest.mark.asyncio
async def test_get_github_default_branch(fake_github: FakeGitHub, mocker: MockerFixture) -> None:
    fake_github.add_repo('user/repo', listed=False, default_branch='main')
    repo = mocker.Mock()
    repo.remote.return_value.url = 'git@github.com:user/repo.git'
    result = await get_github_default_branch(repo=repo, token='fake_token')
    assert result == 'main'
    assert fake_github.repo_gets == ['user/repo']


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_success(fake_github: FakeGitHub) -> None:
    fake_github.add_repo('tatsh/repo', security_status='enabled')
    fake_github.add_pull('tatsh/repo', 1)
    await merge_dependabot_pull_requests(token='fake_token')
    assert fake_github.merge_calls == [('tatsh/repo', 1, {'merge_method': 'rebase'})]


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_success_get_pull_fails(
        fake_github: FakeGitHub) -> None:
    fake_github.add_repo('tatsh/repo', security_status='enabled')
    fake_github.add_pull('tatsh/repo', 1, get_error=400)
    with pytest.raises(DependabotMergeError):
        await merge_dependabot_pull_requests(token='fake_token')
    assert fake_github.posted_comments == []
    assert fake_github.merge_calls == []


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_success_alt(fake_github: FakeGitHub) -> None:
    fake_github.add_repo('tatsh/repo',
                         security_status='not enabled',
                         files={'.github/dependabot.yml'})
    fake_github.add_pull('tatsh/repo', 1)
    await merge_dependabot_pull_requests(token='fake_token')
    assert fake_github.merge_calls == [('tatsh/repo', 1, {'merge_method': 'rebase'})]


@pytest.mark.parametrize('path', ['.github/dependabot.yml', '.github/dependabot.yaml'])
@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_config_without_security_and_analysis(
        fake_github: FakeGitHub, path: str) -> None:
    fake_github.add_repo('tatsh/repo', security_status=None, files={path})
    fake_github.add_pull('tatsh/repo', 1)
    await merge_dependabot_pull_requests(token='fake_token')
    assert fake_github.merge_calls == [('tatsh/repo', 1, {'merge_method': 'rebase'})]


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_marks_notification_done(
        fake_github: FakeGitHub) -> None:
    fake_github.add_repo('tatsh/repo', security_status='enabled')
    fake_github.add_pull('tatsh/repo', 1)
    fake_github.add_notification('tatsh/repo', 1, thread_id='4321')
    await merge_dependabot_pull_requests(token='fake_token', mark_notifications_done=True)
    assert fake_github.threads_marked_done == ['4321']


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_does_not_mark_notification_done_by_default(
        fake_github: FakeGitHub) -> None:
    fake_github.add_repo('tatsh/repo', security_status='enabled')
    fake_github.add_pull('tatsh/repo', 1)
    fake_github.add_notification('tatsh/repo', 1, thread_id='4321')
    await merge_dependabot_pull_requests(token='fake_token')
    assert fake_github.threads_marked_done == []
    assert not any(path == '/notifications' for _, path in fake_github.requests)


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_ignores_non_pull_request_notifications(
        fake_github: FakeGitHub) -> None:
    fake_github.add_repo('tatsh/repo', security_status='enabled')
    fake_github.add_pull('tatsh/repo', 1)
    fake_github.add_notification('tatsh/repo', 1, subject_type='Issue', thread_id='4321')
    await merge_dependabot_pull_requests(token='fake_token', mark_notifications_done=True)
    assert fake_github.threads_marked_done == []


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_ignores_notification_without_a_number(
        fake_github: FakeGitHub) -> None:
    fake_github.add_repo('tatsh/repo', security_status='enabled')
    fake_github.add_pull('tatsh/repo', 1)
    fake_github.add_notification('tatsh/repo',
                                 1,
                                 subject_url='https://api.github.com/repos/tatsh/repo/pulls',
                                 thread_id='4321')
    await merge_dependabot_pull_requests(token='fake_token', mark_notifications_done=True)
    assert fake_github.merge_calls == [('tatsh/repo', 1, {'merge_method': 'rebase'})]
    assert fake_github.threads_marked_done == []


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_archives_email_token_failure(
        caplog: pytest.LogCaptureFixture, fake_github: FakeGitHub, mocker: MockerFixture) -> None:
    mocker.patch('keyring.get_password', return_value=CREDENTIALS_JSON)
    fake_github.add_repo('tatsh/repo', security_status='enabled')
    fake_github.add_pull('tatsh/repo', 1)
    fake_github.gmail.thread_ids = ['t1']
    fake_github.gmail.token_status = 400
    fake_github.gmail.token_payload = {'error': 'invalid_grant'}
    with pytest.raises(GmailConfigurationError, match='HTTP 400'):
        await merge_dependabot_pull_requests(token='fake_token', archive_email=True)
    assert fake_github.gmail.archived_threads == []


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_notification_failure_does_not_fail_merge(
        caplog: pytest.LogCaptureFixture, fake_github: FakeGitHub) -> None:
    fake_github.add_repo('tatsh/repo', security_status='enabled')
    fake_github.add_pull('tatsh/repo', 1)
    fake_github.add_notification('tatsh/repo', 1, thread_id='4321')
    fake_github.thread_delete_error = 500
    with caplog.at_level(logging.WARNING, logger='deltona.git'):
        await merge_dependabot_pull_requests(token='fake_token', mark_notifications_done=True)
    assert fake_github.merge_calls == [('tatsh/repo', 1, {'merge_method': 'rebase'})]
    assert any('as done' in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_merge_pre_commit_ci_pull_requests_marks_notification_done(
        fake_github: FakeGitHub) -> None:
    fake_github.add_repo('tatsh/repo', files={'.pre-commit-config.yaml'})
    fake_github.add_pull('tatsh/repo', 7, user_login='pre-commit-ci[bot]')
    fake_github.add_notification('tatsh/repo', 7, thread_id='99')
    await merge_pre_commit_ci_pull_requests(token='fake_token', mark_notifications_done=True)
    assert fake_github.threads_marked_done == ['99']


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_archives_email(fake_github: FakeGitHub,
                                                             mocker: MockerFixture) -> None:
    mocker.patch('keyring.get_password', return_value=CREDENTIALS_JSON)
    fake_github.add_repo('tatsh/repo', security_status='enabled')
    fake_github.add_pull('tatsh/repo', 478)
    fake_github.gmail.thread_ids = ['t1']
    await merge_dependabot_pull_requests(token='fake_token', archive_email=True)
    assert fake_github.gmail.archived_threads == ['t1']
    assert fake_github.gmail.queries == ['list:repo.tatsh.github.com subject:"(PR #478)"']


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_archives_email_uses_explicit_address(
        fake_github: FakeGitHub, mocker: MockerFixture) -> None:
    get_password = mocker.patch('keyring.get_password', return_value=CREDENTIALS_JSON)
    fake_github.add_repo('tatsh/repo', security_status='enabled')
    fake_github.add_pull('tatsh/repo', 1)
    fake_github.gmail.thread_ids = ['t1']
    await merge_dependabot_pull_requests(token='fake_token',
                                         archive_email=True,
                                         email='other@example.com')
    get_password.assert_called_once_with('deltona:mpr:google', 'other@example.com')
    assert not fake_github.user_endpoint_hit


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_archives_email_falls_back_to_github_address(
        fake_github: FakeGitHub, mocker: MockerFixture) -> None:
    get_password = mocker.patch('keyring.get_password', return_value=CREDENTIALS_JSON)
    fake_github.add_repo('tatsh/repo', security_status='enabled')
    fake_github.add_pull('tatsh/repo', 1)
    await merge_dependabot_pull_requests(token='fake_token', archive_email=True)
    get_password.assert_called_once_with('deltona:mpr:google', 'tatsh@example.com')


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_does_not_archive_email_by_default(
        fake_github: FakeGitHub, mocker: MockerFixture) -> None:
    mocker.patch('keyring.get_password', return_value=CREDENTIALS_JSON)
    fake_github.add_repo('tatsh/repo', security_status='enabled')
    fake_github.add_pull('tatsh/repo', 1)
    fake_github.gmail.thread_ids = ['t1']
    await merge_dependabot_pull_requests(token='fake_token')
    assert fake_github.gmail.archived_threads == []
    assert fake_github.gmail.token_requests == []


@pytest.mark.parametrize(('user_email', 'credentials'), [(None, CREDENTIALS_JSON),
                                                         ('tatsh@example.com', None)])
@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_archives_email_missing_configuration(
        credentials: str | None, fake_github: FakeGitHub, mocker: MockerFixture,
        user_email: str | None) -> None:
    mocker.patch('keyring.get_password', return_value=credentials)
    fake_github.user_email = user_email
    fake_github.add_repo('tatsh/repo', security_status='enabled')
    fake_github.add_pull('tatsh/repo', 1)
    with pytest.raises(GmailConfigurationError):
        await merge_dependabot_pull_requests(token='fake_token', archive_email=True)
    assert fake_github.gmail.archived_threads == []


@pytest.mark.parametrize('status', [401, 403])
@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_rejected_token_stops_the_run(
        fake_github: FakeGitHub, mocker: MockerFixture, status: int) -> None:
    mocker.patch('keyring.get_password', return_value=CREDENTIALS_JSON)
    fake_github.add_repo('tatsh/repo', security_status='enabled')
    fake_github.add_pull('tatsh/repo', 1)
    fake_github.gmail.thread_ids = ['t1']
    fake_github.gmail.modify_status = status
    with pytest.raises(GmailConfigurationError, match='scope'):
        await merge_dependabot_pull_requests(token='fake_token', archive_email=True)


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_archive_email_failure_does_not_fail_merge(
        caplog: pytest.LogCaptureFixture, fake_github: FakeGitHub, mocker: MockerFixture) -> None:
    mocker.patch('keyring.get_password', return_value=CREDENTIALS_JSON)
    fake_github.add_repo('tatsh/repo', security_status='enabled')
    fake_github.add_pull('tatsh/repo', 1)
    fake_github.gmail.thread_ids = ['t1']
    fake_github.gmail.modify_status = 500
    with caplog.at_level(logging.WARNING, logger='deltona.git'):
        await merge_dependabot_pull_requests(token='fake_token', archive_email=True)
    assert fake_github.merge_calls == [('tatsh/repo', 1, {'merge_method': 'rebase'})]
    assert any('archive the email' in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_merge_pre_commit_ci_pull_requests_archives_email(fake_github: FakeGitHub,
                                                                mocker: MockerFixture) -> None:
    mocker.patch('keyring.get_password', return_value=CREDENTIALS_JSON)
    fake_github.add_repo('tatsh/repo', files={'.pre-commit-config.yaml'})
    fake_github.add_pull('tatsh/repo', 9, user_login='pre-commit-ci[bot]')
    fake_github.gmail.thread_ids = ['t9']
    await merge_pre_commit_ci_pull_requests(token='fake_token', archive_email=True)
    assert fake_github.gmail.archived_threads == ['t9']


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_skips_archived(fake_github: FakeGitHub) -> None:
    fake_github.add_repo('tatsh/repo', archived=True)
    await merge_dependabot_pull_requests(token='fake_token')
    assert not any(path.endswith('/pulls') for _, path in fake_github.requests)
    assert not any('/contents/' in path for _, path in fake_github.requests)


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_no_dependabot(fake_github: FakeGitHub) -> None:
    fake_github.add_repo('tatsh/repo', security_status='disabled')
    await merge_dependabot_pull_requests(token='fake_token')
    assert not any(path.endswith('/pulls') for _, path in fake_github.requests)


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_should_raise(fake_github: FakeGitHub) -> None:
    fake_github.add_repo('tatsh/some-repo', security_status='enabled')
    fake_github.add_pull('tatsh/some-repo', 1, merge_error=400)
    with pytest.raises(DependabotMergeError) as exc_info:
        await merge_dependabot_pull_requests(token='fake_token')
    assert exc_info.value.remaining == {'tatsh/some-repo': 1}
    assert fake_github.merge_calls == [('tatsh/some-repo', 1, {'merge_method': 'rebase'})]
    assert fake_github.posted_comments == [('tatsh/some-repo', 1, '@dependabot recreate')]


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_should_raise_debug(caplog: pytest.LogCaptureFixture,
                                                                 fake_github: FakeGitHub) -> None:
    fake_github.add_repo('tatsh/some-repo', security_status='enabled')
    fake_github.add_pull('tatsh/some-repo', 1, merge_error=400)
    with caplog.at_level(logging.DEBUG, logger='deltona.git'), pytest.raises(DependabotMergeError):
        await merge_dependabot_pull_requests(token='fake_token')
    assert any(record.exc_info is not None and 'Will retry' in record.getMessage()
               for record in caplog.records)


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_adds_recreate_comment(
        fake_github: FakeGitHub) -> None:
    fake_github.add_repo('tatsh/repo', security_status='enabled')
    fake_github.add_pull('tatsh/repo', 42, merged=False)
    await merge_dependabot_pull_requests(token='fake_token')
    assert fake_github.merge_calls == [('tatsh/repo', 42, {'merge_method': 'rebase'})]
    assert fake_github.posted_comments == [('tatsh/repo', 42, '@dependabot recreate')]


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_explicit_repos(fake_github: FakeGitHub) -> None:
    fake_github.user_login = 'me'
    fake_github.add_repo('me/mine', listed=False, security_status='enabled')
    fake_github.add_repo('tatsh/other', listed=False, security_status='enabled')
    await merge_dependabot_pull_requests(token='fake_token', repos=['mine', 'tatsh/other'])
    assert not fake_github.list_repos_hit
    assert set(fake_github.repo_gets) == {'me/mine', 'tatsh/other'}


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_explicit_repos_only_full_names(
        fake_github: FakeGitHub) -> None:
    fake_github.add_repo('tatsh/other', listed=False, security_status='enabled')
    await merge_dependabot_pull_requests(token='fake_token', repos=['tatsh/other'])
    assert not fake_github.user_endpoint_hit
    assert fake_github.repo_gets == ['tatsh/other']


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_includes_private_repos(
        fake_github: FakeGitHub) -> None:
    await merge_dependabot_pull_requests(token='fake_token')
    assert fake_github.list_repos_query.get('visibility') == 'all'


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_does_not_add_duplicate_recreate_comment(
        fake_github: FakeGitHub) -> None:
    fake_github.add_repo('tatsh/repo', security_status='enabled')
    fake_github.add_pull('tatsh/repo', 42, merged=False, comments=['@dependabot recreate'])
    await merge_dependabot_pull_requests(token='fake_token')
    assert fake_github.merge_calls == [('tatsh/repo', 42, {'merge_method': 'rebase'})]
    assert fake_github.posted_comments == []


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_logs_unexpected_error_and_continues(
        fake_github: FakeGitHub) -> None:
    fake_github.add_repo('tatsh/boom',
                         security_status='disabled',
                         contents_exc={'.github/dependabot.yml': RuntimeError('unexpected')})
    fake_github.add_repo('tatsh/healthy', security_status='enabled')
    fake_github.add_pull('tatsh/healthy', 1)
    await merge_dependabot_pull_requests(token='fake_token')
    assert fake_github.merge_calls == [('tatsh/healthy', 1, {'merge_method': 'rebase'})]


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_skips_repo_with_pulls_disabled(
        fake_github: FakeGitHub, caplog: pytest.LogCaptureFixture) -> None:
    fake_github.add_repo('tatsh/pulls-disabled', security_status='enabled', pulls_error=404)
    fake_github.add_repo('tatsh/healthy', security_status='enabled')
    fake_github.add_pull('tatsh/healthy', 1)
    with caplog.at_level('INFO', logger='deltona.git'):
        await merge_dependabot_pull_requests(token='fake_token')
    assert fake_github.merge_calls == [('tatsh/healthy', 1, {'merge_method': 'rebase'})]
    assert any('pull requests not available' in r.message and r.levelname == 'INFO'
               for r in caplog.records)
    assert not any(r.levelname == 'ERROR' for r in caplog.records)


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_logs_other_github_errors(
        fake_github: FakeGitHub, caplog: pytest.LogCaptureFixture) -> None:
    fake_github.add_repo('tatsh/failing', security_status='enabled', pulls_error=500)
    with caplog.at_level('ERROR', logger='deltona.git'):
        await merge_dependabot_pull_requests(token='fake_token')
    assert any('GitHub API error' in r.message and r.levelname == 'ERROR' for r in caplog.records)


@pytest.mark.asyncio
async def test_merge_pre_commit_ci_pull_requests_success(fake_github: FakeGitHub) -> None:
    fake_github.add_repo('tatsh/repo', files={'.pre-commit-config.yaml'})
    fake_github.add_pull('tatsh/repo', 7, user_login='pre-commit-ci[bot]')
    await merge_pre_commit_ci_pull_requests(token='fake_token')
    assert ('GET', '/repos/tatsh/repo/contents/.pre-commit-config.yaml') in fake_github.requests
    assert fake_github.merge_calls == [('tatsh/repo', 7, {'merge_method': 'rebase'})]


@pytest.mark.asyncio
async def test_merge_pre_commit_ci_pull_requests_no_pre_commit_config(
        fake_github: FakeGitHub) -> None:
    fake_github.add_repo('tatsh/repo')
    await merge_pre_commit_ci_pull_requests(token='fake_token')
    assert not any(path.endswith('/pulls') for _, path in fake_github.requests)


@pytest.mark.asyncio
async def test_merge_pre_commit_ci_pull_requests_posts_autofix_comment(
        fake_github: FakeGitHub) -> None:
    fake_github.add_repo('tatsh/repo', files={'.pre-commit-config.yaml'})
    fake_github.add_pull('tatsh/repo', 9, user_login='pre-commit-ci[bot]', merged=False)
    await merge_pre_commit_ci_pull_requests(token='fake_token')
    assert fake_github.posted_comments == [('tatsh/repo', 9, 'pre-commit.ci autofix')]


@pytest.mark.asyncio
async def test_merge_pre_commit_ci_pull_requests_does_not_add_duplicate_autofix_comment(
        fake_github: FakeGitHub) -> None:
    fake_github.add_repo('tatsh/repo', files={'.pre-commit-config.yaml'})
    fake_github.add_pull('tatsh/repo',
                         9,
                         user_login='pre-commit-ci[bot]',
                         merged=False,
                         comments=['pre-commit.ci autofix'])
    await merge_pre_commit_ci_pull_requests(token='fake_token')
    assert fake_github.posted_comments == []


@pytest.mark.asyncio
async def test_merge_pre_commit_ci_pull_requests_should_raise(fake_github: FakeGitHub) -> None:
    fake_github.add_repo('tatsh/some-repo', files={'.pre-commit-config.yaml'})
    fake_github.add_pull('tatsh/some-repo', 3, user_login='pre-commit-ci[bot]', merge_error=400)
    with pytest.raises(PreCommitCIMergeError) as exc_info:
        await merge_pre_commit_ci_pull_requests(token='fake_token')
    assert exc_info.value.remaining == {'tatsh/some-repo': 1}
    assert exc_info.value.bot_label == 'pre-commit.ci'
    assert fake_github.posted_comments == [('tatsh/some-repo', 3, 'pre-commit.ci autofix')]


def test_token_path_system_is_not_under_a_home(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.git.platformdirs.site_config_path', return_value=tmp_path / 'site')
    mocker.patch('deltona.git.platformdirs.user_config_path', return_value=tmp_path / 'user')
    # A systemd-system service reads the file as another account, so it cannot live under one home.
    assert token_path('a', 'systemd-system') == tmp_path / 'site' / 'github-a.token'
    assert token_path('a') == tmp_path / 'user' / 'github-a.token'
    assert token_path('Some User') == tmp_path / 'user' / 'github-some-user.token'


def test_store_token_permissions(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.git.platformdirs.user_config_path', return_value=tmp_path / 'config')

    path = store_token('  secret  ', 'a')
    assert path.read_text(encoding='utf-8') == 'secret\n'
    # The account and its group, and nobody else.
    assert path.stat().st_mode & 0o777 == 0o640
    assert path.parent.stat().st_mode & 0o777 == 0o750


def test_store_token_sets_ownership(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.git.platformdirs.user_config_path', return_value=tmp_path / 'config')
    mock_chown = mocker.patch('deltona.git.shutil.chown')

    path = store_token('secret', 'a', group='daemons', user='svc')
    assert mock_chown.call_args_list[0].args[0] == path
    assert mock_chown.call_args_list[0].kwargs == {'group': 'daemons', 'user': 'svc'}
    # The directory too, or the file cannot be reached.
    assert mock_chown.call_args_list[-1].args[0] == path.parent


def test_stored_token_absent(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.git.platformdirs.site_config_path', return_value=tmp_path / 'site')
    mocker.patch('deltona.git.platformdirs.user_config_path', return_value=tmp_path / 'user')
    assert stored_token('a') is None


def test_stored_token_falls_back_to_the_system_location(mocker: MockerFixture,
                                                        tmp_path: Path) -> None:
    mocker.patch('deltona.git.platformdirs.site_config_path', return_value=tmp_path / 'site')
    mocker.patch('deltona.git.platformdirs.user_config_path', return_value=tmp_path / 'user')
    store_token('from-site', 'a', 'systemd-system')
    # A daemon is not told which kind installed it, so both locations are tried.
    assert stored_token('a') == 'from-site'


def test_stored_token_warns_when_a_file_cannot_be_read(mocker: MockerFixture, tmp_path: Path,
                                                       caplog: pytest.LogCaptureFixture) -> None:
    mocker.patch('deltona.git.platformdirs.site_config_path', return_value=tmp_path / 'site')
    mocker.patch('deltona.git.platformdirs.user_config_path', return_value=tmp_path / 'user')
    store_token('unreadable', 'a')
    mocker.patch.object(Path, 'read_text', side_effect=PermissionError('denied'))
    with caplog.at_level(logging.WARNING, logger='deltona.git'):
        assert stored_token('a') is None
    assert 'Could not read the token' in caplog.text


def test_stored_token_ignores_an_empty_file(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.git.platformdirs.site_config_path', return_value=tmp_path / 'site')
    mocker.patch('deltona.git.platformdirs.user_config_path', return_value=tmp_path / 'user')
    path = token_path('a')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('   \n', encoding='utf-8')
    assert stored_token('a') is None


def test_github_token_prefers_the_keyring(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.git.platformdirs.user_config_path', return_value=tmp_path / 'user')
    mocker.patch('deltona.git.keyring.get_password', return_value='from-keyring')
    store_token('from-file', 'a')
    assert github_token('a') == 'from-keyring'


@pytest.mark.parametrize('outcome', [
    {
        'return_value': None
    },
    {
        'side_effect': keyring.errors.KeyringError
    },
])
def test_github_token_falls_back_to_the_file(mocker: MockerFixture, tmp_path: Path,
                                             outcome: dict[str, Any]) -> None:
    mocker.patch('deltona.git.platformdirs.site_config_path', return_value=tmp_path / 'site')
    mocker.patch('deltona.git.platformdirs.user_config_path', return_value=tmp_path / 'user')
    mocker.patch('deltona.git.keyring.get_password', **outcome)
    store_token('from-file', 'a')
    # A machine with no keyring backend at all raises rather than returning nothing.
    assert github_token('a') == 'from-file'


def test_github_token_absent(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.git.platformdirs.site_config_path', return_value=tmp_path / 'site')
    mocker.patch('deltona.git.platformdirs.user_config_path', return_value=tmp_path / 'user')
    mocker.patch('deltona.git.keyring.get_password', return_value=None)
    assert github_token('a') is None


def _watch_gh(mocker: MockerFixture,
              pages: Sequence[Sequence[dict[str, Any]]],
              pulls: dict[str, Any] | None = None,
              poll_interval: str | None = None,
              fail_after: int | None = None,
              fail_on: str | None = None) -> Any:
    feed = iter(pages)
    calls = 0
    # gidgethub only caches a response that carries one of these, which is what makes the
    # conditional request that costs no rate limit.
    headers = {'content-type': 'application/json; charset=utf-8', 'etag': '"tag"'}
    if poll_interval is not None:
        headers['x-poll-interval'] = poll_interval

    async def request(_method: str, url: str, **_kwargs: Any) -> Any:  # ruff: ignore[unused-async]
        nonlocal calls
        calls += 1
        if (fail_after is not None and calls > fail_after) or (fail_on and fail_on in url):
            msg = 'down'
            raise OSError(msg)
        body = (pulls or {}).get(url) if 'pulls' in url else next(feed)
        return mocker.MagicMock(status_code=200, headers=headers, content=json.dumps(body).encode())

    session = mocker.MagicMock()
    session.request = request
    session_class = mocker.patch('deltona.git.niquests.AsyncSession')
    session_class.return_value.__aenter__ = mocker.AsyncMock(return_value=session)
    session_class.return_value.__aexit__ = mocker.AsyncMock(return_value=None)
    return session


def _thread(id_: str,
            url: str = 'https://api.github.com/repos/a/b/pulls/1',
            type_: str = 'PullRequest') -> dict[str, Any]:
    return {'id': id_, 'subject': {'type': type_, 'url': url}}


async def _watch(runs: list[int], **kwargs: Any) -> None:
    async def run() -> None:  # ruff: ignore[unused-async]
        runs.append(1)

    with pytest.raises(_StopWatching):
        await watch_and_merge(run, bot_login=DEPENDABOT_LOGIN, token='t', **kwargs)


@pytest.mark.asyncio
async def test_watch_and_merge_wakes_on_a_bot_pull_request(mocker: MockerFixture) -> None:
    _watch_gh(
        mocker, [[], [_thread('1')]],
        pulls={'https://api.github.com/repos/a/b/pulls/1': {
            'user': {
                'login': DEPENDABOT_LOGIN
            }
        }})
    mocker.patch('deltona.git.anyio.sleep', side_effect=[None, _StopWatching])
    runs: list[int] = []

    await _watch(runs)
    # Once at startup and once for the notification.
    assert len(runs) == 2


@pytest.mark.asyncio
async def test_watch_and_merge_forgets_pull_requests_it_has_read(mocker: MockerFixture) -> None:
    _watch_gh(
        mocker, [[], [_thread('1')], [_thread('1')]],
        pulls={'https://api.github.com/repos/a/b/pulls/1': {
            'user': {
                'login': DEPENDABOT_LOGIN
            }
        }})
    mocker.patch('deltona.git.anyio.sleep', side_effect=[None, None, _StopWatching])
    runs: list[int] = []

    await _watch(runs, sweep=10_000)
    # The pull request read on the first poll is dropped on the second, since this runs for as long
    # as the machine is up. Nothing is new by then, so no further pass happens.
    assert len(runs) == 2


@pytest.mark.asyncio
async def test_watch_and_merge_ignores_another_authors_pull_request(mocker: MockerFixture) -> None:
    _watch_gh(mocker, [[], [_thread('1')]],
              pulls={'https://api.github.com/repos/a/b/pulls/1': {
                  'user': {
                      'login': 'someone'
                  }
              }})
    mocker.patch('deltona.git.anyio.sleep', side_effect=[None, _StopWatching])
    runs: list[int] = []

    await _watch(runs, sweep=10_000)
    # Waking for it would cost a pass over every repository to merge nothing.
    assert len(runs) == 1


@pytest.mark.asyncio
async def test_watch_and_merge_ignores_what_is_not_a_pull_request(mocker: MockerFixture) -> None:
    _watch_gh(mocker, [[], [_thread('1', type_='Issue')]])
    mocker.patch('deltona.git.anyio.sleep', side_effect=[None, _StopWatching])
    runs: list[int] = []

    await _watch(runs, sweep=10_000)
    assert len(runs) == 1


@pytest.mark.asyncio
async def test_watch_and_merge_sweeps_when_due(mocker: MockerFixture) -> None:
    _watch_gh(mocker, [[], []])
    mocker.patch('deltona.git.anyio.sleep', side_effect=[None, _StopWatching])
    runs: list[int] = []

    await _watch(runs, sweep=0)
    # Nothing was notified about, so this pass is the one that makes the daemon correct.
    assert len(runs) == 2


@pytest.mark.asyncio
async def test_watch_and_merge_survives_a_failed_first_read(
        mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    _watch_gh(mocker, [[]], fail_after=0)
    mocker.patch('deltona.git.anyio.sleep', side_effect=[_StopWatching])
    runs: list[int] = []

    with caplog.at_level(logging.WARNING, logger='deltona.git'):
        await _watch(runs, sweep=10_000)
    # Whatever restarts the daemon meets the same blip, so it starts anyway.
    assert 'Could not read notifications' in caplog.text
    assert len(runs) == 1


@pytest.mark.asyncio
async def test_watch_and_merge_survives_a_failed_read(mocker: MockerFixture,
                                                      caplog: pytest.LogCaptureFixture) -> None:
    _watch_gh(mocker, [[]], fail_after=1)
    mocker.patch('deltona.git.anyio.sleep', side_effect=[None, _StopWatching])
    runs: list[int] = []

    with caplog.at_level(logging.WARNING, logger='deltona.git'):
        await _watch(runs, sweep=10_000)
    assert 'Could not read notifications' in caplog.text


@pytest.mark.asyncio
async def test_watch_and_merge_obeys_the_poll_interval(mocker: MockerFixture) -> None:
    _watch_gh(mocker, [[], []], poll_interval='900')
    mock_sleep = mocker.patch('deltona.git.anyio.sleep', side_effect=[None, _StopWatching])
    runs: list[int] = []

    await _watch(runs, poll=60, sweep=10_000)
    # GitHub raises this under load and asks that it be obeyed.
    assert mock_sleep.call_args.args[0] == pytest.approx(900.0)


@pytest.mark.asyncio
async def test_watch_and_merge_keeps_going_after_a_merge_failure(
        mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    _watch_gh(mocker, [[]])
    mocker.patch('deltona.git.anyio.sleep', side_effect=[_StopWatching])

    async def run() -> None:  # ruff: ignore[unused-async]
        raise DependabotMergeError({'a/b': 1})

    with caplog.at_level(logging.WARNING, logger='deltona.git'), pytest.raises(_StopWatching):
        await watch_and_merge(run, bot_login=DEPENDABOT_LOGIN, token='t')
    assert 'remain across' in caplog.text


@pytest.mark.asyncio
async def test_watch_and_merge_skips_a_pull_request_it_cannot_read(mocker: MockerFixture) -> None:
    _watch_gh(mocker, [[], [_thread('1')]], fail_on='pulls')
    mocker.patch('deltona.git.anyio.sleep', side_effect=[None, _StopWatching])
    runs: list[int] = []

    await _watch(runs, sweep=10_000)
    # The periodic pass reaches it either way, which beats reading it once a minute forever.
    assert len(runs) == 1


@pytest.mark.asyncio
async def test_watch_and_merge_ignores_a_notification_with_no_url(mocker: MockerFixture) -> None:
    _watch_gh(mocker, [[], [_thread('1', url='')]])
    mocker.patch('deltona.git.anyio.sleep', side_effect=[None, _StopWatching])
    runs: list[int] = []

    await _watch(runs, sweep=10_000)
    assert len(runs) == 1
