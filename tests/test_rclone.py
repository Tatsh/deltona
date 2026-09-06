from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any
import json
import logging
import plistlib
import subprocess as sp
import time

import pytest

from deltona.rclone import (
    AlreadyRunning,
    DriveChanges,
    InvalidCredentials,
    bisync,
    check_credentials,
    dedupe,
    default_remote,
    default_service_kind,
    default_service_name,
    disable_service,
    enable_service,
    generate_service,
    griveignore_filters,
    griveignore_spec,
    install_service,
    is_drive_remote,
    launchd_label,
    service_path,
    single_instance,
    sync_once,
    uninstall_service,
    watch_and_sync,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def test_default_remote(tmp_path: Path) -> None:
    assert default_remote(tmp_path / 'Documents') == 'gdrive:Documents'
    assert default_remote(tmp_path / 'Documents', 'work') == 'work:Documents'


def test_default_service_name(tmp_path: Path) -> None:
    assert default_service_name(tmp_path / 'My Docs') == 'rclone-bisync-my-docs'


@pytest.mark.parametrize(('platform', 'expected'), [('darwin', 'launchd'),
                                                    ('linux', 'systemd-user')])
def test_default_service_kind(mocker: MockerFixture, platform: str, expected: str) -> None:
    mocker.patch('deltona.rclone.sys.platform', platform)
    assert default_service_kind() == expected


@pytest.mark.parametrize(('name', 'expected'), [('x', 'sh.tat.deltona.x'),
                                                ('sh.tat.deltona.x', 'sh.tat.deltona.x')])
def test_launchd_label(name: str, expected: str) -> None:
    assert launchd_label(name) == expected


def test_service_path(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.rclone.Path.home', return_value=tmp_path)
    assert service_path('launchd', 'x') == tmp_path / 'Library/LaunchAgents/sh.tat.deltona.x.plist'
    assert service_path('systemd-user', 'x') == tmp_path / '.config/systemd/user/x.service'
    assert service_path('systemd-system', 'x') == Path('/etc/systemd/system/x.service')


def test_generate_service_systemd_user() -> None:
    text = generate_service('systemd-user', 'x', ('/bin/thing', 'a b'), description='Sync.')
    assert 'Description=Sync.' in text
    assert "ExecStart=/bin/thing 'a b'" in text
    assert 'WantedBy=default.target' in text
    assert 'User=' not in text


def test_generate_service_systemd_system_user() -> None:
    text = generate_service('systemd-system', 'x', ('/bin/thing',), user='tatsh')
    assert 'User=tatsh' in text
    assert 'WantedBy=multi-user.target' in text


def test_generate_service_launchd() -> None:
    parsed: dict[str, Any] = plistlib.loads(
        generate_service('launchd', 'rclone-bisync-x', ('/bin/thing', '--flag')).encode())
    assert parsed['Label'] == 'sh.tat.deltona.rclone-bisync-x'
    assert parsed['ProgramArguments'] == ['/bin/thing', '--flag']
    assert parsed['RunAtLoad'] is True
    assert 'PATH' in parsed['EnvironmentVariables']


@pytest.mark.parametrize(('kind', 'expected'), [
    ('launchd', 'launchctl'),
    ('systemd-system', 'systemctl'),
    ('systemd-user', 'systemctl'),
])
def test_enable_service(mocker: MockerFixture, tmp_path: Path, kind: str, expected: str) -> None:
    mocker.patch('deltona.rclone.Path.home', return_value=tmp_path)
    mock_run = mocker.patch('deltona.rclone.sp.run')
    enable_service(kind, 'x')  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    assert mock_run.call_args_list[-1].args[0][0] == expected


def test_install_service(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.rclone.Path.home', return_value=tmp_path)
    mock_enable = mocker.patch('deltona.rclone.enable_service')
    path = install_service('systemd-user', 'x', ('/bin/thing',))
    assert path.read_text(encoding='utf-8').startswith('[Unit]')
    mock_enable.assert_called_once_with('systemd-user', 'x')


def test_install_service_no_enable(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.rclone.Path.home', return_value=tmp_path)
    mock_enable = mocker.patch('deltona.rclone.enable_service')
    install_service('systemd-user', 'x', ('/bin/thing',), enable=False)
    mock_enable.assert_not_called()


@pytest.mark.parametrize(('kind', 'expected'), [
    ('launchd', ('launchctl', 'bootout')),
    ('systemd-system', ('systemctl', 'disable', '--now', 'x')),
    ('systemd-user', ('systemctl', '--user', 'disable', '--now', 'x')),
])
def test_disable_service(mocker: MockerFixture, kind: str, expected: tuple[str, ...]) -> None:
    mock_run = mocker.patch('deltona.rclone.sp.run')
    disable_service(kind, 'x')  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    assert mock_run.call_args.args[0][:len(expected)] == expected


def test_disable_service_not_loaded(mocker: MockerFixture) -> None:
    mocker.patch('deltona.rclone.sp.run', side_effect=sp.CalledProcessError(1, 'systemctl'))
    disable_service('systemd-user', 'x')


def test_uninstall_service(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.rclone.Path.home', return_value=tmp_path)
    mocker.patch('deltona.rclone.enable_service')
    mock_run = mocker.patch('deltona.rclone.sp.run')
    path = install_service('systemd-user', 'x', ('/bin/thing',), enable=False)
    assert uninstall_service('systemd-user', 'x') == path
    assert not path.exists()
    assert mock_run.call_args.args[0] == ('systemctl', '--user', 'daemon-reload')


def test_uninstall_service_missing(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.rclone.Path.home', return_value=tmp_path)
    mocker.patch('deltona.rclone.sp.run')
    assert uninstall_service('systemd-user', 'x') is None


def test_uninstall_service_launchd(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.rclone.Path.home', return_value=tmp_path)
    mock_run = mocker.patch('deltona.rclone.sp.run')
    path = service_path('launchd', 'x')
    path.parent.mkdir(parents=True)
    path.touch()
    assert uninstall_service('launchd', 'x') == path
    assert not path.exists()
    assert mock_run.call_count == 1


def test_griveignore_spec_absent(tmp_path: Path) -> None:
    assert griveignore_spec(tmp_path) is None


def test_griveignore_spec_matches(tmp_path: Path) -> None:
    (tmp_path / '.griveignore').write_text('# comment\n\n*.log\nbuild/\n/only-root\n!keep.log\n',
                                           encoding='utf-8')
    spec = griveignore_spec(tmp_path)
    assert spec is not None
    assert spec.match_file('a.log') is True
    assert spec.match_file('sub/a.log') is True
    assert spec.match_file('keep.log') is False
    assert spec.match_file('build/x') is True
    assert spec.match_file('only-root') is True
    assert spec.match_file('sub/only-root') is False


def test_griveignore_filters_absent(tmp_path: Path) -> None:
    assert griveignore_filters(tmp_path) == ()


@pytest.mark.parametrize(('line', 'expected'), [
    ('*.log', ('- /**/*.log/**', '- /**/*.log')),
    ('build/', ('- /**/build/**',)),
    ('/only-root', ('- /only-root/**', '- /only-root')),
    ('doc/build', ('- /doc/build/**', '- /doc/build')),
    ('!keep.log', ('+ /**/keep.log/**', '+ /**/keep.log')),
    ('# comment', ()),
    ('', ()),
    ('!', ()),
])
def test_griveignore_filters_translation(tmp_path: Path, line: str, expected: tuple[str,
                                                                                    ...]) -> None:
    (tmp_path / '.griveignore').write_text(f'{line}\n', encoding='utf-8')
    assert griveignore_filters(tmp_path) == expected


def test_griveignore_filters_reverses_for_negation(tmp_path: Path) -> None:
    (tmp_path / '.griveignore').write_text('*.log\n!keep.log\n', encoding='utf-8')
    rules = griveignore_filters(tmp_path)
    # rclone stops at the first match, so the negation has to come before what it overrides.
    assert rules.index('+ /**/keep.log') < rules.index('- /**/*.log')


def test_bisync_passes_filters(mocker: MockerFixture, tmp_path: Path) -> None:
    (tmp_path / '.griveignore').write_text('*.log\n', encoding='utf-8')
    written: list[str] = []

    # The filter file only exists for as long as rclone is running, so it is read from here.
    def run(command: tuple[str, ...], **_kwargs: Any) -> Any:
        path = Path(command[command.index('--filter-from') + 1])
        written.append(path.read_text(encoding='utf-8'))
        return mocker.MagicMock()

    mocker.patch('deltona.rclone.sp.run', side_effect=run)
    bisync(tmp_path, 'gdrive:D')
    assert written[0].splitlines() == ['- /**/*.log/**', '- /**/*.log']


def test_bisync_without_griveignore(mocker: MockerFixture, tmp_path: Path) -> None:
    mock_run = mocker.patch('deltona.rclone.sp.run')
    bisync(tmp_path, 'gdrive:D')
    assert '--filter-from' not in mock_run.call_args.args[0]


def test_bisync(mocker: MockerFixture, tmp_path: Path) -> None:
    mock_run = mocker.patch('deltona.rclone.sp.run')
    bisync(tmp_path, 'gdrive:D', ('--extra',))
    command = mock_run.call_args.args[0]
    assert command[:4] == ('rclone', 'bisync', str(tmp_path), 'gdrive:D')
    assert '--drive-skip-gdocs' in command
    assert command[-1] == '--extra'
    assert '--resync' not in command
    assert mock_run.call_args.kwargs['check'] is True


def test_bisync_resync(mocker: MockerFixture, tmp_path: Path) -> None:
    mock_run = mocker.patch('deltona.rclone.sp.run')
    bisync(tmp_path, 'gdrive:D', resync=True)
    assert mock_run.call_args.args[0][-1] == '--resync'


def test_dedupe(mocker: MockerFixture) -> None:
    mock_run = mocker.patch('deltona.rclone.sp.run')
    dedupe('gdrive:D')
    assert mock_run.call_args.args[0] == ('rclone', 'dedupe', '--dedupe-mode', 'newest', 'gdrive:D')
    assert mock_run.call_args.kwargs['check'] is True


def test_bisync_logs_completion(mocker: MockerFixture, tmp_path: Path,
                                caplog: pytest.LogCaptureFixture) -> None:
    mocker.patch('deltona.rclone.sp.run')
    with caplog.at_level(logging.INFO, logger='deltona.rclone'):
        bisync(tmp_path, 'gdrive:D')
    assert f'Synchronised `{tmp_path}` with `gdrive:D` in ' in caplog.text
    assert ' seconds.' in caplog.text


def test_bisync_does_not_log_completion_on_failure(mocker: MockerFixture, tmp_path: Path,
                                                   caplog: pytest.LogCaptureFixture) -> None:
    mocker.patch('deltona.rclone.sp.run', side_effect=sp.CalledProcessError(1, 'rclone'))
    with caplog.at_level(logging.INFO,
                         logger='deltona.rclone'), pytest.raises(sp.CalledProcessError):
        bisync(tmp_path, 'gdrive:D')
    assert 'Synchronised' not in caplog.text


def test_dedupe_logs_completion(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    mocker.patch('deltona.rclone.sp.run')
    with caplog.at_level(logging.INFO, logger='deltona.rclone'):
        dedupe('gdrive:D')
    assert 'Deduplicated `gdrive:D` in ' in caplog.text


def test_dedupe_mode(mocker: MockerFixture) -> None:
    mock_run = mocker.patch('deltona.rclone.sp.run')
    dedupe('gdrive:D', 'largest')
    assert mock_run.call_args.args[0][3] == 'largest'


def test_sync_once_first_run_resyncs(mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch,
                                     tmp_path: Path) -> None:
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'cache'))
    mock_bisync = mocker.patch('deltona.rclone.bisync')
    sync_once(tmp_path, 'gdrive:D')
    assert mock_bisync.call_args.kwargs['resync'] is True
    sync_once(tmp_path, 'gdrive:D')
    assert mock_bisync.call_args.kwargs == {}


def test_single_instance_rejects_second(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('XDG_RUNTIME_DIR', str(tmp_path))
    with single_instance(tmp_path), pytest.raises(AlreadyRunning), single_instance(tmp_path):
        pass


def test_single_instance_releases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('XDG_RUNTIME_DIR', str(tmp_path))
    with single_instance(tmp_path):
        pass
    with single_instance(tmp_path):
        pass


def _mock_config_dump(mocker: MockerFixture, **overrides: Any) -> Any:
    return mocker.patch('deltona.rclone.sp.run',
                        return_value=mocker.MagicMock(stdout=json.dumps({
                            'gdrive': {
                                'token': json.dumps({'access_token': 'a-token'}),
                                'type': 'drive',
                                **overrides
                            }
                        })))


def _mock_drive_api(mocker: MockerFixture,
                    pages: list[Any] | None = None,
                    folders: dict[str, Any] | None = None,
                    status_code: int = 200) -> Any:
    session = mocker.patch('deltona.rclone.niquests.Session').return_value.__enter__.return_value
    feed = iter(pages or [])

    def get(url: str, **_kwargs: Any) -> Any:
        response = mocker.MagicMock(status_code=status_code)
        if url.endswith('/startPageToken'):
            response.json.return_value = {'startPageToken': '10'}
        elif url.endswith('/files/root'):
            response.json.return_value = {'id': 'ROOT'}
        elif url.endswith('/files'):
            response.json.return_value = {'files': [{'id': 'ROOT'}]}
        elif '/files/' in url:
            response.json.return_value = (folders or {})[url.rsplit('/', 1)[1]]
        else:
            response.json.return_value = next(feed)
        return response

    session.get.side_effect = get
    return session


def _drive_reader(mocker: MockerFixture, **kwargs: Any) -> Any:
    _mock_config_dump(mocker, **kwargs.pop('config', {}))
    _mock_drive_api(mocker, **kwargs)
    reader = DriveChanges('gdrive:D')
    # The first read only records where the feed has reached.
    assert reader.poll() is False
    return reader


@pytest.mark.parametrize(('type_', 'expected'), [('drive', True), ('s3', False)])
def test_is_drive_remote(
        mocker: MockerFixture, type_: str,
        expected: bool) -> None:  # ruff:ignore[boolean-type-hint-positional-argument]
    _mock_config_dump(mocker, type=type_)
    assert is_drive_remote('gdrive:D') is expected


def test_is_drive_remote_unknown(mocker: MockerFixture) -> None:
    _mock_config_dump(mocker)
    assert is_drive_remote('other:D') is False


def test_drive_changes_baseline_sends_credentials(mocker: MockerFixture) -> None:
    _mock_config_dump(mocker)
    session = _mock_drive_api(mocker)
    assert DriveChanges('gdrive:D').poll() is False
    assert session.get.call_args.args[0].endswith('/startPageToken')
    assert session.get.call_args.kwargs['headers']['Authorization'] == 'Bearer a-token'


def test_drive_changes_reports_nothing(mocker: MockerFixture) -> None:
    reader = _drive_reader(mocker, pages=[{'changes': [], 'newStartPageToken': '11'}])
    assert reader.poll() is False


def test_drive_changes_follows_pages(mocker: MockerFixture) -> None:
    reader = _drive_reader(mocker,
                           pages=[{
                               'changes': [],
                               'nextPageToken': '11'
                           }, {
                               'changes': [{
                                   'file': {
                                       'id': 'F',
                                       'name': 'notes.txt',
                                       'parents': ['ROOT']
                                   }
                               }],
                               'newStartPageToken': '12'
                           }])
    assert reader.poll() is True


def test_drive_changes_shared_drive(mocker: MockerFixture) -> None:
    _mock_config_dump(mocker, team_drive='0ABC')
    session = _mock_drive_api(mocker, [{'changes': [], 'newStartPageToken': '11'}])
    DriveChanges('gdrive:D').poll()
    params = session.get.call_args.kwargs['params']
    assert params['driveId'] == '0ABC'
    assert params['includeItemsFromAllDrives'] == 'true'


def test_drive_changes_no_stored_token(mocker: MockerFixture) -> None:
    mocker.patch('deltona.rclone.sp.run',
                 return_value=mocker.MagicMock(stdout=json.dumps({'gdrive': {
                     'type': 'drive'
                 }})))
    with pytest.raises(InvalidCredentials, match='no stored credentials'):
        DriveChanges('gdrive:D').poll()


def test_watch_and_sync_polls(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.rclone.Observer')
    mocker.patch('deltona.rclone.is_drive_remote', return_value=False)
    mocker.patch('deltona.rclone.dedupe')
    mock_sync = mocker.patch('deltona.rclone.sync_once', side_effect=[None, KeyboardInterrupt])
    watch_and_sync(tmp_path, 'gdrive:D', idle=0.01, poll=0.01)
    assert mock_sync.call_count == 2


def test_watch_and_sync_dedupes_after_first_sync(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.rclone.Observer')
    mocker.patch('deltona.rclone.is_drive_remote', return_value=False)
    mock_dedupe = mocker.patch('deltona.rclone.dedupe')
    mocker.patch('deltona.rclone.sync_once', side_effect=[None, KeyboardInterrupt])
    watch_and_sync(tmp_path, 'gdrive:D', dedupe_mode='oldest', idle=0.01, poll=0.01)
    mock_dedupe.assert_called_once_with('gdrive:D', 'oldest')


def test_watch_and_sync_dedupe_respects_interval(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.rclone.Observer')
    mocker.patch('deltona.rclone.is_drive_remote', return_value=False)
    mock_dedupe = mocker.patch('deltona.rclone.dedupe')
    mocker.patch('deltona.rclone.sync_once', side_effect=[None, None, KeyboardInterrupt])
    watch_and_sync(tmp_path, 'gdrive:D', dedupe_interval=3600, idle=0.01, poll=0.01)
    mock_dedupe.assert_called_once()


def _change(name: str, parent: str = 'ROOT') -> dict[str, Any]:
    return {'file': {'id': f'id-{name}', 'name': name, 'parents': [parent]}}


def test_drive_changes_ignores_matching_names(mocker: MockerFixture, tmp_path: Path) -> None:
    (tmp_path / '.griveignore').write_text('*.log\n', encoding='utf-8')
    reader = _drive_reader(mocker,
                           pages=[{
                               'changes': [_change('a.log')],
                               'newStartPageToken': '11'
                           }])
    assert reader.poll(griveignore_spec(tmp_path)) is False


def test_drive_changes_keeps_unmatched_names(mocker: MockerFixture, tmp_path: Path) -> None:
    (tmp_path / '.griveignore').write_text('*.log\n', encoding='utf-8')
    reader = _drive_reader(mocker,
                           pages=[{
                               'changes': [_change('a.log'), _change('notes.txt')],
                               'newStartPageToken': '11'
                           }])
    assert reader.poll(griveignore_spec(tmp_path)) is True


def test_drive_changes_matches_a_path_not_a_name(mocker: MockerFixture, tmp_path: Path) -> None:
    # A pattern anchored to a subdirectory can only match once the path is known.
    (tmp_path / '.griveignore').write_text('/build/\n', encoding='utf-8')
    reader = _drive_reader(mocker,
                           pages=[{
                               'changes': [_change('out.o', 'BUILD')],
                               'newStartPageToken': '11'
                           }],
                           folders={'BUILD': {
                               'name': 'build',
                               'parents': ['ROOT']
                           }})
    assert reader.poll(griveignore_spec(tmp_path)) is False


def test_drive_changes_anchored_pattern_spares_other_paths(mocker: MockerFixture,
                                                           tmp_path: Path) -> None:
    (tmp_path / '.griveignore').write_text('/build/\n', encoding='utf-8')
    reader = _drive_reader(mocker,
                           pages=[{
                               'changes': [_change('out.o', 'SRC')],
                               'newStartPageToken': '11'
                           }],
                           folders={'SRC': {
                               'name': 'src',
                               'parents': ['ROOT']
                           }})
    assert reader.poll(griveignore_spec(tmp_path)) is True


def test_drive_changes_skips_what_is_outside_the_remote(mocker: MockerFixture) -> None:
    # The feed covers the whole drive, so a change that does not sit under the remote is not one.
    reader = _drive_reader(mocker,
                           pages=[{
                               'changes': [_change('holiday.jpg', 'PHOTOS')],
                               'newStartPageToken': '11'
                           }],
                           folders={'PHOTOS': {
                               'name': 'Photos',
                               'parents': []
                           }})
    assert reader.poll() is False


def _lookups(session: Any, folder: str) -> int:
    return sum(
        1 for call in session.get.call_args_list if call.args[0].endswith(f'/files/{folder}'))


def test_drive_changes_caches_directory_lookups(mocker: MockerFixture, tmp_path: Path) -> None:
    (tmp_path / '.griveignore').write_text('/nothing\n', encoding='utf-8')
    _mock_config_dump(mocker)
    session = _mock_drive_api(mocker, [{
        'changes': [_change('a', 'SUB'), _change('b', 'SUB')],
        'newStartPageToken': '11'
    }, {
        'changes': [_change('c', 'SUB')],
        'newStartPageToken': '12'
    }],
                              folders={'SUB': {
                                  'name': 'sub',
                                  'parents': ['ROOT']
                              }})
    reader = DriveChanges('gdrive:D')
    reader.poll()
    spec = griveignore_spec(tmp_path)
    reader.poll(spec)
    reader.poll(spec)
    # The directory is looked up once and remembered, across changes and across reads.
    assert _lookups(session, 'SUB') == 1


def test_drive_changes_forgets_a_renamed_directory(mocker: MockerFixture, tmp_path: Path) -> None:
    (tmp_path / '.griveignore').write_text('/nothing\n', encoding='utf-8')
    _mock_config_dump(mocker)
    session = _mock_drive_api(mocker, [{
        'changes': [_change('a', 'SUB')],
        'newStartPageToken': '11'
    }, {
        'changes': [{
            'file': {
                'id': 'SUB',
                'mimeType': 'application/vnd.google-apps.folder',
                'name': 'renamed',
                'parents': ['ROOT']
            }
        }],
        'newStartPageToken': '12'
    }, {
        'changes': [_change('b', 'SUB')],
        'newStartPageToken': '13'
    }],
                              folders={'SUB': {
                                  'name': 'sub',
                                  'parents': ['ROOT']
                              }})
    reader = DriveChanges('gdrive:D')
    reader.poll()
    spec = griveignore_spec(tmp_path)
    reader.poll(spec)
    reader.poll(spec)
    reader.poll(spec)
    # The rename drops what was remembered, so the name is fetched again.
    assert _lookups(session, 'SUB') == 2


def test_drive_changes_keeps_removals(mocker: MockerFixture, tmp_path: Path) -> None:
    (tmp_path / '.griveignore').write_text('*.log\n', encoding='utf-8')
    # A removal carries no file, so where it was cannot be looked up and it has to count.
    reader = _drive_reader(mocker,
                           pages=[{
                               'changes': [{
                                   'removed': True
                               }],
                               'newStartPageToken': '11'
                           }])
    assert reader.poll(griveignore_spec(tmp_path)) is True


def test_watch_and_sync_ignores_matching_writes(mocker: MockerFixture, tmp_path: Path) -> None:
    (tmp_path / '.griveignore').write_text('*.log\n', encoding='utf-8')
    observer = mocker.patch('deltona.rclone.Observer').return_value
    mocker.patch('deltona.rclone.is_drive_remote', return_value=False)
    mocker.patch('deltona.rclone.dedupe')

    def schedule(handler: Any, path: str, *, recursive: bool = False) -> None:
        observer.start.side_effect = lambda: handler.on_any_event(
            mocker.MagicMock(src_path=str(tmp_path / 'a.log'), dest_path=''))

    observer.schedule.side_effect = schedule
    mock_sync = mocker.patch('deltona.rclone.sync_once', side_effect=KeyboardInterrupt)
    watch_and_sync(tmp_path, 'gdrive:D', dedupe_interval=0, idle=0.01, poll=0.2)
    # The write was ignored, so the sync came from the poll rather than from the watcher.
    mock_sync.assert_called_once_with(tmp_path, 'gdrive:D', ())


def test_watch_and_sync_keeps_unmatched_writes(mocker: MockerFixture, tmp_path: Path) -> None:
    (tmp_path / '.griveignore').write_text('*.log\n', encoding='utf-8')
    observer = mocker.patch('deltona.rclone.Observer').return_value
    mocker.patch('deltona.rclone.is_drive_remote', return_value=False)
    mocker.patch('deltona.rclone.dedupe')

    def schedule(handler: Any, path: str, *, recursive: bool = False) -> None:
        observer.start.side_effect = lambda: handler.on_any_event(
            mocker.MagicMock(src_path=str(tmp_path / 'notes.txt'), dest_path=''))

    observer.schedule.side_effect = schedule
    mock_sync = mocker.patch('deltona.rclone.sync_once', side_effect=KeyboardInterrupt)
    watch_and_sync(tmp_path, 'gdrive:D', dedupe_interval=0, idle=0.01, poll=30)
    mock_sync.assert_called_once_with(tmp_path, 'gdrive:D', ())


def test_watch_and_sync_picks_up_an_edited_griveignore(mocker: MockerFixture,
                                                       tmp_path: Path) -> None:
    # Nothing is ignored to begin with, and the file is rewritten while the daemon is running.
    (tmp_path / '.griveignore').write_text('# nothing\n', encoding='utf-8')
    observer = mocker.patch('deltona.rclone.Observer').return_value
    mocker.patch('deltona.rclone.is_drive_remote', return_value=False)
    mocker.patch('deltona.rclone.dedupe')
    event = mocker.MagicMock(dest_path='',
                             event_type='modified',
                             is_directory=False,
                             src_path=str(tmp_path / 'a.log'))

    def schedule(handler: Any, path: str, *, recursive: bool = False) -> None:
        def start() -> None:
            (tmp_path / '.griveignore').write_text('*.log\n', encoding='utf-8')
            handler.on_any_event(event)

        observer.start.side_effect = start

    observer.schedule.side_effect = schedule
    mock_sync = mocker.patch('deltona.rclone.sync_once', side_effect=KeyboardInterrupt)
    start = time.monotonic()
    watch_and_sync(tmp_path, 'gdrive:D', dedupe_interval=0, idle=0.01, poll=0.4)
    # The rewritten patterns applied without a restart, so the write did not wake the watcher.
    assert time.monotonic() - start >= 0.4
    mock_sync.assert_called_once_with(tmp_path, 'gdrive:D', ())


def test_watch_and_sync_keeps_moves_out_of_ignored_paths(mocker: MockerFixture,
                                                         tmp_path: Path) -> None:
    (tmp_path / '.griveignore').write_text('*.log\n', encoding='utf-8')
    observer = mocker.patch('deltona.rclone.Observer').return_value
    mocker.patch('deltona.rclone.is_drive_remote', return_value=False)
    mocker.patch('deltona.rclone.dedupe')

    def schedule(handler: Any, path: str, *, recursive: bool = False) -> None:
        observer.start.side_effect = lambda: handler.on_any_event(
            mocker.MagicMock(src_path=str(tmp_path / 'a.log'),
                             dest_path=str(tmp_path / 'notes.txt')))

    observer.schedule.side_effect = schedule
    mock_sync = mocker.patch('deltona.rclone.sync_once', side_effect=KeyboardInterrupt)
    watch_and_sync(tmp_path, 'gdrive:D', dedupe_interval=0, idle=0.01, poll=30)
    mock_sync.assert_called_once_with(tmp_path, 'gdrive:D', ())


def _watch_with_event(mocker: MockerFixture, tmp_path: Path, event: Any) -> Any:
    observer = mocker.patch('deltona.rclone.Observer').return_value
    mocker.patch('deltona.rclone.is_drive_remote', return_value=False)
    mocker.patch('deltona.rclone.dedupe')

    def schedule(handler: Any, path: str, *, recursive: bool = False) -> None:
        observer.start.side_effect = lambda: handler.on_any_event(event)

    observer.schedule.side_effect = schedule
    mock_sync = mocker.patch('deltona.rclone.sync_once', side_effect=KeyboardInterrupt)
    # A poll long enough that only the watcher can produce a synchronisation in time.
    watch_and_sync(tmp_path, 'gdrive:D', dedupe_interval=0, idle=0.01, poll=0.4)
    return mock_sync


@pytest.mark.parametrize('event_type', ['closed_no_write', 'opened'])
def test_watch_and_sync_ignores_reads(mocker: MockerFixture, tmp_path: Path,
                                      event_type: str) -> None:
    # rclone reads every file it compares and the filter file is read from the tree, so a read must
    # never arm the watcher that starts the next run.
    event = mocker.MagicMock(dest_path='',
                             event_type=event_type,
                             is_directory=False,
                             src_path=str(tmp_path / 'notes.txt'))
    start = time.monotonic()
    _watch_with_event(mocker, tmp_path, event)
    assert time.monotonic() - start >= 0.4


def test_watch_and_sync_ignores_parent_directory_writes(mocker: MockerFixture,
                                                        tmp_path: Path) -> None:
    # Writing an ignored file marks its directory as modified, which must not leak through.
    event = mocker.MagicMock(dest_path='',
                             event_type='modified',
                             is_directory=True,
                             src_path=str(tmp_path))
    start = time.monotonic()
    _watch_with_event(mocker, tmp_path, event)
    assert time.monotonic() - start >= 0.4


def test_watch_and_sync_keeps_directory_creation(mocker: MockerFixture, tmp_path: Path) -> None:
    event = mocker.MagicMock(dest_path='',
                             event_type='created',
                             is_directory=True,
                             src_path=str(tmp_path / 'sub'))
    start = time.monotonic()
    _watch_with_event(mocker, tmp_path, event)
    assert time.monotonic() - start < 0.4


def test_watch_and_sync_logs_settled(mocker: MockerFixture, tmp_path: Path,
                                     caplog: pytest.LogCaptureFixture) -> None:
    observer = mocker.patch('deltona.rclone.Observer').return_value
    mocker.patch('deltona.rclone.is_drive_remote', return_value=False)
    mocker.patch('deltona.rclone.dedupe')

    def schedule(handler: Any, path: str, *, recursive: bool = False) -> None:
        observer.start.side_effect = lambda: handler.on_any_event(
            mocker.MagicMock(dest_path='',
                             event_type='modified',
                             is_directory=False,
                             src_path=str(tmp_path / 'notes.txt')))

    observer.schedule.side_effect = schedule
    mocker.patch('deltona.rclone.sync_once', side_effect=[None, KeyboardInterrupt])
    with caplog.at_level(logging.INFO, logger='deltona.rclone'):
        watch_and_sync(tmp_path, 'gdrive:D', dedupe_interval=0, idle=0.01, poll=0.05)
    assert 'Settled after 1 synchronisation, with no change for 0 seconds.' in caplog.text


def test_watch_and_sync_does_not_log_settled_while_idle(mocker: MockerFixture, tmp_path: Path,
                                                        caplog: pytest.LogCaptureFixture) -> None:
    mocker.patch('deltona.rclone.Observer')
    mocker.patch('deltona.rclone.is_drive_remote', return_value=False)
    mocker.patch('deltona.rclone.dedupe')
    mocker.patch('deltona.rclone.sync_once', side_effect=[None, None, KeyboardInterrupt])
    with caplog.at_level(logging.INFO, logger='deltona.rclone'):
        watch_and_sync(tmp_path, 'gdrive:D', dedupe_interval=0, idle=0.01, poll=0.05)
    assert 'Settled' not in caplog.text


def test_watch_and_sync_throttles_runaway(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.rclone.Observer')
    mocker.patch('deltona.rclone.is_drive_remote', return_value=False)
    mocker.patch('deltona.rclone.dedupe')
    mock_sleep = mocker.patch('deltona.rclone.time.sleep')
    mocker.patch('deltona.rclone.sync_once', side_effect=[None, None, KeyboardInterrupt])
    watch_and_sync(tmp_path,
                   'gdrive:D',
                   dedupe_interval=0,
                   idle=0.01,
                   max_syncs_per_minute=2,
                   poll=0.01)
    mock_sleep.assert_called_once()
    assert 0 < mock_sleep.call_args.args[0] <= 60


def test_watch_and_sync_throttle_warns(mocker: MockerFixture, tmp_path: Path,
                                       caplog: pytest.LogCaptureFixture) -> None:
    mocker.patch('deltona.rclone.Observer')
    mocker.patch('deltona.rclone.is_drive_remote', return_value=False)
    mocker.patch('deltona.rclone.dedupe')
    mocker.patch('deltona.rclone.time.sleep')
    mocker.patch('deltona.rclone.sync_once', side_effect=[None, None, KeyboardInterrupt])
    with caplog.at_level(logging.WARNING, logger='deltona.rclone'):
        watch_and_sync(tmp_path,
                       'gdrive:D',
                       dedupe_interval=0,
                       idle=0.01,
                       max_syncs_per_minute=2,
                       poll=0.01)
    assert 'not settling' in caplog.text


def test_watch_and_sync_throttle_allows_slow_syncs(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.rclone.Observer')
    mocker.patch('deltona.rclone.is_drive_remote', return_value=False)
    mocker.patch('deltona.rclone.dedupe')
    mock_sleep = mocker.patch('deltona.rclone.time.sleep')
    mocker.patch('deltona.rclone.time.monotonic', side_effect=[0.0, 100.0, 200.0])
    mocker.patch('deltona.rclone.sync_once', side_effect=[None, None, KeyboardInterrupt])
    watch_and_sync(tmp_path,
                   'gdrive:D',
                   dedupe_interval=0,
                   idle=0.01,
                   max_syncs_per_minute=2,
                   poll=0.01)
    mock_sleep.assert_not_called()


def test_watch_and_sync_throttle_disabled(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.rclone.Observer')
    mocker.patch('deltona.rclone.is_drive_remote', return_value=False)
    mocker.patch('deltona.rclone.dedupe')
    mock_sleep = mocker.patch('deltona.rclone.time.sleep')
    mocker.patch('deltona.rclone.sync_once', side_effect=[None, None, KeyboardInterrupt])
    watch_and_sync(tmp_path,
                   'gdrive:D',
                   dedupe_interval=0,
                   idle=0.01,
                   max_syncs_per_minute=0,
                   poll=0.01)
    mock_sleep.assert_not_called()


def test_watch_and_sync_dedupe_disabled(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.rclone.Observer')
    mocker.patch('deltona.rclone.is_drive_remote', return_value=False)
    mock_dedupe = mocker.patch('deltona.rclone.dedupe')
    mocker.patch('deltona.rclone.sync_once', side_effect=[None, KeyboardInterrupt])
    watch_and_sync(tmp_path, 'gdrive:D', dedupe_interval=0, idle=0.01, poll=0.01)
    mock_dedupe.assert_not_called()


def test_watch_and_sync_debounces(mocker: MockerFixture, tmp_path: Path) -> None:
    observer = mocker.patch('deltona.rclone.Observer').return_value
    mocker.patch('deltona.rclone.is_drive_remote', return_value=False)

    def schedule(handler: Any, path: str, *, recursive: bool = False) -> None:
        observer.start.side_effect = lambda: handler.on_any_event(mocker.MagicMock())

    observer.schedule.side_effect = schedule
    mock_sync = mocker.patch('deltona.rclone.sync_once', side_effect=KeyboardInterrupt)
    watch_and_sync(tmp_path, 'gdrive:D', idle=0.01, poll=30)
    mock_sync.assert_called_once_with(tmp_path, 'gdrive:D', ())
    observer.stop.assert_called_once()


@pytest.mark.parametrize('status_code', [401, 403])
def test_drive_changes_refused(mocker: MockerFixture, status_code: int) -> None:
    _mock_config_dump(mocker)
    _mock_drive_api(mocker, status_code=status_code)
    with pytest.raises(InvalidCredentials, match='refused'):
        DriveChanges('gdrive:D').poll()


def test_check_credentials_accepts(mocker: MockerFixture) -> None:
    mock_run = mocker.patch('deltona.rclone.sp.run')
    check_credentials('gdrive:D')
    assert mock_run.call_args.args[0] == ('rclone', 'about', 'gdrive:')


def test_check_credentials_rejects(mocker: MockerFixture) -> None:
    error = sp.CalledProcessError(1, 'rclone')
    error.stderr = "Failed to about: couldn't fetch token"
    mocker.patch('deltona.rclone.sp.run', side_effect=error)
    with pytest.raises(InvalidCredentials, match="couldn't fetch token"):
        check_credentials('gdrive:D')


def test_check_credentials_rejects_without_stderr(mocker: MockerFixture) -> None:
    mocker.patch('deltona.rclone.sp.run', side_effect=sp.CalledProcessError(1, 'rclone'))
    with pytest.raises(InvalidCredentials, match='cannot authorise'):
        check_credentials('gdrive:D')


def test_watch_and_sync_syncs_on_remote_change(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.rclone.Observer')
    mocker.patch('deltona.rclone.is_drive_remote', return_value=True)
    mock_check = mocker.patch('deltona.rclone.check_credentials')
    reader = mocker.patch('deltona.rclone.DriveChanges').return_value
    reader.poll.return_value = True
    mock_sync = mocker.patch('deltona.rclone.sync_once', side_effect=KeyboardInterrupt)
    watch_and_sync(tmp_path, 'gdrive:D', idle=0.01, poll=30, remote_poll=0.01)
    mock_sync.assert_called_once_with(tmp_path, 'gdrive:D', ())
    mock_check.assert_called_once_with('gdrive:D')
    # The baseline read takes no patterns; every read after it is matched against them.
    assert reader.poll.call_args_list[0].args == ()
    assert reader.poll.call_args_list[1].args[0] is None


def test_watch_and_sync_rejects_bad_credentials(mocker: MockerFixture, tmp_path: Path) -> None:
    observer = mocker.patch('deltona.rclone.Observer').return_value
    mocker.patch('deltona.rclone.is_drive_remote', return_value=True)
    mocker.patch('deltona.rclone.check_credentials', side_effect=InvalidCredentials('Nope.'))
    mock_sync = mocker.patch('deltona.rclone.sync_once')
    with pytest.raises(InvalidCredentials, match='Nope'):
        watch_and_sync(tmp_path, 'gdrive:D', idle=0.01, poll=0.01, remote_poll=0.01)
    mock_sync.assert_not_called()
    observer.start.assert_not_called()


def test_watch_and_sync_skips_remote_watch(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.rclone.Observer')
    mock_is_drive = mocker.patch('deltona.rclone.is_drive_remote')
    mock_check = mocker.patch('deltona.rclone.check_credentials')
    mock_reader = mocker.patch('deltona.rclone.DriveChanges')
    mocker.patch('deltona.rclone.sync_once', side_effect=KeyboardInterrupt)
    watch_and_sync(tmp_path, 'gdrive:D', idle=0.01, poll=0.01, remote_poll=0)
    mock_is_drive.assert_not_called()
    mock_check.assert_not_called()
    mock_reader.assert_not_called()


def test_watch_and_sync_refreshes_expired_token(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch('deltona.rclone.Observer')
    mocker.patch('deltona.rclone.is_drive_remote', return_value=True)
    mock_check = mocker.patch('deltona.rclone.check_credentials')
    reader = mocker.patch('deltona.rclone.DriveChanges').return_value
    polls: list[Any] = []

    def poll(ignore: Any = None) -> bool:
        polls.append(ignore)
        if len(polls) == 1:
            return False
        raise OSError

    reader.poll.side_effect = poll
    mocker.patch('deltona.rclone.sync_once', side_effect=KeyboardInterrupt)
    watch_and_sync(tmp_path, 'gdrive:D', idle=0.01, poll=0.3, remote_poll=0.01)
    assert mock_check.call_count > 1
