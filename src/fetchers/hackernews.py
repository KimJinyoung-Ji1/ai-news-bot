"""HackerNews fetcher — top stories filtered by keywords."""
import datetime
import time
import requests


HN_API = "https://hn.algolia.com/api/v1/search"


def fetch_hackernews_articles(cfg: dict) -> list:
    """
    Fetch HackerNews front-page stories filtered by configured keywords.
    Returns normalized article dicts matching the ai-news-bot format.
    """
    if not cfg.get("enabled", True):
        return []

    keywords = cfg.get("keywords", ["Claude", "Anthropic", "OpenAI", "LLM", "MCP"])
    max_per_fetch = cfg.get("max_per_fetch", 30)

    cutoff = int(
        (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=3)).timestamp()
    )

    articles = []
    seen_ids = set()

    for kw in keywords:
        try:
            params = {
                "query": kw,
                "tags": "story",
                "numericFilters": f"created_at_i>{cutoff}",
                "hitsPerPage": 20,
            }
            r = requests.get(HN_API, params=params, timeout=15)
            r.raise_for_status()
            for hit in r.json().get("hits", []):
                oid = hit.get("objectID")
                if not oid or oid in seen_ids:
                    continue
                seen_ids.add(oid)

                url = hit.get("url") or f"https://news.ycombinator.com/item?id={oid}"
                title = hit.get("title", "").strip()
                if not title:
                    continue

                # Parse pub_date
                pub_date = None
                created_at = hit.get("created_at")
                if created_at:
                    try:
                        pub_date = datetime.datetime.fromisoformat(
                            created_at.replace("Z", "+00:00")
                        )
                    except Exception:
                        pub_date = None

                points = hit.get("points", 0) or 0

                articles.append({
                    "source": "HackerNews",
                    "title": title,
                    "link": url,
                    "summary": f"HN points: {points}",
                    "date": created_at or "",
                    "pub_date": pub_date,
                    "weight": 1.0 + min(points / 500, 1.0),  # scale weight by points, max 2.0
                })
            time.sleep(0.5)
        except Exception as e:
            print(f"[HackerNews error] keyword={kw}: {e}")

    # Sort by points-adjusted weight desc, then dedup by link
    articles.sort(key=lambda x: x["weight"], reverse=True)
    seen_links = set()
    unique = []
    for art in articles:
        if art["link"] not in seen_links:
            seen_links.add(art["link"])
            unique.append(art)

    return unique[:max_per_fetch]
