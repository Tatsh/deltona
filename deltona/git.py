"""Git and Github-related utilities."""

from __future__ import annotations

from contextlib import suppress
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse
import asyncio
import logging
import os
import re
import shutil
import time

from typing_extensions import override
import anyio
import gidgethub
import gidgethub.abc
import keyring
import keyring.errors
import niquests
import platformdirs

from .gmail import (
    KEYRING_SERVICE as GMAIL_KEYRING_SERVICE,
    GmailConfigurationError,
    GmailError,
    archive_github_pull_request_email,
    get_access_token,
)
from .string import pluralize, slugify

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Mapping, MutableMapping
    from pathlib import Path

    from git import Repo

    from .services import ServiceKind

__all__ = ('DEFAULT_NOTIFICATION_POLL_SECONDS', 'DEFAULT_SWEEP_SECONDS', 'DEPENDABOT_LOGIN',
           'KEYRING_SERVICE', 'PRE_COMMIT_CI_LOGIN', 'BotMergeError', 'DependabotMergeError',
           'PreCommitCIMergeError', 'convert_git_ssh_url_to_https', 'get_github_default_branch',
           'github_token', 'merge_dependabot_pull_requests', 'merge_pre_commit_ci_pull_requests',
           'store_token', 'stored_token', 'token_path', 'watch_and_merge')

log = logging.getLogger(__name__)

DEFAULT_NOTIFICATION_POLL_SECONDS = 60.0
"""
Shortest wait between reads of the notifications feed.

GitHub answers an unchanged feed with ``304 Not Modified``, which costs no rate limit, and names
the interval it wants in ``X-Poll-Interval``. Whichever is longer is used.

:meta hide-value:
"""
DEFAULT_SWEEP_SECONDS = 900.0
"""
Longest wait between full passes over every repository.

A notification arrives only for a repository the account is subscribed to and has new pull request
notifications enabled for, so the feed cannot be relied on to report everything. This is what makes
the daemon correct rather than merely quick, and it is what reaches every repository the feed says
nothing about.

:meta hide-value:
"""
DEPENDABOT_LOGIN = 'dependabot[bot]'
"""
Login that authors Dependabot pull requests.

:meta hide-value:
"""
KEYRING_SERVICE = 'tmu-github-api'
"""
Keyring service the GitHub token is stored under, keyed on a username.

:meta hide-value:
"""
PRE_COMMIT_CI_LOGIN = 'pre-commit-ci[bot]'
"""
Login that authors pre-commit.ci pull requests.

:meta hide-value:
"""
_NOTIFICATIONS_URL = '/notifications'
_TOKEN_DIR_MODE = 0o750
_TOKEN_FILE_MODE = 0o640

