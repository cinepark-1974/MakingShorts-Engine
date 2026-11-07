"""터진 영상 찾기 — 일본 시니어 낭독 분야에서 '채널 규모에 비해 많이 본' 영상.

YouTube Data API v3 (공개 데이터, API 키만). 하루 기본 10,000단위 중
search.list 100단위 × 검색어 수 + videos.list·channels.list 1단위씩만 쓴다.

점수 = 조회수 ÷ max(구독자 수, 500)  (구독자가 아주 적은 채널이 과하게 뜨지 않게 바닥을 둔다)
youtube-agent-skill 의 yt-viral(채널 평소 대비 몇 배) 아이디어를 구독자 기준으로 단순화.
"""
from __future__ import annotations

import datetime as dt

import requests

API = "https://www.googleapis.com/youtube/v3"

QUERIES = ["朗読 スカッと", "朗読 感動する話", "朗読 シニア 夫婦", "朗読ドラマ 嫁姑", "朗読 初恋 再会", "朗読 泣ける話"]


def _get(key: str, path: str, **params) -> dict:
    r = requests.get(f"{API}/{path}", params={"key": key, **params}, timeout=20)
    if r.status_code != 200:
        try:
            msg = r.json().get("error", {}).get("message", "")
        except Exception:
            msg = r.text[:200]
        raise RuntimeError(f"YouTube API {path} {r.status_code}: {msg}")
    return r.json()


def _int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def find(key: str, days: int = 14, queries: list | None = None, per_query: int = 15, top: int = 10) -> list[dict]:
    """최근 days 일 동안 올라온 영상 중 점수 상위 top 개."""
    if not key:
        return []
    after = (dt.datetime.utcnow() - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    found = {}
    for q in (queries or QUERIES):
        res = _get(key, "search", part="snippet", q=q, type="video", order="viewCount", publishedAfter=after,
                   regionCode="JP", relevanceLanguage="ja", maxResults=per_query)
        for it in res.get("items", []):
            vid = (it.get("id") or {}).get("videoId")
            sn = it.get("snippet") or {}
            if vid and vid not in found:
                found[vid] = {"id": vid, "title": sn.get("title", ""), "channel": sn.get("channelTitle", ""),
                              "channel_id": sn.get("channelId", ""), "published": sn.get("publishedAt", "")[:10],
                              "query": q}
    if not found:
        return []
    ids = list(found)
    for i in range(0, len(ids), 50):
        res = _get(key, "videos", part="statistics,contentDetails", id=",".join(ids[i:i + 50]))
        for it in res.get("items", []):
            v = found.get(it.get("id"))
            if v:
                v["views"] = _int((it.get("statistics") or {}).get("viewCount"))
                v["duration"] = (it.get("contentDetails") or {}).get("duration", "")
    chans = list({v["channel_id"] for v in found.values() if v["channel_id"]})
    subs = {}
    for i in range(0, len(chans), 50):
        res = _get(key, "channels", part="statistics", id=",".join(chans[i:i + 50]))
        for it in res.get("items", []):
            stt = it.get("statistics") or {}
            subs[it.get("id")] = 0 if stt.get("hiddenSubscriberCount") else _int(stt.get("subscriberCount"))
    out = []
    for v in found.values():
        v["subs"] = subs.get(v["channel_id"], 0)
        v["score"] = round(v.get("views", 0) / max(v["subs"], 500), 1)
        v["short"] = _is_short(v.get("duration", ""))
        v["url"] = f"https://www.youtube.com/watch?v={v['id']}"
        out.append(v)
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:top]


def _is_short(iso: str) -> bool:
    """ISO 8601 길이(PT1M5S 등)가 3분 이하면 쇼츠로 본다."""
    import re
    m = re.fullmatch(r"P(?:\d+D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return False
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s <= 180


def as_prompt(items: list[dict], n: int = 6) -> str:
    """설계 단계에 넣을 참고 문장 (제목만 · 베끼지 말 것)."""
    if not items:
        return ""
    lines = [f"- {v['title']}（{v['views']:,}回 / 登録者{v['subs']:,}人）" for v in items[:n]]
    return ("いま日本のシニア向け朗読で、チャンネル規模に比べて特によく見られている動画のタイトル（参考。"
            "内容や台詞を真似しない。何が刺さっているか＝決定的な瞬間・一言・数字の型だけを学ぶ）:\n" + "\n".join(lines))
