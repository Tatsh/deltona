"""Git commands."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from time import sleep
from typing import TYPE_CHECKING
import getpass
import os
import re
import webbrowser

from bascom import setup_logging
from deltona.constants import CONTEXT_SETTINGS
from deltona.git import (
    BotMergeError,
    DependabotMergeError,
    PreCommitCIMergeError,
    convert_git_ssh_url_to_https,
    get_github_default_branch,
    merge_dependabot_pull_requests,
    merge_pre_commit_ci_pull_requests,
)
from deltona.gmail import (
    KEYRING_SERVICE as GMAIL_KEYRING_SERVICE,
    SCOPE as GMAIL_SCOPE,
    GmailAuthorizationError,
    GmailError,
    authorize,
)
from deltona.string import pluralize
import anyio
import click

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from git import Repo


def _get_git_repo() -> Repo:  # pragma: no cover
    from git import Repo  # ruff:ignore[import-outside-top-level]

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
    """  # ruff:ignore[docstring-missing-exception]
    import keyring  # ruff:ignore[import-outside-top-level]

    setup_logging(debug=debug, loggers={'deltona': {}, 'keyring': {}, 'urllib3': {}})
    token = keyring.get_password('tmu-github-api', username)
    if not token:
        click.echo('No token.', err=True)
        raise click.Abort
    repo = _get_git_repo()
    default_branch = anyio.run(
        partial(get_github_default_branch,
                base_url=base_url,
                origin_name=origin_name,
                repo=repo,
                token=token))
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
    """  # ruff:ignore[docstring-missing-exception]
    import keyring  # ruff:ignore[import-outside-top-level]

    setup_logging(debug=debug, loggers={'deltona': {}, 'gidgethub': {}, 'keyring': {}})
    token = keyring.get_password('tmu-github-api', username)
    if not token:
        click.echo('No token.', err=True)
        raise click.Abort
    repo = _get_git_repo()
    default_branch = anyio.run(
        partial(get_github_default_branch,
                base_url=base_url,
                origin_name=origin_name,
                repo=repo,
                token=token))
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


def _run_bot_merge_with_retry(make_runner: Callable[[tuple[str, ...] | None],
                                                    Callable[[], Awaitable[None]]],
                              initial_repos: tuple[str, ...] | None,
                              error_class: type[BotMergeError], delay: float) -> None:
    repos = initial_repos
    while True:
        try:
            anyio.run(make_runner(repos))
            break
        except error_class as e:
            click.echo(f'Repositories with remaining {e.bot_label} pull requests:')
            for full_name in sorted(e.remaining):
                count = e.remaining[full_name]
                click.echo(f'  {full_name}: {count} {pluralize(count, "pull request")}')
            click.echo(f'Sleeping for {delay} seconds.')
            sleep(delay)
            repos = tuple(sorted(e.remaining))


def _gmail_reauthorize_help(command: str, email: str) -> str:
    return ('Authorise again with:\n\n'
            f'  {command} --authorize-gmail --email {email}\n\n'
            'The OAuth client already stored for that address is reused, so there is nothing to '
            'create or download. Consent expires after seven days while the publishing status of '
            'the application is Testing; publishing it in the Google Cloud console stops that.')


def _gmail_setup_help(command: str, email: str) -> str:
    return (f'Gmail archiving has never been set up for {email}. Once only:\n\n'
            '  1. In the Google Cloud console, enable the Gmail API for a project.\n'
            f'  2. Configure the OAuth consent screen and add the scope {GMAIL_SCOPE}.\n'
            '     Publish the application, otherwise consent expires after seven days.\n'
            '  3. Create an OAuth client ID of type "Desktop app" and download its JSON.\n\n'
            'Then authorise with:\n\n'
            f'  {command} --authorize-gmail --client-secret PATH --email {email}\n\n'
            'Later authorisations need only --authorize-gmail --email, since the client is '
            'stored.')


def _authorize_gmail(ctx: click.Context, _param: click.Parameter,
                     value: bool) -> None:  # noqa: FBT001
    import keyring  # ruff:ignore[import-outside-top-level]

    if not value or ctx.resilient_parsing:
        return
    setup_logging(debug=ctx.params.get('debug', False), loggers={'deltona': {}, 'keyring': {}})
    client_secret: Path | None = ctx.params.get('client_secret')
    if not (email := ctx.params.get('email')):
        msg = '--authorize-gmail requires --email.'
        raise click.UsageError(msg, ctx=ctx)
    # Re-authorising reuses the client already stored beside the refresh token. Only the very
    # first authorisation needs the JSON from the Google Cloud console.
    client = (client_secret.read_text() if client_secret else keyring.get_password(
        GMAIL_KEYRING_SERVICE, email))
    if not client:
        msg = (f'No OAuth client is stored for {email}, so --client-secret is required.\n\n'
               f'{_gmail_setup_help(ctx.command_path, email)}')
        raise click.ClickException(msg)
    try:
        credentials = authorize(client,
                                notify=click.echo,
                                read_redirect=partial(click.prompt, '\nPasted URL'))
    except GmailError as e:
        raise click.ClickException(str(e)) from e
    keyring.set_password(GMAIL_KEYRING_SERVICE, email, credentials)
    click.echo(f'Stored Google credentials for {email}.')
    ctx.exit()


def _run_bot_merge_or_abort(make_runner: Callable[[tuple[str, ...] | None],
                                                  Callable[[], Awaitable[None]]],
                            initial_repos: tuple[str, ...] | None, error_class: type[BotMergeError],
                            delay: float, email: str | None) -> None:
    try:
        _run_bot_merge_with_retry(make_runner, initial_repos, error_class, delay)
    except GmailError as e:
        command = click.get_current_context().command_path
        address = email or 'ADDRESS'
        # An OAuth client is already stored whenever the authorisation itself was refused, so
        # nothing has to be created again.
        help_text = (_gmail_reauthorize_help(command, address) if isinstance(
            e, GmailAuthorizationError) else _gmail_setup_help(command, address))
        click.echo(f'{e}\n\n{help_text}', err=True)
        raise click.Abort from e


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option('-A',
              '--archive-email',
              is_flag=True,
              help='Archive the Gmail thread for each merged pull request.')
@click.option('--authorize-gmail',
              callback=_authorize_gmail,
              expose_value=False,
              is_flag=True,
              help='Only authorise Gmail access and store the credentials, then exit.')
@click.option('-b', '--base-url', help='Base URL for enterprise.')
@click.option('--client-secret',
              is_eager=True,
              type=click.Path(dir_okay=False, exists=True, path_type=Path),
              help='Client secret JSON from the Google Cloud console, for --authorize-gmail.')
@click.option('-d', '--debug', is_eager=True, is_flag=True, help='Enable debug output.')
@click.option('--delay', type=float, default=120, help='Delay in seconds between attempts.')
@click.option('-E',
              '--email',
              is_eager=True,
              help='Email address to archive mail for. Defaults to the GitHub account address.')
@click.option('--concurrency',
              type=int,
              default=os.cpu_count() or 1,
              help='Maximum number of repositories processed in parallel.')
@click.option('-M',
              '--max-concurrent-http-requests',
              type=int,
              default=3,
              help='Hard cap on simultaneous in-flight HTTP requests.')
@click.option('-N',
              '--mark-notifications-done',
              is_flag=True,
              help='Mark the GitHub notification for each merged pull request as done.')
@click.option('-r',
              '--repo',
              'repos',
              multiple=True,
              help='Specific repository to process as NAME or OWNER/NAME. '
              'May be passed multiple times.')
@click.option('-u', '--username', default=getpass.getuser(), help='Username.')
def merge_dependabot_prs_main(
        username: str,
        repos: tuple[str, ...] = (),
        base_url: str | None = None,
        delay: float = 120,
        concurrency: int = 1,
        max_concurrent_http_requests: int = 3,
        email: str | None = None,
        # Consumed by the --authorize-gmail callback.
        client_secret: Path | None = None,  # ruff:ignore[unused-function-argument]
        *,
        archive_email: bool = False,
        debug: bool = False,
        mark_notifications_done: bool = False) -> None:
    """Merge pull requests made by Dependabot on GitHub."""  # ruff:ignore[docstring-missing-exception]
    import keyring  # ruff:ignore[import-outside-top-level]

    setup_logging(debug=debug,
                  loggers={
                      'deltona': {},
                      'keyring': {},
                      'urllib3': {},
                      'urllib3.util.retry': {
                          'level': 'WARNING'
                      }
                  })
    if not (token := keyring.get_password('tmu-github-api', username)):
        click.echo('No token.', err=True)
        raise click.Abort

    def make_runner(current_repos: tuple[str, ...] | None) -> Callable[[], Awaitable[None]]:
        return partial(merge_dependabot_pull_requests,
                       archive_email=archive_email,
                       base_url=base_url,
                       concurrency=concurrency,
                       email=email,
                       mark_notifications_done=mark_notifications_done,
                       max_concurrent_http_requests=max_concurrent_http_requests,
                       repos=current_repos,
                       token=token)

    _run_bot_merge_or_abort(make_runner, repos or None, DependabotMergeError, delay, email)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option('-A',
              '--archive-email',
              is_flag=True,
              help='Archive the Gmail thread for each merged pull request.')
@click.option('--authorize-gmail',
              callback=_authorize_gmail,
              expose_value=False,
              is_flag=True,
              help='Only authorise Gmail access and store the credentials, then exit.')
@click.option('-b', '--base-url', help='Base URL for enterprise.')
@click.option('--client-secret',
              is_eager=True,
              type=click.Path(dir_okay=False, exists=True, path_type=Path),
              help='Client secret JSON from the Google Cloud console, for --authorize-gmail.')
@click.option('-d', '--debug', is_eager=True, is_flag=True, help='Enable debug output.')
@click.option('--delay', type=float, default=120, help='Delay in seconds between attempts.')
@click.option('-E',
              '--email',
              is_eager=True,
              help='Email address to archive mail for. Defaults to the GitHub account address.')
@click.option('--concurrency',
              type=int,
              default=os.cpu_count() or 1,
              help='Maximum number of repositories processed in parallel.')
@click.option('-M',
              '--max-concurrent-http-requests',
              type=int,
              default=3,
              help='Hard cap on simultaneous in-flight HTTP requests.')
@click.option('-N',
              '--mark-notifications-done',
              is_flag=True,
              help='Mark the GitHub notification for each merged pull request as done.')
@click.option('-r',
              '--repo',
              'repos',
              multiple=True,
              help='Specific repository to process as NAME or OWNER/NAME. '
              'May be passed multiple times.')
@click.option('-u', '--username', default=getpass.getuser(), help='Username.')
def merge_pre_commit_ci_prs_main(
        username: str,
        repos: tuple[str, ...] = (),
        base_url: str | None = None,
        delay: float = 120,
        concurrency: int = 1,
        max_concurrent_http_requests: int = 3,
        email: str | None = None,
        # Consumed by the --authorize-gmail callback.
        client_secret: Path | None = None,  # ruff:ignore[unused-function-argument]
        *,
        archive_email: bool = False,
        debug: bool = False,
        mark_notifications_done: bool = False) -> None:
    """Merge pull requests made by pre-commit.ci on GitHub."""  # ruff:ignore[docstring-missing-exception]
    import keyring  # ruff:ignore[import-outside-top-level]

    setup_logging(debug=debug, loggers={'deltona': {}, 'keyring': {}, 'urllib3': {}})
    if not (token := keyring.get_password('tmu-github-api', username)):
        click.echo('No token.', err=True)
        raise click.Abort

    def make_runner(current_repos: tuple[str, ...] | None) -> Callable[[], Awaitable[None]]:
        return partial(merge_pre_commit_ci_pull_requests,
                       archive_email=archive_email,
                       base_url=base_url,
                       concurrency=concurrency,
                       email=email,
                       mark_notifications_done=mark_notifications_done,
                       max_concurrent_http_requests=max_concurrent_http_requests,
                       repos=current_repos,
                       token=token)

    _run_bot_merge_or_abort(make_runner, repos or None, PreCommitCIMergeError, delay, email)
