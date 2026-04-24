"""
AI News Bot - 진입점
Usage: python -m src.main --mode daily|realtime
"""
import argparse
import datetime
import difflib

from .config import load_config, get_env
from .fetchers.rss import fetch_rss_articles
from .fetchers.web import fetch_web_articles
from .analyzer import analyze
from .dedup import article_hash, SupabaseDedup
from .normalize import normalize_title
from .cluster import cluster_articles
from .outputs.telegram import send_telegram
from .outputs.supabase import insert_directive

_FUZZY_THRESHOLD = 0.90


def _recency_factor(pub_date: datetime.datetime | None) -> float:
    if pub_date is None:
        return 0.5
    now = datetime.datetime.now(datetime.timezone.utc)
    if pub_date.tzinfo is None:
        pub_date = pub_date.replace(tzinfo=datetime.timezone.utc)
    age_days = (now - pub_date).total_seconds() / 86400
    return max(0.3, 1 - age_days / 7)


def filter_relevant(articles: list, keywords: list, max_age_days: int = 14) -> list:
    now = datetime.datetime.now(datetime.timezone.utc)
    relevant = []
    for art in articles:
        # P2-B: max_age_days 초과 기사 drop
        pub_date = art.get("pub_date")
        if pub_date is not None:
            if pub_date.tzinfo is None:
                pub_date = pub_date.replace(tzinfo=datetime.timezone.utc)
            age_days = (now - pub_date).total_seconds() / 86400
            if age_days > max_age_days:
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


def run(mode: str = "daily"):
    cfg = load_config()
    gemini_key = get_env("GEMINI_API_KEY")
    tg_token = get_env("TELEGRAM_BOT_TOKEN")
    tg_chat = get_env("TELEGRAM_CHAT_ID")
    sb_key = get_env("SUPABASE_ANON_KEY")
    sb_ji1_key = get_env("SUPABASE_JI1_KEY", required=False) or sb_key
    sb_url = cfg["supabase"]["url"]
    sb_ji1_url = cfg["supabase"]["ji1_url"]
    tg_thread = cfg.get("telegram", {}).get("message_thread_id")
    dedup_cfg = cfg.get("dedup", {})
    max_age_days = cfg.get("analysis", {}).get("max_age_days", 14)

    now_kst = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=9)
    print(f"=== Run started (mode={mode}, KST={now_kst.strftime('%H:%M')}) ===")

    # 중복방지 로드 — 실패 시 발송 없이 종료
    dedup = SupabaseDedup(
        sb_url,
        sb_key,
        dedup_cfg.get("max_cache_size", 2000),
        dedup_cfg.get("window_days", 30),
    )
    ok, _ = dedup.load()
    if not ok:
        send_telegram(
            "[AI 뉴스봇] dedup 로드 실패로 이번 런 스킵. 다음 cron 에서 재시도합니다.",
            tg_token,
            tg_chat,
            message_thread_id=tg_thread,
        )
        print("=== Aborted: dedup load failed ===")
        return

    # 기사 수집
    rss = fetch_rss_articles(cfg["sources"]["rss"])
    web = fetch_web_articles(cfg["sources"]["web"], cfg["keywords"])
    print(f"Fetched: RSS={len(rss)}, Web={len(web)}")

    # 필터링 (P2-A weight + P2-B recency + max_age_days)
    relevant = filter_relevant(rss + web, cfg["keywords"], max_age_days=max_age_days)
    print(f"Relevant: {len(relevant)}")

    # P1-D: 세션 내 fuzzy 중복 제거
    relevant = _fuzzy_deduplicate(relevant)
    print(f"After fuzzy dedup: {len(relevant)}")

    # 중복 제거
    new_articles = []
    new_hashes = []
    for art in relevant:
        h = article_hash(art["title"], art["link"])
        if not dedup.is_sent(h):
            new_articles.append(art)
            new_hashes.append(h)

    print(f"New: {len(new_articles)}")

    if not new_articles:
        if mode == "daily":
            send_telegram(
                f"AI 데일리 ({datetime.datetime.now().strftime('%Y-%m-%d')})\n\n"
                f"새로운 적용 가능한 업데이트 없음.",
                tg_token, tg_chat, message_thread_id=tg_thread,
            )
        dedup.mark_sent(new_hashes)
        print("=== No new articles ===")
        return

    # P2-C: SimHash 클러스터링 — 대표 기사만 LLM 에 전달
    clustered = cluster_articles(new_articles)
    print(f"After clustering: {len(clustered)} (was {len(new_articles)})")

    # Gemini 분석
    max_articles = cfg["analysis"]["max_articles"]
    model = cfg["analysis"]["model"]
    result = analyze(clustered[:max_articles], gemini_key, model)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    items = result.get("items", [])

    if items:
        # 텔레그램 메시지 조립
        header = f"AI 업데이트 ({now})\n{'━' * 20}\n\n"
        body = ""
        directive_items = []
        for i, item in enumerate(items[:cfg["analysis"]["max_items"]], 1):
            title = item.get("title", "")
            summary = item.get("summary", "")
            apply_text = item.get("apply", "")
            link = item.get("link", "")
            directive = item.get("directive", "")

            has_directive = bool(directive.strip())
            marker = " *" if has_directive else ""

            body += f"[{i}]{marker} {title}\n"
            body += f" - {summary}\n"
            body += f" - 적용: {apply_text}\n"
            if link:
                body += f" - {link}\n"
            body += "\n"

            if has_directive:
                directive_items.append((i, title, directive, link))

        if directive_items:
            body += "━" * 20 + "\n"
            body += "* 표시 = 작업지시 등록됨\n"
            nums = ", ".join(str(d[0]) for d in directive_items)
            body += f"등록: [{nums}]번\n"
            body += "Claude Code에서 /directives 로 실행 가능"

        send_telegram(header + body, tg_token, tg_chat, message_thread_id=tg_thread)

        # Directives 등록 → logs.shared_context (ji1-dashboard)
        inserted = 0
        for idx, title, command, link in directive_items:
            note = f"AI뉴스봇 [{idx}]번 항목. 참고: {link}" if link else f"AI뉴스봇 [{idx}]번 항목"
            if insert_directive(f"[뉴스{idx}] {title}"[:30], command, note, sb_ji1_url, sb_ji1_key):
                inserted += 1
        if directive_items:
            print(f"Directives inserted: {inserted}/{len(directive_items)}")
    else:
        lines = [f"AI 업데이트 ({now})\n"]
        for art in new_articles[:10]:
            lines.append(f"- {art['title'][:60]}")
        send_telegram("\n".join(lines), tg_token, tg_chat, message_thread_id=tg_thread)

    # 중복방지 저장
    dedup.mark_sent(new_hashes)
    print("=== Run completed ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="daily", choices=["daily", "realtime"])
    args = parser.parse_args()
    run(args.mode)
