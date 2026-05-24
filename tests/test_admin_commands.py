from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any
import logging

from deltona.commands.admin import (
    clean_old_kernels_and_modules_main,
    generate_html_dir_tree_main,
    kconfig_to_commands_main,
    kconfig_to_json_main,
    patch_bundle_main,
    reset_tpm_enrollments_main,
    slug_rename_main,
    smv_main,
)
from deltona.system import MultipleKeySlots
from pytest_mock import MockerFixture

if TYPE_CHECKING:
    from click.testing import CliRunner
    from pytest_mock import MockerFixture
    import pytest


def test_reset_tpm_enrollments_main_success(mocker: MockerFixture, runner: CliRunner) -> None:
    mock_reset = mocker.patch('deltona.commands.admin.reset_tpm_enrollment')
    mock_reset.return_value = 0

    result = runner.invoke(reset_tpm_enrollments_main, ['uuid1'])
    assert result.exit_code == 0
    mock_reset.assert_called_once()


def test_reset_tpm_enrollments_main_all(mocker: MockerFixture, runner: CliRunner,
                                        tmp_path: Path) -> None:
    mock_reset = mocker.patch('deltona.commands.admin.reset_tpm_enrollment')
    mock_reset.return_value = 0
    fake_crypttab = tmp_path / 'crypttab'
    fake_crypttab.write_text('# fake-crypttab\n'
                             'name1 UUID=uuid1 /dev/mapper/crypt-root tpm2-device=auto\n'
                             'name2 UUID=uuid2 /dev/mapper/crypt-root tpm2-device=auto\n'
                             '# UUID=uuid3 /dev/mapper/crypt-root tpm2-device=auto')

    result = runner.invoke(reset_tpm_enrollments_main, ['-a', '--crypttab', str(fake_crypttab)])
    assert result.exit_code == 0
    mock_reset.assert_has_calls(
        [mocker.call('uuid1', dry_run=True),
         mocker.call('uuid2', dry_run=True)])


def test_reset_tpm_enrollments_main_exception(mocker: MockerFixture, runner: CliRunner) -> None:
    mock_reset = mocker.patch('deltona.commands.admin.reset_tpm_enrollment')
    mock_reset.side_effect = MultipleKeySlots('Unexpected error')

    result = runner.invoke(reset_tpm_enrollments_main, ['uuid1'])
    assert result.exit_code == 0
    assert 'Cannot reset TPM enrolment for' in result.output


def test_clean_old_kernels_and_modules_main_success(mocker: MockerFixture,
                                                    runner: CliRunner) -> None:
    mock_clean = mocker.patch('deltona.commands.admin.clean_old_kernels_and_modules')
    mock_clean.return_value = ['a']

    result = runner.invoke(clean_old_kernels_and_modules_main)
    assert result.exit_code == 0
    mock_clean.assert_called_once()


def test_slug_rename_main_success(mocker: MockerFixture, runner: CliRunner) -> None:
    mock_slug_rename = mocker.patch('deltona.commands.admin.slug_rename')
    mock_slug_rename.return_value = 0

    result = runner.invoke(slug_rename_main, ['old-slug', 'new-slug'])
    assert result.exit_code == 0
    mock_slug_rename.assert_has_calls(
        [mocker.call('old-slug', no_lower=False),
         mocker.call('new-slug', no_lower=False)])
    assert 'old-slug ->' not in result.output


def test_slug_rename_main_success_verbose(mocker: MockerFixture, runner: CliRunner) -> None:
    mock_slug_rename = mocker.patch('deltona.commands.admin.slug_rename')
    mock_slug_rename.return_value = 0

    result = runner.invoke(slug_rename_main, ['old-slug', 'new-slug', '-v'])
    assert result.exit_code == 0
    mock_slug_rename.assert_has_calls(
        [mocker.call('old-slug', no_lower=False),
         mocker.call('new-slug', no_lower=False)])
    assert 'old-slug ->' in result.output
    assert 'new-slug ->' in result.output


def test_patch_bundle_main_success(mocker: MockerFixture, runner: CliRunner) -> None:
    mock_patch_bundle = mocker.patch('deltona.commands.admin.patch_macos_bundle_info_plist')
    mock_patch_bundle.return_value = 0

    result = runner.invoke(patch_bundle_main, ['bundle-path'])
    assert result.exit_code == 0
    data: dict[str, Any] = {}
    mock_patch_bundle.assert_called_once_with(Path('bundle-path'), **data)


