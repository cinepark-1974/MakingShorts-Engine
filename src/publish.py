# src/publish.py
# 너도나도아는커피 숏폼 팩토리 — 업로드 정보 · 성과 기록
#
# make_upload_pack : 대본을 읽고 YouTube Shorts 업로드용 제목·설명·해시태그·태그·고정 댓글·다음 편 예고·섬네일 문구를 한 번에 만든다.
# perf_rows        : 서버에 있는 프로젝트들의 성과 기록을 표(행 목록)로 모은다 → CSV 다운로드용.

import csv
import io
import json

CHANNEL = "너도나도아는커피"

_PACK_SYSTEM = """당신은 유튜브 쇼츠 채널 '너도나도아는커피'(커피 과학·역사 해설)의 업로드 담당자입니다.
대본을 읽고 업로드에 필요한 것을 한 번에 만듭니다. 규칙:
- title: 40자 이내. 비교 주제면 두 이름을 맨 앞에 둔다(예: "예가체프와 수프리모, ..."). 과장·낚시 금지, 대본에 있는 사실만.
- description: 2~3줄. 첫 줄에 영상의 핵심 한 줄. 마지막 줄에 해시태그 3개(#쇼츠 제외, 주제어 중심).
- hashtags: description 에 넣은 해시태그 3개 (배열).
- tags: YouTube 태그 칸용 검색어 8~12개 (배열). 각 2~20자, 사람들이 실제로 검색할 말. 주제와 무관한 말 금지. '#' 붙이지 않는다.
- pinned_comment: 시청자가 한 단어로 답할 수 있는 질문 하나. 두 가지 중 고르게 하는 형식 권장.
- next_teaser: 다음 편 예고 한 줄 (대본 주제와 이어지는 궁금증).
- thumb_line1, thumb_line2: 섬네일 두 줄. 각 줄 공백 포함 9자 이내. 비교 주제면 두 이름을 한 줄씩(예: "콜드브루 vs" / "더치커피"). 대본에 있는 사실만.
- thumb_accent: thumb_line1 또는 thumb_line2 안에 그대로 들어 있는 단어 하나 (색으로 강조).
이모지는 pinned_comment 에만 1개까지. JSON 만 출력:
{"title": "", "description": "", "hashtags": [], "tags": [], "pinned_comment": "", "next_teaser": "", "thumb_line1": "", "thumb_line2": "", "thumb_accent": ""}"""

TAGS_MAX_CHARS = 500     # YouTube Studio 태그 칸 합계 한도 (쉼표 포함)

