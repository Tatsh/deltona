"""Gmail-related utilities."""

from __future__ import annotations

from collections.abc import Mapping
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlencode, urlparse
import json
import logging
import urllib.error
import urllib.request

if TYPE_CHECKING:
    from collections.abc import Callable

    import niquests

__all__ = ('KEYRING_SERVICE', 'REDIRECT_URI', 'SCOPE', 'GmailAuthorizationError',
           'GmailConfigurationError', 'GmailError', 'archive_github_pull_request_email',
           'authorize', 'get_access_token')

log = logging.getLogger(__name__)

KEYRING_SERVICE = 'deltona:mpr:google'
"""Keyring service the authorized user credential is stored under, keyed on the email address.

:meta hide-value:
"""
REDIRECT_URI = 'http://127.0.0.1:45678'
"""Loopback address Google sends the browser to after consent.

Nothing listens on it. The browser fails to connect and the authorisation code stays visible in
the address bar, which is what makes the flow work when the browser is on another machine.

:meta hide-value:
"""
SCOPE = 'https://www.googleapis.com/auth/gmail.modify'
"""The OAuth scope required to remove the ``INBOX`` label from a thread.

:meta hide-value:
"""

# A rejected or insufficiently scoped token is a setup problem and must stop the run, whereas any
# other status is treated as transient.
_REJECTED_STATUSES = (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN)
_SCOPE_HINT = (' The token was rejected, so the credentials or the granted scope are wrong. The '
               f'scope must include {SCOPE}.')

_API_BASE_URL = 'https://gmail.googleapis.com/gmail/v1/users/me'
_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
_TOKEN_URL = 'https://oauth2.googleapis.com/token'  # ruff:ignore[hardcoded-password-string]


class GmailError(RuntimeError):
    """Raised when the Gmail API or the OAuth token endpoint returns an error."""


class GmailConfigurationError(GmailError):
    """Raised when Gmail support is requested but is not set up correctly."""


class GmailAuthorizationError(GmailConfigurationError):
    """
    Raised when the stored authorisation is refused.

    The OAuth client itself is fine, so authorising again is all that is needed.
    """


async def get_access_token(session: niquests.AsyncSession, *, credentials: str) -> str:
    """
    Exchange a stored authorized user credential for an access token.

    Parameters
    ----------
    session : niquests.AsyncSession
        The session to make the request with.
    credentials : str
        The authorized user JSON as stored in the keyring. Must contain
        ``client_id``, ``client_secret``, and ``refresh_token``.

    Returns
    -------
    str
        The access token.

    Raises
    ------
    GmailAuthorizationError
        If the token endpoint refuses the stored refresh token.
    GmailConfigurationError
        If the credential JSON is unusable.
    """
    try:
        data: Mapping[str, Any] = json.loads(credentials)
    except json.JSONDecodeError as e:
        msg = 'The stored Google credentials are not valid JSON.'
        raise GmailConfigurationError(msg) from e
    # A client secret downloaded from the Google Cloud console nests everything under `installed`
    # or `web`, so unwrap it before looking for the fields.
    for wrapper in ('installed', 'web'):
        if isinstance(data.get(wrapper), Mapping):
            data = data[wrapper]
            break
    try:
        payload = {
            'client_id': data['client_id'],
            'client_secret': data['client_secret'],
            'grant_type': 'refresh_token',
            'refresh_token': data['refresh_token']
        }
    except KeyError as e:
        msg = (f'The stored Google credentials are missing `{e.args[0]}`. The keys present are '
               f'{", ".join(sorted(data)) or "(none)"}. A client secret downloaded from the Google '
               'Cloud console is not enough on its own; an authorized user credential containing '
               'a refresh token is required.')
        raise GmailConfigurationError(msg) from e
    response = await session.post(_TOKEN_URL, data=payload)
    if not response.ok:
        # Google explains itself in the body. Quote it rather than guessing, since one status
        # covers an expired grant, a revoked one, a clock skew, and a mismatched client.
        try:
            body = response.json()
        except ValueError:
            body = None
        detail: Mapping[str, Any] = body if isinstance(body, Mapping) else {}
        # Google ends error_description with a full stop of its own, which would double up.
        reported = str(detail.get('error_description') or detail.get('error') or '').strip(' .')
        detail_text = f': {reported}' if reported else ''
        msg = f'The Google token endpoint returned HTTP {response.status_code}{detail_text}.'
        raise GmailAuthorizationError(msg)
    token = (response.json() or {}).get('access_token')
    if not token:
        msg = 'The Google token endpoint did not return an access token.'
        raise GmailAuthorizationError(msg)
    return str(token)


