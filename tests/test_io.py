from __future__ import annotations

from typing import TYPE_CHECKING, Any
import datetime
import os
import subprocess as sp

from deltona.io import (
    RARInfo,
    SFVVerificationError,
    UnRAR,
    UnRARExtractionTestFailed,
    context_os_open,
    extract_gog,
    extract_rar_from_zip,
    make_sfv,
    unpack_0day,
    unpack_ebook,
    verify_sfv,
)
import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

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
    unpack_0day('test_path')
    mock_diz.unlink.assert_called_once()
    mock_path.return_value.glob.assert_any_call('*.rar')
    mock_path.return_value.glob.assert_any_call('*.[rstuvwxyz][0-9a][0-9r]')
    mock_path.return_value.open.return_value.__enter__.return_value.writelines.assert_any_call(
        mocker.ANY)


def test_unpack_0day_no_diz(mocker: MockerFixture) -> None:
    mock_path = mocker.patch('deltona.io.Path')
    mocker.patch('deltona.io.contextlib.chdir')
    mocker.patch('deltona.io.ZipFile')
    mocker.patch('deltona.io.crc32').return_value = 0
    mock_zip = mocker.Mock()
    mock_rar = mocker.Mock()
    mock_rar.name = 'test.rar'
    mock_path.return_value.glob.side_effect = [[mock_zip], [mock_rar], [mock_rar]]
    unpack_0day('test_path', remove_diz=False)
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


def test_unpack_ebook_more_than_1_pdf(mocker: MockerFixture) -> None:
    mock_path = mocker.patch('deltona.io.Path')
    mocker.patch('deltona.io.contextlib.chdir')
    mock_zipfile_cls = mocker.patch('deltona.io.ZipFile')
    mock_extract_rar_from_zip = mocker.patch('deltona.io.extract_rar_from_zip')
    mocker.patch('deltona.io.sp.run')
    # Setup mocks
    mock_dir = mocker.Mock()
    mock_dir.is_dir.return_value = True
    mock_zip1 = mocker.Mock()
    mock_zipfile_cls.side_effect = [mock_zip1]
    mock_dir.iterdir.return_value = [mocker.Mock(name='file.zip', name__endswith='.zip')]
    mock_rar_file = mocker.Mock()
    mock_rar_file.name = 'test.rar'
    mock_extract_rar_from_zip.return_value = ['test.rar']
    # Simulate multiple .pdf files after extraction
    pdf_files = [
        mocker.Mock(name='book1.pdf', lower=lambda: 'book1.pdf'),
        mocker.Mock(name='book2.pdf', lower=lambda: 'book2.pdf'),
    ]
    for pdf in pdf_files:
        pdf.resolve.return_value.parent.name = 'parent_dir'
    mock_dir.iterdir.side_effect = [
        [mocker.Mock(name='file.zip', name__endswith='.zip')],  # for zip_listing
        [],  # for epub_list
        pdf_files,  # pdf_list with multiple PDFs
    ]
    mock_path.side_effect = [mock_dir, mock_rar_file, *pdf_files]
    # Test
    with pytest.raises(ValueError, match='2'):
        unpack_ebook('some_path')


def test_unpack_ebook_more_than_1_epub(mocker: MockerFixture) -> None:
    mock_path = mocker.patch('deltona.io.Path')
    mocker.patch('deltona.io.contextlib.chdir')
    mock_zipfile_cls = mocker.patch('deltona.io.ZipFile')
    mock_extract_rar_from_zip = mocker.patch('deltona.io.extract_rar_from_zip')
    mocker.patch('deltona.io.sp.run')
    # Setup mocks
    mock_dir = mocker.Mock()
    mock_dir.is_dir.return_value = True
    mock_zip1 = mocker.Mock()
    mock_zipfile_cls.side_effect = [mock_zip1]
    mock_dir.iterdir.return_value = [mocker.Mock(name='file.zip', name__endswith='.zip')]
    mock_rar_file = mocker.Mock()
    mock_rar_file.name = 'test.rar'
    mock_extract_rar_from_zip.return_value = ['test.rar']
    # Simulate multiple .epub files after extraction
    epub_files = [
        mocker.Mock(name='book1.epub', lower=lambda: 'book1.epub'),
        mocker.Mock(name='book2.epub', lower=lambda: 'book2.epub'),
    ]
    for epub in epub_files:
        epub.resolve.return_value.parent.name = 'parent_dir'
    mock_dir.iterdir.side_effect = [
        [mocker.Mock(name='file.zip', name__endswith='.zip')],  # for zip_listing
        epub_files,  # epub_list with multiple EPUBs
        [],  # for pdf_list
    ]
    mock_path.side_effect = [mock_dir, mock_rar_file, *epub_files]
    # Test
    with pytest.raises(ValueError, match='2'):
        unpack_ebook('some_path')


