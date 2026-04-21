import os
import pytest
from unittest.mock import patch, mock_open
from src.config import load_config, get_env


SAMPLE_CONFIG = """
supabase:
  url: https://example.supabase.co
  ji1_url: https://ji1.supabase.co
dedup:
  max_cache_size: 500
sources:
  rss:
    - name: TestFeed
      url: https://example.com/rss
  web: []
keywords:
  - claude
  - gpt
analysis:
  max_articles: 10
  max_items: 6
  model: gemini-2.5-flash
telegram:
  message_thread_id: 42
"""


def test_load_config_returns_dict(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yml"
    cfg_file.write_text(SAMPLE_CONFIG, encoding="utf-8")
    monkeypatch.setattr("src.config.CONFIG_FILE", cfg_file)
    cfg = load_config()
    assert isinstance(cfg, dict)
    assert cfg["supabase"]["url"] == "https://example.supabase.co"
    assert cfg["dedup"]["max_cache_size"] == 500


def test_load_config_sources(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yml"
    cfg_file.write_text(SAMPLE_CONFIG, encoding="utf-8")
    monkeypatch.setattr("src.config.CONFIG_FILE", cfg_file)
    cfg = load_config()
    assert cfg["sources"]["rss"][0]["name"] == "TestFeed"
    assert cfg["keywords"] == ["claude", "gpt"]


def test_get_env_present():
    with patch.dict(os.environ, {"MY_TEST_VAR": "hello"}):
        assert get_env("MY_TEST_VAR") == "hello"


def test_get_env_optional_missing():
    env = os.environ.copy()
    env.pop("OPTIONAL_VAR", None)
    with patch.dict(os.environ, env, clear=True):
        result = get_env("OPTIONAL_VAR", required=False)
    assert result == ""


def test_get_env_required_missing():
    env = os.environ.copy()
    env.pop("REQUIRED_VAR", None)
    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(RuntimeError, match="REQUIRED_VAR"):
            get_env("REQUIRED_VAR", required=True)
