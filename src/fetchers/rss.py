import datetime
import feedparser
from bs4 import BeautifulSoup


def fetch_rss_articles(sources: list) -> list:
    articles = []
    for src in sources:
        weight = src.get("weight", 1.0)
        try:
            feed = feedparser.parse(src["url"])
            for entry in feed.entries[:10]:
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                summary = entry.get("summary", "")[:600].strip()
                if title and link:
                    pub_date = None
                    parsed = entry.get("published_parsed")
                    if parsed:
                        try:
                            pub_date = datetime.datetime(*parsed[:6], tzinfo=datetime.timezone.utc)
                        except Exception:
                            pub_date = None
                    articles.append({
                        "source": src["name"],
                        "title": title,
                        "link": link,
                        "summary": BeautifulSoup(summary, "html.parser").get_text()[:400],
                        "date": entry.get("published", ""),
                        "pub_date": pub_date,
                        "weight": weight,
                    })
        except Exception as e:
            print(f"[RSS error] {src['name']}: {e}")
    return articles
