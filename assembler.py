# src/assembler.py
# 너도나도아는커피 숏폼 팩토리 — FFmpeg 최종 합성기 (오버레이 v4)
#
# v4 핵심 변경:
#   1. 다크 패널·스파인·진행바를 PIL 레이어로 이동
#      → PNG 전체가 fade in/out되므로 패널도 함께 자연스럽게 사라짐
#      → FFmpeg drawbox의 alpha 불지원 문제 해결
#   2. 그래픽 요소 크기 2배 확대 (코너 브래킷, 포커스링, 스캔라인)
#   3. 데이터 추출 패턴 수정 — "도\b" (93도), "분\b" (4분) 추가
#   4. 오버레이 표시 구간 단축: 1.0s ~ 3.0s (2초, fade 0.3s 포함)
#   5. 엔딩 컷 방지: apad + -t video_dur

import os
import re
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
# 파일 다운로드 / 복사
# ─────────────────────────────────────────────────────────────────────────────
def _download_to(url: str, dest_path: str, timeout: int = 180) -> bool:
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
    if src.startswith("http"):
        return _download_to(src, dest_path)
    if os.path.exists(src):
        shutil.copy2(src, dest_path)
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# 폰트 탐색
# ─────────────────────────────────────────────────────────────────────────────
def _find_font(bold: bool = False) -> str:
    if bold:
        candidates = [
            "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
            "/usr/share/fonts/nanum/NanumGothicBold.ttf",
            "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
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
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# ffprobe
# ─────────────────────────────────────────────────────────────────────────────
def _probe_video(path: str) -> dict:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", "-select_streams", "v:0", path],
            capture_output=True,
        )
        data   = json.loads(result.stdout.decode())
        stream = data["streams"][0]
        return {
            "w":   int(stream.get("width",    1080)),
            "h":   int(stream.get("height",   1920)),
            "dur": float(stream.get("duration", 5.0)),
        }
    except Exception:
        return {"w": 1080, "h": 1920, "dur": 5.0}


