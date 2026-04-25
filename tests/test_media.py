from __future__ import annotations

from typing import TYPE_CHECKING, Any
import subprocess as sp

from deltona.media import (
    add_info_json_to_media_file,
    archive_dashcam_footage,
    cddb_query,
    create_static_text_video,
    ffprobe,
    get_info_json,
    group_files,
    group_pairs,
    hlg_to_sdr,
    is_audio_input_format_supported,
    pair_redtiger_dashcam_files,
    parse_timestamp,
    supported_audio_input_formats,
)
from niquests import HTTPError
import pytest

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from pytest_mock import MockerFixture


def test_supported_audio_input_formats_success(mocker: MockerFixture) -> None:
    fake_proc = mocker.Mock()
    fake_proc.stdout = '44100 Hz\n48000 Hz\n'
    fake_proc.stderr = ''
    mocker.patch('deltona.media.sp.run', return_value=fake_proc)
    formats = ('f32le', 's16le')
    rates = (44100, 48000)
    result = supported_audio_input_formats('hw:Audio', formats=formats, rates=rates)
    assert set(result) == {('f32le', 44100), ('f32le', 48000), ('s16le', 44100), ('s16le', 48000)}


def test_supported_audio_input_formats_device_error(mocker: MockerFixture) -> None:
    fake_proc = mocker.Mock()
    fake_proc.stdout = ''
    fake_proc.stderr = 'Device or resource busy'
    mocker.patch('deltona.media.sp.run', return_value=fake_proc)
    with pytest.raises(OSError):  # noqa: PT011
        supported_audio_input_formats('hw:Missing', formats=('f32le',), rates=(44100,))


def test_supported_audio_input_formats_partial_support(mocker: MockerFixture) -> None:
    # Simulate ffmpeg only supporting one format/rate
    def fake_run(cmd: Sequence[str], *args: Any, **kwargs: Any) -> Any:
        if 'pcm_f32le' in cmd and '44100' in cmd:
            return mocker.Mock(stdout='44100 Hz', stderr='')
        return mocker.Mock(stdout='', stderr='cannot set sample format 0x')

    mocker.patch('deltona.media.sp.run', side_effect=fake_run)
    result = supported_audio_input_formats('hw:Audio',
                                           formats=('f32le', 's16le'),
                                           rates=(44100, 48000))
    assert result == (('f32le', 44100),)


def test_supported_audio_input_formats_empty(mocker: MockerFixture) -> None:
    mocker.patch('deltona.media.sp.run')
    result = supported_audio_input_formats('hw:Audio', formats=('f32le',), rates=(44100,))
    assert result == ()


def test_is_audio_input_format_supported_true(mocker: MockerFixture) -> None:
    mocker.patch('deltona.media.supported_audio_input_formats', return_value=(('f32le', 44100),))
    assert is_audio_input_format_supported('hw:Audio', 'f32le', 44100) is True


def test_ffprobe_success(mocker: MockerFixture) -> None:
    fake_proc = mocker.Mock()
    fake_proc.stdout = '{"format": {"tags": {"title": "Test"}}}'
    mocker.patch('deltona.media.sp.run', return_value=fake_proc)
    result = ffprobe('test.flac')
    assert isinstance(result, dict)
    assert result['format']['tags']['title'] == 'Test'


def test_get_info_json_flac(mocker: MockerFixture) -> None:
    # Simulate ffprobe returning info_json in tags
    fake_proc = mocker.Mock()
    fake_proc.stdout = '{"format": {"tags": {"info_json": "{\\"foo\\": \\"bar\\"}"}}}'
    mocker.patch('deltona.media.sp.run', return_value=fake_proc)
    result = get_info_json('test.flac')
    assert isinstance(result, dict)
    assert result['foo'] == 'bar'


def test_get_info_json_mp4(mocker: MockerFixture) -> None:
    # Simulate MP4Box returning info_json string
    fake_proc = mocker.Mock()
    fake_proc.stdout = '{"foo": "bar"}'
    mocker.patch('deltona.media.sp.run', return_value=fake_proc)
    result = get_info_json('test.mp4')
    assert isinstance(result, dict)
    assert result['foo'] == 'bar'


def test_get_info_json_mkv(mocker: MockerFixture) -> None:
    # Simulate mkvextract returning info_json as second line
    fake_proc = mocker.Mock()
    fake_proc.stdout = 'Attachment: info.json\n{"foo": "bar"}'
    mocker.patch('deltona.media.sp.run', return_value=fake_proc)
    result = get_info_json('test.mkv')
    assert isinstance(result, dict)
    assert result['foo'] == 'bar'


def test_get_info_json_mp3(mocker: MockerFixture) -> None:
    # Simulate ffprobe returning TXXX tag with info_json
    fake_proc = mocker.Mock()
    fake_proc.stdout = '{"format": {"tags": {"TXXX": "info_json={\\"foo\\": \\"bar\\"}"}}}'
    mocker.patch('deltona.media.sp.run', return_value=fake_proc)
    result = get_info_json('test.mp3')
    assert isinstance(result, dict)
    assert result['foo'] == 'bar'


def test_get_info_json_opus(mocker: MockerFixture) -> None:
    # Simulate ffprobe returning info_json in streams[0].tags
    fake_proc = mocker.Mock()
    fake_proc.stdout = '{"streams": [{"tags": {"info_json": "{\\"foo\\": \\"bar\\"}"}}]}'
    mocker.patch('deltona.media.sp.run', return_value=fake_proc)
    result = get_info_json('test.opus')
    assert isinstance(result, dict)
    assert result['foo'] == 'bar'


def test_get_info_json_raw_true_flac(mocker: MockerFixture) -> None:
    # Test raw=True returns the raw string
    fake_proc = mocker.Mock()
    fake_proc.stdout = '{"format": {"tags": {"info_json": "{\\"foo\\": \\"bar\\"}"}}}'
    mocker.patch('deltona.media.sp.run', return_value=fake_proc)
    result = get_info_json('test.flac', raw=True)
    assert isinstance(result, str)
    assert result == '{"foo": "bar"}'


def test_get_info_json_not_implemented(mocker: MockerFixture) -> None:
    with pytest.raises(NotImplementedError):
        get_info_json('test.unknown')


def test_create_static_text_video_default_args(mocker: MockerFixture, tmp_path: Path) -> None:
    fake_tempfile = mocker.patch('tempfile.NamedTemporaryFile')
    fake_tf = mocker.Mock()
    fake_tf.name = str(tmp_path / 'temp.png')
    fake_tempfile.return_value.__enter__.return_value = fake_tf
    mock_run = mocker.patch('deltona.media.sp.run')
    mock_unlink = mocker.patch('pathlib.Path.unlink')
    audio_file = tmp_path / 'audio.flac'
    audio_file.write_bytes(b'dummy audio')
    text = 'Test Text'
    create_static_text_video(audio_file, text)
    assert mock_run.call_count >= 1
    mock_unlink.assert_called_with()


