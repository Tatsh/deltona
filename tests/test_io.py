from __future__ import annotations

from typing import TYPE_CHECKING
import os

from deltona.io import context_os_open, extract_gog, extract_rar_from_zip, unpack_0day, unpack_ebook
import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pytest_mock import MockerFixture

FILE_DESCRIPTOR = 3


def test_context_os_open(mocker: MockerFixture) -> None:
    mock_open = mocker.patch('os.open', return_value=FILE_DESCRIPTOR)
    mock_close = mocker.patch('os.close')
    with context_os_open('test_path', os.O_RDONLY) as fd:
        assert fd == FILE_DESCRIPTOR
        mock_open.assert_called_once_with('test_path', os.O_RDONLY, 511, dir_fd=None)
    mock_close.assert_called_once_with(FILE_DESCRIPTOR)


def test_unpack_0day(mocker: MockerFixture) -> None:
    mock_path = mocker.patch('deltona.io.Path')
    mocker.patch('deltona.io.contextlib.chdir')
    mocker.patch('deltona.io.ZipFile')
    mocker.patch('deltona.io.crc32').return_value = 0
    mock_zip = mocker.Mock()
    mock_diz = mocker.Mock()
    mock_rar = mocker.Mock()
    mock_rar.name = 'test.rar'
    mock_path.return_value.glob.side_effect = [[mock_zip], [mock_diz], [mock_rar], [mock_rar]]
    unpack_0day('test_path', remove_diz=True)
    mock_diz.unlink.assert_called_once()
    mock_path.return_value.glob.assert_any_call('*.rar')
    mock_path.return_value.glob.assert_any_call('*.[rstuvwxyz][0-9a][0-9r]')
    mock_path.return_value.open.return_value.__enter__.return_value.writelines.assert_any_call(
        mocker.ANY)


def test_extract_rar_from_zip_extracts_rar_files(mocker: MockerFixture) -> None:
    mock_zipfile = mocker.Mock()
    # Simulate two rar files and one non-rar file in the zip
    mock_zipfile.namelist.return_value = ['file1.rar', 'file2.r00', 'file3.txt']
    mock_zipfile.extract = mocker.Mock()
    extracted = list(extract_rar_from_zip(mock_zipfile))
    # Should only extract .rar and .r00 files
    assert extracted == ['file1.rar', 'file2.r00']
    mock_zipfile.extract.assert_any_call('file1.rar')
    mock_zipfile.extract.assert_any_call('file2.r00')
    assert mock_zipfile.extract.call_count == 2


def test_extract_rar_from_zip_no_rar_files(mocker: MockerFixture) -> None:
    mock_zipfile = mocker.Mock()
    mock_zipfile.namelist.return_value = ['file1.txt', 'file2.doc']
    mock_zipfile.extract = mocker.Mock()
    extracted = list(extract_rar_from_zip(mock_zipfile))
    assert extracted == []
    mock_zipfile.extract.assert_not_called()


def test_unpack_ebook_success_pdf(mocker: MockerFixture) -> None:
    mock_path = mocker.patch('deltona.io.Path')
    mocker.patch('deltona.io.contextlib.chdir')
    mock_zipfile_cls = mocker.patch('deltona.io.ZipFile')
    mock_extract_rar_from_zip = mocker.patch('deltona.io.extract_rar_from_zip')
    mock_sp_run = mocker.patch('deltona.io.sp.run')
    mocker.patch('deltona.io.log')
    # Setup mocks
    mock_dir = mocker.MagicMock()
    mock_dir.is_dir.return_value = True
    mock_zip1 = mocker.MagicMock()
    mock_zipfile_cls.side_effect = [mock_zip1]
    mock_dir.iterdir.return_value = [mocker.MagicMock(name='file.zip', name__endswith='.zip')]
    mock_rar_file = mocker.MagicMock()
    mock_rar_file.name = 'test.rar'
    mock_extract_rar_from_zip.return_value = ['test.rar']
    # Simulate .pdf file after extraction
    mock_pdf = mocker.MagicMock()
    mock_pdf.name = 'book.pdf'
    mock_pdf.lower = lambda: 'book.pdf'
    mock_pdf.open.return_value.__enter__.return_value.read.return_value = b'%PDF'
    mock_pdf.resolve.return_value.parent.name = 'parent_dir'
    mock_dir.iterdir.side_effect = [
        [mocker.MagicMock(name='file.zip', name__endswith='.zip')],  # for zip_listing
        [],  # for epub_list
        [mock_pdf],  # for pdf_list
    ]
    mock_path.side_effect = [mock_dir, mock_rar_file, mock_pdf]
    # Test
    unpack_ebook('some_path')
    mock_sp_run.assert_called()
    mock_pdf.rename.assert_called_with('../parent_dir.pdf')
    mock_zip1.close.assert_called_once()
    mock_rar_file.unlink.assert_called_once()