_DEPENDABOT_CONFIG_PATHS = ('.github/dependabot.yml', '.github/dependabot.yaml')


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
        super().__init__(f'{total} {bot_label} {pluralize(total, "pull request")} remain across '
                         f'{len(self.remaining)} '
                         f'{pluralize(len(self.remaining), "repository", "repositories")}.')


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
                     cache: MutableMapping[str, Any] | None = None,
                     limiter: anyio.CapacityLimiter | None = None) -> gidgethub.abc.GitHubAPI:
    class _NiquestsGitHubAPI(gidgethub.abc.GitHubAPI):
        poll_interval = 0.0
        """Seconds GitHub last said to wait before polling again."""
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
            # GitHub increases this under load and asks that it be obeyed rather than assumed. Only
            # the notifications feed carries it, so anything else must leave it alone rather than
            # reset it to nothing.
            if interval := response.headers.get('x-poll-interval'):
                with suppress(ValueError):
                    self.poll_interval = float(interval)
            return response.status_code or 0, response.headers, response.content or b''

        @override
        async def sleep(self, seconds: float) -> None:  # pragma: no cover
            # Required by the gidgethub ABC for rate-limit backoff, which deltona never triggers.
            await anyio.sleep(seconds)

    return _NiquestsGitHubAPI('deltona',
                              base_url=base_url or 'https://api.github.com',
                              cache=cache,
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
        log.exception(  # ruff:ignore[log-exception-outside-except-handler]
            'Failed to merge PR %s in repository `%s`. Will retry.', number, name)
    else:
        log.warning('Failed to merge PR %s in repository `%s`. Will retry.', number, name)


async def _uses_dependabot(gh: gidgethub.abc.GitHubAPI, repo: Mapping[str, Any]) -> bool:
    full_name = repo['full_name']
    for path in _DEPENDABOT_CONFIG_PATHS:
        try:
            await gh.getitem(f'/repos/{full_name}/contents/{path}')
        except gidgethub.HTTPException:
            continue
        return True
    # GitHub omits security_and_analysis from the /user/repos list endpoint, and from the
    # single-repository endpoint for repositories the token has no admin rights on, so only fetch
    # the full repository once no configuration file has been found.
    if 'security_and_analysis' not in repo:
        repo = await gh.getitem(f'/repos/{full_name}')
    updates = (repo.get('security_and_analysis') or {}).get('dependabot_security_updates') or {}
    return updates.get('status') == 'enabled'


async def _uses_pre_commit_ci(gh: gidgethub.abc.GitHubAPI, repo: Mapping[str, Any]) -> bool:
    try:
        await gh.getitem(f'/repos/{repo["full_name"]}/contents/.pre-commit-config.yaml')
    except gidgethub.HTTPException:
        return False
    return True


async def _pull_request_notification_threads(
        gh: gidgethub.abc.GitHubAPI) -> dict[tuple[str, int], str]:
    # Keyed on the repository full name and pull request number rather than the subject URL, so
    # that an enterprise base URL does not affect matching.
    threads: dict[tuple[str, int], str] = {}
    async for thread in gh.getiter('/notifications{?per_page}', {'per_page': 100}):
        subject = thread.get('subject') or {}
        if subject.get('type') != 'PullRequest':
            continue
        number = (subject.get('url') or '').rsplit('/', 1)[-1]
        if not number.isdigit():
            continue
        threads[thread['repository']['full_name'], int(number)] = thread['id']
    return threads


async def _mark_notification_done(gh: gidgethub.abc.GitHubAPI, thread_id: str, *, full_name: str,
                                  number: int) -> None:
    try:
        await gh.delete(f'/notifications/threads/{thread_id}')
    except gidgethub.HTTPException:
        log.warning('Could not mark the notification for PR %s in `%s` as done.', number, full_name)
    else:
        log.debug('Marked the notification for PR %s in `%s` as done.', number, full_name)


async def _archive_email(session: niquests.AsyncSession, *, access_token: str, full_name: str,
                         number: int) -> None:
    try:
        archived = await archive_github_pull_request_email(session,
                                                           access_token=access_token,
                                                           full_name=full_name,
                                                           number=number)
    except GmailConfigurationError:
        # A rejected token will not fix itself on the next pull request, so let it stop the run.
        raise
    except GmailError as e:
        log.warning('Could not archive the email for PR %s in `%s`. %s', number, full_name, e)
    else:
        if archived:
            log.debug('Archived and marked read %s email %s for PR %s in `%s`.', archived,
                      pluralize(archived, 'thread'), number, full_name)
        else:
            log.debug('No email thread found for PR %s in `%s`.', number, full_name)


async def _resolve_gmail_access_token(session: niquests.AsyncSession, gh: gidgethub.abc.GitHubAPI,
                                      email: str | None) -> str:
    if not (address := email or (await gh.getitem('/user')).get('email')):
        msg = ('No email address is available. The authenticated GitHub account has no public '
               'address, so pass one explicitly.')
        raise GmailConfigurationError(msg)
    if not (credentials := keyring.get_password(GMAIL_KEYRING_SERVICE, address)):
        msg = f'No Google credentials are stored for `{address}`.'
        raise GmailConfigurationError(msg)
    token = await get_access_token(session, credentials=credentials)
    log.debug('Archiving emails as `%s`.', address)
    return token


async def _after_merge(gh: gidgethub.abc.GitHubAPI, session: niquests.AsyncSession, *,
                       access_token: str | None, full_name: str, number: int,
                       thread_id: str | None) -> None:
    if thread_id is not None:
        await _mark_notification_done(gh, thread_id, full_name=full_name, number=number)
    if access_token is not None:
        await _archive_email(session, access_token=access_token, full_name=full_name, number=number)


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
                                   repos: Iterable[str] | None = None,
                                   mark_notifications_done: bool = False,
                                   archive_email: bool = False,
                                   email: str | None = None) -> None:
    http_limiter = anyio.CapacityLimiter(max_concurrent_http_requests)
    task_limiter = anyio.CapacityLimiter(concurrency or os.cpu_count() or 1)
    notification_threads: dict[tuple[str, int], str] = {}
    access_token: str | None = None

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
                return True
        except gidgethub.HTTPException:
            _log_merge_failure(number, repo['name'])
            await post_recreate_if_missing(full_name, number)
            return False
        await _after_merge(gh,
                           session,
                           access_token=access_token,
                           full_name=full_name,
                           number=number,
                           thread_id=notification_threads.get((full_name, number)))
        return True

    async def process_repo(repo: Mapping[str, Any]) -> tuple[str, int]:
        async with task_limiter:
            full_name = repo['full_name']
            if repo['archived']:
                log.debug('Skipping archived repository `%s`.', full_name)
                return full_name, 0
            try:
                if not await uses_bot(gh, repo):
                    log.debug('Skipping repository `%s`: no %s configuration detected.', full_name,
                              bot_login)
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
        if mark_notifications_done:
            notification_threads.update(await _pull_request_notification_threads(gh))
        if archive_email:
            access_token = await _resolve_gmail_access_token(session, gh, email)
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
            # Gmail being misconfigured affects every repository, so report it rather than
            # burying one copy of it per repository in the log.
            if isinstance(outcome, GmailConfigurationError):
                raise outcome
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
                                         repos: Iterable[str] | None = None,
                                         mark_notifications_done: bool = False,
                                         archive_email: bool = False,
                                         email: str | None = None) -> None:
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
    mark_notifications_done : bool
        Mark the GitHub notification thread for each merged pull request as
        done. Requires a token with the ``notifications`` or ``repo`` scope.
    archive_email : bool
        Archive the Gmail thread notifying about each merged pull request.
        Credentials are read from the keyring under the service
        ``deltona:mpr:google`` keyed on the email address.
    email : str | None
        The email address to archive mail for. Defaults to the address on the
        authenticated GitHub account.

    Raises
    ------
    DependabotMergeError
        If any pull request could not be merged. The exception's ``remaining``
        attribute maps each affected repository's full name to the number of
        Dependabot pull requests still unmerged.
    """  # ruff:ignore[docstring-extraneous-exception]
    await _merge_bot_pull_requests(archive_email=archive_email,
                                   base_url=base_url,
                                   email=email,
                                   bot_login=DEPENDABOT_LOGIN,
                                   concurrency=concurrency,
                                   error_class=DependabotMergeError,
                                   mark_notifications_done=mark_notifications_done,
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
                                            repos: Iterable[str] | None = None,
                                            mark_notifications_done: bool = False,
                                            archive_email: bool = False,
                                            email: str | None = None) -> None:
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
    mark_notifications_done : bool
        Mark the GitHub notification thread for each merged pull request as
        done. Requires a token with the ``notifications`` or ``repo`` scope.
    archive_email : bool
        Archive the Gmail thread notifying about each merged pull request.
        Credentials are read from the keyring under the service
        ``deltona:mpr:google`` keyed on the email address.
    email : str | None
        The email address to archive mail for. Defaults to the address on the
        authenticated GitHub account.

    Raises
    ------
    PreCommitCIMergeError
        If any pull request could not be merged. The exception's ``remaining``
        attribute maps each affected repository's full name to the number of
        pre-commit.ci pull requests still unmerged.
    """  # ruff:ignore[docstring-extraneous-exception]
    await _merge_bot_pull_requests(archive_email=archive_email,
                                   base_url=base_url,
                                   email=email,
                                   bot_login=PRE_COMMIT_CI_LOGIN,
                                   concurrency=concurrency,
                                   error_class=PreCommitCIMergeError,
                                   mark_notifications_done=mark_notifications_done,
                                   max_concurrent_http_requests=max_concurrent_http_requests,
                                   recreate_command='pre-commit.ci autofix',
                                   repos=repos,
                                   token=token,
                                   uses_bot=_uses_pre_commit_ci)


