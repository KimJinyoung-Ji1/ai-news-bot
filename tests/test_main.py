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
        # pub_date 기본값을 현재 시간으로 변경 — filter_relevant가 None을 제외하므로
        if pub_date is None:
            pub_date = datetime.datetime.now(datetime.timezone.utc)
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
        dedup.is_similar.return_value = False  # persistent fuzzy dedup 기본 통과
        return dedup

    def test_run_local_dedup_no_abort(self):
        """로컬 파일 dedup 은 외부 DB SPOF 가 없다 — 캐시가 비어도 발송을 중단하지 않는다."""
        from src.main import run
        dedup = self._setup_mocks()  # load -> (True, set()), is_sent -> False

        p_arxiv, p_hn, p_gh = self._patch_new_fetchers()
        with patch.dict("os.environ", self._env()):
            with patch("src.main.load_config", return_value=SAMPLE_CONFIG):
                with patch("src.main.LocalFileDedup", return_value=dedup):
                    with patch("src.main.fetch_rss_articles", return_value=[]) as mock_rss:
                        with patch("src.main.fetch_web_articles", return_value=[]):
                            with p_arxiv, p_hn, p_gh:
                                with patch("src.main.send_telegram") as mock_tg:
                                    with self._patch_guard():
                                        run("daily")

        # 기사 수집이 정상 수행됨 (옛 SupabaseDedup 의 abort 분기가 사라짐)
        mock_rss.assert_called_once()
        # 새 기사 없음 → daily 안내 1건 발송
        mock_tg.assert_called_once()

    def _patch_new_fetchers(self):
        """Context manager patches for the 3 new fetchers (returns empty lists)."""
        return (
            patch("src.main.fetch_arxiv_articles", return_value=[]),
            patch("src.main.fetch_hackernews_articles", return_value=[]),
            patch("src.main.fetch_github_trending_articles", return_value=[]),
        )

    def _patch_guard(self):
        """24시간 가드 비활성화 + last_sent 실파일 기록 차단 (테스트 격리).

        2026-06-12: 기존에는 _load_last_sent 만 patch 해서 테스트가 실 운영 파일
        data/last_sent.json 을 덮어쓰는 사고 경로가 있었음 → _save_last_sent 도 patch.
        """
        import contextlib
        stack = contextlib.ExitStack()
        stack.enter_context(patch("src.main._load_last_sent", return_value=None))
        stack.enter_context(patch("src.main._save_last_sent"))
        return stack

    def test_run_no_new_articles_daily(self):
        from src.main import run
        dedup = self._setup_mocks()
        dedup.is_sent.return_value = True

        p_arxiv, p_hn, p_gh = self._patch_new_fetchers()
        with patch.dict("os.environ", self._env()):
            with patch("src.main.load_config", return_value=SAMPLE_CONFIG):
                with patch("src.main.LocalFileDedup", return_value=dedup):
                    with patch("src.main.fetch_rss_articles", return_value=[]):
                        with patch("src.main.fetch_web_articles", return_value=[]):
                            with p_arxiv, p_hn, p_gh:
                                with patch("src.main.send_telegram") as mock_tg:
                                    with self._patch_guard():
                                        run("daily")

        mock_tg.assert_called_once()
        msg = mock_tg.call_args[0][0]
        assert "새로운" in msg or "업데이트" in msg

    def test_run_no_new_articles_realtime_no_telegram(self):
        from src.main import run
        dedup = self._setup_mocks()

        p_arxiv, p_hn, p_gh = self._patch_new_fetchers()
        with patch.dict("os.environ", self._env()):
            with patch("src.main.load_config", return_value=SAMPLE_CONFIG):
                with patch("src.main.LocalFileDedup", return_value=dedup):
                    with patch("src.main.fetch_rss_articles", return_value=[]):
                        with patch("src.main.fetch_web_articles", return_value=[]):
                            with p_arxiv, p_hn, p_gh:
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

        p_arxiv, p_hn, p_gh = self._patch_new_fetchers()
        with patch.dict("os.environ", self._env()):
            with patch("src.main.load_config", return_value=SAMPLE_CONFIG):
                with patch("src.main.LocalFileDedup", return_value=dedup):
                    with patch("src.main.fetch_rss_articles", return_value=articles):
                        with patch("src.main.fetch_web_articles", return_value=[]):
                            with p_arxiv, p_hn, p_gh:
                                with patch("src.main.analyze", return_value=analysis_result):
                                    with patch("src.main.send_telegram") as mock_tg:
                                        with self._patch_guard():
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

        # directive 는 로컬 JSON 파일에 저장됨 (supabase 미사용)
        p_arxiv, p_hn, p_gh = self._patch_new_fetchers()
        with patch.dict("os.environ", self._env()):
            with patch("src.main.load_config", return_value=SAMPLE_CONFIG):
                with patch("src.main.LocalFileDedup", return_value=dedup):
                    with patch("src.main.fetch_rss_articles", return_value=articles):
                        with patch("src.main.fetch_web_articles", return_value=[]):
                            with p_arxiv, p_hn, p_gh:
                                with patch("src.main.analyze", return_value=analysis_result):
                                    with patch("src.main.send_telegram"):
                                        with patch("src.main.save_directives", return_value=1) as mock_save:
                                            with self._patch_guard():
                                                run("daily")

        mock_save.assert_called_once()

    def test_run_empty_analysis_result(self):
        """분석 결과 items 빈 배열 → "인사이트 없음" 메시지 발송 (raw 제목 fallback 없음)."""
        from src.main import run
        dedup = self._setup_mocks()

        now = datetime.datetime.now(datetime.timezone.utc)
        articles = [
            {"title": "Claude update", "summary": "gpt", "link": "https://ex.com/1",
             "source": "Feed", "score": 1, "weight": 1.0, "pub_date": now}
        ]

        p_arxiv, p_hn, p_gh = self._patch_new_fetchers()
        with patch.dict("os.environ", self._env()):
            with patch("src.main.load_config", return_value=SAMPLE_CONFIG):
                with patch("src.main.LocalFileDedup", return_value=dedup):
                    with patch("src.main.fetch_rss_articles", return_value=articles):
                        with patch("src.main.fetch_web_articles", return_value=[]):
                            with p_arxiv, p_hn, p_gh:
                                with patch("src.main.analyze", return_value={"items": []}):
                                    with patch("src.main.send_telegram") as mock_tg:
                                        with self._patch_guard():
                                            run("daily")

        mock_tg.assert_called_once()
        msg = mock_tg.call_args[0][0]
        # 2026-05-28 PM 지시: raw 제목 fallback 없음 — "인사이트 없음" 안내
        assert "인사이트" in msg or "없습니" in msg

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

        p_arxiv, p_hn, p_gh = self._patch_new_fetchers()
        with patch.dict("os.environ", self._env()):
            with patch("src.main.load_config", return_value=SAMPLE_CONFIG):
                with patch("src.main.LocalFileDedup", return_value=dedup):
                    with patch("src.main.fetch_rss_articles", return_value=articles):
                        with patch("src.main.fetch_web_articles", return_value=[]):
                            with p_arxiv, p_hn, p_gh:
                                with patch("src.main.analyze", return_value=analysis_result) as mock_analyze:
                                    with patch("src.main.send_telegram"):
                                        with self._patch_guard():
                                            run("daily")

        # analyze 에 전달된 기사가 1개여야 함 (fuzzy + cluster 거침)
        if mock_analyze.called:
            passed_articles = mock_analyze.call_args[0][0]
            assert len(passed_articles) <= 1

    def test_message_builder_kr_format(self):
        """고도화 포맷 — 한국어 제목·핵심·시사점·카테고리·링크가 메시지에 포함되는지 검증.
        2026-05-28 PM 지시: 이모지 금지 포맷으로 변경. 헤더는 'AI 데일리', 핵심은 '핵심 ', 시사점은 '시사점 '."""
        from src.main import run
        dedup = self._setup_mocks()

        now = datetime.datetime.now(datetime.timezone.utc)
        articles = [
            {"title": "Claude update", "summary": "claude gpt", "link": "https://openai.com/news/1",
             "source": "Feed", "score": 2, "weight": 1.0, "pub_date": now}
        ]
        analysis_result = {
            "items": [
                {
                    "title": "OpenAI 몰타 파트너십 — 전 국민 ChatGPT Plus 무료 제공",
                    "title_kr": "OpenAI 몰타 파트너십 — 전 국민 ChatGPT Plus 무료 제공",
                    "summary": "OpenAI와 몰타 정부가 협약을 체결하여 전 국민에게 ChatGPT Plus를 무료로 배포한다. 유럽 국가 단위로는 첫 번째 사례다. 한국 정부·지자체도 유사 모델을 검토할 수 있다. 즉시 대응보다는 동향 파악 수준.",
                    "summary_kr": "몰타 전 국민 ChatGPT Plus 무료 — 유럽 첫 국가 단위 AI 복지",
                    "insight_kr": "한국 정부 RFP·B2G 진입 신호로 활용 가능",
                    "category": "정책·B2G",
                    "score": 72,
                    "apply": "[NO] 우리 스택 직접 적용 무관. 차용 가능 패턴: 정부 B2G 영업 타겟팅 인텔",
                    "link": "https://openai.com/news/1",
                    "directive": "",
                }
            ]
        }

        p_arxiv, p_hn, p_gh = self._patch_new_fetchers()
        with patch.dict("os.environ", self._env()):
            with patch("src.main.load_config", return_value=SAMPLE_CONFIG):
                with patch("src.main.LocalFileDedup", return_value=dedup):
                    with patch("src.main.fetch_rss_articles", return_value=articles):
                        with patch("src.main.fetch_web_articles", return_value=[]):
                            with p_arxiv, p_hn, p_gh:
                                with patch("src.main.analyze", return_value=analysis_result):
                                    with patch("src.main.send_telegram") as mock_tg:
                                        with self._patch_guard():
                                            run("daily")

        mock_tg.assert_called_once()
        msg = mock_tg.call_args[0][0]
        # 한국어 제목 포함
        assert "OpenAI 몰타 파트너십" in msg
        # 핵심 요약 포함 (이모지 없는 포맷: "핵심  ...")
        assert "핵심" in msg
        assert "몰타" in msg
        # 시사점 포함 (이모지 없는 포맷: "시사점  ...")
        assert "시사점" in msg
        # 카테고리 포함
        assert "정책·B2G" in msg
        # 헤더 포맷 포함 (이모지 없는 포맷: "AI 데일리 (...)")
        assert "AI 데일리" in msg
        # 링크 포함
        assert "openai.com" in msg


