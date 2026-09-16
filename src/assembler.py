# src/assembler.py
# 너도나도아는커피 숏폼 팩토리 — FFmpeg 최종 합성기 (오버레이 v2)
#
# 동작 순서:
#   1. 씬별 video_url(CDN or 로컬) → /tmp 다운로드
#   2. 씬별로 "신비한 건축사전" 스타일 텍스트 오버레이 적용
#   3. FFmpeg concat → 하나의 MP4로 이어붙이기
#   4. 나레이션 MP3(CDN or 로컬) 오버레이
#   5. 최종 MP4 → fal.ai CDN 업로드 → URL 반환
#
# 오버레이 디자인 (신비한 건축사전 스타일):
#   - 하단 다크 패널: 0x090909@0.78 반투명
#   - 황금색 스파인 라인: #D4A843, 3px
#   - KEY POINT 라벨: 소형 황금 박스
#   - overlay_text: 대형 볼드 키워드 (씬 대표 단어)
#   - narration 자막: 하단 중앙 흰색
#   - 씬 타입 라벨 (SCIENCE / RECIPE / MECH 등): 우상단
#   - SCIENCE 씬: "SPEC" 배지 추가

import os
import json
import shutil
import subprocess
import tempfile
import requests
import fal_client


# ─────────────────────────────────────────────────────────────────────────────
# 씬 타입 분류
# ─────────────────────────────────────────────────────────────────────────────
_SCENE_TYPE_KEYWORDS = {
    "SCIENCE": ["science", "spec", "data", "extraction", "chemistry", "molecule",
                "ratio", "temperature", "pressure", "bloom", "particle"],
    "RECIPE":  ["recipe", "pour", "brew", "step", "process", "assembly", "grind"],
    "MECH":    ["machine", "equipment", "mechanism", "mech", "cutaway", "part",
                "component", "detail", "cross"],
    "ORIGIN":  ["origin", "farm", "harvest", "region", "map", "history", "world"],
    "STORY":   ["story", "opening", "hook", "emotion", "cinematic", "barista"],
}

def _classify_scene_type(prompt: str) -> str:
    p = prompt.lower()
    for stype, keywords in _SCENE_TYPE_KEYWORDS.items():
        if any(k in p for k in keywords):
            return stype
    return "STORY"


# ─────────────────────────────────────────────────────────────────────────────
# 내부 헬퍼
# ─────────────────────────────────────────────────────────────────────────────
def _download_to(url: str, dest_path: str, timeout: int = 180) -> bool:
    """URL에서 파일을 다운로드한다. 성공 시 True, 실패 시 False."""
    try:
        resp = requests.get(url, stream=True, timeout=timeout)
        resp.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
        return os.path.getsize(dest_path) > 0
    except Exception:
        return False


def _copy_or_download(src: str, dest_path: str) -> bool:
    """src가 URL이면 다운로드, 로컬 파일이면 복사한다."""
    if src.startswith("http"):
        return _download_to(src, dest_path)
    if os.path.exists(src):
        shutil.copy2(src, dest_path)
        return True
    return False


