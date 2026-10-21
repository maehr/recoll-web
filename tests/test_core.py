# SPDX-License-Identifier: AGPL-3.0-only
"""Edge cases of the pure functions. The doctests in ``core.py`` cover the common cases."""

from __future__ import annotations

from datetime import UTC, date

import pytest

from recoll_web.core import (
    MATCH_END,
    MATCH_START,
    SearchRequest,
    build_query,
    decode_id,
    encode_id,
    format_date,
    highlight_markup,
    html_to_text,
    page_links,
    parse_topdirs,
    query_params,
    to_hit,
)


@pytest.mark.parametrize(
    ("request_", "expected"),
    [
        (SearchRequest(q="  x  "), "x"),
        (SearchRequest(q="x", before=date(2010, 1, 2)), "(x) date:/2010-01-02"),
        (
            SearchRequest(q="x", after=date(2001, 1, 1), before=date(2002, 1, 1)),
            "(x) date:2001-01-01/2002-01-01",
        ),
        (SearchRequest(q="x", dir='/a "b"'), '(x) dir:"/a b"'),
        (SearchRequest(q="x", dir='"'), "x"),
    ],
)
def test_build_query(request_: SearchRequest, expected: str) -> None:
    assert build_query(request_) == expected


def test_query_params_keeps_dates_and_drops_defaults() -> None:
    params = query_params(SearchRequest(q="x", after=date(2020, 5, 1), page=1))
    assert params == {"q": "x", "after": "2020-05-01"}


def test_page_links_in_the_middle() -> None:
    previous, following = page_links(SearchRequest(q="x", page=2), pages=3)
    assert previous == "/?q=x"  # page 1 is the default, so the URL leaves it out
    assert following == "/?q=x&page=3"


@pytest.mark.parametrize("udi", ["x", "/path/ä ö|ipath", "\udcff-not-utf8"])
def test_id_round_trip(udi: str) -> None:
    assert decode_id(encode_id(udi)) == udi


@pytest.mark.parametrize("value", ["", "A", "a=b", "x" * 8193, "%2F"])
def test_decode_id_rejects(value: str) -> None:
    assert decode_id(value) is None


def test_highlight_escapes_the_marked_text_too() -> None:
    markup = highlight_markup(
        f"{MATCH_START}<b>{MATCH_END} & {MATCH_START}{MATCH_START}x{MATCH_END}"
    )
    assert str(markup) == "<mark>&lt;b&gt;</mark> &amp; <mark>x</mark>"


def test_html_to_text_separates_blocks_and_collapses_blank_lines() -> None:
    assert html_to_text("<div><p>x</p></div><br><br><br>y<span>z</span>") == "x\n\nyz"


def test_html_to_text_handles_unbalanced_tags() -> None:
    # The parser reads script content as raw text, so "<script>b" is data, not a nested tag.
    assert html_to_text("</script>a<script><script>b</script>c</script>d") == "acd"


def test_format_date_rejects_out_of_range() -> None:
    assert format_date("1e30", UTC) == ""


def test_parse_topdirs_expands_only_a_leading_tilde() -> None:
    assert parse_topdirs("topdirs = ~ /a~b ~user", "/h") == ("/h", "/a~b", "~user")


def test_to_hit_falls_back_to_a_generic_title() -> None:
    hit = to_hit({"rcludi": "u"}, "")
    assert hit is not None
    assert hit.title == "Untitled document"
    assert hit.modified == ""


def test_parse_topdirs_ignores_subsections() -> None:
    assert parse_topdirs("[/data]\ntopdirs = /no\n") == ()
