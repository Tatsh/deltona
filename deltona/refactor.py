"""Source-code refactoring utilities."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
import ast
import asyncio
import io
import logging
import tokenize

import anyio
import pathspec

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterable, Iterator

__all__ = ('find_removable_trailing_commas', 'remove_trailing_commas',
           'remove_trailing_commas_in_paths')

log = logging.getLogger(__name__)

_SKIP = {
    tokenize.COMMENT, tokenize.DEDENT, tokenize.ENCODING, tokenize.INDENT, tokenize.NEWLINE,
    tokenize.NL
}
_STATEMENT_BREAKS = {tokenize.DEDENT, tokenize.ENCODING, tokenize.INDENT, tokenize.NEWLINE}
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
        if tokens[j].type in _STATEMENT_BREAKS:
            return None
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


async def _git_repo_root(start: anyio.Path) -> anyio.Path | None:
    cur = await start.resolve()
    for c in (cur, *cur.parents):
        if await (c / '.git').exists():
            return c
    return None


async def _gitignore_patterns(start: anyio.Path, repo_root: anyio.Path) -> list[str]:
    chain = [repo_root]
    relative = (await start.resolve()).relative_to(repo_root)
    for part in relative.parts:
        chain.append(chain[-1] / part)
    patterns: list[str] = ['.git']
    log.debug('Seeded patterns: %s.', patterns)
    for level in chain:
        gi = level / '.gitignore'
        if await gi.is_file():
            try:
                lines = (await gi.read_text(encoding='utf-8')).splitlines()
            except OSError as e:
                log.debug('Could not read `%s`: %s.', gi, e)
                continue
            log.debug('Adding %d pattern(s) from `%s`.', len(lines), gi)
            patterns.extend(lines)
    return patterns


async def _combined_spec(start: anyio.Path, repo_root: anyio.Path | None,
                         extra_excludes: Iterable[str]) -> pathspec.PathSpec | None:
    patterns: list[str] = []
    if repo_root is not None:
        patterns.extend(await _gitignore_patterns(start, repo_root))
    extra_list = list(extra_excludes)
    if extra_list:
        log.debug('Adding %d extra exclude pattern(s): %s.', len(extra_list), extra_list)
    patterns.extend(extra_list)
    if not patterns:
        log.debug('No exclude patterns; skipping spec construction.')
        return None
    log.debug('Combined exclude pattern total: %d.', len(patterns))
    return pathspec.PathSpec.from_lines('gitignore', patterns)


async def _walk_directory(
    start: anyio.Path,
    *,
    use_gitignore: bool = False,
    allow_dot: bool = True,
    extra_excludes: Iterable[str] = ()) -> AsyncIterator[anyio.Path]:
    log.debug('Walking `%s`.', start)
    repo_root = await _git_repo_root(start) if use_gitignore else None
    spec = await _combined_spec(start, repo_root, extra_excludes)
    base = repo_root if repo_root is not None else await start.resolve()

    async def is_excluded(path: anyio.Path, *, is_dir: bool) -> bool:
        try:
            rel = (await path.resolve()).relative_to(base)
        except ValueError:
            return False
        if not allow_dot and any(part.startswith('.') for part in rel.parts):
            return True
        if spec is None:
            return False
        rel_str = f'{rel}/' if is_dir else str(rel)
        return spec.match_file(rel_str)

    async def descend(d: anyio.Path) -> AsyncIterator[anyio.Path]:
        log.debug('Descending into `%s`.', d)
        try:
            entries = sorted([e async for e in d.iterdir()])
        except OSError as e:
            log.debug('Cannot iterate `%s`: %s.', d, e)
            return
        for entry in entries:
            if await entry.is_dir():
                if await is_excluded(entry, is_dir=True):
                    log.debug('Pruning directory `%s`.', entry)
                    continue
                async for x in descend(entry):
                    yield x
            elif await entry.is_file():
                if await is_excluded(entry, is_dir=False):
                    log.debug('Skipping file `%s`.', entry)
                    continue
                yield entry

    async for entry in descend(start):
        yield entry


async def _expand_paths(
    paths: Iterable[anyio.Path],
    *,
    use_gitignore: bool = False,
    allow_dot: bool = True,
    extra_excludes: Iterable[str] = ()) -> AsyncIterator[anyio.Path]:
    for p in paths:
        if await p.is_dir():
            async for f in _walk_directory(p,
                                           use_gitignore=use_gitignore,
                                           allow_dot=allow_dot,
                                           extra_excludes=extra_excludes):
                yield f
        else:
            yield p


async def _rewrite_one(path: anyio.Path) -> tuple[Path, str] | None:
    log.debug('Processing `%s`.', path)
    try:
        src = await path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as e:
        log.debug('Skipped `%s`: %s.', path, e)
        return None
    try:
        ast.parse(src)
    except (SyntaxError, ValueError) as e:
        log.debug('Skipped `%s`: not valid Python (%s).', path, e)
        return None
    try:
        new = ''.join(remove_trailing_commas(src))
    except (SyntaxError, tokenize.TokenError) as e:
        log.debug('Skipped `%s`: %s.', path, e)
        return None
    if new == src:
        return None
    await path.write_text(new, encoding='utf-8')
    return Path(path), src


async def remove_trailing_commas_in_paths(
    paths: Iterable[Path],
    *,
    use_gitignore: bool = False,
    allow_dot: bool = True,
    extra_excludes: Iterable[str] = ()) -> dict[Path, str]:
    """
    Remove non-required trailing commas from Python files at the given paths.

    Each path is either a file or a directory. Directories are walked recursively. Files that fail
    to parse as Python (for example, binary files or non-Python text) are silently skipped.
    Per-file work uses :py:class:`anyio.Path` for non-blocking I/O, so callers should drive this
    coroutine from an event loop (for example via :py:func:`asyncio.run`).

    Parameters
    ----------
    paths : Iterable[Path]
        Files or directories to process.
    use_gitignore : bool
        When ``True``, walk directories with ``.gitignore`` filtering against the enclosing git
        repository's rules.
    allow_dot : bool
        When ``True``, include files and directories whose names start with ``.``.
    extra_excludes : Iterable[str]
        Additional gitignore-style patterns to skip when walking directories. Patterns are matched
        relative to the enclosing git repository's root, or to the start directory when there is no
        enclosing repository.

    Returns
    -------
    dict[Path, str]
        A mapping of each modified file's path to its original (pre-modification) content.
    """
    extras = tuple(extra_excludes)
    candidates = [
        f async for f in _expand_paths((anyio.Path(p) for p in paths),
                                       use_gitignore=use_gitignore,
                                       allow_dot=allow_dot,
                                       extra_excludes=extras)
    ]
    results = await asyncio.gather(*(_rewrite_one(f) for f in candidates))
    return {path: original for entry in results if entry is not None for path, original in (entry,)}