def test_patch_bundle_main_adds_retina(mocker: MockerFixture, runner: CliRunner) -> None:
    mock_patch_bundle = mocker.patch('deltona.commands.admin.patch_macos_bundle_info_plist')
    mock_patch_bundle.return_value = 0

    result = runner.invoke(patch_bundle_main, ['bundle-path', '--retina'])
    assert result.exit_code == 0
    data: dict[str, Any] = {'NSHighResolutionCapable': True}
    mock_patch_bundle.assert_called_once_with(Path('bundle-path'), **data)


def test_patch_bundle_main_adds_env_vars(mocker: MockerFixture, runner: CliRunner) -> None:
    mock_patch_bundle = mocker.patch('deltona.commands.admin.patch_macos_bundle_info_plist')
    mock_patch_bundle.return_value = 0

    result = runner.invoke(patch_bundle_main, ['bundle-path', '-E', 'key1', 'value1'])
    assert result.exit_code == 0
    data: dict[str, Any] = {'LSEnvironment': {'key1': 'value1'}}
    mock_patch_bundle.assert_called_once_with(Path('bundle-path'), **data)


def test_kconfig_to_commands_main_success(mocker: MockerFixture, runner: CliRunner) -> None:
    mock_kconfig_to_commands = mocker.patch('deltona.commands.admin.get_kwriteconfig_commands')
    mock_kconfig_to_commands.return_value = ['a']
    mock_kdeglobals = mocker.MagicMock()
    mock_path = mocker.patch('deltona.commands.admin.Path')
    mock_path.home.return_value.__truediv__.return_value.glob.return_value = []
    mock_path.home.return_value.__truediv__.return_value = mock_kdeglobals
    result = runner.invoke(kconfig_to_commands_main, ['-a'])
    assert result.exit_code == 0
    mock_kconfig_to_commands.assert_called_once_with(mock_kdeglobals)


def test_kconfig_to_commands_main_file_arg(mocker: MockerFixture, runner: CliRunner,
                                           tmp_path: Path) -> None:
    mock_kconfig_to_commands = mocker.patch('deltona.commands.admin.get_kwriteconfig_commands')
    mock_kconfig_to_commands.return_value = ['a']
    mock_file = tmp_path / 'filename'
    mock_file.write_text('content')
    result = runner.invoke(kconfig_to_commands_main, [str(mock_file)])
    assert result.exit_code == 0
    mock_kconfig_to_commands.assert_called_once_with(mock_file)


def test_kconfig_to_json_main_all(mocker: MockerFixture, runner: CliRunner, tmp_path: Path) -> None:
    mock_kconfig_to_json = mocker.patch('deltona.commands.admin.get_kconfig_dict')
    mock_kconfig_to_json.return_value = {}
    mock_path = mocker.patch('deltona.commands.admin.Path')
    result = runner.invoke(kconfig_to_json_main, ['--all'])
    assert result.exit_code == 0
    mock_kconfig_to_json.assert_called_with(mock_path.home.return_value.__truediv__.return_value)


def test_kconfig_to_json_main_file_arg(mocker: MockerFixture, runner: CliRunner,
                                       tmp_path: Path) -> None:
    mock_kconfig_to_json = mocker.patch('deltona.commands.admin.get_kconfig_dict')
    mock_kconfig_to_json.return_value = {}
    mock_file = tmp_path / 'filename'
    mock_file.write_text('content')
    result = runner.invoke(kconfig_to_json_main, [str(mock_file)])
    assert result.exit_code == 0
    mock_kconfig_to_json.assert_called_once_with(mock_file)


def test_generate_html_dir_tree_main_success(mocker: MockerFixture, runner: CliRunner,
                                             tmp_path: Path) -> None:
    mock_generate_html_dir_tree = mocker.patch('deltona.commands.admin.generate_html_dir_tree')
    mock_generate_html_dir_tree.return_value = '<html></html>'
    mock_output = tmp_path / 'output.html'
    result = runner.invoke(generate_html_dir_tree_main, [str(tmp_path), '-o', str(mock_output)])
    assert result.exit_code == 0
    mock_generate_html_dir_tree.assert_called_once_with(tmp_path, follow_symlinks=False, depth=2)


