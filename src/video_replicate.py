# src/video_replicate.py
# 너도나도아는커피 숏폼 팩토리 — Replicate MiniMax Video-01 비디오 생성기
# wavespeedai/wan-2.1 → minimax/video-01 교체 (E002 지속 오류 대응)
# replicate.run() → predictions.create() + 폴링 방식 (Streamlit 연결 유지)
# API 키: REPLICATE_API_TOKEN

import io
import os
import sys
import time
import requests
import replicate

# ── Replicate 모델 ID ──────────────────────────────────────────────────────────
MINIMAX_MODEL = "minimax/video-01"   # I2V(first_frame_image) + T2V 통합 모델 (2024 · 되돌림용)
HAILUO_MODEL = "minimax/hailuo-2.3-fast"   # 2026-10 기본 — 그림 → 영상 전용, 1080p 6초
VIDEO_MODELS = {
    "hailuo-2.3-fast": "Hailuo 2.3 Fast (기본 · 1080p 6초)",
    "video-01":        "video-01 (예전 모델)",
}
DEFAULT_VIDEO_MODEL = "hailuo-2.3-fast"
_SCHEMA_CACHE: dict = {}

# 재시도 및 폴링 설정
_MAX_RETRIES      = 5    # 최대 재시도 횟수 (429 전용)
_RETRY_DELAY      = 15   # 429 대기 기본값 (초)
_INTER_SCENE      = 5    # 씬 간 간격 (초)
_POLL_INTERVAL    = 10   # 폴링 간격 (초) — minimax 평균 3~5분 소요
_MAX_POLL_SECONDS = 600  # 폴링 타임아웃 (10분) — 초과 시 해당 씬 error 처리 후 다음 씬으로


# ─────────────────────────────────────────────────────────────────────────────
# 내부 헬퍼
# ─────────────────────────────────────────────────────────────────────────────
def _to_url(output) -> str:
    """FileOutput / 리스트 / 이터레이터 / 문자열 모두 대응해 URL을 반환한다."""
    if hasattr(output, "url"):
        url = str(output.url).strip()
        if url.startswith("http"):
            return url
    if hasattr(output, "__iter__") and not isinstance(output, (str, bytes)):
        items = list(output)
        if items:
            last = items[-1]
            if hasattr(last, "url"):
                url = str(last.url).strip()
            else:
                url = str(last).strip()
            if url.startswith("http"):
                return url
        raise ValueError("Replicate 출력이 비어 있습니다.")
    url = str(output).strip()
    if not url.startswith("http"):
        raise ValueError(f"유효하지 않은 Replicate 출력 URL: {url!r}")
    return url


class InsufficientCreditError(RuntimeError):
    """Replicate 크레딧 부족(402) — 재시도해도 소용없으므로 배치 전체를 즉시 중단한다."""


def _is_credit_error(e: Exception) -> bool:
    """402 크레딧 부족 오류 여부 판별."""
    msg = str(e)
    return "402" in msg or "Insufficient credit" in msg or "insufficient credit" in msg


def _is_rate_limit_error(e: Exception) -> bool:
    """429 rate limit 오류 여부 판별."""
    msg = str(e)
    return "429" in msg or "throttled" in msg or "rate limit" in msg.lower()


def _fetch_image_as_fileobj(url: str) -> io.BytesIO:
    """
    이미지 URL을 서버에서 직접 다운로드해 BytesIO로 반환한다.
    Replicate 추론 서버가 외부 URL에 직접 접근하지 못하는 경우를 방지한다.
    """
    if url and not url.startswith("http") and os.path.exists(url):   # 로컬 보관본
        with open(url, "rb") as f:
            buf = io.BytesIO(f.read())
        buf.name = os.path.basename(url)
        print(f"[video_replicate] 로컬 이미지 사용 → {url}", flush=True)
        return buf
    print(f"[video_replicate] 이미지 다운로드 시작 → {url[:80]}", flush=True)
    try:
        resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        buf = io.BytesIO(resp.content)
        buf.name = "image.jpg"
        print(
            f"[video_replicate] 이미지 다운로드 완료 — {len(resp.content):,} bytes "
            f"| Content-Type: {resp.headers.get('Content-Type', 'unknown')}",
            flush=True,
        )
        return buf
    except Exception as e:
        print(f"[video_replicate] 이미지 다운로드 실패: {e}", flush=True)
        raise RuntimeError(f"레퍼런스 이미지 다운로드 실패 ({url[:60]}…): {e}") from e


