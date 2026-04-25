from __future__ import annotations

from typing import TYPE_CHECKING
import tokenize

from deltona.refactor import find_removable_trailing_commas, remove_trailing_commas
import pytest

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def test_find_removable_trailing_commas_function_call() -> None:
    src = 'foo(a, b,)\n'
    assert list(find_removable_trailing_commas(src)) == [(1, 8)]


def test_find_removable_trailing_commas_list_literal() -> None:
    src = 'x = [1, 2, 3,]\n'
    assert list(find_removable_trailing_commas(src)) == [(1, 12)]


def test_find_removable_trailing_commas_dict_literal() -> None:
    src = "d = {'a': 1, 'b': 2,}\n"
    assert list(find_removable_trailing_commas(src)) == [(1, 19)]


def test_find_removable_trailing_commas_set_literal() -> None:
    src = 's = {1, 2, 3,}\n'
    assert list(find_removable_trailing_commas(src)) == [(1, 12)]


def test_find_removable_trailing_commas_multi_element_tuple() -> None:
    src = 't = (1, 2, 3,)\n'
    assert list(find_removable_trailing_commas(src)) == [(1, 12)]


def test_find_removable_trailing_commas_preserves_single_element_tuple() -> None:
    src = 't = (1,)\n'
    assert list(find_removable_trailing_commas(src)) == []


def test_find_removable_trailing_commas_preserves_single_element_subscript_tuple() -> None:
    src = 'x = a[1,]\n'
    assert list(find_removable_trailing_commas(src)) == []


def test_find_removable_trailing_commas_multi_element_subscript() -> None:
    src = 'x = a[1, 2,]\n'
    assert list(find_removable_trailing_commas(src)) == [(1, 10)]


def test_find_removable_trailing_commas_function_def() -> None:
    src = 'def f(a, b,):\n    pass\n'
    assert list(find_removable_trailing_commas(src)) == [(1, 10)]


def test_find_removable_trailing_commas_class_bases() -> None:
    src = 'class C(Base,):\n    pass\n'
    assert list(find_removable_trailing_commas(src)) == [(1, 12)]


def test_find_removable_trailing_commas_method_chain_call() -> None:
    src = 'obj.method(a, b,)\n'
    assert list(find_removable_trailing_commas(src)) == [(1, 15)]


def test_find_removable_trailing_commas_after_subscript() -> None:
    src = 'arr[0](a, b,)\n'
    assert list(find_removable_trailing_commas(src)) == [(1, 11)]


def test_find_removable_trailing_commas_after_call() -> None:
    src = 'f()(a, b,)\n'
    assert list(find_removable_trailing_commas(src)) == [(1, 8)]


def test_find_removable_trailing_commas_keyword_before_paren() -> None:
    src = 'x = (yield a,)\n'
    assert list(find_removable_trailing_commas(src)) == []


def test_find_removable_trailing_commas_grouping_with_keyword() -> None:
    src = 'x = (a if b else c,)\n'
    assert list(find_removable_trailing_commas(src)) == []


def test_find_removable_trailing_commas_nested() -> None:
    src = 'x = ([1, 2,], [3, 4,],)\n'
    assert sorted(find_removable_trailing_commas(src)) == [(1, 10), (1, 19), (1, 21)]


def test_find_removable_trailing_commas_disabled_block() -> None:
    src = '# rtc-off\nx = (1, 2, 3,)\n# rtc-on\n'
    assert list(find_removable_trailing_commas(src)) == []


def test_find_removable_trailing_commas_disabled_unclosed() -> None:
    src = '# rtc-off\nx = (1, 2, 3,)\n'
    assert list(find_removable_trailing_commas(src)) == []


def test_find_removable_trailing_commas_disabled_then_enabled() -> None:
    src = '# rtc-off\nx = (1, 2, 3,)\n# rtc-on\ny = (4, 5, 6,)\n'
    positions = list(find_removable_trailing_commas(src))
    assert positions == [(4, 12)]


