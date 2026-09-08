"""Tests for :py:mod:`deltona.chrome.flag_binary`."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any
import errno
import os
import struct
import sys

import pytest

from deltona.chrome.flag_binary import (
    FEATURE_ENTRY_STRIDE,
    OS_BITS,
    TYPE_NAMES,
    FlagBinaryUnreadable,
    extract_flag_table,
    find_browser_binary,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

_PLATFORM_OFFSET = 24
_SECTION_HEADER_SIZE = 64
_UNMAPPED_VA = 0x900000
_DECOY_BASE = 0x20000
_ELF_STRING_BASE = 0x1000
_ELF_WORD_BASE = 0x8000
_ELF_NAMES = b'\0.rodata\0.data\0.rela.dyn\0.shstrtab\0'
_ELF_NAME_POSITIONS = (0, 1, 9, 15, 25)
_PE_IMAGE_BASE = 0x140000000
_PE_STRING_RVA = 0x1000
_PE_WORD_RVA = 0x8000
_PE_RELOCATION_RVA = 0x20000
_PE_HEADER_RVA = 0x80
_PE_OPTIONAL_RVA = 0x98
_PE_OPTIONAL_SIZE = 240
_PE_SECTION_RVA = _PE_OPTIONAL_RVA + _PE_OPTIONAL_SIZE
_MACHO_TEXT_VA = 0x100000000
_MACHO_FIXUPS_OFFSET = 0x4000
_MACHO_STRING_OFFSET = 0x1000
_MACHO_WORD_OFFSET = 0x8000
_MACHO_SLICE_SIZE = 0x14000
_MACHO_PAGE_SIZE = 0x4000
_MACHO_CPU_TYPE = 0x100000C
_ENTRY_COUNT = 60
_FEATURE_VALUE_TYPE = TYPE_NAMES.index('FEATURE_VALUE_TYPE')
_LINUX_BETA_BINARY = Path('/opt/google/chrome-beta/chrome')
_DECOYS: tuple[tuple[int, tuple[bytes | None, bytes | None, bytes | None]], ...] = (
    (_DECOY_BASE + 4, (b'unaligned-name', b'Unaligned', b'Unaligned description.')),
    (_DECOY_BASE + 0x100, (None, b'Title', b'Description here.')),
    (_DECOY_BASE + 0x200, (b'x', b'Title', b'Description here.')),
    (_DECOY_BASE + 0x300, (b'a' * 121, b'Title', b'Description here.')),
    (_DECOY_BASE + 0x400, (b'has space', b'Title', b'Description here.')),
    (_DECOY_BASE + 0x500, (b'ok-name', None, b'Description here.')),
    (_DECOY_BASE + 0x600, (b'ok-name', b'T' * 301, b'Description here.')),
    (_DECOY_BASE + 0x700, (b'ok-name', b'Title', None)),
    (_DECOY_BASE + 0x800, (b'ok-name', b'Title', b'short')),
    (_DECOY_BASE + 0x900, (b'ok-name', b'Title', b'')),
    (_DECOY_BASE + 0xA00, (b'bad\x01byte', b'Title', b'Description here.')),
    (_DECOY_BASE + 0xB00, (b'bad\xffutf8', b'Title', b'Description here.')),
    (_DECOY_BASE + 0xC00, (b'a' * 101, b'Title', b'Description here.')),
    (_DECOY_BASE + 0xD00, (b'isolated-seed', b'Isolated', b'Isolated description.')),
)


def _entries(count: int = _ENTRY_COUNT,
             words: Mapping[int, int] | None = None,
             names: Mapping[int, str] | None = None) -> tuple[tuple[str, str, str, int], ...]:
    default = (_FEATURE_VALUE_TYPE << 16) | 0x1F
    return tuple(((names or {}).get(index, f'test-flag-{index:03d}'), f'Test flag {index}',
                  f'Description of test flag number {index}.', (words or {}).get(index, default))
                 for index in range(count))


def _layout(entries: Sequence[tuple[str, str, str,
                                    int]], decoys: Sequence[tuple[int, Sequence[bytes | None]]],
            string_base: int, word_base: int) -> tuple[bytes, dict[int, int]]:
    payloads: list[bytes] = []
    slots: list[tuple[int, list[int | None]]] = []
    for index, entry in enumerate(entries):
        targets: list[int | None] = []
        for text in entry[:3]:
            payloads.append(text.encode())
            targets.append(len(payloads) - 1)
        slots.append((word_base + index * FEATURE_ENTRY_STRIDE, targets))
    for va, decoy in decoys:
        decoy_targets: list[int | None] = []
        for payload in decoy:
            if payload is None:
                decoy_targets.append(None)
            else:
                payloads.append(payload)
                decoy_targets.append(len(payloads) - 1)
        slots.append((va, decoy_targets))
    blob = bytearray()
    offsets: list[int] = []
    for payload in payloads:
        offsets.append(len(blob))
        blob += payload + b'\0'
    pointers = {
        va + step * 8: (_UNMAPPED_VA if target is None else string_base + offsets[target])
        for va, targets in slots
        for step, target in enumerate(targets)
    }
    return bytes(blob), pointers


def _word_blob(entries: Sequence[tuple[str, str, str, int]]) -> bytearray:
    blob = bytearray(FEATURE_ENTRY_STRIDE * len(entries))
    for index, entry in enumerate(entries):
        struct.pack_into('<I', blob, index * FEATURE_ENTRY_STRIDE + _PLATFORM_OFFSET, entry[3])
    return blob


def _build_elf(path: Path,
               entries: Sequence[tuple[str, str, str, int]],
               decoys: Sequence[tuple[int, Sequence[bytes | None]]] = (),
               *,
               relocations: bool = True,
               truncated_names: bool = False,
               word_kind: int = 1) -> Path:
    strings, pointers = _layout(entries, decoys, _ELF_STRING_BASE, _ELF_WORD_BASE)
    words = _word_blob(entries)
    assert _ELF_STRING_BASE + len(strings) <= _ELF_WORD_BASE
    data = bytearray(_ELF_WORD_BASE + len(words))
    data[:4] = b'\x7fELF'
    data[_ELF_STRING_BASE:_ELF_STRING_BASE + len(strings)] = strings
    data[_ELF_WORD_BASE:] = words
    relocation_offset = len(data)
    if relocations:
        for va, target in sorted(pointers.items()):
            data += struct.pack('<QQq', va, 8, target)
    relocation_size = len(data) - relocation_offset
    names_offset = len(data)
    data += _ELF_NAMES
    sections = [(_ELF_NAME_POSITIONS[0], 0, 0, 0, 0),
                (_ELF_NAME_POSITIONS[1], 1, _ELF_STRING_BASE, _ELF_STRING_BASE, len(strings)),
                (_ELF_NAME_POSITIONS[2], word_kind, _ELF_WORD_BASE, _ELF_WORD_BASE, len(words))]
    if relocations:
        sections.append((_ELF_NAME_POSITIONS[3], 4, 0, relocation_offset, relocation_size))
    sections.append((_ELF_NAME_POSITIONS[4], 3, 0, names_offset, len(_ELF_NAMES)))
    section_offset = len(data)
    for name_position, kind, address, offset, size in sections:
        data += struct.pack('<IIQQQQ', name_position, kind, 0, address, offset, size).ljust(
            _SECTION_HEADER_SIZE, b'\0')
    struct.pack_into('<Q', data, 0x28, section_offset)
    struct.pack_into('<HHH', data, 0x3A, _SECTION_HEADER_SIZE, len(sections), len(sections) - 1)
    if truncated_names:
        struct.pack_into('<Q',
                         data, section_offset + (len(sections) - 1) * _SECTION_HEADER_SIZE + 24,
                         len(data))
        data += b'x' * 16
    path.write_bytes(data)
    return path


def _relocation_blocks(slots: Sequence[int]) -> bytes:
    blocks = bytearray()
    for page in sorted({slot & ~0xFFF for slot in slots}):
        # A trailing IMAGE_REL_BASED_ABSOLUTE entry is what a real linker pads a block with.
        payload = b''.join(
            struct.pack('<H', (10 << 12) | (slot & 0xFFF))
            for slot in slots if slot & ~0xFFF == page) + struct.pack('<H', 0)
        blocks += struct.pack('<II', page, 8 + len(payload)) + payload
    return bytes(blocks)


def _build_pe(path: Path,
              entries: Sequence[tuple[str, str, str, int]],
              *,
              magic: int = 0x20B,
              relocation_rva: int = _PE_RELOCATION_RVA,
              short_block: bool = False) -> Path:
    strings, pointers = _layout(entries, (), _PE_IMAGE_BASE + _PE_STRING_RVA,
                                _PE_IMAGE_BASE + _PE_WORD_RVA)
    words = _word_blob(entries)
    assert _PE_STRING_RVA + len(strings) <= _PE_WORD_RVA
    slots = sorted(va - _PE_IMAGE_BASE for va in pointers)
    slots += [_PE_WORD_RVA + 32, _PE_RELOCATION_RVA + 0x100000]
    blocks = (struct.pack('<II', 0, 0) if short_block else b'') + _relocation_blocks(slots)
    data = bytearray(_PE_RELOCATION_RVA + len(blocks))
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3C, _PE_HEADER_RVA)
    data[_PE_HEADER_RVA:_PE_HEADER_RVA + 4] = b'PE\0\0'
    struct.pack_into('<HHIIIHH', data, _PE_HEADER_RVA + 4, 0x8664, 3, 0, 0, 0, _PE_OPTIONAL_SIZE,
                     0x22)
    struct.pack_into('<H', data, _PE_OPTIONAL_RVA, magic)
    struct.pack_into('<Q', data, _PE_OPTIONAL_RVA + 24, _PE_IMAGE_BASE)
    struct.pack_into('<II', data, _PE_OPTIONAL_RVA + 112 + 5 * 8, relocation_rva, len(blocks))
    for index, (name, rva, size) in enumerate(
        (('.rdata', _PE_STRING_RVA, len(strings)), ('.data', _PE_WORD_RVA, len(words)),
         ('.reloc', _PE_RELOCATION_RVA, len(blocks)))):
        start = _PE_SECTION_RVA + index * 40
        data[start:start + len(name)] = name.encode()
        struct.pack_into('<IIII', data, start + 8, size, rva, size, rva)
    data[_PE_STRING_RVA:_PE_STRING_RVA + len(strings)] = strings
    data[_PE_WORD_RVA:_PE_WORD_RVA + len(words)] = words
    data[_PE_RELOCATION_RVA:] = blocks
    for va, target in pointers.items():
        struct.pack_into('<Q', data, va - _PE_IMAGE_BASE, target)
    path.write_bytes(data)
    return path


def _chain_link(target: int, step: int, pointer_format: int) -> int:
    if pointer_format in {2, 6}:
        return (target if pointer_format == 2 else target - _MACHO_TEXT_VA) | ((step // 4) << 51)
    return (target - _MACHO_TEXT_VA) | ((step // 8) << 51)


def _chain_bind(pointer_format: int) -> int:
    return 1 << (63 if pointer_format in {2, 6} else 62)


def _section_64(section: str, segment: str, address: int, size: int, offset: int) -> bytes:
    return (section.encode().ljust(16, b'\0') + segment.encode().ljust(16, b'\0') +
            struct.pack('<QQ', address, size) +
            struct.pack('<IIIIIIII', offset, 0, 0, 0, 0, 0, 0, 0))


def _segment_64(name: str, address: int, offset: int, size: int,
                sections: Sequence[bytes]) -> bytes:
    command = bytearray(
        struct.pack('<II', 0x19, 0) + name.encode().ljust(16, b'\0') +
        struct.pack('<QQQQ', address, size, offset, size) +
        struct.pack('<IIII', 7, 7, len(sections), 0) + b''.join(sections))
    struct.pack_into('<I', command, 4, len(command))
    return bytes(command)


def _fixups_blob(pointer_format: int) -> bytes:
    blob = bytearray(0x1000)
    struct.pack_into('<IIIIIII', blob, 0, 0, 32, 0, 0, 0, 0, 0)
    struct.pack_into('<IIIII', blob, 32, 4, 0, 0x40, 0x80, 0xC0)
    struct.pack_into('<IHHQIH', blob, 32 + 0x40, 0, _MACHO_PAGE_SIZE, pointer_format,
                     _MACHO_WORD_OFFSET, 0, 3)
    struct.pack_into('<HHH', blob, 32 + 0x40 + 22, 0, 0xFFFF, _MACHO_PAGE_SIZE - 8)
    struct.pack_into('<IHHQIH', blob, 32 + 0x80, 0, _MACHO_PAGE_SIZE, pointer_format, 0x50000, 0, 0)
    struct.pack_into('<IHHQIH', blob, 32 + 0xC0, 0, 0, pointer_format, _MACHO_WORD_OFFSET, 0, 0)
    return bytes(blob)


def _build_macho_slice(entries: Sequence[tuple[str, str, str, int]],
                       *,
                       command_size: int | None = None,
                       high_bit_link: bool = False,
                       magic: int = 0xFEEDFACF,
                       pointer_format: int | None = None,
                       text_segment: bool = True) -> bytes:
    word_va = _MACHO_TEXT_VA + _MACHO_WORD_OFFSET
    strings, pointers = _layout(entries, (), _MACHO_TEXT_VA + _MACHO_STRING_OFFSET, word_va)
    words = _word_blob(entries)
    assert _MACHO_STRING_OFFSET + len(strings) <= _MACHO_FIXUPS_OFFSET
    data = bytearray(_MACHO_SLICE_SIZE)
    struct.pack_into('<IIIIIII', data, 0, magic, _MACHO_CPU_TYPE, 0, 6, 0, 0, 0)
    commands = []
    if text_segment:
        commands.append(
            _segment_64('__TEXT', _MACHO_TEXT_VA, 0, _MACHO_WORD_OFFSET, [
                _section_64('__cstring', '__TEXT', _MACHO_TEXT_VA + _MACHO_STRING_OFFSET,
                            len(strings), _MACHO_STRING_OFFSET)
            ]))
    commands.extend((_segment_64(
        '__DATA', word_va, _MACHO_WORD_OFFSET, _MACHO_SLICE_SIZE - _MACHO_WORD_OFFSET, [
            _section_64('__data', '__DATA', word_va, len(words), _MACHO_WORD_OFFSET),
            _section_64('__bss', '__DATA', _MACHO_TEXT_VA + 0x13000, 0x100, 0)
        ]), struct.pack('<II', 0x1B, 24) + b'\0' * 16))
    if pointer_format is not None:
        commands.append(struct.pack('<IIII', 0x80000034, 16, _MACHO_FIXUPS_OFFSET, 0x1000))
        data[_MACHO_FIXUPS_OFFSET:_MACHO_FIXUPS_OFFSET + 0x1000] = _fixups_blob(pointer_format)
        struct.pack_into('<Q', data, _MACHO_SLICE_SIZE - 8,
                         _chain_link(_MACHO_TEXT_VA, 8, pointer_format))
    if command_size is not None:
        commands.append(struct.pack('<II', 0x1B, command_size))
    blob = b''.join(commands)
    data[0x20:0x20 + len(blob)] = blob
    struct.pack_into('<II', data, 16, len(commands), len(blob))
    data[_MACHO_STRING_OFFSET:_MACHO_STRING_OFFSET + len(strings)] = strings
    if pointer_format is None:
        for va, target in pointers.items():
            struct.pack_into('<Q', words, va - word_va, target)
    else:
        for index in range(len(entries)):
            for step in range(3):
                offset = index * FEATURE_ENTRY_STRIDE + step * 8
                if index == len(entries) - 1 and step == 2:
                    raw = _chain_bind(pointer_format)
                else:
                    jump = 8 if step < 2 else FEATURE_ENTRY_STRIDE - 16
                    raw = _chain_link(pointers[word_va + offset], jump, pointer_format)
                    if high_bit_link and not index and not step:
                        raw |= 1 << 63
                struct.pack_into('<Q', words, offset, raw)
    data[_MACHO_WORD_OFFSET:_MACHO_WORD_OFFSET + len(words)] = words
    return bytes(data)


def _build_fat(path: Path, slices: Sequence[bytes], magic: bytes) -> Path:
    wide = magic == b'\xca\xfe\xba\xbf'
    start = 8 + (32 if wide else 20) * len(slices)
    offset = (start + 0xFFF) & ~0xFFF
    header = bytearray(magic + struct.pack('>I', len(slices)))
    body = bytearray()
    for payload in slices:
        position = offset + len(body)
        header += (struct.pack('>IIQQQ', _MACHO_CPU_TYPE, 0, position, len(payload), 14) if wide
                   else struct.pack('>IIIII', _MACHO_CPU_TYPE, 0, position, len(payload), 14))
        body += payload
    data = bytearray(offset)
    data[:len(header)] = header
    data += body
    path.write_bytes(data)
    return path


def _write_macho(path: Path, payload: bytes) -> Path:
    path.write_bytes(payload)
    return path


def _write_image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'\x7fELF' + bytes(60))
    return path


def _write_decoy_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'#!/bin/sh\n')
    return path


def _confine(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    original = Path.is_file
    monkeypatch.setattr(Path, 'is_file', lambda self: self.is_relative_to(root) and original(self))


def _redirect(monkeypatch: pytest.MonkeyPatch, target: Path, source: Path | None) -> None:
    original = Path.open

    # A `source` of None stands for a candidate that exists but cannot be read. Falling through to
    # the real `target` would make the result depend on whether a browser is installed here.
    def opener(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self != target:
            return original(self, *args, **kwargs)
        if source is None:
            raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), str(target))
        return original(source, *args, **kwargs)

    monkeypatch.setattr(Path, 'is_file', lambda self: self == target)
    monkeypatch.setattr(Path, 'open', opener)


def test_extract_flag_table_reads_an_elf_image(tmp_path: Path) -> None:
    words = {
        0: (_FEATURE_VALUE_TYPE << 16) | 0x1F,
        1: 0x0F,
        2: (TYPE_NAMES.index('MULTI_VALUE_TYPE') << 16) | 0x05,
        3: 99 << 16
    }
    table = extract_flag_table(_build_elf(tmp_path / 'chrome', _entries(words=words), _DECOYS))
    assert len(table) == _ENTRY_COUNT
    assert 'isolated-seed' not in table
    assert table['test-flag-000'] == {
        'description': 'Description of test flag number 0.',
        'expiry_milestone': None,
        'line': None,
        'name': 'Test flag 0',
        'never_expires': False,
        'options': [],
        'os': 'kOsAll',
        'owners': [],
        'type': 'FEATURE_VALUE_TYPE'
    }
    assert table['test-flag-001']['os'] == 'kOsDesktop'
    assert table['test-flag-001']['type'] == 'SINGLE_VALUE_TYPE'
    assert table['test-flag-002']['os'] == f'{OS_BITS[0]} | {OS_BITS[2]}'
    assert table['test-flag-002']['type'] == 'MULTI_VALUE_TYPE'
    assert not table['test-flag-003']['os']
    assert table['test-flag-003']['type'] == '99'
    assert table['test-flag-059']['name'] == 'Test flag 59'


def test_extract_flag_table_accepts_allowed_control_characters(tmp_path: Path) -> None:
    entries = list(_entries())
    entries[0] = (entries[0][0], entries[0][1], 'First line.\n\tSecond line.', entries[0][3])
    table = extract_flag_table(_build_elf(tmp_path / 'chrome', entries))
    assert table['test-flag-000']['description'] == 'First line.\n\tSecond line.'


def test_extract_flag_table_extends_the_run_in_both_directions(tmp_path: Path) -> None:
    names = {0: 'leading-entry-M3', _ENTRY_COUNT + 1: 'browsing-history-actor-integration-M3'}
    table = extract_flag_table(
        _build_elf(tmp_path / 'chrome', _entries(_ENTRY_COUNT + 2, names=names)))
    assert len(table) == _ENTRY_COUNT + 2
    assert 'leading-entry-M3' in table
    assert 'browsing-history-actor-integration-M3' in table


def test_extract_flag_table_without_word_sections(tmp_path: Path) -> None:
    table = extract_flag_table(_build_elf(tmp_path / 'chrome', _entries(), word_kind=0))
    assert not table['test-flag-000']['os']
    assert table['test-flag-000']['type'] == 'SINGLE_VALUE_TYPE'


def test_extract_flag_table_rejects_too_few_entries(tmp_path: Path) -> None:
    path = _build_elf(tmp_path / 'chrome', _entries(10))
    with pytest.raises(FlagBinaryUnreadable, match='No flag table found'):
        extract_flag_table(path)


def test_extract_flag_table_rejects_an_elf_without_relocations(tmp_path: Path) -> None:
    path = _build_elf(tmp_path / 'chrome', _entries(), relocations=False)
    with pytest.raises(FlagBinaryUnreadable, match='No flag table found'):
        extract_flag_table(path)


def test_extract_flag_table_rejects_a_truncated_section_name_table(tmp_path: Path) -> None:
    path = _build_elf(tmp_path / 'chrome', _entries(), truncated_names=True)
    with pytest.raises(FlagBinaryUnreadable, match='No flag table found'):
        extract_flag_table(path)


def test_extract_flag_table_rejects_a_file_that_is_not_an_image(tmp_path: Path) -> None:
    path = tmp_path / 'notes.txt'
    path.write_bytes(b'just some text, not a binary at all')
    with pytest.raises(FlagBinaryUnreadable, match='is not an ELF, Mach-O, or PE image'):
        extract_flag_table(path)


def test_extract_flag_table_rejects_an_empty_file(tmp_path: Path) -> None:
    path = tmp_path / 'empty'
    path.write_bytes(b'')
    with pytest.raises(FlagBinaryUnreadable, match='Could not read'):
        extract_flag_table(path)


def test_extract_flag_table_rejects_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FlagBinaryUnreadable, match='Could not read'):
        extract_flag_table(tmp_path / 'nothing-here')


def test_extract_flag_table_reads_a_pe_image(tmp_path: Path) -> None:
    words = {1: 0x0F, 2: (TYPE_NAMES.index('MULTI_VALUE_TYPE') << 16) | 0x05}
    table = extract_flag_table(_build_pe(tmp_path / 'chrome.dll', _entries(words=words)))
    assert len(table) == _ENTRY_COUNT
    assert table['test-flag-000']['os'] == 'kOsAll'
    assert table['test-flag-001']['os'] == 'kOsDesktop'
    assert table['test-flag-002']['os'] == f'{OS_BITS[0]} | {OS_BITS[2]}'


def test_extract_flag_table_rejects_a_pe32_image(tmp_path: Path) -> None:
    path = _build_pe(tmp_path / 'chrome.dll', _entries(), magic=0x10B)
    with pytest.raises(FlagBinaryUnreadable, match='No flag table found'):
        extract_flag_table(path)


def test_extract_flag_table_rejects_a_pe_with_an_orphan_relocation_directory(
        tmp_path: Path) -> None:
    path = _build_pe(tmp_path / 'chrome.dll', _entries(), relocation_rva=0x900000)
    with pytest.raises(FlagBinaryUnreadable, match='No flag table found'):
        extract_flag_table(path)


def test_extract_flag_table_rejects_a_pe_with_a_short_relocation_block(tmp_path: Path) -> None:
    path = _build_pe(tmp_path / 'chrome.dll', _entries(), short_block=True)
    with pytest.raises(FlagBinaryUnreadable, match='No flag table found'):
        extract_flag_table(path)


def test_extract_flag_table_reads_a_thin_macho_image(tmp_path: Path) -> None:
    table = extract_flag_table(
        _write_macho(tmp_path / 'Chrome Framework', _build_macho_slice(_entries())))
    assert len(table) == _ENTRY_COUNT
    assert table['test-flag-000']['name'] == 'Test flag 0'


@pytest.mark.parametrize(('pointer_format', 'high_bit_link'), [(2, False), (6, False), (1, True)])
def test_extract_flag_table_reads_chained_fixups(tmp_path: Path, pointer_format: int, *,
                                                 high_bit_link: bool) -> None:
    payload = _build_macho_slice(_entries(_ENTRY_COUNT + 1),
                                 high_bit_link=high_bit_link,
                                 pointer_format=pointer_format)
    table = extract_flag_table(_write_macho(tmp_path / 'Chrome Framework', payload))
    assert len(table) == _ENTRY_COUNT
    assert table['test-flag-000']['os'] == 'kOsAll'
    assert f'test-flag-{_ENTRY_COUNT:03d}' not in table


def test_extract_flag_table_rejects_an_unknown_chained_pointer_format(tmp_path: Path) -> None:
    payload = _build_macho_slice(_entries(), pointer_format=3)
    with pytest.raises(FlagBinaryUnreadable, match='No flag table found'):
        extract_flag_table(_write_macho(tmp_path / 'Chrome Framework', payload))


@pytest.mark.parametrize('magic', [b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf'])
def test_extract_flag_table_reads_a_fat_macho_image(tmp_path: Path, magic: bytes) -> None:
    slices = (bytes(0x1000), _build_macho_slice(_entries()))
    table = extract_flag_table(_build_fat(tmp_path / 'Chrome Framework', slices, magic))
    assert len(table) == _ENTRY_COUNT


def test_extract_flag_table_rejects_a_macho_without_a_text_segment(tmp_path: Path) -> None:
    payload = _build_macho_slice(_entries(), text_segment=False)
    with pytest.raises(FlagBinaryUnreadable, match='No flag table found'):
        extract_flag_table(_write_macho(tmp_path / 'Chrome Framework', payload))


def test_extract_flag_table_rejects_an_impossible_macho_command_size(tmp_path: Path) -> None:
    payload = _build_macho_slice(_entries(), command_size=4)
    with pytest.raises(FlagBinaryUnreadable, match='No flag table found'):
        extract_flag_table(_write_macho(tmp_path / 'Chrome Framework', payload))


def test_find_browser_binary_finds_the_linux_package(tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, 'platform', 'linux')
    _redirect(monkeypatch, _LINUX_BETA_BINARY, _write_image(tmp_path / 'chrome'))
    assert find_browser_binary('beta') == _LINUX_BETA_BINARY


def test_find_browser_binary_skips_a_file_without_an_image_magic(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, 'platform', 'linux')
    _redirect(monkeypatch, _LINUX_BETA_BINARY, _write_decoy_file(tmp_path / 'chrome'))
    assert find_browser_binary('beta') is None


def test_find_browser_binary_reports_an_unreadable_candidate_as_no_match(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, 'platform', 'linux')
    _redirect(monkeypatch, _LINUX_BETA_BINARY, None)
    assert find_browser_binary('beta') is None


@pytest.mark.parametrize('platform', ['cygwin', 'win32'])
def test_find_browser_binary_prefers_the_newest_windows_version(tmp_path: Path,
                                                                monkeypatch: pytest.MonkeyPatch,
                                                                platform: str) -> None:
    _confine(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, 'platform', platform)
    monkeypatch.delenv('PROGRAMFILES', raising=False)
    monkeypatch.setenv('PROGRAMFILES(X86)', str(tmp_path / 'x86'))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'local'))
    application = tmp_path / 'local' / 'Google/Chrome' / 'Application'
    _write_image(application / '120.0.6099.109' / 'chrome.dll')
    (application / 'temp').mkdir(parents=True)
    newest = _write_image(application / '121.0.6167.85' / 'chrome.dll')
    assert find_browser_binary() == newest


def test_find_browser_binary_returns_none_on_windows_without_an_install(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _confine(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.delenv('PROGRAMFILES', raising=False)
    monkeypatch.delenv('PROGRAMFILES(X86)', raising=False)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'local'))
    assert find_browser_binary('beta') is None


def test_find_browser_binary_prefers_the_newest_macos_version(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _confine(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    versions = (tmp_path / 'Applications' / 'Google Chrome.app' / 'Contents' / 'Frameworks' /
                'Google Chrome Framework.framework' / 'Versions')
    _write_image(versions / '120.0.6099.109' / 'Google Chrome Framework')
    newest = _write_image(versions / '121.0.6167.85' / 'Google Chrome Framework')
    assert find_browser_binary() == newest


def test_find_browser_binary_uses_the_current_macos_symlink(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _confine(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    versions = (tmp_path / 'Applications' / 'Chromium.app' / 'Contents' / 'Frameworks' /
                'Chromium Framework.framework' / 'Versions')
    binary = _write_image(versions / 'Current' / 'Chromium Framework')
    assert find_browser_binary('chromium') == binary


def test_find_browser_binary_returns_none_on_macos_without_an_install(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _confine(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    assert find_browser_binary('canary') is None