def token_path(key: str, kind: ServiceKind | None = None) -> Path:
    """
    Get where the token for a keyring key is kept when there is no keyring to keep it in.

    Parameters
    ----------
    key : str
        Keyring key the token belongs to, which is a username.
    kind : ServiceKind | None
        Kind of service the token is for. A ``systemd-system`` service reads the file as another
        account, so its token belongs where the whole machine can reach it rather than under one
        home directory.

    Returns
    -------
    Path
        Path to the token file, which does not have to exist.
    """
    directory = (platformdirs.site_config_path('deltona')
                 if kind == 'systemd-system' else platformdirs.user_config_path('deltona'))
    return directory / f'github-{slugify(key)}.token'


def store_token(token: str,
                key: str,
                kind: ServiceKind | None = None,
                *,
                group: str | None = None,
                user: str | None = None) -> Path:
    """
    Write a token where a daemon without a keyring can read it.

    The file is readable by its owner and its group, and by nobody else, so that a service running
    as another account can be given the token by group membership alone.

    Parameters
    ----------
    token : str
        The GitHub token.
    key : str
        Keyring key the token belongs to, which is a username.
    kind : ServiceKind | None
        Kind of service the token is for.
    group : str | None
        Group given read access. Defaults to the group the file would be created with.
    user : str | None
        Account given ownership. Defaults to the account writing the file.

    Returns
    -------
    Path
        Path the token was written to.

    Raises
    ------
    LookupError
        If ``group`` or ``user`` names an account or group that does not exist.
    PermissionError
        If the file cannot be written or its ownership cannot be set. Setting an owner other than
        the one writing requires privileges.
    """  # noqa: DOC502
    path = token_path(key, kind)
    path.parent.mkdir(mode=_TOKEN_DIR_MODE, parents=True, exist_ok=True)
    path.parent.chmod(_TOKEN_DIR_MODE)
    # Created, narrowed, and given away before anything is written to it, so the token is never
    # readable by anyone it was not meant for, not even for the moment between being written and
    # being given away. mkdir and touch both have the umask applied to the mode they are given,
    # which can only remove bits, and neither touches the mode of a file that already exists.
    path.touch(mode=_TOKEN_FILE_MODE)
    path.chmod(_TOKEN_FILE_MODE)
    if owner := {name: value for name, value in (('user', user), ('group', group)) if value}:
        shutil.chown(path, **owner)
    if group:
        # The directory has to be traversable by the group for the file inside it to be reachable,
        # but it is shared, so it is given the group without being given away.
        shutil.chown(path.parent, group=group)
    path.write_text(f'{token.strip()}\n', encoding='utf-8')
    log.info('Wrote `%s`.', path)
    return path


