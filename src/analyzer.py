import json
import os
import requests


CLAUDE_MODEL = "claude-sonnet-4-6"  # 2026-05-28 PM 지시 "haiku 말고 sonnet" — 인사이트 품질 강화

PROMPT_TEMPLATE = """너는 AI 도구·방법론을 적극 활용하는 사업가에게 매일 인사이트를 전달하는 큐레이터다.

[독자 프로필 — 2026-05-28 업데이트]
- 인테리어·전시 시공, 정부 지원사업, 몽골 합작법인을 운영하면서 동시에 Claude Code·MCP·자동화 봇을 직접 운영하는 사업가
- 비개발자지만 AI 도구·자동화·워크플로우는 실 도입 적극적 — 도입 가치 있으면 즉시 시도
- 원하는 것: **"오늘만 가치 있는 신선한 인사이트"** — 어제·그제와 다른 것. 적용 가능한 구체적 방법론. 신기술이라도 "어떻게 쓸지 한 줄"이 보이면 OK
- 싫어하는 것: **"X 출시: 기능 향상"** 같은 보도자료 톤. 같은 회사 모델 출시 매일 반복. 표면적 사실 나열만 하고 적용 방법 없음

[선별 기준 — 우선순위]
1. **신기술·신도구·신 MCP·신 라이브러리** — 어제까지 없던 것. 도입 가치 있으면 셋업 1줄 포함
2. **적용 가능한 방법론·워크플로우** — Claude Code 패턴, MCP 활용법, 프롬프트 기법, 자동화 셋업, RAG 패턴 등
3. **실 운영 사례·벤치마크** — 다른 회사가 어떻게 도입했는지, 비용·성능 수치
4. **시장·정책·가격 변화** — 사업 영향 큰 것
5. **모델 출시·릴리즈는 최대 1건** — Anthropic Opus·OpenAI GPT·Google Gemini 같은 메이저 모델 출시는 그날 1건만 (가장 임팩트 큰 1건). 나머지는 제외하거나 점수 낮춤

[다양성·신선도 강제 — 매우 중요]
- **카테고리 균형**: 최종 items 안에 (a) 신도구·MCP·라이브러리 (b) 방법론·워크플로우 (c) 운영사례·벤치마크 (d) 모델·릴리즈 (e) 시장·정책 중 **최소 3개 카테고리** 포함
- **한 회사 2건 초과 금지**: Anthropic 뉴스 3건이면 1건만 통과 (가장 임팩트). OpenAI·구글도 동일
- **"매일 똑같은 보도자료" 금지**: 점수 낮추거나 [SKIP]
- **신선도 신호**: 어제·이번주 보낸 적 있는 주제(Opus 출시·Claude Code 업데이트·GPT 출시 등 반복 주제)는 새로운 정보가 더 있을 때만 포함. 단순 후속 보도면 점수 50 이하

[JSON 형식 - 이 형식만 출력, 다른 텍스트 금지. score는 1~100 정수, 신선도·적용가능성·구체성 기준 — 보도자료성/반복주제 60 이하, 신도구+셋업가이드 80+, 검증된 운영사례 85+, 메이저 모델출시 70~85]
```json
{{
  "items": [
    {{
      "title": "한글 제목 — 무슨 일이 일어났는지 + 핵심 차별점",
      "title_kr": "(title 과 동일)",
      "summary": "3~5문장 (150~600자). 일상어 + 필요 시 도구·기술명. 구성: 1) 무슨 일인가 (회사·시점·핵심) 2) 어제·기존과 무엇이 다른가 (차별 포인트) 3) 어떻게 적용하는가 (셋업 1줄 또는 워크플로우 패턴) 4) 사업·운영에 줄 영향",
      "summary_kr": "핵심 사실 1줄 (40자 이내, 제품·회사명·핵심 차별 포함)",
      "insight_kr": "구체적 적용 방법·활용 1줄 (50자 이내, 어떻게 쓸지 또는 무엇을 시도할지)",
      "category": "신도구·MCP / 방법론·워크플로우 / 운영사례·벤치마크 / 모델·릴리즈 / 시장·정책 중 하나",
      "score": 75,
      "apply": "[YES]/[NO]/[SKIP] 로 시작 (아래 규칙). 최소 40자.",
      "link": "원문 URL",
      "directive": "사업상 바로 할 행동이 있을 때만 명령형 1줄. 없으면 빈 문자열 \"\""
    }}
  ]
}}
```

[apply 필드 형식 규칙 — 구체적 적용 방법 강제]
- [YES]: "[YES] {{구체적 적용 방법 1~2줄 — 어떤 작업·어떤 워크플로우에 어떻게 쓸지. 셋업 키워드 1개 이상 포함}}"
  예: "[YES] mongol-pm DB 검색에 RAG 도입 — BGE-m3-ko 임베딩 + LanceDB 로컬 운영. company_rag 패턴 그대로 재사용 가능"
  예: "[YES] Claude Code 워크플로우에 새 MCP 통합 — settings.json 에 등록 후 ToolSearch 로 스키마 로드 시 즉시 활용"
- [NO]: "[NO] {{우리 운영 환경과 무관한 이유 1줄}}. 다만 {{알아둘 점·향후 적용 가능성 1줄}}"
- [SKIP]: "[SKIP] {{1줄 이유 — 보도자료성/반복주제/실효 X}}"
금지 표현: "참고 수준", "흥미로운 소식", "참고할 만하다", "트렌드를 시사", "고려해볼 수 있다"

[directive 필드 규칙]
사업상 바로 할 행동이 있을 때만 명령형 1줄 (검토하라/도입하라/조사하라/셋업하라 등). 없으면 빈 문자열 "".
구체성 강제: "X 도구를 ~에 도입 검토하라" 처럼 도구명·적용처 포함.

[summary_kr / insight_kr 규칙 — 길이 늘림]
- summary_kr: 핵심 사실 + 차별 포인트. 제품·회사명 포함. 40자 이내.
- insight_kr: **구체적 적용 방법 1줄**. 도구·셋업 키워드 1개 이상 포함. 50자 이내.
  예 (좋음): "Claude Code settings.json에 MCP 추가, ToolSearch로 호출"
  예 (나쁨 — 추상적): "워크플로우 개선에 활용 가능" (금지)
- 텔레그램에서 5초 안에 읽을 요약. 짧되 구체적.

[품질 규칙 — 반드시 지켜]
- 모든 내용 한국어. 영어 원문 그대로 쓰지 마.
- 개발 용어는 일상어로 풀거나 도구 이름 그대로 쓰되 1줄 설명 곁들임
- 이모지 절대 금지 — 본문/요약/시사점 어디에도 금지 (🔴·⚡·★ 등 일체)
- **갯수 채우려 보도자료 끼우지 말 것** — 진짜 알찰 내용 1개면 1개만, 2개면 2개만 (최대 6개). 점수 70 미만 항목은 제외 권장
- 과장·억지 연결 금지. 우리 환경과 무관하면 [NO]/[SKIP] + 낮은 점수
- 특정 회사 편중 금지 — Anthropic/OpenAI/Google Gemini/국내 골고루 (공식 블로그 출처는 weight 우선)
- **"매일 똑같은 모델 출시 뉴스" 금지** — 메이저 모델 출시는 그날 1건만, 나머지는 후속·정책·도구·방법론으로 채움
- **공식 출처 우선** — Google Gemini Blog, OpenAI Blog, Anthropic News/Engineering/Research 등 1차 공식 발표는 redditt·트위터 2차 인용보다 우선

[★ 결론 반대 해석 절대 차단 — PM 사고 2026-06-07 13177~13179]
- 제목·summary에 "X가 Y를 했다", "X가 늘었다/줄었다", "X 가 사기다", "X 가 부정확하다" 같은 단정형 주장을 쓸 때는 **원문 description에 동일 단정이 명시되어 있어야 한다**.
- 원문이 "X가 Y했는가?" 같은 의문문이거나 "주장이 있다", "논쟁 중", "데이터로 반박" 같은 표현이면 **결론 방향을 본인이 추측하지 말고** 의문문·중립 톤으로 그대로 옮긴다.
- 학술·통계 분석 글(p-value, 비교 검정, A/B 테스트)에서는 **저자가 어느 쪽을 지지·반박하는지 명확하지 않으면 SKIP 처리**한다.
- 사고 사례 (재발 방지): "Did Claude Increase Bugs in rsync?" 글이 본문에서 p=46%로 "Claude가 버그 늘렸다는 주장은 통계적 증거 없음"으로 반박했는데, 봇이 제목만 보고 "Claude가 rsync 버그를 늘렸다는 분석"이라고 결론 반대로 발송함. 제목이 의문문일 때는 반드시 SKIP 또는 의문문 그대로 보존.

[★ 임의 도구·기술명 삽입 금지 — PM 사고 2026-06-07 13177~13179]
- directive·summary·insight에 **원문에 없는 구체 도구명·라이브러리명·제품명을 임의로 끌어와 적지 말 것**.
- 예 (사고): 월마트 Code Puppy 기사에는 "LiteLLM"이라는 단어가 없는데, 봇이 "여러 모델 사용"이라는 일반 표현에서 LiteLLM을 임의로 유추해 directive에 삽입함.
- 원문에 명시된 도구명만 사용. 없으면 "여러 모델 라우팅 도구" 같은 일반 표현으로 두고 구체 도구는 사용자에게 검토 위임.

[★ 출시·릴리즈 단계 정확 표기 — PM 사고 2026-06-07 13177~13179]
- "정식 출시"는 정확히 모든 사용자 대상 General Availability일 때만 사용.
- 원문이 "rolling out", "롤아웃 시작", "일부 사용자 대상" 등이면 **"롤아웃 시작"·"부분 출시"** 같이 단계 정확히 표기.
- "출시 예정", "발표"와 "정식 출시" 혼동 금지.
- 예 (사고): OpenAI Lockdown Mode가 "롤아웃 진행 중"인데 봇이 "정식 출시"로 과장함.

기사 목록:
{articles_text}"""


