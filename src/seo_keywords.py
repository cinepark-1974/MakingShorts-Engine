# src/seo_keywords.py
# 너도나도아는커피 숏폼 팩토리 — SEO 키워드 뱅크
#
# [전략]
# - "검증된 고검색 키워드" 탭: YouTube Data API v3로 "커피" 단독 검색 → 24시간 캐시
#   → 하루 1회 호출 (100 units) 로 쿼터 최소 소모
# - "실시간 트렌드" 탭: YouTube 자동완성 (무료, 키 불필요)

import os
import json
import time
import requests
from pathlib import Path


# ── 상수 ──────────────────────────────────────────────────────────────────────
ALL_CHAPTERS = [
    "커피 역사", "원두 산지", "로스팅", "에스프레소",
    "브루잉", "라떼아트", "커피 과학", "카페 문화",
]

GRADE_LABEL = {
    "A": "🔴",
    "B": "🟡",
    "C": "⚪",
}

# 24시간 캐시 파일 경로 (Streamlit Cloud /tmp 는 재시작 시 초기화되지만 세션 내 유지)
_CACHE_FILE = Path("/tmp/coffee_kw_cache.json")
_CACHE_TTL  = 86400   # 24시간 (초)

# ── 챕터 → 관련 단어 매핑 (필터링용) ─────────────────────────────────────────
_CHAPTER_FILTERS = {
    "커피 역사":  ["역사", "기원", "유래", "발견", "전파", "오스만", "에티오피아"],
    "원두 산지":  ["원두", "산지", "에티오피아", "콜롬비아", "예가체프", "수마트라", "케냐"],
    "로스팅":    ["로스팅", "볶기", "로스터", "다크", "라이트", "미디엄", "원두 볶"],
    "에스프레소": ["에스프레소", "샷", "크레마", "추출", "롱블랙", "아메리카노"],
    "브루잉":    ["핸드드립", "브루잉", "푸어오버", "케멕스", "에어로프레스", "프렌치프레스", "드립"],
    "라떼아트":  ["라떼아트", "카푸치노", "플랫화이트", "밀크폼", "스팀", "로제타"],
    "커피 과학":  ["카페인", "성분", "산도", "향미", "플레이버", "과학", "화학"],
    "카페 문화":  ["카페", "스페셜티", "트렌드", "문화", "서울카페", "제3의물결"],
}

# ── 폴백 정적 목록 (API 실패 시) ─────────────────────────────────────────────
_FALLBACK = [
    {"topic": "아이스아메리카노 맛의 진짜 비밀",     "grade": "A", "source": "bank"},
    {"topic": "에스프레소와 롱블랙 차이",           "grade": "A", "source": "bank"},
    {"topic": "예가체프 내추럴 vs 워시드",           "grade": "A", "source": "bank"},
    {"topic": "핸드드립 물 온도가 맛을 바꾼다",       "grade": "A", "source": "bank"},
    {"topic": "카페인 없이 커피 향만 즐기는 법",      "grade": "B", "source": "bank"},
    {"topic": "다크 로스팅 원두가 쓴 이유",          "grade": "B", "source": "bank"},
    {"topic": "라떼아트 하트 그리는 법",             "grade": "B", "source": "bank"},
    {"topic": "스페셜티 커피란 무엇인가",             "grade": "B", "source": "bank"},
    {"topic": "콜드브루 직접 만드는 법",             "grade": "C", "source": "bank"},
    {"topic": "커피 찌꺼기 재활용 아이디어",          "grade": "C", "source": "bank"},
]


# ─────────────────────────────────────────────────────────────────────────────
# 내부: YouTube Data API v3 — "커피" 검색 → 제목 목록 반환
# 하루 1회 호출 (100 units), 결과를 /tmp 파일에 캐시
# ─────────────────────────────────────────────────────────────────────────────
def _fetch_youtube_titles(api_key: str, max_results: int = 50) -> list[str]:
    """YouTube Data API로 "커피" 검색 → 동영상 제목 리스트 반환."""
    try:
        url = "https://www.googleapis.com/youtube/v3/search"
        params = {
            "part":             "snippet",
            "q":                "커피",
            "type":             "video",
            "regionCode":       "KR",
            "relevanceLanguage":"ko",
            "maxResults":       max_results,
            "order":            "viewCount",
            "key":              api_key,
        }
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        items = resp.json().get("items", [])
        return [item["snippet"]["title"] for item in items if "snippet" in item]
    except Exception as e:
        print(f"[seo_keywords] YouTube API 오류: {e}", flush=True)
        return []


