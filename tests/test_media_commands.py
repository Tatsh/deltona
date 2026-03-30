from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock
import enum
import subprocess as sp

from deltona.commands.media import (
    add_cdda_times_main,
    add_info_json_main,
    audio2vid_main,
    cddb_query_main,
    display_info_json_main,
    encode_dashcam_main,
    flac_dir_finalize_main,
    hlg2sdr_main,
    ke_ebook_ex_main,
    mvid_rename_main,
    supported_audio_input_formats_main,
    tbc2srt_main,
    ultraiso_main,
    wait_for_disc_main,
)
from deltona.ultraiso import InsufficientArguments
import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from click.testing import CliRunner
    from pytest_mock import MockerFixture


class _ReturnCodeType(enum.IntEnum):
    SUCCESS = enum.auto()
    FAILURE = enum.auto()


@pytest.mark.parametrize(
    ('input_', 'cdda_return', 'return_code_type'),
    [
        ('', None, _ReturnCodeType.FAILURE),
        ('01:23:45', None, _ReturnCodeType.FAILURE),
        ('01:23:45', '01:23:45', _ReturnCodeType.SUCCESS),
        ('00:00:00', '00:00:00', _ReturnCodeType.SUCCESS),
        ('12:34:00', '12:34:00', _ReturnCodeType.SUCCESS),
        ('01:02:03', '01:02:03', _ReturnCodeType.SUCCESS),
        ('01:02:00', '01:02:00', _ReturnCodeType.SUCCESS),
        ('00:01:', None, _ReturnCodeType.FAILURE),
    ],
)
def test_add_cdda_times_main_success(
    input_: str,
    cdda_return: str,
    return_code_type: _ReturnCodeType,
    mocker: MockerFixture,
    runner: CliRunner,
) -> None:
    mocker.patch('deltona.commands.media.add_cdda_times', return_value=cdda_return)
    result = runner.invoke(add_cdda_times_main, [input_])
    if return_code_type == _ReturnCodeType.SUCCESS:
        assert result.exit_code == 0
        assert cdda_return in result.output
    else:
        assert result.exit_code != 0


def test_wait_for_disc_main_success(mocker: MockerFixture, runner: CliRunner,
                                    tmp_path: Path) -> None:
    mocker.patch('deltona.commands.media.wait_for_disc', return_value=True)
    file = tmp_path / 'disc'
    file.write_text('dummy')
    result = runner.invoke(wait_for_disc_main, [str(file)])
    assert result.exit_code == 0


def test_wait_for_disc_main_fail(mocker: MockerFixture, runner: CliRunner, tmp_path: Path) -> None:
    mocker.patch('deltona.commands.media.wait_for_disc', return_value=False)
    file = tmp_path / 'disc'
    file.write_text('dummy')
    result = runner.invoke(wait_for_disc_main, [str(file)])
    assert result.exit_code != 0


def test_ultraiso_main_success(mocker: MockerFixture, runner: CliRunner, tmp_path: Path) -> None:
    mocker.patch('deltona.commands.media.run_ultraiso')
    result = runner.invoke(ultraiso_main, ['--appid', 'test', '--output', 'out.iso'])
    assert result.exit_code == 0


def test_ultraiso_main_insufficient_args(mocker: MockerFixture, runner: CliRunner) -> None:
    mocker.patch('deltona.commands.media.run_ultraiso', side_effect=InsufficientArguments)
    result = runner.invoke(ultraiso_main, ['--appid', 'test'])
    assert result.exit_code != 0


def test_ultraiso_main_file_not_found_error(mocker: MockerFixture, runner: CliRunner) -> None:
    mocker.patch('deltona.commands.media.run_ultraiso', side_effect=FileNotFoundError)
    result = runner.invoke(ultraiso_main, ['--appid', 'test'])
    assert result.exit_code != 0


def test_supported_audio_input_formats_main_success(mocker: MockerFixture,
                                                    runner: CliRunner) -> None:
    mocker.patch('deltona.commands.media.supported_audio_input_formats',
                 return_value=[('wav', 44100)])
    result = runner.invoke(supported_audio_input_formats_main, ['dummy'])
    assert result.exit_code == 0
    assert 'wav @ 44100' in result.output


