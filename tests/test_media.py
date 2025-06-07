from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any
import subprocess as sp

from deltona.media import (
    add_info_json_to_media_file,
    archive_dashcam_footage,
    cddb_query,
    create_static_text_video,
    ffprobe,
    get_cd_disc_id,
    get_info_json,
    hlg_to_sdr,
    is_audio_input_format_supported,
    rip_cdda_to_flac,
    supported_audio_input_formats,
)
import pytest
import requests

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from pytest_mock import MockerFixture
    from requests_mock import Mocker


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
    assert result['format']['tags']['title'] == 'Test'  # type: ignore[typeddict-item]


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


def test_get_cd_disc_id_linux_success(mocker: MockerFixture) -> None:
    mocker.patch('deltona.media.IS_LINUX', True)  # noqa: FBT003
    fake_fd = 42
    mocker.patch('deltona.media.ctypes.byref')
    mock_context = mocker.patch('deltona.media.context_os_open')
    mock_context.return_value.__enter__.return_value = fake_fd

    fake_libc = mocker.Mock()
    fake_libc.ioctl.side_effect = [0] + [0] * 4  # header + 3 tracks + leadout
    mocker.patch('deltona.media.ctypes.CDLL', return_value=fake_libc)
    header = mocker.patch('deltona.media.CDROMTOCHeader', autospec=True)
    header_instance = header.return_value
    header_instance.cdth_trk1 = 3
    entry = mocker.patch('deltona.media.CDROMTOCEntry', autospec=True)

    def lba_side_effect() -> Iterator[Any]:
        for lba in (100, 200, 300):
            e = mocker.Mock()
            e.cdte_addr.lba = lba
            yield e
        e = mocker.Mock()
        e.cdte_addr.lba = 400
        yield e

    lba_iter = lba_side_effect()
    entry.side_effect = lambda: next(lba_iter)
    mocker.patch('deltona.media.CDROM_LEADOUT', 0xAA)
    mocker.patch('deltona.media.CDROM_LBA', 1)
    mocker.patch('deltona.media.CD_MSF_OFFSET', 150)
    mocker.patch('deltona.media.CD_FRAMES', 75)
    disc_id = get_cd_disc_id('/dev/cdrom')
    assert disc_id == '0d000403 3 250 350 450 7'


def test_get_cd_disc_id_linux_toc_entry_fail_1(mocker: MockerFixture) -> None:
    mocker.patch('deltona.media.IS_LINUX', True)  # noqa: FBT003
    fake_fd = 42
    mocker.patch('deltona.media.ctypes.byref')
    mock_context = mocker.patch('deltona.media.context_os_open')
    mock_context.return_value.__enter__.return_value = fake_fd

    fake_libc = mocker.Mock()
    fake_libc.ioctl.side_effect = [0, -1]
    mocker.patch('deltona.media.ctypes.CDLL', return_value=fake_libc)
    header = mocker.patch('deltona.media.CDROMTOCHeader', autospec=True)
    header_instance = header.return_value
    header_instance.cdth_trk1 = 3
    entry = mocker.patch('deltona.media.CDROMTOCEntry', autospec=True)

    def lba_side_effect() -> Iterator[Any]:
        for lba in (100, 200, 300):
            e = mocker.Mock()
            e.cdte_addr.lba = lba
            yield e
        e = mocker.Mock()
        e.cdte_addr.lba = 400
        yield e

    lba_iter = lba_side_effect()
    entry.side_effect = lambda: next(lba_iter)
    mocker.patch('deltona.media.CDROM_LEADOUT', 0xAA)
    mocker.patch('deltona.media.CDROM_LBA', 1)
    mocker.patch('deltona.media.CD_MSF_OFFSET', 150)
    mocker.patch('deltona.media.CD_FRAMES', 75)
    with pytest.raises(OSError, match=r'^\d+'):
        get_cd_disc_id('/dev/cdrom')


