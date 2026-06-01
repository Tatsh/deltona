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


class FakeGitHub:
    """In-memory GitHub API used to drive :py:mod:`deltona.git` through niquests."""

    _MERGE = re.compile(r'^/repos/(?P<full>[^/]+/[^/]+)/pulls/(?P<num>\d+)/merge$')
    _PULL = re.compile(r'^/repos/(?P<full>[^/]+/[^/]+)/pulls/(?P<num>\d+)$')
    _PULLS = re.compile(r'^/repos/(?P<full>[^/]+/[^/]+)/pulls$')
    _CONTENTS = re.compile(r'^/repos/(?P<full>[^/]+/[^/]+)/contents/(?P<path>.+)$')
    _COMMENTS = re.compile(r'^/repos/(?P<full>[^/]+/[^/]+)/issues/(?P<num>\d+)/comments$')
    _REPO = re.compile(r'^/repos/(?P<full>[^/]+/[^/]+)$')

    def __init__(self) -> None:
        self.user_login = 'tatsh'
        self.repos: dict[str, FakeRepo] = {}
        self.listing: list[str] = []
        self.requests: list[tuple[str, str]] = []
        self.repo_gets: list[str] = []
        self.merge_calls: list[tuple[str, int, dict[str, Any]]] = []
        self.posted_comments: list[tuple[str, int, str]] = []
        self.user_endpoint_hit = False
        self.list_repos_hit = False
        self.list_repos_query: dict[str, str] = {}

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

    def route(self, method: str, url: str, data: bytes | None) -> tuple[int, Any]:
        parts = urlsplit(url)
        path = parts.path
        self.requests.append((method, path))
        if path == '/user':
            self.user_endpoint_hit = True
            return 200, {'login': self.user_login}
        if path == '/user/repos':
            self.list_repos_hit = True
            self.list_repos_query = {k: v[0] for k, v in parse_qs(parts.query).items()}
            return 200, [self.repos[name].payload() for name in self.listing]
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
