import pytest
from unittest.mock import patch, MagicMock, call
from src.dedup import article_hash, SupabaseDedup


# ── article_hash 기본 테스트 ──────────────────────────────────────────────────

def test_article_hash_deterministic():
    h1 = article_hash("Title A", "https://example.com/a")
    h2 = article_hash("Title A", "https://example.com/a")
    assert h1 == h2


def test_article_hash_different_for_different_inputs():
    h1 = article_hash("Title A", "https://example.com/a")
    h2 = article_hash("Title B", "https://example.com/b")
    assert h1 != h2


def test_article_hash_returns_md5_hex():
    h = article_hash("x", "y")
    assert len(h) == 32
    assert all(c in "0123456789abcdef" for c in h)


# ── AC-2: 정규화 해시 동일성 (10 케이스) ────────────────────────────────────

def test_hash_utm_stripped():
    """UTM 파라미터 있는 URL 과 없는 URL 이 같은 해시."""
    h1 = article_hash("Claude 3.5", "https://a.com/x?utm_source=rss")
    h2 = article_hash("Claude 3.5", "https://a.com/x")
    assert h1 == h2


def test_hash_trailing_slash():
    """trailing slash 유무 무관."""
    h1 = article_hash("Claude 3.5", "https://a.com/x/")
    h2 = article_hash("Claude 3.5", "https://a.com/x")
    assert h1 == h2


def test_hash_title_trailing_colon():
    """AC-2 명시 케이스: 'Claude 3.5' vs 'Claude 3.5:'."""
    h1 = article_hash("Claude 3.5", "https://a.com/x?utm_source=rss")
    h2 = article_hash("Claude 3.5:", "https://a.com/x/")
    assert h1 == h2


def test_hash_title_case_insensitive():
    h1 = article_hash("CLAUDE Update", "https://a.com/p")
    h2 = article_hash("claude update", "https://a.com/p")
    assert h1 == h2


def test_hash_url_scheme_case():
    h1 = article_hash("Title", "HTTPS://Example.COM/path")
    h2 = article_hash("Title", "https://example.com/path")
    assert h1 == h2


def test_hash_multiple_utm_params():
    h1 = article_hash("News", "https://blog.com/post?utm_source=x&utm_medium=y&utm_campaign=z")
    h2 = article_hash("News", "https://blog.com/post")
    assert h1 == h2


def test_hash_gclid_stripped():
    h1 = article_hash("AI update", "https://example.com/news?gclid=abc123")
    h2 = article_hash("AI update", "https://example.com/news")
    assert h1 == h2


def test_hash_title_unicode_nfkc():
    """전각 문자 포함 제목이 ASCII 와 동일 해시."""
    h1 = article_hash("\uff43\uff4c\uff41\uff55\uff44\uff45", "https://a.com/p")  # ｃｌａｕｄｅ
    h2 = article_hash("claude", "https://a.com/p")
    assert h1 == h2


def test_hash_title_punctuation_stripped():
    h1 = article_hash("Claude: New Model", "https://a.com/p")
    h2 = article_hash("Claude New Model", "https://a.com/p")
    assert h1 == h2


def test_hash_fbclid_stripped():
    h1 = article_hash("OpenAI news", "https://example.com/a?fbclid=FB123")
    h2 = article_hash("OpenAI news", "https://example.com/a")
    assert h1 == h2


# ── SupabaseDedup ────────────────────────────────────────────────────────────

class TestSupabaseDedup:
    def _make_dedup(self):
        return SupabaseDedup("https://example.supabase.co", "anon-key", max_size=100)

    def test_init(self):
        d = self._make_dedup()
        assert d.max_size == 100
        assert d._cache == set()

    def test_is_sent_false_before_load(self):
        d = self._make_dedup()
        assert d.is_sent("abc") is False

    def test_is_sent_true_after_mark(self):
        d = self._make_dedup()
        d._cache.add("myhash")
        assert d.is_sent("myhash") is True

    def test_load_success_returns_true_and_cache(self):
        """200 응답 후 (True, cache) 반환."""
        d = self._make_dedup()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{"hash": "aaa"}, {"hash": "bbb"}]
        with patch("requests.get", return_value=mock_resp):
            ok, cache = d.load()
        assert ok is True
        assert "aaa" in cache
        assert "bbb" in cache

    def test_load_500_returns_false_empty_set(self, capsys):
        """500 응답 3회 → (False, set()) 반환 — AC-1."""
        d = self._make_dedup()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        with patch("requests.get", return_value=mock_resp), \
             patch("time.sleep"):
            ok, cache = d.load()
        assert ok is False
        assert cache == set()
        captured = capsys.readouterr()
        assert "Load failed" in captured.out

    def test_load_retries_3_times_on_failure(self):
        """500 응답 시 최대 3회 시도."""
        d = self._make_dedup()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        with patch("requests.get", return_value=mock_resp) as mock_get, \
             patch("time.sleep"):
            d.load()
        assert mock_get.call_count == 3

    def test_load_exception_returns_false(self, capsys):
        """네트워크 예외 3회 → (False, set())."""
        d = self._make_dedup()
        with patch("requests.get", side_effect=Exception("net error")), \
             patch("time.sleep"):
            ok, cache = d.load()
        assert ok is False
        assert cache == set()
        captured = capsys.readouterr()
        assert "Load error" in captured.out

    def test_load_succeeds_on_second_attempt(self):
        """1회 실패 후 2회 성공 → (True, cache)."""
        d = self._make_dedup()
        fail_resp = MagicMock()
        fail_resp.status_code = 500
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = [{"hash": "xyz"}]
        with patch("requests.get", side_effect=[fail_resp, ok_resp]), \
             patch("time.sleep"):
            ok, cache = d.load()
        assert ok is True
        assert "xyz" in cache

    def test_mark_sent_success(self):
        d = self._make_dedup()
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        with patch("requests.post", return_value=mock_resp):
            d.mark_sent(["hash1", "hash2"])
        assert "hash1" in d._cache
        assert "hash2" in d._cache

    def test_mark_sent_conflict_409(self):
        d = self._make_dedup()
        mock_resp = MagicMock()
        mock_resp.status_code = 409
        with patch("requests.post", return_value=mock_resp):
            d.mark_sent(["hash1"])
        assert "hash1" in d._cache

    def test_mark_sent_failure_logged(self, capsys):
        d = self._make_dedup()
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        with patch("requests.post", return_value=mock_resp):
            d.mark_sent(["hash1"])
        captured = capsys.readouterr()
        assert "Insert failed" in captured.out

    def test_mark_sent_exception_logged(self, capsys):
        d = self._make_dedup()
        with patch("requests.post", side_effect=Exception("net error")):
            d.mark_sent(["hash1"])
        captured = capsys.readouterr()
        assert "Insert error" in captured.out
        assert "hash1" in d._cache

    def test_mark_sent_empty_list(self):
        d = self._make_dedup()
        with patch("requests.post") as mock_post:
            d.mark_sent([])
        mock_post.assert_not_called()
