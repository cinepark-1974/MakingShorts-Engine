# src/thumbnail.py
# 너도나도아는커피 숏폼 팩토리 — 9:16 섬네일 (1080×1920 PNG), 매 편 같은 틀
#
# 왜 이 배치인가 (채널 화면 캡처로 확인한 것):
#   - 채널 화면의 격자 칸은 9:16 의 위아래 약 10% 를 잘라낸다 → 맨 위 문구가 반쯤 잘렸다
#   - 칸 아래쪽 약 1/3 은 YouTube 가 제목·조회수 글자로 덮는다 → 아래 로고가 읽히지 않았다
#   그래서 꼭 읽혀야 할 글자는 위에서 13%~34% 높이(250~650px)에만 둔다.
#   그림은 그 아래(560px~)에 넣고, 가장자리를 종이색으로 번지게 해서 한 장처럼 보이게 한다.
#
# 틀(매 편 동일):
#   [종이색 바탕] 채널명(작게) → 두 줄 헤드라인(남색, 강조 단어 1개는 커피색) → 그림
#   어두운 그림(훅 히어로샷)이면 바탕이 검정이 되고 글자는 크림색·금색으로 바뀐다.

import os

W, H = 1080, 1920
TEXT_TOP = 250          # 채널명 y
HEAD_TOP = 330          # 헤드라인 첫 줄 y
IMG_TOP = 560           # 그림 윗변 y
MARGIN = 70
FEATHER = 90            # 그림 가장자리 번짐(px)

ILLUST_TYPES = {"SCIENCE_DATA", "EXTRACTION", "MACHINE"}
_FONT_DIRS = ["/usr/share/fonts/truetype/nanum", "/usr/share/fonts/nanum"]


def _font_path(names):
    for d in _FONT_DIRS:
        for n in names:
            p = os.path.join(d, n)
            if os.path.exists(p):
                return p
    return ""


FONT_HEAD = _font_path(["NanumSquareB.ttf", "NanumBarunGothicBold.ttf", "NanumGothicBold.ttf"])
FONT_SUB = _font_path(["NanumBarunGothicBold.ttf", "NanumGothicBold.ttf", "NanumGothic.ttf"])


def _font(path, size):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(path, size) if path else ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()


def _usable(p: str) -> bool:
    return bool(p) and os.path.exists(p) and os.path.getsize(p) > 0


# ─────────────────────────────────────────────────────────────────────────────
# 배경 후보 — 화면에서 고를 수 있게 목록으로 돌려준다
# ─────────────────────────────────────────────────────────────────────────────
def background_candidates(state: dict) -> list:
    """[(라벨, 로컬 경로)] — 스케치 도판을 앞에, 그다음 나머지 컷."""
    illust, others = [], []
    for sc in state.get("scenes", []):
        p = sc.get("image_local", "")
        if not _usable(p):
            continue
        n = int(sc.get("scene_no", 0) or 0)
        kind = "스케치" if sc.get("scene_type") in ILLUST_TYPES else "사진"
        label = f"#{n:02d} {kind} · {(sc.get('overlay_text') or sc.get('name') or '')[:14]}"
        (illust if kind == "스케치" else others).append((label, p))
    return illust + others


