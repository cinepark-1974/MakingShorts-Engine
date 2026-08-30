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


def scene_to_query(scene: dict) -> str:
    """
    씬 딕셔너리에서 Unsplash 검색어를 자동 생성한다.

    우선순위:
    1. flow_prompt 앞 5 단어 (영문이므로 검색 품질 우수)
    2. overlay_text (한국어 자막 키워드)
    3. name (씬 이름)
    항상 'coffee'를 앞에 붙여 커피 관련성을 보장한다.

    Args:
        scene : state["scenes"] 의 씬 딕셔너리

    Returns:
        str : Unsplash 검색어 (예: "coffee barista cinematic espresso")
    """
    # flow_prompt 앞 5 단어 — 이미 Kling용 영문 프롬프트이므로 최우선
    flow = scene.get("flow_prompt", "").strip()
    flow_words = " ".join(flow.split()[:5]) if flow else ""

    if flow_words:
        return f"coffee {flow_words}"

    # 폴백: overlay_text → name
    keyword = (
        scene.get("overlay_text", "").strip()
        or scene.get("name", "").strip()
        or "barista"
    )
    return f"coffee {keyword}"
