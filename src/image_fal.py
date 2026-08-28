# src/image_fal.py
# 너도나도아는커피 숏폼 팩토리 — Fal.ai Flux Pro 레퍼런스 이미지 생성기
# Kling image-to-video의 첫 프레임용 이미지를 자동 생성한다.

import os
import requests
import fal_client


# ── 모델 ID ───────────────────────────────────────────────────────────────────
FLUX_MODEL = "fal-ai/flux-pro/v1.1"

# ── 공통 NEGATIVE 조건 (모든 씬에 적용) ──────────────────────────────────────
NEGATIVE_PROMPT = (
    "text, letters, korean characters, words, watermark, logo, "
    "human face, portrait, person, people, CGI, 3d render, plastic, "
    "blurry, ugly, deformed, gross, slimy, uncanny valley"
)


def generate_reference_image(
    fal_key: str,
    image_prompt: str,
    output_path: str,
    width: int = 720,
    height: int = 1280,
) -> str:
    """
    Fal.ai Flux Pro v1.1로 레퍼런스 이미지(PNG)를 생성하여 로컬에 저장한다.

    Args:
        fal_key      : FAL_KEY (Fal.ai API 키)
        image_prompt : Claude가 생성한 씬별 image_prompt (영문)
        output_path  : 저장할 .png 파일 경로
        width        : 이미지 너비 (기본 720 — 9:16 세로)
        height       : 이미지 높이 (기본 1280 — 9:16 세로)

    Returns:
        str : 저장된 로컬 파일 경로 (= output_path)

    Raises:
        KeyError          : Fal.ai 응답에 images[0].url 필드가 없을 때
        requests.HTTPError: 이미지 파일 다운로드 실패 시
    """
    os.environ["FAL_KEY"] = fal_key

    arguments = {
        "prompt": image_prompt,
        "negative_prompt": NEGATIVE_PROMPT,
        "image_size": {"width": width, "height": height},
        "num_inference_steps": 28,
        "guidance_scale": 3.5,
        "num_images": 1,
        "output_format": "png",
        "enable_safety_checker": True,
    }

    handler = fal_client.submit(FLUX_MODEL, arguments=arguments)
    result  = handler.get()

    image_url = result["images"][0]["url"]

    # 이미지 다운로드 → 로컬 저장
    resp = requests.get(image_url, timeout=60)
    resp.raise_for_status()

    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(output_path, "wb") as f:
        f.write(resp.content)

    return output_path


def generate_images_for_scenes(fal_key: str, scenes: list, project_dir: str) -> list:
    """
    여러 씬의 image_prompt를 순차적으로 Flux로 생성한다.
    이미 image_path가 있는 씬은 건너뛴다.

    Args:
        fal_key     : FAL_KEY
        scenes      : state["scenes"] 리스트
        project_dir : 프로젝트 디렉터리 경로

    Returns:
        list : 업데이트된 scenes 리스트 (image_path, image_status 필드 추가)
    """
    for scene in scenes:
        # image_prompt가 없으면 건너뜀
        if not scene.get("image_prompt", "").strip():
            continue

        # 이미 성공적으로 생성된 경우 건너뜀
        if scene.get("image_status") == "done":
            continue

        sno        = scene["scene_no"]
        out_path   = os.path.join(project_dir, f"scene_{sno:02d}_ref.png")
        scene["image_status"] = "generating"

        try:
            generate_reference_image(
                fal_key=fal_key,
                image_prompt=scene["image_prompt"],
                output_path=out_path,
            )
            scene["image_path"]   = out_path
            scene["image_status"] = "done"
            # Kling image-to-video에 사용할 URL도 로컬 경로로 설정
            scene["reference_image_url"] = out_path
            scene.pop("image_error", None)

        except Exception as e:
            scene["image_status"] = "error"
            scene["image_error"]  = str(e)

    return scenes
