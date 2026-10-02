# src/scenestory.py
# Making Shorts Engine — SceneStory 채널 (일본 시니어 대상 · 9:16 쇼츠)
#
# 한 편 = 소설·영화·드라마·시·역사 속 사랑의 한 장면 + 시나리오 작가의 해설 (60~75초).
# 커피 채널의 제작 흐름(대본 → 이미지 → 음성 → 영상 → 합성 → 업로드 정보)을 그대로 쓰고,
# 채널마다 다른 것만 이 파일에 모은다.
#
#   씬 유형 3가지
#     TITLE  : 작품 타이틀 카드 (AI 그림 없음, 서버에서 바로 그림 + 6초 영상)
#     SKETCH : 작품 속 장면의 기억 — 펜-잉크 수채화. 사람은 뒷모습·실루엣·손만 (얼굴 금지)
#     PHOTO  : 오늘의 장소·물건 — 실사 사진. 사람 얼굴 금지
#
#   실측 기준 (2026-10-01): 일본어 목소리 wcs09USXSN5Bl7FXohVZ → 초당 4.13자 (공백 제외, 문장부호 포함)

import json
import os
import re
import subprocess

CHANNEL = "scenestory"
BRAND = "SceneStory"
BRAND_TTS = "シーンストーリー"
JA_VOICE_ID = "wcs09USXSN5Bl7FXohVZ"
JA_CPS = 4.13

GENRES = {"小説": "소설", "映画": "영화", "ドラマ": "드라마", "詩": "시", "歴史": "역사"}

CLOSING_PRESETS = [
    "あの場面の、その先へ。SceneStory。",
    "物語は、あなたの中で続きます。SceneStory。",
]
DEFAULT_CLOSING = CLOSING_PRESETS[0]

LENGTH_PRESETS = {
    "short": {"label": "짧게 (30~39초)",       "cuts": 8,  "total": (130, 160)},
    "mid":   {"label": "보통 (45~54초)",       "cuts": 10, "total": (185, 225)},
    "long":  {"label": "길게 (60~75초) · 기본", "cuts": 12, "total": (250, 310)},
}
DEFAULT_LENGTH = "long"

SS_TYPES = {"TITLE", "SKETCH", "PHOTO"}
SFX_OK = {"", "ambient_cafe", "deep_bass", "impact_whoosh"}

BGM_PROMPT = (
    "Gentle cinematic solo piano with soft strings, nostalgic and bittersweet romantic mood, "
    "slow 68 BPM, warm and intimate, sits quietly under a Japanese voice-over, "
    "no vocals, no drums, no sudden changes, soft ending."
)

# ── 이미지 화풍 (2026-10-01 Z-Image 로 실제 생성해 확인한 문구) ─────────────────
SKETCH_PREFIX = (
    "Pen-and-ink watercolor sketch on cold-press watercolor paper, cinematic storyboard illustration. "
    "Bold black fineliner ink contour lines with cross-hatching shadows, loose transparent watercolor washes "
    "in sepia, faded indigo, dusty rose and warm lamplight amber that bleed past the ink lines, "
    "white paper left bare for highlights, visible paper grain. Subject: "
)
SKETCH_SUFFIX = (
    " Figures are drawn from behind or in silhouette with no facial features visible. "
    "Generous empty paper in the lower third. No text, no letters, no numbers."
)
PHOTO_PREFIX = "Photorealistic still photograph: "
PHOTO_SUFFIX = " Soft natural light, shallow depth of field. No human faces, no text, no letters."


def closing_tts(text: str) -> str:
    return (text or DEFAULT_CLOSING).replace(BRAND, BRAND_TTS)


