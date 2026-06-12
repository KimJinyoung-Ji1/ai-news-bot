"""spec ai-news-bot-fix-20260612 회귀 테스트.

감사 항목별 수정 전 FAIL 재현 → 수정 후 PASS 검증.
텔레그램 실 발송 없음 (전부 mock), 실 데이터 파일 기록 없음 (_save_last_sent patch).
"""
import contextlib
import copy
import datetime
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.main import filter_relevant, _strip_emoji
from src.outputs.telegram import send_telegram


BASE_CONFIG = {
    "dedup": {"max_cache_size": 100, "window_days": 30},
    "sources": {"rss": [], "web": []},
    "keywords": ["claude", "gpt"],
    "analysis": {"max_articles": 10, "max_items": 6, "model": "gemini-2.5-flash",
                 "max_age_days": 14, "freshness_days": 3, "max_per_source": 2},
    "telegram": {"message_thread_id": None},
    "directive": {"file": "data/directives.json"},
}

ENV = {"GEMINI_API_KEY": "g", "TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"}

VALID_ITEM = {
    "title": "테스트 뉴스", "title_kr": "테스트 뉴스",
    "summary": "요약", "summary_kr": "핵심 한 줄", "insight_kr": "시사점 한 줄",
    "category": "신도구·MCP", "score": 80,
    "apply": "[YES] 적용", "link": "https://ex.com/1", "directive": "",
}


def _art(title: str, link: str, source: str = "Feed",
         pub_date: datetime.datetime | None = "now") -> dict:
    if pub_date == "now":
        pub_date = datetime.datetime.now(datetime.timezone.utc)
    return {"title": title, "summary": "claude gpt", "link": link,
            "source": source, "weight": 1.0, "pub_date": pub_date}


@contextlib.contextmanager
def _run_harness(cfg, articles, analysis_result, send_ok=True):
    """run() 전체 흐름을 mock 격리 — 텔레그램·실파일 기록 일절 없음."""
    dedup = MagicMock()
    dedup.load.return_value = (True, set())
    dedup.is_sent.return_value = False
    dedup.is_similar.return_value = False
    tg = MagicMock(return_value=send_ok)
    with patch.dict("os.environ", ENV), \
         patch("src.main.load_config", return_value=cfg), \
         patch("src.main.LocalFileDedup", return_value=dedup), \
         patch("src.main.fetch_rss_articles", return_value=articles), \
         patch("src.main.fetch_web_articles", return_value=[]), \
         patch("src.main.fetch_arxiv_articles", return_value=[]), \
         patch("src.main.fetch_hackernews_articles", return_value=[]), \
         patch("src.main.fetch_github_trending_articles", return_value=[]), \
         patch("src.main.analyze", return_value=analysis_result) as mock_analyze, \
         patch("src.main.send_telegram", tg), \
         patch("src.main.save_directives", return_value=0), \
         patch("src.main._load_last_sent", return_value=None), \
         patch("src.main._save_last_sent") as mock_save_last:
        yield {"dedup": dedup, "tg": tg, "analyze": mock_analyze,
               "save_last": mock_save_last}


# ── AUD-05: mark_sent 는 LLM이 실제로 본 항목(to_analyze)만 ─────────────────

class TestAud05MarkSentOnlyAnalyzed:
    def test_overflow_articles_not_marked_sent(self):
        """max_articles=1 인데 신규 3건 → LLM이 본 1건만 sent 처리, 2건은 재경쟁."""
        from src.main import run
        cfg = copy.deepcopy(BASE_CONFIG)
        cfg["analysis"]["max_articles"] = 1
        articles = [
            _art("Claude memory tool deep dive guide", "https://a.com/1", "A"),
            _art("GPT realtime voice api pricing drop", "https://b.com/2", "B"),
            _art("Claude code hooks automation pattern", "https://c.com/3", "C"),
        ]
        with _run_harness(cfg, articles, {"items": [dict(VALID_ITEM)]}) as m:
            run("daily")
        m["dedup"].mark_sent.assert_called_once()
        hashes = m["dedup"].mark_sent.call_args[0][0]
        titles = m["dedup"].mark_sent.call_args[1]["titles"]
        assert len(hashes) == 1, f"LLM이 본 1건만 sent 처리해야 함, got {len(hashes)}"
        assert len(titles) == 1