def _make_smv_clients(mocker: MockerFixture, count: int) -> list[Any]:
    clients = [mocker.MagicMock() for _ in range(count)]
    for client in clients:
        client.__enter__.return_value = client
        client.__exit__.return_value = False
    return clients


def test_smv_main_success(mocker: MockerFixture, runner: CliRunner, tmp_path: Path) -> None:
    [mock_client] = _make_smv_clients(mocker, 1)
    mock_paramiko = mocker.patch('paramiko.SSHClient', return_value=mock_client)
    mock_smv = mocker.patch('deltona.commands.admin.secure_move_path')
    mock_smv.return_value = 0
    tmp_src = tmp_path / 'src'
    tmp_src.mkdir()

    result = runner.invoke(smv_main, ['--no-ssh-config', str(tmp_src), 'some_host:dst'])
    assert result.exit_code == 0, result.output
    mock_paramiko.assert_called_once_with()
    mock_smv.assert_called_once_with(mock_client,
                                     tmp_src,
                                     'dst',
                                     bandwidth_limit_kbits=None,
                                     dry_run=False,
                                     preserve_stats=False)
    mock_client.load_system_host_keys.assert_called_once()
    mock_client.connect.assert_called_once_with('some_host',
                                                22,
                                                None,
                                                compress=False,
                                                key_filename=None,
                                                timeout=2.0)


def test_smv_main_parses_user_at_host(mocker: MockerFixture, runner: CliRunner,
                                      tmp_path: Path) -> None:
    [mock_client] = _make_smv_clients(mocker, 1)
    mocker.patch('paramiko.SSHClient', return_value=mock_client)
    mocker.patch('deltona.commands.admin.secure_move_path')
    tmp_src = tmp_path / 'src'
    tmp_src.touch()

    result = runner.invoke(
        smv_main,
        ['--no-ssh-config', str(tmp_src), 'alice@host.example.com:/srv'])
    assert result.exit_code == 0, result.output
    args, _ = mock_client.connect.call_args
    assert args[0] == 'host.example.com'
    assert args[2] == 'alice'


def test_smv_main_reads_ssh_config(mocker: MockerFixture, runner: CliRunner,
                                   tmp_path: Path) -> None:
    [mock_client] = _make_smv_clients(mocker, 1)
    mocker.patch('paramiko.SSHClient', return_value=mock_client)
    mocker.patch('deltona.commands.admin.secure_move_path')
    cfg_file = tmp_path / 'ssh_config'
    cfg_file.write_text(
        'Host limelight\n  HostName 192.168.1.10\n  User tatsh\n  Port 2200\n'
        '  IdentityFile /home/tatsh/.ssh/id_ed25519\n  Compression yes\n  ConnectTimeout 7\n',
        encoding='utf-8')
    tmp_src = tmp_path / 'src'
    tmp_src.touch()

    result = runner.invoke(smv_main, ['-F', str(cfg_file), str(tmp_src), 'limelight:~/Downloads/'])
    assert result.exit_code == 0, result.output
    mock_client.connect.assert_called_once_with('192.168.1.10',
                                                2200,
                                                'tatsh',
                                                compress=True,
                                                key_filename='/home/tatsh/.ssh/id_ed25519',
                                                timeout=7.0)


def test_smv_main_explicit_flags_beat_ssh_config(mocker: MockerFixture, runner: CliRunner,
                                                 tmp_path: Path) -> None:
    [mock_client] = _make_smv_clients(mocker, 1)
    mocker.patch('paramiko.SSHClient', return_value=mock_client)
    mocker.patch('deltona.commands.admin.secure_move_path')
    cfg_file = tmp_path / 'ssh_config'
    cfg_file.write_text(
        'Host limelight\n  HostName config-host\n  User config-user\n  Port 2200\n'
        '  IdentityFile /from/config\n  Compression no\n  ConnectTimeout 7\n',
        encoding='utf-8')
    explicit_key = tmp_path / 'explicit_key'
    explicit_key.touch()
    tmp_src = tmp_path / 'src'
    tmp_src.touch()

    result = runner.invoke(smv_main, [
        '-F',
        str(cfg_file), '-P', '2022', '-i',
        str(explicit_key), '-t', '15', '-C',
        str(tmp_src), 'cli-user@limelight:~/d/'
    ])
    assert result.exit_code == 0, result.output
    mock_client.connect.assert_called_once_with('config-host',
                                                2022,
                                                'cli-user',
                                                compress=True,
                                                key_filename=str(explicit_key),
                                                timeout=15.0)


