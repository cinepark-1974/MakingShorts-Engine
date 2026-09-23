# src/assembler.py
# 너도나도아는커피 숏폼 팩토리 — FFmpeg 최종 합성기 (v4)
#
# v4 변경 (2026-09-23)
#   1) 길이: MiniMax 클립은 6초 고정이라 12컷 ≈ 70초. 나레이션(80초 이상)이 잘리던 문제 수정.
#      → 나레이션 전체 길이를 씬별 대사 분량 비율로 나눠 각 컷 길이를 정하고,
#        모자란 컷은 슬로모션(최대 1.35배) + 마지막 프레임 유지로 늘린다. 나레이션이 끝까지 들어간다.
#   2) 박스 제거: 하단 검은 패널, KEY POINT 박스, 진행 바 박스를 모두 없앴다.
#      자막은 박스 없이 외곽선 + 그림자만으로 읽히게 한다.
#   3) 신비한 건축사전 톤 복구: 씬별 과학 데이터(SPEC)와 지시선 라벨(callouts)을
#      펜 선처럼 얇은 골드 라인으로 그림 위에 얹는다. 박스 없음.
#   4) 9:16 보정: 어떤 비율의 클립이 와도 1080×1920 으로 꽉 채워 중앙 크롭한다.
#
# 모든 그래픽(자막·라벨·데이터)은 PIL 로 투명 PNG 한 장에 그린 뒤 FFmpeg 로 얹는다.
# (drawtext 이스케이프 문제·박스 잔상 문제를 원천 차단)

import os
import re
import json
import shutil
import subprocess
import tempfile
import requests

W, H, FPS = 1080, 1920, 30
MAX_SLOW   = 1.35      # 슬로모션 최대 배율 (이보다 더 필요하면 마지막 프레임 유지)
MIN_SCENE  = 1.8       # 컷 최소 길이 (초)
TAIL_SEC   = 0.8       # 나레이션 끝난 뒤 여운

ILLUSTRATION_TYPES = {"MACHINE", "EXTRACTION", "SCIENCE_DATA"}

# ─────────────────────────────────────────────────────────────────────────────
# 색상 / 폰트
# ─────────────────────────────────────────────────────────────────────────────
GOLD      = (214, 170, 72, 255)
GOLD_SOFT = (214, 170, 72, 170)
CREAM     = (250, 244, 230, 255)
INK       = (18, 14, 10, 255)       # 외곽선

# 배경 밝기에 따라 두 가지 인쇄 톤을 쓴다.
#  - 어두운 실사 컷: 크림색 글자 + 짙은 외곽선
#  - 밝은 종이 스케치 컷: 도감처럼 짙은 잉크 글자 + 얇은 종이색 테두리
PALETTES = {
    "dark": {"text": CREAM, "accent": GOLD, "line": GOLD, "line_soft": GOLD_SOFT,
             "stroke": INK, "shadow": True, "sw": 1.0},
    "light": {"text": (38, 26, 16, 255), "accent": (150, 98, 28, 255),
              "line": (120, 78, 24, 255), "line_soft": (120, 78, 24, 150),
              "stroke": (247, 240, 225, 235), "shadow": False, "sw": 0.8},
}

_FONT_DIRS = ["/usr/share/fonts/truetype/nanum", "/usr/share/fonts/nanum"]


def _font_path(names):
    for d in _FONT_DIRS:
        for n in names:
            p = os.path.join(d, n)
            if os.path.exists(p):
                return p
    return ""


FONT_SANS_BOLD  = _font_path(["NanumBarunGothicBold.ttf", "NanumGothicBold.ttf", "NanumGothic.ttf"])
FONT_SANS       = _font_path(["NanumBarunGothic.ttf", "NanumGothic.ttf"])
FONT_SERIF_BOLD = _font_path(["NanumMyeongjoBold.ttf", "NanumMyeongjo.ttf"]) or FONT_SANS_BOLD


def _font(path, size):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(path, size) if path else ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()


# ─────────────────────────────────────────────────────────────────────────────
# 파일 / ffprobe 헬퍼
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