# ─────────────────────────────────────────────────────────────────────────────
# 1) 대본
# ─────────────────────────────────────────────────────────────────────────────
SYSTEM = """당신은 유튜브 채널 'SceneStory'의 수석 작가입니다. 일본의 60~70대 시청자를 위해
소설·영화·드라마·시·역사 속 사랑의 한 장면을 시나리오 작가의 눈으로 해부하는 쇼츠 대본을 씁니다.
나레이션은 모두 일본어, 차분하고 품위 있는 です・ます調입니다. 반드시 JSON 만 출력합니다.

[절대 규칙]
- 작품명을 밝힌다. 작품의 사실(연도·방송사·작가·장면 묘사)은 확실한 것만 쓴다. 지어낸 장면·대사 금지.
- 대사 인용은 한 편에 한 번, 15자 이내. 저작권이 끝난 작품(예: 1968년 이전 사망 작가의 소설·시)만 길게 인용 가능.
- 자살·동반자살은 사실로 언급만 하고 방법·장면은 쓰지도 그리지도 않는다. 성적 묘사 금지.
- 배우·실존 인물의 이름은 narration 에는 써도 되지만 image_prompt 에는 절대 쓰지 않는다.
- 숫자는 아라비아 숫자를 쓰지 않는다. narration_tts 에는 한자·가나만 (예: 十時, 一九八三年). 영문은 가타카나로.
- 화면을 가리키는 말(ご覧ください 등) 금지.

[씬 유형 scene_type]
- TITLE : 2컷 고정. 작품 타이틀 카드. image_prompt 는 빈 문자열.
- SKETCH: 작품 속 장면의 기억. image_prompt 는 영문, 한 장의 그림을 단정적으로 서술(한 상태·한 동작).
          사람은 뒷모습·실루엣·손으로만. 얼굴 묘사 금지. 시대·장소·소품을 구체적으로.
- PHOTO : 오늘의 장소·물건(시청자의 현재). image_prompt 는 영문, 한 장의 사진을 단정적으로 서술. 사람 없음.
- image_prompt 금지어: "or", "slightly", "maybe", "portrait", "face", "close-up of a person", 배우 이름, 글자.

[구성 — 12컷 기준, 컷 수가 다르면 비율 유지]
1 PHOTO 훅(오늘의 물건 하나로 그 장면을 불러냄, 첫 문장은 질문이나 반전 사실) → 2 TITLE →
3~9 SKETCH(장면 → 작가의 해부: 왜 이 장면이 먹히는가, 물건·시간·거리의 의미) →
10~11 PHOTO(오늘의 시청자에게 돌아옴) → 마지막 컷 엔딩.

[JSON 스키마]
{
 "title": "편 제목(일본어)",
 "title_card": {"work": "作品名(일본 공식 표기)", "genre": "小説|映画|ドラマ|詩|歴史",
                "year": "一九八三年 처럼 한자", "origin": "방송사·출판사·감독 등 한 줄", "creator": "작가·각본가"},
 "scenes": [
  {"scene_no": 1, "name": "훅", "scene_type": "PHOTO", "visual_source": "ai",
   "narration": "자막용 일본어", "narration_tts": "낭독용 일본어(숫자 한자)", "overlay_text": "화면 키워드 12자 이내",
   "image_prompt": "English, one definitive still", "flow_prompt": "English, one subtle camera or light motion",
   "sfx": "", "status": "pending"}
 ]
}
sfx 는 "", "ambient_cafe", "deep_bass", "impact_whoosh" 중 하나 (대부분 "")."""

FACT_SYSTEM = """당신은 일본 문학·영화·드라마·근현대사 팩트체커입니다. 백과사전·공식 자료·신뢰할 수 있는 기사로 확인합니다.
대본 속 사실 주장(작품명, 연도, 방송사·출판사, 작가, 인물 관계, 장면 묘사, 인용)을 하나씩 검증하세요.
작품에 실제로 없는 장면이나 대사로 보이면 '근거없음'으로 판정합니다.
마지막에 아래 JSON 만 출력하세요 (설명 문장 금지).
{"claims": [{"scene_no": 1, "claim": "검증한 문장", "verdict": "확인|수정필요|근거없음",
             "correction": "고쳐 쓸 내용 (없으면 빈 문자열)", "source": "근거 URL"}]}"""

REVISE_RULES = """초안 JSON 을 받아 규칙 위반과 팩트체크 결과를 모두 반영한 최종 JSON 전체를 출력합니다.
- '수정필요'는 correction 대로, '근거없음'은 삭제하거나 확인된 사실로 바꿉니다.
- 글자 수가 범위를 벗어나면 narration·narration_tts 를 함께 늘리거나 줄입니다.
- 설명 없이 JSON 전체만 출력합니다."""


def _spec(length: str) -> dict:
    return LENGTH_PRESETS.get(length) or LENGTH_PRESETS[DEFAULT_LENGTH]


def _nchars(t: str) -> int:
    return len(re.sub(r"\s", "", t or ""))


