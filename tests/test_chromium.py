from __future__ import annotations

from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock

from deltona.chromium import (
    fix_chromium_pwa_icon,
    generate_chrome_user_agent,
    get_last_chrome_major_version,
    get_latest_chrome_major_version,
)
import pytest

if TYPE_CHECKING:
    from pathlib import Path
    from unittest.mock import Mock

    from pytest_mock import MockerFixture


@pytest.fixture
def mock_pil_image_module(mocker: MockerFixture) -> tuple[Mock, Mock]:
    mock_img = mocker.Mock()
    mock_img.size = (128, 128)
    mock_img.resize.return_value = mock_img
    mock_img.save = mocker.Mock()
    mock_image_mod = mocker.Mock()
    mock_image_mod.open.return_value = mock_img
    mock_image_mod.LANCZOS = 'LANCZOS'
    return mock_image_mod, mock_img


@pytest.fixture
def mock_async_session_get(mocker: MockerFixture) -> Mock:
    mock_response = mocker.Mock()
    mock_response.content = b'fake-image'
    mock_session = mocker.MagicMock()
    mock_session.get = AsyncMock(return_value=mock_response)
    mock_async_session = mocker.patch('deltona.chromium.AsyncSession')
    mock_async_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_async_session.return_value.__aexit__ = AsyncMock(return_value=False)
    return cast('Mock', mock_response)


@pytest.fixture
def mock_get_pil_image_module(mocker: MockerFixture, mock_pil_image_module: tuple[Mock,
                                                                                  Mock]) -> Mock:
    mock_image_mod, _ = mock_pil_image_module
    mocker.patch('deltona.chromium._get_pil_image_module', return_value=mock_image_mod)
    return mock_image_mod


@pytest.mark.asyncio
async def test_fix_chromium_pwa_icon_basic(
    tmp_path: Path,
    mock_get_pil_image_module: Mock,
    mock_async_session_get: Mock,
    mock_pil_image_module: tuple[Mock, Mock],
) -> None:
    app_id = 'test_app_id'
    icon_src_uri = 'http://example.com/icon.png'
    config_path = tmp_path
    profile = 'Default'
    mock_img = mock_pil_image_module[1]

    await fix_chromium_pwa_icon(config_path, app_id, icon_src_uri, profile)

    # Check that raise_for_status was called
    mock_async_session_get.raise_for_status.assert_called_once()
    # Check that PIL.Image.open was called
    mock_get_pil_image_module.open.assert_called_once()
    # Check that save was called for each size
    assert mock_img.save.call_count > 0
    # Check that files would be saved in the correct directory
    for call in mock_img.save.call_args_list:
        file_path = call.args[0]
        assert 'Icons' in str(file_path)


@pytest.mark.asyncio
async def test_fix_chromium_pwa_icon_masked(
    tmp_path: Path,
    mock_get_pil_image_module: Mock,
    mock_async_session_get: Mock,
    mock_pil_image_module: tuple[Mock, Mock],
) -> None:
    app_id = 'test_app_id'
    icon_src_uri = 'http://example.com/icon.png'
    config_path = tmp_path
    profile = 'Default'
    mock_img = mock_pil_image_module[1]

    await fix_chromium_pwa_icon(config_path, app_id, icon_src_uri, profile, masked=True)

    # Should save to both Icons and Icons Maskable
    paths = [call.args[0] for call in mock_img.save.call_args_list]
    assert any('Icons Maskable' in str(p) for p in paths)
    assert any('Icons' in str(p) for p in paths)


@pytest.mark.asyncio
async def test_fix_chromium_pwa_icon_monochrome(
    mocker: MockerFixture,
    mock_get_pil_image_module: Mock,
    mock_async_session_get: Mock,
    mock_pil_image_module: tuple[Mock, Mock],
) -> None:
    mock_path = mocker.patch('deltona.chromium.Path').return_value
    app_id = 'test_app_id'
    icon_src_uri = 'http://example.com/icon.png'
    config_path = mocker.MagicMock()
    config_path.__fspath__.return_value = 'some-config'
    profile = 'Default'
    mock_img = mock_pil_image_module[1]

    await fix_chromium_pwa_icon(config_path, app_id, icon_src_uri, profile, monochrome=True)

    # Should save to both Icons and Icons Monochrome
    assert any(x.args[0] for x in mock_path.mock_calls if x.args[0] == 'Icons Monochrome')
    assert any(x.args[0] for x in mock_path.mock_calls if x.args[0] == 'Icons')
    assert mock_img.save.call_count == 8


@pytest.mark.asyncio
async def test_fix_chromium_pwa_icon_not_square(
    tmp_path: Path,
    mock_get_pil_image_module: Mock,
    mock_async_session_get: Mock,
    mock_pil_image_module: tuple[Mock, Mock],
) -> None:
    app_id = 'test_app_id'
    icon_src_uri = 'http://example.com/icon.png'
    config_path = tmp_path
    profile = 'Default'
    mock_img = mock_pil_image_module[1]
    mock_img.size = (128, 64)  # Not square
    with pytest.raises(ValueError, match='Icon is not square'):
        await fix_chromium_pwa_icon(config_path, app_id, icon_src_uri, profile)


