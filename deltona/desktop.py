"""Desktop environment utilities."""

# cspell:ignore optionstr

from __future__ import annotations

from configparser import ConfigParser
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING

from typing_extensions import override

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ('fix_mime_associations',)

_REMOVED_ASSOCIATIONS = 'Removed Associations'


class _CaseSensitiveConfigParser(ConfigParser):
    @override
    def optionxform(self, optionstr: str) -> str:
        return optionstr


def _desktop_id(application: str) -> str:
    return application if application.endswith('.desktop') else f'{application}.desktop'


def _load_desktop_mime_types(application: str, applications_dir: Path) -> frozenset[str]:
    parser = _CaseSensitiveConfigParser(interpolation=None, strict=False)
    try:
        with (applications_dir / application).open(encoding='utf-8') as file:
            parser.read_file(file)
    except FileNotFoundError:
        return frozenset()
    return frozenset(parser.get('Desktop Entry', 'MimeType',
                                fallback='').rstrip(';').split(';')) - {''}


def _matches_declared_type(mime_type: str, declared_types: frozenset[str]) -> bool:
    if mime_type in declared_types:
        return True
    media_type, separator, subtype = mime_type.partition('/')
    if not separator or '+' not in subtype:
        return False
    return f'{media_type}/{subtype.rsplit("+", maxsplit=1)[1]}' in declared_types


def _parse_associations(value: str) -> set[str]:
    return set(value.rstrip(';').split(';')) - {''}


def _serialize_associations(applications: set[str]) -> str:
    return f'{";".join(sorted(applications))};'


def fix_mime_associations(applications: Iterable[str],
                          *,
                          applications_dir: Path,
                          mime_types_file: Path,
                          mimeapps_file: Path,
                          dry_run: bool = False) -> tuple[int, int]:
    """
    Reconcile removed MIME associations with applications' declared MIME types.

    Parameters
    ----------
    applications : Iterable[str]
        Desktop application IDs, with or without the ``.desktop`` suffix.
    applications_dir : pathlib.Path
        Directory containing desktop entry files.
    mime_types_file : pathlib.Path
        File containing known MIME types, one per line.
    mimeapps_file : pathlib.Path
        ``mimeapps.list`` file to update.
    dry_run : bool
        Calculate changes without writing the updated file.

    Returns
    -------
    tuple[int, int]
        Counts of associations added and removed, respectively.
    """
    desktop_ids = frozenset(_desktop_id(application) for application in applications)
    declared_types = {
        application: _load_desktop_mime_types(application, applications_dir)
        for application in desktop_ids
    }
    known_types = frozenset(mime_types_file.read_text(encoding='utf-8').splitlines()) - {''}
    parser = _CaseSensitiveConfigParser(interpolation=None)
    with mimeapps_file.open(encoding='utf-8') as file:
        parser.read_file(file)
    if not parser.has_section(_REMOVED_ASSOCIATIONS):
        parser.add_section(_REMOVED_ASSOCIATIONS)

    added = removed = 0
    for mime_type in sorted(known_types):
        associations = _parse_associations(parser.get(_REMOVED_ASSOCIATIONS, mime_type,
                                                      fallback=''))
        original = associations.copy()
        for application, supported_types in declared_types.items():
            if _matches_declared_type(mime_type, supported_types):
                associations.add(application)
            else:
                associations.discard(application)
        added += len(associations - original)
        removed += len(original - associations)
        if associations:
            parser.set(_REMOVED_ASSOCIATIONS, mime_type, _serialize_associations(associations))
        else:
            parser.remove_option(_REMOVED_ASSOCIATIONS, mime_type)

    if dry_run:
        return added, removed
    with NamedTemporaryFile('w',
                            dir=mimeapps_file.parent,
                            encoding='utf-8',
                            prefix=f'.{mimeapps_file.name}.',
                            delete=False) as file:
        temporary_path = Path(file.name)
        parser.write(file, space_around_delimiters=False)
    try:
        temporary_path.chmod(mimeapps_file.stat().st_mode)
        temporary_path.replace(mimeapps_file)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return added, removed