def test_create_static_text_video_nvenc(mocker: MockerFixture, tmp_path: Path) -> None:
    fake_tempfile = mocker.patch('tempfile.NamedTemporaryFile')
    fake_tf = mocker.Mock()
    fake_tf.name = str(tmp_path / 'temp.png')
    fake_tempfile.return_value.__enter__.return_value = fake_tf
    mock_run = mocker.patch('deltona.media.sp.run')
    mocker.patch('pathlib.Path.unlink')
    audio_file = tmp_path / 'audio.flac'
    audio_file.write_bytes(b'dummy audio')
    text = 'NVENC Test'
    create_static_text_video(audio_file, text, nvenc=True)
    called_args = [call[0][0] for call in mock_run.call_args_list]
    assert any('h264_nvenc' in str(args) for args in called_args)


def test_create_static_text_video_videotoolbox(mocker: MockerFixture, tmp_path: Path) -> None:
    fake_tempfile = mocker.patch('tempfile.NamedTemporaryFile')
    fake_tf = mocker.Mock()
    fake_tf.name = str(tmp_path / 'temp.png')
    fake_tempfile.return_value.__enter__.return_value = fake_tf

    mock_run = mocker.patch('deltona.media.sp.run')
    mocker.patch('pathlib.Path.unlink')

    audio_file = tmp_path / 'audio.flac'
    audio_file.write_bytes(b'dummy audio')
    text = 'VT Test'

    create_static_text_video(audio_file, text, videotoolbox=True)

    called_args = [call[0][0] for call in mock_run.call_args_list]
    assert any('hevc_videotoolbox' in str(args) for args in called_args)


def test_create_static_text_video_nvenc_and_videotoolbox_error(mocker: MockerFixture,
                                                               tmp_path: Path) -> None:
    audio_file = tmp_path / 'audio.flac'
    audio_file.write_bytes(b'dummy audio')
    text = 'Error Test'
    with pytest.raises(ValueError, match=r'^nvenc and videotoolbox parameters are exclusive.'):
        create_static_text_video(audio_file, text, nvenc=True, videotoolbox=True)


def test_create_static_text_video_sp_run_raises(mocker: MockerFixture, tmp_path: Path) -> None:
    fake_tempfile = mocker.patch('tempfile.NamedTemporaryFile')
    fake_tf = mocker.Mock()
    fake_tf.name = str(tmp_path / 'temp.png')
    fake_tempfile.return_value.__enter__.return_value = fake_tf

    mocker.patch('deltona.media.sp.run', side_effect=[sp.CalledProcessError(1, 'cmd'), None])
    mocker.patch('pathlib.Path.unlink')

    audio_file = tmp_path / 'audio.flac'
    audio_file.write_bytes(b'dummy audio')
    text = 'Fail Test'

    with pytest.raises(sp.CalledProcessError):
        create_static_text_video(audio_file, text)


@pytest.mark.asyncio
async def test_cddb_query_no_username(mocker: MockerFixture) -> None:
    cddb_query.cache_clear()
    disc_id = '12345678 1 123 456 789'
    mocker.patch('deltona.media.socket.gethostname', return_value='host')
    mocker.patch('deltona.media.getpass.getuser', return_value=None)
    mocker.patch('keyring.get_password', return_value='host')
    with pytest.raises(ValueError):  # noqa: PT011
        await cddb_query(disc_id)


@pytest.mark.asyncio
async def test_cddb_query_no_host(mocker: MockerFixture) -> None:
    cddb_query.cache_clear()
    disc_id = '12345678 1 123 456 789'
    mocker.patch('deltona.media.socket.gethostname', return_value='host')
    mocker.patch('deltona.media.getpass.getuser', return_value='username')
    mocker.patch('keyring.get_password', return_value=None)
    with pytest.raises(ValueError):  # noqa: PT011
        await cddb_query(disc_id)


@pytest.mark.asyncio
async def test_cddb_query_success_single_match(mocker: MockerFixture) -> None:
    cddb_query.cache_clear()
    disc_id = '12345678 2 123 456 789'
    query_response = '200 rock 12345678 Artist / Album / 2020 / 2\n'
    read_response = ("210 Found exact matches, list follows (until terminating `.')\n"
                     'DTITLE=Artist / Album\n'
                     'DYEAR=2020\n'
                     'DGENRE=Rock\n'
                     'TTITLE0=Track One\n'
                     'TTITLE1=Track Two\n'
                     '.\n')
    mocker.patch('deltona.media.socket.gethostname', return_value='host')
    mocker.patch('deltona.media.getpass.getuser', return_value='user')
    mocker.patch('keyring.get_password', return_value='host')

    def fake_requests_get(url: str,
                          params: Any = None,
                          timeout: int | None = None,
                          **kwargs: Any) -> Any:
        class FakeResponse:
            def __init__(self, text: str) -> None:
                self.text = text
                self.status_code = 200
                self.ok = True

            def raise_for_status(self) -> None:
                pass

        if 'cmd=cddb+query' in url or (params and params.get('cmd', '').startswith('cddb query')):
            return FakeResponse(query_response)
        if 'cmd=cddb+read' in url or (params and params.get('cmd', '').startswith('cddb read')):
            return FakeResponse(read_response)
        msg = 'Unexpected URL'
        raise RuntimeError(msg)

    mock_session = mocker.MagicMock()
    mock_session.get = mocker.AsyncMock(side_effect=fake_requests_get)
    mock_async_session = mocker.patch('deltona.media.AsyncSession')
    mock_async_session.return_value.__aenter__ = mocker.AsyncMock(return_value=mock_session)
    mock_async_session.return_value.__aexit__ = mocker.AsyncMock(return_value=False)
    result = await cddb_query(disc_id)
    assert result.artist == 'Artist'
    assert result.album == 'Album'
    assert result.year == 2020
    assert result.genre.lower() == 'rock'
    assert result.tracks == ('Track One', 'Track Two')


@pytest.mark.asyncio
async def test_cddb_query_multiple_matches_accept_first(mocker: MockerFixture) -> None:
    cddb_query.cache_clear()
    disc_id = '87654321 3 111 222 333'
    query_response = ("210 Found exact matches, list follows (until terminating `.')\n"
                      'rock 87654321 Artist / Album / 2021 / 3\n'
                      'pop 87654321 Artist2 / Album2 / 2022 / 3\n'
                      '.\n')
    read_response = ("210 Found exact matches, list follows (until terminating `.')\n"
                     'DTITLE=Artist / Album\n'
                     'DYEAR=2021\n'
                     'DGENRE=Rock\n'
                     'TTITLE0=Track A\n'
                     'TTITLE1=Track B\n'
                     'TTITLE2=Track C\n'
                     'OTHER=Some other info\n'
                     '.\n')
    mocker.patch('deltona.media.socket.gethostname', return_value='host')
    mocker.patch('deltona.media.getpass.getuser', return_value='user')
    mocker.patch('keyring.get_password', return_value='host')

    def fake_requests_get(url: str,
                          params: Any = None,
                          timeout: int | None = None,
                          **kwargs: Any) -> Any:
        class FakeResponse:
            def __init__(self, text: str) -> None:
                self.text = text
                self.status_code = 200
                self.ok = True

            def raise_for_status(self) -> None:
                pass

        if 'cmd=cddb+query' in url or (params and params.get('cmd', '').startswith('cddb query')):
            return FakeResponse(query_response)
        if 'cmd=cddb+read' in url or (params and params.get('cmd', '').startswith('cddb read')):
            return FakeResponse(read_response)
        msg = 'Unexpected URL'
        raise RuntimeError(msg)

    mock_session = mocker.MagicMock()
    mock_session.get = mocker.AsyncMock(side_effect=fake_requests_get)
    mock_async_session = mocker.patch('deltona.media.AsyncSession')
    mock_async_session.return_value.__aenter__ = mocker.AsyncMock(return_value=mock_session)
    mock_async_session.return_value.__aexit__ = mocker.AsyncMock(return_value=False)
    result = await cddb_query(disc_id, accept_first_match=True)
    assert result.artist == 'Artist'
    assert result.album == 'Album'
    assert result.year == 2021
    assert result.genre.lower() == 'rock'
    assert result.tracks == ('Track A', 'Track B', 'Track C')


