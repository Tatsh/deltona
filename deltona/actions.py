"""GitHub Actions-related utilities."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple
import asyncio
import logging
import re

import niquests

from .git import _make_github_api
from .string import pluralize

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    import gidgethub.abc

__all__ = ('NEVER_RETRY_EVENTS', 'RETRY_RULES', 'RetryCandidate', 'RetryRule',
           'find_retryable_runs', 'rerun_failed_jobs')

log = logging.getLogger(__name__)


class RetryRule(NamedTuple):
    """A failure caused by something other than the code under test."""

    step: re.Pattern[str]
    """Matches the name of the step that failed."""
    error: re.Pattern[str]
    """Matches the failing job's log. This decides the outcome, not the step name."""
    reason: str
    """Why the failure is transient, shown to the user."""


RETRY_RULES = (
    RetryRule(step=re.compile(r'coveralls', re.IGNORECASE),
              error=re.compile(
                  r'internal server error|502 bad gateway|503 service unavailable|'
                  r'504 gateway time-?out', re.IGNORECASE),
              reason='Coveralls returned a server error.'),
    RetryRule(step=re.compile(r'^install (dependencies|uv)\b|setup-msys2', re.IGNORECASE),
              error=re.compile(
                  r'rate limit exceeded|429 too many requests|connection reset by peer|'
                  r'temporary failure in name resolution|failed to establish a new connection',
                  re.IGNORECASE),
              reason='A package source refused the request rather than the request being wrong.'),
    RetryRule(step=re.compile(r'python-appimage|create appimage', re.IGNORECASE),
              error=re.compile(r'rate limit exceeded', re.IGNORECASE),
              reason='python-appimage hit an anonymous GitHub API rate limit.'),
)
"""Rules deciding which failures may be retried.

A failure qualifies only when the name of the step that failed and the text of the job's log both
match the same rule. The log decides: a step name on its own proved too coarse, because
``Install dependencies`` covers both a rate limit and a stale lockfile, and only the former is
worth running again.

:meta hide-value:
"""

NEVER_RETRY_EVENTS = frozenset({'dynamic'})
"""Events whose runs are never started again, whatever their log says.

Dependabot drives its update runs through the ``dynamic`` event. They are recreated with
``@dependabot recreate`` rather than run again, and they install dependencies like any other run,
so without this they would be eligible whenever a package source rate limited them. They are also
the largest single group of failures, at 188 of the 313 observed across the owner's repositories.

:meta hide-value:
"""


class RetryCandidate(NamedTuple):
    """A failed workflow run whose failure matched a rule."""

    repo: str
    """Repository full name."""
    run_id: int
    """Workflow run identifier."""
    workflow: str
    """Name of the workflow that failed."""
    job: str
    """Name of the job that failed."""
    step: str
    """Name of the step that failed."""
    attempt: int
    """Which attempt failed."""
    rule: RetryRule
    """The rule that matched."""
    url: str
    """Link to the run."""


def _matching_rule(step: str, text: str) -> RetryRule | None:
    return next(
        (rule for rule in RETRY_RULES if rule.step.search(step) and rule.error.search(text)), None)


async def _job_log(session: niquests.AsyncSession, *, base_url: str, job_id: int, repo: str,
                   token: str) -> str:
    # Not fetched through gidgethub: the endpoint answers with a redirect to a plain text blob
    # rather than JSON.
    response = await session.get(f'{base_url}/repos/{repo}/actions/jobs/{job_id}/logs',
                                 headers={
                                     'Accept': 'application/vnd.github+json',
                                     'Authorization': f'Bearer {token}'
                                 })
    if not response.ok:
        log.debug('No log for job %d of `%s` (HTTP %s).', job_id, repo, response.status_code)
        return ''
    return response.text or ''


async def _candidates_for_run(session: niquests.AsyncSession, gh: gidgethub.abc.GitHubAPI, *,
                              base_url: str, repo: str, run: Mapping[str, Any],
                              token: str) -> list[RetryCandidate]:
    found: list[RetryCandidate] = []
    jobs = await gh.getitem(f'/repos/{repo}/actions/runs/{run["id"]}/jobs?per_page=100')
    for job in jobs.get('jobs') or ():
        if job.get('conclusion') != 'failure':
            continue
        if not (steps :=
                [s['name'] for s in job.get('steps') or () if s.get('conclusion') == 'failure']):
            continue
        text = await _job_log(session, base_url=base_url, job_id=job['id'], repo=repo, token=token)
        for step in steps:
            if (rule := _matching_rule(step, text)) is not None:
                found.append(
                    RetryCandidate(repo=repo,
                                   run_id=run['id'],
                                   workflow=run.get('name') or '',
                                   job=job.get('name') or '',
                                   step=step,
                                   attempt=run.get('run_attempt') or 1,
                                   rule=rule,
                                   url=run.get('html_url') or ''))
                break
    return found