def test_smv_main_no_ssh_config_skips_lookup(mocker: MockerFixture, runner: CliRunner,
                                             tmp_path: Path) -> None:
    [mock_client] = _make_smv_clients(mocker, 1)
    mocker.patch('paramiko.SSHClient', return_value=mock_client)
    mocker.patch('deltona.commands.admin.secure_move_path')
    fake_home = tmp_path / 'home'
    (fake_home / '.ssh').mkdir(parents=True)
    (fake_home / '.ssh' / 'config').write_text('Host *\n  Port 9999\n', encoding='utf-8')
    mocker.patch('deltona.commands.admin.Path.home', return_value=fake_home)
    tmp_src = tmp_path / 'src'
    tmp_src.touch()

    result = runner.invoke(smv_main, ['--no-ssh-config', str(tmp_src), 'host:dst'])
    assert result.exit_code == 0, result.output
    mock_client.connect.assert_called_once_with('host',
                                                22,
                                                None,
                                                compress=False,
                                                key_filename=None,
                                                timeout=2.0)


def test_smv_main_loads_explicit_f_file(mocker: MockerFixture, runner: CliRunner,
                                        tmp_path: Path) -> None:
    [mock_client] = _make_smv_clients(mocker, 1)
    mocker.patch('paramiko.SSHClient', return_value=mock_client)
    mocker.patch('deltona.commands.admin.secure_move_path')
    tmp_src = tmp_path / 'src'
    tmp_src.touch()
    cfg_file = tmp_path / 'ssh_config'
    cfg_file.write_text('Host limelight\n  HostName 10.0.0.1\n  User tatsh\n  Port 2200\n',
                        encoding='utf-8')

    result = runner.invoke(smv_main, ['-F', str(cfg_file), str(tmp_src), 'limelight:dst'])
    assert result.exit_code == 0, result.output
    mock_client.connect.assert_called_once_with('10.0.0.1',
                                                2200,
                                                'tatsh',
                                                compress=False,
                                                key_filename=None,
                                                timeout=2.0)


def test_smv_main_default_ssh_config_loaded(mocker: MockerFixture, runner: CliRunner,
                                            tmp_path: Path) -> None:
    [mock_client] = _make_smv_clients(mocker, 1)
    mocker.patch('paramiko.SSHClient', return_value=mock_client)
    mocker.patch('deltona.commands.admin.secure_move_path')
    fake_home = tmp_path / 'home'
    (fake_home / '.ssh').mkdir(parents=True)
    (fake_home / '.ssh' / 'config').write_text(
        'Host limelight\n  HostName 10.0.0.1\n  User tatsh\n', encoding='utf-8')
    mocker.patch('deltona.commands.admin.Path.home', return_value=fake_home)
    tmp_src = tmp_path / 'src'
    tmp_src.touch()

    result = runner.invoke(smv_main, [str(tmp_src), 'limelight:dst'])
    assert result.exit_code == 0, result.output
    args, _ = mock_client.connect.call_args
    assert args[0] == '10.0.0.1'
    assert args[2] == 'tatsh'


def test_smv_main_missing_default_ssh_config_noop(mocker: MockerFixture, runner: CliRunner,
                                                  tmp_path: Path) -> None:
    [mock_client] = _make_smv_clients(mocker, 1)
    mocker.patch('paramiko.SSHClient', return_value=mock_client)
    mocker.patch('deltona.commands.admin.secure_move_path')
    fake_home = tmp_path / 'home'
    fake_home.mkdir()
    mocker.patch('deltona.commands.admin.Path.home', return_value=fake_home)
    tmp_src = tmp_path / 'src'
    tmp_src.touch()

    result = runner.invoke(smv_main, [str(tmp_src), 'host:dst'])
    assert result.exit_code == 0, result.output
    mock_client.connect.assert_called_once_with('host',
                                                22,
                                                None,
                                                compress=False,
                                                key_filename=None,
                                                timeout=2.0)