@pytest.mark.asyncio
async def test_cddb_query_multiple_matches_not_accept_first(mocker: MockerFixture) -> None:
    cddb_query.cache_clear()
    disc_id = '87654321 3 111 222 333'
    query_response = ("210 Found exact matches, list follows (until terminating `.')\n"
                      'rock 87654321 Artist / Album / 2021 / 3\n'
                      'pop 87654321 Artist2 / Album2 / 2022 / 3\n'
                      '.\n')
    read_response = ("210 Found exact matches, list follows (until terminating `.')\n"
                     'DTITLE=Artist / Album\n'
                     'DYEAR=2021\n'
                     'DGENRE=Rock\n'
                     'TTITLE0=Track A\n'
                     'TTITLE1=Track B\n'
                     'TTITLE2=Track C\n'
                     '.\n')
    mocker.patch('deltona.media.socket.gethostname', return_value='host')
    mocker.patch('deltona.media.getpass.getuser', return_value='user')
    mocker.patch('keyring.get_password', return_value='host')

    def fake_requests_get(url: str,
                          params: Any = None,
                          timeout: int | None = None,
                          **kwargs: Any) -> Any:
        class FakeResponse:
            def __init__(self, text: str) -> None:
                self.text = text
                self.status_code = 200
                self.ok = True

            def raise_for_status(self) -> None:
                pass

        if 'cmd=cddb+query' in url or (params and params.get('cmd', '').startswith('cddb query')):
            return FakeResponse(query_response)
        if 'cmd=cddb+read' in url or (params and params.get('cmd', '').startswith('cddb read')):
            return FakeResponse(read_response)
        msg = 'Unexpected URL'
        raise RuntimeError(msg)

    mock_session = mocker.MagicMock()
    mock_session.get = mocker.AsyncMock(side_effect=fake_requests_get)
    mock_async_session = mocker.patch('deltona.media.AsyncSession')
    mock_async_session.return_value.__aenter__ = mocker.AsyncMock(return_value=mock_session)
    mock_async_session.return_value.__aexit__ = mocker.AsyncMock(return_value=False)
    with pytest.raises(ValueError, match=r'^\d+'):
        await cddb_query(disc_id)


@pytest.mark.asyncio
async def test_cddb_query_no_match_raises(mocker: MockerFixture) -> None:
    cddb_query.cache_clear()
    disc_id = '00000000 1 0'
    query_response = '202 No match found\n'
    mocker.patch('deltona.media.socket.gethostname', return_value='host')
    mocker.patch('deltona.media.getpass.getuser', return_value='user')
    mocker.patch('keyring.get_password', return_value='host')
    mock_req = mocker.Mock(text=query_response)
    mock_session = mocker.MagicMock()
    mock_session.get = mocker.AsyncMock(return_value=mock_req)
    mock_async_session = mocker.patch('deltona.media.AsyncSession')
    mock_async_session.return_value.__aenter__ = mocker.AsyncMock(return_value=mock_session)
    mock_async_session.return_value.__aexit__ = mocker.AsyncMock(return_value=False)
    with pytest.raises(ValueError, match='202'):
        await cddb_query(disc_id)


@pytest.mark.asyncio
async def test_cddb_query_http_error(mocker: MockerFixture) -> None:
    cddb_query.cache_clear()
    disc_id = '99999999 1 0'
    mocker.patch('deltona.media.socket.gethostname', return_value='host')
    mocker.patch('deltona.media.getpass.getuser', return_value='user')
    mocker.patch('keyring.get_password', return_value='host')
    mock_response = mocker.Mock()
    mock_response.raise_for_status.side_effect = HTTPError
    mock_session = mocker.MagicMock()
    mock_session.get = mocker.AsyncMock(return_value=mock_response)
    mock_async_session = mocker.patch('deltona.media.AsyncSession')
    mock_async_session.return_value.__aenter__ = mocker.AsyncMock(return_value=mock_session)
    mock_async_session.return_value.__aexit__ = mocker.AsyncMock(return_value=False)
    with pytest.raises(HTTPError):
        await cddb_query(disc_id)


def test_hlg_to_sdr_default_args(mocker: MockerFixture, tmp_path: Path) -> None:
    fake_run = mocker.patch('deltona.media.sp.run')
    input_file = tmp_path / 'input.mkv'
    input_file.write_bytes(b'dummy')
    output_file = tmp_path / 'input-sdr.mkv'
    hlg_to_sdr(input_file)
    fake_run.assert_called_once()
    args = fake_run.call_args[0][0]
    assert 'ffmpeg' in args
    assert '-vf' in args
    assert '-c:v' in args
    assert 'libx265' in args
    assert str(output_file) in args


def test_hlg_to_sdr_with_all_args(mocker: MockerFixture, tmp_path: Path) -> None:
    fake_run = mocker.patch('deltona.media.sp.run')
    input_file = tmp_path / 'input.mkv'
    input_file.write_bytes(b'dummy')
    output_file = tmp_path / 'custom.mkv'
    hlg_to_sdr(input_file,
               crf=18,
               output_codec='libx264',
               output_file=output_file,
               input_args=['-threads', '2'],
               output_args=['-map', '0'],
               fast=True,
               delete_after=False)
    args = fake_run.call_args[0][0]
    assert 'ffmpeg' in args
    assert '-threads' in args
    assert '-map' in args
    assert '-vf' in args
    assert 'libx264' in args
    assert str(output_file) in args


