from __future__ import annotations

from typing import TYPE_CHECKING

from deltona.gmail import GmailError, archive_github_pull_request_email, get_access_token
import niquests
import pytest

if TYPE_CHECKING:
    from tests.conftest import FakeGitHub

CREDENTIALS_JSON = ('{"client_id": "id", "client_secret": "secret", "refresh_token": "refresh", '
                    '"type": "authorized_user"}')


@pytest.mark.asyncio
async def test_get_access_token(fake_github: FakeGitHub) -> None:
    async with niquests.AsyncSession() as session:
        token = await get_access_token(session, credentials=CREDENTIALS_JSON)
    assert token == fake_github.gmail.access_token
    assert fake_github.gmail.token_requests == [{
        'client_id': 'id',
        'client_secret': 'secret',
        'grant_type': 'refresh_token',
        'refresh_token': 'refresh'
    }]


@pytest.mark.asyncio
async def test_get_access_token_invalid_json(fake_github: FakeGitHub) -> None:
    async with niquests.AsyncSession() as session:
        with pytest.raises(GmailError, match='valid JSON'):
            await get_access_token(session, credentials='not json')


@pytest.mark.asyncio
async def test_get_access_token_missing_field(fake_github: FakeGitHub) -> None:
    async with niquests.AsyncSession() as session:
        with pytest.raises(GmailError, match='missing'):
            await get_access_token(session, credentials='{"client_id": "id"}')


@pytest.mark.asyncio
async def test_get_access_token_endpoint_error(fake_github: FakeGitHub) -> None:
    fake_github.gmail.token_status = 400
    fake_github.gmail.token_payload = {'error': 'invalid_grant'}
    async with niquests.AsyncSession() as session:
        with pytest.raises(GmailError, match='HTTP 400'):
            await get_access_token(session, credentials=CREDENTIALS_JSON)


@pytest.mark.asyncio
async def test_get_access_token_no_token_in_response(fake_github: FakeGitHub) -> None:
    fake_github.gmail.token_payload = {'expires_in': 3599}
    async with niquests.AsyncSession() as session:
        with pytest.raises(GmailError, match='did not return'):
            await get_access_token(session, credentials=CREDENTIALS_JSON)


@pytest.mark.asyncio
async def test_archive_github_pull_request_email(fake_github: FakeGitHub) -> None:
    fake_github.gmail.thread_ids = ['a', 'b']
    async with niquests.AsyncSession() as session:
        archived = await archive_github_pull_request_email(session,
                                                           access_token='token',
                                                           full_name='tatsh/repo',
                                                           number=478)
    assert archived == 2
    assert fake_github.gmail.archived_threads == ['a', 'b']
    assert fake_github.gmail.queries == ['list:repo.tatsh.github.com subject:"(PR #478)"']


@pytest.mark.asyncio
async def test_archive_github_pull_request_email_matches_a_reply(fake_github: FakeGitHub) -> None:
    # A reply carries a per-event Message-ID, so only the List-ID and subject can match it.
    fake_github.gmail.thread_ids_by_query = {
        'list:other-repo.Tatsh.github.com subject:"(PR #478)"': ['reply-thread']
    }
    async with niquests.AsyncSession() as session:
        archived = await archive_github_pull_request_email(session,
                                                           access_token='token',
                                                           full_name='Tatsh/other-repo',
                                                           number=478)
    assert archived == 1
    assert fake_github.gmail.archived_threads == ['reply-thread']


@pytest.mark.asyncio
async def test_archive_github_pull_request_email_no_match(fake_github: FakeGitHub) -> None:
    async with niquests.AsyncSession() as session:
        archived = await archive_github_pull_request_email(session,
                                                           access_token='token',
                                                           full_name='tatsh/repo',
                                                           number=1)
    assert archived == 0
    assert fake_github.gmail.archived_threads == []


@pytest.mark.asyncio
async def test_archive_github_pull_request_email_search_error(fake_github: FakeGitHub) -> None:
    fake_github.gmail.search_status = 403
    async with niquests.AsyncSession() as session:
        with pytest.raises(GmailError, match='HTTP 403'):
            await archive_github_pull_request_email(session,
                                                    access_token='token',
                                                    full_name='tatsh/repo',
                                                    number=1)


@pytest.mark.asyncio
async def test_archive_github_pull_request_email_modify_error(fake_github: FakeGitHub) -> None:
    fake_github.gmail.thread_ids = ['a']
    fake_github.gmail.modify_status = 500
    async with niquests.AsyncSession() as session:
        with pytest.raises(GmailError, match='HTTP 500'):
            await archive_github_pull_request_email(session,
                                                    access_token='token',
                                                    full_name='tatsh/repo',
                                                    number=1)
