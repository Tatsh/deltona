from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import Mock

from deltona.git import (
    convert_git_ssh_url_to_https,
    get_github_default_branch,
    merge_dependabot_pull_requests,
)
import github
import pytest

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def test_convert_git_ssh_url_to_https() -> None:
    assert convert_git_ssh_url_to_https(
        'git@github.com:user/repo.git') == 'https://github.com/user/repo'
    assert convert_git_ssh_url_to_https(
        'ssh://git@github.com:user/repo.git') == 'https://github.com/user/repo'
    assert convert_git_ssh_url_to_https(
        'https://github.com/user/repo.git') == 'https://github.com/user/repo'


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


def test_merge_dependabot_pull_requests_success(mocker: MockerFixture,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    mock_github = mocker.Mock()
    mock_github_repo = mocker.Mock()
    mock_github.return_value.get_user.return_value.get_repos.return_value = [mock_github_repo]
    mock_github_repo.archived = False
    mock_github_repo.security_and_analysis.dependabot_security_updates.status = 'enabled'
    mock_github_repo.get_pulls.return_value = [Mock(user=Mock(login='dependabot[bot]'), number=1)]
    mock_github_repo.get_pull.return_value.merge.return_value.merged = True
    monkeypatch.setattr('github.Github', mock_github)
    merge_dependabot_pull_requests(token='fake_token')
    mock_github_repo.get_pull.assert_called_once_with(1)
    mock_github_repo.get_pull.return_value.merge.assert_called_once_with(merge_method='rebase')


def test_merge_dependabot_pull_requests_success_alt(mocker: MockerFixture,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    mock_github = mocker.Mock()
    mock_github_repo = mocker.Mock()
    mock_github.return_value.get_user.return_value.get_repos.return_value = [mock_github_repo]
    mock_github_repo.archived = False
    mock_github_repo.security_and_analysis.dependabot_security_updates.status = 'not enabled'
    mock_github_repo.get_pulls.return_value = [Mock(user=Mock(login='dependabot[bot]'), number=1)]
    mock_github_repo.get_pull.return_value.merge.return_value.merged = True
    monkeypatch.setattr('github.Github', mock_github)
    merge_dependabot_pull_requests(token='fake_token')
    mock_github_repo.get_pull.assert_called_once_with(1)
    mock_github_repo.get_pull.return_value.merge.assert_called_once_with(merge_method='rebase')


def test_merge_dependabot_pull_requests_no_dependabot(mocker: MockerFixture,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_ghe(*args: Any) -> None:
        raise github.GithubException(400)

    mock_github = mocker.Mock()
    mock_github_repo = mocker.Mock()
    mock_github_repo.archived = False
    mock_github_repo.get_contents.side_effect = raise_ghe
    mock_github_repo.security_and_analysis.dependabot_security_updates.status = 'disabled'
    mock_github.return_value.get_user.return_value.get_repos.return_value = [mock_github_repo]
    monkeypatch.setattr('github.Github', mock_github)
    merge_dependabot_pull_requests(token='fake_token')
    mock_github_repo.get_pulls.assert_not_called()


def test_merge_dependabot_pull_requests_should_raise(mocker: MockerFixture,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_ghe(*args: Any, **kwargs: Any) -> None:
        raise github.GithubException(400)

    mock_github = mocker.Mock()
    mock_github_repo = mocker.Mock()
    mock_github.return_value.get_user.return_value.get_repos.return_value = [mock_github_repo]
    mock_github_repo.archived = False
    mock_github_repo.security_and_analysis.dependabot_security_updates.status = 'enabled'
    mock_github_repo.get_pulls.return_value = [Mock(user=Mock(login='dependabot[bot]'), number=1)]
    mock_github_repo.get_pull.return_value.merge.side_effect = raise_ghe
    monkeypatch.setattr('github.Github', mock_github)
    with pytest.raises(RuntimeError):
        merge_dependabot_pull_requests(token='fake_token')
    mock_github_repo.get_pull.assert_called_once_with(1)
    mock_github_repo.get_pull.return_value.merge.assert_called_once_with(merge_method='rebase')


def test_merge_dependabot_pull_requests_adds_rebase_comment(
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
    mock_github_repo.get_pulls.return_value = [mock_pull]
    mock_github_repo.get_pull.return_value = mock_pull
    mock_github.return_value.get_user.return_value.get_repos.return_value = [mock_github_repo]
    monkeypatch.setattr('github.Github', mock_github)
    merge_dependabot_pull_requests(token='fake_token')
    mock_github_repo.get_pull.assert_called_once_with(42)
    mock_pull.merge.assert_called_once_with(merge_method='rebase')
    mock_pull.as_issue.assert_called_once()
    mock_issue.create_comment.assert_called_once_with('@dependabot rebase')
