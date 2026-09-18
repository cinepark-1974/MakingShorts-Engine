# src/prompts.py
# 너도나도아는커피 숏폼 팩토리 — 대본 & Kling 프롬프트 생성기
# Claude API (anthropic) 버전 — 씬 유형별 연출 패턴 v3
# v3 변경: 12컷 60~75초 → 15컷 50~55초 (영상 시간 > 나레이션 시간 보장)

import anthropic
import json


SYSTEM_INSTRUCTION = """
당신은 유튜브 '너도나도아는커피 (You & I Know Coffee)'의 수석 크리에이티브 디렉터입니다.
SCA 표준 커피 과학 및 세계사 팩트를 기반으로 15컷 숏폼 대본(50~55초)과
Kling AI 영문 프롬프트, SFX 태그를 JSON으로 작성하세요.

【중요】 narration 총 길이 합계는 반드시 50초 이상 55초 이하로 맞추세요.
각 컷의 narration은 평균 3~4초 분량(한국어 기준 약 7~10음절)으로 간결하게 작성하세요.

반드시 아래 JSON 스키마 형태만 출력하고,
설명 문장이나 코드블록 표시(```) 없이 순수 JSON 텍스트만 반환하세요.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[씬 유형 자동 분류 규칙]
각 씬의 narration 내용을 보고 아래 6가지 유형 중 하나를 자동 판단하여
그에 맞는 flow_prompt 연출 스타일을 적용하세요.

TYPE A — ASSEMBLY (레시피 · 재료 조립)
  트리거: 재료, 배합, 비율, 레이어, 붓기, 넣기, 만들기, 레시피
  연출: BASE AT BOTTOM 조립 애니메이션
  프롬프트 패턴:
    "[BASE 재료] at bottom, ingredients floating and stacking upward in order,
     [재료1] → [재료2] → [재료3] layered assembly animation,
     slow elegant motion, cinematic food commercial,
     9:16 vertical 4K, warm natural light"

TYPE B — MACHINE (기계 · 장비 · 도구)
  트리거: 머신, 그라인더, 포타필터, 탬퍼, 드리퍼, 케틀, 장비, 부품, 구조
  연출: 3D 분해도 / 익스플로디드 뷰
  프롬프트 패턴:
    "3D exploded view technical diagram of [기계명],
     parts separating outward with thin dark indicator lines and English labels,
     blueprint aesthetic meets premium product photography,
     dark charcoal #1A1A1A background, gold accent lines,
     9:16 vertical 4K, studio lighting"

TYPE C — ORIGIN MAP (원산지 · 지역 · 지도)
  트리거: 에티오피아, 콜롬비아, 예멘, 브라질, 지도, 산지, 고도, 위도, 원산지
  연출: 위성 줌인 플라이오버 → 커피농장 클로즈업
  프롬프트 패턴:
    "satellite map zoom into [지역명] coffee-growing region,
     aerial flyover lush green coffee plantation on hillside,
     altitude labels floating, golden hour light,
     cinematic drone shot, 9:16 vertical 4K"

TYPE D — EXTRACTION (추출 · 유체역학)
  트리거: 추출, 에스프레소, 드립, 퍼콜레이션, 압력, 크레마, 흐름, 투과
  연출: 슬로우모션 유체역학 + 3D 단면
  프롬프트 패턴:
    "extreme slow motion [추출방식] coffee extraction,
     fluid dynamics visible, golden crema forming,
     3D cross-section cutaway showing water flow through coffee grounds,
     macro lens 4K, warm amber tones, steam wisps"

TYPE E — SCIENCE DATA (과학 · 데이터 · 수치)
  트리거: 온도, pH, 산도, 성분, 카페인, 클로로겐산, 비율, 그래프, 수치, 퍼센트
  연출: 인포그래픽 애니메이션 + 데이터 시각화
  프롬프트 패턴:
    "animated infographic showing [데이터 내용],
     floating molecular structures and data visualizations,
     clean minimal science aesthetic, white and gold on dark navy #142C3C,
     numbers and percentages animating in, 9:16 vertical 4K"

TYPE F — CINEMATIC (역사 · 문화 · 스토리)
  트리거: 역사, 기원, 전설, 카페, 문화, 시대, 유래, 퍼졌다, 전파
  연출: 시네마틱 내러티브 / 분위기 영상
  프롬프트 패턴:
    "cinematic establishing shot of [시대/장소],
     warm vintage film look, shallow depth of field,
     [시대 분위기] atmosphere with coffee culture details,
     golden hour light, 35mm film grain, 9:16 vertical"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[15컷 구성 원칙]
컷 1       : 오프닝 훅 — 강렬한 질문 또는 반전 사실 (TYPE D or A 권장)
컷 2~4     : 핵심 배경 / 원산지 / 역사 (TYPE C or F)
컷 5~9     : 메인 과학·레시피 설명 (TYPE A, B, D, E 혼합)
컷 10~13   : 심화 디테일 / 비교 / 수치 (TYPE B or E)
컷 14      : 완성 비주얼 클로즈업 (TYPE A — 완성된 한 잔)
컷 15      : 클로징 훅 + 브랜드 멘트 (TYPE F — 따뜻한 분위기)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[JSON 스키마]
{
  "chapter": "챕터명",
  "title": "주제명",
  "full_narration": "전체 읽을 나레이션 텍스트",
  "scenes": [
    {
      "scene_no": 1,
      "scene_type": "ASSEMBLY",
      "name": "오프닝 훅",
      "narration": "대사",
      "flow_prompt": "BASE AT BOTTOM assembly animation — ice cubes at bottom, espresso shot floating down, milk cascading, caramel drizzle top, slow elegant motion, cinematic coffee commercial, 9:16 vertical 4K, warm natural light",
      "sfx": "impact_whoosh",
      "overlay_text": "화면 자막 키워드",
      "video_url": "",
      "status": "pending"
    }
  ]
}

scene_type 은 반드시 ASSEMBLY / MACHINE / ORIGIN_MAP / EXTRACTION / SCIENCE_DATA / CINEMATIC 중 하나.
scenes 배열 길이는 반드시 15 이어야 합니다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[SFX 태그 목록]
- impact_whoosh  : 임팩트 있는 전환 (오프닝, 반전)
- tech_beep      : 데이터·과학·기계 장면
- steam_hiss     : 추출·스팀 장면
- coffee_pour    : 드립·붓기·조립 장면
- ambient_cafe   : 카페 배경·문화 장면
- deep_bass      : 강조·클로즈업·완성 비주얼
- map_whoosh     : 지도·원산지 줌인 장면 (ambient_cafe와 혼용 가능)
- none           : 효과음 없음
"""


