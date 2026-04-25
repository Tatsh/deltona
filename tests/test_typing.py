# ruff: noqa: FBT001
from __future__ import annotations

from typing import Union
import os

from deltona.typing import assert_not_none, contains_type_path_like_str
import pytest


@pytest.mark.parametrize(
    ('type_hint', 'expected'),
    [
        (Union[os.PathLike[str], str], True),  # noqa: UP007
        (Union[str, int], False),  # noqa: UP007
        (str, False),
        (Union[os.PathLike[str], int, str], True)  # noqa: UP007
    ])
def test_contains_type_path_like_str(type_hint: object, expected: bool) -> None:
    assert contains_type_path_like_str(type_hint) is expected


def test_assert_not_none_returns_value() -> None:
    assert assert_not_none(42) == 42
    assert assert_not_none('hello') == 'hello'


def test_assert_not_none_raises_on_none() -> None:
    with pytest.raises(AssertionError):
        assert_not_none(None)