def test_get_cd_disc_id_linux_toc_entry_fail_2(mocker: MockerFixture) -> None:
    mocker.patch('deltona.media.IS_LINUX', True)  # noqa: FBT003
    fake_fd = 42
    mocker.patch('deltona.media.ctypes.byref')
    mock_context = mocker.patch('deltona.media.context_os_open')
    mock_context.return_value.__enter__.return_value = fake_fd

    fake_libc = mocker.Mock()
    fake_libc.ioctl.side_effect = [0, 0, 0, 0, -1]
    mocker.patch('deltona.media.ctypes.CDLL', return_value=fake_libc)
    header = mocker.patch('deltona.media.CDROMTOCHeader', autospec=True)
    header_instance = header.return_value
    header_instance.cdth_trk1 = 3
    entry = mocker.patch('deltona.media.CDROMTOCEntry', autospec=True)

    def lba_side_effect() -> Iterator[Any]:
        for lba in (100, 200, 300):
            e = mocker.Mock()
            e.cdte_addr.lba = lba
            yield e
        e = mocker.Mock()
        e.cdte_addr.lba = 400
        yield e

    lba_iter = lba_side_effect()
    entry.side_effect = lambda: next(lba_iter)
    mocker.patch('deltona.media.CDROM_LEADOUT', 0xAA)
    mocker.patch('deltona.media.CDROM_LBA', 1)
    mocker.patch('deltona.media.CD_MSF_OFFSET', 150)
    mocker.patch('deltona.media.CD_FRAMES', 75)
    with pytest.raises(OSError, match=r'^\d+'):
        get_cd_disc_id('/dev/cdrom')


def test_get_cd_disc_id_not_linux(mocker: MockerFixture) -> None:
    mocker.patch('deltona.media.IS_LINUX', False)  # noqa: FBT003
    with pytest.raises(NotImplementedError):
        get_cd_disc_id('/dev/cdrom')


def test_get_cd_disc_id_ioctl_header_error(mocker: MockerFixture) -> None:
    mocker.patch('deltona.media.ctypes.byref')
    mocker.patch('deltona.media.IS_LINUX', True)  # noqa: FBT003
    mocker.patch('deltona.media.context_os_open').return_value.__enter__.return_value = 42
    fake_libc = mocker.Mock()
    fake_libc.ioctl.side_effect = [-1]
    mocker.patch('deltona.media.ctypes.CDLL', return_value=fake_libc)
    mocker.patch('deltona.media.CDROMTOCHeader', autospec=True)
    with pytest.raises(OSError, match=r'^\d+'):
        get_cd_disc_id('/dev/cdrom')


def test_cddb_query_no_username(mocker: MockerFixture) -> None:
    disc_id = '12345678 1 123 456 789'
    mocker.patch('deltona.media.socket.gethostname', return_value='host')
    mocker.patch('deltona.media.getpass.getuser', return_value=None)
    mocker.patch('deltona.media.keyring.get_password', return_value='host')
    with pytest.raises(ValueError):  # noqa: PT011
        cddb_query(disc_id)


def test_cddb_query_no_host(mocker: MockerFixture) -> None:
    disc_id = '12345678 1 123 456 789'
    mocker.patch('deltona.media.socket.gethostname', return_value='host')
    mocker.patch('deltona.media.getpass.getuser', return_value='username')
    mocker.patch('deltona.media.keyring.get_password', return_value=None)
    with pytest.raises(ValueError):  # noqa: PT011
        cddb_query(disc_id)


def test_cddb_query_success_single_match(mocker: MockerFixture) -> None:
    disc_id = '12345678 2 123 456 789'
    query_response = ('200 rock 12345678 Artist / Album / 2020 / 2\n')
    read_response = ("210 Found exact matches, list follows (until terminating `.')\n"
                     "DTITLE=Artist / Album\n"
                     "DYEAR=2020\n"
                     "DGENRE=Rock\n"
                     "TTITLE0=Track One\n"
                     "TTITLE1=Track Two\n"
                     ".\n")
    mocker.patch('deltona.media.socket.gethostname', return_value='host')
    mocker.patch('deltona.media.getpass.getuser', return_value='user')
    mocker.patch('deltona.media.keyring.get_password', return_value='host')

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

    mocker.patch('deltona.media.requests.get', side_effect=fake_requests_get)
    result = cddb_query(disc_id)
    assert result.artist == 'Artist'
    assert result.album == 'Album'
    assert result.year == 2020
    assert result.genre.lower() == 'rock'
    assert result.tracks == ('Track One', 'Track Two')


