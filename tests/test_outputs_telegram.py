import pytest
from unittest.mock import patch, MagicMock
from src.outputs.telegram import send_telegram


def _mock_ok():
    resp = MagicMock()
    resp.status_code = 200
    return resp


def _mock_fail(status=400, text="Bad Request"):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    return resp


def test_send_telegram_returns_true_on_success():
    with patch("requests.post", return_value=_mock_ok()):
        result = send_telegram("Hello", "token123", "chat456")
    assert result is True


def test_send_telegram_no_token(capsys):
    result = send_telegram("Hello", "", "chat456")
    assert result is False
    captured = capsys.readouterr()
    assert "not set" in captured.out


def test_send_telegram_no_chat(capsys):
    result = send_telegram("Hello", "token123", "")
    assert result is False
    captured = capsys.readouterr()
    assert "not set" in captured.out


def test_send_telegram_empty_chat_id_returns_false_no_send():
    """TELEGRAM_CHAT_ID 빈 값 → send 호출 없이 False 반환 (PM 1:1 송신 차단 가드)."""
    import unittest.mock as mock
    with mock.patch("requests.post") as mock_post:
        result = send_telegram("AI 뉴스 메시지", "some_bot_token", "")
    assert result is False
    mock_post.assert_not_called()


def test_send_telegram_truncates_long_text():
    long_text = "A" * 5000
    captured_payloads = []

    def mock_post(url, json=None, timeout=None):
        captured_payloads.append(json)
        return _mock_ok()

    with patch("requests.post", side_effect=mock_post):
        send_telegram(long_text, "token", "chat")

    assert len(captured_payloads[0]["text"]) <= 4020  # 4000 + truncation suffix


def test_send_telegram_with_thread_id():
    captured_payloads = []

    def mock_post(url, json=None, timeout=None):
        captured_payloads.append(json)
        return _mock_ok()

    with patch("requests.post", side_effect=mock_post):
        send_telegram("Hello", "token", "chat", message_thread_id=99)

    assert captured_payloads[0]["message_thread_id"] == 99


def test_send_telegram_no_thread_id():
    captured_payloads = []

    def mock_post(url, json=None, timeout=None):
        captured_payloads.append(json)
        return _mock_ok()

    with patch("requests.post", side_effect=mock_post):
        send_telegram("Hello", "token", "chat", message_thread_id=None)

    assert "message_thread_id" not in captured_payloads[0]


# AUD-08 (2026-06-12): parse_mode=HTML + plaintext 폴백 이중 발송 제거 —
# plain text 1회 발송으로 단순화. 기존 HTML 폴백 테스트 2건을 대체.
def test_send_telegram_single_plain_attempt_no_fallback():
    """실패 시 폴백 재발송 없이 1회 시도 후 False."""
    with patch("requests.post", return_value=_mock_fail(400, "Bad Request")) as mock_post:
        result = send_telegram("Hello", "token", "chat")
    assert result is False
    assert mock_post.call_count == 1


def test_send_telegram_payload_is_plain_text():
    """payload 에 parse_mode 없음 (HTML 미사용)."""
    captured_payloads = []

    def mock_post(url, json=None, timeout=None):
        captured_payloads.append(json)
        return _mock_ok()

    with patch("requests.post", side_effect=mock_post):
        result = send_telegram("Hello", "token", "chat")
    assert result is True
    assert "parse_mode" not in captured_payloads[0]


def test_send_telegram_exception(capsys):
    with patch("requests.post", side_effect=Exception("network error")):
        result = send_telegram("Hello", "token", "chat")
    assert result is False
    captured = capsys.readouterr()
    assert "Error" in captured.out


def test_url_preview_enabled():
    """disable_web_page_preview must be False to allow link previews."""
    captured_payloads = []

    def mock_post(url, json=None, timeout=None):
        captured_payloads.append(json)
        return _mock_ok()

    with patch("requests.post", side_effect=mock_post):
        send_telegram("https://example.com/news", "token", "chat")

    assert captured_payloads[0].get("disable_web_page_preview") is False
