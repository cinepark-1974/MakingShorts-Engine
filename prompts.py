# src/prompts.py
# 너도나도아는커피 숏폼 팩토리 — 대본 & Kling 프롬프트 생성기
# Claude API (anthropic) 버전 — Gemini 대체

import anthropic
import json


SYSTEM_INSTRUCTION = """
당신은 유튜브 '너도나도아는커피 (You & I Know Coffee)'의 수석 크리에이티브 디렉터입니다.
SCA 표준 커피 과학 및 세계사 팩트를 기반으로 12컷 숏폼 대본(60~75초)과
Kling AI 3D/유체역학/설계도 영문 프롬프트, SFX 태그를 JSON으로 작성하세요.

반드시 아래 JSON 스키마 형태만 출력하고,
설명 문장이나 코드블록 표시(```) 없이 순수 JSON 텍스트만 반환하세요.

[JSON 스키마]
{
  "chapter": "챕터명",
  "title": "주제명",
  "full_narration": "전체 읽을 나레이션 텍스트",
  "scenes": [
    {
      "scene_no": 1,
      "name": "오프닝 훅",
      "narration": "대사",
      "flow_prompt": "A professional Korean barista, cinematic coffee lab, 3D cutaway view, 9:16 vertical, 4k",
      "sfx": "impact_whoosh",
      "overlay_text": "화면 자막 키워드",
      "video_url": "",
      "status": "pending"
    }
  ]
}

[SFX 태그 목록]
- impact_whoosh  : 임팩트 있는 전환
- tech_beep      : 데이터·과학 장면
- steam_hiss     : 커피 추출·스팀 장면
- coffee_pour    : 드립·붓기 장면
- ambient_cafe   : 카페 배경
- deep_bass      : 강조·클로즈업
- none           : 효과음 없음
"""


def generate_script_and_prompts(api_key: str, chapter: str, topic: str) -> dict:
    """
    Claude API를 호출하여 12컷 숏폼 대본과 Kling 영문 프롬프트를 JSON으로 반환한다.

    Args:
        api_key : ANTHROPIC_API_KEY
        chapter : 챕터명  (예: "CH01 커피의 탄생")
        topic   : 주제명  (예: "에티오피아 예가체프 내추럴 프로세싱의 비밀")

    Returns:
        dict : 위 JSON 스키마 형태의 파이썬 딕셔너리

    Raises:
        json.JSONDecodeError : Claude 응답이 유효한 JSON이 아닐 때
        anthropic.APIError   : API 호출 자체가 실패했을 때
    """
    client = anthropic.Anthropic(api_key=api_key)

    user_prompt = (
        f"챕터: '{chapter}', 주제: '{topic}'.\n"
        "12컷 대본과 Kling 비디오용 영문 프롬프트, SFX 태그를 JSON으로 출력해줘."
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=SYSTEM_INSTRUCTION,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw_text = response.content[0].text.strip()

    # 방어 파싱: 혹시 ```json ... ``` 코드블록으로 감싸져 오는 경우 처리
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        if raw_text.lower().startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.strip()

    data = json.loads(raw_text)

    # 스키마 최소 검증
    required_keys = {"chapter", "title", "full_narration", "scenes"}
    missing = required_keys - data.keys()
    if missing:
        raise ValueError(f"Claude 응답에 필수 키가 없습니다: {missing}")

    if not isinstance(data["scenes"], list) or len(data["scenes"]) == 0:
        raise ValueError("scenes 배열이 비어 있습니다.")

    return data
