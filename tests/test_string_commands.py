from __future__ import annotations

from typing import TYPE_CHECKING
import plistlib

from deltona.commands.string import (
    fullwidth2ascii_main,
    is_ascii_main,
    is_bin_main,
    json2yaml_main,
    pl2json_main,
    sanitize_main,
    slugify_main,
    title_fixer_main,
    trim_main,
    ucwords_main,
    underscorize_main,
    urldecode_main,
)
import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from click.testing import CliRunner
    from pytest_mock import MockerFixture


@pytest.mark.parametrize(
    ('input_str', 'expected'),
    [
        ('hello', 0),
        # cspell: disable-next-line  # noqa: ERA001
        ('héllo', 1),
    ])
def test_is_ascii_main(runner: CliRunner, mocker: MockerFixture, tmp_path: Path, input_str: str,
                       expected: int) -> None:
    input_file = tmp_path / 'test_is_ascii.txt'
    input_file.write_text(input_str, encoding='utf-8')
    mocker.patch('deltona.string.is_ascii', return_value=expected == 0)
    result = runner.invoke(is_ascii_main, [str(input_file)])
    assert result.exit_code == expected


def test_urldecode_main_basic(runner: CliRunner, tmp_path: Path) -> None:
    input_file = tmp_path / 'test_urldecode.txt'
    input_file.write_text('hello%20world%21\n', encoding='utf-8')
    result = runner.invoke(urldecode_main, [str(input_file)])
    assert result.exit_code == 0
    assert 'hello world!' in result.output


