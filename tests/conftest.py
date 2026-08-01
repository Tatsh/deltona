"""Configuration for Pytest."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, NoReturn
from urllib.parse import parse_qs, urlsplit
import json
import os
import re

from click.testing import CliRunner
import pytest

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pytest_mock import MockerFixture
    from typing_extensions import Self

if os.getenv('_PYTEST_RAISE', '0') != '0':  # pragma no cover

    @pytest.hookimpl(tryfirst=True)
    def pytest_exception_interact(call: pytest.CallInfo[None]) -> NoReturn:
        assert call.excinfo is not None
        raise call.excinfo.value

    @pytest.hookimpl(tryfirst=True)
    def pytest_internalerror(excinfo: pytest.ExceptionInfo[BaseException]) -> NoReturn:
        raise excinfo.value


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@dataclass
class FakePull:
    number: int
    user_login: str = 'dependabot[bot]'
    merged: bool = True
    merge_error: int | None = None
    get_error: int | None = None
    comments: list[str] = field(default_factory=list)


@dataclass
class FakeRepo:
    full_name: str
    archived: bool = False
    security_status: str | None = None
    default_branch: str = 'main'
    files: set[str] = field(default_factory=set)
    contents_exc: dict[str, BaseException] = field(default_factory=dict)
    pulls: list[FakePull] = field(default_factory=list)
    pulls_error: int | None = None

    @property
    def name(self) -> str:
        return self.full_name.split('/')[-1]

    def payload(self, *, full: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            'archived': self.archived,
            'default_branch': self.default_branch,
            'full_name': self.full_name,
            'name': self.name,
        }
        # Mirror GitHub: security_and_analysis is only returned by the single-repository
        # endpoint, never by the /user/repos list endpoint.
        if full and self.security_status is not None:
            data['security_and_analysis'] = {
                'dependabot_security_updates': {
                    'status': self.security_status
                }
            }
        return data


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self.headers = {'content-type': 'application/json; charset=utf-8'}
        self.content = b'' if payload is None else json.dumps(payload).encode()
        self._payload = payload

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> Any:
        return self._payload


class FakeGmail:
    """In-memory Gmail API used to drive :py:mod:`deltona.gmail` through niquests."""

    _MODIFY = re.compile(r'/users/me/threads/(?P<id>[^/]+)/modify$')

    def __init__(self) -> None:
        self.access_token = 'fake_access_token'
        self.token_status = 200
        self.token_payload: Any = None
        self.search_status = 200
        self.modify_status = 200
        self.thread_ids: list[str] = []
        self.thread_ids_by_query: dict[str, list[str]] | None = None
        self.queries: list[str] = []
        self.archived_threads: list[str] = []
        self.token_requests: list[Mapping[str, str]] = []

    def route(self, method: str, url: str, params: Mapping[str, str] | None,
              data: Mapping[str, str] | None) -> tuple[int, Any]:
        if url.startswith('https://oauth2.googleapis.com/token'):
            self.token_requests.append(dict(data or {}))
            if self.token_payload is not None:
                return self.token_status, self.token_payload
            return self.token_status, {'access_token': self.access_token}
        if (match := self._MODIFY.search(url)):
            if self.modify_status >= 400:
                return self.modify_status, {'error': {'message': 'modify failed'}}
            self.archived_threads.append(match['id'])
            return self.modify_status, {'id': match['id']}
        if url.endswith('/users/me/threads'):
            query = (params or {}).get('q', '')
            self.queries.append(query)
            if self.search_status >= 400:
                return self.search_status, {'error': {'message': 'search failed'}}
            thread_ids = (self.thread_ids if self.thread_ids_by_query is None else
                          self.thread_ids_by_query.get(query, []))
            return 200, {'threads': [{'id': thread_id} for thread_id in thread_ids]}
        msg = f'Unhandled Gmail route: {method} {url}'
        raise AssertionError(msg)


class _FakeAsyncSession:
    def __init__(self, fake: FakeGitHub) -> None:
        self._fake = fake

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def request(self,
                      method: str,
                      url: str,
                      *,
                      headers: Mapping[str, str] | None = None,
                      data: bytes | None = None) -> _FakeResponse:
        status, payload = self._fake.route(method, url, data)
        return _FakeResponse(status, payload)

    async def get(self,
                  url: str,
                  *,
                  headers: Mapping[str, str] | None = None,
                  params: Mapping[str, str] | None = None) -> _FakeResponse:
        status, payload = self._fake.gmail.route('GET', url, params, None)
        return _FakeResponse(status, payload)

    async def post(self,
                   url: str,
                   *,
                   headers: Mapping[str, str] | None = None,
                   data: Mapping[str, str] | None = None,
                   json: Mapping[str, Any] | None = None) -> _FakeResponse:
        status, payload = self._fake.gmail.route('POST', url, None, data)
        return _FakeResponse(status, payload)


class FakeGitHub:
    """In-memory GitHub API used to drive :py:mod:`deltona.git` through niquests."""

    _MERGE = re.compile(r'^/repos/(?P<full>[^/]+/[^/]+)/pulls/(?P<num>\d+)/merge$')
    _PULL = re.compile(r'^/repos/(?P<full>[^/]+/[^/]+)/pulls/(?P<num>\d+)$')
    _PULLS = re.compile(r'^/repos/(?P<full>[^/]+/[^/]+)/pulls$')
    _CONTENTS = re.compile(r'^/repos/(?P<full>[^/]+/[^/]+)/contents/(?P<path>.+)$')
    _COMMENTS = re.compile(r'^/repos/(?P<full>[^/]+/[^/]+)/issues/(?P<num>\d+)/comments$')
    _REPO = re.compile(r'^/repos/(?P<full>[^/]+/[^/]+)$')
    _THREAD = re.compile(r'^/notifications/threads/(?P<id>[^/]+)$')

    def __init__(self) -> None:
        self.user_login = 'tatsh'
        self.user_email: str | None = 'tatsh@example.com'
        self.repos: dict[str, FakeRepo] = {}
        self.listing: list[str] = []
        self.requests: list[tuple[str, str]] = []
        self.repo_gets: list[str] = []
        self.merge_calls: list[tuple[str, int, dict[str, Any]]] = []
        self.posted_comments: list[tuple[str, int, str]] = []
        self.user_endpoint_hit = False
        self.list_repos_hit = False
        self.list_repos_query: dict[str, str] = {}
        self.gmail = FakeGmail()
        self.notifications: list[dict[str, Any]] = []
        self.threads_marked_done: list[str] = []
        self.thread_delete_error: int | None = None

    def add_repo(self, full_name: str, *, listed: bool = True, **kwargs: Any) -> FakeRepo:
        repo = FakeRepo(full_name, **kwargs)
        self.repos[full_name] = repo
        if listed:
            self.listing.append(full_name)
        return repo

    def add_pull(self,
                 full_name: str,
                 number: int,
                 *,
                 user_login: str = 'dependabot[bot]',
                 **kwargs: Any) -> FakePull:
        pull = FakePull(number=number, user_login=user_login, **kwargs)
        self.repos[full_name].pulls.append(pull)
        return pull

    def add_notification(self,
                         full_name: str,
                         number: int,
                         *,
                         thread_id: str,
                         subject_type: str = 'PullRequest') -> None:
        self.notifications.append({
            'id': thread_id,
            'repository': {
                'full_name': full_name
            },
            'subject': {
                'type': subject_type,
                'url': f'https://api.github.com/repos/{full_name}/pulls/{number}'
            }
        })

    def route(self, method: str, url: str, data: bytes | None) -> tuple[int, Any]:
        parts = urlsplit(url)
        path = parts.path
        self.requests.append((method, path))
        if path == '/user':
            self.user_endpoint_hit = True
            return 200, {'email': self.user_email, 'login': self.user_login}
        if path == '/user/repos':
            self.list_repos_hit = True
            self.list_repos_query = {k: v[0] for k, v in parse_qs(parts.query).items()}
            return 200, [self.repos[name].payload() for name in self.listing]
        if (result := self._route_notifications(path)) is not None:
            return result
        if (match := self._MERGE.match(path)):
            return self._route_merge(match, data)
        if (match := self._PULL.match(path)):
            return self._route_pull(match)
        if (match := self._PULLS.match(path)):
            return self._route_pulls(match)
        if (match := self._CONTENTS.match(path)):
            return self._route_contents(match)
        if (match := self._COMMENTS.match(path)):
            return self._route_comments(method, match, data)
        if (match := self._REPO.match(path)):
            self.repo_gets.append(match['full'])
            return 200, self.repos[match['full']].payload(full=True)
        msg = f'Unhandled route: {method} {path}'
        raise AssertionError(msg)

    def _route_notifications(self, path: str) -> tuple[int, Any] | None:
        if path == '/notifications':
            return 200, self.notifications
        if (match := self._THREAD.match(path)):
            if self.thread_delete_error is not None:
                return self.thread_delete_error, {'message': 'thread failed'}
            self.threads_marked_done.append(match['id'])
            return 204, None
        return None

    def _find_pull(self, full: str, number: int) -> FakePull:
        return next(p for p in self.repos[full].pulls if p.number == number)

    def _route_merge(self, match: re.Match[str], data: bytes | None) -> tuple[int, Any]:
        full, number = match['full'], int(match['num'])
        body = json.loads(data) if data else {}
        self.merge_calls.append((full, number, body))
        pull = self._find_pull(full, number)
        if pull.merge_error is not None:
            return pull.merge_error, {'message': 'merge failed'}
        return 200, {'merged': pull.merged}

    def _route_pull(self, match: re.Match[str]) -> tuple[int, Any]:
        full, number = match['full'], int(match['num'])
        pull = self._find_pull(full, number)
        if pull.get_error is not None:
            return pull.get_error, {'message': 'pull failed'}
        return 200, {'number': pull.number, 'user': {'login': pull.user_login}}

    def _route_pulls(self, match: re.Match[str]) -> tuple[int, Any]:
        repo = self.repos[match['full']]
        if repo.pulls_error is not None:
            return repo.pulls_error, {'message': 'pulls failed'}
        return 200, [{'number': p.number, 'user': {'login': p.user_login}} for p in repo.pulls]

    def _route_contents(self, match: re.Match[str]) -> tuple[int, Any]:
        repo = self.repos[match['full']]
        path = match['path']
        if path in repo.contents_exc:
            raise repo.contents_exc[path]
        if path in repo.files:
            return 200, {'path': path}
        return 404, {'message': 'Not Found'}

    def _route_comments(self, method: str, match: re.Match[str],
                        data: bytes | None) -> tuple[int, Any]:
        full, number = match['full'], int(match['num'])
        pull = self._find_pull(full, number)
        if method == 'POST':
            body = json.loads(data)['body'] if data else ''
            self.posted_comments.append((full, number, body))
            pull.comments.append(body)
            return 201, {'body': body}
        return 200, [{'body': c} for c in pull.comments]


@pytest.fixture
def fake_github(mocker: MockerFixture) -> FakeGitHub:
    fake = FakeGitHub()
    mocker.patch('niquests.AsyncSession', return_value=_FakeAsyncSession(fake))
    return fake
