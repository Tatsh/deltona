"""Tests for :py:mod:`deltona.chrome.version`."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from deltona.chrome.version import (
    generate_chrome_user_agent,
    get_last_chrome_major_version,
    get_latest_chrome_major_version,
)

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture


@pytest.mark.asyncio
async def test_get_last_chrome_major_version_found(mocker: MockerFixture, tmp_path: Path) -> None:
    (tmp_path / 'google-chrome-beta').mkdir()
    (tmp_path / 'google-chrome-beta' / 'Last Version').write_text('123.0.0.0', encoding='utf-8')
    mocker.patch('deltona.chrome.version.chrome_config_directory',
                 side_effect=lambda channel: tmp_path / f'google-chrome-{channel}')
    get_last_chrome_major_version.cache_clear()
    assert await get_last_chrome_major_version() == '123'


@pytest.mark.asyncio
async def test_get_last_chrome_major_version_prefers_an_earlier_channel(
        mocker: MockerFixture, tmp_path: Path) -> None:
    for channel, version in (('beta', '120.0.0.0'), ('stable', '119.0.0.0')):
        (tmp_path / f'google-chrome-{channel}').mkdir()
        (tmp_path / f'google-chrome-{channel}' / 'Last Version').write_text(version,
                                                                            encoding='utf-8')
    mocker.patch('deltona.chrome.version.chrome_config_directory',
                 side_effect=lambda channel: tmp_path / f'google-chrome-{channel}')
    get_last_chrome_major_version.cache_clear()
    assert await get_last_chrome_major_version() == '120'


@pytest.mark.asyncio
async def test_get_last_chrome_major_version_not_found(mocker: MockerFixture,
                                                       tmp_path: Path) -> None:
    mocker.patch('deltona.chrome.version.chrome_config_directory',
                 side_effect=lambda channel: tmp_path / f'google-chrome-{channel}')
    get_last_chrome_major_version.cache_clear()
    assert not await get_last_chrome_major_version()


@pytest.mark.asyncio
async def test_get_latest_chrome_major_version_success(mocker: MockerFixture) -> None:
    mock_response = mocker.Mock()
    mock_response.json.return_value = {'versions': [{'version': '124.0.6367.60'}]}
    mock_session = mocker.MagicMock()
    mock_session.get = AsyncMock(return_value=mock_response)
    mock_async_session = mocker.patch('deltona.chrome.version.AsyncSession')
    mock_async_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_async_session.return_value.__aexit__ = AsyncMock(return_value=False)
    get_latest_chrome_major_version.cache_clear()
    result = await get_latest_chrome_major_version()
    assert result == '124'


@pytest.mark.asyncio
async def test_get_latest_chrome_major_version_alt(mocker: MockerFixture) -> None:
    mock_response = mocker.Mock()
    mock_response.json.return_value = {'versions': [{'version': '125.0.6422.60'}]}
    mock_session = mocker.MagicMock()
    mock_session.get = AsyncMock(return_value=mock_response)
    mock_async_session = mocker.patch('deltona.chrome.version.AsyncSession')
    mock_async_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_async_session.return_value.__aexit__ = AsyncMock(return_value=False)
    get_latest_chrome_major_version.cache_clear()
    result = await get_latest_chrome_major_version()
    assert result == '125'


@pytest.mark.asyncio
async def test_get_latest_chrome_major_version_network_error(mocker: MockerFixture) -> None:
    mock_session = mocker.MagicMock()
    mock_session.get = AsyncMock(side_effect=Exception('Network error'))
    mock_async_session = mocker.patch('deltona.chrome.version.AsyncSession')
    mock_async_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_async_session.return_value.__aexit__ = AsyncMock(return_value=False)
    get_latest_chrome_major_version.cache_clear()
    with pytest.raises(Exception, match='Network error'):
        await get_latest_chrome_major_version()


@pytest.mark.asyncio
async def test_generate_chrome_user_agent_with_last_major(mocker: MockerFixture) -> None:
    mocker.patch('deltona.chrome.version.get_last_chrome_major_version',
                 new=AsyncMock(return_value='123'))
    mocker.patch('deltona.chrome.version.get_latest_chrome_major_version',
                 new=AsyncMock(return_value='999'))
    generate_chrome_user_agent.cache_clear()
    ua = await generate_chrome_user_agent()
    assert 'Chrome/123.0.0.0' in ua
    assert ua.startswith('Mozilla/5.0 (Windows NT 10.0; Win64; x64)')


@pytest.mark.asyncio
async def test_generate_chrome_user_agent_with_latest_major(mocker: MockerFixture) -> None:
    mocker.patch('deltona.chrome.version.get_last_chrome_major_version',
                 new=AsyncMock(return_value=''))
    mocker.patch('deltona.chrome.version.get_latest_chrome_major_version',
                 new=AsyncMock(return_value='456'))
    generate_chrome_user_agent.cache_clear()
    ua = await generate_chrome_user_agent()
    assert 'Chrome/456.0.0.0' in ua


@pytest.mark.asyncio
async def test_generate_chrome_user_agent_custom_os(mocker: MockerFixture) -> None:
    mocker.patch('deltona.chrome.version.get_last_chrome_major_version',
                 new=AsyncMock(return_value='789'))
    generate_chrome_user_agent.cache_clear()
    ua = await generate_chrome_user_agent('Linux x86_64')
    assert ua.startswith('Mozilla/5.0 (Linux x86_64)')
    assert 'Chrome/789.0.0.0' in ua


@pytest.mark.asyncio
async def test_generate_chrome_user_agent_cache(mocker: MockerFixture) -> None:
    get_last = mocker.patch('deltona.chrome.version.get_last_chrome_major_version',
                            new=AsyncMock(return_value='321'))
    generate_chrome_user_agent.cache_clear()
    ua1 = await generate_chrome_user_agent()
    ua2 = await generate_chrome_user_agent()
    assert ua1 == ua2
    get_last.assert_called_once()
