from __future__ import annotations

from typing import TYPE_CHECKING, Any
import io
import json
import logging
import urllib.error

from deltona.gmail import (
    REDIRECT_URI,
    GmailAuthorizationError,
    GmailConfigurationError,
    GmailError,
    archive_github_pull_request_email,
    authorize,
    get_access_token,
)
import niquests
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

    from pytest_mock import MockerFixture
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
        with pytest.raises(GmailError, match='missing') as exc_info:
            await get_access_token(session, credentials='{"client_id": "id"}')
    # The keys present are named so that the wrong credential shape is obvious.
    assert 'client_id' in str(exc_info.value)


@pytest.mark.parametrize('wrapper', ['installed', 'web'])
@pytest.mark.asyncio
async def test_get_access_token_unwraps_client_secret(fake_github: FakeGitHub,
                                                      wrapper: str) -> None:
    credentials = json.dumps({wrapper: json.loads(CREDENTIALS_JSON)})
    async with niquests.AsyncSession() as session:
        token = await get_access_token(session, credentials=credentials)
    assert token == fake_github.gmail.access_token


@pytest.mark.asyncio
async def test_get_access_token_client_secret_without_refresh_token(
        fake_github: FakeGitHub) -> None:
    credentials = json.dumps({'installed': {'client_id': 'id', 'client_secret': 'secret'}})
    async with niquests.AsyncSession() as session:
        with pytest.raises(GmailError, match='refresh_token') as exc_info:
            await get_access_token(session, credentials=credentials)
    assert 'client secret' in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_access_token_endpoint_error(fake_github: FakeGitHub) -> None:
    fake_github.gmail.token_status = 400
    fake_github.gmail.token_payload = {
        'error': 'invalid_grant',
        'error_description': 'Token has been expired or revoked.'
    }
    async with niquests.AsyncSession() as session:
        with pytest.raises(GmailAuthorizationError) as exc_info:
            await get_access_token(session, credentials=CREDENTIALS_JSON)
    # What Google said, not a guess about it, and its own full stop must not double up.
    assert str(exc_info.value) == ('The Google token endpoint returned HTTP 400: Token has been '
                                   'expired or revoked.')


@pytest.mark.asyncio
async def test_get_access_token_endpoint_error_without_a_description(
        fake_github: FakeGitHub) -> None:
    fake_github.gmail.token_status = 400
    fake_github.gmail.token_payload = {'error': 'invalid_client'}
    async with niquests.AsyncSession() as session:
        with pytest.raises(GmailAuthorizationError, match='invalid_client'):
            await get_access_token(session, credentials=CREDENTIALS_JSON)


@pytest.mark.asyncio
async def test_get_access_token_endpoint_error_with_a_non_json_body(
        fake_github: FakeGitHub, raw_body: Callable[[str], dict[str, str]]) -> None:
    fake_github.gmail.token_status = 500
    fake_github.gmail.token_payload = raw_body('<html>Gateway Timeout</html>')
    async with niquests.AsyncSession() as session:
        with pytest.raises(GmailAuthorizationError, match='HTTP 500'):
            await get_access_token(session, credentials=CREDENTIALS_JSON)


@pytest.mark.asyncio
async def test_get_access_token_endpoint_error_with_an_unexpected_body(
        fake_github: FakeGitHub) -> None:
    fake_github.gmail.token_status = 500
    fake_github.gmail.token_payload = ['unexpected']
    async with niquests.AsyncSession() as session:
        with pytest.raises(GmailAuthorizationError, match='HTTP 500'):
            await get_access_token(session, credentials=CREDENTIALS_JSON)


@pytest.mark.asyncio
async def test_get_access_token_no_token_in_response(fake_github: FakeGitHub) -> None:
    fake_github.gmail.token_payload = {'expires_in': 3599}
    async with niquests.AsyncSession() as session:
        with pytest.raises(GmailError, match='did not return'):
            await get_access_token(session, credentials=CREDENTIALS_JSON)


REDIRECTED_URL = f'{REDIRECT_URI}/?code=the-code&scope=https://mail.google.com/'


def _fake_token_response(mocker: MockerFixture, payload: dict[str, Any]) -> None:
    response = mocker.MagicMock()
    response.__enter__.return_value = io.StringIO(json.dumps(payload))
    mocker.patch('deltona.gmail.urllib.request.urlopen', return_value=response)


def test_authorize(mocker: MockerFixture) -> None:
    _fake_token_response(mocker, {'refresh_token': 'the-refresh-token'})
    result = json.loads(authorize(CREDENTIALS_JSON, read_redirect=lambda: REDIRECTED_URL))
    assert result == {
        'client_id': 'id',
        'client_secret': 'secret',
        'refresh_token': 'the-refresh-token',
        'type': 'authorized_user'
    }