def test_supported_audio_input_formats_main_oserror(mocker: MockerFixture,
                                                    runner: CliRunner) -> None:
    mocker.patch('deltona.commands.media.supported_audio_input_formats', side_effect=OSError)
    result = runner.invoke(supported_audio_input_formats_main, ['dummy'])
    assert result.exit_code != 0


def test_add_info_json_main(mocker: MockerFixture, runner: CliRunner, tmp_path: Path) -> None:
    f = tmp_path / 'file.mp3'
    f.write_text('dummy')
    mocker.patch('deltona.commands.media.add_info_json_to_media_file')
    result = runner.invoke(add_info_json_main, [str(f)])
    assert result.exit_code == 0


def test_display_info_json_main_success(mocker: MockerFixture, runner: CliRunner,
                                        tmp_path: Path) -> None:
    f = tmp_path / 'file.mp3'
    f.write_text('dummy')
    mocker.patch('deltona.commands.media.get_info_json', return_value='{"foo": "bar"}')
    result = runner.invoke(display_info_json_main, [str(f)])
    assert result.exit_code == 0
    assert '{"foo": "bar"}' in result.output


def test_display_info_json_main_not_implemented(mocker: MockerFixture, runner: CliRunner,
                                                tmp_path: Path) -> None:
    f = tmp_path / 'file.mp3'
    f.write_text('dummy')
    mocker.patch('deltona.commands.media.get_info_json', side_effect=NotImplementedError)
    result = runner.invoke(display_info_json_main, [str(f)])
    assert result.exit_code != 0


def test_display_info_json_main_subprocess_error(mocker: MockerFixture, runner: CliRunner,
                                                 tmp_path: Path) -> None:
    f = tmp_path / 'file.mp3'
    f.write_text('dummy')
    mocker.patch(
        'deltona.commands.media.get_info_json',
        side_effect=sp.CalledProcessError(returncode=1, cmd='ffprobe', output='Error'),
    )
    result = runner.invoke(display_info_json_main, [str(f)])
    assert result.exit_code != 0


def test_audio2vid_main(mocker: MockerFixture, runner: CliRunner, tmp_path: Path) -> None:
    f = tmp_path / 'audio.mp3'
    f.write_text('dummy')
    mocker.patch('deltona.commands.media.create_static_text_video')
    result = runner.invoke(audio2vid_main, [str(f), 'hello', 'world'])
    assert result.exit_code == 0


def test_mvid_rename_main(mocker: MockerFixture, runner: CliRunner, tmp_path: Path) -> None:
    d = tmp_path / 'testdir'
    d.mkdir()
    src = d / 'testdir.mkv'
    src.write_text('dummy')
    non_dir = d / 'non_dir.mkv'
    non_dir.write_text('dummy')
    mocker.patch('send2trash.send2trash', side_effect=[None, None, ValueError])
    result = runner.invoke(mvid_rename_main, [str(d), str(non_dir), str(d)])
    assert result.exit_code == 0


def test_cddb_query_main(mocker: MockerFixture, runner: CliRunner) -> None:
    mock_result = mocker.MagicMock(_asdict=lambda: {'foo': 'bar'})
    mocker.patch('deltona.commands.media.cddb_query', new=AsyncMock(return_value=mock_result))
    result = runner.invoke(cddb_query_main, ['arg1', 'arg2'])
    assert result.exit_code == 0
    assert '"foo": "bar"' in result.output


def test_ke_ebook_ex_main(mocker: MockerFixture, runner: CliRunner, tmp_path: Path) -> None:
    d = tmp_path / 'dir'
    d.mkdir()
    mocker.patch('deltona.commands.media.unpack_ebook')
    mocker.patch('send2trash.send2trash')
    result = runner.invoke(ke_ebook_ex_main, [str(d), '--delete-paths'])
    assert result.exit_code == 0


