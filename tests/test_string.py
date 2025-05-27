# ruff: noqa: RUF001
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from deltona import string
import pytest

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pytest_mock import MockerFixture


def test_strip_ansi_removes_ansi_sequences() -> None:
    ansi_str = '\x1b[31mRed Text\x1b[0m'
    assert string.strip_ansi(ansi_str) == 'Red Text'


def test_strip_ansi_returns_original_if_no_ansi() -> None:
    plain_str = 'No ANSI here'
    assert string.strip_ansi(plain_str) == plain_str


def test_strip_ansi_empty_string() -> None:
    assert string.strip_ansi('') == ''  # noqa: PLC1901


def test_underscorize_replaces_spaces_with_underscore() -> None:
    s = 'hello world test'
    result = string.underscorize(s)
    assert result == 'hello_world_test'


def test_underscorize_replaces_tabs_and_newlines() -> None:
    s = 'hello\tworld\nfoo'
    result = string.underscorize(s)
    assert result == 'hello_world_foo'


def test_underscorize_multiple_whitespace() -> None:
    s = 'a   b\t\tc\n\nd'
    result = string.underscorize(s)
    assert result == 'a_b_c_d'


def test_underscorize_empty_string() -> None:
    s = ''
    result = string.underscorize(s)
    assert result == ''  # noqa: PLC1901


def test_underscorize_no_whitespace() -> None:
    s = 'nowhitespace'
    result = string.underscorize(s)
    assert result == 'nowhitespace'


def test_is_ascii_all_ascii() -> None:
    s = 'hello world'
    assert string.is_ascii(s) is True


def test_is_ascii_with_non_ascii() -> None:
    # cspell: disable-next-line  # noqa: ERA001
    s = 'hello wørld'
    assert string.is_ascii(s) is False


def test_is_ascii_empty_string() -> None:
    s = ''
    assert string.is_ascii(s) is True


def test_is_ascii_all_non_ascii() -> None:
    s = 'øæå'
    assert string.is_ascii(s) is False


def test_is_ascii_with_numbers_and_symbols() -> None:
    s = '1234!@#$'
    assert string.is_ascii(s) is True


def test_is_ascii_with_surrogate_pair() -> None:
    # Simulate a string with a high codepoint (emoji)
    s = 'hello \U0001F600'
    assert string.is_ascii(s) is False


def test_hexstr2bytes_valid_hex() -> None:
    s = '01020a'
    result = string.hexstr2bytes(s)
    assert result == bytes([1, 2, 10])


def test_hexstr2bytes_empty_string() -> None:
    s = ''
    result = string.hexstr2bytes(s)
    assert result == b''


def test_hexstr2bytes_invalid_hex_raises() -> None:
    s = '01z'
    with pytest.raises(ValueError, match='z'):
        string.hexstr2bytes(s)


def test_hexstr2bytes_generator_yields_correct_values() -> None:
    s = '0a1b2c'
    gen = string.hexstr2bytes_generator(s)
    assert list(gen) == [10, 27, 44]


def test_unix_path_to_wine_existing_path(tmp_path: Path) -> None:
    # Create a file and get its path
    file_path = tmp_path / 'file.txt'
    file_path.write_text('test')
    result = string.unix_path_to_wine(str(file_path))
    # Should start with Z: and use backslashes
    assert result.startswith('Z:')
    assert '\\' in result
    assert 'file.txt' in result


def test_unix_path_to_wine_non_existent_path(tmp_path: Path) -> None:
    non_existent = tmp_path / 'does_not_exist.txt'
    result = string.unix_path_to_wine(str(non_existent))
    assert result.startswith('Z:')
    assert '\\' in result
    assert 'does_not_exist.txt' in result


def test_unix_path_to_wine_relative_path() -> None:
    # Use a relative path
    rel_path = 'some/relative/path.txt'
    cwd = Path.cwd()
    expected = f"Z:{str(cwd).replace('/', '\\')}\\some\\relative\\path.txt"
    result = string.unix_path_to_wine(rel_path)
    assert result == expected


def test_unix_path_to_wine_path_with_forward_slashes(tmp_path: Path) -> None:
    file_path = tmp_path / 'dir' / 'file.txt'
    file_path.parent.mkdir(exist_ok=True)
    file_path.write_text('test')
    unix_style = str(file_path).replace('\\', '/')
    result = string.unix_path_to_wine(unix_style)
    assert '\\' in result
    assert 'file.txt' in result


