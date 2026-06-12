import datetime
import re
import requests
from bs4 import BeautifulSoup

# 웹 스크랩 페이지(changelog·news·release notes)는 과거 항목이 그대로 박제되어 있다.
# 예전 코드는 발행일을 "긁은 시각"으로 박아 두세 달 전 항목도 나이 필터를 우회했다.
# 제목 텍스트에 붙은 실제 날짜("Apr 16, 2026")를 파싱해 진짜 발행일을 쓴다.

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_DATE_RE = re.compile(
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*(\d{1,2}),?\s*(\d{4})",
    re.IGNORECASE,
)
# 페이지 제목 앞뒤에 붙는 카테고리 라벨 노이즈 제거용
_CATEGORY_RE = re.compile(
    r"\b(Product|Announcements?|Engineering|Research|Policy|Societal Impacts?|"
    r"Alignment|Interpretability|Company|News|Featured)\b",
    re.IGNORECASE,
)


def _parse_date(text: str):
    """제목 문자열에서 'Mon DD, YYYY' 날짜를 파싱. (pub_date, 날짜 제거된 텍스트) 반환."""
    m = _DATE_RE.search(text)
    if not m:
        return None, text
    mon = _MONTHS.get(m.group(1)[:3].lower())
    try:
        pub = datetime.datetime(
            int(m.group(3)), mon, int(m.group(2)), tzinfo=datetime.timezone.utc
        )
    except (ValueError, TypeError):
        return None, text
    cleaned = (text[: m.start()] + " " + text[m.end():]).strip()
    return pub, cleaned


def _clean_title(text: str) -> str:
    text = _CATEGORY_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_web_articles(sources: list, keywords: list, max_age_days: int = 14) -> list:
    articles = []
    headers = {"User-Agent": "Mozilla/5.0 AI-News-Bot/1.0"}
    now = datetime.datetime.now(datetime.timezone.utc)
    for src in sources:
        weight = src.get("weight", 1.0)
        try:
            resp = requests.get(src["url"], headers=headers, timeout=10)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for a_tag in soup.find_all("a", href=True)[:40]:
                raw = a_tag.get_text(" ", strip=True)
                if not raw or "@" in raw:  # footer 이메일·연락처 링크 제외
                    continue

                pub_date, without_date = _parse_date(raw)
                title = _clean_title(without_date)
                if len(title) < 15:
                    continue
                if not any(kw in title.lower() for kw in keywords):
                    continue

                # 발행일을 못 찾으면 네비게이션/박제된 옛 항목일 가능성 → 제외
                if pub_date is None:
                    continue
                age_days = (now - pub_date).total_seconds() / 86400
                if age_days > max_age_days or age_days < -1:
                    continue

                href = a_tag["href"]
                if not href.startswith("http"):
                    base = src["url"].rsplit("/", 1)[0]
                    href = base + "/" + href.lstrip("/")

                articles.append({
                    "source": src["name"],
                    "title": title[:100],
                    "link": href,
                    "summary": "",
                    "date": pub_date.strftime("%Y-%m-%d"),
                    "pub_date": pub_date,
                    "weight": weight,
                })
        except Exception as e:
            print(f"[Web error] {src['name']}: {e}")
    return articles
