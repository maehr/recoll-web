# SPDX-License-Identifier: AGPL-3.0-only
"""End-to-end tests against the native Recoll module and a temporary index of synthetic files.

Run them with ``pytest -m recoll``. They skip when the module or ``recollindex`` is missing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from recoll_web.core import MATCH_END, MATCH_START, SearchRequest, encode_id, strip_marks
from recoll_web.recoll_backend import Backend, load_recoll, make_backend
from recoll_web.web import Settings, create_app

pytestmark = pytest.mark.recoll

MBOX = """From alice@example.org Mon Jan  1 10:00:00 2024
From: alice@example.org
Subject: First note
Date: Mon, 1 Jan 2024 10:00:00 +0000

The first message mentions Oberon.

From bob@example.org Tue Jan  2 10:00:00 2024
From: bob@example.org
Subject: Second note
Date: Tue, 2 Jan 2024 10:00:00 +0000

The second message mentions Oberon too.
"""


@dataclass(frozen=True)
class Index:
    recoll: Any
    confdir: str
    docs: Path

    def backend(self, page_size: int = 20, roots: tuple[str, ...] | None = None) -> Backend:
        return make_backend(self.recoll, self.confdir, roots or (str(self.docs),), page_size)


def _write(path: Path, text: str, year: int) -> None:
    path.write_text(text)
    stamp = datetime(year, 6, 1).timestamp()
    os.utime(path, (stamp, stamp))


@pytest.fixture(scope="module")
def index(tmp_path_factory: pytest.TempPathFactory) -> Index:
    pytest.importorskip("recoll.recoll")
    recollindex = shutil.which("recollindex") or pytest.skip("recollindex is not on PATH")
    base = tmp_path_factory.mktemp("recoll")
    docs = base / "docs"
    docs.mkdir()
    _write(docs / "alpha #1.txt", "Oberon compares a < b & c in the alpha file.\n", 2001)
    _write(docs / "beta.txt", "The beta file mentions Oberon twice. Oberon!\n", 2020)
    page = "<html><head><title>Gamma page</title><style>p{}</style></head>"
    _write(docs / "page.html", f"{page}<body><p>Oberon in &lt;html&gt;</p></body></html>", 2010)
    _write(docs / "notes.mbox", MBOX, 2024)
    conf = base / "conf"
    conf.mkdir()
    (conf / "recoll.conf").write_text(f'topdirs = "{docs}"\nloglevel = 1\n')
    subprocess.run([recollindex, "-c", str(conf)], check=True, capture_output=True)  # noqa: S603
    return Index(load_recoll(), str(conf), docs)


def test_snippet_is_plain_text_with_marks(index: Index) -> None:
    hits = index.backend().search(SearchRequest(q="compares")).hits
    assert len(hits) == 1
    assert "a < b & c" in strip_marks(hits[0].snippet)
    assert f"{MATCH_START}compares{MATCH_END}" in hits[0].snippet
    assert hits[0].path == str(index.docs / "alpha #1.txt")


def test_paging(index: Index) -> None:
    page = index.backend(page_size=2).search(SearchRequest(q="oberon", page=2))
    assert page.total >= 5
    assert page.page == 2
    assert len(page.hits) == 2


@pytest.mark.parametrize(
    ("request_", "expected"),
    [
        (SearchRequest(q="oberon", category="message"), {"First note", "Second note"}),
        (SearchRequest(q="oberon", category="media"), set()),
        (SearchRequest(q="file", before=date(2005, 1, 1)), {"alpha #1.txt"}),
        (SearchRequest(q="file", after=date(2015, 1, 1)), {"beta.txt"}),
    ],
)
def test_filters(index: Index, request_: SearchRequest, expected: set[str]) -> None:
    hits = index.backend().search(request_).hits
    assert {hit.title for hit in hits} == expected


def test_folder_filter(index: Index) -> None:
    backend = index.backend()
    assert backend.search(SearchRequest(q="oberon", dir=str(index.docs))).total >= 5
    assert backend.search(SearchRequest(q="oberon", dir="/no/such folder")).total == 0


def test_sort_by_date(index: Index) -> None:
    backend = index.backend()
    newest = backend.search(SearchRequest(q="file", sort="newest")).hits
    oldest = backend.search(SearchRequest(q="file", sort="oldest")).hits
    assert [hit.title for hit in newest] == ["beta.txt", "alpha #1.txt"]
    assert [hit.title for hit in oldest] == ["alpha #1.txt", "beta.txt"]


def test_preview_of_html_is_marked_text(index: Index) -> None:
    hit = index.backend().search(SearchRequest(q="gamma")).hits[0]
    shown = index.backend().preview(hit.id, "oberon")
    assert shown is not None
    assert shown.title == "Gamma page"
    assert f"{MATCH_START}Oberon{MATCH_END} in <html>" in shown.text
    assert "p{}" not in shown.text


def test_preview_of_unknown_document(index: Index) -> None:
    assert index.backend().preview(encode_id("/no/such/udi"), "") is None


def test_fetch_plain_file_and_roots(index: Index) -> None:
    hit = index.backend().search(SearchRequest(q="compares")).hits[0]
    found = index.backend().fetch(hit.id)
    assert found is not None
    assert not found.temporary
    assert Path(found.path).read_text().startswith("Oberon compares")
    assert index.backend(roots=("/no/such/root",)).fetch(hit.id) is None


def test_fetch_extracts_a_mail_message(index: Index) -> None:
    hit = index.backend().search(SearchRequest(q="second", category="message")).hits[0]
    found = index.backend().fetch(hit.id)
    assert found is not None
    assert found.temporary
    assert found.filename.startswith("notes-")
    assert found.filename.endswith(".eml")
    assert "The second message" in Path(found.path).read_text()
    os.unlink(found.path)


def test_web_page_escapes_once(index: Index) -> None:
    settings = Settings(confdir=index.confdir, dirs=(str(index.docs),), allow_download=True)
    client = TestClient(create_app(settings, index.backend()))
    text = client.get("/?q=compares", headers={"HX-Request": "true"}).text
    assert "a &lt; b &amp; c" in text
    assert "&amp;lt;" not in text
    assert "<mark>compares</mark>" in text