def test_ke_ebook_ex_main_no_delete(mocker: MockerFixture, runner: CliRunner,
                                    tmp_path: Path) -> None:
    d = tmp_path / 'dir'
    d.mkdir()
    mocker.patch('deltona.commands.media.unpack_ebook')
    mock_send2trash = mocker.patch('send2trash.send2trash')
    result = runner.invoke(ke_ebook_ex_main, [str(d)])
    assert result.exit_code == 0
    mock_send2trash.assert_not_called()


def test_encode_dashcam_main(mocker: MockerFixture, runner: CliRunner, tmp_path: Path) -> None:
    f = tmp_path / 'front'
    r = tmp_path / 'rear'
    o = tmp_path / 'out'
    f.mkdir()
    r.mkdir()
    mocker.patch('deltona.commands.media.archive_dashcam_footage')
    result = runner.invoke(encode_dashcam_main, [str(f), str(r), str(o)])
    assert result.exit_code == 0


def test_encode_dashcam_main_same_dirs(runner: CliRunner, tmp_path: Path) -> None:
    d = tmp_path / 'dir'
    d.mkdir()
    result = runner.invoke(encode_dashcam_main, [str(d), str(d), str(tmp_path / 'out')])
    assert result.exit_code != 0


def test_encode_dashcam_main_defaults(mocker: MockerFixture, runner: CliRunner,
                                      tmp_path: Path) -> None:
    f = tmp_path / 'front'
    r = tmp_path / 'rear'
    o = tmp_path / 'out'
    f.mkdir()
    r.mkdir()
    mock_archive = mocker.patch('deltona.commands.media.archive_dashcam_footage')
    result = runner.invoke(encode_dashcam_main, [str(f), str(r), str(o)])
    assert result.exit_code == 0
    kwargs = mock_archive.call_args[1]
    assert kwargs['video_encoder'] == 'hevc_nvenc'
    assert kwargs['preset'] == 'p7'
    assert kwargs['video_max_bitrate'] == '20M'
    assert kwargs['crf'] == 26
    assert kwargs['chapters'] is True


def test_encode_dashcam_main_no_chapters(mocker: MockerFixture, runner: CliRunner,
                                         tmp_path: Path) -> None:
    f = tmp_path / 'front'
    r = tmp_path / 'rear'
    o = tmp_path / 'out'
    f.mkdir()
    r.mkdir()
    mock_archive = mocker.patch('deltona.commands.media.archive_dashcam_footage')
    result = runner.invoke(encode_dashcam_main, [str(f), str(r), str(o), '--no-chapters'])
    assert result.exit_code == 0
    assert mock_archive.call_args[1]['chapters'] is False


def test_encode_dashcam_main_temp_dir(mocker: MockerFixture, runner: CliRunner,
                                      tmp_path: Path) -> None:
    f = tmp_path / 'front'
    r = tmp_path / 'rear'
    o = tmp_path / 'out'
    t = tmp_path / 'temp'
    f.mkdir()
    r.mkdir()
    t.mkdir()
    mock_archive = mocker.patch('deltona.commands.media.archive_dashcam_footage')
    result = runner.invoke(encode_dashcam_main, [str(f), str(r), str(o), '-T', str(t)])
    assert result.exit_code == 0
    assert mock_archive.call_args[1]['temp_dir'] == t


def test_encode_dashcam_main_no_hwaccel(mocker: MockerFixture, runner: CliRunner,
                                        tmp_path: Path) -> None:
    f = tmp_path / 'front'
    r = tmp_path / 'rear'
    o = tmp_path / 'out'
    f.mkdir()
    r.mkdir()
    mock_archive = mocker.patch('deltona.commands.media.archive_dashcam_footage')
    result = runner.invoke(encode_dashcam_main, [str(f), str(r), str(o), '--no-hwaccel'])
    assert result.exit_code == 0
    mock_archive.assert_called_once()
    assert mock_archive.call_args[1]['hwaccel'] is None


def test_encode_dashcam_main_no_rear_crop(mocker: MockerFixture, runner: CliRunner,
                                          tmp_path: Path) -> None:
    f = tmp_path / 'front'
    r = tmp_path / 'rear'
    o = tmp_path / 'out'
    f.mkdir()
    r.mkdir()
    mock_archive = mocker.patch('deltona.commands.media.archive_dashcam_footage')
    result = runner.invoke(encode_dashcam_main, [str(f), str(r), str(o), '--no-rear-crop'])
    assert result.exit_code == 0
    assert mock_archive.call_args[1]['rear_crop'] is None


