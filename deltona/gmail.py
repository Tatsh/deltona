"""Gmail-related utilities."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
import json
import logging

if TYPE_CHECKING:
    from collections.abc import Mapping

    import niquests

__all__ = ('GmailError', 'archive_github_pull_request_email', 'get_access_token')

log = logging.getLogger(__name__)

_API_BASE_URL = 'https://gmail.googleapis.com/gmail/v1/users/me'
_TOKEN_URL = 'https://oauth2.googleapis.com/token'  # noqa: S105


class GmailError(RuntimeError):
    """Raised when the Gmail API or the OAuth token endpoint returns an error."""


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
    GmailError
        If the credential JSON is unusable or the token endpoint fails.
    """
    try:
        data: Mapping[str, Any] = json.loads(credentials)
    except json.JSONDecodeError as e:
        msg = 'The stored Google credentials are not valid JSON.'
        raise GmailError(msg) from e
    try:
        payload = {
            'client_id': data['client_id'],
            'client_secret': data['client_secret'],
            'grant_type': 'refresh_token',
            'refresh_token': data['refresh_token']
        }
    except KeyError as e:
        msg = f'The stored Google credentials are missing `{e.args[0]}`.'
        raise GmailError(msg) from e
    response = await session.post(_TOKEN_URL, data=payload)
    if not response.ok:
        msg = f'The Google token endpoint returned HTTP {response.status_code}.'
        raise GmailError(msg)
    token = (response.json() or {}).get('access_token')
    if not token:
        msg = 'The Google token endpoint did not return an access token.'
        raise GmailError(msg)
    return str(token)


def _search_query(full_name: str, number: int) -> str:
    # GitHub sets List-ID per repository and suffixes every subject in the thread, including
    # replies, with the pull request number, so together these match any message in the thread
    # without matching the same number in another repository. Searching the root Message-ID
    # <owner/repository/pull/number@github.com> instead would be narrower, not broader: Gmail's
    # rfc822msgid operator matches the Message-ID header only, never the References header that
    # carries that identifier on replies.
    owner, name = full_name.split('/', 1)
    return f'list:{name}.{owner}.github.com subject:"(PR #{number})"'


async def archive_github_pull_request_email(session: niquests.AsyncSession, *, access_token: str,
                                            full_name: str, number: int) -> int:
    """
    Archive the Gmail threads for a GitHub pull request notification.

    Threads are matched on the ``List-ID`` GitHub sets per repository together
    with the pull request number carried in the subject, so any message in the
    thread is enough to find it. Threads are archived by removing the ``INBOX``
    label, which is what the Gmail web interface calls archiving. Messages are
    not deleted and stay searchable.

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
    GmailError
        If Gmail returns an error for the search or for a modification.
    """
    headers = {'Authorization': f'Bearer {access_token}'}
    response = await session.get(f'{_API_BASE_URL}/threads',
                                 headers=headers,
                                 params={'q': _search_query(full_name, number)})
    if not response.ok:
        msg = f'Gmail returned HTTP {response.status_code} searching for PR {number}.'
        raise GmailError(msg)
    threads = (response.json() or {}).get('threads') or []
    archived = 0
    for thread in threads:
        modified = await session.post(f'{_API_BASE_URL}/threads/{thread["id"]}/modify',
                                      headers=headers,
                                      json={'removeLabelIds': ['INBOX']})
        if not modified.ok:
            msg = (f'Gmail returned HTTP {modified.status_code} archiving thread '
                   f'`{thread["id"]}`.')
            raise GmailError(msg)
        archived += 1
    return archived
