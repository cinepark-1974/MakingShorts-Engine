# app.py — 너도나도아는커피 숏폼 팩토리 | Streamlit 메인 대시보드
# Claude API 버전 (Anthropic claude-sonnet-4-6)

import streamlit as st
import os
import time
import threading
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
    page_title="☕ 너도나도아는커피 | 숏폼 팩토리",
    page_icon="☕",
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

/* ── 전체 배경 ── */
.stApp { background-color: #F7FBFC; color: #142C3C; }

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
    from src.image_fal import generate_images_for_scenes, generate_reference_image
    from src.video_fal import generate_single_clip
    MODULES_OK = True
except ImportError as e:
    MODULES_OK = False
    IMPORT_ERROR = str(e)

# ── API 키 로드 ───────────────────────────────────────────────────────────────
def load_api_keys():
    """secrets.toml → 환경변수 순으로 API 키 로드"""
    keys = {}
    for k in [
        "ANTHROPIC_API_KEY",
        "ELEVENLABS_API_KEY",
        "FAL_KEY",
        "GOOGLE_API_KEY",          # 구글 드라이브 이미지 목록 조회용
        "GDRIVE_REF_FOLDER_ID",    # 레퍼런스 이미지 폴더 ID
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
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_session()

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
    # ── 브랜드 로고 ──────────────────────────────────────────────────────────
    if LOGO_B64:
        st.markdown(
            f"""
            <div style="
                padding: 20px 16px 12px;
                text-align: center;
            ">
                <img src="data:image/png;base64,{LOGO_B64}"
                     style="width: 100%; max-width: 200px;
                            filter: brightness(0) invert(1);
                            opacity: 0.92;" />
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown("## ☕ 숏폼 팩토리")

    st.markdown(
        '<div style="text-align:center; color:rgba(255,255,255,0.5); '
        'font-size:11px; letter-spacing:0.08em; margin-bottom:12px;">'
        'SHORTS FACTORY</div>',
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
    projects = manager.list_projects()

    if not projects:
        st.caption("아직 프로젝트가 없습니다.")
    else:
        for p in projects:
            label = p["title"][:40] + ("…" if len(p["title"]) > 40 else "")
            if st.button(label, key=f"proj_{p['id']}", use_container_width=True):
                st.session_state.current_project = manager.load_state(p["dir"])
                st.rerun()

    st.markdown("---")
    st.markdown(
        '<div style="text-align:center; color:rgba(255,255,255,0.4); '
        'font-size:10px; line-height:1.7; padding:4px 0 8px;">'
        'Claude API · ElevenLabs · Fal.ai Kling<br>'
        '<span style="color:rgba(219,161,44,0.6);">You & I Know Coffee</span>'
        '</div>',
        unsafe_allow_html=True,
    )

# ─────────────────────────────────────────────────────────────────────────────
# API 키 체크
# ─────────────────────────────────────────────────────────────────────────────
api_keys = load_api_keys()
REQUIRED_KEYS = ["ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "FAL_KEY"]
missing = [k for k in REQUIRED_KEYS if not api_keys.get(k)]
if missing:
    st.warning(
        f"API 키가 설정되지 않았습니다: **{', '.join(missing)}**\n\n"
        "`.streamlit/secrets.toml` 또는 Streamlit Cloud Secrets에 등록해 주세요.",
        icon="⚠️",
    )

# ─────────────────────────────────────────────────────────────────────────────
# 새 프로젝트 생성 폼 (프로젝트 미선택 시)
# ─────────────────────────────────────────────────────────────────────────────
if st.session_state.current_project is None:
    # 웰컴 헤더
    if LOGO_B64:
        st.markdown(
            f"""
            <div style="text-align:center; padding: 32px 0 8px;">
                <img src="data:image/png;base64,{LOGO_B64}"
                     style="height: 96px; opacity: 0.9;" />
                <div style="margin-top:12px; font-size:13px; color:#4A7A8A;
                            letter-spacing:0.06em;">SHORTS FACTORY</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown("## ☕ 너도나도아는커피 숏폼 팩토리")

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

    # 주제 입력 — 가장 크게, 맨 위
    topic = st.text_input(
        "어떤 커피 이야기를 만들까요?",
        placeholder="예: 아이스아메리카노와 롱블랙의 차이   |   예가체프 내추럴 프로세싱의 비밀",
        help="구체적인 키워드나 질문 형태로 입력할수록 대본 품질이 높아집니다.",
    )

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
            with st.spinner("Claude AI가 12컷 대본을 작성하고 있습니다… (약 20~40초)"):
                try:
                    # 프로젝트 디렉터리 생성
                    new_state = manager.create_new_project(
                        chapter=chapter_for_api,
                        topic=topic.strip()
                    )
                    # Claude API 호출
                    result = generate_script_and_prompts(
                        api_key=api_keys["ANTHROPIC_API_KEY"],
                        chapter=chapter_for_api,
                        topic=topic.strip(),
                    )
                    # state 업데이트
                    new_state["full_narration"] = result.get("full_narration", "")
                    new_state["scenes"] = result.get("scenes", [])
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

any_generating = img_generating or vid_generating


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

    # 대본 재생성 버튼 (경고 모달)
    with st.expander("⚠️ 대본 전체 재생성"):
        st.warning("대본을 다시 생성하면 모든 씬 상태가 초기화됩니다.")
        if st.button("대본 재생성 실행", key="regen_script"):
            if not api_keys.get("ANTHROPIC_API_KEY"):
                st.error("ANTHROPIC_API_KEY가 없습니다.")
            else:
                with st.spinner("재생성 중…"):
                    try:
                        result = generate_script_and_prompts(
                            api_key=api_keys["ANTHROPIC_API_KEY"],
                            chapter=state["chapter"],
                            topic=state["topic"],
                        )
                        state["full_narration"] = result.get("full_narration", "")
                        state["scenes"] = result.get("scenes", [])
                        state["status"] = "script_ready"
                        state["audio_path"] = ""
                        state["final_video_path"] = ""
                        manager.save_state(state)
                        st.session_state.current_project = state
                        st.success("재생성 완료!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"오류: {e}")

st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — 레퍼런스 이미지 생성 (Nano Banana 2)
# ─────────────────────────────────────────────────────────────────────────────
step2_locked = not step1_done
img_done_cnt  = img_done_cnt_panel   # 위에서 계산
step2_done    = p2_done

st.markdown(f"""
<div class="step-header">
  <div class="step-num {"done" if step2_done else ("locked" if step2_locked else "")}">
    {"✓" if step2_done else "2"}
  </div>
  <div>
    <div class="step-title">STEP 2 · 레퍼런스 이미지 생성 (Nano Banana 2)</div>
    <div class="step-sub">
      {"12컷 이미지 완성 — Kling 첫 프레임 준비됨" if step2_done
        else ("STEP 1 대본 생성 후 진행하세요." if step2_locked
              else f"씬별 구도 이미지를 Nano Banana 2로 자동 생성합니다. ({img_done_cnt}/{total_cnt}컷 완료)")}
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

if not step2_locked:
    pending_imgs = [s for s in scenes if s.get("image_status") in ("pending", "error")]
    col_img, col_img_info = st.columns([2, 5])
    with col_img:
        img_gen_btn = st.button(
            f"🖼 이미지 {len(pending_imgs)}컷 일괄 생성",
            disabled=(len(pending_imgs) == 0 or st.session_state.gen_running),
            key="img_gen_all",
        )
    with col_img_info:
        if img_done_cnt > 0:
            st.caption(f"{img_done_cnt}컷 완료 · 미완료 {len(pending_imgs)}컷 남음")

    # ── URL 상태 강제 새로고침 버튼 ─────────────────────────────────────────
    if st.button("🔄 상태 새로고침", key="img_state_refresh"):
        try:
            refreshed = manager.load_state(state["project_dir"])
            st.session_state.current_project = refreshed
            st.rerun()
        except Exception:
            st.warning("상태 파일을 불러오지 못했습니다.")

    if img_gen_btn and not st.session_state.gen_running:
        st.session_state.gen_running = True

        def run_all_images(state_snapshot, fal_key):
            from src.state_manager import StateManager
            from src.image_fal import generate_reference_image
            mgr = StateManager(storage_dir="projects")
            current = mgr.load_state(state_snapshot["project_dir"])
            for scene in current["scenes"]:
                if not scene.get("image_prompt", "").strip():
                    continue
                if scene.get("image_status") == "done":
                    continue
                scene["image_status"] = "generating"
                mgr.save_state(current)          # ← "생성중" 상태 즉시 저장
                try:
                    url = generate_reference_image(fal_key, scene.get("image_prompt", ""))
                    scene["image_path"]            = url   # fal CDN URL
                    scene["image_status"]          = "done"
                    scene["reference_image_url"]   = url
                    scene.pop("image_error", None)
                except Exception as ex:
                    scene["image_status"] = "error"
                    scene["image_error"]  = str(ex)
                mgr.save_state(current)          # ← 완료/오류 상태 저장

        t_img = threading.Thread(
            target=run_all_images,
            args=(state, api_keys["FAL_KEY"]),
            daemon=True,
        )
        t_img.start()
        st.session_state.gen_running = False
        st.info("이미지 생성을 시작했습니다. 화면이 자동으로 갱신됩니다.")

    # 씬별 이미지 썸네일 미리보기 (fal CDN URL 또는 로컬 경로 모두 지원)
    if img_done_cnt > 0:
        with st.expander(f"생성된 이미지 미리보기 ({img_done_cnt}컷)", expanded=False):
            thumb_cols = st.columns(4)
            for i, scene in enumerate(scenes):
                img_path = scene.get("image_path", "")
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
    if os.path.exists(audio_path):
        st.audio(audio_path, format="audio/mp3")
    else:
        st.caption(f"파일 경로: `{audio_path}`")
elif not step3_audio_locked:
    if not api_keys.get("ELEVENLABS_API_KEY"):
        st.info("ELEVENLABS_API_KEY를 Streamlit Cloud Secrets에 등록하면 이 단계를 실행할 수 있습니다.")
    else:
        st.info(
            "🔧 **`src/audio.py` 구현 대기 중** — "
            "ElevenLabs 연동 코드가 완성되면 이 버튼이 활성화됩니다.",
            icon="ℹ️",
        )
        st.button("음성 생성 실행 (준비 중)", disabled=True)

st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — 컷별 영상 생성 (Fal.ai Kling)
# ─────────────────────────────────────────────────────────────────────────────
step3_locked = not step1_done

st.markdown(f"""
<div class="step-header">
  <div class="step-num {"done" if done_cnt == total_cnt and total_cnt > 0 else ("locked" if step3_locked else "")}">
    {"✓" if done_cnt == total_cnt and total_cnt > 0 else "4"}
  </div>
  <div>
    <div class="step-title">STEP 4 · 컷별 영상 생성 (Fal.ai Kling v2.6 Pro)</div>
    <div class="step-sub">9:16 세로 · 5초 · Flux 이미지 첫 프레임 자동 사용 · 컷별 재생성 가능</div>
  </div>
</div>
""", unsafe_allow_html=True)

if step3_locked:
    st.info("STEP 1 대본 생성 후 이 단계를 진행하세요.")
elif not api_keys.get("FAL_KEY"):
    st.warning("FAL_KEY를 Secrets에 등록하면 영상을 생성할 수 있습니다.")
else:
    # 전체 일괄 생성 버튼
    pending_scenes = [s for s in scenes if s.get("status") in ("pending", "error")]
    col_gen, col_info2 = st.columns([2, 5])
    with col_gen:
        all_gen_btn = st.button(
            f"▶ 미완료 {len(pending_scenes)}컷 일괄 생성",
            disabled=(len(pending_scenes) == 0 or st.session_state.gen_running),
        )
    with col_info2:
        if st.session_state.gen_running:
            st.info("영상 생성 중… 완료되면 새로고침 버튼을 눌러 상태를 확인하세요.")

    # 일괄 생성: 백그라운드 스레드로 순차 실행
    if all_gen_btn and not st.session_state.gen_running:
        st.session_state.gen_running = True

        def run_all_pending(state_snapshot, fal_key):
            mgr = StateManager(storage_dir="projects")
            current = mgr.load_state(state_snapshot["project_dir"])
            for scene in current["scenes"]:
                if scene.get("status") in ("pending", "error"):
                    sno = scene["scene_no"]
                    out_path = os.path.join(
                        current["project_dir"], f"scene_{sno:02d}.mp4"
                    )
                    scene["status"] = "generating"
                    mgr.save_state(current)
                    try:
                        generate_single_clip(
                            fal_key=fal_key,
                            prompt=scene.get("flow_prompt", ""),
                            output_path=out_path,
                            image_url=scene.get("reference_image_url", ""),
                        )
                        scene["video_url"] = out_path
                        scene["status"] = "done"
                    except Exception as ex:
                        scene["status"] = "error"
                        scene["error_msg"] = str(ex)
                    mgr.save_state(current)
            # 완료 플래그 (session_state는 스레드에서 직접 못 씀 — 상태 파일로 전달)

        t = threading.Thread(
            target=run_all_pending,
            args=(state, api_keys["FAL_KEY"]),
            daemon=True,
        )
        t.start()
        st.session_state.gen_running = False  # UI 언블락 (스레드가 백그라운드 처리)
        st.info("영상 생성을 시작했습니다. 화면이 자동으로 갱신됩니다.")

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
            vid_url= scene.get("video_url", "")

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
                img_path   = scene.get("image_path", "")
                img_status = scene.get("image_status", "pending")
                current_ref = scene.get("reference_image_url", "")

                # Flux 생성 이미지가 있으면 썸네일 표시
                if img_path and os.path.exists(img_path):
                    st.image(img_path, use_container_width=True,
                             caption=f"Flux 자동생성 · {img_status}")
                    new_ref = img_path  # Kling 첫 프레임으로 자동 사용
                else:
                    # 개별 이미지 생성 버튼
                    img_status_label = {
                        "pending": "⏳ 미생성", "generating": "⚙️ 생성중",
                        "done": "✅ 완료", "error": "❌ 오류"
                    }.get(img_status, "?")
                    st.caption(f"이미지: {img_status_label}")

                    if st.button(f"🖼 #{sno:02d} 이미지 생성",
                                 key=f"img_regen_{sno}",
                                 disabled=(img_status == "generating"),
                                 use_container_width=True):
                        def regen_img(sc, fal_key, proj_dir):
                            from src.state_manager import StateManager
                            from src.image_fal import generate_reference_image
                            out = os.path.join(proj_dir, f"scene_{sc['scene_no']:02d}_ref.png")
                            sc["image_status"] = "generating"
                            try:
                                generate_reference_image(fal_key, sc.get("image_prompt",""), out)
                                sc["image_path"]   = out
                                sc["image_status"] = "done"
                                sc["reference_image_url"] = out
                            except Exception as ex:
                                sc["image_status"] = "error"
                                sc["image_error"]  = str(ex)
                            mgr3 = StateManager(storage_dir="projects")
                            cur3 = mgr3.load_state(proj_dir)
                            for s3 in cur3["scenes"]:
                                if s3["scene_no"] == sc["scene_no"]:
                                    s3.update(sc); break
                            mgr3.save_state(cur3)

                        threading.Thread(
                            target=regen_img,
                            args=(scene, api_keys["FAL_KEY"], state["project_dir"]),
                            daemon=True,
                        ).start()
                        st.info(f"#{sno:02d} 이미지 생성 시작. 자동 갱신됩니다.")

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

                # 영상 미리보기
                if vid_url and os.path.exists(vid_url):
                    st.video(vid_url)
                elif status == "error":
                    st.error(scene.get("error_msg", "알 수 없는 오류"))

                # 개별 재생성 버튼
                btn_disabled = (status == "generating")
                if st.button(
                    f"🔄 #{sno:02d} 재생성",
                    key=f"regen_scene_{sno}",
                    disabled=btn_disabled,
                    use_container_width=True,
                ):
                    out_path = os.path.join(
                        state["project_dir"], f"scene_{sno:02d}.mp4"
                    )
                    # 상태 즉시 업데이트
                    for s in state["scenes"]:
                        if s["scene_no"] == sno:
                            s["status"] = "generating"
                            break
                    manager.save_state(state)

                    def regen_one(scene_ref, fal_key, out, st_ref, proj_dir):
                        mgr2 = StateManager(storage_dir="projects")
                        cur2 = mgr2.load_state(proj_dir)
                        target = next(
                            (sc for sc in cur2["scenes"]
                             if sc["scene_no"] == scene_ref["scene_no"]), None
                        )
                        if not target:
                            return
                        try:
                            generate_single_clip(
                                fal_key=fal_key,
                                prompt=target.get("flow_prompt", ""),
                                output_path=out,
                                image_url=target.get("reference_image_url", ""),
                            )
                            target["video_url"] = out
                            target["status"] = "done"
                        except Exception as ex:
                            target["status"] = "error"
                            target["error_msg"] = str(ex)
                        mgr2.save_state(cur2)

                    t2 = threading.Thread(
                        target=regen_one,
                        args=(scene, api_keys["FAL_KEY"], out_path, state, state["project_dir"]),
                        daemon=True,
                    )
                    t2.start()
                    st.info(f"#{sno:02d} 재생성 시작. 자동 갱신됩니다.")

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
    <div class="step-title">STEP 5 · 최종 합성 (FFmpeg + Whisper 자막)</div>
    <div class="step-sub">
      {"최종 영상 완성!" if step4_done
        else ("STEP 2 음성 + STEP 3 전체 영상 완료 후 실행 가능" if step4_locked
              else "음성·영상·SFX·BGM을 합쳐 다이나믹 자막 포함 숏폼을 생성합니다.")}
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

if step4_done:
    final_path = state["final_video_path"]
    if os.path.exists(final_path):
        st.video(final_path)
        with open(final_path, "rb") as fv:
            st.download_button(
                label="⬇️ 최종 영상 다운로드",
                data=fv,
                file_name=f"{state.get('project_id','final')}.mp4",
                mime="video/mp4",
            )
    else:
        st.caption(f"파일 경로: `{final_path}`")
elif not step4_locked:
    st.info(
        "🔧 **`src/assembler.py` 구현 대기 중** — "
        "FFmpeg·Whisper 합성 코드가 완성되면 이 버튼이 활성화됩니다.",
        icon="ℹ️",
    )
    st.button("최종 합성 실행 (준비 중)", disabled=True)

st.markdown("<br>", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# 자동 새로고침 — 백그라운드 생성 중일 때 10초마다 화면 갱신
# ─────────────────────────────────────────────────────────────────────────────
if any_generating:
    # 상태 파일에서 최신 데이터 다시 로드
    try:
        refreshed = manager.load_state(state["project_dir"])
        st.session_state.current_project = refreshed
    except Exception:
        pass
    time.sleep(10)
    st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# 푸터
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="factory-footer">
  너도나도아는커피 숏폼 팩토리 · Powered by Claude API · ElevenLabs · Fal.ai Kling
</div>
""", unsafe_allow_html=True)