# ─────────────────────────────────────────────────────────────────────────────
# 핵심: 비동기 예측 생성 + 폴링 (Streamlit 연결 유지)
# ─────────────────────────────────────────────────────────────────────────────
def _run_model_with_polling(
    model: str,
    inputs: dict,
    poll_cb=None,       # poll_cb(elapsed_sec: int) — 폴링 중간 상태 보고용
) -> str:
    """
    replicate.predictions.create() 로 예측을 시작하고,
    _POLL_INTERVAL 초마다 상태를 확인해 완료될 때까지 대기한다.

    replicate.run() 대신 이 방식을 사용하는 이유:
    - replicate.run()은 내부적으로 동기 블로킹 → Streamlit WebSocket 연결이 끊어짐
    - predictions.create() + reload() 폴링은 루프마다 제어권이 반환되어
      poll_cb 호출을 통해 Streamlit UI 갱신이 가능하다.

    429 발생 시 지수 백오프 재시도.
    """
    last_error = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            # 예측 시작 (즉시 반환)
            prediction = replicate.predictions.create(
                model=model,
                input=inputs,
            )
            print(
                f"[video_replicate] 예측 시작 id={prediction.id} | 모델={model}",
                flush=True,
            )

            # 폴링 루프
            elapsed = 0
            while prediction.status not in ("succeeded", "failed", "canceled"):
                # 타임아웃: 10분 초과 시 예측 취소 후 오류로 처리
                if elapsed >= _MAX_POLL_SECONDS:
                    print(
                        f"[video_replicate] ⏰ 타임아웃 ({_MAX_POLL_SECONDS}초) "
                        f"— 예측 취소: id={prediction.id}",
                        flush=True,
                    )
                    try:
                        prediction.cancel()
                    except Exception:
                        pass
                    raise RuntimeError(
                        f"폴링 타임아웃 {_MAX_POLL_SECONDS}초 초과 "
                        f"(Replicate id={prediction.id})"
                    )
                time.sleep(_POLL_INTERVAL)
                elapsed += _POLL_INTERVAL
                prediction.reload()
                print(
                    f"[video_replicate] 폴링 {elapsed}초 경과 | 상태={prediction.status}",
                    flush=True,
                )
                if poll_cb:
                    poll_cb(elapsed)

            if prediction.status == "succeeded":
                url = _to_url(prediction.output)
                print(f"[video_replicate] 완료 ({elapsed}초) → {url[:80]}", flush=True)
                return url
            else:
                err = getattr(prediction, "error", "알 수 없는 오류")
                raise RuntimeError(
                    f"Replicate 예측 실패 (status={prediction.status}): {err}"
                )

        except Exception as e:
            last_error = e
            if _is_credit_error(e):
                raise InsufficientCreditError(
                    "Replicate 크레딧이 부족합니다. "
                    "https://replicate.com/account/billing 에서 크레딧을 충전한 뒤 "
                    "몇 분 후 다시 시도하세요."
                ) from e
            if _is_rate_limit_error(e):
                wait = _RETRY_DELAY * attempt
                print(
                    f"[video_replicate] 429 rate limit (시도 {attempt}/{_MAX_RETRIES}) "
                    f"→ {wait}초 대기 후 재시도…",
                    flush=True,
                )
                time.sleep(wait)
            else:
                raise

    raise RuntimeError(
        f"Replicate 429 rate limit: {_MAX_RETRIES}회 재시도 실패 — {last_error}"
    )


# 스케치 화풍 고정 문구 (MACHINE / EXTRACTION / SCIENCE_DATA 씬)
STYLE_LOCK_SUFFIX = (
    "pen-and-ink watercolor sketch on paper in every frame, bold black ink contour lines "
    "and watercolor washes stay drawn on the paper, the paper grain stays visible, "
    "only small elements move gently (liquid, steam, light, curtains, fabric), slow camera push-in, "
    "no photorealism, no 3D render, no text"
)