def _media_duration(path: str) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path],
            capture_output=True,
        )
        return float(json.loads(r.stdout.decode())["format"]["duration"])
    except Exception:
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 씬 타입 / 데이터 추출
# ─────────────────────────────────────────────────────────────────────────────
_TYPE_KEYWORDS = {
    "SCIENCE_DATA": ["science", "data", "ratio", "temperature", "pressure", "compare", "side by side", "beaker"],
    "EXTRACTION":   ["extraction", "crema", "stream", "pour", "brew", "drip"],
    "MACHINE":      ["machine", "cutaway", "cross-section", "component", "mechanism", "portafilter"],
}


def _scene_type(scene: dict) -> str:
    st = (scene.get("scene_type") or "").strip().upper()
    if st:
        return st
    p = (scene.get("flow_prompt", "") + " " + scene.get("image_prompt", "")).lower()
    for t, kws in _TYPE_KEYWORDS.items():
        if any(k in p for k in kws):
            return t
    return "CINEMATIC"


def _extract_data_from_narration(narration: str) -> list:
    """data_points 가 없는 옛 대본용 — 나레이션에서 수치를 찾아 [{label, value}] 로 반환."""
    rules = [
        (r"pH\s*(\d+(?:\.\d+)?)",                         lambda m: ("pH", m.group(1))),
        (r"(\d+(?:\.\d+)?)\s*(?:mg|밀리그램)",            lambda m: ("카페인" if "카페인" in narration else "함량", f"{m.group(1)}mg")),
        (r"(\d+(?:\.\d+)?)\s*(?:°C|℃|도씨|도\b)",         lambda m: ("온도", f"{m.group(1)}°C")),
        (r"(\d+(?:\.\d+)?)\s*(?:bar|바|기압)",            lambda m: ("압력", f"{m.group(1)} bar")),
        (r"(\d+(?:\.\d+)?)\s*(?:ml|mL|밀리리터)",          lambda m: ("용량", f"{m.group(1)}ml")),
        (r"(\d+(?:\.\d+)?)\s*(?:g|그램)\b",               lambda m: ("무게", f"{m.group(1)}g")),
        (r"(\d+(?:\.\d+)?)\s*초",                          lambda m: ("시간", f"{m.group(1)}초")),
        (r"(\d+(?:\.\d+)?)\s*%",                           lambda m: ("비율", f"{m.group(1)}%")),
        (r"(\d+)\s*(?:대|:)\s*(\d+)",                      lambda m: ("비율", f"{m.group(1)} : {m.group(2)}")),
    ]
    out, seen = [], set()
    for pat, fn in rules:
        for m in re.finditer(pat, narration):
            label, value = fn(m)
            if value in seen:
                continue
            seen.add(value)
            out.append({"label": label, "value": value})
            if len(out) >= 3:
                return out
    return out


def _data_points(scene: dict) -> list:
    dp = scene.get("data_points")
    if isinstance(dp, list) and dp:
        clean = []
        for d in dp[:3]:
            if isinstance(d, dict) and str(d.get("value", "")).strip():
                clean.append({"label": str(d.get("label", "")).strip(),
                              "value": str(d.get("value", "")).strip()})
        if clean:
            return clean
    return _extract_data_from_narration(scene.get("narration", ""))


