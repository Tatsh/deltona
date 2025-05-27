"""Typing helpers."""
from __future__ import annotations

from enum import IntEnum
from os import PathLike
from typing import TYPE_CHECKING, Annotated, Any, Literal, NotRequired, TypeVar, TypedDict
import os
import typing

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ('CDStatus', 'DecodeErrorsOption', 'FileDescriptorOrPath', 'INCITS38Code', 'ProbeDict',
           'StrOrBytesPath', 'StrPath', 'StreamDispositionDict', 'StreamsDict', 'UNIXStrPath',
           'assert_not_none', 'contains_type_path_like_str')

DecodeErrorsOption = Literal['ignore', 'replace', 'strict']
"""Decode errors option for :py:func:`deltona.utils.decode`."""
INCITS38Code = Literal['AK', 'AL', 'AR', 'AS', 'AZ', 'CA', 'CO', 'CT', 'DC', 'DE', 'FL', 'FM', 'GA',
                       'GU', 'HI', 'IA', 'ID', 'IL', 'IN', 'KS', 'KY', 'LA', 'MA', 'MD', 'ME', 'MH',
                       'MI', 'MN', 'MO', 'MP', 'MS', 'MT', 'NC', 'ND', 'NE', 'NH', 'NJ', 'NM', 'NV',
                       'NY', 'OH', 'OK', 'OR', 'PA', 'PR', 'PW', 'RI', 'SC', 'SD', 'TN', 'TX', 'UM',
                       'UT', 'VA', 'VI', 'VT', 'WA', 'WI', 'WV', 'WY']
"""Two-letter state code according to INCITS 38-2009."""
StrOrBytesPath = str | bytes | PathLike[str] | PathLike[bytes]
"""String, bytes, ``PathLike[str]`` or ``PathLike[bytes]``."""
StrPath = str | PathLike[str]
"""String or ``PathLike[str]``."""
FileDescriptorOrPath = int | StrOrBytesPath
"""File descriptor or path."""
UNIXStrPath = Annotated[StrPath, 'unix']
"""String or ``PathLike[str]`` that is a UNIX path."""
StrPathMustExist = Annotated[StrPath, 'must_exist']
"""String or ``PathLike[str]`` that must exist."""
_T = TypeVar('_T')


class CDStatus(IntEnum):
    """CD status codes."""
    DISC_OK = 4
    """Disc is OK."""
    DRIVE_NOT_READY = 3
    """Drive is not ready."""
    NO_DISC = 1
    """No disc in drive."""
    NO_INFO = 0
    """No information available."""
    TRAY_OPEN = 2
    """Tray is open."""


def contains_type_path_like_str(type_hints: Any) -> bool:  # pragma: no cover
    """Check if a type hint contains ``os.PathLike[str]``."""
    return os.PathLike[str] in typing.get_args(type_hints)


def assert_not_none(var: _T | None) -> _T:  # pragma: no cover
    """
    Assert the ``var`` is not None and return it.

    This will remove ``| None`` from type ``_T``.
    """
    assert var is not None
    return var


# Used by chrome-bisect-flags
class ChromeLocalStateBrowser(TypedDict):
    """Chrome ``local state[browser]`` dictionary."""
    enabled_labs_experiments: Sequence[str]
    """Enabled labs experiments, also known as flags"""


class ChromeLocalState(TypedDict):
    """Chrome local state dictionary."""
    browser: ChromeLocalStateBrowser
    """Browser."""


class StreamDispositionDict(TypedDict):
    """FFmpeg stream disposition dictionary."""
    default: Literal[0, 1]
    """Default stream."""


class TagsDict(TypedDict):
    """Tags dictionary."""
    info_json: NotRequired[str]
    """Info JSON."""
    TXXX: NotRequired[str]
    """TXXX tag."""


class StreamsDict(TypedDict):
    """FFmpeg stream dictionary."""
    codec_type: Literal['audio', 'video']
    """Codec type."""
    disposition: StreamDispositionDict
    """Stream disposition dictionary."""
    height: int
    """Height of the video stream."""
    tags: TagsDict
    """Tags dictionary."""
    width: int
    """Width of the video stream."""


class FormatDict(TypedDict):
    """FFmpeg format dictionary."""
    tags: TagsDict
    """Tags dictionary."""


class ProbeDict(TypedDict):
    """FFmpeg probe result returned by :py:func:`deltona.media.ffprobe`."""
    format: FormatDict
    """Format dictionary."""
    streams: Sequence[StreamsDict]
    """Dictionary of streams."""