def authorize(client_secret: str,
              *,
              read_redirect: Callable[[], str],
              notify: Callable[[str], None] | None = None) -> str:
    """
    Run the installed application OAuth flow and return an authorized user credential.

    The consent URL is handed to ``notify`` and the redirected URL is read back
    through ``read_redirect``. Nothing is served locally and no browser is
    started, so the browser may run on a different machine to this code. The
    redirect deliberately points at a loopback address nothing listens on: the
    browser fails to connect, but the authorisation code is in the address bar
    either way, which is what has to be pasted back.

    Parameters
    ----------
    client_secret : str
        The client secret JSON downloaded from the Google Cloud console.
    read_redirect : Callable[[], str]
        Returns the URL the browser was redirected to, as pasted by the user.
    notify : Callable[[str], None] | None
        Called with the consent URL. Defaults to logging it.

    Returns
    -------
    str
        The authorized user JSON to store in the keyring.

    Raises
    ------
    GmailConfigurationError
        If the client secret is unusable, consent does not complete, or Google
        returns no refresh token.
    """
    try:
        raw = json.loads(client_secret)
    except json.JSONDecodeError as e:
        msg = 'The client secret is not valid JSON.'
        raise GmailConfigurationError(msg) from e
    config = raw.get('installed') or raw.get('web') or raw
    try:
        client_id, secret = config['client_id'], config['client_secret']
    except KeyError as e:
        msg = f'The client secret is missing `{e.args[0]}`.'
        raise GmailConfigurationError(msg) from e
    url = f'{_AUTH_URL}?' + urlencode({
        'access_type': 'offline',
        'client_id': client_id,
        'prompt': 'consent',
        'redirect_uri': REDIRECT_URI,
        'response_type': 'code',
        'scope': SCOPE
    })
    message = (f'Open this URL in a browser on any machine:\n\n{url}\n\nAfter granting access the '
               f'browser is sent to {REDIRECT_URI} and fails to connect, which is expected. Copy '
               'the whole address it ended up at and paste it here.')
    if notify is None:
        log.info('%s', message)
    else:
        notify(message)
    received = {k: v[0] for k, v in parse_qs(urlparse(read_redirect().strip()).query).items()}
    if 'code' not in received:
        msg = (f'The pasted URL has no authorisation code in it. It carried '
               f'{", ".join(sorted(received)) or "no query string at all"}.')
        raise GmailConfigurationError(msg)
    request = urllib.request.Request(_TOKEN_URL,
                                     data=urlencode({
                                         'client_id': client_id,
                                         'client_secret': secret,
                                         'code': received['code'],
                                         'grant_type': 'authorization_code',
                                         'redirect_uri': REDIRECT_URI
                                     }).encode(),
                                     headers={'Content-Type': 'application/x-www-form-urlencoded'})
    try:
        # The URL is the module-level token endpoint constant, so the scheme is always HTTPS.
        with urllib.request.urlopen(request) as response:  # ruff:ignore[suspicious-url-open-usage]
            payload = json.load(response)
    except urllib.error.URLError as e:
        msg = f'The Google token endpoint rejected the authorisation code: {e}'
        raise GmailConfigurationError(msg) from e
    if 'refresh_token' not in payload:
        msg = ('Google returned no refresh token. Revoke the application at '
               'https://myaccount.google.com/permissions and authorise again.')
        raise GmailConfigurationError(msg)
    return json.dumps(
        {
            'client_id': client_id,
            'client_secret': secret,
            'refresh_token': payload['refresh_token'],
            'type': 'authorized_user'
        },
        indent=2,
        sort_keys=True)


def _search_query(full_name: str, number: int) -> str:
    # GitHub sets List-ID per repository and suffixes every subject in the thread, including
    # replies, with the pull request number, so together these match any message in the thread
    # without matching the same number in another repository. Searching the root Message-ID
    # <owner/repository/pull/number@github.com> instead would be narrower, not broader: Gmail's
    # rfc822msgid operator matches the Message-ID header only, never the References header that
    # carries that identifier on replies.
    #
    # Deliberately not restricted to the inbox. Gmail searches all mail bar spam and trash, so a
    # thread that was archived earlier is still found and can still be marked read.
    owner, name = full_name.split('/', 1)
    return f'list:{name}.{owner}.github.com subject:"(PR #{number})"'


async def archive_github_pull_request_email(session: niquests.AsyncSession, *, access_token: str,
                                            full_name: str, number: int) -> int:
    """
    Archive and mark read the Gmail threads for a GitHub pull request notification.

    Threads are matched on the ``List-ID`` GitHub sets per repository together
    with the pull request number carried in the subject, so any message in the
    thread is enough to find it. The search covers all mail rather than only the
    inbox, so a thread archived by an earlier run is still found and still gets
    marked read.

    The ``INBOX`` and ``UNREAD`` labels are removed, which is what the Gmail web
    interface calls archiving and marking as read. Removing a label a thread does
    not carry is not an error, so this is safe whatever state the thread is in.
    Messages are not deleted and stay searchable.

    Parameters
    ----------
    session : niquests.AsyncSession
        The session to make requests with.
    access_token : str
        A Gmail API access token with a scope permitting label modification.
    full_name : str
        The repository full name as ``owner/name``.
    number : int
        The pull request number.

    Returns
    -------
    int
        The number of threads archived.

    Raises
    ------
    GmailAuthorizationError
        If Gmail rejects the token, which means the authorisation has lapsed or
        the granted scope is wrong.
    GmailError
        If Gmail returns any other error for the search or for a modification.
    """
    headers = {'Authorization': f'Bearer {access_token}'}
    response = await session.get(f'{_API_BASE_URL}/threads',
                                 headers=headers,
                                 params={'q': _search_query(full_name, number)})
    if not response.ok:
        msg = f'Gmail returned HTTP {response.status_code} searching for PR {number}.'
        if response.status_code in _REJECTED_STATUSES:
            raise GmailAuthorizationError(msg + _SCOPE_HINT)
        raise GmailError(msg)
    threads = (response.json() or {}).get('threads') or []
    archived = 0
    for thread in threads:
        modified = await session.post(f'{_API_BASE_URL}/threads/{thread["id"]}/modify',
                                      headers=headers,
                                      json={'removeLabelIds': ['INBOX', 'UNREAD']})
        if not modified.ok:
            msg = (f'Gmail returned HTTP {modified.status_code} archiving thread '
                   f'`{thread["id"]}`.')
            if modified.status_code in _REJECTED_STATUSES:
                raise GmailAuthorizationError(msg + _SCOPE_HINT)
            raise GmailError(msg)
        archived += 1
    return archived
