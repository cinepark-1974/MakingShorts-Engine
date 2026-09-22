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
MINIMAX_MODEL = "minimax/video-01"   # I2V(first_frame_image) + T2V 통합 모델

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


def _is_rate_limit_error(e: Exception) -> bool:
    """429 rate limit 오류 여부 판별."""
    msg = str(e)
    return "429" in msg or "throttled" in msg or "rate limit" in msg.lower()


def _fetch_image_as_fileobj(url: str) -> io.BytesIO:
    """
    이미지 URL을 서버에서 직접 다운로드해 BytesIO로 반환한다.
    Replicate 추론 서버가 외부 URL에 직접 접근하지 못하는 경우를 방지한다.
    """
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


# ─────────────────────────────────────────────────────────────────────────────
# 공개 API: 단일 클립 생성
# ─────────────────────────────────────────────────────────────────────────────
def generate_single_clip_url(
    replicate_token: str,
    prompt: str,
    image_url: str = "",
    poll_cb=None,
) -> str:
    """
    Replicate MiniMax Video-01로 MP4를 생성하고 공개 URL을 반환한다.

    image_url이 있으면 I2V: first_frame_image로 레퍼런스 이미지 전달 (9:16 유지).
    image_url이 없으면 T2V: prompt만 전달.
    """
    os.environ["REPLICATE_API_TOKEN"] = replicate_token

    use_image_mode = bool(image_url and image_url.strip())

    if use_image_mode:
        image_file = _fetch_image_as_fileobj(image_url)
        inputs = {
            "prompt":            prompt,
            "first_frame_image": image_file,
            "prompt_optimizer":  True,
        }
        print(
            f"[video_replicate] I2V 시작: {MINIMAX_MODEL} | prompt={prompt[:60]}…",
            flush=True,
        )
    else:
        inputs = {
            "prompt":           prompt,
            "prompt_optimizer": True,
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