# ─────────────────────────────────────────────────────────────────────────────
# 그리기
# ─────────────────────────────────────────────────────────────────────────────
def _edge_color(img):
    """그림 테두리의 중앙값 색 = 바탕 종이색."""
    from PIL import ImageStat
    small = img.convert("RGB").resize((64, 114))
    strips = [small.crop((0, 0, 64, 6)), small.crop((0, 108, 64, 114)),
              small.crop((0, 0, 4, 114)), small.crop((60, 0, 64, 114))]
    cols = [ImageStat.Stat(s).median for s in strips]
    return tuple(sorted(c[i] for c in cols)[len(cols) // 2] for i in range(3))


def _feather_mask(w, h, f):
    from PIL import Image, ImageDraw, ImageFilter
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rectangle([f, f, w - f, h - f], fill=255)
    return m.filter(ImageFilter.GaussianBlur(f / 2))


def _fit(draw, text, path, start, min_size, max_w):
    size = start
    f = _font(path, size)
    while size > min_size and draw.textlength(text, font=f) > max_w:
        size -= 4
        f = _font(path, size)
    return f


def _draw_line(draw, y, text, accent, font, fill, accent_fill, stroke, stroke_fill):
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


def render_thumbnail(bg_path: str, copy: dict, out_path: str, brand: str,
                     head_font: str = "", sub_font: str = "") -> str:
    from PIL import Image, ImageDraw

    src = Image.open(bg_path).convert("RGB") if _usable(bg_path) else None
    paper = _edge_color(src) if src else (238, 231, 216)
    light = (0.299 * paper[0] + 0.587 * paper[1] + 0.114 * paper[2]) > 128

    base = Image.new("RGB", (W, H), paper)

    # 그림: 560px 아래 영역에 높이를 맞춰 넣고, 가장자리를 종이색으로 번지게
    if src:
        box_h = H - IMG_TOP
        r = box_h / src.height
        iw, ih = int(src.width * r + 0.5), box_h
        if iw > W:                                  # 가로가 넘치면 가로에 맞춤
            r = W / src.width
            iw, ih = W, int(src.height * r + 0.5)
        pic = src.resize((iw, ih), Image.LANCZOS)
        base.paste(pic, ((W - iw) // 2, IMG_TOP), _feather_mask(iw, ih, FEATHER))

    if light:
        fill, accent, stroke_fill = (31, 42, 90), (150, 78, 28), paper      # 남색 · 커피색
        rule = (150, 78, 28)
    else:
        fill, accent, stroke_fill = (248, 242, 228), (226, 176, 70), (12, 10, 8)
        rule = (226, 176, 70)

    d = ImageDraw.Draw(base)

    # 채널명 + 양옆 짧은 선
    head_font, sub_font = head_font or FONT_HEAD, sub_font or FONT_SUB
    f_ch = _font(sub_font, 44)
    tw = d.textlength(brand, font=f_ch)
    cx = W / 2
    d.text((cx - tw / 2, TEXT_TOP), brand, font=f_ch, fill=rule)
    ly = TEXT_TOP + 26
    d.line([(cx - tw / 2 - 90, ly), (cx - tw / 2 - 24, ly)], fill=rule, width=4)
    d.line([(cx + tw / 2 + 24, ly), (cx + tw / 2 + 90, ly)], fill=rule, width=4)

    # 두 줄 헤드라인 (두 줄을 같은 크기로)
    l1, l2 = (copy.get("line1") or "").strip(), (copy.get("line2") or "").strip()
    longest = max([l1, l2], key=len) if (l1 or l2) else ""
    f_head = _fit(d, longest, head_font, 150, 84, W - 2 * MARGIN)
    lh = int(f_head.size * 1.16)
    y = HEAD_TOP
    for line in (l1, l2):
        if line:
            _draw_line(d, y, line, copy.get("accent", ""), f_head, fill, accent,
                       max(6, f_head.size // 16), stroke_fill)
            y += lh

    base.save(out_path, "PNG")
    return out_path


def grid_preview(thumb_path: str, out_path: str, title: str = "") -> str:
    """채널 화면 격자 칸에서 보이는 모습 흉내 — 위아래 10% 잘림 + 아래 1/3 제목 덮임."""
    from PIL import Image, ImageDraw
    im = Image.open(thumb_path).convert("RGB")
    top, bot = int(H * 0.10), int(H * 0.90)
    tile = im.crop((0, top, W, bot))
    tw, th = tile.size
    shade = Image.new("L", (1, th))
    for yy in range(th):
        t = max(0.0, (yy - th * 0.62) / (th * 0.38))
        shade.putpixel((0, yy), int(190 * t))
    dark = Image.new("RGB", (tw, th), (0, 0, 0))
    tile = Image.composite(dark, tile, shade.resize((tw, th)))
    d = ImageDraw.Draw(tile)
    f = _font(FONT_SUB, 58)
    if title:
        d.text((40, th - 250), title[:16], font=f, fill=(255, 255, 255))
        d.text((40, th - 170), title[16:32], font=f, fill=(255, 255, 255))
    d.text((40, th - 90), "조회수 000회", font=_font(FONT_SUB, 48), fill=(230, 230, 230))
    tile.resize((tw // 2, th // 2)).save(out_path, "PNG")
    return out_path


def create_thumbnail(state: dict, copy: dict, bg_path: str, brand: str) -> str:
    head_font = sub_font = ""
    if state.get("channel") == "scenestory":                   # 일본어 글꼴 (Noto CJK JP)
        from src import scenestory
        head_font, sub_font = scenestory.JP_SERIF_BOLD, scenestory.JP_SANS_BOLD
    """project_dir/thumbnail.png 에 저장하고 경로를 돌려준다."""
    project_dir = state.get("project_dir", "projects/tmp")
    os.makedirs(project_dir, exist_ok=True)
    if not _usable(bg_path):
        cands = background_candidates(state)
        bg_path = cands[0][1] if cands else ""
    out = os.path.join(project_dir, "thumbnail.png")
    return render_thumbnail(bg_path, copy, out, brand, head_font, sub_font)
