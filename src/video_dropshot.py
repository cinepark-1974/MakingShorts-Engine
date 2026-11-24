"""Dropshot AI Studio — 움직이는 컷(이미지 → 6초 영상) 생성.

API 사양 (Dropshot API 콘솔 '빠른 시작' 문서, 2026-11-24 확인):
- base URL: https://openapi.aistudio.dropshot.io/v1
- 인증: Authorization: Bearer ds_live_...   (Secrets: DROPSHOT_API_KEY)
- POST /generations  {"model", "input": {...}}  + Idempotency-Key 헤더 → 202, id(api_…), status queued
- GET  /generations/{id} → status queued|processing|completed|failed|canceled, 완료 시 output[{type,url,...}]
- GET  /models/{model} → 받는 입력 항목과 가격 (여기 없는 항목은 거부됨)
- GET  /balance → 남은 크레딧
- 제한: 워크스페이스당 동시 2개, 분당 생성 요청 20개. 영상은 15초마다 확인.
- 실패·취소는 자동 환불. 크레딧 부족은 402 insufficient_credits.
"""
import json
import threading
import time
import uuid

import requests

BASE = "https://openapi.aistudio.dropshot.io/v1"
MODEL = "minimax/hailuo-2.3-fast"
_SLOTS = threading.BoundedSemaphore(2)          # 동시 2개 제한
_SCHEMA = {}


class DropshotError(RuntimeError):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(f"{code}: {message}")
        self.code, self.retryable = code, retryable


def _h(key: str) -> dict:
    return {"Authorization": f"Bearer {key.strip()}", "Content-Type": "application/json"}


def _check(r: requests.Response) -> dict:
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code >= 400:
        err = (data or {}).get("error") or {}
        raise DropshotError(err.get("code") or f"http_{r.status_code}", err.get("message") or r.text[:200],
                            bool(err.get("retryable")) or r.status_code in (429, 503))
    return data


def balance(key: str) -> dict:
    return _check(requests.get(f"{BASE}/balance", headers=_h(key), timeout=30))


def model_info(key: str, model: str = MODEL) -> dict:
    if model not in _SCHEMA:
        _SCHEMA[model] = _check(requests.get(f"{BASE}/models/{model}", headers=_h(key), timeout=30))
    return _SCHEMA[model]


def _param_names(info: dict) -> set:
    """모델 정보에서 입력 항목 이름을 모은다 (응답 모양이 조금 달라도 이름만 찾는다)."""
    names = set()

    def walk(o):
        if isinstance(o, dict):
            n = o.get("name")
            if isinstance(n, str) and ("type" in o or "required" in o or "description" in o):
                names.add(n)
            for k, v in o.items():
                if k in ("input", "inputs", "parameters", "properties", "input_schema") and isinstance(v, dict):
                    names.update(x for x in v.keys() if isinstance(x, str))
                walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)
    walk(info)
    return names


def build_input(info: dict, prompt: str, image_url: str, resolution: str = "1080p", duration: int = 6) -> dict:
    names = _param_names(info)
    img_key = next((k for k in ("start_frame", "first_frame_image", "image", "image_url", "input_image") if k in names),
                   "start_frame")
    inp = {"prompt": prompt, img_key: image_url}
    if not names or "duration" in names:
        inp["duration"] = duration
    if not names or "resolution" in names:
        inp["resolution"] = resolution
    return inp


def create(key: str, model: str, inp: dict) -> str:
    for attempt in range(6):
        r = requests.post(f"{BASE}/generations", headers={**_h(key), "Idempotency-Key": uuid.uuid4().hex},
                          data=json.dumps({"model": model, "input": inp}), timeout=60)
        if r.status_code in (429, 503):
            time.sleep(min(int(r.headers.get("Retry-After") or 15), 60))
            continue
        return _check(r)["id"]
    raise DropshotError("rate_limited", "생성 요청이 계속 거절됨 (동시·분당 제한)", True)


def wait(key: str, gen_id: str, timeout: int = 900, poll: int = 15) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        g = _check(requests.get(f"{BASE}/generations/{gen_id}", headers=_h(key), timeout=30))
        st = g.get("status")
        if st == "completed":
            return g
        if st in ("failed", "canceled"):
            err = g.get("error") or {}
            raise DropshotError(err.get("code") or st, err.get("message") or st)
        time.sleep(poll)
    raise DropshotError("timeout", f"{timeout}초 안에 끝나지 않음 ({gen_id})")


def generate_clip_url(key: str, prompt: str, image_url: str, resolution: str = "1080p", info: dict = None) -> str:
    """이미지(공개 URL) → 6초 영상 URL. 동시 2개까지만 돌린다."""
    mi = model_info(key)
    inp = build_input(mi, prompt, image_url, resolution)
    with _SLOTS:
        gid = create(key, MODEL, inp)
        print(f"[video_dropshot] 생성 시작 {gid} | 항목={sorted(inp)}", flush=True)
        g = wait(key, gid)
    out = next((o for o in g.get("output") or [] if o.get("type") == "video" and o.get("url")), None)
    if not out:
        raise DropshotError("no_output", f"완료됐지만 영상 URL이 없음: {json.dumps(g)[:300]}")
    if info is not None:
        info.update(provider="dropshot", id=gid, credits=g.get("credits") or g.get("cost"))
    return out["url"]


def test_report(key: str) -> dict:
    """무료 확인: 남은 크레딧 + 모델 입력 항목·가격 (영상은 만들지 않음)."""
    rep = {"ok": False}
    try:
        rep["balance"] = balance(key)
        rep["model"] = model_info(key)
        rep["params"] = sorted(_param_names(rep["model"]))
        rep["ok"] = True
    except Exception as e:
        rep["error"] = str(e)[:300]
    return rep
