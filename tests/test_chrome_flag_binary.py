"""Tests for :py:mod:`deltona.chrome.flag_binary`."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple
import struct
import sys

import pytest

from deltona.chrome.flag_binary import (
    FEATURE_ENTRY_STRIDE,
    FlagBinaryUnreadable,
    extract_flag_table,
    find_browser_binary,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pytest_mock import MockerFixture

    from deltona.chrome.typing import ChromeChannel

_RODATA_ADDRESS = 0x1000
_SLOTS_ADDRESS = 0x8000
_RELOCATIONS_ADDRESS = 0x40000
_SECTION_HEADER_SIZE = 64
_RELATIVE = 8
_PROGBITS = 1
_ENOUGH = 60
_PE32_PLUS = 0x20B
_PE_BASE_RELOCATION_INDEX = 5
_PE_DATA_RVA = 0x20000
_PE_DIR64 = 10
_PE_HEADER = 0x80
_PE_IMAGE_BASE = 0x140000000
_PE_OPTIONAL_SIZE = 240
_PE_RDATA_RVA = 0x1000
_PE_RELOC_RVA = 0x40000
_MACHO_MAGIC_64 = 0xFEEDFACF
_MACHO_SEGMENT_64 = 0x19
_MACHO_CSTRING_ADDRESS = 0x2000
_MACHO_CONST_ADDRESS = 0x40000
_MACHO_CHAINED_FIXUPS = 0x80000034
_MACHO_FIXUPS_OFFSET = 0x1000
_MACHO_PAGE_SIZE = 0x1000
_CHAIN_FORMAT_OFFSET = 6


class _Entry(NamedTuple):
    name: str
    title: str
    description: str
    word: int = (4 << 16) | 0x1F


def _entries(count: int = _ENOUGH) -> list[_Entry]:
    return [
        _Entry(f'test-flag-{index:03d}', f'Test Flag {index}',
               f'Description number {index} of the synthetic flag table.') for index in range(count)
    ]


def _build_elf(entries: Sequence[_Entry],
               *,
               bad_name_position: bool = False,
               invalid_utf8: bool = False,
               stray_pointer: bool = False,
               no_words: bool = False,
               unterminated: bool = False) -> bytes:
    blob = bytearray()
    addresses: list[tuple[int, int, int]] = []
    for entry in entries:
        positions = []
        for text in (entry.name, entry.title, entry.description):
            positions.append(_RODATA_ADDRESS + len(blob))
            blob += text.encode() + b'\0'
        addresses.append((positions[0], positions[1], positions[2]))
    if unterminated:
        del blob[-1]
    if invalid_utf8:
        blob[-4] = 0xFF
    slots = bytearray(len(entries) * FEATURE_ENTRY_STRIDE + FEATURE_ENTRY_STRIDE)
    relocations = bytearray()
    for index, (entry, targets) in enumerate(zip(entries, addresses, strict=True)):
        slot = _SLOTS_ADDRESS + index * FEATURE_ENTRY_STRIDE
        struct.pack_into('<I', slots, index * FEATURE_ENTRY_STRIDE + 24, entry.word)
        for step, target in enumerate(targets):
            stray = stray_pointer and index == len(entries) - 1 and step == 2
            relocations += struct.pack('<QQq', slot + step * 8, _RELATIVE,
                                       1 << 40 if stray else target)
    names = bytearray(b'\0')
    name_positions: dict[str, int] = {}
    for name in ('.rodata', '.data.rel.ro', '.rodata.str1.1', '.rela.dyn', '.shstrtab'):
        name_positions[name] = len(names)
        names += name.encode() + b'\0'
    tail = b'A' * 64
    names_address = _RELOCATIONS_ADDRESS + len(relocations)
    header_address = names_address + len(names) + len(tail)
    sections = (
        (0, 0, 0, 0, 0),
        (name_positions['.rodata'], _PROGBITS, _RODATA_ADDRESS, _RODATA_ADDRESS, len(blob)),
        (name_positions['.rodata.str1.1' if no_words else '.data.rel.ro'], _PROGBITS,
         _SLOTS_ADDRESS, _SLOTS_ADDRESS, len(slots)),
        (1 << 30 if bad_name_position else name_positions['.rela.dyn'], 4, _RELOCATIONS_ADDRESS,
         _RELOCATIONS_ADDRESS, len(relocations)),
        (name_positions['.shstrtab'], 3, names_address, names_address, len(names)),
    )
    data = bytearray(header_address + len(sections) * _SECTION_HEADER_SIZE)
    struct.pack_into('<4sBBB', data, 0, b'\x7fELF', 2, 1, 1)
    struct.pack_into('<Q', data, 0x28, header_address)
    struct.pack_into('<HHH', data, 0x3A, _SECTION_HEADER_SIZE, len(sections), len(sections) - 1)
    data[_RODATA_ADDRESS:_RODATA_ADDRESS + len(blob)] = blob
    data[_SLOTS_ADDRESS:_SLOTS_ADDRESS + len(slots)] = slots
    data[_RELOCATIONS_ADDRESS:_RELOCATIONS_ADDRESS + len(relocations)] = relocations
    data[names_address:names_address + len(names)] = names
    data[names_address + len(names):header_address] = tail
    for index, (name_position, kind, address, offset, size) in enumerate(sections):
        struct.pack_into('<IIQQQQ', data, header_address + index * _SECTION_HEADER_SIZE,
                         name_position, kind, 0, address, offset, size)
    return bytes(data)


def _build_pe(entries: Sequence[_Entry],
              *,
              bad_block_size: bool = False,
              magic: int = _PE32_PLUS,
              relocation_type: int = _PE_DIR64,
              relocation_rva: int | None = None) -> bytes:
    blob = bytearray()
    targets: list[tuple[int, int, int]] = []
    for entry in entries:
        positions = []
        for text in (entry.name, entry.title, entry.description):
            positions.append(_PE_IMAGE_BASE + _PE_RDATA_RVA + len(blob))
            blob += text.encode() + b'\0'
        targets.append((positions[0], positions[1], positions[2]))
    slots = bytearray(len(entries) * FEATURE_ENTRY_STRIDE + FEATURE_ENTRY_STRIDE)
    pages: dict[int, list[int]] = {}
    for index, (entry, addresses) in enumerate(zip(entries, targets, strict=True)):
        base = index * FEATURE_ENTRY_STRIDE
        struct.pack_into('<I', slots, base + 24, entry.word)
        for step, target in enumerate(addresses):
            struct.pack_into('<Q', slots, base + step * 8, target)
            rva = _PE_DATA_RVA + base + step * 8
            pages.setdefault(rva & ~0xFFF, []).append(rva & 0xFFF)
    relocations = bytearray()
    for page, offsets in sorted(pages.items()):
        relocations += struct.pack('<II', page, 0 if bad_block_size else 8 + 2 * len(offsets))
        for offset in offsets:
            relocations += struct.pack('<H', (relocation_type << 12) | offset)
    regions = ((b'.rdata', _PE_RDATA_RVA, bytes(blob)), (b'.data', _PE_DATA_RVA, bytes(slots)),
               (b'.reloc', _PE_RELOC_RVA, bytes(relocations)))
    data = bytearray(_PE_RELOC_RVA + len(relocations) + 0x1000)
    data[0:2] = b'MZ'
    struct.pack_into('<I', data, 0x3C, _PE_HEADER)
    data[_PE_HEADER:_PE_HEADER + 4] = b'PE\0\0'
    struct.pack_into('<H', data, _PE_HEADER + 6, len(regions))
    struct.pack_into('<H', data, _PE_HEADER + 20, _PE_OPTIONAL_SIZE)
    optional = _PE_HEADER + 24
    struct.pack_into('<H', data, optional, magic)
    struct.pack_into('<Q', data, optional + 24, _PE_IMAGE_BASE)
    struct.pack_into('<II', data, optional + 112 + _PE_BASE_RELOCATION_INDEX * 8,
                     _PE_RELOC_RVA if relocation_rva is None else relocation_rva, len(relocations))
    for index, (name, rva, payload) in enumerate(regions):
        start = optional + _PE_OPTIONAL_SIZE + index * 40
        data[start:start + len(name)] = name
        struct.pack_into('<IIII', data, start + 8, len(payload), rva, len(payload), rva)
        data[rva:rva + len(payload)] = payload
    return bytes(data)


def _macho_section(sectname: bytes, segname: bytes, address: int, offset: int, size: int) -> bytes:
    section = bytearray(80)
    section[0:len(sectname)] = sectname
    section[16:16 + len(segname)] = segname
    struct.pack_into('<QQ', section, 32, address, size)
    struct.pack_into('<I', section, 48, offset)
    return bytes(section)


def _macho_segment(segname: bytes, address: int, offset: int, size: int,
                   sections: Sequence[bytes]) -> bytes:
    command = bytearray(72)
    struct.pack_into('<II', command, 0, _MACHO_SEGMENT_64, 72 + len(sections) * 80)
    command[8:8 + len(segname)] = segname
    struct.pack_into('<QQQQ', command, 24, address, size, offset, size)
    struct.pack_into('<I', command, 64, len(sections))
    return bytes(command) + b''.join(sections)


def _chain_links(count: int) -> list[tuple[int, int]]:
    offsets = [
        index * FEATURE_ENTRY_STRIDE + step * 8 for index in range(count) for step in (0, 1, 2)
    ]
    steps = [offsets[i + 1] - offsets[i] for i in range(len(offsets) - 1)]
    return list(zip(offsets, [*steps, 0], strict=True))


def _build_macho(entries: Sequence[_Entry],
                 *,
                 bad_command_size: bool = False,
                 bind_arm64e: bool = False,
                 bind_first: bool = False,
                 chain_format: int = _CHAIN_FORMAT_OFFSET,
                 empty_start: bool = False,
                 fat: bool = False,
                 fixups: bool = False,
                 magic: int = _MACHO_MAGIC_64,
                 page_size: int = _MACHO_PAGE_SIZE,
                 text_segment: bytes = b'__TEXT') -> bytes:
    blob = bytearray()
    targets: list[tuple[int, int, int]] = []
    for entry in entries:
        positions = []
        for text in (entry.name, entry.title, entry.description):
            positions.append(_MACHO_CSTRING_ADDRESS + len(blob))
            blob += text.encode() + b'\0'
        targets.append((positions[0], positions[1], positions[2]))
    slots = bytearray(len(entries) * FEATURE_ENTRY_STRIDE + FEATURE_ENTRY_STRIDE)
    flat = [target for addresses in targets for target in addresses]
    links = _chain_links(len(entries))
    for index, entry in enumerate(entries):
        struct.pack_into('<I', slots, index * FEATURE_ENTRY_STRIDE + 24, entry.word)
    for index, ((offset, step), target) in enumerate(zip(links, flat, strict=True)):
        raw = (((step // 4) << 51) | target) if fixups else target
        if fixups and not index:
            raw |= (1 << 63 if bind_first else 0) | (1 << 62 if bind_arm64e else 0)
        struct.pack_into('<Q', slots, offset, raw)
    commands = (_macho_segment(text_segment, 0, 0, _MACHO_CSTRING_ADDRESS + len(blob), [
        _macho_section(b'__cstring', b'__TEXT', _MACHO_CSTRING_ADDRESS, _MACHO_CSTRING_ADDRESS,
                       len(blob))
    ]) + _macho_segment(b'__DATA_CONST', _MACHO_CONST_ADDRESS, _MACHO_CONST_ADDRESS, len(slots), [
        _macho_section(b'__const', b'__DATA_CONST', _MACHO_CONST_ADDRESS, _MACHO_CONST_ADDRESS,
                       len(slots))
    ]))
    if bad_command_size:
        commands += struct.pack('<II', _MACHO_SEGMENT_64, 0)
    if fixups:
        commands += struct.pack('<IIII', _MACHO_CHAINED_FIXUPS, 16, _MACHO_FIXUPS_OFFSET, 64)
    image = bytearray(_MACHO_CONST_ADDRESS + len(slots) + 0x100)
    struct.pack_into('<IiiIIII', image, 0, magic, 0x01000007, 3, 6,
                     2 + int(fixups) + int(bad_command_size), len(commands), 0)
    image[32:32 + len(commands)] = commands
    if fixups:
        struct.pack_into('<IIIIIII', image, _MACHO_FIXUPS_OFFSET, 0, 32, 0, 0, 0, 0, 0)
        starts = _MACHO_FIXUPS_OFFSET + 32
        struct.pack_into('<III', image, starts, 2 if empty_start else 1, 12, 0)
        struct.pack_into('<IHHQIHHH', image, starts + 12, 26, page_size, chain_format,
                         _MACHO_CONST_ADDRESS, 0, 2, 0, 0xFFFF)
    image[_MACHO_CSTRING_ADDRESS:_MACHO_CSTRING_ADDRESS + len(blob)] = blob
    image[_MACHO_CONST_ADDRESS:_MACHO_CONST_ADDRESS + len(slots)] = slots
    if not fat:
        return bytes(image)
    header = bytearray(0x1000)
    header[0:4] = b'\xca\xfe\xba\xbe'
    struct.pack_into('>I', header, 4, 1)
    struct.pack_into('>IIIII', header, 8, 0x01000007, 3, len(header), len(image), 12)
    return bytes(header) + bytes(image)


def _write_macho(tmp_path: Path, entries: Sequence[_Entry], **kwargs: Any) -> Path:
    path = tmp_path / 'Google Chrome Framework'
    path.write_bytes(_build_macho(entries, **kwargs))
    return path


def _write_pe(tmp_path: Path, entries: Sequence[_Entry], **kwargs: Any) -> Path:
    path = tmp_path / 'chrome.dll'
    path.write_bytes(_build_pe(entries, **kwargs))
    return path


def _write_elf(tmp_path: Path, entries: Sequence[_Entry], **kwargs: Any) -> Path:
    path = tmp_path / 'chrome'
    path.write_bytes(_build_elf(entries, **kwargs))
    return path


def test_extract_recovers_every_entry(tmp_path: Path) -> None:
    table = extract_flag_table(_write_elf(tmp_path, _entries()))
    assert len(table) == _ENOUGH
    assert table['test-flag-000'] == {
        'description': 'Description number 0 of the synthetic flag table.',
        'expiry_milestone': None,
        'line': None,
        'name': 'Test Flag 0',
        'never_expires': False,
        'options': [],
        'os': 'kOsAll',
        'owners': [],
        'type': 'FEATURE_VALUE_TYPE'
    }


def test_extract_accepts_a_str_path(tmp_path: Path) -> None:
    assert len(extract_flag_table(str(_write_elf(tmp_path, _entries())))) == _ENOUGH


def test_extract_extends_the_run_past_an_unseedable_name(tmp_path: Path) -> None:
    entries = [
        *_entries(),
        _Entry('browsing-history-actor-integration-M3', 'Milestone Flag',
               'An internal name the seed pattern rejects.')
    ]
    table = extract_flag_table(_write_elf(tmp_path, entries))
    assert 'browsing-history-actor-integration-M3' in table
    assert len(table) == _ENOUGH + 1


@pytest.mark.parametrize(('mask', 'expected'), [
    (0x1F, 'kOsAll'),
    (0x0F, 'kOsDesktop'),
    (0x05, 'kOsMac | kOsLinux'),
    (0x80, 'kOsFuchsia'),
    (0, ''),
])
def test_platform_mask_decoding(tmp_path: Path, mask: int, expected: str) -> None:
    entries = _entries()
    entries[0] = entries[0]._replace(word=(4 << 16) | mask)
    assert extract_flag_table(_write_elf(tmp_path, entries))['test-flag-000']['os'] == expected


@pytest.mark.parametrize(('index', 'expected'), [
    (0, 'SINGLE_VALUE_TYPE'),
    (2, 'MULTI_VALUE_TYPE'),
    (9, 'PLATFORM_FEATURE_WITH_PARAMS_VALUE_TYPE'),
    (42, '42'),
])
def test_entry_type_decoding(tmp_path: Path, index: int, expected: str) -> None:
    entries = _entries()
    entries[0] = entries[0]._replace(word=(index << 16) | 0x1F)
    assert extract_flag_table(_write_elf(tmp_path, entries))['test-flag-000']['type'] == expected


@pytest.mark.parametrize('entry', [
    _Entry('a', 'Short Name', 'The internal name is below the minimum length.'),
    _Entry('has a space', 'Spaced', 'The internal name contains whitespace.'),
    _Entry('x' * 200, 'Too Long', 'The internal name is above the maximum length.'),
    _Entry('unprintable', 'T', 'The title is below the minimum length.'),
    _Entry('short-description', 'Fine Title', 'tiny'),
])
def test_implausible_entries_are_skipped(tmp_path: Path, entry: _Entry) -> None:
    entries = [*_entries(), entry]
    table = extract_flag_table(_write_elf(tmp_path, entries))
    assert len(table) == _ENOUGH


def test_a_control_character_rejects_the_string(tmp_path: Path) -> None:
    entries = [
        *_entries(),
        _Entry('bell-flag', 'Bell\x07Title', 'A title carrying a control byte.')
    ]
    assert len(extract_flag_table(_write_elf(tmp_path, entries))) == _ENOUGH


def test_too_few_entries_is_not_a_flag_table(tmp_path: Path) -> None:
    with pytest.raises(FlagBinaryUnreadable, match='No flag table found'):
        extract_flag_table(_write_elf(tmp_path, _entries(3)))


def test_a_truncated_section_name_table_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(FlagBinaryUnreadable, match='No flag table found'):
        extract_flag_table(_write_elf(tmp_path, _entries(), bad_name_position=True))


@pytest.mark.parametrize('content', [b'not a binary at all', b'\x00' * 64])
def test_an_unrecognised_container_is_rejected(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / 'chrome'
    path.write_bytes(content)
    with pytest.raises(FlagBinaryUnreadable, match='is not an ELF, Mach-O, or PE image'):
        extract_flag_table(path)


def test_an_unreadable_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(FlagBinaryUnreadable):
        extract_flag_table(tmp_path / 'missing')


def test_an_empty_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / 'chrome'
    path.touch()
    with pytest.raises(FlagBinaryUnreadable):
        extract_flag_table(path)


@pytest.mark.parametrize(('channel', 'expected'), [('stable', '/opt/google/chrome/chrome'),
                                                   ('beta', '/opt/google/chrome-beta/chrome'),
                                                   ('canary', '/opt/google/chrome-canary/chrome')])
def test_find_browser_binary_on_linux(mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch,
                                      channel: ChromeChannel, expected: str) -> None:
    monkeypatch.setattr(sys, 'platform', 'linux')
    mocker.patch.object(Path,
                        'is_file',
                        autospec=True,
                        side_effect=lambda self: str(self) == expected)
    mocker.patch.object(Path,
                        'open',
                        autospec=True,
                        side_effect=lambda _self, _mode: BytesIO(b'\x7fELF'))
    assert find_browser_binary(channel) == Path(expected)


def test_find_browser_binary_skips_a_file_that_is_not_an_image(
        mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, 'platform', 'linux')
    mocker.patch.object(Path, 'is_file', autospec=True, return_value=True)
    mocker.patch.object(Path,
                        'open',
                        autospec=True,
                        side_effect=lambda _self, _mode: BytesIO(b'#!/b'))
    assert find_browser_binary() is None


def test_find_browser_binary_skips_a_file_it_cannot_open(mocker: MockerFixture,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, 'platform', 'linux')
    mocker.patch.object(Path, 'is_file', autospec=True, return_value=True)
    mocker.patch.object(Path, 'open', autospec=True, side_effect=OSError)
    assert find_browser_binary() is None


def test_find_browser_binary_returns_none_when_nothing_matches(
        mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, 'platform', 'linux')
    mocker.patch.object(Path, 'is_file', autospec=True, return_value=False)
    assert find_browser_binary('beta') is None


@pytest.mark.parametrize(('channel', 'application'), [('stable', 'Google Chrome'),
                                                      ('beta', 'Google Chrome Beta'),
                                                      ('chromium', 'Chromium')])
def test_find_browser_binary_on_macos(tmp_path: Path, mocker: MockerFixture,
                                      monkeypatch: pytest.MonkeyPatch, channel: ChromeChannel,
                                      application: str) -> None:
    monkeypatch.setattr(sys, 'platform', 'darwin')
    mocker.patch('deltona.chrome.flag_binary.Path.home', return_value=tmp_path)
    framework = (tmp_path / 'Applications' / f'{application}.app' / 'Contents' / 'Frameworks' /
                 f'{application} Framework.framework' / 'Versions')
    for version in ('120.0.1.2', '99.0.0.1'):
        (framework / version).mkdir(parents=True)
        (framework / version / f'{application} Framework').write_bytes(b'\xcf\xfa\xed\xfe')
    assert find_browser_binary(channel) == (framework / '120.0.1.2' / f'{application} Framework')


def test_find_browser_binary_on_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.delenv('PROGRAMFILES', raising=False)
    monkeypatch.delenv('PROGRAMFILES(X86)', raising=False)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    application = tmp_path / 'Google' / 'Chrome' / 'Application'
    for version in ('120.0.1.2', '99.0.0.1'):
        (application / version).mkdir(parents=True)
        (application / version / 'chrome.dll').write_bytes(b'MZ' + b'\0' * 62)
    assert find_browser_binary() == application / '120.0.1.2' / 'chrome.dll'


def test_pe_image_recovers_every_entry(tmp_path: Path) -> None:
    table = extract_flag_table(_write_pe(tmp_path, _entries()))
    assert len(table) == _ENOUGH
    assert table['test-flag-001']['name'] == 'Test Flag 1'
    assert table['test-flag-001']['description'].startswith('Description number 1')
    assert table['test-flag-001']['os'] == 'kOsAll'
    assert table['test-flag-001']['type'] == 'FEATURE_VALUE_TYPE'


def test_a_pe32_image_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(FlagBinaryUnreadable, match='No flag table found'):
        extract_flag_table(_write_pe(tmp_path, _entries(), magic=0x10B))


def test_macho_image_recovers_every_entry(tmp_path: Path) -> None:
    table = extract_flag_table(_write_macho(tmp_path, _entries()))
    assert len(table) == _ENOUGH
    assert table['test-flag-002']['name'] == 'Test Flag 2'
    assert table['test-flag-002']['os'] == 'kOsAll'


def test_a_fat_macho_image_recovers_every_entry(tmp_path: Path) -> None:
    assert len(extract_flag_table(_write_macho(tmp_path, _entries(), fat=True))) == _ENOUGH


def test_a_32_bit_macho_slice_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(FlagBinaryUnreadable, match='No flag table found'):
        extract_flag_table(_write_macho(tmp_path, _entries(), fat=True, magic=0xFEEDFACE))


def test_a_thin_32_bit_macho_is_not_a_recognised_container(tmp_path: Path) -> None:
    with pytest.raises(FlagBinaryUnreadable, match='is not an ELF, Mach-O, or PE image'):
        extract_flag_table(_write_macho(tmp_path, _entries(), magic=0xFEEDFACE))


def test_macho_chained_fixups_recover_every_entry(tmp_path: Path) -> None:
    table = extract_flag_table(_write_macho(tmp_path, _entries(), fixups=True))
    assert len(table) == _ENOUGH
    assert table['test-flag-003']['name'] == 'Test Flag 3'
    assert table['test-flag-003']['description'].startswith('Description number 3')


def test_an_unterminated_string_drops_only_its_own_entry(tmp_path: Path) -> None:
    table = extract_flag_table(_write_elf(tmp_path, _entries(), unterminated=True))
    assert len(table) == _ENOUGH - 1
    assert f'test-flag-{_ENOUGH - 1:03d}' not in table


def test_a_missing_word_section_leaves_the_platform_undecoded(tmp_path: Path) -> None:
    table = extract_flag_table(_write_elf(tmp_path, _entries(), no_words=True))
    assert not table['test-flag-000']['os']
    assert table['test-flag-000']['type'] == 'SINGLE_VALUE_TYPE'


def test_entries_that_cannot_seed_a_run_yield_no_table(tmp_path: Path) -> None:
    entries = [
        _Entry(f'UPPER-FLAG-{index:03d}', f'Upper Flag {index}',
               f'Description number {index} of the synthetic flag table.')
        for index in range(_ENOUGH)
    ]
    with pytest.raises(FlagBinaryUnreadable, match='No flag table found'):
        extract_flag_table(_write_elf(tmp_path, entries))


def test_a_macho_load_command_of_impossible_size_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(FlagBinaryUnreadable, match='No flag table found'):
        extract_flag_table(_write_macho(tmp_path, _entries(), bad_command_size=True))


def test_a_macho_without_a_text_segment_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(FlagBinaryUnreadable, match='No flag table found'):
        extract_flag_table(_write_macho(tmp_path, _entries(), text_segment=b'__LINKEDIT'))


@pytest.mark.parametrize('chain_format', [1, 99])
def test_an_unusable_chain_format_yields_no_table(tmp_path: Path, chain_format: int) -> None:
    with pytest.raises(FlagBinaryUnreadable, match='No flag table found'):
        extract_flag_table(
            _write_macho(tmp_path, _entries(), fixups=True, chain_format=chain_format))


def test_a_relocation_block_of_impossible_size_stops_the_walk(tmp_path: Path) -> None:
    with pytest.raises(FlagBinaryUnreadable, match='No flag table found'):
        extract_flag_table(_write_pe(tmp_path, _entries(), bad_block_size=True))


def test_relocations_of_another_type_are_ignored(tmp_path: Path) -> None:
    with pytest.raises(FlagBinaryUnreadable, match='No flag table found'):
        extract_flag_table(_write_pe(tmp_path, _entries(), relocation_type=3))


def test_a_relocation_directory_outside_every_section_is_ignored(tmp_path: Path) -> None:
    with pytest.raises(FlagBinaryUnreadable, match='No flag table found'):
        extract_flag_table(_write_pe(tmp_path, _entries(), relocation_rva=0x900000))


def test_the_run_extends_backwards_past_an_unseedable_name(tmp_path: Path) -> None:
    entries = [
        _Entry('Leading-Milestone-M3', 'Leading Flag', 'An entry before the seeded run.'),
        *_entries()
    ]
    table = extract_flag_table(_write_elf(tmp_path, entries))
    assert 'Leading-Milestone-M3' in table
    assert len(table) == _ENOUGH + 1


def test_a_string_that_is_not_utf8_is_rejected(tmp_path: Path) -> None:
    table = extract_flag_table(_write_elf(tmp_path, _entries(), invalid_utf8=True))
    assert len(table) == _ENOUGH - 1


def test_a_bind_link_is_skipped_but_the_chain_continues(tmp_path: Path) -> None:
    table = extract_flag_table(_write_macho(tmp_path, _entries(), bind_first=True, fixups=True))
    assert len(table) == _ENOUGH - 1
    assert 'test-flag-001' in table


def test_an_empty_segment_start_is_skipped(tmp_path: Path) -> None:
    table = extract_flag_table(_write_macho(tmp_path, _entries(), empty_start=True, fixups=True))
    assert len(table) == _ENOUGH


def test_a_segment_without_a_page_size_is_skipped(tmp_path: Path) -> None:
    with pytest.raises(FlagBinaryUnreadable, match='No flag table found'):
        extract_flag_table(_write_macho(tmp_path, _entries(), fixups=True, page_size=0))


def test_a_pointer_outside_every_string_section_is_rejected(tmp_path: Path) -> None:
    table = extract_flag_table(_write_elf(tmp_path, _entries(), stray_pointer=True))
    assert len(table) == _ENOUGH - 1


def test_an_arm64e_bind_link_is_skipped(tmp_path: Path) -> None:
    with pytest.raises(FlagBinaryUnreadable, match='No flag table found'):
        extract_flag_table(
            _write_macho(tmp_path, _entries(), bind_arm64e=True, chain_format=1, fixups=True))
