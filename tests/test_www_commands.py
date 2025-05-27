from __future__ import annotations

from typing import TYPE_CHECKING
import json

from deltona.commands.www import (
    check_bookmarks_html_main,
    chrome_bisect_flags_main,
    fix_chromium_pwa_icon_main,
    where_from_main,
)

if TYPE_CHECKING:
    from pathlib import Path

    from click.testing import CliRunner
    from pytest_mock import MockerFixture


def test_where_from_single(mocker: MockerFixture, runner: CliRunner, tmp_path: Path) -> None:
    mock_where_from = mocker.patch('deltona.commands.www.where_from')
    mock_where_from.return_value = 'where_from_result'
    mock_arg1 = tmp_path / 'arg1.txt'
    mock_arg1.write_text('This is a test file.')
    result = runner.invoke(where_from_main, [str(mock_arg1)])
    assert result.exit_code == 0
    assert 'where_from_result' in result.output


def test_where_from_multiple(mocker: MockerFixture, runner: CliRunner, tmp_path: Path) -> None:
    mock_where_from = mocker.patch('deltona.commands.www.where_from')
    mock_where_from.return_value = 'where_from_result'
    mock_arg1 = tmp_path / 'arg1.txt'
    mock_arg1.write_text('This is a test file.')
    mock_arg2 = tmp_path / 'arg2.txt'
    mock_arg2.write_text('This is another test file.')
    result = runner.invoke(where_from_main, [str(mock_arg1), str(mock_arg2)])
    assert result.exit_code == 0
    assert 'arg1.txt: where_from_result' in result.output
    assert 'arg2.txt: where_from_result' in result.output


def test_fix_chromium_pwa_icon_main(mocker: MockerFixture, runner: CliRunner,
                                    tmp_path: Path) -> None:
    mock_fix_icon = mocker.patch('deltona.commands.www.fix_chromium_pwa_icon')
    result = runner.invoke(fix_chromium_pwa_icon_main, ['app_id', 'src_uri', '-c', str(tmp_path)])
    assert result.exit_code == 0
    mock_fix_icon.assert_called_once_with(mocker.ANY,
                                          'app_id',
                                          'src_uri',
                                          'Default',
                                          masked=False,
                                          monochrome=False)


def test_check_bookmarks_html_main(mocker: MockerFixture, runner: CliRunner,
                                   tmp_path: Path) -> None:
    mock_check_urls = mocker.patch('deltona.commands.www.check_bookmarks_html_urls',
                                   return_value=[None, ['a', 'b'], ['c', 'd']])
    mock_file = tmp_path / 'bookmarks.html'
    mock_file.write_text('<html><body>Bookmarks</body></html>')
    result = runner.invoke(check_bookmarks_html_main, [str(mock_file)])
    assert result.exit_code == 0
    mock_check_urls.assert_called_once_with('<html><body>Bookmarks</body></html>')
    assert '2 URLs changed.' in result.output
    assert '2 URLs resulted in 404 response.' in result.output


def test_chrome_bisect_flags_main_no_flags(mocker: MockerFixture, runner: CliRunner,
                                           tmp_path: Path) -> None:
    mock_local_state = tmp_path / 'Local State'
    mock_local_state.write_text(json.dumps({'browser': {'enabled_labs_experiments': []}}))
    result = runner.invoke(chrome_bisect_flags_main, [str(mock_local_state)])
    assert result.exit_code != 0
    assert 'Nothing to test.' in result.output


def test_chrome_bisect_flags_main_3_flags(mocker: MockerFixture, runner: CliRunner,
                                          tmp_path: Path) -> None:
    mocker.patch('deltona.commands.www.kill_processes_by_name')
    mock_local_state = tmp_path / 'Local State'
    mock_local_state.write_text(
        json.dumps({'browser': {
            'enabled_labs_experiments': ['a', 'b', 'c']
        }}))
    result = runner.invoke(chrome_bisect_flags_main, [str(mock_local_state)], input='\n\ny\nn\ny\n')
    assert result.exit_code == 0
    assert 'Saved "Local State" with "a" removed.' in result.output


def test_chrome_bisect_flags_main_4_flags(mocker: MockerFixture, runner: CliRunner,
                                          tmp_path: Path) -> None:
    mocker.patch('deltona.commands.www.kill_processes_by_name')
    mock_local_state = tmp_path / 'Local State'
    mock_local_state.write_text(
        json.dumps({'browser': {
            'enabled_labs_experiments': ['a', 'b', 'c', 'd']
        }}))
    result = runner.invoke(chrome_bisect_flags_main, [str(mock_local_state)],
                           input=('\n\n'
                                  'n\n'
                                  '\n'
                                  'y\n'
                                  '\n'
                                  'n\n'
                                  '\n'
                                  'y\n'))
    assert result.exit_code == 0
    assert 'Saved "Local State" with "d" removed.' in result.output


def test_chrome_bisect_flags_main_invalid_response(mocker: MockerFixture, runner: CliRunner,
                                                   tmp_path: Path) -> None:
    mocker.patch('deltona.commands.www.kill_processes_by_name')
    mock_local_state = tmp_path / 'Local State'
    mock_local_state.write_text(
        json.dumps({'browser': {
            'enabled_labs_experiments': ['a', 'b', 'c', 'd']
        }}))
    result = runner.invoke(chrome_bisect_flags_main, [str(mock_local_state)],
                           input=('\n\n'
                                  'n\n'
                                  '\n'
                                  'y\n'
                                  '\n'
                                  'n\n'
                                  '\n'
                                  '\n'))  # Invalid response here.
    assert result.exit_code == 0
    assert 'Restored original "Local State".' in result.output


def test_chrome_bisect_flags_main_single_flag(mocker: MockerFixture, runner: CliRunner,
                                              tmp_path: Path) -> None:
    mocker.patch('deltona.commands.www.kill_processes_by_name')
    mock_local_state = tmp_path / 'Local State'
    mock_local_state.write_text(json.dumps({'browser': {'enabled_labs_experiments': ['a']}}))
    result = runner.invoke(chrome_bisect_flags_main, [str(mock_local_state)], input='\n\nn\n')
    assert result.exit_code == 0
    assert 'Saved "Local State" with "a" removed.' in result.output
