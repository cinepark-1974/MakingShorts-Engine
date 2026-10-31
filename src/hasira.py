# src/hasira.py
# HASIRA_yo! 제작 라인 — 넌버벌 음악 롱폼 (16:9 · 30분~2시간)
#
# 흐름
#   ① 기획   : 키워드 하나 → Claude 가 제목·그림 프롬프트·움직임 프롬프트·곡 목록(JSON)
#   ② 그림   : Replicate flux-dev 16:9 한 장 (또는 직접 올린 그림)
#   ③ 움직임 : MiniMax 6초 클립 → 앞으로+거꾸로 이어 붙여 끊김 없는 루프 (또는 정지 그림)
#   ④ 음악   : ElevenLabs Music / Google Lyria 3.5 / 직접 올린 곡(Suno 등)
#   ⑤ 합성   : 곡마다 음량 맞춤 → 크로스페이드 연결 → 루프 영상을 스트림 복사로 반복 → 1시간 MP4
#   ⑥ 전달   : Cloudflare R2 에 올리고 7일짜리 내려받기 링크
#   ⑦ 업로드 : 일본어 제목·설명 + 곡 목록 타임스탬프(유튜브 챕터)
#
# 오래 걸리는 ③④⑤ 는 백그라운드 스레드에서 돈다(화면이 다시 실행돼도 끊기지 않음).
# 이 모듈 안에서는 st.* 를 호출하지 않는다.
#
# 확인한 사양
#   - ElevenLabs music.compose(prompt, music_length_ms, force_instrumental) → Iterator[bytes] (MP3)
#     엔진 배경음악에서 이미 쓰는 호출 · API 요금 분당 $0.15 (elevenlabs.io/pricing/api)
#   - Lyria 3.5 : client.interactions.create(model="lyria-3.5", input=...) → output_audio.data (base64 MP3)
#     곡당 약 2분, 연주곡은 프롬프트로 지정 (ai.google.dev/gemini-api/docs/music-generation)
#   - 유튜브 챕터 : 첫 줄 00:00, 3개 이상, 오름차순, 각 10초 이상 (support.google.com/youtube/answer/9884579)

import base64
import json
import os
import re
import shutil
import subprocess
import threading
import time

# ── 설정 ──────────────────────────────────────────────────────────────────────
# 아래 수치는 노션 「HASIRA_yo_Manual_v5.0」 기준
#   Export 1920x1080 · 30fps · H.264 · AAC 320kbps / 음량 LUFS -14 / 곡 간 크로스페이드 1~2초
#   화면은 Ken Burns 1~3% 줌, 완전 정지 금지
W, H, FPS = 1920, 1080, 30
XFADE_SEC = 2.0                  # 곡 사이 크로스페이드
FADE_IN_SEC, FADE_OUT_SEC = 2.0, 6.0
LOUDNESS = "loudnorm=I=-14:TP=-1.5:LRA=11"
AUDIO_BITRATE = "320k"
KB_ZOOM = 0.03                   # Ken Burns 최대 3% 확대
KB_PERIOD = 24                   # 확대→원래 크기 한 바퀴(초) — 이음매 없이 반복
BRAND_SIGNATURE = "行福しなさい、癒しなさい。今日もしばらく寄りかかってください。"
BANNED_WORDS = ["cafe music", "jazz", "lo-fi", "lofi", "bgm", "study music", "ai music", "suno",
                "カフェ", "ジャズ", "作業用", "勉強用"]
ORDER_MODES = {"in_order": "번호 순서대로 (반복 없이)", "abacad": "ABACAD — 핵심곡(★ 첫 곡)을 사이사이 반복"}
EL_PRICE_PER_MIN = 0.15          # ElevenLabs Music API (분당, 2026-10 확인)
LYRIA_MODEL = "lyria-3.5"

PROVIDERS = {
    "elevenlabs": "ElevenLabs Music (바로 사용 가능 · 분당 $0.15)",
    "lyria":      "Google Lyria 3.5 (연결 테스트 통과 후 사용)",
    "upload":     "직접 만든 곡 올리기 (MP3)",
}
LENGTH_OPTIONS = {30: "30분", 60: "1시간", 90: "1시간 30분", 120: "2시간"}
VISUAL_MODES = {"motion": "움직이는 그림 (MiniMax 6초 → 끊김 없는 반복)",
                "kenburns": "Ken Burns (그림 한 장에 1~3% 느린 줌 · 비용 없음)"}

_CHANNEL_RULES = """채널: HASIRA_yo! — 힐링과 성장을 위한 감정 기록 채널. 낮과 밤을 가리지 않고, 낭만과 로망이 머무는 순간을 음악으로 기록한다.
포지셔닝: "카페 음악"이 아닌 "영화적 낭만을 일상에 붙이는 채널". 중심 시리즈 「낭만의 공간」 — 영화 속 한 장면처럼 특정 공간에서 흐르는 음악.
대상: 일본 40~60대 + 글로벌 Cinematic Classical 리스너. 색감: 벚꽃 톤(웜 로즈/앰버).
금지어(제목·태그·설명 어디에도 쓰지 않음): cafe music, jazz, lo-fi, BGM, study music, AI music, Suno, カフェ, ジャズ, 作業用, 勉強用."""

_PROMPT_POLICY = """Suno 프롬프트 정책 (곡마다 영어 한 문단, 이 순서 그대로)
1. 장르 선언: "Cinematic romantic classical instrumental" 또는 "Cinematic classical instrumental" + 분위기 형용사
2. Atmosphere: 테마 공간의 감각적 묘사 (시각·촉각·후각)
3. Instruments: 피아노 + 현악 중심 (cello, violin, viola), 보조로 harp, pizzicato, ambient pad
4. Tempo: BPM 54~68 사이 숫자 하나 + 분위기 형용사
5. Guardrails: "No ..." 문장 3개 이상
금지: jazz, 드럼·퍼커션, 전자음·신스, 밝은 고주파, 급격한 다이나믹 변화, 촬영 용어(dolly shot, close-up 등), 가사·보컬 지시.
예시: "Cinematic romantic classical instrumental with anthemic British soul. Atmosphere: rain around Big Ben, grey sky but heart is full, bittersweet triumph of being alive in London. Instruments: soaring piano melody, bright uplifting strings, warm cello with emotional build. Tempo: BPM 66, steady with anthemic lift. No sudden dynamic changes. No percussion. No electronic sounds." """

_IMAGE_RULES = """- image_prompt: 영문. 16:9 가로 풍경 한 장. 사진 한 장을 묘사하듯 장소·시간·빛·주요 사물을 한 가지 상태로 확정해서 씁니다.
  "or", "maybe", "slightly", "could", "appears" 같은 선택지·추측·완곡 표현을 쓰지 않습니다. 벚꽃 톤(웜 로즈/앰버) 빛.
  no text, no letters, no logo, no watermark 를 명시합니다. 사람이 나오면 뒷모습이나 멀리 있는 작은 실루엣만 둡니다.
- motion_prompt: 영문. 카메라는 고정(static locked-off camera, no camera movement, no zoom, no cuts)이고,
  비·눈·꽃잎·김·촛불·물결·커튼처럼 계속 반복되는 작은 움직임만 적습니다. 사람·사물이 화면 밖으로 나가거나 새로 들어오지 않습니다."""

