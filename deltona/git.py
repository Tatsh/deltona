"""Git and Github-related utilities."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar, cast
from urllib.parse import urlparse
import asyncio
import contextlib
import logging
import os
import re

import anyio

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping
    from types import ModuleType

    from git import Repo
    from github import Github
    from github.AuthenticatedUser import AuthenticatedUser
    from github.PullRequest import PullRequest
    from github.Repository import Repository

__all__ = ('BotMergeError', 'DependabotMergeError', 'PreCommitCIMergeError',
           'convert_git_ssh_url_to_https', 'get_github_default_branch',
           'merge_dependabot_pull_requests', 'merge_pre_commit_ci_pull_requests')

_T = TypeVar('_T')
log = logging.getLogger(__name__)


class BotMergeError(RuntimeError):
    """Raised when one or more bot pull requests could not be merged."""

    bot_label: str
    """Human-readable label for the bot, for example ``'Dependabot'``."""
    remaining: dict[str, int]
    """Mapping of repository full name to the number of pull requests still unmerged."""
    def __init__(self, remaining: Mapping[str, int], *, bot_label: str) -> None:
        self.remaining = dict(remaining)
        self.bot_label = bot_label
        total = sum(self.remaining.values())
        super().__init__(f'{total} {bot_label} pull request(s) remain across '
                         f'{len(self.remaining)} repository(ies).')


class DependabotMergeError(BotMergeError):
    """Raised when one or more Dependabot pull requests could not be merged."""
    def __init__(self, remaining: Mapping[str, int]) -> None:
        super().__init__(remaining, bot_label='Dependabot')


class PreCommitCIMergeError(BotMergeError):
    """Raised when one or more pre-commit.ci pull requests could not be merged."""
    def __init__(self, remaining: Mapping[str, int]) -> None:
        super().__init__(remaining, bot_label='pre-commit.ci')


def convert_git_ssh_url_to_https(url: str) -> str:
    """
    Convert a Git SSH URI to HTTPS.

    Parameters
    ----------
    url : str
        Git SSH URL to convert.

    Returns
    -------
    str
        The HTTPS equivalent URL.
    """
    if url.startswith('https://'):
        return re.sub(r'\.git$', '', url)
    return re.sub(
        r'\.git$', '',
        re.sub(r'\.([a-z]+):',
               r'.\1/',
               re.sub(r'^(?:ssh://)?(?:[a-z0-9A-Z]+@)?', 'https://', url, count=1),
               count=1))


def get_github_default_branch(*,
                              repo: Repo,
                              token: str,
                              base_url: str | None = None,
                              origin_name: str = 'origin') -> str:
    """
    Get the default branch of a GitHub repository.

    Parameters
    ----------
    repo : Repo
        The Git repository.
    token : str
        The GitHub token.
    base_url : str | None
        The base URL of the GitHub API (for enterprise).
    origin_name : str
        The name of the remote to use. Default is 'origin'.

    Returns
    -------
    str
        The default branch of the repository.
    """
    import github  # noqa: PLC0415
    import github.Consts  # noqa: PLC0415

    return github.Github(token, base_url=base_url or github.Consts.DEFAULT_BASE_URL).get_repo(
        urlparse(convert_git_ssh_url_to_https(
            repo.remote(origin_name).url)).path[1:]).default_branch


def _uses_dependabot(repo: Repository, gh: ModuleType) -> bool:
    with contextlib.suppress(AttributeError, gh.GithubException):
        if repo.security_and_analysis.dependabot_security_updates.status == 'enabled':
            return True
    try:
        repo.get_contents('.github/workflows/dependabot.yml')
    except gh.GithubException:
        return False
    else:
        return True


def _uses_pre_commit_ci(repo: Repository, gh: ModuleType) -> bool:
    try:
        repo.get_contents('.pre-commit-config.yaml')
    except gh.GithubException:
        return False
    return True


def _has_recreate_comment(pull: PullRequest, command: str) -> bool:
    try:
        return command in pull.get_issue_comments()[-1].body
    except IndexError:
        return False


def _list_bot_pull_numbers(repo: Repository, bot_login: str) -> list[int]:
    return [x.number for x in repo.get_pulls() if x.user.login == bot_login]


def _get_authenticated_user_login(gh: Github) -> str:
    return gh.get_user().login


def _list_user_repositories(gh: Github) -> list[Repository]:
    return list(
        cast('AuthenticatedUser', gh.get_user()).get_repos(sort='full_name', visibility='all'))


def _merge_bot_pull(pull: PullRequest) -> Any:
    return pull.merge(merge_method='rebase')


def _post_recreate_comment(pull: PullRequest, command: str) -> None:
    pull.as_issue().create_comment(command)


async def _merge_bot_pull_requests(*,
                                   token: str,
                                   bot_login: str,
                                   uses_bot: Callable[[Repository, ModuleType], bool],
                                   error_class: Callable[[Mapping[str, int]], BotMergeError],
                                   recreate_command: str,
                                   base_url: str | None = None,
                                   concurrency: int | None = None,
                                   max_concurrent_http_requests: int = 3,
                                   repos: Iterable[str] | None = None) -> None:
    import github  # noqa: PLC0415
    import github.Consts  # noqa: PLC0415

    http_limiter = anyio.CapacityLimiter(max_concurrent_http_requests)
    task_limiter = anyio.CapacityLimiter(concurrency or os.cpu_count() or 1)

    async def call(fn: Callable[..., _T], /, *args: object) -> _T:
        return await anyio.to_thread.run_sync(  # ty: ignore[unresolved-attribute]
            fn, *args, limiter=http_limiter)

    gh = github.Github(token, base_url=base_url or github.Consts.DEFAULT_BASE_URL, per_page=100)
    if repos is None:
        repositories = await call(_list_user_repositories, gh)
    else:
        specs = list(repos)
        login = (await call(_get_authenticated_user_login, gh) if any(
            '/' not in spec for spec in specs) else '')
        full_names = [spec if '/' in spec else f'{login}/{spec}' for spec in specs]
        repositories = list(await asyncio.gather(*(call(gh.get_repo, n) for n in full_names)))

    async def post_recreate_if_missing(pull: PullRequest) -> None:
        if not await call(_has_recreate_comment, pull, recreate_command):
            await call(_post_recreate_comment, pull, recreate_command)

    async def process_pull(repo: Repository, num: int) -> bool:
        pull: PullRequest | None = None
        try:
            pull = await call(repo.get_pull, num)
            result = await call(_merge_bot_pull, pull)
            if not result.merged:
                log.debug('merge() did not raise but merged is False.')
                await post_recreate_if_missing(pull)
        except github.GithubException:
            log.exception('Failed to merge PR %s in repository %s.', num, repo.name)
            if pull is not None:
                await post_recreate_if_missing(pull)
            return False
        return True

    async def process_repo(repo: Repository) -> tuple[str, int]:
        async with task_limiter:
            if repo.archived:
                return repo.full_name, 0
            if not await call(uses_bot, repo, github):
                return repo.full_name, 0
            log.info('Repository: %s', repo.name)
            pull_numbers = await call(_list_bot_pull_numbers, repo, bot_login)
            outcomes = await asyncio.gather(*(process_pull(repo, n) for n in pull_numbers))
            return repo.full_name, sum(1 for ok in outcomes if not ok)

    results = await asyncio.gather(*(process_repo(r) for r in repositories))
    remaining = {full_name: count for full_name, count in results if count > 0}
    if remaining:
        raise error_class(remaining)


async def merge_dependabot_pull_requests(*,
                                         token: str,
                                         base_url: str | None = None,
                                         concurrency: int | None = None,
                                         max_concurrent_http_requests: int = 3,
                                         repos: Iterable[str] | None = None) -> None:
    """
    Merge pull requests made by Dependabot on GitHub.

    Repositories are processed concurrently up to ``concurrency`` at a time,
    with at most ``max_concurrent_http_requests`` outstanding HTTP requests
    across the whole operation. Private repositories are included.

    Parameters
    ----------
    token : str
        The GitHub token.
    base_url : str | None
        The base URL of the GitHub API (for enterprise).
    concurrency : int | None
        Maximum number of repositories processed in parallel. Defaults to the
        number of CPUs reported by :py:func:`os.cpu_count`, or ``1`` when that
        is unavailable.
    max_concurrent_http_requests : int
        Hard cap on simultaneous in-flight HTTP requests. Default is ``3``.
    repos : Iterable[str] | None
        Specific repositories to process. Each item may be a bare repository
        name (resolved against the authenticated user's login) or a fully
        qualified ``owner/name``. When ``None``, every accessible repository
        is processed.

    Raises
    ------
    DependabotMergeError
        If any pull request could not be merged. The exception's ``remaining``
        attribute maps each affected repository's full name to the number of
        Dependabot pull requests still unmerged.
    """  # noqa: DOC502
    await _merge_bot_pull_requests(base_url=base_url,
                                   bot_login='dependabot[bot]',
                                   concurrency=concurrency,
                                   error_class=DependabotMergeError,
                                   max_concurrent_http_requests=max_concurrent_http_requests,
                                   recreate_command='@dependabot recreate',
                                   repos=repos,
                                   token=token,
                                   uses_bot=_uses_dependabot)


async def merge_pre_commit_ci_pull_requests(*,
                                            token: str,
                                            base_url: str | None = None,
                                            concurrency: int | None = None,
                                            max_concurrent_http_requests: int = 3,
                                            repos: Iterable[str] | None = None) -> None:
    """
    Merge pull requests made by `pre-commit.ci <https://pre-commit.ci>`_ on GitHub.

    Repositories are processed concurrently up to ``concurrency`` at a time,
    with at most ``max_concurrent_http_requests`` outstanding HTTP requests
    across the whole operation. Private repositories are included. Repositories
    without a top-level ``.pre-commit-config.yaml`` are skipped.

    Parameters
    ----------
    token : str
        The GitHub token.
    base_url : str | None
        The base URL of the GitHub API (for enterprise).
    concurrency : int | None
        Maximum number of repositories processed in parallel. Defaults to the
        number of CPUs reported by :py:func:`os.cpu_count`, or ``1`` when that
        is unavailable.
    max_concurrent_http_requests : int
        Hard cap on simultaneous in-flight HTTP requests. Default is ``3``.
    repos : Iterable[str] | None
        Specific repositories to process. Each item may be a bare repository
        name (resolved against the authenticated user's login) or a fully
        qualified ``owner/name``. When ``None``, every accessible repository
        is processed.

    Raises
    ------
    PreCommitCIMergeError
        If any pull request could not be merged. The exception's ``remaining``
        attribute maps each affected repository's full name to the number of
        pre-commit.ci pull requests still unmerged.
    """  # noqa: DOC502
    await _merge_bot_pull_requests(base_url=base_url,
                                   bot_login='pre-commit-ci[bot]',
                                   concurrency=concurrency,
                                   error_class=PreCommitCIMergeError,
                                   max_concurrent_http_requests=max_concurrent_http_requests,
                                   recreate_command='pre-commit.ci autofix',
                                   repos=repos,
                                   token=token,
                                   uses_bot=_uses_pre_commit_ci)