def test_unpack_ebook_success_epub(mocker: MockerFixture) -> None:
    mock_path = mocker.patch('deltona.io.Path')
    mocker.patch('deltona.io.contextlib.chdir')
    mock_zipfile_cls = mocker.patch('deltona.io.ZipFile')
    mock_extract_rar_from_zip = mocker.patch('deltona.io.extract_rar_from_zip')
    mock_sp_run = mocker.patch('deltona.io.sp.run')
    mocker.patch('deltona.io.log')
    # Setup mocks
    mock_dir = mocker.Mock()
    mock_dir.is_dir.return_value = True
    mock_zip1 = mocker.Mock()
    mock_zipfile_cls.side_effect = [mock_zip1]
    mock_dir.iterdir.return_value = [mocker.Mock(name='file.zip', name__endswith='.zip')]
    mock_rar_file = mocker.Mock()
    mock_rar_file.name = 'test.rar'
    mock_extract_rar_from_zip.return_value = ['test.rar']
    # Simulate .epub file after extraction
    mock_epub = mocker.Mock()
    mock_epub.name = 'book.epub'
    mock_epub.lower = lambda: 'book.epub'
    mock_epub.resolve.return_value.parent.name = 'parent_dir'
    mock_dir.iterdir.side_effect = [
        [mocker.Mock(name='file.zip', name__endswith='.zip')],  # for zip_listing
        [mock_epub],  # epub_list
        [],  # for pdf_list
    ]
    mock_path.side_effect = [mock_dir, mock_rar_file, mock_epub]
    # Test
    unpack_ebook('some_path')
    mock_sp_run.assert_called()
    mock_epub.rename.assert_called_with('../parent_dir.epub')
    mock_zip1.close.assert_called_once()
    mock_rar_file.unlink.assert_called_once()


def test_unpack_ebook_not_a_directory(mocker: MockerFixture) -> None:
    mock_path = mocker.patch('deltona.io.Path')
    mock_path.return_value.is_dir.return_value = False
    with pytest.raises(NotADirectoryError):
        unpack_ebook('not-a-dir')


def test_unpack_ebook_no_zip_files(mocker: MockerFixture) -> None:
    mock_path = mocker.patch('deltona.io.Path')
    mocker.patch('deltona.io.contextlib.chdir')
    mock_dir = mocker.Mock()
    mock_path.return_value = mock_dir
    mock_dir.is_dir.return_value = True
    mock_dir.iterdir.return_value = []
    with pytest.raises(FileExistsError):
        unpack_ebook('some_path')


def test_unpack_ebook_no_rar_found(mocker: MockerFixture) -> None:
    mock_path = mocker.patch('deltona.io.Path')
    mocker.patch('deltona.io.contextlib.chdir')
    mock_zipfile_cls = mocker.patch('deltona.io.ZipFile')
    mock_extract_rar_from_zip = mocker.patch('deltona.io.extract_rar_from_zip')
    mock_dir = mocker.Mock()
    mock_path.return_value = mock_dir
    mock_dir.is_dir.return_value = True
    mock_zip1 = mocker.Mock()
    mock_zipfile_cls.side_effect = [mock_zip1]
    mock_dir.iterdir.return_value = [mocker.Mock(name='file.zip', name__endswith='.zip')]
    mock_extract_rar_from_zip.return_value = []
    with pytest.raises(ValueError):  # noqa: PT011
        unpack_ebook('some_path')


