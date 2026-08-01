from __future__ import annotations

from typing import TYPE_CHECKING
import logging

from deltona.git import (
    DependabotMergeError,
    PreCommitCIMergeError,
    convert_git_ssh_url_to_https,
    get_github_default_branch,
    merge_dependabot_pull_requests,
    merge_pre_commit_ci_pull_requests,
)
import pytest

if TYPE_CHECKING:
    from pytest_mock import MockerFixture
    from tests.conftest import FakeGitHub

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
    with caplog.at_level(logging.WARNING, logger='deltona.git'):
        await merge_dependabot_pull_requests(token='fake_token', archive_email=True)
    assert fake_github.merge_calls == [('tatsh/repo', 1, {'merge_method': 'rebase'})]
    assert fake_github.gmail.archived_threads == []
    assert any('access token' in record.getMessage() for record in caplog.records)


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
    await merge_dependabot_pull_requests(token='fake_token', archive_email=True)
    assert fake_github.merge_calls == [('tatsh/repo', 1, {'merge_method': 'rebase'})]
    assert fake_github.gmail.archived_threads == []


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
