from __future__ import annotations

from configparser import ConfigParser
from typing import TYPE_CHECKING

import pytest

from deltona.desktop import fix_mime_associations

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture


def _read_mimeapps(path: Path) -> ConfigParser:
    parser = ConfigParser(interpolation=None)
    parser.read(path)
    return parser


def test_fix_mime_associations_reconciles_selected_applications(tmp_path: Path) -> None:
    applications_dir = tmp_path / 'applications'
    applications_dir.mkdir()
    (applications_dir /
     'viewer.desktop').write_text('[Desktop Entry]\nMimeType=text/plain;image/xml;\n')
    mime_types_file = tmp_path / 'types'
    mime_types_file.write_text('application/pdf\nimage/svg+xml\ntext/plain\n')
    mimeapps_file = tmp_path / 'mimeapps.list'
    mimeapps_file.write_text(
        '[Removed Associations]\napplication/pdf=viewer.desktop;other.desktop;\n')

    added, removed = fix_mime_associations(('viewer',),
                                           applications_dir=applications_dir,
                                           mime_types_file=mime_types_file,
                                           mimeapps_file=mimeapps_file)

    parser = _read_mimeapps(mimeapps_file)
    assert added == 2
    assert removed == 1
    assert parser.get('Removed Associations', 'application/pdf') == 'other.desktop;'
    assert parser.get('Removed Associations', 'image/svg+xml') == 'viewer.desktop;'
    assert parser.get('Removed Associations', 'text/plain') == 'viewer.desktop;'


def test_fix_mime_associations_preserves_unrelated_entries_and_sorts(tmp_path: Path) -> None:
    applications_dir = tmp_path / 'applications'
    applications_dir.mkdir()
    (applications_dir / 'a.desktop').write_text('[Desktop Entry]\nMimeType=text/plain;\n')
    (applications_dir / 'b.desktop').write_text('[Desktop Entry]\nMimeType=text/plain;\n')
    mime_types_file = tmp_path / 'types'
    mime_types_file.write_text('text/plain\n')
    mimeapps_file = tmp_path / 'mimeapps.list'
    mimeapps_file.write_text('[Default Applications]\ntext/plain=default.desktop;\n')

    fix_mime_associations(('b.desktop', 'a'),
                          applications_dir=applications_dir,
                          mime_types_file=mime_types_file,
                          mimeapps_file=mimeapps_file)

    parser = _read_mimeapps(mimeapps_file)
    assert parser.get('Default Applications', 'text/plain') == 'default.desktop;'
    assert parser.get('Removed Associations', 'text/plain') == 'a.desktop;b.desktop;'


def test_fix_mime_associations_missing_desktop_removes_stale_entry(tmp_path: Path) -> None:
    applications_dir = tmp_path / 'applications'
    applications_dir.mkdir()
    mime_types_file = tmp_path / 'types'
    mime_types_file.write_text('text/plain\n')
    mimeapps_file = tmp_path / 'mimeapps.list'
    mimeapps_file.write_text('[Removed Associations]\ntext/plain=missing.desktop;\n')

    added, removed = fix_mime_associations(('missing',),
                                           applications_dir=applications_dir,
                                           mime_types_file=mime_types_file,
                                           mimeapps_file=mimeapps_file)

    assert (added, removed) == (0, 1)
    assert not _read_mimeapps(mimeapps_file).has_option('Removed Associations', 'text/plain')


def test_fix_mime_associations_dry_run_does_not_write(tmp_path: Path) -> None:
    applications_dir = tmp_path / 'applications'
    applications_dir.mkdir()
    (applications_dir / 'viewer.desktop').write_text('[Desktop Entry]\nMimeType=text/plain;\n')
    mime_types_file = tmp_path / 'types'
    mime_types_file.write_text('text/plain\n')
    mimeapps_file = tmp_path / 'mimeapps.list'
    original = '[Added Associations]\ntext/plain=other.desktop;\n'
    mimeapps_file.write_text(original)

    result = fix_mime_associations(('viewer',),
                                   applications_dir=applications_dir,
                                   dry_run=True,
                                   mime_types_file=mime_types_file,
                                   mimeapps_file=mimeapps_file)

    assert result == (1, 0)
    assert mimeapps_file.read_text() == original


def test_fix_mime_associations_removes_temporary_file_on_replace_failure(
        mocker: MockerFixture, tmp_path: Path) -> None:
    applications_dir = tmp_path / 'applications'
    applications_dir.mkdir()
    (applications_dir / 'viewer.desktop').write_text('[Desktop Entry]\nMimeType=text/plain;\n')
    mime_types_file = tmp_path / 'types'
    mime_types_file.write_text('text/plain\n')
    mimeapps_file = tmp_path / 'mimeapps.list'
    original = '[Removed Associations]\n'
    mimeapps_file.write_text(original)
    mocker.patch('pathlib.Path.replace', side_effect=OSError('replace failed'))

    with pytest.raises(OSError, match='replace failed'):
        fix_mime_associations(('viewer',),
                              applications_dir=applications_dir,
                              mime_types_file=mime_types_file,
                              mimeapps_file=mimeapps_file)

    assert mimeapps_file.read_text() == original
    assert tuple(tmp_path.glob('.mimeapps.list.*')) == ()