# ─────────────────────────────────────────────────────────────────────────────
# 공개 API: 단일 클립 생성
# ─────────────────────────────────────────────────────────────────────────────
def model_input_schema(replicate_token: str, model: str = HAILUO_MODEL) -> dict:
    """Replicate 가 공개하는 모델 입력 항목(openapi)을 읽는다 — 항목 이름을 추측하지 않기 위해.
    반환: {항목이름: {"type", "enum", "default", "description"}} · 실패하면 빈 dict."""
    if model in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[model]
    try:
        r = requests.get(f"https://api.replicate.com/v1/models/{model}",
                         headers={"Authorization": f"Bearer {replicate_token}"}, timeout=20)
        r.raise_for_status()
        api = ((r.json().get("latest_version") or {}).get("openapi_schema") or {})
        comps = (api.get("components") or {}).get("schemas") or {}
        props = (comps.get("Input") or {}).get("properties") or {}
        out = {}
        for name, p in props.items():
            info = {"type": p.get("type", ""), "enum": p.get("enum"), "default": p.get("default"),
                    "description": (p.get("description") or "")[:160]}
            for ref in (p.get("allOf") or []):          # enum 이 별도 정의로 빠져 있는 경우
                key = (ref.get("$ref") or "").split("/")[-1]
                if key in comps:
                    info["enum"] = comps[key].get("enum")
                    info["type"] = comps[key].get("type", info["type"])
            out[name] = info
        _SCHEMA_CACHE[model] = out
        return out
    except Exception as e:
        print(f"[video_replicate] 입력 항목 조회 실패 ({model}): {e}", flush=True)
        return {}


def _pick(enum, want):
    if not enum:
        return want
    for w in (want, str(want)):
        if w in enum:
            return w
    return None


def _hailuo_inputs(replicate_token: str, prompt: str, image_file, optimizer: bool) -> dict:
    props = model_input_schema(replicate_token, HAILUO_MODEL)
    img_field = next((f for f in ("first_frame_image", "image", "start_image", "input_image") if f in props),
                     "first_frame_image")
    inputs = {"prompt": prompt, img_field: image_file}
    if not props:                               # 항목을 못 읽었으면 MiniMax 공통 이름으로
        inputs.update(duration=6, resolution="1080p", prompt_optimizer=optimizer)
        return inputs
    if "duration" in props:
        d = _pick(props["duration"].get("enum"), 6)
        if d is not None:
            inputs["duration"] = d
    if "resolution" in props:
        r = _pick(props["resolution"].get("enum"), "1080p")
        if r is not None:
            inputs["resolution"] = r
    if "prompt_optimizer" in props:
        inputs["prompt_optimizer"] = optimizer
    return inputs


def generate_single_clip_url(
    replicate_token: str,
    prompt: str,
    image_url: str = "",
    poll_cb=None,
    style_lock: bool = False,
    prompt_optimizer=None,
    model_pref: str = "",
    info: dict = None,
) -> str:
    """
    Replicate MiniMax Video-01로 MP4를 생성하고 공개 URL을 반환한다.

    image_url이 있으면 I2V: first_frame_image로 레퍼런스 이미지 전달 (9:16 유지).
    image_url이 없으면 T2V: prompt만 전달.
    """
    os.environ["REPLICATE_API_TOKEN"] = replicate_token

    use_image_mode = bool(image_url and image_url.strip())

    # 스케치 일러스트 씬: 첫 프레임의 펜·잉크 수채화 화풍을 영상 내내 유지하도록 고정.
    # prompt_optimizer 가 켜져 있으면 프롬프트가 '시네마틱 실사' 쪽으로 재작성되므로 끈다.
    optimizer = True
    if style_lock:
        prompt = (
            prompt.rstrip(" .,") + ", " + STYLE_LOCK_SUFFIX
        )
        optimizer = False
    if prompt_optimizer is not None:      # HASIRA 루프: 카메라 고정 지시가 재작성되지 않게 끔
        optimizer = bool(prompt_optimizer)

    model_pref = model_pref or DEFAULT_VIDEO_MODEL
    if info is not None:
        info["model"] = "video-01"
    if use_image_mode and model_pref == "hailuo-2.3-fast":
        try:
            image_file = _fetch_image_as_fileobj(image_url)
            inputs = _hailuo_inputs(replicate_token, prompt, image_file, optimizer)
            print(f"[video_replicate] I2V 시작: {HAILUO_MODEL} | 항목={sorted(inputs)} | "
                  f"prompt={prompt[:60]}…", flush=True)
            url = _run_model_with_polling(HAILUO_MODEL, inputs, poll_cb=poll_cb)
            if info is not None:
                info["model"] = "hailuo-2.3-fast"
            return url
        except InsufficientCreditError:
            raise
        except Exception as e:
            if "타임아웃" in str(e):
                raise
            print(f"[video_replicate] Hailuo 2.3 Fast 실패 → video-01 로 다시 만듭니다: {e}", flush=True)
            if info is not None:
                info["fallback_reason"] = str(e)[:300]

    if use_image_mode:
        image_file = _fetch_image_as_fileobj(image_url)
        inputs = {
            "prompt":            prompt,
            "first_frame_image": image_file,
            "prompt_optimizer":  optimizer,
        }
        print(
            f"[video_replicate] I2V 시작: {MINIMAX_MODEL} | prompt={prompt[:60]}…",
            flush=True,
        )
    else:
        inputs = {
            "prompt":           prompt,
            "prompt_optimizer": optimizer,
        }
        print(
            f"[video_replicate] T2V 시작: {MINIMAX_MODEL} | prompt={prompt[:60]}…",
            flush=True,
        )

    return _run_model_with_polling(MINIMAX_MODEL, inputs, poll_cb=poll_cb)


