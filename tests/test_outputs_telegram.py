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


def test_send_telegram_html_fail_retries_plaintext():
    responses = [_mock_fail(400, "Bad HTML"), _mock_ok()]
    with patch("requests.post", side_effect=responses):
        result = send_telegram("Hello", "token", "chat")
    assert result is True


def test_send_telegram_both_fail():
    responses = [_mock_fail(400, "Bad HTML"), _mock_fail(400, "Also bad")]
    with patch("requests.post", side_effect=responses):
        result = send_telegram("Hello", "token", "chat")
    assert result is False


def test_send_telegram_exception(capsys):
    with patch("requests.post", side_effect=Exception("network error")):
        result = send_telegram("Hello", "token", "chat")
    assert result is False
    captured = capsys.readouterr()
    assert "Error" in captured.out
