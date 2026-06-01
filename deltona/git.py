"""Git and Github-related utilities."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse
import asyncio
import logging
import os
import re

from typing_extensions import override
import anyio
import niquests

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Mapping

    from git import Repo
    import gidgethub.abc

__all__ = ('BotMergeError', 'DependabotMergeError', 'PreCommitCIMergeError',
           'convert_git_ssh_url_to_https', 'get_github_default_branch',
           'merge_dependabot_pull_requests', 'merge_pre_commit_ci_pull_requests')

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


def _make_github_api(session: niquests.AsyncSession,
                     *,
                     token: str,
                     base_url: str | None = None,
                     limiter: anyio.CapacityLimiter | None = None) -> gidgethub.abc.GitHubAPI:
    import gidgethub.abc  # noqa: PLC0415

    class _NiquestsGitHubAPI(gidgethub.abc.GitHubAPI):
        @override
        async def _request(self,
                           method: str,
                           url: str,
                           headers: Mapping[str, str],
                           body: bytes = b'') -> tuple[int, Mapping[str, str], bytes]:
            if limiter is None:
                response = await session.request(method, url, headers=dict(headers), data=body)
            else:
                async with limiter:
                    response = await session.request(method, url, headers=dict(headers), data=body)
            return response.status_code or 0, response.headers, response.content or b''

        @override
        async def sleep(self, seconds: float) -> None:  # pragma: no cover
            # Required by the gidgethub ABC for rate-limit backoff, which deltona never triggers.
            await anyio.sleep(seconds)

    return _NiquestsGitHubAPI('deltona',
                              base_url=base_url or 'https://api.github.com',
                              oauth_token=token)


async def get_github_default_branch(*,
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
    full_name = urlparse(convert_git_ssh_url_to_https(repo.remote(origin_name).url)).path[1:]
    async with niquests.AsyncSession() as session:
        gh = _make_github_api(session, base_url=base_url, token=token)
        data = await gh.getitem(f'/repos/{full_name}')
    return str(data['default_branch'])


def _log_merge_failure(number: int, name: str) -> None:
    # Called only from ``except`` handlers, so ``sys.exc_info`` is set and
    # ``log.exception`` attaches the traceback even though it is not lexically inside the handler.
    if log.isEnabledFor(logging.DEBUG):
        log.exception(  # noqa: LOG004
            'Failed to merge PR %s in repository `%s`. Will retry.', number, name)
    else:
        log.warning('Failed to merge PR %s in repository `%s`. Will retry.', number, name)


async def _uses_dependabot(gh: gidgethub.abc.GitHubAPI, repo: Mapping[str, Any]) -> bool:
    import gidgethub  # noqa: PLC0415

    full_name = repo['full_name']
    # The /user/repos list endpoint omits security_and_analysis, so fetch the full repository to
    # read the Dependabot security-updates status when the field is absent.
    if 'security_and_analysis' not in repo:
        repo = await gh.getitem(f'/repos/{full_name}')
    updates = (repo.get('security_and_analysis') or {}).get('dependabot_security_updates') or {}
    if updates.get('status') == 'enabled':
        return True
    try:
        await gh.getitem(f'/repos/{full_name}/contents/.github/workflows/dependabot.yml')
    except gidgethub.HTTPException:
        return False
    return True


async def _uses_pre_commit_ci(gh: gidgethub.abc.GitHubAPI, repo: Mapping[str, Any]) -> bool:
    import gidgethub  # noqa: PLC0415

    try:
        await gh.getitem(f'/repos/{repo["full_name"]}/contents/.pre-commit-config.yaml')
    except gidgethub.HTTPException:
        return False
    return True


async def _merge_bot_pull_requests(*,
                                   token: str,
                                   bot_login: str,
                                   uses_bot: Callable[[gidgethub.abc.GitHubAPI, Mapping[str, Any]],
                                                      Awaitable[bool]],
                                   error_class: Callable[[Mapping[str, int]], BotMergeError],
                                   recreate_command: str,
                                   base_url: str | None = None,
                                   concurrency: int | None = None,
                                   max_concurrent_http_requests: int = 3,
                                   repos: Iterable[str] | None = None) -> None:
    import gidgethub  # noqa: PLC0415

    http_limiter = anyio.CapacityLimiter(max_concurrent_http_requests)
    task_limiter = anyio.CapacityLimiter(concurrency or os.cpu_count() or 1)

    async def post_recreate_if_missing(full_name: str, number: int) -> None:
        comments = [c async for c in gh.getiter(f'/repos/{full_name}/issues/{number}/comments')]
        if not comments or recreate_command not in comments[-1]['body']:
            await gh.post(f'/repos/{full_name}/issues/{number}/comments',
                          data={'body': recreate_command})

    async def process_pull(repo: Mapping[str, Any], number: int) -> bool:
        full_name = repo['full_name']
        try:
            await gh.getitem(f'/repos/{full_name}/pulls/{number}')
        except gidgethub.HTTPException:
            _log_merge_failure(number, repo['name'])
            return False
        try:
            result = await gh.put(f'/repos/{full_name}/pulls/{number}/merge',
                                  data={'merge_method': 'rebase'})
            if not result.get('merged'):
                log.debug('Merge did not raise but merged is False.')
                await post_recreate_if_missing(full_name, number)
        except gidgethub.HTTPException:
            _log_merge_failure(number, repo['name'])
            await post_recreate_if_missing(full_name, number)
            return False
        return True

    async def process_repo(repo: Mapping[str, Any]) -> tuple[str, int]:
        async with task_limiter:
            full_name = repo['full_name']
            try:
                if repo['archived']:
                    return full_name, 0
                if not await uses_bot(gh, repo):
                    return full_name, 0
                log.info('Repository: %s', repo['name'])
                pull_numbers = [
                    pull['number'] async for pull in gh.getiter(f'/repos/{full_name}/pulls')
                    if pull['user']['login'] == bot_login
                ]
            except gidgethub.HTTPException as e:
                if e.status_code == HTTPStatus.NOT_FOUND:
                    log.info('Skipping repository `%s`: pull requests not available.', full_name)
                else:
                    log.exception('Skipping repository `%s` due to GitHub API error.', full_name)
                return full_name, 0
            outcomes = await asyncio.gather(*(process_pull(repo, n) for n in pull_numbers))
            return full_name, sum(1 for ok in outcomes if not ok)

    async with niquests.AsyncSession() as session:
        gh = _make_github_api(session, base_url=base_url, limiter=http_limiter, token=token)
        if repos is None:
            repositories = [
                repo async for repo in gh.getiter('/user/repos{?visibility,sort,per_page}', {
                    'per_page': 100,
                    'sort': 'full_name',
                    'visibility': 'all'
                })
            ]
        else:
            specs = list(repos)
            login = ((await gh.getitem('/user'))['login'] if any(
                '/' not in spec for spec in specs) else '')
            full_names = [spec if '/' in spec else f'{login}/{spec}' for spec in specs]
            repositories = list(
                await asyncio.gather(*(gh.getitem(f'/repos/{name}') for name in full_names)))
        gathered = await asyncio.gather(*(process_repo(r) for r in repositories),
                                        return_exceptions=True)
    remaining: dict[str, int] = {}
    for repo, outcome in zip(repositories, gathered, strict=True):
        if isinstance(outcome, BaseException):
            log.error('Unexpected error processing `%s`: %s', repo['full_name'], outcome)
            continue
        full_name, count = outcome
        if count > 0:
            remaining[full_name] = count
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