# ─────────────────────────────────────────────────────────────────────────────
# textfile 헬퍼
# ─────────────────────────────────────────────────────────────────────────────
def _write_textfile(tmpdir: str, name: str, text: str) -> str:
    path = os.path.join(tmpdir, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


# ─────────────────────────────────────────────────────────────────────────────
# 나레이션 과학 수치 추출 (v4 — "도", "분" 패턴 추가)
# ─────────────────────────────────────────────────────────────────────────────
def _extract_science_data(narration: str) -> list:
    """나레이션에서 숫자+단위 조합 최대 3개 추출."""
    results: list = []
    seen: set     = set()

    checks = [
        # 온도: "93도씨", "93°C", "93℃", "93도" 모두 허용
        (r"(\d+(?:\.\d+)?)\s*(?:°C|도씨|℃|도(?!\s*[중움]))",  "°C"),
        # 압력
        (r"(\d+(?:\.\d+)?)\s*(?:bar|기압|바)",                  "BAR"),
        # 시간(초)
        (r"(\d+(?:\.\d+)?)\s*초\b",                             "SEC"),
        # 시간(분)
        (r"(\d+(?:\.\d+)?)\s*분\b",                             "MIN"),
        # 무게
        (r"(\d+(?:\.\d+)?)\s*(?:그램\b|g\b)",                  "g"),
        # 용량
        (r"(\d+(?:\.\d+)?)\s*(?:ml\b|mL\b|밀리리터)",          "ml"),
        # 퍼센트
        (r"(\d+(?:\.\d+)?)\s*%",                                "%"),
        # 비율 1:N
        (r"1\s*[：:]\s*(\d+(?:\.\d+)?)",                        "RATIO"),
    ]

    for pattern, unit in checks:
        if unit in seen:
            continue
        m = re.search(pattern, narration, re.IGNORECASE)
        if m:
            raw = m.group(1)
            display_val  = f"1:{raw}" if unit == "RATIO" else raw
            results.append({"value": display_val, "unit": unit})
            seen.add(unit)
        if len(results) >= 3:
            break

    return results


# ─────────────────────────────────────────────────────────────────────────────
# PIL 오버레이 PNG 생성 (v4)
# 포함: 다크 패널 · 스파인 · 진행바 · 코너 브래킷 · 스캔라인
#       포커스 십자선 · 동심원 링 · 데이터 레드아웃 · L자 연결선
# ─────────────────────────────────────────────────────────────────────────────
def _generate_annotation_png(
    scene: dict, info: dict, tmpdir: str, scene_no: int, total: int
) -> str:
    png_path = os.path.join(tmpdir, f"ann_{scene_no:02d}.png")

    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        # PIL 없으면 완전 투명 PNG (ffmpeg geq 방식)
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi",
             "-i", f"color=c=black:s={info['w']}x{info['h']}:r=1",
             "-vf", "format=rgba,colorchannelmixer=aa=0",
             "-vframes", "1", png_path],
            capture_output=True,
        )
        return png_path

    w, h       = info["w"], info["h"]
    scene_type = _classify_scene_type(scene.get("flow_prompt", ""))
    narration  = scene.get("narration", "")

    # 색상 팔레트
    GOLD        = (212, 168,  67, 220)
    GOLD_LINE   = (212, 168,  67, 160)
    GOLD_FULL   = (212, 168,  67, 255)
    WHITE_HI    = (255, 255, 255, 240)
    DARK_PANEL  = (  9,   9,   9, 209)  # 0x090909 @ ~82%
    DARK_BOX    = (  9,   9,   9, 200)

    margin   = int(w * 0.04)
    panel_h  = int(h * 0.24)          # 24%로 축소 (v3은 28%)
    panel_y  = h - panel_h

    img  = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # ── 1. 하단 다크 패널 + 황금 스파인 + 진행 바 ──────────────────────────
    draw.rectangle([0, panel_y, w, h], fill=DARK_PANEL)
    draw.rectangle([0, panel_y, 4, h], fill=GOLD_FULL)   # 스파인

    prog_bar_h = 4
    prog_bar_w = max(4, int(w * (scene_no / max(total, 1))))
    prog_y     = panel_y - prog_bar_h - 2
    draw.rectangle([0, prog_y, prog_bar_w, prog_y + prog_bar_h],
                   fill=(212, 168, 67, 230))

    # ── 2. 코너 브래킷 (v4: 더 크고 굵게) ──────────────────────────────────
    bkt   = int(w * 0.10)   # v3: 0.07 → v4: 0.10
    thick = 3               # v3: 2px → v4: 3px
    bot_y = panel_y - margin

    for (cx, cy, dx, dy) in [
        (margin,     margin, +bkt, +bkt),
        (w - margin, margin, -bkt, +bkt),
        (margin,     bot_y,  +bkt, -bkt),
        (w - margin, bot_y,  -bkt, -bkt),
    ]:
        draw.line([(cx, cy), (cx + dx, cy)], fill=GOLD, width=thick)
        draw.line([(cx, cy), (cx, cy + dy)], fill=GOLD, width=thick)

    # ── 3. 수평 스캔 라인 장식 (v4: 더 길고 밝게) ───────────────────────────
    scan_pairs = [
        (int(h * 0.082), int(w * 0.35)),
        (int(h * 0.098), int(w * 0.20)),
    ]
    for sy, sx_end in scan_pairs:
        draw.line([(margin, sy), (sx_end, sy)],           fill=GOLD_LINE, width=1)
        draw.line([(w - margin, sy), (w - sx_end, sy)],   fill=GOLD_LINE, width=1)

    # ── 4. 중앙 포커스 십자선 + 동심원 링 (v4: 대폭 확대) ──────────────────
    fp_x = w // 2
    fp_y = int(h * 0.38)

    cross_len = int(w * 0.05)   # v3: 0.025 → v4: 0.05
    gap       = int(w * 0.015)

    draw.line([(fp_x - cross_len - gap, fp_y), (fp_x - gap, fp_y)], fill=GOLD, width=2)
    draw.line([(fp_x + gap, fp_y), (fp_x + cross_len + gap, fp_y)], fill=GOLD, width=2)
    draw.line([(fp_x, fp_y - cross_len - gap), (fp_x, fp_y - gap)], fill=GOLD, width=2)
    draw.line([(fp_x, fp_y + gap), (fp_x, fp_y + cross_len + gap)], fill=GOLD, width=2)

    # 동심원 링 3개 (v3 대비 반지름 1.5배)
    for r, alpha, lw in [
        (int(w * 0.038), 190, 2),
        (int(w * 0.065), 110, 1),
        (int(w * 0.100),  55, 1),
    ]:
        draw.ellipse([fp_x - r, fp_y - r, fp_x + r, fp_y + r],
                     outline=(212, 168, 67, alpha), width=lw)

    # ── 5. 과학 데이터 레드아웃 박스 ────────────────────────────────────────
    science_data = _extract_science_data(narration)

    if science_data and scene_type in ("SCIENCE", "RECIPE", "MECH"):
        rd_w   = int(w * 0.40)
        rd_x   = w - rd_w - margin
        rd_y   = int(h * 0.10)
        line_h = int(h * 0.050)
        pad_x  = int(w * 0.028)
        pad_y  = int(h * 0.016)
        rd_h   = len(science_data) * line_h + pad_y * 2

        # 배경 + 테두리
        draw.rectangle([rd_x, rd_y, rd_x + rd_w, rd_y + rd_h], fill=DARK_BOX)
        draw.rectangle([rd_x, rd_y, rd_x + 4,    rd_y + rd_h], fill=GOLD_FULL)
        draw.rectangle([rd_x, rd_y, rd_x + rd_w, rd_y + 1],
                       fill=(212, 168, 67, 160))

        # 폰트
        nanum_bold   = "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"
        nanum_normal = "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"
        font_path    = nanum_bold if os.path.exists(nanum_bold) else nanum_normal
        try:
            fnt_val  = ImageFont.truetype(font_path, int(h * 0.034))
            fnt_unit = ImageFont.truetype(font_path, int(h * 0.022))
        except Exception:
            fnt_val = fnt_unit = ImageFont.load_default()

        for i, d in enumerate(science_data):
            ty = rd_y + pad_y + i * line_h
            draw.text((rd_x + pad_x, ty), d["value"],
                      fill=WHITE_HI, font=fnt_val)
            try:
                val_bbox = draw.textbbox((rd_x + pad_x, ty), d["value"], font=fnt_val)
                val_w    = val_bbox[2] - val_bbox[0]
            except AttributeError:
                val_w = int(len(d["value"]) * h * 0.020)
            draw.text(
                (rd_x + pad_x + val_w + int(w * 0.012),
                 ty + int(h * 0.008)),
                d["unit"],
                fill=(212, 168, 67, 220),
                font=fnt_unit,
            )

        # L자 연결선: 포커스 → 레드아웃
        conn_color = (212, 168, 67, 130)
        start_x   = fp_x + int(w * 0.100)
        start_y   = fp_y
        mid_x     = fp_x + int(w * 0.130)
        end_x     = rd_x
        end_y     = rd_y + rd_h // 2

        draw.line([(start_x, start_y), (mid_x, start_y)], fill=conn_color, width=1)
        draw.line([(mid_x, start_y), (mid_x, end_y)],     fill=conn_color, width=1)
        draw.line([(mid_x, end_y), (end_x, end_y)],       fill=conn_color, width=1)
        dot = 4
        draw.ellipse([start_x - dot, start_y - dot,
                      start_x + dot, start_y + dot],
                     fill=(212, 168, 67, 200))

    img.save(png_path, "PNG")
    return png_path