def _system(closing: str, length: str) -> str:
    sp = _spec(length)
    return (SYSTEM + f"\n\n[이번 편 분량]\n- 컷 수 {sp['cuts']}개, narration_tts 합계(공백 제외) "
            f"{sp['total'][0]}~{sp['total'][1]}자.\n- 마지막 컷 narration 은 정확히 「{closing}」.")


def _user(form: dict, length: str) -> str:
    sp = _spec(length)
    return (
        f"장르: {form.get('genre', '')}\n작품: {form.get('work', '')}\n"
        f"작품 정보(연도·방송사 등, 확인용): {form.get('info', '') or '(없음 — 확실한 것만 쓰기)'}\n"
        f"해부할 장면: {form.get('scene', '')}\n"
        f"작가 해설(이 관점을 중심으로): {form.get('note', '') or '(없음 — 장면의 핵심 물건·시간·거리로 해부)'}\n\n"
        f"{sp['cuts']}컷 대본을 JSON 으로 출력해줘."
    )


def lint(data: dict, closing: str, length: str) -> list:
    sp = _spec(length)
    issues = []
    scenes = data.get("scenes") or []
    if len(scenes) != sp["cuts"]:
        issues.append(f"컷이 {sp['cuts']}개가 아니라 {len(scenes)}개입니다.")
    titles = [s for s in scenes if s.get("scene_type") == "TITLE"]
    if len(titles) != 1:
        issues.append(f"TITLE 컷이 1개가 아니라 {len(titles)}개입니다.")
    total = 0
    for s in scenes:
        n = s.get("scene_no")
        st = s.get("scene_type")
        if st not in SS_TYPES:
            issues.append(f"{n}컷 scene_type '{st}' 는 TITLE/SKETCH/PHOTO 가 아닙니다.")
        tts = s.get("narration_tts") or ""
        total += _nchars(tts)
        if re.search(r"[0-9０-９]", tts):
            issues.append(f"{n}컷 narration_tts 에 아라비아 숫자가 있습니다 → 한자로.")
        if re.search(r"[A-Za-zＡ-Ｚａ-ｚ]", tts.replace(BRAND, "")):
            issues.append(f"{n}컷 narration_tts 에 영문이 있습니다 → 가타카나로.")
        ip = (s.get("image_prompt") or "").lower()
        if st in ("SKETCH", "PHOTO"):
            if not ip:
                issues.append(f"{n}컷 image_prompt 가 비어 있습니다.")
            for w in (" or ", "slightly", "maybe", "portrait", "close-up of a person"):
                if w in f" {ip} ":
                    issues.append(f"{n}컷 image_prompt 에 금지어 '{w.strip()}' 가 있습니다.")
            if re.search(r"\bface\b", ip) and "no face" not in ip and "facial" not in ip:
                issues.append(f"{n}컷 image_prompt 에 얼굴(face) 묘사가 있습니다.")
    lo, hi = sp["total"]
    if not lo <= total <= hi:
        issues.append(f"narration_tts 합계 {total}자 — {lo}~{hi}자로 맞춰야 합니다.")
    if scenes and (scenes[-1].get("narration") or "").strip() != closing:
        issues.append(f"마지막 컷 narration 이 엔딩 멘트 「{closing}」 가 아닙니다.")
    return issues


def _fact_payload(data: dict) -> str:
    rows = [{"title_card": data.get("title_card")}]
    for sc in data.get("scenes", []):
        rows.append({"scene_no": sc.get("scene_no"), "narration": sc.get("narration"),
                     "overlay_text": sc.get("overlay_text")})
    return json.dumps(rows, ensure_ascii=False, indent=1)


RESEARCH_SYSTEM = """당신은 일본 문학·영화·드라마·근현대사 자료 조사원입니다. 웹 검색으로 작품의 기본 정보를 찾습니다.
작품명은 한국어나 다른 표기로 들어올 수 있습니다. 일본에서 쓰는 공식 표기를 찾아 주세요.
역사(실제 사건)라면 work 에 사건명, year 에 일어난 해, origin 에 장소·관련 기관, creator 에 중심 인물을 씁니다.
확인하지 못한 칸은 빈 문자열로 둡니다. 추측해서 채우지 않습니다.
마지막에 아래 JSON 만 출력하세요 (설명 문장 금지).
{"found": true, "work": "일본 공식 표기", "year": "1983年", "origin": "방송사·출판사·제작사 등", "creator": "작가·각본가·감독",
 "summary": "줄거리·배경 두세 문장 (한국어)", "source": "근거 URL"}"""


