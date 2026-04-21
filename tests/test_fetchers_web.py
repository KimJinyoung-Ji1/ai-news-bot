import pytest
from unittest.mock import patch, MagicMock
from src.fetchers.web import fetch_web_articles


def _html_with_links(links):
    """Build minimal HTML with anchor tags."""
    tags = "\n".join(f'<a href="{href}">{text}</a>' for href, text in links)
    return f"<html><body>{tags}</body></html>"


def _mock_response(status=200, text="<html><body></body></html>"):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    return resp


def test_fetch_web_returns_list():
    with patch("requests.get", return_value=_mock_response()):
        result = fetch_web_articles([], ["claude"])
    assert isinstance(result, list)


def test_fetch_web_empty_sources():
    result = fetch_web_articles([], ["claude"])
    assert result == []


def test_fetch_web_skips_non_200():
    with patch("requests.get", return_value=_mock_response(status=404)):
        result = fetch_web_articles([{"name": "Bad", "url": "https://bad.com"}], ["claude"])
    assert result == []


def test_fetch_web_finds_matching_links():
    html = _html_with_links([
        ("https://example.com/article", "New Claude API update announced today"),
    ])
    with patch("requests.get", return_value=_mock_response(text=html)):
        result = fetch_web_articles(
            [{"name": "TestSrc", "url": "https://example.com"}],
            ["claude"]
        )
    assert len(result) == 1
    assert result[0]["source"] == "TestSrc"
    assert "claude" in result[0]["title"].lower()


def test_fetch_web_ignores_short_text():
    html = _html_with_links([
        ("https://example.com/article", "AI"),  # too short (<15 chars)
    ])
    with patch("requests.get", return_value=_mock_response(text=html)):
        result = fetch_web_articles(
            [{"name": "TestSrc", "url": "https://example.com"}],
            ["ai"]
        )
    assert result == []


def test_fetch_web_ignores_non_matching_links():
    html = _html_with_links([
        ("https://example.com/sports", "Football match results from yesterday"),
    ])
    with patch("requests.get", return_value=_mock_response(text=html)):
        result = fetch_web_articles(
            [{"name": "TestSrc", "url": "https://example.com"}],
            ["claude", "gpt"]
        )
    assert result == []


def test_fetch_web_fixes_relative_urls():
    html = _html_with_links([
        ("/article/claude-update", "New Claude model features announced here"),
    ])
    with patch("requests.get", return_value=_mock_response(text=html)):
        result = fetch_web_articles(
            [{"name": "TestSrc", "url": "https://example.com/news"}],
            ["claude"]
        )
    assert len(result) == 1
    assert result[0]["link"].startswith("https://")


def test_fetch_web_handles_exception(capsys):
    with patch("requests.get", side_effect=Exception("net error")):
        result = fetch_web_articles(
            [{"name": "BadSrc", "url": "https://bad.com"}],
            ["claude"]
        )
    assert result == []
    captured = capsys.readouterr()
    assert "Web error" in captured.out


def test_fetch_web_limits_to_30_links():
    links = [(f"https://example.com/{i}", f"Claude AI news article number {i} here") for i in range(50)]
    html = _html_with_links(links)
    with patch("requests.get", return_value=_mock_response(text=html)):
        result = fetch_web_articles(
            [{"name": "Src", "url": "https://example.com"}],
            ["claude"]
        )
    assert len(result) <= 30
