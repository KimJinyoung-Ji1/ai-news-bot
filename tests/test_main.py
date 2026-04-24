import datetime
import pytest
from unittest.mock import patch, MagicMock, call
from src.main import filter_relevant, _fuzzy_deduplicate


SAMPLE_CONFIG = {
    "supabase": {"url": "https://sb.co", "ji1_url": "https://ji1.sb.co"},
    "dedup": {"max_cache_size": 100, "window_days": 30},
    "sources": {"rss": [], "web": []},
    "keywords": ["claude", "gpt"],
    "analysis": {"max_articles": 10, "max_items": 6, "model": "gemini-2.5-flash", "max_age_days": 14},
    "telegram": {"message_thread_id": None},
}


class TestFilterRelevant:
    def _make_articles(self, titles_summaries, weight=1.0, pub_date=None):
        return [
            {
                "title": t, "summary": s,
                "link": f"https://example.com/{i}",
                "source": "Test",
                "weight": weight,
                "pub_date": pub_date,
            }
            for i, (t, s) in enumerate(titles_summaries)
        ]

    def test_empty_returns_empty(self):
        result = filter_relevant([], ["claude"])
        assert result == []

    def test_filters_non_matching(self):
        articles = self._make_articles([("Football match results today full recap", "")])
        result = filter_relevant(articles, ["claude", "gpt"])
        assert result == []

    def test_keeps_matching_in_title(self):
        articles = self._make_articles([("New Claude model released with improvements", "")])
        result = filter_relevant(articles, ["claude"])
        assert len(result) == 1

    def test_keeps_matching_in_summary(self):
        articles = self._make_articles([("Tech update", "gpt integration with new features")])
        result = filter_relevant(articles, ["gpt"])
        assert len(result) == 1

    def test_adds_score_field(self):
        articles = self._make_articles([("Claude claude api update", "")])
        result = filter_relevant(articles, ["claude", "api"])
        assert "score" in result[0]

    def test_sorts_by_score_descending(self):
        articles = self._make_articles([
            ("Claude api update", ""),
            ("Claude claude claude gpt api release", ""),
        ])
        result = filter_relevant(articles, ["claude", "gpt", "api"])
        assert result[0]["score"] >= result[1]["score"]

    def test_case_insensitive_matching(self):
        articles = self._make_articles([("New CLAUDE release", "")])
        result = filter_relevant(articles, ["claude"])
        assert len(result) == 1

    def test_drops_articles_older_than_max_age(self):
        """14일 초과 기사 drop."""
        old = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=20)
        articles = self._make_articles([("Claude update", "")], pub_date=old)
        result = filter_relevant(articles, ["claude"], max_age_days=14)
        assert result == []

    def test_keeps_articles_within_max_age(self):
        recent = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=3)
        articles = self._make_articles([("Claude update", "")], pub_date=recent)
        result = filter_relevant(articles, ["claude"], max_age_days=14)
        assert len(result) == 1

    def test_higher_weight_gives_higher_score(self):
        """weight 높은 소스가 score 높음 (keyword hits 동일 시)."""
        now = datetime.datetime.now(datetime.timezone.utc)
        low = [{"title": "Claude new model", "summary": "", "link": "https://a.com/1",
                "source": "Low", "weight": 1.0, "pub_date": now}]
        high = [{"title": "Claude new model", "summary": "", "link": "https://a.com/2",
                 "source": "High", "weight": 3.0, "pub_date": now}]
        res_low = filter_relevant(low, ["claude"])
        res_high = filter_relevant(high, ["claude"])
        assert res_high[0]["score"] > res_low[0]["score"]


