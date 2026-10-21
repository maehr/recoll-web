# SPDX-License-Identifier: AGPL-3.0-only
"""Routes, templates, and headers, with a stub backend."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from recoll_web.core import MATCH_END, MATCH_START, Hit, Preview, ResultPage, SearchRequest
from recoll_web.recoll_backend import Download, RecollError
from recoll_web.web import Settings, create_app

from conftest import StubBackend

HTMX = {"HX-Request": "true"}

HIT = Hit(
    id="dWRpLTA",
    title='Proposal <script>alert("x")</script>',
    path="/data/proposal #1.txt",
    mime="text/plain",
    modified="2025-07-31",
    snippet=f"a < b & {MATCH_START}oberon{MATCH_END}",
)
PAGE = ResultPage(hits=(HIT,), total=25, page=2, pages=3)


def client_for(stub: StubBackend, **settings: object) -> TestClient:
    return TestClient(create_app(Settings(**settings), stub.backend()))  # ty: ignore[invalid-argument-type]


def test_home_page() -> None:
    response = client_for(StubBackend()).get("/")
    assert response.status_code == 200
    assert "Ready to search" in response.text
    assert '<script defer src="/static/htmx.min.js">' in response.text
    assert 'hx-get="/"' in response.text
    assert "Folder" not in response.text  # no dirs, so no folder filter


def test_security_headers() -> None:
    headers = client_for(StubBackend()).get("/").headers
    assert "default-src 'self'" in headers["content-security-policy"]
    assert headers["cache-control"] == "no-store"
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "no-referrer"
    assert headers["vary"] == "HX-Request"


def test_no_inline_script_or_handler() -> None:
    text = client_for(StubBackend(page=PAGE)).get("/?q=oberon").text
    assert "<script>" not in text
    assert "onclick" not in text


def test_htmx_search_returns_the_results_fragment() -> None:
    stub = StubBackend(page=PAGE)
    response = client_for(stub).get("/?q=oberon&category=message&sort=newest&page=2", headers=HTMX)
    assert response.status_code == 200
    assert "<!doctype html>" not in response.text
    assert "Proposal &lt;script&gt;" in response.text
    assert "a &lt; b &amp; <mark>oberon</mark>" in response.text  # escaped once, not twice
    assert "/data/proposal #1.txt" in response.text
    assert (
        'href="/?q=oberon&amp;category=message&amp;sort=newest"' in response.text
    )  # previous page
    assert "page=3" in response.text
    expected = SearchRequest(q="oberon", category="message", sort="newest", page=2)
    assert stub.calls == [("search", expected)]


def test_history_restore_gets_the_full_page() -> None:
    headers = HTMX | {"HX-History-Restore-Request": "true"}
    response = client_for(StubBackend(page=PAGE)).get("/?q=oberon", headers=headers)
    assert "<!doctype html>" in response.text


def test_full_page_keeps_the_form_state() -> None:
    url = "/?q=oberon&category=text&after=2020-01-02&before=&sort=oldest&dir=/srv/a"
    text = client_for(StubBackend(page=PAGE), dirs=("/srv/a", "/srv/b")).get(url).text
    assert '<option value="text" selected>' in text
    assert '<option value="/srv/a" selected>' in text
    assert '<option value="/srv/b" >' in text
    assert 'name="after" value="2020-01-02"' in text
    assert 'name="before" value=""' in text
    assert '<option value="oldest" selected>' in text


@pytest.mark.parametrize(
    "query", ["category=../../x", "page=0", "page=x", "after=yesterday", f"q={'x' * 501}"]
)
def test_invalid_parameters_are_rejected(query: str) -> None:
    assert client_for(StubBackend()).get(f"/?{query}").status_code == 422


def test_no_matches() -> None:
    text = client_for(StubBackend()).get("/?q=nothing", headers=HTMX).text
    assert "No matches found" in text


def test_recoll_error_is_shown() -> None:
    stub = StubBackend(error=RecollError("The Recoll index does not open."))
    text = client_for(stub).get("/?q=x", headers=HTMX).text
    assert "Recoll unavailable" in text
    assert "does not open" in text


def test_unexpected_error_is_logged_not_shown(caplog: pytest.LogCaptureFixture) -> None:
    stub = StubBackend(error=ValueError("/secret/path"))
    with caplog.at_level(logging.ERROR):
        text = client_for(stub).get("/?q=x", headers=HTMX).text
    assert "The search failed" in text
    assert "/secret/path" not in text
    assert "Recoll search failed" in caplog.text


def test_api_search() -> None:
    data = client_for(StubBackend(page=PAGE)).get("/api/search?q=oberon").json()
    assert data["total"] == 25
    assert data["hits"][0]["snippet"] == "a < b & oberon"
    assert data["hits"][0]["snippet_html"] == "a &lt; b &amp; <mark>oberon</mark>"


def test_api_search_error() -> None:
    response = client_for(StubBackend(error=RecollError("gone"))).get("/api/search?q=x")
    assert response.status_code == 503
    assert response.json() == {"detail": "gone"}


PREVIEW = Preview(title="Report <b>", text=f"x {MATCH_START}y{MATCH_END} <i>", truncated=True)


def test_preview_fragment() -> None:
    stub = StubBackend(preview_result=PREVIEW)
    response = client_for(stub).get("/preview/abc?q=y", headers=HTMX)
    assert response.status_code == 200
    assert "<!doctype html>" not in response.text
    assert "Report &lt;b&gt;" in response.text
    assert "x <mark>y</mark> &lt;i&gt;" in response.text
    assert "start of the text only" in response.text
    assert stub.calls == [("preview", ("abc", "y"))]


def test_preview_without_htmx_is_a_full_page() -> None:
    text = client_for(StubBackend(preview_result=PREVIEW)).get("/preview/abc?q=y").text
    assert "<!doctype html>" in text
    assert 'value="y"' in text
    assert "x <mark>y</mark>" in text


def test_preview_of_empty_text() -> None:
    stub = StubBackend(preview_result=Preview(title="T", text="", truncated=False))
    text = client_for(stub).get("/preview/abc", headers=HTMX).text
    assert "no text for this document" in text


def test_preview_not_found() -> None:
    response = client_for(StubBackend()).get("/preview/abc", headers=HTMX)
    assert response.status_code == 404
    assert "does not hold this document" in response.text


def test_preview_error_without_htmx() -> None:
    response = client_for(StubBackend(error=RecollError("cannot extract"))).get("/preview/abc")
    assert response.status_code == 503
    assert "<!doctype html>" in response.text
    assert "cannot extract" in response.text


def test_download_is_off_by_default() -> None:
    stub = StubBackend(download=Download("/etc/hosts", "hosts", "text/plain", temporary=False))
    assert client_for(stub).get("/download/abc").status_code == 404
    assert stub.calls == []
    assert "/download/" not in client_for(StubBackend(page=PAGE)).get("/?q=x").text


def test_download_link_when_allowed() -> None:
    text = client_for(StubBackend(page=PAGE), allow_download=True).get("/?q=x").text
    assert 'href="/download/dWRpLTA"' in text


def test_download_sends_an_attachment(tmp_path: Path) -> None:
    target = tmp_path / "a.html"
    target.write_text("<script>x</script>")
    stub = StubBackend(download=Download(str(target), "a.html", "text/html", temporary=False))
    response = client_for(stub, allow_download=True).get("/download/abc")
    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.text == "<script>x</script>"
    assert target.exists()


def test_download_removes_a_temporary_file(tmp_path: Path) -> None:
    target = tmp_path / "member"
    target.write_text("member")
    stub = StubBackend(download=Download(str(target), "m.eml", "message/rfc822", temporary=True))
    assert client_for(stub, allow_download=True).get("/download/abc").text == "member"
    assert not target.exists()


def test_download_not_found() -> None:
    assert client_for(StubBackend(), allow_download=True).get("/download/abc").status_code == 404


def test_download_error() -> None:
    stub = StubBackend(error=RecollError("cannot extract"))
    response = client_for(stub, allow_download=True).get("/download/abc")
    assert response.status_code == 503


def test_static_files_and_source_link() -> None:
    client = client_for(StubBackend(), source_url="https://example.org/src")
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/htmx.min.js").status_code == 200
    assert 'href="https://example.org/src"' in client.get("/").text
