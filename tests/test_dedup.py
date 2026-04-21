import pytest
from unittest.mock import patch, MagicMock
from src.dedup import article_hash, SupabaseDedup


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

    def test_load_success(self):
        d = self._make_dedup()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{"hash": "aaa"}, {"hash": "bbb"}]
        with patch("requests.get", return_value=mock_resp):
            result = d.load()
        assert "aaa" in result
        assert "bbb" in result

    def test_load_failure_non_200(self, capsys):
        d = self._make_dedup()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        with patch("requests.get", return_value=mock_resp):
            d.load()
        captured = capsys.readouterr()
        assert "Load failed" in captured.out

    def test_load_exception(self, capsys):
        d = self._make_dedup()
        with patch("requests.get", side_effect=Exception("net error")):
            d.load()
        captured = capsys.readouterr()
        assert "Load error" in captured.out

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