def test_cddb_query_multiple_matches_accept_first(mocker: MockerFixture,
                                                  requests_mock: Mocker) -> None:
    disc_id = '87654321 3 111 222 333'
    query_response = ("210 Found exact matches, list follows (until terminating `.')\n"
                      "rock 87654321 Artist / Album / 2021 / 3\n"
                      "pop 87654321 Artist2 / Album2 / 2022 / 3\n"
                      ".\n")
    read_response = ("210 Found exact matches, list follows (until terminating `.')\n"
                     "DTITLE=Artist / Album\n"
                     "DYEAR=2021\n"
                     "DGENRE=Rock\n"
                     "TTITLE0=Track A\n"
                     "TTITLE1=Track B\n"
                     "TTITLE2=Track C\n"
                     "OTHER=Some other info\n"
                     ".\n")
    mocker.patch('deltona.media.socket.gethostname', return_value='host')
    mocker.patch('deltona.media.getpass.getuser', return_value='user')
    mocker.patch('deltona.media.keyring.get_password', return_value='host')

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

    mocker.patch('deltona.media.requests.get', side_effect=fake_requests_get)
    result = cddb_query(disc_id, accept_first_match=True)
    assert result.artist == 'Artist'
    assert result.album == 'Album'
    assert result.year == 2021
    assert result.genre.lower() == 'rock'
    assert result.tracks == ('Track A', 'Track B', 'Track C')


def test_cddb_query_multiple_matches_not_accept_first(mocker: MockerFixture,
                                                      requests_mock: Mocker) -> None:
    disc_id = '87654321 3 111 222 333'
    query_response = ("210 Found exact matches, list follows (until terminating `.')\n"
                      "rock 87654321 Artist / Album / 2021 / 3\n"
                      "pop 87654321 Artist2 / Album2 / 2022 / 3\n"
                      ".\n")
    read_response = ("210 Found exact matches, list follows (until terminating `.')\n"
                     "DTITLE=Artist / Album\n"
                     "DYEAR=2021\n"
                     "DGENRE=Rock\n"
                     "TTITLE0=Track A\n"
                     "TTITLE1=Track B\n"
                     "TTITLE2=Track C\n"
                     ".\n")
    mocker.patch('deltona.media.socket.gethostname', return_value='host')
    mocker.patch('deltona.media.getpass.getuser', return_value='user')
    mocker.patch('deltona.media.keyring.get_password', return_value='host')

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

    mocker.patch('deltona.media.requests.get', side_effect=fake_requests_get)
    with pytest.raises(ValueError, match=r'^\d+'):
        cddb_query(disc_id)


def test_cddb_query_no_match_raises(mocker: MockerFixture) -> None:
    disc_id = '00000000 1 0'
    query_response = '202 No match found\n'
    mocker.patch('deltona.media.socket.gethostname', return_value='host')
    mocker.patch('deltona.media.getpass.getuser', return_value='user')
    mocker.patch('deltona.media.keyring.get_password', return_value='host')
    mock_req = mocker.Mock(text=query_response)
    mocker.patch('deltona.media.requests.get', return_value=mock_req)
    with pytest.raises(ValueError, match='202'):
        cddb_query(disc_id)


def test_cddb_query_http_error(mocker: MockerFixture) -> None:
    disc_id = '99999999 1 0'
    mocker.patch('deltona.media.socket.gethostname', return_value='host')
    mocker.patch('deltona.media.getpass.getuser', return_value='user')
    mocker.patch('deltona.media.keyring.get_password', return_value='host')
    mock_get = mocker.patch('deltona.media.requests.get')
    mock_get.return_value.raise_for_status.side_effect = requests.HTTPError
    with pytest.raises(requests.HTTPError):
        cddb_query(disc_id)


