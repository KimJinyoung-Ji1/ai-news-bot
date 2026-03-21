import requests


def insert_directive(title: str, command: str, note: str,
                     supabase_url: str, anon_key: str) -> bool:
    try:
        resp = requests.post(
            f"{supabase_url}/rest/v1/directives",
            headers={
                "apikey": anon_key,
                "Authorization": f"Bearer {anon_key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            json={
                "title": title,
                "command": command,
                "target_project": "all",
                "priority": "low",
                "status": "pending",
                "source": "ai-news-bot",
                "created_by": 5,
                "sort_order": 90,
                "note": note,
            },
            timeout=10,
        )
        ok = resp.status_code in (200, 201)
        if not ok:
            print(f"[Directive] FAIL ({resp.status_code}): {resp.text[:100]}")
        return ok
    except Exception as e:
        print(f"[Directive] Error: {e}")
        return False