class TestGuard24h:
    """24시간 가드 (_load_last_sent / _save_last_sent / run skip) 단위 테스트."""

    def test_load_last_sent_missing_file(self, tmp_path):
        """파일 없으면 None 반환."""
        from src.main import _load_last_sent
        result = _load_last_sent(str(tmp_path / "last_sent.json"))
        assert result is None

    def test_load_last_sent_valid(self, tmp_path):
        """유효한 ISO 타임스탬프 로드."""
        import json as _json
        from src.main import _load_last_sent
        path = str(tmp_path / "last_sent.json")
        now = datetime.datetime.now(datetime.timezone.utc)
        with open(path, "w", encoding="utf-8") as f:
            _json.dump({"last_sent": now.isoformat()}, f)
        result = _load_last_sent(path)
        assert result is not None
        assert abs((result - now).total_seconds()) < 1

    def test_load_last_sent_corrupt(self, tmp_path):
        """손상된 파일 → None 반환 (abort 없음)."""
        from src.main import _load_last_sent
        path = tmp_path / "last_sent.json"
        path.write_text("not valid json", encoding="utf-8")
        result = _load_last_sent(str(path))
        assert result is None

    def test_save_and_reload_last_sent(self, tmp_path):
        """저장 후 재로드 시 동일 시각 (1초 이내)."""
        from src.main import _save_last_sent, _load_last_sent
        path = str(tmp_path / "last_sent.json")
        before = datetime.datetime.now(datetime.timezone.utc)
        _save_last_sent(path)
        loaded = _load_last_sent(path)
        assert loaded is not None
        assert (loaded - before).total_seconds() < 2

    def test_run_daily_skip_within_guard_window(self):
        """last_sent 가 1시간 전이면 run() 이 skip 하고 send_telegram 미호출."""
        from src.main import run
        recent = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)

        with patch("src.main._load_last_sent", return_value=recent):
            with patch("src.main.load_config", return_value={
                "dedup": {}, "sources": {"rss": [], "web": []},
                "keywords": ["claude"], "analysis": {"max_articles": 5, "max_items": 3,
                "model": "m", "max_age_days": 14}, "telegram": {}, "directive": {}
            }):
                with patch("src.main.send_telegram") as mock_tg:
                    run("daily", dry_run=False)
        mock_tg.assert_not_called()

    def test_run_daily_proceeds_after_guard_window(self):
        """last_sent 가 25시간 전이면 가드 통과 → 정상 진행."""
        from src.main import run
        old = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=25)

        with patch("src.main._load_last_sent", return_value=old):
            with patch("src.main._save_last_sent"):
                with patch("src.main.load_config", return_value={
                    "dedup": {}, "sources": {"rss": [], "web": []},
                    "keywords": ["claude"], "analysis": {"max_articles": 5, "max_items": 3,
                    "model": "m", "max_age_days": 14}, "telegram": {}, "directive": {}
                }):
                    with patch("src.main.LocalFileDedup") as mock_dedup_cls:
                        mock_dedup = MagicMock()
                        mock_dedup.load.return_value = (True, set())
                        mock_dedup.is_sent.return_value = False
                        mock_dedup.is_similar.return_value = False
                        mock_dedup_cls.return_value = mock_dedup
                        with patch("src.main.fetch_rss_articles", return_value=[]):
                            with patch("src.main.fetch_web_articles", return_value=[]):
                                with patch("src.main.fetch_arxiv_articles", return_value=[]):
                                    with patch("src.main.fetch_hackernews_articles", return_value=[]):
                                        with patch("src.main.fetch_github_trending_articles", return_value=[]):
                                            with patch("src.main.send_telegram") as mock_tg:
                                                with patch.dict("os.environ", {
                                                    "GEMINI_API_KEY": "k", "TELEGRAM_BOT_TOKEN": "t",
                                                    "TELEGRAM_CHAT_ID": "c",
                                                }):
                                                    run("daily", dry_run=False)
        # 기사 없어서 "새 업데이트 없음" 메시지 발송됨
        mock_tg.assert_called_once()

    def test_run_dry_run_skips_guard(self):
        """dry_run=True 이면 24시간 가드 체크 안 함 (last_sent 호출 없음)."""
        from src.main import run
        with patch("src.main._load_last_sent") as mock_load:
            with patch("src.main.load_config", return_value={
                "dedup": {}, "sources": {"rss": [], "web": []},
                "keywords": ["claude"], "analysis": {"max_articles": 5, "max_items": 3,
                "model": "m", "max_age_days": 14}, "telegram": {}, "directive": {}
            }):
                with patch("src.main.LocalFileDedup") as mock_dedup_cls:
                    mock_dedup = MagicMock()
                    mock_dedup.load.return_value = (True, set())
                    mock_dedup.is_sent.return_value = False
                    mock_dedup.is_similar.return_value = False
                    mock_dedup_cls.return_value = mock_dedup
                    with patch("src.main.fetch_rss_articles", return_value=[]):
                        with patch("src.main.fetch_web_articles", return_value=[]):
                            with patch("src.main.fetch_arxiv_articles", return_value=[]):
                                with patch("src.main.fetch_hackernews_articles", return_value=[]):
                                    with patch("src.main.fetch_github_trending_articles", return_value=[]):
                                        with patch("src.main.send_telegram"):
                                            with patch.dict("os.environ", {
                                                "GEMINI_API_KEY": "k", "TELEGRAM_BOT_TOKEN": "t",
                                                "TELEGRAM_CHAT_ID": "c",
                                            }):
                                                run("daily", dry_run=True)
        # dry_run=True 이면 가드 체크(_load_last_sent) 호출 안 됨
        mock_load.assert_not_called()
