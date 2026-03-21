import hashlib
import requests


def article_hash(title: str, link: str) -> str:
    return hashlib.md5(f"{title}:{link}".encode()).hexdigest()


class SupabaseDedup:
    def __init__(self, supabase_url: str, anon_key: str, max_size: int = 500):
        self.url = f"{supabase_url}/rest/v1/news_bot_sent"
        self.headers = {
            "apikey": anon_key,
            "Authorization": f"Bearer {anon_key}",
            "Content-Type": "application/json",
        }
        self.max_size = max_size
        self._cache = set()

    def load(self) -> set:
        try:
            resp = requests.get(
                self.url, headers=self.headers,
                params={"select": "hash", "order": "created_at.desc", "limit": self.max_size},
                timeout=10,
            )
            if resp.status_code == 200:
                self._cache = {row["hash"] for row in resp.json()}
            else:
                print(f"[Dedup] Load failed: {resp.status_code}")
        except Exception as e:
            print(f"[Dedup] Load error: {e}")
        return self._cache

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