@pytest.mark.parametrize(
    ('input_str', 'expected'),
    [
        ('http://example.com', True),
        ('https://example.com', True),
        ('ftp://example.com', True),
        ('not_a_url', False),
        ('just some text', False),
        ('example.com', False),
        ('http:/example.com', False),  # only one slash
        ('file://localhost/etc/fstab', True),
        ('custom_proto123://foo', True),
        ('', False)
    ])
def test_is_url_various_cases(input_str: str, expected: bool) -> None:  # noqa: FBT001
    assert string.is_url(input_str) is expected


@pytest.mark.parametrize(
    ('input_str', 'expected'),
    [
        ('ＡＢＣ１２３', 'ABC123'),
        ('！＠＃＄％', '!@#$%'),
        # cspell: disable-next-line  # noqa: ERA001
        ('ａｂｃｄｅｆ', 'abcdef'),
        ('￥１０００', '¥1000'),
        ('Hello　World！', 'Hello World!'),
    ])
def test_fullwidth_to_narrow_various_cases(input_str: str, expected: str) -> None:
    assert string.fullwidth_to_narrow(input_str) == expected


@pytest.mark.parametrize(
    ('input_str', 'expected'), [('Hello World!', 'hello-world'),
                                ('Python_is_awesome', 'python-is-awesome'),
                                ('  spaces   and---underscores__ ', 'spaces-and-underscores-'),
                                ('Special@#%&* Chars', 'special-chars'),
                                ('MiXeD CaSe and 123', 'mixed-case-and-123')])
def test_slugify_various_cases(input_str: str, expected: str) -> None:
    assert string.slugify(input_str) == expected


@pytest.mark.parametrize(
    ('input_str', 'expected'),
    [
        ('XIV', True),  # valid Roman numeral
        # cspell: disable-next-line  # noqa: ERA001
        ('MMXXIV', True),  # valid Roman numeral (2024)
        ('IIII', False),  # invalid (should be IV)
        ('abc', False),  # not a Roman numeral
        ('', False),  # empty string
    ])
def test_is_roman_numeral_various_cases(input_str: str, expected: bool) -> None:  # noqa: FBT001
    assert string.is_roman_numeral(input_str) is expected


@pytest.mark.parametrize(('input_sentence', 'expected'), [
    ('Hello world.', 'World hello.'),
    ('This is a test!', 'Test a is this!'),
    ('I am here?', 'Here am I?'),
    ('Python is fun', 'Fun is python.'),
    ('Why not try?', 'Try not why?'),
])
def test_rev_sentence_various_cases(input_sentence: str, expected: str) -> None:
    assert string.rev_sentence(input_sentence) == expected


@pytest.mark.parametrize(
    ('input_sentences', 'expected'),
    [
        (['Hello world.'], ['World hello.']),
        (['This is a test!', 'Another sentence?'], ['Test a is this!', 'Sentence another?']),
        (['I am here?', 'Python is fun'], ['Here am I?', 'Fun is python.']),
        ([''], []),  # empty string yields nothing
        (['   '], []),  # whitespace-only yields nothing
        (['Why not try?', '', 'Hello world.'], ['Try not why?', 'World hello.']),
        (['A single word.'], ['Word single a.']),
        (['i am here.'], ['Here am I.']),  # test 'i' capitalization
        (['Multiple   spaces here!'], ['Here spaces multiple!']),
    ])
def test_rev_sentences_various_cases(input_sentences: list[str], expected: list[str]) -> None:
    result = list(string.rev_sentences(input_sentences))
    assert result == expected


def test_sanitize_calls_yt_dlp_sanitize_filename_restricted_true(mocker: MockerFixture) -> None:
    fake_sanitize = mocker.Mock(return_value='Safe-File-Name')
    mocker.patch('deltona.string._get_yt_dlp_sanitize_filename', return_value=fake_sanitize)
    result = string.sanitize('Some Unsafe/File-Name.txt', restricted=True)
    fake_sanitize.assert_called_once_with('Some Unsafe/File-Name.txt', restricted=True)
    # Should be lowercased and dashes normalized
    assert result == 'safe-file-name'


def test_sanitize_calls_yt_dlp_sanitize_filename_restricted_false(mocker: MockerFixture) -> None:
    fake_sanitize = mocker.Mock(return_value='Another_File-Name')
    mocker.patch('deltona.string._get_yt_dlp_sanitize_filename', return_value=fake_sanitize)
    result = string.sanitize('Another*File-Name', restricted=False)
    fake_sanitize.assert_called_once_with('Another*File-Name', restricted=False)
    assert result == 'another-file-name'


