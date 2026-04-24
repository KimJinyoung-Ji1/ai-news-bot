import datetime
import requests
from bs4 import BeautifulSoup


def fetch_web_articles(sources: list, keywords: list) -> list:
    articles = []
    headers = {"User-Agent": "Mozilla/5.0 AI-News-Bot/1.0"}
    for src in sources:
        weight = src.get("weight", 1.0)
        try:
            resp = requests.get(src["url"], headers=headers, timeout=10)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            fetched_at = datetime.datetime.now(datetime.timezone.utc)
            for a_tag in soup.find_all("a", href=True)[:30]:
                text = a_tag.get_text(strip=True)
                href = a_tag["href"]
                if len(text) > 15 and any(kw in text.lower() for kw in keywords):
                    if not href.startswith("http"):
                        base = src["url"].rsplit("/", 1)[0]
                        href = base + "/" + href.lstrip("/")
                    articles.append({
                        "source": src["name"],
                        "title": text[:100],
                        "link": href,
                        "summary": "",
                        "date": "",
                        "pub_date": fetched_at,
                        "weight": weight,
                    })
        except Exception as e:
            print(f"[Web error] {src['name']}: {e}")
    return articles
