# src/image_replicate.py
# 너도나도아는커피 숏폼 팩토리 — Replicate 이미지 생성기
#
# fal.ai 접속 불가 시 대안으로 사용.
# image_fal.py + image_gptimage2.py 를 완전 대체합니다.
# API 키: REPLICATE_API_TOKEN

import os
import replicate

# ── 모델 ID ───────────────────────────────────────────────────────────────────
# flux-schnell: 4 steps, 가장 빠름 — 모든 씬 통일 사용 (속도 우선)
# flux-dev: 28 steps, 고품질이지만 3~5배 느림 → 제거
FLUX_SCHNELL_MODEL = "black-forest-labs/flux-schnell"

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


def _build_inputs(prompt: str, illust_mode: bool = False) -> dict:
    """flux-schnell 입력 파라미터를 반환한다."""
    full_prompt = prompt
    if illust_mode:
        full_prompt = (
            "Technical illustration, cutaway diagram, clean linework, "
            "muted scientific color palette. "
            + prompt
        )
    return {
        "prompt":              full_prompt,
        "width":               DEFAULT_WIDTH,
        "height":              DEFAULT_HEIGHT,
        "output_format":       "jpg",    # 유효값: "webp" / "jpg" / "png"
        "output_quality":      90,
        "num_inference_steps": 4,        # schnell 최적값
        "num_outputs":         1,
    }


# ── 공개 API ──────────────────────────────────────────────────────────────────
def generate_reference_image(
    replicate_token: str,
    image_prompt: str,
    model: str = "",         # 하위 호환용 — 현재 무시, 항상 schnell 사용
    illust_mode: bool = False,
) -> str:
    """
    Replicate FLUX Schnell로 레퍼런스 이미지를 생성하고 공개 URL을 반환한다.

    Args:
        replicate_token : REPLICATE_API_TOKEN
        image_prompt    : 영문 이미지 프롬프트
        model           : 미사용 (하위 호환용)
        illust_mode     : True면 일러스트·설계도 스타일 접두어 추가

    Returns:
        str : Replicate CDN 공개 URL
    """
    os.environ["REPLICATE_API_TOKEN"] = replicate_token

    inputs = _build_inputs(image_prompt, illust_mode=illust_mode)
    tag = "[illust]" if illust_mode else "[ref]"
    print(
        f"[image_replicate] flux-schnell {tag} | {image_prompt[:60]}…",
        flush=True,
    )
    output = replicate.run(FLUX_SCHNELL_MODEL, input=inputs)
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
    flux-schnell + illust_mode=True 사용 (flux-dev 대비 3~5배 빠름).
    """
    return generate_reference_image(
        replicate_token=replicate_token,
        image_prompt=image_prompt,
        illust_mode=True,
    )


def generate_images_for_scenes(
    replicate_token: str,
    scenes: list,
    model: str = "",         # 하위 호환용 — 현재 무시, 항상 schnell 사용
) -> list:
    """
    여러 씬의 이미지를 순차 생성하고 scene["image_path"] / ["image_status"] 를 갱신한다.

    Returns:
        list: 업데이트된 scenes
    """
    for scene in scenes:
        prompt = (scene.get("image_prompt") or scene.get("flow_prompt") or "").strip()
        if not prompt:
            continue
        try:
            url = generate_reference_image(replicate_token, prompt)
            scene["image_path"]          = url
            scene["image_status"]        = "done"
            scene["reference_image_url"] = url
            scene.pop("image_error", None)
        except Exception as e:
            scene["image_status"] = "error"
            scene["image_error"]  = str(e)
    return scenes