def test_smv_main_o_overrides_ssh_config(mocker: MockerFixture, runner: CliRunner,
                                         tmp_path: Path) -> None:
    [mock_client] = _make_smv_clients(mocker, 1)
    mocker.patch('paramiko.SSHClient', return_value=mock_client)
    mocker.patch('deltona.commands.admin.secure_move_path')
    cfg_file = tmp_path / 'ssh_config'
    cfg_file.write_text(
        'Host limelight\n  HostName config-host\n  User config-user\n  Port 2200\n'
        '  Compression no\n',
        encoding='utf-8')
    tmp_src = tmp_path / 'src'
    tmp_src.touch()

    result = runner.invoke(smv_main, [
        '-F',
        str(cfg_file), '-o', 'User=alice', '-o', 'Port=3300', '-o', 'Compression=yes',
        str(tmp_src), 'limelight:dst'
    ])
    assert result.exit_code == 0, result.output
    mock_client.connect.assert_called_once_with('config-host',
                                                3300,
                                                'alice',
                                                compress=True,
                                                key_filename=None,
                                                timeout=2.0)


def test_smv_main_o_identityfile(mocker: MockerFixture, runner: CliRunner, tmp_path: Path) -> None:
    [mock_client] = _make_smv_clients(mocker, 1)
    mocker.patch('paramiko.SSHClient', return_value=mock_client)
    mocker.patch('deltona.commands.admin.secure_move_path')
    tmp_src = tmp_path / 'src'
    tmp_src.touch()

    result = runner.invoke(
        smv_main, ['--no-ssh-config', '-o', 'IdentityFile=/keys/from-o',
                   str(tmp_src), 'host:dst'])
    assert result.exit_code == 0, result.output
    _, kwargs = mock_client.connect.call_args
    assert kwargs['key_filename'] == '/keys/from-o'


def test_smv_main_explicit_beats_o(mocker: MockerFixture, runner: CliRunner,
                                   tmp_path: Path) -> None:
    [mock_client] = _make_smv_clients(mocker, 1)
    mocker.patch('paramiko.SSHClient', return_value=mock_client)
    mocker.patch('deltona.commands.admin.secure_move_path')
    tmp_src = tmp_path / 'src'
    tmp_src.touch()

    result = runner.invoke(
        smv_main, ['--no-ssh-config', '-o', 'Port=2200', '-P', '4444',
                   str(tmp_src), 'host:dst'])
    assert result.exit_code == 0, result.output
    args, _ = mock_client.connect.call_args
    assert args[1] == 4444


def test_smv_main_o_unknown_key_rejected(mocker: MockerFixture, runner: CliRunner,
                                         tmp_path: Path) -> None:
    [mock_client] = _make_smv_clients(mocker, 1)
    mocker.patch('paramiko.SSHClient', return_value=mock_client)
    mocker.patch('deltona.commands.admin.secure_move_path')
    tmp_src = tmp_path / 'src'
    tmp_src.touch()

    result = runner.invoke(smv_main,
                           ['--no-ssh-config', '-o', 'KexAlgorithms=foo',
                            str(tmp_src), 'host:dst'])
    assert result.exit_code != 0
    assert 'unsupported ssh option' in result.output.lower()


def test_smv_main_o_malformed_rejected(mocker: MockerFixture, runner: CliRunner,
                                       tmp_path: Path) -> None:
    [mock_client] = _make_smv_clients(mocker, 1)
    mocker.patch('paramiko.SSHClient', return_value=mock_client)
    mocker.patch('deltona.commands.admin.secure_move_path')
    tmp_src = tmp_path / 'src'
    tmp_src.touch()

    result = runner.invoke(smv_main,
                           ['--no-ssh-config', '-o', 'NoEqualsSign',
                            str(tmp_src), 'host:dst'])
    assert result.exit_code != 0
    assert 'expected KEY=VALUE' in result.output


def test_smv_main_v_aliases_debug(mocker: MockerFixture, runner: CliRunner, tmp_path: Path) -> None:
    [mock_client] = _make_smv_clients(mocker, 1)
    mocker.patch('paramiko.SSHClient', return_value=mock_client)
    mocker.patch('deltona.commands.admin.secure_move_path')
    setup_mock = mocker.patch('deltona.commands.admin.setup_logging')
    tmp_src = tmp_path / 'src'
    tmp_src.touch()

    result = runner.invoke(smv_main, ['--no-ssh-config', '-v', str(tmp_src), 'host:dst'])
    assert result.exit_code == 0, result.output
    _, kwargs = setup_mock.call_args
    assert kwargs['debug'] is True


