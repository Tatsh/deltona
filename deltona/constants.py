"""Constants."""

from __future__ import annotations

__all__ = ('CONTEXT_SETTINGS', 'SYSLOG_SOCKETS')

CONTEXT_SETTINGS = {'help_option_names': ('-h', '--help')}
"""
Shared context settings for all commands.

:meta hide-value:
"""
SYSLOG_SOCKETS = ('/dev/log', '/var/run/syslog', '/var/run/log')
"""
Where the local syslog socket lives, in the order to try.

:py:class:`logging.handlers.SysLogHandler` otherwise defaults to UDP on localhost, where nothing
usually listens.

:meta hide-value:
"""
