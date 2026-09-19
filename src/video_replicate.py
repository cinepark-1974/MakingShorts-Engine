# src/video_replicate.py
# 너도나도아는커피 숏폼 팩토리 — Replicate Wan 2.1 비디오 생성기
# fal.ai 접속 불가 시 대안으로 사용. API 키: REPLICATE_API_TOKEN

import os
import sys
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


# ─────────────────────────────────────────────────────────────────────────────
# 내부 헬퍼: Replicate 출력 → URL 추출
# ─────────────────────────────────────────────────────────────────────────────
def _to_url(output) -> str:
    """FileOutput / 리스트 / 이터레이터 / 문자열 모두 대응해 URL을 반환한다."""
    # 이터레이터/제너레이터인 경우 모든 값을 소비해서 마지막(영상) 항목 획득
    if hasattr(output, "__iter__") and not isinstance(output, (str, bytes)):
        items = list(output)
        if items:
            output = items[-1]   # 마지막이 영상인 경우가 일반적
        else:
            raise ValueError("Replicate 출력이 비어 있습니다.")

    url = str(output).strip()
    if not url.startswith("http"):
        raise ValueError(f"유효하지 않은 Replicate 출력 URL: {url!r}")
    return url


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

    image_url이 있으면 image-to-video, 없으면 text-to-video 모드.

    Returns:
        str : Replicate CDN 공개 URL
    """
    os.environ["REPLICATE_API_TOKEN"] = replicate_token

    use_image_mode = bool(image_url and image_url.strip())

    if use_image_mode:
        # Image-to-Video: aspect_ratio 대신 max_area로 해상도 지정
        inputs = {
            "prompt":    prompt,
            "image":     image_url,
            "frames":    DEFAULT_NUM_FRAMES,   # ← duration 아님
            "max_area":  DEFAULT_MAX_AREA,     # "480x832" = 9:16
            "fps":       DEFAULT_FPS,
        }
        model = WAN_I2V_MODEL
    else:
        # Text-to-Video: num_frames + aspect_ratio
        inputs = {
            "prompt":       prompt,
            "aspect_ratio": DEFAULT_ASPECT,
            "num_frames":   DEFAULT_NUM_FRAMES,  # ← duration 아님
            "fps":          DEFAULT_FPS,
        }
        model = WAN_T2V_MODEL

    print(f"[video_replicate] {model} 호출 | prompt={prompt[:60]}...", flush=True)
    output = replicate.run(model, input=inputs)
    url = _to_url(output)
    print(f"[video_replicate] 완료 → {url[:80]}", flush=True)
    return url


# ─────────────────────────────────────────────────────────────────────────────
# 공개 API: 다중 씬 병렬 생성 — CDN URL 저장
# ─────────────────────────────────────────────────────────────────────────────
def generate_clips_parallel_cdn(
    replicate_token: str,
    scenes: list,
    max_workers: int = 4,
    progress_callback=None,
) -> list:
    """
    여러 씬을 병렬로 생성하고 CDN URL을 scene["video_url"]에 기록한다.

    Args:
        replicate_token   : REPLICATE_API_TOKEN
        scenes            : state["scenes"] 리스트
        max_workers       : 동시 생성 스레드 수 (기본 4)
        progress_callback : (scene_no, status) 를 받는 콜백 (선택)

    Returns:
        list : 업데이트된 scenes 리스트
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    targets = [s for s in scenes if s.get("status") in ("pending", "error")]
    if not targets:
        return scenes

    scene_map = {s["scene_no"]: s for s in scenes}

    def _generate_one(scene: dict) -> dict:
        sno     = scene["scene_no"]
        ref_img = scene.get("reference_image_url", "")
        try:
            cdn_url = generate_single_clip_url(
                replicate_token=replicate_token,
                prompt=scene.get("flow_prompt", ""),
                image_url=ref_img,
            )
            return {"scene_no": sno, "status": "done", "video_url": cdn_url}
        except Exception as e:
            # 에러 메시지를 Streamlit Cloud 로그에도 출력
            print(f"[video_replicate] 씬 #{sno:02d} 오류: {e}", file=sys.stderr, flush=True)
            return {"scene_no": sno, "status": "error", "error_msg": str(e)}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_generate_one, s): s["scene_no"] for s in targets}
        for future in as_completed(futures):
            result = future.result()
            sno    = result["scene_no"]
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
