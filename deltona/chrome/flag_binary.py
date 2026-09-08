"""
Recover the ``chrome://flags`` table from an installed browser binary, offline.

The table is the C array ``kFeatureEntries`` from ``chrome/browser/about_flags.cc``. Every element
is a ``flags_ui::FeatureEntry`` whose first three members are ``const char *`` (internal name,
visible name, and visible description), followed by an ``unsigned short supported_platforms`` and a
``Type`` enum sharing one 32-bit word. ``sizeof(FeatureEntry)`` is 80 on every 64-bit build.

None of those pointers can be read straight off disk. A Linux binary is position independent and
keeps the pointer values in its ``.rela.dyn`` addends, a macOS framework packs them into chained
fixups, and only a Windows image stores the pointer in place. Each container therefore gets its own
resolver, after which the scan is the same: find slots where three consecutive pointers all land on
plausible strings, take the longest run of them spaced 80 bytes apart, then extend that run.

What the binary yields is what the installed browser actually compiled, so entries a preprocessor
guard excluded are correctly absent. Owners and expiry milestones are not compiled in at all and
remain available only from ``chrome/browser/flag-metadata.json``.
"""

from __future__ import annotations

from contextlib import contextmanager
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any
import logging
import mmap
import os
import re
import struct
import sys

from .core import CHANNEL_DIRECTORIES

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

    from deltona.typing import StrPath

    from .typing import ChromeChannel

__all__ = ('FEATURE_ENTRY_STRIDE', 'FlagBinaryUnreadable', 'extract_flag_table',
           'find_browser_binary')

log = logging.getLogger(__name__)

FEATURE_ENTRY_STRIDE = 80
"""
``sizeof(flags_ui::FeatureEntry)`` on every 64-bit build.

:meta hide-value:
"""
OS_BITS = ('kOsMac', 'kOsWin', 'kOsLinux', 'kOsCrOS', 'kOsAndroid', 'kOsCrOSOwnerOnly', 'kOsIos',
           'kOsFuchsia')
"""
Names of the ``supported_platforms`` bits, in bit order.

:meta hide-value:
"""
TYPE_NAMES = ('SINGLE_VALUE_TYPE', 'SINGLE_DISABLE_VALUE_TYPE', 'MULTI_VALUE_TYPE',
              'ENABLE_DISABLE_VALUE_TYPE', 'FEATURE_VALUE_TYPE', 'FEATURE_WITH_PARAMS_VALUE_TYPE',
              'ORIGIN_LIST_VALUE_TYPE', 'STRING_VALUE_TYPE', 'PLATFORM_FEATURE_NAME_TYPE',
              'PLATFORM_FEATURE_WITH_PARAMS_VALUE_TYPE')
"""
Macro name of each ``FeatureEntry::Type``, in enum order.

The mapping is one macro per enum value, so the variants that differ only in the switch value they
carry (``SINGLE_VALUE_TYPE_AND_VALUE``, ``SINGLE_DISABLE_VALUE_TYPE_AND_VALUE``, and
``ENABLE_DISABLE_VALUE_TYPE_AND_VALUE``) cannot be told apart from the plain form and are reported
as the plain form. The last two entries exist only in a ChromeOS build.

:meta hide-value:
"""

