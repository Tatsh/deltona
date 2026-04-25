from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock
import tokenize

from deltona.commands.misc import (
    adp_main,
    burnrariso_main,
    gogextract_main,
    remove_trailing_commas_main,
    unpack_0day_main,
)
from deltona.io import SFVVerificationError, UnRARExtractionTestFailed
import pytest

if TYPE_CHECKING:
    from click.testing import CliRunner
    from pytest_mock import MockerFixture


@pytest.fixture
def fake_path(tmp_path: Path) -> Path:
    d = tmp_path / 'dir'
    d.mkdir()
    return d


def test_adp_main(runner: CliRunner, mocker: MockerFixture) -> None:
    mock_calc = mocker.patch('deltona.commands.misc.calculate_salary',
                             new=AsyncMock(return_value=12345))
    result = runner.invoke(adp_main, ['--hours', '100', '--pay-rate', '50', '--state', 'FL'])
    assert result.exit_code == 0
    assert '12345' in result.output
    mock_calc.assert_called_once_with(hours=100, pay_rate=50.0, state='FL')


def test_unpack_0day_main(runner: CliRunner, mocker: MockerFixture, fake_path: Path) -> None:
    mock_unpack = mocker.patch('deltona.commands.misc.unpack_0day')
    result = runner.invoke(unpack_0day_main, [str(fake_path)])
    assert result.exit_code == 0
    mock_unpack.assert_called_once_with(fake_path)