class TestFuzzyDeduplicate:
    def _art(self, title: str) -> dict:
        return {"title": title, "link": "https://example.com", "summary": "", "source": "T",
                "weight": 1.0, "pub_date": None}

    def test_removes_near_duplicate(self):
        arts = [
            self._art("Claude 3.5 Sonnet released by Anthropic today"),
            self._art("Claude 3.5 Sonnet released by Anthropic now"),
        ]
        result = _fuzzy_deduplicate(arts)
        assert len(result) == 1

    def test_keeps_different_articles(self):
        arts = [
            self._art("Claude 3.5 released"),
            self._art("Supabase launches vector database"),
        ]
        result = _fuzzy_deduplicate(arts)
        assert len(result) == 2

    def test_first_article_is_representative(self):
        """첫 번째 기사가 대표로 선택됨."""
        arts = [
            self._art("Claude update released today by Anthropic team"),
            self._art("Claude update released today by Anthropic now"),
        ]
        result = _fuzzy_deduplicate(arts)
        assert result[0]["title"] == arts[0]["title"]

    def test_empty_returns_empty(self):
        assert _fuzzy_deduplicate([]) == []

    def test_single_returns_single(self):
        arts = [self._art("Claude release")]
        assert _fuzzy_deduplicate(arts) == arts