PLAN_SYSTEM = f"""당신은 유튜브 음악 채널 HASIRA_yo!의 아트 디렉터 겸 음악 프로듀서입니다.
{_CHANNEL_RULES}

테마를 받아 아래 JSON 하나만 출력하세요. 설명 문장이나 ``` 표시는 쓰지 않습니다.
{{
  "title_ja": "테마의 일본어 감정 문장 (예: 温泉旅館の夜 — 静かな時間をあなたに)",
  "title_ko": "같은 문장의 한국어 뜻",
  "concept_ko": "이 편의 공간과 음악을 한 문장으로 (한국어)",
  "image_prompt": "...",
  "motion_prompt": "...",
  "tracks": [{{"title_ja": "곡 제목 (일본어, 짧게)", "title_en": "Track title in English", "top": true, "prompt": "Suno 프롬프트"}}]
}}

{_PROMPT_POLICY}

규칙
- tracks 는 요청한 개수와 정확히 같게 만듭니다. 같은 테마 안의 서로 다른 장소·시간·감정으로 곡마다 장면을 바꿉니다.
- top 은 가장 먼저 만들 대표곡 4개만 true 입니다. 첫 번째 곡은 반드시 top 이며 ABACAD 배치의 핵심곡 A 가 됩니다.
- 실존 아티스트 이름·곡 이름은 쓰지 않습니다.
{_IMAGE_RULES}
"""

PLAN_GIVEN_SYSTEM = f"""당신은 유튜브 음악 채널 HASIRA_yo!의 아트 디렉터입니다.
{_CHANNEL_RULES}

곡 프롬프트는 이미 정해져 있습니다(바꾸지 않습니다). 테마와 곡 목록을 받아 아래 JSON 하나만 출력하세요.
{{
  "title_ja": "테마의 일본어 감정 문장 (예: 雨のロンドン、午後の窓辺で)",
  "title_ko": "같은 문장의 한국어 뜻",
  "concept_ko": "이 편의 공간과 음악을 한 문장으로 (한국어)",
  "image_prompt": "...",
  "motion_prompt": "...",
  "track_titles": [{{"no": 1, "title_ja": "곡 제목 (일본어, 짧게)", "title_en": "Track title in English"}}]
}}
- track_titles 는 받은 곡 수와 같고, 각 곡의 한국어 제목과 프롬프트 장면을 살려 옮깁니다.
{_IMAGE_RULES}
"""

PACK_SYSTEM = f"""당신은 유튜브 음악 채널 HASIRA_yo!의 업로드 담당자입니다.
{_CHANNEL_RULES}

1시간 안팎의 Cinematic Classical 영상 업로드 정보를 씁니다. 아래 JSON 하나만 출력하세요.
{{
  "title": "검색 키워드 + HASIRA 감정 문장 + 채널명. 예: Cinematic Piano 1 Hour | 温泉旅館の夜 — 静かな時間をあなたに | HASIRA_yo!",
  "description": "설명 첫 부분 (일본어 250자 이상: 공간·감정 소개, 선곡 의도와 감정 설계 한두 줄, 어울리는 시간). 곡 목록·해시태그·브랜드 서명은 쓰지 않습니다.",
  "tags": ["태그 15~20개 — 3층 구조: 검색(cinematic piano 1 hour, シネマティック ピアノ 1時間, relaxing classical music), 니치(cinematic end credit piano music, 映画のエンドクレジット風ピアノ, romantic classical instrumental for reading), 브랜드(HASIRA_yo + 테마)"],
  "hashtags": ["#CinematicPiano 처럼 # 붙인 3~5개"]
}}
과장된 효능(집중력 몇 배, 치료 효과 등)은 쓰지 않습니다."""

UPLOAD_SETTINGS = [
    ("카테고리", "음악"),
    ("아동용 여부", "아니요, 아동용이 아닙니다"),
    ("동영상 언어", "일본어"),
    ("AI 도구 사용 공개", "업로드 화면에서 반드시 체크 (매뉴얼 Part 0)"),
    ("챕터", "설명란 곡 목록 타임스탬프로 자동 생성 (첫 줄 00:00)"),
    ("섬네일", "Canva · 벚꽃 톤 — 아래 1280×720 그림 바탕"),
    ("예약", "Long-form 금요일 20:00~21:00 JST"),
]


# ─────────────────────────────────────────────────────────────────────────────
# 노션 목록 (Hasira_yo › 테마별 음악 / LP_prompts.csv 를 가져온 스냅샷)
# ─────────────────────────────────────────────────────────────────────────────
SERIES_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "assets", "hasira", "notion_series.json")


def load_series() -> list:
    try:
        with open(SERIES_FILE, encoding="utf-8") as f:
            return json.load(f).get("themes", [])
    except Exception as e:
        print(f"[hasira] 노션 목록 읽기 실패: {e}", flush=True)
        return []


def theme_label(t: dict) -> str:
    tag = f" · {t['status']}" if t.get("status") else ""
    n = len(t.get("prompts") or [])
    pr = f" · 노션 프롬프트 {n}개" if n else ""
    return f"{t['no']}. {t['name_ko']} ({t['name_en']}){tag}{pr}"


# ── 대사 (매뉴얼 Step 6 · 녹음용) ──
OPENING_TMPL = "HASIRA_yo!へようこそ。今日は、{place}へ、ご案内します。"
OPENING_READ = "ハシラヨへ ようこそ。きょうは、{read}へ、ごあんない します。"
OPENING_HANGUL = "하시라요에 요-코소. 쿄-와, {hangul}에, 고안나이 시마스."
OPENING_KO = "HASIRA_yo!에 오신 걸 환영합니다. 오늘은 {name}(으)로 안내하겠습니다."
CLOSING = {
    "ja": "行福しなさい、癒しなさい。今日もしばらく、寄りかかってください。チャンネル登録も、よろしくお願いします。",
    "read": "こうふく しなさい、いやし なさい。きょうも しばらく、よりかかって ください。チャンネル とうろくも、よろしく おねがい します。",
    "hangul": "코-후쿠 시나사이, 이야시 나사이. 쿄-모 시바라쿠, 요리카캇테 쿠다사이. 찬네루 토-로쿠모, 요로시쿠 오네가이 시마스.",
    "ko": "행복하세요, 치유받으세요. 오늘도 잠시 기대어 가세요. 채널 구독도 잘 부탁드립니다.",
}


def opening_lines(theme: dict) -> dict:
    if not theme or not theme.get("place_ja"):
        return {}
    return {"ja": OPENING_TMPL.format(place=theme["place_ja"]),
            "read": OPENING_READ.format(read=theme.get("place_read", "")),
            "hangul": OPENING_HANGUL.format(hangul=theme.get("place_hangul", "")),
            "ko": OPENING_KO.format(name=theme.get("name_ko", ""))}


