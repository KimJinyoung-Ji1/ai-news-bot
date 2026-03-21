import feedparser
from bs4 import BeautifulSoup


def fetch_rss_articles(sources: list) -> list:
    articles = []
    for src in sources:
        try:
            feed = feedparser.parse(src["url"])
            for entry in feed.entries[:10]:
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                summary = entry.get("summary", "")[:300].strip()
                if title and link:
                    articles.append({
                        "source": src["name"], "title": title, "link": link,
                        "summary": BeautifulSoup(summary, "html.parser").get_text()[:200],
                        "date": entry.get("published", ""),
                    })
        except Exception as e:
            print(f"[RSS error] {src['name']}: {e}")
    return articles