def _callouts(scene: dict) -> list:
    out = []
    for c in (scene.get("callouts") or [])[:4]:
        try:
            text = str(c.get("text", "")).strip()
            x, y = float(c.get("x")), float(c.get("y"))
        except Exception:
            continue
        if text and 0 <= x <= 1 and 0 <= y <= 1:
            out.append({"text": text, "x": x, "y": y})
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 텍스트 유틸
# ─────────────────────────────────────────────────────────────────────────────
def _wrap(draw, text: str, font, max_w: int, max_lines: int = 2) -> list:
    """띄어쓰기 기준 줄바꿈 (한글 어절 유지). 넘치면 글자 단위로 자른다."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=font) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
            while draw.textlength(cur, font=font) > max_w and len(cur) > 1:   # 아주 긴 어절
                cut = len(cur)
                while cut > 1 and draw.textlength(cur[:cut], font=font) > max_w:
                    cut -= 1
                lines.append(cur[:cut])
                cur = cur[cut:]
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip() + "…"
    return lines


_PAL = PALETTES["dark"]   # render_overlay_png 가 컷마다 교체


def _text(draw, xy, text, font, fill=None, stroke=5, anchor="la", shadow=None):
    x, y = xy
    fill = fill or _PAL["text"]
    sw = max(2, int(round(stroke * _PAL["sw"])))
    if _PAL["shadow"] if shadow is None else shadow:
        draw.text((x + 3, y + 4), text, font=font, fill=(0, 0, 0, 110), anchor=anchor,
                  stroke_width=sw, stroke_fill=(0, 0, 0, 110))
    draw.text((x, y), text, font=font, fill=fill, anchor=anchor,
              stroke_width=sw, stroke_fill=_PAL["stroke"])


# ─────────────────────────────────────────────────────────────────────────────
# 씬 오버레이 PNG (신비한 건축사전 스타일, 박스 없음)
# ─────────────────────────────────────────────────────────────────────────────
def render_overlay_png(scene: dict, scene_no: int, total: int, out_path: str,
                       light: bool = False) -> str:
    """light=True 이면 밝은 종이 배경용 잉크 톤으로 그린다."""
    from PIL import Image, ImageDraw
    global _PAL
    _PAL = PALETTES["light" if light else "dark"]
    GOLD, GOLD_SOFT, CREAM = _PAL["line"], _PAL["line_soft"], _PAL["text"]
    ACCENT = _PAL["accent"]

    img  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d    = ImageDraw.Draw(img)
    stype = _scene_type(scene)
    is_illust = stype in ILLUSTRATION_TYPES
    m = 56                                           # 외곽 여백

    # ── 1. 코너 브래킷 (도면 프레임) ──────────────────────────────────────
    L = 70
    for cx, cy, dx, dy in [(m, m, 1, 1), (W - m, m, -1, 1),
                           (m, int(H * 0.60), 1, -1), (W - m, int(H * 0.60), -1, -1)]:
        d.line([(cx, cy), (cx + dx * L, cy)], fill=GOLD_SOFT, width=3)
        d.line([(cx, cy), (cx, cy + dy * L)], fill=GOLD_SOFT, width=3)

    # ── 2. 헤더: 채널명 / 도판 번호 ──────────────────────────────────────
    f_head = _font(FONT_SANS_BOLD, 30)
    _text(d, (m + 8, m + 18), "너도나도아는커피", f_head, fill=ACCENT, stroke=3)
    plate = f"PLATE {scene_no:02d} / {total:02d}"
    _text(d, (W - m - 8, m + 18), plate, f_head, fill=CREAM, stroke=3, anchor="ra")

    # ── 3. 데이터 SPEC (우상단, 박스 없이 헤어라인만) ─────────────────────
    data = _data_points(scene)
    if data:
        f_lab = _font(FONT_SANS_BOLD, 30)
        f_val = _font(FONT_SERIF_BOLD, 64)
        x_r   = W - m - 8
        y     = m + 90
        rule_top = y
        for dp in data:
            if dp["label"]:
                _text(d, (x_r, y), dp["label"], f_lab, fill=ACCENT, stroke=3, anchor="ra")
                y += 40
            _text(d, (x_r, y), dp["value"], f_val, fill=CREAM, stroke=5, anchor="ra")
            y += 84
        # 오른쪽 세로 헤어라인 (도면 치수선 느낌)
        d.line([(W - m + 14, rule_top), (W - m + 14, y - 12)], fill=GOLD_SOFT, width=2)
        for ty in (rule_top, y - 12):
            d.line([(W - m + 4, ty), (W - m + 24, ty)], fill=GOLD_SOFT, width=2)

    # ── 4. 지시선 라벨 (callouts) ────────────────────────────────────────
    callouts = _callouts(scene)
    if callouts:
        f_co = _font(FONT_SERIF_BOLD, 40)
        y_min, y_max, gap = int(H * 0.16), int(H * 0.56), 92
        placed = {"L": [], "R": []}
        for c in sorted(callouts, key=lambda c: c["y"]):
            side = "L" if c["x"] < 0.5 else "R"
            ax, ay = int(c["x"] * W), int(c["y"] * H)
            ay = max(y_min, min(y_max, ay))
            ly = ay
            for py in placed[side]:
                if abs(ly - py) < gap:
                    ly = py + gap
            ly = min(ly, y_max)
            placed[side].append(ly)

            # 앵커 점 + 링
            d.ellipse([ax - 7, ay - 7, ax + 7, ay + 7], fill=GOLD)
            d.ellipse([ax - 18, ay - 18, ax + 18, ay + 18], outline=GOLD_SOFT, width=2)
            # 꺾인 지시선 → 라벨
            tw = int(d.textlength(c["text"], font=f_co))
            # 앵커가 여백 라벨 자리와 겹치면: 라벨을 앵커 바로 위에 올리고 짧은 세로 지시선
            crowded = (side == "L" and ax - 18 < m + 20 + tw + 40) or                       (side == "R" and ax + 18 > W - m - 20 - tw - 40)
            if crowded:
                lx = max(m + 20 + tw // 2, min(W - m - 20 - tw // 2, ax))
                ty = ay - 78
                d.line([(ax, ay - 18), (ax, ty + 12)], fill=GOLD, width=3)
                d.line([(lx - tw // 2, ty + 12), (lx + tw // 2, ty + 12)], fill=GOLD_SOFT, width=2)
                _text(d, (lx, ty + 4), c["text"], f_co, stroke=4, anchor="ms")
                continue
            if side == "L":
                ex = m + 20 + tw + 16
                d.line([(ax - 18, ay), (ex + 40, ay), (ex, ly)] if ly != ay else [(ax - 18, ay), (ex, ly)],
                       fill=GOLD, width=3, joint="curve")
                d.line([(m + 20, ly + 30), (ex, ly + 30)], fill=GOLD_SOFT, width=2)
                _text(d, (m + 20, ly + 22), c["text"], f_co, fill=CREAM, stroke=4, anchor="ls")
            else:
                sx = W - m - 20 - tw - 16
                d.line([(ax + 18, ay), (sx - 40, ay), (sx, ly)] if ly != ay else [(ax + 18, ay), (sx, ly)],
                       fill=GOLD, width=3, joint="curve")
                d.line([(sx, ly + 30), (W - m - 20, ly + 30)], fill=GOLD_SOFT, width=2)
                _text(d, (W - m - 20, ly + 22), c["text"], f_co, fill=CREAM, stroke=4, anchor="rs")
    elif is_illust and not data:
        # 라벨·데이터가 전혀 없을 때만 조준 링 (빈 도판 방지)
        fx, fy = W // 2, int(H * 0.38)
        for r, a in [(22, 190), (40, 110), (64, 60)]:
            d.ellipse([fx - r, fy - r, fx + r, fy + r], outline=GOLD[:3] + (a,), width=2)

    # ── 5. 키워드 (명조, 박스 없음) ──────────────────────────────────────
    kw = (scene.get("overlay_text") or "").strip()
    y_sub = int(H * 0.755)
    if kw:
        f_kw = _font(FONT_SERIF_BOLD, 76)
        kw_lines = _wrap(d, kw, f_kw, W - 2 * m - 40, max_lines=2)
        ky = int(H * 0.645) - (len(kw_lines) - 1) * 88
        d.line([(m + 20, ky - 26), (m + 120, ky - 26)], fill=GOLD, width=4)   # 짧은 골드 룰
        for i, line in enumerate(kw_lines):
            _text(d, (m + 20, ky + i * 88), line, f_kw, fill=ACCENT, stroke=6, anchor="la")

    # ── 6. 나레이션 자막 (박스 없음, 외곽선) ─────────────────────────────
    narr = (scene.get("narration") or "").strip()
    if narr:
        f_sub = _font(FONT_SANS_BOLD, 58)
        lines = _wrap(d, narr, f_sub, W - 2 * m - 40, max_lines=3)
        for i, line in enumerate(lines):
            _text(d, (W // 2, y_sub + i * 76), line, f_sub, fill=CREAM, stroke=7, anchor="ma")

    img.save(out_path, "PNG")
    return out_path


def _is_light_clip(path: str, tmpdir: str) -> bool:
    """클립 중간 프레임의 평균 밝기로 '밝은 종이 배경' 여부를 판단한다."""
    frame = os.path.join(tmpdir, "probe_frame.png")
    try:
        mid = max(0.1, (_media_duration(path) or 6.0) / 2)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{mid:.2f}", "-i", path,
                        "-frames:v", "1", "-vf", "scale=90:160", frame], capture_output=True)
        from PIL import Image
        g = Image.open(frame).convert("L")
        return (sum(g.getdata()) / (g.width * g.height)) > 150
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 길이 배분
# ─────────────────────────────────────────────────────────────────────────────
def plan_durations(scenes: list, clip_durs: list, audio_dur: float) -> list:
    """나레이션 분량 비율로 컷 길이를 나눈다. 오디오가 없으면 원본 클립 길이 그대로."""
    if audio_dur <= 0:
        return list(clip_durs)
    total = audio_dur + TAIL_SEC
    weights = [max(len(re.sub(r"\s", "", s.get("narration", ""))), 6) for s in scenes]
    durs = [total * w / sum(weights) for w in weights]
    # 최소 길이 보장 후 나머지 재분배
    for _ in range(3):
        short = [i for i, x in enumerate(durs) if x < MIN_SCENE]
        if not short:
            break
        deficit = sum(MIN_SCENE - durs[i] for i in short)
        for i in short:
            durs[i] = MIN_SCENE
        rest = [i for i in range(len(durs)) if i not in short]
        rest_sum = sum(durs[i] for i in rest) or 1
        for i in rest:
            durs[i] -= deficit * durs[i] / rest_sum
    return [round(x, 3) for x in durs]


# ─────────────────────────────────────────────────────────────────────────────
# 컷 하나 렌더링: 9:16 크롭 → 길이 맞춤 → 오버레이
# ─────────────────────────────────────────────────────────────────────────────
def render_scene_clip(src: str, overlay_png: str, target: float, out_path: str) -> None:
    src_dur = _media_duration(src) or 6.0
    chain = [
        f"scale={W}:{H}:force_original_aspect_ratio=increase",
        f"crop={W}:{H}",
        "setsar=1",
        f"fps={FPS}",
        "setpts=PTS-STARTPTS",
    ]
    if target > src_dur:
        slow = min(target / src_dur, MAX_SLOW)
        chain.append(f"setpts={slow:.4f}*PTS")
        remain = target - src_dur * slow
        if remain > 0.02:
            chain.append(f"tpad=stop_mode=clone:stop_duration={remain:.3f}")
    fade_in = 0.35
    fc = (
        f"[0:v]{','.join(chain)}[base];"
        f"[1:v]format=rgba,fade=t=in:st=0.15:d={fade_in}:alpha=1[ov];"
        f"[base][ov]overlay=0:0:format=auto,format=yuv420p[out]"
    )
    cmd = [
        "ffmpeg", "-y", "-i", src,
        "-loop", "1", "-framerate", str(FPS), "-t", f"{target:.3f}", "-i", overlay_png,
        "-filter_complex", fc, "-map", "[out]", "-an",
        "-t", f"{target:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-r", str(FPS), "-pix_fmt", "yuv420p",
        out_path,
    ]
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0:
        raise ValueError(f"컷 렌더링 실패: {p.stderr.decode(errors='replace')[-800:]}")


# ─────────────────────────────────────────────────────────────────────────────
# 공개 API
# ─────────────────────────────────────────────────────────────────────────────
def assemble_final_video(state: dict, fal_key: str = "", apply_overlay: bool = True) -> str:
    """
    모든 컷 영상 + 나레이션 → 1080×1920 최종 MP4 (project_dir/final.mp4) 경로 반환.
    나레이션은 끝까지 들어가고, 영상 길이는 나레이션 + 여운 0.8초.
    """
    scenes    = sorted(state.get("scenes", []), key=lambda s: s.get("scene_no", 0))
    audio_src = (state.get("audio_path") or "").strip()

    with tempfile.TemporaryDirectory() as tmp:
        # 1. 클립 확보
        items = []
        for s in scenes:
            url = (s.get("video_url") or "").strip()
            if not url:
                continue
            p = os.path.join(tmp, f"clip_{s.get('scene_no', 0):02d}.mp4")
            if _copy_or_download(url, p):
                items.append((s, p))
        if not items:
            raise ValueError("합성할 영상 클립이 없습니다. STEP 4에서 컷 영상을 먼저 생성해 주세요.")

        # 2. 나레이션 길이 → 컷별 목표 길이
        audio_path = ""
        if audio_src:
            audio_path = os.path.join(tmp, "narration.mp3")
            if not _copy_or_download(audio_src, audio_path):
                audio_path = ""
        audio_dur = _media_duration(audio_path) if audio_path else 0.0
        clip_durs = [_media_duration(p) or 6.0 for _, p in items]
        targets   = plan_durations([s for s, _ in items], clip_durs, audio_dur)
        print(f"[assembler] 나레이션 {audio_dur:.1f}초 · 원본 클립 합 {sum(clip_durs):.1f}초 "
              f"→ 최종 {sum(targets):.1f}초", flush=True)

        # 3. 컷별 렌더링
        total = len(items)
        rendered = []
        for i, ((s, p), tgt) in enumerate(zip(items, targets), start=1):
            sno = s.get("scene_no", i)
            png = os.path.join(tmp, f"ov_{sno:02d}.png")
            if apply_overlay:
                render_overlay_png(s, sno, total, png, light=_is_light_clip(p, tmp))
            else:
                from PIL import Image
                Image.new("RGBA", (W, H), (0, 0, 0, 0)).save(png)
            out = os.path.join(tmp, f"r_{sno:02d}.mp4")
            render_scene_clip(p, png, tgt, out)
            rendered.append(out)
            print(f"[assembler] 컷 #{sno:02d} {tgt:.1f}초 완료", flush=True)

        # 4. 이어붙이기 (모든 컷이 같은 규격이라 재인코딩 없이 연결)
        lst = os.path.join(tmp, "list.txt")
        with open(lst, "w", encoding="utf-8") as f:
            for r in rendered:
                f.write(f"file '{r}'\n")
        concat = os.path.join(tmp, "concat.mp4")
        p = subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                            "-c", "copy", concat], capture_output=True)
        if p.returncode != 0:
            raise ValueError(f"FFmpeg concat 실패:\n{p.stderr.decode(errors='replace')[-800:]}")
        video_dur = _media_duration(concat)

        # 5. 나레이션 합치기 (끝까지 들어가도록 영상 길이 기준 + 무음 패딩)
        final = os.path.join(tmp, "final.mp4")
        if audio_path:
            p = subprocess.run(
                ["ffmpeg", "-y", "-i", concat, "-i", audio_path,
                 "-map", "0:v:0", "-map", "1:a:0",
                 "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                 "-af", "apad", "-t", f"{video_dur:.3f}",
                 "-movflags", "+faststart", final],
                capture_output=True,
            )
            if p.returncode != 0:
                raise ValueError(f"FFmpeg 오디오 합성 실패:\n{p.stderr.decode(errors='replace')[-800:]}")
        else:
            shutil.copy2(concat, final)

        project_dir = state.get("project_dir", "/tmp")
        os.makedirs(project_dir, exist_ok=True)
        dest = os.path.join(project_dir, "final.mp4")
        shutil.copy2(final, dest)
        return dest