def test_smv_main_q_silences_info_logs(mocker: MockerFixture, runner: CliRunner, tmp_path: Path,
                                       caplog: pytest.LogCaptureFixture) -> None:
    [mock_client] = _make_smv_clients(mocker, 1)
    mocker.patch('paramiko.SSHClient', return_value=mock_client)
    mocker.patch('deltona.commands.admin.setup_logging')
    mock_smv = mocker.patch('deltona.commands.admin.secure_move_path')
    mock_smv.side_effect = lambda *_args, **_kwargs: logging.getLogger('deltona.probe').info(
        'q-probe')
    tmp_src = tmp_path / 'src'
    tmp_src.touch()

    caplog.set_level(logging.INFO, logger='deltona')
    result = runner.invoke(smv_main, ['--no-ssh-config', '-q', str(tmp_src), 'host:dst'])
    assert result.exit_code == 0, result.output
    assert not any(r.message == 'q-probe' for r in caplog.records)


def test_smv_main_q_silenced_by_v(mocker: MockerFixture, runner: CliRunner, tmp_path: Path,
                                  caplog: pytest.LogCaptureFixture) -> None:
    [mock_client] = _make_smv_clients(mocker, 1)
    mocker.patch('paramiko.SSHClient', return_value=mock_client)
    mocker.patch('deltona.commands.admin.setup_logging')
    mock_smv = mocker.patch('deltona.commands.admin.secure_move_path')
    mock_smv.side_effect = lambda *_args, **_kwargs: logging.getLogger('deltona.probe').info(
        'qv-probe')
    tmp_src = tmp_path / 'src'
    tmp_src.touch()

    caplog.set_level(logging.INFO, logger='deltona')
    result = runner.invoke(smv_main, ['--no-ssh-config', '-q', '-v', str(tmp_src), 'host:dst'])
    assert result.exit_code == 0, result.output
    assert any(r.message == 'qv-probe' for r in caplog.records)


def test_smv_main_l_propagates_to_secure_move_path(mocker: MockerFixture, runner: CliRunner,
                                                   tmp_path: Path) -> None:
    [mock_client] = _make_smv_clients(mocker, 1)
    mocker.patch('paramiko.SSHClient', return_value=mock_client)
    mock_smv = mocker.patch('deltona.commands.admin.secure_move_path')
    tmp_src = tmp_path / 'src'
    tmp_src.touch()

    result = runner.invoke(smv_main, ['--no-ssh-config', '-l', '2048', str(tmp_src), 'host:dst'])
    assert result.exit_code == 0, result.output
    _, kwargs = mock_smv.call_args
    assert kwargs['bandwidth_limit_kbits'] == 2048


def test_smv_main_b_accepted(mocker: MockerFixture, runner: CliRunner, tmp_path: Path) -> None:
    [mock_client] = _make_smv_clients(mocker, 1)
    mocker.patch('paramiko.SSHClient', return_value=mock_client)
    mocker.patch('deltona.commands.admin.secure_move_path')
    tmp_src = tmp_path / 'src'
    tmp_src.touch()

    result = runner.invoke(smv_main, ['--no-ssh-config', '-B', str(tmp_src), 'host:dst'])
    assert result.exit_code == 0, result.output
    assert mock_client.connect.called


def test_smv_main_j_single_hop(mocker: MockerFixture, runner: CliRunner, tmp_path: Path) -> None:
    clients = _make_smv_clients(mocker, 2)
    mocker.patch('paramiko.SSHClient', side_effect=clients)
    mocker.patch('deltona.commands.admin.secure_move_path')
    tmp_src = tmp_path / 'src'
    tmp_src.touch()

    result = runner.invoke(
        smv_main, ['--no-ssh-config', '-J', 'bastion.example.com',
                   str(tmp_src), 'host:dst'])
    assert result.exit_code == 0, result.output
    jump_client, target_client = clients
    args, _ = jump_client.connect.call_args
    assert args[:3] == ('bastion.example.com', 22, None)
    chan = jump_client.get_transport.return_value.open_channel
    chan.assert_called_once_with('direct-tcpip', ('host', 22), ('', 0))
    target_args, target_kwargs = target_client.connect.call_args
    assert target_args[:3] == ('host', 22, None)
    assert target_kwargs['sock'] is chan.return_value


