"""See https://www.sphinx-doc.org/en/master/usage/configuration.html."""
from __future__ import annotations

from datetime import UTC, datetime
from operator import itemgetter
from pathlib import Path
import sys

import tomlkit

with (Path(__file__).parent.parent / 'pyproject.toml').open(newline='\n', encoding='utf-8') as f:
    project_ = tomlkit.load(f).unwrap()['project']
    authors_list, name, version = itemgetter('authors', 'name', 'version')(project_)
authors = [f'{d["name"]} <{d["email"]}>' for d in authors_list]
# region Path setup
# If extensions (or modules to document with autodoc) are in another directory, add these
# directories to sys.path here. If the directory is relative to the documentation root, use
# str(Path().parent.parent) to make it absolute, like shown here.
sys.path.insert(0, str(Path(__file__).parent.parent))
# endregion
author = f'{authors_list[0]["name"]} <{authors_list[0]["email"]}>'
copyright = str(datetime.now(UTC).year)  # noqa: A001
project = name
release = f'v{version}'
extensions = [
    'hoverxref.extension', 'sphinx.ext.autodoc', 'sphinx.ext.intersphinx', 'sphinx.ext.napoleon',
    'sphinx_datatables', 'sphinx_immaterial', 'sphinxcontrib.autodoc_pydantic',
    'sphinxcontrib.jquery'
]
extensions += ['sphinx_click']
datatables_class = 'sphinx-datatable'
datatables_options = {'paging': 0}
datatables_version = '1.13.4'
html_theme = 'sphinx_immaterial'
html_theme_options = {
    'edit_uri': '/tree/master/docs',
    'features': [
        'announce.dismiss', 'content.action.edit', 'content.action.view', 'content.code.copy',
        'content.tabs.link', 'content.tooltips', 'navigation.expand', 'navigation.footer',
        'navigation.sections', 'navigation.top', 'search.share', 'search.suggest', 'toc.follow',
        'toc.sticky'
    ],
    'globaltoc_collapse': True,
    'icon': {
        'edit': 'material/file-edit-outline',
        'repo': 'fontawesome/brands/gitlab'
    },
    'palette': [{
        'media': '(prefers-color-scheme)',
        'toggle': {
            'icon': 'material/brightness-auto',
            'name': 'Switch to light mode'
        }
    }, {
        'accent': 'light-blue',
        'media': '(prefers-color-scheme: light)',
        'primary': 'teal',
        'scheme': 'default',
        'toggle': {
            'icon': 'material/lightbulb',
            'name': 'Switch to dark mode'
        }
    }, {
        'accent': 'blue',
        'media': '(prefers-color-scheme: dark)',
        'primary': 'black',
        'scheme': 'slate',
        'toggle': {
            'icon': 'material/lightbulb-outline',
            'name': 'Switch to system preference'
        }
    }],
    'repo_name': 'deltona',
    'repo_url': 'https://github.com/Tatsh/deltona',
    'site_url': 'https://deltona.readthedocs.org',
    'toc_title_is_page_title': True
}
intersphinx_mapping = {
    'python': ('https://docs.python.org/3', None),
    'bascom': ('https://bascom.readthedocs.io/en/latest/', None),
    'binaryornot': ('https://binaryornot.readthedocs.io/en/latest/', None),
    'bs4': ('https://www.crummy.com/software/BeautifulSoup/bs4/doc/', None),
    'click': ('https://click.palletsprojects.com/en/latest/', None),
    'gitpython': ('https://gitpython.readthedocs.io/en/stable/', None),
    'keyring': ('https://keyring.readthedocs.io/en/latest/', None),
    'mutagen': ('https://mutagen.readthedocs.io/en/latest/', None),
    'paramiko': ('https://paramiko.org/', None),
    'pexpect': ('https://pexpect.readthedocs.io/en/stable/', None),
    'pillow': ('https://pillow.readthedocs.io/en/stable/', None),
    'platformdirs': ('https://platformdirs.readthedocs.io/en/latest/', None),
    'psutil': ('https://psutil.readthedocs.io/en/latest/', None),
    'pydbus': ('https://pydbus.readthedocs.io/en/latest/', None),
    'pygithub': ('https://pygithub.readthedocs.io/en/latest/', None),
    'pygobject': ('https://pygobject.readthedocs.io/en/latest/', None),
    'pyperclip': ('https://pyperclip.readthedocs.io/en/latest/', None),
    'requests': ('https://requests.readthedocs.io/en/latest/', None),
    'typing-extensions': ('https://typing-extensions.readthedocs.io/en/latest/', None),
}
