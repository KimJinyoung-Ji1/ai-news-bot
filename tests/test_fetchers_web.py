import datetime
import pytest
from unittest.mock import patch, MagicMock
from src.fetchers.web import fetch_web_articles

_MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _recent_date_str(days_ago: int = 2) -> str:
    """오늘 기준 N일 전 날짜를 'Mon DD, YYYY' 형식으로 (로케일 무관)."""
    d = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_ago)
    return f"{_MONTH_ABBR[d.month - 1]} {d.day}, {d.year}"


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
        ("https://example.com/article", f"New Claude API update {_recent_date_str()}"),
    ])
    with patch("requests.get", return_value=_mock_response(text=html)):
        result = fetch_web_articles(
            [{"name": "TestSrc", "url": "https://example.com"}],
            ["claude"]
        )
    assert len(result) == 1
    assert result[0]["source"] == "TestSrc"
    assert "claude" in result[0]["title"].lower()


def test_fetch_web_parses_real_pub_date():
    """제목에 박힌 날짜를 실제 발행일로 파싱한다 (긁은 시각으로 박지 않음)."""
    html = _html_with_links([
        ("https://example.com/a", "Introducing Claude Opus 4.7 Apr 16, 2026"),
    ])
    with patch("requests.get", return_value=_mock_response(text=html)):
        # max_age_days 를 넉넉히 줘서 날짜 파싱 자체만 확인
        result = fetch_web_articles(
            [{"name": "TestSrc", "url": "https://example.com"}],
            ["claude"],
            max_age_days=100000,
        )
    assert len(result) == 1
    assert result[0]["pub_date"].date() == datetime.date(2026, 4, 16)
    # 제목에서 날짜 텍스트가 제거됐는지
    assert "2026" not in result[0]["title"]


def test_fetch_web_skips_undated_links():
    """발행일을 못 찾는 링크(네비게이션/박제 항목)는 제외한다."""
    html = _html_with_links([
        ("https://example.com/nav", "New Claude API update announced today"),
    ])
    with patch("requests.get", return_value=_mock_response(text=html)):
        result = fetch_web_articles(
            [{"name": "TestSrc", "url": "https://example.com"}],
            ["claude"]
        )
    assert result == []


def test_fetch_web_skips_old_dated_links():
    """발행일이 max_age_days 를 넘는 옛날 항목은 제외한다."""
    html = _html_with_links([
        ("https://example.com/old", f"Old Claude announcement {_recent_date_str(days_ago=90)}"),
    ])
    with patch("requests.get", return_value=_mock_response(text=html)):
        result = fetch_web_articles(
            [{"name": "TestSrc", "url": "https://example.com"}],
            ["claude"],
            max_age_days=14,
        )
    assert result == []


def test_fetch_web_skips_email_links():
    """footer 이메일 등 '@' 포함 링크는 제외한다."""
    html = _html_with_links([
        ("mailto:press@anthropic.com", f"press@anthropic.com {_recent_date_str()}"),
    ])
    with patch("requests.get", return_value=_mock_response(text=html)):
        result = fetch_web_articles(
            [{"name": "TestSrc", "url": "https://example.com"}],
            ["anthropic"]
        )
    assert result == []


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
        ("/article/claude-update", f"New Claude model features {_recent_date_str()}"),
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


def test_fetch_web_limits_link_scan():
    date = _recent_date_str()
    links = [
        (f"https://example.com/{i}", f"Claude AI news article number {i} {date}")
        for i in range(50)
    ]
    html = _html_with_links(links)
    with patch("requests.get", return_value=_mock_response(text=html)):
        result = fetch_web_articles(
            [{"name": "Src", "url": "https://example.com"}],
            ["claude"]
        )
    # 스캔 상한(40개)을 넘지 않는다
    assert len(result) <= 40
