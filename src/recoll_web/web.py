# SPDX-License-Identifier: AGPL-3.0-only
"""The web layer: settings, request validation, routes, and templates.

:func:`create_app` builds the application from settings and a backend. The routes are closures
over these two values, so the module holds no global state.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.background import BackgroundTask

from . import __version__
from .core import (
    CATEGORIES,
    Category,
    ResultPage,
    SearchRequest,
    Sort,
    highlight_markup,
    page_links,
    strip_marks,
    wants_fragment,
)
from .recoll_backend import Backend, RecollError

logger = logging.getLogger(__name__)

HERE = Path(__file__).parent

#: Headers on every response. The CSP allows no inline script or style.
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; "
        "base-uri 'none'; form-action 'self'"
    ),
    "Referrer-Policy": "no-referrer",
    "Vary": "HX-Request",
    "X-Content-Type-Options": "nosniff",
}


class Settings(BaseSettings):
    """The configuration of recoll-web. Each field also reads ``RECOLL_WEB_<NAME>``.

    Example:
        >>> Settings(port=9000).host
        '127.0.0.1'
    """

    model_config = SettingsConfigDict(env_prefix="RECOLL_WEB_", frozen=True)

    host: str = "127.0.0.1"
    port: int = Field(8080, ge=1, le=65535)
    confdir: str | None = None
    dirs: tuple[str, ...] = ()
    allow_download: bool = False
    page_size: int = Field(20, ge=1, le=200)
    preview_chars: int = Field(45_000, ge=1)
    source_url: str = "https://github.com/maehr/recoll-web"


class SearchParams(BaseModel):
    """The query parameters of a search, validated at the HTTP boundary.

    Example:
        >>> request = SearchParams(q="x", after="", page="2").to_request()
        >>> request.after, request.page
        (None, 2)
    """

    q: str = Field("", max_length=500)
    category: Category = "all"
    dir: str = Field("", max_length=4096)
    after: date | None = None
    before: date | None = None
    sort: Sort = "relevance"
    page: int = Field(1, ge=1, le=10_000)

    @field_validator("after", "before", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        """Read the empty value of an unset HTML date input as no date."""
        return value or None

    def to_request(self) -> SearchRequest:
        """Return the request as a core value."""
        return SearchRequest(**self.model_dump())


def run_search(backend: Backend, request: SearchRequest) -> tuple[ResultPage, str | None]:
    """Return the results and an error message for the user, or ``None`` when there is no error.

    Example:
        >>> def broken(_request): raise RecollError("index is gone")
        >>> run_search(Backend(broken, None, None), SearchRequest(q="x"))[1]
        'index is gone'
    """
    try:
        return backend.search(request), None
    except RecollError as exc:
        return ResultPage(hits=(), total=0, page=1, pages=0), str(exc)
    except Exception:
        logger.exception("Recoll search failed")
        return ResultPage(hits=(), total=0, page=1, pages=0), "The search failed. See the log."


def api_page(page: ResultPage) -> dict[str, Any]:
    """Return a result page as JSON data: the snippet as plain text and as safe HTML.

    Example:
        >>> api_page(ResultPage(hits=(), total=0, page=1, pages=0))
        {'hits': [], 'total': 0, 'page': 1, 'pages': 0}
    """
    hits = [
        asdict(hit)
        | {"snippet": strip_marks(hit.snippet), "snippet_html": highlight_markup(hit.snippet)}
        for hit in page.hits
    ]
    return asdict(page) | {"hits": hits}


def make_templates(settings: Settings) -> Jinja2Templates:
    """Return the template engine, with the ``marks`` filter and the values that each page reads."""
    page_globals = {"categories": CATEGORIES, "settings": settings, "version": __version__}
    templates = Jinja2Templates(
        directory=HERE / "templates", context_processors=[lambda _request: page_globals]
    )
    templates.env.filters["marks"] = highlight_markup
    return templates


def create_app(settings: Settings, backend: Backend) -> FastAPI:
    """Return the application for a backend.

    Example:
        >>> from fastapi.testclient import TestClient
        >>> from .core import EMPTY_PAGE
        >>> app = create_app(Settings(), Backend(lambda r: EMPTY_PAGE, None, None))
        >>> TestClient(app).get("/").status_code
        200
    """
    app = FastAPI(title="Recoll Web", version=__version__, docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = make_templates(settings)

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    def render(request: Request, params: SearchParams, **extra: object) -> HTMLResponse:
        search = params.to_request()
        page, error = run_search(backend, search)
        previous_url, next_url = page_links(search, page.pages)
        context = {
            "search": search,
            "page": page,
            "error": error,
            "previous_url": previous_url,
            "next_url": next_url,
        }
        fragment = wants_fragment(request.headers) and not extra
        name = "_results.html" if fragment else "index.html"
        return templates.TemplateResponse(request, name, context | extra)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, params: Annotated[SearchParams, Query()]) -> HTMLResponse:
        return render(request, params)

    @app.get("/api/search")
    def api_search(params: Annotated[SearchParams, Query()]) -> dict[str, Any]:
        page, error = run_search(backend, params.to_request())
        if error:
            raise HTTPException(status_code=503, detail=error)
        return api_page(page)

    @app.get("/preview/{doc_id}", response_class=HTMLResponse)
    def preview(
        request: Request, doc_id: str, q: Annotated[str, Query(max_length=500)] = ""
    ) -> HTMLResponse:
        try:
            result = backend.preview(doc_id, q)
        except RecollError as exc:
            result, status, message = None, 503, str(exc)
        else:
            status, message = (
                (200, None) if result else (404, "The index does not hold this document.")
            )
        context = {"preview": result, "preview_error": message}
        if wants_fragment(request.headers):
            return templates.TemplateResponse(request, "_preview.html", context, status_code=status)
        response = render(request, SearchParams(q=q), **context)
        response.status_code = status
        return response

    @app.get("/download/{doc_id}")
    def download(doc_id: str) -> FileResponse:
        if not settings.allow_download:
            raise HTTPException(status_code=404)
        try:
            found = backend.fetch(doc_id)
        except RecollError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if found is None:
            raise HTTPException(status_code=404)
        return FileResponse(
            found.path,
            filename=found.filename,
            media_type=found.mime,
            content_disposition_type="attachment",
            background=BackgroundTask(os.unlink, found.path) if found.temporary else None,
        )

    return app
