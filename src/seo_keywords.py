# src/seo_keywords.py
# 너도나도아는커피 숏폼 팩토리 — SEO 키워드 자동 발굴기
#
# 전략: 사전 큐레이션 뱅크(오프라인) + YouTube 자동완성(실시간) 조합
# YouTube 자동완성: API 키 불필요 — suggestqueries.google.com 공개 엔드포인트 사용
# 대한민국 YouTube 기준 hl=ko&gl=KR 파라미터로 한국어 트렌드 반영

import json
import requests


# ── 챕터별 큐레이션 키워드 뱅크 ──────────────────────────────────────────────
# Claude가 생성한 커피 고검색량 키워드 (2026-09 기준 추정치)
# 각 항목: (주제명, 예상_월간검색량_등급)  A=1만↑ / B=3천~1만 / C=1천~3천
KEYWORD_BANK: dict[str, list[tuple[str, str]]] = {
    "에스프레소 추출 과학": [
        ("에스프레소 만드는 법", "A"),
        ("에스프레소 크레마 생기는 이유", "B"),
        ("에스프레소 추출 압력 9바", "B"),
        ("에스프레소 쓴맛 줄이는 방법", "A"),
        ("에스프레소 샷 비율", "B"),
        ("에스프레소 머신 원리", "B"),
        ("리스트레또 vs 룽고 차이", "C"),
        ("에스프레소 과다추출 과소추출", "B"),
    ],
    "커피 원두 선택법": [
        ("커피 원두 차이 아라비카 로부스타", "A"),
        ("커피 원두 추천 입문자", "A"),
        ("싱글오리진 블렌드 차이", "B"),
        ("커피 산지별 맛 차이 에티오피아 콜롬비아", "B"),
        ("커피 원두 보관법", "A"),
        ("커피 원두 유통기한", "B"),
        ("생두 vs 원두 차이", "C"),
        ("스페셜티 커피란", "B"),
    ],
    "로스팅 단계와 맛": [
        ("커피 로스팅 단계 차이", "A"),
        ("라이트 로스트 다크 로스트 뭐가 다를까", "A"),
        ("커피 로스팅 원리", "B"),
        ("홈 로스팅 하는 법", "B"),
        ("커피 신맛 줄이는 방법", "A"),
        ("커피 쓴맛 나는 이유", "A"),
        ("로스팅 날짜 중요한 이유", "B"),
        ("커피 프레쉬니스", "C"),
    ],
    "추출 도구 비교": [
        ("드립 커피 vs 에스프레소 차이", "A"),
        ("모카포트 사용법", "A"),
        ("에어로프레스 커피 만드는 법", "B"),
        ("프렌치프레스 사용법", "A"),
        ("핸드드립 커피 입문", "A"),
        ("콜드브루 만드는 법", "A"),
        ("커피 도구 추천 입문자", "A"),
        ("케멕스 v60 차이", "B"),
    ],
    "카페인과 건강": [
        ("커피 카페인 함량 비교", "A"),
        ("디카페인 커피 카페인 있나", "A"),
        ("커피 하루 몇 잔이 적당한가", "A"),
        ("커피 공복에 마시면", "A"),
        ("커피 수면 영향", "A"),
        ("커피 위장 자극 이유", "B"),
        ("카페인 반감기", "B"),
        ("임산부 커피 섭취 기준", "B"),
    ],
    "라떼아트와 밀크폼": [
        ("라떼아트 만드는 법 입문", "A"),
        ("우유 스티밍 온도", "B"),
        ("마이크로폼 만드는 법", "B"),
        ("오트밀크 라떼아트 가능한가", "B"),
        ("라떼 카푸치노 차이", "A"),
        ("플랫화이트란", "B"),
        ("홈 라떼아트 연습법", "B"),
        ("우유 종류별 스팀 차이", "C"),
    ],
    "커피의 역사와 문화": [
        ("커피 역사 기원", "B"),
        ("에티오피아 커피 기원 전설", "B"),
        ("커피 한국 들어온 역사", "B"),
        ("이탈리아 에스프레소 문화", "B"),
        ("제3의 물결 커피란", "B"),
        ("스페셜티 커피 문화", "B"),
        ("커피벨트 커피 재배 지역", "C"),
        ("커피 무역 역사", "C"),
    ],
    "홈카페 레시피": [
        ("달고나 커피 만드는 법", "A"),
        ("아이스 라떼 만드는 법", "A"),
        ("바닐라 라떼 레시피", "A"),
        ("플랫화이트 만드는 법", "B"),
        ("콜드브루 레시피", "A"),
        ("카라멜 마키아토 만들기", "A"),
        ("에스프레소 토닉 레시피", "B"),
        ("홈카페 입문 장비 추천", "A"),
    ],
}

