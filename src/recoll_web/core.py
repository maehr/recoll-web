# SPDX-License-Identifier: AGPL-3.0-only
"""Pure functions and data carriers of recoll-web.

Nothing in this module touches Recoll, the network, or the file system. Every function returns a new
value from its arguments, so each one is tested with a plain call or a doctest.
"""

from __future__ import annotations

import base64
import html
import ipaddress
import mimetypes
import os
import re
import shlex
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, fields, replace
from datetime import date, datetime, tzinfo
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import urlencode

from markupsafe import Markup, escape

Category = Literal["all", "text", "spreadsheet", "presentation", "media", "message", "other"]
Sort = Literal["relevance", "newest", "oldest"]

#: The Recoll file categories (``rclcat:``), in the order of the Recoll GUI.
CATEGORIES: tuple[Category, ...] = (
    "all",
    "text",
    "spreadsheet",
    "presentation",
    "media",
    "message",
    "other",
)

#: Private-use characters around a match: ``makedocabstract`` inserts them, and :func:`mark_terms`.
MATCH_START = ""
MATCH_END = ""

_MATCH_SPLIT = re.compile(f"([{MATCH_START}{MATCH_END}])")
_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,8192}")
_CONTINUATION = re.compile(r"\\\n")
_HIDDEN_TAGS = frozenset({"script", "style"})
_BLOCK_TAGS = frozenset({
    "address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt", "figcaption",
    "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav",
    "ol", "p", "pre", "section", "table", "td", "th", "title", "tr", "ul",
})  # fmt: skip
_BLANK_LINES = re.compile(r"\n{3,}")
_TOKEN = re.compile(r"\w(?:[\w'\u2019.@-]*\w)?")  # a word, or a compound such as "Oberon.Text"
_WORD = re.compile(r"\w+")


@dataclass(frozen=True)
class SearchRequest:
    """One search, as the user asked for it.

    Example:
        >>> SearchRequest(q="wirth", page=2).page
        2
    """

    q: str = ""
    category: Category = "all"
    dir: str = ""
    after: date | None = None
    before: date | None = None
    sort: Sort = "relevance"
    page: int = 1


@dataclass(frozen=True)
class Hit:
    """One search result.

    ``snippet`` is plain text with :data:`MATCH_START` and :data:`MATCH_END` around each match.

    Example:
        >>> Hit("aWQ", "Report", "/data/report.txt", "text/plain", "2024-05-01", "x").modified
        '2024-05-01'
    """

    id: str
    title: str
    path: str
    mime: str
    modified: str
    snippet: str


@dataclass(frozen=True)
class ResultPage:
    """One page of search results.

    Example:
        >>> ResultPage(hits=(), total=0, page=1, pages=0).total
        0
    """

    hits: tuple[Hit, ...]
    total: int
    page: int
    pages: int


@dataclass(frozen=True)
class Preview:
    """The extracted text of one document, with match markers like :attr:`Hit.snippet`.

    Example:
        >>> Preview("Report", "text", truncated=False).truncated
        False
    """

    title: str
    text: str
    truncated: bool


#: The result of a search that did not run.
EMPTY_PAGE = ResultPage(hits=(), total=0, page=1, pages=0)


def build_query(request: SearchRequest) -> str:
    """Return the Recoll query string for a request.

    The user text stays in Recoll query language. The filters become ``rclcat:``, ``dir:``, and
    ``date:`` clauses, which Recoll joins with AND.

    Example:
        >>> build_query(SearchRequest(q="wirth"))
        'wirth'
        >>> build_query(SearchRequest(q="a OR b", category="message", dir="/my docs"))
        '(a OR b) rclcat:message dir:"/my docs"'
        >>> build_query(SearchRequest(q="x", after=date(2020, 1, 1)))
        '(x) date:2020-01-01/'
    """
    folder = request.dir.replace('"', "")
    clauses = (
        f"rclcat:{request.category}" if request.category != "all" else "",
        f'dir:"{folder}"' if folder else "",
        date_clause(request.after, request.before),
    )
    filters = " ".join(clause for clause in clauses if clause)
    text = request.q.strip()
    return f"({text}) {filters}" if filters else text


