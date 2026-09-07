"""Git commands."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path
from time import sleep
from typing import TYPE_CHECKING, Any, NamedTuple, get_args
import getpass
import os
import re
import shutil
import subprocess as sp
import webbrowser

from bascom import setup_logging
import anyio
import click

from deltona.actions import find_retryable_runs, rerun_failed_jobs
from deltona.constants import CONTEXT_SETTINGS
from deltona.git import (
    DEFAULT_SWEEP_SECONDS,
    DEPENDABOT_LOGIN,
    PRE_COMMIT_CI_LOGIN,
    BotMergeError,
    DependabotMergeError,
    PreCommitCIMergeError,
    convert_git_ssh_url_to_https,
    get_github_default_branch,
    github_token,
    merge_dependabot_pull_requests,
    merge_pre_commit_ci_pull_requests,
    store_token,
    token_path,
    watch_and_merge,
)
from deltona.gmail import (
    KEYRING_SERVICE as GMAIL_KEYRING_SERVICE,
    SCOPE as GMAIL_SCOPE,
    GmailAuthorizationError,
    GmailError,
    authorize,
)
from deltona.services import (
    ServiceKind,
    default_service_kind,
    generate_service,
    install_service,
    service_path,
    uninstall_service,
)
from deltona.string import pluralize, slugify

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from git import Repo

    from deltona.actions import RetryCandidate


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


_SERVICE_KINDS = get_args(ServiceKind)
_SERVICE_META = 'deltona.service'


class _ServiceOptions(NamedTuple):
    """How the daemon is installed and run."""

    api_key: str | None = None
    """Token to store for a machine with no keyring."""
    dry_run: bool = False
    """Print the definition instead of writing it."""
    install: bool = False
    """Install the service."""
    kind: ServiceKind | None = None
    """Kind of service manager. Defaults to the one native to this platform."""
    name: str | None = None
    """Service name."""
    no_enable: bool = False
    """Write the definition without starting anything."""
    service_group: str | None = None
    """Group given read access to a stored token."""
    service_user: str | None = None
    """Account a ``systemd-system`` service runs as."""
    sweep: float = DEFAULT_SWEEP_SECONDS
    """Longest wait between passes over every repository."""
    uninstall: bool = False
    """Remove the service."""
    watch: bool = False
    """Keep running rather than making one pass."""


def _collect(ctx: click.Context, param: click.Parameter, value: Any) -> Any:
    # Kept off the command signature, which would otherwise carry eleven more parameters that only
    # ever travel together.
    ctx.meta.setdefault(_SERVICE_META, {})[str(param.name)] = value
    return value


def _service_option(*param_decls: str, **kwargs: Any) -> Callable[..., Any]:
    return click.option(*param_decls, callback=_collect, expose_value=False, **kwargs)


def _service_options(func: Callable[..., None]) -> Callable[..., None]:
    for option in reversed(
        (_service_option('--api-key',
                         envvar='DELTONA_GITHUB_API_KEY',
                         help='GitHub token to store for a machine with no keyring, readable only'
                         ' by the account and group the service runs as. Giving it as'
                         ' DELTONA_GITHUB_API_KEY keeps it out of the shell history.'),
         _service_option('--install-service',
                         'install',
                         is_flag=True,
                         help='Install a service that merges whenever a pull request is notified'
                         ' about, then exit.'),
         _service_option('-k',
                         '--kind',
                         type=click.Choice(_SERVICE_KINDS),
                         help='Service manager to target. Defaults to the one native to this'
                         ' platform.'),
         _service_option('--dry-run',
                         is_flag=True,
                         help='Print what would be written or removed instead of doing it.'),
         _service_option('--name',
                         help='Service name. Defaults to a name based on the command and'
                         ' --username.'),
         _service_option('--no-enable',
                         is_flag=True,
                         help='Write the service definition without starting anything.'),
         _service_option('--service-group', help='Group given read access to the stored token.'),
         _service_option('--service-user', help='Account a systemd-system service runs as.'),
         _service_option('--sweep',
                         default=DEFAULT_SWEEP_SECONDS,
                         show_default=True,
                         type=float,
                         help='Longest wait in seconds between passes over every repository.'),
         _service_option('--uninstall-service',
                         'uninstall',
                         is_flag=True,
                         help='Remove the installed service and exit.'),
         _service_option('-w',
                         '--watch',
                         is_flag=True,
                         help='Keep running, merging whenever the bot opens a pull request.'))):
        func = option(func)
    return func


def _service_settings() -> _ServiceOptions:
    return _ServiceOptions(**click.get_current_context().meta.get(_SERVICE_META, {}))


def _service_name(name: str | None, program: str, username: str) -> str:
    # The username is part of the name so that one machine can run a service per GitHub account.
    return name or f'{program}-{slugify(username)}'


def _daemon_command(program: str, username: str, *, forwarded: Mapping[str, Any],
                    sweep: float) -> list[str]:
    # The console script name rather than whatever argv[0] happened to be, so that the definition
    # does not depend on how the command that wrote it was invoked.
    command = [shutil.which(program) or program, '--watch', '-u', username, '--sweep', str(sweep)]
    # A match statement reads better here, but yapf and Ruff disagree about the spacing of the
    # `False | None` pattern, so one of them rejects whatever the other writes.
    for flag, value in sorted(forwarded.items()):
        if value is True:
            command.append(flag)
        elif isinstance(value, tuple):
            for item in value:
                command += [flag, str(item)]
        elif value is not None and value is not False:
            command += [flag, str(value)]
    return command


def _remove_service(kind: ServiceKind, name: str, *, dry_run: bool) -> None:
    if dry_run:
        click.echo(f'Would remove {service_path(kind, name)}.')
        return
    if (removed := uninstall_service(kind, name)) is None:
        click.echo(f'No {kind} service named {name}.', err=True)
        raise click.exceptions.Exit(1)
    click.echo(f'Removed {removed}.')


def _resolve_service_token(username: str, kind: ServiceKind, service: _ServiceOptions) -> None:
    if service.api_key:
        if service.dry_run:
            click.echo(f'Would store the token at {token_path(username, kind)}.', err=True)
            return
        store_token(service.api_key,
                    username,
                    kind,
                    group=service.service_group,
                    user=service.service_user)
        return
    if github_token(username, kind) is None:
        click.echo(
            f'No token for {username} in the keyring or at {token_path(username, kind)}. Pass'
            ' --api-key to store one.',
            err=True)
        raise click.Abort


def _add_service(program: str, username: str, kind: ServiceKind, name: str, *,
                 forwarded: Mapping[str, Any], service: _ServiceOptions) -> None:
    _resolve_service_token(username, kind, service)
    command = _daemon_command(program, username, forwarded=forwarded, sweep=service.sweep)
    description = f'Merge bot pull requests on GitHub for {username}.'
    if service.dry_run:
        click.echo(
            generate_service(kind,
                             name,
                             command,
                             description=description,
                             user=service.service_user))
        return
    path = install_service(kind,
                           name,
                           command,
                           description=description,
                           enable=not service.no_enable,
                           user=service.service_user)
    click.echo(f'Installed {path}.')


def _handle_service(program: str, username: str, *, forwarded: Mapping[str, Any],
                    service: _ServiceOptions) -> bool:
    """
    Install or remove the service, if either was asked for.

    Parameters
    ----------
    program : str
        Console script the service runs.
    username : str
        Keyring key the service reads its token under.
    forwarded : Mapping[str, Any]
        Options passed on to the daemon, keyed on the flag that carries them.
    service : _ServiceOptions
        How the service is installed and run.

    Returns
    -------
    bool
        Whether the command has done its work and should stop.
    """  # noqa: DOC501
    if service.install and service.uninstall:
        msg = '--install-service and --uninstall-service cannot both be given.'
        raise click.UsageError(msg)
    if not service.install and not service.uninstall:
        # These do nothing on their own, and --dry-run silently meaning "merge for real" is the
        # worst of the ways that could be taken.
        if given := [
                flag
                for flag, value in (('--api-key', service.api_key), ('--dry-run', service.dry_run),
                                    ('--name', service.name), ('--no-enable', service.no_enable),
                                    ('--service-group', service.service_group),
                                    ('--service-user', service.service_user)) if value
        ]:
            msg = (f'{", ".join(given)} {pluralize(len(given), "is", "are")} only used with'
                   ' --install-service.')
            raise click.UsageError(msg)
        return False
    kind = service.kind or default_service_kind()
    name = _service_name(service.name, program, username)
    try:
        if service.uninstall:
            _remove_service(kind, name, dry_run=service.dry_run)
        else:
            _add_service(program, username, kind, name, forwarded=forwarded, service=service)
    except sp.CalledProcessError as e:
        click.echo(f'Failed to {"remove" if service.uninstall else "enable"} {name}.', err=True)
        raise click.Abort from e
    except FileNotFoundError as e:
        click.echo(f'{e.filename} is not installed.', err=True)
        raise click.Abort from e
    except (LookupError, PermissionError) as e:
        click.echo(str(e), err=True)
        raise click.Abort from e
    return True


def _run_merge_command(merge: Callable[..., Awaitable[None]], error_class: type[BotMergeError], *,
                       archive_email: bool, base_url: str | None, bot_login: str, concurrency: int,
                       delay: float, email: str | None, mark_notifications_done: bool,
                       max_concurrent_http_requests: int, program: str, repos: tuple[str, ...],
                       username: str) -> None:
    service = _service_settings()
    if _handle_service(program,
                       username,
                       forwarded={
                           '-A': archive_email,
                           '-b': base_url,
                           '-E': email,
                           '-M': max_concurrent_http_requests,
                           '-N': mark_notifications_done,
                           '-r': repos or None,
                           '--concurrency': concurrency,
                           '--delay': delay
                       },
                       service=service):
        return
    if not (token := github_token(username, service.kind)):
        click.echo('No token.', err=True)
        raise click.Abort

    def make_runner(current_repos: tuple[str, ...] | None) -> Callable[[], Awaitable[None]]:
        return partial(merge,
                       archive_email=archive_email,
                       base_url=base_url,
                       concurrency=concurrency,
                       email=email,
                       mark_notifications_done=mark_notifications_done,
                       max_concurrent_http_requests=max_concurrent_http_requests,
                       repos=current_repos,
                       token=token)

    if service.watch:
        anyio.run(
            partial(watch_and_merge,
                    make_runner(repos or None),
                    base_url=base_url,
                    bot_login=bot_login,
                    sweep=service.sweep,
                    token=token))
        return
    _run_bot_merge_or_abort(make_runner, repos or None, error_class, delay, email)


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
@_service_options
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
    """
    Merge pull requests made by Dependabot on GitHub.

    --watch keeps running and merges whenever GitHub notifies about a pull request, and sweeps
    every repository every --sweep seconds regardless. A notification arrives only for a repository
    the account is subscribed to and has new pull request notifications enabled for, so the sweep
    is what makes the daemon correct rather than merely quick.
    """
    setup_logging(debug=debug,
                  loggers={
                      'deltona': {},
                      'keyring': {},
                      'urllib3': {},
                      'urllib3.util.retry': {
                          'level': 'WARNING'
                      }
                  })
    _run_merge_command(merge_dependabot_pull_requests,
                       DependabotMergeError,
                       archive_email=archive_email,
                       base_url=base_url,
                       bot_login=DEPENDABOT_LOGIN,
                       concurrency=concurrency,
                       delay=delay,
                       email=email,
                       mark_notifications_done=mark_notifications_done,
                       max_concurrent_http_requests=max_concurrent_http_requests,
                       program='merge-dependabot-prs',
                       repos=repos,
                       username=username)


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
@_service_options
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
    """
    Merge pull requests made by pre-commit.ci on GitHub.

    --watch keeps running and merges whenever GitHub notifies about a pull request, and sweeps
    every repository every --sweep seconds regardless. A notification arrives only for a repository
    the account is subscribed to and has new pull request notifications enabled for, so the sweep
    is what makes the daemon correct rather than merely quick.
    """
    setup_logging(debug=debug, loggers={'deltona': {}, 'keyring': {}, 'urllib3': {}})
    _run_merge_command(merge_pre_commit_ci_pull_requests,
                       PreCommitCIMergeError,
                       archive_email=archive_email,
                       base_url=base_url,
                       bot_login=PRE_COMMIT_CI_LOGIN,
                       concurrency=concurrency,
                       delay=delay,
                       email=email,
                       mark_notifications_done=mark_notifications_done,
                       max_concurrent_http_requests=max_concurrent_http_requests,
                       program='merge-pre-commit-prs',
                       repos=repos,
                       username=username)


def _describe(candidate: RetryCandidate) -> str:
    return (f'{candidate.repo} run {candidate.run_id} ({candidate.workflow or "unnamed"}): '
            f'job {candidate.job or "unnamed"}, step {candidate.step!r}. {candidate.rule.reason}')


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option('-b', '--base-url', help='Base URL for enterprise.')
@click.option('--concurrency',
              type=int,
              default=4,
              help='Maximum number of repositories examined in parallel.')
@click.option('-d', '--debug', is_flag=True, help='Enable debug output.')
@click.option('-n',
              '--dry-run',
              is_flag=True,
              help='Only report what would be started again, without starting anything.')
@click.option('-m',
              '--max-attempts',
              type=int,
              default=2,
              help='Leave a run alone once it has been attempted this many times.')
@click.option('-r',
              '--repo',
              'repos',
              multiple=True,
              help='Specific repository to examine as NAME or OWNER/NAME. '
              'May be passed multiple times.')
@click.option('-s',
              '--since',
              default=None,
              help='Only consider runs created on or after this date, as YYYY-MM-DD. '
              'Defaults to a day ago.')
@click.option('-u', '--username', default=getpass.getuser(), help='Username.')
@click.option('-y',
              '--yes',
              expose_value=False,
              is_flag=True,
              help='Accepted and ignored. Starting the runs again is already the default.')
def retry_gh_jobs_main(username: str,
                       repos: tuple[str, ...] = (),
                       base_url: str | None = None,
                       concurrency: int = 4,
                       max_attempts: int = 2,
                       since: str | None = None,
                       *,
                       debug: bool = False,
                       dry_run: bool = False) -> None:
    """
    Run failed GitHub Actions jobs again where the failure was not the code's fault.

    Only failures matching a known transient signature are considered, such as a Coveralls server
    error or a package source refusing a request. A test failure, a type error, or anything under
    Dependabot is left alone.

    Matching runs are started again unless --dry-run is passed.
    """  # ruff:ignore[docstring-missing-exception]
    import keyring  # ruff:ignore[import-outside-top-level]

    setup_logging(debug=debug, loggers={'deltona': {}, 'keyring': {}, 'urllib3': {}})
    if not (token := keyring.get_password('tmu-github-api', username)):
        click.echo('No token.', err=True)
        raise click.Abort
    if since is None:
        since = (datetime.now(tz=timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%d')
    candidates = anyio.run(
        partial(find_retryable_runs,
                base_url=base_url,
                concurrency=concurrency,
                max_attempts=max_attempts,
                repos=repos or None,
                since=since,
                token=token))
    if not candidates:
        click.echo('No failed runs worth starting again.')
        return
    for candidate in candidates:
        click.echo(_describe(candidate))
    count = len(candidates)
    if dry_run:
        click.echo(f'\n{count} {pluralize(count, "run")} would be started again. '
                   'Drop --dry-run to do it.')
        return
    started = anyio.run(
        partial(rerun_failed_jobs, base_url=base_url, candidates=candidates, token=token))
    click.echo(f'\nStarted {started} of {count} {pluralize(count, "run")} again.')
    if started != count:
        raise click.exceptions.Exit(1)
