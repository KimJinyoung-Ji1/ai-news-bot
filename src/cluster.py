"""SimHash 기반 기사 클러스터링.

Hamming distance <= 3 이면 동일 클러스터로 간주하고
소스 weight * recency 점수가 가장 높은 대표 기사 1건만 남긴다.
"""
import datetime
from simhash import Simhash

from .normalize import normalize_title

_HAMMING_THRESHOLD = 12


def simhash_of(text: str) -> int:
    """텍스트를 64-bit SimHash 정수로 변환."""
    return Simhash(text).value


def _hamming_distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _recency_factor(pub_date: datetime.datetime | None) -> float:
    if pub_date is None:
        return 0.5
    now = datetime.datetime.now(datetime.timezone.utc)
    if pub_date.tzinfo is None:
        pub_date = pub_date.replace(tzinfo=datetime.timezone.utc)
    age_days = (now - pub_date).total_seconds() / 86400
    return max(0.3, 1 - age_days / 7)


def _article_score(article: dict) -> float:
    weight = float(article.get("weight", 1.0))
    rf = _recency_factor(article.get("pub_date"))
    return weight * rf


def cluster_articles(articles: list) -> list:
    """유사 기사를 클러스터링하고 각 클러스터에서 대표 기사 1건만 반환."""
    if not articles:
        return []

    hashes = [simhash_of(normalize_title(a.get("title", ""))) for a in articles]
    assigned = [-1] * len(articles)
    cluster_id = 0

    for i in range(len(articles)):
        if assigned[i] != -1:
            continue
        assigned[i] = cluster_id
        for j in range(i + 1, len(articles)):
            if assigned[j] != -1:
                continue
            if _hamming_distance(hashes[i], hashes[j]) <= _HAMMING_THRESHOLD:
                assigned[j] = cluster_id
        cluster_id += 1

    clusters: dict[int, list] = {}
    for idx, cid in enumerate(assigned):
        clusters.setdefault(cid, []).append(articles[idx])

    result = []
    for cid in sorted(clusters):
        members = clusters[cid]
        best = max(members, key=_article_score)
        result.append(best)

    return result