# ─────────────────────────────────────────────────────────────────────────────
# FFmpeg 텍스트 필터그래프 (v4)
# — 패널/스파인/진행바는 PIL에서 처리하므로 여기선 텍스트만
# — KEY POINT 배경 박스도 drawbox + enable= 으로 유지
# ─────────────────────────────────────────────────────────────────────────────
def _build_text_filtergraph(
    scene: dict,
    scene_no: int,
    total: int,
    info: dict,
    tmpdir: str,
    font: str,
    font_bold: str,
    show_start: float,
    show_end: float,
) -> str:
    w, h = info["w"], info["h"]

    panel_h      = int(h * 0.24)       # PIL과 동일 비율
    panel_y      = h - panel_h
    margin_l     = 4 + int(w * 0.04)  # 스파인(4px) + 여백
    margin_r     = int(w * 0.04)
    font_size_kw = max(40, int(h * 0.040))
    font_size_nr = max(28, int(h * 0.028))
    font_size_lb = max(24, int(h * 0.024))
    font_size_ch = max(22, int(h * 0.022))

    GOLD   = "0xD4A843"
    WHITE  = "0xFFFFFF"
    GOLD_A = "0xD4A843@0.92"

    scene_type = _classify_scene_type(scene.get("flow_prompt", ""))
    overlay_kw = scene.get("overlay_text", "").strip() or scene.get("name", "").strip()
    narration  = scene.get("narration", "").strip()

    if len(narration) > 32:
        mid      = len(narration) // 2
        split_at = narration.rfind(" ", 0, mid + 4)
        if split_at < 5:
            split_at = mid
        narration_display = narration[:split_at] + "\n" + narration[split_at:].strip()
    else:
        narration_display = narration

    channel_name = "너도나도아는커피"
    scene_label  = f"{scene_type}  {scene_no:02d} / {total:02d}"

    tf_kw = _write_textfile(tmpdir, f"kw_{scene_no:02d}.txt", overlay_kw)
    tf_nr = _write_textfile(tmpdir, f"nr_{scene_no:02d}.txt", narration_display)
    tf_ch = _write_textfile(tmpdir, f"ch_{scene_no:02d}.txt", channel_name)
    tf_lb = _write_textfile(tmpdir, f"lb_{scene_no:02d}.txt", scene_label)
    tf_kp = _write_textfile(tmpdir, f"kp_{scene_no:02d}.txt", "KEY POINT")

    fd = 0.3
    # 텍스트 페이드 — PIL 오버레이와 동일 구간
    alpha_expr = (
        f"if(lt(t,{show_start}),0,"
        f"if(lt(t,{show_start + fd}),(t-{show_start})/{fd},"
        f"if(lt(t,{show_end - fd}),1,"
        f"if(lt(t,{show_end}),({show_end}-t)/{fd},0))))"
    )
    # drawbox enable (abrupt, 텍스트 fade와 함께 쓰면 자연스러움)
    enable_expr = f"between(t,{show_start},{show_end})"

    def fopt(bold: bool = False) -> str:
        fp = font_bold if (bold and font_bold) else font
        return f"fontfile='{fp}':" if fp else ""

    kp_box_x = margin_l
    kp_box_y = panel_y + int(panel_h * 0.10)
    kp_box_w = int(w * 0.24)
    kp_box_h = font_size_lb + 10
    kw_y     = kp_box_y + kp_box_h + int(h * 0.010)
    nr_y     = panel_y + int(panel_h * 0.60)

    spec_box_x = w - int(w * 0.22) - margin_r
    spec_box_y = int(h * 0.04)
    spec_box_w = int(w * 0.22)
    spec_box_h = font_size_lb + 8

    parts = []

    # KEY POINT 배경 박스
    parts.append(
        f"drawbox=x={kp_box_x}:y={kp_box_y}:w={kp_box_w}:h={kp_box_h}"
        f":color={GOLD_A}:t=fill:enable='{enable_expr}'"
    )
    # KEY POINT 텍스트
    parts.append(
        f"drawtext={fopt(True)}textfile='{tf_kp}'"
        f":x={kp_box_x + 6}:y={kp_box_y + 5}"
        f":fontsize={font_size_lb}:fontcolor=0x0A0A0A:alpha='{alpha_expr}'"
    )
    # overlay_text 키워드
    parts.append(
        f"drawtext={fopt(True)}textfile='{tf_kw}'"
        f":x={margin_l}:y={kw_y}"
        f":fontsize={font_size_kw}:fontcolor={WHITE}:alpha='{alpha_expr}'"
    )
    # 나레이션 자막
    parts.append(
        f"drawtext={fopt(False)}textfile='{tf_nr}'"
        f":x=(w-text_w)/2:y={nr_y}"
        f":fontsize={font_size_nr}:fontcolor={WHITE}:line_spacing=6:alpha='{alpha_expr}'"
    )
    # 채널명 (좌상단)
    parts.append(
        f"drawtext={fopt(False)}textfile='{tf_ch}'"
        f":x={int(w * 0.04)}:y={int(h * 0.04)}"
        f":fontsize={font_size_ch}:fontcolor={GOLD}:alpha='{alpha_expr}'"
    )
    # 씬 타입 라벨 (우상단)
    parts.append(
        f"drawtext={fopt(False)}textfile='{tf_lb}'"
        f":x=w-text_w-{margin_r}:y={int(h * 0.04)}"
        f":fontsize={font_size_ch}:fontcolor={WHITE}:alpha='{alpha_expr}'"
    )
    # SCIENCE SPEC 배지
    if scene_type == "SCIENCE":
        tf_sp = _write_textfile(tmpdir, f"sp_{scene_no:02d}.txt", "SPEC")
        parts.append(
            f"drawbox=x={spec_box_x}:y={spec_box_y}"
            f":w={spec_box_w}:h={spec_box_h}"
            f":color={GOLD_A}:t=fill:enable='{enable_expr}'"
        )
        parts.append(
            f"drawtext={fopt(True)}textfile='{tf_sp}'"
            f":x={spec_box_x + int(spec_box_w * 0.25)}:y={spec_box_y + 4}"
            f":fontsize={font_size_lb}:fontcolor=0x0A0A0A:alpha='{alpha_expr}'"
        )

    return ",".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# 씬별 오버레이 적용