def test_rip_cdda_to_flac_creates_album_dir_and_flac_files(mocker: MockerFixture,
                                                           tmp_path: Path) -> None:
    # Setup mocks
    fake_cddb_result = mocker.Mock()
    fake_cddb_result.artist = 'TestArtist'
    fake_cddb_result.album = 'TestAlbum'
    fake_cddb_result.year = 2023
    fake_cddb_result.tracks = ('Track1', 'Track2')
    mocker.patch('deltona.media.cddb_query', return_value=fake_cddb_result)
    mocker.patch('deltona.media.get_cd_disc_id', return_value='fake_disc_id')
    mocker.patch('deltona.media.sp.run')
    mock_popen = mocker.patch('deltona.media.sp.Popen')
    mock_popen.return_value.wait.return_value = 0
    album_dir = tmp_path / 'TestArtist-TestAlbum-2023'
    # Call function
    rip_cdda_to_flac(drive='/dev/cdrom', output_dir=tmp_path, stderr_callback=None, username='user')
    # Album dir should be created
    assert album_dir.exists()
    # Should call cdparanoia and flac for each track
    calls = [call[0][0] for call in mock_popen.call_args_list]
    assert any('cdparanoia' in str(args) for args in calls)
    assert any('flac' in str(args) for args in calls)
    # Should be called for each track
    assert sum('cdparanoia' in str(args) for args in calls) == len(fake_cddb_result.tracks)
    assert sum('flac' in str(args) for args in calls) == len(fake_cddb_result.tracks)


def test_rip_cdda_to_flac_album_artist_override(mocker: MockerFixture, tmp_path: Path) -> None:
    fake_cddb_result = mocker.Mock()
    fake_cddb_result.artist = 'WrongArtist'
    fake_cddb_result.album = 'Album'
    fake_cddb_result.year = 2022
    fake_cddb_result.tracks = ('T1',)
    mocker.patch('deltona.media.cddb_query', return_value=fake_cddb_result)
    mocker.patch('deltona.media.get_cd_disc_id', return_value='fake_disc_id')
    mocker.patch('deltona.media.sp.Popen').return_value.wait.return_value = 0
    mocker.patch('deltona.media.sp.run')
    album_dir = tmp_path / 'Override-Album-2022'
    rip_cdda_to_flac(drive='/dev/cdrom',
                     output_dir=tmp_path,
                     album_artist='Override',
                     stderr_callback=None,
                     username='user')
    assert album_dir.exists()


def test_rip_cdda_to_flac_calls_stderr_callback(mocker: MockerFixture, tmp_path: Path) -> None:
    fake_cddb_result = mocker.Mock()
    fake_cddb_result.artist = 'A'
    fake_cddb_result.album = 'B'
    fake_cddb_result.year = 2021
    fake_cddb_result.tracks = ('T1',)
    mocker.patch('deltona.media.cddb_query', return_value=fake_cddb_result)
    mocker.patch('deltona.media.get_cd_disc_id', return_value='fake_disc_id')
    mocker.patch('deltona.media.sp.run')
    mock_proc = mocker.Mock()
    mock_proc.stderr = mocker.Mock()
    mock_proc.stderr.readline.side_effect = ['progress line\n', '\n']
    mock_proc.stderr.readable.side_effect = [True, True, False]
    mocker.patch('deltona.media.sp.Popen', return_value=mock_proc)
    cb = mocker.Mock()
    rip_cdda_to_flac(drive='/dev/cdrom', output_dir=tmp_path, stderr_callback=cb, username='user')
    cb.assert_any_call('progress line')


