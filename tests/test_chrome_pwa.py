from __future__ import annotations

from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock

import pytest

from deltona.chrome.pwa import fix_chromium_pwa_icon

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
    mock_async_session = mocker.patch('deltona.chrome.pwa.AsyncSession')
    mock_async_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_async_session.return_value.__aexit__ = AsyncMock(return_value=False)
    return cast('Mock', mock_response)


@pytest.fixture
def mock_get_pil_image_module(mocker: MockerFixture, mock_pil_image_module: tuple[Mock,
                                                                                  Mock]) -> Mock:
    mock_image_mod, _ = mock_pil_image_module
    mocker.patch('deltona.chrome.pwa._get_pil_image_module', return_value=mock_image_mod)
    return mock_image_mod


@pytest.mark.asyncio
async def test_fix_chromium_pwa_icon_basic(tmp_path: Path, mock_get_pil_image_module: Mock,
                                           mock_async_session_get: Mock,
                                           mock_pil_image_module: tuple[Mock, Mock]) -> None:
    app_id = 'test_app_id'
    icon_src_uri = 'http://example.com/icon.png'
    config_path = tmp_path
    profile = 'Default'
    mock_img = mock_pil_image_module[1]

    await fix_chromium_pwa_icon(config_path, app_id, icon_src_uri, profile)

    mock_async_session_get.raise_for_status.assert_called_once()
    mock_get_pil_image_module.open.assert_called_once()
    assert mock_img.save.call_count > 0
    for call in mock_img.save.call_args_list:
        file_path = call.args[0]
        assert 'Icons' in str(file_path)


@pytest.mark.asyncio
async def test_fix_chromium_pwa_icon_masked(tmp_path: Path, mock_get_pil_image_module: Mock,
                                            mock_async_session_get: Mock,
                                            mock_pil_image_module: tuple[Mock, Mock]) -> None:
    app_id = 'test_app_id'
    icon_src_uri = 'http://example.com/icon.png'
    config_path = tmp_path
    profile = 'Default'
    mock_img = mock_pil_image_module[1]

    await fix_chromium_pwa_icon(config_path, app_id, icon_src_uri, profile, masked=True)

    paths = [call.args[0] for call in mock_img.save.call_args_list]
    assert any('Icons Maskable' in str(p) for p in paths)
    assert any('Icons' in str(p) for p in paths)


@pytest.mark.asyncio
async def test_fix_chromium_pwa_icon_monochrome(mocker: MockerFixture,
                                                mock_get_pil_image_module: Mock,
                                                mock_async_session_get: Mock,
                                                mock_pil_image_module: tuple[Mock, Mock]) -> None:
    mock_path = mocker.patch('deltona.chrome.pwa.Path').return_value
    app_id = 'test_app_id'
    icon_src_uri = 'http://example.com/icon.png'
    config_path = mocker.MagicMock()
    config_path.__fspath__.return_value = 'some-config'
    profile = 'Default'
    mock_img = mock_pil_image_module[1]

    await fix_chromium_pwa_icon(config_path, app_id, icon_src_uri, profile, monochrome=True)

    assert any(x.args[0] for x in mock_path.mock_calls if x.args[0] == 'Icons Monochrome')
    assert any(x.args[0] for x in mock_path.mock_calls if x.args[0] == 'Icons')
    assert mock_img.save.call_count == 8


@pytest.mark.asyncio
async def test_fix_chromium_pwa_icon_not_square(tmp_path: Path, mock_get_pil_image_module: Mock,
                                                mock_async_session_get: Mock,
                                                mock_pil_image_module: tuple[Mock, Mock]) -> None:
    app_id = 'test_app_id'
    icon_src_uri = 'http://example.com/icon.png'
    config_path = tmp_path
    profile = 'Default'
    mock_img = mock_pil_image_module[1]
    mock_img.size = (128, 64)  # Not square
    with pytest.raises(ValueError, match='Icon is not square'):
        await fix_chromium_pwa_icon(config_path, app_id, icon_src_uri, profile)
