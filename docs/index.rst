deltona
=============================

.. only:: html

   .. image:: https://img.shields.io/pypi/pyversions/deltona.svg?color=blue&logo=python&logoColor=white
      :target: https://www.python.org/
      :alt: Python versions

   .. image:: https://img.shields.io/pypi/v/deltona
      :target: https://pypi.org/project/deltona/
      :alt: PyPI - Version

   .. image:: https://img.shields.io/github/v/tag/Tatsh/deltona
      :target: https://github.com/Tatsh/deltona/tags
      :alt: GitHub tag (with filter)

   .. image:: https://img.shields.io/github/license/Tatsh/deltona
      :target: https://github.com/Tatsh/deltona/blob/master/LICENSE.txt
      :alt: License

   .. image:: https://img.shields.io/github/commits-since/Tatsh/deltona/v0.1.1/master
      :target: https://github.com/Tatsh/deltona/compare/v0.1.1...master
      :alt: GitHub commits since latest release (by SemVer including pre-releases)

   .. image:: https://github.com/Tatsh/deltona/actions/workflows/qa.yml/badge.svg
      :target: https://github.com/Tatsh/deltona/actions/workflows/qa.yml
      :alt: QA

   .. image:: https://github.com/Tatsh/deltona/actions/workflows/tests.yml/badge.svg
      :target: https://github.com/Tatsh/deltona/actions/workflows/tests.yml
      :alt: Tests

   .. image:: https://coveralls.io/repos/github/Tatsh/deltona/badge.svg?branch=master
      :target: https://coveralls.io/github/Tatsh/deltona?branch=master
      :alt: Coverage Status

   .. image:: https://readthedocs.org/projects/deltona/badge/?version=latest
      :target: https://deltona.readthedocs.org/?badge=latest
      :alt: Documentation Status

   .. image:: https://www.mypy-lang.org/static/mypy_badge.svg
      :target: http://mypy-lang.org/
      :alt: mypy

   .. image:: https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white
      :target: https://github.com/pre-commit/pre-commit
      :alt: pre-commit

   .. image:: https://img.shields.io/badge/pydocstyle-enabled-AD4CD3
      :target: http://www.pydocstyle.org/en/stable/
      :alt: pydocstyle

   .. image:: https://img.shields.io/badge/pytest-zz?logo=Pytest&labelColor=black&color=black
      :target: https://docs.pytest.org/en/stable/
      :alt: pytest

   .. image:: https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json
      :target: https://github.com/astral-sh/ruff
      :alt: Ruff

   .. image:: https://static.pepy.tech/badge/deltona/month
      :target: https://pepy.tech/project/deltona
      :alt: Downloads

   .. image:: https://img.shields.io/github/stars/Tatsh/deltona?logo=github&style=flat
      :target: https://github.com/Tatsh/deltona/stargazers
      :alt: Stargazers

   .. image:: https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fpublic.api.bsky.app%2Fxrpc%2Fapp.bsky.actor.getProfile%2F%3Factor%3Ddid%3Aplc%3Auq42idtvuccnmtl57nsucz72%26query%3D%24.followersCount%26style%3Dsocial%26logo%3Dbluesky%26label%3DFollow%2520%40Tatsh&query=%24.followersCount&style=social&logo=bluesky&label=Follow%20%40Tatsh
      :target: https://bsky.app/profile/Tatsh.bsky.social
      :alt: Follow @Tatsh

   .. image:: https://img.shields.io/mastodon/follow/109370961877277568?domain=hostux.social&style=social
      :target: https://hostux.social/@Tatsh
      :alt: Mastodon Follow

A lot of uncategorised utilities.

Commands
--------

.. click:: deltona.commands.media:add_cdda_times_main
   :prog: add-cdda-times
   :nested: full

.. click:: deltona.commands.media:add_info_json_main
   :prog: add-info-json
   :nested: full

.. click:: deltona.commands.misc:adp_main
   :prog: adp
   :nested: full