# 전체 챕터 목록 (UI 드롭다운용)
ALL_CHAPTERS = list(KEYWORD_BANK.keys())


# ── YouTube/Google 자동완성 실시간 조회 ──────────────────────────────────────
def fetch_youtube_suggestions(seed_keyword: str, max_results: int = 8) -> list[str]:
    """
    Google의 YouTube 자동완성 엔드포인트에서 실시간 연관 검색어를 가져온다.
    API 키 불필요. 실패 시 빈 리스트 반환(앱 중단 없음).

    Args:
        seed_keyword : 검색 씨앗 키워드 (예: "에스프레소")
        max_results  : 최대 반환 개수

    Returns:
        list[str] : 자동완성 검색어 목록
    """
    try:
        url = "https://suggestqueries.google.com/complete/search"
        params = {
            "client": "youtube",
            "q":      seed_keyword,
            "hl":     "ko",
            "gl":     "KR",
            "ds":     "yt",
        }
        resp = requests.get(url, params=params, timeout=4)
        resp.raise_for_status()

        # 응답 형식: [0, [["검색어", 0], ...], ...]
        # Content-Type이 application/json이 아닐 수 있어 직접 파싱
        raw = resp.text
        # JSONP 형식 대비: )]}' 로 시작하는 경우 제거
        if raw.startswith(")]}'"):
            raw = raw[4:]
        data = json.loads(raw)

        # data[1]: [["검색어", score], ...]
        suggestions = []
        for item in data[1]:
            if isinstance(item, list) and len(item) > 0:
                suggestions.append(item[0])
            elif isinstance(item, str):
                suggestions.append(item)
            if len(suggestions) >= max_results:
                break

        return suggestions

    except Exception:
        # 네트워크 오류, 파싱 실패 등 — 조용히 실패
        return []


# ── 챕터별 키워드 조회 ────────────────────────────────────────────────────────
def get_keywords_for_chapter(chapter: str) -> list[dict]:
    """
    챕터에 해당하는 큐레이션 키워드 목록을 반환한다.

    Returns:
        list[dict] : [{"topic": str, "grade": str, "source": "bank"}, ...]
    """
    items = KEYWORD_BANK.get(chapter, [])
    return [
        {"topic": topic, "grade": grade, "source": "bank"}
        for topic, grade in items
    ]


# ── 실시간 트렌드 키워드 조회 ─────────────────────────────────────────────────
def get_trending_keywords(chapter: str, max_realtime: int = 5) -> list[dict]:
    """
    챕터 큐레이션 키워드 + YouTube 실시간 트렌드를 합쳐 반환한다.

    Returns:
        list[dict] : [{"topic": str, "grade": str, "source": "bank"|"youtube"}, ...]
    """
    results = get_keywords_for_chapter(chapter)

    # 챕터명의 첫 번째 단어를 씨앗 키워드로 사용
    seed = chapter.split()[0] if chapter else "커피"
    live = fetch_youtube_suggestions(seed, max_results=max_realtime)

    # 중복 제거 (이미 뱅크에 있는 것은 건너뜀)
    existing_topics = {r["topic"] for r in results}
    for topic in live:
        if topic not in existing_topics:
            results.append({"topic": topic, "grade": "?", "source": "youtube"})
            existing_topics.add(topic)

    return results


# ── 등급 뱃지 텍스트 ─────────────────────────────────────────────────────────
GRADE_LABEL = {
    "A": "🔥 고검색",
    "B": "✨ 중검색",
    "C": "💡 틈새",
    "?": "📡 실시간",
}