_INTERNAL_NAME_RE = re.compile(r'^[a-z0-9][a-z0-9._-]*$')
_ALLOWED_CONTROL = frozenset({9, 10})
_FIRST_PRINTABLE = 0x20
_PLATFORM_OFFSET = 24
_MINIMUM_ENTRIES = 50
_MAXIMUM_STRING = 8192
_NAME_MINIMUM = 2
_NAME_MAXIMUM = 120
_SEED_NAME_MAXIMUM = 100
_TITLE_MAXIMUM = 300
_DESCRIPTION_MINIMUM = 10
_OS_ALL = 0x1F
_OS_DESKTOP = 0x0F
_ELF_MAGIC = b'\x7fELF'
_ELF_PROGBITS = 1
_ELF_RELATIVE_RELOCATION = 8
_ELF_STRING_SECTIONS = frozenset({'.data.rel.ro', '.rodata', '.rodata.str1.1'})
_ELF_WORD_SECTIONS = frozenset({'.data', '.data.rel.ro'})
_MACHO_MAGIC_64 = 0xFEEDFACF
_MACHO_FAT_MAGICS = frozenset({b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf'})
_MACHO_MAGICS = frozenset({b'\xcf\xfa\xed\xfe', *_MACHO_FAT_MAGICS})
_MACHO_SEGMENT_64 = 0x19
_MACHO_CHAINED_FIXUPS = 0x80000034
_MACHO_COMMAND_MINIMUM = 8
_MACHO_STRING_SECTIONS = frozenset({'__cstring', '__const', '__objc_methname'})
_MACHO_WORD_SEGMENTS = frozenset({'__AUTH_CONST', '__DATA', '__DATA_CONST'})
_CHAIN_START_NONE = 0xFFFF
_CHAIN_FORMAT_ABSOLUTE = 2
_CHAIN_FORMATS_64 = frozenset({_CHAIN_FORMAT_ABSOLUTE, 6})
_CHAIN_FORMATS_ARM64E = frozenset({1, 9, 12})
_PE_MAGIC = b'MZ'
_PE32_PLUS = 0x20B
_PE_BASE_RELOCATION_INDEX = 5
_PE_DIR64 = 10
_PE_RELOCATION_HEADER = 8
_PE_SECTIONS = frozenset({'.data', '.rdata'})
_IMAGE_MAGICS = (_ELF_MAGIC, _PE_MAGIC, *_MACHO_MAGICS)
_MACOS_APP_NAMES: dict[ChromeChannel, str] = {
    'beta': 'Google Chrome Beta',
    'canary': 'Google Chrome Canary',
    'chromium': 'Chromium',
    'dev': 'Google Chrome Dev',
    'stable': 'Google Chrome'
}
_WINDOWS_DIRECTORY_NAMES: dict[ChromeChannel, str] = {
    'beta': 'Google/Chrome Beta',
    'canary': 'Google/Chrome SxS',
    'chromium': 'Chromium',
    'dev': 'Google/Chrome Dev',
    'stable': 'Google/Chrome'
}


class FlagBinaryUnreadable(Exception):
    """Raised when a file is not a browser binary or holds no recognisable flag table."""


class _Image:
    """A memory-mapped binary reduced to what the flag table scan needs."""
    def __init__(self, data: mmap.mmap, pointers: dict[int, int],
                 strings: Sequence[tuple[int, int, int]], words: Sequence[tuple[int, int,
                                                                                int]]) -> None:
        self.pointers = pointers
        self._data = data
        self._strings = sorted(strings)
        self._words = sorted(words)

    def string(self, va: int) -> str | None:
        """
        Read the NUL-terminated string at a virtual address.

        Parameters
        ----------
        va : int
            The virtual address.

        Returns
        -------
        str | None
            The string, or ``None`` when the address is outside every string section, is not
            terminated within :py:data:`_MAXIMUM_STRING` bytes, or the bytes are not printable
            UTF-8.
        """
        for base, offset, size in self._strings:
            if base <= va < base + size:
                start = offset + (va - base)
                end = self._data.find(b'\0', start, min(start + _MAXIMUM_STRING + 1, offset + size))
                if end <= start:
                    return None
                raw = self._data[start:end]
                if any(byte < _FIRST_PRINTABLE and byte not in _ALLOWED_CONTROL for byte in raw):
                    return None
                try:
                    return raw.decode()
                except UnicodeDecodeError:
                    return None
        return None

    def word(self, va: int) -> int:
        """
        Read the raw little-endian 32-bit word at a virtual address.

        Parameters
        ----------
        va : int
            The virtual address.

        Returns
        -------
        int
            The word, or ``0`` when the address is outside every section carrying one.
        """
        for base, offset, size in self._words:
            if base <= va < base + size - 4:
                word: int = struct.unpack_from('<I', self._data, offset + (va - base))[0]
                return word
        return 0


def _fixed_string(data: mmap.mmap, offset: int, size: int) -> str:
    return data[offset:offset + size].rstrip(b'\0').decode(errors='replace')


def _load_elf(data: mmap.mmap) -> _Image:
    section_offset, = struct.unpack_from('<Q', data, 0x28)
    entry_size, count, name_index = struct.unpack_from('<HHH', data, 0x3A)
    raw = [
        struct.unpack_from('<IIQQQQ', data, section_offset + i * entry_size) for i in range(count)
    ]
    names_offset = raw[name_index][4]
    sections = []
    for name_position, kind, _, address, offset, size in raw:
        end = data.find(b'\0', names_offset + name_position)
        if end < 0:
            msg = 'ELF section name table is truncated.'
            raise FlagBinaryUnreadable(msg)
        sections.append((data[names_offset + name_position:end].decode(errors='replace'), kind,
                         address, offset, size))
    pointers: dict[int, int] = {}
    for name, _, _, offset, size in sections:
        if name == '.rela.dyn':
            pointers.update({
                target: addend
                for target, info, addend in struct.iter_unpack(
                    '<QQq',
                    memoryview(data)[offset:offset + size])
                if (info & 0xFFFFFFFF) == _ELF_RELATIVE_RELOCATION
            })
            break
    return _Image(data, pointers, [(address, offset, size)
                                   for name, kind, address, offset, size in sections
                                   if kind == _ELF_PROGBITS and name in _ELF_STRING_SECTIONS],
                  [(address, offset, size) for name, kind, address, offset, size in sections
                   if kind == _ELF_PROGBITS and name in _ELF_WORD_SECTIONS])


def _macho_slices(data: mmap.mmap) -> list[tuple[int, int]]:
    if data[:4] not in _MACHO_FAT_MAGICS:
        return [(0, len(data))]
    count, = struct.unpack_from('>I', data, 4)
    wide = data[:4] == b'\xca\xfe\xba\xbf'
    layout, stride = ('>IIQQQ', 32) if wide else ('>IIIII', 20)
    return [(offset, size)
            for _, _, offset, size, _ in (struct.unpack_from(layout, data, 8 + i * stride)
                                          for i in range(count))]


def _macho_commands(
    data: mmap.mmap, base: int
) -> tuple[list[tuple[str, int, int]], list[tuple[str, str, int, int, int]], int | None]:
    count, = struct.unpack_from('<I', data, base + 16)
    position = base + 32
    segments: list[tuple[str, int, int]] = []
    sections: list[tuple[str, str, int, int, int]] = []
    fixups: int | None = None
    for _ in range(count):
        command, command_size = struct.unpack_from('<II', data, position)
        if command_size < _MACHO_COMMAND_MINIMUM:
            msg = 'Mach-O load command has an impossible size.'
            raise FlagBinaryUnreadable(msg)
        if command == _MACHO_SEGMENT_64:
            address, _, file_offset, _ = struct.unpack_from('<QQQQ', data, position + 24)
            segments.append((_fixed_string(data, position + 8, 16), address, base + file_offset))
            section_count, = struct.unpack_from('<I', data, position + 64)
            for i in range(section_count):
                start = position + 72 + i * 80
                section_address, section_size = struct.unpack_from('<QQ', data, start + 32)
                section_offset, = struct.unpack_from('<I', data, start + 48)
                sections.append((_fixed_string(data, start + 16, 16), _fixed_string(
                    data, start, 16), section_address, section_offset, section_size))
        elif command == _MACHO_CHAINED_FIXUPS:
            fixups, = struct.unpack_from('<I', data, position + 8)
            fixups += base
        position += command_size
    return segments, sections, fixups


def _load_macho(data: mmap.mmap, base: int, size: int) -> _Image:
    magic, = struct.unpack_from('<I', data, base)
    if magic != _MACHO_MAGIC_64:
        msg = f'Not a 64-bit Mach-O slice (magic 0x{magic:08x}).'
        raise FlagBinaryUnreadable(msg)
    segments, sections, fixups = _macho_commands(data, base)
    text = next((address for name, address, _ in segments if name == '__TEXT'), None)
    if text is None:
        msg = 'Mach-O slice has no __TEXT segment.'
        raise FlagBinaryUnreadable(msg)
    pointers = (_chained_fixups(data, fixups, text, segments, base + size)
                if fixups is not None else _macho_plain_pointers(data, sections, base))
    return _Image(data, pointers, [(address, base + offset, section_size)
                                   for _, name, address, offset, section_size in sections
                                   if offset and name in _MACHO_STRING_SECTIONS],
                  [(address, base + offset, section_size)
                   for segment, _, address, offset, section_size in sections
                   if offset and segment in _MACHO_WORD_SEGMENTS])


def _macho_plain_pointers(data: mmap.mmap, sections: Sequence[tuple[str, str, int, int, int]],
                          base: int) -> dict[int, int]:
    pointers: dict[int, int] = {}
    for segment, _, address, offset, size in sections:
        if not offset or segment not in _MACHO_WORD_SEGMENTS:
            continue
        for position in range(0, size - 8, 8):
            value, = struct.unpack_from('<Q', data, base + offset + position)
            if value:
                pointers[address + position] = value
    return pointers


def _decode_chained_pointer(raw: int, pointer_format: int,
                            text: int) -> tuple[int | None, int] | None:
    """
    Decode one link of a chained-fixup pointer.

    Parameters
    ----------
    raw : int
        The 64-bit word stored in the pointer slot.
    pointer_format : int
        ``pointer_format`` of the enclosing ``dyld_chained_starts_in_segment``.
    text : int
        Virtual address of the ``__TEXT`` segment, which the offset formats are relative to.

    Returns
    -------
    tuple[int | None, int] | None
        The rebase target (``None`` when the link is a bind rather than a rebase) and the byte
        offset of the next link, or ``None`` when the format is not understood.
    """
    if pointer_format in _CHAIN_FORMATS_64:
        step = ((raw >> 51) & 0xFFF) * 4
        if raw >> 63:
            return None, step
        target = (raw & 0xFFFFFFFFF) | (((raw >> 36) & 0xFF) << 56)
        return (target if pointer_format == _CHAIN_FORMAT_ABSOLUTE else text + target), step
    if pointer_format in _CHAIN_FORMATS_ARM64E:
        step = ((raw >> 51) & 0x7FF) * 8
        if (raw >> 62) & 1:
            return None, step
        return text + (raw & (0xFFFFFFFF if raw >> 63 else 0xFFFFFFFFF)), step
    return None


def _chained_fixups(data: mmap.mmap, header: int, text: int,
                    segments: Sequence[tuple[str, int, int]], limit: int) -> dict[int, int]:
    starts_offset, = struct.unpack_from('<I', data, header + 4)
    starts = header + starts_offset
    count, = struct.unpack_from('<I', data, starts)
    pointers: dict[int, int] = {}
    for relative in struct.unpack_from(f'<{count}I', data, starts + 4):
        if not relative:
            continue
        info = starts + relative
        (_, page_size, pointer_format, segment_offset, _, page_count) = struct.unpack_from(
            '<IHHQIH', data, info)
        segment = next((s for s in segments if s[1] in {text + segment_offset, segment_offset}),
                       None)
        if segment is None or not page_size:
            continue
        for page, start in enumerate(struct.unpack_from(f'<{page_count}H', data, info + 22)):
            if start != _CHAIN_START_NONE:
                _walk_chain(data, pointers, (segment[1], segment[2]),
                            (page * page_size + start, pointer_format, text, limit))
    return pointers


def _walk_chain(data: mmap.mmap, pointers: dict[int, int], segment: tuple[int, int],
                chain: tuple[int, int, int, int]) -> None:
    address, file_offset = segment
    cursor, pointer_format, text, limit = chain
    while file_offset + cursor + 8 <= limit:
        raw, = struct.unpack_from('<Q', data, file_offset + cursor)
        decoded = _decode_chained_pointer(raw, pointer_format, text)
        if decoded is None:
            return
        target, step = decoded
        if target is not None:
            pointers[address + cursor] = target
        if not step:
            return
        cursor += step


def _pe_sections(data: mmap.mmap) -> tuple[int, int, int, list[tuple[str, int, int, int]]]:
    header, = struct.unpack_from('<I', data, 0x3C)
    section_count, = struct.unpack_from('<H', data, header + 6)
    optional_size, = struct.unpack_from('<H', data, header + 20)
    optional = header + 24
    magic, = struct.unpack_from('<H', data, optional)
    if magic != _PE32_PLUS:
        msg = 'Not a PE32+ image.'
        raise FlagBinaryUnreadable(msg)
    image_base, = struct.unpack_from('<Q', data, optional + 24)
    relocation_rva, relocation_size = struct.unpack_from(
        '<II', data, optional + 112 + _PE_BASE_RELOCATION_INDEX * 8)
    sections = []
    for i in range(section_count):
        start = optional + optional_size + i * 40
        virtual_size, rva, raw_size, raw_offset = struct.unpack_from('<IIII', data, start + 8)
        sections.append((_fixed_string(data, start, 8), rva, min(virtual_size, raw_size)
                         or raw_size, raw_offset))
    return image_base, relocation_rva, relocation_size, sections


def _load_pe(data: mmap.mmap) -> _Image:
    image_base, relocation_rva, relocation_size, sections = _pe_sections(data)

    def to_offset(rva: int) -> int | None:
        for _, section_rva, size, raw_offset in sections:
            if section_rva <= rva < section_rva + max(size, 1):
                return raw_offset + (rva - section_rva)
        return None

    pointers: dict[int, int] = {}
    offset = to_offset(relocation_rva)
    end = (offset or 0) + relocation_size
    while offset is not None and offset < end:
        page_rva, block_size = struct.unpack_from('<II', data, offset)
        if block_size < _PE_RELOCATION_HEADER:
            break
        for i in range((block_size - _PE_RELOCATION_HEADER) // 2):
            entry, = struct.unpack_from('<H', data, offset + _PE_RELOCATION_HEADER + i * 2)
            if (entry >> 12) != _PE_DIR64:
                continue
            slot = page_rva + (entry & 0xFFF)
            if (slot_offset := to_offset(slot)) is not None:
                value, = struct.unpack_from('<Q', data, slot_offset)
                if value:
                    pointers[image_base + slot] = value
        offset += block_size
    regions = [(image_base + rva, raw_offset, size) for name, rva, size, raw_offset in sections
               if name in _PE_SECTIONS]
    return _Image(data, pointers, regions, regions)


def _entry_strings(image: _Image, va: int) -> tuple[str, str, str] | None:
    first, second, third = (image.pointers.get(va), image.pointers.get(va + 8),
                            image.pointers.get(va + 16))
    if first is None or second is None or third is None:
        return None
    name = image.string(first)
    if (not name or not _NAME_MINIMUM <= len(name) <= _NAME_MAXIMUM
            or any(character.isspace() for character in name)):
        return None
    title = image.string(second)
    if not title or not _NAME_MINIMUM <= len(title) <= _TITLE_MAXIMUM:
        return None
    description = image.string(third)
    if not description or len(description) < _DESCRIPTION_MINIMUM:
        return None
    return name, title, description


def _entry_addresses(image: _Image) -> range:
    seeds = {
        va
        for va in image.pointers if not va % 8 and (entry := _entry_strings(image, va))
        and _INTERNAL_NAME_RE.match(entry[0]) and len(entry[0]) <= _SEED_NAME_MAXIMUM
    }
    best: tuple[int, int] = (0, 0)
    seen: set[int] = set()
    for va in sorted(seeds):
        if va in seen:
            continue
        end = va
        while end in seeds:
            seen.add(end)
            end += FEATURE_ENTRY_STRIDE
        if end - va > best[1] - best[0]:
            best = (va, end)
    if best == (0, 0):
        return range(0)
    # kFeatureEntries is one contiguous C array, so a looser test may grow the run in both
    # directions. Without this the run stops at the first internal name carrying an uppercase
    # milestone suffix and recall drops by a fifth.
    low, high = best
    while _entry_strings(image, low - FEATURE_ENTRY_STRIDE) is not None:
        low -= FEATURE_ENTRY_STRIDE
    while _entry_strings(image, high) is not None:
        high += FEATURE_ENTRY_STRIDE
    return range(low, high, FEATURE_ENTRY_STRIDE)


def _decode_platforms(mask: int) -> str:
    if mask == _OS_ALL:
        return 'kOsAll'
    if mask == _OS_DESKTOP:
        return 'kOsDesktop'
    return ' | '.join(name for index, name in enumerate(OS_BITS) if mask & (1 << index))


def _scan(image: _Image) -> dict[str, dict[str, Any]]:
    table: dict[str, dict[str, Any]] = {}
    for va in _entry_addresses(image):
        if (entry := _entry_strings(image, va)) is None:
            continue
        name, title, description = entry
        word = image.word(va + _PLATFORM_OFFSET)
        kind = (word >> 16) & 0xFFFF
        table[name] = {
            'description': description,
            'expiry_milestone': None,
            'line': None,
            'name': title,
            'never_expires': False,
            'options': [],
            'os': _decode_platforms(word & 0xFFFF),
            'owners': [],
            'type': TYPE_NAMES[kind] if kind < len(TYPE_NAMES) else str(kind)
        }
    return table


@contextmanager
def _mapped(path: Path) -> Iterator[mmap.mmap]:
    try:
        with path.open('rb') as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
            yield data
    except (OSError, ValueError) as e:
        msg = f'Could not read `{path}`: {e}'
        raise FlagBinaryUnreadable(msg) from e


def _loaders(data: mmap.mmap, name: str) -> list[Callable[[], _Image]]:
    if data[:4] == _ELF_MAGIC:
        return [partial(_load_elf, data)]
    if data[:2] == _PE_MAGIC:
        return [partial(_load_pe, data)]
    if data[:4] in _MACHO_MAGICS:
        return [partial(_load_macho, data, offset, size) for offset, size in _macho_slices(data)]
    msg = f'`{name}` is not an ELF, Mach-O, or PE image.'
    raise FlagBinaryUnreadable(msg)


def extract_flag_table(binary: StrPath) -> dict[str, dict[str, Any]]:
    """
    Recover the ``chrome://flags`` table compiled into a browser binary.

    The result has the same shape as :py:func:`deltona.chrome.flags.parse_flag_sources` returns, so
    the two are interchangeable. ``expiry_milestone``, ``line``, ``never_expires``, and ``owners``
    are not compiled into the binary and are always ``None``, ``None``, ``False``, and ``[]``.
    ``options`` is always empty because the choice arrays cannot be associated with their entry,
    which leaves consumers to fall back to the generic Default, Enabled, and Disabled labels.

    A universal Mach-O binary is tried one slice at a time, and the first slice holding a table
    wins. Every slice of a shipped framework carries the same table.

    Parameters
    ----------
    binary : StrPath
        Path to the executable or library holding the table. On Windows this is ``chrome.dll``,
        never ``chrome.exe``, and on macOS it is the framework binary rather than the application's
        own executable.

    Returns
    -------
    dict[str, dict[str, Any]]
        Every flag keyed by internal name, with ``description``, ``expiry_milestone``, ``line``,
        ``name``, ``never_expires``, ``options``, ``os``, ``owners``, and ``type``.

    Raises
    ------
    FlagBinaryUnreadable
        If the file cannot be read, is not a recognised container, or holds no flag table. A result
        of fewer than 50 entries is treated as no table at all, which is what an unrelated binary
        yields.
    """
    path = Path(binary)
    with _mapped(path) as data:
        for load in _loaders(data, path.name):
            try:
                table = _scan(load())
            except (FlagBinaryUnreadable, IndexError, UnicodeDecodeError, ValueError,
                    struct.error) as e:
                log.debug('Could not scan `%s`: %s', path, e)
                continue
            if len(table) >= _MINIMUM_ENTRIES:
                return table
            log.debug('Rejecting %d entries recovered from `%s`.', len(table), path)
    msg = f'No flag table found in `{path}`.'
    raise FlagBinaryUnreadable(msg)


def _is_image(path: Path) -> bool:
    try:
        with path.open('rb') as f:
            head = f.read(4)
    except OSError:
        return False
    return any(head.startswith(magic) for magic in _IMAGE_MAGICS)


def _version_key(path: Path) -> tuple[int, ...]:
    return tuple(int(part) if part.isdigit() else 0 for part in path.name.split('.'))


def _newest_first(parent: Path) -> list[Path]:
    if not parent.is_dir():
        return []
    return sorted((child for child in parent.iterdir() if child.is_dir()),
                  key=_version_key,
                  reverse=True)


def _linux_candidates(channel: ChromeChannel) -> Iterator[Path]:
    # Google's packages name the install directory after the user data directory without the vendor
    # prefix, so `google-chrome-beta` is installed to `/opt/google/chrome-beta`.
    suffix = CHANNEL_DIRECTORIES['linux'][channel].removeprefix('google-')
    yield Path('/opt/google') / suffix / 'chrome'


def _macos_candidates(channel: ChromeChannel) -> Iterator[Path]:
    application = _MACOS_APP_NAMES[channel]
    for base in (Path('/Applications'), Path.home() / 'Applications'):
        framework = (base / f'{application}.app' / 'Contents' / 'Frameworks' /
                     f'{application} Framework.framework')
        for version in ('Current', *(path.name for path in _newest_first(framework / 'Versions'))):
            yield framework / 'Versions' / version / f'{application} Framework'


def _windows_candidates(channel: ChromeChannel) -> Iterator[Path]:
    for variable in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA'):
        if not (base := os.environ.get(variable)):
            continue
        application = Path(base) / _WINDOWS_DIRECTORY_NAMES[channel] / 'Application'
        for version in _newest_first(application):
            yield version / 'chrome.dll'


def find_browser_binary(channel: ChromeChannel = 'stable') -> Path | None:
    """
    Find the installed browser binary holding the flag table.

    On Linux this is the binary inside the directory Google's own package installs to. On Windows
    the newest versioned ``chrome.dll`` under each of the three install roots is preferred, and on
    macOS the framework binary inside the application bundle.

    Parameters
    ----------
    channel : ChromeChannel
        Release channel to look for. Default is ``'stable'``.

    Returns
    -------
    pathlib.Path | None
        Path to the binary, or ``None`` if no candidate exists. The file is only checked for a
        container magic number, so it may still turn out to hold no flag table.
    """
    if sys.platform == 'darwin':
        candidates = _macos_candidates(channel)
    elif sys.platform in {'cygwin', 'win32'}:
        candidates = _windows_candidates(channel)
    else:
        candidates = _linux_candidates(channel)
    for candidate in candidates:
        if candidate.is_file() and _is_image(candidate):
            log.debug('Using the browser binary at `%s`.', candidate)
            return candidate
    return None