# ─────────────────────────────────────────────────────────────────────────────
# 제작 보드 (노션 「테마별 음악」 대신) — R2 hasira/_board.json 에 저장
# ─────────────────────────────────────────────────────────────────────────────
BOARD_KEY = "hasira/_board.json"
BOARD_LOCAL = os.path.join("projects", "_hasira_board.json")
BOARD_FIELDS = ["plan_month", "youtube_url", "shorts_url", "upload_date", "views_1w", "memo"]
STAGES = ["예정", "기획", "음악", "합성 완료", "업로드 완료"]
DEFAULT_MONTH = {"03": "2026-11", "02": "2026-11", "04": "2026-12", "05": "2026-12"}


def _board_from_series() -> dict:
    themes = {}
    for t in load_series():
        themes[t["no"]] = {
            "no": t["no"], "name_ko": t["name_ko"], "name_en": t["name_en"],
            "place_ja": t.get("place_ja", ""), "place_read": t.get("place_read", ""),
            "place_hangul": t.get("place_hangul", ""),
            "stage": "업로드 완료" if t.get("youtube_url") else ("음악" if t.get("status") == "음악생성" else "예정"),
            "detail": "QC 통과 20곡 (Suno)" if t.get("status") == "음악생성" else "",
            "plan_month": DEFAULT_MONTH.get(t["no"], ""), "youtube_url": t.get("youtube_url", ""),
            "shorts_url": "", "upload_date": t.get("upload_date", ""), "views_1w": None,
            "memo": t.get("memo", ""), "project_id": "", "has_prompts": bool(t.get("prompts")),
        }
    return {"themes": themes, "updated": ""}


def load_board(keys: dict) -> dict:
    board = None
    if _r2_ok(keys):
        from src import r2_store
        try:
            board = r2_store.get_json(keys, BOARD_KEY)
        except Exception as e:
            print(f"[hasira] 보드 읽기 실패(R2): {e}", flush=True)
    if board is None and os.path.exists(BOARD_LOCAL):
        try:
            with open(BOARD_LOCAL, encoding="utf-8") as f:
                board = json.load(f)
        except Exception:
            board = None
    base = _board_from_series()
    if not board:
        return base
    for no, t in base["themes"].items():          # 새로 생긴 기본 테마·필드 보충
        cur = board.setdefault("themes", {}).setdefault(no, t)
        for k, v in t.items():
            cur.setdefault(k, v)
    return board


def save_board(keys: dict, board: dict) -> str:
    board["updated"] = time.strftime("%Y-%m-%d %H:%M")
    os.makedirs(os.path.dirname(BOARD_LOCAL), exist_ok=True)
    with open(BOARD_LOCAL, "w", encoding="utf-8") as f:
        json.dump(board, f, ensure_ascii=False, indent=1)
    if _r2_ok(keys):
        from src import r2_store
        try:
            r2_store.put_json(keys, BOARD_KEY, board)
            return "r2"
        except Exception as e:
            print(f"[hasira] 보드 저장 실패(R2): {e}", flush=True)
    return "local"


def board_themes(board: dict) -> list:
    return sorted(board.get("themes", {}).values(), key=lambda t: t["no"])


def add_theme(board: dict, name_ko: str, name_en: str, place_ja: str = "",
              place_read: str = "", place_hangul: str = "") -> dict:
    nos = [int(n) for n in board.get("themes", {}) if str(n).isdigit()]
    no = f"{(max(nos) if nos else 0) + 1:02d}"
    t = {"no": no, "name_ko": name_ko.strip(), "name_en": name_en.strip(), "place_ja": place_ja.strip(),
         "place_read": place_read.strip(), "place_hangul": place_hangul.strip(), "stage": "예정", "detail": "",
         "plan_month": "", "youtube_url": "", "shorts_url": "", "upload_date": "", "views_1w": None,
         "memo": "", "project_id": "", "has_prompts": False}
    board.setdefault("themes", {})[no] = t
    return t


def stage_of(state: dict) -> tuple:
    """프로젝트 상태 → (단계, 세부)."""
    tracks = state.get("tracks", [])
    done = sum(1 for t in tracks if t.get("status") == "done")
    fin = state.get("final") or {}
    if fin.get("seconds"):
        return "합성 완료", f"{fmt_time(fin['seconds'], True)} · {fin.get('made_at', '')}"
    if done:
        loop = "루프 있음" if (state.get("loop") or {}).get("local") or (state.get("loop") or {}).get("r2_key") else "루프 없음"
        return "음악", f"{done}/{len(tracks)}곡 · {loop}"
    return "기획", f"{len(tracks)}곡 기획 · {state.get('created_at', '')[:8]}"


def sync_board(keys: dict, state: dict) -> bool:
    """프로젝트 진행 상황을 보드에 반영 (바뀐 경우에만 저장). 업로드 완료로 적힌 테마는 건드리지 않는다."""
    no = state.get("notion_theme_no") or state.get("theme_no")
    if not no:
        return False
    board = load_board(keys)
    t = board.get("themes", {}).get(no)
    if t is None:
        return False
    stage, detail = stage_of(state)
    if t.get("stage") == "업로드 완료":
        stage = t["stage"]
    new = {"stage": stage, "detail": detail, "project_id": state.get("project_id", "")}
    if all(t.get(k) == v for k, v in new.items()):
        return False
    t.update(new)
    save_board(keys, board)
    return True


def strip_banned(text: str) -> str:
    """금지어가 들어간 태그·해시태그를 걸러낼 때 쓰는 검사용 소문자 문자열."""
    return (text or "").lower()


def has_banned(text: str) -> bool:
    t = strip_banned(text)
    return any(w in t for w in BANNED_WORDS)


# ─────────────────────────────────────────────────────────────────────────────
# 공통 헬퍼
# ─────────────────────────────────────────────────────────────────────────────
def project_files(state: dict, *parts) -> str:
    d = os.path.join(state.get("project_dir", "projects/tmp"), "hasira", *parts[:-1])
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, parts[-1])


def usable(path: str) -> bool:
    return bool(path) and os.path.exists(path) and os.path.getsize(path) > 0


def duration(path: str) -> float:
    try:
        r = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path],
                           capture_output=True, timeout=60)
        return float(json.loads(r.stdout.decode())["format"]["duration"])
    except Exception:
        return 0.0


def fmt_time(sec: float, force_hours: bool = False) -> str:
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h or force_hours:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _r2_ok(keys: dict) -> bool:
    from src import r2_store
    return r2_store.is_configured(keys)


def r2_key(state: dict, name: str) -> str:
    return f"hasira/{state.get('project_id', 'tmp')}/{name}"


def keep_in_r2(keys: dict, state: dict, local: str, name: str, content_type: str = "") -> str:
    """R2 가 설정돼 있으면 올리고 key 를 돌려준다. 실패·미설정이면 빈 문자열."""
    if not _r2_ok(keys) or not usable(local):
        return ""
    from src import r2_store
    try:
        return r2_store.upload_file(keys, local, r2_key(state, name), content_type)
    except Exception as e:
        print(f"[hasira] R2 업로드 실패 {name}: {e}", flush=True)
        return ""


