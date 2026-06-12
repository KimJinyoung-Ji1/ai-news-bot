"""
AI News Bot - 진입점
Usage: python -m src.main --mode daily|realtime
"""
import argparse
import datetime
import difflib
import json
import os
import re

# 이모지 strip — 2026-05-28 PM 지시 "이모지 쓸데없는거 다 빼"
# LLM이 프롬프트 어기고 본문에 이모지 추가하는 케이스 후처리 차단
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F5FF"  # Misc Symbols and Pictographs (🔴 등)
    "\U0001F600-\U0001F64F"  # Emoticons
    "\U0001F680-\U0001F6FF"  # Transport
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"  # Supplemental Symbols
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U00002600-\U000026FF"  # Misc Symbols
    "\U00002700-\U000027BF"  # Dingbats
    # AUD-06 (2026-06-12) — 범위 보강
    "\U00002B00-\U00002BFF"  # Misc Symbols and Arrows (⭐ 등)
    "\U00002300-\U000023FF"  # Misc Technical (⏰⏳ 등)
    "\U0001F100-\U0001F2FF"  # Enclosed Alphanumeric/Ideographic Supplement (🅰🈯 + 🇦-🇿 국기)
    "\U0001F650-\U0001F67F"  # Ornamental Dingbats
    "\U0000FE0F"             # Variation Selector-16
    "\U0000200D"             # Zero Width Joiner
    "\U000020E3"             # Combining Enclosing Keycap
    "\U0000203C"             # ‼
    "\U00002049"             # ⁉
    "]+",
    flags=re.UNICODE,
)

def _strip_emoji(s: str) -> str:
    if not s:
        return s
    return _EMOJI_RE.sub("", s).strip()

from .config import load_config, get_env, ROOT_DIR
from .fetchers.rss import fetch_rss_articles
from .fetchers.web import fetch_web_articles
from .fetchers.arxiv import fetch_arxiv_articles
from .fetchers.hackernews import fetch_hackernews_articles
from .fetchers.github_trending import fetch_github_trending_articles
from .analyzer import analyze
from .dedup import article_hash, LocalFileDedup
from .normalize import normalize_title
from .cluster import cluster_articles
from .outputs.telegram import send_telegram
from .outputs.directive_store import save_directives

_LAST_SENT_FILENAME = "data/last_sent.json"
_GUARD_HOURS = 23  # 이 시간 이내 재실행 시 skip (중복 발송 방지)


def _last_sent_path() -> str:
    p = str(ROOT_DIR / _LAST_SENT_FILENAME)
    return p


def _load_last_sent(path: str) -> datetime.datetime | None:
    """마지막 발송 시각을 로드. 파일 없거나 손상 시 None 반환."""
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            ts = data.get("last_sent")
            if ts:
                dt = datetime.datetime.fromisoformat(ts)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
                return dt
    except (json.JSONDecodeError, OSError, ValueError):
        pass
    return None


def _save_last_sent(path: str) -> None:
    """현재 시각을 마지막 발송 시각으로 저장 (원자적 교체)."""
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"last_sent": now_iso}, f, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError as e:
        print(f"[Guard] last_sent save error: {e}")

_FUZZY_THRESHOLD = 0.90
TOP_N = 5


def _recency_factor(pub_date: datetime.datetime | None) -> float:
    if pub_date is None:
        # 날짜 불명 항목은 오래된 박제 기사일 가능성이 높으므로 대폭 하향
        return 0.15
    now = datetime.datetime.now(datetime.timezone.utc)
    if pub_date.tzinfo is None:
        pub_date = pub_date.replace(tzinfo=datetime.timezone.utc)
    age_days = (now - pub_date).total_seconds() / 86400
    return max(0.3, 1 - age_days / 7)