def test_hlg_to_sdr_delete_after_true(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.media.sp.run')
    mocker.patch('send2trash.send2trash')
    input_file = tmp_path / 'input.mkv'
    input_file.write_bytes(b'dummy')
    hlg_to_sdr(input_file, delete_after=True)


def test_hlg_to_sdr_raises_on_run_error(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.media.sp.run', side_effect=sp.CalledProcessError(1, 'ffmpeg'))
    input_file = tmp_path / 'input.mkv'
    input_file.write_bytes(b'dummy')
    with pytest.raises(sp.CalledProcessError):
        hlg_to_sdr(input_file)


def test_group_files_single_group(tmp_path: Path) -> None:
    for i in range(3):
        (tmp_path / f'2024051216440{i}_video.mp4').write_bytes(b'data')
    result = group_files(str(f) for f in tmp_path.iterdir())
    assert len(result) == 1
    assert len(result[0]) == 3


def test_group_files_multiple_groups(tmp_path: Path) -> None:
    (tmp_path / '20240512164400_video.mp4').write_bytes(b'data')
    (tmp_path / '20240512174400_video.mp4').write_bytes(b'data')
    result = group_files(str(f) for f in tmp_path.iterdir())
    assert len(result) == 2
    assert len(result[0]) == 1
    assert len(result[1]) == 1


def test_pair_redtiger_dashcam_files_basic(tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    front_dir.mkdir()
    rear_dir.mkdir()
    (front_dir / '20240512164400_000001A.MP4').write_bytes(b'front')
    (front_dir / '20240512164700_000003A.MP4').write_bytes(b'front')
    (rear_dir / '20240512164401_000002B.MP4').write_bytes(b'rear')
    (rear_dir / '20240512164701_000004B.MP4').write_bytes(b'rear')
    pairs = pair_redtiger_dashcam_files(front_dir, rear_dir)
    assert len(pairs) == 2
    assert pairs[0][1].name == '20240512164400_000001A.MP4'
    assert pairs[0][0].name == '20240512164401_000002B.MP4'
    assert pairs[1][1].name == '20240512164700_000003A.MP4'
    assert pairs[1][0].name == '20240512164701_000004B.MP4'


def test_pair_redtiger_dashcam_files_unmatched_front(tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    front_dir.mkdir()
    rear_dir.mkdir()
    (front_dir / '20240512164400_000001A.MP4').write_bytes(b'front')
    (front_dir / '20240512170000_000003A.MP4').write_bytes(b'front')
    (rear_dir / '20240512164401_000002B.MP4').write_bytes(b'rear')
    pairs = pair_redtiger_dashcam_files(front_dir, rear_dir)
    assert len(pairs) == 1
    assert pairs[0][1].name == '20240512164400_000001A.MP4'


def test_pair_redtiger_dashcam_files_unmatched_rear(tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    front_dir.mkdir()
    rear_dir.mkdir()
    (front_dir / '20240512164400_000001A.MP4').write_bytes(b'front')
    (rear_dir / '20240512164401_000002B.MP4').write_bytes(b'rear')
    (rear_dir / '20240512170000_000004B.MP4').write_bytes(b'rear')
    pairs = pair_redtiger_dashcam_files(front_dir, rear_dir)
    assert len(pairs) == 1
    assert pairs[0][0].name == '20240512164401_000002B.MP4'


def test_pair_redtiger_dashcam_files_skips_hidden(tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    front_dir.mkdir()
    rear_dir.mkdir()
    (front_dir / '.hidden.MP4').write_bytes(b'front')
    (rear_dir / '.hidden.MP4').write_bytes(b'rear')
    (front_dir / '20240512164400_000001A.MP4').write_bytes(b'front')
    (rear_dir / '20240512164401_000002B.MP4').write_bytes(b'rear')
    pairs = pair_redtiger_dashcam_files(front_dir, rear_dir)
    assert len(pairs) == 1


def test_pair_redtiger_dashcam_files_zero_offset(tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    front_dir.mkdir()
    rear_dir.mkdir()
    (front_dir / '20240512164400_000001A.MP4').write_bytes(b'front')
    (rear_dir / '20240512164400_000002B.MP4').write_bytes(b'rear')
    pairs = pair_redtiger_dashcam_files(front_dir, rear_dir)
    assert len(pairs) == 1


def test_group_pairs_single_group(tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    front_dir.mkdir()
    rear_dir.mkdir()
    f1 = front_dir / '20240512164400_000001A.MP4'
    f2 = front_dir / '20240512164700_000003A.MP4'
    r1 = rear_dir / '20240512164401_000002B.MP4'
    r2 = rear_dir / '20240512164701_000004B.MP4'
    for f in (f1, f2, r1, r2):
        f.write_bytes(b'data')
    pairs = [(r1.resolve(), f1.resolve()), (r2.resolve(), f2.resolve())]
    groups = group_pairs(pairs, clip_length=3)
    assert len(groups) == 1
    assert len(groups[0]) == 2


def test_group_pairs_multiple_groups(tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    front_dir.mkdir()
    rear_dir.mkdir()
    f1 = front_dir / '20240512164400_000001A.MP4'
    f2 = front_dir / '20240512174400_000003A.MP4'
    r1 = rear_dir / '20240512164401_000002B.MP4'
    r2 = rear_dir / '20240512174401_000004B.MP4'
    for f in (f1, f2, r1, r2):
        f.write_bytes(b'data')
    pairs = [(r1.resolve(), f1.resolve()), (r2.resolve(), f2.resolve())]
    groups = group_pairs(pairs, clip_length=3)
    assert len(groups) == 2
    assert len(groups[0]) == 1
    assert len(groups[1]) == 1


def test_group_pairs_empty() -> None:
    assert group_pairs([]) == []


def test_archive_dashcam_footage_basic_merge(mocker: MockerFixture, tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    rear_dir.mkdir()
    output_dir.mkdir()
    for i in range(3):
        (front_dir / f'2024051216440{i}_00000{2 * i}A.MP4').write_bytes(b'front')
        (rear_dir / f'2024051216440{i}_00000{2 * i + 1}B.MP4').write_bytes(b'rear')
    mock_run = mocker.patch('deltona.media.sp.run')
    mocker.patch('deltona.media.ffprobe', return_value={'format': {'duration': '180.0'}})
    mock_send2trash = mocker.patch('send2trash.send2trash')
    archive_dashcam_footage(front_dir, rear_dir, output_dir, max_offset=1)
    assert mock_run.call_count == 4
    assert mock_send2trash.call_count == 6


def test_archive_dashcam_footage_unmatched_rear_skipped(mocker: MockerFixture,
                                                        tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    rear_dir.mkdir()
    output_dir.mkdir()
    (front_dir / '20240512164400_000001A.MP4').write_bytes(b'front')
    (rear_dir / '20240512164401_000002B.MP4').write_bytes(b'rear')
    (rear_dir / '20240512170000_000004B.MP4').write_bytes(b'rear')  # unmatched
    mock_run = mocker.patch('deltona.media.sp.run')
    mocker.patch('deltona.media.ffprobe', return_value={'format': {'duration': '180.0'}})
    mock_send2trash = mocker.patch('send2trash.send2trash')
    archive_dashcam_footage(front_dir, rear_dir, output_dir)
    # 1 encode + 1 concat = 2 sp.run calls
    assert mock_run.call_count == 2
    # Only the matched pair is sent to trash (2 files)
    assert mock_send2trash.call_count == 2


def test_archive_dashcam_footage_unmatched_front_skipped(mocker: MockerFixture,
                                                         tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    rear_dir.mkdir()
    output_dir.mkdir()
    (front_dir / '20240512164400_000001A.MP4').write_bytes(b'front')
    (front_dir / '20240512170000_000003A.MP4').write_bytes(b'front')  # unmatched
    (rear_dir / '20240512164401_000002B.MP4').write_bytes(b'rear')
    mock_run = mocker.patch('deltona.media.sp.run')
    mocker.patch('deltona.media.ffprobe', return_value={'format': {'duration': '180.0'}})
    mock_send2trash = mocker.patch('send2trash.send2trash')
    archive_dashcam_footage(front_dir, rear_dir, output_dir)
    assert mock_run.call_count == 2
    assert mock_send2trash.call_count == 2


def test_archive_dashcam_footage_no_delete(mocker: MockerFixture, tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    rear_dir.mkdir()
    output_dir.mkdir()
    (front_dir / '20240512164400_000001A.MP4').write_bytes(b'front')
    (rear_dir / '20240512164401_000002B.MP4').write_bytes(b'rear')
    mock_run = mocker.patch('deltona.media.sp.run')
    mocker.patch('deltona.media.ffprobe', return_value={'format': {'duration': '180.0'}})
    mock_send2trash = mocker.patch('send2trash.send2trash')
    archive_dashcam_footage(front_dir, rear_dir, output_dir, no_delete=True)
    assert mock_run.call_count == 2
    assert not mock_send2trash.called


def test_archive_dashcam_footage_crash_deletes_unfinished_files(tmp_path: Path,
                                                                mocker: MockerFixture) -> None:
    mocker.patch('deltona.media.sp.run',
                 side_effect=[None, sp.CalledProcessError(1, 'ffmpeg', stderr=b'')])
    mocker.patch('deltona.media.ffprobe', return_value={'format': {'duration': '180.0'}})
    mocker.patch('send2trash.send2trash')
    mock_unlink = mocker.patch('deltona.media.Path.unlink')
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    rear_dir.mkdir()
    output_dir.mkdir()
    (front_dir / '20240512164400_000001A.MP4').write_bytes(b'front')
    (front_dir / '20240512164401_000003A.MP4').write_bytes(b'front')
    (rear_dir / '20240512164400_000002B.MP4').write_bytes(b'rear')
    (rear_dir / '20240512164401_000004B.MP4').write_bytes(b'rear')
    with pytest.raises(sp.CalledProcessError):
        archive_dashcam_footage(front_dir, rear_dir, output_dir)
    assert mock_unlink.call_count == 1


def test_archive_dashcam_footage_calls_with_correct_args(mocker: MockerFixture,
                                                         tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    rear_dir.mkdir()
    output_dir.mkdir()
    (front_dir / '20240512164400_000001A.MP4').write_bytes(b'front')
    (rear_dir / '20240512164400_000002B.MP4').write_bytes(b'rear')
    mock_run = mocker.patch('deltona.media.sp.run')
    mocker.patch('deltona.media.ffprobe', return_value={'format': {'duration': '180.0'}})
    mock_send2trash = mocker.patch('send2trash.send2trash')
    archive_dashcam_footage(front_dir,
                            rear_dir,
                            output_dir,
                            video_encoder='hevc_nvenc',
                            video_bitrate='2M')
    args = mock_run.call_args_list[0].args[0]
    assert 'hevc_nvenc' in args
    assert '-b:v' in args
    assert '2M' in args
    assert mock_send2trash.called


def test_archive_dashcam_footage_calls_with_correct_args_no_delete(mocker: MockerFixture,
                                                                   tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    rear_dir.mkdir()
    output_dir.mkdir()
    (front_dir / '20240512164400_000001A.MP4').write_bytes(b'front')
    (rear_dir / '20240512164400_000002B.MP4').write_bytes(b'rear')
    mock_run = mocker.patch('deltona.media.sp.run')
    mocker.patch('deltona.media.ffprobe', return_value={'format': {'duration': '180.0'}})
    mock_send2trash = mocker.patch('send2trash.send2trash')
    archive_dashcam_footage(front_dir,
                            rear_dir,
                            output_dir,
                            no_delete=True,
                            video_encoder='hevc_nvenc',
                            video_bitrate='2M')
    args = mock_run.call_args_list[0].args[0]
    assert 'hevc_nvenc' in args
    assert '-b:v' in args
    assert '2M' in args
    assert not mock_send2trash.called


def test_archive_dashcam_footage_skips_hidden_files(mocker: MockerFixture, tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    rear_dir.mkdir()
    output_dir.mkdir()
    (front_dir / '.hidden_front.mp4').write_bytes(b'front')
    (rear_dir / '.hidden_rear.mp4').write_bytes(b'rear')
    (front_dir / '20240512164400_000001A.MP4').write_bytes(b'front')
    (rear_dir / '20240512164401_000002B.MP4').write_bytes(b'rear')
    mock_run = mocker.patch('deltona.media.sp.run')
    mocker.patch('deltona.media.ffprobe', return_value={'format': {'duration': '180.0'}})
    mock_send2trash = mocker.patch('send2trash.send2trash')
    archive_dashcam_footage(front_dir, rear_dir, output_dir)
    assert mock_run.call_count == 2
    assert mock_send2trash.call_count == 2


def test_archive_dashcam_footage_multiple_groups(mocker: MockerFixture, tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    rear_dir.mkdir()
    output_dir.mkdir()
    # Group 1: two pairs
    (front_dir / '20240512164400_000001A.MP4').write_bytes(b'front')
    (rear_dir / '20240512164401_000002B.MP4').write_bytes(b'rear')
    (front_dir / '20240512164700_000003A.MP4').write_bytes(b'front')
    (rear_dir / '20240512164701_000004B.MP4').write_bytes(b'rear')
    # Group 2: one pair (10 hour gap)
    (front_dir / '20240513004400_000005A.MP4').write_bytes(b'front')
    (rear_dir / '20240513004401_000006B.MP4').write_bytes(b'rear')
    # Unmatched rear
    (rear_dir / '20240513100000_000008B.MP4').write_bytes(b'rear')
    mock_run = mocker.patch('deltona.media.sp.run')
    mocker.patch('deltona.media.ffprobe', return_value={'format': {'duration': '180.0'}})
    mock_send2trash = mocker.patch('send2trash.send2trash')
    archive_dashcam_footage(front_dir, rear_dir, output_dir)
    # Group 1: 2 encodes + 1 concat = 3; Group 2: 1 encode + 1 concat = 2; total = 5
    assert mock_run.call_count == 5
    # 3 matched pairs = 6 files trashed
    assert mock_send2trash.call_count == 6


def test_archive_dashcam_footage_chapters_in_concat_args(mocker: MockerFixture,
                                                         tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    rear_dir.mkdir()
    output_dir.mkdir()
    (front_dir / '20240512164400_000001A.MP4').write_bytes(b'front')
    (front_dir / '20240512164700_000003A.MP4').write_bytes(b'front')
    (rear_dir / '20240512164401_000002B.MP4').write_bytes(b'rear')
    (rear_dir / '20240512164701_000004B.MP4').write_bytes(b'rear')
    mock_run = mocker.patch('deltona.media.sp.run')
    mocker.patch('deltona.media.ffprobe', return_value={'format': {'duration': '180.0'}})
    mock_send2trash = mocker.patch('send2trash.send2trash')
    archive_dashcam_footage(front_dir, rear_dir, output_dir)
    # Concat command is the last sp.run call
    concat_args = mock_run.call_args_list[-1].args[0]
    assert '-map_metadata' in concat_args
    assert '1' in concat_args
    assert mock_send2trash.call_count == 4


def test_archive_dashcam_footage_chapters_duration_fallback_to_stream(mocker: MockerFixture,
                                                                      tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    rear_dir.mkdir()
    output_dir.mkdir()
    (front_dir / '20240512164400_000001A.MP4').write_bytes(b'front')
    (rear_dir / '20240512164401_000002B.MP4').write_bytes(b'rear')
    mock_run = mocker.patch('deltona.media.sp.run')
    mocker.patch('deltona.media.ffprobe',
                 return_value={
                     'format': {},
                     'streams': [{
                         'duration': '120.5'
                     }]
                 })
    mocker.patch('send2trash.send2trash')
    archive_dashcam_footage(front_dir, rear_dir, output_dir)
    concat_args = mock_run.call_args_list[-1].args[0]
    assert '-map_metadata' in concat_args


def test_archive_dashcam_footage_chapters_no_setpts(mocker: MockerFixture, tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    rear_dir.mkdir()
    output_dir.mkdir()
    (front_dir / '20240512164400_000001A.MP4').write_bytes(b'front')
    (rear_dir / '20240512164401_000002B.MP4').write_bytes(b'rear')
    mock_run = mocker.patch('deltona.media.sp.run')
    mocker.patch('deltona.media.ffprobe', return_value={'format': {'duration': '180.0'}})
    mocker.patch('send2trash.send2trash')
    archive_dashcam_footage(front_dir, rear_dir, output_dir, setpts=None)
    concat_args = mock_run.call_args_list[-1].args[0]
    assert '-map_metadata' in concat_args


def test_archive_dashcam_footage_chapters_no_duration(mocker: MockerFixture,
                                                      tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    rear_dir.mkdir()
    output_dir.mkdir()
    (front_dir / '20240512164400_000001A.MP4').write_bytes(b'front')
    (rear_dir / '20240512164401_000002B.MP4').write_bytes(b'rear')
    mock_run = mocker.patch('deltona.media.sp.run')
    mocker.patch('deltona.media.ffprobe', return_value={'format': {}, 'streams': [{}]})
    mocker.patch('send2trash.send2trash')
    archive_dashcam_footage(front_dir, rear_dir, output_dir)
    concat_args = mock_run.call_args_list[-1].args[0]
    assert '-map_metadata' in concat_args


def test_archive_dashcam_footage_no_chapters(mocker: MockerFixture, tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    rear_dir.mkdir()
    output_dir.mkdir()
    (front_dir / '20240512164400_000001A.MP4').write_bytes(b'front')
    (rear_dir / '20240512164401_000002B.MP4').write_bytes(b'rear')
    mock_run = mocker.patch('deltona.media.sp.run')
    mocker.patch('deltona.media.ffprobe', return_value={'format': {'duration': '180.0'}})
    mock_send2trash = mocker.patch('send2trash.send2trash')
    archive_dashcam_footage(front_dir, rear_dir, output_dir, chapters=False)
    concat_args = mock_run.call_args_list[-1].args[0]
    assert '-map_metadata' not in concat_args
    assert mock_send2trash.call_count == 2


def test_archive_dashcam_footage_single_camera(mocker: MockerFixture, tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    output_dir.mkdir()
    for i in range(3):
        (front_dir / f'2024051216440{i}_00000{i}A.MP4').write_bytes(b'front')
    mock_run = mocker.patch('deltona.media.sp.run')
    mocker.patch('deltona.media.ffprobe', return_value={'format': {'duration': '180.0'}})
    mock_send2trash = mocker.patch('send2trash.send2trash')
    archive_dashcam_footage(front_dir, None, output_dir)
    # 3 encodes + 1 concat = 4 sp.run calls
    assert mock_run.call_count == 4
    # Only front files trashed (3)
    assert mock_send2trash.call_count == 3
    # Single-camera: no -filter_complex, use -vf for setpts
    first_encode_args = mock_run.call_args_list[0].args[0]
    assert '-filter_complex' not in first_encode_args
    assert '-vf' in first_encode_args


def test_archive_dashcam_footage_single_camera_pair_fn_none_rear_dir_set(
        mocker: MockerFixture, tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    rear_dir.mkdir()
    output_dir.mkdir()
    (front_dir / '20240512164400_000001A.MP4').write_bytes(b'front')
    mock_run = mocker.patch('deltona.media.sp.run')
    mocker.patch('deltona.media.ffprobe', return_value={'format': {'duration': '180.0'}})
    mocker.patch('send2trash.send2trash')
    archive_dashcam_footage(front_dir, rear_dir, output_dir, pair_fn=None)
    first_encode_args = mock_run.call_args_list[0].args[0]
    assert '-filter_complex' not in first_encode_args


def test_archive_dashcam_footage_custom_pair_fn(mocker: MockerFixture, tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    rear_dir.mkdir()
    output_dir.mkdir()
    f1 = front_dir / '20240512164400_000001A.MP4'
    r1 = rear_dir / '20240512164401_000002B.MP4'
    f1.write_bytes(b'front')
    r1.write_bytes(b'rear')
    custom_pair = mocker.Mock(return_value=[(r1.resolve(), f1.resolve())])
    mocker.patch('deltona.media.sp.run')
    mocker.patch('deltona.media.ffprobe', return_value={'format': {'duration': '180.0'}})
    mocker.patch('send2trash.send2trash')
    archive_dashcam_footage(front_dir, rear_dir, output_dir, pair_fn=custom_pair)
    custom_pair.assert_called_once()


def test_archive_dashcam_footage_custom_group_fn(mocker: MockerFixture, tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    rear_dir.mkdir()
    output_dir.mkdir()
    f1 = front_dir / '20240512164400_000001A.MP4'
    r1 = rear_dir / '20240512164401_000002B.MP4'
    f1.write_bytes(b'front')
    r1.write_bytes(b'rear')
    pairs = [(r1.resolve(), f1.resolve())]
    custom_group = mocker.Mock(return_value=[pairs])
    mocker.patch('deltona.media.sp.run')
    mocker.patch('deltona.media.ffprobe', return_value={'format': {'duration': '180.0'}})
    mocker.patch('send2trash.send2trash')
    archive_dashcam_footage(front_dir, rear_dir, output_dir, group_fn=custom_group)
    custom_group.assert_called_once()


def test_archive_dashcam_footage_single_camera_no_setpts(mocker: MockerFixture,
                                                         tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    output_dir.mkdir()
    (front_dir / '20240512164400_000001A.MP4').write_bytes(b'front')
    mock_run = mocker.patch('deltona.media.sp.run')
    mocker.patch('deltona.media.ffprobe', return_value={'format': {'duration': '180.0'}})
    mocker.patch('send2trash.send2trash')
    archive_dashcam_footage(front_dir, None, output_dir, setpts=None)
    first_encode_args = mock_run.call_args_list[0].args[0]
    assert '-filter_complex' not in first_encode_args
    assert '-vf' not in first_encode_args


@pytest.mark.parametrize('ext', ['flac', 'mp3', 'opus'])
def test_add_info_json_to_media_file_flac_mp3_opus(mocker: MockerFixture, tmp_path: Path,
                                                   ext: str) -> None:
    media_file = tmp_path / f'test.{ext}'
    media_file.write_bytes(b'dummy')
    info_json = tmp_path / 'test.info.json'
    info_json.write_text('{"upload_date": "20220101"}')
    mock_run = mocker.patch('deltona.media.sp.run')
    mocker.patch('deltona.media.copyfile')
    mocker.patch('deltona.media.utime')
    mocker.patch('deltona.media.Path.unlink')
    mocker.patch('deltona.media.Path.exists', return_value=True)
    mocker.patch('deltona.media.Path.open',
                 mocker.mock_open(read_data='{"upload_date": "20220101"}'))
    add_info_json_to_media_file(media_file, info_json)
    assert mock_run.called


def test_add_info_json_to_media_file_mp4(mocker: MockerFixture, tmp_path: Path) -> None:
    media_file = tmp_path / 'test.mp4'
    media_file.write_bytes(b'dummy')
    info_json = tmp_path / 'test.info.json'
    info_json.write_text('{"upload_date": "20220101"}')
    mocker.patch('deltona.media.copyfile')
    mock_run = mocker.patch('deltona.media.sp.run')
    mocker.patch('deltona.media.utime')
    mocker.patch('deltona.media.Path.unlink')
    mocker.patch('deltona.media.Path.exists', return_value=True)
    mocker.patch('deltona.media.Path.open',
                 mocker.mock_open(read_data='{"upload_date": "20220101"}'))
    add_info_json_to_media_file(media_file, info_json)
    assert mock_run.called


def test_add_info_json_to_media_file_mkv_ignores_existing(mocker: MockerFixture,
                                                          tmp_path: Path) -> None:
    media_file = tmp_path / 'test.mkv'
    media_file.write_bytes(b'dummy')
    info_json = tmp_path / 'test.info.json'
    info_json.write_text('{"upload_date": "20220101"}')
    mock_run = mocker.patch('deltona.media.sp.run')
    mock_run.return_value.stdout = (
        "Attachment ID 1: type 'application/json', size 123 bytes, file name 'info.json'")
    mocker.patch('deltona.media.utime')
    mocker.patch('deltona.media.Path.unlink')
    mocker.patch('deltona.media.Path.exists', return_value=True)
    mocker.patch('deltona.media.Path.open',
                 mocker.mock_open(read_data='{"upload_date": "20220101"}'))
    add_info_json_to_media_file(media_file, info_json)
    assert mock_run.called


def test_add_info_json_to_media_file_mkv(mocker: MockerFixture, tmp_path: Path) -> None:
    media_file = tmp_path / 'test.mkv'
    media_file.write_bytes(b'dummy')
    info_json = tmp_path / 'test.info.json'
    info_json.write_text('{"upload_date": "20220101"}')
    mock_run = mocker.patch('deltona.media.sp.run')
    mock_run.return_value.stdout = ''
    mock_utime = mocker.patch('deltona.media.utime')
    mocker.patch('deltona.media.Path.unlink')
    mocker.patch('deltona.media.Path.exists', return_value=True)
    mocker.patch('deltona.media.Path.open',
                 mocker.mock_open(read_data='{"upload_date": "20220101"}'))
    add_info_json_to_media_file(media_file, info_json)
    assert mock_run.call_count == 2
    mock_utime.assert_called_once()


def test_add_info_json_to_media_file_json_path_not_exists(mocker: MockerFixture,
                                                          tmp_path: Path) -> None:
    media_file = tmp_path / 'test.flac'
    mocker.patch('deltona.media.Path.exists', return_value=False)
    mock_log = mocker.patch('deltona.media.log')
    add_info_json_to_media_file(media_file)
    mock_log.warning.assert_called_once()


def test_add_info_json_to_media_file_unknown_extension(mocker: MockerFixture,
                                                       tmp_path: Path) -> None:
    media_file = tmp_path / 'test.unknown'
    info_json = tmp_path / 'test.info.json'
    info_json.write_text('{"upload_date": "20220101"}')
    mocker.patch('deltona.media.Path.exists', return_value=True)
    mocker.patch('deltona.media.Path.open',
                 mocker.mock_open(read_data='{"upload_date": "20220101"}'))
    mock_unlink = mocker.patch('deltona.media.Path.unlink')
    add_info_json_to_media_file(media_file, info_json)
    assert not mock_unlink.called


def test_add_info_json_to_media_file_set_date_handles_missing_upload_date(
        mocker: MockerFixture, tmp_path: Path) -> None:
    media_file = tmp_path / 'test.flac'
    info_json = tmp_path / 'test.info.json'
    info_json.write_text('{}')
    mocker.patch('deltona.media.sp.run')
    mocker.patch('deltona.media.copyfile')
    mock_utime = mocker.patch('deltona.media.utime')
    mocker.patch('deltona.media.Path.unlink')
    mocker.patch('deltona.media.Path.exists', return_value=True)
    mocker.patch('deltona.media.Path.open', mocker.mock_open(read_data='{}'))
    add_info_json_to_media_file(media_file, info_json)
    assert not mock_utime.called


def test_add_info_json_to_media_file_set_date_handles_empty_upload_date(
        mocker: MockerFixture, tmp_path: Path) -> None:
    media_file = tmp_path / 'test.flac'
    info_json = tmp_path / 'test.info.json'
    info_json.write_text('{}')
    mocker.patch('deltona.media.sp.run')
    mocker.patch('deltona.media.copyfile')
    mock_utime = mocker.patch('deltona.media.utime')
    mocker.patch('deltona.media.Path.unlink')
    mocker.patch('deltona.media.Path.exists', return_value=True)
    mocker.patch('deltona.media.Path.open', mocker.mock_open(read_data='{"upload_date": ""}'))
    add_info_json_to_media_file(media_file, info_json)
    assert not mock_utime.called


def test_parse_timestamp_success() -> None:
    result = parse_timestamp('20240512164400_000001A.MP4', r'^(\d+)_.*', '%Y%m%d%H%M%S')
    assert result.year == 2024
    assert result.month == 5
    assert result.day == 12
    assert result.hour == 16
    assert result.minute == 44
    assert result.second == 0


def test_parse_timestamp_no_match() -> None:
    with pytest.raises(AssertionError):
        parse_timestamp('no-match-here.MP4', r'^(\d+)_.*', '%Y%m%d%H%M%S')


def test_parse_timestamp_custom_format() -> None:
    result = parse_timestamp('2024-05-12_file.MP4', r'^([\d-]+)_.*', '%Y-%m-%d')
    assert result.year == 2024
    assert result.month == 5
    assert result.day == 12


def test_pair_redtiger_dashcam_files_empty_dirs(tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    front_dir.mkdir()
    rear_dir.mkdir()
    pairs = pair_redtiger_dashcam_files(front_dir, rear_dir)
    assert pairs == []


def test_pair_redtiger_dashcam_files_max_offset_larger(tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    front_dir.mkdir()
    rear_dir.mkdir()
    (front_dir / '20240512164400_000001A.MP4').write_bytes(b'front')
    (rear_dir / '20240512164403_000002B.MP4').write_bytes(b'rear')
    # Default max_offset=1 should not pair these (3 second gap)
    pairs_default = pair_redtiger_dashcam_files(front_dir, rear_dir, max_offset=1)
    assert len(pairs_default) == 0
    # max_offset=5 should pair them
    pairs_wide = pair_redtiger_dashcam_files(front_dir, rear_dir, max_offset=5)
    assert len(pairs_wide) == 1


def test_pair_redtiger_dashcam_files_picks_closest_rear(tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    front_dir.mkdir()
    rear_dir.mkdir()
    (front_dir / '20240512164400_000001A.MP4').write_bytes(b'front')
    (rear_dir / '20240512164358_000002B.MP4').write_bytes(b'rear')
    (rear_dir / '20240512164400_000003B.MP4').write_bytes(b'rear')
    pairs = pair_redtiger_dashcam_files(front_dir, rear_dir, max_offset=3)
    assert len(pairs) == 1
    assert pairs[0][0].name == '20240512164400_000003B.MP4'


def test_group_pairs_boundary_at_clip_length(tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    front_dir.mkdir()
    rear_dir.mkdir()
    # Exactly 3 minute gap (clip_length=3), should NOT start a new group
    f1 = front_dir / '20240512164400_000001A.MP4'
    f2 = front_dir / '20240512164700_000003A.MP4'
    r1 = rear_dir / '20240512164400_000002B.MP4'
    r2 = rear_dir / '20240512164700_000004B.MP4'
    for f in (f1, f2, r1, r2):
        f.write_bytes(b'data')
    pairs = [(r1.resolve(), f1.resolve()), (r2.resolve(), f2.resolve())]
    groups = group_pairs(pairs, clip_length=3)
    assert len(groups) == 1


def test_group_pairs_just_over_clip_length(tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    front_dir.mkdir()
    rear_dir.mkdir()
    # 4 minute gap with clip_length=3 should start new group
    f1 = front_dir / '20240512164400_000001A.MP4'
    f2 = front_dir / '20240512164800_000003A.MP4'
    r1 = rear_dir / '20240512164400_000002B.MP4'
    r2 = rear_dir / '20240512164800_000004B.MP4'
    for f in (f1, f2, r1, r2):
        f.write_bytes(b'data')
    pairs = [(r1.resolve(), f1.resolve()), (r2.resolve(), f2.resolve())]
    groups = group_pairs(pairs, clip_length=3)
    assert len(groups) == 2


def test_group_pairs_single_pair(tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    front_dir.mkdir()
    rear_dir.mkdir()
    f1 = front_dir / '20240512164400_000001A.MP4'
    r1 = rear_dir / '20240512164400_000002B.MP4'
    f1.write_bytes(b'data')
    r1.write_bytes(b'data')
    pairs = [(r1.resolve(), f1.resolve())]
    groups = group_pairs(pairs)
    assert len(groups) == 1
    assert len(groups[0]) == 1


def test_archive_dashcam_footage_overwrite_flag(mocker: MockerFixture, tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    rear_dir.mkdir()
    output_dir.mkdir()
    (front_dir / '20240512164400_000001A.MP4').write_bytes(b'front')
    (rear_dir / '20240512164401_000002B.MP4').write_bytes(b'rear')
    mock_run = mocker.patch('deltona.media.sp.run')
    mocker.patch('deltona.media.ffprobe', return_value={'format': {'duration': '180.0'}})
    mocker.patch('send2trash.send2trash')
    archive_dashcam_footage(front_dir, rear_dir, output_dir, overwrite=True)
    first_call_args = mock_run.call_args_list[0].args[0]
    assert '-y' in first_call_args


def test_archive_dashcam_footage_no_hwaccel(mocker: MockerFixture, tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    rear_dir.mkdir()
    output_dir.mkdir()
    (front_dir / '20240512164400_000001A.MP4').write_bytes(b'front')
    (rear_dir / '20240512164401_000002B.MP4').write_bytes(b'rear')
    mock_run = mocker.patch('deltona.media.sp.run')
    mocker.patch('deltona.media.ffprobe', return_value={'format': {'duration': '180.0'}})
    mocker.patch('send2trash.send2trash')
    archive_dashcam_footage(front_dir, rear_dir, output_dir, hwaccel=None, video_decoder=None)
    first_call_args = mock_run.call_args_list[0].args[0]
    assert '-hwaccel' not in first_call_args


def test_archive_dashcam_footage_no_setpts(mocker: MockerFixture, tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    rear_dir.mkdir()
    output_dir.mkdir()
    (front_dir / '20240512164400_000001A.MP4').write_bytes(b'front')
    (rear_dir / '20240512164401_000002B.MP4').write_bytes(b'rear')
    mock_run = mocker.patch('deltona.media.sp.run')
    mocker.patch('deltona.media.ffprobe', return_value={'format': {'duration': '180.0'}})
    mocker.patch('send2trash.send2trash')
    archive_dashcam_footage(front_dir, rear_dir, output_dir, setpts=None)
    first_call_args = mock_run.call_args_list[0].args[0]
    assert 'setpts' not in ' '.join(first_call_args)


def test_archive_dashcam_footage_no_rear_crop(mocker: MockerFixture, tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    rear_dir.mkdir()
    output_dir.mkdir()
    (front_dir / '20240512164400_000001A.MP4').write_bytes(b'front')
    (rear_dir / '20240512164401_000002B.MP4').write_bytes(b'rear')
    mock_run = mocker.patch('deltona.media.sp.run')
    mocker.patch('deltona.media.ffprobe', return_value={'format': {'duration': '180.0'}})
    mocker.patch('send2trash.send2trash')
    archive_dashcam_footage(front_dir, rear_dir, output_dir, rear_crop=None)
    first_call_args = mock_run.call_args_list[0].args[0]
    assert 'crop=' not in ' '.join(first_call_args)


def test_archive_dashcam_footage_output_file_rename_on_conflict(mocker: MockerFixture,
                                                                tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    rear_dir.mkdir()
    output_dir.mkdir()
    (front_dir / '20240512164400_000001A.MP4').write_bytes(b'front')
    (rear_dir / '20240512164401_000002B.MP4').write_bytes(b'rear')
    # Pre-create the output file so the rename logic triggers
    (output_dir / '20240512164400_000001A.mkv').write_bytes(b'existing')
    mock_run = mocker.patch('deltona.media.sp.run')
    mocker.patch('deltona.media.ffprobe', return_value={'format': {'duration': '180.0'}})
    mocker.patch('send2trash.send2trash')
    archive_dashcam_footage(front_dir, rear_dir, output_dir, overwrite=False)
    # The concat command should use a renamed output path
    concat_call_args = mock_run.call_args_list[-1].args[0]
    output_path_str = concat_call_args[-1]
    assert '-0001' in output_path_str


def test_archive_dashcam_footage_creates_output_dir(mocker: MockerFixture, tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output' / 'nested'
    front_dir.mkdir()
    rear_dir.mkdir()
    (front_dir / '20240512164400_000001A.MP4').write_bytes(b'front')
    (rear_dir / '20240512164401_000002B.MP4').write_bytes(b'rear')
    mocker.patch('deltona.media.sp.run')
    mocker.patch('deltona.media.ffprobe', return_value={'format': {'duration': '180.0'}})
    mocker.patch('send2trash.send2trash')
    archive_dashcam_footage(front_dir, rear_dir, output_dir)
    assert output_dir.exists()