def ensure_local(keys: dict, item: dict, dest: str) -> str:
    """item['local'] 이 없으면(서버 재시작·JSON 복구) R2 에서 다시 받아 온다."""
    if usable(item.get("local", "")):
        return item["local"]
    if item.get("r2_key") and _r2_ok(keys):
        from src import r2_store
        try:
            r2_store.download_file(keys, item["r2_key"], dest)
            if usable(dest):
                item["local"] = dest
                return dest
        except Exception as e:
            print(f"[hasira] R2 다시 받기 실패 {item.get('r2_key')}: {e}", flush=True)
    return ""


def _download(url: str, dest: str) -> str:
    import requests
    r = requests.get(url, stream=True, timeout=300, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in r.iter_content(1 << 16):
            f.write(chunk)
    if not usable(dest):
        raise RuntimeError("내려받은 파일이 비어 있습니다.")
    return dest


# ─────────────────────────────────────────────────────────────────────────────
# ① 기획
# ─────────────────────────────────────────────────────────────────────────────
def default_track_count(target_min: int, track_min: float) -> int:
    return max(3, int(round(target_min / max(track_min, 1.0))))


def _ask_json(api_key: str, system: str, user: str, check) -> dict:
    import anthropic
    from src.prompts import SCRIPT_MODEL, _text_of, _extract_json
    client = anthropic.Anthropic(api_key=api_key)
    last = None
    for _ in range(2):
        resp = client.messages.create(model=SCRIPT_MODEL, max_tokens=12000, system=system,
                                      messages=[{"role": "user", "content": user}])
        try:
            data = _extract_json(_text_of(resp))
            check(data)
            return data
        except Exception as e:
            last = e
    raise ValueError(f"기획 JSON 을 읽지 못했습니다: {last}")


def make_plan(api_key: str, theme: str, n_tracks: int, target_min: int, given: list = None) -> dict:
    """given: 노션에 이미 있는 프롬프트 [{code, title_ko, top, prompt}] — 있으면 프롬프트는 그대로 쓰고
    Claude 는 제목·그림·움직임·곡 일본어 제목만 만든다."""
    if given:
        listing = "\n".join(f"{i + 1}. {g.get('title_ko', '')} — {g.get('prompt', '')}" for i, g in enumerate(given))
        user = f"테마: {theme.strip()}\n영상 길이: 약 {target_min}분\n곡 목록 ({len(given)}곡):\n{listing}\nJSON 만 출력하세요."

        def _check(d):
            if not d.get("image_prompt"):
                raise ValueError("image_prompt 가 비어 있습니다.")
        plan = _ask_json(api_key, PLAN_GIVEN_SYSTEM, user, _check)
        names = {int(x.get("no", 0)): x for x in (plan.get("track_titles") or []) if isinstance(x, dict)}
        plan["tracks"] = [{"title_ja": names.get(i + 1, {}).get("title_ja") or g.get("title_ko", ""),
                           "title_en": names.get(i + 1, {}).get("title_en", ""),
                           "title_ko": g.get("title_ko", ""), "code": g.get("code", ""),
                           "top": bool(g.get("top")), "prompt": g["prompt"]}
                          for i, g in enumerate(given)]
        plan["prompt_source"] = "notion"
        return plan

    user = f"테마: {theme.strip()}\n영상 길이: 약 {target_min}분\n곡 개수: 정확히 {n_tracks}곡\nJSON 만 출력하세요."

    def _check(d):
        tr = [t for t in (d.get("tracks") or []) if isinstance(t, dict) and t.get("prompt")]
        if not d.get("image_prompt") or not tr:
            raise ValueError("image_prompt 또는 tracks 가 비어 있습니다.")
    plan = _ask_json(api_key, PLAN_SYSTEM, user, _check)
    plan["tracks"] = [t for t in plan["tracks"] if isinstance(t, dict) and t.get("prompt")][:n_tracks]
    if plan["tracks"] and not any(t.get("top") for t in plan["tracks"]):
        plan["tracks"][0]["top"] = True
    plan["prompt_source"] = "claude"
    return plan


def new_tracks_from_plan(plan: dict) -> list:
    return [{"no": i + 1, "title_ja": t.get("title_ja", ""), "title_en": t.get("title_en", ""),
             "title_ko": t.get("title_ko", ""), "code": t.get("code", ""), "top": bool(t.get("top")),
             "prompt": t.get("prompt", ""), "status": "pending", "local": "", "r2_key": "",
             "seconds": 0.0, "source": "", "error": ""}
            for i, t in enumerate(plan.get("tracks") or [])]


def track_prompt(state: dict, track: dict, seconds: int) -> str:
    """ElevenLabs·Lyria 용: 매뉴얼 형식 프롬프트 그대로 + 연주곡·길이 지시."""
    mins = max(1, round(seconds / 60))
    return (f"{track.get('prompt', '').strip().rstrip('.')}. Instrumental only, no vocals, no voice. "
            f"About {mins} minutes long, gentle intro and a soft natural ending.")


# ─────────────────────────────────────────────────────────────────────────────
# ② 그림 (16:9)
# ─────────────────────────────────────────────────────────────────────────────
def generate_image(replicate_token: str, prompt: str) -> str:
    """Replicate flux-dev 16:9 → URL (1시간 뒤 삭제되므로 바로 내려받아 보관할 것)."""
    from src import image_replicate as ir
    os.environ["REPLICATE_API_TOKEN"] = replicate_token
    inputs = {"prompt": prompt, "aspect_ratio": "16:9", "num_inference_steps": 28, "guidance": 3.5,
              "output_format": "jpg", "output_quality": 95, "num_outputs": 1}
    return ir._to_url(ir._run_prediction(ir.FLUX_DEV_MODEL, inputs, ir.TIMEOUT_DEV, "[hasira/flux-dev 16:9]"))


def save_image(keys: dict, state: dict, src: str, source: str) -> dict:
    """URL 또는 로컬 파일을 프로젝트에 보관하고 1280×720 섬네일 바탕도 만든다."""
    ext = ".png" if src.lower().split("?")[0].endswith(".png") else ".jpg"
    dest = project_files(state, f"image{ext}")
    if src.startswith("http"):
        _download(src, dest)
    elif os.path.abspath(src) != os.path.abspath(dest):
        shutil.copyfile(src, dest)
    thumb = project_files(state, "thumbnail_base_1280x720.jpg")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", dest, "-vf",
                    "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720",
                    "-q:v", "2", thumb], check=True, timeout=120)
    img = {"local": dest, "source": source, "thumb_local": thumb,
           "r2_key": keep_in_r2(keys, state, dest, f"image{ext}", "image/jpeg" if ext == ".jpg" else "image/png")}
    state["image"] = img
    state["loop"] = {}                     # 그림이 바뀌면 예전 루프는 무효
    state["final"] = {}
    return img


