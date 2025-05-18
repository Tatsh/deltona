"""Typing helpers."""
from __future__ import annotations

from enum import IntEnum
from os import PathLike
from typing import Annotated, Any, Literal, NotRequired, TypeVar, TypedDict
import os
import typing

if typing.TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ('CDStatus', 'DecodeErrorsOption', 'FileDescriptorOrPath', 'INCITS38Code', 'ProbeDict',
           'StrOrBytesPath', 'StrPath', 'StreamDispositionDict', 'StreamsDict', 'UNIXStrPath',
           'assert_not_none', 'contains_type_path_like_str')

DecodeErrorsOption = Literal['ignore', 'replace', 'strict']
INCITS38Code = Literal['AK', 'AL', 'AR', 'AS', 'AZ', 'CA', 'CO', 'CT', 'DC', 'DE', 'FL', 'FM', 'GA',
                       'GU', 'HI', 'IA', 'ID', 'IL', 'IN', 'KS', 'KY', 'LA', 'MA', 'MD', 'ME', 'MH',
                       'MI', 'MN', 'MO', 'MP', 'MS', 'MT', 'NC', 'ND', 'NE', 'NH', 'NJ', 'NM', 'NV',
                       'NY', 'OH', 'OK', 'OR', 'PA', 'PR', 'PW', 'RI', 'SC', 'SD', 'TN', 'TX', 'UM',
                       'UT', 'VA', 'VI', 'VT', 'WA', 'WI', 'WV', 'WY']
StrOrBytesPath = str | bytes | PathLike[str] | PathLike[bytes]
StrPath = str | PathLike[str]
"""String or ``PathLike[str]``."""
FileDescriptorOrPath = int | StrOrBytesPath
UNIXStrPath = Annotated[StrPath, 'unix']
StrPathMustExist = Annotated[StrPath, 'must_exist']
_T = TypeVar('_T')


class CDStatus(IntEnum):
    """CD status codes."""
    DISC_OK = 4
    DRIVE_NOT_READY = 3
    NO_DISC = 1
    NO_INFO = 0
    TRAY_OPEN = 2


def contains_type_path_like_str(type_hints: Any) -> bool:
    """Check if a type hint contains ``os.PathLike[str]``."""
    return os.PathLike[str] in typing.get_args(type_hints)


def assert_not_none(var: _T | None) -> _T:
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
