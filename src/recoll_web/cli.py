# SPDX-License-Identifier: AGPL-3.0-only
"""The command line. ``recoll-web [OPTIONS]`` starts the server.

:func:`build_app` is also an ASGI factory: ``uvicorn --factory recoll_web.cli:build_app``.
It then reads the settings from the ``RECOLL_WEB_*`` environment variables.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any

import typer
import uvicorn
from fastapi import FastAPI

from . import __version__
from .core import is_loopback, parse_topdirs, resolve_confdir
from .recoll_backend import Recoll, RecollError, load_recoll, make_backend
from .web import Settings, create_app

LOOPBACK_WARNING = (
    "Warning: recoll-web has no authentication. Every client that reaches this address can read "
    "the titles, paths, and text of the indexed documents."
)

cli = typer.Typer(add_completion=False, help="A small web interface for Recoll full-text search.")


def read_topdirs(confdir: str, home: str) -> tuple[str, ...]:
    """Return the ``topdirs`` of ``recoll.conf`` in ``confdir``, else ``home`` like Recoll does.

    Example:
        >>> read_topdirs("/no/such/folder", "/h")
        ('/h',)
    """
    conf = Path(confdir, "recoll.conf")
    dirs = parse_topdirs(conf.read_text(errors="replace"), home) if conf.is_file() else ()
    return dirs or (home,)


def build_app(settings: Settings | None = None, recoll: Recoll | None = None) -> FastAPI:
    """Return the application, with the native Recoll module unless ``recoll`` is given.

    Example:
        >>> from types import SimpleNamespace
        >>> app = build_app(Settings(confdir="/no/conf"), recoll=SimpleNamespace())
        >>> app.title
        'Recoll Web'

    Raises:
        RecollError: The native Recoll module does not import.
    """
    settings = settings or Settings()
    home = str(Path.home())
    confdir = resolve_confdir(settings.confdir, os.environ, home)
    dirs = settings.dirs or read_topdirs(confdir, home)
    settings = settings.model_copy(update={"confdir": confdir, "dirs": dirs})
    backend = make_backend(
        recoll or load_recoll(), confdir, dirs, settings.page_size, settings.preview_chars
    )
    return create_app(settings, backend)


def show_version(value: bool) -> None:
    """Print the version and stop, for ``--version``."""
    if value:
        typer.echo(f"recoll-web {__version__}")
        raise typer.Exit


@cli.command()
def serve(
    host: Annotated[str | None, typer.Option(help="Bind address. [default: 127.0.0.1]")] = None,
    port: Annotated[int | None, typer.Option(help="Port. [default: 8080]")] = None,
    confdir: Annotated[
        str | None,
        typer.Option(
            "--confdir",
            "-c",
            help="Recoll configuration folder. [default: $RECOLL_CONFDIR, ~/.recoll]",
        ),
    ] = None,
    dirs: Annotated[
        list[str] | None,
        typer.Option(
            "--dir",
            help="Folder for the folder filter and the download check. Repeat for more. "
            "[default: topdirs of recoll.conf]",
        ),
    ] = None,
    allow_download: Annotated[
        bool | None,
        typer.Option(
            "--allow-download/--no-download",
            help="Serve the original files under the folders. [default: no download]",
        ),
    ] = None,
    version: Annotated[  # noqa: ARG001 - show_version handles it
        bool,
        typer.Option("--version", callback=show_version, is_eager=True, help="Show the version."),
    ] = False,
) -> None:
    """Start the recoll-web server. Each option also reads RECOLL_WEB_<OPTION>."""
    given: dict[str, Any] = {
        "host": host,
        "port": port,
        "confdir": confdir,
        "dirs": tuple(dirs) if dirs else None,
        "allow_download": allow_download,
    }
    settings = Settings(**{key: value for key, value in given.items() if value is not None})
    if not is_loopback(settings.host):
        typer.echo(LOOPBACK_WARNING, err=True)
    try:
        app = build_app(settings)
    except RecollError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    uvicorn.run(app, host=settings.host, port=settings.port)


def main() -> None:
    """Run the command line."""
    cli()