# ─────────────────────────────────────────────────────────────────────────────
# ③ 루프 영상
# ─────────────────────────────────────────────────────────────────────────────
X264 = ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-g", str(FPS * 2), "-keyint_min", str(FPS * 2), "-sc_threshold", "0"]
FILL = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1"


def _frame_count(path: str) -> int:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
                        "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", path],
                       capture_output=True, timeout=120)
    try:
        return int(r.stdout.decode().strip().split(",")[0])
    except Exception:
        return 0


def build_pingpong_loop(raw_clip: str, out: str) -> str:
    """6초 클립 → 앞으로 재생 + 거꾸로 재생(양 끝 프레임 1장씩 제외) = 이음매 없는 약 12초 루프.
    거꾸로 재생은 원본 해상도에서 처리해 메모리를 아낀다(720p 150장 ≈ 200MB)."""
    n = _frame_count(raw_clip)
    rev_trim = f"trim=start_frame=1:end_frame={max(n - 1, 2)}," if n > 3 else ""
    vf = (f"[0:v]fps={FPS},split[f][b];[b]reverse,{rev_trim}setpts=PTS-STARTPTS[r];"
          f"[f][r]concat=n=2:v=1:a=0,{FILL},format=yuv420p[v]")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", raw_clip, "-filter_complex", vf, "-map", "[v]",
                    *X264, "-crf", "22", "-maxrate", "2M", "-bufsize", "4M", "-an",
                    "-movflags", "+faststart", out], check=True, timeout=900)
    return out


def build_kenburns_loop(image: str, out: str, period: int = KB_PERIOD, zoom: float = KB_ZOOM) -> str:
    """그림 한 장 → 1.00 → 1.03 → 1.00 배로 천천히 숨 쉬듯 확대·축소 (매뉴얼: 1~3% 줌, 완전 정지 금지).
    코사인 곡선이라 끝 프레임이 첫 프레임과 같아져 이음매 없이 반복된다.
    흔들림을 줄이려고 4K 로 키운 뒤 줌하고 1080p 로 내보낸다."""
    n = int(period * FPS)
    z = f"1+{zoom / 2:.4f}*(1-cos(2*PI*on/{n}))"
    vf = (f"scale=3840:2160:force_original_aspect_ratio=increase,crop=3840:2160,"
          f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS},"
          f"setsar=1,format=yuv420p")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", str(FPS), "-t", f"{n / FPS:.3f}",
                    "-i", image, "-vf", vf, "-frames:v", str(n), *X264, "-crf", "20", "-an",
                    "-movflags", "+faststart", out], check=True, timeout=900)
    return out


def motion_prompt_full(state: dict) -> str:
    mp = (state.get("plan") or {}).get("motion_prompt", "").rstrip(" .")
    return (f"{mp}. Static locked-off camera, no camera movement, no zoom, no pan, no cuts, "
            f"the scene composition stays exactly the same, only the small repeating elements move, "
            f"no text.")


# ─────────────────────────────────────────────────────────────────────────────
# ④ 음악
# ─────────────────────────────────────────────────────────────────────────────
class StopAll(RuntimeError):
    """크레딧·권한 문제처럼 다음 곡도 똑같이 실패할 오류."""


def _gen_elevenlabs(api_key: str, prompt: str, seconds: int, dest: str) -> str:
    from elevenlabs import ElevenLabs
    try:
        audio = ElevenLabs(api_key=api_key).music.compose(
            prompt=prompt, music_length_ms=int(max(10, min(600, seconds)) * 1000), force_instrumental=True)
        with open(dest, "wb") as f:
            for c in audio:
                if c:
                    f.write(c)
    except Exception as e:
        msg = str(e)
        if any(k in msg.lower() for k in ("quota", "credit", "401", "402", "payment", "unauthorized")):
            raise StopAll(f"ElevenLabs 크레딧·권한 문제로 멈췄습니다: {msg[:300]}")
        raise
    if not usable(dest):
        raise RuntimeError("ElevenLabs 가 빈 음악을 돌려줬습니다.")
    return dest


def _gen_lyria(api_key: str, prompt: str, dest: str) -> str:
    from google import genai
    try:
        inter = genai.Client(api_key=api_key).interactions.create(model=LYRIA_MODEL, input=prompt)
    except Exception as e:
        msg = str(e)
        if any(k in msg for k in ("PERMISSION_DENIED", "SERVICE_DISABLED", "403", "RESOURCE_EXHAUSTED", "429",
                                  "API_KEY_INVALID", "billing")):
            raise StopAll(f"Google Lyria 연결 문제로 멈췄습니다: {msg[:300]}")
        raise
    audio = getattr(inter, "output_audio", None)
    raw = getattr(audio, "data", None) if audio is not None else None
    if not raw:
        raise RuntimeError("Lyria 응답에 output_audio 가 없습니다 (연결 테스트의 응답 구조 JSON 을 확인).")
    with open(dest, "wb") as f:
        f.write(base64.b64decode(raw) if isinstance(raw, str) else bytes(raw))
    return dest


def suno_style(state: dict, track: dict) -> str:
    """Suno 에 붙여 넣을 프롬프트 (노션 Prompt Full 과 같은 문장 · Instrumental 켜고 사용)."""
    return track.get("prompt", "").strip()


def suno_sheet(state: dict) -> str:
    """기획 곡 목록 전체를 Suno 작업용 글 파일로."""
    plan = state.get("plan") or {}
    lines = [f"HASIRA_yo! — {plan.get('title_ja', state.get('title', ''))}",
             "Suno: Instrumental 켜기 · Top 곡(★)부터 · 프롬프트당 A/B 2개 생성 후 QC", ""]
    for t in sorted(state.get("tracks", []), key=lambda x: x["no"]):
        if not t.get("prompt"):
            continue
        star = " ★Top" if t.get("top") else ""
        code = f" {t['code']}" if t.get("code") else ""
        lines += [f"#{t['no']:02d}{code}{star} {t.get('title_ko', '')}",
                  f"Title: {t.get('title_en') or t.get('title_ja', '')}",
                  f"(곡 제목 표기: {t.get('title_ja', '')})", f"Prompt: {suno_style(state, t)}", ""]
    return "\n".join(lines)


def add_uploaded_track(keys: dict, state: dict, filename: str, data: bytes, no: int = None) -> dict:
    """직접 만든 곡(Suno 등) 넣기.
    no 를 주면 기획 목록의 그 자리에, 안 주면 아직 비어 있는 첫 자리에 넣는다(기획 제목 유지).
    빈 자리가 없으면 목록 끝에 추가하고 파일 이름(확장자 제외)을 곡 제목으로 쓴다."""
    tracks = state.setdefault("tracks", [])
    slot = None
    if no is not None:
        slot = next((t for t in tracks if t["no"] == no), None)
    else:
        slot = next((t for t in sorted(tracks, key=lambda x: x["no"])
                     if t.get("status") != "done" and t.get("prompt")), None)
    ext = os.path.splitext(filename)[1].lower() or ".mp3"
    tno = slot["no"] if slot else max([t["no"] for t in tracks] or [0]) + 1
    dest = project_files(state, "music", f"track_{tno:02d}{ext}")
    tmp = dest + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    sec = duration(tmp)
    if sec <= 0:
        os.remove(tmp)
        raise ValueError(f"{filename}: 오디오 파일로 읽을 수 없습니다.")
    os.replace(tmp, dest)
    fname = os.path.splitext(os.path.basename(filename))[0].strip()
    info = {"status": "done", "local": dest, "seconds": round(sec, 2), "source": "upload", "error": "",
            "file_name": os.path.basename(filename),
            "r2_key": keep_in_r2(keys, state, dest, f"music/track_{tno:02d}{ext}", "audio/mpeg")}
    if slot is None:
        slot = {"no": tno, "title_ja": fname, "title_en": fname, "prompt": ""}
        tracks.append(slot)
    slot.update(info)
    state["final"] = {}
    return slot