def test_sanitize_returns_minimum_dash_if_empty(mocker: MockerFixture) -> None:
    fake_sanitize = mocker.Mock(return_value='_')
    mocker.patch('deltona.string._get_yt_dlp_sanitize_filename', return_value=fake_sanitize)
    result = string.sanitize('', restricted=True)
    assert result == '-'


def test_sanitize_removes_dot_dash_and_normalizes(mocker: MockerFixture) -> None:
    fake_sanitize = mocker.Mock(return_value='file.-name--test')
    mocker.patch('deltona.string._get_yt_dlp_sanitize_filename', return_value=fake_sanitize)
    result = string.sanitize('file.-name--test', restricted=True)
    assert result == 'file-name-test'


def test_sanitize_replaces_pattern(mocker: MockerFixture) -> None:
    fake_sanitize = mocker.Mock(return_value='abc-s-def')
    mocker.patch('deltona.string._get_yt_dlp_sanitize_filename', return_value=fake_sanitize)
    result = string.sanitize('abc-s-def', restricted=True)
    # The ([a-z0-9])\-s\- pattern should be replaced with \1s-
    assert result == 'abcs-def'


def test_add_unidecode_custom_replacement_adds_to_cache(mocker: MockerFixture) -> None:
    fake_cache: dict[int, Sequence[str | None] | None] = {}
    fake_unidecode = mocker.Mock()
    mocker.patch('deltona.string._get_unidecode_cache_and_unidecode',
                 return_value=(fake_cache, fake_unidecode))
    mocker.patch('deltona.string.assert_not_none', side_effect=lambda x: x)
    # Add replacement for 'ø'
    find = 'ø'
    replace = 'oe'
    codepoint = ord(find)
    section = codepoint >> 8
    position = codepoint % 256
    # Simulate cache section as None
    fake_cache[section] = None
    string.add_unidecode_custom_replacement(find, replace)
    assert isinstance(fake_cache[section], list)
    assert fake_cache[section][position] == replace  # type: ignore[index]


def test_add_unidecode_custom_replacement_overwrites_existing(mocker: MockerFixture) -> None:
    fake_cache: dict[int, Sequence[str | None] | None] = {}
    fake_unidecode = mocker.Mock()
    mocker.patch('deltona.string._get_unidecode_cache_and_unidecode',
                 return_value=(fake_cache, fake_unidecode))
    mocker.patch('deltona.string.assert_not_none', side_effect=lambda x: x)
    find = 'ø'
    replace = 'oe'
    codepoint = ord(find)
    section = codepoint >> 8
    position = codepoint % 256
    # Simulate cache section as a list with a previous value
    fake_cache[section] = [None] * (position + 1)
    fake_cache[section][position] = 'old'  # type: ignore[index]
    string.add_unidecode_custom_replacement(find, replace)
    assert fake_cache[section][position] == replace  # type: ignore[index]


def test_add_unidecode_custom_replacement_handles_existing_tuple(mocker: MockerFixture) -> None:
    fake_cache: dict[int, Sequence[str | None] | None] = {}
    fake_unidecode = mocker.Mock()
    mocker.patch('deltona.string._get_unidecode_cache_and_unidecode',
                 return_value=(fake_cache, fake_unidecode))
    mocker.patch('deltona.string.assert_not_none', side_effect=lambda x: x)
    find = 'ø'
    replace = 'oe'
    codepoint = ord(find)
    section = codepoint >> 8
    position = codepoint % 256
    # Simulate cache section as a tuple (immutable)
    fake_cache[section] = tuple([None] * (position + 1))
    string.add_unidecode_custom_replacement(find, replace)
    assert isinstance(fake_cache[section], list)
    assert fake_cache[section][position] == replace  # type: ignore[index]


def test_add_unidecode_custom_replacement_calls_unidecode(mocker: MockerFixture) -> None:
    fake_cache: dict[int, Sequence[str | None] | None] = {}
    fake_unidecode = mocker.Mock()
    mocker.patch('deltona.string._get_unidecode_cache_and_unidecode',
                 return_value=(fake_cache, fake_unidecode))
    mocker.patch('deltona.string.assert_not_none', side_effect=lambda x: x)
    find = 'ø'
    replace = 'oe'
    fake_cache[ord(find) >> 8] = None
    string.add_unidecode_custom_replacement(find, replace)
    fake_unidecode.assert_called_once_with(find)
