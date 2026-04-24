import hashlib
import time
import datetime
import requests

from .normalize import normalize_url, normalize_title


def article_hash(title: str, link: str) -> str:
    norm = normalize_title(title) + "|" + normalize_url(link)
    return hashlib.md5(norm.encode()).hexdigest()


class SupabaseDedup:
    def __init__(
        self,
        supabase_url: str,
        anon_key: str,
        max_size: int = 2000,
        window_days: int = 30,
    ):
        self.url = f"{supabase_url}/rest/v1/news_bot_sent"
        self.headers = {
            "apikey": anon_key,
            "Authorization": f"Bearer {anon_key}",
            "Content-Type": "application/json",
        }
        self.max_size = max_size
        self.window_days = window_days
        self._cache: set = set()

    def load(self) -> tuple[bool, set]:
        """캐시를 로드한다. 성공 시 (True, cache), 실패 시 (False, set()) 반환."""
        cutoff = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=self.window_days)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        max_retries = 3
        for attempt in range(max_retries):
            try:
                resp = requests.get(
                    self.url,
                    headers=self.headers,
                    params={
                        "select": "hash",
                        "order": "created_at.desc",
                        "limit": self.max_size,
                        "created_at": f"gte.{cutoff}",
                    },
                    timeout=10,
                )
                if resp.status_code == 200:
                    self._cache = {row["hash"] for row in resp.json()}
                    print(f"[Dedup] Loaded {len(self._cache)} hashes (window={self.window_days}d)")
                    return (True, self._cache)
                print(
                    f"[Dedup] Load failed: {resp.status_code}"
                    f" (attempt {attempt + 1}/{max_retries})"
                )
            except Exception as e:
                print(
                    f"[Dedup] Load error: {e}"
                    f" (attempt {attempt + 1}/{max_retries})"
                )

            if attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"[Dedup] Retrying in {wait}s...")
                time.sleep(wait)

        print("[Dedup] load() failed after all retries — run aborted")
        return (False, set())

    def is_sent(self, h: str) -> bool:
        return h in self._cache

    def mark_sent(self, hashes: list):
        for h in hashes:
            try:
                resp = requests.post(
                    self.url,
                    headers={**self.headers, "Prefer": "return=minimal"},
                    json={"hash": h},
                    timeout=10,
                )
                if resp.status_code not in (200, 201, 409):
                    print(f"[Dedup] Insert failed: {resp.status_code}")
            except Exception as e:
                print(f"[Dedup] Insert error: {e}")
            self._cache.add(h)