def test_find_removable_trailing_commas_directive_unbalanced_on() -> None:
    src = '# rtc-on\nx = (1, 2, 3,)\n'
    assert list(find_removable_trailing_commas(src)) == [(2, 12)]


def test_find_removable_trailing_commas_no_change() -> None:
    src = 'x = (1, 2, 3)\n'
    assert list(find_removable_trailing_commas(src)) == []


def test_find_removable_trailing_commas_empty_source() -> None:
    assert list(find_removable_trailing_commas('')) == []


def test_remove_trailing_commas_basic() -> None:
    src = 'x = (1, 2, 3,)\n'
    assert ''.join(remove_trailing_commas(src)) == 'x = (1, 2, 3)\n'


def test_remove_trailing_commas_no_change() -> None:
    src = 'x = (1,)\n'
    assert ''.join(remove_trailing_commas(src)) == src


def test_remove_trailing_commas_multi_line() -> None:
    src = 'def f(\n    a,\n    b,\n):\n    pass\n'
    out = ''.join(remove_trailing_commas(src))
    assert out == 'def f(\n    a,\n    b\n):\n    pass\n'


def test_remove_trailing_commas_invalid_source_raises() -> None:
    with pytest.raises((SyntaxError, tokenize.TokenError)):
        ''.join(remove_trailing_commas('x = ('))


def test_find_removable_trailing_commas_nested_call() -> None:
    src = 'f(g(),)\n'
    assert list(find_removable_trailing_commas(src)) == [(1, 5)]


def test_find_removable_trailing_commas_only_directive() -> None:
    src = '# rtc-off\n# rtc-on\n'
    assert list(find_removable_trailing_commas(src)) == []


def test_find_removable_trailing_commas_directive_no_off() -> None:
    src = 'x = (1, 2,)\n# rtc-on\n'
    assert list(find_removable_trailing_commas(src)) == [(1, 9)]


def test_find_removable_trailing_commas_string_with_comma() -> None:
    src = "x = ('a,', 'b,',)\n"
    assert list(find_removable_trailing_commas(src)) == [(1, 15)]


def test_find_removable_trailing_commas_after_dot() -> None:
    src = 'x = obj.method(a, b,)\n'
    assert list(find_removable_trailing_commas(src)) == [(1, 19)]


def test_find_removable_trailing_commas_preserves_subscript_single_inner() -> None:
    src = 'x = a[(1,)]\n'
    assert list(find_removable_trailing_commas(src)) == []


def test_remove_trailing_commas_yields_lines() -> None:
    src = 'x = (1, 2,)\ny = [3, 4,]\n'
    lines = list(remove_trailing_commas(src))
    assert lines == ['x = (1, 2)\n', 'y = [3, 4]\n']


def test_find_removable_trailing_commas_paren_at_start_of_file() -> None:
    src = '(1, 2,)\n'
    assert list(find_removable_trailing_commas(src)) == [(1, 5)]


def test_find_removable_trailing_commas_call_with_list_arg() -> None:
    src = 'f([(1,)], a,)\n'
    assert list(find_removable_trailing_commas(src)) == [(1, 11)]


def test_find_removable_trailing_commas_paren_after_comment_only_file() -> None:
    src = '# comment\n(1, 2,)\n'
    assert list(find_removable_trailing_commas(src)) == [(2, 5)]


def test_remove_trailing_commas_skips_position_past_line_end(mocker: MockerFixture) -> None:
    mocker.patch('deltona.refactor.find_removable_trailing_commas', return_value=[(1, 99)])
    src = 'short\n'
    assert ''.join(remove_trailing_commas(src)) == src


def test_remove_trailing_commas_skips_position_not_pointing_at_comma(mocker: MockerFixture) -> None:
    mocker.patch('deltona.refactor.find_removable_trailing_commas', return_value=[(1, 0)])
    src = 'x = 1\n'
    assert ''.join(remove_trailing_commas(src)) == src
