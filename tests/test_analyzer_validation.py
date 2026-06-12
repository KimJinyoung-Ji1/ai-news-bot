"""Tests for _validate_item — pure validation, no Anthropic API calls."""
import pytest
from src.analyzer import _validate_item


def _make_item(**overrides):
    base = {
        "title": "Claude Haiku 4.5 API 응답 속도 40% 향상",
        "summary": "Anthropic이 Haiku 4.5 모델의 응답 속도를 40% 개선했다고 2026년 5월 발표했다. 기존 대비 토큰당 처리 시간이 절반으로 줄었으며 비용도 20% 절감됐다. 우리 mongol-pm 채팅 응답 체감 속도에 즉시 반영 가능하다. 다음 배포 사이클에 모델 상수 업데이트 권장.",
        "apply": "[YES] mongol-pm/src/services/chat.ts: CLAUDE_MODEL 상수를 claude-haiku-4-5로 업데이트하고 retry backoff 추가",
        "directive": "mongol-pm/src/services/chat.ts의 CLAUDE_MODEL 상수를 claude-haiku-4-5로 변경하라",
        "link": "https://anthropic.com/news/haiku-4-5",
    }
    base.update(overrides)
    return base


class TestValidItemYes:
    def test_valid_yes_apply_passes(self):
        item = _make_item()
        ok, err = _validate_item(item)
        assert ok, f"Expected pass, got: {err}"

    def test_valid_no_apply_passes(self):
        item = _make_item(
            apply="[NO] 미국 한정 Plaid 연동, 우리 스택 무관. 차용 가능 패턴: HybridLlm api_guardrail.py에 PII 마스킹 강화",
            directive="",
        )
        ok, err = _validate_item(item)
        assert ok, f"Expected pass, got: {err}"

    def test_skip_apply_passes(self):
        item = _make_item(
            apply="[SKIP] 가십성 기업 인수 소식, 기술·운영 함의 없음 — 반복 보도자료성",
            directive="",
        )
        ok, err = _validate_item(item)
        assert ok, f"Expected pass, got: {err}"

    def test_directive_empty_ok(self):
        item = _make_item(
            apply="[NO] 미국 한정 서비스라 우리 스택에 직접 적용 불가. 차용 가능 패턴: Supabase Edge Functions 인증 로직에 rate limiting 추가",
            directive="",
        )
        ok, err = _validate_item(item)
        assert ok, f"Expected pass, got: {err}"

    def test_directive_command_passes(self):
        item = _make_item(
            directive="HybridLlm api_guardrail.py에 PII 마스킹 로직 추가하라",
        )
        ok, err = _validate_item(item)
        assert ok, f"Expected pass, got: {err}"


class TestValidItemFailures:
    def test_apply_missing_prefix_fails(self):
        item = _make_item(apply="참고 수준으로 확인하면 좋을 것 같은 내용입니다")
        ok, err = _validate_item(item)
        assert not ok
        assert "[YES]/[NO]/[SKIP]" in err

    def test_apply_too_short_fails(self):
        item = _make_item(apply="[YES] X")
        ok, err = _validate_item(item)
        assert not ok
        assert "too short" in err

    def test_summary_too_short_fails(self):
        # Under new threshold: min 100 chars
        item = _make_item(summary="짧음")
        ok, err = _validate_item(item)
        assert not ok
        assert "too short" in err

    def test_summary_too_long_fails(self):
        # Over threshold: max 600 chars
        long_summary = "가" * 601
        item = _make_item(summary=long_summary)
        ok, err = _validate_item(item)
        assert not ok
        assert "too long" in err

    def test_summary_exactly_150_passes(self):
        # Exactly at minimum boundary (min 150 chars)
        summary_150 = (
            "Anthropic이 Claude Haiku 4.5 모델의 응답 속도를 40% 개선했다고 2026년 5월 발표했다. "
            "기존 대비 토큰당 처리 시간이 절반으로 줄었으며 비용도 20% 절감됐다. "
            "mongol-pm 채팅 응답 체감 속도에 즉시 반영 가능하며 다음 배포 사이클에 모델 상수 업데이트를 권장한다."
        )
        assert len(summary_150) >= 150, f"테스트 데이터가 너무 짧음: {len(summary_150)}자"
        item = _make_item(summary=summary_150)
        ok, err = _validate_item(item)
        assert ok, f"Expected pass, got: {err}"

    def test_directive_not_command_fails(self):
        item = _make_item(directive="고려해볼 수 있는 내용이다")
        ok, err = _validate_item(item)
        assert not ok
        assert "command form" in err

    def test_missing_field_fails(self):
        item = _make_item()
        del item["link"]
        ok, err = _validate_item(item)
        assert not ok
        assert "missing field" in err
