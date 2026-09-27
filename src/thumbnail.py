# src/thumbnail.py
# 너도나도아는커피 숏폼 팩토리 — 9:16 섬네일 (1080×1920 PNG)
#
# 구성
#   배경  : 이 프로젝트의 스케치 도판 이미지 1장 (없으면 최종 영상의 한 장면)
#   문구  : Claude 가 대본을 읽고 두 줄 훅 문구를 만든다 (강조 단어 1개는 골드)
#   브랜드: 채널명 + 도판 코너 브래킷 — 영상 오버레이와 같은 톤
#   배치  : Shorts 피드에서 아래쪽은 제목·버튼에 가려지므로 문구는 위쪽 1/3 에 둔다
#
# 박스는 쓰지 않는다. 글자 외곽선으로만 읽히게 하고, 어두운 배경일 때만 위쪽에 옅은 그라데이션.

import json
import os
import re
import subprocess

W, H = 1080, 1920
ILLUST_TYPES = {"SCIENCE_DATA", "EXTRACTION", "MACHINE"}
CHANNEL = "너도나도아는커피"

_FONT_DIRS = ["/usr/share/fonts/truetype/nanum", "/usr/share/fonts/nanum"]


def _font_path(names):
    for d in _FONT_DIRS:
        for n in names:
            p = os.path.join(d, n)
            if os.path.exists(p):
                return p
    return ""


FONT_HEAD = _font_path(["NanumSquareB.ttf", "NanumBarunGothicBold.ttf", "NanumGothicBold.ttf"])
FONT_SUB  = _font_path(["NanumBarunGothicBold.ttf", "NanumGothicBold.ttf", "NanumGothic.ttf"])


def _font(path, size):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(path, size) if path else ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()


# ─────────────────────────────────────────────────────────────────────────────
# 1) 배경 고르기
# ─────────────────────────────────────────────────────────────────────────────
def _usable(p: str) -> bool:
    return bool(p) and os.path.exists(p) and os.path.getsize(p) > 0


def pick_background(state: dict, work_dir: str) -> str:
    scenes = state.get("scenes", [])
    # 스케치 도판 우선 → 다른 로컬 이미지
    for want_illust in (True, False):
        for sc in scenes:
            if want_illust and sc.get("scene_type") not in ILLUST_TYPES:
                continue
            if _usable(sc.get("image_local", "")):
                return sc["image_local"]
    # 최종 영상에서 스케치 컷 중간 장면 한 장
    final = state.get("final_video_path", "")
    if _usable(final):
        out = os.path.join(work_dir, "thumb_bg.png")
        t = 4.0
        try:
            r = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", final],
                               capture_output=True)
            dur = float(json.loads(r.stdout.decode())["format"]["duration"])
            t = max(1.0, dur * 0.22)
        except Exception:
            pass
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", final,
                        "-frames:v", "1", out], capture_output=True)
        if _usable(out):
            return out
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# 2) 문구 만들기 (Claude)
# ─────────────────────────────────────────────────────────────────────────────
COPY_SYSTEM = """당신은 유튜브 쇼츠 섬네일 카피라이터입니다. 채널: 너도나도아는커피 (커피 과학 해설).
대본을 읽고 섬네일 문구를 만듭니다. 규칙:
- line1, line2: 두 줄 훅. 각 줄 공백 포함 9자 이내. 호기심을 일으키되 대본에 있는 사실만.
- accent: line1 또는 line2 안에 그대로 들어 있는 단어 하나 (골드로 강조).
- sub: 주제를 설명하는 한 줄, 16자 이내.
- 물음표·느낌표는 한 번까지. 이모지 금지.
JSON 만 출력: {"line1": "", "line2": "", "accent": "", "sub": ""}"""


def fallback_copy(state: dict) -> dict:
    topic = (state.get("topic") or "").strip()
    first = (state.get("scenes") or [{}])[0].get("overlay_text", "") or topic
    words = first.split()
    half = max(1, len(words) // 2)
    l1 = " ".join(words[:half]) or first[:9]
    l2 = " ".join(words[half:]) or ""
    sub = ""
    for w in topic.split():                     # 16자 안에서 어절 단위로 자르기
        if len((sub + " " + w).strip()) > 16:
            break
        sub = (sub + " " + w).strip()
    accent = max(words, key=len) if words else ""
    return {"line1": l1, "line2": l2, "accent": accent, "sub": sub or topic[:16]}


def make_copy(api_key: str, state: dict) -> dict:
    if not api_key:
        return fallback_copy(state)
    try:
        import anthropic
        narr = " ".join((s.get("narration") or "") for s in state.get("scenes", []))
        user = f"주제: {state.get('topic', '')}\n\n대본:\n{narr}"
        resp = anthropic.Anthropic(api_key=api_key).messages.create(
            model="claude-sonnet-4-6", max_tokens=400, system=COPY_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        raw = "".join(getattr(b, "text", "") for b in resp.content)
        data = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
        if not data.get("line1"):
            raise ValueError("line1 없음")
        return {k: str(data.get(k, "")).strip() for k in ("line1", "line2", "accent", "sub")}
    except Exception as e:
        print(f"[thumbnail] 문구 생성 실패 → 기본 문구: {e}", flush=True)
        return fallback_copy(state)


# ─────────────────────────────────────────────────────────────────────────────
# 3) 그리기
# ─────────────────────────────────────────────────────────────────────────────
def _cover(img, w, h):
    from PIL import Image
    r = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * r + 0.5), int(img.height * r + 0.5)), Image.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