def test_urldecode_main_netloc(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    input_file = tmp_path / 'test_urldecode_netloc.txt'
    # cspell: disable-next-line  # noqa: ERA001
    input_file.write_text('https%3A%2F%2Fexample.com%2Ffoo\n', encoding='utf-8')
    mocker.patch('sys.argv', ['netloc'])
    result = runner.invoke(urldecode_main, [str(input_file)])
    assert result.exit_code == 0
    assert 'example.com' in result.output


def test_underscorize_main(runner: CliRunner, tmp_path: Path) -> None:
    input_file = tmp_path / 'test_underscorize.txt'
    input_file.write_text('Hello World\n', encoding='utf-8')
    result = runner.invoke(underscorize_main, [str(input_file)])
    assert result.exit_code == 0
    assert 'Hello_World' in result.output


def test_json2yaml_main(runner: CliRunner, tmp_path: Path) -> None:
    input_file = tmp_path / 'test_json2yaml.json'
    input_file.write_text('{"a": 1, "b": 2}', encoding='utf-8')
    result = runner.invoke(json2yaml_main, [str(input_file)])
    assert result.exit_code == 0
    assert 'a: 1' in result.output


def test_json2yaml_main_flow_style(runner: CliRunner, tmp_path: Path) -> None:
    input_file = tmp_path / 'test_json2yaml_flow.json'
    input_file.write_text('{"a": 1, "b": 2}', encoding='utf-8')
    result = runner.invoke(json2yaml_main, ['-d', str(input_file)])
    assert result.exit_code == 0
    assert '{a: 1}' in result.output or 'a: 1' in result.output


def test_sanitize_main_default(runner: CliRunner, tmp_path: Path) -> None:
    input_file = tmp_path / 'test_sanitize.txt'
    input_file.write_text('hello<>:"/\\|?*\n', encoding='utf-8')
    result = runner.invoke(sanitize_main, [str(input_file)])
    assert result.exit_code == 0
    assert 'hello' in result.output


def test_sanitize_main_no_restricted(runner: CliRunner, tmp_path: Path) -> None:
    input_file = tmp_path / 'test_sanitize_no_restricted.txt'
    input_file.write_text('hello<>:"/\\|?*\n', encoding='utf-8')
    result = runner.invoke(sanitize_main, ['-R', str(input_file)])
    assert result.exit_code == 0
    assert 'hello' in result.output


def test_trim_main(runner: CliRunner, tmp_path: Path) -> None:
    input_file = tmp_path / 'test_trim.txt'
    input_file.write_text('  hello  \n  world  \n', encoding='utf-8')
    result = runner.invoke(trim_main, [str(input_file)])
    assert result.exit_code == 0
    assert result.output == 'hello\nworld\n'


def test_ucwords_main(runner: CliRunner, tmp_path: Path) -> None:
    input_file = tmp_path / 'test_ucwords.txt'
    input_file.write_text('hello world\n', encoding='utf-8')
    result = runner.invoke(ucwords_main, [str(input_file)])
    assert result.exit_code == 0
    assert result.output == 'Hello World\n'


def test_pl2json_main_valid(runner: CliRunner, tmp_path: Path) -> None:
    data = {'foo': 'bar'}
    pl_file = tmp_path / 'test.plist'
    with pl_file.open('wb') as f:
        plistlib.dump(data, f)
    result = runner.invoke(pl2json_main, [str(pl_file)])
    assert '"foo": "bar"' in result.output


def test_pl2json_main_invalid(runner: CliRunner, tmp_path: Path) -> None:
    pl_file = tmp_path / 'test.plist'
    pl_file.write_bytes(b'not a plist')
    result = runner.invoke(pl2json_main, [str(pl_file)])
    assert result.exit_code != 0


def test_pl2json_main_cannot_serialize(runner: CliRunner, tmp_path: Path,
                                       mocker: MockerFixture) -> None:
    mocker.patch('deltona.commands.string.plistlib.load')
    mocker.patch('deltona.commands.string.json.dumps', side_effect=TypeError)
    pl_file = tmp_path / 'test.plist'
    pl_file.touch()
    result = runner.invoke(pl2json_main, [str(pl_file)])
    assert result.exit_code != 0
    assert 'A non-JSON serialisable item is present in the file.' in result.output


def test_is_bin_main_binary(runner: CliRunner, tmp_path: Path, mocker: MockerFixture) -> None:
    mocker.patch('deltona.commands.string.is_binary_string', return_value=True)
    file = tmp_path / 'binfile'
    file.write_bytes(b'\x00\x01\x02')
    result = runner.invoke(is_bin_main, [str(file)])
    assert result.exit_code == 0


def test_is_bin_main_not_binary(runner: CliRunner, tmp_path: Path) -> None:
    file = tmp_path / 'ascii_file'
    file.write_text('abc\n')
    result = runner.invoke(is_bin_main, [str(file)])
    assert result.exit_code == 1


def test_is_bin_main_empty_not_binary(runner: CliRunner, tmp_path: Path) -> None:
    file = tmp_path / 'ascii_file'
    file.write_text('')
    result = runner.invoke(is_bin_main, [str(file)])
    assert result.exit_code == 1


def test_fullwidth2ascii_main(runner: CliRunner, tmp_path: Path) -> None:
    input_file = tmp_path / 'test_fullwidth2ascii.txt'
    # cspell: disable-next-line  # noqa: ERA001
    input_file.write_text('ｈｅｌｌｏ\n', encoding='utf-8')  # noqa: RUF001
    result = runner.invoke(fullwidth2ascii_main, [str(input_file)])
    assert 'hello' in result.output


def test_slugify_main(runner: CliRunner, tmp_path: Path) -> None:
    input_file = tmp_path / 'test_slugify.txt'
    input_file.write_text('Hello, World!\n', encoding='utf-8')
    result = runner.invoke(slugify_main, [str(input_file)])
    assert result.exit_code == 0
    assert 'hello-world' in result.output


def test_slugify_main_no_lower(runner: CliRunner, tmp_path: Path) -> None:
    input_file = tmp_path / 'test_slugify_no_lower.txt'
    input_file.write_text('Hello, World!\n', encoding='utf-8')
    result = runner.invoke(slugify_main, ['--no-lower', str(input_file)])
    assert result.exit_code == 0
    assert 'Hello-World' in result.output


def test_title_fixer_main_basic(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    input_file = tmp_path / 'test_title_fixer.txt'
    input_file.write_text('some title\n', encoding='utf-8')
    mocker.patch('deltona.naming.adjust_title', return_value='Fixed Title')
    result = runner.invoke(title_fixer_main, [str(input_file)])
    assert result.exit_code == 0
    assert 'Fixed Title' in result.output


def test_title_fixer_main_no_modes(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(title_fixer_main, ['--no-english'], input='some title\n')
    assert result.exit_code != 0
    assert 'No modes specified.' in result.output
