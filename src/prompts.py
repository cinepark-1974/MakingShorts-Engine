# src/prompts.py
# 너도나도아는커피 숏폼 팩토리 — 대본 & 이미지/영상 프롬프트 생성기
# Claude API (anthropic) 버전 — 씬 유형별 연출 패턴 v4 (visual_source 추가)

import anthropic
import json
import re


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

  ASSEMBLY    → "ai"    (재료 분해도, 레이어 배치, 레시피 → flux-pro 포토리얼)
  MACHINE     → "ai"    (기계 구조, 부품 — flux-dev 편집 일러스트)
  SCIENCE_DATA→ "ai"    (비교 시각화, 수치 — flux-dev 편집 일러스트)
  EXTRACTION  → "ai"    (추출 장면, 크레마 — flux-dev 편집 일러스트)
  ORIGIN_MAP  → "photo" (실제 산지 풍경, 농장, 지형)
  CINEMATIC   → "photo" (카페 분위기, 역사 장면, 바리스타 실루엣)

[AI 이미지 작성 절대 규칙 — visual_source: "ai" 씬 전용]
image_prompt는 FLUX AI 이미지 생성용 영문 프롬프트다.
반드시 아래 조건을 지킬 것:

  ① NO TEXT — 한글, 영문, 숫자, 글자, 워터마크, 로고 일절 금지
     → 프롬프트 안에 "pure visual only zero text zero labels zero words" 문구를 반드시 포함할 것
  ② NO FACE — 사람 얼굴, 인물 초상 금지. 손만 허용(EXTRACTION 씬 한정)
  ③ NO CGI  — 3D 렌더 느낌, 플라스틱 질감, 언캐니밸리 금지
  ④ 금지 단어 — "infographic", "chart", "graph", "diagram", "label", "legend",
                 "data visualization" 절대 사용 금지.
     이 단어들이 프롬프트에 포함되면 FLUX가 텍스트 레이블이 붙은 도표를 생성한다.
  ⑤ 씬 타입별 렌더링 방식 — 프롬프트 작성 시 반드시 구분할 것
     ASSEMBLY               → flux-pro 포토리얼 (음식 사진 스타일)
                              "Hasselblad", "macro lens", "commercial food photography" 등 카메라 표현 사용 가능
     MACHINE / EXTRACTION
     SCIENCE_DATA           → flux-dev 수채화 스케치 (pen-and-ink + watercolor wash)
                              ★ 카메라·촬영 표현 절대 금지 ★
                              "Hasselblad", "macro lens f2.8", "commercial photography",
                              "studio product photography", "shallow depth of field" 사용 금지
                              → 이 표현들이 수채화 스케치 접두사(image_fal.py 자동 삽입)와 충돌해
                                 어중간한 포토리얼 결과물(언캐니밸리)이 나온다.
                              ✓ 대신 사용할 표현:
                              "delicate ink lines", "watercolor wash", "paper texture",
                              "warm amber tones", "sketchbook quality", "artbook illustration"

[실사 씬 — visual_source: "photo" 씬]
image_prompt는 Unsplash 검색어 역할을 한다.
간결한 영문 키워드로 작성한다. 예: "coffee farm Ethiopia mountain misty"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[씬 유형 자동 분류 — 6가지]
narration 내용을 보고 scene_type과 visual_source를 동시에 결정한다.