@pytest.mark.asyncio
async def test_get_last_chrome_major_version_found(mocker: MockerFixture) -> None:
    mock_path = mocker.patch('deltona.chromium.anyio.Path')
    mock_expanded = mocker.MagicMock()
    mock_version_path = mocker.MagicMock()
    mock_version_path.exists = AsyncMock(return_value=True)
    mock_version_path.read_text = AsyncMock(return_value='123.0.0.0')
    mock_expanded.__truediv__ = mocker.Mock(return_value=mock_version_path)
    mock_path.return_value.expanduser = AsyncMock(return_value=mock_expanded)
    get_last_chrome_major_version.cache_clear()
    result = await get_last_chrome_major_version()
    assert result == '123'


@pytest.mark.asyncio
async def test_get_last_chrome_major_version_not_found(mocker: MockerFixture) -> None:
    mock_path = mocker.patch('deltona.chromium.anyio.Path')
    mock_expanded = mocker.MagicMock()
    mock_version_path = mocker.MagicMock()
    mock_version_path.exists = AsyncMock(return_value=False)
    mock_expanded.__truediv__ = mocker.Mock(return_value=mock_version_path)
    mock_path.return_value.expanduser = AsyncMock(return_value=mock_expanded)
    get_last_chrome_major_version.cache_clear()
    result = await get_last_chrome_major_version()
    assert not result


@pytest.mark.asyncio
async def test_get_latest_chrome_major_version_success(mocker: MockerFixture) -> None:
    mock_response = mocker.Mock()
    mock_response.json.return_value = {'versions': [{'version': '124.0.6367.60'}]}
    mock_session = mocker.MagicMock()
    mock_session.get = AsyncMock(return_value=mock_response)
    mock_async_session = mocker.patch('deltona.chromium.AsyncSession')
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
    mock_async_session = mocker.patch('deltona.chromium.AsyncSession')
    mock_async_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_async_session.return_value.__aexit__ = AsyncMock(return_value=False)
    get_latest_chrome_major_version.cache_clear()
    result = await get_latest_chrome_major_version()
    assert result == '125'


@pytest.mark.asyncio
async def test_get_latest_chrome_major_version_network_error(mocker: MockerFixture) -> None:
    mock_session = mocker.MagicMock()
    mock_session.get = AsyncMock(side_effect=Exception('Network error'))
    mock_async_session = mocker.patch('deltona.chromium.AsyncSession')
    mock_async_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_async_session.return_value.__aexit__ = AsyncMock(return_value=False)
    get_latest_chrome_major_version.cache_clear()
    with pytest.raises(Exception, match='Network error'):
        await get_latest_chrome_major_version()


@pytest.mark.asyncio
async def test_generate_chrome_user_agent_with_last_major(mocker: MockerFixture) -> None:
    mocker.patch('deltona.chromium.get_last_chrome_major_version',
                 new=AsyncMock(return_value='123'))
    mocker.patch('deltona.chromium.get_latest_chrome_major_version',
                 new=AsyncMock(return_value='999'))
    generate_chrome_user_agent.cache_clear()
    ua = await generate_chrome_user_agent()
    assert 'Chrome/123.0.0.0' in ua
    assert ua.startswith('Mozilla/5.0 (Windows NT 10.0; Win64; x64)')


@pytest.mark.asyncio
async def test_generate_chrome_user_agent_with_latest_major(mocker: MockerFixture) -> None:
    mocker.patch('deltona.chromium.get_last_chrome_major_version', new=AsyncMock(return_value=''))
    mocker.patch('deltona.chromium.get_latest_chrome_major_version',
                 new=AsyncMock(return_value='456'))
    generate_chrome_user_agent.cache_clear()
    ua = await generate_chrome_user_agent()
    assert 'Chrome/456.0.0.0' in ua


@pytest.mark.asyncio
async def test_generate_chrome_user_agent_custom_os(mocker: MockerFixture) -> None:
    mocker.patch('deltona.chromium.get_last_chrome_major_version',
                 new=AsyncMock(return_value='789'))
    generate_chrome_user_agent.cache_clear()
    ua = await generate_chrome_user_agent('Linux x86_64')
    assert ua.startswith('Mozilla/5.0 (Linux x86_64)')
    assert 'Chrome/789.0.0.0' in ua


@pytest.mark.asyncio
async def test_generate_chrome_user_agent_cache(mocker: MockerFixture) -> None:
    get_last = mocker.patch('deltona.chromium.get_last_chrome_major_version',
                            new=AsyncMock(return_value='321'))
    generate_chrome_user_agent.cache_clear()
    ua1 = await generate_chrome_user_agent()
    ua2 = await generate_chrome_user_agent()
    assert ua1 == ua2
    get_last.assert_called_once()
