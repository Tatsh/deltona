from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Any
import plistlib

from deltona.www import (
    KEY_ORIGIN_URL,
    KEY_WHERE_FROMS,
    BookmarksDataset,
    BookmarksHTMLFolderAttributes,
    check_bookmarks_html_urls,
    create_parsed_tree_structure,
    generate_html_dir_tree,
    parse_bookmarks_html,
    upload_to_imgbb,
    where_from,
)
from requests import HTTPError
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from bs4 import BeautifulSoup
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
    r = upload_to_imgbb(str(img_path), api_key='dummy-key', timeout=1)
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
    r = upload_to_imgbb(str(img_path), keyring_username='testuser', timeout=1)
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
        upload_to_imgbb(str(img_path), api_key='bad-key', timeout=1)


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

    data, changed, not_found = check_bookmarks_html_urls(html)
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
        <DT><A>Invalid</A>
    </DL>
    """
    requests_mock.head('https://redirect.com', status_code=301, headers={'location': '/new-loc'})
    # Patch user agent generator
    mocker.patch('deltona.www.generate_chrome_user_agent', return_value='UA')

    data, changed, not_found = check_bookmarks_html_urls(html)
    # Should have one link in data
    assert len(data) == 2
    # Should have one changed link
    assert len(changed) == 1
    # The href should be rewritten to absolute
    assert changed[0]['attrs']['href'].endswith('/new-loc')  # type: ignore[typeddict-item]
    assert changed[0]['title'] == 'Redirected'  # type: ignore[typeddict-item]
    # No not found
    assert not_found == []


def test_check_bookmarks_html_urls_full_redirect(mocker: MockerFixture,
                                                 requests_mock: Mocker) -> None:
    html = """
    <DL>
        <DT><A HREF="https://redirect.com" ADD_DATE="789">Redirected</A>
    </DL>
    """
    requests_mock.head('https://redirect.com',
                       status_code=301,
                       headers={'location': 'https://new-host/new-loc'})
    mocker.patch('deltona.www.generate_chrome_user_agent', return_value='UA')
    data, changed, not_found = check_bookmarks_html_urls(html)
    assert len(data) == 1
    assert len(changed) == 1
    assert changed[0]['attrs']['href'].endswith('/new-loc')  # type: ignore[typeddict-item]
    assert changed[0]['title'] == 'Redirected'  # type: ignore[typeddict-item]
    assert not_found == []


def test_check_bookmarks_html_urls_exhaustive_check(mocker: MockerFixture) -> None:
    html = """
<!DOCTYPE NETSCAPE-Bookmark-file-1>
<!-- This is an automatically generated file.
     It will be read and overwritten.
     DO NOT EDIT! -->
    <META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
    <TITLE>Bookmarks</TITLE>
    <H1>Bookmarks</H1>
    <DL><p>
        <DT><H3 ADD_DATE="1649305257" LAST_MODIFIED="1741660172" PERSONAL_TOOLBAR_FOLDER="true">
            Bookmarks bar</H3>
        <DT><A HREF="https://mail.google.com/"></A>
        <DT><A HREF="https://github.com/issues"></A>
    <DL><p>
        <DT><A HREF="https://forums.mydigitallife.net">
        <DT><A HREF="https://deltona.dev">Deltona</A>
    <DL><p>
        <DT><A HREF="https://deltona.zzz">Deltona</A>
        <DT><A HREF="https://deltona.yyy/docs">Documentation</A>
        <DT><H3 ADD_DATE="1620763254" LAST_MODIFIED="1697216205">Other folder</H3>
        <DL><p>
            <DT><A HREF="https://deltona.fff/docs/installation">Installation</A>
            <DT><A HREF="https://deltona.ggg/docs/usage">Usage</A>
        </DL><p>
    </DL><p>
    <DT><A HREF="https://deltona.dev/blog">Blog</A>
    <DT><A HREF="https://deltona.dev/contact">Contact</A>
</DL><p>
<DT><H3 ADD_DATE="1620763254" LAST_MODIFIED="1697216205">Downloads</H3>
<DL><p>
    <DT><A HREF="https://deltona.dev/downloads">Deltona Downloads</A>
    <DT><A HREF="https://deltona.dev/downloads/deltona-0.1.0.tar.gz">Deltona 0.1.0</A>
    <DT><A HREF="https://deltona.dev/downloads/deltona-0.2.0.tar.gz">Deltona 0.2.0</A>
