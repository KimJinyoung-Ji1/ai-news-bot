import pytest
from unittest.mock import patch, MagicMock
from src.outputs.supabase import insert_directive


def _mock_ok():
    resp = MagicMock()
    resp.status_code = 201
    return resp


def _mock_fail(status=500):
    resp = MagicMock()
    resp.status_code = status
    resp.text = "Server Error"
    return resp


def test_insert_directive_returns_true_on_success():
    with patch("requests.post", return_value=_mock_ok()):
        result = insert_directive("Title", "command", "note", "https://sb.co", "anon-key")
    assert result is True


def test_insert_directive_no_anon_key(capsys):
    result = insert_directive("Title", "command", "note", "https://sb.co", "")
    assert result is False
    captured = capsys.readouterr()
    assert "SKIP" in captured.out


def test_insert_directive_fails_on_non_200(capsys):
    with patch("requests.post", return_value=_mock_fail(500)):
        result = insert_directive("Title", "command", "note", "https://sb.co", "key")
    assert result is False
    captured = capsys.readouterr()
    assert "FAIL" in captured.out


def test_insert_directive_status_200_also_ok():
    resp = MagicMock()
    resp.status_code = 200
    with patch("requests.post", return_value=resp):
        result = insert_directive("Title", "command", "note", "https://sb.co", "key")
    assert result is True


def test_insert_directive_exception_returns_false(capsys):
    with patch("requests.post", side_effect=Exception("net error")):
        result = insert_directive("Title", "command", "note", "https://sb.co", "key")
    assert result is False
    captured = capsys.readouterr()
    assert "Error" in captured.out


def test_insert_directive_payload_structure():
    captured_payloads = []

    def mock_post(url, headers=None, json=None, timeout=None):
        captured_payloads.append(json)
        return _mock_ok()

    with patch("requests.post", side_effect=mock_post):
        insert_directive("Test Title", "some command", "a note", "https://sb.co", "key")

    payload = captured_payloads[0]
    assert payload["category"] == "directive"
    assert payload["title"] == "Test Title"
    assert payload["content"] == "some command"
    assert payload["source"] == "ai-news-bot"
    assert payload["is_active"] is True
