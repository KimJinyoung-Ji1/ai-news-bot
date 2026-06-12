"""Unit tests for src/fetchers/hackernews.py — mock Algolia API, no real network."""
from unittest.mock import patch, MagicMock
import datetime
import json
import pytest


def _mock_hn_response(hits: list) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"hits": hits}
    return mock_resp


_SAMPLE_HITS = [
    {
        "objectID": "12345",
        "title": "Claude 3.7 Sonnet shows 70% improvement on coding benchmarks",
        "url": "https://anthropic.com/news/claude-3-7",
        "points": 450,
        "created_at": "2026-05-14T10:00:00Z",
    },
    {
        "objectID": "67890",
        "title": "OpenAI GPT-5 API now available for developers",
        "url": "https://openai.com/blog/gpt5-api",
        "points": 320,
        "created_at": "2026-05-14T08:00:00Z",
    },
]


class TestHackerNewsFetcher:
    def test_mock_api_returns_articles(self):
        """Mock requests.get and confirm articles are returned."""
        cfg = {
            "enabled": True,
            "keywords": ["Claude"],
            "max_per_fetch": 30,
        }
        mock_resp = _mock_hn_response(_SAMPLE_HITS)

        with patch("src.fetchers.hackernews.requests.get", return_value=mock_resp):
            with patch("src.fetchers.hackernews.time.sleep"):
                from src.fetchers.hackernews import fetch_hackernews_articles
                articles = fetch_hackernews_articles(cfg)

        assert len(articles) >= 1

    def test_keyword_filter_deduplicates(self):
        """Same story appearing in multiple keyword queries is deduplicated."""
        cfg = {
            "enabled": True,
            "keywords": ["Claude", "Anthropic"],  # Both queries may return same story
            "max_per_fetch": 30,
        }
        mock_resp = _mock_hn_response(_SAMPLE_HITS)

        with patch("src.fetchers.hackernews.requests.get", return_value=mock_resp):
            with patch("src.fetchers.hackernews.time.sleep"):
                from src.fetchers.hackernews import fetch_hackernews_articles
                articles = fetch_hackernews_articles(cfg)

        links = [a["link"] for a in articles]
        assert len(links) == len(set(links)), "Duplicate links found"

    def test_article_fields_normalized(self):
        """Confirm required ai-news-bot fields are present and typed correctly."""
        cfg = {
            "enabled": True,
            "keywords": ["Claude"],
            "max_per_fetch": 30,
        }
        mock_resp = _mock_hn_response(_SAMPLE_HITS)

        with patch("src.fetchers.hackernews.requests.get", return_value=mock_resp):
            with patch("src.fetchers.hackernews.time.sleep"):
                from src.fetchers.hackernews import fetch_hackernews_articles
                articles = fetch_hackernews_articles(cfg)

        for art in articles:
            assert "source" in art
            assert art["source"] == "HackerNews"
            assert "title" in art and art["title"]
            assert "link" in art and art["link"].startswith("http")
            assert "summary" in art
            assert "pub_date" in art
            assert "weight" in art

    def test_disabled_returns_empty(self):
        """When enabled=False, no network call and empty list."""
        cfg = {"enabled": False}
        with patch("src.fetchers.hackernews.requests.get") as mock_get:
            from src.fetchers.hackernews import fetch_hackernews_articles
            articles = fetch_hackernews_articles(cfg)

        assert articles == []
        mock_get.assert_not_called()