def _validate_item(item: dict) -> tuple[bool, str]:
    """Validate analyzer output item. Returns (ok, error_msg)."""
    required = ["title", "summary", "apply", "directive", "link"]
    for f in required:
        if f not in item:
            return False, f"missing field: {f}"

    # apply must start with [YES], [NO], or [SKIP]
    apply = item["apply"].strip()
    if not (apply.startswith("[YES]") or apply.startswith("[NO]") or apply.startswith("[SKIP]")):
        return False, f"apply must start with [YES]/[NO]/[SKIP], got: {apply[:40]}"
    if len(apply) < 40:
        return False, f"apply too short ({len(apply)} chars), min 40 (구체적 적용 방법 강제)"

    # summary: 3~5 sentences (150~600 chars) — 2026-05-28 PM 지시 인사이트 강화
    summary = item["summary"].strip()
    if len(summary) < 150:
        return False, f"summary too short ({len(summary)} chars), min 150 (차별 포인트·적용 방법 포함 강제)"
    if len(summary) > 600:
        return False, f"summary too long ({len(summary)} chars), max 600"

    # directive: empty OR contains Korean command keyword
    directive = item["directive"].strip()
    if directive:
        command_keywords = ["추가", "검토", "변경", "삭제", "구현", "도입", "갱신", "수정", "테스트", "확인", "조사", "하라", "시오"]
        if not any(kw in directive for kw in command_keywords):
            return False, f"directive must be command form (Korean verb) or empty, got: {directive[:60]}"

    return True, ""


