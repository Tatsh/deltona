"""Main script."""
from __future__ import annotations

import click

__all__ = ('main',)


@click.command(context_settings={'help_option_names': ('-h', '--help')})
@click.option('--force-color', help='Force enable colour log output.', is_flag=True)
@click.option('--no-color', help='Disable colour log output.', is_flag=True)
@click.option('-d', '--debug', help='Enable debug level logging.', is_flag=True)
def main(*, debug: bool = False, force_color: bool = False, no_color: bool = False) -> None:
    click.echo('Do something here.')