# ─────────────────────────────────────────────────────────────────────────────
# 백그라운드 작업
# ─────────────────────────────────────────────────────────────────────────────
_JOBS: dict = {}
_LOCK = threading.Lock()


def get_job(project_id: str):
    return _JOBS.get(project_id)


def is_running(project_id: str) -> bool:
    j = _JOBS.get(project_id)
    return bool(j and j["thread"].is_alive())


def request_stop(project_id: str) -> None:
    j = _JOBS.get(project_id)
    if j:
        j["stop"] = True


def _start(project_id: str, kind: str, label: str, target, args) -> bool:
    with _LOCK:
        if is_running(project_id):
            return False
        job = {"kind": kind, "label": label, "msg": "준비 중", "done": 0, "total": 0, "pct": 0.0,
               "error": "", "stop": False, "started_at": time.time(), "finished_at": None, "result": ""}
        th = threading.Thread(target=_wrap, args=(job, target, args), daemon=True)
        job["thread"] = th
        _JOBS[project_id] = job
        th.start()
        return True


def _wrap(job, target, args):
    try:
        target(job, *args)
    except BaseException as e:
        job["error"] = f"{type(e).__name__}: {e}"
        print(f"[hasira] {job['kind']} 작업 오류: {e}", flush=True)
    finally:
        job["finished_at"] = time.time()


def _save(save_fn, state):
    try:
        save_fn(state)
    except Exception as e:
        print(f"[hasira] 상태 저장 실패: {e}", flush=True)


# ── ③ 루프 작업 ──
def start_loop_job(state: dict, keys: dict, save_fn) -> bool:
    return _start(state["project_id"], "loop", "움직임 루프 만들기", _loop_worker, (state, keys, save_fn))


def _loop_worker(job, state, keys, save_fn):
    img = ensure_local(keys, state.get("image") or {}, project_files(state, "image.jpg"))
    if not img:
        raise RuntimeError("그림이 없습니다. 먼저 그림을 만들거나 올려 주세요.")
    mode = state.get("visual_mode", "motion")
    if mode not in VISUAL_MODES:          # 예전 프로젝트의 'still' → Ken Burns
        mode = state["visual_mode"] = "kenburns"
    out = project_files(state, "loop.mp4")
    loop = {"mode": mode}
    if mode == "motion":
        from src.video_replicate import generate_single_clip_url
        job["msg"] = "MiniMax 로 6초 움직임 클립 만드는 중 (보통 3~5분)"
        url = generate_single_clip_url(keys.get("REPLICATE_API_TOKEN", ""), motion_prompt_full(state),
                                       image_url=img, prompt_optimizer=False)
        raw = project_files(state, "motion_raw.mp4")
        _download(url, raw)
        loop["raw_local"] = raw
        loop["raw_r2_key"] = keep_in_r2(keys, state, raw, "motion_raw.mp4", "video/mp4")
        job["msg"] = "앞뒤로 이어 붙여 끊김 없는 루프로 인코딩 중"
        build_pingpong_loop(raw, out)
    else:
        job["msg"] = f"Ken Burns 루프 인코딩 중 ({KB_PERIOD}초 · 최대 {int(KB_ZOOM * 100)}% 줌)"
        build_kenburns_loop(img, out)
    loop.update(local=out, seconds=round(duration(out), 2),
                r2_key=keep_in_r2(keys, state, out, "loop.mp4", "video/mp4"))
    state["loop"] = loop
    state["final"] = {}
    _save(save_fn, state)
    job["msg"] = f"완료 — {loop['seconds']}초 루프"


# ── ④ 음악 작업 ──
def start_music_job(state: dict, keys: dict, save_fn, nos: list) -> bool:
    return _start(state["project_id"], "music", "음악 만들기", _music_worker, (state, keys, save_fn, list(nos)))


def _music_worker(job, state, keys, save_fn, nos):
    provider = state.get("provider", "elevenlabs")
    seconds = int(state.get("track_sec", 180))
    by_no = {t["no"]: t for t in state.get("tracks", [])}
    job["total"] = len(nos)
    for i, no in enumerate(nos):
        t = by_no.get(no)
        if t is None:
            continue
        if job["stop"]:
            break
        job["msg"] = f"{i + 1}/{len(nos)}곡 · #{no:02d} {t.get('title_ja', '')} 만드는 중"
        t["status"], t["error"] = "generating", ""
        dest = project_files(state, "music", f"track_{no:02d}.mp3")
        try:
            prompt = track_prompt(state, t, seconds)
            if provider == "lyria":
                _gen_lyria(keys.get("GOOGLE_API_KEY", ""), prompt, dest)
            else:
                _gen_elevenlabs(keys.get("ELEVENLABS_API_KEY", ""), prompt, seconds, dest)
            t.update(status="done", local=dest, seconds=round(duration(dest), 2), source=provider,
                     r2_key=keep_in_r2(keys, state, dest, f"music/track_{no:02d}.mp3", "audio/mpeg"))
            state["final"] = {}
        except StopAll as e:
            t.update(status="error", error=str(e))
            job["error"] = str(e)
            _save(save_fn, state)
            break
        except Exception as e:
            t.update(status="error", error=f"{type(e).__name__}: {e}"[:400])
        job["done"] = i + 1
        job["pct"] = (i + 1) / max(len(nos), 1)
        _save(save_fn, state)
    for t in by_no.values():
        if t.get("status") == "generating":
            t["status"] = "pending"
    _save(save_fn, state)
    ok = sum(1 for t in by_no.values() if t.get("status") == "done")
    job["msg"] = f"끝 — 완성 {ok}곡"


# ─────────────────────────────────────────────────────────────────────────────
# ⑤ 합성
# ─────────────────────────────────────────────────────────────────────────────
def _core_track(done: list) -> dict:
    tops = [t for t in done if t.get("top")]
    return (tops or done)[0]