def research_work(client, form: dict) -> dict:
    """작품 정보(공식 표기·연도·방송사·작가)를 웹 검색으로 찾는다. 사용자가 몰라도 되게."""
    from src.prompts import SCRIPT_MODEL, _text_of, _extract_json
    user = (f"장르: {form.get('genre', '')}\n작품: {form.get('work', '')}\n"
            f"참고(사용자가 아는 정보, 비어 있을 수 있음): {form.get('info', '')}\n"
            f"해부할 장면(작품 특정에 참고): {form.get('scene', '')}")
    messages = [{"role": "user", "content": user}]
    try:
        tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 4}]
        resp = client.messages.create(model=SCRIPT_MODEL, max_tokens=3000, system=RESEARCH_SYSTEM,
                                      messages=messages, tools=tools)
        for _ in range(3):
            if getattr(resp, "stop_reason", "") != "pause_turn":
                break
            messages = messages + [{"role": "assistant", "content": resp.content}]
            resp = client.messages.create(model=SCRIPT_MODEL, max_tokens=3000, system=RESEARCH_SYSTEM,
                                          messages=messages, tools=tools)
        r = _extract_json(_text_of(resp))
        r["web_search"] = True
        return r
    except Exception as e:
        print(f"[scenestory] 작품 정보 조사 실패: {e}", flush=True)
        return {"found": False, "web_search": False, "error": str(e)}


def fact_check(client, form: dict, data: dict) -> dict:
    from src.prompts import SCRIPT_MODEL, _text_of, _extract_json, _call_json
    user = f"작품: {form.get('work', '')} ({form.get('genre', '')})\n\n검증할 대본:\n{_fact_payload(data)}"
    messages = [{"role": "user", "content": user}]
    try:
        tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 6}]
        resp = client.messages.create(model=SCRIPT_MODEL, max_tokens=8000, system=FACT_SYSTEM,
                                      messages=messages, tools=tools)
        for _ in range(3):
            if getattr(resp, "stop_reason", "") != "pause_turn":
                break
            messages = messages + [{"role": "assistant", "content": resp.content}]
            resp = client.messages.create(model=SCRIPT_MODEL, max_tokens=8000, system=FACT_SYSTEM,
                                          messages=messages, tools=tools)
        result = _extract_json(_text_of(resp))
        result["web_search"] = True
        return result
    except Exception as e:
        print(f"[scenestory] 웹 검색 검증 실패 → 모델 지식으로 검증: {e}", flush=True)
    try:
        result = _call_json(client, FACT_SYSTEM, user, max_tokens=6000)
        result["web_search"] = False
        return result
    except Exception as e:
        return {"claims": [], "web_search": False, "error": str(e)}


def finalize(data: dict, closing: str) -> dict:
    scenes = data.get("scenes") or []
    if not scenes:
        raise ValueError("scenes 배열이 비어 있습니다.")
    for i, sc in enumerate(scenes, start=1):
        sc["scene_no"] = i
        if sc.get("scene_type") not in SS_TYPES:
            sc["scene_type"] = "SKETCH"
        sc["visual_source"] = "ai"                      # Unsplash 를 쓰지 않는다
        sc.setdefault("image_path", "")
        sc.setdefault("image_status", "pending")
        sc.setdefault("video_url", "")
        sc.setdefault("status", "pending")
        sc["data_points"], sc["callouts"] = [], []
        if sc.get("sfx") not in SFX_OK:
            sc["sfx"] = ""
        if not (sc.get("narration_tts") or "").strip():
            sc["narration_tts"] = sc.get("narration", "")
        if not sc.get("flow_prompt"):
            sc["flow_prompt"] = sc.pop("video_prompt", "") or "slow gentle push-in, soft light flicker"
        if sc["scene_type"] == "TITLE":
            sc["image_prompt"] = ""
    last = scenes[-1]
    last["narration"] = closing
    last["narration_tts"] = closing_tts(closing)
    data["full_narration"] = "".join((sc.get("narration_tts") or "").strip() for sc in scenes)
    data.setdefault("title_card", {})
    return data