def test_unpack_ebook_pdf_not_pdf(mocker: MockerFixture) -> None:
    mock_path = mocker.patch('deltona.io.Path')
    mocker.patch('deltona.io.contextlib.chdir')
    mock_zipfile_cls = mocker.patch('deltona.io.ZipFile')
    mock_extract_rar_from_zip = mocker.patch('deltona.io.extract_rar_from_zip')
    mocker.patch('deltona.io.sp.run')
    # Setup mocks
    mock_dir = mocker.Mock()
    mock_dir.is_dir.return_value = True
    mock_zip1 = mocker.Mock()
    mock_zipfile_cls.side_effect = [mock_zip1]
    mock_dir.iterdir.return_value = [mocker.Mock(name='file.zip', name__endswith='.zip')]
    mock_rar_file = mocker.Mock()
    mock_rar_file.name = 'test.rar'
    mock_extract_rar_from_zip.return_value = ['test.rar']
    # Simulate non-PDF file after extraction
    mock_pdf = mocker.MagicMock()
    mock_pdf.open.return_value.__enter__.return_value.read.return_value = b'Not a PDF'
    mock_dir.iterdir.side_effect = [
        [mocker.Mock(name='file.zip', name__endswith='.zip')],  # for zip_listing
        [],  # for epub_list
        [mock_pdf],  # pdf_list with non-PDF file
    ]
    mock_path.side_effect = [mock_dir, mock_rar_file, mock_pdf]
    # Test
    with pytest.raises(ValueError, match='Not '):
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


def test_verify_sfv_success(mocker: MockerFixture) -> None:
    mock_path = mocker.patch('deltona.io.Path')
    mock_file = mocker.MagicMock()
    mock_path.return_value = mock_file
    # Simulate SFV file with one valid entry
    sfv_content = 'file1.bin ABCDEF12\n'
    mock_file.open.return_value.__enter__.return_value = sfv_content.splitlines(keepends=True)
    mock_file.parent.__truediv__.return_value.read_bytes.return_value = b'data'
    mocker.patch('deltona.io.crc32', return_value=int('ABCDEF12', 16))
    verify_sfv('test.sfv')
    mock_file.open.assert_called_once_with(encoding='utf-8')


def test_verify_sfv_raises_on_crc_mismatch(mocker: MockerFixture) -> None:
    mock_path = mocker.patch('deltona.io.Path')
    mock_file = mocker.MagicMock()
    mock_path.return_value = mock_file
    sfv_content = 'file1.bin 12345678\n'
    mock_file.open.return_value.__enter__.return_value = sfv_content.splitlines(keepends=True)
    mock_file.parent.__truediv__.return_value.read_bytes.return_value = b'wrong'
    mocker.patch('deltona.io.crc32', return_value=int('87654321', 16))
    with pytest.raises(SFVVerificationError) as exc:
        verify_sfv('test.sfv')
    assert 'file1.bin' in str(exc.value)
    assert 'Expected 12345678' in str(exc.value)
    assert 'Actual: 87654321' in str(exc.value)


def test_verify_sfv_ignores_comments_and_blank_lines(mocker: MockerFixture) -> None:
    mock_path = mocker.patch('deltona.io.Path')
    mock_file = mocker.MagicMock()
    mock_path.return_value = mock_file
    sfv_content = ['; This is a comment\n', '# Another comment\n', '\n', 'file2.bin 11111111\n']
    mock_file.open.return_value.__enter__.return_value = sfv_content
    mock_file.parent.__truediv__.return_value.read_bytes.return_value = b'data'
    mocker.patch('deltona.io.crc32', return_value=int('11111111', 16))
    verify_sfv('test.sfv')
    mock_file.open.assert_called_once_with(encoding='utf-8')


def test_verify_sfv_handles_multiple_files(mocker: MockerFixture) -> None:
    mock_path = mocker.patch('deltona.io.Path')
    mock_file = mocker.MagicMock()
    mock_path.return_value = mock_file
    sfv_content = ['file1.bin 11111111\n', 'file2.bin 22222222\n']
    mock_file.open.return_value.__enter__.return_value = sfv_content

    def crc32_side_effect(data: bytes) -> int:
        if data == b'data1':
            return int('11111111', 16)
        if data == b'data2':
            return int('22222222', 16)
        return 0

    parent = mock_file.parent
    parent.__truediv__.side_effect = lambda fname: mocker.Mock(read_bytes=mocker.Mock(
        return_value=b'data1' if fname == 'file1.bin' else b'data2'))
    mocker.patch('deltona.io.crc32', side_effect=crc32_side_effect)
    verify_sfv('test.sfv')