▶ TYPE A — ASSEMBLY (레시피 · 재료 · 조립 · 비율 분배)
  트리거: 재료, 배합, 비율, 레이어, 붓기, 넣기, 레시피, 만들기, 분산
  visual_source: "ai"

  ★ 레시피 주제에서 ASSEMBLY 씬은 3~4컷으로 반드시 분산한다.
     씬마다 시각적 초점이 달라야 한다. 아래 4가지 하위패턴 중 씬 내용에 맞는 것을 선택할 것.
     같은 패턴을 두 씬에 연속으로 쓰지 않는다.

  [하위패턴 1 — 재료 클로즈업] 한 가지 핵심 재료만 단독으로 강조한다.
    "Macro hero shot of [재료 하나] — [재료 묘사: e.g. 'espresso shot with golden crema'
     or 'ice crystals with frosted surface texture'],
     single ingredient floating dramatically on warm off-white background #FFF8F0,
     extreme close-up, dramatic side rim lighting, Hasselblad 80mm macro lens,
     shallow depth of field, pure visual zero text zero labels zero words,
     no people, 9:16 vertical 4K"

  [하위패턴 2 — 비율 시각화] 재료 간 양적 비율을 물리적 크기 차이로 표현한다.
    "Three minimalist glass vessels of starkly different heights placed side by side —
     TALLEST vessel filled with [A재료, 색]: [전체의 몇 분의 몇 비율],
     MEDIUM vessel filled with [B재료, 색]: [비율],
     SHORTEST vessel filled with [C재료, 색]: [비율],
     each vessel precisely proportioned to reflect actual recipe ratio,
     dark charcoal #1A1A1A background, warm amber studio lighting,
     pure visual zero text zero labels zero numbers, no people, 9:16 vertical 4K"

  [하위패턴 3 — 폭발 분해도] BASE AT BOTTOM 원칙으로 재료를 수직 분해한다.
  ★ MASTER TEMPLATE v9 DNA — 원작자가 설계한 광고 포스터 폭발도 개념을 FLUX에 맞게 적용.
     "BASE AT BOTTOM" 원칙: 맨 아래=베이스 재료, 위로 갈수록 나중에 올라가는 재료 순.
     커피 예시: Bottom=Ice Cubes → Cold Water → Espresso Shot → Top=Foam or Sauce

    "Premium exploded ingredient breakdown, BASE AT BOTTOM stacking order —
     [베이스재료] floating at very BOTTOM of frame,
     [재료2] floating above with clear separation gap,
     [재료3] floating above that,
     [재료4] floating above that,
     [최상단재료] floating at very TOP of frame,
     EXACTLY 5 ingredients total stacked vertically, each ingredient EXTRA LARGE scale
     very prominent close-up filling at least 40% of frame width,
     thin elegant dark brown indicator lines only connecting each element
     (lines only — ZERO text ZERO labels ZERO words on any line),
     [배경 자동선택]:
       커피음료(아이스아메리카노·라떼·마키아토·에이드) → warm beige #EDE6D6 or off-white #FFF8F0
       따뜻한커피음료 → clean warm off-white #FFF8F0
       음식(비빔밥·가츠동·포케) → warm off-white #FFF8F0 or dark charcoal #1A1A1A
     soft natural window light from left, warm natural light,
     commercial food photography Hasselblad H6D-100c 80mm f2.8,
     real food styling natural imperfections,
     pure visual zero text zero labels zero words zero numbers,
     no people, no tablecloth, no fabric texture, no CGI, no 3D render,
     9:16 vertical 4K"

  [하위패턴 4 — 완성 히어로샷] 완성된 음료를 대형 히어로 스케일로 담는다.
  ★ MASTER TEMPLATE v9 오른쪽 패널 DNA — 분해도와 한 쌍이 되는 완성 비주얼.

    "Completed [음료명/음식명] large hero scale prominent in [matte black or white cup/bowl/glass] —
     clean elegant plating, light sauce brush not heavy drip, balanced visual weight,
     [아이스드링크: ice crystals and condensation on glass exterior,
      dramatic side backlighting revealing distinct liquid layer transparency],
     [따뜻한음료: steam wisps rising gently, warm amber backlight],
     [음식: natural imperfections in real food styling, vibrant color],
     soft natural window light from left, warm natural light,
     commercial food photography Hasselblad H6D-100c 80mm f2.8,
     real food styling natural imperfections, 8K real photo,
     pure visual zero text zero labels zero words,
     no people, no tablecloth, no linen texture, no heavy sauce drip,
     no gross, no slimy, no plastic, no CGI, no 3D render,
     9:16 vertical 4K"

  flow_prompt 패턴:
    "[재료들] floating and assembling downward into [완성된 잔/그릇],
     slow elegant layering motion from top, each ingredient settling into position,
     cinematic food commercial, warm natural light, 9:16 vertical 4K"