def stored_token(key: str, kind: ServiceKind | None = None) -> str | None:
    """
    Read a token written by :py:func:`store_token`.

    Parameters
    ----------
    key : str
        Keyring key the token belongs to, which is a username.
    kind : ServiceKind | None
        Kind of service the token is for. Both locations are tried when this is not given, since a
        daemon is not told which kind installed it.

    Returns
    -------
    str | None
        The token, or ``None`` if there is no readable file holding one.
    """
    for one in ((kind,) if kind is not None else (None, 'systemd-system')):
        path = token_path(key, one)
        try:
            if token := path.read_text(encoding='utf-8').strip():
                return token
        except FileNotFoundError:
            log.debug('No token file at `%s`.', path)
        except OSError as e:
            log.warning('Could not read the token at `%s`: %s', path, e)
    return None


def github_token(key: str, kind: ServiceKind | None = None) -> str | None:
    """
    Get the GitHub token for a keyring key, from the keyring or from where it was stored.

    The keyring is asked first, so a machine that has one behaves as it always has. A machine
    without one, which is the usual case for a service running as another account, falls back to
    the file :py:func:`store_token` wrote.

    Parameters
    ----------
    key : str
        Keyring key the token belongs to, which is a username.
    kind : ServiceKind | None
        Kind of service the token is for.

    Returns
    -------
    str | None
        The token, or ``None`` if neither source has one.
    """
    with suppress(keyring.errors.KeyringError):
        if token := keyring.get_password(KEYRING_SERVICE, key):
            return token
    return stored_token(key, kind)


async def _seen_notifications(gh: gidgethub.abc.GitHubAPI) -> set[str]:
    # A blip while the daemon is starting must not end it, since whatever restarts it meets the
    # same blip. Starting with nothing seen costs one pass that finds nothing to do.
    try:
        return set(await _pull_request_notifications(gh))
    except (OSError, gidgethub.GitHubException) as e:
        log.warning('Could not read notifications: %s', e)
        return set()


