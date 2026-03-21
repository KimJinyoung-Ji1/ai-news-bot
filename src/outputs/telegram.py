import requests
from bs4 import BeautifulSoup


def send_telegram(text: str, bot_token: str, chat_id: str) -> bool:
    if not bot_token or not chat_id:
        print("[Telegram] Token/ChatID not set")
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    if len(text) > 4000:
        text = text[:4000] + "\n\n... (잘림)"
    try:
        resp = requests.post(url, json={
            "chat_id": chat_id, "text": text,
            "parse_mode": "HTML", "disable_web_page_preview": True,
        }, timeout=10)
        if resp.status_code == 200:
            return True
        # HTML 실패 시 plain text 재시도
        resp2 = requests.post(url, json={
            "chat_id": chat_id,
            "text": BeautifulSoup(text, "html.parser").get_text(),
            "disable_web_page_preview": True,
        }, timeout=10)
        return resp2.status_code == 200
    except Exception as e:
        print(f"[Telegram] Error: {e}")
        return False
