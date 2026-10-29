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

# 캐시 파일 경로 (Streamlit Cloud /tmp 는 재시작 시 초기화되지만 세션 내 유지)
_CACHE_FILE     = Path("/tmp/coffee_kw_cache.json")
_CACHE_TTL_OK   = 86400   # 24시간 — 성공 결과 캐시
_CACHE_TTL_FAIL =  3600   #  1시간 — 실패(403 등) 결과 캐시, 복구 시 빠른 재시도 허용

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
    """
    캐시 파일이 유효하면 제목 리스트 반환 (빈 리스트 [] 포함).
    만료되었거나 파일이 없으면 None 반환.
    성공 캐시 TTL = 24h / 실패 캐시 TTL = 1h
    """
    if not _CACHE_FILE.exists():
        return None
    try:
        data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        ttl  = _CACHE_TTL_OK if data.get("ok") else _CACHE_TTL_FAIL
        if time.time() - data.get("ts", 0) < ttl:
            return data.get("titles", [])   # 빈 리스트도 유효한 캐시로 반환
    except Exception:
        pass
    return None


def _save_cache(titles: list[str]) -> None:
    """결과(빈 리스트 포함)를 캐시 파일에 저장. ok 플래그로 성공/실패 TTL 구분."""
    try:
        _CACHE_FILE.write_text(
            json.dumps({"ts": time.time(), "titles": titles, "ok": bool(titles)},
                       ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def _get_titles(api_key: str) -> list[str]:
    """
    캐시 우선, 없으면 API 호출 후 캐시 저장.
    ※ 실패(빈 결과)도 반드시 캐시 — 403 반복 호출 방지.
    """
    cached = _load_cache()
    if cached is not None:   # None = 만료·없음 / [] = 캐시된 실패 결과
        return cached
    titles = _fetch_youtube_titles(api_key)
    _save_cache(titles)      # 빈 결과도 저장하여 다음 재실행에서 반복 호출 차단
    return titles


# ─────────────────────────────────────────────────────────────────────────────
# 내부: YouTube 자동완성 (무료, API 키 불필요)
# ─────────────────────────────────────────────────────────────────────────────
def _parse_suggest(raw: str) -> list[str]:
    """자동완성 응답 파싱. JSONP(window.google.ac.h([...])) 와 순수 JSON 모두 처리."""
    raw = (raw or "").strip()
    a, b = raw.find("["), raw.rfind("]")
    if a == -1 or b == -1:
        return []
    data = json.loads(raw[a:b + 1])
    out = []
    for s in (data[1] if len(data) > 1 else []):
        if isinstance(s, list) and s:
            out.append(str(s[0]))
        elif isinstance(s, str):
            out.append(s)
    return out


def _autocomplete(seed: str, count: int = 10) -> list[str]:
    """YouTube 검색창 자동완성 (비공식·무료). 실패하면 빈 리스트."""
    url = "https://suggestqueries.google.com/complete/search"
    for client in ("youtube", "firefox"):
        try:
            params = {"client": client, "q": seed, "hl": "ko", "gl": "KR", "ds": "yt"}
            resp = requests.get(url, params=params, timeout=5,
                                headers={"User-Agent": "Mozilla/5.0"})
            items = [x for x in _parse_suggest(resp.text) if x.strip() and x.strip() != seed.strip()]
            if items:
                return items[:count]
        except Exception as e:
            print(f"[seo_keywords] 자동완성 실패 ({client}, {seed}): {e}", flush=True)
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


# ─────────────────────────────────────────────────────────────────────────────
# 공개 API: 오늘의 추천 주제 (매일 바뀜, 이미 만든 주제는 제외)
# ─────────────────────────────────────────────────────────────────────────────
TOPIC_SEEDS = ["커피", "아메리카노", "라떼", "원두", "에스프레소", "핸드드립", "카페인",
               "콜드브루", "디카페인", "로스팅", "스페셜티 커피", "커피 머신", "라떼아트", "카페"]

_TOPIC_SYSTEM = """당신은 유튜브 쇼츠 채널 '너도나도아는커피'(커피 과학·역사 해설, 60~75초)의 기획자입니다.
사람들이 실제로 검색하는 말(자동완성 목록)을 참고해, 쇼츠 한 편으로 만들 주제 10개를 제안하세요.
- 주제는 "왜/어떻게/차이/비밀" 처럼 궁금증이 생기는 한 줄, 22자 이내.
- SCA 기준 등 사실로 설명할 수 있는 주제만. 가격·매장 추천·제품 광고 주제는 제외.
- [이미 만든 주제]와 겹치거나 비슷한 것은 제외.
- 가능한 한 자동완성 목록(실제 검색어)에서 고르고, 주제 문장에 그 검색어의 핵심 단어를 그대로 살리세요.
- 자동완성 목록에서 착안한 주제는 signal 에 그 검색어를 그대로 적고, 아니면 빈 문자열.
JSON 만 출력: {"topics": [{"topic": "", "signal": ""}]}"""


def _topics_cache_file(day: str) -> Path:
    return Path(f"/tmp/coffee_topics_{day}.json")


def get_daily_topics(anthropic_key: str, made_titles: list = None,
                     refresh: bool = False, max_topics: int = 10) -> dict:
    """
    반환: {"date": "YYYY-MM-DD", "topics": [{"topic", "grade", "source", "signal"}], "signals": n, "note": ""}
    - 매일 날짜가 바뀌면 새로 만든다. refresh=True 면 다른 검색어 묶음으로 다시 만든다.
    - 자동완성을 못 받으면 AI 기획만으로, AI 도 실패하면 기본 목록.
    """
    import datetime
    import random
    day = datetime.date.today().isoformat()
    cache = _topics_cache_file(day)
    if cache.exists() and not refresh:
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except Exception:
            pass

    rnd = random.Random(time.time() if refresh else day)
    # 궁금증형 씨앗으로 실제 검색어를 모으고, 드라마·쇼핑·브랜드 검색어는 미리 걸러낸다
    _q = collect_question_queries(made_titles=made_titles, n_seeds=8, per_seed=10,
                                  max_items=40, refresh_salt=rnd.random())
    signals = [it["topic"] for it in _q["items"]]

    result = {"date": day, "topics": [], "signals": len(signals), "note": ""}
    if anthropic_key:
        try:
            import anthropic
            made = "\n".join(f"- {t}" for t in (made_titles or [])[:40]) or "- 없음"
            sig = "\n".join(f"- {t}" for t in signals) or "- (자동완성 없음: 커피 과학 상식에서 고르세요)"
            user = f"[오늘 날짜] {day}\n[자동완성 검색어]\n{sig}\n\n[이미 만든 주제]\n{made}"
            resp = anthropic.Anthropic(api_key=anthropic_key).messages.create(
                model="claude-sonnet-4-6", max_tokens=1500, system=_TOPIC_SYSTEM,
                messages=[{"role": "user", "content": user}],
            )
            raw = "".join(getattr(b, "text", "") for b in resp.content)
            data = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
            for t in data.get("topics", [])[:max_topics]:
                topic = str(t.get("topic", "")).strip()
                if not topic:
                    continue
                signal = str(t.get("signal", "")).strip()
                result["topics"].append({
                    "topic": topic, "signal": signal,
                    "grade": "A" if signal else "B",
                    "source": "youtube" if signal else "ai",
                })
        except Exception as e:
            result["note"] = f"AI 추천 실패: {e}"
            print(f"[seo_keywords] 오늘의 주제 생성 실패: {e}", flush=True)
    if not result["topics"]:
        pool = _FALLBACK[:]
        rnd.shuffle(pool)
        result["topics"] = pool[:6]
        result["note"] = result["note"] or "ANTHROPIC_API_KEY 없음 — 기본 목록"
    try:
        cache.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 공개 API: 궁금증 검색어 수집 (실시간 트렌드 탭 · 오늘의 추천 주제 공용)
# ─────────────────────────────────────────────────────────────────────────────
# '커피' 한 단어로 자동완성을 조회하면 드라마·노래·쇼핑·밈 검색어만 나온다.
# 그래서 "사람이 궁금할 때 치는 앞부분"을 씨앗으로 여러 개 조회하고,
# 쓸 수 없는 검색어를 규칙으로 걸러 실제 궁금증 검색어만 남긴다.

QUESTION_SEEDS_BY_CHAPTER = {
    "CH01": ["커피 기원", "커피 역사", "커피 유래", "아메리카노 유래", "카페라떼 유래", "커피 처음"],
    "CH02": ["아라비카 로부스타", "예가체프", "게이샤 커피", "원두 산지", "원두 종류", "커피 품종"],
    "CH03": ["내추럴 워시드", "커피 가공", "무산소 발효 커피", "허니 프로세스", "커피 발효"],
    "CH04": ["로스팅 차이", "다크 로스팅", "라이트 로스팅", "원두 볶은 날짜", "원두 로스팅"],
    "CH05": ["에스프레소 왜", "에스프레소 크레마", "에스프레소 샷", "롱블랙 아메리카노", "리스트레토"],
    "CH06": ["핸드드립 물 온도", "핸드드립 분쇄도", "드립커피 차이", "콜드브루 더치", "프렌치프레스"],
    "CH07": ["아이스 아메리카노 왜", "아인슈페너", "플랫화이트 라떼", "카푸치노 라떼 차이", "아포가토"],
    "CH08": ["스페셜티 커피", "카페 아메리카노 왜", "한국 커피 소비", "커피 문화", "바리스타"],
    "CH09": ["커피 마시면", "카페인 몇시간", "디카페인 카페인", "커피 공복", "커피 하루 몇잔",
             "커피 잠", "커피 이뇨", "커피 효능", "커피 부작용", "커피 먹으면"],
    "CH10": ["원두 보관", "원두 분쇄", "모카포트", "커피 그라인더 차이", "캡슐커피 차이"],
}

QUESTION_SEEDS_GENERAL = [
    "커피 마시면", "커피 먹으면", "커피 왜", "커피 차이", "커피 이유", "커피 공복",
    "커피 하루", "커피 잠", "카페인 몇시간", "디카페인", "아메리카노 왜", "아메리카노 차이",
    "라떼 차이", "에스프레소 왜", "원두 보관", "원두 차이", "커피 효능", "커피 부작용",
    "콜드브루 차이", "핸드드립 왜", "아이스 아메리카노 왜", "커피 산미",
]

# 쓸 수 없는 검색어(드라마·노래·쇼핑·브랜드·매장·밈·커피 외 용도)
_BLOCK_WORDS = [
    # 쇼핑·가격
    "추천", "가격", "할인", "최저가", "쿠팡", "구매", "판매", "직구", "리뷰", "후기", "순위",
    "기프티콘", "쿠폰", "이벤트", "신메뉴", "메뉴판", "칼로리표",
    # 브랜드·매장
    "스타벅스", "스벅", "메가", "컴포즈", "빽다방", "이디야", "투썸", "할리스", "폴바셋",
    "블루보틀", "커피빈", "맥심", "카누", "네스프레소", "돌체구스토", "드롱기", "브레빌", "필립스",
    "1호점", "매장", "창업", "알바", "프랜차이즈",
    # 드라마·노래·방송·밈
    "프린스", "드라마", "노래", "가사", "ost", "mr", "브금", "bgm", "playlist", "플레이리스트",
    "할래요", "손경제", "엔톡", "사장님이", "밈", "짤", "asmr", "브이로그", "vlog", "먹방",
    # 커피 외 용도
    "샴푸", "스크럽", "팩", "비누", "염색", "탈색", "향수", "방향제", "탈취", "화분", "비료",
    "그림", "색칠", "네일", "캔들", "디퓨저",
]

# 궁금증·상식 주제의 표시어 — 이 중 하나는 있어야 통과
_QUESTION_MARKERS = [
    "왜", "이유", "차이", "비교", "vs", "마시면", "먹으면", "몇", "언제", "얼마", "하루", "공복",
    "효능", "효과", "부작용", "건강", "잠", "수면", "이뇨", "탈수", "속쓰림", "위염", "배아픈", "역사", "기원", "유래",
    "원리", "과학", "보관", "온도", "분쇄", "추출", "산미", "쓴맛", "방법", "만드는", "뜻", "종류",
    "카페인", "디카페인", "크레마", "로스팅", "품종", "산지", "가공", "내추럴", "워시드", "발효",
]


def _is_usable_query(q: str) -> bool:
    """숏폼 상식 주제로 쓸 수 있는 검색어인지 판단."""
    s = q.strip().lower()
    if len(s.replace(" ", "")) < 4:
        return False
    if any(w in s for w in _BLOCK_WORDS):
        return False
    return any(m in s for m in _QUESTION_MARKERS)


def _norm(t: str) -> str:
    return "".join(str(t).split()).lower()


def collect_question_queries(chapter: str = "", made_titles: list = None,
                             n_seeds: int = 8, per_seed: int = 10,
                             max_items: int = 16, refresh_salt: float = 0.0) -> dict:
    """
    궁금증형 씨앗 여러 개로 YouTube 자동완성을 모아, 쓸 수 있는 검색어만 반환.

    반환: {"seeds": [...], "raw": n, "items": [{"topic", "grade", "source", "signal"}]}
      - topic : 실제 검색어 (클릭하면 주제 입력창에 들어감)
      - 이미 만든 주제와 겹치는 검색어는 제외
    """
    import random
    from concurrent.futures import ThreadPoolExecutor

    code = (chapter or "").split()[0] if chapter else ""
    pool = QUESTION_SEEDS_BY_CHAPTER.get(code) or QUESTION_SEEDS_GENERAL
    rnd = random.Random(refresh_salt or time.time())
    seeds = pool[:] if len(pool) <= n_seeds else rnd.sample(pool, n_seeds)

    with ThreadPoolExecutor(max_workers=min(8, len(seeds))) as ex:
        results = list(ex.map(lambda sd: _autocomplete(sd, count=per_seed), seeds))

    raw = [q for lst in results for q in lst]
    made = [_norm(t) for t in (made_titles or []) if t]
    seen, items = set(), []
    for q in raw:
        k = _norm(q)
        if k in seen or not _is_usable_query(q):
            continue
        if any(k in m or m in k for m in made if len(m) >= 4):
            continue
        seen.add(k)
        items.append({"topic": q.strip(), "grade": "A", "source": "youtube", "signal": q.strip()})
    rnd.shuffle(items)
    return {"seeds": seeds, "raw": len(raw), "items": items[:max_items]}
