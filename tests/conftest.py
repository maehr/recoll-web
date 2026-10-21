# SPDX-License-Identifier: AGPL-3.0-only
"""A fake Recoll module that behaves like the native one where recoll-web depends on it.

Like Recoll 1.44, the fake escapes ``<`` and ``&`` in abstracts and highlight results, returns an
empty document for an unknown ``rcludi``, and sorts only before ``execute``. ``getgroups``
expands each word of the last query to itself and its upper case.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

import pytest

from recoll_web.core import EMPTY_PAGE, Preview, ResultPage
from recoll_web.recoll_backend import Backend, Download

T = TypeVar("T")


def _mark(text: str, term: str, methods: Any) -> str:
    """Escape like Recoll and wrap each ``term`` with the marks of ``methods``."""
    start, end = methods.startMatch(0), methods.endMatch()
    return html.escape(text, quote=False).replace(term, f"{start}{term}{end}")


@dataclass
class FakeDoc:
    rcludi: str = ""
    title: str = ""
    filename: str = ""
    url: str = ""
    mtype: str = "text/plain"
    mtime: str = "1754000000"
    ipath: str = ""
    abstract: str = ""
    text: str = "a < b & oberon"

    def getbinurl(self) -> bytes:
        return self.url.encode()


@dataclass
class FakeQuery:
    docs: list[FakeDoc]
    abstract_fails: bool = False
    executed: list[str] = field(default_factory=list)
    sort: tuple[str, bool] | None = None
    position: int = 0
    scrolled: list[int] = field(default_factory=list)
    closed: bool = False

    def sortby(self, name: str, ascending: bool = True) -> None:
        assert not self.executed, "sortby must come before execute"
        self.sort = (name, ascending)

    def execute(self, query_string: str) -> int:
        self.executed.append(query_string)
        return len(self.docs)

    def scroll(self, value: int, mode: str = "relative") -> int:
        assert mode == "absolute"
        self.position = value
        self.scrolled.append(value)
        return value

    def fetchone(self) -> FakeDoc | None:
        if self.position >= len(self.docs):
            return None
        self.position += 1
        return self.docs[self.position - 1]

    def makedocabstract(self, doc: Any, *, methods: object) -> str:
        if self.abstract_fails:
            raise RuntimeError("no abstract")
        return _mark(doc.text, "oberon", methods)

    def getgroups(self) -> list[tuple[list[str], list[str]]]:
        return [([word], [word, word.upper()]) for word in self.executed[-1].split()]

    def close(self) -> None:
        self.closed = True


@dataclass
class FakeDb:
    docs: list[FakeDoc]
    abstract_fails: bool = False
    queries: list[FakeQuery] = field(default_factory=list)
    abstract_params: dict[str, int] = field(default_factory=dict)
    closed: bool = False

    def setAbstractParams(self, *, maxchars: int, contextwords: int) -> None:
        self.abstract_params = {"maxchars": maxchars, "contextwords": contextwords}

    def query(self) -> FakeQuery:
        self.queries.append(FakeQuery(self.docs, self.abstract_fails))
        return self.queries[-1]

    def getDoc(self, udi: str) -> FakeDoc:
        return next((doc for doc in self.docs if doc.rcludi == udi), FakeDoc(rcludi=udi, url=""))

    def close(self) -> None:
        self.closed = True


@dataclass
class FakeExtracted:
    text: str
    mimetype: str


@dataclass
class FakeExtractor:
    doc: FakeDoc
    fails: bool

    def textextract(self, ipath: str) -> FakeExtracted:
        if self.fails:
            raise RuntimeError("no filter")
        return FakeExtracted(text=self.doc.text, mimetype=self.doc.mtype)

    def idoctofile(self, ipath: str, mimetype: str, *, ofilename: str) -> str:
        if self.fails:
            raise RuntimeError("no filter")
        Path(ofilename).write_text(f"member {ipath}")
        return ofilename


@dataclass
class FakeRecoll:
    """A stand-in for the ``recoll.recoll`` module."""

    docs: list[FakeDoc] = field(default_factory=list)
    connect_fails: bool = False
    extract_fails: bool = False
    abstract_fails: bool = False
    connections: list[FakeDb] = field(default_factory=list)

    def connect(self, confdir: str | None = None, *, writable: bool = False) -> FakeDb:
        assert writable is False
        if self.connect_fails:
            raise RuntimeError("no index")
        self.connections.append(FakeDb(self.docs, self.abstract_fails))
        return self.connections[-1]

    def Extractor(self, doc: Any) -> FakeExtractor:
        return FakeExtractor(doc, self.extract_fails)

    @property
    def db(self) -> FakeDb:
        return self.connections[-1]


def make_docs(count: int, folder: str = "/data") -> list[FakeDoc]:
    """Return ``count`` documents with distinct IDs, titles, and paths."""
    return [
        FakeDoc(
            rcludi=f"udi-{n}",
            title=f"Doc {n}",
            filename=f"d{n}.txt",
            url=f"file://{folder}/d{n}.txt",
        )
        for n in range(count)
    ]


@pytest.fixture
def fake_recoll() -> FakeRecoll:
    return FakeRecoll(docs=make_docs(3))


@dataclass
class StubBackend:
    """A backend with fixed answers that records its calls."""

    page: ResultPage = EMPTY_PAGE
    preview_result: Preview | None = None
    download: Download | None = None
    error: Exception | None = None
    calls: list[tuple[str, object]] = field(default_factory=list)

    def _answer(self, name: str, arg: object, value: T) -> T:
        self.calls.append((name, arg))
        if self.error:
            raise self.error
        return value

    def backend(self) -> Backend:
        return Backend(
            search=lambda request: self._answer("search", request, self.page),
            preview=lambda doc_id, q: self._answer("preview", (doc_id, q), self.preview_result),
            fetch=lambda doc_id: self._answer("fetch", doc_id, self.download),
        )