.. click:: deltona.commands.media:audio2vid_main
   :prog: audio2vid
   :nested: full

.. click:: deltona.commands.misc:burnrariso_main
   :prog: burnrariso
   :nested: full

.. click:: deltona.commands.media:cddb_query_main
   :prog: cddb-query
   :nested: full

.. click:: deltona.commands.www:check_bookmarks_html_main
   :prog: check-bookmarks-html
   :nested: full

.. click:: deltona.commands.www:chrome_bisect_flags_main
   :prog: chrome-bisect-flags
   :nested: full

.. click:: deltona.commands.admin:clean_old_kernels_and_modules_main
   :prog: clean-old-kernels-modules
   :nested: full

.. click:: deltona.commands.desktop:connect_g603_main
   :prog: connect-g603
   :nested: full

.. click:: deltona.commands.media:display_info_json_main
   :prog: display-info-json
   :nested: full

.. click:: deltona.commands.media:encode_dashcam_main
   :prog: encode-dashcam
   :nested: full

.. click:: deltona.commands.www:fix_chromium_pwa_icon_main
   :prog: fix-pwa-icon
   :nested: full

.. click:: deltona.commands.media:flac_dir_finalize_main
   :prog: flac-dir-finalize
   :nested: full

.. click:: deltona.commands.media:flacted_main
   :prog: flacted
   :nested: full

.. click:: deltona.commands.string:fullwidth2ascii_main
   :prog: fullwidth2ascii
   :nested: full

.. click:: deltona.commands.git:git_checkout_default_branch_main
   :prog: git-checkout-default-branch
   :nested: full

.. click:: deltona.commands.git:git_checkout_default_branch_main
   :prog: git-co-default-branch
   :nested: full

.. click:: deltona.commands.git:git_open_main
   :prog: git-open
   :nested: full

.. click:: deltona.commands.git:git_rebase_default_branch_main
   :prog: git-rebase-default-branch
   :nested: full

.. click:: deltona.commands.misc:gogextract_main
   :prog: gogextract
   :nested: full

.. click:: deltona.commands.media:hlg2sdr_main
   :prog: hlg2sdr
   :nested: full

.. click:: deltona.commands.admin:generate_html_dir_tree_main
   :prog: htmltree
   :nested: full

.. click:: deltona.commands.desktop:inhibit_notifications_main
   :prog: inhibit-notifications
   :nested: full

.. click:: deltona.commands.string:is_ascii_main
   :prog: is-ascii
   :nested: full

.. click:: deltona.commands.string:is_bin_main
   :prog: is-bin
   :nested: full

.. click:: deltona.commands.string:json2yaml_main
   :prog: json2yaml
   :nested: full

.. click:: deltona.commands.admin:kconfig_to_commands_main
   :prog: kconfig-to-commands
   :nested: full

.. click:: deltona.commands.media:ke_ebook_ex_main
   :prog: ke-ebook-ex
   :nested: full

.. click:: deltona.commands.desktop:kill_gamescope_main
   :prog: kill-gamescope
   :nested: full

.. click:: deltona.commands.wine:kill_wine_main
   :prog: kill-wine
   :nested: full

.. click:: deltona.commands.git:merge_dependabot_prs_main
   :prog: merge-dependabot-prs
   :nested: full

.. click:: deltona.commands.wine:mkwineprefix_main
   :prog: mkwineprefix
   :nested: full

.. click:: deltona.commands.media:add_info_json_main
   :prog: mp4json
   :nested: full

.. click:: deltona.commands.media:display_info_json_main
   :prog: mp4json-display
   :nested: full

.. click:: deltona.commands.desktop:mpv_sbs_main
   :prog: mpv-sbs
   :nested: full

.. click:: deltona.commands.media:mvid_rename_main
   :prog: mvid-rename
   :nested: full

.. click:: deltona.commands.string:urldecode_main
   :prog: netloc
   :nested: full

.. click:: deltona.commands.admin:patch_bundle_main
   :prog: patch-bundle
   :nested: full

