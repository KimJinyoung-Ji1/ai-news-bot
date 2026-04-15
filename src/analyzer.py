import json
import requests


PROMPT_TEMPLATE = """너는 시니어 개발자 수준의 기술 브리핑 작성자야.

[대상 독자]
- 중소기업 PM겸 풀스택 개발자
- 기술스택: Next.js 14 (App Router), Supabase, Vercel, Cloudflare R2
- 개발도구: Claude Code (Opus 4.6), Gemini API
- 관심사: AI 기반 업무 자동화, 코딩 생산성, AI 코딩 도구

아래 AI 관련 기사 목록을 분석해서 JSON으로 출력해.

[JSON 형식 - 이 형식만 출력, 다른 텍스트 금지]
```json
{{
  "items": [
    {{
      "title": "한글 제목 (구체적으로 — 무엇이 어떻게 변경되었는지)",
      "summary": "핵심 변경 내용 2~3문장. 이전과 무엇이 달라졌는지, 개발자에게 어떤 영향이 있는지 구체적으로.",
      "apply": "우리 프로젝트(Next.js+Supabase+Vercel)에 적용 가능한 구체적 방법. 적용 불가능하면 '참고 수준'이라고.",
      "link": "원문 URL",
      "directive": "Claude Code에게 내릴 구체적 작업지시 (적용 가능한 경우만. 불가능하면 빈 문자열)"
    }}
  ]
}}
```

[품질 규칙 — 반드시 지켜]
- 이모지 사용 금지
- 모든 내용 한국어 번역 필수. 영어 그대로 쓰지 마.
- 최대 6개 항목. Anthropic/Claude > OpenAI > Google > 기타 우선순위.
- 기술 변경/신기능/API 업데이트/성능 개선만. 투자/인사/마케팅/일반 AI 윤리 논란 제외.
- summary는 "~가 출시되었다" 같은 한 줄 요약이 아니라, 구체적 변경 내용과 영향을 2~3문장으로 설명해야 함.
- apply는 "적용 가능" 같은 뻔한 말 금지. 구체적으로 어떤 파일/기능에 어떻게 적용할지, 또는 "참고 수준"인지 명확히.
- directive: Claude Code한테 시키면 바로 실행 가능한 수준으로 구체적. 적용 불가능하면 빈 문자열 "".
- 사소한 패치/마이너 버그 수정/이미 알려진 내용은 제외. 실질적 가치가 있는 것만 선별.
- 같은 주제의 기사가 여러 개면 가장 정보량이 많은 1개만 선택.

기사 목록:
{articles_text}"""


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


def _analyze_claude(articles_text: str, prompt: str, api_key: str) -> dict:
    """Claude API (Anthropic) 분석 — 1차 엔진."""
    import time
    max_retries = 3
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
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 4096,
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
            print(f"[Analyzer/Claude] Parse error: {e}")
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


def analyze(articles: list, api_key: str, model: str = "gemini-2.5-flash") -> dict:
    if not api_key or not articles:
        return {"items": []}

    articles_text = ""
    for i, art in enumerate(articles, 1):
        articles_text += f"{i}. [{art['source']}] {art['title']}\n"
        if art.get("summary"):
            articles_text += f"   {art['summary'][:400]}\n"
        articles_text += f"   링크: {art['link']}\n\n"

    prompt = PROMPT_TEMPLATE.format(articles_text=articles_text)

    # 1차: Claude API (ANTHROPIC_API_KEY)
    import os
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    if anthropic_key:
        print("[Analyzer] Trying Claude API first...")
        result = _analyze_claude(articles_text, prompt, anthropic_key)
        if result and result.get("items"):
            for item in result.get("items", []):
                for key in ("title", "summary", "apply", "directive"):
                    if isinstance(item.get(key), str):
                        item[key] = item[key].replace("\\n", "\n")
            print(f"[Analyzer] Claude OK: {len(result['items'])} items")
            return result
        print("[Analyzer] Claude failed, falling back to Gemini...")

    # 2차: Gemini API (폴백)
    result = _analyze_gemini(articles_text, prompt, api_key, model)
    if result:
        for item in result.get("items", []):
            for key in ("title", "summary", "apply", "directive"):
                if isinstance(item.get(key), str):
                    item[key] = item[key].replace("\\n", "\n")
        print(f"[Analyzer] Gemini OK: {len(result.get('items', []))} items")
        return result

    return {"items": []}
