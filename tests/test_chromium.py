from __future__ import annotations

from typing import TYPE_CHECKING, cast

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
    from requests_mock import Mocker


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
def mock_requests_get(mocker: MockerFixture) -> Mock:
    mock_response = mocker.Mock()
    mock_response.content = b'fake-image'
    mocker.patch('requests.get', return_value=mock_response)
    return cast('Mock', mock_response)


@pytest.fixture
def mock_get_pil_image_module(mocker: MockerFixture, mock_pil_image_module: tuple[Mock,
                                                                                  Mock]) -> Mock:
    mock_image_mod, _ = mock_pil_image_module
    mocker.patch('deltona.chromium._get_pil_image_module', return_value=mock_image_mod)
    return mock_image_mod


def test_fix_chromium_pwa_icon_basic(tmp_path: Path, mock_get_pil_image_module: Mock,
                                     mock_requests_get: Mock,
                                     mock_pil_image_module: tuple[Mock, Mock]) -> None:
    app_id = 'test_app_id'
    icon_src_uri = 'http://example.com/icon.png'
    config_path = tmp_path
    profile = 'Default'
    mock_img = mock_pil_image_module[1]

    fix_chromium_pwa_icon(config_path, app_id, icon_src_uri, profile)

    # Check that requests.get was called
    mock_requests_get.raise_for_status.assert_called_once()
    # Check that PIL.Image.open was called
    mock_get_pil_image_module.open.assert_called_once()
    # Check that save was called for each size
    assert mock_img.save.call_count > 0
    # Check that files would be saved in the correct directory
    for call in mock_img.save.call_args_list:
        file_path = call.args[0]
        assert 'Icons' in str(file_path)


def test_fix_chromium_pwa_icon_masked(tmp_path: Path, mock_get_pil_image_module: Mock,
                                      mock_requests_get: Mock,
                                      mock_pil_image_module: tuple[Mock, Mock]) -> None:
    app_id = 'test_app_id'
    icon_src_uri = 'http://example.com/icon.png'
    config_path = tmp_path
    profile = 'Default'
    mock_img = mock_pil_image_module[1]

    fix_chromium_pwa_icon(config_path, app_id, icon_src_uri, profile, masked=True)

    # Should save to both Icons and Icons Maskable
    paths = [call.args[0] for call in mock_img.save.call_args_list]
    assert any('Icons Maskable' in str(p) for p in paths)
    assert any('Icons' in str(p) for p in paths)


def test_fix_chromium_pwa_icon_monochrome(mocker: MockerFixture, mock_get_pil_image_module: Mock,
                                          mock_requests_get: Mock,
                                          mock_pil_image_module: tuple[Mock, Mock]) -> None:
    mock_path = mocker.patch('deltona.chromium.Path').return_value
    app_id = 'test_app_id'
    icon_src_uri = 'http://example.com/icon.png'
    config_path = mocker.MagicMock()
    config_path.__fspath__.return_value = 'some-config'
    profile = 'Default'
    mock_img = mock_pil_image_module[1]

    fix_chromium_pwa_icon(config_path, app_id, icon_src_uri, profile, monochrome=True)

    # Should save to both Icons and Icons Monochrome
    assert any(x.args[0] for x in mock_path.mock_calls if x.args[0] == 'Icons Monochrome')
    assert any(x.args[0] for x in mock_path.mock_calls if x.args[0] == 'Icons')
    assert mock_img.save.call_count == 8


def test_fix_chromium_pwa_icon_not_square(tmp_path: Path, mock_get_pil_image_module: Mock,
                                          mock_requests_get: Mock,
                                          mock_pil_image_module: tuple[Mock, Mock]) -> None:
    app_id = 'test_app_id'
    icon_src_uri = 'http://example.com/icon.png'
    config_path = tmp_path
    profile = 'Default'
    mock_img = mock_pil_image_module[1]
    mock_img.size = (128, 64)  # Not square
    with pytest.raises(ValueError, match='Icon is not square'):
        fix_chromium_pwa_icon(config_path, app_id, icon_src_uri, profile)