def _find_font(bold: bool = False) -> str:
    """
    시스템에서 한국어 폰트 경로를 찾는다.
    fonts-nanum 패키지 기준 경로를 우선 탐색.
    """
    candidates = []
    if bold:
        candidates = [
            "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
            "/usr/share/fonts/nanum/NanumGothicBold.ttf",
            "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",   # 볼드 없으면 일반
            "/usr/share/fonts/nanum/NanumGothic.ttf",
        ]
    else:
        candidates = [
            "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
            "/usr/share/fonts/nanum/NanumGothic.ttf",
            "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        ]
    for p in candidates:
        if os.path.exists(p):
            return p
    # 폰트 못 찾으면 시스템 기본 (영문만 표시될 수 있음)
    return ""


def _probe_video(path: str) -> dict:
    """ffprobe로 영상의 width, height, duration을 가져온다."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_streams", "-select_streams", "v:0", path,
            ],
            capture_output=True,
        )
        data = json.loads(result.stdout.decode())
        stream = data["streams"][0]
        w = int(stream.get("width", 1080))
        h = int(stream.get("height", 1920))
        # duration: stream 또는 format에서
        dur = float(stream.get("duration", 5.0))
        return {"w": w, "h": h, "dur": dur}
    except Exception:
        return {"w": 1080, "h": 1920, "dur": 5.0}


def _write_textfile(tmpdir: str, name: str, text: str) -> str:
    """텍스트를 파일로 저장하고 경로를 반환 (FFmpeg textfile= 용)."""
    path = os.path.join(tmpdir, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def _build_overlay_filter(
    scene: dict,
    scene_no: int,
    total: int,
    info: dict,
    tmpdir: str,
    font: str,
    font_bold: str,
) -> list:
    """
    "신비한 건축사전" 스타일 FFmpeg filtergraph 문자열 목록을 반환한다.

    반환: ["-vf", "<filtergraph>"] 형태 args 리스트
    """
    w = info["w"]
    h = info["h"]
    dur = info["dur"]

    # ── 상대 사이즈 계산 ──────────────────────────────────────────────────
    panel_h      = int(h * 0.28)          # 하단 패널 높이 (28%)
    panel_y      = h - panel_h            # 패널 시작 Y
    spine_w      = 4                      # 황금 스파인 두께(px)
    margin_l     = spine_w + int(w * 0.04)  # 스파인 + 좌측 여백
    margin_r     = int(w * 0.04)
    font_size_kw = max(38, int(h * 0.038))  # overlay_text 키워드 폰트
    font_size_nr = max(26, int(h * 0.026))  # narration 자막 폰트
    font_size_lb = max(22, int(h * 0.022))  # 라벨 / KEY POINT 폰트
    font_size_ch = max(20, int(h * 0.020))  # 채널명 폰트

    # ── 색상 (FFmpeg 0xRRGGBB@alpha 표기) ────────────────────────────────
    GOLD    = "0xD4A843"
    WHITE   = "0xFFFFFF"
    DARK    = "0x090909@0.82"
    GOLD_A  = "0xD4A843@0.90"

    # ── 씬 타입 분류 ─────────────────────────────────────────────────────
    flow_prompt = scene.get("flow_prompt", "")
    scene_type  = _classify_scene_type(flow_prompt)

    # ── 텍스트 내용 ───────────────────────────────────────────────────────
    overlay_text = scene.get("overlay_text", "").strip() or scene.get("name", "").strip()
    narration    = scene.get("narration", "").strip()

    # narration을 최대 30자씩 2줄로 자름 (긴 문장 대비)
    if len(narration) > 32:
        mid = len(narration) // 2
        # 공백 기준으로 가장 가까운 지점 찾기
        split_at = narration.rfind(" ", 0, mid + 4)
        if split_at < 5:
            split_at = mid
        narration_display = narration[:split_at] + "\n" + narration[split_at:].strip()
    else:
        narration_display = narration

    channel_name = "너도나도아는커피"
    scene_label  = f"{scene_type}  {scene_no:02d} / {total:02d}"

    # ── textfile 경로들 ───────────────────────────────────────────────────
    tf_keyword = _write_textfile(tmpdir, f"kw_{scene_no:02d}.txt",  overlay_text)
    tf_narr    = _write_textfile(tmpdir, f"nr_{scene_no:02d}.txt",  narration_display)
    tf_channel = _write_textfile(tmpdir, f"ch_{scene_no:02d}.txt",  channel_name)
    tf_label   = _write_textfile(tmpdir, f"lb_{scene_no:02d}.txt",  scene_label)
    tf_keypoint = _write_textfile(tmpdir, f"kp_{scene_no:02d}.txt", "KEY POINT")

    # ── 페이드 애니메이션 (AVExpr) ────────────────────────────────────────
    fade_in  = 0.3
    fade_out = 0.3
    alpha_expr = (
        f"if(lt(t,{fade_in}),t/{fade_in},"
        f"if(lt(t,{dur - fade_out}),1,"
        f"({dur}-t)/{fade_out}))"
    )

    # ── 폰트 옵션 (폰트 없으면 생략) ─────────────────────────────────────
    def font_opt(is_bold=False):
        fp = font_bold if (is_bold and font_bold) else font
        if fp:
            return f"fontfile='{fp}':"
        return ""

    # ── 프로그레스 바 좌표 ────────────────────────────────────────────────
    prog_h   = 3
    prog_y   = panel_y - prog_h - 2
    prog_w   = int(w * (scene_no / total))

    # ── KEY POINT 박스 좌표 ───────────────────────────────────────────────
    kp_box_x = margin_l
    kp_box_y = panel_y + int(panel_h * 0.12)
    kp_box_w = int(w * 0.22)
    kp_box_h = font_size_lb + 8

    # ── overlay_text 키워드 Y 위치 ────────────────────────────────────────
    kw_y = kp_box_y + kp_box_h + int(h * 0.012)

    # ── narration 자막 Y 위치 (패널 하단) ────────────────────────────────
    nr_y = panel_y + int(panel_h * 0.62)

    # ── SPEC 배지 (SCIENCE 씬 전용) ───────────────────────────────────────
    spec_box_x = w - int(w * 0.22) - margin_r
    spec_box_y = int(h * 0.04)
    spec_box_w = int(w * 0.22)
    spec_box_h = font_size_lb + 8

    # ── filtergraph 조각 조립 ─────────────────────────────────────────────
    filters = []

    # A. 하단 다크 패널
    filters.append(
        f"drawbox=x=0:y={panel_y}:w={w}:h={panel_h}:color={DARK}:t=fill"
    )

    # B. 황금 스파인 라인 (좌측 세로선)
    filters.append(
        f"drawbox=x=0:y={panel_y}:w={spine_w}:h={panel_h}:color={GOLD_A}:t=fill"
    )

    # C. 프로그레스 바 (씬 진행도, 패널 위)
    if prog_w > 0:
        filters.append(
            f"drawbox=x=0:y={prog_y}:w={prog_w}:h={prog_h}:color={GOLD_A}:t=fill"
        )

    # D. KEY POINT 배경 박스 + 텍스트
    filters.append(
        f"drawbox=x={kp_box_x}:y={kp_box_y}:w={kp_box_w}:h={kp_box_h}"
        f":color={GOLD_A}:t=fill"
    )
    filters.append(
        f"drawtext={font_opt(True)}textfile='{tf_keypoint}'"
        f":x={kp_box_x + 6}:y={kp_box_y + 4}"
        f":fontsize={font_size_lb}:fontcolor=0x0A0A0A"
        f":alpha='{alpha_expr}'"
    )

    # E. overlay_text 키워드 (굵은 대형 글자)
    filters.append(
        f"drawtext={font_opt(True)}textfile='{tf_keyword}'"
        f":x={margin_l}:y={kw_y}"
        f":fontsize={font_size_kw}:fontcolor={WHITE}"
        f":alpha='{alpha_expr}'"
    )

    # F. 나레이션 자막 (줄바꿈 지원)
    filters.append(
        f"drawtext={font_opt(False)}textfile='{tf_narr}'"
        f":x=(w-text_w)/2:y={nr_y}"
        f":fontsize={font_size_nr}:fontcolor={WHITE}"
        f":line_spacing=6"
        f":alpha='{alpha_expr}'"
    )

    # G. 채널명 (좌상단)
    filters.append(
        f"drawtext={font_opt(False)}textfile='{tf_channel}'"
        f":x={int(w * 0.04)}:y={int(h * 0.04)}"
        f":fontsize={font_size_ch}:fontcolor={GOLD}"
        f":alpha='{alpha_expr}'"
    )

    # H. 씬 타입 라벨 (우상단)
    filters.append(
        f"drawtext={font_opt(False)}textfile='{tf_label}'"
        f":x=w-text_w-{margin_r}:y={int(h * 0.04)}"
        f":fontsize={font_size_ch}:fontcolor={WHITE}"
        f":alpha='{alpha_expr}'"
    )

    # I. SCIENCE 씬: SPEC 배지
    if scene_type == "SCIENCE":
        tf_spec = _write_textfile(tmpdir, f"sp_{scene_no:02d}.txt", "SPEC")
        filters.append(
            f"drawbox=x={spec_box_x}:y={spec_box_y}:w={spec_box_w}:h={spec_box_h}"
            f":color={GOLD_A}:t=fill"
        )
        filters.append(
            f"drawtext={font_opt(True)}textfile='{tf_spec}'"
            f":x={spec_box_x + int(spec_box_w * 0.25)}:y={spec_box_y + 4}"
            f":fontsize={font_size_lb}:fontcolor=0x0A0A0A"
            f":alpha='{alpha_expr}'"
        )

    filtergraph = ",".join(filters)
    return ["-vf", filtergraph]


def _apply_overlay_to_clip(
    src_path: str,
    out_path: str,
    scene: dict,
    scene_no: int,
    total: int,
    tmpdir: str,
    font: str,
    font_bold: str,
) -> bool:
    """
    단일 클립에 오버레이를 적용해 out_path로 저장.
    성공 시 True, 실패 시 False.
    """
    info = _probe_video(src_path)
    vf_args = _build_overlay_filter(
        scene, scene_no, total, info, tmpdir, font, font_bold
    )
    cmd = (
        ["ffmpeg", "-y", "-i", src_path]
        + vf_args
        + ["-c:v", "libx264", "-preset", "fast", "-crf", "22",
           "-c:a", "copy", out_path]
    )
    proc = subprocess.run(cmd, capture_output=True)
    return proc.returncode == 0


# ─────────────────────────────────────────────────────────────────────────────
# 공개 API
# ─────────────────────────────────────────────────────────────────────────────
def assemble_final_video(
    state: dict,
    fal_key: str,
    apply_overlay: bool = True,
) -> str:
    """
    state의 모든 씬 video_url과 audio_path를 합쳐 최종 숏폼을 만들고
    fal.ai CDN URL을 반환한다.

    Args:
        state         : 프로젝트 상태 dict (scenes, audio_path 포함)
        fal_key       : FAL_KEY (fal.ai 업로드용)
        apply_overlay : True면 "신비한 건축사전" 스타일 오버레이 적용

    Returns:
        str : 최종 영상 fal CDN URL

    Raises:
        ValueError : 합성할 클립이 없거나 FFmpeg 실패 시
    """
    os.environ["FAL_KEY"] = fal_key

    scenes    = state.get("scenes", [])
    audio_src = state.get("audio_path", "").strip()
    total     = len([s for s in scenes if s.get("video_url", "").strip()])

    # 폰트 경로 사전 탐색
    font      = _find_font(bold=False)
    font_bold = _find_font(bold=True)

    with tempfile.TemporaryDirectory() as tmpdir:

        # ── 1. 비디오 클립 다운로드 ─────────────────────────────────────────
        clip_items = []   # (clip_path, scene_dict) 튜플 목록
        for scene in sorted(scenes, key=lambda s: s.get("scene_no", 0)):
            video_src = scene.get("video_url", "").strip()
            if not video_src:
                continue
            sno       = scene.get("scene_no", 0)
            clip_path = os.path.join(tmpdir, f"clip_{sno:02d}.mp4")
            if _copy_or_download(video_src, clip_path):
                clip_items.append((clip_path, scene, sno))

        if not clip_items:
            raise ValueError(
                "합성할 영상 클립이 없습니다. "
                "STEP 4에서 모든 컷 영상을 먼저 생성해 주세요."
            )

        # ── 2. 씬별 오버레이 적용 ────────────────────────────────────────────
        final_clips = []
        for clip_path, scene, sno in clip_items:
            if apply_overlay:
                ov_path = os.path.join(tmpdir, f"ov_{sno:02d}.mp4")
                ok = _apply_overlay_to_clip(
                    clip_path, ov_path, scene, sno, total,
                    tmpdir, font, font_bold
                )
                final_clips.append(ov_path if ok else clip_path)
            else:
                final_clips.append(clip_path)

        # ── 3. FFmpeg 클립 리스트 파일 ──────────────────────────────────────
        list_file = os.path.join(tmpdir, "clips.txt")
        with open(list_file, "w", encoding="utf-8") as f:
            for p in final_clips:
                escaped = p.replace("\\", "\\\\").replace("'", "\\'")
                f.write(f"file '{escaped}'\n")

        # ── 4. 클립 이어붙이기 ──────────────────────────────────────────────
        concat_path = os.path.join(tmpdir, "concat.mp4")
        proc = subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", list_file,
                "-c", "copy",
                concat_path,
            ],
            capture_output=True,
        )
        if proc.returncode != 0:
            err = proc.stderr.decode(errors="replace")[-1000:]
            raise ValueError(f"FFmpeg concat 실패:\n{err}")

        # ── 5. 나레이션 오디오 준비 ─────────────────────────────────────────
        audio_path = ""
        if audio_src:
            audio_path = os.path.join(tmpdir, "narration.mp3")
            if not _copy_or_download(audio_src, audio_path):
                audio_path = ""   # 오디오 실패해도 영상 합성 계속

        # ── 6. 오디오 합성 ──────────────────────────────────────────────────
        final_path = os.path.join(tmpdir, "final.mp4")

        if audio_path and os.path.exists(audio_path):
            proc = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", concat_path,
                    "-i", audio_path,
                    "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "128k",
                    "-map", "0:v:0",
                    "-map", "1:a:0",
                    "-shortest",
                    final_path,
                ],
                capture_output=True,
            )
            if proc.returncode != 0:
                err = proc.stderr.decode(errors="replace")[-1000:]
                raise ValueError(f"FFmpeg 오디오 합성 실패:\n{err}")
        else:
            shutil.copy2(concat_path, final_path)

        # ── 7. fal.ai CDN 업로드 ────────────────────────────────────────────
        with open(final_path, "rb") as f:
            video_bytes = f.read()

        cdn_url = fal_client.upload(video_bytes, content_type="video/mp4")
        return cdn_url
