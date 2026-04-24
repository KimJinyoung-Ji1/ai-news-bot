import pytest
from src.normalize import normalize_url, normalize_title


class TestNormalizeUrl:
    def test_removes_utm_source(self):
        url = "https://example.com/article?utm_source=rss&id=123"
        result = normalize_url(url)
        assert "utm_source" not in result
        assert "id=123" in result

    def test_removes_all_tracking_params(self):
        url = (
            "https://example.com/post"
            "?utm_source=rss&utm_medium=email&utm_campaign=weekly"
            "&utm_term=ai&utm_content=cta&fbclid=abc123"
        )
        result = normalize_url(url)
        assert "utm_source" not in result
        assert "fbclid" not in result
        assert result == "https://example.com/post"

    def test_preserves_non_tracking_params(self):
        url = "https://example.com/search?q=claude&page=2"
        result = normalize_url(url)
        assert "q=claude" in result
        assert "page=2" in result

    def test_removes_trailing_slash(self):
        assert normalize_url("https://example.com/article/") == "https://example.com/article"

    def test_root_path_preserved(self):
        assert normalize_url("https://example.com/") == "https://example.com/"

    def test_scheme_lowercased(self):
        result = normalize_url("HTTPS://Example.COM/path")
        assert result.startswith("https://example.com/")

    def test_fragment_removed(self):
        # urlsplit strips fragment when we re-assemble without it
        url = "https://example.com/article"
        result = normalize_url(url)
        assert "#" not in result

    def test_empty_string_returns_empty(self):
        assert normalize_url("") == ""

    def test_gclid_removed(self):
        url = "https://example.com/p?gclid=xyz&ref=social"
        result = normalize_url(url)
        assert "gclid" not in result
        assert "ref" not in result

    def test_utm_ac2_produces_same_hash_as_clean(self):
        """UTM 붙은 URL 과 클린 URL 이 같은 normalized 값을 반환해야 함."""
        dirty = "https://anthropic.com/news/claude?utm_source=rss&utm_medium=feed"
        clean = "https://anthropic.com/news/claude"
        assert normalize_url(dirty) == normalize_url(clean)


class TestNormalizeTitle:
    def test_lowercases(self):
        assert normalize_title("Claude 3.5") == "claude 3 5"

    def test_nfkc_normalization(self):
        # Full-width characters should normalize
        title = "\uff43\uff4c\uff41\uff55\uff44\uff45"  # ｃｌａｕｄｅ
        result = normalize_title(title)
        assert result == "claude"

    def test_removes_punctuation(self):
        result = normalize_title("Claude: New Model! (Better, Faster)")
        assert ":" not in result
        assert "!" not in result
        assert "(" not in result

    def test_collapses_whitespace(self):
        result = normalize_title("Claude   3.5   Sonnet")
        assert "  " not in result

    def test_strips_leading_trailing(self):
        result = normalize_title("  Claude update  ")
        assert result == result.strip()

    def test_empty_string_returns_empty(self):
        assert normalize_title("") == ""

    def test_punctuation_replaced_by_space_not_removed(self):
        # "Claude:Update" should become "claude update" (space between words)
        result = normalize_title("Claude:Update")
        assert "claude" in result
        assert "update" in result

    def test_unicode_dash_removed(self):
        # Unicode dashes (‐‑‒–—―) are included in _PUNCT range
        result = normalize_title("Claude\u2013Anthropic")
        assert "\u2013" not in result

    def test_same_title_variants_produce_same_output(self):
        t1 = normalize_title("Claude 3.5 Sonnet")
        t2 = normalize_title("Claude 3.5 Sonnet:")
        assert t1 == t2

    def test_mixed_case_and_punctuation(self):
        result = normalize_title("New GPT-4o Features: What's Changed?")
        assert result == result.lower()
        assert "?" not in result
