# src/image_replicate.py
# 너도나도아는커피 숏폼 팩토리 — Replicate 이미지 생성기
#
# API 키: REPLICATE_API_TOKEN
#
# v3 수정 (2026-09-23)
#   - [버그] flux 모델에는 width/height 입력이 없다 → 그동안 무시되어 전부 1:1 정사각 이미지가 나왔다.
#            Replicate 공식 입력값 aspect_ratio="9:16" (768×1344) 으로 교체.
#   - [스타일 복구] 과학·구조·추출 씬(일러스트)은 flux-dev + 검증된 펜·잉크 수채화 스케치 접두사.
#            ("신비한 건축사전" 톤. 예전 GPT Image 2 / Imagen 3 에서 검증한 접두사를 그대로 이식)
#   - 사진형 씬(ASSEMBLY 등)은 기존처럼 flux-schnell (빠름)
#
# v4 (2026-09-23)
#   - 일러스트 씬 기본 모델을 prunaai/z-image-turbo 로 교체.
#     펜-잉크 수채화 스케치 샘플을 이 모델로 실제 생성해 화풍을 확인했다.
#     입력: width/height 직접 지정 (720×1280 = 정확히 9:16), steps 8, guidance 0 (터보 모델 권장값).
#   - Z-Image 호출이 실패하면 자동으로 flux-dev 로 다시 생성한다 (앱이 멈추지 않도록).

import os
import replicate

# ── 모델 ID ───────────────────────────────────────────────────────────────────
FLUX_SCHNELL_MODEL = "black-forest-labs/flux-schnell"   # 사진형 — 빠름
FLUX_DEV_MODEL     = "black-forest-labs/flux-dev"       # 일러스트형 — 스케치 품질 우선
FLUX_PRO_MODEL     = FLUX_SCHNELL_MODEL                 # 하위 호환 별칭
ZIMAGE_MODEL       = "prunaai/z-image-turbo"            # 일러스트형 기본 — 스케치 화풍 검증 완료
ZIMAGE_W, ZIMAGE_H = 720, 1280                          # 9:16

ASPECT_RATIO = "9:16"   # 768×1344 세로 (cog-flux ASPECT_RATIOS 기준)

# ── 일러스트 스타일 (펜-잉크 수채화 스케치) ─────────────────────────────────
# 2026-09-23 실제 생성 테스트로 확인한 문구. 두 샘플(두 잔 비교 / 에스프레소 머신 단면) 모두
# 굵은 잉크 윤곽 + 크로스해칭 + 선 밖으로 번지는 수채 물감 + 종이 여백이 나왔다.
# 글자는 이미지에 넣지 않는다 — 수치·라벨은 합성 단계(assembler)에서 정확한 한글로 얹는다.
ILLUSTRATION_PREFIX = (
    "Pen-and-ink watercolor sketch on cold-press watercolor paper. "
    "Bold black fineliner ink contour lines with cross-hatching shadows, "
    "loose transparent watercolor washes in coffee brown, amber, caramel and copper "
    "that bleed past the ink lines, white paper left bare for highlights, "
    "small ink splatters and watercolor blooms, visible paper grain. Subject: "
)
ILLUSTRATION_SUFFIX = (
    " Thin pencil construction lines and ink measurement ticks around the subject. "
    "Scientific naturalist sketchbook plate, cream paper background, "
    "subject at the center of the page, generous empty paper in the lower third. "
    "No text, no letters, no numbers, no people."
)

# 사진 촬영 표현은 스케치 접두사와 충돌한다 (prompts.py 규칙 ⑤와 동일)
_PHOTO_WORDS = (
    "hasselblad", "macro lens", "commercial food photography", "commercial photography",
    "studio product photography", "shallow depth of field", "8k real photo", "photorealistic",
    "f2.8", "f/2.8", "bokeh background", "bokeh", "4k", "8k", "studio lighting", "dramatic side lighting", "cinematic",
)


def _strip_photo_words(prompt: str) -> str:
    """스케치 화풍과 충돌하는 촬영·조명·어두운 배경 표현을 지운다."""
    import re
    out = prompt
    for w in _PHOTO_WORDS:
        out = re.sub(re.escape(w), "", out, flags=re.IGNORECASE)
    out = re.sub(r"\b\d+\s*mm\b", "", out, flags=re.IGNORECASE)                 # 렌즈 초점거리
    out = re.sub(r"\b(on|against)\s+(a\s+)?dark\s+(matte\s+|marble\s+|wood\s+|slate\s+)?"
                 r"(surface|background|table|marble|slate)\b", "", out, flags=re.IGNORECASE)  # 어두운 배경
    out = re.sub(r"\b9:16 vertical\b", "", out, flags=re.IGNORECASE)
    out = re.sub(r"\s*,(\s*,)+", ",", out)                                         # 연속 쉼표
    out = re.sub(r"\s+,", ",", out)
    return " ".join(out.split()).strip(" ,")


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────
def _to_url(output) -> str:
    """FileOutput / 리스트 / 이터레이터 / 문자열 모두 대응해 URL을 반환한다."""
    if hasattr(output, "url"):
        url = str(output.url).strip()
        if url.startswith("http"):
            return url
    if hasattr(output, "__iter__") and not isinstance(output, (str, bytes)):
        items = list(output)
        if not items:
            raise ValueError("Replicate 이미지 출력이 비어 있습니다.")
        first = items[0]
        url = str(first.url).strip() if hasattr(first, "url") else str(first).strip()
        if url.startswith("http"):
            return url
    url = str(output).strip()
    if not url.startswith("http"):
        raise ValueError(f"유효하지 않은 Replicate 출력 URL: {url!r}")
    return url


