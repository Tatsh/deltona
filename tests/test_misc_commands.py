from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from deltona.commands.misc import adp_main, burnrariso_main, gogextract_main, unpack_0day_main
from deltona.io import SFVVerificationError, UnRARExtractionTestFailed
import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from click.testing import CliRunner
    from pytest_mock import MockerFixture


@pytest.fixture
def fake_path(tmp_path: Path) -> Path:
    d = tmp_path / 'dir'
    d.mkdir()
    return d


def test_adp_main(runner: CliRunner, mocker: MockerFixture) -> None:
    mock_calc = mocker.patch('deltona.commands.misc.calculate_salary', return_value=12345)
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
