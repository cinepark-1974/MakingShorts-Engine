# src/video_replicate.py
# 너도나도아는커피 숏폼 팩토리 — Replicate Wan 2.1 비디오 생성기
# fal.ai 접속 불가 시 대안으로 사용. API 키: REPLICATE_API_TOKEN

import os
import requests
import replicate

# ── Replicate 모델 ID ──────────────────────────────────────────────────────────
# Wan 2.1 T2V 480p — text-to-video
# 배포 시점에 https://replicate.com/models 에서 최신 ID 확인 권장
WAN_T2V_MODEL  = "wavespeedai/wan-2.1-t2v-480p"
WAN_I2V_MODEL  = "wavespeedai/wan-2.1-i2v-480p"   # image-to-video

DEFAULT_DURATION = 5   # 초
DEFAULT_ASPECT   = "9:16"


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
        model  = WAN_I2V_MODEL
        inputs = {
            "prompt":       prompt,
            "image":        image_url,
            "duration":     DEFAULT_DURATION,
            "aspect_ratio": DEFAULT_ASPECT,
        }
    else:
        model  = WAN_T2V_MODEL
        inputs = {
            "prompt":       prompt,
            "duration":     DEFAULT_DURATION,
            "aspect_ratio": DEFAULT_ASPECT,
        }

    output = replicate.run(model, input=inputs)

    # Replicate 반환값: URL 문자열 또는 [URL] 리스트
    if isinstance(output, list):
        return str(output[0])
    return str(output)


# ─────────────────────────────────────────────────────────────────────────────
# 공개 API: 다중 씬 병렬 생성 — CDN URL 반환
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
