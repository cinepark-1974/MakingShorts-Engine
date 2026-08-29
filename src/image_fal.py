# src/image_fal.py
# 너도나도아는커피 숏폼 팩토리 — Fal.ai FLUX Schnell 레퍼런스 이미지 생성기
# 생성된 이미지는 fal.ai CDN URL로 저장 (로컬 다운로드 없음 → Reboot 후에도 상태 유지)

import os
import fal_client


# ── 모델 ID ───────────────────────────────────────────────────────────────────
# flux/schnell : 컷당 3~5초, 안정적, 9:16 커스텀 사이즈 지원
# negative_prompt / guidance_scale 미지원 — 프롬프트로 제어
FLUX_MODEL = "fal-ai/flux/schnell"


def generate_reference_image(
    fal_key: str,
    image_prompt: str,
    output_path: str = "",   # 하위 호환용 — 더 이상 로컬 저장 안 함
    width: int = 720,
    height: int = 1280,
) -> str:
    """
    Fal.ai FLUX Schnell로 레퍼런스 이미지를 생성하고 fal CDN URL을 반환한다.
    로컬에 다운로드하지 않으므로 Streamlit Reboot 후에도 URL이 유효하다.

    Args:
        fal_key      : FAL_KEY (Fal.ai API 키)
        image_prompt : 씬별 프롬프트 (영문) — image_prompt 없으면 flow_prompt 사용
        output_path  : (미사용, 하위 호환 유지용)
        width        : 이미지 너비 (기본 720 — 9:16 세로)
        height       : 이미지 높이 (기본 1280 — 9:16 세로)

    Returns:
        str : fal.ai CDN 공개 이미지 URL
    """
    os.environ["FAL_KEY"] = fal_key

    # flux/schnell 지원 파라미터만 사용 (negative_prompt, guidance_scale 없음)
    arguments = {
        "prompt":                image_prompt,
        "image_size":            {"width": width, "height": height},
        "num_inference_steps":   4,   # schnell 최적값 (1~12)
        "num_images":            1,
        "output_format":         "jpeg",
        "enable_safety_checker": True,
    }

    handler = fal_client.submit(FLUX_MODEL, arguments=arguments)
    result  = handler.get()

    return result["images"][0]["url"]   # fal CDN URL 반환


def generate_images_for_scenes(fal_key: str, scenes: list, project_dir: str = "") -> list:
    """
    여러 씬의 프롬프트를 순차적으로 FLUX Schnell로 생성한다.
    image_status가 'done'인 씬은 건너뛴다.
    image_prompt 없으면 flow_prompt를 사용한다.
    결과는 fal CDN URL로 저장한다.
    """
    for scene in scenes:
        # image_prompt 우선, 없으면 flow_prompt 사용
        prompt = (scene.get("image_prompt") or scene.get("flow_prompt") or "").strip()
        if not prompt:
            continue
        if scene.get("image_status") == "done":
            continue

        scene["image_status"] = "generating"

        try:
            url = generate_reference_image(
                fal_key=fal_key,
                image_prompt=prompt,
            )
            scene["image_path"]          = url   # fal CDN URL
            scene["image_status"]        = "done"
            scene["reference_image_url"] = url
            scene.pop("image_error", None)

        except Exception as e:
            scene["image_status"] = "error"
            scene["image_error"]  = str(e)

    return scenes
