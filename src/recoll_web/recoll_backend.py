# SPDX-License-Identifier: AGPL-3.0-only
"""The adapter between recoll-web and the native Recoll Python module.

Only this module calls Recoll. Each function takes the Recoll module as an argument, so a test
passes a fake module. :func:`make_backend` binds the arguments once and returns a :class:`Backend`.

Each call opens its own read-only connection. The native module gives no thread-safety guarantee
for shared objects, and the web server runs the calls in a thread pool.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from functools import partial
from itertools import islice
from types import SimpleNamespace
from typing import Protocol, cast

from .core import (
    EMPTY_PAGE,
    MATCH_END,
    MATCH_START,
    Preview,
    ResultPage,
    SearchRequest,
    as_plain_text,
    build_query,
    decode_id,
    group_terms,
    is_under,
    mark_terms,
    member_filename,
    page_count,
    page_offset,
    recoll_text,
    sort_spec,
    to_hit,
)

#: The document fields that :func:`doc_fields` copies.
FIELDS = ("rcludi", "title", "filename", "url", "mtype", "mtime", "ipath", "abstract")

#: The highlight methods for Recoll: they mark a match with the private-use markers of ``core``.
MARKS = SimpleNamespace(startMatch=lambda _index: MATCH_START, endMatch=lambda: MATCH_END)

IMPORT_HELP = (
    "The Recoll Python module does not import. Install Recoll with its Python module, then run "
    "recoll-web with the same Python, or in a venv made with --system-site-packages."
)


class RecollError(RuntimeError):
    """Recoll cannot do the operation. The message is safe to show to the user."""


class Doc(Protocol):
    """The part of ``recoll.Doc`` that recoll-web uses. The fields are dynamic attributes."""

    def getbinurl(self) -> bytes:
        """Return the URL as bytes, for a path that is not valid UTF-8."""
        ...


class Extracted(Protocol):
    """The result of ``Extractor.textextract``."""

    text: str
    mimetype: str


class TextExtractor(Protocol):
    """The part of ``recoll.Extractor`` that recoll-web uses."""

    def textextract(self, ipath: str, /) -> Extracted:
        """Return the text of the document at ``ipath``."""
        ...

    def idoctofile(self, ipath: str, mimetype: str, *, ofilename: str) -> str:
        """Write the document at ``ipath`` into ``ofilename``, in its native format."""
        ...


class Query(Protocol):
    """The part of ``recoll.Query`` that recoll-web uses."""

    def sortby(self, field: str, /, *, ascending: bool = True) -> None:
        """Set the sort order. Call it before :meth:`execute`."""
        ...

    def execute(self, query_string: str, /) -> int:
        """Run a search and return the estimated number of results."""
        ...

    def scroll(self, value: int, /, mode: str = "relative") -> int:
        """Move the result cursor."""
        ...

    def fetchone(self) -> Doc | None:
        """Return the next result."""
        ...

    def makedocabstract(self, doc: Doc, /, *, methods: object) -> str:
        """Return the snippets of a result, with the match markers of ``methods``."""
        ...

    def getgroups(self) -> list[tuple[list[str], list[str]]]:
        """Return the user terms of the last search and their expansions."""
        ...

    def close(self) -> None:
        """Release the query."""
        ...


class Db(Protocol):
    """The part of ``recoll.Db`` that recoll-web uses."""

    def setAbstractParams(self, *, maxchars: int, contextwords: int) -> None:  # noqa: N802
        """Set the snippet size."""
        ...

    def query(self) -> Query:
        """Return a new query."""
        ...

    def getDoc(self, udi: str, /) -> Doc:  # noqa: N802
        """Return the document of a ``rcludi``. An unknown ``rcludi`` gives an empty document."""
        ...

    def close(self) -> None:
        """Close the connection."""
        ...


class Recoll(Protocol):
    """The part of the ``recoll.recoll`` module that recoll-web uses."""

    def connect(self, confdir: str | None = None, *, writable: bool = False) -> Db:
        """Open a connection to the index of ``confdir``."""
        ...

    def Extractor(self, doc: Doc, /) -> TextExtractor:  # noqa: N802
        """Return an extractor for a document."""
        ...


@dataclass(frozen=True)
class Download:
    """A file that the web layer sends. ``temporary`` means: delete it after the response.

    Example:
        >>> Download("/tmp/x", "x.pdf", "application/pdf", temporary=True).filename
        'x.pdf'
    """

    path: str
    filename: str
    mime: str
    temporary: bool


@dataclass(frozen=True)
class Backend:
    """The operations of the web layer, as a record of functions.

    Example:
        >>> backend = Backend(lambda r: EMPTY_PAGE, lambda i, q: None, lambda i: None)
        >>> backend.search(SearchRequest(q="x")).total
        0
    """

    search: Callable[[SearchRequest], ResultPage]
    preview: Callable[[str, str], Preview | None]
    fetch: Callable[[str], Download | None]


def load_recoll() -> Recoll:  # pragma: no cover - needs the native module; see test_integration
    """Import the native Recoll module.

    Older Recoll versions have ``Extractor`` in the separate ``rclextract`` module only. Recoll 1.44
    keeps ``rclextract`` for compatibility, so this import works with both.

    Raises:
        RecollError: The module does not import.
    """
    try:
        from recoll import rclextract, recoll  # noqa: PLC0415  # ty: ignore[unresolved-import]
    except ImportError as exc:
        raise RecollError(IMPORT_HELP) from exc
    # The native module is untyped. The protocol states what recoll-web expects of it.
    return cast("Recoll", SimpleNamespace(connect=recoll.connect, Extractor=rclextract.Extractor))


def doc_fields(doc: object) -> dict[str, str]:
    """Return the :data:`FIELDS` of a Recoll document as strings.

    Example:
        >>> doc_fields(SimpleNamespace(title=" Report ", mtime=None))["title"]
        'Report'
    """
    return {key: str(getattr(doc, key, None) or "").strip() for key in FIELDS}


@contextmanager
def connection(recoll: Recoll, confdir: str | None) -> Generator[Db, None, None]:
    """Open a read-only connection and close it at the end of the block.

    Raises:
        RecollError: The index does not open.
    """
    try:
        db = recoll.connect(confdir, writable=False)
    except Exception as exc:
        raise RecollError(
            "The Recoll index does not open. Check the configuration folder "
            "(--confdir or RECOLL_CONFDIR) and the permissions of the index."
        ) from exc
    try:
        yield db
    finally:
        db.close()


@contextmanager
def open_query(db: Db) -> Generator[Query, None, None]:
    """Return a new query and close it at the end of the block."""
    query = db.query()
    try:
        yield query
    finally:
        query.close()


def abstract(query: Query, doc: Doc, fallback: str) -> str:
    """Return the snippets of a result as plain text with match markers.

    Recoll cannot build snippets for some documents. Then the stored abstract is used.
    """
    try:
        return recoll_text(query.makedocabstract(doc, methods=MARKS))
    except Exception:  # noqa: BLE001 - the native module raises plain exceptions
        return fallback


def search(
    recoll: Recoll, confdir: str | None, page_size: int, request: SearchRequest
) -> ResultPage:
    """Run a search and return one page of results. An empty query returns no results."""
    if not request.q.strip():
        return EMPTY_PAGE
    with connection(recoll, confdir) as db, open_query(db) as query:
        db.setAbstractParams(maxchars=300, contextwords=18)
        if spec := sort_spec(request.sort):
            query.sortby(spec[0], ascending=spec[1])
        total = query.execute(build_query(request))
        offset = page_offset(request.page, page_size)
        if 0 < offset < total:
            query.scroll(offset, mode="absolute")
        count = max(min(page_size, total - offset), 0)
        docs = islice(iter(query.fetchone, None), count)
        fields = ((doc, doc_fields(doc)) for doc in docs)
        hits = (to_hit(f, abstract(query, doc, f["abstract"])) for doc, f in fields)
        return ResultPage(
            hits=tuple(hit for hit in hits if hit),
            total=total,
            page=request.page,
            pages=page_count(total, page_size),
        )


def find_doc(db: Db, doc_id: str) -> tuple[Doc, dict[str, str]] | None:
    """Return the document of an ID and its fields, or ``None`` when the index does not hold it."""
    udi = decode_id(doc_id)
    if udi is None:
        return None
    doc = db.getDoc(udi)
    fields = doc_fields(doc)
    return (doc, fields) if fields["url"] else None


def highlight(db: Db, query_text: str, text: str) -> str:
    """Return ``text`` with markers around the matches of ``query_text``."""
    if not query_text.strip():
        return text
    with open_query(db) as query:
        query.execute(query_text)
        return mark_terms(text, group_terms(query.getgroups()))


def preview(
    recoll: Recoll, confdir: str | None, max_chars: int, doc_id: str, query_text: str
) -> Preview | None:
    """Return the text of a document, with the matches of ``query_text`` marked.

    Raises:
        RecollError: Recoll cannot extract the text.
    """
    with connection(recoll, confdir) as db:
        found = find_doc(db, doc_id)
        if found is None:
            return None
        doc, fields = found
        try:
            extracted = recoll.Extractor(doc).textextract(fields["ipath"])
        except Exception as exc:
            raise RecollError("Recoll cannot extract the text of this document.") from exc
        text = as_plain_text(str(extracted.text or ""), str(extracted.mimetype or ""))
        return Preview(
            title=fields["title"] or fields["filename"] or "Document",
            text=highlight(db, query_text, text[:max_chars]),
            truncated=len(text) > max_chars,
        )


def fetch(
    recoll: Recoll, confdir: str | None, roots: Sequence[str], doc_id: str
) -> Download | None:
    """Return the original file of a document, or ``None`` when it is not under ``roots``.

    A document inside an archive or a mail folder is extracted into a temporary file.

    Raises:
        RecollError: Recoll cannot extract the embedded document.
    """
    with connection(recoll, confdir) as db:
        found = find_doc(db, doc_id)
        if found is None:
            return None
        doc, fields = found
        path = os.path.realpath(os.fsdecode(doc.getbinurl().removeprefix(b"file://")))
        allowed = [os.path.realpath(root) for root in roots]
        if not (is_under(path, allowed) and os.path.isfile(path)):
            return None
        mime = fields["mtype"] or "application/octet-stream"
        if not fields["ipath"]:
            return Download(path, os.path.basename(path), mime, temporary=False)
        handle, target = tempfile.mkstemp(prefix="recoll-web-")
        os.close(handle)
        try:
            recoll.Extractor(doc).idoctofile(fields["ipath"], mime, ofilename=target)
        except Exception as exc:
            with suppress(OSError):
                os.unlink(target)
            raise RecollError("Recoll cannot extract this document.") from exc
        name = member_filename(os.path.basename(path), fields["ipath"], mime)
        return Download(target, name, mime, temporary=True)


def make_backend(
    recoll: Recoll,
    confdir: str | None,
    roots: Sequence[str],
    page_size: int = 20,
    preview_chars: int = 45_000,
) -> Backend:
    """Bind the Recoll module and the settings to the backend functions.

    Example:
        >>> backend = make_backend(SimpleNamespace(), "/conf", ["/data"])
        >>> backend.search(SearchRequest(q="  ")).total
        0
    """
    return Backend(
        search=partial(search, recoll, confdir, page_size),
        preview=partial(preview, recoll, confdir, preview_chars),
        fetch=partial(fetch, recoll, confdir, tuple(roots)),
    )
