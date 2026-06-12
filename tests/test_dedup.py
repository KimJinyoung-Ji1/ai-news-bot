import datetime
import json
import pytest
from unittest.mock import patch, MagicMock, call
from src.dedup import article_hash, LocalFileDedup


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


# ── LocalFileDedup (로컬 파일 기반, 외부 DB 미사용) ──────────────────────────────

class TestLocalFileDedup:
    def test_load_missing_file_returns_empty_ok(self, tmp_path):
        """파일이 없으면 빈 캐시로 정상 진행 (abort 없음)."""
        d = LocalFileDedup(str(tmp_path / "sent.json"))
        ok, cache = d.load()
        assert ok is True
        assert cache == set()

    def test_mark_then_is_sent_persists(self, tmp_path):
        """mark_sent 후 새 인스턴스로 load 해도 기억된다 (파일 영속)."""
        path = str(tmp_path / "sent.json")
        d = LocalFileDedup(path)
        d.load()
        d.mark_sent(["hashA", "hashB"])
        assert d.is_sent("hashA")

        d2 = LocalFileDedup(path)
        d2.load()
        assert d2.is_sent("hashA")
        assert d2.is_sent("hashB")
        assert not d2.is_sent("hashZ")

    def test_window_evicts_old_hashes(self, tmp_path):
        """window_days 보다 오래된 해시는 load 시 제외된다."""
        path = tmp_path / "sent.json"
        old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=100)).isoformat()
        recent = datetime.datetime.now(datetime.timezone.utc).isoformat()
        path.write_text(json.dumps({"old": old, "recent": recent}), encoding="utf-8")

        d = LocalFileDedup(str(path), window_days=45)
        d.load()
        assert d.is_sent("recent")
        assert not d.is_sent("old")

    def test_corrupt_file_starts_empty(self, tmp_path):
        """손상된 JSON 파일이어도 빈 캐시로 진행 (발송 중단 없음)."""
        path = tmp_path / "sent.json"
        path.write_text("{ this is not valid json ", encoding="utf-8")
        d = LocalFileDedup(str(path))
        ok, cache = d.load()
        assert ok is True
        assert cache == set()

    def test_max_size_evicts_oldest(self, tmp_path):
        """max_size 초과 시 가장 오래된 해시부터 제거된다."""
        path = str(tmp_path / "sent.json")
        d = LocalFileDedup(path, max_size=2)
        d.load()
        d.mark_sent(["h1"])
        d.mark_sent(["h2"])
        d.mark_sent(["h3"])  # h1 이 밀려남
        assert len(d._cache) == 2
        assert d.is_sent("h3")
        assert not d.is_sent("h1")


# ── LocalFileDedup: persistent fuzzy title dedup ─────────────────────────────

class TestLocalFileDedupTitles:
    def _make(self, tmp_path, threshold: float = 0.75) -> LocalFileDedup:
        path = str(tmp_path / "sent_hashes.json")
        titles_file = str(tmp_path / "sent_titles.json")
        d = LocalFileDedup(path, titles_file=titles_file, similarity_threshold=threshold)
        d.load()
        return d

    def test_is_similar_blocks_near_duplicate(self, tmp_path):
        """저장된 제목과 유사한 제목을 차단한다."""
        from src.normalize import normalize_title
        d = self._make(tmp_path)
        # "Claude 4.7 Opus 출시" 저장
        norm1 = normalize_title("Claude 4.7 Opus 출시")
        d.mark_sent(["hash_a"], titles=[norm1])

        # "Anthropic releases Claude 4.7" 신규 → 완전히 다른 언어이지만 임계치 0.75 기준 확인
        norm2 = normalize_title("claude 47 opus 출시")  # 거의 동일 → 차단
        assert d.is_similar(norm2) is True

    def test_is_similar_allows_distinct(self, tmp_path):
        """완전히 다른 주제의 제목은 통과시킨다."""
        from src.normalize import normalize_title
        d = self._make(tmp_path)
        norm1 = normalize_title("Claude 4.7 출시")
        d.mark_sent(["hash_a"], titles=[norm1])

        norm2 = normalize_title("GPT-5 발표")
        assert d.is_similar(norm2) is False

    def test_window_filter_drops_expired_titles(self, tmp_path):
        """50일 전 타임스탬프 항목은 캐시에서 제외된다."""
        titles_file = tmp_path / "sent_titles.json"
        old_ts = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=50)
        ).isoformat()
        titles_file.write_text(
            json.dumps({"claude 47 opus 출시": old_ts}), encoding="utf-8"
        )
        hashes_file = str(tmp_path / "sent_hashes.json")
        d = LocalFileDedup(
            hashes_file,
            window_days=45,
            titles_file=str(titles_file),
            similarity_threshold=0.75,
        )
        d.load()
        # 50일 전 항목은 window 45일 밖 → 캐시에서 제외
        assert len(d._title_cache) == 0
        assert d.is_similar("claude 47 opus 출시") is False

    def test_titles_persist_across_instances(self, tmp_path):
        """mark_sent(titles=...) 후 새 인스턴스로 load 해도 유사도 차단이 유지된다."""
        from src.normalize import normalize_title
        hashes_file = str(tmp_path / "sent_hashes.json")
        titles_file = str(tmp_path / "sent_titles.json")

        d1 = LocalFileDedup(hashes_file, titles_file=titles_file, similarity_threshold=0.75)
        d1.load()
        norm = normalize_title("Claude 4.7 Opus 출시")
        d1.mark_sent(["hash_x"], titles=[norm])

        d2 = LocalFileDedup(hashes_file, titles_file=titles_file, similarity_threshold=0.75)
        d2.load()
        # 거의 동일한 제목 → 차단
        assert d2.is_similar(normalize_title("claude 47 opus 출시")) is True

    def test_no_titles_file_is_similar_always_false(self, tmp_path):
        """titles_file 미설정 시 is_similar는 항상 False (하위 호환)."""
        path = str(tmp_path / "sent_hashes.json")
        d = LocalFileDedup(path)  # titles_file 없음
        d.load()
        d.mark_sent(["h"], titles=["some title"])
        assert d.is_similar("some title") is False
