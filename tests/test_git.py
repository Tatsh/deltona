from __future__ import annotations

from typing import TYPE_CHECKING, Any

from deltona.git import (
    DependabotMergeError,
    PreCommitCIMergeError,
    convert_git_ssh_url_to_https,
    get_github_default_branch,
    merge_dependabot_pull_requests,
    merge_pre_commit_ci_pull_requests,
)
import github
import pytest

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def test_convert_git_ssh_url_to_https() -> None:
    assert (convert_git_ssh_url_to_https('git@github.com:user/repo.git') ==
            'https://github.com/user/repo')
    assert (convert_git_ssh_url_to_https('ssh://git@github.com:user/repo.git') ==
            'https://github.com/user/repo')
    assert (convert_git_ssh_url_to_https('https://github.com/user/repo.git') ==
            'https://github.com/user/repo')


def test_get_github_default_branch(mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    mock_github = mocker.Mock()
    mock_repo = mocker.Mock()
    mock_github.get_repo.return_value = mock_repo
    monkeypatch.setattr('github.Github', mock_github)
    mock_repo.remote.return_value.url = 'git@github.com:user/repo.git'
    mock_github.return_value.get_repo.return_value.default_branch = 'main'
    result = get_github_default_branch(repo=mock_repo, token='fake_token')
    assert result == 'main'
    mock_github.return_value.get_repo.assert_called_once_with('user/repo')


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_success(mocker: MockerFixture,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    mock_github = mocker.Mock()
    mock_github_repo = mocker.Mock()
    mock_github.return_value.get_user.return_value.get_repos.return_value = [mock_github_repo]
    mock_github_repo.archived = False
    mock_github_repo.security_and_analysis.dependabot_security_updates.status = 'enabled'
    mock_github_repo.get_pulls.return_value = [
        mocker.Mock(user=mocker.Mock(login='dependabot[bot]'), number=1)
    ]
    mock_github_repo.get_pull.return_value.merge.return_value.merged = True
    monkeypatch.setattr('github.Github', mock_github)
    await merge_dependabot_pull_requests(token='fake_token')
    mock_github_repo.get_pull.assert_called_once_with(1)
    mock_github_repo.get_pull.return_value.merge.assert_called_once_with(merge_method='rebase')


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_success_get_pull_fails(
        mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    mock_github = mocker.Mock()
    mock_github_repo = mocker.Mock()
    mock_github.return_value.get_user.return_value.get_repos.return_value = [mock_github_repo]
    mock_github_repo.archived = False
    mock_github_repo.security_and_analysis.dependabot_security_updates.status = 'enabled'
    mock_pull = mocker.MagicMock(user=mocker.Mock(login='dependabot[bot]'), number=1)
    mock_github_repo.get_pull.side_effect = github.GithubException(400)
    mock_github_repo.get_pulls.return_value = [mock_pull]
    monkeypatch.setattr('github.Github', mock_github)
    with pytest.raises(RuntimeError):
        await merge_dependabot_pull_requests(token='fake_token')
    mock_pull.as_issue.return_value.create_comment.assert_not_called()


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_success_alt(mocker: MockerFixture,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    mock_github = mocker.Mock()
    mock_github_repo = mocker.Mock()
    mock_github.return_value.get_user.return_value.get_repos.return_value = [mock_github_repo]
    mock_github_repo.archived = False
    mock_github_repo.security_and_analysis.dependabot_security_updates.status = 'not enabled'
    mock_github_repo.get_pulls.return_value = [
        mocker.Mock(user=mocker.Mock(login='dependabot[bot]'), number=1)
    ]
    mock_github_repo.get_pull.return_value.merge.return_value.merged = True
    monkeypatch.setattr('github.Github', mock_github)
    await merge_dependabot_pull_requests(token='fake_token')
    mock_github_repo.get_pull.assert_called_once_with(1)
    mock_github_repo.get_pull.return_value.merge.assert_called_once_with(merge_method='rebase')


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_skips_archived(
        mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    mock_github = mocker.Mock()
    mock_github_repo = mocker.Mock()
    mock_github_repo.archived = True
    mock_github.return_value.get_user.return_value.get_repos.return_value = [mock_github_repo]
    monkeypatch.setattr('github.Github', mock_github)
    await merge_dependabot_pull_requests(token='fake_token')
    mock_github_repo.get_pulls.assert_not_called()
    mock_github_repo.get_contents.assert_not_called()


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_no_dependabot(
        mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_ghe(*args: Any) -> None:
        raise github.GithubException(400)

    mock_github = mocker.Mock()
    mock_github_repo = mocker.Mock()
    mock_github_repo.archived = False
    mock_github_repo.get_contents.side_effect = raise_ghe
    mock_github_repo.security_and_analysis.dependabot_security_updates.status = 'disabled'
    mock_github.return_value.get_user.return_value.get_repos.return_value = [mock_github_repo]
    monkeypatch.setattr('github.Github', mock_github)
    await merge_dependabot_pull_requests(token='fake_token')
    mock_github_repo.get_pulls.assert_not_called()


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_should_raise(mocker: MockerFixture,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    mock_github = mocker.Mock()
    mock_github_repo = mocker.Mock()
    mock_github_repo.full_name = 'tatsh/some-repo'
    mock_github.return_value.get_user.return_value.get_repos.return_value = [mock_github_repo]
    mock_github_repo.archived = False
    mock_github_repo.security_and_analysis.dependabot_security_updates.status = 'enabled'
    pull = mocker.Mock(user=mocker.Mock(login='dependabot[bot]'), number=1)
    pull.get_issue_comments.return_value = []
    mock_github_repo.get_pulls.return_value = [pull]
    mock_github_repo.get_pull.return_value = pull
    mock_github_repo.get_pull.return_value.merge.side_effect = github.GithubException(400)
    monkeypatch.setattr('github.Github', mock_github)
    with pytest.raises(DependabotMergeError) as exc_info:
        await merge_dependabot_pull_requests(token='fake_token')
    assert exc_info.value.remaining == {'tatsh/some-repo': 1}
    mock_github_repo.get_pull.assert_called_once_with(1)
    mock_github_repo.get_pull.return_value.merge.assert_called_once_with(merge_method='rebase')


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_adds_recreate_comment(
        mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    mock_github = mocker.Mock()
    mock_github_repo = mocker.Mock()
    mock_pull = mocker.Mock()
    mock_issue = mocker.Mock()
    mock_github_repo.archived = False
    mock_github_repo.security_and_analysis.dependabot_security_updates.status = 'enabled'
    mock_pull.user.login = 'dependabot[bot]'
    mock_pull.number = 42
    merge_result = mocker.Mock()
    merge_result.merged = False
    mock_pull.merge.return_value = merge_result
    mock_pull.as_issue.return_value = mock_issue
    mock_pull.get_issue_comments.return_value = []
    mock_github_repo.get_pulls.return_value = [mock_pull]
    mock_github_repo.get_pull.return_value = mock_pull
    mock_github.return_value.get_user.return_value.get_repos.return_value = [mock_github_repo]
    monkeypatch.setattr('github.Github', mock_github)
    await merge_dependabot_pull_requests(token='fake_token')
    mock_github_repo.get_pull.assert_called_once_with(42)
    mock_pull.merge.assert_called_once_with(merge_method='rebase')
    mock_pull.as_issue.assert_called_once()
    mock_issue.create_comment.assert_called_once_with('@dependabot recreate')


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_explicit_repos(
        mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    mock_github = mocker.Mock()
    mock_github.return_value.get_user.return_value.login = 'me'
    bare_repo = mocker.Mock()
    bare_repo.archived = False
    bare_repo.security_and_analysis.dependabot_security_updates.status = 'enabled'
    bare_repo.get_pulls.return_value = []
    full_repo = mocker.Mock()
    full_repo.archived = False
    full_repo.security_and_analysis.dependabot_security_updates.status = 'enabled'
    full_repo.get_pulls.return_value = []
    mock_github.return_value.get_repo.side_effect = (lambda name: bare_repo
                                                     if name == 'me/mine' else full_repo)
    monkeypatch.setattr('github.Github', mock_github)
    await merge_dependabot_pull_requests(token='fake_token', repos=['mine', 'tatsh/other'])
    mock_github.return_value.get_user.return_value.get_repos.assert_not_called()
    assert mock_github.return_value.get_repo.call_args_list == [
        mocker.call('me/mine'), mocker.call('tatsh/other')
    ]


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_explicit_repos_only_full_names(
        mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    mock_github = mocker.Mock()
    repo = mocker.Mock()
    repo.archived = False
    repo.security_and_analysis.dependabot_security_updates.status = 'enabled'
    repo.get_pulls.return_value = []
    mock_github.return_value.get_repo.return_value = repo
    monkeypatch.setattr('github.Github', mock_github)
    await merge_dependabot_pull_requests(token='fake_token', repos=['tatsh/other'])
    mock_github.return_value.get_user.assert_not_called()
    mock_github.return_value.get_repo.assert_called_once_with('tatsh/other')


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_includes_private_repos(
        mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    mock_github = mocker.Mock()
    mock_github.return_value.get_user.return_value.get_repos.return_value = []
    monkeypatch.setattr('github.Github', mock_github)
    await merge_dependabot_pull_requests(token='fake_token')
    _, kwargs = mock_github.return_value.get_user.return_value.get_repos.call_args
    assert kwargs.get('visibility') == 'all'


@pytest.mark.asyncio
async def test_merge_dependabot_pull_requests_does_not_add_duplicate_recreate_comment(
        mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    mock_github = mocker.Mock()
    mock_github_repo = mocker.Mock()
    mock_pull = mocker.Mock()
    mock_issue = mocker.Mock()
    mock_github_repo.archived = False
    mock_github_repo.security_and_analysis.dependabot_security_updates.status = 'enabled'
    mock_pull.user.login = 'dependabot[bot]'
    mock_pull.number = 42
    merge_result = mocker.Mock()
    merge_result.merged = False
    mock_pull.merge.return_value = merge_result
    mock_pull.as_issue.return_value = mock_issue
    mock_comment = mocker.Mock(body='@dependabot recreate')
    mock_pull.get_issue_comments.return_value = [mock_comment]
    mock_github_repo.get_pulls.return_value = [mock_pull]
    mock_github_repo.get_pull.return_value = mock_pull
    mock_github.return_value.get_user.return_value.get_repos.return_value = [mock_github_repo]
    monkeypatch.setattr('github.Github', mock_github)
    await merge_dependabot_pull_requests(token='fake_token')
    mock_github_repo.get_pull.assert_called_once_with(42)
    mock_pull.merge.assert_called_once_with(merge_method='rebase')
    mock_issue.create_comment.assert_not_called()


@pytest.mark.asyncio
async def test_merge_pre_commit_ci_pull_requests_success(mocker: MockerFixture,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    mock_github = mocker.Mock()
    mock_github_repo = mocker.Mock()
    mock_github.return_value.get_user.return_value.get_repos.return_value = [mock_github_repo]
    mock_github_repo.archived = False
    mock_github_repo.get_pulls.return_value = [
        mocker.Mock(user=mocker.Mock(login='pre-commit-ci[bot]'), number=7)
    ]
    mock_github_repo.get_pull.return_value.merge.return_value.merged = True
    monkeypatch.setattr('github.Github', mock_github)
    await merge_pre_commit_ci_pull_requests(token='fake_token')
    mock_github_repo.get_contents.assert_called_once_with('.pre-commit-config.yaml')
    mock_github_repo.get_pull.assert_called_once_with(7)
    mock_github_repo.get_pull.return_value.merge.assert_called_once_with(merge_method='rebase')


@pytest.mark.asyncio
async def test_merge_pre_commit_ci_pull_requests_no_pre_commit_config(
        mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_ghe(*args: Any) -> None:
        raise github.GithubException(404)

    mock_github = mocker.Mock()
    mock_github_repo = mocker.Mock()
    mock_github_repo.archived = False
    mock_github_repo.get_contents.side_effect = raise_ghe
    mock_github.return_value.get_user.return_value.get_repos.return_value = [mock_github_repo]
    monkeypatch.setattr('github.Github', mock_github)
    await merge_pre_commit_ci_pull_requests(token='fake_token')
    mock_github_repo.get_pulls.assert_not_called()


@pytest.mark.asyncio
async def test_merge_pre_commit_ci_pull_requests_posts_autofix_comment(
        mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    mock_github = mocker.Mock()
    mock_github_repo = mocker.Mock()
    mock_pull = mocker.Mock()
    mock_issue = mocker.Mock()
    mock_github_repo.archived = False
    mock_pull.user.login = 'pre-commit-ci[bot]'
    mock_pull.number = 9
    merge_result = mocker.Mock()
    merge_result.merged = False
    mock_pull.merge.return_value = merge_result
    mock_pull.as_issue.return_value = mock_issue
    mock_pull.get_issue_comments.return_value = []
    mock_github_repo.get_pulls.return_value = [mock_pull]
    mock_github_repo.get_pull.return_value = mock_pull
    mock_github.return_value.get_user.return_value.get_repos.return_value = [mock_github_repo]
    monkeypatch.setattr('github.Github', mock_github)
    await merge_pre_commit_ci_pull_requests(token='fake_token')
    mock_issue.create_comment.assert_called_once_with('pre-commit.ci autofix')


@pytest.mark.asyncio
async def test_merge_pre_commit_ci_pull_requests_does_not_add_duplicate_autofix_comment(
        mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    mock_github = mocker.Mock()
    mock_github_repo = mocker.Mock()
    mock_pull = mocker.Mock()
    mock_issue = mocker.Mock()
    mock_github_repo.archived = False
    mock_pull.user.login = 'pre-commit-ci[bot]'
    mock_pull.number = 9
    merge_result = mocker.Mock()
    merge_result.merged = False
    mock_pull.merge.return_value = merge_result
    mock_pull.as_issue.return_value = mock_issue
    mock_pull.get_issue_comments.return_value = [mocker.Mock(body='pre-commit.ci autofix')]
    mock_github_repo.get_pulls.return_value = [mock_pull]
    mock_github_repo.get_pull.return_value = mock_pull
    mock_github.return_value.get_user.return_value.get_repos.return_value = [mock_github_repo]
    monkeypatch.setattr('github.Github', mock_github)
    await merge_pre_commit_ci_pull_requests(token='fake_token')
    mock_issue.create_comment.assert_not_called()


@pytest.mark.asyncio
async def test_merge_pre_commit_ci_pull_requests_should_raise(
        mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    mock_github = mocker.Mock()
    mock_github_repo = mocker.Mock()
    mock_github_repo.full_name = 'tatsh/some-repo'
    mock_github.return_value.get_user.return_value.get_repos.return_value = [mock_github_repo]
    mock_github_repo.archived = False
    pull = mocker.Mock(user=mocker.Mock(login='pre-commit-ci[bot]'), number=3)
    pull.get_issue_comments.return_value = []
    mock_github_repo.get_pulls.return_value = [pull]
    mock_github_repo.get_pull.return_value = pull
    mock_github_repo.get_pull.return_value.merge.side_effect = github.GithubException(400)
    monkeypatch.setattr('github.Github', mock_github)
    with pytest.raises(PreCommitCIMergeError) as exc_info:
        await merge_pre_commit_ci_pull_requests(token='fake_token')
    assert exc_info.value.remaining == {'tatsh/some-repo': 1}
    assert exc_info.value.bot_label == 'pre-commit.ci'
    pull.as_issue.return_value.create_comment.assert_called_once_with('pre-commit.ci autofix')