# ── AUD-02: send_telegram 성공 시에만 mark_sent + _save_last_sent ───────────

class TestAud02SendResultGate:
    def test_send_failure_skips_mark_sent_and_last_sent(self):
        from src.main import run
        articles = [_art("Claude update news today", "https://a.com/1")]
        with _run_harness(copy.deepcopy(BASE_CONFIG), articles,
                          {"items": [dict(VALID_ITEM)]}, send_ok=False) as m:
            run("daily")
        m["dedup"].mark_sent.assert_not_called()
        m["save_last"].assert_not_called()

    def test_send_success_marks_sent_and_saves_last_sent(self):
        from src.main import run
        articles = [_art("Claude update news today", "https://a.com/1")]
        with _run_harness(copy.deepcopy(BASE_CONFIG), articles,
                          {"items": [dict(VALID_ITEM)]}, send_ok=True) as m:
            run("daily")
        m["dedup"].mark_sent.assert_called_once()
        m["save_last"].assert_called_once()


# ── AUD-03: API 실패(None) vs 품질 미달({"items": []}) 구분 ─────────────────

class TestAud03FailureVsQualityMiss:
    def test_analyze_returns_none_when_all_engines_api_fail(self):
        from src.analyzer import analyze
        fail = MagicMock()
        fail.status_code = 500
        fail.text = "server error"
        arts = [{"source": "s", "title": "t", "link": "https://x.com", "summary": "y"}]
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "k"}):
            with patch("requests.post", return_value=fail), patch("time.sleep"):
                result = analyze(arts, "gemini-key")
        assert result is None, "API 전면 실패는 None 이어야 함 (품질 미달 {'items': []} 과 구분)"

    def test_analyze_returns_empty_items_on_quality_miss(self):
        """엔진이 정상 응답(JSON OK)했지만 items 비면 {"items": []} (None 아님)."""
        from src.analyzer import analyze
        gemini_resp = MagicMock()
        gemini_resp.status_code = 200
        gemini_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": json.dumps({"items": []})}]}}]
        }
        arts = [{"source": "s", "title": "t", "link": "https://x.com", "summary": "y"}]
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}):
            with patch("requests.post", return_value=gemini_resp):
                result = analyze(arts, "gemini-key")
        assert result == {"items": []}

    def test_run_analysis_failure_sends_honest_message_no_burn(self):
        """analyze=None → '분석 실패' 정직 메시지 + mark_sent 생략 (허위 '기준 미달' 금지)."""
        from src.main import run
        articles = [_art("Claude update news today", "https://a.com/1")]
        with _run_harness(copy.deepcopy(BASE_CONFIG), articles, None) as m:
            run("daily")
        m["tg"].assert_called_once()
        msg = m["tg"].call_args[0][0]
        assert "분석 실패" in msg
        assert "기준 미달" not in msg
        m["dedup"].mark_sent.assert_not_called()


# ── AUD-14: max_items 6 통일 ────────────────────────────────────────────────

class TestAud14MaxItemsUnified:
    def test_config_max_items_is_6(self):
        from src.config import load_config
        cfg = load_config()
        assert cfg["analysis"]["max_items"] == 6

    def test_config_freshness_days_is_3(self):
        from src.config import load_config
        cfg = load_config()
        assert cfg["analysis"].get("freshness_days") == 3

    def test_prompt_says_max_6(self):
        from src.analyzer import PROMPT_TEMPLATE
        assert "최대 6개" in PROMPT_TEMPLATE


# ── B: 신선도 하드 컷 + pub_date None recency 페널티 ────────────────────────