# ─────────────────────────────────────────────────────────────────────────────
# 공개 API: 다중 씬 순차 생성
# ─────────────────────────────────────────────────────────────────────────────
def generate_clips_parallel_cdn(
    replicate_token: str,
    scenes: list,
    max_workers: int = 1,       # 하위 호환용 — 순차 처리 고정
    progress_callback=None,     # (scene_no, status_str) — 완료/오류 시 호출
    poll_callback=None,         # (scene_no, elapsed_sec) — 폴링 중간 호출
) -> list:
    """
    여러 씬을 순차로 생성하고 CDN URL을 scene["video_url"]에 기록한다.

    Args:
        replicate_token  : REPLICATE_API_TOKEN
        scenes           : state["scenes"] 리스트
        max_workers      : 미사용 (하위 호환용)
        progress_callback: (scene_no, status) 완료/오류 시 호출
        poll_callback    : (scene_no, elapsed_sec) 폴링 중간 상태 보고 (Streamlit UI 갱신용)
    """
    targets = [s for s in scenes if s.get("status") in ("pending", "error")]
    if not targets:
        return scenes

    scene_map = {s["scene_no"]: s for s in scenes}

    for i, scene in enumerate(targets):
        sno     = scene["scene_no"]
        ref_img = scene.get("reference_image_url", "")

        if i > 0:
            print(
                f"[video_replicate] 씬 간 {_INTER_SCENE}초 대기 (rate limit 예방)…",
                flush=True,
            )
            time.sleep(_INTER_SCENE)

        # 폴링 중간 콜백 래퍼
        def _poll_cb(elapsed: int, _sno=sno):
            if poll_callback:
                poll_callback(_sno, elapsed)

        try:
            cdn_url = generate_single_clip_url(
                replicate_token=replicate_token,
                prompt=scene.get("flow_prompt", ""),
                image_url=ref_img,
                poll_cb=_poll_cb,
            )
            result = {"scene_no": sno, "status": "done", "video_url": cdn_url}

        except InsufficientCreditError as e:
            # 크레딧 부족: 현재 씬은 '대기'로 되돌리고 배치 전체 중단 (남은 씬 헛시도 방지)
            print(f"[video_replicate] 크레딧 부족 — 배치 중단", file=sys.stderr, flush=True)
            scene_map[sno]["status"] = "pending"
            raise

        except Exception as e:
            print(f"[video_replicate] 씬 #{sno:02d} 오류: {e}", file=sys.stderr, flush=True)
            result = {"scene_no": sno, "status": "error", "error_msg": str(e)}

        target = scene_map[sno]
        target["status"] = result["status"]
        if result["status"] == "done":
            target["video_url"] = result["video_url"]
            target.pop("error_msg", None)
        else:
            target["error_msg"] = result.get("error_msg", "알 수 없는 오류")

        if progress_callback:
            progress_callback(sno, result["status"])

    return scenes
