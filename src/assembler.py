# src/assembler.py
# 너도나도아는커피 숏폼 팩토리 — FFmpeg 최종 합성기 (오버레이 v3)
#
# 동작 순서:
#   1. 씬별 video_url(CDN or 로컬) → /tmp 다운로드
#   2. PIL로 씬별 어노테이션 PNG 생성 (과학 데이터, 코너 브래킷, 포커스링)
#   3. FFmpeg filter_complex로 PNG 오버레이 + 텍스트 오버레이 적용
#   4. FFmpeg concat → 하나의 MP4
#   5. 나레이션 MP3 합성 (apad로 길이 보정, 엔딩 컷 방지)
#   6. 최종 MP4 → fal.ai CDN 업로드
#
# 오버레이 디자인 (신비한 건축사전 v3):
#   PIL 레이어:
#     - 4 코너 골드 브래킷
#     - 수평 스캔 라인 장식
#     - 중앙 포커스 십자선 + 동심원 링 (3개)
#     - SCIENCE/RECIPE/MECH 씬: 수치 데이터 레드아웃 박스 (우상단)
#     - 데이터 → 포커스 연결 L자 라인
#   FFmpeg 텍스트 레이어 (하단 패널, 클립 중간 구간만 표시):
#     - 하단 다크 패널 + 황금 스파인 라인
#     - KEY POINT 라벨 박스
#     - overlay_text 키워드 (대형 볼드)
#     - narration 자막
#     - 채널명 (좌상단), 씬 번호/타입 (우상단)
#     - SCIENCE 씬: SPEC 배지
#     ※ 표시 구간: t=0.8 ~ t=4.0 (5초 클립 기준, fade in/out 0.3초)

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
# 내부 헬퍼 — 파일 다운로드 / 복사
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
    candidates = []
    if bold:
        candidates = [
            "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
            "/usr/share/fonts/nanum/NanumGothicBold.ttf",
            "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
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
        data = json.loads(result.stdout.decode())
        stream = data["streams"][0]
        w   = int(stream.get("width", 1080))
        h   = int(stream.get("height", 1920))
        dur = float(stream.get("duration", 5.0))
        return {"w": w, "h": h, "dur": dur}
    except Exception:
        return {"w": 1080, "h": 1920, "dur": 5.0}


# ─────────────────────────────────────────────────────────────────────────────
# textfile 헬퍼 (FFmpeg drawtext용 UTF-8 파일)
# ─────────────────────────────────────────────────────────────────────────────
def _write_textfile(tmpdir: str, name: str, text: str) -> str:
    path = os.path.join(tmpdir, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


# ─────────────────────────────────────────────────────────────────────────────
# 나레이션에서 과학 수치 추출 (최대 3개)
# ─────────────────────────────────────────────────────────────────────────────
def _extract_science_data(narration: str) -> list:
    """나레이션 텍스트에서 숫자+단위 조합을 추출하여 반환."""
    results = []
    seen_units: set = set()

    checks = [
        (r"(\d+(?:\.\d+)?)\s*(?:°C|도씨|℃)",      "°C"),
        (r"(\d+(?:\.\d+)?)\s*(?:bar|기압|바)",       "BAR"),
        (r"(\d+(?:\.\d+)?)\s*초\b",                  "SEC"),
        (r"(\d+(?:\.\d+)?)\s*(?:그램\b|g\b)",        "g"),
        (r"(\d+(?:\.\d+)?)\s*(?:ml\b|mL\b|밀리리터)", "ml"),
        (r"(\d+(?:\.\d+)?)\s*%",                      "%"),
        (r"1\s*[：:]\s*(\d+(?:\.\d+)?)",             "RATIO"),
    ]

    for pattern, unit in checks:
        if unit in seen_units:
            continue
        m = re.search(pattern, narration, re.IGNORECASE)
        if m:
            raw = m.group(1)
            if unit == "RATIO":
                display_val  = f"1:{raw}"
                display_unit = "RATIO"
            else:
                display_val  = raw
                display_unit = unit
            results.append({"value": display_val, "unit": display_unit})
            seen_units.add(unit)
        if len(results) >= 3:
            break

    return results


# ─────────────────────────────────────────────────────────────────────────────
# PIL 어노테이션 PNG 생성 (과학 그래픽 오버레이)
# ─────────────────────────────────────────────────────────────────────────────
def _generate_annotation_png(scene: dict, info: dict, tmpdir: str, scene_no: int) -> str:
    """
    PIL로 투명 어노테이션 PNG 생성.
    - 4 코너 골드 브래킷
    - 수평 스캔 라인 장식
    - 포커스 십자선 + 동심원 링
    - 과학 수치 레드아웃 박스 + 연결 L자 라인 (SCIENCE/RECIPE/MECH)
    PIL 미설치 시 FFmpeg 명령으로 빈 투명 PNG 생성.
    """
    png_path = os.path.join(tmpdir, f"ann_{scene_no:02d}.png")

    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        # PIL 없으면 ffmpeg로 투명 1프레임 PNG 생성
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi",
             f"-i", f"color=c=white@0:s={info['w']}x{info['h']}:r=1",
             "-vframes", "1", png_path],
            capture_output=True,
        )
        return png_path

    w, h         = info["w"], info["h"]
    scene_type   = _classify_scene_type(scene.get("flow_prompt", ""))
    narration    = scene.get("narration", "")

    GOLD         = (212, 168,  67, 210)
    GOLD_DIM     = (212, 168,  67, 100)
    GOLD_BORDER  = (212, 168,  67, 255)
    WHITE_BRIGHT = (255, 255, 255, 235)
    DARK_BG      = (  9,   9,   9, 200)

    margin  = int(w * 0.04)
    panel_h = int(h * 0.28)     # 하단 텍스트 패널 높이 (FFmpeg drawbox와 동일 비율)
    panel_y = h - panel_h

    img  = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # ── A. 코너 브래킷 ──────────────────────────────────────────────────────
    bkt   = int(w * 0.07)   # 브래킷 길이
    thick = 2
    bot_y = panel_y - margin  # 하단 브래킷 Y (패널 위)

    for (cx, cy, dx, dy) in [
        (margin,      margin, +bkt, +bkt),   # 좌상
        (w - margin,  margin, -bkt, +bkt),   # 우상
        (margin,      bot_y,  +bkt, -bkt),   # 좌하
        (w - margin,  bot_y,  -bkt, -bkt),   # 우하
    ]:
        draw.line([(cx, cy), (cx + dx, cy)], fill=GOLD, width=thick)
        draw.line([(cx, cy), (cx, cy + dy)], fill=GOLD, width=thick)

    # ── B. 수평 스캔 라인 장식 ───────────────────────────────────────────────
    for sy, sx_end_ratio in [(int(h * 0.085), 0.28), (int(h * 0.100), 0.16)]:
        sx_end = int(w * sx_end_ratio)
        draw.line([(margin, sy), (sx_end, sy)],     fill=GOLD_DIM, width=1)
        draw.line([(w - margin, sy), (w - sx_end, sy)], fill=GOLD_DIM, width=1)

    # ── C. 포커스 십자선 + 동심원 링 ─────────────────────────────────────────
    fp_x = w // 2
    fp_y = int(h * 0.40)

    cross_len = int(w * 0.025)
    gap       = int(w * 0.012)

    # 십자선 (중심 갭 있는 스코프 스타일)
    draw.line([(fp_x - cross_len - gap, fp_y), (fp_x - gap, fp_y)], fill=GOLD, width=1)
    draw.line([(fp_x + gap, fp_y), (fp_x + cross_len + gap, fp_y)], fill=GOLD, width=1)
    draw.line([(fp_x, fp_y - cross_len - gap), (fp_x, fp_y - gap)], fill=GOLD, width=1)
    draw.line([(fp_x, fp_y + gap), (fp_x, fp_y + cross_len + gap)], fill=GOLD, width=1)

    # 동심원 링 3개 (점점 희미)
    for r, alpha in [(int(w * 0.025), 170), (int(w * 0.043), 90), (int(w * 0.068), 45)]:
        draw.ellipse([fp_x - r, fp_y - r, fp_x + r, fp_y + r],
                     outline=(212, 168, 67, alpha), width=1)

    # ── D. 과학 데이터 레드아웃 박스 (SCIENCE / RECIPE / MECH) ──────────────
    science_data = _extract_science_data(narration)

    if science_data and scene_type in ("SCIENCE", "RECIPE", "MECH"):
        rd_w   = int(w * 0.38)
        rd_x   = w - rd_w - margin
        rd_y   = int(h * 0.115)
        line_h = int(h * 0.046)
        pad_x  = int(w * 0.025)
        pad_y  = int(h * 0.016)
        rd_h   = len(science_data) * line_h + pad_y * 2

        # 배경 박스
        draw.rectangle([rd_x, rd_y, rd_x + rd_w, rd_y + rd_h], fill=DARK_BG)
        # 좌측 골드 보더 (3px)
        draw.rectangle([rd_x, rd_y, rd_x + 3, rd_y + rd_h], fill=GOLD_BORDER)
        # 상단 얇은 골드 라인
        draw.rectangle([rd_x, rd_y, rd_x + rd_w, rd_y + 1], fill=(212, 168, 67, 140))

        # 폰트 로드
        nanum_bold   = "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"
        nanum_normal = "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"
        try:
            fnt_val  = ImageFont.truetype(
                nanum_bold if os.path.exists(nanum_bold) else nanum_normal,
                int(h * 0.030),
            )
            fnt_unit = ImageFont.truetype(
                nanum_bold if os.path.exists(nanum_bold) else nanum_normal,
                int(h * 0.020),
            )
        except Exception:
            fnt_val = fnt_unit = ImageFont.load_default()

        # 각 수치 행
        for i, d in enumerate(science_data):
            ty = rd_y + pad_y + i * line_h
            draw.text((rd_x + pad_x, ty), d["value"],
                      fill=WHITE_BRIGHT, font=fnt_val)
            # 단위는 값 오른쪽에, 골드색, 살짝 아래
            try:
                val_bbox = draw.textbbox((rd_x + pad_x, ty), d["value"], font=fnt_val)
                val_w    = val_bbox[2] - val_bbox[0]
            except AttributeError:
                val_w = int(len(d["value"]) * h * 0.018)
            draw.text(
                (rd_x + pad_x + val_w + int(w * 0.012), ty + int(h * 0.007)),
                d["unit"],
                fill=(212, 168, 67, 210),
                font=fnt_unit,
            )

        # ── E. 포커스 → 레드아웃 L자 연결선 ────────────────────────────────
        conn_color = (212, 168, 67, 110)
        start_x   = fp_x + int(w * 0.068)      # 포커스 링 오른쪽 끝 근처
        start_y   = fp_y
        mid_x     = fp_x + int(w * 0.10)
        end_x     = rd_x
        end_y     = rd_y + rd_h // 2

        draw.line([(start_x, start_y), (mid_x, start_y)], fill=conn_color, width=1)
        draw.line([(mid_x, start_y), (mid_x, end_y)],    fill=conn_color, width=1)
        draw.line([(mid_x, end_y), (end_x, end_y)],      fill=conn_color, width=1)

        # 연결 시작점 작은 점
        dot = 3
        draw.ellipse(
            [start_x - dot, start_y - dot, start_x + dot, start_y + dot],
            fill=(212, 168, 67, 190),
        )

    img.save(png_path, "PNG")
    return png_path