def test_make_sfv_writes_header_and_crc_lines(mocker: MockerFixture, tmp_path: Path) -> None:
    mock_file1 = tmp_path / 'file1.bin'
    mock_file1.touch()
    mock_file2 = tmp_path / 'file2.bin'
    mock_file2.touch()
    mock_datetime = mocker.patch('deltona.io.datetime')
    mock_datetime.now.return_value.isoformat.return_value = '2024-06-01 12:00:00'

    def mock_fromtimestamp(ts: str, tz: Any = None) -> Any:
        return mocker.Mock(isoformat=lambda _: f'date{int(ts)}')

    mock_datetime.fromtimestamp.side_effect = mock_fromtimestamp
    mock_crc32 = mocker.patch('deltona.io.crc32')
    mock_crc32.side_effect = [0x11111111, 0x22222222]
    mock_out_file = tmp_path / 'test.sfv'

    make_sfv(mock_out_file, [mock_file1, mock_file2], header=True)
    content = mock_out_file.read_text(encoding='utf-8')
    assert content.startswith('; Generated on')
    assert 'file1.bin 11111111' in content
    assert 'file2.bin 22222222' in content


def test_make_sfv_no_header(mocker: MockerFixture, tmp_path: Path) -> None:
    mock_file = tmp_path / 'file1.bin'
    mock_file.touch()
    mock_out_file = tmp_path / 'test.sfv'
    mocker.patch('deltona.io.crc32', return_value=0xDEADBEEF)
    make_sfv(mock_out_file, [str(mock_file)], header=False)
    written = mock_out_file.read_text(encoding='utf-8')
    assert not written.startswith(';')
    assert 'file1.bin DEADBEEF' in written


def test_make_sfv_empty_files_list(mocker: MockerFixture, tmp_path: Path) -> None:
    mock_file = tmp_path / 'file1.sfv'
    mock_file.touch()
    make_sfv(mock_file, [], header=True)
    content = mock_file.read_text(encoding='utf-8')
    assert content.startswith('; Generated on')


def test_unrar_list_files_parses_output(mocker: MockerFixture) -> None:
    mock_sp_run = mocker.patch('deltona.io.sp.run')
    mock_sp_run.return_value.stdout = """UNRAR 7.11 freeware

Archive: the-archive.rar
Details: RAR 1.5

 Attributes      Size     Date    Time   Name
----------- ---------  ---------- -----  ----
    ..A....    137536  2011-06-07 21:54  xy/file2.bin
    ..A....    381453  2011-06-07 21:54  xy/file1.txt
    ...D...         0  2011-06-07 21:53  xy
----------- ---------  ---------- -----  ----
              8356365                    6
""".strip()
    unrar = UnRAR('unrar')
    files = list(unrar.list_files('archive.rar'))
    assert len(files) == 3
    assert isinstance(files[0], RARInfo)
    assert files[1].name == 'xy/file1.txt'
    assert files[0].name == 'xy/file2.bin'
    assert files[0].size == 137536
    assert files[0].date == datetime.datetime(2011, 6, 7, 21, 54, tzinfo=datetime.UTC)


def test_unrar_test_extraction_success(mocker: MockerFixture) -> None:
    mock_sp_run = mocker.patch('deltona.io.sp.run')
    unrar = UnRAR('unrar')
    # Should not raise
    unrar.test_extraction('archive.rar', 'file.txt')
    mock_sp_run.assert_called_once_with(('unrar', 't', '-y', '-inul', 'archive.rar', 'file.txt'),
                                        check=True)


def test_unrar_test_extraction_failure(mocker: MockerFixture) -> None:
    mocker.patch('deltona.io.sp.run', side_effect=sp.CalledProcessError(1, 'unrar'))
    unrar = UnRAR('unrar')
    with pytest.raises(UnRARExtractionTestFailed):
        unrar.test_extraction('archive.rar', 'file.txt')


def test_unrar_pipe_context_manager(mocker: MockerFixture) -> None:
    mock_popen = mocker.patch('deltona.io.sp.Popen')
    mock_proc = mocker.MagicMock()
    mock_popen.return_value.__enter__.return_value = mock_proc
    unrar = UnRAR('unrar')
    with unrar.pipe('archive.rar', 'file.txt') as proc:
        assert proc is mock_proc
    mock_popen.assert_called_once_with(('unrar', 'p', '-y', '-inul', 'archive.rar', 'file.txt'),
                                       stdout=mocker.ANY,
                                       close_fds=True)
