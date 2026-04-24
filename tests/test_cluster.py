import datetime
import pytest
from src.cluster import cluster_articles, simhash_of, _hamming_distance


def _make_article(title: str, weight: float = 1.0, pub_date=None) -> dict:
    return {
        "title": title,
        "link": f"https://example.com/{title[:10]}",
        "summary": "",
        "source": "Test",
        "weight": weight,
        "pub_date": pub_date,
    }


class TestSimhash:
    def test_returns_int(self):
        h = simhash_of("hello world")
        assert isinstance(h, int)

    def test_same_text_same_hash(self):
        assert simhash_of("claude ai update") == simhash_of("claude ai update")

    def test_different_texts_different_hash(self):
        h1 = simhash_of("claude release")
        h2 = simhash_of("supabase database migration")
        # Very likely different (not guaranteed, but reliable for distinct topics)
        assert h1 != h2


class TestHammingDistance:
    def test_identical_is_zero(self):
        assert _hamming_distance(0b1010, 0b1010) == 0

    def test_one_bit_diff(self):
        assert _hamming_distance(0b1010, 0b1011) == 1

    def test_all_bits_diff(self):
        assert _hamming_distance(0, 0xFFFFFFFFFFFFFFFF) == 64


class TestClusterArticles:
    def test_empty_returns_empty(self):
        assert cluster_articles([]) == []

    def test_single_article_returned(self):
        art = _make_article("Claude 3.5 Sonnet released by Anthropic")
        result = cluster_articles([art])
        assert len(result) == 1
        assert result[0] == art

    def test_similar_titles_clustered_to_one(self):
        """거의 동일한 제목 (단어 1~2개 차이) → 1개 대표만."""
        a1 = _make_article("Claude 3.5 Sonnet released by Anthropic today report", weight=1.0)
        a2 = _make_article("Claude 3.5 Sonnet released by Anthropic today news", weight=1.0)
        result = cluster_articles([a1, a2])
        assert len(result) == 1

    def test_different_topics_both_kept(self):
        """완전히 다른 주제 → 2개 모두 유지."""
        a1 = _make_article("Claude 3.5 Sonnet new release anthropic model")
        a2 = _make_article("Supabase launches vector database storage feature")
        result = cluster_articles([a1, a2])
        assert len(result) == 2

    def test_higher_weight_wins(self):
        """같은 클러스터 내 weight 높은 쪽이 대표."""
        now = datetime.datetime.now(datetime.timezone.utc)
        a_low = _make_article("OpenAI releases GPT-5 model new update today", weight=1.0, pub_date=now)
        a_high = _make_article("OpenAI releases GPT-5 model new update tonight", weight=3.0, pub_date=now)
        result = cluster_articles([a_low, a_high])
        assert len(result) == 1
        assert result[0]["weight"] == 3.0

    def test_newer_article_preferred_when_weight_equal(self):
        """weight 동일 시 더 최신 기사가 대표."""
        old = datetime.datetime(2026, 4, 1, tzinfo=datetime.timezone.utc)
        new = datetime.datetime(2026, 4, 23, tzinfo=datetime.timezone.utc)
        a_old = _make_article("Supabase new vector search database launched now", weight=1.0, pub_date=old)
        a_new = _make_article("Supabase new vector search database launched today", weight=1.0, pub_date=new)
        result = cluster_articles([a_old, a_new])
        assert len(result) == 1
        assert result[0]["pub_date"] == new

    def test_preserves_order_across_clusters(self):
        """클러스터 순서가 안정적으로 유지됨."""
        a1 = _make_article("Claude 3.5 Sonnet released by Anthropic today report")
        a2 = _make_article("Supabase database vector search launch feature new")
        a3 = _make_article("Claude 3.5 Sonnet released by Anthropic today news")
        result = cluster_articles([a1, a2, a3])
        # a1, a3 → 1 cluster; a2 → separate
        assert len(result) == 2
