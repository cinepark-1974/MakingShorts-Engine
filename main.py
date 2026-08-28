# app.py — 너도나도아는커피 숏폼 팩토리 | Streamlit 메인 대시보드
# Claude API 버전 (Anthropic claude-sonnet-4-6)

import streamlit as st
import os
import time
import threading
import base64
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
</style>
""", unsafe_allow_html=True)

# ── 소스 모듈 임포트 ─────────────────────────────────────────────────────────
try:
    from src.state_manager import StateManager
    from src.prompts import generate_script_and_prompts
    from src.video_fal import generate_single_clip
    MODULES_OK = True
except ImportError as e:
    MODULES_OK = False
    IMPORT_ERROR = str(e)

# ── API 키 로드 ───────────────────────────────────────────────────────────────
def load_api_keys():
    """secrets.toml → 환경변수 순으로 API 키 로드"""
    keys = {}
    for k in ["ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "FAL_KEY"]:
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
missing = [k for k, v in api_keys.items() if not v]
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

    col1, col2 = st.columns([1, 2])
    with col1:
        chapter = st.text_input(
            "챕터 (Chapter)",
            placeholder="예: CH01 커피의 탄생",
            help="예시: CH01 커피의 탄생 / CH02 에스프레소의 과학"
        )
    with col2:
        topic = st.text_input(
            "주제 (Topic)",
            placeholder="예: 에티오피아 예가체프 내추럴 프로세싱의 비밀",
            help="구체적일수록 좋은 대본이 생성됩니다."
        )

    st.markdown("")
    start_btn = st.button(
        "☕ 대본 생성 시작",
        disabled=(not chapter or not topic or not api_keys.get("ANTHROPIC_API_KEY")),
        use_container_width=False,
    )

    if start_btn:
        if not chapter.strip() or not topic.strip():
            st.error("챕터와 주제를 모두 입력해 주세요.")
        else:
            with st.spinner("Claude AI가 12컷 대본을 작성하고 있습니다… (약 20~40초)"):
                try:
                    # 프로젝트 디렉터리 생성
                    new_state = manager.create_new_project(
                        chapter=chapter.strip(),
                        topic=topic.strip()
                    )
                    # Claude API 호출
                    result = generate_script_and_prompts(
                        api_key=api_keys["ANTHROPIC_API_KEY"],
                        chapter=chapter.strip(),
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
# STEP 2 — 음성 생성 (ElevenLabs) — 스텁
# ─────────────────────────────────────────────────────────────────────────────
step2_done = bool(state.get("audio_path"))
step2_locked = not step1_done

st.markdown(f"""
<div class="step-header">
  <div class="step-num {"done" if step2_done else ("locked" if step2_locked else "")}">
    {"✓" if step2_done else "2"}
  </div>
  <div>
    <div class="step-title">STEP 2 · 나레이션 음성 생성 (ElevenLabs)</div>
    <div class="step-sub">{"음성 파일 준비 완료" if step2_done else ("STEP 1을 먼저 완료하세요." if step2_locked else "전체 나레이션을 ElevenLabs API로 MP3 변환합니다.")}</div>
  </div>
</div>
""", unsafe_allow_html=True)

if step2_done:
    audio_path = state["audio_path"]
    if os.path.exists(audio_path):
        st.audio(audio_path, format="audio/mp3")
    else:
        st.caption(f"파일 경로: `{audio_path}`")
elif not step2_locked:
    if not api_keys.get("ELEVENLABS_API_KEY"):
        st.info("ELEVENLABS_API_KEY를 Secrets에 등록하면 이 단계를 실행할 수 있습니다.")
    else:
        # audio.py 구현 완료 후 활성화
        st.info(
            "🔧 **`src/audio.py` 구현 대기 중** — "
            "ElevenLabs 연동 코드가 완성되면 이 버튼이 활성화됩니다.",
            icon="ℹ️",
        )
        st.button("음성 생성 실행 (준비 중)", disabled=True)

st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — 컷별 영상 생성 (Fal.ai Kling)
# ─────────────────────────────────────────────────────────────────────────────
step3_locked = not step1_done

st.markdown(f"""
<div class="step-header">
  <div class="step-num {"done" if done_cnt == total_cnt and total_cnt > 0 else ("locked" if step3_locked else "")}">
    {"✓" if done_cnt == total_cnt and total_cnt > 0 else "3"}
  </div>
  <div>
    <div class="step-title">STEP 3 · 컷별 영상 생성 (Fal.ai Kling v2.6 Pro)</div>
    <div class="step-sub">9:16 세로 · 5초 · 컷별 개별 생성 및 재생성 가능</div>
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
        st.info("일괄 생성을 시작했습니다. 완료 후 새로고침 버튼을 누르세요.")

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
                    st.info(f"#{sno:02d} 재생성 시작. 잠시 후 새로고침하세요.")

st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — 최종 합성 (FFmpeg + Whisper) — 스텁
# ─────────────────────────────────────────────────────────────────────────────
step4_done   = bool(state.get("final_video_path"))
step4_locked = done_cnt < total_cnt or total_cnt == 0 or not state.get("audio_path")

st.markdown(f"""
<div class="step-header">
  <div class="step-num {"done" if step4_done else ("locked" if step4_locked else "")}">
    {"✓" if step4_done else "4"}
  </div>
  <div>
    <div class="step-title">STEP 4 · 최종 합성 (FFmpeg + Whisper 자막)</div>
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
# 푸터
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="factory-footer">
  너도나도아는커피 숏폼 팩토리 · Powered by Claude API · ElevenLabs · Fal.ai Kling
</div>
""", unsafe_allow_html=True)
