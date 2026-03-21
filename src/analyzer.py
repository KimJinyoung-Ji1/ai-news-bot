import json
import requests


PROMPT_TEMPLATE = """너는 시니어 개발자 수준의 기술 브리핑 작성자야.

[대상 독자]
- 중소기업 PM겸 풀스택 개발자
- 기술스택: Next.js 14 (App Router), Supabase, Vercel, Cloudflare R2
- 개발도구: Claude Code (Opus 4.6), Gemini API (2.5 Flash)
- 관심사: AI 기반 업무 자동화, 코딩 생산성

아래 AI 관련 기사 목록을 분석해서 JSON으로 출력해.

[JSON 형식 - 이 형식만 출력, 다른 텍스트 금지]
```json
{{
  "items": [
    {{
      "title": "한글 제목",
      "summary": "변경 내용 1줄 요약",
      "apply": "우리 프로젝트 적용방법 1줄",
      "link": "원문 URL",
      "directive": "Claude Code에게 내릴 구체적 작업지시 (적용 가능한 경우만. 불가능하면 빈 문자열)"
    }}
  ]
}}
```

[규칙]
- 이모지 사용 금지
- 모든 내용 한국어 번역 필수. 영어 그대로 쓰지 마.
- 최대 6개 항목. Anthropic/Claude 우선.
- 기술 변경/신기능만. 투자/인사/마케팅 제외.
- directive: Claude Code한테 시키면 바로 실행 가능한 수준으로 구체적. 적용 불가능하면 빈 문자열 "".

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


def analyze(articles: list, api_key: str, model: str = "gemini-2.5-flash") -> dict:
    if not api_key or not articles:
        return {"items": []}

    articles_text = ""
    for i, art in enumerate(articles, 1):
        articles_text += f"{i}. [{art['source']}] {art['title']}\n"
        if art.get("summary"):
            articles_text += f"   {art['summary'][:150]}\n"
        articles_text += f"   링크: {art['link']}\n\n"

    prompt = PROMPT_TEMPLATE.format(articles_text=articles_text)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    for attempt in range(2):
        try:
            resp = requests.post(url, json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.3, "maxOutputTokens": 8000},
            }, timeout=60)

            if resp.status_code == 429:
                import time
                wait = 5 * (attempt + 1)
                print(f"[Analyzer] Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue

            if resp.status_code != 200:
                print(f"[Analyzer] Gemini error: {resp.status_code}")
                return {"items": []}

            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]

            # JSON 추출
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            text = _fix_json_newlines(text)
            result = json.loads(text)

            # 줄바꿈 복원
            for item in result.get("items", []):
                for key in ("title", "summary", "apply", "directive"):
                    if isinstance(item.get(key), str):
                        item[key] = item[key].replace("\\n", "\n")

            return result

        except json.JSONDecodeError as e:
            print(f"[Analyzer] JSON parse error: {e}")
            return {"items": []}
        except Exception as e:
            print(f"[Analyzer] Error: {e}")
            return {"items": []}

    return {"items": []}