async def _resolve_repos(gh: gidgethub.abc.GitHubAPI,
                         repos: Iterable[str] | None) -> tuple[str, ...]:
    if repos is None:
        return tuple([
            repo['full_name']
            async for repo in gh.getiter('/user/repos{?visibility,sort,per_page}', {
                'per_page': 100,
                'sort': 'full_name',
                'visibility': 'all'
            }) if not repo['archived']
        ])
    specs = list(repos)
    login = ((await gh.getitem('/user'))['login'] if any('/' not in spec for spec in specs) else '')
    return tuple(spec if '/' in spec else f'{login}/{spec}' for spec in specs)


async def find_retryable_runs(*,
                              token: str,
                              repos: Iterable[str] | None = None,
                              base_url: str | None = None,
                              max_attempts: int = 2,
                              since: str | None = None,
                              concurrency: int = 4) -> list[RetryCandidate]:
    """
    Find failed workflow runs whose failure matches a rule in :py:data:`RETRY_RULES`.

    Parameters
    ----------
    token : str
        A GitHub token with access to the repositories.
    repos : Iterable[str] | None
        Repositories to examine, each given as ``NAME`` or ``OWNER/NAME``. Every repository the
        token can see, archived ones aside, is examined when this is ``None``.
    base_url : str | None
        Base URL of the GitHub API, for enterprise instances.
    max_attempts : int
        Leave a run alone once it has been attempted this many times, so that a failure which
        recurs on every attempt is not run again indefinitely.
    since : str | None
        Only consider runs created on or after this ISO 8601 date.
    concurrency : int
        Greatest number of repositories examined at once.

    Returns
    -------
    list[RetryCandidate]
        Every failed run that matched, in the order the repositories were given. A repository that
        could not be examined is logged and skipped rather than failing the whole search.
    """
    api_base = base_url or 'https://api.github.com'
    limiter = asyncio.Semaphore(concurrency)
    query = 'status=failure&per_page=50' + (f'&created=>={since}' if since else '')

    async def for_repo(session: niquests.AsyncSession, gh: gidgethub.abc.GitHubAPI,
                       repo: str) -> list[RetryCandidate]:
        async with limiter:
            runs = await gh.getitem(f'/repos/{repo}/actions/runs?{query}')
            found: list[RetryCandidate] = []
            for run in runs.get('workflow_runs') or ():
                if run.get('event') in NEVER_RETRY_EVENTS:
                    log.debug('Skipping run %d of `%s`, a %s run.', run['id'], repo,
                              run.get('event'))
                    continue
                if (run.get('run_attempt') or 1) >= max_attempts:
                    log.debug('Skipping run %d of `%s`, already attempted %s times.', run['id'],
                              repo, run.get('run_attempt'))
                    continue
                found.extend(await _candidates_for_run(session,
                                                       gh,
                                                       base_url=api_base,
                                                       repo=repo,
                                                       run=run,
                                                       token=token))
            return found

    async with niquests.AsyncSession() as session:
        gh = _make_github_api(session, base_url=base_url, token=token)
        repo_names = await _resolve_repos(gh, repos)
        log.debug('Examining %d %s.', len(repo_names),
                  pluralize(len(repo_names), 'repository', 'repositories'))
        gathered = await asyncio.gather(*(for_repo(session, gh, repo) for repo in repo_names),
                                        return_exceptions=True)
    candidates: list[RetryCandidate] = []
    for repo, outcome in zip(repo_names, gathered, strict=True):
        if isinstance(outcome, BaseException):
            log.warning('Could not examine `%s`: %s', repo, outcome)
            continue
        candidates.extend(outcome)
    return candidates


async def rerun_failed_jobs(*,
                            token: str,
                            candidates: Iterable[RetryCandidate],
                            base_url: str | None = None) -> int:
    """
    Ask GitHub to run the failed jobs of each given run again.

    Only the jobs that failed are run again, so anything that already passed is left alone.

    Parameters
    ----------
    token : str
        A GitHub token carrying write access to Actions.
    candidates : Iterable[RetryCandidate]
        Runs to start again.
    base_url : str | None
        Base URL of the GitHub API, for enterprise instances.

    Returns
    -------
    int
        How many runs GitHub accepted. A run it refused is logged and counted as not started.
    """
    import gidgethub  # ruff:ignore[import-outside-top-level]

    started = 0
    async with niquests.AsyncSession() as session:
        gh = _make_github_api(session, base_url=base_url, token=token)
        for candidate in candidates:
            try:
                await gh.post(
                    f'/repos/{candidate.repo}/actions/runs/{candidate.run_id}/rerun-failed-jobs',
                    data={})
            except gidgethub.HTTPException as e:
                log.warning('Could not run job of `%s` run %d again: %s', candidate.repo,
                            candidate.run_id, e)
                continue
            log.debug('Started run %d of `%s` again.', candidate.run_id, candidate.repo)
            started += 1
    return started