def generate_script(api_key: str, form: dict, progress=None, closing: str = "", length: str = "") -> dict:
    """초안 → 규칙 검사 → 웹 검색 팩트체크 → 자동 수정(최대 2회) → 마무리."""
    import anthropic
    from src.prompts import _call_json
    say = progress or (lambda m: None)
    closing = (closing or DEFAULT_CLOSING).strip()
    length = length if length in LENGTH_PRESETS else DEFAULT_LENGTH
    client = anthropic.Anthropic(api_key=api_key)
    system = _system(closing, length)

    say("⓪ 작품 정보 찾는 중 (웹 검색)…")
    research = research_work(client, form)
    form = dict(form)
    if research.get("found") and research.get("work"):
        form["work"] = research["work"]
        known = " · ".join(x for x in (research.get("year"), research.get("origin"), research.get("creator")) if x)
        form["info"] = "; ".join(x for x in (form.get("info", ""), known,
                                             f"줄거리: {research.get('summary', '')}") if x)
        say(f"　→ 『{form['work']}』 {known}")
    else:
        say("　→ 작품 정보를 찾지 못했습니다. 입력한 내용만으로 쓰고, 사실 확인 단계에서 다시 검증합니다.")

    say("① 초안 작성 중…")
    draft = _call_json(client, system, _user(form, length), max_tokens=12000)
    issues = lint(draft, closing, length)

    say("② 작품 사실 확인 중 (웹 검색)…")
    facts = fact_check(client, form, draft)
    flagged = [c for c in facts.get("claims", []) if c.get("verdict") in ("수정필요", "근거없음")]

    data, rounds = draft, 0
    for _ in range(2):
        if not (issues or flagged):
            break
        say("③ 검증 결과 반영해 자동 수정 중…")
        user = ("[규칙 위반]\n" + ("\n".join(f"- {i}" for i in issues) or "- 없음") +
                "\n\n[팩트체크 결과]\n" + json.dumps(flagged, ensure_ascii=False, indent=1) +
                "\n\n[초안 JSON]\n" + json.dumps(data, ensure_ascii=False))
        data = _call_json(client, system + "\n\n" + REVISE_RULES, user, max_tokens=14000)
        rounds += 1
        flagged = []
        issues = lint(data, closing, length)
    data = finalize(data, closing)
    final_issues = lint(data, closing, length)
    total = sum(_nchars(sc.get("narration_tts", "")) for sc in data["scenes"])
    data["verification"] = {
        "web_search": facts.get("web_search", False), "claims": facts.get("claims", []),
        "revise_rounds": rounds, "remaining_issues": final_issues,
        "tts_chars": total, "est_seconds": round(total / JA_CPS),
    }
    data["closing"], data["length"] = closing, length
    data["form"], data["research"] = form, research
    if not research.get("found"):
        data["verification"]["remaining_issues"].append(
            "작품 정보를 웹에서 찾지 못했습니다. 타이틀 카드의 연도·방송사·작가를 꼭 확인하세요.")
    say("✅ 대본 완성")
    return data


# ─────────────────────────────────────────────────────────────────────────────
# 2) 글꼴 · 타이틀 카드
# ─────────────────────────────────────────────────────────────────────────────
_NOTO = "/usr/share/fonts/opentype/noto/"
JP_SANS_BOLD = _NOTO + "NotoSansCJK-Bold.ttc"
JP_SERIF_BOLD = _NOTO + "NotoSerifCJK-Bold.ttc"


def jp_font(path: str, size: int):
    """Noto CJK 묶음 파일의 0번이 일본어(JP) 글꼴. 없으면 나눔 → 기본 글꼴."""
    from PIL import ImageFont
    for p, idx in ((path, 0), ("/usr/share/fonts/truetype/nanum/NanumBarunGothicBold.ttf", 0)):
        try:
            if os.path.exists(p):
                return ImageFont.truetype(p, size, index=idx)
        except Exception:
            continue
    return ImageFont.load_default()