def _validate_and_filter_items(result: dict, label: str) -> dict:
    """Validate each item. directive 형식만 불량이면 뉴스는 살리고 directive만 비운다
    (부가 필드 때문에 핵심 뉴스를 통째로 버리지 않도록)."""
    valid_items = []
    for i, item in enumerate(result.get("items", [])):
        ok, err = _validate_item(item)
        if ok:
            valid_items.append(item)
            continue
        # summary 길이 초과면 600자로 잘라서 유지 (살짝 넘는다고 통째 버리지 않음)
        if "summary too long" in err:
            item["summary"] = item["summary"][:597].rstrip() + "..."
            ok2, _ = _validate_item(item)
            if ok2:
                valid_items.append(item)
                print(f"[Analyzer/{label}] Item {i}: summary 길이 초과 -> 단축 후 유지")
                continue
        # directive 형식 문제일 뿐이면 directive만 비우고 재검증해서 살린다
        if "directive" in err and item.get("directive", "").strip():
            item["directive"] = ""
            ok2, _ = _validate_item(item)
            if ok2:
                valid_items.append(item)
                print(f"[Analyzer/{label}] Item {i}: directive 형식 불량 -> directive 제거 후 유지")
                continue
        print(f"[Analyzer/{label}] Item {i} dropped: {err}")
    result["items"] = valid_items
    return result