def test_rip_cdda_to_flac_raises_on_cdparanoia_failure(mocker: MockerFixture,
                                                       tmp_path: Path) -> None:
    fake_cddb_result = mocker.Mock()
    fake_cddb_result.artist = 'A'
    fake_cddb_result.album = 'B'
    fake_cddb_result.year = 2021
    fake_cddb_result.tracks = ('T1',)
    mocker.patch('deltona.media.cddb_query', return_value=fake_cddb_result)
    mocker.patch('deltona.media.get_cd_disc_id', return_value='fake_disc_id')
    mocker.patch('deltona.media.sp.Popen').return_value.wait.return_value = 1
    with pytest.raises(sp.CalledProcessError):
        rip_cdda_to_flac(drive='/dev/cdrom', output_dir=tmp_path, username='user')


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
    hlg_to_sdr(
        input_file,
        crf=18,
        output_codec='libx264',
        output_file=output_file,
        input_args=['-threads', '2'],
        output_args=['-map', '0'],
        fast=True,
        delete_after=False,
    )
    args = fake_run.call_args[0][0]
    assert 'ffmpeg' in args
    assert '-threads' in args
    assert '-map' in args
    assert '-vf' in args
    assert 'libx264' in args
    assert str(output_file) in args


def test_hlg_to_sdr_delete_after_true(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.media.sp.run')
    mocker.patch('deltona.media.send2trash')
    input_file = tmp_path / 'input.mkv'
    input_file.write_bytes(b'dummy')
    hlg_to_sdr(input_file, delete_after=True)


def test_hlg_to_sdr_raises_on_run_error(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.media.sp.run', side_effect=sp.CalledProcessError(1, 'ffmpeg'))
    input_file = tmp_path / 'input.mkv'
    input_file.write_bytes(b'dummy')
    with pytest.raises(sp.CalledProcessError):
        hlg_to_sdr(input_file)


def test_archive_dashcam_footage_basic_merge(mocker: MockerFixture, tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    rear_dir.mkdir()
    output_dir.mkdir()
    for i in range(3):
        (front_dir / f'2024051216440{i}_front.mp4').write_bytes(b'front')
        (rear_dir / f'2024051216440{i}_rear.mp4').write_bytes(b'rear')
    mock_run = mocker.patch('deltona.media.sp.run')
    mock_send2trash = mocker.patch('deltona.media.send2trash')
    archive_dashcam_footage(front_dir, rear_dir, output_dir)
    assert mock_run.call_count == 4
    assert mock_send2trash.call_count == 6


def test_archive_dashcam_footage_group_discrepancy_resolution(mocker: MockerFixture,
                                                              tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    rear_dir.mkdir()
    output_dir.mkdir()
    for i in range(2):
        (front_dir / f'2024051216440{i}_front.mp4').write_bytes(b'front')
        (rear_dir / f'2024051216440{i}_rear.mp4').write_bytes(b'rear')
    (rear_dir / '20240612164401_rear.mp4').write_bytes(b'rear')  # extra rear file
    mock_run = mocker.patch('deltona.media.sp.run')
    mock_send2trash = mocker.patch('deltona.media.send2trash')
    archive_dashcam_footage(front_dir,
                            rear_dir,
                            output_dir,
                            allow_group_discrepancy_resolution=True)
    assert mock_run.call_count == 3
    assert mock_send2trash.call_count == 4


def test_archive_dashcam_footage_group_discrepancy_raises(tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    rear_dir.mkdir()
    output_dir.mkdir()
    (front_dir / '20240512164400_front.mp4').write_bytes(b'front')
    (rear_dir / '20240512164400_rear.mp4').write_bytes(b'rear')
    (rear_dir / '20240512164401_rear.mp4').write_bytes(b'rear')
    with pytest.raises(ValueError, match=r'\d+'):
        archive_dashcam_footage(front_dir,
                                rear_dir,
                                output_dir,
                                allow_group_discrepancy_resolution=False)


def test_archive_dashcam_footage_group_discrepancy_raises_2(tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    rear_dir.mkdir()
    output_dir.mkdir()
    (front_dir / '20240512164400_front.mp4').write_bytes(b'front')
    (rear_dir / '20240512164400_rear.mp4').write_bytes(b'rear')
    (rear_dir / '20240515164401_rear.mp4').write_bytes(b'rear')
    with pytest.raises(ValueError, match=r'\d+'):
        archive_dashcam_footage(front_dir,
                                rear_dir,
                                output_dir,
                                allow_group_discrepancy_resolution=False)


def test_archive_dashcam_footage_group_discrepancy_unresolved(tmp_path: Path) -> None:
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    rear_dir.mkdir()
    output_dir.mkdir()
    (front_dir / '20240512164400_front.mp4').write_bytes(b'front')
    (rear_dir / '20240512164400_rear.mp4').write_bytes(b'rear')
    (rear_dir / '20240515164401_rear.mp4').write_bytes(b'rear')
    with pytest.raises(ValueError, match=r'\d+'):
        archive_dashcam_footage(front_dir, rear_dir, output_dir)


def test_archive_dashcam_footage_group_discrepancy_solving_bg_len_gt(tmp_path: Path,
                                                                     mocker: MockerFixture) -> None:
    mocker.patch('deltona.media.sp.run')
    mock_trash = mocker.patch('deltona.media.send2trash')
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    rear_dir.mkdir()
    output_dir.mkdir()
    last = (rear_dir / '20240512164400_rear.mp4')
    (front_dir / '20240512164400_front.mp4').write_bytes(b'front')
    (rear_dir / '20240512164401_rear.mp4').write_bytes(b'rear')
    last.write_bytes(b'rear')
    archive_dashcam_footage(front_dir, rear_dir, output_dir)
    mock_trash.assert_has_calls([mocker.call(last)])


def test_archive_dashcam_footage_group_discrepancy_solving_bg_len_gt_no_delete(
        tmp_path: Path, mocker: MockerFixture) -> None:
    mocker.patch('deltona.media.sp.run')
    mock_trash = mocker.patch('deltona.media.send2trash')
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    rear_dir.mkdir()
    output_dir.mkdir()
    last = (rear_dir / '20240512164400_rear.mp4')
    (front_dir / '20240512164400_front.mp4').write_bytes(b'front')
    (rear_dir / '20240512164401_rear.mp4').write_bytes(b'rear')
    last.write_bytes(b'rear')
    archive_dashcam_footage(front_dir, rear_dir, output_dir, no_delete=True)
    mock_trash.assert_not_called()


def test_archive_dashcam_footage_group_discrepancy_solving_fg_len_gt(tmp_path: Path,
                                                                     mocker: MockerFixture) -> None:
    mocker.patch('deltona.media.sp.run')
    mock_trash = mocker.patch('deltona.media.send2trash')
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    rear_dir.mkdir()
    output_dir.mkdir()
    last = (front_dir / '20240512164400_rear.mp4')
    (rear_dir / '20240512164400_front.mp4').write_bytes(b'front')
    (front_dir / '20240512164401_rear.mp4').write_bytes(b'rear')
    (output_dir / '20240512164400_rear.mkv').touch()
    last.write_bytes(b'rear')
    archive_dashcam_footage(front_dir, rear_dir, output_dir)
    mock_trash.assert_has_calls([mocker.call(last)])


def test_archive_dashcam_footage_group_discrepancy_solving_fg_len_gt_no_delete(
        tmp_path: Path, mocker: MockerFixture) -> None:
    mocker.patch('deltona.media.sp.run')
    mock_trash = mocker.patch('deltona.media.send2trash')
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    rear_dir.mkdir()
    output_dir.mkdir()
    last = (front_dir / '20240512164400_rear.mp4')
    (rear_dir / '20240512164400_front.mp4').write_bytes(b'front')
    (front_dir / '20240512164401_rear.mp4').write_bytes(b'rear')
    (output_dir / '20240512164400_rear.mkv').touch()
    last.write_bytes(b'rear')
    archive_dashcam_footage(front_dir, rear_dir, output_dir, no_delete=True)
    mock_trash.assert_not_called()


def test_archive_dashcam_footage_group_discrepancy_solving_ignores_extra(
        tmp_path: Path, mocker: MockerFixture) -> None:
    mocker.patch('deltona.media.sp.run')
    mock_trash = mocker.patch('deltona.media.send2trash')
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    rear_dir.mkdir()
    output_dir.mkdir()
    last = (front_dir / '20240512164400_rear.mp4')
    (rear_dir / '20240512164400_front.mp4').write_bytes(b'front')
    (front_dir / '20240512164401_rear.mp4').write_bytes(b'rear')
    (front_dir / '20240512164402_rear.mp4').write_bytes(b'rear')
    last.write_bytes(b'rear')
    archive_dashcam_footage(front_dir, rear_dir, output_dir, overwrite=True)
    assert mock_trash.call_count == 2


def test_archive_dashcam_footage_group_discrepancy_solving_ignores_extra_no_delete(
        tmp_path: Path, mocker: MockerFixture) -> None:
    mocker.patch('deltona.media.sp.run')
    mock_trash = mocker.patch('deltona.media.send2trash')
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    rear_dir.mkdir()
    output_dir.mkdir()
    last = (front_dir / '20240512164400_rear.mp4')
    (rear_dir / '20240512164400_front.mp4').write_bytes(b'front')
    (front_dir / '20240512164401_rear.mp4').write_bytes(b'rear')
    (front_dir / '20240512164402_rear.mp4').write_bytes(b'rear')
    last.write_bytes(b'rear')
    archive_dashcam_footage(front_dir, rear_dir, output_dir, overwrite=True, no_delete=True)
    assert mock_trash.call_count == 0


def test_archive_dashcam_footage_crash_deletes_unfinished_files(tmp_path: Path,
                                                                mocker: MockerFixture) -> None:
    mocker.patch('deltona.media.sp.run',
                 side_effect=[None, sp.CalledProcessError(1, 'ffmpeg', stderr=b'')])
    mocker.patch('deltona.media.send2trash')
    mock_unlink = mocker.patch('deltona.media.Path.unlink')
    front_dir = tmp_path / 'front'
    rear_dir = tmp_path / 'rear'
    output_dir = tmp_path / 'output'
    front_dir.mkdir()
    rear_dir.mkdir()
    output_dir.mkdir()
    (rear_dir / '20240512164400_rear.mp4').write_bytes(b'rear')
    (rear_dir / '20240512164401_rear.mp4').write_bytes(b'rear')
    (front_dir / '20240512164400_front.mp4').write_bytes(b'front')
    (front_dir / '20240512164401_front.mp4').write_bytes(b'front')
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
    (front_dir / '0_front.mp4').write_bytes(b'front')
    (rear_dir / '0_rear.mp4').write_bytes(b'rear')
    mock_run = mocker.patch('deltona.media.sp.run')
    mock_send2trash = mocker.patch('deltona.media.send2trash')
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
    (front_dir / '0_front.mp4').write_bytes(b'front')
    (rear_dir / '0_rear.mp4').write_bytes(b'rear')
    mock_run = mocker.patch('deltona.media.sp.run')
    mock_send2trash = mocker.patch('deltona.media.send2trash')
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
    (front_dir / '0_front.mp4').write_bytes(b'front')
    (rear_dir / '0_rear.mp4').write_bytes(b'rear')
    mocker.patch('deltona.media.group_files',
                 side_effect=lambda items, *_: [[Path(x)] for x in sorted(items)])
    mock_run = mocker.patch('deltona.media.sp.run')
    mock_send2trash = mocker.patch('deltona.media.send2trash')
    archive_dashcam_footage(front_dir, rear_dir, output_dir)
    assert mock_run.call_count == 2
    assert mock_send2trash.call_count == 2


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
    mock_run.return_value.stdout = ("Attachment ID 1: type 'application/json', size 123 bytes, "
                                    "file name 'info.json'")
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
