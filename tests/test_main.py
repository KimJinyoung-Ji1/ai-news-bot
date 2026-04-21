import pytest
from unittest.mock import patch, MagicMock, call
from src.main import filter_relevant


SAMPLE_CONFIG = {
    "supabase": {"url": "https://sb.co", "ji1_url": "https://ji1.sb.co"},
    "dedup": {"max_cache_size": 100},
    "sources": {"rss": [], "web": []},
    "keywords": ["claude", "gpt"],
    "analysis": {"max_articles": 10, "max_items": 6, "model": "gemini-2.5-flash"},
    "telegram": {"message_thread_id": None},
}


class TestFilterRelevant:
    def _make_articles(self, titles_summaries):
        return [
            {"title": t, "summary": s, "link": f"https://example.com/{i}", "source": "Test"}
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


class TestRunFunction:
    def _env(self):
        return {
            "GEMINI_API_KEY": "gemini-key",
            "TELEGRAM_BOT_TOKEN": "tg-token",
            "TELEGRAM_CHAT_ID": "chat-id",
            "SUPABASE_ANON_KEY": "sb-anon-key",
        }

    def _setup_mocks(self):
        dedup = MagicMock()
        dedup.load.return_value = set()
        dedup.is_sent.return_value = False
        return dedup

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

        articles = [
            {"title": "Claude update", "summary": "great news", "link": "https://ex.com/1",
             "source": "Feed", "score": 2}
        ]
        analysis_result = {
            "items": [
                {"title": "Claude 업데이트", "summary": "요약", "apply": "적용", "link": "https://ex.com/1", "directive": ""}
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

        articles = [
            {"title": "Claude update", "summary": "gpt test", "link": "https://ex.com/1",
             "source": "Feed", "score": 2}
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

        articles = [
            {"title": "Claude update", "summary": "gpt", "link": "https://ex.com/1",
             "source": "Feed", "score": 1}
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
