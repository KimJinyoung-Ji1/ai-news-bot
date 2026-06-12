"""Unit tests for src/fetchers/github_trending.py — mock HTML parsing, no real network."""
from unittest.mock import patch, MagicMock
import pytest


# Minimal HTML mimicking GitHub trending page structure
_TRENDING_HTML = """
<html><body>
<article class="Box-row">
  <h2><a href="/openai/gpt-5-tools">openai / gpt-5-tools</a></h2>
  <p>An open-source LLM agent framework with MCP support</p>
  <a href="/openai/gpt-5-tools/stargazers">1,234</a>
</article>
<article class="Box-row">
  <h2><a href="/some/css-framework-tools">some / css-framework-tools</a></h2>
  <p>A CSS framework for web design and layouts</p>
  <a href="/some/css-framework-tools/stargazers">500</a>
</article>
</body></html>
"""


def _mock_response(html: str, status: int = 200) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.status_code = status
    mock_resp.text = html
    return mock_resp


class TestGitHubTrendingFetcher:
    def test_mock_parse_html_returns_ai_repos(self):
        """Mock requests.get and confirm AI-keyword repos are returned."""
        cfg = {
            "enabled": True,
            "languages": ["Python"],
            "keywords": ["ai", "llm", "claude", "mcp", "agent"],
            "max_per_fetch": 20,
        }
        mock_resp = _mock_response(_TRENDING_HTML)

        with patch("src.fetchers.github_trending.requests.get", return_value=mock_resp):
            with patch("src.fetchers.github_trending.time.sleep"):
                from src.fetchers.github_trending import fetch_github_trending_articles
                articles = fetch_github_trending_articles(cfg)

        assert len(articles) >= 1
        titles = [a["title"] for a in articles]
        # AI repos should be included
        assert any("gpt-5-tools" in t or "llm" in t.lower() or "mcp" in t.lower() for t in titles)

    def test_language_filter_adds_source_tag(self):
        """Each article source should include the language name."""
        cfg = {
            "enabled": True,
            "languages": ["TypeScript"],
            "keywords": ["ai", "llm", "mcp", "agent"],
            "max_per_fetch": 20,
        }
        mock_resp = _mock_response(_TRENDING_HTML)

        with patch("src.fetchers.github_trending.requests.get", return_value=mock_resp):
            with patch("src.fetchers.github_trending.time.sleep"):
                from src.fetchers.github_trending import fetch_github_trending_articles
                articles = fetch_github_trending_articles(cfg)

        for art in articles:
            assert "TypeScript" in art["source"], f"Expected TypeScript in source: {art['source']}"

    def test_non_ai_repos_excluded(self):
        """Repos without AI keywords in title or description must be excluded."""
        cfg = {
            "enabled": True,
            "languages": ["Python"],
            "keywords": ["ai", "llm", "claude", "mcp", "agent"],
            "max_per_fetch": 20,
        }
        mock_resp = _mock_response(_TRENDING_HTML)

        with patch("src.fetchers.github_trending.requests.get", return_value=mock_resp):
            with patch("src.fetchers.github_trending.time.sleep"):
                from src.fetchers.github_trending import fetch_github_trending_articles
                articles = fetch_github_trending_articles(cfg)

        titles = [a["title"] for a in articles]
        # css-framework-tools is CSS framework, no AI keywords — must be excluded
        assert not any("css-framework-tools" in t for t in titles)

    def test_disabled_returns_empty(self):
        """When enabled=False, no network call and empty list."""
        cfg = {"enabled": False}
        with patch("src.fetchers.github_trending.requests.get") as mock_get:
            from src.fetchers.github_trending import fetch_github_trending_articles
            articles = fetch_github_trending_articles(cfg)

        assert articles == []
        mock_get.assert_not_called()