def _fit(draw, text, path, start, min_size, max_w):
    size = start
    f = _font(path, size)
    while size > min_size and draw.textlength(text, font=f) > max_w:
        size -= 4
        f = _font(path, size)
    return f


def _draw_line(draw, y, text, accent, font, fill, accent_fill, stroke, stroke_fill):
    """가운데 정렬 한 줄. accent 단어만 다른 색."""
    parts = [text]
    if accent and accent in text:
        i = text.index(accent)
        parts = [text[:i], accent, text[i + len(accent):]]
    total = sum(draw.textlength(p, font=font) for p in parts)
    x = (W - total) / 2
    for k, p in enumerate(parts):
        if not p:
            continue
        color = accent_fill if (len(parts) == 3 and k == 1) else fill
        draw.text((x, y), p, font=font, fill=color, stroke_width=stroke, stroke_fill=stroke_fill)
        x += draw.textlength(p, font=font)


def render_thumbnail(bg_path: str, copy: dict, out_path: str) -> str:
    from PIL import Image, ImageDraw

    if _usable(bg_path):
        base = _cover(Image.open(bg_path).convert("RGB"), W, H).convert("RGBA")
    else:
        base = Image.new("RGBA", (W, H), (238, 230, 214, 255))

    # 위쪽 1/3 밝기로 인쇄 톤 결정 (영상 오버레이와 같은 규칙)
    top = base.crop((0, 0, W, H // 3)).convert("L").resize((60, 60))
    light = (sum(top.getdata()) / 3600) > 150
    if light:
        fill, accent, stroke_fill = (38, 26, 16, 255), (160, 96, 20, 255), (248, 242, 228, 255)
        line_c = (120, 78, 24, 220)
    else:
        fill, accent, stroke_fill = (250, 244, 230, 255), (226, 176, 70, 255), (14, 10, 8, 255)
        line_c = (214, 170, 72, 220)
        # 어두운 배경만: 위쪽 옅은 그라데이션 (박스 아님)
        grad = Image.new("L", (1, H // 2))
        for yy in range(H // 2):
            grad.putpixel((0, yy), int(150 * (1 - yy / (H // 2)) ** 1.6))
        shade = Image.new("RGBA", (W, H // 2), (0, 0, 0, 255))
        shade.putalpha(grad.resize((W, H // 2)))
        base.alpha_composite(shade, (0, 0))

    d = ImageDraw.Draw(base)
    m = 60

    # 도판 코너 브래킷
    L = 90
    for cx, cy, dx, dy in [(m, m, 1, 1), (W - m, m, -1, 1), (m, H - m, 1, -1), (W - m, H - m, -1, -1)]:
        d.line([(cx, cy), (cx + dx * L, cy)], fill=line_c, width=5)
        d.line([(cx, cy), (cx, cy + dy * L)], fill=line_c, width=5)

    # 채널명
    f_ch = _font(FONT_SUB, 44)
    d.text((W / 2 - d.textlength(CHANNEL, font=f_ch) / 2, 150), CHANNEL, font=f_ch,
           fill=accent, stroke_width=4, stroke_fill=stroke_fill)

    # 두 줄 헤드라인 (같은 크기로 맞춤)
    l1, l2 = copy.get("line1", ""), copy.get("line2", "")
    longest = max([l1, l2], key=len) if (l1 or l2) else ""
    f_head = _fit(d, longest, FONT_HEAD, 190, 96, W - 2 * m - 40)
    lh = int(f_head.size * 1.18)
    y = 260
    for line in (l1, l2):
        if line:
            _draw_line(d, y, line, copy.get("accent", ""), f_head, fill, accent,
                       max(8, f_head.size // 14), stroke_fill)
            y += lh

    # 서브 문구 + 짧은 룰
    sub = copy.get("sub", "")
    if sub:
        y += 16
        d.line([(W / 2 - 70, y), (W / 2 + 70, y)], fill=line_c, width=4)
        f_sub = _fit(d, sub, FONT_SUB, 64, 40, W - 2 * m - 80)
        d.text((W / 2 - d.textlength(sub, font=f_sub) / 2, y + 26), sub, font=f_sub,
               fill=fill, stroke_width=5, stroke_fill=stroke_fill)

    base.convert("RGB").save(out_path, "PNG")
    return out_path


def create_thumbnail(state: dict, api_key: str = "", copy: dict = None) -> tuple:
    """(섬네일 경로, 사용한 문구) — project_dir/thumbnail.png 에 저장."""
    project_dir = state.get("project_dir", "projects/tmp")
    os.makedirs(project_dir, exist_ok=True)
    bg = pick_background(state, project_dir)
    copy = copy or make_copy(api_key, state)
    out = os.path.join(project_dir, "thumbnail.png")
    render_thumbnail(bg, copy, out)
    return out, copy