def wrap_ja(draw, text: str, font, max_w: int, max_lines: int = 3) -> list:
    """일본어는 띄어쓰기가 없으므로 글자 단위로 줄을 나눈다. 문장부호는 줄 앞에 오지 않게."""
    lines, cur = [], ""
    for ch in text:
        if draw.textlength(cur + ch, font=font) <= max_w:
            cur += ch
            continue
        if ch in "、。」』）！？…" and cur:
            cur += ch                                  # 문장부호는 앞 줄 끝에 붙인다
            continue
        lines.append(cur)
        cur = ch
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:-1] + "…"
    return lines


def render_title_card(title_card: dict, out_png: str, W: int = 1080, H: int = 1920) -> str:
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, H), (24, 18, 30))
    d = ImageDraw.Draw(img)
    for y in range(H):                                 # 위 짙은 보라 → 아래 짙은 갈색
        t = y / H
        d.line([(0, y), (W, y)], fill=(int(36 - 8 * t), int(22 - 4 * t), int(52 - 30 * t)))
    gold, cream, dim = (200, 150, 105), (238, 222, 205), (170, 150, 140)
    tc = title_card or {}
    f_brand = jp_font(JP_SERIF_BOLD, 40)
    d.text((W / 2, 300), "SceneStory", font=f_brand, fill=gold, anchor="ma")
    d.line([(W / 2 - 160, 370), (W / 2 + 160, 370)], fill=(150, 110, 80), width=2)
    genre = tc.get("genre", "")
    if genre:
        d.text((W / 2, 560), f"― {genre} ―", font=jp_font(JP_SANS_BOLD, 44), fill=dim, anchor="ma")
    work = (tc.get("work") or "").strip("『』「」")
    label = f"『{work}』" if work else ""
    size = 110                                         # 한 줄에 들어가면 한 줄로 (최소 76)
    f_work = jp_font(JP_SERIF_BOLD, size)
    while size > 76 and d.textlength(label, font=f_work) > W - 140:
        size -= 4
        f_work = jp_font(JP_SERIF_BOLD, size)
    if d.textlength(label, font=f_work) <= W - 140:
        lines = [label]
    else:                                              # 긴 제목은 두 줄로 반씩 (한 글자만 넘어가지 않게)
        f_work = jp_font(JP_SERIF_BOLD, 96)
        half = (len(label) + 1) // 2
        lines = [label[:half], label[half:]]
    y = 680
    for ln in lines:
        d.text((W / 2, y), ln, font=f_work, fill=cream, anchor="ma")
        y += int(f_work.size * 1.3)
    y += 30
    f_info = jp_font(JP_SANS_BOLD, 46)
    for txt in (tc.get("year", ""), tc.get("origin", ""), tc.get("creator", "")):
        if txt:
            y += 30
            for ln in wrap_ja(d, txt, f_info, W - 200, max_lines=2):
                d.text((W / 2, y), ln, font=f_info, fill=dim, anchor="ma")
                y += 64
    img.save(out_png, "PNG")
    return out_png


def make_still_clip(png: str, out_mp4: str, seconds: float = 6.0) -> str:
    """타이틀 카드 한 장 → 아주 느리게 다가가는 6초 영상 (MiniMax 를 쓰지 않음)."""
    frames = int(seconds * 25)
    vf = (f"scale=2160:-1,zoompan=z='min(zoom+0.0006,1.05)':d={frames}:"
          f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=25,format=yuv420p")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", png, "-vf", vf,
           "-t", f"{seconds}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", out_mp4]
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode(errors="replace")[-400:])
    return out_mp4


def prepare_title_scenes(state: dict) -> None:
    """TITLE 컷은 대본이 나오자마자 그림과 영상을 서버에서 만들어 '완료' 상태로 둔다."""
    pdir = os.path.join(state.get("project_dir", "projects/tmp"), "media")
    os.makedirs(pdir, exist_ok=True)
    for sc in state.get("scenes", []):
        if sc.get("scene_type") != "TITLE":
            continue
        n = int(sc.get("scene_no", 0))
        png = render_title_card(state.get("title_card") or {}, os.path.join(pdir, f"title_{n:02d}.png"))
        mp4 = make_still_clip(png, os.path.join(pdir, f"title_{n:02d}.mp4"))
        sc.update(image_path=png, image_local=png, reference_image_url=png, image_status="done",
                  _img_source="title", video_url=mp4, video_local=mp4, status="done")


