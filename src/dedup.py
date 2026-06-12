import difflib
import hashlib
import json
import os
import datetime

from .normalize import normalize_url, normalize_title


def article_hash(title: str, link: str) -> str:
    norm = normalize_title(title) + "|" + normalize_url(link)
    return hashlib.md5(norm.encode()).hexdigest()


class LocalFileDedup:
    """로컬 JSON 파일 기반 중복방지 — 외부 DB 의존 없음.

    단일 PC에서 cron 으로 도는 봇에는 외부 supabase 가 과하고 단일 장애점이었다.
    {hash: ISO_timestamp} 를 파일에 저장하고, load 시 window_days 이내만 캐시한다.
    파일이 없거나 손상돼도 빈 캐시로 정상 진행하므로 발송이 멈추지 않는다.
    """

    def __init__(
        self,
        path: str,
        max_size: int = 3000,
        window_days: int = 60,
        titles_file: str | None = None,
        similarity_threshold: float = 0.65,
    ):
        self.path = path
        self.max_size = max_size
        self.window_days = window_days
        self.titles_file = titles_file
        self.similarity_threshold = similarity_threshold
        self._store: dict = {}  # hash -> ISO timestamp
        self._cache: set = set()
        self._title_store: dict = {}  # normalized_title -> ISO timestamp
        self._title_cache: list = []   # window 내 정규화 제목 목록 (순서 보존)

    def load(self) -> tuple[bool, set]:
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            days=self.window_days
        )
        raw = {}
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[Dedup] Local load error: {e} - starting empty")
            raw = {}

        kept = {}
        for h, ts in raw.items():
            try:
                t = datetime.datetime.fromisoformat(ts)
                if t.tzinfo is None:
                    t = t.replace(tzinfo=datetime.timezone.utc)
                if t >= cutoff:
                    kept[h] = ts
            except (ValueError, TypeError):
                continue

        self._store = kept
        self._cache = set(kept.keys())
        print(f"[Dedup] Loaded {len(self._cache)} hashes from local file (window={self.window_days}d)")

        # titles 파일 로드 (있을 때만)
        self._load_titles(cutoff)

        return (True, self._cache)

    def _load_titles(self, cutoff: datetime.datetime) -> None:
        """sent_titles.json 에서 window 내 제목 목록을 캐시에 올린다."""
        if not self.titles_file:
            return
        raw_titles = {}
        try:
            if os.path.exists(self.titles_file):
                with open(self.titles_file, "r", encoding="utf-8") as f:
                    raw_titles = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[Dedup] Titles load error: {e} - starting empty titles")
            raw_titles = {}

        kept_titles = {}
        for title, ts in raw_titles.items():
            try:
                t = datetime.datetime.fromisoformat(ts)
                if t.tzinfo is None:
                    t = t.replace(tzinfo=datetime.timezone.utc)
                if t >= cutoff:
                    kept_titles[title] = ts
            except (ValueError, TypeError):
                continue

        self._title_store = kept_titles
        self._title_cache = list(kept_titles.keys())
        print(f"[Dedup] Loaded {len(self._title_cache)} titles from local file (window={self.window_days}d)")

    def is_sent(self, h: str) -> bool:
        return h in self._cache

    def is_similar(self, normalized_title: str) -> bool:
        """발송 이력의 제목과 fuzzy 유사도 비교. threshold 이상이면 True(차단).

        titles_file 미설정 시 항상 False(차단하지 않음)를 반환하여 하위호환을 보장한다.
        """
        if not self.titles_file:
            return False
        for seen in self._title_cache:
            ratio = difflib.SequenceMatcher(None, normalized_title, seen).ratio()
            if ratio >= self.similarity_threshold:
                return True
        return False

    def mark_sent(self, hashes: list, titles: list | None = None):
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        for h in hashes:
            self._store[h] = now_iso
            self._cache.add(h)

        # max_size 초과 시 오래된 항목부터 제거
        if len(self._store) > self.max_size:
            ordered = sorted(self._store.items(), key=lambda kv: kv[1])
            for h, _ in ordered[: len(self._store) - self.max_size]:
                self._store.pop(h, None)
                self._cache.discard(h)

        self._save()

        # titles 영구 저장
        if titles and self.titles_file:
            for t in titles:
                self._title_store[t] = now_iso
                if t not in self._title_cache:
                    self._title_cache.append(t)
            # max_size 동일 기준으로 오래된 제목 정리
            if len(self._title_store) > self.max_size:
                ordered_t = sorted(self._title_store.items(), key=lambda kv: kv[1])
                for t, _ in ordered_t[: len(self._title_store) - self.max_size]:
                    self._title_store.pop(t, None)
                    if t in self._title_cache:
                        self._title_cache.remove(t)
            self._save_titles()

    def _save(self):
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._store, f, ensure_ascii=False)
            os.replace(tmp, self.path)  # 원자적 교체 — 쓰다 죽어도 본 파일 보존
        except OSError as e:
            print(f"[Dedup] Local save error: {e}")

    def _save_titles(self):
        if not self.titles_file:
            return
        directory = os.path.dirname(self.titles_file)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp = self.titles_file + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._title_store, f, ensure_ascii=False)
            os.replace(tmp, self.titles_file)
        except OSError as e:
            print(f"[Dedup] Titles save error: {e}")