def date_clause(after: date | None, before: date | None) -> str:
    """Return a Recoll ``date:`` clause, open at the side that is ``None``.

    Example:
        >>> date_clause(None, date(2010, 12, 31))
        'date:/2010-12-31'
        >>> date_clause(None, None)
        ''
    """
    if after is None and before is None:
        return ""
    start = after.isoformat() if after else ""
    end = before.isoformat() if before else ""
    return f"date:{start}/{end}"


def sort_spec(sort: Sort) -> tuple[str, bool] | None:
    """Return the Recoll sort field and the ascending flag, or ``None`` for relevance order.

    Example:
        >>> sort_spec("newest")
        ('mtime', False)
        >>> sort_spec("relevance") is None
        True
    """
    return {"newest": ("mtime", False), "oldest": ("mtime", True)}.get(sort)


def page_count(total: int, size: int) -> int:
    """Return the number of pages for ``total`` results.

    Example:
        >>> page_count(41, 20)
        3
    """
    return -(-total // size)


def page_offset(page: int, size: int) -> int:
    """Return the index of the first result on a 1-based page.

    Example:
        >>> page_offset(3, 20)
        40
    """
    return (page - 1) * size


def query_params(request: SearchRequest) -> dict[str, str]:
    """Return the URL parameters of a request, without the default values.

    Example:
        >>> query_params(SearchRequest(q="wirth", sort="oldest"))
        {'q': 'wirth', 'sort': 'oldest'}
    """
    default = SearchRequest()
    return {
        f.name: str(getattr(request, f.name))
        for f in fields(request)
        if getattr(request, f.name) != getattr(default, f.name)
    }


def page_url(request: SearchRequest, page: int, path: str = "/") -> str:
    """Return the URL of another page of the same search.

    Example:
        >>> page_url(SearchRequest(q="a b"), 2)
        '/?q=a+b&page=2'
    """
    return f"{path}?{urlencode(query_params(replace(request, page=page)))}"


def page_links(request: SearchRequest, pages: int) -> tuple[str | None, str | None]:
    """Return the URLs of the previous and the next page, or ``None`` at an end.

    Example:
        >>> page_links(SearchRequest(q="x"), pages=2)
        (None, '/?q=x&page=2')
    """
    previous = page_url(request, request.page - 1) if request.page > 1 else None
    following = page_url(request, request.page + 1) if request.page < pages else None
    return previous, following


def encode_id(udi: str) -> str:
    """Return an opaque, URL-safe document ID for a Recoll ``rcludi``.

    Example:
        >>> encode_id("/data/a.txt|")
        'L2RhdGEvYS50eHR8'
    """
    raw = udi.encode("utf-8", "surrogateescape")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_id(value: str) -> str | None:
    """Return the ``rcludi`` of a document ID, or ``None`` for an invalid ID.

    Example:
        >>> decode_id(encode_id("/data/a.txt|"))
        '/data/a.txt|'
        >>> decode_id("../etc/passwd") is None
        True
    """
    if not _ID_PATTERN.fullmatch(value):
        return None
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except ValueError:
        return None
    return raw.decode("utf-8", "surrogateescape")


def recoll_text(value: str) -> str:
    """Return plain text from a Recoll abstract.

    Recoll escapes ``<`` and every ``&`` in an abstract, so :func:`html.unescape` is an exact
    inverse. Without it, the template escapes the text a second time and shows ``&lt;``.

    Example:
        >>> recoll_text("a &lt; b &amp;amp; c")
        'a < b &amp; c'
    """
    return html.unescape(value)


def strip_marks(text: str) -> str:
    """Return the text without match markers.

    Example:
        >>> strip_marks(f"a {MATCH_START}b{MATCH_END}")
        'a b'
    """
    return text.replace(MATCH_START, "").replace(MATCH_END, "")


def group_terms(groups: Iterable[tuple[Sequence[str], Sequence[str]]]) -> frozenset[str]:
    """Return all terms of ``Query.getgroups()``: the user terms and their expansions.

    Example:
        >>> sorted(group_terms([(["oberon"], ["Oberon", "oberons"]), (["a", "b"], ["A", "B"])]))
        ['A', 'B', 'Oberon', 'a', 'b', 'oberon', 'oberons']
    """
    return frozenset(term for users, expanded in groups for term in (*users, *expanded))


def mark_terms(text: str, terms: Iterable[str]) -> str:
    """Return ``text`` with match markers around each word that is one of ``terms``, in any case.

    A compound such as ``Oberon.Text`` matches as a whole. When it does not, its plain words can
    match one by one. The scan is linear, also for the long term lists of a wildcard query.

    Do not use ``Query.highlight`` for this: it turns plain text into HTML (``<br>`` for each
    line break) and can put the markers around the inserted tags.

    Example:
        >>> show = lambda s: s.replace(MATCH_START, "[").replace(MATCH_END, "]")
        >>> terms = ["oberon", "oberon's", "Oberon.Text"]
        >>> show(mark_terms("Oberon-based oberon's code. See OBERON.Text.", terms))
        "[Oberon]-based [oberon's] code. See [OBERON.Text]."
    """
    wanted = frozenset(term.lower() for term in terms if term)

    def mark(match: re.Match[str]) -> str:
        word = match.group(0)
        return f"{MATCH_START}{word}{MATCH_END}" if word.lower() in wanted else word

    def mark_token(match: re.Match[str]) -> str:
        marked = mark(match)
        return marked if marked != match.group(0) else _WORD.sub(mark, marked)

    return _TOKEN.sub(mark_token, text) if wanted else text


def highlight_markup(text: str) -> Markup:
    """Return safe HTML with each marked match in ``<mark>``.

    The function escapes each text segment. It opens and closes a tag in the same step, so the
    output stays balanced even when a document holds a stray marker character.

    Example:
        >>> highlight_markup(f"a < b {MATCH_START}Oberon{MATCH_END}!")
        Markup('a &lt; b <mark>Oberon</mark>!')
        >>> highlight_markup(f"{MATCH_END}<x>{MATCH_START}")
        Markup('&lt;x&gt;')
    """
    parts: list[Markup] = []
    inside = False
    for token in _MATCH_SPLIT.split(text):
        if token in (MATCH_START, MATCH_END):
            inside = token == MATCH_START
        elif token:
            parts.append(Markup("<mark>%s</mark>") % token if inside else escape(token))
    return Markup("").join(parts)


class _TextParser(HTMLParser):
    """Collect the text of an HTML document, without ``script`` and ``style`` content.

    A block element starts a new line, so that the words of two blocks stay apart.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:  # noqa: ARG002
        if tag in _HIDDEN_TAGS:
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _HIDDEN_TAGS:
            self._skip = max(self._skip - 1, 0)
        elif tag in _BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.chunks.append(data)


def html_to_text(markup: str) -> str:
    r"""Return the visible text of an HTML document.

    Example:
        >>> html_to_text("<title>T</title><p>a &amp; <b>b</b></p><style>p{}</style>c")
        'T\n\na & b\nc'
    """
    parser = _TextParser()
    parser.feed(markup)
    parser.close()
    return _BLANK_LINES.sub("\n\n", "".join(parser.chunks)).strip()


def as_plain_text(text: str, mime: str) -> str:
    """Return extracted document text as plain text, whatever type Recoll returned.

    Example:
        >>> as_plain_text("<b>x</b>", "text/html")
        'x'
        >>> as_plain_text("<b>x</b>", "text/plain")
        '<b>x</b>'
    """
    return html_to_text(text) if mime == "text/html" else text


def display_path(url: str) -> str:
    """Return the file path of a Recoll URL.

    Recoll stores ``file://`` and the raw path, without percent-encoding. Do not parse it as a URL:
    a ``#`` or a ``?`` in a file name would cut the path.

    Example:
        >>> display_path("file:///data/a #1.txt")
        '/data/a #1.txt'
        >>> display_path("https://example.org/x")
        'https://example.org/x'
    """
    return url.removeprefix("file://")


def member_filename(container: str, ipath: str, mime: str) -> str:
    """Return a download name for a document inside an archive or a mail folder.

    Example:
        >>> member_filename("list.mbox", "3", "message/rfc822")
        'list-3.eml'
        >>> member_filename("", "docs/a b.pdf", "application/x-unknown")
        'document-docs_a_b_pdf'
    """
    stem = os.path.splitext(container)[0] or "document"
    member = re.sub(r"\W+", "_", ipath).strip("_")
    return f"{stem}-{member}{mimetypes.guess_extension(mime) or ''}"


def format_date(timestamp: str, tz: tzinfo | None = None) -> str:
    """Return the ISO date of a Unix timestamp, or ``""`` when it is not one.

    ``tz=None`` uses the local time zone of the server.

    Example:
        >>> from datetime import timezone
        >>> format_date("1754000000", timezone.utc)
        '2025-07-31'
        >>> format_date("")
        ''
    """
    try:
        return datetime.fromtimestamp(int(float(timestamp)), tz).date().isoformat()
    except (ValueError, OverflowError, OSError):
        return ""


def to_hit(doc: Mapping[str, str], snippet: str, tz: tzinfo | None = None) -> Hit | None:
    """Return a hit for the fields of a Recoll document, or ``None`` when it has no ``rcludi``.

    Example:
        >>> from datetime import timezone
        >>> doc = {"rcludi": "u", "filename": "a.txt", "url": "file:///d/a.txt", "mtime": "0"}
        >>> hit = to_hit(doc, "snippet", timezone.utc)
        >>> hit.id, hit.title, hit.path, hit.modified
        ('dQ', 'a.txt', '/d/a.txt', '1970-01-01')
        >>> to_hit({"title": "no udi"}, "") is None
        True
    """
    udi = doc.get("rcludi", "")
    if not udi:
        return None
    return Hit(
        id=encode_id(udi),
        title=doc.get("title") or doc.get("filename") or "Untitled document",
        path=display_path(doc.get("url", "")),
        mime=doc.get("mtype", ""),
        modified=format_date(doc.get("mtime", ""), tz),
        snippet=snippet,
    )


def parse_topdirs(conf_text: str, home: str = "~") -> tuple[str, ...]:
    r"""Return the ``topdirs`` of a ``recoll.conf`` text, with ``~`` expanded.

    The function joins continuation lines and stops at the first subsection.

    Example:
        >>> conf = '# x\ntopdirs = ~/docs "/my mail" \\\n  /srv\n[~/docs]\ntopdirs = /no\n'
        >>> parse_topdirs(conf, home="/h")
        ('/h/docs', '/my mail', '/srv')
        >>> parse_topdirs("loglevel = 2")
        ()
    """
    for line in _CONTINUATION.sub(" ", conf_text).splitlines():
        if line.lstrip().startswith("["):
            break
        key, sep, value = line.partition("=")
        if sep and key.strip() == "topdirs":
            return tuple(re.sub(r"^~(?=/|$)", home, word) for word in shlex.split(value))
    return ()


def resolve_confdir(confdir: str | None, env: Mapping[str, str], home: str) -> str:
    """Return the Recoll configuration folder, in the order that Recoll itself uses.

    Example:
        >>> resolve_confdir(None, {"RECOLL_CONFDIR": "/etc/rcl"}, "/h")
        '/etc/rcl'
        >>> resolve_confdir(None, {}, "/h")
        '/h/.recoll'
    """
    return confdir or env.get("RECOLL_CONFDIR") or os.path.join(home, ".recoll")


def is_under(path: str, roots: Sequence[str]) -> bool:
    """Return whether ``path`` is inside one of ``roots``.

    The check is lexical. Resolve symbolic links in all arguments before the call.

    Example:
        >>> is_under("/data/a/b.txt", ["/srv", "/data/a"])
        True
        >>> is_under("/data/ab.txt", ["/data/a"])
        False
    """
    return any(os.path.commonpath([path, root]) == root for root in roots)


def is_loopback(host: str) -> bool:
    """Return whether a bind address only accepts local connections.

    Example:
        >>> is_loopback("127.0.0.1"), is_loopback("localhost"), is_loopback("0.0.0.0")
        (True, True, False)
    """
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def wants_fragment(headers: Mapping[str, str]) -> bool:
    """Return whether an htmx request wants a page fragment instead of the full page.

    An htmx history restore needs the full page, although it also sends ``HX-Request``.
    Pass headers with lowercase keys, or a case-insensitive mapping.

    Example:
        >>> wants_fragment({"hx-request": "true"})
        True
        >>> wants_fragment({"hx-request": "true", "hx-history-restore-request": "true"})
        False
    """
    return (
        headers.get("hx-request") == "true" and headers.get("hx-history-restore-request") != "true"
    )