def playlist(state: dict) -> list:
    """재생 순서. in_order: 번호순 / abacad: 핵심곡 A 를 사이사이 반복.
    목표 길이에 못 미치면(repeat_fill) 처음부터 다시 돌려 채운다."""
    done = [t for t in sorted(state.get("tracks", []), key=lambda x: x["no"])
            if t.get("status") == "done" and t.get("seconds", 0) > XFADE_SEC * 2 + 10]
    if not done:
        return []
    if state.get("order_mode") == "abacad" and len(done) >= 2:
        a = _core_track(done)
        cycle = []
        for o in [t for t in done if t is not a]:
            cycle += [a, o]
    else:
        cycle = done
    target = int(state.get("target_min", 60)) * 60
    out, total = [], 0.0
    while True:
        for t in cycle:
            out.append(t)
            total += t["seconds"] - (XFADE_SEC if len(out) > 1 else 0)
            if total >= target:
                return out
        if not state.get("repeat_fill", True):
            return out


# ── 인트로·아웃트로 목소리 (매뉴얼 Part 0 레벨 1: 크리에이터 보이스 5~10초) ──
VOICE_KINDS = {"intro": "인트로", "outro": "아웃트로"}


def save_voice(keys: dict, state: dict, kind: str, filename: str, data: bytes, shared: bool = True) -> dict:
    ext = os.path.splitext(filename)[1].lower() or ".mp3"
    dest = project_files(state, "voice", f"{kind}{ext}")
    with open(dest, "wb") as f:
        f.write(data)
    sec = duration(dest)
    if sec <= 0:
        os.remove(dest)
        raise ValueError(f"{filename}: 오디오 파일로 읽을 수 없습니다.")
    v = {"local": dest, "seconds": round(sec, 2), "file_name": os.path.basename(filename),
         "r2_key": keep_in_r2(keys, state, dest, f"voice/{kind}{ext}", "audio/mpeg")}
    shared = shared and kind == "outro"          # 인트로는 편마다 테마가 달라 공용으로 두지 않는다
    if shared and _r2_ok(keys):                 # 다음 편에서도 그대로 쓰도록 공용 보관
        from src import r2_store
        try:
            r2_store.upload_file(keys, dest, f"hasira/_shared/{kind}.audio", "audio/mpeg")
        except Exception as e:
            print(f"[hasira] 공용 목소리 보관 실패: {e}", flush=True)
    state.setdefault("voice", {})[kind] = v
    state["final"] = {}
    return v


def get_voice(keys: dict, state: dict, kind: str) -> str:
    """이 편의 목소리 → 없으면 R2 공용 목소리(지난 편에서 올린 것). use_voice 가 꺼져 있으면 빈 문자열."""
    if not (state.get("use_voice") or {}).get(kind, True):
        return ""
    v = (state.get("voice") or {}).get(kind) or {}
    got = ensure_local(keys, v, project_files(state, "voice", f"{kind}.mp3")) if v else ""
    if got:
        return got
    if kind == "outro" and _r2_ok(keys) and not (state.get("voice") or {}).get(f"_{kind}_shared_missing"):
        shared = {"r2_key": f"hasira/_shared/{kind}.audio"}
        got = ensure_local(keys, shared, project_files(state, "voice", f"{kind}_shared.audio"))
        if got:
            state.setdefault("voice", {})[kind] = {"local": got, "r2_key": shared["r2_key"],
                                                  "seconds": round(duration(got), 2), "file_name": "(공용)"}
            return got
        state.setdefault("voice", {})[f"_{kind}_shared_missing"] = True
    return ""


def chapters(items: list) -> list:
    """[(시작초, 곡 제목)] — 크로스페이드만큼 앞당겨진 실제 시작 시점."""
    out, t = [], 0.0
    for i, tr in enumerate(items):
        out.append((t, tr.get("title_ja") or tr.get("title_en") or f"Track {tr['no']}"))
        t += tr["seconds"] - XFADE_SEC
    return out


def chapter_text(chs: list, total: float) -> str:
    long = total >= 3600
    lines = []
    for i, (t, title) in enumerate(chs):
        stamp = "00:00" if i == 0 else fmt_time(t, force_hours=long)
        lines.append(f"{stamp} {title}")
    return "\n".join(lines)


def _run_ffmpeg(args: list, total_sec: float, job: dict, label: str, timeout: int = 7200):
    """-progress 로 진행률을 읽으며 ffmpeg 실행."""
    cmd = ["ffmpeg", "-y", "-v", "error", "-nostats", "-progress", "pipe:1", *args]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    t0 = time.time()
    for line in p.stdout:
        if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
            try:
                cur = int(line.split("=")[1]) / 1e6
                if total_sec > 0:
                    job["pct"] = min(cur / total_sec, 0.999)
                    job["msg"] = f"{label} · {fmt_time(cur)} / {fmt_time(total_sec)}"
            except ValueError:
                pass
        if job.get("stop"):
            p.kill()
            raise RuntimeError("중지했습니다.")
        if time.time() - t0 > timeout:
            p.kill()
            raise TimeoutError(f"{label} 가 {timeout // 60}분 안에 끝나지 않았습니다.")
    p.wait()
    if p.returncode != 0:
        raise RuntimeError(f"{label} 실패: {p.stderr.read()[-800:]}")


def start_render_job(state: dict, keys: dict, save_fn) -> bool:
    return _start(state["project_id"], "render", "최종 합성", _render_worker, (state, keys, save_fn))