def _fallback(state: dict) -> dict:
    topic = (state.get("topic") or "").strip()
    first = (state.get("scenes") or [{}])[0].get("overlay_text", "") or topic
    words = first.split()
    half = max(1, len(words) // 2)
    return {
        "title": topic[:40],
        "description": f"{topic}\n\n#커피 #{CHANNEL} #커피상식",
        "hashtags": ["#커피", f"#{CHANNEL}", "#커피상식"],
        "tags": [w for w in [topic[:20], "커피", "커피상식", CHANNEL, "커피과학"] if w],
        "pinned_comment": "여러분은 어느 쪽인가요? 댓글로 알려주세요 ☕",
        "next_teaser": "",
        "thumb_line1": " ".join(words[:half])[:9] or topic[:9],
        "thumb_line2": " ".join(words[half:])[:9],
        "thumb_accent": "",
    }


def _clean_tags(tags) -> list:
    """중복·'#' 제거, 합계 500자(쉼표 포함) 안으로 자른다."""
    out, total = [], 0
    for t in tags or []:
        t = str(t).replace("#", "").replace(",", " ").strip()
        if not t or t in out or len(t) > 30:
            continue
        add = len(t) + (1 if out else 0)
        if total + add > TAGS_MAX_CHARS:
            break
        out.append(t)
        total += add
    return out


def tags_text(pack: dict) -> str:
    return ",".join(pack.get("tags") or [])


def all_in_one(pack: dict) -> str:
    """한 번에 복사해 메모장 등에 붙여 둘 수 있는 전체 묶음."""
    parts = [
        ("제목", pack.get("title", "")),
        ("설명", pack.get("description", "")),
        ("태그", tags_text(pack)),
        ("고정 댓글", pack.get("pinned_comment", "")),
        ("다음 편 예고", pack.get("next_teaser", "")),
    ]
    return "\n\n".join(f"[{k}]\n{v}" for k, v in parts if v)


def thumb_copy(pack: dict) -> dict:
    return {"line1": pack.get("thumb_line1", ""), "line2": pack.get("thumb_line2", ""),
            "accent": pack.get("thumb_accent", "")}


UPLOAD_SETTINGS = [
    ("카테고리", "교육"),
    ("아동용 여부", "아니요, 아동용이 아닙니다"),
    ("동영상 언어", "한국어"),
    ("변경되거나 합성된 콘텐츠", "사실적인 AI 인물·실사 장면이 들어간 편은 '예'"),
    ("섬네일", "Shorts 맞춤 섬네일은 데스크톱 YouTube Studio 에서 올립니다"),
]


def _ss_pack_system() -> str:
    from src import scenestory
    return scenestory.PACK_SYSTEM


def channel_brand(state: dict) -> str:
    return "SceneStory" if (state or {}).get("channel") == "scenestory" else CHANNEL


def upload_settings(state: dict) -> list:
    if (state or {}).get("channel") == "scenestory":
        from src import scenestory
        return scenestory.UPLOAD_SETTINGS
    return UPLOAD_SETTINGS


def _fallback_ss(state: dict) -> dict:
    tc = state.get("title_card") or {}
    work = (tc.get("work") or state.get("topic") or "").strip("『』")
    from src import scenestory
    info = scenestory.work_info_line(state) or f"『{work}』"
    return {"title": f"『{work}』"[:40], "description": f"作品：{info}\n\n#SceneStory #名場面 #{work}",
            "hashtags": ["#SceneStory", "#名場面", f"#{work}"], "tags": [work, "名場面", "SceneStory"],
            "pinned_comment": "この場面、覚えていますか？", "next_teaser": "",
            "thumb_line1": work[:9], "thumb_line2": "名場面", "thumb_accent": ""}


def make_upload_pack(api_key: str, state: dict) -> dict:
    is_ss = (state or {}).get("channel") == "scenestory"
    fb = _fallback_ss if is_ss else _fallback
    if not api_key:
        return fb(state)
    try:
        import anthropic
        narr = " ".join((s.get("narration") or "") for s in state.get("scenes", []))
        user = f"주제: {state.get('topic', '')}\n\n대본:\n{narr}"
        resp = anthropic.Anthropic(api_key=api_key).messages.create(
            model="claude-sonnet-4-6", max_tokens=1200, system=(_ss_pack_system() if is_ss else _PACK_SYSTEM),
            messages=[{"role": "user", "content": user}],
        )
        raw = "".join(getattr(b, "text", "") for b in resp.content)
        data = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
        pack = fb(state)
        for k in pack:
            if data.get(k):
                pack[k] = data[k]
        pack["title"] = str(pack["title"])[:40]
        pack["tags"] = _clean_tags(pack.get("tags"))
        for k in ("thumb_line1", "thumb_line2"):
            pack[k] = str(pack.get(k, ""))[:12]
        if pack.get("thumb_accent") and pack["thumb_accent"] not in (pack["thumb_line1"] + pack["thumb_line2"]):
            pack["thumb_accent"] = ""
        if is_ss:                                   # 작품 정보는 설명 첫 줄과 고정 댓글 첫 줄에 반드시
            from src import scenestory
            info = scenestory.work_info_line(state)
            if info:
                if info not in pack.get("description", ""):
                    pack["description"] = f"作品：{info}\n" + pack.get("description", "")
                if info not in pack.get("pinned_comment", ""):
                    pack["pinned_comment"] = f"作品：{info}\n" + pack.get("pinned_comment", "")
        return pack
    except Exception as e:
        print(f"[publish] 업로드 정보 생성 실패 → 기본값: {e}", flush=True)
        return fb(state)


# ─────────────────────────────────────────────────────────────────────────────
# 성과 기록
# ─────────────────────────────────────────────────────────────────────────────
PERF_FIELDS = ["upload_date", "views_7d", "viewed_rate", "avg_view_pct", "likes", "comments", "memo"]
PERF_LABELS = {
    "upload_date":  "업로드 날짜",
    "views_7d":     "7일 조회수",
    "viewed_rate":  "시청함 비율 % (vs 넘김)",
    "avg_view_pct": "평균 시청 비율 %",
    "likes":        "좋아요",
    "comments":     "댓글",
    "memo":         "메모",
}


def perf_row(state: dict) -> dict:
    scenes = state.get("scenes") or [{}]
    perf = state.get("perf") or {}
    row = {
        "project_id": state.get("project_id", ""),
        "topic":      state.get("topic", ""),
        "length":     state.get("length", ""),
        "cuts":       len(state.get("scenes") or []),
        "hook_text":  scenes[0].get("overlay_text", ""),
        "hook_line":  scenes[0].get("narration", ""),
        "title":      (state.get("upload_pack") or {}).get("title", ""),
    }
    row.update({k: perf.get(k, "") for k in PERF_FIELDS})
    return row


def perf_csv(rows: list) -> bytes:
    buf = io.StringIO()
    cols = ["project_id", "topic", "length", "cuts", "hook_text", "hook_line", "title"] + PERF_FIELDS
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c, "") for c in cols})
    return ("﻿" + buf.getvalue()).encode("utf-8")   # 엑셀에서 한글 깨짐 방지
