from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from deltona.commands.admin import (
    clean_old_kernels_and_modules_main,
    generate_html_dir_tree_main,
    kconfig_to_commands_main,
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


def test_generate_html_dir_tree_main_success(mocker: MockerFixture, runner: CliRunner,
                                             tmp_path: Path) -> None:
    mock_generate_html_dir_tree = mocker.patch('deltona.commands.admin.generate_html_dir_tree')
    mock_generate_html_dir_tree.return_value = '<html></html>'
    mock_output = tmp_path / 'output.html'
    result = runner.invoke(generate_html_dir_tree_main, [str(tmp_path), '-o', str(mock_output)])
    assert result.exit_code == 0
    mock_generate_html_dir_tree.assert_called_once_with(tmp_path, follow_symlinks=False, depth=2)


def test_smv_main_success(mocker: MockerFixture, runner: CliRunner, tmp_path: Path) -> None:
    mock_ssh_client_cls = mocker.patch('deltona.commands.admin.get_ssh_client_cls')
    mock_client = mock_ssh_client_cls.return_value.return_value.__enter__.return_value
    mock_smv = mocker.patch('deltona.commands.admin.secure_move_path')
    mock_smv.return_value = 0
    tmp_src = tmp_path / 'src'
    tmp_src.mkdir()

    result = runner.invoke(smv_main, [str(tmp_src), 'some_host:dst'])
    assert result.exit_code == 0
    mock_smv.assert_called_once_with(mock_client,
                                     tmp_src,
                                     'dst',
                                     dry_run=False,
                                     preserve_stats=False)
    mock_client.load_system_host_keys.assert_called_once()
