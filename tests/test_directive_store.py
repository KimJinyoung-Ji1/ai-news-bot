# -*- coding: utf-8 -*-
"""로컬 directive 저장(directive_store) 단위 테스트 — supabase 미사용."""
import json
from src.outputs.directive_store import save_directives


def _read(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def test_empty_returns_zero(tmp_path):
    assert save_directives([], str(tmp_path / "d.json")) == 0


def test_saves_and_persists(tmp_path):
    p = str(tmp_path / "d.json")
    n = save_directives([(1, "뉴스1 제목", "검토하라", "https://a.com")], p)
    assert n == 1
    data = _read(p)
    assert len(data) == 1
    assert data[0]["title"] == "뉴스1 제목"
    assert data[0]["command"] == "검토하라"
    assert data[0]["done"] is False
    assert "date" in data[0]


def test_dedup_by_title(tmp_path):
    p = str(tmp_path / "d.json")
    save_directives([(1, "같은제목", "c1", "l1")], p)
    n = save_directives([(1, "같은제목", "c2", "l2"), (2, "새제목", "c3", "l3")], p)
    assert n == 1  # '같은제목'은 skip, '새제목'만 추가
    data = _read(p)
    assert len(data) == 2


def test_caps_at_200(tmp_path):
    p = str(tmp_path / "d.json")
    save_directives([(i, f"제목{i}", "c", "l") for i in range(250)], p)
    data = _read(p)
    assert len(data) == 200
    assert any(d["title"] == "제목249" for d in data)   # 최근 것 유지
    assert all(d["title"] != "제목0" for d in data)      # 오래된 것 제거


def test_corrupt_file_recovers(tmp_path):
    p = tmp_path / "d.json"
    p.write_text("{ broken json", encoding="utf-8")
    n = save_directives([(1, "복구테스트", "확인하라", "l")], str(p))
    assert n == 1
    assert len(_read(str(p))) == 1
