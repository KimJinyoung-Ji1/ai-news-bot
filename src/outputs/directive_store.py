# -*- coding: utf-8 -*-
"""작업지시(directive)를 로컬 JSON 파일에 저장 — 외부 DB(supabase) 의존 없음.

컴퓨터를 24시간 켜두는 단일 PC 환경에서는 ji1 supabase(RLS 제약으로 매일 실패)
대신 로컬 파일이 더 단순하고 안정적이다. Claude Code 가 이 파일을 직접 읽어
/directives 로 활용할 수 있다.
"""
import json
import os
import datetime


def save_directives(items: list, path: str) -> int:
    """directive 항목을 로컬 JSON 에 append (제목 기준 중복 skip, 최근 200건 유지).

    items: [(idx, title, command, link), ...]
    반환: 새로 추가된 건수
    """
    if not items:
        return 0

    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    existing = []
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            existing = []

    seen = {d.get("title") for d in existing}
    now = datetime.datetime.now().isoformat(timespec="seconds")
    added = 0
    for idx, title, command, link in items:
        if title in seen:
            continue
        existing.append({
            "date": now,
            "title": title,
            "command": command,
            "link": link,
            "done": False,
        })
        seen.add(title)
        added += 1

    existing = existing[-200:]  # 최근 200건만 보관

    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError as e:
        print(f"[Directive] 로컬 저장 오류: {e}")
        return 0
    return added