# ─────────────────────────────────────────────────────────────────────────────
# FFmpeg 텍스트 오버레이 필터 (하단 패널, 표시 구간 제한)
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
    """
    하단 패널 텍스트 필터그래프 문자열 반환.
    show_start ~ show_end 구간에만 표시 (fade in/out 0.3초).
    """
    w   = info["w"]
    h   = info["h"]

    # ── 사이즈 ────────────────────────────────────────────────────────────────
    panel_h      = int(h * 0.28)
    panel_y      = h - panel_h
    spine_w      = 4
    margin_l     = spine_w + int(w * 0.04)
    margin_r     = int(w * 0.04)
    font_size_kw = max(38, int(h * 0.038))
    font_size_nr = max(26, int(h * 0.026))
    font_size_lb = max(22, int(h * 0.022))
    font_size_ch = max(20, int(h * 0.020))

    # ── 색상 ─────────────────────────────────────────────────────────────────
    GOLD   = "0xD4A843"
    WHITE  = "0xFFFFFF"
    DARK   = "0x090909@0.82"
    GOLD_A = "0xD4A843@0.90"

    # ── 씬 타입 ──────────────────────────────────────────────────────────────
    scene_type  = _classify_scene_type(scene.get("flow_prompt", ""))
    overlay_kw  = scene.get("overlay_text", "").strip() or scene.get("name", "").strip()
    narration   = scene.get("narration", "").strip()

    # narration 2줄 분할
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

    # ── textfile ─────────────────────────────────────────────────────────────
    tf_kw  = _write_textfile(tmpdir, f"kw_{scene_no:02d}.txt", overlay_kw)
    tf_nr  = _write_textfile(tmpdir, f"nr_{scene_no:02d}.txt", narration_display)
    tf_ch  = _write_textfile(tmpdir, f"ch_{scene_no:02d}.txt", channel_name)
    tf_lb  = _write_textfile(tmpdir, f"lb_{scene_no:02d}.txt", scene_label)
    tf_kp  = _write_textfile(tmpdir, f"kp_{scene_no:02d}.txt", "KEY POINT")

    # ── 페이드 (show_start ~ show_end, 각 0.3초 fade) ────────────────────────
    fd = 0.3
    alpha_expr = (
        f"if(lt(t,{show_start}),0,"
        f"if(lt(t,{show_start + fd}),(t-{show_start})/{fd},"
        f"if(lt(t,{show_end - fd}),1,"
        f"if(lt(t,{show_end}),({show_end}-t)/{fd},0))))"
    )

    def fopt(bold: bool = False) -> str:
        fp = font_bold if (bold and font_bold) else font
        return f"fontfile='{fp}':" if fp else ""

    # ── 좌표 ─────────────────────────────────────────────────────────────────
    prog_h     = 3
    prog_y     = panel_y - prog_h - 2
    prog_w     = int(w * (scene_no / total))

    kp_box_x = margin_l
    kp_box_y = panel_y + int(panel_h * 0.12)
    kp_box_w = int(w * 0.22)
    kp_box_h = font_size_lb + 8
    kw_y     = kp_box_y + kp_box_h + int(h * 0.012)
    nr_y     = panel_y + int(panel_h * 0.62)

    spec_box_x = w - int(w * 0.22) - margin_r
    spec_box_y = int(h * 0.04)
    spec_box_w = int(w * 0.22)
    spec_box_h = font_size_lb + 8

    # ── 필터 조각 ─────────────────────────────────────────────────────────────
    parts = []

    # 하단 다크 패널
    parts.append(f"drawbox=x=0:y={panel_y}:w={w}:h={panel_h}:color={DARK}:t=fill")
    # 황금 스파인
    parts.append(f"drawbox=x=0:y={panel_y}:w={spine_w}:h={panel_h}:color={GOLD_A}:t=fill")
    # 진행 바
    if prog_w > 0:
        parts.append(f"drawbox=x=0:y={prog_y}:w={prog_w}:h={prog_h}:color={GOLD_A}:t=fill")
    # KEY POINT 박스
    parts.append(
        f"drawbox=x={kp_box_x}:y={kp_box_y}:w={kp_box_w}:h={kp_box_h}:color={GOLD_A}:t=fill"
    )
    parts.append(
        f"drawtext={fopt(True)}textfile='{tf_kp}'"
        f":x={kp_box_x + 6}:y={kp_box_y + 4}"
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
            f":w={spec_box_w}:h={spec_box_h}:color={GOLD_A}:t=fill"
        )
        parts.append(
            f"drawtext={fopt(True)}textfile='{tf_sp}'"
            f":x={spec_box_x + int(spec_box_w * 0.25)}:y={spec_box_y + 4}"
            f":fontsize={font_size_lb}:fontcolor=0x0A0A0A:alpha='{alpha_expr}'"
        )

    return ",".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# 씬별 오버레이 적용 (PIL PNG + FFmpeg 텍스트, filter_complex)
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
    """
    단일 클립에 PIL 어노테이션 PNG + FFmpeg 텍스트 오버레이 적용.
    성공 True, 실패 False.
    """
    info = _probe_video(src_path)
    dur  = info["dur"]

    # 오버레이 표시 구간: t=0.8 ~ t=(dur-0.6), 단 최대 3.5초 노출
    show_start = 0.8
    show_end   = min(dur - 0.6, show_start + 3.5)
    if show_end <= show_start + 0.6:
        # 클립이 너무 짧으면 단순 표시
        show_start = 0.2
        show_end   = dur - 0.2

    # PIL 어노테이션 PNG 생성
    ann_png = _generate_annotation_png(scene, info, tmpdir, scene_no)

    # 텍스트 필터그래프
    text_fg = _build_text_filtergraph(
        scene, scene_no, total, info, tmpdir, font, font_bold,
        show_start, show_end,
    )

    # filter_complex 구성
    # [1:v] = 어노테이션 PNG (루프 확장됨)
    ann_fade = (
        f"[1:v]format=rgba,"
        f"fade=t=in:st={show_start}:d=0.3:alpha=1,"
        f"fade=t=out:st={show_end - 0.3}:d=0.3:alpha=1[ann];"
    )
    overlay_chain = f"[0:v][ann]overlay=0:0[base];"
    text_chain    = f"[base]{text_fg}[out]"

    filter_complex = ann_fade + overlay_chain + text_chain

    cmd = (
        ["ffmpeg", "-y",
         "-i", src_path,
         "-loop", "1", "-t", str(dur), "-i", ann_png,
         "-filter_complex", filter_complex,
         "-map", "[out]",
         "-map", "0:a?",
         "-c:v", "libx264", "-preset", "fast", "-crf", "22",
         "-c:a", "copy",
         out_path]
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
    state의 모든 씬 video_url + audio_path → 최종 숏폼 MP4 합성 → fal CDN URL 반환.

    Args:
        state         : 프로젝트 상태 dict (scenes, audio_path 포함)
        fal_key       : FAL_KEY
        apply_overlay : True면 "신비한 건축사전" 오버레이 적용

    Returns:
        str : 최종 영상 fal CDN URL

    Raises:
        ValueError : 합성할 클립이 없거나 FFmpeg 실패 시
    """
    os.environ["FAL_KEY"] = fal_key

    scenes    = state.get("scenes", [])
    audio_src = state.get("audio_path", "").strip()
    total     = len([s for s in scenes if s.get("video_url", "").strip()])

    font      = _find_font(bold=False)
    font_bold = _find_font(bold=True)

    with tempfile.TemporaryDirectory() as tmpdir:

        # ── 1. 비디오 클립 다운로드 ─────────────────────────────────────────
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

        # ── 3. FFmpeg 클립 리스트 파일 ──────────────────────────────────────
        list_file = os.path.join(tmpdir, "clips.txt")
        with open(list_file, "w", encoding="utf-8") as f:
            for p in final_clips:
                escaped = p.replace("\\", "\\\\").replace("'", "\\'")
                f.write(f"file '{escaped}'\n")

        # ── 4. 클립 이어붙이기 ──────────────────────────────────────────────
        concat_path = os.path.join(tmpdir, "concat.mp4")
        proc = subprocess.run(
            ["ffmpeg", "-y",
             "-f", "concat", "-safe", "0",
             "-i", list_file,
             "-c", "copy",
             concat_path],
            capture_output=True,
        )
        if proc.returncode != 0:
            err = proc.stderr.decode(errors="replace")[-1000:]
            raise ValueError(f"FFmpeg concat 실패:\n{err}")

        # ── 5. 비디오 정확한 길이 확인 ──────────────────────────────────────
        video_dur_info = _probe_video(concat_path)
        video_dur      = video_dur_info["dur"]

        # ── 6. 나레이션 오디오 준비 ─────────────────────────────────────────
        audio_path = ""
        if audio_src:
            audio_path = os.path.join(tmpdir, "narration.mp3")
            if not _copy_or_download(audio_src, audio_path):
                audio_path = ""

        # ── 7. 오디오 합성 ──────────────────────────────────────────────────
        #    apad: 오디오가 영상보다 짧을 때 무음으로 패딩
        #    -t video_dur: 정확히 영상 길이에 맞춰 컷 (엔딩 컷 방지)
        final_path = os.path.join(tmpdir, "final.mp4")

        if audio_path and os.path.exists(audio_path):
            proc = subprocess.run(
                ["ffmpeg", "-y",
                 "-i", concat_path,
                 "-i", audio_path,
                 "-c:v", "copy",
                 "-c:a", "aac", "-b:a", "128k",
                 "-map", "0:v:0",
                 "-map", "1:a:0",
                 "-af", "apad",          # 오디오 짧으면 무음 패딩
                 "-t", str(video_dur),   # 영상 길이에 맞춰 정확히 컷
                 final_path],
                capture_output=True,
            )
            if proc.returncode != 0:
                err = proc.stderr.decode(errors="replace")[-1000:]
                raise ValueError(f"FFmpeg 오디오 합성 실패:\n{err}")
        else:
            shutil.copy2(concat_path, final_path)

        # ── 8. fal.ai CDN 업로드 ────────────────────────────────────────────
        with open(final_path, "rb") as f:
            video_bytes = f.read()

        cdn_url = fal_client.upload(video_bytes, content_type="video/mp4")
        return cdn_url
