# src/publish.py
# 너도나도아는커피 숏폼 팩토리 — 업로드 정보 · 성과 기록
#
# make_upload_pack : 대본을 읽고 YouTube Shorts 업로드용 제목·설명·해시태그·고정 댓글·다음 편 예고를 만든다.
# perf_rows        : 서버에 있는 프로젝트들의 성과 기록을 표(행 목록)로 모은다 → CSV 다운로드용.

import csv
import io
import json

CHANNEL = "너도나도아는커피"

_PACK_SYSTEM = """당신은 유튜브 쇼츠 채널 '너도나도아는커피'(커피 과학·역사 해설)의 업로드 담당자입니다.
대본을 읽고 업로드 정보를 만듭니다. 규칙:
- title: 40자 이내. 사람들이 검색할 핵심어를 앞에 둔다. 과장·낚시 금지, 대본에 있는 사실만.
- description: 2~3줄. 첫 줄에 영상의 핵심 한 줄. 마지막 줄에 해시태그 3개(#쇼츠 제외, 주제어 중심).
- hashtags: description 에 넣은 해시태그 3개 (배열).
- pinned_comment: 시청자가 한 단어로 답할 수 있는 질문 하나. 두 가지 중 고르게 하는 형식 권장.
- next_teaser: 다음 편 예고 한 줄 (대본 주제와 이어지는 궁금증).
이모지는 pinned_comment 에만 1개까지. JSON 만 출력:
{"title": "", "description": "", "hashtags": [], "pinned_comment": "", "next_teaser": ""}"""


def _fallback(state: dict) -> dict:
    topic = (state.get("topic") or "").strip()
    return {
        "title": topic[:40],
        "description": f"{topic}\n\n#커피 #{CHANNEL} #커피상식",
        "hashtags": ["#커피", f"#{CHANNEL}", "#커피상식"],
        "pinned_comment": "여러분은 어느 쪽인가요? 댓글로 알려주세요 ☕",
        "next_teaser": "",
    }


def make_upload_pack(api_key: str, state: dict) -> dict:
    if not api_key:
        return _fallback(state)
    try:
        import anthropic
        narr = " ".join((s.get("narration") or "") for s in state.get("scenes", []))
        user = f"주제: {state.get('topic', '')}\n\n대본:\n{narr}"
        resp = anthropic.Anthropic(api_key=api_key).messages.create(
            model="claude-sonnet-4-6", max_tokens=800, system=_PACK_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        raw = "".join(getattr(b, "text", "") for b in resp.content)
        data = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
        pack = _fallback(state)
        for k in pack:
            if data.get(k):
                pack[k] = data[k]
        pack["title"] = str(pack["title"])[:40]
        return pack
    except Exception as e:
        print(f"[publish] 업로드 정보 생성 실패 → 기본값: {e}", flush=True)
        return _fallback(state)


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