▶ TYPE B — MACHINE (기계 · 장비 · 도구 · 구조)
  트리거: 머신, 그라인더, 포타필터, 탬퍼, 드리퍼, 케틀, 장비, 부품, 구조
  visual_source: "ai"

  ★ 금지 단어: "blueprint", "technical diagram", "schematic", "illustration", "cutaway diagram"
     이 단어들이 텍스트 레이블과 그리드선을 유발한다.
     레퍼런스: Apple iPhone/AirPods 제품 분해 광고 사진 스타일 — 어두운 배경에 금속 부품들이 공중 부양.

  [하위패턴 1 — 전체 분해도 (Apple 스타일)] 기계 전체를 부품별로 분해해 수직으로 배치한다.
    "Premium exploded product photography of [기계명] —
     [부품1: 맨 아래 베이스 부품] floating at very bottom,
     [부품2] floating above with precise gap,
     [부품3] floating above that,
     [부품4] floating above that,
     [부품5: 외관 상단] floating at very top,
     each metallic component casting precise soft drop shadow,
     [소재 묘사: 'brushed stainless steel surface', 'matte black anodized aluminum',
      'polished chrome collar', 'ceramic flat burr disc'],
     dark charcoal #1A1A1A background, gold accent rim lighting #DBA12C,
     delicate ink lines, warm watercolor wash fills, sketchbook artbook quality,
     pure visual zero text zero labels zero words zero annotations,
     no people, no CGI, no blueprint grid, no 3D render, no photorealism,
     9:16 vertical 4K"

  [하위패턴 2 — 핵심 부품 클로즈업] 핵심 부품 하나를 극단적으로 클로즈업해 질감을 강조한다.
    "Extreme close-up macro hero shot of [핵심 부품명] —
     [소재·질감 묘사: e.g.
      'brushed stainless steel portafilter with micro-perforated filter basket,
       water droplets caught in filter basket holes',
      or 'ceramic flat burr grinder disc with precision-engineered tungsten ridges,
         fine coffee ground particles caught in burr grooves',
      or 'matte black espresso tamper with chrome collar and mirror-flat base,
         coffee grounds residue on tamper face'],
     dramatic single-source studio lighting from upper-left,
     gold accent highlight catching metal edge,
     dark charcoal #1A1A1A background,
     delicate ink linework, watercolor wash detail, warm amber tones,
     sketchbook artbook quality, material texture visible,
     pure visual zero text zero labels zero words,
     no people, no CGI, no 3D render, no photorealism,
     9:16 vertical 4K"

  flow_prompt 패턴:
    "metallic parts slowly drifting apart revealing internal structure,
     smooth 360-degree rotation, studio lighting catching each component edge,
     premium hardware documentary style, 9:16 vertical 4K"

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

  ★ "cross-section diagram", "cutaway view" 금지 — 다이어그램 스타일로 빠짐.
     레퍼런스: 실제 커피 매크로 사진작가 스타일 (Dritan Alsela, James Hoffmann 채널 비주얼).
     물리적 실체가 있는 피사체를 극단 클로즈업하는 것이 이 씬의 핵심.

  [하위패턴 1 — 추출 순간] 에스프레소/드립 추출이 진행되는 찰나를 포착한다.
    "Extreme macro photography of [에스프레소/드립] coffee extraction in progress —
     [에스프레소: 'twin golden amber espresso streams flowing from portafilter spout,
       rich golden crema bubbling at surface with tiger-stripe pattern,
       coffee puck moisture visible through basket holes,
       micro steam wisps rising from fresh extraction'],
     [드립: 'single bloom water droplet suspended above dark coffee grounds in paper filter,
       golden-amber extraction liquid dripping below,
       paper filter glowing amber with warm backlight behind it'],
     warm amber golden tones, dramatic backlighting from behind subject,
     extreme close-up extreme detail, fluid physics and imperfections visible,
     delicate ink strokes, amber watercolor wash blooms on paper texture,
     sketchbook artbook quality, warm golden glow,
     pure visual zero text zero labels zero words,
     hands allowed at frame edge (absolutely no face),
     no CGI, no 3D render, no photorealism, no harsh moody dark,
     9:16 vertical 4K"

  [하위패턴 2 — 크레마 클로즈업] 갓 추출된 에스프레소 크레마 표면을 극단 확대한다.
    "Extreme close-up macro of fresh espresso crema surface in ceramic espresso cup —
     rich golden-brown crema with natural tiger-stripe swirl pattern,
     micro bubbles and coffee oil droplets glistening on surface,
     [optional: small espresso spoon breaking crema surface tension at edge],
     warm studio lighting from upper-left,
     delicate ink linework, watercolor wash fills, paper grain texture,
     warm amber color grade, sketchbook artbook quality,
     pure visual zero text zero labels zero words,
     hands allowed holding cup edge (no face),
     no CGI, no 3D render, no photorealism, no plastic cup,
     9:16 vertical 4K"

  flow_prompt 패턴:
    "extreme slow motion espresso extraction, golden crema building up slowly,
     fluid dynamics visible in amber liquid, micro steam wisps rising,
     warm cinematic lighting, 9:16 vertical 4K"

▶ TYPE E — SCIENCE_DATA (과학 · 수치 · 비교 · 성분 · 차이점)
  트리거: 온도, pH, 산도, 성분, 카페인, 비율, 수치, 퍼센트, 차이, 비교,
          vs, 다른 점, 같은 점, 롱블랙, 아메리카노 차이 등
  visual_source: "ai"

  ★★ SCIENCE_DATA 이미지 작성 핵심 원칙 ★★
  FLUX는 "개념"을 묘사하면 플로우차트·흩어진 도형·추상 형태를 만든다.
  반드시 "스튜디오에서 실제로 촬영할 수 있는 피사체"를 묘사한다.
  모든 데이터와 비교는 실제 음료·용기·재료의 물리적 차이(색·투명도·양·높이)로 표현한다.

  금지 단어: "abstract", "geometric", "floating spheres", "zones", "conceptual",
             "infographic", "chart", "graph", "diagram", "label", "molecular cluster"
  → 이 단어들이 있으면 플로우차트 또는 SF 그래픽이 나온다.

  [하위패턴 1 — 두 음료 나란히 비교] 아메리카노/롱블랙처럼 두 음료를 실제로 나란히 놓는다.
    "Two identical tall clear glasses placed side by side on [dark marble/light marble] surface —
     LEFT glass: [음료1 구체 묘사: e.g. 'lighter translucent coffee-brown liquid, ice cubes visible,
       water poured first creating uniform diluted color throughout'],
     RIGHT glass: [음료2 구체 묘사: e.g. 'darker concentrated espresso sitting on top of cold water,
       visible dark-to-light gradient layer from top to bottom, ice cubes underneath'],
     dramatic side lighting from left revealing liquid transparency and color depth difference,
     condensation droplets on both glass exteriors,
     delicate ink outlines, soft watercolor wash fills showing liquid layers,
     warm cream paper texture background, sketchbook artbook quality,
     pure visual zero text zero labels zero words,
     no people, no CGI, no 3D render, no photorealism, 9:16 vertical 4K"

  [하위패턴 2 — 비율 비커] 물·에스프레소 비율을 실험실 계량 용기로 물리적으로 표현한다.
    "Two clear glass beakers or measuring cylinders placed side by side on dark surface —
     LEFT container: [재료A 묘사: e.g. 'filled 3/4 height with clear water,
       tiny espresso shot layer settling at bottom, amber tint diffusing upward'],
     RIGHT container: [재료B 묘사: e.g. 'filled 1/2 height with concentrated espresso,
       dark rich brown throughout with golden crema ring at surface'],
     [fill height difference clearly visible showing volume ratio],
     dramatic overhead or 45-degree angle studio lighting,
     dark matte surface, warm amber studio light from left,
     delicate ink lines, watercolor wash fills, paper grain texture,
     warm amber and cream tones, sketchbook artbook quality,
     pure visual zero text zero labels zero words zero numbers,
     no people, no CGI, no photorealism, 9:16 vertical 4K"

  [하위패턴 3 — 재료 클로즈업 대비] 핵심 재료 하나를 극단 클로즈업해 성분·질감 차이를 보인다.
    "Extreme macro close-up of [핵심 재료: e.g. 'espresso crema surface' or
     'coffee grounds texture in portafilter' or 'ice melt pattern in cold brew'],
     [재료의 구체적 물리 묘사: e.g. 'golden-brown crema with tiger-stripe natural oil pattern,
       micro bubbles visible, coffee lipids glistening under warm light'],
     extreme close-up detail, delicate ink linework,
     warm amber watercolor wash, paper grain texture, bokeh background,
     sketchbook artbook quality, real texture visible,
     pure visual zero text zero labels zero words,
     no people, no CGI, no 3D render, no photorealism, 9:16 vertical 4K"

  flow_prompt 패턴:
    "two drinks side by side, liquid layers slowly settling and separating,
     color contrast becoming more vivid, condensation forming on glass,
     warm cinematic lighting, 9:16 vertical 4K"

▶ TYPE F — CINEMATIC (역사 · 문화 · 스토리 · 분위기)
  트리거: 역사, 기원, 전설, 카페, 문화, 시대, 유래, 퍼졌다, 전파
  visual_source: "photo"
  image_prompt 패턴(Unsplash 검색어):
    "coffee cafe vintage atmospheric warm light barista"
  flow_prompt 패턴:
    "slow cinematic camera drift, warm golden atmosphere,
     film grain visible, 9:16 vertical 4K"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[나레이션 작성 원칙 — ElevenLabs 더빙용 해설 대본]

이 채널의 나레이션은 한 사람이 60~75초 동안 이어서 들려주는 '짧은 과학 해설'이다.
12개 씬 narration 을 순서대로 이어 읽었을 때 하나의 이야기로 들려야 한다.

▶ 이야기 구조 (반드시 이 흐름)
  훅(의외의 사실) → 궁금증 → 차이가 생기는 지점 → 왜 그런가(원리) → 그래서 무엇이 달라지나 → 한 줄 결론 → 브랜드 멘트
  - "다르다"만 반복하지 말고, 반드시 "왜" 다른지 인과를 설명한다. (예: 무엇을 먼저 붓기 때문에 → 무엇이 어떻게 되고 → 그래서 맛·향이 어떻다)
  - 각 씬은 앞 씬을 받아 이어진다. 필요한 곳에 이음말을 씬 첫머리에 넣는다.
    (그런데 / 그래서 / 바로 이 때문에 / 반대로 / 결국 / 여기서 재미있는 건)

▶ 분량
  - 씬당 공백 제외 18~40자, 1~2문장.
  - 12씬 narration_tts 합계 공백 제외 310~380자 (ElevenLabs 실측 초당 약 4.9자 → 65~75초).

▶ 화면을 가리키는 말은 12씬 전체에서 최대 3번
  ("왼쪽이 ~, 오른쪽이 ~", "단면을 보면", "보시다시피", "숫자로 보면" 등)
  - 실사(photo) 씬에서는 화면을 가리키는 말을 쓰지 않는다.
  - 나머지 씬은 해설 문장으로 쓴다. 화면 설명은 그림 위 라벨·데이터가 대신한다.

▶ 말투 (귀로 듣는 문장)
  - 한 문장에 한 가지 정보만. 주어를 빠뜨리지 않는다. ("롱블랙은 ~", "아메리카노는 ~")
  - '~입니다.'로 끝나는 문장이 세 씬 연속 나오지 않게 종결을 섞는다.
    (~죠. / ~거든요. / ~습니다. / ~예요. / 명사로 끝맺기)
  - 괄호, 슬래시, 화살표, 기호(→ / : + ~ %)를 쓰지 않는다.
  - 줄표(—)는 전체에서 2번 이하.

▶ 사실 정확성 (가장 중요)
  - SCA 기준·백과사전 수준에서 확인되는 사실만 쓴다.
  - 출처를 댈 수 없는 수치(두께 mm, pH, 지속 시간 등)는 쓰지 않는다. 모르면 수치 없이 설명한다.
  - 주제와 관계없는 곁가지 사실(예: 원두 원산지)을 끼워 넣지 않는다.

▶ narration 과 narration_tts — 두 필드를 모두 쓴다
  - narration     : 화면 자막용. 숫자·단위를 그대로 써도 된다. (예: "물 150ml에 샷 하나")
  - narration_tts : ElevenLabs 가 읽을 문장. narration 과 내용이 같고 표기만 다르다.
      · 숫자·단위·영문을 모두 한글 읽는 소리로 쓴다.
        예) 150ml → 백오십 밀리리터 / 9 bar → 구 바 / 1950년대 → 천구백오십년대 / pH → 피에이치
      · 아라비아 숫자와 영문 알파벳을 한 글자도 쓰지 않는다.
      · 쉼표는 실제로 숨을 쉬는 자리에만 찍는다.

▶ 오프닝(1씬): 멈춰 서게 만드는 의외의 사실이나 질문.
▶ 클로징(12씬): 반드시 "너도나도아는커피, 오늘도 한 잔 더 알아갔습니다." 로 끝낸다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[12컷 구성 원칙]

정보 전달이 목적이므로 12컷 중 최소 7컷은 반드시 인포그래픽(AI 생성) 씬이어야 한다.
실사(photo) 씬은 오프닝·클로징 분위기 연출용으로 최대 4~5컷으로 제한한다.

컷 1       : 오프닝 훅 — 강한 질문 or 반전 사실 (TYPE F or A, visual_source: "photo" or "ai")
컷 2       : 핵심 비주얼 — 주제 전체 조감 (TYPE E or A, visual_source: "ai")
컷 3       : 배경·원산지·역사 (TYPE C or F, visual_source: "photo")
컷 4~5     : 핵심 과학·구조 설명 (TYPE B or D, visual_source: "ai")
컷 6~8     : 메인 레시피/비교/수치 인포그래픽 (TYPE A or E, visual_source: "ai")
컷 9       : 심화 데이터·수치 (TYPE E, visual_source: "ai")
컷 10      : 분위기 전환 (TYPE F or C, visual_source: "photo")
컷 11      : 완성 비주얼 클로즈업 (TYPE A or D, visual_source: "ai")
컷 12      : 클로징 훅 + 브랜드 멘트 (TYPE F, visual_source: "photo")

[비교 주제 특칙]
주제에 'vs', '차이', '비교', '아메리카노', '롱블랙', '두 가지' 등이 포함되면:
  → TYPE E (SCIENCE_DATA) 씬을 최소 3컷 이상 배치한다.
  → 각 비교 씬은 서로 다른 각도: 물 비율 / 추출 순서 / 맛 프로파일 / 카페인 수치 등.
  → 화면을 가리키는 말은 12씬 전체 최대 3번 규칙을 그대로 지킨다.

[레시피 주제 특칙]
주제에 '레시피', '만들기', '방법', '만드는 법' 등이 포함되면:
  → TYPE A (ASSEMBLY) 씬을 3~4컷 분산 배치한다.
  → 각 ASSEMBLY 씬은 서로 다른 하위패턴을 써야 한다.
     아래 4컷 구성을 기준으로 삼는다:

  ASSEMBLY 컷 1 (재료 클로즈업): 주재료 하나만 단독 강조 — 하위패턴 1 사용
    narration 예시: "재료는 딱 세 가지입니다."
    image_prompt: 하위패턴 1 — Macro hero shot of [핵심 재료] single ingredient floating...

  ASSEMBLY 컷 2 (비율 시각화): 재료 간 양적 비율 — 하위패턴 2 사용
    narration 예시: "양으로 보면 물이 에스프레소의 다섯 배쯤 들어갑니다."
    image_prompt: 하위패턴 2 — Three vessels of different heights...

  ASSEMBLY 컷 3 (폭발 분해도): BASE AT BOTTOM 원칙으로 5재료 수직 분해 — 하위패턴 3 사용
    narration 예시: "순서는 얼음이 먼저, 그다음 물, 마지막이 에스프레소예요."
    image_prompt: 하위패턴 3 — Premium exploded breakdown, BASE AT BOTTOM,
                  Ice Cubes at very bottom → Cold Water → Espresso Shot at top,
                  EXTRA LARGE scale, thin indicator lines only (zero text zero labels),
                  warm beige #EDE6D6 background, Hasselblad 80mm f2.8...

  ASSEMBLY 컷 4 (완성 히어로샷): 완성된 음료 대형 히어로 — 하위패턴 4 사용
    narration 예시: "레이어가 섞이지 않는 게 핵심입니다."
    image_prompt: 하위패턴 4 — Completed [음료명] large hero scale in matte black cup,
                  ice crystals and condensation, distinct liquid layers,
                  Hasselblad H6D-100c 80mm f2.8, 8K real photo...

  → 레시피가 단순하면 3컷으로 줄여도 되나, 하위패턴은 반드시 다른 것 사용.
  → 한 씬에 모든 재료를 몰아넣지 않는다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[신비한 건축사전 도판 데이터 — data_points / callouts]

이미지에는 글자를 넣지 않는다. 대신 합성 단계에서 정확한 한글 라벨과 수치를
펜 선 지시선으로 그림 위에 얹는다. 그 재료가 data_points 와 callouts 다.

▶ data_points (도판 우상단 SPEC 수치, 0~3개)
  - visual_source "ai" 씬 중 수치가 있는 씬에 반드시 작성. 없으면 [].
  - 형식: [{"label": "짧은 항목명", "value": "값+단위"}]
  - label 6자 이내, value 10자 이내. SCA 기준 등 검증 가능한 사실만.
  - 예: [{"label": "pH", "value": "5.0"}, {"label": "카페인", "value": "63mg"},
         {"label": "추출 압력", "value": "9 bar"}]

▶ callouts (그림 속 부위를 가리키는 지시선 라벨, 0~4개)
  - MACHINE / EXTRACTION / SCIENCE_DATA / ASSEMBLY 씬에 2~4개 작성. photo 씬은 [].
  - 형식: [{"text": "라벨", "x": 0.0~1.0, "y": 0.0~1.0}]
  - text 8자 이내 명사형 (예: "크레마층", "포터필터", "찬물 150ml", "얼음").
  - x, y 는 9:16 화면 기준 비율 좌표(좌상단 0,0 / 우하단 1,1)로, 그 부위가 있을 위치다.
    image_prompt 에서 직접 지정한 구도와 반드시 일치시킨다.
      · 피사체는 화면 위쪽 2/3 (y 0.15~0.58) 에 두도록 image_prompt 를 쓴다.
      · 두 대상 나란히 비교 → 왼쪽 대상 x≈0.30, 오른쪽 대상 x≈0.70.
      · 아래→위 층 구조 → 바닥층 y≈0.55, 가운데 y≈0.42, 윗층 y≈0.28.
  - y 0.60 아래는 키워드·자막 자리이므로 쓰지 않는다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[JSON 스키마]
{
  "chapter": "챕터명",
  "title": "주제명",
  "full_narration": "12개 씬 narration을 자연스럽게 이어붙인 전체 낭독 텍스트 (60~75초 분량)",
  "scenes": [
    {
      "scene_no": 1,
      "scene_type": "ASSEMBLY",
      "visual_source": "ai",
      "name": "오프닝 훅",
      "narration": "롱블랙은 물 150ml를 먼저 채우고 샷을 얹습니다.",
      "narration_tts": "롱블랙은 물 백오십 밀리리터를 먼저 채우고 샷을 얹습니다.",
      "image_prompt": "Exploded flat-lay of ice cubes, espresso shot glass, cold water splash arranged vertically from bottom to top — ice at very bottom, each element floating with subtle separation, thin elegant dark guide lines, warm off-white background #FFF8F0, commercial food photography, Hasselblad 80mm f2.8, shallow depth of field, pure visual zero text zero labels zero words, no people, 9:16 vertical 4K",
      "flow_prompt": "ice cubes, espresso, water floating and stacking into tall glass, slow elegant assembly motion, cinematic coffee commercial, 9:16 vertical 4K",
      "sfx": "impact_whoosh",
      "overlay_text": "화면 자막 키워드",
      "data_points": [{"label": "순서", "value": "얼음→물→샷"}],
      "callouts": [{"text": "에스프레소", "x": 0.5, "y": 0.28}, {"text": "찬물", "x": 0.5, "y": 0.42}, {"text": "얼음", "x": 0.5, "y": 0.55}],
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


SCRIPT_MODEL = "claude-sonnet-4-6"
CLOSING_LINE = "너도나도아는커피, 오늘도 한 잔 더 알아갔습니다."
POINTER_PHRASES = ["보시다시피", "왼쪽이", "오른쪽이", "단면을 보면", "위에서부터",
                   "숫자로 보면", "이 비율입니다", "이 순서대로", "화면을 보면", "여기를 보면"]
TTS_CHARS_PER_SEC = 4.9          # ElevenLabs 실측 (project_10: 236자 / 48.5초)
TOTAL_MIN, TOTAL_MAX = 310, 380  # 약 65~75초
SCENE_MIN, SCENE_MAX = 18, 40
_AI_TYPES = {"ASSEMBLY", "MACHINE", "EXTRACTION", "SCIENCE_DATA"}


# ─────────────────────────────────────────────────────────────────────────────
# 공통 헬퍼
# ─────────────────────────────────────────────────────────────────────────────
def _nchars(t: str) -> int:
    return len(re.sub(r"\s", "", t or ""))


def _text_of(response) -> str:
    """응답의 text 블록을 모두 이어 붙인다 (웹검색 결과 블록은 건너뜀)."""
    return "".join(getattr(b, "text", "") for b in response.content if getattr(b, "type", "") == "text")


def _extract_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
    a, b = raw.find("{"), raw.rfind("}")
    if a == -1 or b == -1:
        raise ValueError("응답에서 JSON 을 찾지 못했습니다.")
    return json.loads(raw[a:b + 1])


def _call_json(client, system: str, user: str, max_tokens: int = 12000, retries: int = 1) -> dict:
    last = None
    for _ in range(retries + 1):
        resp = client.messages.create(
            model=SCRIPT_MODEL, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}],
        )
        try:
            return _extract_json(_text_of(resp))
        except Exception as e:      # JSON 이 깨졌으면 한 번 더
            last = e
    raise ValueError(f"대본 JSON 파싱 실패: {last}")


# ─────────────────────────────────────────────────────────────────────────────
# 1) 규칙 검사 (코드로 확실하게 잡을 수 있는 것)
# ─────────────────────────────────────────────────────────────────────────────
def lint_script(data: dict) -> list:
    """대본 규칙 위반 목록을 돌려준다. 빈 리스트면 통과."""
    issues = []
    scenes = data.get("scenes") or []
    if len(scenes) != 12:
        issues.append(f"씬이 12개가 아니라 {len(scenes)}개입니다.")
    total = 0
    pointer_hits = []
    endings = []
    for sc in scenes:
        n = sc.get("scene_no")
        tts = (sc.get("narration_tts") or "").strip()
        if not (sc.get("narration") or "").strip():
            issues.append(f"{n}씬: narration 이 비어 있습니다.")
        if not tts:
            issues.append(f"{n}씬: narration_tts 가 비어 있습니다.")
            continue
        c = _nchars(tts)
        total += c
        if c < SCENE_MIN or c > SCENE_MAX:
            issues.append(f"{n}씬: 낭독 분량 {c}자 (허용 {SCENE_MIN}~{SCENE_MAX}자).")
        if re.search(r"[0-9A-Za-z]", tts):
            issues.append(f"{n}씬: narration_tts 에 숫자·영문이 남아 있습니다 → 한글 소리로: \"{tts}\"")
        if re.search(r"[()/→:+~%<>]", tts):
            issues.append(f"{n}씬: narration_tts 에 기호가 있습니다: \"{tts}\"")
        for ph in POINTER_PHRASES:
            if ph in (sc.get("narration") or ""):
                pointer_hits.append(n)
                if sc.get("visual_source") == "photo":
                    issues.append(f"{n}씬: 실사 씬에 화면 지시어 '{ph}' 가 있습니다.")
                break
        endings.append(tts.rstrip().endswith("니다."))
    if total and not (TOTAL_MIN <= total <= TOTAL_MAX):
        issues.append(f"전체 낭독 {total}자 ≈ {total / TTS_CHARS_PER_SEC:.0f}초 "
                      f"(목표 {TOTAL_MIN}~{TOTAL_MAX}자 ≈ 65~75초).")
    if len(pointer_hits) > 3:
        issues.append(f"화면 지시어가 {len(pointer_hits)}번 (씬 {pointer_hits}) — 최대 3번.")
    run = 0
    for i, e in enumerate(endings, start=1):
        run = run + 1 if e else 0
        if run == 3:
            issues.append(f"'~니다.' 종결이 {i - 2}~{i}씬에서 세 번 연속입니다.")
    em = sum((sc.get("narration_tts") or "").count("—") for sc in scenes)
    if em > 2:
        issues.append(f"줄표(—)가 {em}번 — 최대 2번.")
    if scenes and CLOSING_LINE not in (scenes[-1].get("narration_tts") or ""):
        issues.append(f"12씬이 '{CLOSING_LINE}' 로 끝나지 않습니다.")
    return issues


# ─────────────────────────────────────────────────────────────────────────────
# 2) 사실 검증 (웹 검색)
# ─────────────────────────────────────────────────────────────────────────────
FACT_SYSTEM = """당신은 커피 과학 팩트체커입니다. SCA 기준, 백과사전, 신뢰할 수 있는 커피 전문 자료로 확인합니다.
대본 속 모든 사실 주장(나레이션, 화면 키워드, 데이터 수치, 라벨)을 하나씩 검증하세요.
확인되지 않거나 출처를 찾을 수 없는 수치는 '근거없음'으로 판정합니다.
마지막에 아래 JSON 만 출력하세요 (설명 문장 금지).
{"claims": [{"scene_no": 1, "claim": "검증한 문장 또는 수치", "verdict": "확인|수정필요|근거없음",
             "correction": "수정필요·근거없음일 때 고쳐 쓸 내용 (없으면 빈 문자열)", "source": "근거 URL"}]}"""


def _fact_payload(data: dict) -> str:
    rows = []
    for sc in data.get("scenes", []):
        rows.append({
            "scene_no": sc.get("scene_no"), "narration": sc.get("narration"),
            "overlay_text": sc.get("overlay_text"), "data_points": sc.get("data_points"),
            "callouts": [c.get("text") for c in (sc.get("callouts") or []) if isinstance(c, dict)],
        })
    return json.dumps(rows, ensure_ascii=False, indent=1)


def fact_check(client, topic: str, data: dict) -> dict:
    """웹 검색으로 사실 검증. 웹 검색을 쓸 수 없으면 모델 지식으로만 검증하고 표시한다."""
    user = f"주제: {topic}\n\n검증할 대본:\n{_fact_payload(data)}"
    messages = [{"role": "user", "content": user}]
    try:
        tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 6}]
        resp = client.messages.create(model=SCRIPT_MODEL, max_tokens=8000, system=FACT_SYSTEM,
                                      messages=messages, tools=tools)
        for _ in range(3):   # 긴 검색은 pause_turn 으로 멈춘다 → 이어서 요청
            if getattr(resp, "stop_reason", "") != "pause_turn":
                break
            messages = messages + [{"role": "assistant", "content": resp.content}]
            resp = client.messages.create(model=SCRIPT_MODEL, max_tokens=8000, system=FACT_SYSTEM,
                                          messages=messages, tools=tools)
        result = _extract_json(_text_of(resp))
        result["web_search"] = True
        return result
    except Exception as e:
        print(f"[prompts] 웹 검색 검증 실패 → 모델 지식으로 검증: {e}", flush=True)
    try:
        result = _call_json(client, FACT_SYSTEM, user, max_tokens=6000)
        result["web_search"] = False
        return result
    except Exception as e:
        return {"claims": [], "web_search": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# 3) 자동 수정
# ─────────────────────────────────────────────────────────────────────────────
REVISE_RULES = """당신은 '너도나도아는커피' 대본 수석 에디터입니다.
초안 JSON 을 받아, 규칙 위반과 팩트체크 결과를 모두 반영한 최종 JSON 전체를 출력합니다.
- 팩트체크에서 '수정필요'는 correction 대로 고치고, '근거없음' 수치는 삭제하거나 확인된 사실로 바꿉니다.
- data_points 에는 '확인' 판정을 받은 수치만 남깁니다. 없으면 [].
- 12씬 narration 이 하나의 해설로 이어지게 다듬습니다 (훅 → 차이 → 왜 → 그래서 → 결론).
- narration_tts 는 narration 과 같은 내용을 ElevenLabs 가 읽기 좋게: 숫자·영문·기호 없이 한글 소리로.
- scene_no, scene_type, visual_source, image_prompt, flow_prompt, sfx 는 사실 오류가 없는 한 그대로 둡니다.
- 설명 없이 JSON 전체만 출력합니다."""


def revise_script(client, data: dict, issues: list, facts: dict) -> dict:
    user = (
        "[규칙 위반]\n" + ("\n".join(f"- {i}" for i in issues) or "- 없음") +
        "\n\n[팩트체크 결과]\n" + json.dumps(facts.get("claims", []), ensure_ascii=False, indent=1) +
        "\n\n[초안 JSON]\n" + json.dumps(data, ensure_ascii=False)
    )
    return _call_json(client, SYSTEM_INSTRUCTION + "\n\n" + REVISE_RULES, user, max_tokens=14000)


# ─────────────────────────────────────────────────────────────────────────────
# 공개 API
# ─────────────────────────────────────────────────────────────────────────────
def _finalize(data: dict) -> dict:
    required = {"chapter", "title", "scenes"}
    missing = required - data.keys()
    if missing:
        raise ValueError(f"Claude 응답에 필수 키가 없습니다: {missing}")
    if not isinstance(data["scenes"], list) or not data["scenes"]:
        raise ValueError("scenes 배열이 비어 있습니다.")
    for sc in data["scenes"]:
        sc.setdefault("image_path", "")
        sc.setdefault("image_status", "pending")
        sc.setdefault("video_url", "")
        sc.setdefault("status", "pending")
        sc.setdefault("data_points", [])
        sc.setdefault("callouts", [])
        if not (sc.get("narration_tts") or "").strip():
            sc["narration_tts"] = sc.get("narration", "")
        if not sc.get("visual_source"):
            sc["visual_source"] = "ai" if sc.get("scene_type", "") in _AI_TYPES else "photo"
    # 음성은 narration_tts 합본으로 만든다 (컷 길이 배분도 이 텍스트 기준)
    data["full_narration"] = " ".join(
        (sc.get("narration_tts") or "").strip() for sc in data["scenes"]
        if (sc.get("narration_tts") or "").strip()
    )
    return data


def generate_script_and_prompts(api_key: str, chapter: str, topic: str, progress=None) -> dict:
    """
    12컷 대본 생성 → 규칙 검사 → 웹 검색 팩트체크 → 자동 수정 → 재검사(필요 시 1회 더 수정).
    반환 dict 의 "verification" 에 검증 기록(판정·출처·남은 문제)을 담는다.
    progress: 선택 — progress(메시지) 로 진행 단계를 화면에 알린다.
    """
    say = progress or (lambda m: None)
    client = anthropic.Anthropic(api_key=api_key)

    user_prompt = (
        f"챕터: '{chapter}', 주제: '{topic}'.\n\n"
        "아래 조건을 모두 지켜서 12컷 대본을 JSON으로 출력해줘.\n\n"
        "① 씬 유형(scene_type)과 visual_source를 자동 판단할 것.\n"
        "② 인포그래픽(visual_source: 'ai') 씬이 최소 7컷 이상 포함될 것.\n"
        "③ narration 은 12씬이 한 편의 해설로 이어지게: 훅 → 차이 → 왜(원리) → 그래서 → 결론.\n"
        "   씬당 공백 제외 18~40자, 합계 310~380자. 화면을 가리키는 말은 전체 최대 3번.\n"
        "④ 모든 씬에 narration(자막용)과 narration_tts(ElevenLabs 낭독용, 숫자·영문을 한글 소리로)를 함께 쓸 것.\n"
        "   확인할 수 없는 수치는 쓰지 말 것.\n"
        "⑤ image_prompt: 'ai' 씬은 FLUX 영문 프롬프트, 'photo' 씬은 Unsplash 검색 키워드.\n"
        "⑥ 'ai' 씬은 data_points(확인된 수치만)와 callouts(지시선 라벨+좌표)를 작성할 것. photo 씬은 둘 다 []."
    )

    say("① 초안 작성 중…")
    draft = _call_json(client, SYSTEM_INSTRUCTION, user_prompt, max_tokens=12000)
    draft_issues = lint_script(draft)

    say("② 사실 검증 중 (웹 검색)…")
    facts = fact_check(client, topic, draft)
    flagged = [c for c in facts.get("claims", []) if c.get("verdict") in ("수정필요", "근거없음")]

    data, rounds = draft, 0
    if draft_issues or flagged:
        say("③ 검증 결과 반영해 자동 수정 중…")
        data = revise_script(client, draft, draft_issues, facts)
        rounds = 1
        remaining = lint_script(data)
        if remaining:
            say("④ 남은 문제 한 번 더 수정 중…")
            data = revise_script(client, data, remaining, {"claims": []})
            rounds = 2
    data = _finalize(data)

    final_issues = lint_script(data)
    total = sum(_nchars(sc.get("narration_tts", "")) for sc in data["scenes"])
    data["verification"] = {
        "web_search":      facts.get("web_search", False),
        "claims":          facts.get("claims", []),
        "draft_issues":    draft_issues,
        "revise_rounds":   rounds,
        "remaining_issues": final_issues,
        "tts_chars":       total,
        "est_seconds":     round(total / TTS_CHARS_PER_SEC),
    }
    say("✅ 대본 완성")
    return data