def test_get_last_chrome_major_version_found(mocker: MockerFixture) -> None:
    mock_path = mocker.patch('deltona.chromium.Path')
    mock_instance = mock_path.return_value.expanduser.return_value
    mock_instance.__truediv__.return_value.exists.return_value = True
    mock_instance.__truediv__.return_value.read_text.return_value = '123.0.0.0'
    # Clear cache in case of previous calls
    get_last_chrome_major_version.cache_clear()
    result = get_last_chrome_major_version()
    assert result == '123'


def test_get_last_chrome_major_version_not_found(mocker: MockerFixture) -> None:
    mock_path = mocker.patch('deltona.chromium.Path')
    mock_instance = mock_path.return_value.expanduser.return_value
    mock_instance.__truediv__.return_value.exists.return_value = False
    get_last_chrome_major_version.cache_clear()
    result = get_last_chrome_major_version()
    assert not result


def test_get_latest_chrome_major_version_success(mocker: MockerFixture) -> None:
    # Mock requests.get to return a fake version JSON
    mock_response = mocker.Mock()
    mock_response.json.return_value = {'versions': [{'version': '124.0.6367.60'}]}
    mocker.patch('requests.get', return_value=mock_response)
    get_latest_chrome_major_version.cache_clear()
    result = get_latest_chrome_major_version()
    assert result == '124'


def test_get_latest_chrome_major_version_requests_mock(requests_mock: Mocker) -> None:
    # Use requests-mock to mock the API endpoint
    url = ('https://versionhistory.googleapis.com/v1/chrome/platforms/win/channels/stable/versions')
    requests_mock.get(url, json={'versions': [{'version': '125.0.6422.60'}]})
    get_latest_chrome_major_version.cache_clear()
    result = get_latest_chrome_major_version()
    assert result == '125'


def test_get_latest_chrome_major_version_network_error(mocker: MockerFixture) -> None:
    # Simulate a network error
    mocker.patch('requests.get', side_effect=Exception('Network error'))
    get_latest_chrome_major_version.cache_clear()
    with pytest.raises(Exception, match='Network error'):
        get_latest_chrome_major_version()


def test_generate_chrome_user_agent_with_last_major(mocker: MockerFixture) -> None:
    mocker.patch('deltona.chromium.get_last_chrome_major_version', return_value='123')
    mocker.patch('deltona.chromium.get_latest_chrome_major_version', return_value='999')
    generate_chrome_user_agent.cache_clear()
    ua = generate_chrome_user_agent()
    assert 'Chrome/123.0.0.0' in ua
    assert ua.startswith('Mozilla/5.0 (Windows NT 10.0; Win64; x64)')


def test_generate_chrome_user_agent_with_latest_major(mocker: MockerFixture) -> None:
    mocker.patch('deltona.chromium.get_last_chrome_major_version', return_value='')
    mocker.patch('deltona.chromium.get_latest_chrome_major_version', return_value='456')
    generate_chrome_user_agent.cache_clear()
    ua = generate_chrome_user_agent()
    assert 'Chrome/456.0.0.0' in ua


def test_generate_chrome_user_agent_custom_os(mocker: MockerFixture) -> None:
    mocker.patch('deltona.chromium.get_last_chrome_major_version', return_value='789')
    generate_chrome_user_agent.cache_clear()
    ua = generate_chrome_user_agent('Linux x86_64')
    assert ua.startswith('Mozilla/5.0 (Linux x86_64)')
    assert 'Chrome/789.0.0.0' in ua


def test_generate_chrome_user_agent_cache(mocker: MockerFixture) -> None:
    get_last = mocker.patch('deltona.chromium.get_last_chrome_major_version', return_value='321')
    generate_chrome_user_agent.cache_clear()
    ua1 = generate_chrome_user_agent()
    ua2 = generate_chrome_user_agent()
    assert ua1 == ua2
    get_last.assert_called_once()
