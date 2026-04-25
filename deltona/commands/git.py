"""Git commands."""

from __future__ import annotations

from functools import partial
from time import sleep
from typing import TYPE_CHECKING
import getpass
import os
import re
import webbrowser

from bascom import setup_logging
from deltona.constants import CONTEXT_SETTINGS
from deltona.git import (
    DependabotMergeError,
    convert_git_ssh_url_to_https,
    get_github_default_branch,
    merge_dependabot_pull_requests,
)
import anyio
import click

if TYPE_CHECKING:
    from git import Repo


def _get_git_repo() -> Repo:  # pragma: no cover
    from git import Repo  # noqa: PLC0415

    return Repo(search_parent_directories=True)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('origin_name', metavar='ORIGIN_NAME', default='origin')
@click.option('-b', '--base-url', help='Base URL for enterprise.')
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
@click.option('-u', '--username', default=getpass.getuser(), help='Username (passed to keyring).')
def git_checkout_default_branch_main(username: str,
                                     base_url: str | None = None,
                                     origin_name: str = 'origin',
                                     *,
                                     debug: bool = False) -> None:
    """
    Checkout to the default branch.

    For repositories whose origin is on GitHub only.

    To set a token, ``keyring set tmu-github-api "${USER}"``. The token must have
    access to the public_repo or repo scope.
    """  # noqa: DOC501
    import keyring  # noqa: PLC0415

    setup_logging(debug=debug, loggers={'deltona': {}, 'github': {}, 'keyring': {}})
    token = keyring.get_password('tmu-github-api', username)
    if not token:
        click.echo('No token.', err=True)
        raise click.Abort
    repo = _get_git_repo()
    default_branch = get_github_default_branch(repo=repo,
                                               base_url=base_url,
                                               token=token,
                                               origin_name=origin_name)
    next(b for b in repo.heads if b.name == default_branch).checkout()


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('origin_name', metavar='ORIGIN_NAME', default='origin')
@click.option('-b', '--base-url', help='Base URL for enterprise.')
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
@click.option('-u', '--username', default=getpass.getuser(), help='Username (passed to keyring).')
@click.option('-r',
              '--remote',
              is_flag=True,
              help='Rebase with the origin copy of the default branch.')
def git_rebase_default_branch_main(username: str,
                                   base_url: str | None = None,
                                   origin_name: str = 'origin',
                                   *,
                                   debug: bool = False,
                                   remote: bool = False) -> None:
    """
    Rebase the current head with the default branch.

    For repositories whose origin is on GitHub only.

    To set a token, ``keyring set tmu-github-api "${USER}"``. The token must have
    access to the public_repo or repo scope.
    """  # noqa: DOC501
    import keyring  # noqa: PLC0415

    setup_logging(debug=debug, loggers={'deltona': {}, 'github': {}, 'keyring': {}})
    token = keyring.get_password('tmu-github-api', username)
    if not token:
        click.echo('No token.', err=True)
        raise click.Abort
    repo = _get_git_repo()
    default_branch = get_github_default_branch(repo=repo,
                                               base_url=base_url,
                                               token=token,
                                               origin_name=origin_name)
    repo.git.rebase(f'{origin_name}/{default_branch}' if remote else default_branch)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('name', default='origin')
def git_open_main(name: str = 'origin') -> None:
    """Open assumed repository web representation (GitHub, GitLab, etc) based on the origin."""
    url = _get_git_repo().remote(name).url
    if re.search(r'^https?://', url):
        webbrowser.open(url)
        return
    webbrowser.open(convert_git_ssh_url_to_https(url))


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option('-b', '--base-url', help='Base URL for enterprise.')
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
@click.option('--delay', type=float, default=120, help='Delay in seconds between attempts.')
@click.option('--concurrency',
              type=int,
              default=os.cpu_count() or 1,
              help='Maximum number of repositories processed in parallel.')
@click.option('-M',
              '--max-concurrent-http-requests',
              type=int,
              default=3,
              help='Hard cap on simultaneous in-flight HTTP requests.')
@click.option('-r',
              '--repo',
              'repos',
              multiple=True,
              help='Specific repository to process as NAME or OWNER/NAME. '
              'May be passed multiple times.')
@click.option('-u', '--username', default=getpass.getuser(), help='Username.')
def merge_dependabot_prs_main(username: str,
                              repos: tuple[str, ...] = (),
                              base_url: str | None = None,
                              delay: float = 120,
                              concurrency: int = 1,
                              max_concurrent_http_requests: int = 3,
                              *,
                              debug: bool = False) -> None:
    """Merge pull requests made by Dependabot on GitHub."""  # noqa: DOC501
    import keyring  # noqa: PLC0415

    setup_logging(debug=debug, loggers={'deltona': {}, 'github': {}, 'keyring': {}})
    if not (token := keyring.get_password('tmu-github-api', username)):
        click.echo('No token.', err=True)
        raise click.Abort
    runner = partial(merge_dependabot_pull_requests,
                     base_url=base_url,
                     concurrency=concurrency,
                     max_concurrent_http_requests=max_concurrent_http_requests,
                     repos=repos or None,
                     token=token)
    while True:
        try:
            anyio.run(runner)
            break
        except DependabotMergeError as e:
            click.echo('Repositories with remaining Dependabot pull requests:')
            for full_name in sorted(e.remaining):
                click.echo(f'  {full_name}: {e.remaining[full_name]} pull request(s)')
            click.echo(f'Sleeping for {delay} seconds.')
            sleep(delay)