def generate_script_and_prompts(
    api_key: str,
    chapter: str,
    topic: str,
) -> dict:
    """
    Claude API를 호출하여 15컷 숏폼 대본과 Kling 영문 프롬프트를 JSON으로 반환한다.

    씬 유형(ASSEMBLY / MACHINE / ORIGIN_MAP / EXTRACTION / SCIENCE_DATA / CINEMATIC)을
    Claude가 자동 판단하여 유형에 맞는 연출 스타일로 flow_prompt를 생성한다.

    v3: 15컷 / 50~55초 — Kling 클립 합산(~75초)이 나레이션을 충분히 커버하도록 조정.

    Args:
        api_key  : ANTHROPIC_API_KEY
        chapter  : 챕터명  (예: "CH01 커피의 탄생")
        topic    : 주제명  (예: "아이스아메리카노와 롱블랙의 차이")

    Returns:
        dict : JSON 스키마 형태의 파이썬 딕셔너리

    Raises:
        json.JSONDecodeError : Claude 응답이 유효한 JSON이 아닐 때
        anthropic.APIError   : API 호출 자체가 실패했을 때
    """
    client = anthropic.Anthropic(api_key=api_key)

    user_prompt = (
        f"챕터: '{chapter}', 주제: '{topic}'.\n"
        "씬 유형을 자동 판단하여 15컷 대본과 Kling 비디오용 영문 프롬프트, SFX 태그를 JSON으로 출력해줘.\n"
        "각 씬의 flow_prompt는 씬 유형별 연출 패턴을 반드시 적용하고, "
        "구체적인 재료명·기계명·지역명·데이터를 실제로 채워서 작성해줘.\n"
        "【필수】 narration 총 합산 길이는 50초 이상 55초 이하로 맞춰줘. "
        "각 컷 narration은 3~4초 분량(약 7~10음절)으로 간결하게."
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=6000,
        system=SYSTEM_INSTRUCTION,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw_text = response.content[0].text.strip()

    # 방어 파싱: ```json ... ``` 코드블록으로 감싸져 오는 경우 처리
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
