import requests
from bs4 import BeautifulSoup


def send_telegram(text: str, bot_token: str, chat_id: str, message_thread_id: int = None) -> bool:
    if not bot_token or not chat_id:
        print("[Telegram] Token/ChatID not set")
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    if len(text) > 4000:
        text = text[:4000] + "\n\n... (잘림)"
    try:
        payload = {
            "chat_id": chat_id, "text": text,
            "parse_mode": "HTML", "disable_web_page_preview": True,
        }
        if message_thread_id is not None:
            payload["message_thread_id"] = message_thread_id
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code == 200:
            print(f"[Telegram] OK (thread={message_thread_id})")
            return True
        print(f"[Telegram] HTML failed ({resp.status_code}): {resp.text[:200]}")
        # HTML 실패 시 plain text 재시도
        payload2 = {
            "chat_id": chat_id,
            "text": BeautifulSoup(text, "html.parser").get_text(),
            "disable_web_page_preview": True,
        }
        if message_thread_id is not None:
            payload2["message_thread_id"] = message_thread_id
        resp2 = requests.post(url, json=payload2, timeout=15)
        if resp2.status_code == 200:
            print(f"[Telegram] OK (plaintext fallback)")
            return True
        print(f"[Telegram] Plaintext also failed ({resp2.status_code}): {resp2.text[:200]}")
        return False
    except Exception as e:
        print(f"[Telegram] Error: {e}")
        return False