def test_encode_dashcam_main_no_setpts(mocker: MockerFixture, runner: CliRunner,
                                       tmp_path: Path) -> None:
    f = tmp_path / 'front'
    r = tmp_path / 'rear'
    o = tmp_path / 'out'
    f.mkdir()
    r.mkdir()
    mock_archive = mocker.patch('deltona.commands.media.archive_dashcam_footage')
    result = runner.invoke(encode_dashcam_main, [str(f), str(r), str(o), '--no-setpts'])
    assert result.exit_code == 0
    assert mock_archive.call_args[1]['setpts'] is None


def test_encode_dashcam_main_max_offset(mocker: MockerFixture, runner: CliRunner,
                                        tmp_path: Path) -> None:
    f = tmp_path / 'front'
    r = tmp_path / 'rear'
    o = tmp_path / 'out'
    f.mkdir()
    r.mkdir()
    mock_archive = mocker.patch('deltona.commands.media.archive_dashcam_footage')
    result = runner.invoke(encode_dashcam_main, [str(f), str(r), str(o), '--max-offset', '5'])
    assert result.exit_code == 0
    assert mock_archive.call_args[1]['max_offset'] == 5


def test_encode_dashcam_main_no_rear_dir(mocker: MockerFixture, runner: CliRunner,
                                         tmp_path: Path) -> None:
    f = tmp_path / 'front'
    f.mkdir()
    mock_archive = mocker.patch('deltona.commands.media.archive_dashcam_footage')
    result = runner.invoke(encode_dashcam_main, [str(f)])
    assert result.exit_code == 0
    assert mock_archive.call_args[1]['pair_fn'] is None
    assert mock_archive.call_args[0][1] is None


def test_encode_dashcam_main_no_delete(mocker: MockerFixture, runner: CliRunner,
                                       tmp_path: Path) -> None:
    f = tmp_path / 'front'
    r = tmp_path / 'rear'
    o = tmp_path / 'out'
    f.mkdir()
    r.mkdir()
    mock_archive = mocker.patch('deltona.commands.media.archive_dashcam_footage')
    result = runner.invoke(encode_dashcam_main, [str(f), str(r), str(o), '-D'])
    assert result.exit_code == 0
    assert mock_archive.call_args[1]['no_delete'] is True


def test_hlg2sdr_main(mocker: MockerFixture, runner: CliRunner, tmp_path: Path) -> None:
    f = tmp_path / 'file.mkv'
    f.write_text('dummy')
    mocker.patch('deltona.commands.media.hlg_to_sdr')
    result = runner.invoke(hlg2sdr_main, [str(f)])
    assert result.exit_code == 0


def test_tbc2srt_main(mocker: MockerFixture, runner: CliRunner, tmp_path: Path) -> None:
    f = tmp_path / 'file.tbc'
    f.write_text('dummy')
    mocker.patch('deltona.commands.media.sp.run')
    mocker.patch('send2trash.send2trash')
    result = runner.invoke(tbc2srt_main, [str(f)])
    assert result.exit_code == 0


def test_flac_dir_finalize_main(mocker: MockerFixture, runner: CliRunner, tmp_path: Path) -> None:
    d = tmp_path / 'album'
    d.mkdir()
    flac = d / '01.flac'
    flac.write_text('dummy')
    img = d / 'cover.jpg'
    img.write_text('dummy')
    mocker.patch('deltona.commands.media.underscorize', side_effect=lambda x: x)
    mocker.patch('deltona.commands.media.make_sfv')
    mocker.patch(
        'deltona.commands.media.sp.run',
        return_value=mocker.MagicMock(
            stdout='tracknumber=1\nartist=Artist\ntitle=Title\nunknown\n'),
    )
    result = runner.invoke(flac_dir_finalize_main, [str(d)])
    assert result.exit_code == 0