async def _pull_request_notifications(gh: gidgethub.abc.GitHubAPI) -> dict[str, str]:
    return {
        thread['id']: (thread.get('subject') or {}).get('url') or ''
        async for thread in gh.getiter('/notifications{?per_page}', {'per_page': 100})
        if (thread.get('subject') or {}).get('type') == 'PullRequest'
    }


async def _authored_by(gh: gidgethub.abc.GitHubAPI, url: str, login: str) -> bool:
    if not url:
        return False
    try:
        pull = await gh.getitem(url)
    except (OSError, gidgethub.GitHubException) as e:
        # Treated as not worth waking for. The periodic pass reaches it either way, which beats
        # re-reading a pull request that cannot be read, once a minute, forever.
        log.warning('Could not read `%s`: %s', url, e)
        return False
    return bool(((pull or {}).get('user') or {}).get('login') == login)


async def watch_and_merge(run: Callable[[], Awaitable[None]],
                          *,
                          bot_login: str,
                          token: str,
                          base_url: str | None = None,
                          poll: float = DEFAULT_NOTIFICATION_POLL_SECONDS,
                          sweep: float = DEFAULT_SWEEP_SECONDS) -> None:
    """
    Merge whenever the bot's pull request is notified about, and periodically regardless.

    The notifications feed is read rather than waited on, since GitHub delivers notifications only
    to a public HTTPS endpoint. An unchanged feed is answered with ``304 Not Modified``, which
    costs no rate limit, so reading it every minute is cheap.

    A notification arrives only for a repository the account is subscribed to and has new pull
    request notifications enabled for. The feed is therefore what makes the daemon quick and the
    periodic pass is what makes it correct.

    Only a notification about a pull request ``bot_login`` opened wakes the merge, since anything
    else would cost a pass over every repository to merge nothing. The author is not in the
    notification, so each one that has not been seen before costs a request to find out.

    Parameters
    ----------
    run : Callable[[], Awaitable[None]]
        What to await when something may have changed. Anything it raises other than
        :py:class:`BotMergeError` ends the watch.
    bot_login : str
        Login whose pull requests are worth waking for, such as :py:data:`DEPENDABOT_LOGIN`.
    token : str
        The GitHub token.
    base_url : str | None
        The base URL of the GitHub API (for enterprise).
    poll : float
        Shortest wait between reads of the feed. ``X-Poll-Interval`` wins when it is longer.
    sweep : float
        Longest wait between passes, regardless of what the feed reports.
    """
    # gidgethub turns this into the conditional request that makes an unchanged feed free.
    cache: dict[str, Any] = {}
    async with niquests.AsyncSession() as session:
        gh = _make_github_api(session, base_url=base_url, cache=cache, token=token)
        seen = await _seen_notifications(gh)
        log.info(
            'Watching notifications for %s. A repository without new pull request'
            ' notifications enabled is reached only every %.0f seconds.', bot_login, sweep)
        await _run_and_log(run)
        # Measured from when a pass finished rather than from when it started, so that one taking
        # longer than the wait does not leave every pass after it immediately due.
        last = time.monotonic()
        while True:
            await anyio.sleep(max(poll, getattr(gh, 'poll_interval', 0.0)))
            # Only the feed's own entry earns its keep, since it is what makes an unchanged feed
            # free. A pull request is read once and never again, and this runs for as long as the
            # machine is up.
            for url in [url for url in cache if _NOTIFICATIONS_URL not in url]:
                del cache[url]
            try:
                threads = await _pull_request_notifications(gh)
            except (OSError, gidgethub.GitHubException) as e:
                log.warning('Could not read notifications: %s', e)
                continue
            new = set(threads) - seen
            seen = set(threads)
            woken = [thread for thread in new if await _authored_by(gh, threads[thread], bot_login)]
            if not woken and (time.monotonic() - last) < sweep:
                continue
            if woken:
                log.info('%d new %s pull %s.', len(woken), bot_login,
                         pluralize(len(woken), 'request'))
            await _run_and_log(run)
            last = time.monotonic()


async def _run_and_log(run: Callable[[], Awaitable[None]]) -> None:
    try:
        await run()
    except BotMergeError as e:
        # The next pass tries again, so this is not what ends the daemon.
        log.warning('%s', e)