def test_gogextract_main(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    fake_file = tmp_path / 'archive.gog'
    fake_file.write_text('data')
    mock_extract = mocker.patch('deltona.commands.misc.extract_gog')
    result = runner.invoke(gogextract_main, [str(fake_file), '-o', str(tmp_path)])
    assert result.exit_code == 0
    mock_extract.assert_called_once_with(fake_file, tmp_path)


def test_burnrariso_main_success(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    rar_file = tmp_path / 'test.rar'
    rar_file.write_text('data')
    iso_file = MagicMock()
    iso_file.name = 'test.iso'
    iso_file.size = 123456
    mock_unrar = mocker.patch('deltona.commands.misc.UnRAR')
    unrar_instance = mock_unrar.return_value
    unrar_instance.list_files.return_value = [iso_file]
    unrar_instance.pipe.return_value.__enter__.return_value.stdout = MagicMock()
    unrar_instance.pipe.return_value.__exit__.return_value = False
    unrar_instance.pipe.return_value.__enter__.return_value.wait = MagicMock(return_value=0)
    unrar_instance.pipe.return_value.__enter__.return_value.returncode = 0
    mock_popen = mocker.patch('deltona.commands.misc.sp.Popen')
    popen_instance = mock_popen.return_value.__enter__.return_value
    popen_instance.wait.return_value = 0
    popen_instance.returncode = 0
    mocker.patch('deltona.commands.misc.verify_sfv')
    mocker.patch('deltona.commands.misc.Path.exists', return_value=True)
    result = runner.invoke(burnrariso_main, [str(rar_file), '--no-crc-check'])
    assert result.exit_code == 0
    unrar_instance.list_files.assert_called_once()
    mock_popen.assert_called()


def test_burnrariso_main_failure(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    rar_file = tmp_path / 'test.rar'
    rar_file.write_text('data')
    iso_file = MagicMock()
    iso_file.name = 'test.iso'
    iso_file.size = 123456
    mock_unrar = mocker.patch('deltona.commands.misc.UnRAR')
    unrar_instance = mock_unrar.return_value
    unrar_instance.list_files.return_value = [iso_file]
    unrar_instance.pipe.return_value.__enter__.return_value.stdout = MagicMock()
    unrar_instance.pipe.return_value.__exit__.return_value = False
    unrar_instance.pipe.return_value.__enter__.return_value.wait = MagicMock(return_value=0)
    unrar_instance.pipe.return_value.__enter__.return_value.returncode = 0
    mock_popen = mocker.patch('deltona.commands.misc.sp.Popen')
    popen_instance = mock_popen.return_value.__enter__.return_value
    popen_instance.wait.return_value = 0
    popen_instance.returncode = 1
    mocker.patch('deltona.commands.misc.verify_sfv')
    mocker.patch('deltona.commands.misc.Path.exists', return_value=True)
    result = runner.invoke(burnrariso_main, [str(rar_file), '--no-crc-check'])
    assert result.exit_code != 0
    unrar_instance.list_files.assert_called_once()
    mock_popen.assert_called()


def test_burnrariso_main_no_iso(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    rar_file = tmp_path / 'test.rar'
    rar_file.write_text('data')
    mock_unrar = mocker.patch('deltona.commands.misc.UnRAR')
    unrar_instance = mock_unrar.return_value
    unrar_instance.list_files.return_value = []
    result = runner.invoke(burnrariso_main, [str(rar_file), '--no-crc-check'])
    assert result.exit_code != 0


def test_burnrariso_main_iso_no_size(runner: CliRunner, mocker: MockerFixture,
                                     tmp_path: Path) -> None:
    rar_file = tmp_path / 'test.rar'
    rar_file.write_text('data')
    iso_file = MagicMock()
    iso_file.name = 'test.iso'
    iso_file.size = 0
    mock_unrar = mocker.patch('deltona.commands.misc.UnRAR')
    unrar_instance = mock_unrar.return_value
    unrar_instance.list_files.return_value = [iso_file]
    result = runner.invoke(burnrariso_main, [str(rar_file), '--no-crc-check'])
    assert result.exit_code != 0


def test_burnrariso_main_missing_sfv_file(runner: CliRunner, mocker: MockerFixture,
                                          tmp_path: Path) -> None:
    rar_file = tmp_path / 'test.rar'
    rar_file.write_text('data')
    iso_file = MagicMock()
    iso_file.name = 'test.iso'
    iso_file.size = 123
    mock_unrar = mocker.patch('deltona.commands.misc.UnRAR')
    unrar_instance = mock_unrar.return_value
    unrar_instance.list_files.return_value = [iso_file]
    result = runner.invoke(burnrariso_main, [str(rar_file)])
    assert result.exit_code != 0
    assert isinstance(result.exception, FileNotFoundError)


def test_burnrariso_main_sfv_fail(runner: CliRunner, mocker: MockerFixture, tmp_path: Path) -> None:
    rar_file = tmp_path / 'test.rar'
    rar_file.write_text('data')
    iso_file = MagicMock()
    iso_file.name = 'test.iso'
    iso_file.size = 123
    mock_unrar = mocker.patch('deltona.commands.misc.UnRAR')
    unrar_instance = mock_unrar.return_value
    unrar_instance.list_files.return_value = [iso_file]
    mocker.patch('deltona.commands.misc.Path.exists', return_value=True)
    mock_verify = mocker.patch('deltona.commands.misc.verify_sfv',
                               side_effect=SFVVerificationError('.', 1, 0))
    result = runner.invoke(burnrariso_main, [str(rar_file)])
    assert result.exit_code != 0
    mock_verify.assert_called()


def test_burnrariso_main_test_extraction_fail(runner: CliRunner, mocker: MockerFixture,
                                              tmp_path: Path) -> None:
    rar_file = tmp_path / 'test.rar'
    rar_file.write_text('data')
    iso_file = MagicMock()
    iso_file.name = 'test.iso'
    iso_file.size = 123
    mock_unrar = mocker.patch('deltona.commands.misc.UnRAR')
    unrar_instance = mock_unrar.return_value
    unrar_instance.list_files.return_value = [iso_file]
    unrar_instance.test_extraction.side_effect = UnRARExtractionTestFailed
    mocker.patch('deltona.commands.misc.Path.exists', return_value=True)
    mocker.patch('deltona.commands.misc.verify_sfv')
    mocker.patch('deltona.commands.misc.sp.Popen')
    result = runner.invoke(burnrariso_main, [str(rar_file), '--test-extraction'])
    assert result.exit_code != 0


def test_remove_trailing_commas_main_modifies(runner: CliRunner, tmp_path: Path) -> None:
    f = tmp_path / 'x.py'
    f.write_text('x = (1, 2, 3,)\n')
    result = runner.invoke(remove_trailing_commas_main, [str(f), '--no-format'])
    assert result.exit_code == 0
    assert 'Modified 1 file.' in result.output
    assert f.read_text() == 'x = (1, 2, 3)\n'


def test_remove_trailing_commas_main_no_change(runner: CliRunner, tmp_path: Path) -> None:
    f = tmp_path / 'clean.py'
    f.write_text('x = (1,)\n')
    result = runner.invoke(remove_trailing_commas_main, [str(f), '--no-format'])
    assert result.exit_code == 0
    assert 'Modified 0 files.' in result.output


def test_remove_trailing_commas_main_skips_non_python(runner: CliRunner, tmp_path: Path) -> None:
    f = tmp_path / 'data.cff'
    f.write_text('cff-version: 1.2.0\n')
    result = runner.invoke(remove_trailing_commas_main, [str(f), '--no-format'])
    assert result.exit_code == 0
    assert 'Modified 0 files.' in result.output


def test_remove_trailing_commas_main_skips_binary(runner: CliRunner, tmp_path: Path) -> None:
    f = tmp_path / 'binary.dat'
    f.write_bytes(b'\x00\x01\x02\x03\xff')
    result = runner.invoke(remove_trailing_commas_main, [str(f), '--no-format'])
    assert result.exit_code == 0
    assert 'Modified 0 files.' in result.output


def test_remove_trailing_commas_main_skips_unreadable(runner: CliRunner, tmp_path: Path,
                                                      mocker: MockerFixture) -> None:
    f = tmp_path / 'oops.py'
    f.write_text('x = (1,)\n')
    mocker.patch('pathlib.Path.read_text', side_effect=OSError('boom'))
    result = runner.invoke(remove_trailing_commas_main, [str(f), '--no-format'])
    assert result.exit_code == 0


def test_remove_trailing_commas_main_skips_token_error(runner: CliRunner, tmp_path: Path,
                                                       mocker: MockerFixture) -> None:
    f = tmp_path / 'broken.py'
    f.write_text('x = (1,)\n')
    mocker.patch('deltona.commands.misc.remove_trailing_commas',
                 side_effect=tokenize.TokenError('bad'))
    mocker.patch('deltona.commands.misc.ast.parse')
    result = runner.invoke(remove_trailing_commas_main, [str(f), '--no-format'])
    assert result.exit_code == 0


def test_remove_trailing_commas_main_directory(runner: CliRunner, tmp_path: Path) -> None:
    (tmp_path / 'a.py').write_text('x = (1, 2,)\n')
    (tmp_path / 'b.py').write_text('y = [3, 4,]\n')
    (tmp_path / 'data.txt').write_text('cff-version: 1.2.0\n')
    result = runner.invoke(remove_trailing_commas_main, [str(tmp_path), '--no-format'])
    assert result.exit_code == 0
    assert 'Modified 2 files.' in result.output


def test_remove_trailing_commas_main_no_dot(runner: CliRunner, tmp_path: Path) -> None:
    (tmp_path / 'a.py').write_text('x = (1, 2,)\n')
    hidden = tmp_path / '.hidden'
    hidden.mkdir()
    (hidden / 'b.py').write_text('y = (1, 2,)\n')
    result = runner.invoke(remove_trailing_commas_main, [str(tmp_path), '--no-format', '--no-dot'])
    assert result.exit_code == 0
    assert 'Modified 1 file.' in result.output
    assert (hidden / 'b.py').read_text() == 'y = (1, 2,)\n'


def test_remove_trailing_commas_main_gitignore(runner: CliRunner, tmp_path: Path) -> None:
    (tmp_path / '.git').mkdir()
    (tmp_path / '.gitignore').write_text('build/\n')
    (tmp_path / 'a.py').write_text('x = (1, 2,)\n')
    build = tmp_path / 'build'
    build.mkdir()
    (build / 'b.py').write_text('y = (1, 2,)\n')
    result = runner.invoke(remove_trailing_commas_main, [str(tmp_path), '--no-format'])
    assert result.exit_code == 0
    assert 'Modified 1 file.' in result.output
    assert (build / 'b.py').read_text() == 'y = (1, 2,)\n'


def test_remove_trailing_commas_main_no_gitignore(runner: CliRunner, tmp_path: Path) -> None:
    (tmp_path / '.git').mkdir()
    (tmp_path / '.gitignore').write_text('build/\n')
    (tmp_path / 'a.py').write_text('x = (1, 2,)\n')
    build = tmp_path / 'build'
    build.mkdir()
    (build / 'b.py').write_text('y = (1, 2,)\n')
    result = runner.invoke(remove_trailing_commas_main,
                           [str(tmp_path), '--no-format', '--no-gitignore'])
    assert result.exit_code == 0
    assert 'Modified 2 files.' in result.output


def test_remove_trailing_commas_main_runs_format(runner: CliRunner, tmp_path: Path,
                                                 mocker: MockerFixture) -> None:
    f = tmp_path / 'x.py'
    f.write_text('x = (1, 2, 3,)\n')
    (tmp_path / 'package.json').write_text('{"scripts": {"format": "x", "ruff:fix": "y"}}')
    yarn = tmp_path / 'yarn-fake'
    yarn.write_text('')
    mocker.patch('deltona.commands.misc.shutil.which', return_value=str(yarn))
    mocker.patch('pathlib.Path.cwd', return_value=tmp_path)
    run_mock = mocker.patch('deltona.commands.misc.sp.run')
    result = runner.invoke(remove_trailing_commas_main, [str(f)])
    assert result.exit_code == 0
    assert run_mock.call_count == 2


def test_remove_trailing_commas_main_no_yarn(runner: CliRunner, tmp_path: Path,
                                             mocker: MockerFixture) -> None:
    f = tmp_path / 'x.py'
    f.write_text('x = (1, 2, 3,)\n')
    mocker.patch('deltona.commands.misc.shutil.which', return_value=None)
    run_mock = mocker.patch('deltona.commands.misc.sp.run')
    result = runner.invoke(remove_trailing_commas_main, [str(f)])
    assert result.exit_code == 0
    run_mock.assert_not_called()


def test_remove_trailing_commas_main_package_json_invalid(runner: CliRunner, tmp_path: Path,
                                                          mocker: MockerFixture) -> None:
    f = tmp_path / 'x.py'
    f.write_text('x = (1, 2, 3,)\n')
    (tmp_path / 'package.json').write_text('not json')
    yarn = tmp_path / 'yarn-fake'
    yarn.write_text('')
    mocker.patch('deltona.commands.misc.shutil.which', return_value=str(yarn))
    mocker.patch('pathlib.Path.cwd', return_value=tmp_path)
    run_mock = mocker.patch('deltona.commands.misc.sp.run')
    result = runner.invoke(remove_trailing_commas_main, [str(f)])
    assert result.exit_code == 0
    run_mock.assert_not_called()


def test_remove_trailing_commas_main_package_json_no_scripts(runner: CliRunner, tmp_path: Path,
                                                             mocker: MockerFixture) -> None:
    f = tmp_path / 'x.py'
    f.write_text('x = (1, 2, 3,)\n')
    (tmp_path / 'package.json').write_text('{"name": "x"}')
    yarn = tmp_path / 'yarn-fake'
    yarn.write_text('')
    mocker.patch('deltona.commands.misc.shutil.which', return_value=str(yarn))
    mocker.patch('pathlib.Path.cwd', return_value=tmp_path)
    run_mock = mocker.patch('deltona.commands.misc.sp.run')
    result = runner.invoke(remove_trailing_commas_main, [str(f)])
    assert result.exit_code == 0
    run_mock.assert_not_called()


def test_remove_trailing_commas_main_package_json_not_found(runner: CliRunner, tmp_path: Path,
                                                            mocker: MockerFixture) -> None:
    f = tmp_path / 'x.py'
    f.write_text('x = (1, 2, 3,)\n')
    yarn = tmp_path / 'yarn-fake'
    yarn.write_text('')
    mocker.patch('deltona.commands.misc.shutil.which', return_value=str(yarn))
    mocker.patch('pathlib.Path.cwd', return_value=tmp_path)
    run_mock = mocker.patch('deltona.commands.misc.sp.run')
    result = runner.invoke(remove_trailing_commas_main, [str(f)])
    assert result.exit_code == 0
    run_mock.assert_not_called()


def test_remove_trailing_commas_main_package_json_walks_up(runner: CliRunner, tmp_path: Path,
                                                           mocker: MockerFixture) -> None:
    (tmp_path / 'package.json').write_text('{"scripts": {"format": "x"}}')
    sub = tmp_path / 'sub' / 'deeper'
    sub.mkdir(parents=True)
    f = sub / 'x.py'
    f.write_text('x = (1, 2, 3,)\n')
    yarn = tmp_path / 'yarn-fake'
    yarn.write_text('')
    mocker.patch('deltona.commands.misc.shutil.which', return_value=str(yarn))
    mocker.patch('pathlib.Path.cwd', return_value=sub)
    run_mock = mocker.patch('deltona.commands.misc.sp.run')
    result = runner.invoke(remove_trailing_commas_main, [str(f)])
    assert result.exit_code == 0
    assert run_mock.call_count == 1


def test_remove_trailing_commas_main_undone_by_format(runner: CliRunner, tmp_path: Path,
                                                      mocker: MockerFixture) -> None:
    f = tmp_path / 'x.py'
    original = 'x = (1, 2, 3,)\n'
    f.write_text(original)
    (tmp_path / 'package.json').write_text('{"scripts": {"format": "x", "ruff:fix": "y"}}')
    yarn = tmp_path / 'yarn-fake'
    yarn.write_text('')
    mocker.patch('deltona.commands.misc.shutil.which', return_value=str(yarn))
    mocker.patch('pathlib.Path.cwd', return_value=tmp_path)

    def fake_run(_args: object, **_kwargs: object) -> MagicMock:
        f.write_text(original)
        return MagicMock(returncode=0)

    mocker.patch('deltona.commands.misc.sp.run', side_effect=fake_run)
    result = runner.invoke(remove_trailing_commas_main, [str(f)])
    assert result.exit_code == 0
    assert 'Modified 0 files.' in result.output


def test_remove_trailing_commas_main_disabled_directive(runner: CliRunner, tmp_path: Path) -> None:
    f = tmp_path / 'x.py'
    f.write_text('# rtc-off\nx = (1, 2, 3,)\n# rtc-on\n')
    result = runner.invoke(remove_trailing_commas_main, [str(f), '--no-format'])
    assert result.exit_code == 0
    assert 'Modified 0 files.' in result.output


def test_remove_trailing_commas_main_gitignore_outside_repo(runner: CliRunner,
                                                            tmp_path: Path) -> None:
    (tmp_path / 'a.py').write_text('x = (1, 2,)\n')
    result = runner.invoke(remove_trailing_commas_main, [str(tmp_path), '--no-format'])
    assert result.exit_code == 0
    assert 'Modified 1 file.' in result.output


def test_remove_trailing_commas_main_nested_gitignore(runner: CliRunner, tmp_path: Path) -> None:
    (tmp_path / '.git').mkdir()
    (tmp_path / '.gitignore').write_text('*.bak\n')
    sub = tmp_path / 'sub'
    sub.mkdir()
    (sub / 'a.py').write_text('x = (1, 2,)\n')
    result = runner.invoke(remove_trailing_commas_main, [str(sub), '--no-format'])
    assert result.exit_code == 0
    assert (sub / 'a.py').read_text() == 'x = (1, 2)\n'


def test_remove_trailing_commas_main_unreadable_gitignore(runner: CliRunner, tmp_path: Path,
                                                          mocker: MockerFixture) -> None:
    (tmp_path / '.git').mkdir()
    (tmp_path / '.gitignore').write_text('*.bak\n')
    (tmp_path / 'a.py').write_text('x = (1, 2,)\n')
    real_read = Path.read_text

    def fake_read_text(self: Path, encoding: str | None = None, errors: str | None = None) -> str:
        if self.name == '.gitignore':
            msg = 'boom'
            raise OSError(msg)
        return real_read(self, encoding=encoding, errors=errors)

    mocker.patch.object(Path, 'read_text', fake_read_text)
    result = runner.invoke(remove_trailing_commas_main, [str(tmp_path), '--no-format'])
    assert result.exit_code == 0


def test_remove_trailing_commas_main_symlink_escapes_base(runner: CliRunner,
                                                          tmp_path: Path) -> None:
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / '.git').mkdir()
    (repo / '.gitignore').write_text('')
    outside = tmp_path / 'outside'
    outside.mkdir()
    target = outside / 'a.py'
    target.write_text('x = (1, 2,)\n')
    (repo / 'link.py').symlink_to(target)
    result = runner.invoke(remove_trailing_commas_main, [str(repo), '--no-format'])
    assert result.exit_code == 0


def test_remove_trailing_commas_main_ruff_fix_returns_nonzero(runner: CliRunner, tmp_path: Path,
                                                              mocker: MockerFixture) -> None:
    f = tmp_path / 'x.py'
    f.write_text('x = (1, 2, 3,)\n')
    (tmp_path / 'package.json').write_text('{"scripts": {"format": "x", "ruff:fix": "y"}}')
    yarn = tmp_path / 'yarn-fake'
    yarn.write_text('')
    mocker.patch('deltona.commands.misc.shutil.which', return_value=str(yarn))
    mocker.patch('pathlib.Path.cwd', return_value=tmp_path)

    def fake_run(args: tuple[str, ...], **_kwargs: object) -> MagicMock:
        return MagicMock(returncode=0 if args[1] == 'format' else 1)

    mocker.patch('deltona.commands.misc.sp.run', side_effect=fake_run)
    result = runner.invoke(remove_trailing_commas_main, [str(f)])
    assert result.exit_code == 0


def test_remove_trailing_commas_main_file_disappears_after_format(runner: CliRunner, tmp_path: Path,
                                                                  mocker: MockerFixture) -> None:
    f = tmp_path / 'x.py'
    f.write_text('x = (1, 2, 3,)\n')
    (tmp_path / 'package.json').write_text('{"scripts": {"format": "x"}}')
    yarn = tmp_path / 'yarn-fake'
    yarn.write_text('')
    mocker.patch('deltona.commands.misc.shutil.which', return_value=str(yarn))
    mocker.patch('pathlib.Path.cwd', return_value=tmp_path)

    def delete_during_format(_args: object, **_kwargs: object) -> MagicMock:
        f.unlink()
        return MagicMock(returncode=0)

    mocker.patch('deltona.commands.misc.sp.run', side_effect=delete_during_format)
    result = runner.invoke(remove_trailing_commas_main, [str(f)])
    assert result.exit_code == 0
    assert 'Modified 1 file.' in result.output