def test_authorize_accepts_a_pasted_url_with_surrounding_space(mocker: MockerFixture) -> None:
    _fake_token_response(mocker, {'refresh_token': 'the-refresh-token'})
    credentials = authorize(CREDENTIALS_JSON, read_redirect=lambda: f'  {REDIRECTED_URL}  \n')
    assert json.loads(credentials)['refresh_token'] == 'the-refresh-token'


def test_authorize_reports_the_url_to_notify(mocker: MockerFixture) -> None:
    _fake_token_response(mocker, {'refresh_token': 'the-refresh-token'})
    notified: list[str] = []
    authorize(CREDENTIALS_JSON, notify=notified.append, read_redirect=lambda: REDIRECTED_URL)
    assert len(notified) == 1
    assert 'accounts.google.com' in notified[0]
    assert 'access_type=offline' in notified[0]
    assert 'prompt=consent' in notified[0]
    # The user has to be told that the failed connection is expected.
    assert REDIRECT_URI in notified[0]


def test_authorize_unwraps_client_secret(mocker: MockerFixture) -> None:
    _fake_token_response(mocker, {'refresh_token': 'the-refresh-token'})
    credentials = json.dumps({'installed': {'client_id': 'id', 'client_secret': 'secret'}})
    result = authorize(credentials, read_redirect=lambda: REDIRECTED_URL)
    assert json.loads(result)['refresh_token'] == 'the-refresh-token'


def test_authorize_invalid_json() -> None:
    with pytest.raises(GmailConfigurationError, match='valid JSON'):
        authorize('not json', read_redirect=lambda: REDIRECTED_URL)


def test_authorize_missing_field() -> None:
    with pytest.raises(GmailConfigurationError, match='missing'):
        authorize('{"client_id": "id"}', read_redirect=lambda: REDIRECTED_URL)


@pytest.mark.parametrize('pasted', [f'{REDIRECT_URI}/?error=access_denied', 'nonsense', ''])
def test_authorize_pasted_url_without_a_code(pasted: str) -> None:
    with pytest.raises(GmailConfigurationError, match='no authorisation code'):
        authorize(CREDENTIALS_JSON, read_redirect=lambda: pasted)


def test_authorize_no_refresh_token(mocker: MockerFixture) -> None:
    _fake_token_response(mocker, {'access_token': 'only-an-access-token'})
    with pytest.raises(GmailConfigurationError, match='no refresh token'):
        authorize(CREDENTIALS_JSON, read_redirect=lambda: REDIRECTED_URL)


def test_authorize_token_endpoint_rejects_code(mocker: MockerFixture) -> None:
    mocker.patch('deltona.gmail.urllib.request.urlopen',
                 side_effect=urllib.error.URLError('bad request'))
    with pytest.raises(GmailConfigurationError, match='rejected the authorisation code'):
        authorize(CREDENTIALS_JSON, read_redirect=lambda: REDIRECTED_URL)


def test_authorize_logs_the_url_without_notify(caplog: pytest.LogCaptureFixture,
                                               mocker: MockerFixture) -> None:
    _fake_token_response(mocker, {'refresh_token': 'the-refresh-token'})
    with caplog.at_level(logging.INFO, logger='deltona.gmail'):
        authorize(CREDENTIALS_JSON, read_redirect=lambda: REDIRECTED_URL)
    assert any('Open this URL' in record.getMessage() for record in caplog.records)


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
    # Marking read as well as archiving, and never restricted to the inbox, so a thread archived
    # by an earlier run is still found and still gets marked read.
    assert all(
        body == {'removeLabelIds': ['INBOX', 'UNREAD']} for body in fake_github.gmail.modify_bodies)
    assert 'in:inbox' not in fake_github.gmail.queries[0]
    assert 'label:' not in fake_github.gmail.queries[0]


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
    fake_github.gmail.search_status = 500
    async with niquests.AsyncSession() as session:
        with pytest.raises(GmailError, match='HTTP 500') as exc_info:
            await archive_github_pull_request_email(session,
                                                    access_token='token',
                                                    full_name='tatsh/repo',
                                                    number=1)
    # A server-side failure is transient, so it must not be reported as misconfiguration.
    assert not isinstance(exc_info.value, GmailConfigurationError)


@pytest.mark.parametrize('status', [401, 403])
@pytest.mark.asyncio
async def test_archive_github_pull_request_email_rejected_token(fake_github: FakeGitHub,
                                                                status: int) -> None:
    fake_github.gmail.search_status = status
    async with niquests.AsyncSession() as session:
        with pytest.raises(GmailConfigurationError, match='scope'):
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
