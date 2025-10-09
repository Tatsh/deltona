local utils = import 'utils.libjsonnet';

{
  // Project-specific
  local settings = self,
  description: 'A lot of uncategorised utilities.',
  keywords: ['bluetooth', 'command line', 'file management', 'git', 'multimedia'],
  project_name: 'deltona',
  version: '0.0.2',
  want_main: false,  // Multiple entry points.
  want_man: true,
  supported_python_versions: ['3.%d' % i for i in std.range(12, 14)],
  has_multiple_entry_points: true,
  pyproject+: {
    project+: {
      classifiers: utils.pyprojectClassifiers(settings, [
        'Environment :: Console',
        'Intended Audience :: End Users/Desktop',
        'Intended Audience :: Information Technology',
        'Intended Audience :: System Administrators',
        'Operating System :: POSIX :: Linux',
        'Operating System :: MacOS',
        'Operating System :: Microsoft :: Windows',
        'Topic :: Desktop Environment',
        'Topic :: Desktop Environment :: K Desktop Environment (KDE)',
        'Topic :: File Formats',
        'Topic :: Games/Entertainment',
        'Topic :: Internet :: WWW/HTTP :: Browsers',
        'Topic :: Multimedia',
        'Topic :: System :: Hardware',
        'Topic :: System :: Systems Administration',
        'Topic :: Utilities',
      ]),
      scripts: {
        // admin
        'clean-old-kernels-modules': 'deltona.commands.admin:clean_old_kernels_and_modules_main',
        htmltree: 'deltona.commands.admin:generate_html_dir_tree_main',
        'kconfig-to-commands': 'deltona.commands.admin:kconfig_to_commands_main',
        'kconfig-to-json': 'deltona.commands.admin:kconfig_to_json_main',
        'patch-bundle': 'deltona.commands.admin:patch_bundle_main',
        'slug-rename': 'deltona.commands.admin:slug_rename_main',
        smv: 'deltona.commands.admin:smv_main',
        'systemd-reset-tpm-cryptenroll': 'deltona.commands.admin:reset_tpm_enrollments_main',
        // desktop
        'connect-g603': 'deltona.commands.desktop:connect_g603_main',
        'inhibit-notifications': 'deltona.commands.desktop:inhibit_notifications_main',
        'kill-gamescope': 'deltona.commands.desktop:kill_gamescope_main',
        'mpv-sbs': 'deltona.commands.desktop:mpv_sbs_main',
        umpv: 'deltona.commands.desktop:umpv_main',
        'upload-to-imgbb': 'deltona.commands.desktop:upload_to_imgbb_main',
        // flacted
        'flac-album': 'deltona.commands.media:flacted_main',
        'flac-artist': 'deltona.commands.media:flacted_main',
        'flac-dir-finalize': 'deltona.commands.media:flac_dir_finalize_main',
        'flac-genre': 'deltona.commands.media:flacted_main',
        'flac-title': 'deltona.commands.media:flacted_main',
        'flac-track': 'deltona.commands.media:flacted_main',
        'flac-year': 'deltona.commands.media:flacted_main',
        flacted: 'deltona.commands.media:flacted_main',
        // git
        'git-checkout-default-branch': 'deltona.commands.git:git_checkout_default_branch_main',
        'git-co-default-branch': 'deltona.commands.git:git_checkout_default_branch_main',
        'git-open': 'deltona.commands.git:git_open_main',
        'git-rebase-default-branch': 'deltona.commands.git:git_rebase_default_branch_main',
        'merge-dependabot-prs': 'deltona.commands.git:merge_dependabot_prs_main',
        // media
        'add-cdda-times': 'deltona.commands.media:add_cdda_times_main',
        'add-info-json': 'deltona.commands.media:add_info_json_main',
        audio2vid: 'deltona.commands.media:audio2vid_main',
        'cddb-query': 'deltona.commands.media:cddb_query_main',
        'display-info-json': 'deltona.commands.media:display_info_json_main',
        'encode-dashcam': 'deltona.commands.media:encode_dashcam_main',
        hlg2sdr: 'deltona.commands.media:hlg2sdr_main',
        'ke-ebook-ex': 'deltona.commands.media:ke_ebook_ex_main',
        mp4json: 'deltona.commands.media:add_info_json_main',
        'mp4json-display': 'deltona.commands.media:display_info_json_main',
        'mvid-rename': 'deltona.commands.media:mvid_rename_main',
        ripcd: 'deltona.commands.media:ripcd_main',
        'show-info-json': 'deltona.commands.media:display_info_json_main',
        'supported-audio-input-formats': 'deltona.commands.media:supported_audio_input_formats_main',
        tbc2srt: 'deltona.commands.media:tbc2srt_main',
        uiso: 'deltona.commands.media:ultraiso_main',
        'wait-for-disc': 'deltona.commands.media:wait_for_disc_main',
        // misc
        adp: 'deltona.commands.misc:adp_main',
        burnrariso: 'deltona.commands.misc:burnrariso_main',
        gogextract: 'deltona.commands.misc:gogextract_main',
        'unpack-0day': 'deltona.commands.misc:unpack_0day_main',
        // string
        cssq: 'deltona.commands.string:cssq_main',
        fullwidth2ascii: 'deltona.commands.string:fullwidth2ascii_main',
        'is-ascii': 'deltona.commands.string:is_ascii_main',
        'is-bin': 'deltona.commands.string:is_bin_main',
        json2yaml: 'deltona.commands.string:json2yaml_main',
        netloc: 'deltona.commands.string:urldecode_main',
        pl2json: 'deltona.commands.string:pl2json_main',
        sanitize: 'deltona.commands.string:sanitize_main',
        slugify: 'deltona.commands.string:slugify_main',
        'title-fixer': 'deltona.commands.string:title_fixer_main',
        trim: 'deltona.commands.string:trim_main',
        ucwords: 'deltona.commands.string:ucwords_main',
        underscorize: 'deltona.commands.string:underscorize_main',
        urldecode: 'deltona.commands.string:urldecode_main',
        // wine
        'kill-wine': 'deltona.commands.wine:kill_wine_main',
        mkwineprefix: 'deltona.commands.wine:mkwineprefix_main',
        'patch-uiso-font': 'deltona.commands.wine:patch_ultraiso_font_main',
        'set-wine-fonts': 'deltona.commands.wine:set_wine_fonts_main',
        unix2wine: 'deltona.commands.wine:unix2wine_main',
        'unregister-wine-assocs': 'deltona.commands.wine:unregister_wine_file_associations_main',
        winegoginstall: 'deltona.commands.wine:winegoginstall_main',
        wineshell: 'deltona.commands.wine:wineshell_main',
        // www
        'check-bookmarks-html': 'deltona.commands.www:check_bookmarks_html_main',
        'chrome-bisect-flags': 'deltona.commands.www:chrome_bisect_flags_main',
        'fix-pwa-icon': 'deltona.commands.www:fix_chromium_pwa_icon_main',
        'where-from': 'deltona.commands.www:where_from_main',
      },
    },
    tool+: {
      poetry+: {
        dependencies+: {
          beautifulsoup4: {
            optional: true,
            version: utils.latestPypiPackageVersionCaret('beautifulsoup4'),
          },
          binaryornot: utils.latestPypiPackageVersionCaret('binaryornot'),
          click: utils.latestPypiPackageVersionCaret('click'),
          gitpython: {
            optional: true,
            version: utils.latestPypiPackageVersionCaret('gitpython'),
          },
          html5lib: {
            optional: true,
            version: utils.latestPypiPackageVersionCaret('html5lib'),
          },
          keyring: utils.latestPypiPackageVersionCaret('keyring'),
          mutagen: {
            optional: true,
            version: utils.latestPypiPackageVersionCaret('mutagen'),
          },
          paramiko: {
            optional: true,
            version: utils.latestPypiPackageVersionCaret('paramiko'),
          },
          pexpect: {
            optional: true,
            version: utils.latestPypiPackageVersionCaret('pexpect'),
          },
          pillow: {
            optional: true,
            version: utils.latestPypiPackageVersionCaret('pillow'),
          },
          platformdirs: {
            optional: true,
            version: utils.latestPypiPackageVersionCaret('platformdirs'),
          },
          psutil: {
            optional: true,
            version: utils.latestPypiPackageVersionCaret('psutil'),
          },
          pydbus: {
            optional: true,
            platform: 'linux',
            version: utils.latestPypiPackageVersionCaret('pydbus'),
          },
          pygithub: {
            optional: true,
            version: utils.latestPypiPackageVersionCaret('pygithub'),
          },
          pygobject: {
            optional: true,
            platform: 'linux',
            version: utils.latestPypiPackageVersionCaret('pygobject'),
          },
          pyperclip: {
            optional: true,
            version: utils.latestPypiPackageVersionCaret('pyperclip'),
          },
          python: '>=3.10,<3.14',
          'python-xz': {
            optional: true,
            version: utils.latestPypiPackageVersionCaret('python-xz'),
          },
          pyyaml: {
            optional: true,
            version: utils.latestPypiPackageVersionCaret('pyyaml'),
          },
          requests: utils.latestPypiPackageVersionCaret('requests'),
          send2trash: utils.latestPypiPackageVersionCaret('send2trash'),
          soupsieve: {
            optional: true,
            version: utils.latestPypiPackageVersionCaret('soupsieve'),
          },
          unidecode: {
            optional: true,
            version: utils.latestPypiPackageVersionCaret('unidecode'),
          },
          'yt-dlp': {
            optional: true,
            version: utils.latestPypiPackageVersionCaret('yt-dlp'),
          },
        },
        extras: {
          admin: ['paramiko'],
          desktop: ['pydbus', 'pygobject', 'pyperclip'],
          git: ['gitpython', 'pygithub'],
          media: ['mutagen', 'platformdirs'],
          string: ['unidecode', 'pyyaml', 'yt-dlp'],
          wine: ['pexpect', 'platformdirs', 'psutil', 'python-xz'],
          www: ['beautifulsoup4', 'html5lib', 'pillow'],
        },
        group+: {
          dev+: {
            dependencies+: {
              'pydbus-stubs': '^0',
              'types-beautifulsoup4': utils.latestPypiPackageVersionCaret('types-beautifulsoup4'),
              'types-binaryornot': utils.latestPypiPackageVersionCaret('types-binaryornot'),
              'types-paramiko': utils.latestPypiPackageVersionCaret('types-paramiko'),
              'types-pexpect': utils.latestPypiPackageVersionCaret('types-pexpect'),
              'types-pillow': utils.latestPypiPackageVersionCaret('types-pillow'),
              'types-psutil': utils.latestPypiPackageVersionCaret('types-psutil'),
              'types-pyperclip': utils.latestPypiPackageVersionCaret('types-pyperclip'),
              'types-pyyaml': utils.latestPypiPackageVersionCaret('types-pyyaml'),
              'types-requests': utils.latestPypiPackageVersionCaret('types-requests'),
              'types-send2trash': utils.latestPypiPackageVersionCaret('types-send2trash'),
              'types-yt-dlp': utils.latestPypiPackageVersionCaret('types-yt-dlp'),
            },
          },
          tests+: {
            dependencies+: {
              'requests-mock': utils.latestPypiPackageVersionCaret('requests-mock'),
            },
          },
        },
      },
      ruff+: {
        lint+: {
          pylint+: {
            'max-nested-blocks': 6,
            'max-statements': 150,
          },
        },
      },
    },
  },
  copilot: {
    intro: 'Deltona is a collection of uncategorised CLI utilities and Python modules.',
  },
  local exclude_from_all = [
    'clean-old-kernels-modules',
    'connect-g603',
    'inhibit-notifications',
    'kill-gamescope',
    'systemd-reset-tpm-cryptenroll',
    'wait-for-disc',
  ],
  pyinstaller: {
    macos_exclusions: exclude_from_all,
    windows_exclusions: exclude_from_all + [
      'kill-wine',
      'mkwineprefix',
      'set-wine-fonts',
      'unregister-wine-assocs',
      'winegoginstall',
      'wineshell',
    ],
  },
  local apt_packages = ['libcairo2-dev', 'libgirepository-2.0-dev'],
  github+: {
    workflows+: {
      qa+: {
        apt_packages: apt_packages,
      },
      tests+: {
        apt_packages: apt_packages,
      },
    },
  },
  readthedocs+: {
    build+: {
      apt_packages: apt_packages,
      os: 'ubuntu-24.04',
    },
    sphinx+: {
      fail_on_warning: false,
    },
  },
}