</DL><p>
    """
    mocker.patch('deltona.www.generate_chrome_user_agent', return_value='UA')
    mock_session = mocker.patch('deltona.www.requests.Session')
    n = 0

    def mock_head(url: str, **kwargs: Any) -> Any:
        nonlocal n
        if url.startswith('https://deltona.dev'):
            return mocker.MagicMock(status_code=HTTPStatus.OK)
        n += 1
        return mocker.MagicMock(
            status_code=HTTPStatus.FOUND if n % 3 == 0 else HTTPStatus.NOT_FOUND if n %
            2 == 0 else HTTPStatus.OK,
            headers={'location': 'https://deltona.dev' if n % 2 == 0 else '/index.html'})

    mock_session.return_value.head.side_effect = mock_head
    data, changed, not_found = check_bookmarks_html_urls(html)
    mock_session.return_value.head.assert_has_calls([
        mocker.call('https://mail.google.com/'),
        mocker.call('https://github.com/issues'),
        mocker.call('https://forums.mydigitallife.net'),
        mocker.call('https://deltona.dev'),
        mocker.call('https://deltona.zzz'),
        mocker.call('https://deltona.yyy/docs'),
        mocker.call('https://deltona.fff/docs/installation'),
        mocker.call('https://deltona.ggg/docs/usage'),
        mocker.call('https://deltona.dev/blog'),
        mocker.call('https://deltona.dev/contact'),
        mocker.call('https://deltona.dev/downloads'),
        mocker.call('https://deltona.dev/downloads/deltona-0.1.0.tar.gz'),
        mocker.call('https://deltona.dev/downloads/deltona-0.2.0.tar.gz')
    ])
    assert data == [{
        'type': 'link',
        'title': '',
        'attrs': {
            'href': 'https://mail.google.com/'
        }
    }, {
        'type': 'link',
        'title': '',
        'attrs': {
            'href': 'https://github.com/issues'
        }
    }, {
        'type': 'link',
        'title': '',
        'attrs': {
            'href': 'https://forums.mydigitallife.net/index.html'
        }
    }, {
        'type': 'link',
        'title': 'Deltona',
        'attrs': {
            'href': 'https://deltona.dev'
        }
    }, {
        'type': 'link',
        'title': 'Deltona',
        'attrs': {
            'href': 'https://deltona.zzz'
        }
    }, {
        'type': 'link',
        'title': 'Documentation',
        'attrs': {
            'href': 'https://deltona.yyy/docs'
        }
    }, {
        'attrs': {
            'add_date': '1620763254',
            'last_modified': '1697216205'
        },
        'children': [{
            'type': 'link',
            'title': 'Installation',
            'attrs': {
                'href': 'https://deltona.dev'
            }
        }],
        'name': 'Other folder',
        'type': 'folder'
    }, {
        'type': 'link',
        'title': 'Usage',
        'attrs': {
            'href': 'https://deltona.ggg/docs/usage'
        }
    }, {
        'type': 'link',
        'title': 'Blog',
        'attrs': {
            'href': 'https://deltona.dev/blog'
        }
    }, {
        'type': 'link',
        'title': 'Contact',
        'attrs': {
            'href': 'https://deltona.dev/contact'
        }
    }, {
        'attrs': {
            'add_date': '1620763254',
            'last_modified': '1697216205'
        },
        'children': [{
            'type': 'link',
            'title': 'Deltona Downloads',
            'attrs': {
                'href': 'https://deltona.dev/downloads'
            }
        }],
        'name': 'Downloads',
        'type': 'folder'
    }, {
        'type': 'link',
        'title': 'Deltona 0.1.0',
        'attrs': {
            'href': 'https://deltona.dev/downloads/deltona-0.1.0.tar.gz'
        }
    }, {
        'type': 'link',
        'title': 'Deltona 0.2.0',
        'attrs': {
            'href': 'https://deltona.dev/downloads/deltona-0.2.0.tar.gz'
        }
    }]
    assert len(changed) == 2
    assert len(not_found) == 2


def test_where_from_linux(mocker: MockerFixture) -> None:
    # Simulate IS_LINUX = True
    mocker.patch('deltona.www.IS_LINUX', True)  # noqa: FBT003
    # Mock getxattr to return bytes
    mock_getxattr = mocker.patch('deltona.www._getxattr', return_value=b'https://example.com')
    # Should return the decoded string
    result = where_from('dummy-file')
    assert result == 'https://example.com'
    mock_getxattr.assert_called_once_with('dummy-file', KEY_ORIGIN_URL)


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
    result = where_from('dummy-file', webpage=False)
    assert result == 'https://file.com'
    mock_getxattr.assert_called_once_with('dummy-file', KEY_WHERE_FROMS)


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
    result = where_from('dummy-file', webpage=True)
    assert result == 'https://webpage.com'
    mock_getxattr.assert_called_once_with('dummy-file', KEY_WHERE_FROMS)


def test_generate_html_dir_tree_basic(tmp_path: Path) -> None:
    # Create a simple directory structure
    d1 = tmp_path / 'dir1'
    d1.mkdir()
    f1 = d1 / 'file1.txt'
    f1.write_text('hello')
    f2 = tmp_path / 'file2.txt'
    f2.write_text('world')

    # Patch Path.iterdir to avoid OS-specific ordering
    # (but here we use the real filesystem)

    html = generate_html_dir_tree(tmp_path)
    # Should contain both file2.txt and dir1/file1.txt
    assert 'file2.txt' in html
    assert 'file1.txt' in html
    assert 'dir1' in html
    # Should have <ul> and <li> tags
    assert '<ul' in html
    assert '<li' in html


def test_generate_html_dir_tree_nested(tmp_path: Path) -> None:
    # Create nested directories
    d1 = tmp_path / 'a'
    d1.mkdir()
    d2 = d1 / 'b'
    d2.mkdir()
    f1 = d2 / 'c.txt'
    f1.write_text('nested')

    html = generate_html_dir_tree(tmp_path)
    # Should contain all directory and file names
    assert 'a' in html
    assert 'b' in html
    assert 'c.txt' in html


def test_generate_html_dir_tree_empty_dir(tmp_path: Path) -> None:
    # Empty directory

    html = generate_html_dir_tree(tmp_path)
    # Should still return valid HTML
    assert '<ul' in html
    assert '</ul>' in html


def test_generate_html_dir_tree_symlink(tmp_path: Path) -> None:
    # Create a file and a symlink to it
    f1 = tmp_path / 'real.txt'
    f1.write_text('data')
    symlink = tmp_path / 'link.txt'
    symlink.symlink_to(f1)

    html = generate_html_dir_tree(tmp_path)
    # Should include both the real file and the symlink
    assert 'real.txt' in html
    assert 'link.txt' in html


def test_parse_bookmarks_html(mocker: MockerFixture) -> None:
    def recurse_bookmarks_html(soup: BeautifulSoup, callback: Callable[..., Any]) -> None:
        callback(mocker.MagicMock(), 'title', ['a', 'b'])

    mocker.patch('deltona.www.create_parsed_tree_structure', return_value=[])
    mocker.patch('deltona.www.recurse_bookmarks_html', recurse_bookmarks_html)
    ret = parse_bookmarks_html('')
    assert ret == []


def test_create_parsed_tree_structure_creates_new_folders(mocker: MockerFixture) -> None:
    folder_path: list[tuple[str, BookmarksHTMLFolderAttributes]] = [
        ('Folder1', {
            'add_date': '1',
            'last_modified': '2'
        }),
        ('Folder2', {
            'add_date': '3',
            'last_modified': '4'
        }),
    ]
    data: BookmarksDataset = []
    result = create_parsed_tree_structure(folder_path, data)
    assert isinstance(result, list)
    assert len(data) == 1
    assert data[0]['name'] == 'Folder1'  # type: ignore[typeddict-item]
    assert data[0]['type'] == 'folder'
    assert 'children' in data[0]
    assert data[0]['children'][0]['name'] == 'Folder2'  # type: ignore[typeddict-item]
    assert data[0]['children'][0]['type'] == 'folder'
    assert result is data[0]['children'][0]['children']
