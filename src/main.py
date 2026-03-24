"""
AI News Bot - 진입점
Usage: python -m src.main --mode daily|realtime
"""
import argparse
import datetime

from .config import load_config, get_env
from .fetchers.rss import fetch_rss_articles
from .fetchers.web import fetch_web_articles
from .analyzer import analyze
from .dedup import article_hash, SupabaseDedup
from .outputs.telegram import send_telegram
from .outputs.supabase import insert_directive


def filter_relevant(articles: list, keywords: list) -> list:
    relevant = []
    for art in articles:
        text = f"{art['title']} {art['summary']}".lower()
        score = sum(1 for kw in keywords if kw in text)
        if score >= 1:
            art["score"] = score
            relevant.append(art)
    relevant.sort(key=lambda x: x["score"], reverse=True)
    return relevant


def run(mode: str = "daily"):
    cfg = load_config()
    gemini_key = get_env("GEMINI_API_KEY")
    tg_token = get_env("TELEGRAM_BOT_TOKEN")
    tg_chat = get_env("TELEGRAM_CHAT_ID")
    sb_key = get_env("SUPABASE_ANON_KEY")
    sb_url = cfg["supabase"]["url"]

    print(f"=== Run started (mode={mode}) ===")

    # 중복방지 로드
    dedup = SupabaseDedup(sb_url, sb_key, cfg["dedup"]["max_cache_size"])
    dedup.load()

    # 기사 수집
    rss = fetch_rss_articles(cfg["sources"]["rss"])
    web = fetch_web_articles(cfg["sources"]["web"], cfg["keywords"])
    print(f"Fetched: RSS={len(rss)}, Web={len(web)}")

    # 필터링
    relevant = filter_relevant(rss + web, cfg["keywords"])
    print(f"Relevant: {len(relevant)}")

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
                tg_token, tg_chat, message_thread_id=2,
            )
        dedup.mark_sent(new_hashes)
        print("=== No new articles ===")
        return

    # Gemini 분석
    max_articles = cfg["analysis"]["max_articles"]
    model = cfg["analysis"]["model"]
    result = analyze(new_articles[:max_articles], gemini_key, model)
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

        send_telegram(header + body, tg_token, tg_chat, message_thread_id=2)

        # Directives 등록 (실패해도 봇 동작에 영향 없음)
        inserted = 0
        for idx, title, command, link in directive_items:
            note = f"AI뉴스봇 [{idx}]번 항목. 참고: {link}" if link else f"AI뉴스봇 [{idx}]번 항목"
            if insert_directive(f"[뉴스{idx}] {title}"[:30], command, note, sb_url, sb_key):
                inserted += 1
        if directive_items:
            print(f"Directives inserted: {inserted}/{len(directive_items)}")
    else:
        lines = [f"AI 업데이트 ({now})\n"]
        for art in new_articles[:10]:
            lines.append(f"- {art['title'][:60]}")
        send_telegram("\n".join(lines), tg_token, tg_chat, message_thread_id=2)

    # 중복방지 저장
    dedup.mark_sent(new_hashes)
    print("=== Run completed ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="daily", choices=["daily", "realtime"])
    args = parser.parse_args()
    run(args.mode)