# ─────────────────────────────────────────────────────────────────────────────
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
    info = _probe_video(src_path)
    dur  = info["dur"]

    # 오버레이 표시 구간: 1.0s ~ 3.0s (2초 노출)
    show_start = 1.0
    show_end   = min(dur - 0.8, show_start + 2.0)
    if show_end <= show_start + 0.6:
        show_start = 0.3
        show_end   = dur - 0.3

    # PIL 어노테이션 PNG 생성
    ann_png = _generate_annotation_png(scene, info, tmpdir, scene_no, total)

    # 텍스트 필터그래프
    text_fg = _build_text_filtergraph(
        scene, scene_no, total, info, tmpdir, font, font_bold,
        show_start, show_end,
    )

    fd = 0.3
    # filter_complex:
    # [1:v] = 어노테이션 PNG (-loop 1 로 영상 길이만큼 확장)
    # PNG에 fade in/out 적용 → [0:v]에 overlay → 텍스트 적용
    filter_complex = (
        f"[1:v]format=rgba,"
        f"fade=t=in:st={show_start}:d={fd}:alpha=1,"
        f"fade=t=out:st={show_end - fd}:d={fd}:alpha=1[ann];"
        f"[0:v][ann]overlay=0:0[base];"
        f"[base]{text_fg}[out]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", src_path,
        "-loop", "1", "-t", str(dur), "-i", ann_png,
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-map", "0:a?",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "copy",
        out_path,
    ]
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
    state의 모든 씬 video_url + audio_path → 최종 숏폼 MP4 → fal CDN URL 반환.
    """
    os.environ["FAL_KEY"] = fal_key

    scenes    = state.get("scenes", [])
    audio_src = state.get("audio_path", "").strip()
    total     = len([s for s in scenes if s.get("video_url", "").strip()])

    font      = _find_font(bold=False)
    font_bold = _find_font(bold=True)

    with tempfile.TemporaryDirectory() as tmpdir:

        # ── 1. 클립 다운로드 ──────────────────────────────────────────────────
        clip_items = []
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
                "합성할 영상 클립이 없습니다. STEP 4에서 모든 컷 영상을 먼저 생성해 주세요."
            )

        # ── 2. 씬별 오버레이 적용 ────────────────────────────────────────────
        final_clips = []
        for clip_path, scene, sno in clip_items:
            if apply_overlay:
                ov_path = os.path.join(tmpdir, f"ov_{sno:02d}.mp4")
                ok = _apply_overlay_to_clip(
                    clip_path, ov_path, scene, sno, total,
                    tmpdir, font, font_bold,
                )
                final_clips.append(ov_path if ok else clip_path)
            else:
                final_clips.append(clip_path)

        # ── 3. 클립 리스트 파일 ─────────────────────────────────────────────
        list_file = os.path.join(tmpdir, "clips.txt")
        with open(list_file, "w", encoding="utf-8") as f:
            for p in final_clips:
                escaped = p.replace("\\", "\\\\").replace("'", "\\'")
                f.write(f"file '{escaped}'\n")

        # ── 4. concat ────────────────────────────────────────────────────────
        concat_path = os.path.join(tmpdir, "concat.mp4")
        proc = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", list_file, "-c", "copy", concat_path],
            capture_output=True,
        )
        if proc.returncode != 0:
            err = proc.stderr.decode(errors="replace")[-1000:]
            raise ValueError(f"FFmpeg concat 실패:\n{err}")

        # ── 5. 영상 길이 확인 ────────────────────────────────────────────────
        video_dur = _probe_video(concat_path)["dur"]

        # ── 6. 오디오 준비 ──────────────────────────────────────────────────
        audio_path = ""
        if audio_src:
            audio_path = os.path.join(tmpdir, "narration.mp3")
            if not _copy_or_download(audio_src, audio_path):
                audio_path = ""

        # ── 6b. 나레이션 길이 감지 → 영상이 짧으면 마지막 프레임 freeze 연장 ──
        # 나레이션이 클립 합산보다 길면 마지막 프레임을 정지해서 채운다.
        # (prompts.py가 15컷/50~55초로 생성해도 안전망으로 유지)
        mix_target = video_dur  # 최종 믹스 길이 (초)
        video_for_mix = concat_path

        if audio_path and os.path.exists(audio_path):
            narr_probe = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_streams", "-select_streams", "a:0", audio_path],
                capture_output=True,
            )
            try:
                narr_data = json.loads(narr_probe.stdout.decode())
                narr_dur  = float(narr_data["streams"][0].get("duration", video_dur))
            except Exception:
                narr_dur = video_dur

            tail_buf = 1.0   # 나레이션 끝 뒤 1초 여유
            need_dur = narr_dur + tail_buf

            if need_dur > video_dur:
                # tpad 필터: 마지막 프레임을 복제해 부족한 시간만큼 연장
                extend_sec = need_dur - video_dur
                extended_path = os.path.join(tmpdir, "concat_extended.mp4")
                proc_ext = subprocess.run(
                    ["ffmpeg", "-y",
                     "-i", concat_path,
                     "-vf", f"tpad=stop_mode=clone:stop_duration={extend_sec:.3f}",
                     "-c:v", "libx264", "-preset", "fast",
                     "-c:a", "copy",
                     extended_path],
                    capture_output=True,
                )
                if proc_ext.returncode == 0:
                    video_for_mix = extended_path
                    mix_target    = need_dur

        # ── 7. 오디오 합성 ──────────────────────────────────────────────────
        # -t mix_target: 정확한 목표 길이로 컷 (영상 ≥ 나레이션 보장 후)
        final_path = os.path.join(tmpdir, "final.mp4")

        if audio_path and os.path.exists(audio_path):
            proc = subprocess.run(
                ["ffmpeg", "-y",
                 "-i", video_for_mix,
                 "-i", audio_path,
                 "-c:v", "copy",
                 "-c:a", "aac", "-b:a", "128k",
                 "-map", "0:v:0",
                 "-map", "1:a:0",
                 "-af", "apad",
                 "-t", str(mix_target),
                 final_path],
                capture_output=True,
            )
            if proc.returncode != 0:
                err = proc.stderr.decode(errors="replace")[-1000:]
                raise ValueError(f"FFmpeg 오디오 합성 실패:\n{err}")
        else:
            shutil.copy2(video_for_mix, final_path)

        # ── 8. fal.ai 업로드 ────────────────────────────────────────────────
        with open(final_path, "rb") as f:
            video_bytes = f.read()

        return fal_client.upload(video_bytes, content_type="video/mp4")
