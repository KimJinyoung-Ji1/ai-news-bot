"""ArXiv fetcher — cs.AI / cs.CL / cs.LG categories, recent N days."""
import datetime
import time
import feedparser


def fetch_arxiv_articles(cfg: dict) -> list:
    """
    Fetch recent arXiv papers from cs.AI, cs.CL, cs.LG categories.
    Returns normalized article dicts matching the ai-news-bot format.
    """
    if not cfg.get("enabled", True):
        return []

    categories = cfg.get("categories", ["cs.AI", "cs.CL", "cs.LG"])
    days = cfg.get("days", 7)
    max_per_fetch = cfg.get("max_per_fetch", 20)

    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    articles = []

    for cat in categories:
        try:
            query = f"cat:{cat}"
            url = (
                "https://export.arxiv.org/api/query"
                f"?search_query={query}"
                f"&max_results={max_per_fetch}"
                "&sortBy=submittedDate&sortOrder=descending"
            )
            feed = feedparser.parse(url)
            for entry in feed.entries:
                title = entry.get("title", "").replace("\n", " ").strip()
                link = entry.get("id", "").replace("http://", "https://")
                summary = entry.get("summary", "").replace("\n", " ")[:400].strip()

                # Parse pub_date
                pub_date = None
                published = entry.get("published_parsed")
                if published:
                    try:
                        pub_date = datetime.datetime(*published[:6], tzinfo=datetime.timezone.utc)
                    except Exception:
                        pub_date = None

                # Filter by date
                if pub_date and pub_date < cutoff:
                    continue

                if not title or not link:
                    continue

                articles.append({
                    "source": f"arXiv/{cat}",
                    "title": title,
                    "link": link,
                    "summary": summary,
                    "date": entry.get("published", ""),
                    "pub_date": pub_date,
                    "weight": 1.5,
                })
            time.sleep(1)
        except Exception as e:
            print(f"[arXiv error] {cat}: {e}")

    # Deduplicate by link
    seen = set()
    unique = []
    for art in articles:
        if art["link"] not in seen:
            seen.add(art["link"])
            unique.append(art)

    return unique[:max_per_fetch]
