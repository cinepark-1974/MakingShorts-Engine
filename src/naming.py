# src/naming.py
# 내려받는 파일 이름 규칙 (모든 채널 공통)
#   {제작일}_{채널}_{제목}_{종류}.{확장자}
#   예) 20261104_SceneStory_閉店の日の豆腐屋_main.mp4
#       20261104_SceneStory_閉店の日の豆腐屋_trailer.mp4
#       20261104_SceneStory_閉店の日の豆腐屋_thumbnail.jpg
#       20261103_Coffee_아메리카노와-롱블랙_main.mp4
#       20261101_HASIRA_雨のロンドン_main.mp4
# 같은 편의 파일은 이름 앞부분이 같아서 폴더에서 나란히 정렬된다.

import re
import time

CHANNEL_CODE = {"coffee": "Coffee", "scenestory": "SceneStory", "hasira": "HASIRA"}
KINDS = {
    "main": "본편·완성 영상", "trailer": "예고 쇼츠", "thumbnail": "섬네일",
    "thumbnail-base": "글자 없는 섬네일 바탕", "trailer-cover": "쇼츠 표지", "compilation": "모음편", "upload": "업로드 정보",
}


def _date(state: dict) -> str:
    pid = str(state.get("project_id", ""))
    m = re.match(r"(\d{8})", pid)
    return m.group(1) if m else time.strftime("%Y%m%d")


def _title(state: dict) -> str:
    plan = state.get("plan") or {}
    t = (plan.get("title_ja") or state.get("title") or state.get("topic") or "untitled")
    t = re.sub(r"\s*\(.*?\)\s*$", "", str(t))            # 'タイトル (한국어)' 꼴이면 괄호 부분 제거
    t = re.sub(r"^\[.*?\]\s*", "", t)                     # '[챕터] 주제' 꼴이면 챕터 표시 제거
    t = t.split(" — ")[0]
    t = re.sub(r'[\\/:*?"<>|\r\n\t]', "", t)              # 파일 이름에 못 쓰는 글자
    t = re.sub(r"\s+", "-", t.strip()).strip("-.")
    return t[:30] or "untitled"


def out_name(state: dict, kind: str, ext: str, channel: str = "") -> str:
    ch = CHANNEL_CODE.get(channel or state.get("channel") or "coffee", "Coffee")
    return f"{_date(state)}_{ch}_{_title(state)}_{kind}.{ext.lstrip('.')}"


def content_disposition(filename: str) -> str:
    """R2 내려받기 링크용. 일본어·한국어 이름도 깨지지 않게 RFC 5987 형식을 함께 넣는다."""
    from urllib.parse import quote
    ascii_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename)
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