def _fix_json_newlines(text: str) -> str:
    """JSON 문자열 내부의 리터럴 줄바꿈을 이스케이프 처리"""
    fixed = []
    in_string = False
    escape_next = False
    for ch in text:
        if escape_next:
            fixed.append(ch)
            escape_next = False
            continue
        if ch == '\\':
            escape_next = True
            fixed.append(ch)
            continue
        if ch == '"':
            in_string = not in_string
            fixed.append(ch)
            continue
        if in_string and ch == '\n':
            fixed.append('\\n')
            continue
        if in_string and ch == '\r':
            continue
        fixed.append(ch)
    return ''.join(fixed)


def _postprocess_items(result: dict) -> dict:
    for item in result.get("items", []):
        for key in ("title", "summary", "apply", "directive"):
            if isinstance(item.get(key), str):
                item[key] = item[key].replace("\\n", "\n")
    return result


def _analyze_claude(articles_text: str, prompt: str, api_key: str) -> dict:
    """Claude API (Anthropic) 분석 — 1차 엔진."""
    import time
    max_retries = 3
    parse_retried = False  # AUD-15: JSON parse error 1회 재시도 플래그
    for attempt in range(max_retries):
        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": CLAUDE_MODEL,
                    "max_tokens": 8192,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=90,
            )
            if resp.status_code in (500, 529):
                wait = 2 ** attempt  # 1s → 2s → 4s
                print(f"[Analyzer/Claude] {resp.status_code}, retry {attempt+1}/{max_retries}, waiting {wait}s...")
                time.sleep(wait)
                continue
            if resp.status_code == 429:
                print(f"[Analyzer/Claude] 429 rate limit, retry {attempt+1}/{max_retries}, waiting 60s...")
                time.sleep(60)
                continue
            if 400 <= resp.status_code < 500:
                print(f"[Analyzer/Claude] {resp.status_code} client error, no retry: {resp.text[:200]}")
                return None
            if resp.status_code != 200:
                print(f"[Analyzer/Claude] Error: {resp.status_code} {resp.text[:200]}")
                return None
            text = resp.json()["content"][0]["text"]
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            text = _fix_json_newlines(text)
            return json.loads(text)
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            # AUD-15: parse error 는 1회 재시도, 재실패 시 None(→ Gemini 폴백)
            if not parse_retried:
                parse_retried = True
                print(f"[Analyzer/Claude] Parse error: {e} — 1회 재시도")
                continue
            print(f"[Analyzer/Claude] Parse error (재시도 후): {e} — Gemini 폴백")
            return None
        except Exception as e:
            print(f"[Analyzer/Claude] Error: {e}")
            return None
    print(f"[Analyzer/Claude] {max_retries}회 재시도 실패")
    return None


