"""Tests for the actions module."""

from __future__ import annotations

from typing import TYPE_CHECKING

from deltona.actions import find_retryable_runs, rerun_failed_jobs
import pytest

if TYPE_CHECKING:
    from .conftest import FakeGitHub

COVERALLS_LOG = '⚠️ Internal server error. Please contact Coveralls team.'
LOCKFILE_LOG = ('YN0028: The lockfile would have been modified by this install, which is '
                'explicitly forbidden.')
OPENSSL_LOG = 'error: failed to build `maturin`\nCould not find openssl via pkg-config'
RATE_LIMIT_LOG = 'urllib.error.HTTPError: HTTP Error 403: rate limit exceeded'


@pytest.mark.asyncio
async def test_find_retryable_runs_matches_coveralls(fake_github: FakeGitHub) -> None:
    fake_github.add_repo('tatsh/deltona')
    fake_github.add_run('tatsh/deltona', 1, workflow='Tests')
    fake_github.add_job(1, 10, failed_steps=['Coveralls'], log=COVERALLS_LOG, name='coverage')
    found = await find_retryable_runs(repos=['tatsh/deltona'], token='t')
    assert len(found) == 1
    assert found[0].repo == 'tatsh/deltona'
    assert found[0].run_id == 1
    assert found[0].job == 'coverage'
    assert found[0].step == 'Coveralls'
    assert found[0].workflow == 'Tests'
    assert found[0].rule.reason == 'Coveralls returned a server error.'
    assert found[0].url == 'https://github.com/tatsh/deltona/actions/runs/1'


@pytest.mark.asyncio
@pytest.mark.parametrize(('step', 'log'), [('Install dependencies (Yarn)', LOCKFILE_LOG),
                                           ('Install dependencies (uv)', OPENSSL_LOG),
                                           ('Lint with mypy', COVERALLS_LOG),
                                           ('Run Dependabot', COVERALLS_LOG),
                                           ('Run tests', 'assert 1 == 2'),
                                           ('Coveralls', 'assert 1 == 2')])
async def test_find_retryable_runs_leaves_real_failures_alone(fake_github: FakeGitHub, step: str,
                                                              log: str) -> None:
    fake_github.add_repo('tatsh/deltona')
    fake_github.add_run('tatsh/deltona', 1)
    fake_github.add_job(1, 10, failed_steps=[step], log=log)
    assert await find_retryable_runs(repos=['tatsh/deltona'], token='t') == []


@pytest.mark.asyncio
async def test_find_retryable_runs_never_touches_a_dependabot_run(fake_github: FakeGitHub) -> None:
    # A Dependabot update run installs dependencies like any other, so without the event guard a
    # rate limited one would match the install rule.
    fake_github.add_repo('tatsh/deltona')
    fake_github.add_run('tatsh/deltona', 1, event='dynamic', workflow='uv in /. - Update #1')
    fake_github.add_job(1,
                        10,
                        failed_steps=['Install dependencies (uv)'],
                        log='error: HTTP status 429 Too Many Requests')
    assert await find_retryable_runs(repos=['tatsh/deltona'], token='t') == []


@pytest.mark.asyncio
async def test_find_retryable_runs_allows_the_same_failure_on_a_push_run(
        fake_github: FakeGitHub) -> None:
    fake_github.add_repo('tatsh/deltona')
    fake_github.add_run('tatsh/deltona', 1, event='push')
    fake_github.add_job(1,
                        10,
                        failed_steps=['Install dependencies (uv)'],
                        log='error: HTTP status 429 Too Many Requests')
    assert len(await find_retryable_runs(repos=['tatsh/deltona'], token='t')) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(('step', 'log'), [('Coveralls', COVERALLS_LOG),
                                           ('Upload coverage to Coveralls', ('error: 503 Service '
                                                                             'Unavailable')),
                                           ('Install dependencies (uv)', ('error: HTTP status 429 '
                                                                          'Too Many Requests')),
                                           ('Install uv', 'connection reset by peer'),
                                           ('Build with python-appimage', RATE_LIMIT_LOG),
                                           ('Create AppImage', RATE_LIMIT_LOG)])
async def test_find_retryable_runs_matches_transient_failures(fake_github: FakeGitHub, step: str,
                                                              log: str) -> None:
    fake_github.add_repo('tatsh/deltona')
    fake_github.add_run('tatsh/deltona', 1)
    fake_github.add_job(1, 10, failed_steps=[step], log=log)
    assert len(await find_retryable_runs(repos=['tatsh/deltona'], token='t')) == 1


@pytest.mark.asyncio
async def test_find_retryable_runs_respects_max_attempts(fake_github: FakeGitHub) -> None:
    fake_github.add_repo('tatsh/deltona')
    fake_github.add_run('tatsh/deltona', 1, attempt=2)
    fake_github.add_job(1, 10, failed_steps=['Coveralls'], log=COVERALLS_LOG)
    assert await find_retryable_runs(repos=['tatsh/deltona'], token='t') == []
    assert len(await find_retryable_runs(max_attempts=3, repos=['tatsh/deltona'], token='t')) == 1


