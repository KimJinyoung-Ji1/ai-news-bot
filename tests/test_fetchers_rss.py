import pytest
from unittest.mock import patch, MagicMock
from src.fetchers.rss import fetch_rss_articles


def _make_entry(title="Test Title", link="https://example.com/article", summary="<p>Summary</p>", published="Mon, 01 Jan 2024"):
    entry = MagicMock()
    entry.get.side_effect = lambda k, default="": {
        "title": title, "link": link, "summary": summary, "published": published
    }.get(k, default)
    return entry


def _make_feed(entries):
    feed = MagicMock()
    feed.entries = entries
    return feed


def test_fetch_rss_returns_list():
    with patch("feedparser.parse", return_value=_make_feed([])):
        result = fetch_rss_articles([{"name": "TestFeed", "url": "https://example.com/rss"}])
    assert isinstance(result, list)


def test_fetch_rss_parses_articles():
    entry = _make_entry()
    with patch("feedparser.parse", return_value=_make_feed([entry])):
        result = fetch_rss_articles([{"name": "TestFeed", "url": "https://example.com/rss"}])
    assert len(result) == 1
    assert result[0]["title"] == "Test Title"
    assert result[0]["link"] == "https://example.com/article"
    assert result[0]["source"] == "TestFeed"


def test_fetch_rss_strips_html_from_summary():
    entry = _make_entry(summary="<b>Bold text</b> plain")
    with patch("feedparser.parse", return_value=_make_feed([entry])):
        result = fetch_rss_articles([{"name": "Feed", "url": "https://example.com/rss"}])
    assert "<b>" not in result[0]["summary"]
    assert "Bold text" in result[0]["summary"]


def test_fetch_rss_skips_empty_title():
    entry = _make_entry(title="", link="https://example.com/article")
    with patch("feedparser.parse", return_value=_make_feed([entry])):
        result = fetch_rss_articles([{"name": "Feed", "url": "https://example.com/rss"}])
    assert len(result) == 0


def test_fetch_rss_skips_empty_link():
    entry = _make_entry(title="Title", link="")
    with patch("feedparser.parse", return_value=_make_feed([entry])):
        result = fetch_rss_articles([{"name": "Feed", "url": "https://example.com/rss"}])
    assert len(result) == 0


def test_fetch_rss_limits_to_10_entries():
    entries = [_make_entry(title=f"Title {i}", link=f"https://example.com/{i}") for i in range(20)]
    with patch("feedparser.parse", return_value=_make_feed(entries)):
        result = fetch_rss_articles([{"name": "Feed", "url": "https://example.com/rss"}])
    assert len(result) == 10


def test_fetch_rss_handles_exception(capsys):
    with patch("feedparser.parse", side_effect=Exception("parse error")):
        result = fetch_rss_articles([{"name": "BadFeed", "url": "https://bad.url/rss"}])
    assert result == []
    captured = capsys.readouterr()
    assert "RSS error" in captured.out


def test_fetch_rss_multiple_sources():
    entry1 = _make_entry(title="Article 1", link="https://src1.com/a")
    entry2 = _make_entry(title="Article 2", link="https://src2.com/b")
    feeds = [_make_feed([entry1]), _make_feed([entry2])]
    with patch("feedparser.parse", side_effect=feeds):
        result = fetch_rss_articles([
            {"name": "Src1", "url": "https://src1.com/rss"},
            {"name": "Src2", "url": "https://src2.com/rss"},
        ])
    assert len(result) == 2
    sources = {r["source"] for r in result}
    assert sources == {"Src1", "Src2"}