def test_smv_main_j_multi_hop_chain(mocker: MockerFixture, runner: CliRunner,
                                    tmp_path: Path) -> None:
    clients = _make_smv_clients(mocker, 3)
    mocker.patch('paramiko.SSHClient', side_effect=clients)
    mocker.patch('deltona.commands.admin.secure_move_path')
    tmp_src = tmp_path / 'src'
    tmp_src.touch()

    result = runner.invoke(smv_main, [
        '--no-ssh-config', '-J', 'alice@j1.example.com:2200,j2.example.com',
        str(tmp_src), 'target:dst'
    ])
    assert result.exit_code == 0, result.output
    j1, j2, target = clients
    assert j1.connect.call_args.args[:3] == ('j1.example.com', 2200, 'alice')
    j1.get_transport.return_value.open_channel.assert_called_once_with(
        'direct-tcpip', ('j2.example.com', 22), ('', 0))
    assert j2.connect.call_args.args[:3] == ('j2.example.com', 22, None)
    assert j2.connect.call_args.kwargs[
        'sock'] is j1.get_transport.return_value.open_channel.return_value
    j2.get_transport.return_value.open_channel.assert_called_once_with(
        'direct-tcpip', ('target', 22), ('', 0))
    assert target.connect.call_args.kwargs[
        'sock'] is j2.get_transport.return_value.open_channel.return_value


def test_smv_main_j_skips_empty_entries(mocker: MockerFixture, runner: CliRunner,
                                        tmp_path: Path) -> None:
    clients = _make_smv_clients(mocker, 2)
    mocker.patch('paramiko.SSHClient', side_effect=clients)
    mocker.patch('deltona.commands.admin.secure_move_path')
    tmp_src = tmp_path / 'src'
    tmp_src.touch()

    result = runner.invoke(smv_main,
                           ['--no-ssh-config', '-J', ',bastion,,',
                            str(tmp_src), 'host:dst'])
    assert result.exit_code == 0, result.output
    jump_client, _ = clients
    assert jump_client.connect.call_args.args[:3] == ('bastion', 22, None)


def test_smv_main_j_invalid_port_rejected(mocker: MockerFixture, runner: CliRunner,
                                          tmp_path: Path) -> None:
    [mock_client] = _make_smv_clients(mocker, 1)
    mocker.patch('paramiko.SSHClient', return_value=mock_client)
    mocker.patch('deltona.commands.admin.secure_move_path')
    tmp_src = tmp_path / 'src'
    tmp_src.touch()

    result = runner.invoke(smv_main,
                           ['--no-ssh-config', '-J', 'host:xyz',
                            str(tmp_src), 'target:dst'])
    assert result.exit_code != 0
    assert 'invalid jump port' in result.output


def test_smv_main_o_proxyjump_used_when_no_explicit_j(mocker: MockerFixture, runner: CliRunner,
                                                      tmp_path: Path) -> None:
    clients = _make_smv_clients(mocker, 2)
    mocker.patch('paramiko.SSHClient', side_effect=clients)
    mocker.patch('deltona.commands.admin.secure_move_path')
    tmp_src = tmp_path / 'src'
    tmp_src.touch()

    result = runner.invoke(
        smv_main, ['--no-ssh-config', '-o', 'ProxyJump=bastion.via-o',
                   str(tmp_src), 'host:dst'])
    assert result.exit_code == 0, result.output
    jump_client, _ = clients
    assert jump_client.connect.call_args.args[:3] == ('bastion.via-o', 22, None)


def test_smv_main_explicit_j_beats_o_proxyjump(mocker: MockerFixture, runner: CliRunner,
                                               tmp_path: Path) -> None:
    clients = _make_smv_clients(mocker, 2)
    mocker.patch('paramiko.SSHClient', side_effect=clients)
    mocker.patch('deltona.commands.admin.secure_move_path')
    tmp_src = tmp_path / 'src'
    tmp_src.touch()

    result = runner.invoke(smv_main, [
        '--no-ssh-config', '-J', 'explicit.jump', '-o', 'ProxyJump=loser.jump',
        str(tmp_src), 'host:dst'
    ])
    assert result.exit_code == 0, result.output
    jump_client, _ = clients
    assert jump_client.connect.call_args.args[:3] == ('explicit.jump', 22, None)
