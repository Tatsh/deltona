"""Main CLI group wrapping all commands."""

from __future__ import annotations

from importlib import import_module
from typing import Any
import sys

from deltona.constants import CONTEXT_SETTINGS
import click

_COMMANDS: dict[str, str] = {
    'add-cdda-times': 'deltona.commands.media:add_cdda_times_main',
    'add-info-json': 'deltona.commands.media:add_info_json_main',
    'adp': 'deltona.commands.misc:adp_main',
    'audio2vid': 'deltona.commands.media:audio2vid_main',
    'burnrariso': 'deltona.commands.misc:burnrariso_main',
    'cddb-query': 'deltona.commands.media:cddb_query_main',
    'check-bookmarks-html': 'deltona.commands.www:check_bookmarks_html_main',
    'chrome-bisect-flags': 'deltona.commands.www:chrome_bisect_flags_main',
    'clean-old-kernels-modules': 'deltona.commands.admin:clean_old_kernels_and_modules_main',
    'connect-g603': 'deltona.commands.desktop:connect_g603_main',
    'cssq': 'deltona.commands.string:cssq_main',
    'display-info-json': 'deltona.commands.media:display_info_json_main',
    'encode-dashcam': 'deltona.commands.media:encode_dashcam_main',
    'fix-pwa-icon': 'deltona.commands.www:fix_chromium_pwa_icon_main',
    'flac-dir-finalize': 'deltona.commands.media:flac_dir_finalize_main',
    'fullwidth2ascii': 'deltona.commands.string:fullwidth2ascii_main',
    'git-checkout-default-branch': 'deltona.commands.git:git_checkout_default_branch_main',
    'git-co-default-branch': 'deltona.commands.git:git_checkout_default_branch_main',
    'git-open': 'deltona.commands.git:git_open_main',
    'git-rebase-default-branch': 'deltona.commands.git:git_rebase_default_branch_main',
    'gogextract': 'deltona.commands.misc:gogextract_main',
    'hlg2sdr': 'deltona.commands.media:hlg2sdr_main',
    'htmltree': 'deltona.commands.admin:generate_html_dir_tree_main',
    'inhibit-notifications': 'deltona.commands.desktop:inhibit_notifications_main',
    'is-ascii': 'deltona.commands.string:is_ascii_main',
    'is-bin': 'deltona.commands.string:is_bin_main',
    'json2yaml': 'deltona.commands.string:json2yaml_main',
    'kconfig-to-commands': 'deltona.commands.admin:kconfig_to_commands_main',
    'kconfig-to-json': 'deltona.commands.admin:kconfig_to_json_main',
    'ke-ebook-ex': 'deltona.commands.media:ke_ebook_ex_main',
    'kill-gamescope': 'deltona.commands.desktop:kill_gamescope_main',
    'kill-wine': 'deltona.commands.wine:kill_wine_main',
    'merge-dependabot-prs': 'deltona.commands.git:merge_dependabot_prs_main',
    'mp4json': 'deltona.commands.media:add_info_json_main',
    'mp4json-display': 'deltona.commands.media:display_info_json_main',
    'mpv-sbs': 'deltona.commands.desktop:mpv_sbs_main',
    'mvid-rename': 'deltona.commands.media:mvid_rename_main',
    'netloc': 'deltona.commands.string:urldecode_main',
    'patch-bundle': 'deltona.commands.admin:patch_bundle_main',
    'patch-uiso-font': 'deltona.commands.wine:patch_ultraiso_font_main',
    'pl2json': 'deltona.commands.string:pl2json_main',
    'sanitize': 'deltona.commands.string:sanitize_main',
    'set-wine-fonts': 'deltona.commands.wine:set_wine_fonts_main',
    'show-info-json': 'deltona.commands.media:display_info_json_main',
    'slug-rename': 'deltona.commands.admin:slug_rename_main',
    'slugify': 'deltona.commands.string:slugify_main',
    'smv': 'deltona.commands.admin:smv_main',
    'supported-audio-input-formats': 'deltona.commands.media:supported_audio_input_formats_main',
    'systemd-reset-tpm-cryptenroll': 'deltona.commands.admin:reset_tpm_enrollments_main',
    'tbc2srt': 'deltona.commands.media:tbc2srt_main',
    'title-fixer': 'deltona.commands.string:title_fixer_main',
    'trim': 'deltona.commands.string:trim_main',
    'ucwords': 'deltona.commands.string:ucwords_main',
    'uiso': 'deltona.commands.media:ultraiso_main',
    'umpv': 'deltona.commands.desktop:umpv_main',
    'underscorize': 'deltona.commands.string:underscorize_main',
    'unix2wine': 'deltona.commands.wine:unix2wine_main',
    'unpack-0day': 'deltona.commands.misc:unpack_0day_main',
    'unregister-wine-assocs': 'deltona.commands.wine:unregister_wine_file_associations_main',
    'upload-to-imgbb': 'deltona.commands.desktop:upload_to_imgbb_main',
    'urldecode': 'deltona.commands.string:urldecode_main',
    'wait-for-disc': 'deltona.commands.media:wait_for_disc_main',
    'where-from': 'deltona.commands.www:where_from_main',
    'winegoginstall': 'deltona.commands.wine:winegoginstall_main',
    'wineshell': 'deltona.commands.wine:wineshell_main',
}
_LINUX_ONLY: frozenset[str] = frozenset({
    'clean-old-kernels-modules',
    'connect-g603',
    'inhibit-notifications',
    'kill-gamescope',
    'systemd-reset-tpm-cryptenroll',
    'wait-for-disc',
})
_NOT_WINDOWS: frozenset[str] = _LINUX_ONLY | frozenset({
    'kill-wine',
    'set-wine-fonts',
    'unregister-wine-assocs',
    'winegoginstall',
    'wineshell',
})


def _excluded() -> frozenset[str]:
    if sys.platform == 'win32':
        return _NOT_WINDOWS
    if sys.platform == 'darwin':
        return _LINUX_ONLY
    return frozenset()


class _LazyGroup(click.Group):
    def __init__(self,
                 *args: Any,
                 lazy_subcommands: dict[str, str] | None = None,
                 **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._lazy_subcommands = lazy_subcommands or {}

    def list_commands(self, ctx: click.Context) -> list[str]:  # noqa: ARG002
        excluded = _excluded()
        return sorted(k for k in self._lazy_subcommands if k not in excluded)

    def get_command(
            self,
            ctx: click.Context,  # noqa: ARG002
            cmd_name: str) -> click.Command | None:
        if cmd_name not in self._lazy_subcommands or cmd_name in _excluded():
            return None
        module_path, func_name = self._lazy_subcommands[cmd_name].rsplit(':', 1)
        cmd: click.Command = getattr(import_module(module_path), func_name)
        cmd.name = cmd_name
        return cmd


@click.group(cls=_LazyGroup, lazy_subcommands=_COMMANDS, context_settings=CONTEXT_SETTINGS)
def main() -> None:
    """Deltona - a collection of utilities."""