class TestRunFunction:
    def _env(self):
        return {
            "GEMINI_API_KEY": "gemini-key",
            "TELEGRAM_BOT_TOKEN": "tg-token",
            "TELEGRAM_CHAT_ID": "chat-id",
            "SUPABASE_ANON_KEY": "sb-anon-key",
        }

    def _setup_mocks(self, load_ok=True):
        dedup = MagicMock()
        dedup.load.return_value = (load_ok, set())
        dedup.is_sent.return_value = False
        return dedup

    def test_run_dedup_load_failure_aborts_without_sending(self):
        """AC-1: dedup.load 실패 시 발송 없이 종료 + skip 알림 1건."""
        from src.main import run
        dedup = self._setup_mocks(load_ok=False)

        with patch.dict("os.environ", self._env()):
            with patch("src.main.load_config", return_value=SAMPLE_CONFIG):
                with patch("src.main.SupabaseDedup", return_value=dedup):
                    with patch("src.main.fetch_rss_articles", return_value=[]) as mock_rss:
                        with patch("src.main.send_telegram") as mock_tg:
                            run("daily")

        # 기사 수집 자체가 일어나지 않아야 함 (abort)
        mock_rss.assert_not_called()
        # skip 알림 1건만 발송
        mock_tg.assert_called_once()
        msg = mock_tg.call_args[0][0]
        assert "dedup" in msg.lower() or "스킵" in msg or "skip" in msg.lower()

    def test_run_no_new_articles_daily(self):
        from src.main import run
        dedup = self._setup_mocks()
        dedup.is_sent.return_value = True

        with patch.dict("os.environ", self._env()):
            with patch("src.main.load_config", return_value=SAMPLE_CONFIG):
                with patch("src.main.SupabaseDedup", return_value=dedup):
                    with patch("src.main.fetch_rss_articles", return_value=[]):
                        with patch("src.main.fetch_web_articles", return_value=[]):
                            with patch("src.main.send_telegram") as mock_tg:
                                run("daily")

        mock_tg.assert_called_once()
        msg = mock_tg.call_args[0][0]
        assert "새로운" in msg or "업데이트" in msg

    def test_run_no_new_articles_realtime_no_telegram(self):
        from src.main import run
        dedup = self._setup_mocks()

        with patch.dict("os.environ", self._env()):
            with patch("src.main.load_config", return_value=SAMPLE_CONFIG):
                with patch("src.main.SupabaseDedup", return_value=dedup):
                    with patch("src.main.fetch_rss_articles", return_value=[]):
                        with patch("src.main.fetch_web_articles", return_value=[]):
                            with patch("src.main.send_telegram") as mock_tg:
                                run("realtime")

        mock_tg.assert_not_called()

    def test_run_with_new_articles_and_analysis(self):
        from src.main import run
        dedup = self._setup_mocks()

        now = datetime.datetime.now(datetime.timezone.utc)
        articles = [
            {"title": "Claude update", "summary": "great news", "link": "https://ex.com/1",
             "source": "Feed", "score": 2, "weight": 1.0, "pub_date": now}
        ]
        analysis_result = {
            "items": [
                {"title": "Claude 업데이트", "summary": "요약", "apply": "적용",
                 "link": "https://ex.com/1", "directive": ""}
            ]
        }

        with patch.dict("os.environ", self._env()):
            with patch("src.main.load_config", return_value=SAMPLE_CONFIG):
                with patch("src.main.SupabaseDedup", return_value=dedup):
                    with patch("src.main.fetch_rss_articles", return_value=articles):
                        with patch("src.main.fetch_web_articles", return_value=[]):
                            with patch("src.main.analyze", return_value=analysis_result):
                                with patch("src.main.send_telegram") as mock_tg:
                                    run("daily")

        mock_tg.assert_called_once()

    def test_run_with_directive_inserts(self):
        from src.main import run
        dedup = self._setup_mocks()

        now = datetime.datetime.now(datetime.timezone.utc)
        articles = [
            {"title": "Claude update", "summary": "gpt test", "link": "https://ex.com/1",
             "source": "Feed", "score": 2, "weight": 1.0, "pub_date": now}
        ]
        analysis_result = {
            "items": [
                {"title": "Claude 업데이트", "summary": "요약", "apply": "적용",
                 "link": "https://ex.com/1", "directive": "Run some command here now"}
            ]
        }

        with patch.dict("os.environ", self._env()):
            with patch("src.main.load_config", return_value=SAMPLE_CONFIG):
                with patch("src.main.SupabaseDedup", return_value=dedup):
                    with patch("src.main.fetch_rss_articles", return_value=articles):
                        with patch("src.main.fetch_web_articles", return_value=[]):
                            with patch("src.main.analyze", return_value=analysis_result):
                                with patch("src.main.send_telegram"):
                                    with patch("src.main.insert_directive", return_value=True) as mock_insert:
                                        run("daily")

        mock_insert.assert_called_once()

    def test_run_empty_analysis_result(self):
        from src.main import run
        dedup = self._setup_mocks()

        now = datetime.datetime.now(datetime.timezone.utc)
        articles = [
            {"title": "Claude update", "summary": "gpt", "link": "https://ex.com/1",
             "source": "Feed", "score": 1, "weight": 1.0, "pub_date": now}
        ]

        with patch.dict("os.environ", self._env()):
            with patch("src.main.load_config", return_value=SAMPLE_CONFIG):
                with patch("src.main.SupabaseDedup", return_value=dedup):
                    with patch("src.main.fetch_rss_articles", return_value=articles):
                        with patch("src.main.fetch_web_articles", return_value=[]):
                            with patch("src.main.analyze", return_value={"items": []}):
                                with patch("src.main.send_telegram") as mock_tg:
                                    run("daily")

        mock_tg.assert_called_once()
        msg = mock_tg.call_args[0][0]
        assert "Claude update" in msg

    def test_run_fuzzy_dedup_removes_similar_articles(self):
        """세션 내 fuzzy 중복 제거 — 거의 동일한 제목 2개 중 1개만 남음."""
        from src.main import run
        dedup = self._setup_mocks()

        now = datetime.datetime.now(datetime.timezone.utc)
        articles = [
            {"title": "Claude 3.5 Sonnet released by Anthropic today",
             "summary": "claude gpt", "link": "https://ex.com/1",
             "source": "Feed", "weight": 1.0, "pub_date": now},
            {"title": "Claude 3.5 Sonnet released by Anthropic now",
             "summary": "claude gpt", "link": "https://ex.com/2",
             "source": "Feed", "weight": 1.0, "pub_date": now},
        ]
        analysis_result = {"items": []}

        with patch.dict("os.environ", self._env()):
            with patch("src.main.load_config", return_value=SAMPLE_CONFIG):
                with patch("src.main.SupabaseDedup", return_value=dedup):
                    with patch("src.main.fetch_rss_articles", return_value=articles):
                        with patch("src.main.fetch_web_articles", return_value=[]):
                            with patch("src.main.analyze", return_value=analysis_result) as mock_analyze:
                                with patch("src.main.send_telegram"):
                                    run("daily")

        # analyze 에 전달된 기사가 1개여야 함 (fuzzy + cluster 거침)
        if mock_analyze.called:
            passed_articles = mock_analyze.call_args[0][0]
            assert len(passed_articles) <= 1