@pytest.mark.asyncio
async def test_find_retryable_runs_ignores_jobs_that_passed(fake_github: FakeGitHub) -> None:
    fake_github.add_repo('tatsh/deltona')
    fake_github.add_run('tatsh/deltona', 1)
    # A step allowed to fail leaves the job green. There is nothing to start again.
    fake_github.add_job(1, 10, conclusion='success', failed_steps=['Coveralls'], log=COVERALLS_LOG)
    fake_github.add_job(1, 11, failed_steps=[], log=COVERALLS_LOG, passed_steps=['Coveralls'])
    assert await find_retryable_runs(repos=['tatsh/deltona'], token='t') == []


@pytest.mark.asyncio
async def test_find_retryable_runs_reports_one_candidate_per_job(fake_github: FakeGitHub) -> None:
    fake_github.add_repo('tatsh/deltona')
    fake_github.add_run('tatsh/deltona', 1)
    fake_github.add_job(1,
                        10,
                        failed_steps=['Coveralls', 'Upload coverage to Coveralls'],
                        log=COVERALLS_LOG)
    found = await find_retryable_runs(repos=['tatsh/deltona'], token='t')
    assert len(found) == 1
    assert found[0].step == 'Coveralls'


@pytest.mark.asyncio
async def test_find_retryable_runs_survives_an_unreadable_log(fake_github: FakeGitHub) -> None:
    fake_github.add_repo('tatsh/deltona')
    fake_github.add_run('tatsh/deltona', 1)
    fake_github.add_job(1, 10, failed_steps=['Coveralls'], log=COVERALLS_LOG)
    fake_github.job_log_errors[10] = 404
    assert await find_retryable_runs(repos=['tatsh/deltona'], token='t') == []


@pytest.mark.asyncio
async def test_find_retryable_runs_skips_archived_repositories(fake_github: FakeGitHub) -> None:
    fake_github.add_repo('tatsh/deltona')
    fake_github.add_repo('tatsh/old', archived=True)
    for name in ('tatsh/deltona', 'tatsh/old'):
        fake_github.add_run(name, 1 if name == 'tatsh/deltona' else 2)
    fake_github.add_job(1, 10, failed_steps=['Coveralls'], log=COVERALLS_LOG)
    fake_github.add_job(2, 20, failed_steps=['Coveralls'], log=COVERALLS_LOG)
    found = await find_retryable_runs(token='t')
    assert [c.repo for c in found] == ['tatsh/deltona']


@pytest.mark.asyncio
async def test_find_retryable_runs_expands_a_bare_repository_name(fake_github: FakeGitHub) -> None:
    fake_github.add_repo('tatsh/deltona')
    fake_github.add_run('tatsh/deltona', 1)
    fake_github.add_job(1, 10, failed_steps=['Coveralls'], log=COVERALLS_LOG)
    found = await find_retryable_runs(repos=['deltona'], token='t')
    assert [c.repo for c in found] == ['tatsh/deltona']
    assert fake_github.user_endpoint_hit


@pytest.mark.asyncio
async def test_find_retryable_runs_skips_a_repository_it_cannot_read(
        fake_github: FakeGitHub) -> None:
    for name in ('tatsh/broken', 'tatsh/deltona'):
        fake_github.add_repo(name)
        fake_github.add_run(name, 1 if name == 'tatsh/broken' else 2)
    fake_github.runs_errors['tatsh/broken'] = 403
    fake_github.add_job(2, 20, failed_steps=['Coveralls'], log=COVERALLS_LOG)
    found = await find_retryable_runs(repos=['tatsh/broken', 'tatsh/deltona'], token='t')
    assert [c.repo for c in found] == ['tatsh/deltona']


@pytest.mark.asyncio
async def test_find_retryable_runs_passes_since_to_the_api(fake_github: FakeGitHub) -> None:
    fake_github.add_repo('tatsh/deltona')
    await find_retryable_runs(repos=['tatsh/deltona'], since='2026-08-17', token='t')
    assert fake_github.runs_query['created'] == '>=2026-08-17'
    assert fake_github.runs_query['status'] == 'failure'


@pytest.mark.asyncio
async def test_rerun_failed_jobs(fake_github: FakeGitHub) -> None:
    fake_github.add_repo('tatsh/deltona')
    fake_github.add_run('tatsh/deltona', 1)
    fake_github.add_job(1, 10, failed_steps=['Coveralls'], log=COVERALLS_LOG)
    found = await find_retryable_runs(repos=['tatsh/deltona'], token='t')
    assert await rerun_failed_jobs(candidates=found, token='t') == 1
    assert fake_github.rerun_calls == [('tatsh/deltona', 1)]


@pytest.mark.asyncio
async def test_rerun_failed_jobs_counts_a_refusal_as_not_started(fake_github: FakeGitHub) -> None:
    fake_github.add_repo('tatsh/deltona')
    for run_id, job_id in ((1, 10), (2, 20)):
        fake_github.add_run('tatsh/deltona', run_id)
        fake_github.add_job(run_id, job_id, failed_steps=['Coveralls'], log=COVERALLS_LOG)
    fake_github.rerun_errors[1] = 403
    found = await find_retryable_runs(repos=['tatsh/deltona'], token='t')
    assert len(found) == 2
    assert await rerun_failed_jobs(candidates=found, token='t') == 1
    assert fake_github.rerun_calls == [('tatsh/deltona', 2)]