def test_unpack_ebook_no_pdf_or_epub(mocker: MockerFixture) -> None:
    mock_path = mocker.patch('deltona.io.Path')
    mocker.patch('deltona.io.contextlib.chdir')
    mock_zipfile_cls = mocker.patch('deltona.io.ZipFile')
    mock_extract_rar_from_zip = mocker.patch('deltona.io.extract_rar_from_zip')
    mocker.patch('deltona.io.sp.run')
    mock_dir = mocker.Mock()
    mock_path.return_value = mock_dir
    mock_dir.is_dir.return_value = True
    mock_zip1 = mocker.Mock()
    mock_zipfile_cls.side_effect = [mock_zip1]
    mock_dir.iterdir.return_value = [mocker.Mock(name='file.zip', name__endswith='.zip')]
    mock_rar_file = mocker.Mock()
    mock_rar_file.name = 'test.rar'
    mock_extract_rar_from_zip.return_value = ['test.rar']
    mock_dir.iterdir.side_effect = [
        [mocker.Mock(name='file.zip', name__endswith='.zip')],  # for zip_listing
        [],  # for pdf_list
        [],  # for epub_list
    ]
    with pytest.raises(ValueError):  # noqa: PT011
        unpack_ebook('some_path')


def test_extract_gog_success(mocker: MockerFixture) -> None:
    mock_path = mocker.patch('deltona.io.Path')
    mock_copyfileobj = mocker.patch('deltona.io.shutil.copyfileobj')
    mock_input_path = mocker.MagicMock()
    mock_output_dir = mocker.MagicMock()
    mock_path.side_effect = [mock_output_dir, mock_input_path]
    mock_game_bin = mocker.Mock()
    mock_input_path.resolve.return_value.open.return_value.__enter__.return_value = mock_game_bin
    script = (b'#!/bin/sh\n'
              b'offset=`head -n 5 "$0"`\n'
              b'filesizes="1234"\n')
    mock_game_bin.read.side_effect = [
        script,
        script,
        b'mojosetup data',
        b'data zip data',
    ]
    mock_game_bin.seek = mocker.MagicMock()
    mock_game_bin.tell.side_effect = [42]

    def readline_side_effect() -> Iterator[bytes]:
        for _ in range(5):
            yield b'line\n'

    mock_game_bin.readline.side_effect = readline_side_effect()
    mock_unpacker_sh_f = mocker.MagicMock()
    mock_mojosetup_tar_f = mocker.MagicMock()
    mock_datafile_f = mocker.MagicMock()
    mock_output_dir.__truediv__.return_value.open.return_value.__enter__.side_effect = [
        mock_unpacker_sh_f, mock_mojosetup_tar_f, mock_datafile_f
    ]
    extract_gog('input.gog', 'output_dir')
    mock_output_dir.mkdir.assert_called_once_with(parents=True)
    assert mock_game_bin.seek.call_count >= 3
    mock_copyfileobj.assert_called_once_with(mock_game_bin, mock_datafile_f)


def test_extract_gog_invalid_offset(mocker: MockerFixture) -> None:
    mock_path = mocker.patch('deltona.io.Path')
    mocker.patch('deltona.io.shutil.copyfileobj')
    mock_input_path = mocker.MagicMock()
    mock_output_dir = mocker.MagicMock()
    mock_path.side_effect = [mock_output_dir, mock_input_path]
    mock_game_bin = mocker.Mock()
    mock_input_path.resolve.return_value.open.return_value.__enter__.return_value = mock_game_bin
    script = b'#!/bin/sh\nfilesizes="1234"\n'
    mock_game_bin.read.return_value = script
    with pytest.raises(ValueError):  # noqa: PT011
        extract_gog('input.gog', 'output_dir')
    mock_output_dir.mkdir.assert_called_once_with(parents=True)


def test_extract_gog_invalid_filesize(mocker: MockerFixture) -> None:
    mock_path = mocker.patch('deltona.io.Path')
    mock_input_path = mocker.MagicMock()
    mock_output_dir = mocker.MagicMock()
    mock_path.side_effect = [mock_output_dir, mock_input_path]
    mock_game_bin = mocker.Mock()
    mock_input_path.resolve.return_value.open.return_value.__enter__.return_value = mock_game_bin
    script = (b'#!/bin/sh\n'
              b'offset=`head -n 5 "$0"`\n')
    mock_game_bin.read.side_effect = [script, script]
    mock_game_bin.seek = mocker.MagicMock()
    mock_game_bin.tell.side_effect = [42]

    def readline_side_effect() -> Iterator[bytes]:
        for _ in range(5):
            yield b'line\n'

    mock_game_bin.readline.side_effect = readline_side_effect()
    mock_unpacker_sh_f = mocker.MagicMock()
    open_f = mock_output_dir.__truediv__.return_value.open.return_value
    open_f.__enter__.return_value = mock_unpacker_sh_f
    with pytest.raises(ValueError):  # noqa: PT011
        extract_gog('input.gog', 'output_dir')
    mock_output_dir.mkdir.assert_called_once_with(parents=True)
