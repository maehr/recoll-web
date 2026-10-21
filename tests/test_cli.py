# SPDX-License-Identifier: AGPL-3.0-only
"""The command line and the application factory, with the fake Recoll module."""

from __future__ import annotations

import importlib
import runpy
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from recoll_web import __version__, cli
from recoll_web.recoll_backend import RecollError
from recoll_web.web import Settings

from conftest import FakeRecoll, make_docs

runner = CliRunner()


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace the server start and the native import. Return the recorded server starts."""
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        cli.uvicorn, "run", lambda app, **kwargs: calls.append({"app": app, **kwargs})
    )
    monkeypatch.setattr(cli, "load_recoll", FakeRecoll)
    for name in (
        "RECOLL_CONFDIR",
        "RECOLL_WEB_HOST",
        "RECOLL_WEB_DIRS",
        "RECOLL_WEB_ALLOW_DOWNLOAD",
    ):
        monkeypatch.delenv(name, raising=False)
    return calls


def test_read_topdirs(tmp_path: Path) -> None:
    (tmp_path / "recoll.conf").write_text("topdirs = ~/docs /srv\n")
    assert cli.read_topdirs(str(tmp_path), "/h") == ("/h/docs", "/srv")


def test_read_topdirs_defaults_to_home(tmp_path: Path) -> None:
    (tmp_path / "recoll.conf").write_text("loglevel = 2\n")
    assert cli.read_topdirs(str(tmp_path), "/h") == ("/h",)


def test_build_app_reads_topdirs(tmp_path: Path) -> None:
    (tmp_path / "recoll.conf").write_text(f"topdirs = {tmp_path}/docs\n")
    recoll = FakeRecoll(docs=make_docs(1))
    app = cli.build_app(Settings(confdir=str(tmp_path)), recoll=recoll)
    text = TestClient(app).get("/?q=x").text
    assert f'<option value="{tmp_path}/docs"' in text
    assert "Doc 0" in text


def test_serve_starts_uvicorn(started: list[dict[str, Any]], tmp_path: Path) -> None:
    args = [
        "--port",
        "9001",
        "--confdir",
        str(tmp_path),
        "--dir",
        "/a",
        "--dir",
        "/b",
        "--allow-download",
    ]
    result = runner.invoke(cli.cli, args)
    assert result.exit_code == 0, result.output
    assert started[0]["host"] == "127.0.0.1"
    assert started[0]["port"] == 9001
    assert "Warning" not in result.output
    text = TestClient(started[0]["app"]).get("/").text
    assert '<option value="/b"' in text


def test_serve_reads_the_environment(
    started: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RECOLL_WEB_PORT", "9002")
    assert runner.invoke(cli.cli, []).exit_code == 0
    assert started[0]["port"] == 9002


def test_serve_warns_on_a_public_address(started: list[dict[str, Any]]) -> None:
    result = runner.invoke(cli.cli, ["--host", "0.0.0.0"])  # noqa: S104 - the case under test
    assert result.exit_code == 0
    assert "no authentication" in result.output


def test_serve_stops_without_recoll(
    started: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing() -> None:
        raise RecollError("The Recoll Python module does not import.")

    monkeypatch.setattr(cli, "load_recoll", missing)
    result = runner.invoke(cli.cli, [])
    assert result.exit_code == 1
    assert "Error: The Recoll Python module does not import." in result.output
    assert started == []


def test_version() -> None:
    result = runner.invoke(cli.cli, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"recoll-web {__version__}"


def test_main(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["recoll-web", "--version"])
    with pytest.raises(SystemExit) as stop:
        cli.main()
    assert stop.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_python_dash_m(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["recoll-web", "--version"])
    with pytest.raises(SystemExit) as stop:
        runpy.run_module("recoll_web", run_name="__main__")
    assert stop.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_main_module_import_does_not_start() -> None:
    module = importlib.import_module("recoll_web.__main__")
    assert module.main is cli.main