def _load_cache() -> list[str] | None:
    """캐시 파일이 유효하면 제목 리스트 반환, 만료·없으면 None."""
    if not _CACHE_FILE.exists():
        return None
    try:
        data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        if time.time() - data.get("ts", 0) < _CACHE_TTL:
            return data.get("titles", [])
    except Exception:
        pass
    return None


def _save_cache(titles: list[str]) -> None:
    try:
        _CACHE_FILE.write_text(
            json.dumps({"ts": time.time(), "titles": titles}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def _get_titles(api_key: str) -> list[str]:
    """캐시 우선, 없으면 API 호출 후 캐시 저장."""
    cached = _load_cache()
    if cached:
        return cached
    titles = _fetch_youtube_titles(api_key)
    if titles:
        _save_cache(titles)
    return titles


# ─────────────────────────────────────────────────────────────────────────────
# 내부: YouTube 자동완성 (무료, API 키 불필요)
# ─────────────────────────────────────────────────────────────────────────────
def _autocomplete(seed: str, count: int = 10) -> list[str]:
    try:
        url = "https://suggestqueries.google.com/complete/search"
        params = {"client": "youtube", "q": seed, "hl": "ko", "gl": "KR", "ds": "yt"}
        resp = requests.get(url, params=params, timeout=5)
        raw  = resp.text
        # 응답 형식: function(["seed", [["kw1",...], ...]])
        start = raw.index("[")
        data  = json.loads(raw[start:])
        suggestions = data[1]
        return [s[0] for s in suggestions if isinstance(s, list)][:count]
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# 공개 API: 챕터별 키워드 (검증된 고검색 탭)
# ─────────────────────────────────────────────────────────────────────────────
def get_keywords_for_chapter(chapter: str, api_key: str = "") -> list[dict]:
    """
    YouTube "커피" 검색 결과(캐시)에서 챕터 연관 제목을 필터링해 반환.
    api_key 없으면 폴백 정적 목록 반환.
    """
    if not api_key:
        # API 키 없음 → 폴백
        filters = _CHAPTER_FILTERS.get(chapter, [])
        if filters:
            return [k for k in _FALLBACK if any(f in k["topic"] for f in filters)] or _FALLBACK[:6]
        return _FALLBACK[:6]

    titles = _get_titles(api_key)
    if not titles:
        return _FALLBACK[:6]

    filters = _CHAPTER_FILTERS.get(chapter, [])
    results: list[dict] = []

    # 1순위: 필터 단어 포함 제목
    if filters:
        for t in titles:
            if any(f in t for f in filters):
                results.append({"topic": t, "grade": "A", "source": "youtube"})
        for t in titles:
            if t not in [r["topic"] for r in results]:
                results.append({"topic": t, "grade": "B", "source": "youtube"})
    else:
        # 챕터 없음 → 전체 상위 목록
        for i, t in enumerate(titles):
            grade = "A" if i < 15 else ("B" if i < 35 else "C")
            results.append({"topic": t, "grade": grade, "source": "youtube"})

    return results[:14]


# ─────────────────────────────────────────────────────────────────────────────
# 공개 API: 실시간 트렌드 (실시간 트렌드 탭)
# ─────────────────────────────────────────────────────────────────────────────
def get_trending_keywords(seed: str, max_realtime: int = 8) -> list[dict]:
    """
    YouTube 자동완성(무료)으로 실시간 키워드 반환.
    API 키 불필요, 쿼터 소모 없음.
    """
    suggestions = _autocomplete(seed, count=max_realtime)
    return [
        {"topic": s, "grade": "A", "source": "youtube"}
        for s in suggestions
    ]