def _analyze_gemini(articles_text: str, prompt: str, api_key: str, model: str) -> dict:
    """Gemini API 분석 — 폴백 엔진."""
    import time
    max_retries = 3
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    for attempt in range(max_retries):
        try:
            resp = requests.post(url, json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.3, "maxOutputTokens": 8000},
            }, timeout=90)
            if resp.status_code in (500, 529, 503):
                wait = 2 ** attempt  # 1s → 2s → 4s
                print(f"[Analyzer/Gemini] {resp.status_code}, retry {attempt+1}/{max_retries}, waiting {wait}s...")
                time.sleep(wait)
                continue
            if resp.status_code == 429:
                print(f"[Analyzer/Gemini] 429 rate limit, retry {attempt+1}/{max_retries}, waiting 60s...")
                time.sleep(60)
                continue
            if 400 <= resp.status_code < 500:
                print(f"[Analyzer/Gemini] {resp.status_code} client error, no retry")
                return None
            if resp.status_code != 200:
                print(f"[Analyzer/Gemini] Error: {resp.status_code}")
                return None
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            text = _fix_json_newlines(text)
            return json.loads(text)
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            print(f"[Analyzer/Gemini] Parse error: {e}")
            return None
        except Exception as e:
            print(f"[Analyzer/Gemini] Error: {e}")
            return None
    print(f"[Analyzer/Gemini] {max_retries}회 재시도 실패")
    return None


def analyze(articles: list, api_key: str, model: str = "gemini-2.5-flash") -> dict | None:
    """기사 목록을 LLM 으로 분석.

    반환 규약 (AUD-03, 2026-06-12):
    - None            = 분석 엔진(API) 호출 전부 실패 — 호출측은 mark_sent 생략 + 재시도 안내
    - {"items": []}   = 엔진은 정상 응답했지만 진짜 품질 미달 (또는 입력 없음)
    - {"items": [..]} = 정상 분석 결과
    """
    if not api_key or not articles:
        return {"items": []}

    articles_text = ""
    for i, art in enumerate(articles, 1):
        articles_text += f"{i}. [{art['source']}] {art['title']}\n"
        if art.get("summary"):
            articles_text += f"   {art['summary'][:400]}\n"
        articles_text += f"   링크: {art['link']}\n\n"

    prompt = PROMPT_TEMPLATE.format(articles_text=articles_text)

    # AUD-03: 엔진이 한 번이라도 JSON 정상 응답했는지 추적 — API 실패와 품질 미달 구분
    engine_responded = False

    # 1차: Claude API (ANTHROPIC_API_KEY)
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    if anthropic_key:
        print("[Analyzer] Trying Claude API first...")
        result = _analyze_claude(articles_text, prompt, anthropic_key)
        if result is not None:
            engine_responded = True
            if result.get("items"):
                result = _postprocess_items(result)
                result = _validate_and_filter_items(result, "Claude")
                if result.get("items"):
                    print(f"[Analyzer] Claude OK: {len(result['items'])} items")
                    return result
        print("[Analyzer] Claude failed or all items invalid, falling back to Gemini...")

    # 2차: Gemini API (폴백)
    result = _analyze_gemini(articles_text, prompt, api_key, model)
    if result is not None:
        engine_responded = True
        result = _postprocess_items(result)
        result = _validate_and_filter_items(result, "Gemini")
        print(f"[Analyzer] Gemini OK: {len(result.get('items', []))} items")
        return result

    # 엔진이 정상 응답한 적 있으면 품질 미달, 전부 API 실패면 None
    if engine_responded:
        return {"items": []}
    print("[Analyzer] All engines failed (API) — returning None")
    return None
