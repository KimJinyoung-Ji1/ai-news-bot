import requests

# 텔레그램 1메시지 한도(4096) 아래 안전 마진
_MAX_LEN = 4000
# main.py 의 항목 구분선과 동일 — 이 경계로만 분할한다 (AUD-07)
_ITEM_SEP = "\n" + "─" * 12 + "\n"


def _split_message(text: str) -> list[str]:
    """4000자 초과 메시지를 항목 구분선 경계로 분할.

    - 구분선이 없는 초과 세그먼트만 최후수단으로 절단 ("... (잘림)")
    - 한 파트 안에서는 구분선을 보존해 항목 포맷 유지
    """
    if len(text) <= _MAX_LEN:
        return [text]
    parts = []
    current = ""
    for seg in text.split(_ITEM_SEP):
        if len(seg) > _MAX_LEN:
            seg = seg[:_MAX_LEN] + "\n\n... (잘림)"
        candidate = seg if not current else current + _ITEM_SEP + seg
        if len(candidate) <= _MAX_LEN:
            current = candidate
        else:
            if current:
                parts.append(current)
            current = seg
    if current:
        parts.append(current)
    return parts


def send_telegram(text: str, bot_token: str, chat_id: str, message_thread_id: int = None) -> bool:
    """plain text 발송 (AUD-08: parse_mode 미사용 — HTML 태그를 쓰지 않으므로 1회 발송).

    4000자 초과 시 항목 구분선 경계로 분할 발송 (AUD-07).
    모든 파트에 동일 message_thread_id, 파트 2+ 는 헤더 없이 (본문 연속).
    """
    if not bot_token or not chat_id:
        print("[Telegram] Token/ChatID not set")
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    parts = _split_message(text)
    try:
        for idx, part in enumerate(parts, 1):
            payload = {
                "chat_id": chat_id, "text": part,
                "disable_web_page_preview": False,
            }
            if message_thread_id is not None:
                payload["message_thread_id"] = message_thread_id
            resp = requests.post(url, json=payload, timeout=15)
            if resp.status_code != 200:
                print(f"[Telegram] Send failed part {idx}/{len(parts)}"
                      f" ({resp.status_code}): {resp.text[:200]}")
                return False
        print(f"[Telegram] OK ({len(parts)} part(s), thread={message_thread_id})")
        return True
    except Exception as e:
        print(f"[Telegram] Error: {e}")
        return False
