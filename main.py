# main.py — Making Shorts Engine | 채널 3개(너도나도아는커피 · SceneStory · HASIRA_yo!) 제작 대시보드
# Claude API 버전 (Anthropic claude-sonnet-4-6)

import streamlit as st
import os
import time
import base64
import requests
from pathlib import Path


# ── 로고 로드 (base64 임베드) ─────────────────────────────────────────────────
def _load_logo_b64() -> str:
    """assets/images/logo.png를 base64로 인코딩해 반환. 없으면 빈 문자열."""
    logo_path = Path(__file__).parent / "assets" / "images" / "logo.png"
    if logo_path.exists():
        with open(logo_path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return ""

LOGO_B64 = _load_logo_b64()


# ── 채널 ─────────────────────────────────────────────────────────────────────
# 프로젝트 state["channel"] 에 저장된다. 예전 프로젝트(값 없음)는 커피로 본다.
CHANNELS = {
    "coffee":     "너도나도아는커피",
    "scenestory": "SceneStory",
    "hasira":     "HASIRA_yo!",
}
CHANNEL_KEYS = list(CHANNELS.keys())


def project_channel(state: dict) -> str:
    ch = (state or {}).get("channel") or "coffee"
    return ch if ch in CHANNELS else "coffee"


def current_channel() -> str:
    ch = st.session_state.get("channel_pick")
    return ch if ch in CHANNELS else st.session_state.get("_last_channel", "coffee")


# ── 구글 드라이브 레퍼런스 이미지 목록 로드 ──────────────────────────────────
@st.cache_data(ttl=300)  # 5분 캐시 — 새 이미지 추가 후 새로고침하면 반영
def load_gdrive_images(api_key: str, folder_id: str) -> list[dict]:
    """
    공개 구글 드라이브 폴더에서 이미지 파일 목록을 가져온다.

    Args:
        api_key   : Google API Key (Drive API v3 접근용)
        folder_id : 드라이브 폴더 ID (URL의 /folders/ 뒤 문자열)

    Returns:
        [{"name": "파일명.jpg", "url": "공개다운로드URL"}, ...]
        API 키 / 폴더 ID가 없거나 오류 시 빈 리스트 반환
    """
    if not api_key or not folder_id:
        return []

    try:
        endpoint = "https://www.googleapis.com/drive/v3/files"
        params = {
            "q": (
                f"'{folder_id}' in parents "
                "and mimeType contains 'image/' "
                "and trashed = false"
            ),
            "fields": "files(id, name)",
            "orderBy": "name",
            "pageSize": 100,
            "key": api_key,
        }
        resp = requests.get(endpoint, params=params, timeout=10)
        resp.raise_for_status()
        files = resp.json().get("files", [])

        return [
            {
                "name": f["name"],
                "url": f"https://drive.google.com/uc?export=download&id={f['id']}",
                "view_url": f"https://drive.google.com/file/d/{f['id']}/view",
            }
            for f in files
        ]
    except Exception:
        return []

# ── 페이지 설정 (반드시 첫 번째 st 호출) ─────────────────────────────────────
st.set_page_config(
    page_title="Making Shorts Engine",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS (Paperlogy 팔레트 — 다크 네이비 사이드바 + 아이스화이트 메인 + 골드앰버) ──
st.markdown("""
<style>
/*
  ── Paperlogy 팔레트 ───────────────────────────────────────────
  navy-dark  : #142C3C  (사이드바 배경 · 강조 텍스트)
  navy-deep  : #0F3B59  (버튼 호버 · 링크)
  navy-mid   : #1E3A4E  (카드 보더 · 서브 텍스트)
  gold       : #DBA12C  (포인트 — 씬 번호 · 버튼 · 보더)
  ice-white  : #F7FBFC  (메인 배경)
  steel-gray : #C8D6DD  (서브 배경 · 칩)
  white      : #FFFFFF  (카드 배경)
  ─────────────────────────────────────────────────────────────
*/

/* ── 채널 배너 모서리 ── */
[data-testid="stImage"] img { border-radius: 12px; }

/* ── 전체 배경 ── */
.stApp { background-color: #F7FBFC; color: #142C3C; }
/* 본문 위젯 라벨·라디오 글자 — 브라우저가 다크 모드여도 읽히게 */
[data-testid="stMain"] [data-testid="stWidgetLabel"] p, [data-testid="stMain"] [data-testid="stWidgetLabel"] label,
[data-testid="stMain"] [role="radiogroup"] label p, [data-testid="stMain"] [data-testid="stExpander"] summary p,
[data-testid="stMain"] [data-testid="stCaptionContainer"], [data-testid="stMain"] .stMarkdown p { color: #142C3C !important; }

/* ── 사이드바 — 다크 네이비 ── */
section[data-testid="stSidebar"] {
    background-color: #142C3C !important;
    border-right: none;
}
section[data-testid="stSidebar"] * { color: rgba(255,255,255,0.88) !important; }
section[data-testid="stSidebar"] .stMarkdown h1,
section[data-testid="stSidebar"] .stMarkdown h2,
section[data-testid="stSidebar"] .stMarkdown h3 {
    color: #FFFFFF !important;
}
section[data-testid="stSidebar"] hr {
    border-color: rgba(255,255,255,0.15) !important;
}
/* 사이드바 버튼 — 골드 아웃라인 */
section[data-testid="stSidebar"] .stButton > button {
    background: transparent !important;
    border: 1px solid rgba(219,161,44,0.6) !important;
    color: rgba(255,255,255,0.88) !important;
    box-shadow: none !important;
    text-align: left;
    font-weight: 500 !important;
}
section[data-testid="stSidebar"] .stButton > button:hover {
    background: rgba(219,161,44,0.15) !important;
    border-color: #DBA12C !important;
    color: #FFFFFF !important;
}
/* 사이드바 새 프로젝트 버튼 — 골드 솔리드 */
section[data-testid="stSidebar"] .stButton:first-of-type > button {
    background: #DBA12C !important;
    border-color: #DBA12C !important;
    color: #142C3C !important;
    font-weight: 700 !important;
}

/* ── 씬 카드 ── */
.scene-card {
    background: #FFFFFF;
    border: 1.5px solid #C8D6DD;
    border-radius: 12px;
    padding: 14px 16px;
    margin-bottom: 12px;
    box-shadow: 0 2px 8px rgba(20,44,60,0.06);
    transition: border-color 0.15s, box-shadow 0.15s;
}
.scene-card:hover {
    border-color: #DBA12C;
    box-shadow: 0 4px 16px rgba(20,44,60,0.10);
}

/* ── 상태 배지 ── */
.badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.4px;
}
.badge-pending    { background:#EBF1F5; color:#6A8A9A; border:1px solid #C8D6DD; }
.badge-generating { background:#FDF5E3; color:#A07020; border:1px solid #DBA12C; }
.badge-done       { background:#E6F4EC; color:#1A6640; border:1px solid #7DC49A; }
.badge-error      { background:#FDECEA; color:#B03020; border:1px solid #EFA090; }

/* ── 씬 번호 / 이름 ── */
.scene-num {
    font-size: 22px;
    font-weight: 900;
    color: #DBA12C;
    line-height: 1;
}
.scene-name {
    font-size: 12px;
    color: #0F3B59;
    margin-top: 3px;
    font-weight: 600;
    letter-spacing: 0.02em;
}

/* ── 나레이션 박스 ── */
.narration-text {
    font-size: 13px;
    color: #142C3C;
    line-height: 1.75;
    margin: 8px 0;
    padding: 9px 14px;
    background: #F7FBFC;
    border-left: 3px solid #DBA12C;
    border-radius: 0 6px 6px 0;
}

/* ── 영문 프롬프트 박스 ── */
.prompt-text {
    font-size: 11px;
    color: #1E3A4E;
    font-family: monospace;
    background: #EBF1F5;
    padding: 6px 10px;
    border-radius: 6px;
    word-break: break-all;
    margin-top: 6px;
    border: 1px solid #C8D6DD;
    opacity: 0.85;
}

/* ── 메타 칩 (SFX / 오버레이) ── */
.meta-chips { display: flex; gap: 8px; margin-top: 6px; flex-wrap: wrap; }
.chip {
    font-size: 11px;
    padding: 2px 9px;
    border-radius: 12px;
    background: #C8D6DD;
    color: #0F3B59;
    border: 1px solid #B0C4CE;
    font-weight: 600;
}

/* ── 스텝 헤더 ── */
.step-header {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 14px 20px;
    background: #FFFFFF;
    border-radius: 10px;
    margin-bottom: 16px;
    border: 1.5px solid #C8D6DD;
    box-shadow: 0 2px 10px rgba(20,44,60,0.06);
}
.step-num {
    width: 34px; height: 34px;
    border-radius: 50%;
    background: #DBA12C;
    color: #142C3C;
    font-weight: 900;
    font-size: 15px;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
    box-shadow: 0 2px 8px rgba(219,161,44,0.35);
}
.step-num.done   { background: #142C3C; color: #DBA12C; box-shadow: none; }
.step-num.locked { background: #C8D6DD; color: #7A9AAA; box-shadow: none; }
.step-title { font-size: 15px; font-weight: 700; color: #142C3C; }
.step-sub   { font-size: 12px; color: #4A7A8A; margin-top: 2px; }

/* ── 프로그레스 바 ── */
div[data-testid="stProgress"] > div > div {
    background: linear-gradient(90deg, #DBA12C, #F0C050) !important;
}

/* ── 메인 영역 버튼 — 골드 솔리드 ── */
.stButton > button {
    background: #DBA12C !important;
    color: #142C3C !important;
    border: none !important;
    font-weight: 700 !important;
    border-radius: 8px !important;
    box-shadow: 0 2px 8px rgba(219,161,44,0.30) !important;
    transition: background 0.15s, box-shadow 0.15s;
}
.stButton > button:hover {
    background: #C8901A !important;
    box-shadow: 0 4px 14px rgba(219,161,44,0.45) !important;
}
/* ── 비활성(disabled) 버튼 — 명확하게 표시 ── */
.stButton > button:disabled,
.stButton > button[disabled] {
    background: #E8EFF3 !important;
    color: #8AAABB !important;
    border: 1.5px solid #C8D6DD !important;
    box-shadow: none !important;
    cursor: not-allowed;
    font-weight: 600 !important;
}

/* ── 입력 필드 — 라이트 테마 강제 ── */
.stTextInput > div > div > input {
    background-color: #FFFFFF !important;
    color: #142C3C !important;
    border: 1.5px solid #C8D6DD !important;
    border-radius: 8px !important;
}
.stTextInput > div > div > input:focus {
    border-color: #DBA12C !important;
    box-shadow: 0 0 0 2px rgba(219,161,44,0.20) !important;
}
.stTextInput > div > div > input::placeholder {
    color: #9ABBC8 !important;
}

/* ── 푸터 ── */
.factory-footer {
    text-align: center;
    color: #7A9AAA;
    font-size: 12px;
    padding: 24px 0 8px;
    border-top: 1px solid #C8D6DD;
    margin-top: 16px;
}

/* ── 파이프라인 현황 패널 ── */
.pipeline-panel {
    background: #FFFFFF;
    border: 1.5px solid #C8D6DD;
    border-radius: 12px;
    padding: 14px 20px 16px;
    margin-bottom: 18px;
    box-shadow: 0 2px 10px rgba(20,44,60,0.06);
}
.pipeline-title {
    font-size: 11px;
    font-weight: 700;
    color: #7A9AAA;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    margin-bottom: 12px;
}
.pipeline-steps {
    display: flex;
    gap: 0;
    align-items: stretch;
}
.pipe-step {
    flex: 1;
    padding: 10px 12px;
    border-radius: 8px;
    background: #F7FBFC;
    border: 1.5px solid #C8D6DD;
    margin-right: 6px;
    position: relative;
    min-width: 0;
}
.pipe-step:last-child { margin-right: 0; }
.pipe-step.done {
    background: #E8F5EE;
    border-color: #7DC49A;
}
.pipe-step.active {
    background: #FDF5E3;
    border-color: #DBA12C;
    box-shadow: 0 0 0 2px rgba(219,161,44,0.20);
    animation: pulse-border 1.8s ease-in-out infinite;
}
.pipe-step.locked {
    background: #EBF1F5;
    border-color: #C8D6DD;
    opacity: 0.65;
}
@keyframes pulse-border {
    0%, 100% { box-shadow: 0 0 0 2px rgba(219,161,44,0.20); }
    50%       { box-shadow: 0 0 0 4px rgba(219,161,44,0.38); }
}
.pipe-icon {
    font-size: 18px;
    line-height: 1;
    margin-bottom: 4px;
}
.pipe-label {
    font-size: 10px;
    font-weight: 700;
    color: #1E3A4E;
    letter-spacing: 0.02em;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.pipe-count {
    font-size: 11px;
    font-weight: 600;
    color: #4A7A8A;
    margin-top: 2px;
}
.pipe-step.done .pipe-label  { color: #1A6640; }
.pipe-step.done .pipe-count  { color: #2E8050; }
.pipe-step.active .pipe-label { color: #A07020; }
.pipe-step.active .pipe-count { color: #A07020; }
.pipe-connector {
    display: flex;
    align-items: center;
    color: #C8D6DD;
    font-size: 14px;
    padding: 0 2px;
    flex-shrink: 0;
}

/* ── 자동새로고침 배지 ── */
.refresh-badge {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    background: #FDF5E3;
    border: 1px solid #DBA12C;
    border-radius: 16px;
    padding: 3px 10px;
    font-size: 11px;
    font-weight: 600;
    color: #A07020;
}
</style>
""", unsafe_allow_html=True)

# ── 소스 모듈 임포트 ─────────────────────────────────────────────────────────
try:
    from src.state_manager import StateManager
    from src.prompts import generate_script_and_prompts
    from src.image_replicate import generate_images_for_scenes, generate_reference_image
    MODULES_OK = True
except ImportError as e:
    MODULES_OK = False
    IMPORT_ERROR = str(e)

# SEO 키워드 모듈 — 없어도 앱 기동에 영향 없음 (lazy)
try:
    from src.seo_keywords import (
        get_keywords_for_chapter,
        get_trending_keywords,
        get_daily_topics,
        GRADE_LABEL,
        ALL_CHAPTERS as SEO_CHAPTERS,
    )
    SEO_MODULE_OK = True
except ImportError:
    SEO_MODULE_OK = False

# ── 씬별 이미지 소스 판단 ────────────────────────────────────────────────────
# Claude가 대본 생성 시 scene_type과 visual_source를 함께 결정한다.
# visual_source: "ai"  → FLUX AI 생성 (인포그래픽·단면도·비교표·추출 시각화)
# visual_source: "photo" → Unsplash 실사 (산지 풍경·카페 분위기·역사 장면)
# 구 대본(visual_source 필드 없음) 호환을 위해 scene_type으로 폴백 판단.
_AI_SCENE_TYPES = {"ASSEMBLY", "MACHINE", "EXTRACTION", "SCIENCE_DATA"}

def needs_ai_image(scene: dict) -> bool:
    """scene의 visual_source 또는 scene_type으로 AI 이미지 생성 필요 여부 반환."""
    vs = scene.get("visual_source", "")
    if vs:
        return vs == "ai"
    # 폴백: scene_type 기반
    return scene.get("scene_type", "") in _AI_SCENE_TYPES


def unsplash_for_scene(scene: dict, all_scenes: list, access_key: str) -> str:
    """이 씬에 맞는 Unsplash 사진 — 다른 컷에서 이미 쓴 사진과 지금 사진은 건너뛴다."""
    from src.image_search import search_unsplash_pick, scene_to_query
    used = [s.get("_unsplash_id") for s in all_scenes if s.get("_unsplash_id")]
    url, pid = search_unsplash_pick(scene_to_query(scene), access_key, exclude_ids=used)
    scene["_unsplash_id"] = pid
    return url


def smart_ai_image(scene: dict, replicate_token: str, google_key: str) -> tuple:
    """
    씬 타입에 따라 최적 AI 엔진으로 이미지를 생성하고 (cdn_url, source_label)을 반환한다.

    라우팅:
      MACHINE / EXTRACTION / SCIENCE_DATA  →  Gemini Imagen 3 (수채화 스케치)
      ASSEMBLY                             →  FLUX Pro (포토리얼 음식사진)
      기타 / google_key 없음               →  FLUX Dev (폴백)

    Returns:
        tuple[str, str]: (Replicate CDN URL, source_label)
        source_label: "flux-illust" | "flux-pro" | "flux"
    """
    from src.image_replicate import (
        generate_reference_image, generate_illustration_image,
    )
    scene_type = scene.get("scene_type", "")
    prompt = (scene.get("image_prompt") or scene.get("flow_prompt") or "").strip()

    # SceneStory — 스케치(얼굴 없음) / 실사(사람 없음) / 타이틀 카드(서버에서 직접 그림)
    if scene_type in ("SKETCH", "PHOTO"):
        from src.image_replicate import generate_scenestory_image
        return generate_scenestory_image(replicate_token, prompt, scene_type), f"ss-{scene_type.lower()}"
    if scene_type == "TITLE":
        from src import scenestory as _ss
        _cur = st.session_state.get("current_project") or {}
        _ss.prepare_title_scenes(_cur)
        return scene.get("image_local") or scene.get("image_path", ""), "title"

    # MACHINE / EXTRACTION / SCIENCE_DATA → 일러스트·설계도 스타일 (flux-schnell + illust_mode)
    if scene_type in {"MACHINE", "EXTRACTION", "SCIENCE_DATA"}:
        url = generate_illustration_image(
            replicate_token=replicate_token,
            image_prompt=prompt,
        )
        return url, "flux-illust"

    # 1컷 훅 → 고품질 포토리얼 히어로샷 (flux-dev)
    if scene_type == "HOOK":
        url = generate_reference_image(replicate_token, prompt, hero_mode=True)
        return url, "flux-hero"

    # 그 외 (ASSEMBLY 포함) → FLUX Schnell (빠른 레퍼런스, 모든 씬 통일)
    url = generate_reference_image(replicate_token, prompt)
    label = "flux"
    return url, label

# ── API 키 로드 ───────────────────────────────────────────────────────────────
def load_api_keys():
    """secrets.toml → 환경변수 순으로 API 키 로드"""
    keys = {}
    for k in [
        "ANTHROPIC_API_KEY",
        "ELEVENLABS_API_KEY",
        "ELEVENLABS_VOICE_ID",
        "FAL_KEY",
        "REPLICATE_API_TOKEN",     # Replicate MiniMax Video-01 (fal.ai 대안 비디오 백엔드)
        "UNSPLASH_ACCESS_KEY",     # Unsplash 라이센스 프리 사진 검색용
        "GOOGLE_API_KEY",          # 구글 드라이브 이미지 목록 조회용 (폴백)
        "GDRIVE_REF_FOLDER_ID",    # 레퍼런스 이미지 폴더 ID (폴백)
        "R2_ENDPOINT",             # Cloudflare R2 (결과물 보관·전달)
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET",
        "ELEVENLABS_VOICE_ID_JA",  # SceneStory 일본어 나레이션 (없으면 기본값 사용)
    ]:
        try:
            keys[k] = st.secrets[k]
        except Exception:
            keys[k] = os.environ.get(k, "")
    return keys

# ── 세션 상태 초기화 ──────────────────────────────────────────────────────────
def init_session():
    defaults = {
        "current_project": None,   # dict: 현재 열린 프로젝트 state
        "manager": None,           # StateManager 인스턴스
        "gen_running": False,       # 생성 중 락
        "video_threads": {},        # scene_no → Thread
        "force_refresh": False,    # 버튼 직후 최소 1회 자동갱신 강제
        "stop_requested": False,   # 영상 배치 생성 중단 요청 플래그
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_session()

# 생성 락이 걸린 채 화면이 다시 실행되면(버튼 클릭·새로고침·연결 재접속) 락이 풀리지 않아
# 버튼이 계속 회색으로 멈춰 있던 문제 → 3분 넘은 락은 끊긴 작업으로 보고 푼다.
if st.session_state.get("gen_running") and \
        time.time() - st.session_state.get("gen_running_since", 0) > 180:
    st.session_state.gen_running = False

# ── StateManager 싱글턴 ───────────────────────────────────────────────────────
@st.cache_resource
def get_manager():
    return StateManager(storage_dir="projects")

# ── 헬퍼: 배지 HTML ───────────────────────────────────────────────────────────
STATUS_LABEL = {
    "pending":    ("⏳ 대기", "badge-pending"),
    "generating": ("⚙️ 생성중", "badge-generating"),
    "done":       ("✅ 완료", "badge-done"),
    "error":      ("❌ 오류", "badge-error"),
}

def badge_html(status: str) -> str:
    label, cls = STATUS_LABEL.get(status, ("?", "badge-pending"))
    return f'<span class="badge {cls}">{label}</span>'

# ── 헬퍼: 전체 진행률 계산 ────────────────────────────────────────────────────
def calc_progress(scenes: list) -> tuple[int, int]:
    """완료 씬 수, 전체 씬 수"""
    done = sum(1 for s in scenes if s.get("status") == "done")
    return done, len(scenes)

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    # ── 엔진 워드마크 ────────────────────────────────────────────────────────
    st.markdown(
        '<div style="padding:22px 8px 6px; text-align:center;">'
        '<div style="font-size:24px; font-weight:800; letter-spacing:0.04em; color:#FFFFFF;">'
        'MAKING SHORTS</div>'
        '<div style="font-size:13px; font-weight:700; letter-spacing:0.42em; color:#DBA12C; '
        'margin-top:2px;">ENGINE</div></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div style="text-align:center; color:rgba(255,255,255,0.55); font-size:12px; '
        f'margin:6px 0 10px;">지금 채널 · {CHANNELS[current_channel()]}</div>',
        unsafe_allow_html=True,
    )
    st.markdown("---")

    if not MODULES_OK:
        st.error(f"모듈 로드 실패\n```\n{IMPORT_ERROR}\n```")
        st.stop()

    manager = get_manager()

    # 새 프로젝트 버튼
    if st.button("✚ 새 프로젝트 시작", use_container_width=True):
        st.session_state.current_project = None
        st.rerun()

    st.markdown("#### 기존 프로젝트")
    projects = [p for p in manager.list_projects()
                if p.get("channel", "coffee") == current_channel()]

    if not projects:
        st.caption("아직 프로젝트가 없습니다.")
    else:
        for p in projects:
            label = p["title"][:40] + ("…" if len(p["title"]) > 40 else "")
            if st.button(label, key=f"proj_{p['id']}", use_container_width=True):
                st.session_state.current_project = manager.load_state(p["dir"])
                st.rerun()

    st.markdown("---")

    # ── JSON 백업 / 복구 ──────────────────────────────────────────────────────
    st.markdown(
        '<div style="color:rgba(255,255,255,0.6); font-size:11px; '
        'margin-bottom:6px;">💾 프로젝트 백업 / 복구</div>',
        unsafe_allow_html=True,
    )

    # 현재 프로젝트 JSON 다운로드
    if st.session_state.get("current_project"):
        import json as _json
        _proj = st.session_state.current_project
        _json_bytes = _json.dumps(_proj, ensure_ascii=False, indent=2).encode("utf-8")
        _filename = f"{_proj.get('title', 'project')[:30]}.json"
        st.download_button(
            label="⬇ 현재 프로젝트 JSON 저장",
            data=_json_bytes,
            file_name=_filename,
            mime="application/json",
            use_container_width=True,
            key="json_download",
        )
    else:
        st.caption("프로젝트를 선택하면 JSON 저장 버튼이 나타납니다.")

    # JSON 업로드로 복구
    uploaded_json = st.file_uploader(
        "⬆ JSON 업로드로 복구",
        type=["json"],
        key="json_upload",
        label_visibility="collapsed",
    )
    # 업로드 파일은 업로더에 계속 남아 있으므로, 같은 파일은 한 번만 복구한다.
    # (이 검사가 없으면 복구 → rerun → 다시 복구 → rerun … 무한 반복되어 대시보드가 안 뜸)
    _upload_id = (
        getattr(uploaded_json, "file_id", None)
        or (f"{uploaded_json.name}:{uploaded_json.size}" if uploaded_json is not None else None)
    ) if uploaded_json is not None else None
    if uploaded_json is not None and st.session_state.get("_restored_upload_id") != _upload_id:
        import json as _json
        try:
            st.session_state._restored_upload_id = _upload_id
            restored = _json.loads(uploaded_json.getvalue().decode("utf-8"))
            # ① 세션 상태 먼저 설정 — 디스크 저장 실패와 무관하게 복구 보장
            st.session_state.current_project = restored
            # 복구한 프로젝트의 채널로 화면 전환 (채널 선택 위젯이 그려지기 전이라 바꿀 수 있음)
            st.session_state["channel_pick"] = project_channel(restored)
            st.session_state["_last_channel"] = project_channel(restored)
            # ② 디렉터리 생성 후 디스크 저장 시도 (실패해도 세션 복구는 유지)
            try:
                import os as _os
                proj_dir = restored.get("project_dir", "")
                if proj_dir:
                    _os.makedirs(proj_dir, exist_ok=True)
                manager.save_state(restored)
            except Exception:
                pass  # 디스크 저장 실패는 무시 — 세션 내 작업은 계속 가능
            st.success("복구 완료!")
            time.sleep(0.5)
            st.rerun()
        except Exception as _e:
            st.error(f"복구 실패: {_e}")

    st.markdown("---")

    # ── 연결 테스트 (R2 보관소 · Google Lyria 음악) ─────────────────────────
    with st.expander("🔧 연결 테스트"):
        _tk = load_api_keys()
        if st.button("☁️ R2 연결 테스트", key="r2_test_btn", use_container_width=True):
            from src import r2_store
            with st.spinner("R2 에 작은 파일을 올리고 다시 받는 중…"):
                st.session_state["_r2_report"] = r2_store.test_connection(_tk)
        _r2 = st.session_state.get("_r2_report")
        if _r2:
            for _name, _ok, _msg in _r2["steps"]:
                st.markdown(f"{'✅' if _ok else '❌'} **{_name}** — {_msg}")
            if _r2["ok"]:
                st.success("R2 연결 성공 — 버킷에 _tests/connection_test.txt 가 생겼습니다.")

        st.markdown("---")
        st.caption("SceneStory 일본어 목소리로 시험 문장을 읽혀 속도를 잽니다.")
        if st.button("🎙 일본어 목소리 테스트", key="ja_voice_btn", use_container_width=True):
            from src import voice_test
            with st.spinner("일본어 음성 만드는 중…"):
                st.session_state["_ja_voice"] = voice_test.test_voice(
                    _tk.get("ELEVENLABS_API_KEY", ""),
                    _tk.get("ELEVENLABS_VOICE_ID_JA", "") or voice_test.JA_VOICE_ID)
        _jv = st.session_state.get("_ja_voice")
        if _jv:
            from src import voice_test
            if _jv["ok"]:
                st.success(f"성공 — {_jv['seconds']}초 · 초당 {_jv['cps']}자 "
                           f"(문장부호 빼면 {_jv['cps_no_punct']}자)")
                st.audio(_jv["audio"], format="audio/mpeg")
            else:
                st.error(f"실패 — {_jv['error']}")
            st.download_button("⬇ 측정 결과 JSON (Claude 에게 전달용)",
                               data=voice_test.result_json(_jv), file_name="ja_voice_test.json",
                               mime="application/json", key="ja_voice_dl", use_container_width=True)

        st.markdown("---")
        st.caption("Lyria 30초 음악 클립 1개를 받아 봅니다 (Google 요금이 발생할 수 있음).")
        if st.button("🎵 Lyria 연결 테스트", key="lyria_test_btn", use_container_width=True):
            from src import music_lyria
            with st.spinner("음악 만드는 중… (보통 수십 초)"):
                st.session_state["_lyria_report"] = music_lyria.test_clip(_tk.get("GOOGLE_API_KEY", ""))
        _ly = st.session_state.get("_lyria_report")
        if _ly:
            from src import music_lyria
            if _ly["ok"]:
                st.success(f"성공 — {_ly['model']} · {_ly['seconds']}초 걸림 · "
                           f"{len(_ly['audio']) // 1024}KB")
                st.audio(_ly["audio"], format=_ly["mime"] or "audio/mpeg")
            else:
                st.error(f"실패 — {_ly['error']}")
            st.download_button("⬇ 응답 구조 JSON (Claude 에게 전달용)",
                               data=music_lyria.structure_json(_ly),
                               file_name="lyria_test_response.json", mime="application/json",
                               key="lyria_json_dl", use_container_width=True)

    st.markdown("---")
    st.markdown(
        '<div style="text-align:center; color:rgba(255,255,255,0.4); '
        'font-size:10px; line-height:1.7; padding:4px 0 8px;">'
        'Claude · ElevenLabs · Replicate · Google Lyria · Cloudflare R2<br>'
        '<span style="color:rgba(219,161,44,0.6);">Making Shorts Engine · BLUE JEANS PICTURES</span>'
        '</div>',
        unsafe_allow_html=True,
    )

# ─────────────────────────────────────────────────────────────────────────────
# 채널 선택 (너도나도아는커피 · SceneStory · HASIRA_yo!)
# ─────────────────────────────────────────────────────────────────────────────
def _on_channel_change():
    ch = st.session_state.get("channel_pick")
    if ch not in CHANNELS:          # 선택된 것을 다시 눌러 해제한 경우 → 이전 채널 유지
        st.session_state["channel_pick"] = st.session_state.get("_last_channel", "coffee")
        return
    st.session_state["_last_channel"] = ch
    cur = st.session_state.get("current_project")
    if cur and project_channel(cur) != ch:
        st.session_state.current_project = None


if st.session_state.get("channel_pick") not in CHANNELS:
    st.session_state["channel_pick"] = st.session_state.get("_last_channel", "coffee")
st.segmented_control(
    "채널", CHANNEL_KEYS, format_func=lambda k: CHANNELS[k],
    key="channel_pick", on_change=_on_channel_change, label_visibility="collapsed",
)
CHANNEL = current_channel()
st.session_state["_last_channel"] = CHANNEL

# ─────────────────────────────────────────────────────────────────────────────
# API 키 체크
# ─────────────────────────────────────────────────────────────────────────────
api_keys = load_api_keys()
# FAL_KEY는 선택 사항 — REPLICATE_API_TOKEN 으로 대체 가능
REQUIRED_KEYS = ["ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY"]
missing = [k for k in REQUIRED_KEYS if not api_keys.get(k)]
if missing:
    st.warning(
        f"API 키가 설정되지 않았습니다: **{', '.join(missing)}**\n\n"
        "`.streamlit/secrets.toml` 또는 Streamlit Cloud Secrets에 등록해 주세요.",
        icon="⚠️",
    )



def show_channel_banner(ch: str):
    """채널 배너 (assets/images/banner_<채널>.jpg). 파일을 같은 이름으로 바꿔 올리면 그대로 반영된다."""
    p = Path(__file__).parent / "assets" / "images" / f"banner_{ch}.jpg"
    if p.exists():
        st.image(str(p), use_container_width=True)
    else:
        st.markdown(f"## {CHANNELS[ch]}")


if CHANNEL == "scenestory" and st.session_state.current_project is None:
    from src import scenestory as ss
    show_channel_banner("scenestory")
    st.markdown(
        '<p style="text-align:center; color:#1E3A4E; font-size:14px; margin:4px 0 18px;">'
        '키워드 하나만 넣으면 Claude 가 웹에서 실제 작품 속 장면 후보 3개를 찾아 옵니다. '
        '하나를 고르면 일본어 대본을 쓰고 사실을 다시 확인합니다.</p>',
        unsafe_allow_html=True,
    )
    st.session_state.setdefault("ss_cands", [])
    st.session_state.setdefault("ss_seen", [])

    with st.form("ss_find_form", border=False):
        _k1, _k2 = st.columns([4, 1], vertical_alignment="bottom")
        with _k1:
            ss_kw = st.text_input("① 키워드", key="ss_kw",
                                  placeholder="예: 불륜 남편 / 첫사랑 편지 / 금요일의 아내들에게 / 벚꽃 이별")
        with _k2:
            _find = st.form_submit_button("🔎 장면 찾기", type="primary", use_container_width=True)

    def _ss_search(exclude):
        if not ss_kw.strip():
            st.error("키워드를 입력해 주세요.")
        elif not api_keys.get("ANTHROPIC_API_KEY"):
            st.error("ANTHROPIC_API_KEY 가 없습니다.")
        else:
            with st.spinner("웹에서 작품과 장면을 찾는 중… (약 30초~1분)"):
                r = ss.find_candidates(api_keys["ANTHROPIC_API_KEY"], ss_kw, exclude=exclude)
            if r["error"] and not r["candidates"]:
                st.error(f"후보를 찾지 못했습니다. 키워드를 바꿔 보세요.\n\n{r['error']}")
            st.session_state.ss_cands = r["candidates"]
            st.session_state.ss_seen = list(dict.fromkeys(
                (exclude or []) + [c["work"] for c in r["candidates"]]))

    if _find:
        _ss_search([])

    _cands = st.session_state.ss_cands
    _pick = None
    if _cands:
        st.markdown("**② 장면 고르기**")
        for _i, _c in enumerate(_cands):
            with st.container(border=True):
                _meta = " · ".join(x for x in (ss.GENRES.get(_c.get("genre"), ""), _c.get("year"),
                                                _c.get("origin"), _c.get("creator")) if x)
                _ko = f" ({_c['work_ko']})" if _c.get("work_ko") and _c["work_ko"] != _c["work"] else ""
                st.markdown(f"**『{_c['work']}』**{_ko}  \n<small>{_meta}</small>", unsafe_allow_html=True)
                st.write(_c.get("scene", ""))
                _nm = [x for x in (_c.get("names") or []) if isinstance(x, dict) and x.get("name")]
                if _nm:
                    st.caption("이름·지명 · " + " / ".join(
                        f"{x['name']}（{x.get('yomi', '')}）" + (f" {x['who']}" if x.get("who") else "") for x in _nm))
                if _c.get("angle"):
                    st.caption(f"해설 각도 · {_c['angle']}")
                if _c.get("why"):
                    st.caption(f"시니어 포인트 · {_c['why']}")
                if _c.get("source"):
                    st.caption(f"근거 · {_c['source']}")
                if st.button("✍️ 이 장면으로 대본 만들기", key=f"ss_pick_{_i}", type="primary",
                             use_container_width=True):
                    _pick = _c
        if st.button("🔄 다른 후보 찾기", key="ss_more"):
            _ss_search(st.session_state.ss_seen)
            st.rerun()

    with st.expander("세부 설정 (선택 — 그대로 두어도 됩니다)"):
        ss_note = st.text_area("작가 해설 한 줄 — 비우면 후보 카드의 해설 각도를 씁니다", height=70, key="ss_note",
                               placeholder="예: 옆집 창문이 보이는 거리가 불륜 드라마의 무대가 된 이유")
        _c1, _c2 = st.columns(2)
        with _c1:
            ss_length = st.radio("영상 길이", list(ss.LENGTH_PRESETS), index=2,
                                 format_func=lambda k: ss.LENGTH_PRESETS[k]["label"], key="ss_length")
        with _c2:
            ss_closing = st.selectbox("엔딩 멘트 (마지막 컷)", ss.CLOSING_PRESETS, key="ss_closing")

    if _pick is not None:
        _form = ss.form_from_candidate(_pick, ss_note)
        with st.status(f"『{_pick['work']}』 일본어 대본을 쓰고 사실을 확인합니다… (약 1~3분)", expanded=True):
            try:
                new_state = manager.create_new_project(chapter=_form["genre"], topic=_form["work"],
                                                       channel="scenestory")
                result = ss.generate_script(api_keys["ANTHROPIC_API_KEY"], _form, progress=st.write,
                                            closing=ss_closing, length=ss_length)
                _form = result.get("form") or _form
                new_state["topic"] = _form.get("work", new_state.get("topic", ""))
                new_state.update(
                    title=result.get("title", ""), title_card=result.get("title_card", {}),
                    full_narration=result.get("full_narration", ""), scenes=result.get("scenes", []),
                    verification=result.get("verification", {}), closing=result.get("closing", ss_closing),
                    length=result.get("length", ss_length), ss_form=_form, ss_keyword=ss_kw.strip(),
                    status="script_ready",
                )
                st.write("④ 타이틀 카드 만드는 중…")
                ss.prepare_title_scenes(new_state)
                manager.save_state(new_state)
                st.session_state.current_project = new_state
                st.session_state.ss_cands, st.session_state.ss_seen = [], []
                st.success("대본 생성 완료!")
                time.sleep(0.5)
                st.rerun()
            except Exception as e:
                st.error(f"대본 생성 중 오류가 발생했습니다:\n```\n{e}\n```")
    st.stop()

if CHANNEL == "hasira":
    show_channel_banner("hasira")
    st.info("HASIRA_yo! 음악 제작 라인은 준비 중입니다. 먼저 사이드바 「🔧 연결 테스트」에서 "
            "R2 와 Lyria 연결을 확인해 주세요.")
    st.markdown(
        "- **음악**: Google Lyria 로 곡 여러 개를 만들어 크로스페이드로 1시간 이상 연결\n"
        "- **영상**: 16:9 그림 한 장 + 반복 움직임(비 · 눈 · 꽃잎 · 김 · 불빛)\n"
        "- **전달**: 완성본은 Cloudflare R2 에 올리고 7일짜리 내려받기 링크로 받기\n"
        "- **업로드 정보**: 곡 목록 타임스탬프(챕터)가 들어간 설명 자동 작성"
    )
    st.stop()

# ─────────────────────────────────────────────────────────────────────────────
# 새 프로젝트 생성 폼 (프로젝트 미선택 시)
# ─────────────────────────────────────────────────────────────────────────────
if st.session_state.current_project is None:
    # 웰컴 헤더 — 채널 배너
    show_channel_banner("coffee")

    st.markdown(
        '<p style="text-align:center; color:#1E3A4E; font-size:14px; margin:4px 0 24px;">'
        '챕터와 주제를 입력하면 Claude AI가 12컷 대본을 자동 생성합니다.'
        '</p>',
        unsafe_allow_html=True,
    )
    st.markdown("---")

    # ── 챕터 목록 (드롭다운) ─────────────────────────────────────────────────
    CHAPTERS = {
        "CH01 · 커피의 탄생과 역사":    "CH01 커피의 탄생과 역사",
        "CH02 · 품종과 원산지":         "CH02 품종과 원산지",
        "CH03 · 가공 방식 (프로세싱)":  "CH03 가공 방식",
        "CH04 · 로스팅의 과학":         "CH04 로스팅의 과학",
        "CH05 · 에스프레소의 원리":     "CH05 에스프레소의 원리",
        "CH06 · 브루잉 방법론":         "CH06 브루잉 방법론",
        "CH07 · 아이스 & 시그니처 음료":"CH07 아이스 & 시그니처 음료",
        "CH08 · 카페 문화와 트렌드":    "CH08 카페 문화와 트렌드",
        "CH09 · 커피와 건강":           "CH09 커피와 건강",
        "CH10 · 홈카페 장비 가이드":    "CH10 홈카페 장비 가이드",
        "─────────────":               None,          # 구분선 역할 (선택 불가)
        "챕터 없이 주제만으로 생성":    "MISC",
    }
    CHAPTER_LABELS = list(CHAPTERS.keys())

    # ── session_state: SEO 키워드 클릭 시 topic 자동 채우기 ─────────────────
    if "seo_selected_topic" not in st.session_state:
        st.session_state["seo_selected_topic"] = ""

    # SEO 버튼 클릭 후 rerun 시 위젯 렌더링 전에 값을 적용 (위젯 충돌 방지)
    if st.session_state.get("_seo_pending_topic"):
        st.session_state["topic_text_input"] = st.session_state["_seo_pending_topic"]
        st.session_state["seo_selected_topic"] = st.session_state["_seo_pending_topic"]
        del st.session_state["_seo_pending_topic"]

    # 주제 입력 — 가장 크게, 맨 위
    if "topic_text_input" not in st.session_state:
        st.session_state["topic_text_input"] = st.session_state.get("seo_selected_topic", "")
    topic = st.text_input(
        "어떤 커피 이야기를 만들까요?",
        placeholder="예: 아이스아메리카노와 롱블랙의 차이   |   예가체프 내추럴 프로세싱의 비밀",
        help="구체적인 키워드나 질문 형태로 입력할수록 대본 품질이 높아집니다.",
        key="topic_text_input",
    )
    # 직접 타이핑하면 SEO 선택값 초기화 (충돌 방지)
    if topic != st.session_state.get("seo_selected_topic", ""):
        st.session_state["seo_selected_topic"] = topic

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # 챕터 선택 — 선택형, 기본값은 "챕터 없이"
    col_ch, col_gap = st.columns([2, 3])
    with col_ch:
        chapter_label = st.selectbox(
            "챕터 분류 (선택)",
            options=CHAPTER_LABELS,
            index=CHAPTER_LABELS.index("챕터 없이 주제만으로 생성"),
            help="챕터를 선택하면 해당 영역에 맞는 대본이 생성됩니다. 몰라도 괜찮습니다.",
        )

    # 구분선 선택 방지
    chapter_val = CHAPTERS.get(chapter_label)
    if chapter_val is None:
        st.warning("구분선은 선택할 수 없습니다. 다른 챕터를 선택해 주세요.")
        chapter_val = "MISC"

    # 최종 챕터 문자열
    chapter = "" if chapter_val == "MISC" else chapter_val

    # ── SEO 키워드 추천 UI ────────────────────────────────────────────────────
    if SEO_MODULE_OK:
        with st.expander("💡 SEO 인기 키워드 추천 (클릭하면 자동 입력됩니다)", expanded=False):
            # 탭: 큐레이션 / 실시간
            tab_bank, tab_live = st.tabs(["🗓 오늘의 추천 주제", "📡 YouTube 실시간 트렌드"])

            with tab_bank:
                # 매일 바뀌는 추천 주제: YouTube 자동완성(실제 검색어) + Claude 기획, 이미 만든 주제 제외
                _refresh = st.button("🔄 다른 주제 받기", key="seo_daily_refresh")
                if _refresh or "seo_daily" not in st.session_state:
                    with st.spinner("오늘의 주제를 고르는 중… (약 10초)"):
                        st.session_state["seo_daily"] = get_daily_topics(
                            api_keys.get("ANTHROPIC_API_KEY", ""),
                            made_titles=[p["title"] for p in manager.list_projects()],
                            refresh=_refresh,
                        )
                _daily = st.session_state["seo_daily"]
                _kw_list = _daily.get("topics", [])
                st.caption(
                    f"{_daily.get('date', '')} 기준 · "
                    + (f"YouTube 검색어 {_daily.get('signals', 0)}개 반영 · " if _daily.get("signals") else "검색어 수집 실패 → AI 기획만 반영 · ")
                    + "📡 = 실제 검색어에서 나온 주제 · 이미 만든 주제는 제외"
                )
                if _daily.get("note"):
                    st.caption(_daily["note"])
                _cols = st.columns(2)
                for _i, _kw in enumerate(_kw_list):
                    _tag = "📡" if _kw.get("source") == "youtube" else GRADE_LABEL.get(_kw.get("grade", ""), "💡")
                    with _cols[_i % 2]:
                        if st.button(f"{_tag}  {_kw['topic']}", key=f"seo_bank_{_i}",
                                     use_container_width=True, help=_kw.get("signal") or None):
                            st.session_state["_seo_pending_topic"] = _kw["topic"]
                            st.rerun()

            with tab_live:
                # 씨앗 키워드: 챕터 첫 단어 or 기본값 "커피"
                _seed_word = chapter.split()[0] if chapter else "커피"
                st.caption(f"'{_seed_word}' 기준 YouTube 자동완성 실시간 조회")
                if st.button("🔄 실시간 조회", key="seo_refresh_live"):
                    st.session_state["seo_live_keywords"] = get_trending_keywords(
                        _seed_word, max_realtime=8
                    )

                _live_kws = st.session_state.get("seo_live_keywords", [])
                if _live_kws:
                    _live_cols = st.columns(2)
                    for _j, _kw in enumerate(_live_kws):
                        _src_tag = "📡" if _kw["source"] == "youtube" else GRADE_LABEL.get(_kw["grade"], "")
                        _label = f"{_src_tag}  {_kw['topic']}"
                        with _live_cols[_j % 2]:
                            if st.button(_label, key=f"seo_live_{_j}", use_container_width=True):
                                st.session_state["_seo_pending_topic"] = _kw["topic"]
                                st.rerun()
                elif "seo_live_keywords" in st.session_state:
                    st.warning("YouTube 자동완성을 받아오지 못했습니다. 잠시 뒤 다시 조회해 주세요.")
                else:
                    st.info("'실시간 조회' 버튼을 눌러 YouTube 트렌드 키워드를 가져오세요.")

    # 엔딩 멘트 (12컷 고정 문장)
    from src.prompts import CLOSING_PRESETS
    _closing_opts = CLOSING_PRESETS + ["직접 입력"]
    _closing_pick = st.selectbox("엔딩 멘트 (마지막 컷)", _closing_opts, index=0, key="closing_pick",
                                 help="자막에는 '너도나도아는커피'로, 성우 낭독은 '너도나도 아는 커피'로 띄어 읽습니다.")
    if _closing_pick == "직접 입력":
        _closing_text = st.text_input("엔딩 멘트 직접 입력", value="", key="closing_custom",
                                      placeholder="예: 알고 마시면 더 맛있습니다. 너도나도아는커피.").strip()
    else:
        _closing_text = _closing_pick

    # 영상 길이 (컷 수·낭독 분량이 함께 바뀜)
    from src.prompts import LENGTH_PRESETS, DEFAULT_LENGTH
    _len_keys = list(LENGTH_PRESETS.keys())
    _length_key = st.radio(
        "영상 길이", _len_keys, index=_len_keys.index(DEFAULT_LENGTH), horizontal=True,
        format_func=lambda k: LENGTH_PRESETS[k]["label"], key="length_pick",
        help="같은 주제를 짧게도 만들어 '시청함 비율'을 비교해 보세요. 짧을수록 영상 생성 비용도 줄어듭니다.",
    )

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    start_btn = st.button(
        "☕ 대본 생성 시작",
        disabled=(not topic.strip() or not api_keys.get("ANTHROPIC_API_KEY")),
        use_container_width=False,
    )

    if start_btn:
        if not topic.strip():
            st.error("주제를 입력해 주세요.")
        else:
            chapter_for_api = chapter.strip() if chapter.strip() else "MISC"
            with st.status("Claude AI가 대본을 쓰고 스스로 검증합니다… (약 1~3분)", expanded=True) as _sst:
                try:
                    # 프로젝트 디렉터리 생성
                    new_state = manager.create_new_project(
                        chapter=chapter_for_api,
                        topic=topic.strip(),
                        channel="coffee",
                    )
                    # Claude API 호출
                    result = generate_script_and_prompts(
                        api_key=api_keys["ANTHROPIC_API_KEY"],
                        chapter=chapter_for_api,
                        topic=topic.strip(),
                        progress=st.write,
                        closing=_closing_text,
                        length=_length_key,
                    )
                    # state 업데이트
                    new_state["full_narration"] = result.get("full_narration", "")
                    new_state["scenes"] = result.get("scenes", [])
                    new_state["verification"] = result.get("verification", {})
                    new_state["closing"] = result.get("closing", _closing_text)
                    new_state["length"] = result.get("length", _length_key)
                    new_state["status"] = "script_ready"
                    manager.save_state(new_state)

                    st.session_state.current_project = new_state
                    st.success("대본 생성 완료!")
                    time.sleep(0.5)
                    st.rerun()

                except Exception as e:
                    st.error(f"대본 생성 중 오류가 발생했습니다:\n```\n{e}\n```")

    st.stop()  # 프로젝트 없을 때는 여기까지

# ─────────────────────────────────────────────────────────────────────────────
# 프로젝트 대시보드 (프로젝트 선택됨)
# ─────────────────────────────────────────────────────────────────────────────
state = st.session_state.current_project

# ── 백그라운드 영상 작업이 있으면 그 작업이 갱신 중인 상태를 화면에 사용 ──────────
from src import video_jobs, media_store
PROJECT_KEY = state.get("project_id") or state.get("project_dir", "")
_vjob = video_jobs.get_job(PROJECT_KEY)
VIDEO_BUSY = video_jobs.is_running(PROJECT_KEY)
if _vjob is not None and (VIDEO_BUSY or not _vjob.get("ui_done")):
    state = _vjob["state"]
    st.session_state.current_project = state
    if not VIDEO_BUSY:
        _vjob["ui_done"] = True
        if _vjob.get("error"):
            st.session_state.video_error_msg = _vjob["error"]
if not VIDEO_BUSY:
    # 작업이 없는데 '생성중'으로 남은 컷(끊긴 작업의 흔적)은 '대기'로 정리
    for _s in state.get("scenes", []):
        if _s.get("status") == "generating":
            _s["status"] = "pending"

scenes = state.get("scenes", [])
done_cnt, total_cnt = calc_progress(scenes)

# ── 상단 헤더 ─────────────────────────────────────────────────────────────────
st.markdown(f"## [{state.get('chapter','')}] {state.get('topic','')}")

col_info, col_reload = st.columns([6, 1])
with col_info:
    st.caption(
        f"프로젝트 ID: `{state.get('project_id','')}` · "
        f"상태: `{state.get('status','')}` · "
        f"영상 진행: **{done_cnt}/{total_cnt}**컷 완료"
    )
with col_reload:
    if st.button("🔄 새로고침"):
        try:
            refreshed = manager.load_state(state["project_dir"])
            st.session_state.current_project = refreshed
        except Exception:
            pass
        st.rerun()

if total_cnt > 0:
    st.progress(done_cnt / total_cnt)

# ─────────────────────────────────────────────────────────────────────────────
# 파이프라인 현황 패널 (모든 단계 한눈에)
# ─────────────────────────────────────────────────────────────────────────────
img_done_cnt_panel = sum(1 for s in scenes if s.get("image_status") == "done")
img_generating     = any(s.get("image_status") == "generating" for s in scenes)
vid_generating     = any(s.get("status") == "generating" for s in scenes)

any_generating = img_generating or vid_generating or st.session_state.get("force_refresh", False)


def _pipe_cls(done: bool, active: bool, locked: bool) -> str:
    if done:   return "done"
    if active: return "active"
    if locked: return "locked"
    return ""


def _pipe_icon(done: bool, active: bool, locked: bool) -> str:
    if done:   return "✅"
    if active: return "⚙️"
    if locked: return "🔒"
    return "⏳"


p1_done   = bool(scenes)
p1_active = False
p1_locked = False

p2_done   = (img_done_cnt_panel == total_cnt and total_cnt > 0)
p2_active = img_generating
p2_locked = not p1_done

p3_done   = bool(state.get("audio_path"))
p3_active = False
p3_locked = not p1_done

p4_done   = (done_cnt == total_cnt and total_cnt > 0)
p4_active = vid_generating
p4_locked = not p1_done

p5_done   = bool(state.get("final_video_path"))
p5_active = False
p5_locked = done_cnt < total_cnt or total_cnt == 0 or not state.get("audio_path")


def _pipe_step_html(icon, label, count_str, cls):
    return (
        f'<div class="pipe-step {cls}">'
        f'<div class="pipe-icon">{icon}</div>'
        f'<div class="pipe-label">{label}</div>'
        f'<div class="pipe-count">{count_str}</div>'
        f'</div>'
    )


refresh_badge = ""
if any_generating:
    refresh_badge = '<span class="refresh-badge">⚙️ 생성 중 · 자동 새로고침</span>'

s1 = _pipe_step_html(_pipe_icon(p1_done,p1_active,p1_locked), "① 대본",   "완료" if p1_done else "대기",                              _pipe_cls(p1_done,p1_active,p1_locked))
s2 = _pipe_step_html(_pipe_icon(p2_done,p2_active,p2_locked), "② 이미지", f"{img_done_cnt_panel}/{total_cnt}컷" if not p2_locked else "잠금", _pipe_cls(p2_done,p2_active,p2_locked))
s3 = _pipe_step_html(_pipe_icon(p3_done,p3_active,p3_locked), "③ 음성",   "완료" if p3_done else ("대기" if p3_locked else "준비중"),         _pipe_cls(p3_done,p3_active,p3_locked))
s4 = _pipe_step_html(_pipe_icon(p4_done,p4_active,p4_locked), "④ 영상",   f"{done_cnt}/{total_cnt}컷" if not p4_locked else "잠금",           _pipe_cls(p4_done,p4_active,p4_locked))
s5 = _pipe_step_html(_pipe_icon(p5_done,p5_active,p5_locked), "⑤ 합성",   "완료" if p5_done else ("잠금" if p5_locked else "대기"),           _pipe_cls(p5_done,p5_active,p5_locked))

panel_html = (
    '<div class="pipeline-panel">'
    '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">'
    '<div class="pipeline-title">⚡ 파이프라인 현황</div>'
    f'{refresh_badge}'
    '</div>'
    f'<div class="pipeline-steps">{s1}{s2}{s3}{s4}{s5}</div>'
    '</div>'
)
st.markdown(panel_html, unsafe_allow_html=True)

st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — 대본 (항상 표시, 완료 상태)
# ─────────────────────────────────────────────────────────────────────────────
step1_done = bool(scenes)

step1_cls  = "done" if step1_done else ""
st.markdown(f"""
<div class="step-header">
  <div class="step-num {step1_cls}">{"✓" if step1_done else "1"}</div>
  <div>
    <div class="step-title">STEP 1 · 대본 생성 (Claude API)</div>
    <div class="step-sub">{"12컷 대본 · Kling 영문 프롬프트 · SFX 태그 완성" if step1_done else "대본을 아직 생성하지 않았습니다."}</div>
  </div>
</div>
""", unsafe_allow_html=True)

if step1_done:
    with st.expander("전체 나레이션 원고 보기", expanded=False):
        st.markdown(f"""
        <div style="
            background:#130f0b; border-left:4px solid #c8a96e;
            padding:16px 20px; border-radius:0 8px 8px 0;
            font-size:14px; line-height:1.8; color:#d4cfc8;
            white-space:pre-wrap;
        ">{state.get('full_narration','(없음)')}</div>
        """, unsafe_allow_html=True)

    # 대본 자동 검증 리포트
    _ver = state.get("verification") or {}
    if _ver:
        _rem = _ver.get("remaining_issues") or []
        _bad = [c for c in (_ver.get("claims") or []) if c.get("verdict") in ("수정필요", "근거없음")]
        _title = (
            f"🔎 대본 자동 검증 — 예상 길이 약 {_ver.get('est_seconds', '?')}초 · "
            f"{'웹 검색 팩트체크' if _ver.get('web_search') else '모델 지식 검증 (웹 검색 불가)'} · "
            f"자동 수정 {_ver.get('revise_rounds', 0)}회"
            + (f" · ⚠️ 남은 문제 {len(_rem)}건" if _rem else " · 규칙 통과")
        )
        with st.expander(_title, expanded=bool(_rem)):
            for _r in _rem:
                st.warning(_r)
            if _bad:
                st.markdown("**초안에서 고친 사실 오류**")
                for _c in _bad:
                    _src = f" — [출처]({_c['source']})" if str(_c.get("source", "")).startswith("http") else ""
                    st.markdown(f"- {_c.get('scene_no', '')}씬 · {_c.get('verdict')}: {_c.get('claim', '')} → {_c.get('correction', '')}{_src}")
            _ok = [c for c in (_ver.get("claims") or []) if c.get("verdict") == "확인"]
            if _ok:
                st.markdown("**확인된 사실**")
                for _c in _ok:
                    _src = f" — [출처]({_c['source']})" if str(_c.get("source", "")).startswith("http") else ""
                    st.markdown(f"- {_c.get('scene_no', '')}씬 · {_c.get('claim', '')}{_src}")

    # SceneStory — 길이가 범위를 벗어난 대본: 나레이션만 줄이기 (이미지·영상은 그대로)
    if project_channel(state) == "scenestory":
        from src import scenestory as _ss
        _lo, _hi = _ss.LENGTH_PRESETS.get(state.get("length") or "long", _ss.LENGTH_PRESETS["long"])["total"]
        _now = _ss._total(state)
        _no_yomi = not (state.get("title_card") or {}).get("work_yomi")
        _tsub, _ = _ss.title_narration(state.get("title_card") or {})
        _old_title = any(sc.get("scene_type") == "TITLE" and _tsub and sc.get("narration") != _tsub
                         for sc in state.get("scenes", []))
        _no_yomi = _no_yomi or _old_title
        if not _lo <= _now <= _hi or _no_yomi:
            _why = []
            if not _lo <= _now <= _hi:
                _why.append(f"나레이션이 약 {round(_now / _ss.JA_CPS)}초입니다 (목표 {round(_lo / _ss.JA_CPS)}~{round(_hi / _ss.JA_CPS)}초).")
            if _no_yomi:
                _why.append("작품명·작가·연도 표기나 읽기(발음)를 새 방식으로 고칠 수 있는 편입니다.")
            st.error(" ".join(_why) + " 아래 버튼은 나레이션 글만 고치고 이미지·영상 클립은 그대로 둡니다. "
                     "그다음 음성과 합성만 다시 하면 됩니다.")
            if st.button("✂️ 나레이션 길이·발음 맞추기", key="ss_fit_len", type="primary"):
                if not api_keys.get("ANTHROPIC_API_KEY"):
                    st.error("ANTHROPIC_API_KEY가 없습니다.")
                else:
                    with st.status("나레이션 길이·발음 맞추는 중… (약 30초~1분)", expanded=True):
                        try:
                            _ss.refit_project(api_keys["ANTHROPIC_API_KEY"], state, progress=st.write)
                            state["audio_path"] = ""
                            state["final_video_path"] = ""
                            if state.get("status") == "done":
                                state["status"] = "script_ready"
                            manager.save_state(state)
                            st.session_state.current_project = state
                            st.rerun()
                        except Exception as e:
                            st.error(f"오류: {e}")

    # 대본 재생성 버튼 (경고 모달)
    with st.expander("⚠️ 대본 전체 재생성"):
        st.warning("대본을 다시 생성하면 모든 씬 상태가 초기화됩니다.")
        if st.button("대본 재생성 실행", key="regen_script"):
            if not api_keys.get("ANTHROPIC_API_KEY"):
                st.error("ANTHROPIC_API_KEY가 없습니다.")
            else:
                with st.status("대본 재생성 + 자동 검증 중… (약 1~3분)", expanded=True):
                    try:
                        if project_channel(state) == "scenestory":
                            from src import scenestory as _ss
                            result = _ss.generate_script(
                                api_keys["ANTHROPIC_API_KEY"], state.get("ss_form") or {},
                                progress=st.write, closing=state.get("closing", ""),
                                length=state.get("length", ""))
                            state["title_card"] = result.get("title_card", {})
                            state["title"] = result.get("title", state.get("title", ""))
                        else:
                            result = generate_script_and_prompts(
                                api_key=api_keys["ANTHROPIC_API_KEY"],
                                chapter=state["chapter"],
                                topic=state["topic"],
                                progress=st.write,
                                closing=state.get("closing", ""),
                                length=state.get("length", ""),
                            )
                        state["full_narration"] = result.get("full_narration", "")
                        state["scenes"] = result.get("scenes", [])
                        state["verification"] = result.get("verification", {})
                        state["status"] = "script_ready"
                        state["audio_path"] = ""
                        state["final_video_path"] = ""
                        if project_channel(state) == "scenestory":
                            _ss.prepare_title_scenes(state)
                        manager.save_state(state)
                        st.session_state.current_project = state
                        st.success("재생성 완료!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"오류: {e}")

st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — 레퍼런스 이미지 생성 (FLUX Schnell)
# ─────────────────────────────────────────────────────────────────────────────
step2_locked = not step1_done
img_done_cnt  = img_done_cnt_panel   # 위에서 계산
step2_done    = p2_done

_unsplash_key = api_keys.get("UNSPLASH_ACCESS_KEY", "")
_img_src_label = "Unsplash · FLUX AI 선택 가능" if _unsplash_key else "FLUX Schnell (AI 생성)"

st.markdown(f"""
<div class="step-header">
  <div class="step-num {"done" if step2_done else ("locked" if step2_locked else "")}">
    {"✓" if step2_done else "2"}
  </div>
  <div>
    <div class="step-title">STEP 2 · 레퍼런스 이미지 ({_img_src_label})</div>
    <div class="step-sub">
      {"12컷 이미지 완성 — Kling 첫 프레임 준비됨" if step2_done
        else ("STEP 1 대본 생성 후 진행하세요." if step2_locked
              else f"씬별 구도 이미지를 자동 수집합니다. ({img_done_cnt}/{total_cnt}컷 완료)")}
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

BATCH_SIZE = 4   # 이미지: 4장 × 3회 = 12컷

if not step2_locked:
    # 'pending'만 next_batch 대상 — 'error'는 버튼 카운트에는 남기되 자동 재시도 안 함
    # (STEP 4에서 text-to-video로 처리되므로 무한 루프 방지)
    pending_imgs  = [s for s in scenes if s.get("image_status") == "pending"]
    error_imgs    = [s for s in scenes if s.get("image_status") == "error"]
    next_batch    = pending_imgs[:BATCH_SIZE]
    batch_nos     = [s["scene_no"] for s in next_batch]
    batch_label   = f"{batch_nos[0]}~{batch_nos[-1]}컷" if batch_nos else ""

    # ── 이미지 생성 모드 선택 ────────────────────────────────────────────────
    if _unsplash_key:
        _mode_options = [
            "🎯 자동 판단 (씬별 최적 소스)",
            "📷 모두 Unsplash 실사",
            "🤖 모두 FLUX AI",
        ]
    else:
        _mode_options = ["🤖 FLUX AI 생성 (인포그래픽 · 3D · 단면도)"]

    _img_mode = st.radio(
        "이미지 소스",
        options=_mode_options,
        horizontal=True,
        key="img_mode_radio",
        label_visibility="collapsed",
    )
    _mode_is_auto  = _unsplash_key and "자동" in _img_mode
    _use_unsplash_batch = _unsplash_key and "Unsplash" in _img_mode

    col_img, col_img_retry, col_img_info = st.columns([2, 2, 4])
    with col_img:
        _src_icon = "📷" if _use_unsplash_batch else "🤖"
        img_gen_btn = st.button(
            f"{_src_icon} 다음 {len(next_batch)}컷 ({batch_label})" if next_batch else "✅ 이미지 완료",
            disabled=(len(next_batch) == 0 or st.session_state.gen_running),
            key="img_gen_all",
        )
    with col_img_retry:
        # 실패 컷 재시도 버튼 — error 상태인 컷을 pending으로 되돌려 다음 배치에 포함
        if error_imgs:
            retry_btn = st.button(
                f"🔁 실패 {len(error_imgs)}컷 재시도",
                disabled=st.session_state.gen_running,
                key="img_retry_errors",
                help="수집 실패한 컷을 pending으로 되돌려 다시 시도합니다.",
            )
            if retry_btn:
                for s in error_imgs:
                    s["image_status"] = "pending"
                    s.pop("image_error", None)
                try:
                    manager.save_state(state)
                except Exception:
                    pass
                st.rerun()
        else:
            st.empty()
    with col_img_info:
        done_label = f"{img_done_cnt}/{total_cnt}컷 완료"
        if error_imgs:
            done_label += f" · ⚠️ {len(error_imgs)}컷 실패 (STEP 4에서 텍스트→영상으로 대체)"
        elif pending_imgs:
            done_label += f" · 남은 {len(pending_imgs)}컷"
        else:
            done_label += " — 모두 완료"
        st.caption(done_label)

    # ── 배치 오류 표시 (스레드에서 잡힌 전체 오류) ──────────────────────────
    if state.get("batch_image_error"):
        st.error(f"이미지 생성 오류: {state['batch_image_error']}")

    # ── 상태 새로고침 버튼 ────────────────────────────────────────────────────
    if st.button("🔄 상태 새로고침", key="img_state_refresh"):
        st.session_state.gen_running = False     # 멈춘 락 해제
        try:
            st.session_state.current_project = manager.load_state(state["project_dir"])
        except Exception:
            pass                                  # 파일이 없으면 지금 화면의 상태를 그대로 쓴다
        st.rerun()

    if img_gen_btn and not st.session_state.gen_running:
        st.session_state.gen_running = True
        st.session_state.gen_running_since = time.time()
        try:
            prog      = st.empty()
            err_box   = st.empty()
            done_cnt_local = 0
            all_ok = True

            for i, scene in enumerate(next_batch):
                prompt = (scene.get("image_prompt") or scene.get("flow_prompt") or "").strip()
                if not prompt:
                    continue
                sno = scene["scene_no"]
                prog.info(f"🖼 {sno}컷 생성 중… ({i+1}/{len(next_batch)}컷)")

                try:
                    # 소스 결정:
                    #   "모두 FLUX AI"         → 항상 FLUX
                    #   "모두 Unsplash"        → 항상 Unsplash
                    #   "자동 판단" or 키없음  → visual_source / scene_type 기반 분기
                    _rep_key_ok = bool(api_keys.get("REPLICATE_API_TOKEN", ""))
                    if scene.get("scene_type") in ("SKETCH", "PHOTO", "TITLE"):   # SceneStory 는 항상 AI
                        _use_flux = True
                    elif not _unsplash_key and _rep_key_ok:
                        _use_flux = True
                    elif not _unsplash_key and not _rep_key_ok:
                        # Replicate도 Unsplash도 없으면 오류 방지: 빈 URL → error 처리
                        raise RuntimeError("이미지 생성 불가: REPLICATE_API_TOKEN 과 UNSPLASH_ACCESS_KEY 가 모두 없습니다.")
                    elif "FLUX" in _img_mode and "모두" in _img_mode:
                        _use_flux = True
                    elif "Unsplash" in _img_mode and "모두" in _img_mode:
                        _use_flux = False
                    else:  # 자동 판단
                        _use_flux = needs_ai_image(scene)

                    if _use_flux:
                        # AI 생성: 씬 타입에 따라 FLUX Schnell/Dev/Pro로 자동 분기 (Replicate)
                        url, _ai_src = smart_ai_image(
                            scene,
                            api_keys.get("REPLICATE_API_TOKEN", ""),
                            api_keys.get("GOOGLE_API_KEY", ""),
                        )
                    else:
                        # Unsplash 라이센스 프리 실사 사진 (산지·카페·분위기)
                        url = unsplash_for_scene(scene, state["scenes"], _unsplash_key)
                        _ai_src = "unsplash"
                    # 어느 소스로 생성했는지 기록 (썸네일 캡션·수동 교체 참고용)
                    scene["_img_source"] = _ai_src

                    # scene은 state["scenes"] 안의 같은 dict 참조 — 직접 수정
                    scene["image_path"]          = url
                    media_store.forget_image(scene)
                    media_store.keep_image(scene, state.get("project_dir", "projects/tmp"))
                    scene["image_status"]        = "done"
                    scene["reference_image_url"] = url
                    scene.pop("image_error", None)
                    done_cnt_local += 1

                except Exception as ex:
                    all_ok = False
                    scene["image_status"] = "error"
                    scene["image_error"]  = str(ex)
                    err_box.error(f"#{sno:02d} 수집 실패: {ex}")
                    if "크레딧" in str(ex):          # 크레딧 부족이면 다음 컷도 실패 → 배치 중단
                        try:
                            manager.save_state(state)
                        except Exception:
                            pass
                        break

                # 씬마다 즉시 저장 — 에러는 화면에 표시
                try:
                    manager.save_state(state)
                except Exception as save_ex:
                    err_box.error(f"상태 저장 실패: {save_ex}")
                    all_ok = False
        finally:
            # 중간에 화면이 다시 실행돼 끊겨도 락은 반드시 푼다
            st.session_state.gen_running = False

        prog.empty()
        st.session_state.gen_running = False

        # JSON에서 재로드해 세션 상태 갱신 (저장된 실제 값을 반영)
        try:
            refreshed = manager.load_state(state["project_dir"])
            st.session_state.current_project = refreshed
        except Exception:
            st.session_state.current_project = state

        if all_ok:
            st.success(f"{batch_label} {done_cnt_local}컷 이미지 수집 완료!")
        else:
            st.warning("일부 컷에서 오류가 발생했습니다. 위 오류 메시지를 확인하세요.")
        st.rerun()

    # 씬별 이미지 썸네일 미리보기 (fal CDN URL 또는 로컬 경로 모두 지원)
    if img_done_cnt > 0:
        with st.expander(f"생성된 이미지 미리보기 ({img_done_cnt}컷)", expanded=False):
            thumb_cols = st.columns(4)
            for i, scene in enumerate(scenes):
                img_path = media_store.image_source(scene)
                if not img_path:
                    continue
                is_url = img_path.startswith("http")
                if is_url or os.path.exists(img_path):
                    with thumb_cols[i % 4]:
                        st.image(img_path, caption=f"#{scene['scene_no']:02d} {scene.get('name','')}", use_container_width=True)

st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — 음성 생성 (ElevenLabs) — 스텁
# ─────────────────────────────────────────────────────────────────────────────
step3_audio_done   = bool(state.get("audio_path"))
step3_audio_locked = not step1_done

st.markdown(f"""
<div class="step-header">
  <div class="step-num {"done" if step3_audio_done else ("locked" if step3_audio_locked else "")}">
    {"✓" if step3_audio_done else "3"}
  </div>
  <div>
    <div class="step-title">STEP 3 · 나레이션 음성 생성 (ElevenLabs)</div>
    <div class="step-sub">{"음성 파일 준비 완료" if step3_audio_done else ("STEP 1을 먼저 완료하세요." if step3_audio_locked else "전체 나레이션을 ElevenLabs API로 MP3 변환합니다.")}</div>
  </div>
</div>
""", unsafe_allow_html=True)

if step3_audio_done:
    audio_path = state["audio_path"]
    _audio_is_url = audio_path.startswith("http")
    if _audio_is_url or os.path.exists(audio_path):
        st.audio(audio_path, format="audio/mp3")
    else:
        st.warning("음성 파일이 세션 초기화로 사라졌습니다. 아래 버튼으로 재생성하세요.")

elif not step3_audio_locked:
    if not api_keys.get("ELEVENLABS_API_KEY"):
        st.info("ELEVENLABS_API_KEY를 Streamlit Cloud Secrets에 등록하면 이 단계를 실행할 수 있습니다.")
    else:
        narration_text = state.get("full_narration", "").strip()
        if not narration_text:
            st.warning("대본에 full_narration 텍스트가 없습니다. STEP 1을 먼저 실행하세요.")
        else:
            if project_channel(state) == "scenestory":
                from src.voice_test import JA_VOICE_ID as _JA
                voice_id = api_keys.get("ELEVENLABS_VOICE_ID_JA") or _JA      # 일본어 나레이션
            else:
                voice_id = api_keys.get("ELEVENLABS_VOICE_ID", "8jHHF8rMqMlg8if2mOUe")
            st.caption(f"음성 ID: `{voice_id}` · 모델: `eleven_multilingual_v2`")
            audio_btn = st.button("🎙 나레이션 음성 생성", key="audio_gen")
            if audio_btn:
                with st.spinner("ElevenLabs 음성 생성 중… (약 20~40초)"):
                    try:
                        from src.audio import generate_narration_cdn
                        # 로컬 project_dir에 narration.mp3 저장 (fal CDN 대신)
                        cdn_url = generate_narration_cdn(
                            api_key=api_keys["ELEVENLABS_API_KEY"],
                            text=narration_text,
                            fal_key=api_keys.get("FAL_KEY", ""),
                            voice_id=voice_id,
                            project_dir=state.get("project_dir", "/tmp"),
                        )
                        state["audio_path"] = cdn_url
                        manager.save_state(state)
                        st.session_state.current_project = state
                        st.success("음성 생성 완료!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"음성 생성 실패: {e}")

st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — 컷별 영상 생성 (Replicate MiniMax Video-01)
# ─────────────────────────────────────────────────────────────────────────────
# 이미지가 모두 '시도됨' (done 또는 error) 이면 STEP 4 진행 허용.
# error 컷은 reference_image_url이 없으므로 Kling이 text-to-video 모드로 자동 처리.
img_all_attempted = (
    all(s.get("image_status") in ("done", "error") for s in scenes)
    if scenes else False
)
step3_locked = not step1_done or (not img_all_attempted and total_cnt > 0)

st.markdown(f"""
<div class="step-header">
  <div class="step-num {"done" if done_cnt == total_cnt and total_cnt > 0 else ("locked" if step3_locked else "")}">
    {"✓" if done_cnt == total_cnt and total_cnt > 0 else "4"}
  </div>
  <div>
    <div class="step-title">STEP 4 · 컷별 영상 생성 (MiniMax Video-01)</div>
    <div class="step-sub">9:16 세로 · Flux 이미지 첫 프레임 자동 사용 · 클립당 3~5분 · 컷별 재생성 가능</div>
  </div>
</div>
""", unsafe_allow_html=True)

if step3_locked:
    st.info("STEP 1 대본 생성 후 이 단계를 진행하세요.")
elif not api_keys.get("REPLICATE_API_TOKEN"):
    st.warning("REPLICATE_API_TOKEN을 Streamlit Secrets에 등록하면 영상을 생성할 수 있습니다.")
else:
    # 영상: 3컷씩 배치 생성 — 실제 생성은 백그라운드 작업(src/video_jobs.py)이 담당
    VIDEO_BATCH_SIZE  = 3
    pending_scenes    = [s for s in scenes if s.get("status") in ("pending", "error")]
    next_vid_batch    = pending_scenes[:VIDEO_BATCH_SIZE]
    vid_batch_nos     = [s["scene_no"] for s in next_vid_batch]
    vid_batch_label   = ", ".join(f"#{n:02d}" for n in vid_batch_nos)

    # ── 비디오 백엔드: Replicate (fal.ai 접속 불가로 비활성화) ─────────────────
    _fal_key        = api_keys.get("FAL_KEY", "")
    _replicate_key  = api_keys.get("REPLICATE_API_TOKEN", "")
    _use_replicate  = bool(_replicate_key)

    col_gen, col_stop, col_info2 = st.columns([2, 1, 4])
    with col_gen:
        all_gen_btn = st.button(
            "⏳ 영상 생성 중…" if VIDEO_BUSY
            else (f"▶ 다음 {len(next_vid_batch)}컷 생성 ({vid_batch_label})" if next_vid_batch else "✅ 영상 완료"),
            disabled=(len(next_vid_batch) == 0 or VIDEO_BUSY),
        )
    with col_stop:
        stop_btn = st.button(
            "⏹ 중단",
            disabled=not VIDEO_BUSY,
            help="지금 생성 중인 컷은 마저 끝내고, 나머지 컷은 건너뜁니다.",
        )
    with col_info2:
        if not VIDEO_BUSY:
            st.caption(
                f"{done_cnt}/{total_cnt}컷 완료"
                + (f" · 남은 {len(pending_scenes)}컷" if pending_scenes else " — 모두 완료")
            )

    if stop_btn:
        video_jobs.request_stop(PROJECT_KEY)
        st.info("중단 요청됨 — 지금 생성 중인 컷까지만 완료합니다.")

    # ── 직전 배치 오류 원인 표시 (rerun 후에도 유지) ─────────────────────────
    if st.session_state.get("video_error_msg") and not VIDEO_BUSY:
        st.error(f"직전 영상 생성 실패 원인: {st.session_state.video_error_msg}")

    # ── 배치 시작: 백그라운드 작업으로 넘기고 즉시 화면 갱신 ────────────────────
    if all_gen_btn and next_vid_batch and not VIDEO_BUSY:
        st.session_state.video_error_msg = ""
        video_jobs.start_job(
            project_id=PROJECT_KEY,
            state=state,
            scene_nos=vid_batch_nos,
            replicate_token=_replicate_key,
            save_fn=manager.save_state,
        )
        st.rerun()

    # ── 컷별 실시간 진행 패널 (3초마다 자동 갱신) ─────────────────────────────
    @st.fragment(run_every=3)
    def _video_progress_panel(project_key: str):
        job = video_jobs.get_job(project_key)
        if job is None:
            return
        running = video_jobs.is_running(project_key)
        now     = time.time()
        prog    = job["progress"]

        done_n  = sum(1 for n in job["scene_nos"] if prog[n]["state"] == "done")
        total_n = len(job["scene_nos"])
        with st.container(border=True):
            if running:
                st.markdown(f"**🎬 영상 생성 진행 중 — {done_n}/{total_n}컷 완료**")
            else:
                st.markdown(f"**작업 종료 — {done_n}/{total_n}컷 완료**")

            for n in job["scene_nos"]:
                p = prog[n]
                s = p["state"]
                if s == "queued":
                    st.markdown(f"⏳ **#{n:02d}** 대기 중 — 앞 컷이 끝나면 시작합니다")
                elif s == "generating":
                    el = int(now - (p["started"] or now))
                    m, sec = divmod(el, 60)
                    if p["last_poll"]:
                        ago = int(now - p["last_poll"])
                        beat = f"Replicate 응답 {ago}초 전"
                        if ago > 60:
                            beat = f"⚠️ Replicate 응답 없음 {ago}초째"
                    else:
                        beat = "Replicate에 요청 전송 중"
                    st.markdown(f"🎬 **#{n:02d}** 생성 중 · {m}분 {sec:02d}초 경과 · {beat}")
                    st.progress(min(el / 180, 0.97), text="보통 2~3분 소요 · 10분 넘으면 자동으로 오류 처리")
                elif s == "done":
                    st.markdown(f"✅ **#{n:02d}** 완료")
                elif s == "error":
                    st.markdown(f"❌ **#{n:02d}** 오류 — {p.get('msg', '')[:200]}")
                elif s == "skipped":
                    st.markdown(f"⏸ **#{n:02d}** 건너뜀 (중단 또는 크레딧 부족)")

            if job.get("stop") and running:
                st.caption("중단 요청됨 — 지금 컷까지만 완료합니다.")
            st.caption(f"마지막 확인 {time.strftime('%H:%M:%S', time.localtime(now))} · 화면을 새로고침해도 생성은 계속됩니다")

        # 컷 상태가 바뀌면 전체 화면(씬 카드 배지·영상 미리보기)도 갱신
        sig = tuple(prog[n]["state"] for n in job["scene_nos"]) + (running,)
        if sig != job.get("ui_sig"):
            first = job.get("ui_sig") is None
            job["ui_sig"] = sig
            if not first:
                st.rerun(scope="app")

    _recent_job = (
        _vjob is not None and _vjob.get("finished_at")
        and (time.time() - _vjob["finished_at"] < 60)
    )
    if VIDEO_BUSY or _recent_job:
        _video_progress_panel(PROJECT_KEY)

    st.markdown("")

    # ── 12컷 씬 카드 그리드 ────────────────────────────────────────────────
    cols_per_row = 3
    for row_start in range(0, len(scenes), cols_per_row):
        row_scenes = scenes[row_start : row_start + cols_per_row]
        cols = st.columns(cols_per_row)

        for col, scene in zip(cols, row_scenes):
            sno    = scene.get("scene_no", "?")
            sname  = scene.get("name", "")
            status = scene.get("status", "pending")
            narr   = scene.get("narration", "")
            prompt = scene.get("flow_prompt", "")
            sfx    = scene.get("sfx", "")
            overlay= scene.get("overlay_text", "")
            vid_url= media_store.video_source(scene)

            with col:
                st.markdown(f"""
                <div class="scene-card">
                  <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                    <div>
                      <div class="scene-num">#{sno:02d}</div>
                      <div class="scene-name">{sname}</div>
                    </div>
                    {badge_html(status)}
                  </div>
                  <div class="narration-text">{narr}</div>
                  <div class="meta-chips">
                    <span class="chip">🔊 {sfx if sfx else '—'}</span>
                    <span class="chip">📝 {overlay if overlay else '—'}</span>
                  </div>
                  <div class="prompt-text">{prompt[:120]}{"…" if len(prompt)>120 else ""}</div>
                </div>
                """, unsafe_allow_html=True)

                # ── 레퍼런스 이미지 (Flux 자동생성 우선 / 드라이브 폴백) ──────
                img_path   = media_store.image_source(scene)
                img_status = scene.get("image_status", "pending")
                current_ref = scene.get("reference_image_url", "")

                # 이미지 썸네일 표시 (Unsplash URL 또는 fal CDN URL 또는 로컬 경로 모두 지원)
                _img_is_url = img_path.startswith("http")
                if img_path and (_img_is_url or os.path.exists(img_path)):
                    _src_tag = scene.get("_img_source") or (
                        "unsplash" if "images.unsplash" in img_path else "flux"
                    )
                    _type_tag = scene.get("scene_type", "")
                    _src_display = {
                        "unsplash": "📷 Unsplash",
                        "gpt2":     "🎨 GPT Image 2",
                        "gemini":   "🎨 Gemini",
                        "flux":     "🤖 FLUX",
                    }.get(_src_tag, "🤖 FLUX")
                    _img_src_caption = _src_display + (f" · {_type_tag}" if _type_tag else "")
                    st.image(img_path, use_container_width=True,
                             caption=f"{_img_src_caption} · {img_status}")
                    new_ref = scene.get("image_path", "")  # 원본 주소 유지 (로컬 사본은 image_local 에 따로 보관)

                    # ── 이미지 교체 옵션 ────────────────────────────────────
                    # AI 씬(훅·도판): 주 버튼 = AI 다시 생성, 보조 = 사진으로 교체
                    # 사진 씬        : 주 버튼 = 다른 사진,     보조 = AI로 교체
                    _is_ai_scene = needs_ai_image(scene)
                    _swap_btn = _ai_swap_btn = False
                    if _unsplash_key:
                        _sw_c1, _sw_c2 = st.columns(2)
                        with _sw_c1:
                            _main_clicked = st.button(
                                "🎨 다시 생성" if _is_ai_scene else "📷 다른 사진",
                                key=f"swap_img_{sno}", use_container_width=True,
                                disabled=st.session_state.gen_running,
                            )
                        with _sw_c2:
                            _alt_clicked = st.button(
                                "📷 사진으로 교체" if _is_ai_scene else "🤖 AI로 교체",
                                key=f"ai_img_{sno}", use_container_width=True,
                                disabled=st.session_state.gen_running,
                            )
                        if _is_ai_scene:
                            _ai_swap_btn, _swap_btn = _main_clicked, _alt_clicked
                        else:
                            _swap_btn, _ai_swap_btn = _main_clicked, _alt_clicked
                    else:
                        _ai_swap_btn = st.button(
                            "🎨 다시 생성", key=f"swap_img_{sno}",
                            use_container_width=True,
                            disabled=st.session_state.gen_running,
                        )

                    if _swap_btn:
                        with st.spinner(f"#{sno:02d} 다른 사진 검색 중…"):
                            try:
                                url = unsplash_for_scene(scene, state["scenes"], _unsplash_key)
                                scene["image_path"]          = url
                                media_store.forget_image(scene)
                                media_store.keep_image(scene, state.get("project_dir", "projects/tmp"))
                                scene["image_status"]        = "done"
                                scene["reference_image_url"] = url
                                scene["_img_source"]         = "unsplash"
                                scene.pop("image_error", None)
                                manager.save_state(state)
                                st.session_state.current_project = state
                                st.rerun()
                            except Exception as ex:
                                st.error(f"#{sno:02d} 교체 실패: {ex}")

                    if _ai_swap_btn:
                        with st.spinner(f"#{sno:02d} AI 이미지 생성 중… (약 20~60초)"):
                            try:
                                url, _ai_src = smart_ai_image(
                                    scene, api_keys.get("REPLICATE_API_TOKEN", ""), api_keys.get("GOOGLE_API_KEY", "")
                                )
                                scene["image_path"]          = url
                                media_store.forget_image(scene)
                                media_store.keep_image(scene, state.get("project_dir", "projects/tmp"))
                                scene["image_status"]        = "done"
                                scene["reference_image_url"] = url
                                scene["_img_source"]         = _ai_src
                                scene.pop("image_error", None)
                                manager.save_state(state)
                                st.session_state.current_project = state
                                st.rerun()
                            except Exception as ex:
                                st.error(f"#{sno:02d} AI 생성 실패: {ex}")

                    # URL 직접 붙여넣기 (Enter 치면 즉시 적용)
                    _custom_url = st.text_input(
                        "또는 URL 직접 입력",
                        value="",
                        placeholder="https://… 붙여넣고 Enter",
                        key=f"custom_img_{sno}",
                        label_visibility="collapsed",
                    ).strip()
                    if _custom_url and _custom_url != img_path:
                        scene["image_path"]          = _custom_url
                        media_store.forget_image(scene)
                        media_store.keep_image(scene, state.get("project_dir", "projects/tmp"))
                        scene["image_status"]        = "done"
                        scene["reference_image_url"] = _custom_url
                        new_ref = _custom_url
                        manager.save_state(state)
                        st.session_state.current_project = state
                        st.rerun()

                else:
                    # 개별 이미지 생성 버튼
                    img_status_label = {
                        "pending": "⏳ 미생성", "generating": "⚙️ 생성중",
                        "done": "✅ 완료", "error": "❌ 오류"
                    }.get(img_status, "?")
                    st.caption(f"이미지: {img_status_label}")

                    _btn_disabled = (img_status == "generating" or st.session_state.gen_running)
                    if _unsplash_key:
                        _rc1, _rc2 = st.columns(2)
                        with _rc1:
                            _unsplash_single = st.button(
                                "📷 Unsplash", key=f"img_regen_{sno}",
                                disabled=_btn_disabled, use_container_width=True,
                            )
                        with _rc2:
                            _flux_single = st.button(
                                "🤖 FLUX AI", key=f"img_flux_{sno}",
                                disabled=_btn_disabled, use_container_width=True,
                            )
                    else:
                        _unsplash_single = False
                        _flux_single = st.button(
                            f"🖼 #{sno:02d} 이미지 생성", key=f"img_regen_{sno}",
                            disabled=_btn_disabled, use_container_width=True,
                        )

                    if _unsplash_single:
                        with st.spinner(f"#{sno:02d} Unsplash 검색 중…"):
                            try:
                                url = unsplash_for_scene(scene, state["scenes"], _unsplash_key)
                                scene["image_path"]          = url
                                media_store.forget_image(scene)
                                media_store.keep_image(scene, state.get("project_dir", "projects/tmp"))
                                scene["image_status"]        = "done"
                                scene["reference_image_url"] = url
                                scene["_img_source"]         = "unsplash"
                                scene.pop("image_error", None)
                                manager.save_state(state)
                                st.session_state.current_project = state
                                st.rerun()
                            except Exception as ex:
                                scene["image_status"] = "error"
                                scene["image_error"]  = str(ex)
                                manager.save_state(state)
                                st.error(f"#{sno:02d} 오류: {ex}")

                    if _flux_single:
                        with st.spinner(f"#{sno:02d} AI 이미지 생성 중… (약 20~60초)"):
                            try:
                                url, _ai_src = smart_ai_image(
                                    scene, api_keys.get("REPLICATE_API_TOKEN", ""), api_keys.get("GOOGLE_API_KEY", "")
                                )
                                scene["image_path"]          = url
                                media_store.forget_image(scene)
                                media_store.keep_image(scene, state.get("project_dir", "projects/tmp"))
                                scene["image_status"]        = "done"
                                scene["reference_image_url"] = url
                                scene["_img_source"]         = _ai_src
                                scene.pop("image_error", None)
                                manager.save_state(state)
                                st.session_state.current_project = state
                                st.rerun()
                            except Exception as ex:
                                scene["image_status"] = "error"
                                scene["image_error"]  = str(ex)
                                manager.save_state(state)
                                st.error(f"#{sno:02d} 오류: {ex}")

                    # 드라이브 또는 URL 수동 입력 폴백
                    gdrive_images = load_gdrive_images(
                        api_key=api_keys.get("GOOGLE_API_KEY", ""),
                        folder_id=api_keys.get("GDRIVE_REF_FOLDER_ID", ""),
                    )
                    if gdrive_images:
                        img_options = ["(사용 안 함)"] + [img["name"] for img in gdrive_images]
                        current_name = next(
                            (img["name"] for img in gdrive_images if img["url"] == current_ref),
                            "(사용 안 함)"
                        )
                        selected_name = st.selectbox(
                            "또는 드라이브 이미지",
                            options=img_options,
                            index=img_options.index(current_name) if current_name in img_options else 0,
                            key=f"ref_img_{sno}",
                        )
                        new_ref = next(
                            (img["url"] for img in gdrive_images if img["name"] == selected_name), ""
                        )
                    else:
                        new_ref = st.text_input(
                            "또는 이미지 URL 직접 입력",
                            value=current_ref,
                            placeholder="https://drive.google.com/file/d/.../view",
                            key=f"ref_img_{sno}",
                        ).strip()

                # reference_image_url 저장
                if new_ref != current_ref:
                    scene["reference_image_url"] = new_ref
                    manager.save_state(state)

                # 영상 미리보기 (CDN URL 또는 로컬 경로 모두 지원)
                _vid_is_url = vid_url.startswith("http") if vid_url else False
                if vid_url and (_vid_is_url or os.path.exists(vid_url)):
                    st.video(vid_url)
                elif status == "error":
                    st.error(scene.get("error_msg", "알 수 없는 오류"))

                # 개별 재생성 버튼 — 백그라운드 작업으로 실행 (진행 패널에 표시)
                btn_disabled = (status == "generating" or VIDEO_BUSY or not _use_replicate)
                if st.button(
                    f"🔄 #{sno:02d} 재생성",
                    key=f"regen_scene_{sno}",
                    disabled=btn_disabled,
                    use_container_width=True,
                ):
                    st.session_state.video_error_msg = ""
                    video_jobs.start_job(
                        project_id=PROJECT_KEY,
                        state=state,
                        scene_nos=[sno],
                        replicate_token=_replicate_key,
                        save_fn=manager.save_state,
                    )
                    st.rerun()


st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — 최종 합성 (FFmpeg + Whisper) — 스텁
# ─────────────────────────────────────────────────────────────────────────────
step4_done   = bool(state.get("final_video_path"))
step4_locked = done_cnt < total_cnt or total_cnt == 0 or not state.get("audio_path")

st.markdown(f"""
<div class="step-header">
  <div class="step-num {"done" if step4_done else ("locked" if step4_locked else "")}">
    {"✓" if step4_done else "5"}
  </div>
  <div>
    <div class="step-title">STEP 5 · 최종 합성 (자막 · 효과음 · 배경음악)</div>
    <div class="step-sub">
      {"최종 영상 완성!" if step4_done
        else ("STEP 2 음성 + STEP 3 전체 영상 완료 후 실행 가능" if step4_locked
              else "음성·영상·SFX·BGM을 합쳐 다이나믹 자막 포함 숏폼을 생성합니다.")}
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

def _assemble_controls(label: str, key: str) -> None:
    """효과음·배경음악 옵션 + 합성 버튼 (처음 합성 / 다시 합성 공용)."""
    c1, c2 = st.columns(2)
    with c1:
        use_sfx = st.checkbox("🔊 효과음 넣기", value=True, key=f"{key}_sfx",
                              help="컷이 바뀔 때마다 대본의 SFX 태그에 맞는 효과음을 넣습니다.")
    with c2:
        use_bgm = st.checkbox("🎵 배경음악 넣기", value=True, key=f"{key}_bgm",
                              help="영상 길이에 맞춘 연주곡을 깔고, 나레이션이 나올 때는 자동으로 작아집니다.")
    if (use_sfx or use_bgm) and not api_keys.get("ELEVENLABS_API_KEY"):
        st.caption("ELEVENLABS_API_KEY 가 없어 소리를 만들 수 없습니다. assets/sfx, assets/bgm 에 올린 파일만 사용됩니다.")
    if st.button(label, key=key):
        with st.spinner("합성 중… 처음 한 번은 효과음·배경음악 생성까지 포함해 약 3~6분 걸립니다. 화면을 누르지 마세요."):
            try:
                from src.assembler import assemble_final_video
                local_path = assemble_final_video(
                    state,
                    elevenlabs_key=api_keys.get("ELEVENLABS_API_KEY", ""),
                    with_sfx=use_sfx,
                    with_bgm=use_bgm,
                )
                state["final_video_path"] = local_path
                state["status"] = "done"
                manager.save_state(state)
                st.session_state.current_project = state
                st.success("최종 합성 완료!")
                st.rerun()
            except Exception as e:
                st.error(f"합성 실패: {e}")


if step4_done:
    final_path = state["final_video_path"]
    _final_is_url = final_path.startswith("http") if final_path else False
    if _final_is_url or os.path.exists(final_path):
        st.video(final_path)
        if _final_is_url:
            st.markdown(f"[⬇️ 최종 영상 다운로드]({final_path})")
        else:
            with open(final_path, "rb") as fv:
                st.download_button(
                    label="⬇️ 최종 영상 다운로드",
                    data=fv,
                    file_name=f"{state.get('project_id','final')}.mp4",
                    mime="video/mp4",
                )
    else:
        st.caption(f"파일 경로: `{final_path}`")
    if not step4_locked:
        with st.expander("🔁 다시 합성 (효과음·배경음악 설정 변경)"):
            _assemble_controls("🎬 다시 합성", "reassemble_btn")
elif not step4_locked:
    st.info("영상 클립과 나레이션 음성이 준비되면 아래 버튼으로 최종 영상을 합성합니다.")
    _assemble_controls("🎬 최종 합성 실행", "assemble_btn")

st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — 업로드 정보 · 성과 기록
# ─────────────────────────────────────────────────────────────────────────────
from src import publish

st.markdown("""
<div class="step-header">
  <div class="step-num">6</div>
  <div>
    <div class="step-title">STEP 6 · 업로드 정보 · 성과 기록</div>
    <div class="step-sub">제목 · 설명 · 태그 · 고정 댓글 · 섬네일을 한 번에 만들고, 올린 뒤 7일 성과를 기록합니다</div>
  </div>
</div>
""", unsafe_allow_html=True)

from src import thumbnail as thumb_mod

_pack = state.get("upload_pack") or {}
_thumb_bgs = thumb_mod.background_candidates(state)


def _make_thumb(bg_path: str = ""):
    _p = state.get("upload_pack") or {}
    path = thumb_mod.create_thumbnail(state, publish.thumb_copy(_p), bg_path, publish.channel_brand(state))
    state["thumbnail_path"] = path
    state["thumbnail_bg"] = bg_path


if st.button("📝 업로드 정보 · 섬네일 한 번에 만들기" if not _pack else "🔁 업로드 정보 · 섬네일 다시 만들기",
             key="pack_btn", type="primary"):
    with st.spinner("제목 · 설명 · 태그 · 고정 댓글 · 섬네일 만드는 중… (약 15초)"):
        state["upload_pack"] = publish.make_upload_pack(api_keys.get("ANTHROPIC_API_KEY", ""), state)
        try:
            _make_thumb(_thumb_bgs[0][1] if _thumb_bgs else "")
        except Exception as e:
            st.warning(f"섬네일 생성 실패 — 업로드 정보는 만들어졌습니다: {e}")
        manager.save_state(state)
        st.session_state.current_project = state
        st.rerun()

if _pack:
    st.caption("각 칸 오른쪽 위 복사 아이콘으로 그대로 붙여 넣으면 됩니다.")
    _t1, _t2 = st.tabs(["📋 항목별", "🧾 전체 한 번에"])
    with _t1:
        st.markdown("**제목**")
        st.code(_pack.get("title", ""), language=None)
        st.markdown("**설명 (해시태그 포함)**")
        st.code(_pack.get("description", ""), language=None)
        st.markdown(f"**태그** — YouTube Studio '태그' 칸에 붙여 넣기 ({len(publish.tags_text(_pack))}/500자)")
        st.code(publish.tags_text(_pack), language=None)
        st.markdown("**고정 댓글** — 올린 직후 댓글로 달고 '고정'")
        st.code(_pack.get("pinned_comment", ""), language=None)
        if _pack.get("next_teaser"):
            st.markdown("**다음 편 예고** — 고정 댓글 아래에 한 줄 더")
            st.code(_pack.get("next_teaser", ""), language=None)
    with _t2:
        st.code(publish.all_in_one(_pack), language=None)
    with st.expander("⚙️ 업로드 설정 (매번 같음)"):
        for _k, _v in publish.upload_settings(state):
            st.markdown(f"- **{_k}**: {_v}")

    # ── 섬네일 ──
    st.markdown("**섬네일 (1080×1920)** — 매 편 같은 틀, 글자는 채널 화면에서 잘리지 않는 위치")
    _thumb_path = state.get("thumbnail_path", "")
    _tc1, _tc2 = st.columns([1, 1])
    with _tc1:
        if _thumb_path and os.path.exists(_thumb_path):
            st.image(_thumb_path, use_container_width=True)
            with open(_thumb_path, "rb") as _fh:
                st.download_button("⬇️ 섬네일 PNG 다운로드", data=_fh.read(),
                                   file_name=f"thumbnail_{state.get('project_id', 'shorts')}.png",
                                   mime="image/png", key="thumb_dl")
        else:
            st.info("섬네일이 아직 없습니다. 오른쪽에서 문구와 배경을 확인하고 '섬네일 다시 그리기'를 누르세요.")
    with _tc2:
        _l1 = st.text_input("윗줄 (9자 안팎)", value=_pack.get("thumb_line1", ""), key="thumb_l1")
        _l2 = st.text_input("아랫줄 (9자 안팎)", value=_pack.get("thumb_line2", ""), key="thumb_l2")
        _ac = st.text_input("강조 단어 (윗줄·아랫줄 안의 단어)", value=_pack.get("thumb_accent", ""), key="thumb_ac")
        _bg_pick = ""
        if _thumb_bgs:
            _labels = [l for l, _ in _thumb_bgs]
            _paths = [p for _, p in _thumb_bgs]
            _cur = state.get("thumbnail_bg", "")
            _idx = _paths.index(_cur) if _cur in _paths else 0
            _sel = st.selectbox("배경 그림", _labels, index=_idx, key="thumb_bg")
            _bg_pick = _paths[_labels.index(_sel)]
        else:
            st.caption("서버에 남은 컷 이미지가 없어 종이색 바탕으로 그립니다.")
        if st.button("🖼 섬네일 다시 그리기", key="thumb_redraw"):
            _pack["thumb_line1"], _pack["thumb_line2"], _pack["thumb_accent"] = _l1, _l2, _ac
            state["upload_pack"] = _pack
            try:
                _make_thumb(_bg_pick)
                manager.save_state(state)
                st.session_state.current_project = state
                st.rerun()
            except Exception as e:
                st.error(f"섬네일 생성 실패: {e}")

with st.expander("📊 성과 기록 (올리고 7일 뒤 YouTube Studio 숫자를 적어 두세요)"):
    _perf = dict(state.get("perf") or {})
    _pc1, _pc2 = st.columns(2)
    for _i, _k in enumerate(publish.PERF_FIELDS):
        with (_pc1 if _i % 2 == 0 else _pc2):
            _perf[_k] = st.text_input(publish.PERF_LABELS[_k], value=str(_perf.get(_k, "")),
                                      key=f"perf_{_k}")
    if st.button("💾 성과 저장", key="perf_save"):
        state["perf"] = _perf
        manager.save_state(state)
        st.session_state.current_project = state
        st.success("저장했습니다. JSON 백업에도 함께 들어갑니다.")
    # 서버에 있는 모든 프로젝트 성과표
    _rows = []
    for _p in manager.list_projects():
        try:
            _rows.append(publish.perf_row(manager.load_state(_p["dir"])))
        except Exception:
            pass
    if _rows:
        st.dataframe(
            [{"주제": r["topic"], "길이": r["length"], "훅": r["hook_text"],
              "7일 조회수": r["views_7d"], "시청함 %": r["viewed_rate"]} for r in _rows],
            use_container_width=True, hide_index=True,
        )
        st.download_button("⬇️ 성과표 CSV 다운로드", data=publish.perf_csv(_rows),
                           file_name="shorts_performance.csv", mime="text/csv", key="perf_csv")
        st.caption("서버가 재시작되면 이 표도 비워집니다. CSV로 내려받아 한 파일에 모아 두면 "
                   "어떤 훅·길이가 잘 되는지 비교할 수 있습니다.")

st.markdown("<br>", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# 자동 새로고침 — 백그라운드 생성 중일 때 10초마다 화면 갱신
# ─────────────────────────────────────────────────────────────────────────────
if any_generating:
    # force_refresh는 한 번만 — 다음 사이클부터는 실제 generating 상태로 판단
    st.session_state.force_refresh = False
    # 상태 파일에서 최신 데이터 다시 로드
    try:
        refreshed = manager.load_state(state["project_dir"])
        st.session_state.current_project = refreshed
    except Exception:
        pass
    time.sleep(8)
    st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# 푸터
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="factory-footer">
  너도나도아는커피 숏폼 팩토리 · Powered by Claude API · ElevenLabs · Replicate MiniMax Video-01
</div>
""", unsafe_allow_html=True)
