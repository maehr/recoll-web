# SPDX-License-Identifier: AGPL-3.0-only
"""The Recoll adapter, against the fake Recoll module of ``conftest.py``."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from recoll_web.core import EMPTY_PAGE, MATCH_END, MATCH_START, SearchRequest, encode_id
from recoll_web.recoll_backend import (
    RecollError,
    doc_fields,
    fetch,
    make_backend,
    preview,
    search,
)

from conftest import FakeDoc, FakeRecoll, make_docs


def test_empty_query_does_not_connect(fake_recoll: FakeRecoll) -> None:
    assert search(fake_recoll, None, 20, SearchRequest(q=" ")) is EMPTY_PAGE
    assert fake_recoll.connections == []


def test_search_pages_sorts_and_closes() -> None:
    recoll = FakeRecoll(docs=make_docs(25))
    page = search(recoll, "/conf", 20, SearchRequest(q="x", category="text", sort="newest", page=2))
    query = recoll.db.queries[0]
    assert query.executed == ["(x) rclcat:text"]
    assert query.sort == ("mtime", False)
    assert query.scrolled == [20]
    assert [hit.title for hit in page.hits] == [f"Doc {n}" for n in range(20, 25)]
    assert (page.total, page.page, page.pages) == (25, 2, 2)
    assert recoll.db.abstract_params == {"maxchars": 300, "contextwords": 18}
    assert query.closed
    assert recoll.db.closed


def test_first_page_does_not_scroll(fake_recoll: FakeRecoll) -> None:
    page = search(fake_recoll, None, 2, SearchRequest(q="x"))
    assert fake_recoll.db.queries[0].scrolled == []
    assert fake_recoll.db.queries[0].sort is None
    assert len(page.hits) == 2


def test_page_after_the_end_is_empty(fake_recoll: FakeRecoll) -> None:
    page = search(fake_recoll, None, 20, SearchRequest(q="x", page=5))
    assert page.hits == ()
    assert fake_recoll.db.queries[0].scrolled == []


def test_snippet_is_unescaped_once_and_marked(fake_recoll: FakeRecoll) -> None:
    hit = search(fake_recoll, None, 20, SearchRequest(q="oberon")).hits[0]
    assert hit.snippet == f"a < b & {MATCH_START}oberon{MATCH_END}"


def test_snippet_falls_back_to_the_stored_abstract() -> None:
    recoll = FakeRecoll(
        docs=[FakeDoc(rcludi="u", url="file:///d/a", abstract="stored")], abstract_fails=True
    )
    assert search(recoll, None, 20, SearchRequest(q="x")).hits[0].snippet == "stored"


def test_document_without_udi_is_skipped() -> None:
    recoll = FakeRecoll(docs=[FakeDoc(url="file:///d/a"), *make_docs(1)])
    page = search(recoll, None, 20, SearchRequest(q="x"))
    assert [hit.title for hit in page.hits] == ["Doc 0"]


def test_connect_failure_is_a_recoll_error() -> None:
    with pytest.raises(RecollError, match="does not open"):
        search(FakeRecoll(connect_fails=True), None, 20, SearchRequest(q="x"))


def test_preview_marks_matches_and_truncates() -> None:
    doc = FakeDoc(rcludi="u", title="T", url="file:///d/a", text="x < oberon " * 10)
    result = preview(FakeRecoll(docs=[doc]), None, 15, encode_id("u"), "oberon")
    assert result is not None
    assert result.title == "T"
    assert result.text == f"x < {MATCH_START}oberon{MATCH_END} x < "
    assert result.truncated


def test_preview_without_query_is_plain_text() -> None:
    doc = FakeDoc(
        rcludi="u",
        filename="a.html",
        url="file:///d/a",
        mtype="text/html",
        text="<p>a &amp; oberon</p>",
    )
    recoll = FakeRecoll(docs=[doc])
    result = preview(recoll, None, 1000, encode_id("u"), "")
    assert result is not None
    assert (result.title, result.text, result.truncated) == ("a.html", "a & oberon", False)
    assert recoll.db.queries == []


def test_preview_title_falls_back() -> None:
    result = preview(
        FakeRecoll(docs=[FakeDoc(rcludi="u", url="file:///d/a")]), None, 10, encode_id("u"), ""
    )
    assert result is not None
    assert result.title == "Document"


@pytest.mark.parametrize("doc_id", [encode_id("unknown"), "not base64!"])
def test_preview_of_unknown_document_is_none(fake_recoll: FakeRecoll, doc_id: str) -> None:
    assert preview(fake_recoll, None, 100, doc_id, "x") is None


def test_preview_extraction_failure_is_a_recoll_error() -> None:
    recoll = FakeRecoll(docs=make_docs(1), extract_fails=True)
    with pytest.raises(RecollError, match="extract the text"):
        preview(recoll, None, 100, encode_id("udi-0"), "")


@pytest.fixture
def files(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    root.mkdir()
    (root / "a #1.txt").write_text("plain")
    (root / "mail.mbox").write_text("mbox")
    (tmp_path / "secret.txt").write_text("outside")
    os.symlink(tmp_path / "secret.txt", root / "link.txt")
    return root


def _recoll_for(*docs: FakeDoc, extract_fails: bool = False) -> FakeRecoll:
    return FakeRecoll(docs=list(docs), extract_fails=extract_fails)


def test_fetch_plain_file(files: Path) -> None:
    doc = FakeDoc(rcludi="u", url=f"file://{files}/a #1.txt", mtype="")
    found = fetch(_recoll_for(doc), None, [str(files)], encode_id("u"))
    assert found is not None
    assert found.filename == "a #1.txt"
    assert found.mime == "application/octet-stream"
    assert not found.temporary
    assert Path(found.path).read_text() == "plain"


@pytest.mark.parametrize("name", ["../secret.txt", "link.txt", "missing.txt", ""])
def test_fetch_refuses_paths_outside_the_roots(files: Path, name: str) -> None:
    doc = FakeDoc(rcludi="u", url=f"file://{files}/{name}")
    assert fetch(_recoll_for(doc), None, [str(files)], encode_id("u")) is None


def test_fetch_unknown_document(files: Path, fake_recoll: FakeRecoll) -> None:
    assert fetch(fake_recoll, None, [str(files)], encode_id("unknown")) is None


def test_fetch_extracts_an_embedded_document(files: Path) -> None:
    doc = FakeDoc(
        rcludi="u",
        filename="m.eml",
        url=f"file://{files}/mail.mbox",
        mtype="message/rfc822",
        ipath="3",
    )
    found = fetch(_recoll_for(doc), None, [str(files)], encode_id("u"))
    assert found is not None
    assert found.temporary
    assert (found.filename, found.mime) == ("mail-3.eml", "message/rfc822")
    assert Path(found.path).read_text() == "member 3"
    os.unlink(found.path)


def test_fetch_extraction_failure_leaves_no_file(
    files: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr("tempfile.tempdir", None)
    doc = FakeDoc(rcludi="u", url=f"file://{files}/mail.mbox", ipath="3")
    with pytest.raises(RecollError, match="cannot extract this document"):
        fetch(_recoll_for(doc, extract_fails=True), None, [str(files)], encode_id("u"))
    assert not list(tmp_path.glob("recoll-web-*"))


def test_doc_fields_reads_missing_fields_as_empty() -> None:
    assert doc_fields(object()) == dict.fromkeys(doc_fields(object()), "")


def test_make_backend_binds_the_arguments(files: Path) -> None:
    docs = make_docs(3, folder=str(files))
    backend = make_backend(FakeRecoll(docs=docs), None, [str(files)], page_size=2, preview_chars=5)
    assert len(backend.search(SearchRequest(q="x")).hits) == 2
    shown = backend.preview(encode_id("udi-0"), "")
    assert shown is not None
    assert shown.text == "a < b"
    assert backend.fetch(encode_id("udi-0")) is None  # d0.txt does not exist on disk
