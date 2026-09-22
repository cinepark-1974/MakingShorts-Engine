# src/image_replicate.py
# 너도나도아는커피 숏폼 팩토리 — Replicate 이미지 생성기
#
# fal.ai 접속 불가 시 대안으로 사용.
# image_fal.py + image_gptimage2.py 를 완전 대체합니다.
# API 키: REPLICATE_API_TOKEN

import os
import replicate

# ── 모델 ID ───────────────────────────────────────────────────────────────────
FLUX_DEV_MODEL     = "black-forest-labs/flux-dev"          # 고품질 (ASSEMBLY·일러스트)
FLUX_PRO_MODEL     = "black-forest-labs/flux-1.1-pro"      # 미사용 (width/height 스키마 불일치)
FLUX_SCHNELL_MODEL = "black-forest-labs/flux-schnell"       # 고속·저비용 (레퍼런스 이미지 기본값)

# 9:16 세로 영상 기준 해상도
DEFAULT_WIDTH  = 576
DEFAULT_HEIGHT = 1024


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────
def _to_url(output) -> str:
    """FileOutput / 리스트 / 이터레이터 / 문자열 모두 대응해 URL을 반환한다."""
    # 1) FileOutput 객체: .url 속성 우선 (Replicate Python client >= 1.0)
    if hasattr(output, "url"):
        url = str(output.url).strip()
        if url.startswith("http"):
            return url

    # 2) 리스트나 이터레이터: 첫 번째 항목
    if hasattr(output, "__iter__") and not isinstance(output, (str, bytes)):
        items = list(output)
        if not items:
            raise ValueError("Replicate 이미지 출력이 비어 있습니다.")
        first = items[0]
        # 첫 항목이 FileOutput이면 .url 시도, 아니면 str()
        if hasattr(first, "url"):
            url = str(first.url).strip()
        else:
            url = str(first).strip()
        if url.startswith("http"):
            return url

    # 3) 문자열 / 기타 직접 변환
    url = str(output).strip()
    if not url.startswith("http"):
        raise ValueError(f"유효하지 않은 Replicate 출력 URL: {url!r}")
    return url


def _build_inputs(model: str, prompt: str) -> dict:
    """모델별 입력 파라미터 딕셔너리를 반환한다."""
    base = {
        "prompt":         prompt,
        "width":          DEFAULT_WIDTH,
        "height":         DEFAULT_HEIGHT,
        "output_format":  "jpg",    # webp → jpg: 유효값은 "webp"/"jpg"/"png" 중 하나
        "output_quality": 90,
    }
    if "schnell" in model:
        base["num_inference_steps"] = 4
        base["num_outputs"] = 1
    elif "flux-dev" in model:
        base["num_inference_steps"] = 28
        base["guidance"] = 3.5
        base["num_outputs"] = 1
    # flux-1.1-pro: 사용 중단 (width/height 파라미터 스키마 불일치 + 느림)
    # ASSEMBLY 씬은 flux-dev로 처리
    return base


# ── 공개 API ──────────────────────────────────────────────────────────────────
def generate_reference_image(
    replicate_token: str,
    image_prompt: str,
    model: str = "",
    illust_mode: bool = False,
) -> str:
    """
    Replicate FLUX로 레퍼런스 이미지를 생성하고 공개 URL을 반환한다.

    Args:
        replicate_token : REPLICATE_API_TOKEN
        image_prompt    : 영문 이미지 프롬프트
        model           : Replicate 모델 ID (기본: FLUX_SCHNELL_MODEL)
        illust_mode     : True면 일러스트·설계도 스타일 접두어 추가

    Returns:
        str : Replicate CDN 공개 URL
    """
    os.environ["REPLICATE_API_TOKEN"] = replicate_token

    if not model:
        model = FLUX_SCHNELL_MODEL

    full_prompt = image_prompt
    if illust_mode:
        full_prompt = (
            "Technical illustration, cutaway diagram, clean linework, "
            "muted scientific color palette. "
            + image_prompt
        )

    inputs = _build_inputs(model, full_prompt)
    print(f"[image_replicate] {model.split('/')[-1]} | {image_prompt[:60]}…", flush=True)
    output = replicate.run(model, input=inputs)
    url = _to_url(output)
    print(f"[image_replicate] → {url[:80]}", flush=True)
    return url


def generate_illustration_image(
    replicate_token: str,
    image_prompt: str,
) -> str:
    """
    일러스트·설계도 스타일 이미지 생성.
    MACHINE / EXTRACTION / SCIENCE_DATA 씬 전용.
    (image_gptimage2.py 대체)
    """
    return generate_reference_image(
        replicate_token=replicate_token,
        image_prompt=image_prompt,
        model=FLUX_DEV_MODEL,
        illust_mode=True,
    )


def generate_images_for_scenes(
    replicate_token: str,
    scenes: list,
    model: str = "",
) -> list:
    """
    여러 씬의 이미지를 순차 생성하고 scene["image_path"] / ["image_status"] 를 갱신한다.
    (generate_images_for_scenes API 호환용)

    Returns:
        list: 업데이트된 scenes
    """
    for scene in scenes:
        prompt = (scene.get("image_prompt") or scene.get("flow_prompt") or "").strip()
        if not prompt:
            continue
        try:
            url = generate_reference_image(replicate_token, prompt, model=model)
            scene["image_path"]          = url
            scene["image_status"]        = "done"
            scene["reference_image_url"] = url
            scene.pop("image_error", None)
        except Exception as e:
            scene["image_status"] = "error"
            scene["image_error"]  = str(e)
    return scenes
