from __future__ import annotations

from typing import TYPE_CHECKING
import plistlib

from deltona import www
from requests import HTTPError
import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture
    from requests_mock import Mocker


def test_upload_to_imgbb_with_api_key(tmp_path: Path, mocker: MockerFixture,
                                      requests_mock: Mocker) -> None:
    # Create a dummy image file
    img_path = tmp_path / 'test.png'
    img_path.write_bytes(b'fake-image-data')

    # Mock requests.post
    url = 'https://api.imgbb.com/1/upload'
    expected_response = {'data': {'url': 'https://imgbb.com/test.png'}}
    requests_mock.post(url, json=expected_response, status_code=200)

    # Call function
    r = www.upload_to_imgbb(str(img_path), api_key='dummy-key', timeout=1)
    assert r.status_code == 200
    assert r.json() == expected_response


def test_upload_to_imgbb_with_keyring(tmp_path: Path, mocker: MockerFixture,
                                      requests_mock: Mocker) -> None:
    # Create a dummy image file
    img_path = tmp_path / 'test2.png'
    img_path.write_bytes(b'another-fake-image-data')

    # Mock keyring.get_password
    mocker.patch('keyring.get_password', return_value='keyring-key')
    # Mock getuser
    mocker.patch('deltona.www.getuser', return_value='testuser')

    # Mock requests.post
    url = 'https://api.imgbb.com/1/upload'
    expected_response = {'data': {'url': 'https://imgbb.com/test2.png'}}
    requests_mock.post(url, json=expected_response, status_code=200)

    # Call function without api_key, but with keyring_username
    r = www.upload_to_imgbb(str(img_path), keyring_username='testuser', timeout=1)
    assert r.status_code == 200
    assert r.json() == expected_response


def test_upload_to_imgbb_raises_for_status(tmp_path: Path, mocker: MockerFixture,
                                           requests_mock: Mocker) -> None:
    img_path = tmp_path / 'fail.png'
    img_path.write_bytes(b'fail-data')

    requests_mock.post('https://api.imgbb.com/1/upload',
                       status_code=400,
                       json={'error': 'bad request'})
    with pytest.raises(HTTPError):
        www.upload_to_imgbb(str(img_path), api_key='bad-key', timeout=1)


def test_check_bookmarks_html_urls_basic(mocker: MockerFixture, requests_mock: Mocker) -> None:
    # Minimal bookmarks.html with two links: one valid, one 404
    html = """
    <DL>
        <DT><A HREF="https://example.com" ADD_DATE="123">Example</A>
        <DT><A HREF="https://notfound.com" ADD_DATE="456">NotFound</A>
    </DL>
    """
    # Mock HEAD requests
    requests_mock.head('https://example.com', status_code=200)
    requests_mock.head('https://notfound.com', status_code=404)

    # Patch user agent generator to avoid dependency
    mocker.patch('deltona.www.generate_chrome_user_agent', return_value='UA')

    data, changed, not_found = www.check_bookmarks_html_urls(html)
    # Should have both links in data
    assert len(data) == 2
    # No changed links
    assert changed == []
    # One not found
    assert len(not_found) == 1
    assert not_found[0]['attrs']['href'] == 'https://notfound.com'  # type: ignore[typeddict-item]
    assert not_found[0]['title'] == 'NotFound'  # type: ignore[typeddict-item]


def test_check_bookmarks_html_urls_redirect(mocker: MockerFixture, requests_mock: Mocker) -> None:
    html = """
    <DL>
        <DT><A HREF="https://redirect.com" ADD_DATE="789">Redirected</A>
    </DL>
    """
    # Simulate 301 redirect
    requests_mock.head('https://redirect.com', status_code=301, headers={'location': '/new-loc'})
    # Patch user agent generator
    mocker.patch('deltona.www.generate_chrome_user_agent', return_value='UA')

    data, changed, not_found = www.check_bookmarks_html_urls(html)
    # Should have one link in data
    assert len(data) == 1
    # Should have one changed link
    assert len(changed) == 1
    # The href should be rewritten to absolute
    assert changed[0]['attrs']['href'].endswith('/new-loc')  # type: ignore[typeddict-item]
    assert changed[0]['title'] == 'Redirected'  # type: ignore[typeddict-item]
    # No not found
    assert not_found == []


def test_where_from_linux(mocker: MockerFixture) -> None:
    # Simulate IS_LINUX = True
    mocker.patch('deltona.www.IS_LINUX', True)  # noqa: FBT003
    # Mock getxattr to return bytes
    mock_getxattr = mocker.patch('deltona.www._getxattr', return_value=b'https://example.com')
    # Should return the decoded string
    result = www.where_from('dummy-file')
    assert result == 'https://example.com'
    mock_getxattr.assert_called_once_with('dummy-file', www.KEY_ORIGIN_URL)


def test_where_from_macos_webpage_false(mocker: MockerFixture) -> None:
    # Simulate IS_LINUX = False
    mocker.patch('deltona.www.IS_LINUX', False)  # noqa: FBT003
    # Prepare fake plist data
    fake_plist = plistlib.dumps(['https://file.com', 'https://webpage.com'])
    # Patch hexstr2bytes to just return the bytes
    mocker.patch('deltona.www.hexstr2bytes', return_value=fake_plist)
    # Mock getxattr to return a dummy value (will be passed to hexstr2bytes)
    mock_getxattr = mocker.patch('deltona.www._getxattr', return_value=b'dummy')
    # Should return the first item (index 0)
    result = www.where_from('dummy-file', webpage=False)
    assert result == 'https://file.com'
    mock_getxattr.assert_called_once_with('dummy-file', www.KEY_WHERE_FROMS)


def test_where_from_macos_webpage_true(mocker: MockerFixture) -> None:
    # Simulate IS_LINUX = False
    mocker.patch('deltona.www.IS_LINUX', False)  # noqa: FBT003
    # Prepare fake plist data
    fake_plist = plistlib.dumps(['https://file.com', 'https://webpage.com'])
    # Patch hexstr2bytes to just return the bytes
    mocker.patch('deltona.www.hexstr2bytes', return_value=fake_plist)
    # Mock getxattr to return a dummy value (will be passed to hexstr2bytes)
    mock_getxattr = mocker.patch('deltona.www._getxattr', return_value=b'dummy')
    # Should return the second item (index 1)
    result = www.where_from('dummy-file', webpage=True)
    assert result == 'https://webpage.com'
    mock_getxattr.assert_called_once_with('dummy-file', www.KEY_WHERE_FROMS)
