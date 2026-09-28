# src/image_search.py
# 너도나도아는커피 숏폼 팩토리 — Unsplash 라이센스 프리 사진 검색기
#
# Unsplash License: 무료·상업적 사용 가능, 저작권자 귀속 불필요 (권장)
# API Docs: https://unsplash.com/documentation
# 무료 플랜: 50 req/hr (Demo), 프로덕션 등록 시 5,000 req/hr

import requests

UNSPLASH_API_BASE = "https://api.unsplash.com"


def search_unsplash(
    query: str,
    access_key: str,
    orientation: str = "portrait",   # 9:16 세로 숏폼에 최적
    per_page: int = 5,
    page: int = 1,
) -> str:
    """
    Unsplash에서 검색어에 맞는 라이센스 프리 사진을 찾아 URL을 반환한다.

    Args:
        query      : 검색어 (영어 권장, 예: "coffee espresso barista")
        access_key : Unsplash Access Key (UNSPLASH_ACCESS_KEY)
        orientation: "portrait" | "landscape" | "squarish"
        per_page   : 검색 결과 수 (1~30)
        page       : 페이지 번호 (다른 결과 원할 때 2, 3 등)

    Returns:
        str : 사진 regular URL (~1080px 폭, Kling 첫 프레임에 적합)

    Raises:
        ValueError          : 검색 결과 없음
        requests.HTTPError  : API 인증 오류 / 호출 초과
    """
    endpoint = f"{UNSPLASH_API_BASE}/search/photos"
    params = {
        "query":       query,
        "orientation": orientation,
        "per_page":    per_page,
        "page":        page,
    }
    headers = {
        "Authorization":  f"Client-ID {access_key}",
        "Accept-Version": "v1",
    }

    resp = requests.get(endpoint, params=params, headers=headers, timeout=15)
    resp.raise_for_status()

    results = resp.json().get("results", [])
    if not results:
        raise ValueError(f"Unsplash 검색 결과 없음: '{query}'")

    # regular URL: 최대 1080px 폭 — Kling image-to-video 첫 프레임에 충분
    return results[0]["urls"]["regular"]


_CAMERA_WORDS = {
    "slow", "cinematic", "camera", "drift", "drifting", "across", "push-in", "push", "pull", "back",
    "zoom", "pan", "tilt", "shot", "close-up", "closeup", "wide", "aerial", "flyover", "of", "the",
    "a", "an", "and", "with", "in", "on", "at", "from", "to", "9:16", "vertical", "4k", "8k",
    "film", "grain", "visible", "warm", "golden", "atmosphere", "lighting", "light", "moody",
    "atmospheric", "natural", "morning", "motion", "gentle", "gently",
}


def _keywords(text: str, limit: int = 6) -> list:
    words = []
    for w in text.replace(",", " ").replace("—", " ").split():
        lw = w.strip(".!?:;()").lower()
        if lw and lw not in _CAMERA_WORDS and not lw.isdigit() and lw not in words:
            words.append(lw)
        if len(words) >= limit:
            break
    return words


def scene_to_query(scene: dict) -> str:
    """
    씬에서 Unsplash 검색어를 만든다.
    1순위: image_prompt (photo 씬은 대본 단계에서 '검색 키워드'로 작성됨)
    2순위: flow_prompt 에서 카메라·움직임 단어를 뺀 명사들
    3순위: overlay_text / name
    (예전에는 flow_prompt 앞 다섯 단어를 그대로 써서 'slow cinematic camera drift across' 같은
     카메라 표현으로 검색 → 컷마다 같은 사진이 나오는 문제가 있었다)
    """
    for field in ("image_prompt", "flow_prompt"):
        kws = _keywords(scene.get(field, "") or "")
        if len(kws) >= 2:
            if "coffee" not in kws:
                kws = ["coffee"] + kws[:5]
            return " ".join(kws)
    keyword = (scene.get("overlay_text", "") or scene.get("name", "") or "barista").strip()
    return f"coffee {keyword}"


def search_unsplash_pick(query: str, access_key: str, exclude_ids=(), page: int = 1):
    """
    검색 결과 15장 중 이미 쓴 사진(exclude_ids)을 건너뛰고 첫 사진을 고른다.
    반환: (url, photo_id). 결과가 모두 쓰였으면 다음 페이지를 한 번 더 본다.
    """
    headers = {"Authorization": f"Client-ID {access_key}", "Accept-Version": "v1"}
    for pg in (page, page + 1):
        resp = requests.get(
            f"{UNSPLASH_API_BASE}/search/photos",
            params={"query": query, "orientation": "portrait", "per_page": 15, "page": pg},
            headers=headers, timeout=15,
        )
        resp.raise_for_status()
        for r in resp.json().get("results", []):
            if r.get("id") not in set(exclude_ids):
                return r["urls"]["regular"], r.get("id", "")
    raise ValueError(f"Unsplash 에서 새 사진을 찾지 못했습니다: '{query}'")
