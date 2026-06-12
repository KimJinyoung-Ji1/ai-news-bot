"""Unit tests for src/fetchers/arxiv.py — mock requests, no real network calls."""
import datetime
from unittest.mock import patch, MagicMock
import pytest


# 최근 논문 날짜는 동적으로 — 절대 날짜를 박으면 days 필터 경계를 시간이 지나며 벗어나
# 테스트가 깨진다(2026-05 고정값이 7일 윈도우 밖으로 밀려난 사례).
_RECENT_PUB = (
    datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
).strftime("%Y-%m-%dT%H:%M:%SZ")

# Minimal Atom feed XML for arXiv
_ATOM_FEED_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>https://arxiv.org/abs/2505.12345</id>
    <title>LLM Agent Self-Improvement via Reinforcement</title>
    <summary>We propose a novel RL-based method for LLM agent self-improvement.</summary>
    <published>{_RECENT_PUB}</published>
  </entry>
  <entry>
    <id>https://arxiv.org/abs/2505.99999</id>
    <title>Old Paper Outside Window</title>
    <summary>A very old paper that should be filtered out.</summary>
    <published>2020-01-01T00:00:00Z</published>
  </entry>
</feed>"""


def _make_mock_feed(xml: str):
    import feedparser
    return feedparser.parse(xml)


class TestArxivFetcher:
    def test_mock_requests_returns_articles(self):
        """Mock feedparser.parse and confirm articles are returned."""
        cfg = {"enabled": True, "categories": ["cs.AI"], "days": 7, "max_per_fetch": 20}
        mock_feed = _make_mock_feed(_ATOM_FEED_XML)

        with patch("src.fetchers.arxiv.feedparser.parse", return_value=mock_feed):
            with patch("src.fetchers.arxiv.time.sleep"):
                from src.fetchers.arxiv import fetch_arxiv_articles
                articles = fetch_arxiv_articles(cfg)

        # At least 1 article (recent one passes date filter)
        assert len(articles) >= 1

    def test_parses_atom_feed_fields(self):
        """Confirm title, link, summary, pub_date are correctly parsed."""
        cfg = {"enabled": True, "categories": ["cs.AI"], "days": 365, "max_per_fetch": 20}
        mock_feed = _make_mock_feed(_ATOM_FEED_XML)

        with patch("src.fetchers.arxiv.feedparser.parse", return_value=mock_feed):
            with patch("src.fetchers.arxiv.time.sleep"):
                from src.fetchers.arxiv import fetch_arxiv_articles
                articles = fetch_arxiv_articles(cfg)

        assert any(art for art in articles if "LLM Agent" in art["title"])
        recent = next(a for a in articles if "LLM Agent" in a["title"])
        assert recent["link"].startswith("https://arxiv.org/abs/")
        assert "RL" in recent["summary"] or "novel" in recent["summary"]
        assert recent["pub_date"] is not None
        assert isinstance(recent["pub_date"], datetime.datetime)

    def test_filter_by_date_excludes_old_papers(self):
        """Papers older than cfg['days'] must be excluded."""
        cfg = {"enabled": True, "categories": ["cs.AI"], "days": 7, "max_per_fetch": 20}
        mock_feed = _make_mock_feed(_ATOM_FEED_XML)

        with patch("src.fetchers.arxiv.feedparser.parse", return_value=mock_feed):
            with patch("src.fetchers.arxiv.time.sleep"):
                from src.fetchers.arxiv import fetch_arxiv_articles
                articles = fetch_arxiv_articles(cfg)

        # "Old Paper" from 2020 must be filtered out
        titles = [a["title"] for a in articles]
        assert not any("Old Paper" in t for t in titles)

    def test_disabled_returns_empty(self):
        """When enabled=False, no network call and empty list."""
        cfg = {"enabled": False}
        with patch("src.fetchers.arxiv.feedparser.parse") as mock_parse:
            from src.fetchers.arxiv import fetch_arxiv_articles
            articles = fetch_arxiv_articles(cfg)

        assert articles == []
        mock_parse.assert_not_called()