# ─────────────────────────────────────────────────────────────────────────────
# 3) 합성용 자막 오버레이 (박스 없음, 큰 자막)
# ─────────────────────────────────────────────────────────────────────────────
def render_overlay_png(scene: dict, scene_no: int, total: int, out_path: str, light: bool,
                       work: str = "", W: int = 1080, H: int = 1920) -> str:
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if light:
        text, accent, stroke = (38, 26, 20, 255), (140, 82, 60, 255), (247, 240, 228, 235)
    else:
        text, accent, stroke = (246, 236, 222, 255), (214, 168, 120, 255), (12, 8, 10, 230)

    def _t(xy, s, f, fill, sw, anchor="la"):
        if not light:
            d.text((xy[0] + 3, xy[1] + 4), s, font=f, fill=(0, 0, 0, 110), anchor=anchor,
                   stroke_width=sw, stroke_fill=(0, 0, 0, 110))
        d.text(xy, s, font=f, fill=fill, anchor=anchor, stroke_width=sw, stroke_fill=stroke)

    m = 60
    f_head = jp_font(JP_SERIF_BOLD, 34)
    _t((m, m + 10), "SceneStory", f_head, accent, 3)
    if work and scene.get("scene_type") != "TITLE":
        w = work if work.startswith("『") else f"『{work}』"
        _t((W - m, m + 10), w, jp_font(JP_SANS_BOLD, 34), text, 3, anchor="ra")

    kw = (scene.get("overlay_text") or "").strip()
    if kw and scene.get("scene_type") != "TITLE":
        f_kw = jp_font(JP_SERIF_BOLD, 84)
        ky = int(H * 0.60)
        for i, ln in enumerate(wrap_ja(d, kw, f_kw, W - 2 * m, max_lines=2)):
            _t((W // 2, ky + i * 100), ln, f_kw, accent, 6, anchor="ma")

    narr = (scene.get("narration") or "").strip()
    if narr:
        f_sub = jp_font(JP_SANS_BOLD, 72)               # 커피 채널(58)보다 크게 — 시니어 시청자
        y0 = int(H * 0.735)
        for i, ln in enumerate(wrap_ja(d, narr, f_sub, W - 2 * m - 20, max_lines=3)):
            _t((W // 2, y0 + i * 94), ln, f_sub, text, 7, anchor="ma")
    img.save(out_path, "PNG")
    return out_path


# ─────────────────────────────────────────────────────────────────────────────
# 4) 업로드 정보 (일본어)
# ─────────────────────────────────────────────────────────────────────────────
PACK_SYSTEM = """당신은 일본 유튜브 쇼츠 채널 'SceneStory'(작품 속 사랑의 명장면 해설, 시청자 60~70대)의 업로드 담당자입니다.
대본을 읽고 업로드 정보를 일본어로 만듭니다. 규칙:
- title: 40자 이내. 작품명(『』)을 앞에, 장면의 물건·순간을 뒤에. 과장·선정적 표현 금지.
- description: 2~3줄 일본어. 첫 줄에 핵심 한 줄, 마지막 줄에 해시태그 3개.
- hashtags: description 의 해시태그 3개 (배열, 일본어).
- tags: 검색어 8~12개 (배열, 일본어). 작품명·장르·연대 중심. '#' 없이.
- pinned_comment: 시청자가 짧게 답할 수 있는 일본어 질문 하나 (추억을 묻는 형식 권장).
- next_teaser: 다음 편 예고 한 줄 (일본어).
- thumb_line1, thumb_line2: 섬네일 두 줄, 각 9자 이내 일본어. 윗줄은 작품명.
- thumb_accent: 두 줄 안에 그대로 있는 단어 하나.
이모지는 pinned_comment 에만 1개까지. JSON 만 출력:
{"title": "", "description": "", "hashtags": [], "tags": [], "pinned_comment": "", "next_teaser": "", "thumb_line1": "", "thumb_line2": "", "thumb_accent": ""}"""

UPLOAD_SETTINGS = [
    ("카테고리", "映画とアニメ (영화/애니메이션) 또는 エンターテイメント"),
    ("아동용 여부", "아니요, 아동용이 아닙니다"),
    ("동영상 언어", "일본어"),
    ("변경되거나 합성된 콘텐츠", "실사 AI 사진이 들어가므로 '예'"),
    ("섬네일", "Shorts 맞춤 섬네일은 데스크톱 YouTube Studio 에서 올립니다"),
]