.. click:: deltona.commands.wine:patch_ultraiso_font_main
   :prog: patch-uiso-font
   :nested: full

.. click:: deltona.commands.string:pl2json_main
   :prog: pl2json
   :nested: full

.. click:: deltona.commands.media:ripcd_main
   :prog: ripcd
   :nested: full

.. click:: deltona.commands.string:sanitize_main
   :prog: sanitize
   :nested: full

.. click:: deltona.commands.wine:set_wine_fonts_main
   :prog: set-wine-fonts
   :nested: full

.. click:: deltona.commands.media:display_info_json_main
   :prog: show-info-json
   :nested: full

.. click:: deltona.commands.admin:slug_rename_main
   :prog: slug-rename
   :nested: full

.. click:: deltona.commands.string:slugify_main
   :prog: slugify
   :nested: full

.. click:: deltona.commands.admin:smv_main
   :prog: smv
   :nested: full

.. click:: deltona.commands.media:supported_audio_input_formats_main
   :prog: supported-audio-input-formats
   :nested: full

.. click:: deltona.commands.admin:reset_tpm_enrollments_main
   :prog: systemd-reset-tpm-cryptenroll
   :nested: full

.. click:: deltona.commands.media:tbc2srt_main
   :prog: tbc2srt
   :nested: full

.. click:: deltona.commands.string:title_fixer_main
   :prog: title-fixer
   :nested: full

.. click:: deltona.commands.string:trim_main
   :prog: trim
   :nested: full

.. click:: deltona.commands.string:ucwords_main
   :prog: ucwords
   :nested: full

.. click:: deltona.commands.media:ultraiso_main
   :prog: uiso
   :nested: full

.. click:: deltona.commands.desktop:umpv_main
   :prog: umpv
   :nested: full

.. click:: deltona.commands.string:underscorize_main
   :prog: underscorize
   :nested: full

.. click:: deltona.commands.wine:unix2wine_main
   :prog: unix2wine
   :nested: full

.. click:: deltona.commands.misc:unpack_0day_main
   :prog: unpack-0day
   :nested: full

.. click:: deltona.commands.wine:unregister_wine_file_associations_main
   :prog: unregister-wine-assocs
   :nested: full

.. click:: deltona.commands.desktop:upload_to_imgbb_main
   :prog: upload-to-imgbb
   :nested: full

.. click:: deltona.commands.string:urldecode_main
   :prog: urldecode
   :nested: full

.. click:: deltona.commands.media:wait_for_disc_main
   :prog: wait-for-disc
   :nested: full

.. click:: deltona.commands.www:where_from_main
   :prog: where-from
   :nested: full

.. click:: deltona.commands.wine:winegoginstall_main
   :prog: winegoginstall
   :nested: full

.. click:: deltona.commands.wine:wineshell_main
   :prog: wineshell
   :nested: full

.. only:: html

   .. automodule:: deltona.constants
      :members:

   .. automodule:: deltona.gentoo
      :members:

   .. automodule:: deltona.git
      :members:

   .. automodule:: deltona.io
      :members:

   .. automodule:: deltona.media
      :members:

   .. automodule:: deltona.naming
      :members:

   .. automodule:: deltona.string
      :members:

   .. automodule:: deltona.system
      :members:

   .. automodule:: deltona.typing
      :members:

   .. automodule:: deltona.ultraiso
      :members:

   .. automodule:: deltona.utils
      :members:
      :exclude-members: setup_logging

   .. automodule:: deltona.windows
      :members:

   .. automodule:: deltona.www
      :members:

   Indices and tables
   ==================
   * :ref:`genindex`
   * :ref:`modindex`

.. _ffmpeg crop filter: https://ffmpeg.org/ffmpeg-filters.html#crop
.. _ffmpeg setpts filter: https://ffmpeg.org/ffmpeg-filters.html#setpts_002c-asetpts
.. _strptime() Format Codes: https://docs.python.org/3/library/datetime.html#strftime-and-strptime-format-codes
