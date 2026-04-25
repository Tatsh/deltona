"""Source-code refactoring utilities."""
from __future__ import annotations

from typing import TYPE_CHECKING
import io
import tokenize

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ('find_removable_trailing_commas', 'remove_trailing_commas')

_SKIP = {
    tokenize.COMMENT, tokenize.DEDENT, tokenize.ENCODING, tokenize.INDENT, tokenize.NEWLINE,
    tokenize.NL
}
_KEYWORDS_BEFORE_PAREN_NOT_CALL = {
    'and', 'as', 'assert', 'async', 'await', 'del', 'elif', 'else', 'except', 'finally', 'for',
    'from', 'global', 'if', 'import', 'in', 'is', 'lambda', 'nonlocal', 'not', 'or', 'raise',
    'return', 'try', 'while', 'with', 'yield'
}
_CLOSE_TO_OPEN = {')': '(', ']': '[', '}': '{'}
_DIRECTIVE_OFF = 'rtc-off'
_DIRECTIVE_ON = 'rtc-on'


def _disabled_lines(tokens: list[tokenize.TokenInfo]) -> set[int]:
    off: int | None = None
    disabled: set[int] = set()
    for tok in tokens:
        if tok.type != tokenize.COMMENT:
            continue
        text = tok.string.lstrip('#').strip()
        if text == _DIRECTIVE_OFF and off is None:
            off = tok.start[0]
        elif text == _DIRECTIVE_ON and off is not None:
            disabled.update(range(off, tok.start[0] + 1))
            off = None
    if off is not None:
        last_line = tokens[-1].start[0] if tokens else off
        disabled.update(range(off, last_line + 1))
    return disabled


def _prev_sig(tokens: list[tokenize.TokenInfo], i: int) -> tokenize.TokenInfo | None:
    for j in range(i - 1, -1, -1):
        if tokens[j].type not in _SKIP:
            return tokens[j]
    return None


def _next_sig_index(tokens: list[tokenize.TokenInfo], i: int) -> int | None:
    for j in range(i + 1, len(tokens)):
        if tokens[j].type not in _SKIP:
            return j
    return None  # pragma: no cover


def _classify_open(tokens: list[tokenize.TokenInfo], i: int) -> str:
    prev = _prev_sig(tokens, i)
    if prev is None:
        return 'literal'
    if prev.type == tokenize.NAME:
        return 'literal' if prev.string in _KEYWORDS_BEFORE_PAREN_NOT_CALL else 'call'
    if prev.string in {')', ']', '.'}:
        return 'call'
    return 'literal'


def _matching_open(tokens: list[tokenize.TokenInfo], close_i: int) -> int | None:
    close_str = tokens[close_i].string
    want_open = _CLOSE_TO_OPEN[close_str]
    depth = 1
    for j in range(close_i - 1, -1, -1):
        if tokens[j].type != tokenize.OP:
            continue
        if tokens[j].string == close_str:
            depth += 1
        elif tokens[j].string == want_open:
            depth -= 1
            if depth == 0:
                return j
    return None  # pragma: no cover


def _depth_zero_commas(tokens: list[tokenize.TokenInfo], open_i: int, close_i: int) -> int:
    inner_depth = 0
    commas = 0
    for j in range(open_i + 1, close_i):
        if tokens[j].type != tokenize.OP:
            continue
        if tokens[j].string in '([{':
            inner_depth += 1
        elif tokens[j].string in ')]}':
            inner_depth -= 1
        elif tokens[j].string == ',' and inner_depth == 0:
            commas += 1
    return commas


def _is_required_single_element(tokens: list[tokenize.TokenInfo], open_i: int, close_i: int,
                                close_str: str, kind: str) -> bool:
    is_tuple = close_str == ')' and kind == 'literal'
    is_subscript_tuple = close_str == ']' and kind == 'call'
    if not (is_tuple or is_subscript_tuple):
        return False
    return _depth_zero_commas(tokens, open_i, close_i) == 1


def _open_kinds(tokens: list[tokenize.TokenInfo]) -> dict[int, str]:
    return {
        i: _classify_open(tokens, i)
        for i, tok in enumerate(tokens)
        if tok.type == tokenize.OP and tok.string in {'(', '[', '{'}
    }


def _comma_is_removable(tokens: list[tokenize.TokenInfo], i: int, open_kind: dict[int,
                                                                                  str]) -> bool:
    nxt_i = _next_sig_index(tokens, i)
    if nxt_i is None or tokens[nxt_i].string not in _CLOSE_TO_OPEN:
        return False
    open_i = _matching_open(tokens, nxt_i)
    if open_i is None:  # pragma: no cover
        return False
    kind = open_kind.get(open_i, 'literal')
    return not _is_required_single_element(tokens, open_i, nxt_i, tokens[nxt_i].string, kind)


def find_removable_trailing_commas(source: str) -> Iterator[tuple[int, int]]:
    """
    Yield positions of trailing commas that can be removed without changing semantics.

    Trailing commas required for single-element tuple literals (``(x,)``) or single-element
    subscript-tuple expressions (``a[x,]``, equivalent to ``a[(x,)]``) are not yielded.

    Lines between ``# rtc-off`` and ``# rtc-on`` comments are skipped.

    Parameters
    ----------
    source : str
        Python source code.

    Yields
    ------
    tuple[int, int]
        ``(line, column)`` of each removable comma. Lines are 1-indexed and columns are 0-indexed,
        matching :py:mod:`tokenize`.
    """
    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    open_kind = _open_kinds(tokens)
    disabled = _disabled_lines(tokens)
    for i, tok in enumerate(tokens):
        if (tok.type == tokenize.OP and tok.string == ',' and tok.start[0] not in disabled
                and _comma_is_removable(tokens, i, open_kind)):
            yield (tok.start[0], tok.start[1])


def remove_trailing_commas(source: str) -> Iterator[str]:
    """
    Yield lines of ``source`` with non-required trailing commas removed.

    See :py:func:`find_removable_trailing_commas` for the rules used to decide which commas are
    safe to remove.

    Parameters
    ----------
    source : str
        Python source code.

    Yields
    ------
    str
        Each line of the modified source, with line endings preserved. Joining the result with
        ``''.join(...)`` reconstitutes the full source.
    """
    positions = sorted(find_removable_trailing_commas(source), reverse=True)
    lines = source.splitlines(keepends=True)
    for line, col in positions:
        idx = line - 1
        text = lines[idx]
        if col < len(text) and text[col] == ',':
            lines[idx] = text[:col] + text[col + 1:]
    yield from lines
