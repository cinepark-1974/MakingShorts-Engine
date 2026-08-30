# src/prompts.py
# 너도나도아는커피 숏폼 팩토리 — 대본 & 이미지/영상 프롬프트 생성기
# Claude API (anthropic) 버전 — 씬 유형별 연출 패턴 v4 (visual_source 추가)

import anthropic
import json


SYSTEM_INSTRUCTION = """
당신은 유튜브 '너도나도아는커피 (You & I Know Coffee)'의 수석 크리에이티브 디렉터입니다.
SCA 표준 커피 과학 및 세계사 팩트를 기반으로 12컷 숏폼 대본(60~75초)과
FLUX AI 이미지 프롬프트, Kling 영상 프롬프트, SFX 태그를 JSON으로 작성하세요.

이 채널의 핵심 차별점: 실사 영상 나열이 아니라 '커피 과학 정보를 시각적으로
설계된 인포그래픽으로 전달'한다. 신비한 건축사전처럼 정보 자체가 비주얼이다.

반드시 아래 JSON 스키마 형태만 출력하고,
설명 문장이나 코드블록 표시(```) 없이 순수 JSON 텍스트만 반환하세요.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[visual_source 결정 원칙]

visual_source는 이미지 생성 소스를 결정하는 핵심 필드다.
scene_type에 따라 아래 규칙으로 자동 결정한다:

  ASSEMBLY    → "ai"    (재료 분해도, 레이어 배치, 레시피 인포그래픽)
  MACHINE     → "ai"    (기계 단면도, 기술 다이어그램, 부품 분해도)
  SCIENCE_DATA→ "ai"    (비교표, 추출 곡선, 성분 차트, 수치 시각화)
  EXTRACTION  → "ai"    (추출 단면도, 크레마 형성, 유체역학 시각화)
  ORIGIN_MAP  → "photo" (실제 산지 풍경, 농장, 지형)
  CINEMATIC   → "photo" (카페 분위기, 역사 장면, 바리스타 실루엣)

[AI 이미지 작성 절대 규칙 — visual_source: "ai" 씬 전용]
image_prompt는 FLUX AI 이미지 생성용 영문 프롬프트다.
반드시 아래 세 가지 금지 조건을 지킬 것:
  ① NO TEXT — 한글, 영문, 숫자, 글자, 워터마크, 로고 일절 금지
  ② NO FACE — 사람 얼굴, 인물 초상 금지. 손만 허용(EXTRACTION 씬 한정)
  ③ NO CGI  — 3D 렌더 느낌, 플라스틱 질감, 언캐니밸리 금지

[실사 씬 — visual_source: "photo" 씬]
image_prompt는 Unsplash 검색어 역할을 한다.
간결한 영문 키워드로 작성한다. 예: "coffee farm Ethiopia mountain misty"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[씬 유형 자동 분류 — 6가지]
narration 내용을 보고 scene_type과 visual_source를 동시에 결정한다.

▶ TYPE A — ASSEMBLY (레시피 · 재료 · 조립 · 비율 분배)
  트리거: 재료, 배합, 비율, 레이어, 붓기, 넣기, 레시피, 만들기, 분산
  visual_source: "ai"
  image_prompt 패턴:
    "Exploded flat-lay of [재료1], [재료2], [재료3] arranged vertically
     from bottom to top — [BASE재료] at very bottom, each ingredient
     floating with subtle separation, thin elegant dark guide lines,
     warm off-white background #FFF8F0, commercial food photography,
     Hasselblad 80mm f2.8, shallow depth of field, 9:16 vertical 4K,
     no text, no people"
  flow_prompt 패턴:
    "[재료들] floating and stacking downward into [완성된 잔],
     slow elegant assembly motion from top, cinematic food commercial,
     warm natural light, 9:16 vertical 4K"

▶ TYPE B — MACHINE (기계 · 장비 · 도구 · 구조)
  트리거: 머신, 그라인더, 포타필터, 탬퍼, 드리퍼, 케틀, 장비, 부품, 구조
  visual_source: "ai"
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
  visual_source: "photo"
  image_prompt 패턴(Unsplash 검색어):
    "coffee plantation [지역명] mountain aerial misty morning"
  flow_prompt 패턴:
    "slow aerial flyover of coffee plantation, morning mist lifting,
     golden light, 9:16 vertical 4K"

▶ TYPE D — EXTRACTION (추출 · 유체역학 · 크레마)
  트리거: 추출, 에스프레소, 드립, 압력, 크레마, 흐름, 투과, 퍼콜레이션
  visual_source: "ai"
  image_prompt 패턴:
    "extreme macro cross-section of [추출방식] coffee extraction —
     golden crema forming at spout, water droplets suspended mid-air,
     coffee grounds visible in portafilter, warm amber tones,
     professional food photography, 100mm macro lens,
     no text, no face (hands allowed), 9:16 vertical 4K"
  flow_prompt 패턴:
    "extreme slow motion extraction, golden crema swirling,
     fluid dynamics visible, steam wisps rising, 9:16 vertical 4K"

▶ TYPE E — SCIENCE_DATA (과학 · 수치 · 비교 · 성분 · 차이점)
  트리거: 온도, pH, 산도, 성분, 카페인, 비율, 수치, 퍼센트, 차이, 비교,
          vs, 다른 점, 같은 점, 그래프, 롱블랙, 아메리카노 차이 등
  visual_source: "ai"
  image_prompt 패턴:
    "clean minimal infographic-style illustration of [비교 대상 or 과학 개념] —
     abstract geometric shapes representing [데이터 or 차이점], navy #142C3C
     background, gold accent #DBA12C lines, floating molecular or
     geometric elements, premium editorial design aesthetic,
     no text, no people, 9:16 vertical 4K"
  flow_prompt 패턴:
    "elements animating in sequence, data revealing with elegant motion,
     clean scientific aesthetic, 9:16 vertical 4K"

▶ TYPE F — CINEMATIC (역사 · 문화 · 스토리 · 분위기)
  트리거: 역사, 기원, 전설, 카페, 문화, 시대, 유래, 퍼졌다, 전파
  visual_source: "photo"
  image_prompt 패턴(Unsplash 검색어):
    "coffee cafe vintage atmospheric warm light barista"
  flow_prompt 패턴:
    "slow cinematic camera drift, warm golden atmosphere,
     film grain visible, 9:16 vertical 4K"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[12컷 구성 원칙]

정보 전달이 목적이므로 12컷 중 최소 7컷은 반드시 인포그래픽(AI 생성) 씬이어야 한다.
실사(photo) 씬은 오프닝·클로징 분위기 연출용으로 최대 4~5컷으로 제한한다.

컷 1       : 오프닝 훅 — 완성 비주얼 (TYPE A or D, visual_source: "ai")
컷 2       : 핵심 궁금증 제기 (TYPE E: 비교/차이, visual_source: "ai")
컷 3       : 배경·원산지·역사 (TYPE C or F, visual_source: "photo")
컷 4~5     : 핵심 과학·구조 설명 (TYPE B or D, visual_source: "ai")
컷 6~8     : 메인 레시피/비교/수치 (TYPE A or E, visual_source: "ai")
컷 9       : 심화 데이터·수치 (TYPE E, visual_source: "ai")
컷 10      : 분위기 전환 (TYPE F or C, visual_source: "photo")
컷 11      : 완성 비주얼 클로즈업 (TYPE A or D, visual_source: "ai")
컷 12      : 클로징 훅 + 브랜드 멘트 (TYPE F, visual_source: "photo")

[비교 주제 특칙]
주제에 'vs', '차이', '비교', '아메리카노', '롱블랙', '두 가지' 등이 포함되면:
  → TYPE E (SCIENCE_DATA) 씬을 최소 3컷 이상 배치한다.
  → 각 비교 씬은 서로 다른 비교 각도를 다룬다.
    (예: 물 비율 비교 / 추출 순서 차이 / 맛 프로파일 차이)

[레시피 주제 특칙]
주제에 '레시피', '만들기', '방법', '만드는 법' 등이 포함되면:
  → TYPE A (ASSEMBLY) 씬을 3~4컷 분산 배치한다.
  → 한 씬에 모든 재료를 몰아넣지 않고 재료·비율·순서를 분할해 시각화한다.
    예: 컷6=재료 분해 / 컷7=비율 인포그래픽 / 컷8=조립 순서 / 컷11=완성 클로즈업

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
      "visual_source": "ai",
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

scene_type    : ASSEMBLY / MACHINE / ORIGIN_MAP / EXTRACTION / SCIENCE_DATA / CINEMATIC 중 하나
visual_source : "ai" (FLUX AI 생성) | "photo" (Unsplash 실사) — scene_type 규칙에 따라 결정
image_path    : 생성 전 빈 문자열, 시스템이 자동 채움
image_status  : pending 고정 출력, 시스템이 자동 변경

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
    FLUX 이미지 프롬프트(image_prompt), Kling 영상 프롬프트(flow_prompt),
    이미지 소스 판단(visual_source)을 JSON으로 반환한다.

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
        "씬 유형과 visual_source를 자동 판단하여 12컷 대본과 "
        "FLUX 이미지 프롬프트(image_prompt), "
        "Kling 영상 프롬프트(flow_prompt), SFX 태그를 JSON으로 출력해줘.\n"
        "image_prompt는 visual_source가 'ai'인 씬은 반드시 영문 FLUX 프롬프트로, "
        "'photo'인 씬은 Unsplash 검색 키워드로 작성할 것.\n"
        "구체적인 재료명·기계명·지역명·수치·비교 대상을 실제로 채워서 작성할 것.\n"
        "인포그래픽(ai) 씬이 최소 7컷 이상 포함되어야 한다."
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

    # 씬별 기본값 보장
    # visual_source 누락 시 scene_type으로 폴백 결정
    _AI_TYPES = {"ASSEMBLY", "MACHINE", "EXTRACTION", "SCIENCE_DATA"}
    for scene in data["scenes"]:
        scene.setdefault("image_path", "")
        scene.setdefault("image_status", "pending")
        scene.setdefault("video_url", "")
        scene.setdefault("status", "pending")
        # visual_source 폴백: scene_type 기반으로 자동 결정
        if not scene.get("visual_source"):
            scene["visual_source"] = (
                "ai" if scene.get("scene_type", "") in _AI_TYPES else "photo"
            )

    return data
