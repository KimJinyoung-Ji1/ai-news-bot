"""GitHub Trending fetcher — daily trending repos filtered by AI keywords."""
import re
import time
import requests
from bs4 import BeautifulSoup


HEADERS = {"User-Agent": "Mozilla/5.0 AI-News-Bot/1.0"}


def fetch_github_trending_articles(cfg: dict) -> list:
    """
    Fetch GitHub daily trending repositories filtered by language and AI keywords.
    Returns normalized article dicts matching the ai-news-bot format.
    """
    if not cfg.get("enabled", True):
        return []

    languages = cfg.get("languages", ["Python", "TypeScript", "JavaScript"])
    ai_keywords = set(cfg.get("keywords", ["ai", "llm", "claude", "mcp", "agent"]))
    max_per_fetch = cfg.get("max_per_fetch", 20)

    articles = []
    seen_paths = set()

    for lang in languages:
        try:
            url = f"https://github.com/trending/{lang.lower()}?since=daily"
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            repo_articles = soup.select("article.Box-row")

            for art in repo_articles:
                h2 = art.select_one("h2 a")
                if not h2:
                    continue
                path = h2.get("href", "").strip("/")
                if not path or path in seen_paths:
                    continue

                title = path.replace("/", " / ")
                desc_el = art.select_one("p")
                description = desc_el.get_text(strip=True) if desc_el else ""

                # Stars
                star_el = art.select_one("a[href$='/stargazers']")
                stars_text = star_el.get_text(strip=True).replace(",", "") if star_el else "0"
                try:
                    stars = int(re.sub(r"[^\d]", "", stars_text) or "0")
                except ValueError:
                    stars = 0

                # Filter by AI keyword
                combined = (title + " " + description).lower()
                if not any(kw in combined for kw in ai_keywords):
                    continue

                seen_paths.add(path)
                articles.append({
                    "source": f"GitHub Trending/{lang}",
                    "title": f"[{lang}] {title}: {description}"[:120] if description else f"[{lang}] {title}",
                    "link": "https://github.com/" + path,
                    "summary": description[:400] if description else f"GitHub trending {lang} repository",
                    "date": "",
                    # AUD-09: 수집시각 박제 금지 — trending 은 발행일 개념이 없으므로
                    # None 으로 두고 recency 페널티(_recency_factor)를 받게 한다
                    "pub_date": None,
                    "weight": 1.0 + min(stars / 1000, 1.0),  # scale by stars, max 2.0
                })

            time.sleep(1)
        except Exception as e:
            print(f"[GitHub Trending error] lang={lang}: {e}")

    articles.sort(key=lambda x: x["weight"], reverse=True)
    return articles[:max_per_fetch]