def _render_worker(job, state, keys, save_fn):
    # 1) 재료 확인 (서버 재시작 뒤면 R2 에서 다시 받기)
    loop = state.get("loop") or {}
    loop_path = ensure_local(keys, loop, project_files(state, "loop.mp4"))
    if not loop_path:
        raise RuntimeError("루프 영상이 없습니다. ③ 움직임 단계를 먼저 끝내 주세요.")
    items = playlist(state)
    if len(items) < 1:
        raise RuntimeError("완성된 곡이 없습니다.")
    uniq = {t["no"]: t for t in items}
    job["msg"] = "곡 파일 확인 중"
    for no, t in uniq.items():
        ext = os.path.splitext(t.get("local") or t.get("r2_key") or ".mp3")[1] or ".mp3"
        if not ensure_local(keys, t, project_files(state, "music", f"track_{no:02d}{ext}")):
            raise RuntimeError(f"#{no:02d} 곡 파일이 없습니다 (서버 재시작으로 사라졌고 R2 보관본도 없음).")

    # 2) 곡마다 음량 맞춤 → 44.1kHz 스테레오 WAV (같은 곡이 반복돼도 한 번만)
    norm = {}
    job["total"] = len(uniq)
    for i, (no, t) in enumerate(uniq.items()):
        job["msg"] = f"음량 맞추는 중 {i + 1}/{len(uniq)}"
        job["pct"] = i / max(len(uniq), 1)
        out = project_files(state, "work", f"norm_{no:02d}.wav")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", t["local"], "-af",
                        f"{LOUDNESS},aresample=44100", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", out],
                       check=True, timeout=900)
        norm[no] = out
        t["seconds"] = round(duration(out), 2)      # 실제 길이로 보정 (챕터 정확도)
        if job["stop"]:
            raise RuntimeError("중지했습니다.")

    # 2-1) 인트로·아웃트로 목소리 (있으면 음량 맞춰 앞뒤에 붙임)
    voice = {}
    for kind in VOICE_KINDS:
        src = get_voice(keys, state, kind)
        if src:
            out = project_files(state, "work", f"voice_{kind}.wav")
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-af", f"{LOUDNESS},aresample=44100",
                            "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", out], check=True, timeout=300)
            voice[kind] = (out, duration(out))
    intro_sec = voice.get("intro", ("", 0.0))[1]
    outro_sec = voice.get("outro", ("", 0.0))[1]

    # 3) 크로스페이드 연결 (+ 인트로·아웃트로) → AAC
    chs = [(t + intro_sec, title) for t, title in chapters(items)]
    music_sec = chs[-1][0] - intro_sec + items[-1]["seconds"]
    total = intro_sec + music_sec + outro_sec
    music = project_files(state, "work", "music.m4a")
    args = []
    for t in items:
        args += ["-i", norm[t["no"]]]
    if len(items) == 1:
        fc = "[0:a]anull[m]"
    else:
        parts, prev = [], "[0:a]"
        for i in range(1, len(items)):
            lab = f"[x{i}]"
            parts.append(f"{prev}[{i}:a]acrossfade=d={XFADE_SEC}:c1=tri:c2=tri{lab}")
            prev = lab
        fc = ";".join(parts) + f";{prev}anull[m]"
    fc += (f";[m]afade=t=in:st=0:d={FADE_IN_SEC},"
           f"afade=t=out:st={max(music_sec - FADE_OUT_SEC, 0):.2f}:d={FADE_OUT_SEC}[mf]")
    seq, k = [], len(items)
    if "intro" in voice:
        args += ["-i", voice["intro"][0]]
        seq.append(f"[{k}:a]")
        k += 1
    seq.append("[mf]")
    if "outro" in voice:
        args += ["-i", voice["outro"][0]]
        seq.append(f"[{k}:a]")
        k += 1
    fc += (f";{''.join(seq)}concat=n={len(seq)}:v=0:a=1[a]" if len(seq) > 1 else ";[mf]anull[a]")
    _run_ffmpeg([*args, "-filter_complex", fc, "-map", "[a]", "-c:a", "aac", "-b:a", AUDIO_BITRATE,
                 "-ar", "44100", "-ac", "2", music], total, job, "음악 연결·인코딩")
    total = duration(music) or total

    # 4) 루프 영상을 스트림 복사로 반복 + 음악 → 최종 MP4 (영상은 다시 인코딩하지 않음)
    job["msg"], job["pct"] = "영상 반복 결합 중", 0.0
    final = project_files(state, f"HASIRA_{state.get('project_id', 'final')}.mp4")
    _run_ffmpeg(["-stream_loop", "-1", "-i", loop_path, "-i", music, "-map", "0:v:0", "-map", "1:a:0",
                 "-c", "copy", "-t", f"{total:.3f}", "-movflags", "+faststart", final],
                total, job, "영상 결합")
    for f in list(norm.values()) + [v[0] for v in voice.values()]:
        try:
            os.remove(f)
        except OSError:
            pass

    info = {"local": final, "seconds": round(duration(final), 2), "bytes": os.path.getsize(final),
            "chapters": [[round(t, 2), title] for t, title in chs], "made_at": time.strftime("%Y-%m-%d %H:%M"),
            "intro_sec": round(intro_sec, 2), "outro_sec": round(outro_sec, 2),
            "order_mode": state.get("order_mode", "in_order")}
    # 5) R2 로 전달
    if _r2_ok(keys):
        job["msg"], job["pct"] = f"R2 에 올리는 중 ({info['bytes'] / 1e6:.0f}MB)", 0.999
        info["r2_key"] = keep_in_r2(keys, state, final, os.path.basename(final), "video/mp4")
    state["final"] = info
    _save(save_fn, state)
    job["msg"], job["pct"] = f"완료 — {fmt_time(info['seconds'], True)} · {info['bytes'] / 1e6:.0f}MB", 1.0


def final_link(keys: dict, state: dict) -> str:
    info = state.get("final") or {}
    if not info.get("r2_key") or not _r2_ok(keys):
        return ""
    from src import r2_store
    return r2_store.download_link(keys, info["r2_key"], filename=os.path.basename(info["r2_key"]))


# ─────────────────────────────────────────────────────────────────────────────
# ⑦ 업로드 정보
# ─────────────────────────────────────────────────────────────────────────────
def make_upload_pack(api_key: str, state: dict) -> dict:
    """매뉴얼 Step 8: 제목(검색 키워드 + 감정 문장 + 채널명), 설명 250자+, 챕터, 브랜드 서명, #태그 3~5, 태그 15~20.
    금지어가 들어간 태그·해시태그는 코드에서 한 번 더 걸러낸다."""
    info = state.get("final") or {}
    chs = [(t, title) for t, title in info.get("chapters", [])]
    total = info.get("seconds", 0)
    plan = state.get("plan") or {}
    hours = max(1, round(total / 3600)) if total else 1
    pack = {"title": " | ".join(x for x in (f"Cinematic Piano {hours} Hour", plan.get("title_ja", ""), "HASIRA_yo!") if x),
            "description": "", "tags": [], "hashtags": []}
    if api_key:
        import anthropic
        from src.prompts import SCRIPT_MODEL, _text_of, _extract_json
        names = ", ".join(dict.fromkeys(title for _, title in chs))
        user = (f"영상 길이: {fmt_time(total, True)}\n테마: {state.get('theme', state.get('keyword', ''))}\n"
                f"감정 문장: {plan.get('title_ja', '')}\n공간: {plan.get('concept_ko', '')}\n곡 제목들: {names}")
        try:
            resp = anthropic.Anthropic(api_key=api_key).messages.create(
                model=SCRIPT_MODEL, max_tokens=2500, system=PACK_SYSTEM,
                messages=[{"role": "user", "content": user}])
            pack.update({k: v for k, v in _extract_json(_text_of(resp)).items() if v})
        except Exception as e:
            print(f"[hasira] 업로드 정보 생성 실패 → 기본 제목 사용: {e}", flush=True)
    tags = [str(t).strip().lstrip("#") for t in pack.get("tags") or [] if str(t).strip()]
    tags = [t for t in dict.fromkeys(tags) if not has_banned(t)][:20]
    while tags and len(",".join(tags)) > 480:          # YouTube 태그 칸 합계 500자
        tags.pop()
    pack["tags"] = tags
    hts = [h if str(h).startswith("#") else f"#{h}" for h in (pack.get("hashtags") or [])]
    hts = [h for h in hts if not has_banned(h)][:5]
    pack["banned_in_title"] = [w for w in BANNED_WORDS if w in strip_banned(pack.get("title", ""))]
    tracklist = chapter_text(chs, total) if len(chs) >= 3 else ""
    body = pack.get("description", "").strip()
    if tracklist:
        body += "\n\n― Tracklist ―\n" + tracklist
    body += "\n\n" + BRAND_SIGNATURE
    if hts:
        body += "\n\n" + " ".join(hts)
    pack["full_description"] = body.strip()
    pack["description_chars"] = len(pack.get("description", ""))
    state["upload_pack"] = pack
    return pack
