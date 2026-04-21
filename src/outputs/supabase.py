import requests


def insert_directive(title: str, command: str, note: str,
                     supabase_url: str, anon_key: str) -> bool:
    """AI 뉴스봇 directive를 logs.shared_context에 등록 (best-effort)"""
    if not anon_key:
        print("[Directive] SKIP: no ji1 key")
        return False
    try:
        resp = requests.post(
            f"{supabase_url}/rest/v1/shared_context",
            headers={
                "apikey": anon_key,
                "Authorization": f"Bearer {anon_key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
                "Accept-Profile": "logs",
                "Content-Profile": "logs",
            },
            json={
                "category": "directive",
                "title": title,
                "content": command,
                "project": "all",
                "source": "ai-news-bot",
                "is_active": True,
                "note": note,
            },
            timeout=10,
        )
        ok = resp.status_code in (200, 201)
        if ok:
            print(f"[Directive] OK: {title[:40]}")
        else:
            print(f"[Directive] FAIL ({resp.status_code}): {resp.text[:200]}")
        return ok
    except Exception as e:
        print(f"[Directive] Error (non-fatal): {e}")
        return False