def filter_relevant(articles: list, keywords: list, max_age_days: int = 14,
                    freshness_days: int | None = None) -> list:
    """키워드 매칭 + 신선도 필터.

    - pub_date 가 max_age_days 또는 freshness_days(하드 컷) 초과 과거 → drop
    - pub_date None → drop 하지 않고 _recency_factor 페널티만 적용 (2026-06-12 spec B)
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    relevant = []
    for art in articles:
        # P2-B: max_age_days / freshness_days 초과 기사 drop
        pub_date = art.get("pub_date")
        if pub_date is not None:
            if pub_date.tzinfo is None:
                pub_date = pub_date.replace(tzinfo=datetime.timezone.utc)
            age_days = (now - pub_date).total_seconds() / 86400
            if age_days > max_age_days:
                continue
            # 신선도 하드 컷 — 예전 뉴스 차단 (config analysis.freshness_days)
            if freshness_days is not None and age_days > freshness_days:
                continue

        text = f"{art['title']} {art['summary']}".lower()
        kw_hits = sum(1 for kw in keywords if kw in text)
        if kw_hits < 1:
            continue

        weight = float(art.get("weight", 1.0))
        rf = _recency_factor(art.get("pub_date"))
        score = kw_hits * weight * rf
        art["score"] = score
        relevant.append(art)

    relevant.sort(key=lambda x: x["score"], reverse=True)
    return relevant


def _diversify_by_source(articles: list, max_per_source: int = 2, primary_only: bool = False) -> list:
    """소스 독점 방지 — score 순서를 유지하되 한 소스(또는 벤더 그룹)가 상위를
    독식하지 않도록 재배치한다. 쿼터 내 기사를 앞에, 초과분을 뒤로 보낸다(버리지 않음).
    Anthropic 릴리즈 편향(Claude Code/Status/SDK/Cookbook 등)을 완화한다.
    primary_only=True 이면 쿼터 내 기사만 반환(overflow 제외) — LLM 입력 구성 시 사용."""
    from collections import defaultdict

    def _group(src: str) -> str:
        low = src.lower()
        if "anthropic" in low or "claude" in low:
            return "anthropic"
        if "openai" in low or "chatgpt" in low:
            return "openai"
        if "google" in low or "deepmind" in low or "gemini" in low:
            return "google"
        if "github trending" in low:
            return "github_trending"
        if "arxiv" in low:
            return "arxiv"
        if "hackernews" in low:
            return "hackernews"
        return src

    counts = defaultdict(int)
    primary, overflow = [], []
    for art in articles:
        key = _group(art.get("source", ""))
        if counts[key] < max_per_source:
            primary.append(art)
            counts[key] += 1
        else:
            overflow.append(art)

    if primary_only:
        return primary

    # overflow 내에서도 anthropic 무날짜 항목을 후순위로 밀어 벤더 다양성 강화
    def _overflow_sort_key(a):
        is_anthropic = _group(a.get("source", "")) == "anthropic"
        has_date = a.get("pub_date") is not None
        # (anthropic이고 날짜없으면 맨 뒤) > (anthropic이면 뒤) > (날짜없으면 약간 뒤)
        return (2 if (is_anthropic and not has_date) else 1 if is_anthropic else 0,
                0 if has_date else 1)

    overflow.sort(key=_overflow_sort_key)
    return primary + overflow


def _fuzzy_deduplicate(articles: list) -> list:
    """세션 내 유사 기사 제거 (SequenceMatcher 기반)."""
    result = []
    seen_titles = []
    for art in articles:
        norm = normalize_title(art.get("title", ""))
        duplicate = False
        for seen in seen_titles:
            ratio = difflib.SequenceMatcher(None, norm, seen).ratio()
            if ratio >= _FUZZY_THRESHOLD:
                duplicate = True
                break
        if not duplicate:
            result.append(art)
            seen_titles.append(norm)
    return result


def run(mode: str = "daily", dry_run: bool = False):
    cfg = load_config()
    gemini_key = get_env("GEMINI_API_KEY")
    tg_token = get_env("TELEGRAM_BOT_TOKEN")
    tg_chat = get_env("TELEGRAM_CHAT_ID")
    tg_thread = cfg.get("telegram", {}).get("message_thread_id")
    dedup_cfg = cfg.get("dedup", {})
    max_age_days = cfg.get("analysis", {}).get("max_age_days", 14)
    # 신선도 하드 컷 (기본 3일) — "예전 뉴스가 계속 온다" 차단
    freshness_days = cfg.get("analysis", {}).get("freshness_days", 3)

    # 작업지시(directive) — 로컬 JSON 파일에 저장 (supabase 완전 제거).
    # 컴퓨터를 24시간 켜두는 단일 PC 환경이므로 외부 DB 없이 로컬로 자립한다.
    directive_file = cfg.get("directive", {}).get("file", "data/directives.json")
    if not os.path.isabs(directive_file):
        directive_file = str(ROOT_DIR / directive_file)

    now_kst = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=9)
    print(f"=== Run started (mode={mode}, dry_run={dry_run}, KST={now_kst.strftime('%H:%M')}) ===")

    # 24시간 가드 — 같은 날 중복 발송 방지 (Task Scheduler 오작동·수동 재실행 차단)
    last_sent_file = _last_sent_path()
    if not dry_run and mode == "daily":
        last_sent = _load_last_sent(last_sent_file)
        if last_sent is not None:
            elapsed_hours = (
                datetime.datetime.now(datetime.timezone.utc) - last_sent
            ).total_seconds() / 3600
            if elapsed_hours < _GUARD_HOURS:
                print(
                    f"[Guard] Last sent {elapsed_hours:.1f}h ago "
                    f"(< {_GUARD_HOURS}h). Skip to prevent duplicate. "
                    f"last_sent={last_sent.isoformat()}"
                )
                print("=== Run skipped (24h guard) ===")
                return

    # 중복방지 — 로컬 JSON 파일 (외부 DB 의존 제거, 단일 장애점 해소)
    dedup_file = dedup_cfg.get("file", "data/sent_hashes.json")
    if not os.path.isabs(dedup_file):
        dedup_file = str(ROOT_DIR / dedup_file)
    titles_file = dedup_cfg.get("titles_file", "data/sent_titles.json")
    if not os.path.isabs(titles_file):
        titles_file = str(ROOT_DIR / titles_file)
    dedup = LocalFileDedup(
        dedup_file,
        dedup_cfg.get("max_cache_size", 3000),
        dedup_cfg.get("window_days", 60),
        titles_file=titles_file,
        similarity_threshold=dedup_cfg.get("similarity_threshold", 0.65),
    )
    dedup.load()

    # 기사 수집
    rss = fetch_rss_articles(cfg["sources"]["rss"])
    web = fetch_web_articles(cfg["sources"]["web"], cfg["keywords"], max_age_days=max_age_days)
    arxiv = fetch_arxiv_articles(cfg["sources"].get("arxiv", {}))
    hn = fetch_hackernews_articles(cfg["sources"].get("hackernews", {}))
    gh = fetch_github_trending_articles(cfg["sources"].get("github_trending", {}))
    print(f"Fetched: RSS={len(rss)}, Web={len(web)}, arXiv={len(arxiv)}, HackerNews={len(hn)}, GitHub={len(gh)}")

    # 필터링 (P2-A weight + P2-B recency + max_age_days + freshness 하드 컷)
    relevant = filter_relevant(rss + web + arxiv + hn + gh, cfg["keywords"],
                               max_age_days=max_age_days, freshness_days=freshness_days)
    print(f"Relevant: {len(relevant)}")

    # P1-D: 세션 내 fuzzy 중복 제거
    relevant = _fuzzy_deduplicate(relevant)
    print(f"After fuzzy dedup: {len(relevant)}")

    # 중복 제거 (hash exact + title fuzzy persistent + deny_keywords 영구 차단)
    # 2026-06-04 PM 12782 — config dedup.deny_keywords 부분일치 1건이면 즉시 차단
    deny_keywords = [str(kw).lower().strip() for kw in dedup_cfg.get("deny_keywords", []) if kw]
    denied_count = 0
    new_articles = []
    for art in relevant:
        h = article_hash(art["title"], art["link"])
        norm_title = normalize_title(art["title"])
        if deny_keywords and any(kw in norm_title for kw in deny_keywords):
            denied_count += 1
            continue
        if dedup.is_sent(h):
            continue
        if dedup.is_similar(norm_title):
            continue  # persistent fuzzy 차단
        new_articles.append(art)
    if denied_count:
        print(f"[Deny] {denied_count} articles blocked by deny_keywords")

    print(f"New: {len(new_articles)}")

    if not new_articles:
        if mode == "daily":
            # AUD-04: 하드코딩 이모지 제거 (이모지 절대 금지 정본)
            msg = (
                f"AI 데일리 ({datetime.datetime.now().strftime('%Y-%m-%d')})\n"
                f"{'━' * 17}\n\n"
                f"새로운 적용 가능한 업데이트 없음."
            )
            if dry_run:
                print(f"[DRY-RUN] Would send 'no-new-articles' message ({len(msg)} chars)")
            else:
                ok = send_telegram(msg, tg_token, tg_chat, message_thread_id=tg_thread)
                # AUD-11: 발송 성공 시 last_sent 저장 — 같은 날 중복 "없음" 메시지 차단
                if ok:
                    _save_last_sent(last_sent_file)
        print("=== No new articles ===")
        return

    # P2-C: SimHash 클러스터링 — 대표 기사만 LLM 에 전달
    clustered = cluster_articles(new_articles)
    print(f"After clustering: {len(clustered)} (was {len(new_articles)})")

    # 소스 다양성 — 한 벤더(Anthropic 등) 독점 방지
    max_per_source = cfg.get("analysis", {}).get("max_per_source", 2)
    max_articles = cfg["analysis"]["max_articles"]
    # 1차 diversify: overflow를 뒤로 밀어 score 순 유지 (전체 풀 보존)
    clustered = _diversify_by_source(clustered, max_per_source)
    # LLM 입력: max_articles 범위 내에서 primary_only로 overflow 배제
    # -> Anthropic overflow가 max_articles 슬라이스에 잔류하는 편중 차단
    to_analyze = _diversify_by_source(clustered[:max_articles], max_per_source, primary_only=True)
    print(f"After diversify (max {max_per_source}/source): top sources = "
          + ", ".join(f"{a['source'][:18]}" for a in to_analyze[:6]))

    # Gemini 분석
    model = cfg["analysis"]["model"]
    result = analyze(to_analyze, gemini_key, model)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    divider = "━" * 17

    # AUD-05: sent 처리 대상은 LLM 에 실제로 보여준 항목(to_analyze)만.
    # max_articles 초과·diversify 탈락분은 소각하지 않고 다음 실행에서 재경쟁한다.
    analyzed_hashes = [article_hash(a["title"], a["link"]) for a in to_analyze]
    analyzed_titles = [normalize_title(a["title"]) for a in to_analyze]

    # AUD-03: None = 분석 엔진(API) 호출 실패 — 품질 미달({"items": []})과 구분.
    # 실패 시 mark_sent 생략(후보 보존) + 허위 "기준 미달" 문구 대신 정직 메시지.
    if result is None:
        msg = (
            f"AI 데일리 ({now})\n{divider}\n\n"
            f"분석 실패 — 분석 엔진(Claude·Gemini) 호출이 모두 실패했습니다.\n"
            f"수집한 후보 {len(to_analyze)}건은 보존했으며 내일 재시도합니다."
        )
        if dry_run:
            print(f"[DRY-RUN] Would send 'analysis-failed' message ({len(msg)} chars)")
        else:
            ok = send_telegram(msg, tg_token, tg_chat, message_thread_id=tg_thread)
            if ok and mode == "daily":
                _save_last_sent(last_sent_file)
        print("=== Run completed (analysis failed — candidates preserved) ===")
        return

    items = result.get("items", [])
    sent_ok = False

    if items:
        # 텔레그램 메시지 조립 — 2026-05-28 PM 지시 모바일 가독성 강화
        # (이모지 X, 들여쓰기 X, 항목 간 구분선 O, 메타+링크는 항목 하단)
        item_sep = "─" * 12
        header = f"AI 데일리 ({now})\n{divider}\n"
        body = ""
        directive_items = []
        max_items = cfg["analysis"]["max_items"]
        for i, item in enumerate(items[:max_items], 1):
            # 이모지 강제 strip (LLM이 프롬프트 어겨도 차단)
            title_kr = _strip_emoji(item.get("title_kr") or item.get("title", ""))
            summary_kr = _strip_emoji(item.get("summary_kr", "").strip())
            insight_kr = _strip_emoji(item.get("insight_kr", "").strip())
            category = item.get("category", "")
            score = item.get("score", "")
            link = item.get("link", "")
            directive = item.get("directive", "")
            # 소스: link 도메인 추출
            source_label = ""
            if link:
                try:
                    from urllib.parse import urlparse
                    domain = urlparse(link).netloc.replace("www.", "")
                    source_label = domain
                except Exception:
                    pass

            has_directive = bool(directive.strip())

            # 타이틀
            body += f"\n[{i}] {title_kr}\n\n"
            # 핵심·시사점 (들여쓰기 X, 본문 라벨)
            if summary_kr:
                body += f"핵심  {summary_kr}\n"
            if insight_kr:
                body += f"시사점  {insight_kr}\n"
            # 메타 한 줄 (소스 · 점수 · 카테고리) + 링크
            meta_bits = []
            if source_label:
                meta_bits.append(source_label)
            if score:
                meta_bits.append(f"{score}pt")
            if category:
                meta_bits.append(category)
            if meta_bits:
                body += f"\n{' · '.join(meta_bits)}\n"
            if link:
                body += f"{link}\n"
            # 항목 구분선 (마지막 항목 제외)
            if i < min(len(items), max_items):
                body += f"\n{item_sep}\n"

            if has_directive:
                directive_items.append((i, title_kr, directive, link))

        # "오늘의 작업지시 N건 기록" 표기 제거 (2026-05-28 PM 지시 — 노이즈)
        # directive 자체는 directive_store.py 가 로컬 JSON에 계속 저장함

        if dry_run:
            print(f"[DRY-RUN] Would send telegram message ({len(header+body)} chars)")
            print(f"[DRY-RUN] Items: {len(items[:cfg['analysis']['max_items']])}")
            print(f"[DRY-RUN] Directives: {len(directive_items)} (would save to {os.path.basename(directive_file)}, telegram 표기 없음)")
            # 본문 미리보기 — 품질 검증용
            print("\n" + "=" * 70)
            print("[DRY-RUN PREVIEW — 텔레그램에 보낼 실제 메시지]")
            print("=" * 70)
            print(header + body)
            print("=" * 70)
        else:
            # AUD-02: 발송 결과를 확인해 성공 시에만 mark_sent + last_sent 갱신
            sent_ok = send_telegram(header + body, tg_token, tg_chat, message_thread_id=tg_thread)

            # Directives 로컬 JSON 저장 (supabase 의존 없음) — 발송 성공 시에만
            if sent_ok and directive_items:
                formatted = [(idx, f"[뉴스{idx}] {title}"[:40], command, link)
                             for idx, title, command, link in directive_items]
                added = save_directives(formatted, directive_file)
                print(f"Directives saved locally: {added}/{len(directive_items)} -> {directive_file}")
    else:
        # 2026-05-28 PM 지시: raw 제목 fallback 금지 — "알찰 내용 없음" 솔직 알림
        # (여기는 엔진이 정상 응답했지만 진짜 품질 미달인 경우만 도달 — AUD-03)
        msg = (
            f"AI 데일리 ({now})\n{divider}\n\n"
            f"오늘은 인사이트 줄 만한 새 소식이 없습니다.\n"
            f"(분석 가능 후보 {len(to_analyze)}건은 모두 신선도·실용성 기준 미달로 제외됨)"
        )
        if dry_run:
            print(f"[DRY-RUN] Would send 'no-news' telegram message ({len(msg)} chars)")
        else:
            sent_ok = send_telegram(msg, tg_token, tg_chat, message_thread_id=tg_thread)

    # 중복방지 저장 — AUD-02: 발송 성공 시에만 (실패 시 다음 실행에서 재발송 경쟁)
    if dry_run:
        print(f"[DRY-RUN] Would mark {len(analyzed_hashes)} hashes as sent (skipped)")
        print(f"[DRY-RUN] Would save last_sent timestamp to {last_sent_file} (skipped)")
    elif sent_ok:
        dedup.mark_sent(analyzed_hashes, titles=analyzed_titles)
        if mode == "daily":
            _save_last_sent(last_sent_file)
            print(f"[Guard] last_sent updated -> {last_sent_file}")
    else:
        print("[Guard] send failed — mark_sent/last_sent skipped (다음 실행에서 재시도)")
    print("=== Run completed ===")


if __name__ == "__main__":
    # Windows cron(cp949 stdout)에서 한글·em-dash 출력 시 UnicodeEncodeError 로
    # 런 전체가 죽던 문제 방어 (5/21·5/23 크래시). bat 의 PYTHONIOENCODING 과 이중 방어.
    import sys
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="daily", choices=["daily", "realtime"])
    parser.add_argument("--dry-run", action="store_true", help="Skip telegram send and dedup write")
    args = parser.parse_args()
    run(args.mode, dry_run=args.dry_run)
