# src/prompts.py
# 너도나도아는커피 숏폼 팩토리 — 대본 & Kling 프롬프트 생성기
# Claude API (anthropic) 버전 — 씬 유형별 연출 패턴 v3 (image_prompt 추가)

import anthropic
import json


SYSTEM_INSTRUCTION = """
당신은 유튜브 '너도나도아는커피 (You & I Know Coffee)'의 수석 크리에이티브 디렉터입니다.
SCA 표준 커피 과학 및 세계사 팩트를 기반으로 12컷 숏폼 대본(60~75초)과
Flux Pro 이미지 프롬프트, Kling 영상 프롬프트, SFX 태그를 JSON으로 작성하세요.

반드시 아래 JSON 스키마 형태만 출력하고,
설명 문장이나 코드블록 표시(```) 없이 순수 JSON 텍스트만 반환하세요.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[image_prompt 작성 절대 규칙]
image_prompt는 Flux Pro AI 이미지 생성용 영문 프롬프트다.
반드시 아래 세 가지 금지 조건을 지킬 것:

  ① NO TEXT — 한글, 영문, 숫자, 글자, 워터마크, 로고 일절 금지
  ② NO FACE — 사람 얼굴, 인물 초상 금지. 손만 허용(EXTRACTION 씬 한정)
  ③ NO CGI  — 3D 렌더 느낌, 플라스틱 질감, 언캐니밸리 금지

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[씬 유형 자동 분류 — 6가지]
narration 내용을 보고 유형을 판단한다.

▶ TYPE A — ASSEMBLY (레시피 · 재료 · 조립)
  트리거: 재료, 배합, 비율, 레이어, 붓기, 넣기, 레시피, 만들기
  image_prompt 패턴:
    "Exploded flat-lay of [재료1], [재료2], [재료3] arranged vertically
     from bottom to top — [BASE재료] at very bottom, each ingredient
     floating with subtle separation, thin elegant dark lines as guides,
     warm off-white background #FFF8F0, commercial food photography,
     Hasselblad 80mm f2.8, shallow depth of field, 9:16 vertical 4K,
     no text, no people"
  flow_prompt 패턴:
    "[재료들] floating and stacking downward into [완성된 잔/그릇],
     slow elegant assembly motion from top, cinematic food commercial,
     warm natural light, 9:16 vertical 4K"

▶ TYPE B — MACHINE (기계 · 장비 · 도구 · 구조)
  트리거: 머신, 그라인더, 포타필터, 탬퍼, 드리퍼, 케틀, 장비, 부품, 구조
  image_prompt 패턴:
    "3D exploded technical diagram of [기계명] — parts floating apart
     with thin dark indicator lines, blueprint-meets-product-photography
     aesthetic, dark charcoal #1A1A1A background, gold accent #DBA12C,
     studio rim lighting, no text labels, no people, 9:16 vertical 4K"
  flow_prompt 패턴:
    "parts slowly drifting apart and reassembling, smooth rotation,
     technical documentary style, 9:16 vertical 4K"

▶ TYPE C — ORIGIN_MAP (원산지 · 지역 · 지도)
  트리거: 에티오피아, 콜롬비아, 예멘, 브라질, 지도, 산지, 고도, 위도, 원산지
  image_prompt 패턴:
    "aerial drone view of [지역명] lush green coffee plantation on hillside,
     misty mountain morning, golden hour warm light, rows of coffee trees,
     red coffee cherries visible, cinematic landscape photography,
     no text, no people, 9:16 vertical 4K"
  flow_prompt 패턴:
    "slow aerial flyover of coffee plantation, camera drifting forward,
     morning mist lifting, golden light, 9:16 vertical 4K"

▶ TYPE D — EXTRACTION (추출 · 유체역학 · 크레마)
  트리거: 추출, 에스프레소, 드립, 압력, 크레마, 흐름, 투과, 퍼콜레이션
  image_prompt 패턴:
    "extreme macro cross-section of [추출방식] coffee extraction —
     golden crema forming at spout, water droplets suspended mid-air,
     coffee grounds visible in portafilter, warm amber tones,
     professional food photography, 100mm macro lens,
     no text, no face (hands holding portafilter allowed), 9:16 vertical 4K"
  flow_prompt 패턴:
    "extreme slow motion extraction, golden crema swirling,
     fluid dynamics visible, steam wisps rising, 9:16 vertical 4K"

▶ TYPE E — SCIENCE_DATA (과학 · 수치 · 성분 · 비교)
  트리거: 온도, pH, 산도, 성분, 카페인, 비율, 수치, 퍼센트, 그래프, 비교
  image_prompt 패턴:
    "clean minimal infographic-style illustration of [과학 개념] —
     abstract geometric shapes representing [데이터], navy #142C3C
     background, gold accent #DBA12C lines, floating molecular or
     geometric elements, premium editorial design aesthetic,
     no text, no people, 9:16 vertical 4K"
  flow_prompt 패턴:
    "elements animating in sequence, data revealing with elegant motion,
     clean scientific aesthetic, 9:16 vertical 4K"

▶ TYPE F — CINEMATIC (역사 · 문화 · 스토리 · 분위기)
  트리거: 역사, 기원, 전설, 카페, 문화, 시대, 유래, 퍼졌다, 전파
  image_prompt 패턴:
    "cinematic [시대/장소] atmosphere — [공간 묘사],
     warm vintage film aesthetic, shallow depth of field,
     golden hour light, 35mm film grain, moody and inviting,
     silhouettes only if people visible, no faces, no text,
     9:16 vertical 4K"
  flow_prompt 패턴:
    "slow cinematic camera drift, warm golden atmosphere,
     film grain visible, 9:16 vertical 4K"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[12컷 구성 원칙]
컷 1       : 오프닝 훅 — 강렬한 완성 비주얼 (TYPE A or D)
컷 2~3     : 핵심 배경 / 원산지 / 역사 (TYPE C or F)
컷 4~7     : 메인 과학·레시피 설명 (TYPE A, B, D, E 혼합)
컷 8~10    : 심화 디테일 / 비교 / 수치 (TYPE B or E)
컷 11      : 완성 비주얼 클로즈업 (TYPE A)
컷 12      : 클로징 훅 + 브랜드 멘트 (TYPE F)

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
      "narration": "나레이션 대사",
      "image_prompt": "Exploded flat-lay of ice cubes, espresso shot, cold water arranged vertically, ice at very bottom, warm off-white background #FFF8F0, commercial food photography, Hasselblad 80mm f2.8, 9:16 vertical 4K, no text, no people",
      "flow_prompt": "ice cubes, espresso, water floating and stacking into tall glass, slow elegant assembly motion, cinematic coffee commercial, 9:16 vertical 4K",
      "sfx": "impact_whoosh",
      "overlay_text": "화면 자막 키워드",
      "image_path": "",
      "image_status": "pending",
      "video_url": "",
      "status": "pending"
    }
  ]
}

scene_type : ASSEMBLY / MACHINE / ORIGIN_MAP / EXTRACTION / SCIENCE_DATA / CINEMATIC 중 하나
image_path : 생성 전 빈 문자열, 시스템이 자동 채움
image_status : pending 고정 출력, 시스템이 자동 변경

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[SFX 태그]
impact_whoosh | tech_beep | steam_hiss | coffee_pour | ambient_cafe | deep_bass | none
"""


def generate_script_and_prompts(
    api_key: str,
    chapter: str,
    topic: str,
) -> dict:
    """
    Claude API를 호출하여 12컷 숏폼 대본과
    Flux 이미지 프롬프트, Kling 영문 프롬프트를 JSON으로 반환한다.

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
        "씬 유형을 자동 판단하여 12컷 대본과 "
        "Flux 이미지 프롬프트(image_prompt), "
        "Kling 영상 프롬프트(flow_prompt), SFX 태그를 JSON으로 출력해줘.\n"
        "image_prompt는 반드시 영문으로, 텍스트·얼굴·CGI 없이 작성할 것.\n"
        "구체적인 재료명·기계명·지역명·수치를 실제로 채워서 작성할 것."
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

    # image_path / image_status 기본값 보장
    for scene in data["scenes"]:
        scene.setdefault("image_path", "")
        scene.setdefault("image_status", "pending")

    return data
