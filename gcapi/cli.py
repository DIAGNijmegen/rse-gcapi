import sys
from typing import Any

import click


@click.command()
def main(*_: Any, **__: Any) -> int:
    """Console script for gcapi."""
    click.echo("Replace this message by putting your code into gcapi.cli.main")
    click.echo("See click documentation at http://click.pocoo.org/")
    return 0


if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover
