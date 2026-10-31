# src/captions.py
# 숏폼 팩토리 — 말 따라 바뀌는 큰 자막 (커피 · SceneStory 공통)
#
# 예전: 컷마다 나레이션 전체를 3줄로 6초 내내 띄움
# 지금: 나레이션을 짧은 구절로 나눠 1~2초마다 바꿔 띄움 (박스 없음, 굵은 외곽선)
#
# 시간 배분: 엔진은 컷 길이를 "그 컷 나레이션 글자 수" 비율로 정한다(assembler.plan_durations).
#            구절도 같은 기준(글자 수 비율)으로 나누므로 컷 안에서 말과 자막이 같은 속도로 흘러간다.
#            말 속도가 고르지 않은 대목에서는 0.5초 안팎 어긋날 수 있다 (ElevenLabs 글자별 시간 정보를 쓰면 더 정확해짐).

import os
import re

KO_MAX = 11          # 한 구절 최대 글자 수 (공백 제외) — 86px 한 줄에 들어가는 길이
JA_MAX = 16
MIN_SEC = 0.7        # 한 구절 최소 표시 시간

_JA_BREAK_AFTER = set("、。！？」』）")
_JA_SOFT_AFTER = set("はがをにでともへやねよか")


def _n(t: str) -> int:
    return len(re.sub(r"\s", "", t or ""))


def _split_ko(text: str) -> list:
    out = []
    for sent in re.split(r"(?<=[.!?。,，])\s+", text.strip()):
        words, cur = sent.split(), ""
        for w in words:
            cand = (cur + " " + w).strip()
            if cur and _n(cand) > KO_MAX:
                out.append(cur)
                cur = w
            else:
                cur = cand
        if cur:
            if out and _n(cur) <= 6 and _n(out[-1]) + _n(cur) <= KO_MAX + 3 and not re.search(r"[.!?。,，]$", out[-1]):
                out[-1] = out[-1] + " " + cur        # 「때문입니다.」 처럼 짧은 꼬리는 앞 구절에 붙인다
            else:
                out.append(cur)
    return out


def _split_ja(text: str) -> list:
    text = re.sub(r"\s+", "", text.strip())
    out, cur = [], ""
    for i, ch in enumerate(text):
        cur += ch
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if ch in _JA_BREAK_AFTER and nxt not in _JA_BREAK_AFTER:
            if _n(cur) >= 4 or ch in "。！？":
                out.append(cur)
                cur = ""
        elif _n(cur) >= JA_MAX and ch in _JA_SOFT_AFTER:
            out.append(cur)
            cur = ""
        elif _n(cur) >= JA_MAX + 6:
            out.append(cur)
            cur = ""
    if cur:
        if out and _n(cur) <= 2:
            out[-1] += cur
        else:
            out.append(cur)
    return out


def split_phrases(text: str, lang: str = "ko") -> list:
    text = (text or "").strip()
    if not text:
        return []
    ps = _split_ja(text) if lang == "ja" else _split_ko(text)
    return [p for p in ps if p.strip()]


def timeline(phrases: list, duration: float, start_pad: float = 0.0) -> list:
    """[(시작, 끝, 구절)] — 글자 수 비율로 duration 을 나눈다."""
    if not phrases or duration <= 0:
        return []
    usable = max(duration - start_pad, 0.5)
    w = [max(_n(p), 1) for p in phrases]
    tot = sum(w)
    secs = [max(usable * x / tot, MIN_SEC) for x in w]
    scale = usable / sum(secs)
    secs = [x * scale for x in secs]
    out, t = [], start_pad
    for p, s in zip(phrases, secs):
        out.append((round(t, 3), round(min(t + s, duration), 3), p))
        t += s
    return out


def render_caption_png(text: str, out_path: str, W: int, H: int, lang: str = "ko",
                       light: bool = False, y_ratio: float = 0.74) -> str:
    """구절 하나를 큰 글자로 (최대 2줄). 박스 없이 외곽선 + 그림자."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = _font(lang, 84 if lang == "ja" else 86)
    max_w = W - 2 * 70
    lines = _wrap(d, text, font, max_w, lang)
    if len(lines) > 2:
        font = _font(lang, 70)
        lines = _wrap(d, text, font, max_w, lang)[:2]
    if light:
        fill, stroke = (30, 22, 16, 255), (250, 244, 232, 240)
    else:
        fill, stroke = (255, 250, 240, 255), (10, 8, 8, 235)
    lh = int(font.size * 1.25)
    y0 = int(H * y_ratio) - (len(lines) - 1) * lh // 2
    for i, ln in enumerate(lines):
        xy = (W // 2, y0 + i * lh)
        if not light:
            d.text((xy[0] + 3, xy[1] + 5), ln, font=font, fill=(0, 0, 0, 120), anchor="ma",
                   stroke_width=9, stroke_fill=(0, 0, 0, 120))
        d.text(xy, ln, font=font, fill=fill, anchor="ma", stroke_width=9, stroke_fill=stroke)
    img.save(out_path, "PNG")
    return out_path


def _font(lang: str, size: int):
    if lang == "ja":
        from src.scenestory import jp_font, JP_SANS_BOLD
        return jp_font(JP_SANS_BOLD, size)
    from src.assembler import _font as ko_font, FONT_SANS_BOLD
    return ko_font(FONT_SANS_BOLD, size)


def _wrap(d, text: str, font, max_w: int, lang: str) -> list:
    if d.textlength(text, font=font) <= max_w:
        return [text]
    if lang == "ja":
        from src.scenestory import phrase_wrap
        return phrase_wrap(d, text, font, max_w)
    words, lines, cur = text.split(), [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        if cur and d.textlength(cand, font=font) > max_w:
            lines.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines


def build_for_scene(scene: dict, duration: float, tmpdir: str, sno: int, W: int, H: int,
                    lang: str = "ko", light: bool = False, instant: bool = False) -> list:
    """컷 하나의 자막 구간 PNG 목록 [(시작, 끝, png 경로)]."""
    text = (scene.get("narration") or "").strip()
    if not text:
        return []
    tl = timeline(split_phrases(text, lang), duration, start_pad=0.0 if instant else 0.15)
    out = []
    for i, (a, b, p) in enumerate(tl):
        png = os.path.join(tmpdir, f"cap_{sno:02d}_{i:02d}.png")
        render_caption_png(p, png, W, H, lang=lang, light=light)
        out.append((a, b, png))
    return out