def _illustration_prompt(prompt: str) -> str:
    return ILLUSTRATION_PREFIX + _strip_photo_words(prompt).rstrip(" .") + "." + ILLUSTRATION_SUFFIX


def _build_zimage_inputs(prompt: str) -> dict:
    return {
        "prompt":              _illustration_prompt(prompt),
        "width":               ZIMAGE_W,
        "height":              ZIMAGE_H,
        "num_inference_steps": 8,
        "guidance_scale":      0.0,
        "output_format":       "jpg",
        "output_quality":      92,
    }


def _build_inputs(prompt: str, illust_mode: bool = False) -> dict:
    if illust_mode:
        return {
            "prompt":              _illustration_prompt(prompt),
            "aspect_ratio":        ASPECT_RATIO,
            "num_inference_steps": 28,
            "guidance":            3.5,
            "output_format":       "jpg",
            "output_quality":      92,
            "num_outputs":         1,
        }
    return {
        "prompt":         prompt,
        "aspect_ratio":   ASPECT_RATIO,
        "output_format":  "jpg",
        "output_quality": 90,
        "num_outputs":    1,
    }


# ── 공개 API ──────────────────────────────────────────────────────────────────
def generate_reference_image(
    replicate_token: str,
    image_prompt: str,
    model: str = "",         # 하위 호환용 — 무시
    illust_mode: bool = False,
) -> str:
    """
    9:16 세로 레퍼런스 이미지를 생성하고 Replicate CDN URL을 반환한다.
    illust_mode=True 이면 flux-dev + 펜·잉크 수채화 스케치 스타일.
    """
    os.environ["REPLICATE_API_TOKEN"] = replicate_token

    if illust_mode:
        # 1순위: Z-Image Turbo (스케치 화풍 검증 모델)
        try:
            print(f"[image_replicate] [illust/z-image-turbo] 720x1280 | {image_prompt[:60]}…", flush=True)
            url = _to_url(replicate.run(ZIMAGE_MODEL, input=_build_zimage_inputs(image_prompt)))
            print(f"[image_replicate] → {url[:80]}", flush=True)
            return url
        except Exception as e:
            print(f"[image_replicate] z-image-turbo 실패 → flux-dev 로 재시도: {e}", flush=True)

    model_id = FLUX_DEV_MODEL if illust_mode else FLUX_SCHNELL_MODEL
    inputs = _build_inputs(image_prompt, illust_mode=illust_mode)
    tag = "[illust/flux-dev]" if illust_mode else "[photo/flux-schnell]"
    print(f"[image_replicate] {tag} 9:16 | {image_prompt[:60]}…", flush=True)
    output = replicate.run(model_id, input=inputs)
    url = _to_url(output)
    print(f"[image_replicate] → {url[:80]}", flush=True)
    return url


def generate_illustration_image(replicate_token: str, image_prompt: str) -> str:
    """MACHINE / EXTRACTION / SCIENCE_DATA 씬 전용 — 신비한 건축사전 스케치."""
    return generate_reference_image(
        replicate_token=replicate_token,
        image_prompt=image_prompt,
        illust_mode=True,
    )


ILLUSTRATION_TYPES = {"MACHINE", "EXTRACTION", "SCIENCE_DATA"}


def generate_images_for_scenes(
    replicate_token: str,
    scenes: list,
    model: str = "",         # 하위 호환용 — 무시
) -> list:
    """여러 씬의 이미지를 순차 생성하고 scene 의 image 필드를 갱신한다."""
    for scene in scenes:
        prompt = (scene.get("image_prompt") or scene.get("flow_prompt") or "").strip()
        if not prompt:
            continue
        try:
            url = generate_reference_image(
                replicate_token, prompt,
                illust_mode=scene.get("scene_type", "") in ILLUSTRATION_TYPES,
            )
            scene["image_path"]          = url
            scene["image_status"]        = "done"
            scene["reference_image_url"] = url
            scene.pop("image_error", None)
        except Exception as e:
            scene["image_status"] = "error"
            scene["image_error"]  = str(e)
    return scenes
