# src/video_replicate.py
# 너도나도아는커피 숏폼 팩토리 — Replicate Wan 2.1 비디오 생성기
# fal.ai 접속 불가 시 대안으로 사용. API 키: REPLICATE_API_TOKEN

import io
import os
import sys
import time
import requests
import replicate

# ── Replicate 모델 ID ──────────────────────────────────────────────────────────
WAN_T2V_MODEL = "wavespeedai/wan-2.1-t2v-480p"   # text-to-video
WAN_I2V_MODEL = "wavespeedai/wan-2.1-i2v-480p"   # image-to-video

# 기본 생성 옵션 (5초 × 16fps = 80프레임)
DEFAULT_FPS        = 16
DEFAULT_NUM_FRAMES = 5 * DEFAULT_FPS   # 80
DEFAULT_ASPECT     = "9:16"
DEFAULT_MAX_AREA   = "480x832"         # I2V: width×height (세로 9:16)

# 429 재시도 설정 ($5 미만 계정: burst=1, 6 req/min 제한)
_MAX_RETRIES  = 5       # 최대 재시도 횟수
_RETRY_DELAY  = 15      # 기본 대기 시간 (초) — 429 응답에 포함된 시간보다 여유 있게
_INTER_SCENE  = 5       # 씬 간 간격 (초) — rate limit 예방용


# ─────────────────────────────────────────────────────────────────────────────
# 내부 헬퍼: Replicate 출력 → URL 추출
# ─────────────────────────────────────────────────────────────────────────────
def _to_url(output) -> str:
    """FileOutput / 리스트 / 이터레이터 / 문자열 모두 대응해 URL을 반환한다."""
    # FileOutput 객체: .url 속성 우선 (Replicate Python client >= 1.0)
    if hasattr(output, "url"):
        url = str(output.url).strip()
        if url.startswith("http"):
            return url

    # 이터레이터/제너레이터: 마지막 항목 (영상 URL)
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
    이미지 URL을 Streamlit 서버에서 직접 다운로드해 BytesIO로 반환한다.

    Replicate 추론 서버가 외부 URL(Unsplash, FLUX CDN 등)에 직접 접근하지
    못해 E002가 발생하는 경우를 방지한다.
    Replicate Python client는 BytesIO를 받으면 자체 스토리지에 업로드한 뒤
    추론 서버에 내부 URL을 전달하므로 외부 접근 문제가 없어진다.
    """
    print(f"[video_replicate] 이미지 다운로드 시작 → {url[:80]}", flush=True)
    try:
        resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        buf = io.BytesIO(resp.content)
        buf.name = "image.jpg"   # Replicate client가 Content-Type 추론에 사용
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
# 내부 헬퍼: 모델 실행 + 429 재시도
# ─────────────────────────────────────────────────────────────────────────────
def _run_model_with_retry(model: str, inputs: dict) -> str:
    """
    replicate.run()을 실행하고 429 rate limit 시 지수 백오프로 재시도한다.
    성공 시 CDN URL을 반환한다.
    """
    last_error = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            output = replicate.run(model, input=inputs)
            url = _to_url(output)
            print(f"[video_replicate] 완료 → {url[:80]}", flush=True)
            return url
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
# 공개 API: 단일 클립 생성 — CDN URL 반환
# ─────────────────────────────────────────────────────────────────────────────
def generate_single_clip_url(
    replicate_token: str,
    prompt: str,
    image_url: str = "",
) -> str:
    """
    Replicate Wan 2.1로 MP4를 생성하고 공개 URL을 반환한다.

    image_url이 있으면 I2V(image-to-video) 시도 → E002 발생 시 T2V 자동 전환.
    image_url이 없으면 처음부터 T2V.
    429 Rate limit 발생 시 최대 _MAX_RETRIES 회 자동 재시도.

    Returns:
        str : Replicate CDN 공개 URL
    """
    os.environ["REPLICATE_API_TOKEN"] = replicate_token

    use_image_mode = bool(image_url and image_url.strip())

    # ── I2V 시도 ──────────────────────────────────────────────────────────────
    if use_image_mode:
        image_obj = _fetch_image_as_fileobj(image_url)
        i2v_inputs = {
            "prompt": prompt,
            "image":  image_obj,
        }
        print(
            f"[video_replicate] I2V 시도: {WAN_I2V_MODEL} | prompt={prompt[:60]}…",
            flush=True,
        )
        try:
            return _run_model_with_retry(WAN_I2V_MODEL, i2v_inputs)
        except Exception as e:
            if "E002" in str(e):
                # I2V 모델 내부 오류(E002) → T2V 자동 전환
                print(
                    f"[video_replicate] I2V E002 발생 → T2V 모드로 자동 전환",
                    flush=True,
                )
            else:
                raise   # E002 외 오류는 그대로 전파

    # ── T2V (I2V 없음 또는 E002 폴백) ─────────────────────────────────────────
    t2v_inputs = {
        "prompt":       prompt,
        "aspect_ratio": DEFAULT_ASPECT,
        "num_frames":   DEFAULT_NUM_FRAMES,
        "fps":          DEFAULT_FPS,
    }
    print(
        f"[video_replicate] T2V 실행: {WAN_T2V_MODEL} | prompt={prompt[:60]}…",
        flush=True,
    )
    return _run_model_with_retry(WAN_T2V_MODEL, t2v_inputs)


# ─────────────────────────────────────────────────────────────────────────────
# 공개 API: 다중 씬 순차 생성 — CDN URL 저장
# (병렬 처리 제거 — $5 미만 계정 burst=1 rate limit 대응)
# ─────────────────────────────────────────────────────────────────────────────
def generate_clips_parallel_cdn(
    replicate_token: str,
    scenes: list,
    max_workers: int = 1,     # burst=1 계정 대응: 항상 순차 처리
    progress_callback=None,
) -> list:
    """
    여러 씬을 순차로 생성하고 CDN URL을 scene["video_url"]에 기록한다.

    ※ max_workers 파라미터는 하위 호환을 위해 유지하지만 항상 1로 동작합니다.
       Replicate $5 미만 계정은 burst=1 제한이 있어 병렬 처리 시 전부 429.

    Args:
        replicate_token   : REPLICATE_API_TOKEN
        scenes            : state["scenes"] 리스트
        max_workers       : 미사용 (하위 호환용)
        progress_callback : (scene_no, status) 를 받는 콜백 (선택)

    Returns:
        list : 업데이트된 scenes 리스트
    """
    targets = [s for s in scenes if s.get("status") in ("pending", "error")]
    if not targets:
        return scenes

    scene_map = {s["scene_no"]: s for s in scenes}

    for i, scene in enumerate(targets):
        sno     = scene["scene_no"]
        ref_img = scene.get("reference_image_url", "")

        # 씬 간 간격 — 첫 씬은 대기 없음
        if i > 0:
            print(
                f"[video_replicate] 씬 간 {_INTER_SCENE}초 대기 (rate limit 예방)…",
                flush=True,
            )
            time.sleep(_INTER_SCENE)

        try:
            cdn_url = generate_single_clip_url(
                replicate_token=replicate_token,
                prompt=scene.get("flow_prompt", ""),
                image_url=ref_img,
            )
            result = {"scene_no": sno, "status": "done", "video_url": cdn_url}

        except Exception as e:
            print(f"[video_replicate] 씬 #{sno:02d} 오류: {e}", file=sys.stderr, flush=True)
            result = {"scene_no": sno, "status": "error", "error_msg": str(e)}

        # scene dict 업데이트
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
