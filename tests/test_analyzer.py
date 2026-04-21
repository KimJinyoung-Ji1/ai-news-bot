import json
import pytest
from unittest.mock import patch, MagicMock
from src.analyzer import (
    analyze, _fix_json_newlines, _postprocess_items,
    _analyze_claude, _analyze_gemini,
)


SAMPLE_ARTICLES = [
    {"source": "TestFeed", "title": "Claude 4 released", "link": "https://example.com/1", "summary": "Major update"},
    {"source": "OpenAI", "title": "GPT-5 announced", "link": "https://example.com/2", "summary": "New model"},
]

SAMPLE_RESULT = {
    "items": [
        {
            "title": "Claude 4 출시",
            "summary": "Anthropic이 Claude 4를 출시했습니다. 성능이 크게 향상됐습니다.",
            "apply": "API 호출 시 모델명 업데이트 필요",
            "link": "https://example.com/1",
            "directive": "src/analyzer.py의 CLAUDE_MODEL 상수를 claude-4로 변경",
        }
    ]
}


def _make_claude_response(body: dict):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "content": [{"text": json.dumps(body)}]
    }
    return resp


def _make_gemini_response(body: dict):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": json.dumps(body)}]}}]
    }
    return resp


class TestFixJsonNewlines:
    def test_no_change_outside_string(self):
        text = '{"key": "value"}'
        assert _fix_json_newlines(text) == text

    def test_escapes_literal_newline_in_string(self):
        text = '{"key": "line1\nline2"}'
        fixed = _fix_json_newlines(text)
        assert "\\n" in fixed

    def test_removes_carriage_return_in_string(self):
        text = '{"key": "line1\rline2"}'
        fixed = _fix_json_newlines(text)
        assert "\r" not in fixed

    def test_handles_escaped_backslash(self):
        text = '{"key": "path\\\\file"}'
        fixed = _fix_json_newlines(text)
        assert fixed == text


class TestPostprocessItems:
    def test_unescapes_newlines_in_fields(self):
        result = {"items": [{"title": "a\\nb", "summary": "x", "apply": "y", "directive": "z"}]}
        out = _postprocess_items(result)
        assert "\n" in out["items"][0]["title"]

    def test_handles_missing_items_key(self):
        result = {}
        out = _postprocess_items(result)
        assert out == {}

    def test_handles_non_string_field(self):
        result = {"items": [{"title": 123, "summary": None, "apply": "ok", "directive": ""}]}
        out = _postprocess_items(result)
        assert out["items"][0]["title"] == 123


class TestAnalyzeClaude:
    def test_returns_dict_on_success(self):
        resp = _make_claude_response(SAMPLE_RESULT)
        with patch("requests.post", return_value=resp):
            result = _analyze_claude("articles text", "prompt", "test-api-key")
        assert result is not None
        assert "items" in result

    def test_returns_none_on_client_error(self, capsys):
        resp = MagicMock()
        resp.status_code = 401
        resp.text = "Unauthorized"
        with patch("requests.post", return_value=resp):
            result = _analyze_claude("articles text", "prompt", "bad-key")
        assert result is None

    def test_returns_none_on_json_parse_error(self, capsys):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"content": [{"text": "not json at all"}]}
        with patch("requests.post", return_value=resp):
            result = _analyze_claude("articles text", "prompt", "key")
        assert result is None

    def test_parses_fenced_json(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "content": [{"text": f"```json\n{json.dumps(SAMPLE_RESULT)}\n```"}]
        }
        with patch("requests.post", return_value=resp):
            result = _analyze_claude("articles", "prompt", "key")
        assert result is not None

    def test_retries_on_500(self):
        fail = MagicMock()
        fail.status_code = 500
        ok = _make_claude_response(SAMPLE_RESULT)
        with patch("requests.post", side_effect=[fail, ok]):
            with patch("time.sleep"):
                result = _analyze_claude("articles", "prompt", "key")
        assert result is not None


class TestAnalyzeGemini:
    def test_returns_dict_on_success(self):
        resp = _make_gemini_response(SAMPLE_RESULT)
        with patch("requests.post", return_value=resp):
            result = _analyze_gemini("articles text", "prompt", "gemini-key", "gemini-2.5-flash")
        assert result is not None
        assert "items" in result

    def test_returns_none_on_client_error(self):
        resp = MagicMock()
        resp.status_code = 400
        with patch("requests.post", return_value=resp):
            result = _analyze_gemini("articles", "prompt", "key", "model")
        assert result is None

    def test_retries_on_503(self):
        fail = MagicMock()
        fail.status_code = 503
        ok = _make_gemini_response(SAMPLE_RESULT)
        with patch("requests.post", side_effect=[fail, ok]):
            with patch("time.sleep"):
                result = _analyze_gemini("articles", "prompt", "key", "model")
        assert result is not None


class TestAnalyze:
    def test_returns_empty_on_no_articles(self):
        result = analyze([], "key")
        assert result == {"items": []}

    def test_returns_empty_on_no_api_key(self):
        result = analyze(SAMPLE_ARTICLES, "")
        assert result == {"items": []}

    def test_uses_claude_first_when_anthropic_key_set(self):
        claude_resp = _make_claude_response(SAMPLE_RESULT)
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "claude-key"}):
            with patch("requests.post", return_value=claude_resp):
                result = analyze(SAMPLE_ARTICLES, "gemini-key")
        assert result["items"][0]["title"] == "Claude 4 출시"

    def test_falls_back_to_gemini_when_claude_fails(self):
        claude_fail = MagicMock()
        claude_fail.status_code = 500
        gemini_resp = _make_gemini_response(SAMPLE_RESULT)
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "claude-key"}):
            with patch("requests.post", side_effect=[claude_fail, claude_fail, claude_fail, gemini_resp]):
                with patch("time.sleep"):
                    result = analyze(SAMPLE_ARTICLES, "gemini-key")
        assert result is not None

    def test_uses_gemini_when_no_anthropic_key(self):
        gemini_resp = _make_gemini_response(SAMPLE_RESULT)
        with patch.dict("os.environ", {}, clear=True):
            env_without_key = {"PATH": ""}
            with patch.dict("os.environ", env_without_key):
                with patch("requests.post", return_value=gemini_resp):
                    result = analyze(SAMPLE_ARTICLES, "gemini-key")
        assert result is not None

    def test_builds_articles_text(self):
        captured_calls = []

        def mock_post(url, headers=None, json=None, timeout=None):
            if json and "messages" in json:
                captured_calls.append(json["messages"][0]["content"])
            return _make_claude_response(SAMPLE_RESULT)

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "key"}):
            with patch("requests.post", side_effect=mock_post):
                analyze(SAMPLE_ARTICLES, "gemini-key")

        assert len(captured_calls) > 0
        prompt = captured_calls[0]
        assert "Claude 4 released" in prompt
        assert "GPT-5 announced" in prompt