class TestFreshnessHardCut:
    def test_article_older_than_freshness_days_dropped(self):
        old = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=5)
        arts = [_art("Claude old news from last week", "https://a.com/1", pub_date=old)]
        result = filter_relevant(arts, ["claude"], max_age_days=14, freshness_days=3)
        assert result == [], "freshness_days=3 초과 과거 기사는 스코어링 전 drop"

    def test_article_within_freshness_days_kept(self):
        recent = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
        arts = [_art("Claude fresh news today", "https://a.com/1", pub_date=recent)]
        result = filter_relevant(arts, ["claude"], max_age_days=14, freshness_days=3)
        assert len(result) == 1

    def test_no_pub_date_kept_with_recency_penalty(self):
        """pub_date 없는 기사는 drop 하지 않고 recency 페널티만 적용."""
        no_date = [_art("Claude dateless news item", "https://a.com/1", pub_date=None)]
        fresh = [_art("Claude dateless news item", "https://a.com/2",
                      pub_date=datetime.datetime.now(datetime.timezone.utc))]
        res_none = filter_relevant(no_date, ["claude"], freshness_days=3)
        res_fresh = filter_relevant(fresh, ["claude"], freshness_days=3)
        assert len(res_none) == 1, "pub_date None 은 drop 금지"
        assert res_none[0]["score"] < res_fresh[0]["score"], "None 은 페널티 점수"


# ── AUD-09: github_trending pub_date 수집시각 박제 금지 ─────────────────────

class TestAud09GithubTrendingPubDate:
    _HTML = """
    <html><body>
    <article class="Box-row">
      <h2><a href="/openai/gpt-5-tools">openai / gpt-5-tools</a></h2>
      <p>An open-source LLM agent framework with MCP support</p>
      <a href="/openai/gpt-5-tools/stargazers">1,234</a>
    </article>
    </body></html>
    """

    def test_pub_date_is_none_not_fetch_time(self):
        from src.fetchers.github_trending import fetch_github_trending_articles
        cfg = {"enabled": True, "languages": ["Python"],
               "keywords": ["ai", "llm", "mcp", "agent"], "max_per_fetch": 20}
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.status_code = 200
        resp.text = self._HTML
        with patch("src.fetchers.github_trending.requests.get", return_value=resp):
            with patch("src.fetchers.github_trending.time.sleep"):
                articles = fetch_github_trending_articles(cfg)
        assert len(articles) >= 1
        assert all(a["pub_date"] is None for a in articles), \
            "pub_date 에 수집시각 박제 금지 — None + recency 페널티 방식"


# ── AUD-04: 하드코딩 이모지 삭제 ────────────────────────────────────────────

class TestAud04NoHardcodedEmoji:
    def test_no_news_message_has_no_robot_emoji(self):
        from src.main import run
        with _run_harness(copy.deepcopy(BASE_CONFIG), [], {"items": []}) as m:
            run("daily")
        m["tg"].assert_called_once()
        msg = m["tg"].call_args[0][0]
        assert "\U0001F916" not in msg, "하드코딩 이모지(robot) 금지"
        assert "AI 데일리" in msg


# ── AUD-11: no-news 경로에서도 _save_last_sent (같은 날 중복 '없음' 차단) ───

class TestAud11NoNewsSavesLastSent:
    def test_no_news_daily_saves_last_sent(self):
        from src.main import run
        with _run_harness(copy.deepcopy(BASE_CONFIG), [], {"items": []}) as m:
            run("daily")
        m["save_last"].assert_called_once()

    def test_no_news_dry_run_does_not_send(self):
        from src.main import run
        with _run_harness(copy.deepcopy(BASE_CONFIG), [], {"items": []}) as m:
            run("daily", dry_run=True)
        m["tg"].assert_not_called()
        m["save_last"].assert_not_called()


# ── AUD-06: _strip_emoji 정규식 범위 보강 ───────────────────────────────────

class TestAud06EmojiRanges:
    @pytest.mark.parametrize("ch", [
        "⭐",        # ⭐ U+2B00-2BFF
        "⏰",        # ⏰ U+2300-23FF
        "‼",        # ‼
        "⁉",        # ⁉
        "\U0001F1F0\U0001F1F7",  # 🇰🇷 국기 (U+1F1E6-1F1FF)
        "\U0001F22F",    # 🈯 U+1F100-1F2FF
        "\U0001F65B",    # U+1F650-1F67F
    ])
    def test_extended_ranges_stripped(self, ch):
        assert ch not in _strip_emoji(f"머리{ch}꼬리")

    def test_keycap_sequence_stripped(self):
        # "1️⃣" = "1" + U+FE0F + U+20E3 → 숫자만 남음
        assert _strip_emoji("1️⃣ 순위") == "1 순위"

    def test_zwj_family_sequence_stripped(self):
        assert _strip_emoji("\U0001F468‍\U0001F469‍\U0001F467") == ""

    def test_dividers_and_middot_preserved(self):
        s = "AI 데일리\n" + "━" * 17 + "\n" + "─" * 12 + "\nopenai.com · 80pt"
        assert _strip_emoji(s) == s


# ── AUD-07 / AUD-08: 텔레그램 분할 발송 + parse_mode 제거 ───────────────────

class TestAud07Aud08Telegram:
    def _ok(self):
        resp = MagicMock()
        resp.status_code = 200
        return resp

    def test_long_message_split_on_item_separator(self):
        sep = "\n" + "─" * 12 + "\n"
        header = "AI 데일리 (2026-06-12)\n" + "━" * 17 + "\n"
        items = [f"[{i}] " + "가" * 800 + "\nhttps://ex.com/" + str(i) for i in range(1, 8)]
        text = header + sep.join(items)
        assert len(text) > 4000

        payloads = []

        def mock_post(url, json=None, timeout=None):
            payloads.append(json)
            return self._ok()

        with patch("requests.post", side_effect=mock_post):
            ok = send_telegram(text, "tok", "chat", message_thread_id=2)

        assert ok is True
        assert len(payloads) >= 2, "4000자 초과는 구분선 경계 분할 발송"
        assert all(len(p["text"]) <= 4000 for p in payloads)
        assert all(p["message_thread_id"] == 2 for p in payloads), "모든 파트 동일 thread"
        assert "AI 데일리" in payloads[0]["text"]
        assert "AI 데일리" not in payloads[1]["text"], "파트 2+ 는 헤더 없이"
        merged = "".join(p["text"] for p in payloads)
        assert "잘림" not in merged, "구분선 분할 시 내용 절단 금지"
        for i in range(1, 8):
            assert f"[{i}]" in merged, f"항목 {i} 유실"

    def test_payload_has_no_parse_mode(self):
        payloads = []

        def mock_post(url, json=None, timeout=None):
            payloads.append(json)
            return self._ok()

        with patch("requests.post", side_effect=mock_post):
            send_telegram("plain text", "tok", "chat")
        assert "parse_mode" not in payloads[0], "HTML parse_mode 제거 — plain text 1회 발송"

    def test_part_failure_returns_false(self):
        fail = MagicMock()
        fail.status_code = 400
        fail.text = "Bad Request"
        with patch("requests.post", return_value=fail) as mock_post:
            ok = send_telegram("hello", "tok", "chat")
        assert ok is False
        assert mock_post.call_count == 1, "HTML→plaintext 이중 발송 폴백 제거"


# ── AUD-15: Claude JSON parse error 1회 재시도 ──────────────────────────────

class TestAud15ClaudeParseRetry:
    def test_parse_error_retried_once_then_succeeds(self):
        from src.analyzer import _analyze_claude
        bad = MagicMock()
        bad.status_code = 200
        bad.json.return_value = {"content": [{"text": "not json at all"}]}
        good = MagicMock()
        good.status_code = 200
        good.json.return_value = {"content": [{"text": json.dumps({"items": []})}]}
        with patch("requests.post", side_effect=[bad, good]):
            result = _analyze_claude("articles", "prompt", "key")
        assert result is not None, "parse error 1회 재시도 후 성공해야 함"

    def test_parse_error_twice_returns_none_for_gemini_fallback(self):
        from src.analyzer import _analyze_claude
        bad = MagicMock()
        bad.status_code = 200
        bad.json.return_value = {"content": [{"text": "not json at all"}]}
        with patch("requests.post", return_value=bad):
            result = _analyze_claude("articles", "prompt", "key")
        assert result is None


# ── AUD-17: dead code SupabaseDedup 삭제 ────────────────────────────────────

class TestAud17DeadCodeRemoved:
    def test_supabase_dedup_class_removed(self):
        import src.dedup as dedup_mod
        assert not hasattr(dedup_mod, "SupabaseDedup")

    def test_requests_import_removed(self):
        import src.dedup as dedup_mod
        source = Path(dedup_mod.__file__).read_text(encoding="utf-8")
        assert "import requests" not in source
